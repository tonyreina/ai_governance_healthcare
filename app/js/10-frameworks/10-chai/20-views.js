/* ============================================================
   CHAI: views
   Every screen that renders CHAI content -- stages, checkpoints,
   the applied model card, and the report.
   ============================================================ */
const shortDecision = d => ({"Proceed with conditions":"Conditional","Revise and resubmit":"Revise","Continue with changes":"Changes","Retrain or revise":"Retrain"}[d]||d);

function renderStage(s){
  const c=scoreOf(s.items);
  return `<p class="eyebrow">${esc(t("stage.eyebrow",{n:s.n}))}</p><h1>${esc(s.title)}</h1>
  <p class="lede">${esc(s.blurb)}</p>
  <div class="legend">${Object.entries(PRINCIPLES).map(([k,p])=>`<span><span class="pchip">${k}</span> ${esc(p.name)}</span>`).join("")}</div>
  <ol class="checklist">${s.items.map(it=>ciHTML(it)).join("")}</ol>
  <p style="font-size:13px;color:var(--muted);margin-top:10px">${esc(t("stage.answered",{answered:c.answered,total:c.total}))}</p>
  ${s.metrics?metricsHTML():""}
  ${pager()}`;
}
function ciHTML(it){
  const d=S.items[it.id]||{}; const st=d.status||"";
  const open = openItems.has(it.id);
  const late = d.due && parseDay(d.due)<parseDay(TODAY()) && st!=="met" && st!=="na";
  const notes = (d.evidence||d.owner||d.due) && !open ? `<span class="has-notes">${late?`<b style="color:var(--red)">${esc(t("ci.overdue",{date:fmtDay(d.due)}))}</b>`:esc(t("ci.notes"))}</span>`:"";
  return `<li class="ci${open?" open":""}" data-item="${it.id}">
    <div class="ci-row">
      <span class="pchip" title="${esc(PRINCIPLES[it.p].name)}">${it.p}</span>
      <div class="ci-text">${esc(it.text)}<button class="more" data-toggle="${it.id}" aria-expanded="${open}">${esc(t(open?"ci.hide":"ci.more"))}</button>${notes}</div>
      <div class="seg" role="group" aria-label="${esc(t("ci.statusGroup"))}">${Object.keys(STATUS).map(k=>`<button data-set="${it.id}" data-s="${k}" aria-pressed="${st===k}">${esc(t(STATUS_KEY[k]))}</button>`).join("")}</div>
    </div>
    <div class="ci-detail">
      <div><label for="ev_${it.id}">${esc(t("ci.evidence"))}</label><textarea id="ev_${it.id}" rows="2" data-bind="items.${it.id}.evidence" ${NO_BROWSER_ASSIST}>${esc(d.evidence||"")}</textarea></div>
      <div><label for="ow_${it.id}">${esc(t("ci.owner"))}</label><input type="text" id="ow_${it.id}" data-bind="items.${it.id}.owner" value="${esc(d.owner||"")}"></div>
      <div><label for="du_${it.id}">${esc(t("ci.due"))}</label><input type="date" id="du_${it.id}" data-bind="items.${it.id}.due" value="${esc(d.due||"")}"></div>
    </div>
  </li>`;
}
function metricsHTML(){
  return `<h2>${esc(t("metrics.title"))}</h2>
  <p class="lede" style="margin-bottom:12px">${esc(t("metrics.lede"))}</p>
  <div class="mwrap"><table class="mtable"><thead><tr><th style="width:24%">${esc(t("metrics.col.category"))}</th><th>${esc(t("metrics.col.metric"))}</th><th style="width:13%">${esc(t("metrics.col.value"))}</th><th style="width:15%">${esc(t("metrics.col.ci"))}</th><th style="width:22%">${esc(t("metrics.col.pop"))}</th><th><span class="vh">${esc(t("metrics.remove"))}</span></th></tr></thead><tbody>
  ${S.metrics.map((m,i)=>`<tr>
    <td><select aria-label="${esc(t("metrics.col.category"))}" data-bind="metrics.${i}.cat">${METRIC_CATS.map(c=>`<option${m.cat===c?" selected":""}>${c}</option>`).join("")}</select></td>
    <td><input type="text" aria-label="${esc(t("metrics.col.metric"))}" data-bind="metrics.${i}.name" value="${esc(m.name)}" placeholder="${esc(t("metrics.placeholder"))}"></td>
    <td><input type="text" aria-label="${esc(t("metrics.col.value"))}" data-bind="metrics.${i}.value" value="${esc(m.value)}"></td>
    <td><input type="text" aria-label="${esc(t("metrics.col.ci"))}" data-bind="metrics.${i}.ci" value="${esc(m.ci)}"></td>
    <td><input type="text" aria-label="${esc(t("metrics.col.pop"))}" data-bind="metrics.${i}.pop" value="${esc(m.pop)}"></td>
    <td><button class="icon-btn ro-hide" data-delmetric="${i}" aria-label="${esc(t("metrics.removeLabel"))}">${esc(t("metrics.remove"))}</button></td></tr>`).join("")}
  </tbody></table></div>
  ${S.metrics.length?"":`<p style="font-size:14px;color:var(--muted)">${esc(t("metrics.none"))}</p>`}
  <button class="btn ro-hide" data-act="addmetric" style="margin-top:10px">${esc(t("metrics.add"))}</button>
  ${teSuggestHTML()}`;
}

