/* ============================================================
   The framework screens (#168)

   One implementation of each screen a framework shows, drawn from its
   definition: a section's checklist, a checkpoint's decision, a
   supplement's overview, and the primary's report. A framework's own
   code (a plug-in such as CHAI's model card) adds views and report
   sections through the hooks in 90-register.js; nothing here names one.
   ============================================================ */

/* What kind of rail entry a view is; the shell passes it back untouched. */
const ViewKind = Object.freeze({
  SECTION: "section", GATE: "gate", OVERVIEW: "overview", REPORT: "report",
});
/* Where a definition's categories sit: on its items (CHAI's principles) or on its
   sections (OPTICA's domains). */
const CategoriesOn = Object.freeze({ ITEMS: "items", SECTIONS: "sections" });
/* The report's view id, the same in every build (the header's "View report"). */
const REPORT_VIEW = "report";

/* ---------- a section's checklist ---------- */

function itemChipHTML(F, it) {
  if (F.hasSlot(UiSlot.COVERED_BY)) {
    const ids = (it.crossRefs || {}).ids || [];
    return ids.length
      ? `<span class="pchip" title="${esc(t(F.slot(UiSlot.COVERED_BY), {ids: ids.join(", ")}))}">${esc(ids[0])}</span>`
      : `<span class="pchip" title="${esc(t(F.slot(UiSlot.NOT_COVERED)))}">—</span>`;
  }
  return it.category !== undefined
    ? `<span class="pchip" title="${esc(F.categoryLabel(it.category))}">${esc(it.category)}</span>`
    : "";
}

function itemHTML(F, it) {
  const d = F.answers(S)[it.id] || {}; const st = d.status || "";
  const open = openItems.has(it.id);
  const late = d.due && parseDay(d.due) < parseDay(TODAY()) && !SETTLED.has(F.fw.classOf(st));
  const why = F.reason ? d[F.reason.reasonField] : "";
  const notes = (d.evidence || d.owner || d.due || why || refList(d).length) && !open ? `<span class="has-notes">${late ? `<b style="color:var(--red)">${esc(t("ci.overdue", {date: fmtDay(d.due)}))}</b>` : esc(t("ci.notes"))}</span>` : "";
  const store = F.primary ? "" : ` data-store="${esc(F.answersPath)}"`;
  const path = `${F.answersPath}.${it.id}`;
  const p = F.vp;
  const reasonHTML = F.reason && st === F.reason.value
    ? `<div class="wide"><label for="${esc(p)}dr_${esc(it.id)}">${esc(t(F.reason.reasonMsg))}</label><textarea id="${esc(p)}dr_${esc(it.id)}" rows="2" data-bind="${esc(path)}.${esc(F.reason.reasonField)}" ${NO_BROWSER_ASSIST}>${esc(why || "")}</textarea></div>`
    : "";
  return `<li class="ci${esc(open ? " open" : "")}" data-item="${esc(it.id)}"${F.reason ? ` data-reason-for="${esc(F.reason.value)}"` : ""}>
    <div class="ci-row">
      ${itemChipHTML(F, it)}
      <div class="ci-text">${esc(F.itemText(it))}<button class="more" data-toggle="${esc(it.id)}" aria-expanded="${esc(open)}">${esc(t(open ? "ci.hide" : "ci.more"))}</button>${notes}</div>
      <div class="seg" role="group" aria-label="${esc(t("ci.statusGroup"))}">${F.def.statuses.map(s => `<button data-set="${esc(it.id)}"${store} data-s="${esc(s.value)}" aria-pressed="${esc(st === s.value)}">${esc(F.statusLabel(s.value))}</button>`).join("")}</div>
    </div>
    <div class="ci-detail">
      <div><label for="${esc(p)}ev_${esc(it.id)}">${esc(t("ci.evidence"))}</label><textarea id="${esc(p)}ev_${esc(it.id)}" rows="2" data-bind="${esc(path)}.evidence" data-md="1" ${NO_BROWSER_ASSIST}>${esc(d.evidence || "")}</textarea>${mdPreviewHTML(d.evidence)}</div>
      <div><label for="${esc(p)}ow_${esc(it.id)}">${esc(t("ci.owner"))}</label><input type="text" id="${esc(p)}ow_${esc(it.id)}" data-bind="${esc(path)}.owner" value="${esc(d.owner || "")}"></div>
      <div><label for="${esc(p)}du_${esc(it.id)}">${esc(t("ci.due"))}</label><input type="date" id="${esc(p)}du_${esc(it.id)}" data-bind="${esc(path)}.due" value="${esc(d.due || "")}"></div>
      ${refsHTML(path, d)}${reasonHTML}
    </div>
  </li>`;
}

