/* ============================================================
   Events
   ============================================================ */
document.addEventListener("click",async e=>{
  const row=e.target.closest(".prow");
  const t=e.target.closest("button");
  if(!t && row){ openProject(row.dataset.open); return; }
  if(!t) return;
  if(t.dataset.archive && !WORKSPACE_RO){
    const id=t.dataset.archive, p=PROJECTS.get(id);
    if(!p) return;
    if(!canOwn(p)){ toast("Only an owner can archive this project"); return; }
    const v=!p.archived;
    p.archived=v;
    queuePatch(id, Object.assign({archived:v}, stamp()));
    writeLog(id, v?"Archived":"Restored");
    updateDashboard();
    toast(v?"Project archived":"Project restored");
    return;
  }
  if(t.dataset.revoke && canOwn(S)){
    const id=t.dataset.revoke;
    if(wouldOrphan(S,id,"")){ toast("A project must keep at least one owner"); return; }
    S.access=accessPatch(S,id,""); queuePatch(CUR,Object.assign({access:S.access},stamp()));
    writeLog(CUR,`Removed access for ${id}`); renderMain(false); toast("Access removed"); return;
  }
  if(t.dataset.open){ openProject(t.dataset.open); return; }
  if(t.dataset.home){ goHome(); return; }
  if(t.dataset.go){ go(t.dataset.go); return; }
  if(t.dataset.framework && !RO){
    const f=frameworkById(t.dataset.framework);
    if(f && f.id==="optica") setOpticaEnabled(!f.enabled(S));
    return;
  }
  if(t.dataset.filter){ UI.filter=t.dataset.filter; saveUI(); updateDashboard(); document.querySelector(`[data-filter="${UI.filter}"]`)?.focus(); return; }
  if(t.dataset.set && !RO){
    const id=t.dataset.set, store=t.dataset.store||"items";
    const cur=((get(store)||{})[id]||{}).status||"";
    const val = cur===t.dataset.s ? "" : t.dataset.s;
    edit(`${store}.${id}.status`, val);
    const li=t.closest(".ci");
    li.querySelectorAll(".seg button").forEach(b=>b.setAttribute("aria-pressed", String(b.dataset.s===val)));
    if((val==="partial"||val==="notmet") && !openItems.has(id)){ openItems.add(id); li.classList.add("open"); const m=li.querySelector(".more"); m.textContent="Hide details"; m.setAttribute("aria-expanded","true"); }
    renderRail(); return;
  }
  if(t.dataset.toggle){
    const id=t.dataset.toggle, li=t.closest(".ci"); const open=!openItems.has(id);
    open?openItems.add(id):openItems.delete(id);
    li.classList.toggle("open",open); t.textContent=open?"Hide details":"Evidence & owner"; t.setAttribute("aria-expanded",String(open));
    if(open && !RO) li.querySelector("textarea").focus();
    return;
  }
  if(t.dataset.gate && !RO){
    const k=t.dataset.gate, g=S.gates[k]||{};
    const val = g.decision===t.dataset.d ? "" : t.dataset.d;
    const now=new Date().toISOString();
    const patch={gates:{[k]:{decision:val, signedBy:val?(ME.id||null):null, signedAt:val?now:null, date: val ? (g.date||TODAY()) : (g.date||"")}}};
    deepMerge(S,patch); const st=stamp(); Object.assign(S,st);
    queuePatch(CUR, Object.assign(patch,st));
    writeLog(CUR, val?`${GATES[k].title}: ${val}`:`${GATES[k].title}: decision cleared`);
    renderRail(); renderMain(false); return;
  }
  // Add a CHAI-recommended metric. Name and category only: the value, the
  // interval and the population are measurements the organization has to make,
  // and pre-filling them would be inventing results.
  if(t.dataset.te && !RO){
    const name=t.dataset.te;
    if(!S.metrics.some(m=>(m.name||"").trim().toLowerCase()===name.trim().toLowerCase())){
      S.metrics.push({cat:t.dataset.teCat||METRIC_CATS[0],name,value:"",ci:"",pop:""});
      saveMetrics();
    }
    renderMain(false); renderLabel();
    // Put the cursor where the user now has to type.
    const rows=[...document.querySelectorAll('.mtable input[aria-label="Metric"]')];
    const row=rows.find(i=>i.value===name);
    if(row) row.closest("tr").querySelector('input[aria-label="Value"]').focus();
    return;
  }
  if(t.dataset.delmetric!=null && !RO){ S.metrics.splice(+t.dataset.delmetric,1); saveMetrics(); renderMain(false); renderLabel(); return; }
  const a=t.dataset.act; if(!a) return;
  if(a==="new"){ const f=document.getElementById("newform"); if(f){ f.hidden=false; document.getElementById("newname").focus(); } return; }
  if(a==="new-cancel"){ document.getElementById("newform").hidden=true; return; }
  if(a==="samples"){
    t.disabled=true;
    try{ await loadSamples(); }
    finally{ t.disabled=false; }
    return;
  }
  if(a==="legacy"){
    try{ const j=JSON.parse(localStorage.getItem("chai-review-v1")); const p=normalize(Object.assign(blankProject(j.meta.solution),{meta:j.meta,items:j.items||{},gates:j.gates||{},metrics:j.metrics||[],card:j.card||{}}));
      Object.values(p.items).forEach(x=>{ if(x) delete x._open; });
      const id=await createProject(p,"Imported from a review saved in this browser"); if(id){ localStorage.setItem("chai-legacy-imported","1"); document.getElementById("legacyBanner")?.remove(); toast("Review added to the workspace"); }
    }catch(err){ toast("Couldn't read the earlier review"); }
    return;
  }
  if(a==="legacy-dismiss"){ try{localStorage.setItem("chai-legacy-imported","1");}catch(e){} document.getElementById("legacyBanner")?.remove(); return; }
  if(a==="import"){ document.getElementById("importFile").click(); return; }
  if(a==="dl-csv"){ download(`ai-governance-portfolio-${TODAY()}.csv`, exportCSV()); return; }
  if(!S) return;
  if(a==="claim"){
    if(!ME.id){ toast("No signed-in user to claim ownership"); return; }
    S.access=accessPatch(S,ME.id,"owner"); queuePatch(CUR,Object.assign({access:S.access},stamp()));
    writeLog(CUR,"Claimed ownership"); RO=false; CAN_DELETE=true; renderProject(false); toast("You are now an owner"); return;
  }
  if(a==="grant"){
    if(!canOwn(S)){ toast("Only an owner can grant access"); return; }
    const el=document.querySelector("[data-grant-id]");
    const id=el&&el.value?el.value.trim():"";
    const roleEl=document.querySelector("[data-grant-role]");
    const role=roleEl?roleEl.value:"reader";
    if(!id){ toast("Enter a user id"); return; }
    S.access=accessPatch(S,id,role); queuePatch(CUR,Object.assign({access:S.access},stamp()));
    writeLog(CUR,`Granted ${ROLE_LABEL[role].toLowerCase()} to ${id}`); renderMain(false); toast("Access granted"); return;
  }
  if(a==="addmetric"){ S.metrics.push({cat:METRIC_CATS[0],name:"",value:"",ci:"",pop:""}); saveMetrics(); renderMain(false); const ins=document.querySelectorAll('.mtable input[aria-label="Metric"]'); ins[ins.length-1]?.focus(); }
  else if(a==="example"){ exampleInto(S); const st=stamp(); queuePatch(CUR,Object.assign({meta:clone(S.meta),items:clone(S.items),gates:clone(S.gates),metrics:clone(S.metrics),card:clone(S.card),cardUpdatedAt:S.cardUpdatedAt},st)); writeLog(CUR,"Example data filled in"); renderProject(false); toast("Example filled in"); }
  else if(a==="archive"){ if(!canOwn(S)){ toast("Only an owner can archive this project"); return; } const v=!S.archived; S.archived=v; queuePatch(CUR,Object.assign({archived:v},stamp())); writeLog(CUR,v?"Archived":"Restored"); renderMain(false); toast(v?"Project archived":"Project restored"); }
  else if(a==="delete"){ if(!canOwn(S)){ toast("Only an owner can delete this project"); return; } openDeleteDialog(); }
  else if(a==="newreview"){ const now=new Date().toISOString(); const patch={gates:{D:{date:TODAY(),signedBy:ME.id||null,signedAt:now}}}; deepMerge(S,patch); queuePatch(CUR,Object.assign(patch,stamp())); writeLog(CUR,`Checkpoint D: periodic review recorded (${S.gates.D.decision})`); renderRail(); renderMain(false); toast("Periodic review recorded"); }
  else if(a==="dl-html") download(`${slug(S.meta.solution)}-chai-review.html`, exportHTML());
  else if(a==="dl-md") download(`${slug(S.meta.solution)}-chai-review.md`, exportMD());
  else if(a==="dl-json") download(`${slug(S.meta.solution)}-chai-review.json`, JSON.stringify(projectJSON(S),null,2));
  else if(a==="dl-pdf") exportPDF();
  else if(a==="print") window.print();
});
document.addEventListener("submit",async e=>{
  if(e.target.id!=="newform") return; e.preventDefault();
  const name=document.getElementById("newname").value.trim(); if(!name){ document.getElementById("newname").focus(); return; }
  const id=await createProject(blankProject(name),"Project created");
  if(id){ const wait=()=>PROJECTS.has(id)?openProject(id,"setup"):setTimeout(wait,120); wait(); }
});
document.addEventListener("input",e=>{
  const el=e.target;
  if(el.id==="q"){ UI.q=el.value; updateDashboard(); return; }
  const p=el.dataset && el.dataset.bind; if(!p || RO || !S) return;
  // Mark this as live typing so the changelog waits for the field to be
  // finished rather than describing each keystroke.
  setTyping(true);
  try{ edit(p, el.value); } finally { setTyping(false); }
  if(p.startsWith("meta.")||p.startsWith("card.")||p.startsWith("metrics.")) renderLabel();
  if(p==="meta.solution"||p.startsWith("card.")) renderRail();
});
/* A text edit is finished when focus leaves the field. Capture phase, because
   `blur` does not bubble. This is what turns a sentence into one changelog
   entry regardless of how long the typist paused in the middle of it. */
