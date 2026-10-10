/* ============================================================
   Every framework in this build, registered from its definition (#168)

   Runs after every framework's own code, so a plug-in's extras (CHAI's
   model card view, its report section, its samples) are in place. A
   framework with no code of its own -- OPTICA, or a developer's -- needs
   nothing but its definition.

   Extras a framework's code may give (FRAMEWORK_EXTRAS[id]):
     views(p)         rail entries after the sections and gates (CHAI: the card)
     render(v)        markup for those views
     reportSections() markup in the report, before the history
     markdownExtras(ctx), jsonExtras(p), samples, panel(), onClick(btn),
     onChange(el), describePath(parts)   as in 00-registry.js
   ============================================================ */

const ITEM_FIELD = Object.freeze({ status: "status", evidence: "evidence", owner: "owner", due: "due date" });
const GATE_FIELD = Object.freeze({ decision: "decision", by: "decided by", date: "decision date",
  rationale: "rationale", conditions: "conditions" });

/* Switching a supplement on or off for the open project. Off keeps every answer:
   it only hides the views, so a team that pauses that review loses nothing. */
function setFrameworkEnabled(id, on) {
  if (RO || !S) return;
  const F = FACADES[id];
  if (!S[id]) S[id] = { [SupplementKey.ENABLED]: false, [SupplementKey.ANSWERS]: {} };
  edit(`${id}.${SupplementKey.ENABLED}`, !!on);
  writeLog(CUR, `${on ? "Enabled" : "Disabled"} the ${F.def.title || F.def.name}`);
  const v = viewById(UI.view);
  if (!on && (!v || v.fw.id === id)) go("setup");
  else renderProject(false);
}

/* Worked examples written as data in a definition (`samples`), for a framework with
   no code of its own: each a project with some answers and dated decisions. */
function dataSamples(F) {
  const specs = F.def.samples || [];
  if (!specs.length) return undefined;
  const build = (spec, now) => {
    const d = n => ymd(addDays(now, n)), iso = n => addDays(now, n).toISOString();
    const p = blankProject(spec.name);
    Object.assign(p.meta, spec.meta || {});
    Object.entries(spec.answers || {}).forEach(([itemId, status]) => {
      p.items[itemId] = {status, evidence: "", owner: "", due: ""};
    });
    Object.entries(spec.decisions || {}).forEach(([gateId, [decision, day, rationale]]) => {
      p.gates[gateId] = {decision, by: spec.by || "", date: d(day), rationale: rationale || "",
        signedBy: ME.id || null, signedAt: iso(day)};
    });
    return p;
  };
  return {
    count: () => specs.length,
    loadAll: async () => {
      const now = new Date();
      // Only this build's records: a hidden record of another framework with a
      // sample's name must not stop the sample being added.
      const have = new Set([...PROJECTS.values()].filter(isOwnRecord).map(p => (p.meta.solution || "").trim()));
      const missing = specs.filter(spec => !have.has(spec.name));
      if (!missing.length) { toast(t("toast.samplesHere")); return; }
      for (const spec of missing) await createProject(build(spec, now), "Sample project added");
      toast(t("toast.samplesAdded", {count: missing.length}));
    },
    fill: p => {
      const filled = build(specs[0], new Date());
      p.items = filled.items; p.gates = filled.gates;
      return {items: clone(p.items), gates: clone(p.gates)};
    },
  };
}