function sectionLegendHTML(F) {
  if (F.hasSlot(UiSlot.LEGEND)) return `<div class="legend"><span>${esc(t(F.slot(UiSlot.LEGEND)))}</span></div>`;
  const cats = F.def.categoriesOn === CategoriesOn.SECTIONS ? [] : (F.def.categories || []);
  return cats.length
    ? `<div class="legend">${cats.map(c => `<span><span class="pchip">${esc(c.id)}</span> ${esc(F.categoryLabel(c.id))}</span>`).join("")}</div>`
    : "";
}

function renderSection(F, sectionId) {
  const s = F.fw.sections.find(x => x.id === sectionId);
  const c = F.score(s.items, S);
  const body = F.sectionBody(s);
  const external = s.items.filter(i => F.whoExternal(i.who)).length;
  const slots = (s.slots || []).map(name => { const h = PLUGINS.get(name); return h && h.slot ? h.slot() : ""; }).join("");
  const answered = esc(t(F.slot(UiSlot.SECTION_ANSWERED), {answered: c.answered, total: c.total}))
    + (c.declined && F.hasSlot(UiSlot.DECLINED_COUNT) ? esc(t(F.slot(UiSlot.DECLINED_COUNT), {count: c.declined})) : "")
    + (F.hasSlot(UiSlot.CHIP_NOTE) ? `. ${esc(t(F.slot(UiSlot.CHIP_NOTE)))}` : "");
  return `<p class="eyebrow">${esc(t(F.slot(UiSlot.SECTION_EYEBROW), {n: s.n, total: F.fw.sections.length, domain: s.category}))}</p><h1>${esc(F.sectionTitle(s))}</h1>
  ${body ? `<p class="lede">${esc(body)}</p>` : ""}
  ${fwNoteHTML(F)}
  ${sectionLegendHTML(F)}${external && F.hasSlot(UiSlot.EXTERNAL_COUNT) ? `<p style="font-size:13px;color:var(--muted)">${esc(t(F.slot(UiSlot.EXTERNAL_COUNT), {count: external, total: s.items.length}))}</p>` : ""}
  <ol class="checklist">${s.items.map(it => itemHTML(F, it)).join("")}</ol>
  <p style="font-size:13px;color:var(--muted);margin-top:10px">${answered}</p>
  ${slots}
  ${pager()}`;
}

/* ---------- a checkpoint ---------- */

