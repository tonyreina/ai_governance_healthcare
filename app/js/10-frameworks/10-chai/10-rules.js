/* ============================================================
   CHAI: lifecycle rules
   Phase, review cadence, compliance flags and status. These read
   STAGES and GATES from 00-definition.js and are CHAI's alone;
   nothing here is shared with another framework.
   ============================================================ */
/* CHAI's content as the reader sees it (D-60): the English in the definitions,
   translated through tf() when the reader chose another language. Records and
   exports that machines read keep the English. */
const stageTitle = s => tf(`chai.stage.${s.id}.title`, s.title);
const stageBlurb = s => tf(`chai.stage.${s.id}.blurb`, s.blurb);
const itemText = it => tf(`chai.item.${it.id}`, it.text);
const principleName = k => tf(`chai.principle.${k}`, PRINCIPLES[k].name);
const gateTitle = k => tf(`chai.gate.${k}.title`, GATES[k].title);
const gateQuestion = k => tf(`chai.gate.${k}.q`, GATES[k].q);
const gateHelp = k => tf(`chai.gate.${k}.help`, GATES[k].help);
const optionText = o => tf(`chai.option.${o}`, o);
const cardSecName = sec => tf(`chai.card.sec.${CARD.indexOf(sec)}`, sec.sec);
const cardLabel = f0 => tf(`chai.card.${f0}.label`, CARD_LABEL[f0]);
const cardHint = f => f[2] ? tf(`chai.card.${f[0]}.hint`, f[2]) : "";
const metricCatName = c => tf(`chai.metricCat.${c}`, c);

/* CHAI's rules are the engine's, run on CHAI's definition (#168). These names are
   TRANSITIONAL: CHAI's screens and the tests still call them; PR B removes them. */
const CHAI_FW = ENGINES.chai;
function allItems(){ return CHAI_FW.items.map(it => ({id: it.id, p: it.category, text: it.text, stage: STAGES.find(s => s.id === it.section.id)})); }
const gapsUpTo = (p, stageId) => CHAI_FW.gapsUpTo(p, stageId).map(it => ({id: it.id, p: it.category, text: it.text, stage: STAGES.find(s => s.id === it.section.id)}));
const dec = (p, k) => CHAI_FW.decision(p, k);
const optionClass = d => CHAI_FW.decisionClass(d);
const isGo = d => CHAI_FW.advances(d);
const GATE_IDS = Object.keys(GATES);
const phase = p => CHAI_FW.phase(p);
const cadenceMonths = p => CHAI_FW.cadenceMonths(p);
const nextReview = p => CHAI_FW.nextReview(p);
const latestGo = p => CHAI_FW.latestGo(p);
const flags = p => CHAI_FW.flags(p);
const statusOf = p => CHAI_FW.status(p);

/* The model card's flags, at the point CHAI's definition places them: while a
   project is piloting or live, its core fields are filled and it was edited after
   the latest approval. */
registerPlugin(ChaiPlugin.MODEL_CARD, {
  flags({p, live, piloting}) {
    const F = [];
    if (!(live || piloting)) return F;
    const missing = CORE_CARD.filter(k => !cardValOf(p, k));
    if (missing.length) F.push({sev: live ? Severity.RED : Severity.AMBER, text: `Model card missing ${missing.length} core field${missing.length > 1 ? "s" : ""}`, msg: ["flag.cardMissing", {count: missing.length}]});
    const lg = latestGo(p); const cu = p.cardUpdatedAt ? new Date(p.cardUpdatedAt) : null;
    if (lg && (!cu || cu < lg.d)) F.push({sev: Severity.AMBER, text: `Model card not updated since ${GATES[lg.k].title}`, msg: ["flag.cardStale", {gateKey: lg.k}]});
    return F;
  },
});
/* Key metrics, recorded at stage 4, are expected once a project pilots. */
registerPlugin(ChaiPlugin.METRICS, {
  flags({p, live, piloting}) {
    if (!(live || piloting) || p.metrics.some(m => m.name || m.value)) return [];
    return [{sev: Severity.AMBER, text: "No key metrics recorded", msg: ["flag.noMetrics", {}]}];
  },
});
registerPlugin(ChaiPlugin.TE_METRICS, {});
registerPlugin(ChaiPlugin.SAMPLES, {});
