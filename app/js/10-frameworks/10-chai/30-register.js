/* ============================================================
   CHAI: registration
   Declares CHAI to the shell. This is the only file that has to
   change when a CHAI screen is added or reordered.

   CHAI is the primary framework of the default build: always on, it
   owns the project document's `items` and `gates` keys, the status on
   the portfolio (through its spine, 25-spine.js), and the applied model
   card. There is ONE primary per build, because the portfolio needs one
   status and mixing two frameworks' judgments into one number would be
   meaningless (docs/crosswalk.md). Another framework can be the primary
   in a build of its own (#168).
   ============================================================ */
registerFramework({
  id: "chai",
  label: "CHAI",
  primary: true,
  spine: CHAI_SPINE,
  describePath: chaiDescribePath,
  statusName: v => Object.hasOwn(STATUS, v) ? STATUS[v] : undefined,
  panel: () => renderLabel(),
  onClick: btn => chaiClick(btn),
  onChange: el => chaiChange(el),

  enabled: () => true,

  blank: () => ({ items: {}, gates: { A: {}, B: {}, C: {}, D: {} } }),

  normalize(p) {
    p.items = p.items || {};
    p.gates = Object.assign({ A: {}, B: {}, C: {}, D: {} }, p.gates || {});
  },

  views(p) {
    const out = [];
    STAGES.forEach(s => {
      out.push({
        id: s.id, kind: "stage", label: stageTitle(s), num: s.n, short: t("rail.stageShort", {n: s.n}),
        meta: () => { const c = scoreOf(s.items, p.items); return `${c.answered}/${c.total}`; },
        metaCls: () => { const c = scoreOf(s.items, p.items); return c.answered === c.total ? "done" : ""; },
      });
      Object.entries(GATES).filter(([, g]) => g.after === s.id).forEach(([key, g]) => {
        out.push({
          id: "g" + key, kind: "gate", gate: key, label: gateTitle(key), cls: "gate",
          numHTML: '<span class="diamond" aria-hidden="true"></span>',
          meta: () => { const d = (p.gates[key] || {}).decision || ""; return d ? esc(shortDecision(d)) : esc(t("dash.gateOpen")); },
          metaCls: () => { const d = (p.gates[key] || {}).decision || ""; return !d ? "" : (isGo(d) ? "done" : "warn"); },
        });
      });
    });
    out.push({
      id: "card", kind: "card", label: t("card.title"), glyph: "≡", sep: "before",
      meta: () => `${CARD_FIELDS.filter(k => cardValOf(p, k)).length}/${CARD_FIELDS.length}`,
    });
    out.push({ id: "report", kind: "report", label: t("rail.report"), glyph: "✓" });
    return out;
  },

  render(v) {
    if (v.kind === "stage") return renderStage(STAGES.find(s => s.id === v.id));
    if (v.kind === "gate") return renderGate(v.gate);
    if (v.kind === "card") return renderCardForm();
    return renderReport();
  },
});
