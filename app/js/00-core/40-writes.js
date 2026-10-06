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
async function flush(pid,retry){
  if(flushing[pid]){ clearTimeout(timers[pid]); timers[pid]=setTimeout(()=>flush(pid),300); return; }
  const p=pending[pid]; if(!p) return; delete pending[pid];
  flushing[pid]=true;
  try{
    await STORE.update(pid,p);
    if(!pending[pid]) setSaved(MODE==="shared"?"Saved to shared workspace":"Saved in this browser");
  }
  catch(e){
    const c=e&&e.code;
    if(c==="unavailable" && !retry){ pending[pid]=deepMerge(p,pending[pid]||{}); flushing[pid]=false; setTimeout(()=>flush(pid,true),800+Math.random()*700); return; }
    if(c==="invalid_argument"){ setReadOnly(true); toast("You can view this workspace but not edit it"); }
    else if(c==="quota_exceeded"){ toast("The workspace is full. Archive or delete old projects."); }
    else if(c==="revoked"){ setReadOnly(true); }
    else toast("Couldn't save. Check your connection and try again.");
    setSaved("Not saved");
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
function writeLog(pid,text){ if(RO) return; STORE.log(pid,{at:new Date().toISOString(),by:ME.id||null,text}).catch(()=>{}); }

async function createProject(data,logText){
  if(RO) return null;
  const id=newId();
  try{
    await STORE.create(id,data);
    STORE.log(id,{at:new Date().toISOString(),by:ME.id||null,
      text:logText||"Project created", hash:contentHash(data)}).catch(()=>{});
    return id;
  }
  catch(e){ toast(e&&e.code==="quota_exceeded"?"The workspace is full. Archive or delete old projects.":"Couldn't create the project"); return null; }
}
