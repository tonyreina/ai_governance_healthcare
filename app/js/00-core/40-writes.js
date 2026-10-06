/* ============================================================
   Writes
   ============================================================ */
function setSaved(t){ document.getElementById("saved").textContent=t; }
function stamp(extra){ return Object.assign({updatedAt:new Date().toISOString(), updatedBy:ME.id||null}, extra||{}); }
function queuePatch(pid,patch){
  if(RO) return;
  deepMerge(pending[pid]||(pending[pid]={}), patch);
  setSaved("Saving…");
  clearTimeout(timers[pid]); timers[pid]=setTimeout(()=>flush(pid),550);
}
/* Send one project's pending patch.

   The patch is REMOVED from `pending` before the request and put back if the
   request fails, rather than being deleted outright. It used to be deleted up
   front and restored for exactly one error code on exactly the first attempt,
   so a 403, a 404, or a second consecutive outage discarded the user's typing
   while telling them to "try again" -- with nothing left to try again with.

   `attempt` counts retries for backoff. Anything still pending when this
   returns is merged on top, so an edit made DURING the request is not lost
   either. */
const MAX_SAVE_ATTEMPTS = 6;

async function flush(pid,attempt){
  if(flushing[pid]){ clearTimeout(timers[pid]); timers[pid]=setTimeout(()=>flush(pid,attempt),300); return; }
  const p=pending[pid]; if(!p) return; delete pending[pid];
  flushing[pid]=true;
  const restore = ()=>{ pending[pid] = deepMerge(p, pending[pid]||{}); };
  try{
    await STORE.update(pid,p);
    if(!pending[pid]) setSaved(MODE==="shared"?"Saved to shared workspace":"Saved in this browser");
  }
  catch(e){
    const c=e&&e.code;
    const n=(attempt||0)+1;

    // Transient: keep the edit and come back for it.
    if(c==="unavailable" && n < MAX_SAVE_ATTEMPTS){
      restore();
      flushing[pid]=false;
      setSaved("Not saved yet \u2014 retrying");
      setTimeout(()=>flush(pid,n), Math.min(8000, 400*Math.pow(2,n)) + Math.random()*400);
      return;
    }

    // Permanent, and about permission rather than connectivity. Keep the
    // edit anyway: the user can still see and copy what they wrote, which
    // they cannot do if we drop it.
    if(c==="permission_denied" || c==="invalid_argument" || c==="revoked"){
      restore();
      setReadOnly(true);
      toast("Your access to this project changed. Your latest edits could not be saved.");
      setSaved("Not saved \u2014 no longer editable");
    }
    else if(c==="not_found"){
      toast("This project no longer exists, so your last edits could not be saved.");
      setSaved("Not saved");
    }
    else if(c==="quota_exceeded"){
      restore();
      toast("The workspace is full. Archive or delete old projects.");
      setSaved("Not saved \u2014 workspace full");
    }
    else {
      restore();
      toast("Couldn't save. Your changes are still here; check your connection.");
      setSaved("Not saved");
    }
  } finally { flushing[pid]=false; }
}
function patchFromPath(path,val){
  const ks=path.split("."); const out={}; let o=out;
  for(let i=0;i<ks.length-1;i++){ o=o[ks[i]]={}; } o[ks[ks.length-1]]=val; return out;
}
function setLocal(path,val){
  const ks=path.split("."); let o=S;
  for(let i=0;i<ks.length-1;i++){ if(o[ks[i]]==null||typeof o[ks[i]]!=="object") o[ks[i]]={}; o=o[ks[i]]; }
  o[ks[ks.length-1]]=val;
}
function edit(path,val){
  const before = path.startsWith("metrics.") ? clone(S.metrics) : clone(get(path));
  setLocal(path,val);
  let patch;
  if(path.startsWith("metrics.")) patch={metrics:clone(S.metrics), cardUpdatedAt:new Date().toISOString()};
  else { patch=patchFromPath(path,val); if(path.startsWith("card.")) patch.cardUpdatedAt=new Date().toISOString(); }
  if(patch.cardUpdatedAt) S.cardUpdatedAt=patch.cardUpdatedAt;
  const st=stamp(); S.updatedAt=st.updatedAt; S.updatedBy=st.updatedBy;
  queuePatch(CUR, Object.assign(patch,st));
  bufferChange(CUR, path, before);
  // Typing is the ONLY continuous edit: it arrives one character at a time
  // and is not finished until focus leaves. Everything else -- a status
  // button, a dropdown, a date, a programmatic change -- is complete the
  // moment it happens, so it is described straight away.
  //
  // Expressed as "flush unless typing" rather than by listing the discrete
  // controls, because a list would need extending every time a control is
  // added, and the one that got missed would silently stop logging.
  if(!TYPING) flushChanges(CUR, path);
}

