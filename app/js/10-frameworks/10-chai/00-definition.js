/* ============================================================
   Content model
   Checklist items are paraphrased summaries organized around the
   CHAI six-stage lifecycle and five principles. They are not the
   official CHAI Responsible AI Checklist text.
   ============================================================ */
const PRINCIPLES = {
  U:{name:"Usefulness, usability & efficacy"},
  F:{name:"Fairness"},
  S:{name:"Safety & reliability"},
  T:{name:"Transparency & accountability"},
  P:{name:"Security & privacy"}
};
const STAGES = [
  {id:"s1",n:1,title:"Define the problem & plan",blurb:"Agree on the clinical or operational problem, confirm AI is the right tool, and name who is accountable before anything is built or bought.",items:[
    ["U","Problem statement and target outcome agreed with clinical and operational stakeholders"],
    ["U","Current-state or root-cause analysis shows AI is an appropriate intervention, not just a possible one"],
    ["U","Success measures and a baseline to compare against are defined"],
    ["F","Affected patient populations identified, including groups at risk of being underserved or harmed"],
    ["S","Potential harms and failure modes listed, with severity and likelihood"],
    ["T","Accountable owner, governance body, and decision rights named"],
    ["P","Data needs, privacy, consent, and regulatory constraints scoped"]
  ]},
  {id:"s2",n:2,title:"Design the AI system",blurb:"Specify how the system fits into care: who uses it, where in the workflow, what it outputs, and what happens when it is wrong.",items:[
    ["U","End users took part in workflow and interface design"],
    ["U","Intended use, users, and care setting documented, with out-of-scope uses listed"],
    ["F","Subgroups and fairness criteria for evaluation pre-specified"],
    ["S","Decision thresholds defined and clinically justified"],
    ["S","Human oversight and override path designed into the workflow"],
    ["T","Pathway for reporting safety issues and harms drafted, naming who reports to whom"],
    ["P","Threat model, access controls, and data flows designed"]
  ]},
  {id:"s3",n:3,title:"Engineer the AI solution",blurb:"Build or configure the model with traceable data and documented choices, so the assessment stage has something it can verify.",items:[
    ["T","Data provenance and known data limitations documented"],
    ["F","Demographic and socio-demographic make-up of development data characterized"],
    ["F","Bias mitigation approach chosen and documented"],
    ["S","Data quality checks and handling of missing data documented"],
    ["T","Version control in place for datasets, code, and model artifacts"],
    ["P","De-identification or other privacy-enhancing techniques applied where appropriate"],
    ["S","People responsible for monitoring data and model behavior designated"]
  ]},
  {id:"s4",n:4,title:"Assess",blurb:"Validate the solution locally before patients are exposed to it. Record key metrics below; they flow into the model card.",items:[
    ["U","Performance validated on local data representative of the deployment population"],
    ["F","Performance compared across demographic subgroups, with gaps explained"],
    ["S","Calibration checked, not only discrimination"],
    ["S","Silent (shadow) evaluation run in the live environment"],
    ["S","Installation qualification completed, where applicable"],
    ["T","Explanations of outputs are suited to the intended users"],
    ["P","Security review or vendor security assessment completed"],
    ["T","Safety reporting pathway updated with what assessment revealed"]
  ], metrics:true},
  {id:"s5",n:5,title:"Pilot",blurb:"Run a small, time-boxed pilot to learn whether the solution helps in real care, for whom, and at what cost to staff.",items:[
    ["U","Pilot scope, sites, duration, and stop rules defined"],
    ["U","Usability and workflow fit assessed with frontline users"],
    ["U","Real-world effect on outcomes or process measured against baseline"],
    ["F","Pilot results checked for differences across patient groups"],
    ["S","Adverse events and near misses tracked and reviewed"],
    ["T","Users trained, and the approach to patient disclosure decided"]
  ]},
  {id:"s6",n:6,title:"Deploy & monitor",blurb:"Scale up with monitoring, change control, and a plan for when to retrain or retire.",items:[
    ["S","Performance and drift monitoring live, with alert thresholds and an owner"],
    ["F","Subgroup performance monitored on an ongoing basis"],
    ["T","Audit schedule and change control set, with a revised model card for each version"],
    ["S","Incident response, rollback, and retirement criteria documented"],
    ["P","Access reviews and security patching scheduled"],
    ["U","Value to patients and staff re-evaluated periodically"]
  ]}
];
STAGES.forEach(s=>s.items=s.items.map((it,i)=>({id:`${s.id}-${i+1}`,p:it[0],text:it[1]})));

const GATES = {
  A:{after:"s1",title:"Checkpoint A",q:"Approve moving to design?",help:"Is the problem worth solving with AI, and is the plan sound enough to start design?",options:["Proceed","Proceed with conditions","Revise and resubmit","Stop"]},
  B:{after:"s4",title:"Checkpoint B",q:"Approve a pilot?",help:"Has local assessment shown the solution is safe, effective, and fair enough to expose a small group of patients to it?",options:["Proceed","Proceed with conditions","Revise and resubmit","Stop"]},
  C:{after:"s5",title:"Checkpoint C",q:"Approve deployment at scale?",help:"Did the pilot show real benefit without unacceptable harm or disparity?",options:["Proceed","Proceed with conditions","Revise and resubmit","Stop"]},
  D:{after:"s6",title:"Checkpoint D",q:"Periodic review decision",help:"Based on monitoring, should the solution continue as is, change, or be retired? Record a new review each cycle; the next due date is set from it.",options:["Continue","Continue with changes","Retrain or revise","Retire"]}
};

/* Each decision's class (GateClass in 00-core/10-model.js). The stored value is the
   English option, unchanged; only its meaning is declared here. */
const GATE_OPTION_CLASS = Object.freeze({
  "Proceed": GateClass.GO,
  "Proceed with conditions": GateClass.CONDITIONAL,
  "Revise and resubmit": GateClass.REVISE,
  "Stop": GateClass.STOP,
  "Continue": GateClass.GO,
  "Continue with changes": GateClass.CONDITIONAL,
  "Retrain or revise": GateClass.REVISE,
  "Retire": GateClass.RETIRE,
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