/* CHAI publishes a consensus set of methods and metrics per use case, and says
   to consult them when completing the Applied Model Card. This is that moment,
   so the list is offered here rather than left on another website.

   Picking one fills in the name and category only. The value, the interval and
   the population are the organization's own measurements; pre-filling those
   would be inventing results. */
function teSuggestHTML(){
  const chosen = (S.meta||{}).chaiUseCase || "";
  const uc = CHAI_TE[chosen];
  const options = Object.entries(CHAI_TE)
    .map(([k,v])=>`<option value="${esc(k)}"${k===chosen?" selected":""}>${esc(v.label)}</option>`)
    .join("");

  let body;
  if(!uc){
    body = `<p style="font-size:13px;color:var(--muted);margin:8px 0 0">${esc(t("te.choose"))}</p>`;
  } else {
    const byCat = {};
    uc.metrics.forEach(m=>{ (byCat[m.cat] = byCat[m.cat] || []).push(m); });
    const have = new Set(S.metrics.map(m=>(m.name||"").trim().toLowerCase()));
    body = METRIC_CATS.filter(c=>byCat[c]).map(c=>`
      <p style="font-size:12.5px;font-weight:700;margin:12px 0 4px">${esc(c)}</p>
      <div style="display:flex;flex-wrap:wrap;gap:6px">
        ${byCat[c].map(m=>{
          const added = have.has(m.name.trim().toLowerCase());
          const note = [m.when, m.who].filter(Boolean).join(" \u00b7 ");
          return `<button class="btn ro-hide" data-te="${esc(m.name)}" data-te-cat="${esc(c)}"
            ${added?"disabled":""} style="font-size:12px;padding:4px 9px"
            title="${esc(note||t("te.recommended"))}">${added?"\u2713 ":""}${esc(m.name)}</button>`;
        }).join("")}
      </div>`).join("")
      // The attribution CC BY 4.0 requires: the source, the license and the copyright
      // line stay in every language (te.credit keeps {link} and the © line verbatim).
      + `<p style="font-size:12px;color:var(--muted);margin:12px 0 0">${tHtml("te.credit",{count:uc.metrics.length},{link:`<a href="${esc(uc.url)}" target="_blank" rel="noopener">${esc(t("te.linkText",{label:uc.label}))}</a>`})}</p>`;
  }

  return `<details class="fallback ro-hide" style="margin-top:16px"${chosen?" open":""}>
    <summary style="cursor:pointer;font-size:14px;font-weight:600">${esc(t("te.summary"))}</summary>
    <p style="font-size:13px;color:var(--muted);margin:8px 0">${esc(t("te.lede"))}</p>
    <label for="teUse" style="font-size:12.5px;font-weight:700">${esc(t("te.useCase"))}</label>
    <select id="teUse" data-te-use style="margin-left:8px">
      <option value="">${esc(t("te.select"))}</option>${options}
    </select>
    ${body}
  </details>`;
}
function renderGate(key){
  const G=GATES[key], g=S.gates[key]||{};
  const s=STAGES.find(x=>x.id===G.after);
  const gaps=gapsUpTo(S,G.after);
  const partial = STAGES.slice(0,STAGES.indexOf(s)+1).flatMap(x=>x.items).filter(it=>(S.items[it.id]||{}).status==="partial").length;
  let note="";
  if(gaps.length){
    note=`<div class="note"><b>${esc(t("gate.gaps",{count:gaps.length,n:s.n}))}${partial?esc(t("gate.andPartial",{count:partial})):""}.</b>${isGo(g.decision)?` ${esc(t("gate.recordConditions"))}`:""}
    <ul class="gaplist">${gaps.slice(0,6).map(it=>`<li>${esc(t("gate.gapItem",{n:it.stage.n,text:it.text}))} <em>(${esc(t((S.items[it.id]||{}).status?"gate.notMet":"gate.unanswered"))})</em></li>`).join("")}${gaps.length>6?`<li>${esc(t("dash.andMore",{count:gaps.length-6}))}</li>`:""}</ul></div>`;
  } else if(partial) note=`<div class="note">${esc(t("gate.answeredPartial",{count:partial,n:s.n}))}</div>`;
  else note=`<div class="note ok">${esc(t("gate.allMet",{n:s.n}))}</div>`;
  const nr = key==="D" ? nextReview(S) : null;
  return `<p class="eyebrow">${esc(t("gate.eyebrow",{title:G.title,n:s.n}))}</p><h1>${esc(G.q)}</h1>
  <p class="lede">${esc(G.help)}</p>
  ${note}
  <div class="gate-panel">
    <p style="margin:0;font-weight:600">${esc(t("gate.decision"))}</p>
    <div class="decisions" role="group" aria-label="${esc(t("gate.decision"))}">${G.options.map(o=>`<button data-gate="${key}" data-d="${esc(o)}" aria-pressed="${g.decision===o}">${esc(o)}</button>`).join("")}</div>
    <div class="fields">
      ${field(`gates.${key}.by`,t("gate.by"),t("gate.byHint"),0)}
      ${field(`gates.${key}.date`,t("gate.date"),"",0,null,"date")}
      ${field(`gates.${key}.rationale`,t("gate.rationale"),t("gate.rationaleHint"),1)}
    </div>
    ${g.decision?`<p class="signed">${g.signedAt?tHtml("gate.recordedOn",{date:fmtDay(g.signedAt.slice(0,10))},{who:who(g.signedBy)}):tHtml("gate.recorded",{},{who:who(g.signedBy)})}${nr?` ${esc(t("gate.nextDue",{date:fmtDay(nr)}))}`:""}</p>`:""}
    ${key==="D"&&g.decision?`<p class="ro-hide" style="margin:12px 0 0"><button class="btn" data-act="newreview">${esc(t("gate.newReview"))}</button></p>`:""}
  </div>
  ${pager()}`;
}
function renderCardForm(){
  return `<p class="eyebrow">${esc(t("card.eyebrow"))}</p><h1>${esc(t("card.title"))}</h1>
  <p class="lede">${esc(t("card.lede",{fields:CORE_CARD.map(k=>CARD_LABEL[k].toLowerCase()).join(", ")}))}</p>
  ${S.cardUpdatedAt?`<p style="font-size:13px;color:var(--muted);margin:-8px 0 0">${esc(t("card.updated",{when:ago(S.cardUpdatedAt)}))}</p>`:""}
  ${CARD.map(sec=>`<h2>${esc(sec.sec)}</h2><div class="fields">${sec.fields.map(f=>{
      const ph = f[0]==="name"?S.meta.solution: f[0]==="developer"?S.meta.developer:"";
      return field(`card.${f[0]}`,f[1]+(CORE_CARD.includes(f[0])?` ${t("card.coreTag")}`:""),f[2],f[3]).replace(/data-bind="card\.(name|developer)"/, m=>`${m} placeholder="${esc(ph)}"`);
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
  if(!LOG.length) return `<p style="font-size:14px;color:var(--muted)">${esc(t("history.none"))}</p>`;
  return `<ul class="history">${LOG.slice(0,25).map(e=>`<li><time>${esc(fmtDay((e.at||"").slice(0,10)))}</time><span>${esc(e.text)} <span style="color:var(--muted)">${tHtml("log.by",{},{who:who(e.by)})}</span></span></li>`).join("")}</ul>`;
}
function reportBody(names){
  const nm = id => names ? esc(displayName(id)) : who(id);
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
    ${logWindowNote()?`<p style="color:var(--muted);font-size:13px"><strong>${esc(logWindowNote())}</strong></p>`:""}
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
