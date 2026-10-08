/* ============================================================
   App state
   ============================================================ */
/* Where this session's data lives. A closed set, so it is a frozen object and
   never a bare string: `MODE === "shared"` once sat next to `MODE = "api"` and
   was false forever, which told every server-backed user their work was "Saved
   in this browser" (#55). `Mode.APi` is undefined and a test fails; "apI" is
   just a different string and nothing does. */
const Mode = Object.freeze({
  CONNECTING: "connecting",  // booting; the store is not chosen yet
  LOCAL: "local",            // this browser only (localStorage)
  API: "api",                // the self-hosted server (PostgreSQL)
  ARTIFACT: "artifact",      // a Claude artifact's database
});
/* What the header says about each mode. Keyed by Mode, like SAVED_LABEL, so a
   new mode cannot ship without a label, and no two modes share one: the
   Claude artifact mode was labeled "Shared workspace", identically to the
   self-hosted PostgreSQL server, which hid the difference between data inside
   a hospital's administrative boundary and data outside it (#64). */
const MODE_LABEL = Object.freeze({
  [Mode.LOCAL]:    Object.freeze({text:"This browser only", cls:""}),
  [Mode.API]:      Object.freeze({text:"Shared workspace",  cls:"shared"}),
  [Mode.ARTIFACT]: Object.freeze({text:"Claude artifact",   cls:"artifact"}),
});
/* The export formats the dashboard can produce, as the server names them
   (server/app/accessaudit.py ExportFormat). Reported to it when one is produced. */
const ExportFormat = Object.freeze({
  MD: "md", HTML: "html", PDF: "pdf", JSON: "json", CSV: "csv",
});
/* `data-act` values for buttons. The older actions are still bare strings in
   70-events.js (baselined in scripts/enum_baseline.json); a NEW action goes here,
   so a typo is `Act.LOG_OLDR` -> undefined -> a failing test, not a comparison
   that is quietly false forever. */
const Act = Object.freeze({
  LOG_OLDER: "log-older",   // load a deeper page of the audit history
  UNLOCK: "unlock",         // leave the idle lock: reload, through the front door
});
let STORE=null, MODE=Mode.CONNECTING, RO=false, CAN_DELETE=true, USER=null;
// Set when the whole workspace is view-only (an artifact shared read-only).
// Outranks any per-project role: it is a property of how you got here.
let WORKSPACE_RO=false;
const ME={id:null};
let PROJECTS=new Map(), LOADED=false;
let CUR=null;              // open project id
let S=null;                // working copy of open project
let LOG=[], unsubLog=null;
/* How many entries the project has in all, when the store says. LOG is a WINDOW
   onto the history (the newest page), never the whole of it, and an export or a
   view that renders it must say so: a PDF filed as the record of a two-year
   review used to show the newest 60 entries and nothing about the rest (#40).
   null means the store cannot tell. */
let LOG_TOTAL=null;
const openItems=new Set();
const pending={}, timers={}, flushing={};
let UI={view:"setup", project:null, filter:"all", q:""};
try{ UI=Object.assign(UI, JSON.parse(localStorage.getItem("chai-ui-v2"))||{}); }catch(e){}
function saveUI(){ try{ localStorage.setItem("chai-ui-v2",JSON.stringify({view:UI.view,project:CUR,filter:UI.filter})); }catch(e){} }

/* names */
const NAMES={};
/* Ids a lookup could not name, so a render does not ask again for the same ghost. */
const UNNAMED=new Set();

/* What to show for a person: their name if known, "you" for the viewer, and
   otherwise what each mode can honestly say. The server-backed mode shows the id
   (ugly, but it is what a reviewer can match to a directory, and "someone" tells
   them nothing); the Claude artifact and browser-only modes keep "someone", since
   an id there is not something a person can use or should be shown (#39). */
function displayName(id){
  if(!id) return "someone";
  if(NAMES[id]) return NAMES[id];
  if(id===ME.id) return "you";
  return MODE===Mode.API ? id : "someone";
}

/* Where names come from: the Claude runtime's profiles(), or the server store's. */
function nameSource(){
  if(USER && USER.profiles) return USER;
  if(STORE && typeof STORE.profiles==="function") return STORE;
  return null;
}

/* Ask for the names of any ids not yet asked about, and remember the answers. */
async function primeNames(ids){
  const src = nameSource();
  const need=[...new Set((ids||[]).filter(i=>i && !(i in NAMES) && !UNNAMED.has(i)))];
  if(!need.length || !src) return;
  need.forEach(i=>UNNAMED.add(i));   // claimed up front, so concurrent renders do not repeat it
  try{
    const ps=await src.profiles(need);
    need.forEach(i=>{
      const p=ps[i];
      if(p){ UNNAMED.delete(i); NAMES[i]= p.isMe ? "you" : (p.name||p.email||""); if(!NAMES[i]) delete NAMES[i]; }
    });
  }catch(e){ /* a name is a convenience; the ids still show */ }
}

/* Every person a project document names: its access lists, who signed off and who
   last edited. The same set the server will agree to name (principals.ids_in_doc). */
function idsOfProject(p){
  const found=new Set(); if(!p) return [];
  const a=p.access||{};
  ["owners","writers","readers"].forEach(k=>(Array.isArray(a[k])?a[k]:[]).forEach(i=>found.add(i)));
  Object.values(p.gates||{}).forEach(g=>{ if(g && g.signedBy) found.add(g.signedBy); });
  ["updatedBy","cardUpdatedBy"].forEach(k=>{ if(p[k]) found.add(p[k]); });
  return [...found].filter(Boolean);
}
/* Fetch names for these ids, then refresh whatever is already on screen. */
function warmNames(ids){
  return primeNames(ids).then(()=>{ if(document.getElementById("main")) resolveNames(document); });
}

async function resolveNames(root){
  root=root||document;
  const els=[...root.querySelectorAll("[data-uid]")];
  const ids=[...new Set(els.map(e=>e.dataset.uid).filter(Boolean))];
  els.forEach(e=>{ if(!e.dataset.uid) e.textContent = MODE===Mode.LOCAL?"you (this browser)":"someone"; });
  await primeNames(ids);
  els.forEach(e=>{ const i=e.dataset.uid; if(i) e.textContent = displayName(i); });
}
const who = id => `<span data-uid="${esc(id||"")}">${esc(displayName(id))}</span>`;