function renderGate(F, key) {
  const fw = F.fw, G = fw.gateById[key], g = (S.gates || {})[key] || {};
  const s = fw.sections.find(x => x.id === G.after);
  const answers = F.answers(S);
  const gaps = fw.gapsUpTo(S, G.after);
  const partial = fw.sections.slice(0, fw.sections.indexOf(s) + 1).flatMap(x => x.items)
    .filter(it => fw.classOf((answers[it.id] || {}).status) === StatusClass.PARTIAL).length;
  let note = "";
  if (gaps.length) {
    note = `<div class="note"><b>${esc(t(F.slot(UiSlot.GATE_GAPS), {count: gaps.length, n: s.n}))}${partial ? esc(t("gate.andPartial", {count: partial})) : ""}.</b>${fw.advances(g.decision, key) ? ` ${esc(t("gate.recordConditions"))}` : ""}
    <ul class="gaplist">${gaps.slice(0, 6).map(it => `<li>${esc(t(F.slot(UiSlot.GATE_GAP_ITEM), {n: it.section.n, text: F.itemText(it)}))} <em>(${esc(t((answers[it.id] || {}).status ? "gate.notMet" : "gate.unanswered"))})</em></li>`).join("")}${gaps.length > 6 ? `<li>${esc(t("dash.andMore", {count: gaps.length - 6}))}</li>` : ""}</ul></div>`;
  } else if (partial) note = `<div class="note">${esc(t(F.slot(UiSlot.GATE_ANSWERED_PARTIAL), {count: partial, n: s.n}))}</div>`;
  else note = `<div class="note ok">${esc(t(F.slot(UiSlot.GATE_ALL_MET), {n: s.n}))}</div>`;
  const isReview = fw.review && fw.review.gate === key;
  const nr = isReview ? fw.nextReview(S) : null;
  return `<p class="eyebrow">${esc(t(F.slot(UiSlot.GATE_EYEBROW), {title: F.gateTitle(key), n: s.n}))}</p><h1>${esc(F.gateQuestion(key))}</h1>
  <p class="lede">${esc(F.gateHelp(key))}</p>
  ${fwNoteHTML(F)}
  ${note}
  <div class="gate-panel">
    <p style="margin:0;font-weight:600">${esc(t("gate.decision"))}</p>
    <div class="decisions" role="group" aria-label="${esc(t("gate.decision"))}">${G.options.map(o => `<button data-gate="${esc(key)}" data-d="${esc(o.value)}" aria-pressed="${esc(g.decision === o.value)}">${esc(F.optionLabel(o.value))}</button>`).join("")}</div>
    <div class="fields">
      ${field(`gates.${key}.by`, t("gate.by"), t("gate.byHint"), 0)}
      ${field(`gates.${key}.date`, t("gate.date"), "", 0, null, "date")}
      ${field(`gates.${key}.rationale`, t("gate.rationale"), t("gate.rationaleHint"), 1, null, null, null, true)}
    </div>
    ${g.decision ? `<p class="signed">${g.signedAt ? tHtml("gate.recordedOn", {date: fmtDay(g.signedAt.slice(0, 10))}, {who: who(g.signedBy)}) : tHtml("gate.recorded", {}, {who: who(g.signedBy)})}${nr ? ` ${esc(t("gate.nextDue", {date: fmtDay(nr)}))}` : ""}</p>` : ""}
    ${isReview && g.decision ? `<p class="ro-hide" style="margin:12px 0 0"><button class="btn" data-act="newreview">${esc(t("gate.newReview"))}</button></p>` : ""}
  </div>
  ${pager()}`;
}

/* ---------- a supplement's overview, and its switched-off screen ---------- */

function whoBreakdown(F, p) {
  const answers = F.answers(p), out = {};
  F.fw.items.forEach(it => {
    const who = it.who || "unassigned";
    const b = out[who] || (out[who] = {who, total: 0, answered: 0, outstanding: []});
    b.total++;
    if ((answers[it.id] || {}).status) b.answered++;
    else b.outstanding.push(it);
  });
  return Object.values(out).sort((a, b) => b.total - a.total);
}

