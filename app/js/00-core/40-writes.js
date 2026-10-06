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
    flushChanges(pid);
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
}

/* Changelog coalescing.

   edit() runs on every keystroke, so logging there wrote one entry per
   character -- forty entries to record one sentence, which makes the audit
   trail useless exactly when someone needs to read it.

   Instead the ORIGINAL value of each touched path is kept until the save
   settles, and one entry per path is written at flush. "One entry per field
   per save" is also the honest unit: it is what actually reached the store. */
const changeBuf = {};

function bufferChange(pid, path, before){
  if(RO) return;
  const buf = changeBuf[pid] || (changeBuf[pid] = {});
  // Keep the earliest value only; later keystrokes are the same edit.
  if(!(path in buf)) buf[path] = before;
}

function flushChanges(pid){
  const buf = changeBuf[pid];
  if(!buf) return;
  delete changeBuf[pid];
  for(const path of Object.keys(buf)){
    const now = path.startsWith("metrics.") ? clone(S && S.metrics) : (S ? get(path) : undefined);
    logChange(pid, path, buf[path], now, S);
  }
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
