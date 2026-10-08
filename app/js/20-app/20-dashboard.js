/* ============================================================
   Dashboard
   ============================================================ */
function lcTrack(p){
  const ph=phase(p);
  const pip=s=>{const c=scoreOf(s.items,p.items); const frac=c.total?c.answered/c.total:0;
    return `<span class="pip${frac===1?" full":""}${ph.stage===s.n?" cur":""}" title="Stage ${s.n}: ${c.answered}/${c.total} answered"><i style="height:${Math.round(frac*100)}%"></i>${s.n}</span>`;};
  const gd=k=>{const d=dec(p,k); const cls=!d?"":(/Stop|Retire/.test(d)?"stop":/conditions|changes|Revise|Retrain/.test(d)?"cond":"go"); return `<span class="gd ${cls}" title="${GATES[k].title}: ${esc(d||"open")}"></span>`;};
  const S_=STAGES;
  return `<div class="lc" aria-hidden="true">${pip(S_[0])}${gd("A")}${pip(S_[1])}${pip(S_[2])}${pip(S_[3])}${gd("B")}${pip(S_[4])}${gd("C")}${pip(S_[5])}${gd("D")}</div><div class="lc-label">${esc(ph.label)}</div>`;
}
function dashData(){
  const list=[...PROJECTS.values()].map(p=>normalize(p));
  const rows=list.map(p=>({p, st:statusOf(p), f:flags(p), score:scoreOf(allItems(),p.items).pct, nr:nextReview(p)}));
  return rows;
}
function renderDashboardShell(){
  document.body.classList.add("home");
  document.getElementById("projName").textContent = "Portfolio";
  const m=document.getElementById("main");
  let legacy=null;
  try{ const raw=localStorage.getItem("chai-review-v1"); if(raw && !localStorage.getItem("chai-legacy-imported")){ const j=JSON.parse(raw); if(j&&j.meta&&(j.meta.solution||Object.keys(j.items||{}).length)) legacy=j; } }catch(e){}
  m.innerHTML = `
    <div class="dash-head">
      <div><p class="eyebrow">AI governance</p><h1>AI projects under review</h1>
      <p class="lede">Every AI solution your organization is evaluating or running, checked against the CHAI lifecycle. Projects out of compliance or needing an update rise to the top.</p></div>
      <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:flex-start">
        <button class="btn ro-hide" data-act="samples" title="Add any sample projects not already in this workspace">Add samples</button>
        <button class="btn primary ro-hide" data-act="new">New project</button>
      </div>
    </div>
    ${legacy?`<div class="banner ro-hide" id="legacyBanner"><span>A review of <b>${esc(legacy.meta.solution||"an AI solution")}</b> was saved in this browser before the shared workspace existed.</span><span style="display:flex;gap:8px"><button class="btn" data-act="legacy">Add it to the workspace</button><button class="btn ghost" data-act="legacy-dismiss">Dismiss</button></span></div>`:""}
    <form class="newform ro-hide" id="newform" hidden>
      <label for="newname" class="vh">Name of the AI solution</label>
      <input type="text" id="newname" placeholder="Name of the AI solution, e.g. Sepsis early warning" autocomplete="off">
      <button class="btn primary" type="submit">Create project</button>
      <button class="btn ghost" type="button" data-act="new-cancel">Cancel</button>
    </form>
    <div class="tallies" id="tallies" role="group" aria-label="Filter by status"></div>
    <div class="toolbar">
      <label for="q" class="vh">Search projects</label>
      <input type="search" id="q" placeholder="Search by name, developer, or sponsor" value="${esc(UI.q||"")}">
      <span class="spacer"></span>
      <button class="btn ghost" data-act="dl-csv">Export portfolio (CSV)</button>
      <button class="btn ghost ro-hide" data-act="import">Import project JSON</button>
    </div>
    <div id="plistHost"></div>`;
  applyRO(m);
  updateDashboard();
}
function updateDashboard(){
  const host=document.getElementById("plistHost"); if(!host) return;
  const t=document.getElementById("tallies");
  if(!LOADED){ host.innerHTML=`<p style="color:var(--muted)">Loading projects…</p>`; t.innerHTML=""; return; }
  const rows=dashData();
  const active=rows.filter(r=>!r.p.archived);
  const cnt=k=>active.filter(r=>r.st.key===k).length;
  const archived=rows.length-active.length;
  const T=[["red","Out of compliance",cnt("red")],["amber","Needs update",cnt("amber")],["green","On track",cnt("green")],["retired","Retired or stopped",cnt("retired")],["all","All active",active.length]];
  if(archived) T.push(["archived","Archived",archived]);
  t.innerHTML = T.map(([k,l,n])=>`<button class="tally ${k==="archived"?"retired":k}" data-filter="${k}" aria-pressed="${UI.filter===k}"><span class="n">${n}</span><span class="t">${l}</span></button>`).join("");
  const q=(UI.q||"").toLowerCase().trim();
  let list = UI.filter==="archived" ? rows.filter(r=>r.p.archived) : active.filter(r=>UI.filter==="all"||r.st.key===UI.filter);
  if(q) list=list.filter(r=>[r.p.meta.solution,r.p.meta.developer,r.p.meta.sponsor,r.p.meta.org].join(" ").toLowerCase().includes(q));
  const rank={red:0,amber:1,green:2,retired:3};
  list.sort((a,b)=>(rank[a.st.key]-rank[b.st.key]) || (b.f.length-a.f.length) || (a.p.meta.solution||"").localeCompare(b.p.meta.solution||""));
  if(!rows.length){
    host.innerHTML=`<div class="empty-state"><p>No AI projects yet. Add the first solution your organization is evaluating, or load ${SAMPLES.length} sample projects \u2014 one per CHAI use case \u2014 to see how compliance flags work.</p>
      <div class="ro-hide" style="display:flex;gap:8px;flex-wrap:wrap"><button class="btn primary" data-act="new">New project</button><button class="btn" data-act="samples">Load sample projects</button></div></div>`;
    applyRO(host); return;
  }
  if(!list.length){ host.innerHTML=`<p style="color:var(--muted);margin-top:18px">No projects match. Clear the search or choose another status.</p>`; return; }
  const today=parseDay(TODAY());
  host.innerHTML=`<div class="phead" aria-hidden="true"><span>Project</span><span>Lifecycle</span><span>Readiness</span><span>Next review</span><span>Status</span></div>
  <ul class="plist">${list.map(r=>{const p=r.p; const late=r.nr&&parseDay(r.nr)<today;
    return `<li class="prow ${r.st.key}" data-open="${esc(p.id)}">
      <div><button class="pname" data-open="${esc(p.id)}">${esc(p.meta.solution||"Untitled AI solution")}</button>
        <div class="psub">${esc([p.meta.developer,p.meta.sponsor&&("Sponsor: "+p.meta.sponsor)].filter(Boolean).join(" · ")||"No developer or sponsor recorded")}</div>
        <div class="psub">Updated ${esc(ago(p.updatedAt))} by ${who(p.updatedBy)}${p.archived?" · archived":""}</div></div>
      <div>${lcTrack(p)}</div>
      <div><span class="pct">${r.score}%</span></div>
      <div>${r.nr?`<span class="due${late?" late":""}">${esc(fmtDay(r.nr))}</span>${late?`<div class="small" style="color:var(--red)">overdue</div>`:""}`:`<span class="small">${phase(p).key==="deployed"?"not set":"not live"}</span>`}</div>
      <div><span class="st ${r.st.key}">${esc(r.st.label)}</span>
        ${r.f.length?`<ul class="flags">${r.f.slice(0,3).map(f=>`<li class="${f.sev}">${esc(f.text)}</li>`).join("")}${r.f.length>3?`<li>and ${r.f.length-3} more</li>`:""}</ul>`:""}
        <button class="icon-btn ro-hide parchive" data-archive="${esc(p.id)}"
          aria-label="${p.archived?"Restore":"Archive"} ${esc(p.meta.solution||"this project")}"
          title="${p.archived?"Restore to the active portfolio":"Archive: keeps the record, removes it from the active portfolio"}"
          >${p.archived?"Restore":"Archive"}</button></div>
    </li>`;}).join("")}</ul>`;
  resolveNames(host);
}
function goHome(){
  flushAllChanges();
  if(CUR && pending[CUR]) flush(CUR);
  if(unsubLog){ unsubLog(); unsubLog=null; }
  CUR=null; S=null; LOG=[]; LOG_TOTAL=null; openItems.clear(); saveUI();
  document.getElementById("panel").classList.remove("open");
  renderDashboardShell(); window.scrollTo({top:0});
}
function openProject(id,view){
  flushAllChanges();          // leaving a project ends any edit in progress
  const p=PROJECTS.get(id); if(!p) return;
  if(unsubLog){ unsubLog(); unsubLog=null; }
  CUR=id; S=normalize(clone(p)); LOG=[]; LOG_TOTAL=null; openItems.clear();
  // Read-only is a property of this project and this user, not of the
  // workspace: the same person may own one review and only read another.
  RO = WORKSPACE_RO || !canWrite(S);
  document.body.classList.toggle("ro", RO);
  CAN_DELETE = !WORKSPACE_RO && canOwn(S);
  UI.view=view||"setup"; saveUI();
  warmNames(idsOfProject(S));
  unsubLog=STORE.subscribeLog(id,(l,meta)=>{ LOG=l||[]; LOG_TOTAL=(meta && Number.isFinite(meta.total)) ? meta.total : null; warmNames(LOG.map(e=>e.by)); if(CUR===id && (UI.view==="setup"||UI.view==="report") && !editingInMain()){ const y=window.scrollY; renderMain(false); window.scrollTo(0,y);} });
  renderProject(true);
}
function go(view){ flushAllChanges(); UI.view=view; saveUI(); renderRail(); renderMain(true); document.getElementById("panel").classList.remove("open"); }
