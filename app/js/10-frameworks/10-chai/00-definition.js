/* ============================================================
   CHAI: the applied model card and its metrics (plug-in data)
   ============================================================ */
/* CHAI's criteria, stages, checkpoints and rules are data:
   app/frameworks/chai/framework.json, run by the engine (01-engine/). What
   remains here is CHAI's code plug-ins: the applied model card and its key
   metrics. */
/* CHAI's code plug-ins, by the names its definition uses. */
const ChaiPlugin = Object.freeze({
  MODEL_CARD: "chai.modelCard", METRICS: "chai.metrics", TE_METRICS: "chai.teMetrics", SAMPLES: "chai.samples",
});

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
