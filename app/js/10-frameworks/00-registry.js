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
     primary   true on exactly one framework per build: the one the
               portfolio's status, phase, flags, score and report come from
     spine     the primary's answers to those questions (below)
     describePath (parts) => string|null   the change history's words for a
               path in this framework's own keys, or null if not its own
     statusName (value) => string|undefined   English name of a stored status

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

/* The spine (#168): what the shell asks of the primary framework, and never of
   CHAI or OPTICA by name. The shell may show a portfolio, a report and exports
   only through these, so a build with a different framework needs no change
   outside its own directory.

     items()            every criterion: {id, text, category, section}
     itemLabel(it)      a criterion as the reader sees it
     sections()         [{id, n, title, items}] in order
     sectionLabel(s)
     categories()       [{id, name}]: what a score is broken down by
     categoryLabel(id)
     gates()            [{id, after, title}] in order
     gateLabel(id), gateQuestion(id), optionLabel(option)
     gateRecord(p, id)  {decision, by, date, rationale, signedBy, ...}
     decisionClass(d)   a GateClass member, or null
     answers(p)         {itemId: {status, evidence, owner, due, refs}}
     phase(p), flags(p), status(p), nextReview(p)
     score(p, items?)   {pct, answered, total, applicable}
     reportBody(names)  the report's HTML (screen, HTML export, PDF)
     markdownExtras(ctx) lines appended after the open gaps (CHAI: the model card)
     jsonExtras(p)      keys merged into the JSON export (CHAI: model_card)
     samples            optional {count(), loadAll(), fill(p) => patch}: worked
                        examples for the portfolio and for one project */
function primaryFramework() {
  const primary = FRAMEWORKS.filter(f => f.primary);
  if (primary.length !== 1) throw new Error(`a build needs exactly one primary framework, found ${primary.length}`);
  return primary[0];
}
const spine = () => primaryFramework().spine;

/* The change history's words for a path, from whichever framework owns it. */
function frameworkDescribePath(parts) {
  for (const f of FRAMEWORKS) {
    const out = f.describePath ? f.describePath(parts) : null;
    if (out) return out;
  }
  return null;
}
const frameworkStatusName = value => {
  for (const f of FRAMEWORKS) { const n = f.statusName ? f.statusName(value) : undefined; if (n) return n; }
  return undefined;
};

/* Frameworks switched on for a project. The primary is always on: it is
   the spine the status and the portfolio are computed from (CHAI in the
   default build). Others may be opt-in per project. */
function activeFrameworks(p) {
  const proj = p || S;
  return FRAMEWORKS.filter(f => { try { return f.enabled(proj); } catch (e) { return false; } });
}

/* Every rail entry, in framework registration order, each tagged with
   the framework that owns it so the shell can route back without a
   lookup table. */
function activeViews(p) {
  const proj = p || S;
  const all = activeFrameworks(proj).flatMap(f =>
    (f.views(proj) || []).map(v => ({ ...v, fw: f }))
  );
  // A view may declare `order: "end"` to sit after everything else, whichever
  // framework contributed it. Used by reference views -- the changelog is not
  // a step in the review and should not interrupt the numbered sequence.
  return [...all.filter(v => v.order !== "end"), ...all.filter(v => v.order === "end")];
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

/* What a reader sees for a phase, a status or a flag. The objects keep their English
   `label`/`text` for exports (which stay English); `msg` names the catalog entry, and
   a date parameter is formatted in the reader's language here. */
const phaseLabel = ph => t(ph.msg);
const statusLabel = st => t(st.msg);
function flagText(f){
  if(!f.msg) return f.text;
  const [key, params] = f.msg;
  const p = Object.assign({}, params);
  if(p.date) p.date = fmtDay(p.date);
  if(p.gateKey){ p.gate = spine().gateLabel(p.gateKey); delete p.gateKey; }
  return t(key, p);
}

/* The side panel (CHAI: the applied model card). A framework without one hides
   the header button that opens it. */
const hasPanel = () => !!primaryFramework().panel;
function renderPanel(){ const f = primaryFramework(); if (f.panel) f.panel(); }

/* A click or a change offered to the active frameworks first, for the controls
   that are a framework's own (CHAI's metric buttons and use-case picker). */
function frameworkClick(btn) {
  for (const f of activeFrameworks(S)) if (f.onClick && f.onClick(btn)) return true;
  return false;
}
function frameworkChange(el) {
  if (!S) return false;
  for (const f of activeFrameworks(S)) if (f.onChange && f.onChange(el)) return true;
  return false;
}
