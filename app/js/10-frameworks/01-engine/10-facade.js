/* ============================================================
   A framework, as the screens and the shell use it (#168)

   One object per definition: where its answers live in a record, its
   words as the reader sees them (each through the catalog key its
   definition implies, falling back to the definition's English), and
   the whole-sentence keys ("ui slots") a definition supplies for the
   few screens whose wording is its own.
   ============================================================ */

/* A definition's role in a build. */
const Role = Object.freeze({ PRIMARY: "primary", SUPPLEMENT: "supplement" });

/* What a screen asks a definition to word. A definition's `ui` maps a slot to a
   catalog key; a slot it leaves out gets the engine's neutral key (DEFAULT_SLOT),
   so a framework that brings no catalog keys still reads well. CHAI and OPTICA
   name today's keys, so their wording and its translations are unchanged.
   scripts/check_framework.py checks the slot names and that each key exists. */
const UiSlot = Object.freeze({
  // A section's screen and the rail.
  RAIL_OVERVIEW: "railOverview", RAIL_SHORT: "railShort", PIP_TITLE: "pipTitle",
  SECTION_EYEBROW: "sectionEyebrow", SECTION_ANSWERED: "sectionAnswered",
  DECLINED_COUNT: "declinedCount", CHIP_NOTE: "chipNote", LEGEND: "legend",
  EXTERNAL_COUNT: "externalCount", COVERED_BY: "coveredBy", NOT_COVERED: "notCovered",
  // A checkpoint.
  GATE_EYEBROW: "gateEyebrow", GATE_GAPS: "gateGaps", GATE_ANSWERED_PARTIAL: "gateAnsweredPartial",
  GATE_ALL_MET: "gateAllMet", GATE_GAP_ITEM: "gateGapItem",
  // The portfolio, setup and the delete dialog.
  DASH_LEDE: "dashLede", DASH_EMPTY: "dashEmpty", SETUP_EYEBROW: "setupEyebrow", FW_LEDE: "fwLede",
  DEL_REMOVES: "delRemoves", DEL_DESTROYS: "delDestroys",
  // The report and the exports.
  REPORT_EYEBROW: "reportEyebrow", TITLE_SUFFIX: "titleSuffix", COL_SECTION: "colSection",
  COL_ITEM: "colItem", COL_CATEGORY: "colCategory", CHECKPOINTS: "checkpoints", COL_GATE: "colGate",
  NO_GAPS: "noGaps", READINESS_DETAIL: "readinessDetail", MD_OVERALL: "mdOverall",
  DISCLAIMER: "disclaimer", MD_FOOTER: "mdFooter",
  // The notes on translated framework text.
  FW_NOTE: "fwNote",
  // Flags whose words name the framework's things.
  FLAG_LIVE_OPEN: "flagLiveOpen", FLAG_NO_RATIONALE: "flagNoRationale", FLAG_NO_DEPLOY_DATE: "flagNoDeployDate",
  // A supplement's overview, its switched-off screen and its switch.
  OVERVIEW_TITLE: "overviewTitle", OVERVIEW_LEDE: "overviewLede",
  CARD_ANSWERED: "cardAnswered", CARD_PROGRESS: "cardProgress", CARD_DECLINED: "cardDeclined",
  WHO_OWES: "whoOwes", RELAY: "relay", COL_WHO: "colWho", COL_OUTSTANDING: "colOutstanding",
  NEVER_TITLE: "neverTitle", NEVER_DETAIL: "neverDetail", OFF: "off", TURN_ON: "turnOn",
  TOGGLE_ON_DETAIL: "toggleOnDetail", TOGGLE_OFF_DETAIL: "toggleOffDetail",
});
/* The engine's neutral words, for a slot a definition does not fill. Slots with
   no default (a legend, a chip note, the crossRef chip, a section's short rail
   name) are simply left out when a definition does not name them. */
