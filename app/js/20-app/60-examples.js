/* ============================================================
   Examples
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
function fillItems(p, stages, status){ STAGES.filter(s=>stages.includes(s.n)).forEach(s=>s.items.forEach(it=>p.items[it.id]={status,evidence:"",owner:"",due:""})); }
function exampleInto(p){
  const today=new Date(), d=n=>ymd(addDays(today,n));
  Object.assign(p.meta,{org:p.meta.org||"Example Regional Health",developer:"Example Vendor, Inc.",sourcing:"Purchased from a vendor",sponsor:"Dr. A. Rivera, Hospital Medicine",reviewers:"CMIO; nursing informatics lead; data science lead; compliance officer; patient and family advisor",riskTier:"Moderate",startDate:d(-40),scope:"Adult med-surg units at two hospitals; vendor version 3.2"});
  fillItems(p,[1,2],"met");
  p.items["s1-4"]={status:"partial",evidence:"Limited-English-proficiency patients not yet considered.",owner:"Nursing informatics",due:d(21)};
  p.items["s3-1"]={status:"partial",evidence:"Vendor provided a summary only; full provenance requested.",owner:"Procurement",due:d(14)};
  p.items["s3-2"]={status:"notmet",evidence:"Vendor has not shared development cohort demographics.",owner:"Procurement",due:d(14)};
  p.gates.A={decision:"Proceed",by:"AI governance committee",date:d(-30),rationale:"Clear clinical need; strong sponsor.",signedBy:ME.id||null,signedAt:new Date().toISOString()};
  p.metrics=clone(EX_METRICS);
  p.card=Object.assign(clone(EX_CARD),{releaseStage:"Silent evaluation"}); p.cardUpdatedAt=new Date().toISOString();
}
async function loadSamples(){
  const now=new Date(), d=n=>ymd(addDays(now,n)), iso=n=>addDays(now,n).toISOString();
  // 1: live, review overdue, one criterion not met
  const a=blankProject("Sepsis early warning (sample)");
  Object.assign(a.meta,{org:"Example Regional Health",developer:"Example Vendor, Inc.",sourcing:"Purchased from a vendor",sponsor:"Dr. L. Chen, Critical Care",riskTier:"High",reviewCadence:"12 months",scope:"All adult inpatient units"});
  fillItems(a,[1,2,3,4,5,6],"met");
  a.items["s3-2"]={status:"notmet",evidence:"Vendor declined to share cohort demographics.",owner:"Procurement",due:d(-20)};
  a.items["s6-2"]={status:"partial",evidence:"Subgroup dashboard built for age and sex only.",owner:"Data science",due:d(30)};
  ["A","B","C"].forEach((k,i)=>a.gates[k]={decision:"Proceed",by:"AI governance committee",date:d(-520+i*60),rationale:"Met criteria for this stage.",signedBy:ME.id||null,signedAt:iso(-520+i*60)});
  a.card=Object.assign(clone(EX_CARD),{summary:"Flags adult inpatients at risk of sepsis for rapid assessment."}); a.metrics=clone(EX_METRICS); a.cardUpdatedAt=iso(-420); a.updatedAt=iso(-30);
  // 2: pilot, conditional approval without conditions, card stale
  const b=blankProject("Ambient clinical documentation (sample)");
  Object.assign(b.meta,{org:"Example Regional Health",developer:"Example Scribe Co.",sourcing:"Purchased from a vendor",sponsor:"Dr. M. Okafor, Primary Care",riskTier:"Moderate",scope:"Six primary care clinics"});
  fillItems(b,[1,2,3,4],"met"); b.items["s4-2"]={status:"partial",evidence:"Accuracy for non-native English speakers under review.",owner:"Clinical informatics",due:d(25)};
  b.gates.A={decision:"Proceed",by:"AI governance committee",date:d(-120),rationale:"High clinician burden; good fit.",signedBy:ME.id||null,signedAt:iso(-120)};
  b.gates.B={decision:"Proceed with conditions",by:"AI governance committee",date:d(-20),rationale:"",signedBy:ME.id||null,signedAt:iso(-20)};
  b.card={summary:"Drafts visit notes from ambient audio for clinician review and signature.",intendedUse:"Draft note generation during outpatient visits.",users:"Primary care clinicians",population:"Adult outpatients who consent to recording",outOfScope:"Behavioral health and sensitive visits",risks:"Hallucinated findings; omissions.",riskLevel:"Moderate",outputs:"Draft visit note",inputSource:"Visit audio",maintenance:"Monthly note-quality audit."};
  b.metrics=[{cat:"Safety & reliability",name:"Notes with a clinically significant error",value:"1.8%",ci:"",pop:"Silent evaluation, 400 notes"}];
  b.cardUpdatedAt=iso(-60); b.updatedAt=iso(-3);
  // 3: early, on track
  const c=blankProject("Stroke imaging triage (sample)");
  Object.assign(c.meta,{org:"Example Regional Health",developer:"Internal radiology AI team",sourcing:"Built internally",sponsor:"Dr. P. Nguyen, Neuroradiology",riskTier:"High"});
  fillItems(c,[1],"met"); c.items["s2-1"]={status:"met"}; c.items["s2-2"]={status:"met"}; c.items["s2-3"]={status:"partial",evidence:"Scanner-vendor subgroups being added.",owner:"Radiology AI team",due:d(10)};
  c.gates.A={decision:"Proceed",by:"AI governance committee",date:d(-10),rationale:"Door-to-needle time is a priority metric.",signedBy:ME.id||null,signedAt:iso(-10)};
  c.updatedAt=iso(-1);
  for(const p of [a,b,c]) await createProject(p,"Sample project added");
  toast("Sample projects added");
}
