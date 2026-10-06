/* ============================================================
   CHAI: views
   Every screen that renders CHAI content -- stages, checkpoints,
   the applied model card, and the report.
   ============================================================ */
const shortDecision = d => ({"Proceed with conditions":"Conditional","Revise and resubmit":"Revise","Continue with changes":"Changes","Retrain or revise":"Retrain"}[d]||d);

function renderStage(s){
  const c=scoreOf(s.items);
  return `<p class="eyebrow">Stage ${s.n} of 6</p><h1>${esc(s.title)}</h1>
  <p class="lede">${esc(s.blurb)}</p>
  <div class="legend">${Object.entries(PRINCIPLES).map(([k,p])=>`<span><span class="pchip">${k}</span> ${esc(p.name)}</span>`).join("")}</div>
  <ol class="checklist">${s.items.map(it=>ciHTML(it)).join("")}</ol>
  <p style="font-size:13px;color:var(--muted);margin-top:10px">${c.answered} of ${c.total} answered. Give anything partial or not met an owner and a due date; overdue actions are flagged on the dashboard.</p>
  ${s.metrics?metricsHTML():""}
  ${pager()}`;
}
function ciHTML(it){
  const d=S.items[it.id]||{}; const st=d.status||"";
  const open = openItems.has(it.id);
  const late = d.due && parseDay(d.due)<parseDay(TODAY()) && st!=="met" && st!=="na";
  const notes = (d.evidence||d.owner||d.due) && !open ? `<span class="has-notes">${late?`<b style="color:var(--red)">overdue ${esc(fmtDay(d.due))}</b>`:"notes added"}</span>`:"";
  return `<li class="ci${open?" open":""}" data-item="${it.id}">
    <div class="ci-row">
      <span class="pchip" title="${esc(PRINCIPLES[it.p].name)}">${it.p}</span>
      <div class="ci-text">${esc(it.text)}<button class="more" data-toggle="${it.id}" aria-expanded="${open}">${open?"Hide details":"Evidence & owner"}</button>${notes}</div>
      <div class="seg" role="group" aria-label="Status">${Object.entries(STATUS).map(([k,l])=>`<button data-set="${it.id}" data-s="${k}" aria-pressed="${st===k}">${l}</button>`).join("")}</div>
    </div>
    <div class="ci-detail">
      <div><label for="ev_${it.id}">Evidence or notes</label><textarea id="ev_${it.id}" rows="2" data-bind="items.${it.id}.evidence">${esc(d.evidence||"")}</textarea></div>
      <div><label for="ow_${it.id}">Owner</label><input type="text" id="ow_${it.id}" data-bind="items.${it.id}.owner" value="${esc(d.owner||"")}"></div>
      <div><label for="du_${it.id}">Due</label><input type="date" id="du_${it.id}" data-bind="items.${it.id}.due" value="${esc(d.due||"")}"></div>
    </div>
  </li>`;
}
function metricsHTML(){
  return `<h2>Key metrics</h2>
  <p class="lede" style="margin-bottom:12px">Report each metric with the population it was measured on. Add one row per subgroup for fairness results.</p>
  <div class="mwrap"><table class="mtable"><thead><tr><th style="width:24%">Category</th><th>Metric</th><th style="width:13%">Value</th><th style="width:15%">95% CI</th><th style="width:22%">Population or subgroup</th><th><span class="vh">Remove</span></th></tr></thead><tbody>
  ${S.metrics.map((m,i)=>`<tr>
    <td><select aria-label="Category" data-bind="metrics.${i}.cat">${METRIC_CATS.map(c=>`<option${m.cat===c?" selected":""}>${c}</option>`).join("")}</select></td>
    <td><input type="text" aria-label="Metric" data-bind="metrics.${i}.name" value="${esc(m.name)}" placeholder="e.g. AUROC"></td>
    <td><input type="text" aria-label="Value" data-bind="metrics.${i}.value" value="${esc(m.value)}"></td>
    <td><input type="text" aria-label="95% CI" data-bind="metrics.${i}.ci" value="${esc(m.ci)}"></td>
    <td><input type="text" aria-label="Population" data-bind="metrics.${i}.pop" value="${esc(m.pop)}"></td>
    <td><button class="icon-btn ro-hide" data-delmetric="${i}" aria-label="Remove metric">Remove</button></td></tr>`).join("")}
  </tbody></table></div>
  ${S.metrics.length?"":`<p style="font-size:14px;color:var(--muted)">No metrics yet. Add the ones your team will stand behind.</p>`}
  <button class="btn ro-hide" data-act="addmetric" style="margin-top:10px">Add metric</button>`;
}
function renderGate(key){
  const G=GATES[key], g=S.gates[key]||{};
  const s=STAGES.find(x=>x.id===G.after);
  const gaps=gapsUpTo(S,G.after);
  const partial = STAGES.slice(0,STAGES.indexOf(s)+1).flatMap(x=>x.items).filter(it=>(S.items[it.id]||{}).status==="partial").length;
  let note="";
  if(gaps.length){
    note=`<div class="note"><b>${gaps.length} item${gaps.length>1?"s":""} in stages 1–${s.n} ${gaps.length>1?"are":"is"} unanswered or not met${partial?`, and ${partial} partial`:""}.</b>${isGo(g.decision)?" Record the conditions or the accepted risk in the rationale.":""}
    <ul class="gaplist">${gaps.slice(0,6).map(it=>`<li>Stage ${it.stage.n}: ${esc(it.text)} <em>(${(S.items[it.id]||{}).status?"not met":"unanswered"})</em></li>`).join("")}${gaps.length>6?`<li>and ${gaps.length-6} more</li>`:""}</ul></div>`;
  } else if(partial) note=`<div class="note">All items through stage ${s.n} are answered; ${partial} ${partial>1?"are":"is"} partial.</div>`;
  else note=`<div class="note ok">Every applicable item through stage ${s.n} is met.</div>`;
  const nr = key==="D" ? nextReview(S) : null;
  return `<p class="eyebrow">${G.title}, after stage ${s.n}</p><h1>${esc(G.q)}</h1>
  <p class="lede">${esc(G.help)}</p>
  ${note}
  <div class="gate-panel">
    <p style="margin:0;font-weight:600">Decision</p>
    <div class="decisions" role="group" aria-label="Decision">${G.options.map(o=>`<button data-gate="${key}" data-d="${esc(o)}" aria-pressed="${g.decision===o}">${esc(o)}</button>`).join("")}</div>
    <div class="fields">
      ${field(`gates.${key}.by`,"Decided by","Committee, or name and role",0)}
      ${field(`gates.${key}.date`,"Decision date","YYYY-MM-DD",0)}
      ${field(`gates.${key}.rationale`,"Rationale and conditions","What the decision rests on, conditions attached, and when it will be revisited",1)}
    </div>
    ${g.decision?`<p class="signed">Recorded by ${who(g.signedBy)}${g.signedAt?` on ${esc(fmtDay(g.signedAt.slice(0,10)))}`:""}.${nr?` Next periodic review due ${esc(fmtDay(nr))}.`:""}</p>`:""}
    ${key==="D"&&g.decision?`<p class="ro-hide" style="margin:12px 0 0"><button class="btn" data-act="newreview">Record a new periodic review today</button></p>`:""}
  </div>
  ${pager()}`;
}
function renderCardForm(){
  return `<p class="eyebrow">Transparency</p><h1>Applied model card</h1>
  <p class="lede">The fields follow the CHAI Applied Model Card template. Core fields for live or piloted solutions: ${CORE_CARD.map(k=>CARD_LABEL[k].toLowerCase()).join(", ")}. Edits here mark the card as updated on the dashboard.</p>
  ${S.cardUpdatedAt?`<p style="font-size:13px;color:var(--muted);margin:-8px 0 0">Card last updated ${esc(ago(S.cardUpdatedAt))}.</p>`:""}
  ${CARD.map(sec=>`<h2>${esc(sec.sec)}</h2><div class="fields">${sec.fields.map(f=>{
      const ph = f[0]==="name"?S.meta.solution: f[0]==="developer"?S.meta.developer:"";
      return field(`card.${f[0]}`,f[1]+(CORE_CARD.includes(f[0])?" (core)":""),f[2],f[3]).replace(/data-bind="card\.(name|developer)"/, m=>`${m} placeholder="${esc(ph)}"`);
    }).join("")}</div>`).join("")}
  ${pager()}`;
}

