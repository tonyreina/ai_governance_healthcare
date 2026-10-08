/* ============================================================
   OPTICA: views
   One screen per chapter, plus an overview that answers the
   question OPTICA's stakeholder relay actually turns on: who owes
   the next answers.

   Markup reuses the CHAI checklist classes (.ci, .seg, .checklist)
   so no new CSS is needed and the two checklists look like one
   tool. The state path differs -- optica.answers.<key> rather than
   items.<id> -- which is what keeps the data cleanly separable.
   ============================================================ */
const OPTICA_PRODUCER_LABEL = {
  adopter: "Your organization",
  developer: "The solution's developer",
  either: "Either party",
};

function opticaItemHTML(it) {
  const d = opticaAnswer(S, it.key);
  const st = d.status || "";
  const open = openItems.has(it.key);
  const late = d.due && parseDay(d.due) < parseDay(TODAY()) && st !== "met" && st !== "na";
  const notes = (d.evidence || d.owner || d.due || d.declineReason) && !open
    ? `<span class="has-notes">${late ? `<b style="color:var(--red)">overdue ${esc(fmtDay(d.due))}</b>` : "notes added"}</span>` : "";
  const chai = it.chai && it.chai.length
    ? `<span class="pchip" title="Partially covered by CHAI ${esc(it.chai.join(", "))}">${esc(it.chai[0])}</span>`
    : `<span class="pchip" title="No CHAI criterion covers this">—</span>`;

  return `<li class="ci${open ? " open" : ""}" data-item="${esc(it.key)}">
    <div class="ci-row">
      ${chai}
      <div class="ci-text">${esc(it.text)}<button class="more" data-toggle="${esc(it.key)}" aria-expanded="${open}">${open ? "Hide details" : "Evidence & owner"}</button>${notes}</div>
      <div class="seg" role="group" aria-label="Status">${Object.entries(OPTICA_STATUS).map(([k, l]) =>
        `<button data-set="${esc(it.key)}" data-store="optica.answers" data-s="${k}" aria-pressed="${st === k}">${l}</button>`).join("")}</div>
    </div>
    <div class="ci-detail">
      <div><label for="oev_${esc(it.key)}">Evidence or notes</label><textarea id="oev_${esc(it.key)}" rows="2" data-bind="optica.answers.${esc(it.key)}.evidence" ${NO_BROWSER_ASSIST}>${esc(d.evidence || "")}</textarea></div>
      <div><label for="oow_${esc(it.key)}">Owner</label><input type="text" id="oow_${esc(it.key)}" data-bind="optica.answers.${esc(it.key)}.owner" value="${esc(d.owner || "")}"></div>
      <div><label for="odu_${esc(it.key)}">Due</label><input type="date" id="odu_${esc(it.key)}" data-bind="optica.answers.${esc(it.key)}.due" value="${esc(d.due || "")}"></div>
      ${st === "declined" ? `<div class="wide"><label for="odr_${esc(it.key)}">Why this was declined</label><textarea id="odr_${esc(it.key)}" rows="2" data-bind="optica.answers.${esc(it.key)}.declineReason" ${NO_BROWSER_ASSIST}>${esc(d.declineReason || "")}</textarea></div>` : ""}
    </div>
  </li>`;
}

function renderOpticaChapter(n) {
  const c = OPTICA.chapters.find(x => x.n === n);
  const s = opticaScore(c.items, S);
  const vendor = c.items.filter(i => i.who === "developer").length;
  return `<p class="eyebrow">OPTICA chapter ${c.n} of 13 · domain ${c.domain}</p>
  <h1>${esc(c.title)}</h1>
  ${c.purpose ? `<p class="lede">${esc(c.purpose)}</p>` : ""}
  <div class="legend">
    <span>Questions are this project's paraphrase of OPTICA, not its published wording.</span>
  </div>
  ${vendor ? `<p style="font-size:13px;color:var(--muted)">${vendor} of ${c.items.length} item${vendor === 1 ? "" : "s"} here can only be answered by the solution's developer.</p>` : ""}
  <ol class="checklist">${c.items.map(opticaItemHTML).join("")}</ol>
  <p style="font-size:13px;color:var(--muted);margin-top:10px">${s.answered} of ${s.total} answered${s.declined ? `, ${s.declined} declined` : ""}. The chip on each row names the CHAI criterion that partially covers it, or a dash where none does.</p>
  ${pager()}`;
}

function renderOpticaOverview() {
  const all = opticaScore(OPTICA_ITEMS, S);
  const byWho = opticaByProducer(S);
  const rows = byWho.map(b => `<tr>
      <td>${esc(OPTICA_PRODUCER_LABEL[b.who] || b.who)}</td>
      <td>${b.answered}/${b.total}</td>
      <td>${b.outstanding.length ? esc(b.outstanding.slice(0, 6).map(i => i.num).join(", ")) + (b.outstanding.length > 6 ? ` +${b.outstanding.length - 6} more` : "") : "—"}</td>
    </tr>`).join("");

  return `<p class="eyebrow">OPTICA</p>
  <h1>Adoption review</h1>
  <p class="lede">77 items in 13 chapters, answered by five stakeholders in sequence. OPTICA asks whether <em>this</em> organization should adopt <em>this</em> solution; it runs alongside the CHAI lifecycle and never changes it.</p>

  <div class="cards">
    <div class="card"><h3>Answered</h3><p class="big">${all.answered}/${all.total}</p></div>
    <div class="card"><h3>Progress</h3><p class="big">${all.pct}%</p></div>
    <div class="card"><h3>Declined</h3><p class="big">${all.declined}</p></div>
  </div>

  <h2>Who owes the next answers</h2>
  <p style="font-size:13px;color:var(--muted)">OPTICA is a relay: each stage is completed by one stakeholder before the next begins. Outstanding items are listed by the party that can answer them.</p>
  <table class="tbl"><thead><tr><th>Stakeholder</th><th>Answered</th><th>Outstanding</th></tr></thead><tbody>${rows}</tbody></table>

  <div class="note">
    <p><b>OPTICA answers never change CHAI status.</b> The two checklists ask different parties for different evidence at different moments, and no OPTICA item fully discharges a CHAI criterion. Evidence can be cited in both; a judgment in one is not a judgment in the other.</p>
  </div>
  ${pager()}`;
}

function renderOpticaOff() {
  return `<p class="eyebrow">OPTICA</p><h1>Adoption review</h1>
  <p class="lede">OPTICA is not switched on for this project.</p>
  <p>Turn it on in <button class="btn" data-go="setup">Project setup</button> to add its 77 adoption questions alongside the CHAI lifecycle.</p>`;
}
