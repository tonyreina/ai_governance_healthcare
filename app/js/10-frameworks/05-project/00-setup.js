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
    ${field("meta.startDate","Review start date","",0,null,"date")}
    ${field("meta.reviewers","Review team","Names and roles, e.g. CMIO, data science, nursing informatics, compliance, patient representative",1)}
    ${field("meta.scope","Scope of this review","Sites, units, and versions in scope",1)}
  </div>
  ${frameworkToggles()}

  <h2>History</h2>
  ${historyHTML()}
  ${accessHTML()}

  <h2>Manage</h2>
  <div style="display:flex;flex-wrap:wrap;gap:8px">
    ${empty&&!RO?`<button class="btn" data-act="example">Fill with an example</button>`:""}
    ${canOwn(S)?`<button class="btn" data-act="archive">${S.archived?"Restore project":"Archive project"}</button>
    <button class="btn danger" data-act="delete">Delete project</button>`
    :`<p style="font-size:13px;color:var(--muted);margin:0">Archiving and deleting are owner-only. ${esc(roleNote())}</p>`}
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


/* Who holds what on this project. Owner-only to change, because
   granting access is itself a privilege. */
function accessHTML(){
  const a=accessOf(S), mine=roleOf(S), owner=canOwn(S);
  const rows=ROLES.flatMap(role=>a[role+"s"].map(id=>({id,role})));

  if(!identityKnown()){
    return `<h2>Access</h2>
    <div class="note"><p><b>Roles are not enforced in this view.</b> This browser
    has no signed-in user, so there is nobody to check a permission against.
    Anyone who can open this page can change anything in it. Run the tool with a
    backend, or publish it as a shared artifact, for access control to mean
    anything.</p></div>`;
  }

  const list = rows.length
    ? `<table class="tbl"><thead><tr><th>Person</th><th>Role</th>${owner?"<th><span class=\"vh\">Change</span></th>":""}</tr></thead><tbody>
       ${rows.map(r=>`<tr>
         <td>${who(r.id)}${r.id===ME.id?" <span class=\"small\">(you)</span>":""}</td>
         <td>${owner?`<select data-role-for="${esc(r.id)}">${ROLES.map(x=>`<option value="${x}"${x===r.role?" selected":""}>${esc(ROLE_LABEL[x])}</option>`).join("")}</select>`:esc(ROLE_LABEL[r.role])}</td>
         ${owner?`<td><button class="icon-btn" data-revoke="${esc(r.id)}" aria-label="Remove access">Remove</button></td>`:""}
       </tr>`).join("")}</tbody></table>`
    : `<p style="font-size:13px;color:var(--muted)">No access list recorded, so this
       project is open to everyone in the workspace. Claim it to restrict who can
       change it.</p>`;

  return `<h2>Access</h2>
  <p style="font-size:13px;color:var(--muted)">Owners can delete, archive and change
  access. Writers can fill in the review. Readers can see it and change nothing.
  You are ${esc(mine?ROLE_LABEL[mine].toLowerCase():"not listed")} on this project.</p>
  ${list}
  ${owner?`<div style="display:flex;flex-wrap:wrap;gap:8px;align-items:flex-end;margin-top:10px">
    <div class="field" style="margin:0"><label for="grantWho">Add someone</label>
      <input type="text" id="grantWho" placeholder="Their user id" data-grant-id></div>
    <div class="field" style="margin:0"><label for="grantRole">Role</label>
      <select id="grantRole" data-grant-role>${ROLES.map(x=>`<option value="${x}">${esc(ROLE_LABEL[x])}</option>`).join("")}</select></div>
    <button class="btn" data-act="grant">Grant access</button>
  </div>`:""}
  ${unclaimed(S)&&identityKnown()?`<button class="btn primary" data-act="claim" style="margin-top:10px">Claim ownership</button>`:""}`;
}

const roleNote = () => {
  const r = roleOf(S);
  return r ? `You have ${ROLE_LABEL[r].toLowerCase()}.` : "You are not listed on this project.";
};
