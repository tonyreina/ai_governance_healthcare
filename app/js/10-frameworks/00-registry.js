/* ============================================================
   Framework registry
   A framework is a self-contained checklist: its own items, its own
   views, its own progress. Frameworks never read each other, and the
   app shell never names one. Adding a third means adding a directory
   under app/js/10-frameworks/ that calls registerFramework().

   The contract:
     id        string, stable, used in data keys and the DOM
     label     short display name
     enabled   (p) => bool    is it switched on for this project?
     views     (p) => [view]  rail entries, in order
     render    (view, p) => html
     blank     () => object   extra keys merged into a new project
     normalize (p) => void    repair shape on load; must be idempotent

   A view is {id, kind, label, num, meta, cls, sep}. The shell renders
   the rail from these fields alone; `kind` is the framework's own
   business and is passed back to render() untouched.
   ============================================================ */
const FRAMEWORKS = [];

function registerFramework(f) {
  if (FRAMEWORKS.some(x => x.id === f.id)) throw new Error(`framework ${f.id} already registered`);
  FRAMEWORKS.push(f);
  return f;
}

const frameworkById = id => FRAMEWORKS.find(f => f.id === id);

/* Frameworks switched on for a project. CHAI is always on: it is the
   spine the compliance status and the dashboard are computed from.
   Others are opt-in per project. */
function activeFrameworks(p) {
  const proj = p || S;
  return FRAMEWORKS.filter(f => { try { return f.enabled(proj); } catch (e) { return false; } });
}

/* Every rail entry, in framework registration order, each tagged with
   the framework that owns it so the shell can route back without a
   lookup table. */
function activeViews(p) {
  const proj = p || S;
  return activeFrameworks(proj).flatMap(f =>
    (f.views(proj) || []).map(v => ({ ...v, fw: f }))
  );
}

const viewById = (id, p) => activeViews(p).find(v => v.id === id);

/* Extra top-level keys a new project needs. Existing projects without
   them stay valid: every framework's normalize() has to cope with its
   own keys being absent, which is what keeps old exports importable. */
function frameworkBlank() {
  return FRAMEWORKS.reduce((acc, f) => Object.assign(acc, f.blank ? f.blank() : {}), {});
}

function frameworkNormalize(p) {
  FRAMEWORKS.forEach(f => { if (f.normalize) f.normalize(p); });
  return p;
}
