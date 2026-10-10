/* ============================================================
   Core: the project document
   Framework-agnostic. Knows a project has meta, items, gates,
   metrics and a card -- not what any of them mean.
   ============================================================ */
const blankMeta = ()=>({solution:"",org:"",developer:"",sourcing:"",sponsor:"",reviewers:"",riskTier:"",reviewCadence:"",startDate:"",scope:"",chaiUseCase:""});
function blankProject(name){
  const now=new Date().toISOString();
  // A build of other frameworks stamps every record it makes with its primary, and
  // opens and imports only records stamped so (isOwnRecord, R-67); a record with
  // none is the published build's. The server does not check the stamp yet.
  const stamp = BUILD.published ? {} : {framework: {id: BUILD.primary}};
  return {meta:{...blankMeta(),solution:name||"",...stamp}, ...frameworkBlank(), metrics:[], card:{},
    access: ME.id ? {owners:[ME.id], writers:[], readers:[]} : blankAccess(),
    archived:false, createdAt:now, createdBy:ME.id||null, updatedAt:now, updatedBy:ME.id||null, cardUpdatedAt:null};
}
function normalize(p){
  p.meta=Object.assign(blankMeta(),p.meta||{});
  p.metrics=Array.isArray(p.metrics)?p.metrics:[]; p.card=p.card||{};
  p.access=Object.assign(blankAccess(), p.access||{});
  frameworkNormalize(p); return p;
}
/* The record as the store holds it, kept beside the copy normalize() fills in.

   A record an older dashboard wrote lacks fields normalize() now fills
   (meta.chaiUseCase, card, access, a checkpoint), so the filled-in copy is not the
   record. The fingerprint is the stored record's: it is what the server hashes into
   each revision, and what an export's _state is, so the setup page, the export and
   the version history give the same record one fingerprint. Hashing the filled-in
   copy gave an older record two (#177). The stored record moves with every patch
   the store is sent (queuePatch), so it stays what the store will hold. */
const STORED = new WeakMap();
function normalizeStored(raw){ const p = normalize(clone(raw)); STORED.set(p, raw); return p; }
const storedRecord = p => (p && STORED.get(p)) || p;
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

/* A status's meaning, its label and its weight belong to the framework that
   defines it (app/frameworks/<id>/framework.json, the engine's StatusClass). */
