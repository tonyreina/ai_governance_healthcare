/* ============================================================
   OPTICA: content

   OPTICA's content is data: app/frameworks/optica/framework.json, embedded
   by the build as FRAMEWORK_DEFS.optica and run by the engine (01-engine/).
   The constants below are TRANSITIONAL views of that definition in the
   shapes OPTICA's screens still read (#168 PR A); the generic renderers
   replace them.

   Item wording is this project's own paraphrase. The OPTICA paper
   (NEJM AI 2024) is copyright Massachusetts Medical Society and
   marked for personal use only; its text is not reproduced here or
   anywhere in this repository.

   Item keys are dot-free ("7-11", not "7.11") because the app's
   edit()/get() helpers split state paths on ".", so a dotted key
   cannot be addressed. The dotted form is display only.
   ============================================================ */
const OPTICA_DEF = FRAMEWORK_DEFS.optica;
const OPTICA = {
  domains: Object.fromEntries(OPTICA_DEF.categories.map(c => [c.id, c.name])),
  chapters: OPTICA_DEF.sections.map(s => ({
    n: s.n, domain: s.category, title: s.title, purpose: s.purpose || "",
    items: s.items.map(it => ({
      key: it.id, num: it.num, text: it.text, who: it.who || "",
      stage: (it.attrs || {}).stage || "",
      rel: (it.crossRefs || {}).relation || "",
      chai: (it.crossRefs || {}).ids || [],
    })),
  })),
};
const OPTICA_ITEMS = OPTICA.chapters.flatMap(c => c.items.map(i => ({ ...i, chapter: c })));
