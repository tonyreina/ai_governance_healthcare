/* ============================================================
   The framework engine (#168)

   Turns a framework definition (app/frameworks/<id>/framework.json,
   embedded by the build as FRAMEWORK_DEFS) into the answers the shell
   asks of a framework: its items, a status's class, a score, the
   phase a project is in, its flags, its status and its next review.

   Every word a definition uses that the engine acts on is a member of
   an enum below, validated at build by scripts/check_framework.py, so
   the engine never compares a definition's wording: "Proceed" and
   "Continue" both advance because both are class GO, and a status
   counts as done because its class is DONE.
   ============================================================ */

/* What a stored answer means, whatever a framework calls it. */
const StatusClass = Object.freeze({
  DONE: "done",          // met, answered: full credit
  PARTIAL: "partial",    // half credit; an open gap in reports
  OPEN: "open",          // not met, outstanding: no credit; an open gap
  DECLINED: "declined",  // a reasoned "we chose not to": answered, no credit, out of the denominator
  EXCLUDED: "excluded",  // not applicable: out of the denominator
});
const STATUS_WEIGHT = Object.freeze({
  [StatusClass.DONE]: 1, [StatusClass.PARTIAL]: 0.5, [StatusClass.OPEN]: 0,
});
/* Statuses whose due date no longer matters (an action that is done or not
   applicable is not overdue; a declined one still is, as today). */
const SETTLED = Object.freeze(new Set([StatusClass.DONE, StatusClass.EXCLUDED]));

/* Where a phase sits in a lifecycle. Flags and the review clock key on the role,
   never on a phase's own name. */
const PhaseRole = Object.freeze({
  PLANNING: "planning", BUILD: "build", PILOT: "pilot", LIVE: "live",
});
/* The phase key every framework shares for a project that has ended. */
const PhaseKey = Object.freeze({ RETIRED: "retired" });

const Severity = Object.freeze({ RED: "red", AMBER: "amber" });
const StatusKey = Object.freeze({ RED: "red", AMBER: "amber", GREEN: "green", RETIRED: "retired" });

/* The flag rules a definition may switch on. Each rule's English text (exports)
   and catalog key (screens) are the engine's, not the definition's. */
const FlagRule = Object.freeze({
  PAST_DUE: "pastDue",
  OPEN_WHEN_LIVE: "openWhenLive",
  REVIEW: "review",
  REVISE_AT_REVIEW: "reviseAtReview",
  APPROVAL_WITHOUT_RATIONALE: "approvalWithoutRationale",
  IDLE: "idle",
});

/* Code plug-ins a definition names (the CHAI model card, its metrics). A plug-in
   contributes flags at the point the definition places it, so the order of the
   flag list is the definition's. */
const PLUGINS = new Map();
function registerPlugin(name, hooks) {
  if (PLUGINS.has(name)) throw new Error(`plugin ${name} already registered`);
  PLUGINS.set(name, hooks);
  return hooks;
}

