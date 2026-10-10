/* ============================================================
   Content model
   Checklist items are paraphrased summaries organized around the
   CHAI six-stage lifecycle and five principles. They are not the
   official CHAI Responsible AI Checklist text.
   ============================================================ */
/* CHAI's content is data: app/frameworks/chai/framework.json, embedded by the build
   as FRAMEWORK_DEFS.chai and run by the engine (01-engine/). These are TRANSITIONAL
   views of that definition in the shapes CHAI's screens still read (#168 PR A); the
   generic renderers replace them, and tests/test_framework_boundary.py fails if one
   is still here after that. */
const CHAI_DEF = FRAMEWORK_DEFS.chai;
/* CHAI's code plug-ins, by the names its definition uses. */
const ChaiPlugin = Object.freeze({
  MODEL_CARD: "chai.modelCard", METRICS: "chai.metrics", TE_METRICS: "chai.teMetrics", SAMPLES: "chai.samples",
});
const PRINCIPLES = Object.freeze(Object.fromEntries(CHAI_DEF.categories.map(c => [c.id, {name: c.name}])));
const STAGES = CHAI_DEF.sections.map(s => ({
  id: s.id, n: s.n, title: s.title, blurb: s.blurb,
  ...((s.slots || []).includes(ChaiPlugin.METRICS) ? {metrics: true} : {}),
  items: s.items.map(it => ({id: it.id, p: it.category, text: it.text})),
}));
const GATES = Object.fromEntries(CHAI_DEF.gates.map(g => [g.id,
  {after: g.after, title: g.title, q: g.question, help: g.help, options: g.options.map(o => o.value)}]));
/* Each decision's class (GateClass in 00-core/10-model.js), from the definition. */
const GATE_OPTION_CLASS = Object.freeze(Object.fromEntries(
  CHAI_DEF.gates.flatMap(g => g.options.map(o => [o.value, o.class]))));

const CARD = [
  {sec:"Identity",fields:[
    ["name","Name","",0],["developer","Developer","",0],["contact","Inquiries or to report an issue","Email or phone",0],
    ["releaseStage","Release stage","e.g. Pilot, General availability",0],["releaseDate","Release date","",0],["version","Version","Tie the card to a software version",0],
    ["availability","Global availability","",0],["regulatory","Regulatory approval, if applicable","e.g. FDA 510(k) number, or not a device",0],
    ["summary","Summary","The most important things a clinician or buyer should know",1],["keywords","Keywords","",0]]},
  {sec:"Uses and directions",fields:[
    ["intendedUse","Intended use and workflow","",1],["users","Primary intended users","",0],["howTo","How to use","",1],
    ["population","Targeted patient population","",1],["outOfScope","Cautioned out-of-scope settings and use cases","",1]]},
  {sec:"Warnings",fields:[
    ["risks","Known risks and limitations","",1],["biases","Known biases or ethical considerations","",1],["riskLevel","Clinical risk level","e.g. Low, Moderate, High, with a one-line reason",0]]},
  {sec:"Trust ingredients",fields:[
    ["outputs","Outcome(s) and output(s)","",1],["modelType","Model type","",0],["foundation","Foundation models used, if applicable","",0],
    ["inputSource","Input data source","",1],["dataType","Input and output data types","",0],["devData","Development data characterization","Size, dates, sites, demographics",1],
    ["biasMitigation","Bias mitigation approaches","",1],["maintenance","Ongoing maintenance","Monitoring, retraining cadence, owner",1],
    ["security","Security and compliance practices or accreditations","",1]]},
  {sec:"Resources",fields:[
    ["evalRefs","Evaluation references","",1],["trials","Clinical trials","",0],["pubs","Peer-reviewed publications","",1],
    ["reimbursement","Reimbursement status","",0],["consent","Patient consent or disclosure","",1]]}
];
const CARD_FIELDS = CARD.flatMap(s=>s.fields.map(f=>f[0]));
const CORE_CARD = ["intendedUse","users","population","outOfScope","risks","riskLevel","outputs","inputSource","maintenance"];
const CARD_LABEL = Object.fromEntries(CARD.flatMap(s=>s.fields.map(f=>[f[0],f[1]])));
const METRIC_CATS = ["Usefulness, usability & efficacy","Fairness & equity","Safety & reliability"];
