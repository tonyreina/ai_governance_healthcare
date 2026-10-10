/* ============================================================
   CHAI: the model card's and the metrics' rules (plug-ins)
   The rest of CHAI's rules (phase, review, the lifecycle flags) are
   the engine's, run on CHAI's definition.
   ============================================================ */
/* The model card as the reader sees it (D-60): the English here, translated
   through tf() when the reader chose another language. */
const cardSecName = sec => tf(`chai.card.sec.${CARD.indexOf(sec)}`, sec.sec);
const cardLabel = f0 => tf(`chai.card.${f0}.label`, CARD_LABEL[f0]);
const cardHint = f => f[2] ? tf(`chai.card.${f[0]}.hint`, f[2]) : "";
const metricCatName = c => tf(`chai.metricCat.${c}`, c);

/* The model card's flags, at the point CHAI's definition places them: while a
   project is piloting or live, its core fields are filled and it was edited after
   the latest approval. */
registerPlugin(ChaiPlugin.MODEL_CARD, {
  flags({p, live, piloting, fw}) {
    const F = [];
    if (!(live || piloting)) return F;
    const missing = CORE_CARD.filter(k => !cardValOf(p, k));
    if (missing.length) F.push({sev: live ? Severity.RED : Severity.AMBER, text: `Model card missing ${missing.length} core field${missing.length > 1 ? "s" : ""}`, msg: ["flag.cardMissing", {count: missing.length}]});
    const lg = fw.latestGo(p); const cu = p.cardUpdatedAt ? new Date(p.cardUpdatedAt) : null;
    if (lg && (!cu || cu < lg.d)) F.push({sev: Severity.AMBER, text: `Model card not updated since ${fw.gateById[lg.k].title}`, msg: ["flag.cardStale", {gateKey: lg.k}]});
    return F;
  },
});
/* Key metrics, recorded at stage 4 (its slot), are expected once a project pilots. */
registerPlugin(ChaiPlugin.METRICS, {
  flags({p, live, piloting}) {
    if (!(live || piloting) || p.metrics.some(m => m.name || m.value)) return [];
    return [{sev: Severity.AMBER, text: "No key metrics recorded", msg: ["flag.noMetrics", {}]}];
  },
  slot: () => metricsHTML(),
});
registerPlugin(ChaiPlugin.TE_METRICS, {});
registerPlugin(ChaiPlugin.SAMPLES, {});
