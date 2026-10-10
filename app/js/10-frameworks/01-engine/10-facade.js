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

/* What a screen asks a definition to word. Each value in a definition's `ui` is a
   catalog key; scripts/check_framework.py checks the slot names and that each key
   exists. */
const UiSlot = Object.freeze({
  RAIL_OVERVIEW: "railOverview",       // a supplement's overview, in the rail
  RAIL_SHORT: "railShort",             // a section's short name: {n}
  SECTION_EYEBROW: "sectionEyebrow",   // above a section's title: {n} {total} {domain}
  SECTION_ANSWERED: "sectionAnswered", // under a section's list: {answered} {total}
  DECLINED_COUNT: "declinedCount",     // after it, when some are declined: {count}
  CHIP_NOTE: "chipNote",               // after that: what the item chips mean
  LEGEND: "legend",                    // above the list, instead of the category legend
  EXTERNAL_COUNT: "externalCount",     // items an outside party answers: {count} {total}
  COVERED_BY: "coveredBy",             // a crossRef chip's tooltip: {ids}
  NOT_COVERED: "notCovered",           // an item with no crossRef
  OVERVIEW_TITLE: "overviewTitle", OVERVIEW_LEDE: "overviewLede",
  CARD_ANSWERED: "cardAnswered", CARD_PROGRESS: "cardProgress", CARD_DECLINED: "cardDeclined",
  WHO_OWES: "whoOwes", RELAY: "relay", COL_WHO: "colWho", COL_OUTSTANDING: "colOutstanding",
  NEVER_TITLE: "neverTitle", NEVER_DETAIL: "neverDetail",
  OFF: "off", TURN_ON: "turnOn",
  TOGGLE_ON_DETAIL: "toggleOnDetail", TOGGLE_OFF_DETAIL: "toggleOffDetail",
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
    hasSlot: slot => Object.hasOwn(ui, slot),
    slot: slot => ui[slot],
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
