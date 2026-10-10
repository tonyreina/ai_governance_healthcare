/* ============================================================
   Core: find text anywhere in a project (#57)
   "Where does this person, vendor or phrase appear?" without opening every
   project. Looks through every string in a project's current document; a
   person's name also finds the ids they are stored under, because access
   lists and sign-offs hold ids. Only what this browser already holds: the
   current version of each project the viewer can open. Earlier revisions and
   the audit log are not here, and the UI says so.
   ============================================================ */
const SEARCH_LABEL = Object.freeze({
  id: "project id", createdBy: "created by", updatedBy: "last changed by",
  cardUpdatedBy: "model card changed by",
});
function searchLabel(path){
  const top = path.split(".")[0];
  return SEARCH_LABEL[top] || describePath(path);
}
/* The ids whose known name contains the query: "Pat" finds pat@hosp.org. */
function idsNamed(q){
  return Object.entries(NAMES)
    .filter(([id, name]) => name && id !== ME.id && name.toLowerCase().includes(q))
    .map(([id]) => id.toLowerCase());
}
/* Where in this project the text appears, as labels a reader recognizes. */
/* The record's framework stamp is the build's, not anything a person wrote: a
   search for part of the framework's id must not match every record (#168). */
const NOT_SEARCHED = new Set(["meta.framework"]);
function textHits(p, query){
  const q = String(query || "").trim().toLowerCase();
  if(!q || !p) return [];
  const terms = [q, ...idsNamed(q)];
  const hits = [];
  const walk = (v, path) => {
    if(typeof v === "string"){
      const s = v.toLowerCase();
      if(terms.some(t => s.includes(t))){
        const label = searchLabel(path);
        if(!hits.includes(label)) hits.push(label);
      }
    } else if(Array.isArray(v)){
      v.forEach(x => walk(x, path));          // a list's position is not a place a reader knows
    } else if(v && typeof v === "object"){
      if(NOT_SEARCHED.has(path)) return;
      for(const k of Object.keys(v)) if(safeKey(k)) walk(v[k], path ? `${path}.${k}` : k);
    }
  };
  walk(p, "");
  return hits;
}
