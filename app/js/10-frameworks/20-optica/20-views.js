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
const OPTICA_PRODUCER_KEY = Object.freeze({
  adopter: "optica.who.adopter",
  developer: "optica.who.developer",
  either: "optica.who.either",
});

function opticaItemHTML(it) {
  const d = opticaAnswer(S, it.key);
  const st = d.status || "";
  const open = openItems.has(it.key);
  const late = d.due && parseDay(d.due) < parseDay(TODAY()) && st !== "met" && st !== "na";
  const notes = (d.evidence || d.owner || d.due || d.declineReason) && !open
    ? `<span class="has-notes">${late ? `<b style="color:var(--red)">${esc(t("ci.overdue", {date: fmtDay(d.due)}))}</b>` : esc(t("ci.notes"))}</span>` : "";
  const chai = it.chai && it.chai.length
    ? `<span class="pchip" title="${esc(t("optica.coveredBy", {ids: it.chai.join(", ")}))}">${esc(it.chai[0])}</span>`
    : `<span class="pchip" title="${esc(t("optica.notCovered"))}">—</span>`;

  return `<li class="ci${open ? " open" : ""}" data-item="${esc(it.key)}">
    <div class="ci-row">
      ${chai}
      <div class="ci-text">${esc(opticaItemText(it))}<button class="more" data-toggle="${esc(it.key)}" aria-expanded="${open}">${esc(t(open ? "ci.hide" : "ci.more"))}</button>${notes}</div>
      <div class="seg" role="group" aria-label="${esc(t("ci.statusGroup"))}">${Object.keys(OPTICA_STATUS).map(k =>
        `<button data-set="${esc(it.key)}" data-store="optica.answers" data-s="${k}" aria-pressed="${st === k}">${esc(t(OPTICA_STATUS_KEY[k]))}</button>`).join("")}</div>
    </div>
    <div class="ci-detail">
      <div><label for="oev_${esc(it.key)}">${esc(t("ci.evidence"))}</label><textarea id="oev_${esc(it.key)}" rows="2" data-bind="optica.answers.${esc(it.key)}.evidence" ${NO_BROWSER_ASSIST}>${esc(d.evidence || "")}</textarea></div>
      <div><label for="oow_${esc(it.key)}">${esc(t("ci.owner"))}</label><input type="text" id="oow_${esc(it.key)}" data-bind="optica.answers.${esc(it.key)}.owner" value="${esc(d.owner || "")}"></div>
      <div><label for="odu_${esc(it.key)}">${esc(t("ci.due"))}</label><input type="date" id="odu_${esc(it.key)}" data-bind="optica.answers.${esc(it.key)}.due" value="${esc(d.due || "")}"></div>
      ${st === "declined" ? `<div class="wide"><label for="odr_${esc(it.key)}">${esc(t("optica.whyDeclined"))}</label><textarea id="odr_${esc(it.key)}" rows="2" data-bind="optica.answers.${esc(it.key)}.declineReason" ${NO_BROWSER_ASSIST}>${esc(d.declineReason || "")}</textarea></div>` : ""}
    </div>
  </li>`;
}

function renderOpticaChapter(n) {
  const c = OPTICA.chapters.find(x => x.n === n);
  const s = opticaScore(c.items, S);
  const vendor = c.items.filter(i => i.who === "developer").length;
  return `<p class="eyebrow">${esc(t("optica.chapterEyebrow", {n: c.n, domain: c.domain}))}</p>
  <h1>${esc(opticaChapterTitle(c))}</h1>
  ${c.purpose ? `<p class="lede">${esc(tf(`optica.chapter.${c.n}.purpose`, c.purpose))}</p>` : ""}
  ${fwNoteHTML()}
  <div class="legend">
    <span>${esc(t("optica.paraphrase"))}</span>
  </div>
  ${vendor ? `<p style="font-size:13px;color:var(--muted)">${esc(t("optica.vendorOnly", {count: vendor, total: c.items.length}))}</p>` : ""}
  <ol class="checklist">${c.items.map(opticaItemHTML).join("")}</ol>
  <p style="font-size:13px;color:var(--muted);margin-top:10px">${esc(t("optica.answered", {answered: s.answered, total: s.total}))}${s.declined ? esc(t("optica.declinedCount", {count: s.declined})) : ""}. ${esc(t("optica.chipNote"))}</p>
  ${pager()}`;
}

function renderOpticaOverview() {
  const all = opticaScore(OPTICA_ITEMS, S);
  const byWho = opticaByProducer(S);
  const rows = byWho.map(b => `<tr>
      <td>${esc(OPTICA_PRODUCER_KEY[b.who] ? t(OPTICA_PRODUCER_KEY[b.who]) : b.who)}</td>
      <td>${b.answered}/${b.total}</td>
      <td>${b.outstanding.length ? esc(b.outstanding.slice(0, 6).map(i => i.num).join(", ")) + (b.outstanding.length > 6 ? ` ${t("dash.andMore", {count: b.outstanding.length - 6})}` : "") : "—"}</td>
    </tr>`).join("");

  return `<p class="eyebrow">OPTICA</p>
  <h1>${esc(t("optica.title"))}</h1>
  <p class="lede">${esc(t("optica.lede"))}</p>

  <div class="cards">
    <div class="card"><h3>${esc(t("optica.card.answered"))}</h3><p class="big">${all.answered}/${all.total}</p></div>
    <div class="card"><h3>${esc(t("optica.card.progress"))}</h3><p class="big">${all.pct}%</p></div>
    <div class="card"><h3>${esc(t("optica.card.declined"))}</h3><p class="big">${all.declined}</p></div>
  </div>

  <h2>${esc(t("optica.whoOwes"))}</h2>
  <p style="font-size:13px;color:var(--muted)">${esc(t("optica.relay"))}</p>
  <table class="tbl"><thead><tr><th>${esc(t("optica.col.stakeholder"))}</th><th>${esc(t("optica.card.answered"))}</th><th>${esc(t("optica.col.outstanding"))}</th></tr></thead><tbody>${rows}</tbody></table>

  <div class="note">
    <p><b>${esc(t("optica.neverTitle"))}</b> ${esc(t("optica.neverDetail"))}</p>
  </div>
  ${pager()}`;
}

function renderOpticaOff() {
  return `<p class="eyebrow">OPTICA</p><h1>${esc(t("optica.title"))}</h1>
  <p class="lede">${esc(t("optica.off"))}</p>
  <p>${tHtml("optica.turnOn", {}, {setup: `<button class="btn" data-go="setup">${esc(t("rail.setup"))}</button>`})}</p>`;
}
