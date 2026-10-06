/* ============================================================
   Examples
   One sample project per CHAI use case, so the portfolio shows the
   range of things a governance committee actually has in front of
   it: a retired model, one out of compliance, a couple mid-pilot,
   and several still in intake.

   Each sample names its CHAI use case, which pre-selects the
   Testing & Evaluation metric picker at stage 4, and carries a few
   metrics with CHAI's own metric names so the connection between
   the two is visible rather than described.

   Samples are declarative: the table below says what state a
   project is in, and buildSample() assembles it. Adding one means
   adding a row, not another block of imperative code.
   ============================================================ */
const EX_CARD={contact:"aigovernance@example.org",releaseStage:"General availability",version:"3.2-local",availability:"United States",regulatory:"Not FDA-cleared; deployed as clinical decision support",
  summary:"Scores adult inpatients every hour for risk of clinical deterioration within 12 hours. Flags patients for nurse review; does not replace clinical judgment.",
  keywords:"early warning, deterioration, inpatient",intendedUse:"Hourly risk score on the unit patient list; scores above threshold prompt a bedside nurse assessment.",
  users:"Bedside and charge nurses on adult med-surg units",howTo:"Review flagged patients within 30 minutes and document the assessment; escalate per rapid-response policy.",
  population:"Adults 18+ admitted to medical-surgical units",outOfScope:"ICU, pediatrics, obstetrics, emergency department, and comfort-care patients",
  risks:"Alert fatigue; reduced sensitivity in younger adults; depends on timely vital-sign charting.",biases:"Development cohort demographics not yet disclosed by vendor.",riskLevel:"Moderate: informs escalation decisions",
  outputs:"Risk score 0–100 and a threshold flag",modelType:"Gradient-boosted trees",foundation:"None",inputSource:"EHR vital signs, labs, nursing assessments",dataType:"Structured EHR data in; numeric score out",
  maintenance:"Monthly performance and drift report to the AI governance committee; vendor recalibration annually or on drift alert."};
const EX_METRICS=[
  {cat:"Usefulness, usability & efficacy",name:"AUROC, 12-hour deterioration",value:"0.82",ci:"0.80–0.84",pop:"All adults, local validation"},
  {cat:"Fairness & equity",name:"Sensitivity at threshold",value:"0.71",ci:"0.66–0.76",pop:"Age 18–30"},
  {cat:"Fairness & equity",name:"Sensitivity at threshold",value:"0.79",ci:"0.77–0.81",pop:"Age 65+"},
  {cat:"Safety & reliability",name:"Calibration slope",value:"0.94",ci:"",pop:"All adults"}];

const U="Usefulness, usability & efficacy", F="Fairness & equity", SR="Safety & reliability";

/* Each row: how far the review got, what is outstanding, and why.
   `stages` are filled "met"; `items` overrides individual criteria;
   `gates` are decisions already taken. `day` offsets are relative to
   today, so the dashboard's overdue and due-soon states are live. */