/* A framework, from its definition. */
function engineFramework(def) {
  const sections = def.sections.map(s => ({ ...s, items: s.items.map(it => ({ ...it })) }));
  sections.forEach(s => s.items.forEach(it => {
    if (it.category === undefined && s.category !== undefined) it.category = s.category;
  }));
  const items = sections.flatMap(s => s.items.map(it => ({ ...it, section: s })));
  const statusClass = Object.fromEntries((def.statuses || []).map(st => [st.value, st.class]));
  const optionClass = {};
  const gateOptionClass = {};
  (def.gates || []).forEach(g => {
    gateOptionClass[g.id] = Object.fromEntries(g.options.map(o => [o.value, o.class]));
    g.options.forEach(o => { optionClass[o.value] = o.class; });
  });
  const gates = (def.gates || []).map(g => ({ ...g }));
  const gateById = Object.fromEntries(gates.map(g => [g.id, g]));
  const phases = def.phases || [];
  const sectionN = Object.fromEntries(sections.map(s => [s.id, s.n]));
  const review = def.review || null;
  // A flag's catalog key: the definition's own, or the engine's neutral one (UiSlot).
  const slotKey = s => (def.ui && Object.hasOwn(def.ui, s)) ? def.ui[s] : DEFAULT_SLOT[s];
  // English nouns for the flags' export text (screens use catalog keys).
  const [itemOne, itemMany] = (def.nouns || {}).item || ["item", "items"];

  const classOf = value => (value && Object.hasOwn(statusClass, value)) ? statusClass[value] : null;
  /* A decision's class, or null when none is recorded. A stored value this build
     does not know (an edited import, a renamed option) has no class, so it neither
     advances nor ends anything. */
  /* By the checkpoint it was recorded at: a value that is not one of that gate's
     options has no class there (D = "Stop" ends nothing; the server's retirement
     rules are per checkpoint too). Without a gate, by value alone (one class per
     value, check-framework). */
  const decisionClass = (d, gateId) => {
    if (!d) return null;
    if (gateId !== undefined) {
      const at = gateOptionClass[gateId] || {};
      return Object.hasOwn(at, d) ? at[d] : null;
    }
    return Object.hasOwn(optionClass, d) ? optionClass[d] : null;
  };
  const advances = (d, gateId) => ADVANCES.has(decisionClass(d, gateId));
  const decision = (p, k) => ((p.gates || {})[k] || {}).decision || "";

  /* Score over any list of items against a project's answers. Declined counts as
     answered but adds nothing and leaves the denominator; excluded leaves it too. */
  function score(list, answers) {
    let sum = 0, n = 0, answered = 0, declined = 0;
    list.forEach(it => {
      const st = (answers[it.id] || {}).status;
      if (st) answered++;
      const c = classOf(st);
      if (c === StatusClass.DECLINED) { declined++; return; }
      if (c === StatusClass.EXCLUDED) return;
      n++; sum += Object.hasOwn(STATUS_WEIGHT, c) ? STATUS_WEIGHT[c] : 0;
    });
    return { pct: n ? Math.round(sum / n * 100) : 0, answered, total: list.length, applicable: n, declined };
  }

  /* Items with no answer, or an open one, in every section up to and including
     `sectionId`: what an approval at a gate after that section leaves open. */
  function gapsUpTo(p, sectionId) {
    const idx = sections.findIndex(s => s.id === sectionId);
    const answers = p.items || {};
    return sections.slice(0, idx + 1).flatMap(s => s.items
      .filter(it => { const st = (answers[it.id] || {}).status; return !st || classOf(st) === StatusClass.OPEN; })
      .map(it => ({ ...it, section: s })));
  }

  function phase(p) {
    // `label` is the English an export records; `msg` is the catalog key a reader sees.
    const classes = gates.map(g => decisionClass(decision(p, g.id), g.id));
    if (classes.includes(GateClass.STOP)) return { key: PhaseKey.RETIRED, label: "Stopped", msg: "phase.stopped" };
    if (classes.includes(GateClass.RETIRE)) return { key: PhaseKey.RETIRED, label: "Retired", msg: "phase.retired" };
    for (let i = phases.length - 1; i >= 0; i--) {
      const ph = phases[i];
      if (i === 0 || advances(decision(p, ph.reachedBy), ph.reachedBy)) {
        return { key: ph.key, label: ph.label, stage: sectionN[ph.section], msg: ph.msg, role: ph.role,
          tfKey: `${def.id}.phase.${ph.key}` };
      }
    }
    return { key: "", label: "", msg: "", role: null };
  }
  const isLive = ph => ph.role === PhaseRole.LIVE;
  const isPilot = ph => ph.role === PhaseRole.PILOT;

  function cadenceMonths(p) {
    const n = parseInt(p.meta.reviewCadence, 10);
    if (n > 0) return n;
    const byTier = (review && review.monthsByRiskTier) || {};
    return Object.hasOwn(byTier, p.meta.riskTier) ? byTier[p.meta.riskTier] : review.defaultMonths;
  }
  /* The next periodic review: only while live. The clock starts at the first
     anchor gate that has a decision and a date, else at the last anchor's date. */
  function nextReview(p) {
    if (!review || !isLive(phase(p))) return null;
    const anchors = review.anchors;
    let base = null;
    for (let i = 0; i < anchors.length && !base; i++) {
      const g = (p.gates || {})[anchors[i]] || {};
      const last = i === anchors.length - 1;
      if (last || g.decision) base = parseDay(g.date || "");
    }
    if (!base) return null;
    return ymd(addMonths(base, cadenceMonths(p)));
  }
  /* The latest dated approval, by gate order: what the model card must be newer than. */
  function latestGo(p) {
    let best = null;
    gates.forEach(gate => {
      const g = (p.gates || {})[gate.id] || {};
      if (advances(g.decision, gate.id)) { const d = parseDay(g.date); if (d && (!best || d > best.d)) best = { k: gate.id, d }; }
    });
    return best;
  }

  const fw = {
    def, sections, items, gates, gateById, phases, review,
    classOf, decisionClass, advances, decision, score, gapsUpTo, phase, isLive, isPilot,
    cadenceMonths, nextReview, latestGo,
  };

  /* Red = out of compliance, amber = needs update. In the definition's order, then
     red before amber (stable). */
  fw.flags = function flags(p) {
    const F = []; const ph = phase(p); const today = parseDay(TODAY());
    if (ph.key === PhaseKey.RETIRED) return F;
    const live = isLive(ph), piloting = isPilot(ph);
    const answers = p.items || {};
    const ctx = { p, phase: ph, live, piloting, today, fw };
    for (const entry of def.flags || []) {
      if (entry.plugin) {
        const hooks = PLUGINS.get(entry.plugin);
        if (hooks && hooks.flags) F.push(...hooks.flags(ctx));
        continue;
      }
      switch (entry.rule) {
        case FlagRule.PAST_DUE: {
          const overdue = items.filter(it => { const d = answers[it.id] || {}; const due = parseDay(d.due); return due && due < today && !SETTLED.has(classOf(d.status)); });
          if (overdue.length) F.push({ sev: (live || piloting) ? Severity.RED : Severity.AMBER, text: `${overdue.length} action${overdue.length > 1 ? "s" : ""} past due`, msg: ["flag.pastDue", { count: overdue.length }] });
          break;
        }
        case FlagRule.OPEN_WHEN_LIVE: {
          if (!live) break;
          const open = items.filter(it => classOf((answers[it.id] || {}).status) === StatusClass.OPEN).length;
          if (open) F.push({ sev: Severity.RED, text: `Live with ${open} ${open > 1 ? itemMany : itemOne} not met`, msg: [slotKey(UiSlot.FLAG_LIVE_OPEN), { count: open }] });
          break;
        }
        case FlagRule.REVIEW: {
          if (!live) break;
          const nr = nextReview(p);
          if (!nr) F.push({ sev: Severity.RED, text: `Live with no deployment date recorded at ${gateById[entry.gate].title}`, msg: [slotKey(UiSlot.FLAG_NO_DEPLOY_DATE), { gateKey: entry.gate }] });
          else {
            const left = daysBetween(today, parseDay(nr));
            if (left < 0) F.push({ sev: Severity.RED, text: `Periodic review overdue since ${fmtDay(nr)}`, msg: ["flag.reviewOverdue", { date: nr }] });
            else if (left <= review.dueSoonDays) F.push({ sev: Severity.AMBER, text: `Periodic review due ${fmtDay(nr)}`, msg: ["flag.reviewDue", { date: nr }] });
          }
          break;
        }
        case FlagRule.REVISE_AT_REVIEW: {
          if (live && decisionClass(decision(p, entry.gate), entry.gate) === GateClass.REVISE) F.push({ sev: Severity.AMBER, text: "Last review asked for retraining or revision", msg: ["flag.retrain", {}] });
          break;
        }
        case FlagRule.APPROVAL_WITHOUT_RATIONALE: {
          gates.forEach(gate => {
            const g = (p.gates || {})[gate.id] || {};
            if (!advances(g.decision, gate.id) || (g.rationale || "").trim()) return;
            if (decisionClass(g.decision, gate.id) === GateClass.CONDITIONAL) F.push({ sev: Severity.AMBER, text: `${gate.title}: conditional approval with no conditions recorded`, msg: ["flag.noConditions", { gateKey: gate.id }] });
            else if (gapsUpTo(p, gate.after).length) F.push({ sev: Severity.AMBER, text: `${gate.title}: approved with open ${itemMany} and no rationale`, msg: [slotKey(UiSlot.FLAG_NO_RATIONALE), { gateKey: gate.id }] });
          });
          break;
        }
        case FlagRule.IDLE: {
          if (!live && p.updatedAt) { const idle = daysBetween(new Date(p.updatedAt), new Date()); if (idle > entry.days) F.push({ sev: Severity.AMBER, text: `No activity in ${idle} days`, msg: ["flag.idle", { count: idle }] }); }
          break;
        }
        default: assertNever(entry.rule);
      }
    }
    return F.sort((a, b) => (a.sev === Severity.RED ? 0 : 1) - (b.sev === Severity.RED ? 0 : 1));
  };

  fw.status = function status(p) {
    const ph = phase(p);
    if (ph.key === PhaseKey.RETIRED) return { key: StatusKey.RETIRED, label: ph.label, msg: ph.msg };
    const f = fw.flags(p);
    if (f.some(x => x.sev === Severity.RED)) return { key: StatusKey.RED, label: "Out of compliance", msg: "status.red" };
    if (f.length) return { key: StatusKey.AMBER, label: "Needs update", msg: "status.amber" };
    return { key: StatusKey.GREEN, label: "On track", msg: "status.green" };
  };

  return fw;
}

/* The engines for this build's frameworks, by id. */
const ENGINES = Object.freeze(Object.fromEntries(
  Object.entries(FRAMEWORK_DEFS).map(([id, def]) => [id, engineFramework(def)])
));
