/* ============================================================
   Session controls (#49)

   The application has no session of its own: identity arrives from the front door
   on every request. So the real automatic-logoff control is the front door's session
   lifetime, which docs/deploy.md says where to set. What lives here is defense in
   depth on a shared workstation:

   - an idle lock, off unless the server says how many minutes. It hides the record
     and asks for a reload, and a reload goes back through the front door, so a
     session that has ended is not quietly revived. It saves unsaved edits first, so
     locking never costs anyone work;
   - a sign-out link to wherever the front door ends a session, rendered only if the
     URL is one this page is willing to link to.
   ============================================================ */

/* The same allowlist the server applies to SIGN_OUT_URL (config._SIGN_OUT_OK): an
   https URL, or a path on this origin. Applied again here because the server's
   answer is data, and this is the last place before it becomes a link. */
const SIGN_OUT_OK = /^(https:\/\/[^\s/]+[^\s]*|\/(?!\/)[^\s]*)$/;

function renderSignOut(url){
  if(typeof url!=="string" || !SIGN_OUT_OK.test(url)) return false;
  const header=document.querySelector("header.top");
  if(!header) return false;
  let a=document.getElementById("signOut");
  if(!a){
    a=document.createElement("a");
    a.id="signOut"; a.className="btn ghost";
    const saved=document.getElementById("saved");
    header.insertBefore(a, saved ? saved.nextSibling : null);
  }
  a.setAttribute("href",url);
  a.textContent="Sign out";
  return true;
}

const IDLE_EVENTS=["pointerdown","keydown","scroll","touchstart","mousemove","wheel"];
let IDLE_TIMER=null, IDLE_MS=0, IDLE_LAST=0, IDLE_BUMP=null;

function stopIdleLock(){
  if(IDLE_TIMER){ clearInterval(IDLE_TIMER); IDLE_TIMER=null; }
  if(IDLE_BUMP){ IDLE_EVENTS.forEach(e=>document.removeEventListener(e,IDLE_BUMP,true)); IDLE_BUMP=null; }
}

/* Start (or restart) the idle lock. 0 or less is off. Returns whether it is running. */
function startIdleLock(minutes){
  stopIdleLock();
  if(!(minutes>0)) return false;
  IDLE_MS=minutes*60000; IDLE_LAST=Date.now();
  IDLE_BUMP=()=>{ IDLE_LAST=Date.now(); };
  IDLE_EVENTS.forEach(e=>document.addEventListener(e,IDLE_BUMP,{passive:true,capture:true}));
  // Often enough to lock close to on time, rarely enough to cost nothing.
  IDLE_TIMER=setInterval(()=>{ if(Date.now()-IDLE_LAST>=IDLE_MS) lockNow(); },
                         Math.max(250,Math.min(IDLE_MS/4,15000)));
  return true;
}

function lockNow(){
  if(document.getElementById("lockScreen")) return;
  // Work in progress is written before anything is hidden. A lock that loses an
  // edit teaches people to turn it off.
  try{ flushAllChanges(); if(CUR && pending[CUR]) flush(CUR); }catch(e){}
  stopIdleLock();
  const el=document.createElement("div");
  el.id="lockScreen";
  el.setAttribute("role","dialog");
  el.setAttribute("aria-modal","true");
  el.setAttribute("aria-labelledby","lockTitle");
  el.innerHTML=`<div class="lock-card">
    <h1 id="lockTitle">Locked</h1>
    <p>This workspace locked after a period of inactivity, so the record is not left
    open on an unattended screen. Your changes were saved. Reload to continue; you may
    be asked to sign in again.</p>
    <button class="btn primary" type="button" data-act="${Act.UNLOCK}">Reload</button>
  </div>`;
  document.body.classList.add("locked");
  document.body.appendChild(el);
  const b=el.querySelector("button"); if(b) b.focus();
}

/* Apply what /api/health told us. Fields an older server does not send are absent,
   which means off. */
function startSession(health){
  if(!health) return;
  renderSignOut(health.sign_out_url);
  startIdleLock(Number(health.idle_lock_minutes)||0);
}
