/* ============================================================
   OPTICA: rules
   OPTICA's own progress, kept strictly apart from CHAI's.

   Two rules decide everything here, both from docs/crosswalk.md:

   1. NO STATUS PROPAGATION, in either direction. Evidence is shared
      by citing it; judgment never is. No OPTICA answer may change a
      CHAI criterion's status or a readiness percentage, and none of
      this feeds flags() or statusOf(). Breaking that would silently
      re-gate every existing project.

   2. A DECLINE IS A DISTINCT STATE. OPTICA accepts a reasoned "we
      chose not to" as a complete answer for some items; CHAI's
      local-validation obligations are unconditional. So "declined"
      is tracked separately and never folded into the percentage as
      though it were met.
   ============================================================ */
const OPTICA_STATUS = { met: "Answered", partial: "Partial", notmet: "Outstanding", declined: "Declined", na: "N/A" };   // English: exports
const OPTICA_STATUS_KEY = Object.freeze({ met: "optica.status.met", partial: "status.partial", notmet: "optica.status.notmet", declined: "optica.status.declined", na: "status.na" });
const OPTICA_VAL = { met: 1, partial: 0.5, notmet: 0, declined: 0 };

/* OPTICA's content as the reader sees it (D-60); this project's paraphrase is the
   English source, and records keep their keys, never the wording. */
const opticaItemText = it => tf(`optica.item.${it.key}`, it.text);
const opticaChapterTitle = c => tf(`optica.chapter.${c.n}.title`, c.title);

const opticaOn = p => !!((p || S).optica || {}).enabled;
const opticaAnswers = p => ((p || S).optica || {}).answers || {};
const opticaAnswer = (p, key) => opticaAnswers(p)[key] || {};

/* Progress over any list of OPTICA items. Declines are counted as
   answered (the stakeholder did respond) but contribute nothing to
   the percentage, and are reported separately so they stay visible. */
function opticaScore(items, p) {
  const answers = opticaAnswers(p);
  let sum = 0, n = 0, answered = 0, declined = 0;
  items.forEach(it => {
    const st = (answers[it.key] || {}).status;
    if (st) answered++;
    if (st === "declined") { declined++; return; }
    if (st === "na") return;
    n++; sum += OPTICA_VAL[st] || 0;
  });
  return { pct: n ? Math.round(sum / n * 100) : 0, answered, total: items.length, applicable: n, declined };
}

/* Who still owes answers. OPTICA assigns each item to one of five
   stakeholders and runs them in sequence, so "which stakeholder is
   blocking" is the question that actually moves a review along --
   and ~a third of the items can only be answered by the vendor. */
function opticaByProducer(p) {
  const answers = opticaAnswers(p);
  const out = {};
  OPTICA_ITEMS.forEach(it => {
    const who = it.who || "unassigned";
    const b = out[who] || (out[who] = { who, total: 0, answered: 0, outstanding: [] });
    b.total++;
    if ((answers[it.key] || {}).status) b.answered++;
    else b.outstanding.push(it);
  });
  return Object.values(out).sort((a, b) => b.total - a.total);
}

const opticaOutstanding = p => OPTICA_ITEMS.filter(it => !(opticaAnswer(p, it.key).status));