/* Changelog coalescing.

   One entry per completed edit, not per keystroke and not per save.

   Two earlier versions were wrong in instructive ways. Logging inside edit()
   wrote one entry per character: forty entries to record one sentence, burying
   the record it exists to document. Logging at save-flush was better but still
   split a sentence in two whenever the typist paused longer than the 550ms
   save debounce -- which is just "stopped to think mid-sentence", a completely
   normal thing to do.

   So the trigger is the edit being FINISHED, which for a text field means
   focus leaving it. Saving still debounces independently: data is written
   while you type, and the changelog describes what you wrote once you are
   done. The two concerns were conflated; they are now separate.

   Discrete controls -- a status button, a dropdown, a date picker -- are
   complete the moment they change, so they flush immediately. */
const changeBuf = {};

/* True only while an `input` event from a text field is being handled.
   Set around the edit() call in the input handler, nowhere else. */
let TYPING = false;
const setTyping = v => { TYPING = !!v; };

function bufferChange(pid, path, before){
  if(RO) return;
  const buf = changeBuf[pid] || (changeBuf[pid] = {});
  // Keep the earliest value only; later keystrokes are the same edit.
  if(!(path in buf)) buf[path] = before;
}

/* Write the entry for one path, or for every buffered path when no path is
   given. Called on blur, when leaving a view, and before the page unloads --
   anywhere an in-progress edit stops being in progress. */
function flushChanges(pid, path){
  const buf = changeBuf[pid];
  if(!buf) return;
  const paths = path ? (path in buf ? [path] : []) : Object.keys(buf);
  for(const key of paths){
    const before = buf[key];
    delete buf[key];
    const now = key.startsWith("metrics.") ? clone(S && S.metrics) : (S ? get(key) : undefined);
    logChange(pid, key, before, now, S);
  }
  if(!Object.keys(buf).length) delete changeBuf[pid];
}

/* Everything in flight, for every project. */
function flushAllChanges(){
  Object.keys(changeBuf).forEach(pid => flushChanges(pid));
}
function saveMetrics(){
  const now=new Date().toISOString(); S.cardUpdatedAt=now; const st=stamp(); Object.assign(S,st);
  queuePatch(CUR, Object.assign({metrics:clone(S.metrics), cardUpdatedAt:now}, st));
}
/* Append one audit entry.

   This used to end in `.catch(()=>{})`. A log that can silently lose entries
   while continuing to look complete is worse than no log: a reviewer cannot
   tell a quiet period from a dropped write, and the whole point of the record
   is that someone will rely on it a year later.

   So a failure is retried, and a failure that survives the retries is said
   out loud rather than swallowed. The entry is kept in `logQueue` across
   retries so a transient outage does not lose it. */
const logQueue = [];
let logDraining = false;

function writeLog(pid,text){
  if(RO) return;
  logQueue.push({pid, entry:{at:new Date().toISOString(), by:ME.id||null, text}, tries:0});
  drainLog();
}

async function drainLog(){
  if(logDraining || !logQueue.length) return;
  logDraining = true;
  try{
    while(logQueue.length){
      const item = logQueue[0];
      try{
        await STORE.log(item.pid, item.entry);
        logQueue.shift();
      }catch(e){
        const code = e && e.code;
        // A permission failure or a project that is gone will not succeed on
        // a retry. Drop the item, but say so: the user just did something the
        // record now does not show.
        if(code === "permission_denied" || code === "not_found"){
          logQueue.shift();
          setSaved("Audit entry not recorded");
          toast("That change was saved, but could not be added to the audit log.");
          continue;
        }
        if(++item.tries >= 5){
          logQueue.shift();
          setSaved("Audit entry not recorded");
          toast("That change was saved, but could not be added to the audit log.");
          continue;
        }
        // Back off and let a later call pick it up.
        logDraining = false;
        setTimeout(drainLog, 400 * item.tries + Math.random() * 300);
        return;
      }
    }
  } finally {
    logDraining = false;
  }
}

/* Entries still in flight, for the unload path. */
const pendingLogCount = () => logQueue.length;

async function createProject(data,logText){
  if(RO) return null;
  const id=newId();
  try{
    await STORE.create(id,data);
    // Goes through the same queue as every other entry, so a transient
    // failure here is retried rather than dropped. See writeLog().
    logQueue.push({pid:id, tries:0, entry:{
      at:new Date().toISOString(), by:ME.id||null,
      text:logText||"Project created", hash:contentHash(data)}});
    drainLog();
    return id;
  }
  catch(e){ toast(e&&e.code==="quota_exceeded"?"The workspace is full. Archive or delete old projects.":"Couldn't create the project"); return null; }
}
