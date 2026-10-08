/* ============================================================
   Dashboard
   ============================================================ */
function lcTrack(p){
  const ph=phase(p);
  const pip=s=>{const c=scoreOf(s.items,p.items); const frac=c.total?c.answered/c.total:0;
    return `<span class="pip${frac===1?" full":""}${ph.stage===s.n?" cur":""}" title="${esc(t("dash.pipTitle",{n:s.n,answered:c.answered,total:c.total}))}"><i style="height:${Math.round(frac*100)}%"></i>${s.n}</span>`;};
  const gd=k=>{const d=dec(p,k); const cls=!d?"":(/Stop|Retire/.test(d)?"stop":/conditions|changes|Revise|Retrain/.test(d)?"cond":"go"); return `<span class="gd ${cls}" title="${esc(gateTitle(k))}: ${esc(d?optionText(d):t("dash.gateOpen"))}"></span>`;};
  const S_=STAGES;
  return `<div class="lc" aria-hidden="true">${pip(S_[0])}${gd("A")}${pip(S_[1])}${pip(S_[2])}${pip(S_[3])}${gd("B")}${pip(S_[4])}${gd("C")}${pip(S_[5])}${gd("D")}</div><div class="lc-label">${esc(phaseLabel(ph))}</div>`;
}
function dashData(){
  const list=[...PROJECTS.values()].map(p=>normalize(p));
  const rows=list.map(p=>({p, st:statusOf(p), f:flags(p), score:scoreOf(allItems(),p.items).pct, nr:nextReview(p)}));
  return rows;
}
/* The portfolio's search fields, by element id: one definition, read by the
   template and by the input handler (70-events.js). */
