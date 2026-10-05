/* ============================================================
   App state
   ============================================================ */
let STORE=null, MODE="connecting", RO=false, CAN_DELETE=true, USER=null;
const ME={id:null};
let PROJECTS=new Map(), LOADED=false;
let CUR=null;              // open project id
let S=null;                // working copy of open project
let LOG=[], unsubLog=null;
const openItems=new Set();
const pending={}, timers={}, flushing={};
let UI={view:"setup", project:null, filter:"all", q:""};
try{ UI=Object.assign(UI, JSON.parse(localStorage.getItem("chai-ui-v2"))||{}); }catch(e){}
function saveUI(){ try{ localStorage.setItem("chai-ui-v2",JSON.stringify({view:UI.view,project:CUR,filter:UI.filter})); }catch(e){} }

/* names */
const NAMES={};
async function resolveNames(root){
  root=root||document;
  const els=[...root.querySelectorAll("[data-uid]")];
  const ids=[...new Set(els.map(e=>e.dataset.uid).filter(Boolean))];
  els.forEach(e=>{ if(!e.dataset.uid) e.textContent = MODE==="local"?"you (this browser)":"someone"; });
  const need=ids.filter(i=>!(i in NAMES));
  if(need.length && USER && USER.profiles){
    try{ const ps=await USER.profiles(need); need.forEach(i=>{ const p=ps[i]; NAMES[i]= p ? (p.isMe ? "you" : (p.name||"someone")) : "someone"; }); }catch(e){ need.forEach(i=>NAMES[i]="someone"); }
  }
  els.forEach(e=>{ const i=e.dataset.uid; if(i) e.textContent = NAMES[i] || (i===ME.id?"you":"someone"); });
}
const who = id => `<span data-uid="${esc(id||"")}">${id&&NAMES[id]?esc(NAMES[id]):"someone"}</span>`;
