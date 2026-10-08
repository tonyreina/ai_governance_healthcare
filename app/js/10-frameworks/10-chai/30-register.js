/* ============================================================
   CHAI: registration
   Declares CHAI to the shell. This is the only file that has to
   change when a CHAI screen is added or reordered.

   CHAI is always enabled. It owns the project document's `items`
   and `gates` keys, the compliance status on the dashboard, and the
   applied model card -- so the tool is a CHAI tool with other
   frameworks alongside, not a neutral host of several equals. That
   is a deliberate choice: the dashboard needs ONE status, and
   mixing two frameworks' judgements into one number would be
   meaningless. See docs/crosswalk.md.
   ============================================================ */
registerFramework({
  id: "chai",
  label: "CHAI",

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
        id: s.id, kind: "stage", label: s.title, num: s.n, short: t("rail.stageShort", {n: s.n}),
        meta: () => { const c = scoreOf(s.items, p.items); return `${c.answered}/${c.total}`; },
        metaCls: () => { const c = scoreOf(s.items, p.items); return c.answered === c.total ? "done" : ""; },
      });
      Object.entries(GATES).filter(([, g]) => g.after === s.id).forEach(([key, g]) => {
        out.push({
          id: "g" + key, kind: "gate", gate: key, label: g.title, cls: "gate",
          numHTML: '<span class="diamond" aria-hidden="true"></span>',
          meta: () => { const d = (p.gates[key] || {}).decision || ""; return d ? esc(shortDecision(d)) : esc(t("dash.gateOpen")); },
          metaCls: () => { const d = (p.gates[key] || {}).decision || ""; return !d ? "" : (/Stop|Retire|Revise|Retrain/.test(d) ? "warn" : "done"); },
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