function labelHTML(p){
  p=p||S;
  const v=k=>cardValOf(p,k);
  const dd=k=>v(k)?esc(v(k)):`<span class="empty">Not provided</span>`;
  const rows=keys=>keys.map(([k,l])=>`<div class="l-row"><dt>${esc(l)}</dt><dd>${dd(k)}</dd></div>`).join("");
  const sec=name=>CARD.find(s=>s.sec===name).fields.map(f=>[f[0],f[1]]);
  const ms=p.metrics.filter(m=>m.name||m.value);
  const metricsBlock = ms.length
    ? METRIC_CATS.map(c=>{const g=ms.filter(m=>m.cat===c); if(!g.length) return "";
        return `<div class="l-mcat">${esc(c)}</div>${g.map(m=>`<div class="l-metric"><span>${esc(m.name||"Metric")}${m.pop?`, ${esc(m.pop)}`:""}</span><span>${esc(m.value||"–")}${m.ci?` <span style="font-weight:400">(${esc(m.ci)})</span>`:""}</span></div>`).join("")}`;}).join("")
    : `<div class="l-row"><span class="empty">No metrics entered</span></div>`;
  return `<div class="label">
    <p class="l-kicker">Applied model card</p>
    <h2 class="l-name">${v("name")?esc(v("name")):'<span class="empty">Unnamed solution</span>'}</h2>
    <p class="l-dev">Developer: <b>${dd("developer")}</b></p>
    <p class="l-dev">Inquiries or issues: ${dd("contact")}</p>
    <div class="r8"></div>
    <div class="l-grid">
      <div><b>Release stage</b>${dd("releaseStage")}</div><div><b>Release date</b>${dd("releaseDate")}</div><div><b>Version</b>${dd("version")}</div>
      <div><b>Availability</b>${dd("availability")}</div><div style="grid-column:span 2"><b>Regulatory approval</b>${dd("regulatory")}</div>
    </div>
    <div class="r4"></div>
    <p class="l-sec">Summary</p><div style="white-space:pre-wrap">${dd("summary")}</div>
    <div style="margin-top:3px"><b>Keywords:</b> ${dd("keywords")}</div>
    <div class="r8"></div>
    <p class="l-sec">Uses and directions</p><dl>${rows(sec("Uses and directions"))}</dl>
    <div class="r4"></div>
    <p class="l-sec">Warnings</p><dl>${rows(sec("Warnings"))}</dl>
    <div class="r8"></div>
    <p class="l-sec">Trust ingredients</p><dl>${rows(sec("Trust ingredients"))}</dl>
    <div class="r4"></div>
    <p class="l-sec">Key metrics</p>${metricsBlock}
    <div class="r4"></div>
    <p class="l-sec">Resources</p><dl>${rows(sec("Resources"))}</dl>
    <div class="r1"></div>
    <p class="l-foot">Structure follows the CHAI Applied Model Card template (draft v0.1). Prepared by the deploying organization; not a CHAI certification.</p>
  </div>`;
}
function renderLabel(){ if(S) document.getElementById("labelHost").innerHTML = labelHTML(); }

