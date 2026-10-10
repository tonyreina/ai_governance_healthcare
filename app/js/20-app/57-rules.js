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
  // A server that names none (or not as text) is shown as "?", never "undefined".
  const named = rules && typeof rules === "object" && !Array.isArray(rules)
    && typeof rules.primary === "string" && rules.primary;
  RULES_SERVER_PRIMARY = named ? rules.primary.slice(0, 64) : "?";
  showRulesBanner();
  return RULES_PROBLEMS;
}

/* What the banner says now, as [tag, problem, text]: its title, each problem's
   sentence, and, while it blocks, what stops. "Other changes still save" is said
   only to a person with a project open that they may edit: to anyone else it is
   not true, or not theirs to know. */
function rulesBannerParts(){
  const blocking = rulesBlockWrites();
  const vars = {page: BUILD.primary, server: RULES_SERVER_PRIMARY};
  const parts = [["B", "", t(blocking ? "rules.title" : "rules.titleUnsynced")]];
  RULES_PROBLEMS.forEach(p => parts.push(["SPAN", p, t(RULES_PROBLEM_KEY[p], vars)]));
  if(blocking){
    parts.push(["SPAN", "", t("rules.blocked")]);
    if(S && !RO) parts.push(["SPAN", "", t("rules.othersSave")]);
  }
  return parts;
}

/* Put the banner's words in place, changing only the parts that differ, so a
   change of language or of the open project does not announce the whole alert
   again. Text only: the server's words never become markup. */
function fillRulesBanner(){
  const el = document.getElementById("rulesBanner");
  if(!el) return;
  const parts = rulesBannerParts();
  parts.forEach(([tag, problem, text], i) => {
    let part = el.children[i];
    if(!part || part.tagName !== tag || (part.dataset.rules || "") !== problem){
      const made = document.createElement(tag);
      if(tag !== "B") made.className = "sw-detail";
      if(problem) made.dataset.rules = problem;
      if(part) el.replaceChild(made, part); else el.appendChild(made);
      part = made;
    }
    if(part.textContent !== text) part.textContent = text;
  });
  while(el.children.length > parts.length) el.lastElementChild.remove();
}

/* Draw the banner, or bring it up to date. It is one element for the life of the
   page: made with its role, inserted empty and filled a moment later, since a
   live region inserted already full is not reliably announced (role=status
   above all); after that, a change of language or of the open project changes
   its words in place (fillRulesBanner). dir=auto, with each part isolated, sets
   the whole banner in the direction of the words it shows: its sentences stay
   English in Hebrew until reviewed (D-59), and are not each aligned their own
   way. */
function showRulesBanner(){
  let el = document.getElementById("rulesBanner");
  if(!RULES_PROBLEMS.length){ if(el) el.remove(); return; }
  const blocking = rulesBlockWrites();
  const fresh = !el;
  if(fresh){
    el = document.createElement("div");
    el.id = "rulesBanner";
    el.dir = "auto";
  }
  el.className = "storage-warning rules-banner" + (blocking ? " blocking" : "");
  el.setAttribute("role", blocking ? "alert" : "status");
  if(!fresh){ fillRulesBanner(); return; }
  const header = document.querySelector("header.top");
  if(!header || !header.parentNode) return;
  header.parentNode.insertBefore(el, header.nextSibling);
  setTimeout(fillRulesBanner, 50);
}
