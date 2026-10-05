/* ============================================================
   Project setup
   The project itself: who is reviewing what, the history, and which
   optional frameworks are switched on. This is not CHAI's screen --
   it belongs to the project, which is why it lives outside the
   framework directories and registers first so it heads the rail.

   The compliance banner does read CHAI's flags(). That is deliberate
   and documented: CHAI is the spine the dashboard status comes from,
   and only one framework can own that. See docs/crosswalk.md.
   ============================================================ */
function frameworkToggles(){
  const optional = FRAMEWORKS.filter(f => f.id !== "chai" && f.id !== "project");
  if(!optional.length) return "";
  const rows = optional.map(f=>{
    const on = f.enabled(S);
    return `<li style="display:flex;align-items:center;gap:10px;padding:6px 0">
      <button class="btn${on?" primary":""}" data-framework="${esc(f.id)}" aria-pressed="${on}">${on?"On":"Off"}</button>
      <span><b>${esc(f.label)}</b> \u2014 ${on?"its views appear in the rail below CHAI's":"77 adoption questions, answered by five stakeholders"}</span>
    </li>`;
  }).join("");
  return `<h2 class="ro-hide">Frameworks</h2>
  <p class="ro-hide" style="font-size:13px;color:var(--muted)">CHAI always runs. Switching another framework on adds its questions alongside; answers are kept if you switch it off again, and neither framework changes the other's status.</p>
  <ul class="ro-hide" style="list-style:none;padding:0;margin:0">${rows}</ul>`;
}

function renderSetup(){
  const f=flags(S), st=statusOf(S), nr=nextReview(S);
  const empty = !Object.keys(S.items).length && !Object.keys(S.card).length;
  return `<p class="eyebrow">Before stage 1</p><h1>Project setup</h1>
  <p class="lede">Everyone with access to this workspace sees and edits the same project. Changes save automatically.</p>
  <div class="note ${st.key==="green"?"ok":""}" style="${st.key==="retired"?"border-color:var(--muted);background:var(--sunk)":""}"><b>${esc(st.label)}</b> · ${esc(phase(S).label)}${nr?` · next periodic review ${esc(fmtDay(nr))}`:""}
    ${f.length?`<ul class="gaplist">${f.map(x=>`<li>${esc(x.text)}</li>`).join("")}</ul>`:""}</div>
  <div class="fields">
    ${field("meta.solution","AI solution under review","",0)}
    ${field("meta.org","Health system, hospital, or department","",0)}
    ${field("meta.developer","Developer or vendor","",0)}
    ${field("meta.sourcing","How it was sourced","",0,["Purchased from a vendor","Built internally","Co-developed","Open-source model, locally adapted"])}
    ${field("meta.sponsor","Clinical sponsor","Accountable clinical owner",0)}
    ${field("meta.riskTier","Risk tier","Your organization's own triage",0,["Low","Moderate","High"])}
    ${field("meta.reviewCadence","Periodic review cadence once live","Defaults to 6 months for high risk, otherwise 12",0,["3 months","6 months","12 months","24 months"])}
    ${field("meta.startDate","Review start date","YYYY-MM-DD",0)}
    ${field("meta.reviewers","Review team","Names and roles, e.g. CMIO, data science, nursing informatics, compliance, patient representative",1)}
    ${field("meta.scope","Scope of this review","Sites, units, and versions in scope",1)}
  </div>
  ${frameworkToggles()}

  <h2>History</h2>
  ${historyHTML()}
  <h2 class="ro-hide">Manage</h2>
  <div class="ro-hide" style="display:flex;flex-wrap:wrap;gap:8px">
    ${empty?`<button class="btn" data-act="example">Fill with an example</button>`:""}
    <button class="btn" data-act="archive">${S.archived?"Restore project":"Archive project"}</button>
    ${CAN_DELETE?`<button class="btn danger" data-act="delete">Delete project</button>`:""}
  </div>
  ${pager()}`;
}

registerFramework({
  id: "project",
  label: "Project",
  enabled: () => true,
  blank: () => ({}),
  views: () => [{ id: "setup", kind: "setup", label: "Project setup", num: 0, sep: "after" }],
  render: () => renderSetup(),
});