/* ---------- report ---------- */
function historyHTML(){
  if(!LOG.length) return `<p style="font-size:14px;color:var(--muted)">No recorded events yet.</p>`;
  return `<ul class="history">${LOG.slice(0,25).map(e=>`<li><time>${esc(fmtDay((e.at||"").slice(0,10)))}</time><span>${esc(e.text)} <span style="color:var(--muted)">by ${who(e.by)}</span></span></li>`).join("")}</ul>`;
}
function reportBody(names){
  const nm = id => names ? esc(id?(NAMES[id]||"someone"):"someone") : who(id);
  const all=allItems(); const ov=scoreOf(all);
  const unanswered=all.filter(it=>!(S.items[it.id]||{}).status).length;
  const gaps=all.filter(it=>{const st=(S.items[it.id]||{}).status; return !st||st==="notmet"||st==="partial";});
  const tag=st=>`<span class="tag ${st||"none"}">${st?STATUS[st]:"Unanswered"}</span>`;
  const m=S.meta, F=flags(S), st=statusOf(S), nr=nextReview(S);
  return `<div class="r-head">
      <p class="eyebrow">CHAI lifecycle assurance review</p>
      <h1>${esc(m.solution||"Untitled AI solution")}</h1>
      <div class="r-meta">
        <div><b>Status</b>${esc(st.label)}</div><div><b>Lifecycle phase</b>${esc(phase(S).label)}</div>
        <div><b>Organization</b>${esc(m.org||"–")}</div><div><b>Developer</b>${esc(m.developer||"–")}</div>
        <div><b>Sourcing</b>${esc(m.sourcing||"–")}</div><div><b>Risk tier</b>${esc(m.riskTier||"–")}</div>
        <div><b>Clinical sponsor</b>${esc(m.sponsor||"–")}</div><div><b>Next periodic review</b>${nr?esc(fmtDay(nr)):"–"}</div>
        <div><b>Report generated</b>${esc(fmtDay(TODAY()))}</div>
      </div>
      ${m.reviewers?`<p style="font-size:13.5px;margin:10px 0 0"><b>Review team:</b> ${esc(m.reviewers)}</p>`:""}
      ${m.scope?`<p style="font-size:13.5px;margin:4px 0 0"><b>Scope:</b> ${esc(m.scope)}</p>`:""}
    </div>
    <h2>Compliance flags</h2>
    ${F.length?`<ul class="gaplist" style="font-size:14px">${F.map(f=>`<li><span class="tag ${f.sev==="red"?"notmet":"partial"}">${f.sev==="red"?"Out of compliance":"Needs update"}</span> ${esc(f.text)}</li>`).join("")}</ul>`:`<p>No open flags.</p>`}
    <h2>Readiness</h2>
    <div class="overall"><span class="big">${ov.pct}%</span><p>of applicable criteria met (partial counts as half, unanswered as zero). ${ov.answered} of ${ov.total} items answered${unanswered?`; ${unanswered} still open`:""}.</p></div>
    <div class="bars">${Object.entries(PRINCIPLES).map(([k,p])=>{const sc=scoreOf(all.filter(it=>it.p===k)); return `<div class="bar"><span>${esc(p.name)}</span><span class="track"><span class="fill ${barCls(sc.pct)}" style="width:${sc.pct}%;display:block"></span></span><span class="pct">${sc.pct}%</span></div>`;}).join("")}</div>
    <h2>Lifecycle status</h2>
    <div class="r-wrap"><table class="rtable"><thead><tr><th>Stage</th><th>Answered</th><th>Met</th><th>Partial</th><th>Not met</th><th>Score</th></tr></thead><tbody>
    ${STAGES.map(s=>{const cnt=k=>s.items.filter(it=>(S.items[it.id]||{}).status===k).length; const sc=scoreOf(s.items);
      return `<tr><td>${s.n}. ${esc(s.title)}</td><td>${sc.answered}/${sc.total}</td><td>${cnt("met")}</td><td>${cnt("partial")}</td><td>${cnt("notmet")}</td><td><b>${sc.pct}%</b></td></tr>`;}).join("")}
    </tbody></table></div>
    <h2>Checkpoint decisions</h2>
    <div class="r-wrap"><table class="rtable"><thead><tr><th>Checkpoint</th><th>Decision</th><th>Decided by</th><th>Date</th><th>Rationale and conditions</th></tr></thead><tbody>
    ${Object.entries(GATES).map(([k,G])=>{const g=S.gates[k]||{}; return `<tr><td>${G.title}<br><span style="color:var(--muted);font-size:12px">${esc(G.q)}</span></td><td>${g.decision?`<b>${esc(g.decision)}</b>`:'<span style="color:var(--muted)">Not yet decided</span>'}</td><td>${esc(g.by||"")}${g.signedBy?`<br><span style="color:var(--muted);font-size:12px">recorded by ${nm(g.signedBy)}</span>`:""}</td><td>${esc(g.date||"")}</td><td style="white-space:pre-wrap">${esc(g.rationale||"")}</td></tr>`;}).join("")}
    </tbody></table></div>
    <h2>Open gaps and actions</h2>
    ${gaps.length?`<div class="r-wrap"><table class="rtable"><thead><tr><th>Stage</th><th>Criterion</th><th>Principle</th><th>Status</th><th>Owner</th><th>Due</th></tr></thead><tbody>
      ${gaps.map(it=>{const d=S.items[it.id]||{}; const late=d.due&&parseDay(d.due)<parseDay(TODAY()); return `<tr><td>${it.stage.n}</td><td>${esc(it.text)}${d.evidence?`<br><span style="color:var(--muted);font-size:12.5px;white-space:pre-wrap">${esc(d.evidence)}</span>`:""}</td><td>${esc(PRINCIPLES[it.p].name)}</td><td>${tag(d.status)}</td><td>${esc(d.owner||"–")}</td><td${late?' style="color:var(--red);font-weight:700"':""}>${esc(d.due||"–")}</td></tr>`;}).join("")}
    </tbody></table></div>`:`<p>No open gaps. Every applicable criterion is met.</p>`}
    <h2>Applied model card</h2>
    <div style="max-width:560px">${labelHTML()}</div>
    <h2>Sign-off history</h2>
    ${LOG.length?`<div class="r-wrap"><table class="rtable"><tbody>${LOG.map(e=>`<tr><td style="width:120px">${esc(fmtDay((e.at||"").slice(0,10)))}</td><td>${esc(e.text)}</td><td>${nm(e.by)}</td></tr>`).join("")}</tbody></table></div>`:`<p>No recorded events.</p>`}
    <h2>Appendix: full checklist</h2>
    ${STAGES.map(s=>`<h3 style="font-size:15px;margin:18px 0 6px">${s.n}. ${esc(s.title)}</h3><div class="r-wrap"><table class="rtable"><tbody>
      ${s.items.map(it=>{const d=S.items[it.id]||{}; return `<tr><td style="width:46px"><span class="pchip">${it.p}</span></td><td>${esc(it.text)}${d.evidence?`<br><span style="color:var(--muted);font-size:12.5px;white-space:pre-wrap">${esc(d.evidence)}</span>`:""}</td><td style="width:110px">${tag(d.status)}</td></tr>`;}).join("")}
    </tbody></table></div>`).join("")}
    <p class="disclaimer">This report organizes a local review around the Coalition for Health AI (CHAI) six-stage lifecycle and five principles, and the structure of the CHAI Applied Model Card. Checklist wording is a paraphrased summary, not the official CHAI Responsible AI Checklist. It is an internal governance record, not a certification, legal opinion, or regulatory determination.</p>`;
}
function renderReport(){
  return `<div class="report">
    <div class="r-actions" id="ractions">
      <button class="btn primary" data-act="dl-html">Download report (HTML)</button>
      <button class="btn" data-act="dl-pdf">Download PDF</button>
      <button class="btn" data-act="dl-md">Download Markdown</button>
      <button class="btn" data-act="dl-json">Download project data (JSON)</button>
      <button class="btn ghost" data-act="print">Print</button>
    </div>
    <div id="dlFallback"></div>
    ${reportBody()}
    ${pager()}
  </div>`;
}
