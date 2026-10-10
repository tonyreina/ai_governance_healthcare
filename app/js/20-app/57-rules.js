/* ============================================================
   The retirement-rules banner (#168, D-83)

   Shown below the header, in API mode only, when the server's retirement rules
   are not this page's (00-core/35-rules.js). It is not dismissable: the fix is
   the operator's (run the migrate job with this build's manifest.json), and a
   banner a person can close hides the problem from the next decision. While the
   rules disagree it is an alert, and the page records no checkpoint decision and
   creates no record; when they agree but no manifest confirmed them it is a
   status, and nothing is stopped.
   ============================================================ */
function checkRetirementRules(health){
  const rules = health && health.retirement_rules;
  RULES_PROBLEMS = rulesProblems(rules, BUILD);
  // The server's word for its primary, shown as text and never trusted as more.
  RULES_SERVER_PRIMARY = rules && typeof rules === "object" ? String(rules.primary).slice(0, 64) : "";
  showRulesBanner();
  return RULES_PROBLEMS;
}

function showRulesBanner(){
  const old = document.getElementById("rulesBanner");
  if(old) old.remove();
  if(!RULES_PROBLEMS.length) return;
  const blocking = rulesBlockWrites();
  const el = document.createElement("div");
  el.id = "rulesBanner";
  el.className = "storage-warning rules-banner" + (blocking ? " blocking" : "");
  el.setAttribute("role", blocking ? "alert" : "status");
  const lines = RULES_PROBLEMS.map(p =>
    `<span class="sw-detail" data-rules="${esc(p)}">${esc(t(RULES_PROBLEM_KEY[p], {page: BUILD.primary, server: RULES_SERVER_PRIMARY}))}</span>`);
  if(blocking) lines.push(`<span class="sw-detail">${esc(t("rules.blocked"))}</span>`);
  el.innerHTML = `<b>${esc(t(blocking ? "rules.title" : "rules.titleUnsynced"))}</b> ${lines.join(" ")}`;  // xss-ok: every text escaped above; tests/test_rules_banner.py shows the server's words stay text
  const header = document.querySelector("header.top");
  if(header && header.parentNode) header.parentNode.insertBefore(el, header.nextSibling);
}