const SAMPLES=[
  {
    name:"Sepsis early warning (sample)", use:"sepsis-risk-prediction",
    meta:{developer:"Example Vendor, Inc.",sourcing:"Purchased from a vendor",sponsor:"Dr. L. Chen, Critical Care",riskTier:"High",reviewCadence:"12 months",scope:"All adult inpatient units"},
    stages:[1,2,3,4,5,6],
    items:{"s3-2":["notmet","Vendor declined to share cohort demographics.","Procurement",-20],
           "s6-2":["partial","Subgroup dashboard built for age and sex only.","Data science",30]},
    gates:{A:["Proceed",-520],B:["Proceed",-460],C:["Proceed",-400]},
    card:{summary:"Flags adult inpatients at risk of sepsis for rapid assessment."},
    metrics:[...EX_METRICS,
      {cat:U,name:"Area under the curve (AUC)—receiver operating characteristic (ROC) (AUC-ROC)",value:"0.81",ci:"0.79–0.83",pop:"Local validation, 18 months"}],
    updated:-30, cardAt:-420,
  },
  {
    name:"Ambient clinical documentation (sample)", use:"Ambient-AI",
    meta:{developer:"Example Scribe Co.",sourcing:"Purchased from a vendor",sponsor:"Dr. M. Okafor, Primary Care",riskTier:"Moderate",scope:"Six primary care clinics"},
    stages:[1,2,3,4],
    items:{"s4-2":["partial","Accuracy for non-native English speakers under review.","Clinical informatics",25]},
    gates:{A:["Proceed",-120],B:["Proceed with conditions",-20]},
    card:{summary:"Drafts visit notes from ambient audio for clinician review and signature.",intendedUse:"Draft note generation during outpatient visits.",users:"Primary care clinicians",population:"Adult outpatients who consent to recording",outOfScope:"Behavioral health and sensitive visits",risks:"Hallucinated findings; omissions.",riskLevel:"Moderate",outputs:"Draft visit note",inputSource:"Visit audio",maintenance:"Monthly note-quality audit."},
    metrics:[{cat:SR,name:"Notes with a clinically significant error",value:"1.8%",ci:"",pop:"Silent evaluation, 400 notes"}],
    updated:-3, cardAt:-60,
  },
  {
    name:"Stroke imaging triage (sample)", use:"clinical-decision-support",
    meta:{developer:"Internal radiology AI team",sourcing:"Built internally",sponsor:"Dr. P. Nguyen, Neuroradiology",riskTier:"High"},
    stages:[1],
    items:{"s2-1":["met"],"s2-2":["met"],"s2-3":["partial","Scanner-vendor subgroups being added.","Radiology AI team",10]},
    gates:{A:["Proceed",-10]},
    updated:-1,
  },
  {
    name:"Discharge summary drafting (sample)", use:"patient-discharge-summarization",
    meta:{developer:"Example Health LLM Co.",sourcing:"Purchased from a vendor",sponsor:"Dr. R. Adeyemi, Hospital Medicine",riskTier:"Moderate",scope:"Medicine and surgery wards, two hospitals"},
    stages:[1,2,3,4],
    items:{"s4-1":["partial","Local evaluation on 300 summaries; clinician review ongoing.","Clinical informatics",18],
           "s4-8":["notmet","Safety reporting route for summary errors not yet agreed.","Patient safety",-5]},
    gates:{A:["Proceed",-150]},
    card:{summary:"Drafts a discharge summary from the encounter record for clinician editing and sign-off.",intendedUse:"Draft generation at discharge; the clinician remains the author.",users:"Hospitalists and discharge coordinators",population:"Adults discharged from medicine and surgery wards",outOfScope:"Deaths, transfers to other acute facilities, and against-medical-advice discharges",risks:"Omission of an active problem or a changed medication; fluent text invites less scrutiny.",riskLevel:"Moderate: a clinician signs every summary",outputs:"Draft discharge summary text",inputSource:"Encounter notes, medication list, problem list",maintenance:"Monthly sample audit by hospital medicine."},
    metrics:[{cat:U,name:"DocLens",value:"0.78",ci:"",pop:"300 local summaries"},
             {cat:U,name:"BERTScore",value:"0.89",ci:"",pop:"300 local summaries"},
             {cat:SR,name:"Omission rate of active problems",value:"4.2%",ci:"2.6–6.5%",pop:"Clinician-reviewed sample, n=300"}],
    updated:-6, cardAt:-20,
  },
  {
    name:"Prior authorization criteria matching (sample)", use:"prior-authorization-ai-supported-criteria-matching",
    meta:{developer:"Example Payer Systems",sourcing:"Purchased from a vendor",sponsor:"J. Whitfield, Revenue Cycle",riskTier:"Moderate",scope:"Outpatient imaging and infusion authorizations"},
    stages:[1,2],
    items:{"s1-5":["partial","Harm register drafted; denial-delay scenarios still to be assessed.","Compliance",12],
           "s2-5":["notmet","Escalation path for contested matches not designed.","Utilization management",20]},
    gates:{A:["Proceed with conditions",-45]},
    card:{summary:"Matches submitted clinical documentation against payer coverage criteria to support, never to replace, a human authorization decision.",intendedUse:"Surfaces which coverage criteria are met and which are unevidenced.",users:"Utilization review nurses",outOfScope:"Any automated denial. Denials remain a human decision.",risks:"Over-reliance on a confident-looking match; policy drift after a payer update.",riskLevel:"Moderate: cannot deny, but can shape a reviewer's attention"},
    metrics:[{cat:U,name:"Reduce Turnaround Time (TAT)",value:"-31%",ci:"",pop:"Pilot queue vs. prior quarter"},
             {cat:U,name:"Policy Coverage Completeness",value:"92%",ci:"",pop:"Benchmark policy set"},
             {cat:F,name:"Predictive Parity (Positive Predictive Value Parity)",value:"0.04",ci:"",pop:"Largest gap across payer line of business"}],
    updated:-9, cardAt:-30,
  },
  {
    name:"Patient-facing health advice chatbot (sample)", use:"general-health-advice-chatbot",
    meta:{developer:"Example Digital Front Door",sourcing:"Co-developed",sponsor:"Dr. S. Haddad, Population Health",riskTier:"High",scope:"Public website and patient portal"},
    stages:[1,2],
    items:{"s1-5":["partial","Crisis and emergency-symptom scenarios still being enumerated.","Clinical safety",8],
           "s2-4":["notmet","Escalation threshold for urgent symptoms not yet set.","Clinical safety",6],
           "s2-6":["notmet","No safety reporting route for harmful advice.","Patient safety",-2]},
    gates:{A:["Revise and resubmit",-14]},
    card:{summary:"Answers general health questions for patients, with escalation to a clinician for anything urgent.",population:"Adults using the patient portal",outOfScope:"Diagnosis, medication dosing, emergencies, pediatrics, and mental health crises",risks:"Plausible but wrong advice; failure to escalate an emergency.",riskLevel:"High: unsupervised patient-facing advice"},
    metrics:[{cat:U,name:"Low-Confidence Trigger Rate; Escalation Success Rate",value:"88%",ci:"",pop:"Escalation success, scripted red-flag set"},
             {cat:SR,name:"Percentage (%) Uptime",value:"99.4%",ci:"",pop:"Staging, 90 days"}],
    updated:-2,
  },
  {
    name:"Mental health triage support (sample)", use:"mental-health",
    meta:{developer:"Example Behavioral AI",sourcing:"Purchased from a vendor",sponsor:"Dr. K. Oyelaran, Behavioral Health",riskTier:"High",scope:"Behavioral health intake line"},
    stages:[1],
    items:{"s1-4":["partial","Populations at risk of under-detection not yet characterized.","Behavioral health",15],
           "s1-5":["notmet","Self-harm failure modes not enumerated.","Clinical safety",-8]},
    gates:{},
    card:{summary:"Supports triage of behavioral health intake contacts; never autonomous.",riskLevel:"High: crisis detection failure is a safety event"},
    metrics:[{cat:F,name:"Cross-Demographic Safety & Quality Disparity Score (CDSQ-DS)",value:"pending",ci:"",pop:"Not yet measured locally"}],
    updated:-4,
  },
  {
    name:"Clinical trial pre-screening (sample)", use:"clinical-trials",
    meta:{developer:"Example Research Informatics",sourcing:"Built internally",sponsor:"Dr. T. Lindqvist, Oncology Research",riskTier:"Moderate",scope:"Oncology trials portfolio"},
    stages:[1,2,3],
    items:{"s3-5":["partial","Dataset and model artifacts versioned; code not yet.","Research informatics",22]},
    gates:{A:["Proceed",-200]},
    card:{summary:"Pre-screens the EHR for patients who may be eligible for an open trial; a coordinator confirms every match.",riskLevel:"Moderate: affects access to research, not direct care"},
    metrics:[{cat:U,name:"Enrollment Rate",value:"+18%",ci:"",pop:"Pilot arm vs. matched prior period"},
             {cat:F,name:"Patient-Criterion Fairness-Constrained Matching (Accuracy/Fairness Trade-off Curve)",value:"see report",ci:"",pop:"Race and language subgroups"}],
    updated:-11, cardAt:-50,
  },
  {
    name:"EHR record search (sample)", use:"electronic-health-record-information-retrieval",
    meta:{developer:"Example EHR Vendor",sourcing:"Purchased from a vendor",sponsor:"Dr. N. Brightwater, CMIO office",riskTier:"Low",reviewCadence:"24 months",scope:"Enterprise-wide, read-only"},
    stages:[1,2,3,4,5,6],
    items:{},
    gates:{A:["Proceed",-700],B:["Proceed",-640],C:["Proceed",-580],D:["Continue",-200]},
    card:{summary:"Retrieves and cites passages from a patient's record in response to a clinician's question.",
      intendedUse:"Answers a clinician's question about one patient by quoting that patient's own record, with a citation to the source note.",
      users:"Any clinician with existing read access to the record",
      population:"All patients with a record in the EHR",
      outOfScope:"Clinical recommendations, summarization across patients, and any population or research query",
      risks:"A retrieved passage can be accurate but stale; a question can be answered from the wrong encounter.",
      riskLevel:"Low: retrieval only, always cited to the source document",
      outputs:"Quoted passages with citations to the source note",
      inputSource:"The patient's existing EHR documents, respecting the user's access rights",
      maintenance:"Annual review; citation-accuracy audit each quarter."},
    metrics:[{cat:U,name:"Citation accuracy",value:"97.1%",ci:"",pop:"Quarterly audit, 500 answers"}],
    updated:-45, cardAt:-180,
  },
  {
    name:"Autonomous scheduling agent (sample)", use:"agentic",
    meta:{developer:"Example Agent Labs",sourcing:"Purchased from a vendor",sponsor:"Operations committee",riskTier:"High",scope:"Specialty clinic scheduling"},
    stages:[1,2,3,4,5],
    items:{},
    gates:{A:["Proceed",-300],B:["Proceed",-240],C:["Stop",-30]},
    card:{summary:"Took scheduling actions on a patient's behalf across several systems.",riskLevel:"High: acted without a human in the loop",risks:"Pilot showed unrecoverable actions with no audit trail."},
    metrics:[{cat:U,name:"Goal Completion Rate (GCR)",value:"0.74",ci:"",pop:"Pilot, 6 weeks"},
             {cat:SR,name:"Autonomy Index (AIx)",value:"high",ci:"",pop:"Pilot; flagged at Checkpoint C"}],
    updated:-30, cardAt:-120,
  },
];

