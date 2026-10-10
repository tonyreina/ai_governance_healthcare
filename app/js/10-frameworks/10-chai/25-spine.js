/* ============================================================
   CHAI: the spine
   CHAI's answers to what the shell asks of the primary framework
   (00-registry.js). The shell calls these and never the CHAI
   functions behind them, so another framework can stand in its
   place (#168).
   ============================================================ */
const CHAI_SPINE = {
  items: () => allItems().map(it => ({ ...it, category: it.p, section: it.stage })),
  itemLabel: it => itemText(it),
  sections: () => STAGES,
  sectionLabel: s => stageTitle(s),
  categories: () => Object.keys(PRINCIPLES).map(k => ({ id: k, name: PRINCIPLES[k].name })),
  categoryLabel: k => principleName(k),
  gates: () => GATE_IDS.map(k => ({ id: k, after: GATES[k].after, title: GATES[k].title })),
  gateLabel: k => gateTitle(k),
  gateQuestion: k => gateQuestion(k),
  optionLabel: o => optionText(o),
  gateRecord: (p, k) => (p.gates || {})[k] || {},
  decisionClass: d => optionClass(d),
  answers: p => p.items || {},
  phase: p => phase(p),
  flags: p => flags(p),
  status: p => statusOf(p),
  nextReview: p => nextReview(p),
  score: (p, list) => scoreOf(list || allItems(), p.items),
  reportBody: names => reportBody(names),
  markdownExtras: ctx => chaiCardMarkdown(ctx),
  jsonExtras: p => ({ model_card: Object.fromEntries(CARD_FIELDS.map(k => [k, cardValOf(p, k)])) }),
  // Worked examples: a portfolio of sample projects, and one filled-in project.
  samples: {
    count: () => SAMPLES.length,
    loadAll: () => loadSamples(),
    fill: p => {
      exampleInto(p);
      return {meta: clone(p.meta), items: clone(p.items), gates: clone(p.gates), metrics: clone(p.metrics),
        card: clone(p.card), cardUpdatedAt: p.cardUpdatedAt};
    },
  },
};

/* The model card and its metrics, in the Markdown report. CHAI's own section:
   another framework has no card, and contributes its own extras or none. */
function chaiCardMarkdown({ line, p }){
  const L = [];
  L.push(`## ${t("card.title")}`, "");
  if(frameworkTranslated()) L.push(`_${t("fw.note")}_`, "");
  CARD.forEach(sec => {
    L.push(`### ${cardSecName(sec)}`, "");
    sec.fields.forEach(f => L.push(`- **${cardLabel(f[0])}:** ${line(cardValOf(p, f[0])) || `_${t("label.notProvided")}_`}`));
    L.push("");
    if(sec.sec === "Trust ingredients"){
      L.push(`### ${t("metrics.title")}`, "");
      if(p.metrics.length){
        L.push(`| ${t("metrics.col.category")} | ${t("metrics.col.metric")} | ${t("metrics.col.value")} | ${t("metrics.col.ci")} | ${t("md.population")} |`, "|---|---|---|---|---|");
        p.metrics.forEach(x => L.push(`| ${line(metricCatName(x.cat))} | ${line(x.name)} | ${line(x.value)} | ${line(x.ci)} | ${line(x.pop)} |`));
      } else L.push(`_${t("md.noneEntered")}_`);
      L.push("");
    }
  });
  return L;
}

/* The change history's words for CHAI's own keys. */
const ChaiKey = Object.freeze({ ITEMS: "items", GATES: "gates", CARD: "card", METRICS: "metrics" });
const CHAI_ITEM_FIELD = Object.freeze({ status: "status", evidence: "evidence", owner: "owner", due: "due date" });
const CHAI_GATE_FIELD = Object.freeze({ decision: "decision", by: "decided by", date: "decision date",
  rationale: "rationale", conditions: "conditions" });
function chaiDescribePath(parts){
  if(parts[0] === ChaiKey.ITEMS){
    const id = parts[1];
    const item = allItems().find(i => i.id === id);
    const what = parts[2] === Field.REFS ? "evidence reference"
      : (Object.hasOwn(CHAI_ITEM_FIELD, parts[2]) ? CHAI_ITEM_FIELD[parts[2]] : parts[2]);
    return item ? `${what} of “${item.text}”` : `${what} of criterion ${id}`;
  }
  if(parts[0] === ChaiKey.GATES){
    const gate = Object.hasOwn(GATES, parts[1]) ? GATES[parts[1]] : null;
    const what = Object.hasOwn(CHAI_GATE_FIELD, parts[2]) ? CHAI_GATE_FIELD[parts[2]] : parts[2];
    return gate ? `${what} for ${gate.title}` : `${what} for checkpoint ${parts[1]}`;
  }
  if(parts[0] === ChaiKey.CARD) return `model card: ${Object.hasOwn(CARD_LABEL, parts[1]) ? CARD_LABEL[parts[1]] : parts[1]}`;
  if(parts[0] === ChaiKey.METRICS) return "key metrics";
  return null;
}