const DEFAULT_SLOT = Object.freeze({
  [UiSlot.RAIL_OVERVIEW]: "engine.supp.rail", [UiSlot.PIP_TITLE]: "engine.pipTitle",
  [UiSlot.SECTION_EYEBROW]: "engine.section.eyebrow", [UiSlot.SECTION_ANSWERED]: "engine.section.answered",
  [UiSlot.NOT_COVERED]: "engine.supp.notCovered",
  [UiSlot.GATE_EYEBROW]: "engine.gate.eyebrow", [UiSlot.GATE_GAPS]: "engine.gate.gaps",
  [UiSlot.GATE_ANSWERED_PARTIAL]: "engine.gate.answeredPartial", [UiSlot.GATE_ALL_MET]: "engine.gate.allMet",
  [UiSlot.GATE_GAP_ITEM]: "engine.gate.gapItem",
  [UiSlot.DASH_LEDE]: "engine.dash.lede", [UiSlot.DASH_EMPTY]: "engine.dash.empty",
  [UiSlot.SETUP_EYEBROW]: "engine.setup.eyebrow",
  [UiSlot.FW_LEDE]: "engine.fw.lede", [UiSlot.DEL_REMOVES]: "engine.del.removes", [UiSlot.DEL_DESTROYS]: "engine.del.destroys",
  [UiSlot.REPORT_EYEBROW]: "engine.report.eyebrow", [UiSlot.TITLE_SUFFIX]: "engine.export.titleSuffix",
  [UiSlot.COL_SECTION]: "engine.col.section", [UiSlot.COL_ITEM]: "engine.col.item",
  [UiSlot.COL_CATEGORY]: "engine.col.category", [UiSlot.CHECKPOINTS]: "engine.checkpoints",
  [UiSlot.COL_GATE]: "engine.col.gate", [UiSlot.NO_GAPS]: "engine.report.noGaps",
  [UiSlot.READINESS_DETAIL]: "engine.report.readinessDetail", [UiSlot.MD_OVERALL]: "engine.md.overall",
  [UiSlot.DISCLAIMER]: "engine.report.disclaimer", [UiSlot.MD_FOOTER]: "engine.md.footer",
  [UiSlot.FW_NOTE]: "engine.fw.note",
  [UiSlot.FLAG_LIVE_OPEN]: "engine.flag.liveOpen", [UiSlot.FLAG_NO_RATIONALE]: "engine.flag.noRationale",
  [UiSlot.FLAG_NO_DEPLOY_DATE]: "engine.flag.noLiveDate",
  [UiSlot.OVERVIEW_TITLE]: "engine.supp.title", [UiSlot.OVERVIEW_LEDE]: "engine.supp.lede",
  [UiSlot.CARD_ANSWERED]: "engine.supp.answered", [UiSlot.CARD_PROGRESS]: "engine.supp.progress",
  [UiSlot.CARD_DECLINED]: "engine.supp.declined", [UiSlot.WHO_OWES]: "engine.supp.whoOwes",
  [UiSlot.RELAY]: "engine.supp.relay", [UiSlot.COL_WHO]: "engine.supp.colWho",
  [UiSlot.COL_OUTSTANDING]: "engine.supp.colOutstanding", [UiSlot.NEVER_TITLE]: "engine.supp.neverTitle",
  [UiSlot.NEVER_DETAIL]: "engine.supp.neverDetail", [UiSlot.OFF]: "engine.supp.off",
  [UiSlot.TURN_ON]: "engine.supp.turnOn", [UiSlot.TOGGLE_ON_DETAIL]: "engine.fw.onDetail",
  [UiSlot.TOGGLE_OFF_DETAIL]: "engine.fw.offDetail",
});

/* A stored status's CSS class, by its class: the report's and the screens' tags were
   styled by CHAI's stored values, which this keeps, for every framework. */
const STATUS_TONE = Object.freeze({
  [StatusClass.DONE]: "met", [StatusClass.PARTIAL]: "partial", [StatusClass.OPEN]: "notmet",
  [StatusClass.DECLINED]: "na", [StatusClass.EXCLUDED]: "na",
});

/* A record's keys a primary framework's answers and decisions live under. Fixed by
   the server contract: sign-off attribution, the people a record names and the
   retention SQL all read exactly these (D-75). */