function renderOverview(F) {
  const all = F.score(null, S);
  const rows = whoBreakdown(F, S).map(b => `<tr>
      <td>${esc(F.whoLabel(b.who))}</td>
      <td>${b.answered}/${b.total}</td>
      <td>${b.outstanding.length ? esc(b.outstanding.slice(0, 6).map(i => i.num || i.id).join(", ")) + (b.outstanding.length > 6 ? ` ${t("dash.andMore", {count: b.outstanding.length - 6})}` : "") : "—"}</td>
    </tr>`).join("");
  const whos = (F.def.whos || []).length ? `<h2>${esc(t(F.slot(UiSlot.WHO_OWES)))}</h2>
  <p style="font-size:13px;color:var(--muted)">${esc(t(F.slot(UiSlot.RELAY)))}</p>
  <table class="tbl"><thead><tr><th>${esc(t(F.slot(UiSlot.COL_WHO)))}</th><th>${esc(t(F.slot(UiSlot.CARD_ANSWERED)))}</th><th>${esc(t(F.slot(UiSlot.COL_OUTSTANDING)))}</th></tr></thead><tbody>${rows}</tbody></table>` : "";
  return `<p class="eyebrow">${esc(F.def.name)}</p>
  <h1>${esc(t(F.slot(UiSlot.OVERVIEW_TITLE), {name: F.def.name}))}</h1>
  <p class="lede">${esc(t(F.slot(UiSlot.OVERVIEW_LEDE)))}</p>

  <div class="cards">
    <div class="card"><h3>${esc(t(F.slot(UiSlot.CARD_ANSWERED)))}</h3><p class="big">${all.answered}/${all.total}</p></div>
    <div class="card"><h3>${esc(t(F.slot(UiSlot.CARD_PROGRESS)))}</h3><p class="big">${all.pct}%</p></div>
    <div class="card"><h3>${esc(t(F.slot(UiSlot.CARD_DECLINED)))}</h3><p class="big">${all.declined}</p></div>
  </div>

  ${whos}

  <div class="note">
    <p><b>${esc(t(F.slot(UiSlot.NEVER_TITLE), {primary: primaryFramework().label}))}</b> ${esc(t(F.slot(UiSlot.NEVER_DETAIL)))}</p>
  </div>
  ${pager()}`;
}

function renderOff(F) {
  return `<p class="eyebrow">${esc(F.def.name)}</p><h1>${esc(t(F.slot(UiSlot.OVERVIEW_TITLE), {name: F.def.name}))}</h1>
  <p class="lede">${esc(t(F.slot(UiSlot.OFF), {name: F.def.name}))}</p>
  <p>${tHtml(F.slot(UiSlot.TURN_ON), {}, {setup: `<button class="btn" data-go="setup">${esc(t("rail.setup"))}</button>`})}</p>`;
}

/* ---------- the primary's report ---------- */

function historyHTML() {
  if (!LOG.length) return `<p style="font-size:14px;color:var(--muted)">${esc(t("history.none"))}</p>`;
  return `<ul class="history">${LOG.slice(0, 25).map(e => `<li><time>${esc(fmtDay((e.at || "").slice(0, 10)))}</time><span>${bdi(e.text)} <span style="color:var(--muted)">${tHtml("log.by", {}, {who: who(e.by)})}</span></span></li>`).join("")}</ul>`;
}