const SearchField = Object.freeze({ QUERY: "q", ALL_TEXT: "qall" });
const SEARCH_HINT = Object.freeze({ NAMES: "dash.searchNames", ALL_TEXT: "dash.searchAll" });
function renderDashboardShell(){
  document.body.classList.add("home");
  document.getElementById("projName").textContent = t("header.portfolio");
  const m=document.getElementById("main");
  let legacy=null;
  try{ const raw=localStorage.getItem("chai-review-v1"); if(raw && !localStorage.getItem("chai-legacy-imported")){ const j=JSON.parse(raw); if(j&&j.meta&&(j.meta.solution||Object.keys(j.items||{}).length)) legacy=j; } }catch(e){}
  m.innerHTML = `
    <div class="dash-head">
      <div><p class="eyebrow">${esc(t("dash.eyebrow"))}</p><h1>${esc(t("dash.title"))}</h1>
      <p class="lede">${esc(t("dash.lede"))}</p></div>
      <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:flex-start">
        <button class="btn ro-hide" data-act="samples" title="${esc(t("dash.addSamplesTitle"))}">${esc(t("dash.addSamples"))}</button>
        <button class="btn primary ro-hide" data-act="new">${esc(t("dash.newProject"))}</button>
      </div>
    </div>
    ${legacy?`<div class="banner ro-hide" id="legacyBanner"><span>${tHtml("dash.legacy",{},{name:`<b>${esc(legacy.meta.solution||t("dash.legacyUnnamed"))}</b>`})}</span><span style="display:flex;gap:8px"><button class="btn" data-act="legacy">${esc(t("dash.legacyAdd"))}</button><button class="btn ghost" data-act="legacy-dismiss">${esc(t("dash.legacyDismiss"))}</button></span></div>`:""}
    <form class="newform ro-hide" id="newform" hidden>
      <label for="newname" class="vh">${esc(t("dash.newName"))}</label>
      <input type="text" id="newname" placeholder="${esc(t("dash.newNamePlaceholder"))}" autocomplete="off">
      <button class="btn primary" type="submit">${esc(t("dash.create"))}</button>
      <button class="btn ghost" type="button" data-act="new-cancel">${esc(t("dash.cancel"))}</button>
    </form>
    <div class="tallies" id="tallies" role="group" aria-label="${esc(t("dash.filterLabel"))}"></div>
    <div class="toolbar">
      <label for="${SearchField.QUERY}" class="vh">${esc(t("dash.searchLabel"))}</label>
      <input type="search" id="${SearchField.QUERY}" placeholder="${esc(t(UI.qAll?SEARCH_HINT.ALL_TEXT:SEARCH_HINT.NAMES))}" value="${esc(UI.q||"")}">
      <label class="qall"><input type="checkbox" id="${SearchField.ALL_TEXT}"${UI.qAll?" checked":""}> ${esc(t("dash.searchAllToggle"))}</label>
      <span class="spacer"></span>
      <button class="btn ghost" data-act="dl-csv">${esc(t("dash.exportCsv"))}</button>
      <button class="btn ghost ro-hide" data-act="import">${esc(t("dash.importJson"))}</button>
    </div>
    <div id="plistHost"></div>`;
  applyRO(m);
  updateDashboard();
}
function updateDashboard(){
  const host=document.getElementById("plistHost"); if(!host) return;
  const tl=document.getElementById("tallies");
  if(!LOADED){ host.innerHTML=`<p style="color:var(--muted)">${esc(t("dash.loading"))}</p>`; tl.innerHTML=""; return; }
  const rows=dashData();
  const active=rows.filter(r=>!r.p.archived);
  const cnt=k=>active.filter(r=>r.st.key===k).length;
  const archived=rows.length-active.length;
  const T=[["red",t("dash.tally.red"),cnt("red")],["amber",t("dash.tally.amber"),cnt("amber")],["green",t("dash.tally.green"),cnt("green")],["retired",t("dash.tally.retired"),cnt("retired")],["all",t("dash.tally.all"),active.length]];
  if(archived) T.push(["archived",t("dash.tally.archived"),archived]);
  tl.innerHTML = T.map(([k,l,n])=>`<button class="tally ${k==="archived"?"retired":k}" data-filter="${k}" aria-pressed="${UI.filter===k}"><span class="n">${n}</span><span class="t">${esc(l)}</span></button>`).join("");
  const q=(UI.q||"").toLowerCase().trim();
  const everything = !!(UI.qAll && q);
  let list = UI.filter==="archived" ? rows.filter(r=>r.p.archived) : active.filter(r=>UI.filter==="all"||r.st.key===UI.filter);
  if(everything){
    // Every project the viewer can open, archived included, whatever the status filter.
    list = rows.map(r=>Object.assign(r,{hits:textHits(r.p,q)})).filter(r=>r.hits.length);
  }
  else if(q) list=list.filter(r=>[r.p.meta.solution,r.p.meta.developer,r.p.meta.sponsor,r.p.meta.org].join(" ").toLowerCase().includes(q));
  const note = everything
    ? `<p class="small search-note" id="searchNote">${esc(t("dash.searchNote"))}${MODE===Mode.API?` ${esc(t("dash.searchNoteServer"))}`:""}</p>`
    : "";
  const rank={red:0,amber:1,green:2,retired:3};
  list.sort((a,b)=>(rank[a.st.key]-rank[b.st.key]) || (b.f.length-a.f.length) || (a.p.meta.solution||"").localeCompare(b.p.meta.solution||""));
  if(!rows.length){
    host.innerHTML=`<div class="empty-state"><p>${esc(t("dash.empty",{count:SAMPLES.length}))}</p>
      <div class="ro-hide" style="display:flex;gap:8px;flex-wrap:wrap"><button class="btn primary" data-act="new">${esc(t("dash.newProject"))}</button><button class="btn" data-act="samples">${esc(t("dash.loadSamples"))}</button></div></div>`;
    applyRO(host); return;
  }
  if(!list.length){ host.innerHTML= note + (everything
      ? `<p style="color:var(--muted);margin-top:18px">${esc(t("dash.noTextMatch"))}</p>`
      : `<p style="color:var(--muted);margin-top:18px">${esc(t("dash.noMatch"))}</p>`); return; }
  const today=parseDay(TODAY());
  host.innerHTML=`${note}<div class="phead" aria-hidden="true"><span>${esc(t("dash.col.project"))}</span><span>${esc(t("dash.col.lifecycle"))}</span><span>${esc(t("dash.col.readiness"))}</span><span>${esc(t("dash.col.nextReview"))}</span><span>${esc(t("dash.col.status"))}</span></div>
  <ul class="plist">${list.map(r=>{const p=r.p; const late=r.nr&&parseDay(r.nr)<today; const name=p.meta.solution||t("dash.thisProject");
    return `<li class="prow ${r.st.key}" data-open="${esc(p.id)}">
      <div><button class="pname" data-open="${esc(p.id)}">${esc(p.meta.solution||t("project.untitled"))}</button>
        <div class="psub">${esc([p.meta.developer,p.meta.sponsor&&t("dash.sponsor",{name:p.meta.sponsor})].filter(Boolean).join(" · ")||t("dash.noDeveloper"))}</div>
        <div class="psub">${tHtml("dash.updated",{when:ago(p.updatedAt)},{who:who(p.updatedBy)})}${p.archived?` · ${esc(t("dash.archivedTag"))}`:""}</div>
        ${r.hits&&everything?`<div class="psub hits">${esc(t("dash.foundIn",{places:r.hits.slice(0,4).join("; ")}))}${r.hits.length>4?` ${esc(t("dash.andMore",{count:r.hits.length-4}))}`:""}</div>`:""}</div>
      <div>${lcTrack(p)}</div>
      <div><span class="pct">${r.score}%</span></div>
      <div>${r.nr?`<span class="due${late?" late":""}">${esc(fmtDay(r.nr))}</span>${late?`<div class="small" style="color:var(--red)">${esc(t("dash.overdue"))}</div>`:""}`:`<span class="small">${esc(t(phase(p).key==="deployed"?"dash.notSet":"dash.notLive"))}</span>`}</div>
      <div><span class="st ${r.st.key}">${esc(statusLabel(r.st))}</span>
        ${r.f.length?`<ul class="flags">${r.f.slice(0,3).map(f=>`<li class="${f.sev}">${esc(flagText(f))}</li>`).join("")}${r.f.length>3?`<li>${esc(t("dash.andMore",{count:r.f.length-3}))}</li>`:""}</ul>`:""}
        <button class="icon-btn ro-hide parchive" data-archive="${esc(p.id)}"
          aria-label="${esc(t(p.archived?"dash.restoreLabel":"dash.archiveLabel",{name}))}"
          title="${esc(t(p.archived?"dash.restoreTitle":"dash.archiveTitle"))}"
          >${esc(t(p.archived?"dash.restore":"dash.archive"))}</button></div>
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
