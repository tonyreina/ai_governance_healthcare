/* ============================================================
   CHAI: what its code adds to the engine's framework (#168)
   The model card view and report section, the Markdown and JSON
   extras, the samples, the side panel and its own controls.
   ============================================================ */
/* The model card view, in the rail after the last checkpoint. */
const CHAI_CARD_VIEW = "card";
frameworkExtras("chai", {
  views: p => [{
    id: CHAI_CARD_VIEW, kind: CHAI_CARD_VIEW, label: t("card.title"), glyph: "≡", sep: "before",
    meta: () => `${CARD_FIELDS.filter(k => cardValOf(p, k)).length}/${CARD_FIELDS.length}`,
  }],
  render: v => v.kind === CHAI_CARD_VIEW ? renderCardForm() : "",
  // In the report, before the history: the card as a reader would see it.
  reportSections: () => `<h2>${esc(t("card.title"))}</h2>
    <div style="max-width:560px">${labelHTML()}</div>
    `,
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
  panel: () => renderLabel(),
  onClick: btn => chaiClick(btn),
  onChange: el => chaiChange(el),
  describePath: parts => chaiDescribePath(parts),
});

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

/* The change history's words for the model card's and the metrics' keys (the
   items and checkpoints are the engine's). */
const ChaiKey = Object.freeze({ CARD: "card", METRICS: "metrics", META: "meta", USE_CASE: "chaiUseCase" });
function chaiDescribePath(parts){
  if(parts[0] === ChaiKey.META && parts[1] === ChaiKey.USE_CASE) return "CHAI use case";
  if(parts[0] === ChaiKey.CARD) return `model card: ${Object.hasOwn(CARD_LABEL, parts[1]) ? CARD_LABEL[parts[1]] : parts[1]}`;
  if(parts[0] === ChaiKey.METRICS) return "key metrics";
  return null;
}