function registerDefinition(id) {
  const F = FACADES[id];
  const fw = F.fw, def = F.def, extras = FRAMEWORK_EXTRAS[id] || {};
  F.extras = extras;
  const meta = (list, p) => () => { const c = fw.score(list, F.answers(p)); return `${c.answered}/${c.total}`; };
  const metaCls = (list, p) => () => { const c = fw.score(list, F.answers(p)); return c.answered === c.total ? "done" : ""; };

  function views(p) {
    const out = [];
    if (!F.primary) {
      out.push({
        id, kind: ViewKind.OVERVIEW, label: t(F.slot(UiSlot.RAIL_OVERVIEW), {name: def.name}), glyph: "◇", sep: "before",
        meta: meta(fw.items, p), metaCls: metaCls(fw.items, p), short: def.name,
      });
    }
    fw.sections.forEach(s => {
      out.push({
        id: F.vp + s.id, kind: ViewKind.SECTION, section: s.id, label: F.sectionTitle(s), num: s.n,
        short: F.hasSlot(UiSlot.RAIL_SHORT) ? t(F.slot(UiSlot.RAIL_SHORT), {n: s.n}) : `${def.name} ${s.n}`,
        meta: meta(s.items, p), metaCls: metaCls(s.items, p),
      });
      fw.gates.filter(g => g.after === s.id).forEach(g => {
        out.push({
          id: "g" + g.id, kind: ViewKind.GATE, gate: g.id, label: F.gateTitle(g.id), cls: "gate",
          numHTML: '<span class="diamond" aria-hidden="true"></span>',
          meta: () => { const d = ((p.gates || {})[g.id] || {}).decision || ""; return d ? esc(F.shortDecision(d)) : esc(t("dash.gateOpen")); },
          metaCls: () => { const d = ((p.gates || {})[g.id] || {}).decision || ""; return !d ? "" : (fw.advances(d, g.id) ? "done" : "warn"); },
        });
      });
    });
    if (extras.views) out.push(...extras.views(p));
    if (F.primary) out.push({ id: REPORT_VIEW, kind: ViewKind.REPORT, label: t("rail.report"), glyph: "✓" });
    return out;
  }

  function render(v) {
    if (!F.enabled(S)) return renderOff(F);
    switch (v.kind) {
      case ViewKind.SECTION: return renderSection(F, v.section);
      case ViewKind.GATE: return renderGate(F, v.gate);
      case ViewKind.OVERVIEW: return renderOverview(F);
      case ViewKind.REPORT: return renderReport(F);
      default: return extras.render ? extras.render(v) : "";
    }
  }

  function describePath(parts) {
    if (F.primary && parts[0] === RecordKey.ITEMS) {
      const item = fw.items.find(i => i.id === parts[1]);
      const what = parts[2] === Field.REFS ? "evidence reference"
        : (Object.hasOwn(ITEM_FIELD, parts[2]) ? ITEM_FIELD[parts[2]] : parts[2]);
      return item ? `${what} of “${item.text}”` : `${what} of criterion ${parts[1]}`;
    }
    if (F.primary && parts[0] === RecordKey.GATES) {
      const gate = fw.gateById[parts[1]];
      const what = Object.hasOwn(GATE_FIELD, parts[2]) ? GATE_FIELD[parts[2]] : parts[2];
      return gate ? `${what} for ${gate.title}` : `${what} for checkpoint ${parts[1]}`;
    }
    if (!F.primary && parts[0] === id && parts[1] === SupplementKey.ANSWERS) {
      const item = fw.items.find(i => i.id === parts[2]);
      const reason = F.reason && parts[3] === F.reason.reasonField ? F.reason.reasonLabel : null;
      const what = parts[3] === Field.REFS ? "evidence reference"
        : reason || (Object.hasOwn(ITEM_FIELD, parts[3]) ? ITEM_FIELD[parts[3]] : parts[3]);
      return item ? `${def.name} ${item.num || item.id}: ${what}` : `${def.name} ${parts[2]}: ${what}`;
    }
    return extras.describePath ? extras.describePath(parts) : null;
  }

  const spine = F.primary ? {
    items: () => fw.items,
    itemLabel: it => F.itemText(it),
    sections: () => fw.sections,
    sectionLabel: s => F.sectionTitle(s),
    categories: () => def.categories || [],
    categoryLabel: k => F.categoryLabel(k),
    gates: () => fw.gates,
    gateLabel: k => F.gateTitle(k),
    gateQuestion: k => F.gateQuestion(k),
    optionLabel: o => F.optionLabel(o),
    gateRecord: (p, k) => (p.gates || {})[k] || {},
    decisionClass: (d, gateId) => fw.decisionClass(d, gateId),
    // A sentence's catalog key for this framework: its own, or the engine's.
    uiKey: slot => F.slot(slot),
    name: def.name,
    statusKnown: v => fw.classOf(v) !== null,
    statusLabel: v => F.statusLabel(v),
    answers: p => F.answers(p),
    phase: p => fw.phase(p),
    isLive: ph => fw.isLive(ph),
    flags: p => fw.flags(p),
    status: p => fw.status(p),
    nextReview: p => fw.nextReview(p),
    reviewGateId: () => (fw.review || {}).gate || null,
    score: (p, list) => fw.score(list || fw.items, F.answers(p)),
    reportBody: names => reportBody(F, names),
    reportViewId: REPORT_VIEW,
    fileSuffix: (def.export || {}).fileSuffix || `${id}-review`,
    schemaId: (def.export || {}).schemaId || `${id}-review/1`,
    markdownExtras: extras.markdownExtras,
    jsonExtras: extras.jsonExtras,
    samples: extras.samples || dataSamples(F),
  } : undefined;

  registerFramework({
    id, label: def.name, primary: F.primary, spine, def, facade: F,
    enabled: p => F.enabled(p),
    blank: () => F.primary
      ? { [RecordKey.ITEMS]: {}, [RecordKey.GATES]: Object.fromEntries(fw.gates.map(g => [g.id, {}])) }
      : (def.optIn ? {} : { [id]: { [SupplementKey.ANSWERS]: {} } }),
    normalize(p) {
      if (F.primary) {
        p.items = p.items || {};
        p.gates = Object.assign(Object.fromEntries(fw.gates.map(g => [g.id, {}])), p.gates || {});
        return;
      }
      if (!p[id]) return;
      if (def.optIn) p[id][SupplementKey.ENABLED] = !!p[id][SupplementKey.ENABLED];
      p[id][SupplementKey.ANSWERS] = p[id][SupplementKey.ANSWERS] || {};
    },
    views, render, describePath,
    statusName: v => F.statusName(v),
    toggle: def.optIn ? on => setFrameworkEnabled(id, on) : undefined,
    optIn: !!def.optIn,
    panel: extras.panel, onClick: extras.onClick, onChange: extras.onChange,
  });
}

const FACADES = Object.fromEntries(Object.keys(FRAMEWORK_DEFS).map(id => [id, frameworkFacade(id)]));
Object.keys(FRAMEWORK_DEFS).forEach(registerDefinition);
