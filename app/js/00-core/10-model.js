/* ============================================================
   Core: the project document
   Framework-agnostic. Knows a project has meta, items, gates,
   metrics and a card -- not what any of them mean.
   ============================================================ */
const blankMeta = ()=>({solution:"",org:"",developer:"",sourcing:"",sponsor:"",reviewers:"",riskTier:"",reviewCadence:"",startDate:"",scope:"",chaiUseCase:""});
function blankProject(name){
  const now=new Date().toISOString();
  return {meta:{...blankMeta(),solution:name||""}, ...frameworkBlank(), metrics:[], card:{},
    access: ME.id ? {owners:[ME.id], writers:[], readers:[]} : blankAccess(),
    archived:false, createdAt:now, createdBy:ME.id||null, updatedAt:now, updatedBy:ME.id||null, cardUpdatedAt:null};
}
function normalize(p){
  p.meta=Object.assign(blankMeta(),p.meta||{});
  p.metrics=Array.isArray(p.metrics)?p.metrics:[]; p.card=p.card||{};
  p.access=Object.assign(blankAccess(), p.access||{});
  frameworkNormalize(p); return p;
}
const cardValOf = (p,k) => ((p.card||{})[k]||"").trim() || (k==="name"?(p.meta.solution||"").trim():"") || (k==="developer"?(p.meta.developer||"").trim():"");

/* What a checkpoint decision means, whatever a framework calls it. A framework
   classes each of its options; the engine reads only the class, so "Proceed" and
   "Continue" both advance and "Stop" and "Retire" both end, with no wording
   compared anywhere (#168). */
const GateClass = Object.freeze({
  GO: "go",                    // approved: advances the lifecycle
  CONDITIONAL: "conditional",  // approved with conditions: advances, conditions owed
  REVISE: "revise",            // sent back: does not advance
  STOP: "stop",                // ended before going live
  RETIRE: "retire",            // taken out of service after going live
});
const ADVANCES = Object.freeze(new Set([GateClass.GO, GateClass.CONDITIONAL]));

const STATUS = {met:"Met",partial:"Partial",notmet:"Not met",na:"N/A"};   // English: exports
const STATUS_KEY = Object.freeze({met:"status.met",partial:"status.partial",notmet:"status.notmet",na:"status.na"});
const VAL = {met:1,partial:.5,notmet:0};

// Generic: scores any list of {id} against any items map. Framework rules
// decide WHICH list to pass; this does not know.
function scoreOf(list, items){
  items=items||S.items; let sum=0,n=0,answered=0;
  list.forEach(it=>{ const st=(items[it.id]||{}).status; if(st) answered++; if(st==="na") return; n++; sum+=VAL[st]||0; });
  return {pct:n?Math.round(sum/n*100):0,answered,total:list.length,applicable:n};
}
