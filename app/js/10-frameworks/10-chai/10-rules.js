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

function allItems(){ return STAGES.flatMap(s=>s.items.map(it=>({...it,stage:s}))); }
function gapsUpTo(p,stageId){
  const idx=STAGES.findIndex(s=>s.id===stageId);
  return STAGES.slice(0,idx+1).flatMap(s=>s.items.filter(it=>{const st=(p.items[it.id]||{}).status; return !st||st==="notmet";}).map(it=>({...it,stage:s})));
}
const dec = (p,k)=> ((p.gates||{})[k]||{}).decision||"";
/* A decision's class, or null when none is recorded. A stored value this build
   does not know (an edited import, a renamed option) has no class, so it neither
   advances nor ends anything. */
const optionClass = d => (d && Object.hasOwn(GATE_OPTION_CLASS, d)) ? GATE_OPTION_CLASS[d] : null;
const isGo = d => ADVANCES.has(optionClass(d));
const GATE_IDS = Object.keys(GATES);
function phase(p){
  // `label` is the English an export records; `msg` is the catalog key a reader sees.
  const classes = GATE_IDS.map(k => optionClass(dec(p,k)));
  if(classes.includes(GateClass.STOP)) return {key:"retired",label:"Stopped",msg:"phase.stopped"};
  if(classes.includes(GateClass.RETIRE)) return {key:"retired",label:"Retired",msg:"phase.retired"};
  if(isGo(dec(p,"C"))) return {key:"deployed",label:"Deployed",stage:6,msg:"phase.deployed"};
  if(isGo(dec(p,"B"))) return {key:"pilot",label:"Pilot",stage:5,msg:"phase.pilot"};
  if(isGo(dec(p,"A"))) return {key:"build",label:"Design, build & assess",stage:2,msg:"phase.build"};
  return {key:"intake",label:"Intake & planning",stage:1,msg:"phase.intake"};
}
function cadenceMonths(p){ const n=parseInt(p.meta.reviewCadence,10); return n>0?n:(p.meta.riskTier==="High"?6:12); }
function nextReview(p){
  if(phase(p).key!=="deployed") return null;
  const base = parseDay(dec(p,"D") ? p.gates.D.date : "") || parseDay(p.gates.C.date);
  if(!base) return null;
  return ymd(addMonths(base,cadenceMonths(p)));
}
function latestGo(p){
  let best=null;
  ["A","B","C","D"].forEach(k=>{ const g=p.gates[k]||{}; if(isGo(g.decision)){ const d=parseDay(g.date); if(d && (!best||d>best.d)) best={k,d}; }});
  return best;
}

/* Compliance rules. Red = out of compliance, amber = needs update. */
function flags(p){
  const F=[]; const ph=phase(p); const today=parseDay(TODAY());
  if(ph.key==="retired") return F;
  const live = ph.key==="deployed", piloting = ph.key==="pilot";
  const items=allItems();
  const overdue = items.filter(it=>{const d=p.items[it.id]||{}; const due=parseDay(d.due); return due && due<today && d.status!=="met" && d.status!=="na";});
  if(overdue.length) F.push({sev:(live||piloting)?"red":"amber",text:`${overdue.length} action${overdue.length>1?"s":""} past due`,msg:["flag.pastDue",{count:overdue.length}]});
  if(live){
    const notmet=items.filter(it=>(p.items[it.id]||{}).status==="notmet").length;
    if(notmet) F.push({sev:"red",text:`Live with ${notmet} criteri${notmet>1?"a":"on"} not met`,msg:["flag.liveNotMet",{count:notmet}]});
    const nr=nextReview(p);
    if(!nr) F.push({sev:"red",text:"Live with no deployment date recorded at Checkpoint C",msg:["flag.noDeployDate",{}]});
    else { const d=parseDay(nr), left=daysBetween(today,d);
      if(left<0) F.push({sev:"red",text:`Periodic review overdue since ${fmtDay(nr)}`,msg:["flag.reviewOverdue",{date:nr}]});
      else if(left<=30) F.push({sev:"amber",text:`Periodic review due ${fmtDay(nr)}`,msg:["flag.reviewDue",{date:nr}]}); }
    if(optionClass(dec(p,"D"))===GateClass.REVISE) F.push({sev:"amber",text:"Last review asked for retraining or revision",msg:["flag.retrain",{}]});
  }
  if(live||piloting){
    const missing=CORE_CARD.filter(k=>!cardValOf(p,k));
    if(missing.length) F.push({sev:live?"red":"amber",text:`Model card missing ${missing.length} core field${missing.length>1?"s":""}`,msg:["flag.cardMissing",{count:missing.length}]});
    const lg=latestGo(p); const cu=p.cardUpdatedAt?new Date(p.cardUpdatedAt):null;
    if(lg && (!cu || cu < lg.d)) F.push({sev:"amber",text:`Model card not updated since ${GATES[lg.k].title}`,msg:["flag.cardStale",{gateKey:lg.k}]});
    if(!p.metrics.some(m=>m.name||m.value)) F.push({sev:"amber",text:"No key metrics recorded",msg:["flag.noMetrics",{}]});
  }
  ["A","B","C","D"].forEach(k=>{ const g=p.gates[k]||{};
    if(isGo(g.decision) && !(g.rationale||"").trim()){
      if(optionClass(g.decision)===GateClass.CONDITIONAL) F.push({sev:"amber",text:`${GATES[k].title}: conditional approval with no conditions recorded`,msg:["flag.noConditions",{gateKey:k}]});
      else if(gapsUpTo(p,GATES[k].after).length) F.push({sev:"amber",text:`${GATES[k].title}: approved with open criteria and no rationale`,msg:["flag.noRationale",{gateKey:k}]});
    }});
  if(!live && p.updatedAt){ const idle=daysBetween(new Date(p.updatedAt),new Date()); if(idle>90) F.push({sev:"amber",text:`No activity in ${idle} days`,msg:["flag.idle",{count:idle}]}); }
  return F.sort((a,b)=>(a.sev==="red"?0:1)-(b.sev==="red"?0:1));
}
function statusOf(p){
  const ph=phase(p); if(ph.key==="retired") return {key:"retired",label:ph.label,msg:ph.msg};
  const f=flags(p);
  if(f.some(x=>x.sev==="red")) return {key:"red",label:"Out of compliance",msg:"status.red"};
  if(f.length) return {key:"amber",label:"Needs update",msg:"status.amber"};
  return {key:"green",label:"On track",msg:"status.green"};
}
