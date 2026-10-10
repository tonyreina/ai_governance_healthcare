/* ============================================================
   Retirement rules: does the server retire records by this page's? (#168, D-83)

   The server decides when a project is retired, and so when its record comes due
   for disposal, from the rules loaded out of the manifest.json built beside this
   page (D-76). /api/health reports the rules it holds as `retirement_rules`:
   their `hash`, its `primary` framework, and whether a build's manifest set them
   (`synced`). The build embeds this page's own hash (BUILD.ruleSetHash) and
   primary (BUILD.primary), so the page can tell when the two disagree: the server
   would then retire records by rules this page does not show.

   Nothing here runs without a server: in local mode, or from a file, there is no
   other side to disagree with. A server that sends no `retirement_rules` (one
   from before #168, or one that cannot read them) is not second-guessed: the
   page has nothing to compare, and says nothing (D-83).
   ============================================================ */
/* What can be wrong, each with its own sentence. A closed set, so a frozen object. */
const RulesProblem = Object.freeze({
  PRIMARY: "primary",     // the server's records follow another framework's rules
  HASH: "hash",           // same primary, different rules for it
  UNSYNCED: "unsynced",   // no build's manifest set or confirmed the server's rules
});
const RULES_PROBLEM_KEY = Object.freeze({
  [RulesProblem.PRIMARY]: "rules.primary",
  [RulesProblem.HASH]: "rules.hash",
  [RulesProblem.UNSYNCED]: "rules.unsynced",
});
/* The problems that stop the writes the rules govern: a checkpoint decision, and a
   new record. When the server holds the page's own rules but no manifest confirmed
   them (UNSYNCED alone), the rules a decision is retired by are the ones the page
   shows, so nothing is stopped; the banner still says so. */
const RULES_BLOCKING = Object.freeze([RulesProblem.PRIMARY, RulesProblem.HASH]);

/* What the server said, as problems. [] when it agrees, or said nothing. */
let RULES_PROBLEMS = [], RULES_SERVER_PRIMARY = "";

/* Compare the server's `retirement_rules` with a build's ({primary, ruleSetHash}).
   A different primary always means different rules, so it is reported instead of
   the hash, which would only repeat it in vaguer words. Anything but exactly the
   page's value is a disagreement: a malformed answer is not taken as agreement. */
function rulesProblems(rules, build){
  if(!rules || typeof rules !== "object") return [];
  const out = [];
  if(rules.primary !== build.primary) out.push(RulesProblem.PRIMARY);
  else if(rules.hash !== build.ruleSetHash) out.push(RulesProblem.HASH);
  if(rules.synced !== true) out.push(RulesProblem.UNSYNCED);
  return out;
}

/* Whether the page must refuse a checkpoint decision or a new record now. */
const rulesBlockWrites = () => RULES_PROBLEMS.some(p => RULES_BLOCKING.includes(p));