function reportBody(F, names) {
  const fw = F.fw;
  const nm = id => names ? bdi(displayName(id)) : who(id);
  const all = fw.items; const answers = F.answers(S); const ov = F.score(all, S);
  const unanswered = all.filter(it => !(answers[it.id] || {}).status).length;
  const gaps = all.filter(it => { const st = (answers[it.id] || {}).status; const c = fw.classOf(st); return !st || c === StatusClass.OPEN || c === StatusClass.PARTIAL; });
  // A stored status is whatever an import or an API writer put there, so the class
  // comes from the known set and never from the value (#155).
  const tag = st => { const known = fw.classOf(st) !== null; return `<span class="tag ${esc(known ? F.statusTone(st) : "none")}">${esc(known ? F.statusLabel(st) : t("report.unanswered"))}</span>`; };
  const m = S.meta, Fl = fw.flags(S), st = fw.status(S), nr = fw.nextReview(S);
  const counted = F.def.statuses.filter(s => [StatusClass.DONE, StatusClass.PARTIAL, StatusClass.OPEN].includes(s.class));
  const extras = F.extras.reportSections ? F.extras.reportSections() : "";
  return `<div class="r-head">
      <p class="eyebrow">${esc(t(F.slot(UiSlot.REPORT_EYEBROW), {name: F.def.name}))}</p>
      <h1>${m.solution ? bdi(m.solution) : esc(t("project.untitled"))}</h1>
      <div class="r-meta">
        <div><b>${esc(t("report.status"))}</b>${esc(statusLabel(st))}</div><div><b>${esc(t("report.phase"))}</b>${esc(phaseLabel(fw.phase(S)))}</div>
        <div><b>${esc(t("report.org"))}</b>${bdi(m.org || "–")}</div><div><b>${esc(t("report.developer"))}</b>${bdi(m.developer || "–")}</div>
        <div><b>${esc(t("report.sourcing"))}</b>${esc(m.sourcing ? (SOURCING_KEY[m.sourcing] ? t(SOURCING_KEY[m.sourcing]) : m.sourcing) : "–")}</div><div><b>${esc(t("report.riskTier"))}</b>${esc(m.riskTier ? (RISK_KEY[m.riskTier] ? t(RISK_KEY[m.riskTier]) : m.riskTier) : "–")}</div>
        <div><b>${esc(t("report.sponsor"))}</b>${bdi(m.sponsor || "–")}</div><div><b>${esc(t("report.nextReview"))}</b>${nr ? esc(fmtDay(nr)) : "–"}</div>
        <div><b>${esc(t("report.generated"))}</b>${esc(fmtDay(TODAY()))}</div>
      </div>
      ${m.reviewers ? `<p style="font-size:13.5px;margin:10px 0 0"><b>${esc(t("report.team"))}</b> ${bdi(m.reviewers)}</p>` : ""}
      ${m.scope ? `<p style="font-size:13.5px;margin:4px 0 0"><b>${esc(t("report.scope"))}</b> ${bdi(m.scope)}</p>` : ""}
    </div>
    ${fwNoteHTML(F)}
    <h2>${esc(t("report.flags"))}</h2>
    ${Fl.length ? `<ul class="gaplist" style="font-size:14px">${Fl.map(f => `<li><span class="tag ${esc(f.sev === Severity.RED ? "notmet" : "partial")}">${esc(t(f.sev === Severity.RED ? "status.red" : "status.amber"))}</span> ${esc(flagText(f))}</li>`).join("")}</ul>` : `<p>${esc(t("report.noFlags"))}</p>`}
    <h2>${esc(t("report.readiness"))}</h2>
    <div class="overall"><span class="big">${ov.pct}%</span><p>${esc(t(F.slot(UiSlot.READINESS_DETAIL), {answered: ov.answered, total: ov.total}))}${unanswered ? esc(t("report.stillOpen", {count: unanswered})) : ""}.</p></div>
    <div class="bars">${(F.def.categories || []).map(c => { const sc = F.score(all.filter(it => it.category === c.id), S); return `<div class="bar"><span>${esc(F.categoryLabel(c.id))}</span><span class="track"><span class="fill ${esc(barCls(sc.pct))}" style="width:${esc(sc.pct)}%;display:block"></span></span><span class="pct">${sc.pct}%</span></div>`; }).join("")}</div>
    <h2>${esc(t("report.lifecycle"))}</h2>
    <div class="r-wrap"><table class="rtable"><thead><tr><th>${esc(t(F.slot(UiSlot.COL_SECTION)))}</th><th>${esc(t("report.col.answered"))}</th>${counted.map(s => `<th>${esc(F.statusLabel(s.value))}</th>`).join("")}<th>${esc(t("report.col.score"))}</th></tr></thead><tbody>
    ${fw.sections.map(s => { const cnt = v => s.items.filter(it => (answers[it.id] || {}).status === v).length; const sc = F.score(s.items, S);
      return `<tr><td>${s.n}. ${esc(F.sectionTitle(s))}</td><td>${sc.answered}/${sc.total}</td>${counted.map(c => `<td>${cnt(c.value)}</td>`).join("")}<td><b>${sc.pct}%</b></td></tr>`; }).join("")}
    </tbody></table></div>
    <h2>${esc(t(F.slot(UiSlot.CHECKPOINTS)))}</h2>
    <div class="r-wrap"><table class="rtable"><thead><tr><th>${esc(t(F.slot(UiSlot.COL_GATE)))}</th><th>${esc(t("gate.decision"))}</th><th>${esc(t("gate.by"))}</th><th>${esc(t("report.col.date"))}</th><th>${esc(t("gate.rationale"))}</th></tr></thead><tbody>
    ${fw.gates.map(gate => { const k = gate.id, g = (S.gates || {})[k] || {}; return `<tr><td>${esc(F.gateTitle(k))}<br><span style="color:var(--muted);font-size:12px">${esc(F.gateQuestion(k))}</span></td><td>${g.decision ? `<b>${esc(F.optionLabel(g.decision))}</b>` : `<span style="color:var(--muted)">${esc(t("report.notDecided"))}</span>`}</td><td>${bdi(g.by || "")}${g.signedBy ? `<br><span style="color:var(--muted);font-size:12px">${tHtml("report.recordedBy", {}, {who: nm(g.signedBy)})}</span>` : ""}</td><td>${esc(g.date || "")}</td><td class="md">${mdHTML(g.rationale || "")}</td></tr>`; }).join("")}
    </tbody></table></div>
    <h2>${esc(t("report.gaps"))}</h2>
    ${gaps.length ? `<div class="r-wrap"><table class="rtable"><thead><tr><th>${esc(t(F.slot(UiSlot.COL_SECTION)))}</th><th>${esc(t(F.slot(UiSlot.COL_ITEM)))}</th><th>${esc(t(F.slot(UiSlot.COL_CATEGORY)))}</th><th>${esc(t("report.status"))}</th><th>${esc(t("ci.owner"))}</th><th>${esc(t("ci.due"))}</th></tr></thead><tbody>
      ${gaps.map(it => { const d = answers[it.id] || {}; const late = d.due && parseDay(d.due) < parseDay(TODAY()); return `<tr><td>${it.section.n}</td><td>${esc(F.itemText(it))}${d.evidence ? `<div class="md md-note">${mdHTML(d.evidence)}</div>` : ""}${refsReportHTML(d)}</td><td>${it.category !== undefined ? esc(F.categoryLabel(it.category)) : ""}</td><td>${tag(d.status)}</td><td>${bdi(d.owner || "–")}</td><td${late ? ' style="color:var(--red);font-weight:700"' : ""}>${esc(d.due || "–")}</td></tr>`; }).join("")}
    </tbody></table></div>` : `<p>${esc(t(F.slot(UiSlot.NO_GAPS)))}</p>`}
    ${extras}<h2>${esc(t("report.history"))}</h2>
    ${logWindowNote() ? `<p style="color:var(--muted);font-size:13px"><strong>${esc(logWindowNote())}</strong></p>` : ""}
    ${LOG.length ? `<div class="r-wrap"><table class="rtable"><tbody>${LOG.map(e => `<tr><td style="width:120px">${esc(fmtDay((e.at || "").slice(0, 10)))}</td><td>${bdi(e.text)}</td><td>${nm(e.by)}</td></tr>`).join("")}</tbody></table></div>` : `<p>${esc(t("report.noEvents"))}</p>`}
    <h2>${esc(t("report.appendix"))}</h2>
    ${fw.sections.map(s => `<h3 style="font-size:15px;margin:18px 0 6px">${s.n}. ${esc(F.sectionTitle(s))}</h3><div class="r-wrap"><table class="rtable"><tbody>
      ${s.items.map(it => { const d = answers[it.id] || {}; return `<tr><td style="width:46px">${it.category !== undefined ? `<span class="pchip">${esc(it.category)}</span>` : ""}</td><td>${esc(F.itemText(it))}${d.evidence ? `<div class="md md-note">${mdHTML(d.evidence)}</div>` : ""}${refsReportHTML(d)}</td><td style="width:110px">${tag(d.status)}</td></tr>`; }).join("")}
    </tbody></table></div>`).join("")}
    <p class="disclaimer">${esc(t(F.slot(UiSlot.DISCLAIMER), {name: F.def.name}))}</p>`;
}

function renderReport(F) {
  return `<div class="report">
    <div class="r-actions" id="ractions">
      <button class="btn primary" data-act="dl-html">${esc(t("report.dlHtml"))}</button>
      <button class="btn" data-act="dl-pdf">${esc(t("report.dlPdf"))}</button>
      <button class="btn" data-act="dl-md">${esc(t("report.dlMd"))}</button>
      <button class="btn" data-act="dl-json">${esc(t("report.dlJson"))}</button>
      <button class="btn ghost" data-act="print">${esc(t("report.print"))}</button>
    </div>
    ${reportBody(F)}
    ${pager()}
  </div>`;
}