document.addEventListener("blur", e=>{
  const el=e.target;
  const p=el && el.dataset && el.dataset.bind;
  if(p && CUR) flushChanges(CUR, p);
}, true);

document.addEventListener("change",e=>{
  const el=e.target;
  // The use-case picker is stored on the project, so the chosen framework
  // persists and the suggestions are there next time someone opens stage 4.
  if(el.dataset && el.dataset.teUse!=null && S && !RO){ edit("meta.chaiUseCase", el.value); renderMain(false); return; }
  if(el.dataset && el.dataset.bind && S && !RO && (el.tagName==="SELECT" || el.type==="date")){
    edit(el.dataset.bind, el.value);   // discrete: edit() flushes it already
    renderLabel(); renderRail();
  }
});
/* An edit still in the buffer when the page goes away would never be
   described. pagehide covers closing, navigating and mobile backgrounding;
   visibilitychange catches a tab switch, which is a common way to stop
   mid-sentence. */
addEventListener("pagehide", flushAllChanges);
addEventListener("visibilitychange", ()=>{ if(document.visibilityState==="hidden") flushAllChanges(); });

document.getElementById("brandBtn").onclick=()=>goHome();
document.getElementById("goReport").onclick=()=>{ if(S) go("report"); };
document.getElementById("importFile").onchange=async e=>{
  const f=e.target.files[0]; if(!f) return;
  try{
    const j=JSON.parse(await f.text()); const st=j._state||j;
    if(!st.meta||!st.items) throw new Error("not a review");
    const p=normalize(Object.assign(blankProject(st.meta.solution), clone(st))); delete p.id;
    Object.values(p.items).forEach(x=>{ if(x) delete x._open; }); delete p.view;
    p.updatedAt=new Date().toISOString(); p.updatedBy=ME.id||null;
    const id=await createProject(p,"Imported from a JSON export");
    if(id) toast("Project imported");
  }catch(err){ toast("That file isn't a project export from this tool"); }
  e.target.value="";
};
const panel=document.getElementById("panel");
document.getElementById("openPreview").onclick=()=>{ renderLabel(); panel.classList.add("open"); document.getElementById("closePreview").focus(); };
document.getElementById("closePreview").onclick=()=>panel.classList.remove("open");
document.addEventListener("keydown",e=>{ if(e.key==="Escape") panel.classList.remove("open"); });
window.addEventListener("pagehide",()=>{ Object.keys(pending).forEach(flush); });

let toastT;
function toast(msg){ const t=document.getElementById("toast"); t.textContent=msg; t.classList.add("show"); clearTimeout(toastT); toastT=setTimeout(()=>t.classList.remove("show"),2400); }