function fillItems(p, stages, status){ STAGES.filter(s=>stages.includes(s.n)).forEach(s=>s.items.forEach(it=>p.items[it.id]={status,evidence:"",owner:"",due:""})); }

function buildSample(spec, now){
  const d=n=>ymd(addDays(now,n)), iso=n=>addDays(now,n).toISOString();
  const p=blankProject(spec.name);
  Object.assign(p.meta,{org:"Example Regional Health",chaiUseCase:spec.use||""},spec.meta||{});
  fillItems(p, spec.stages||[], "met");
  Object.entries(spec.items||{}).forEach(([id,[status,evidence,owner,due]])=>{
    p.items[id]={status,evidence:evidence||"",owner:owner||"",due:due==null?"":d(due)};
  });
  Object.entries(spec.gates||{}).forEach(([k,[decision,day]])=>{
    p.gates[k]={decision,by:"AI governance committee",date:d(day),
      rationale:/Stop|Revise/.test(decision)?"See the review record.":"Met criteria for this stage.",
      signedBy:ME.id||null,signedAt:iso(day)};
  });
  if(spec.card) p.card=Object.assign(spec.use==="sepsis-risk-prediction"?clone(EX_CARD):{}, spec.card);
  if(spec.metrics) p.metrics=clone(spec.metrics);
  if(spec.cardAt!=null) p.cardUpdatedAt=iso(spec.cardAt);
  if(spec.updated!=null) p.updatedAt=iso(spec.updated);
  return p;
}

