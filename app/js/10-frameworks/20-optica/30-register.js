/* ============================================================
   OPTICA: registration
   Opt-in per project. A project that has never switched OPTICA on
   carries no `optica` key at all, so existing exports stay valid
   and teams that only run CHAI never see 77 extra rows.
   ============================================================ */
registerFramework({
  id: "optica",
  label: "OPTICA",
  describePath: opticaDescribePath,
  statusName: v => Object.hasOwn(OPTICA_STATUS, v) ? OPTICA_STATUS[v] : undefined,
  toggle: on => setOpticaEnabled(on),

  enabled: p => opticaOn(p),

  // Deliberately empty: a new project does NOT get an optica key.
  // It appears the first time someone switches the framework on.
  blank: () => ({}),

  normalize(p) {
    if (!p.optica) return;
    p.optica.enabled = !!p.optica.enabled;
    p.optica.answers = p.optica.answers || {};
  },

  views(p) {
    const out = [{
      id: "optica", kind: "overview", label: t("optica.rail"),
      glyph: "◇", sep: "before",
      meta: () => { const s = opticaScore(OPTICA_ITEMS, p); return `${s.answered}/${s.total}`; },
      metaCls: () => { const s = opticaScore(OPTICA_ITEMS, p); return s.answered === s.total ? "done" : ""; },
      short: "OPTICA",
    }];
    OPTICA.chapters.forEach(c => {
      out.push({
        id: "o" + c.n, kind: "chapter", chapter: c.n, label: opticaChapterTitle(c), num: c.n,
        short: `OPTICA ${c.n}`,
        meta: () => { const s = opticaScore(c.items, p); return `${s.answered}/${s.total}`; },
        metaCls: () => { const s = opticaScore(c.items, p); return s.answered === s.total ? "done" : ""; },
      });
    });
    return out;
  },

  render(v) {
    if (!opticaOn(S)) return renderOpticaOff();
    return v.kind === "chapter" ? renderOpticaChapter(v.chapter) : renderOpticaOverview();
  },
});

/* Switching the framework on or off for the open project. Turning it
   off keeps every answer: it only hides the views, so a team that
   pauses an OPTICA review does not lose the work. */
function setOpticaEnabled(on) {
  if (RO || !S) return;
  if (!S.optica) S.optica = { enabled: false, answers: {} };
  edit("optica.enabled", !!on);
  writeLog(CUR, `${on ? "Enabled" : "Disabled"} the OPTICA adoption review`);
  if (!on && String(UI.view).startsWith("o")) go("setup");
  else renderProject(false);
}