const RecordKey = Object.freeze({ ITEMS: "items", GATES: "gates" });
/* Under a supplement's own key: its answers, and whether it is switched on. */
const SupplementKey = Object.freeze({ ANSWERS: "answers", ENABLED: "enabled" });

function frameworkFacade(id) {
  const def = FRAMEWORK_DEFS[id];
  const fw = ENGINES[id];
  const primary = def.role === Role.PRIMARY;
  const ns = def.id;
  const keys = Object.assign({ section: "section", sectionBody: "blurb", category: "category" }, def.keys || {});
  const vp = def.viewPrefix !== undefined ? def.viewPrefix : `${id}-`;
  const ui = def.ui || {};
  const statusByValue = Object.fromEntries(def.statuses.map(s => [s.value, s]));
  const optionByValue = {};
  (def.gates || []).forEach(g => g.options.forEach(o => { optionByValue[o.value] = o; }));
  const whoByValue = Object.fromEntries((def.whos || []).map(w => [w.value, w]));
  const categoryName = Object.fromEntries((def.categories || []).map(c => [c.id, c.name]));
  const reason = def.statuses.find(s => s.reasonField) || null;
  // A primary's answers and decisions are at the record's top level, where the
  // server attributes sign-off and finds people (D-75); a supplement's under its id.
  const answersPath = primary ? RecordKey.ITEMS : `${id}.${SupplementKey.ANSWERS}`;

  const F = {
    id, def, fw, primary, ns, keys, vp, ui, reason, answersPath,
    // A slot is filled when the definition names a key or the engine has a default.
    hasSlot: slot => Object.hasOwn(ui, slot) || Object.hasOwn(DEFAULT_SLOT, slot),
    slot: slot => Object.hasOwn(ui, slot) ? ui[slot] : DEFAULT_SLOT[slot],
    // English nouns for the export-only flag text (screens use catalog keys).
    itemNoun: n => { const no = (def.nouns || {}).item || ["item", "items"]; return n === 1 ? no[0] : no[1]; },
    answers: p => (primary ? (p || S).items : (((p || S)[id] || {})[SupplementKey.ANSWERS])) || {},
    enabled: p => primary || !def.optIn || !!(((p || S)[id] || {})[SupplementKey.ENABLED]),
    sectionTitle: s => tf(`${ns}.${keys.section}.${s.id}.title`, s.title),
    sectionBody: s => s[keys.sectionBody] ? tf(`${ns}.${keys.section}.${s.id}.${keys.sectionBody}`, s[keys.sectionBody]) : "",
    itemText: it => tf(`${ns}.item.${it.id}`, it.text),
    categoryLabel: k => tf(`${ns}.${keys.category}.${k}`, categoryName[k] || k),
    gateTitle: k => tf(`${ns}.gate.${k}.title`, fw.gateById[k].title),
    gateQuestion: k => tf(`${ns}.gate.${k}.q`, fw.gateById[k].question || ""),
    gateHelp: k => tf(`${ns}.gate.${k}.help`, fw.gateById[k].help || ""),
    optionLabel: v => tf(`${ns}.option.${v}`, (optionByValue[v] || {}).label || v),
    shortDecision: v => {
      const o = optionByValue[v];
      return o && o.short ? tf(`${ns}.short.${v}`, o.short) : tf(`${ns}.option.${v}`, (o || {}).label || v);
    },
    statusLabel: v => {
      const s = statusByValue[v];
      if (!s) return v;
      return s.msg ? t(s.msg) : tf(`${ns}.status.${v}`, s.label);
    },
    statusName: v => Object.hasOwn(statusByValue, v) ? statusByValue[v].label : undefined,
    statusTone: v => { const c = fw.classOf(v); return c ? STATUS_TONE[c] : "none"; },
    whoLabel: v => { const w = whoByValue[v]; if (!w) return v; return w.msg ? t(w.msg) : tf(`${ns}.who.${v}`, w.label); },
    whoExternal: v => !!(whoByValue[v] || {}).external,
  };
  F.score = (list, p) => fw.score(list || fw.items, F.answers(p));
  return F;
}