function exampleInto(p){
  const today=new Date(), d=n=>ymd(addDays(today,n));
  Object.assign(p.meta,{org:p.meta.org||"Example Regional Health",developer:"Example Vendor, Inc.",sourcing:"Purchased from a vendor",sponsor:"Dr. A. Rivera, Hospital Medicine",reviewers:"CMIO; nursing informatics lead; data science lead; compliance officer; patient and family advisor",riskTier:"Moderate",startDate:d(-40),scope:"Adult med-surg units at two hospitals; vendor version 3.2",chaiUseCase:"sepsis-risk-prediction"});
  fillItems(p,[1,2],"met");
  p.items["s1-4"]={status:"partial",evidence:"Limited-English-proficiency patients not yet considered.",owner:"Nursing informatics",due:d(21)};
  p.items["s3-1"]={status:"partial",evidence:"Vendor provided a summary only; full provenance requested.",owner:"Procurement",due:d(14)};
  p.items["s3-2"]={status:"notmet",evidence:"Vendor has not shared development cohort demographics.",owner:"Procurement",due:d(14)};
  p.gates.A={decision:"Proceed",by:"AI governance committee",date:d(-30),rationale:"Clear clinical need; strong sponsor.",signedBy:ME.id||null,signedAt:new Date().toISOString()};
  p.metrics=clone(EX_METRICS);
  p.card=Object.assign(clone(EX_CARD),{releaseStage:"Silent evaluation"}); p.cardUpdatedAt=new Date().toISOString();
}

/* Additive and repeatable. The samples used to be loadable only into an
   empty workspace, from a button that vanished as soon as anything existed --
   so anyone who loaded them once could never get the ones added later, and
   there was no way to top up. Matching on name keeps a second press from
   duplicating what is already there. */
async function loadSamples(){
  const now=new Date();
  const have=new Set([...PROJECTS.values()].map(p=>(p.meta.solution||"").trim()));
  const missing=SAMPLES.filter(spec=>!have.has(spec.name));
  if(!missing.length){ toast("All sample projects are already here"); return; }
  for(const spec of missing) await createProject(buildSample(spec, now), "Sample project added");
  toast(`${missing.length} sample project${missing.length===1?"":"s"} added`);
}
