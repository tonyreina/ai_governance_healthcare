/* ============================================================
   CHAI: views
   Every screen that renders CHAI content -- stages, checkpoints,
   the applied model card, and the report.
   ============================================================ */
const SHORT_DECISION = Object.freeze({"Proceed with conditions":"Conditional","Revise and resubmit":"Revise","Continue with changes":"Changes","Retrain or revise":"Retrain"});
const shortDecision = d => SHORT_DECISION[d] ? tf(`chai.short.${d}`, SHORT_DECISION[d]) : tf(`chai.option.${d}`, d);

function renderStage(s){
  const c=scoreOf(s.items);
  return `<p class="eyebrow">${esc(t("stage.eyebrow",{n:s.n}))}</p><h1>${esc(stageTitle(s))}</h1>
  <p class="lede">${esc(stageBlurb(s))}</p>
  ${fwNoteHTML()}
  <div class="legend">${Object.keys(PRINCIPLES).map(k=>`<span><span class="pchip">${k}</span> ${esc(principleName(k))}</span>`).join("")}</div>
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
      <span class="pchip" title="${esc(principleName(it.p))}">${it.p}</span>
      <div class="ci-text">${esc(itemText(it))}<button class="more" data-toggle="${it.id}" aria-expanded="${open}">${esc(t(open?"ci.hide":"ci.more"))}</button>${notes}</div>
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
    <td><select aria-label="${esc(t("metrics.col.category"))}" data-bind="metrics.${i}.cat">${METRIC_CATS.map(c=>`<option value="${esc(c)}"${m.cat===c?" selected":""}>${esc(metricCatName(c))}</option>`).join("")}</select></td>
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
    .map(([k,v])=>`<option value="${esc(k)}"${k===chosen?" selected":""}>${esc(tf(`te.usecase.${k}`, v.label))}</option>`)
    .join("");

  let body;
  if(!uc){
    body = `<p style="font-size:13px;color:var(--muted);margin:8px 0 0">${esc(t("te.choose"))}</p>`;
  } else {
    const byCat = {};
    uc.metrics.forEach(m=>{ (byCat[m.cat] = byCat[m.cat] || []).push(m); });
    const have = new Set(S.metrics.map(m=>(m.name||"").trim().toLowerCase()));
    body = METRIC_CATS.filter(c=>byCat[c]).map(c=>`
      <p style="font-size:12.5px;font-weight:700;margin:12px 0 4px">${esc(metricCatName(c))}</p>
      <div style="display:flex;flex-wrap:wrap;gap:6px">
        ${byCat[c].map(m=>{
          const added = have.has(m.name.trim().toLowerCase());
          const note = [m.when, m.who].filter(Boolean).join(" \u00b7 ");
          return `<button class="btn ro-hide" data-te="${esc(m.name)}" data-te-cat="${esc(c)}"
            ${added?"disabled":""} style="font-size:12px;padding:4px 9px"
            title="${esc(note||t("te.recommended"))}">${added?"\u2713 ":""}${esc(tf(`te.metric.${m.name}`, m.name))}</button>`;
        }).join("")}
      </div>`).join("")
      // The attribution CC BY 4.0 requires: the source, the license and the copyright
      // line stay in every language (te.credit keeps {link} and the © line verbatim).
      + `<p style="font-size:12px;color:var(--muted);margin:12px 0 0">${tHtml("te.credit",{count:uc.metrics.length},{link:`<a href="${esc(uc.url)}" target="_blank" rel="noopener">${esc(t("te.linkText",{label:tf(`te.usecase.${chosen}`, uc.label)}))}</a>`})}</p>`  // url-ok: CHAI's published address, from the generated definitions, not a person's text
      // CC BY 4.0 also asks that changes be indicated: the names are translated,
      // the descriptions behind the link are not, and the record keeps CHAI's English.
      + (frameworkTranslated() ? `<p class="te-note small" role="note">${esc(t("te.note"))}</p>` : "");
  }

  return `<details class="fallback ro-hide" style="margin-top:16px"${chosen?" open":""}>
    <summary style="cursor:pointer;font-size:14px;font-weight:600">${esc(t("te.summary"))}</summary>
    <p style="font-size:13px;color:var(--muted);margin:8px 0">${esc(t("te.lede"))}</p>
    <label for="teUse" style="font-size:12.5px;font-weight:700">${esc(t("te.useCase"))}</label>
    <select id="teUse" data-te-use style="margin-inline-start:8px">
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
    <ul class="gaplist">${gaps.slice(0,6).map(it=>`<li>${esc(t("gate.gapItem",{n:it.stage.n,text:itemText(it)}))} <em>(${esc(t((S.items[it.id]||{}).status?"gate.notMet":"gate.unanswered"))})</em></li>`).join("")}${gaps.length>6?`<li>${esc(t("dash.andMore",{count:gaps.length-6}))}</li>`:""}</ul></div>`;
  } else if(partial) note=`<div class="note">${esc(t("gate.answeredPartial",{count:partial,n:s.n}))}</div>`;
  else note=`<div class="note ok">${esc(t("gate.allMet",{n:s.n}))}</div>`;
  const nr = key==="D" ? nextReview(S) : null;
  return `<p class="eyebrow">${esc(t("gate.eyebrow",{title:gateTitle(key),n:s.n}))}</p><h1>${esc(gateQuestion(key))}</h1>
  <p class="lede">${esc(gateHelp(key))}</p>
  ${fwNoteHTML()}
  ${note}
  <div class="gate-panel">
    <p style="margin:0;font-weight:600">${esc(t("gate.decision"))}</p>
    <div class="decisions" role="group" aria-label="${esc(t("gate.decision"))}">${G.options.map(o=>`<button data-gate="${key}" data-d="${esc(o)}" aria-pressed="${g.decision===o}">${esc(optionText(o))}</button>`).join("")}</div>
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
  <p class="lede">${esc(t("card.lede",{fields:CORE_CARD.map(k=>cardLabel(k).toLocaleLowerCase(intlTag())).join(", ")}))}</p>
  ${S.cardUpdatedAt?`<p style="font-size:13px;color:var(--muted);margin:-8px 0 0">${esc(t("card.updated",{when:ago(S.cardUpdatedAt)}))}</p>`:""}
  ${fwNoteHTML()}
  ${CARD.map(sec=>`<h2>${esc(cardSecName(sec))}</h2><div class="fields">${sec.fields.map(f=>{
      const ph = f[0]==="name"?S.meta.solution: f[0]==="developer"?S.meta.developer:"";
      return field(`card.${f[0]}`,cardLabel(f[0])+(CORE_CARD.includes(f[0])?` ${t("card.coreTag")}`:""),cardHint(f),f[3]).replace(/data-bind="card\.(name|developer)"/, m=>`${m} placeholder="${esc(ph)}"`);
    }).join("")}</div>`).join("")}
  ${pager()}`;
}

function labelHTML(p){
  p=p||S;
  const v=k=>cardValOf(p,k);
  const dd=k=>v(k)?bdi(v(k)):`<span class="empty">${esc(t("label.notProvided"))}</span>`;
  const rows=keys=>keys.map(([k,l])=>`<div class="l-row"><dt>${esc(l)}</dt><dd>${dd(k)}</dd></div>`).join("");
  const sec=name=>CARD.find(s=>s.sec===name).fields.map(f=>[f[0],cardLabel(f[0])]);
  const secName=name=>cardSecName(CARD.find(s=>s.sec===name));
  const ms=p.metrics.filter(m=>m.name||m.value);
  const metricsBlock = ms.length
    ? METRIC_CATS.map(c=>{const g=ms.filter(m=>m.cat===c); if(!g.length) return "";
        return `<div class="l-mcat">${esc(metricCatName(c))}</div>${g.map(m=>`<div class="l-metric"><span>${m.name?bdi(m.name):esc(t("metrics.col.metric"))}${m.pop?`, ${bdi(m.pop)}`:""}</span><span>${bdi(m.value||"–")}${m.ci?` <span style="font-weight:400">(${bdi(m.ci)})</span>`:""}</span></div>`).join("")}`;}).join("")
    : `<div class="l-row"><span class="empty">${esc(t("label.noMetrics"))}</span></div>`;
  return `<div class="label">
    <p class="l-kicker">${esc(t("card.title"))}</p>
    <h2 class="l-name">${v("name")?bdi(v("name")):`<span class="empty">${esc(t("label.unnamed"))}</span>`}</h2>
    <p class="l-dev">${tHtml("label.developer",{},{name:`<b>${dd("developer")}</b>`})}</p>
    <p class="l-dev">${tHtml("label.contact",{},{value:dd("contact")})}</p>
    <div class="r8"></div>
    <div class="l-grid">
      <div><b>${esc(t("label.releaseStage"))}</b>${dd("releaseStage")}</div><div><b>${esc(t("label.releaseDate"))}</b>${dd("releaseDate")}</div><div><b>${esc(t("label.version"))}</b>${dd("version")}</div>
      <div><b>${esc(t("label.availability"))}</b>${dd("availability")}</div><div style="grid-column:span 2"><b>${esc(t("label.regulatory"))}</b>${dd("regulatory")}</div>
    </div>
    <div class="r4"></div>
    <p class="l-sec">${esc(t("label.summary"))}</p><div style="white-space:pre-wrap">${dd("summary")}</div>
    <div style="margin-top:3px"><b>${esc(t("label.keywords"))}</b> ${dd("keywords")}</div>
    <div class="r8"></div>
    <p class="l-sec">${esc(secName("Uses and directions"))}</p><dl>${rows(sec("Uses and directions"))}</dl>
    <div class="r4"></div>
    <p class="l-sec">${esc(secName("Warnings"))}</p><dl>${rows(sec("Warnings"))}</dl>
    <div class="r8"></div>
    <p class="l-sec">${esc(secName("Trust ingredients"))}</p><dl>${rows(sec("Trust ingredients"))}</dl>
    <div class="r4"></div>
    <p class="l-sec">${esc(t("metrics.title"))}</p>${metricsBlock}
    <div class="r4"></div>
    <p class="l-sec">${esc(secName("Resources"))}</p><dl>${rows(sec("Resources"))}</dl>
    <div class="r1"></div>
    <p class="l-foot">${esc(t("label.foot"))}</p>
  </div>`;
}
function renderLabel(){ if(S) document.getElementById("labelHost").innerHTML = labelHTML(); }

/* ---------- report ---------- */
function historyHTML(){
  if(!LOG.length) return `<p style="font-size:14px;color:var(--muted)">${esc(t("history.none"))}</p>`;
  return `<ul class="history">${LOG.slice(0,25).map(e=>`<li><time>${esc(fmtDay((e.at||"").slice(0,10)))}</time><span>${bdi(e.text)} <span style="color:var(--muted)">${tHtml("log.by",{},{who:who(e.by)})}</span></span></li>`).join("")}</ul>`;
}
function reportBody(names){
  const nm = id => names ? bdi(displayName(id)) : who(id);
  const all=allItems(); const ov=scoreOf(all);
  const unanswered=all.filter(it=>!(S.items[it.id]||{}).status).length;
  const gaps=all.filter(it=>{const st=(S.items[it.id]||{}).status; return !st||st==="notmet"||st==="partial";});
  // A stored status is whatever an import or an API writer put there, so the class
  // comes from the known set and never from the value (#155).
  const tag=st=>{ const known=Object.hasOwn(STATUS_KEY,st); return `<span class="tag ${known?st:"none"}">${esc(known?t(STATUS_KEY[st]):t("report.unanswered"))}</span>`; };
  const m=S.meta, F=flags(S), st=statusOf(S), nr=nextReview(S);
  return `<div class="r-head">
      <p class="eyebrow">${esc(t("report.eyebrow"))}</p>
      <h1>${m.solution?bdi(m.solution):esc(t("project.untitled"))}</h1>
      <div class="r-meta">
        <div><b>${esc(t("report.status"))}</b>${esc(statusLabel(st))}</div><div><b>${esc(t("report.phase"))}</b>${esc(phaseLabel(phase(S)))}</div>
        <div><b>${esc(t("report.org"))}</b>${bdi(m.org||"–")}</div><div><b>${esc(t("report.developer"))}</b>${bdi(m.developer||"–")}</div>
        <div><b>${esc(t("report.sourcing"))}</b>${esc(m.sourcing?(SOURCING_KEY[m.sourcing]?t(SOURCING_KEY[m.sourcing]):m.sourcing):"–")}</div><div><b>${esc(t("report.riskTier"))}</b>${esc(m.riskTier?(RISK_KEY[m.riskTier]?t(RISK_KEY[m.riskTier]):m.riskTier):"–")}</div>
        <div><b>${esc(t("report.sponsor"))}</b>${bdi(m.sponsor||"–")}</div><div><b>${esc(t("report.nextReview"))}</b>${nr?esc(fmtDay(nr)):"–"}</div>
        <div><b>${esc(t("report.generated"))}</b>${esc(fmtDay(TODAY()))}</div>
      </div>
      ${m.reviewers?`<p style="font-size:13.5px;margin:10px 0 0"><b>${esc(t("report.team"))}</b> ${bdi(m.reviewers)}</p>`:""}
      ${m.scope?`<p style="font-size:13.5px;margin:4px 0 0"><b>${esc(t("report.scope"))}</b> ${bdi(m.scope)}</p>`:""}
    </div>
    ${fwNoteHTML()}
    <h2>${esc(t("report.flags"))}</h2>
    ${F.length?`<ul class="gaplist" style="font-size:14px">${F.map(f=>`<li><span class="tag ${f.sev==="red"?"notmet":"partial"}">${esc(t(f.sev==="red"?"status.red":"status.amber"))}</span> ${esc(flagText(f))}</li>`).join("")}</ul>`:`<p>${esc(t("report.noFlags"))}</p>`}
    <h2>${esc(t("report.readiness"))}</h2>
    <div class="overall"><span class="big">${ov.pct}%</span><p>${esc(t("report.readinessDetail",{answered:ov.answered,total:ov.total}))}${unanswered?esc(t("report.stillOpen",{count:unanswered})):""}.</p></div>
    <div class="bars">${Object.keys(PRINCIPLES).map(k=>{const sc=scoreOf(all.filter(it=>it.p===k)); return `<div class="bar"><span>${esc(principleName(k))}</span><span class="track"><span class="fill ${barCls(sc.pct)}" style="width:${sc.pct}%;display:block"></span></span><span class="pct">${sc.pct}%</span></div>`;}).join("")}</div>
    <h2>${esc(t("report.lifecycle"))}</h2>
    <div class="r-wrap"><table class="rtable"><thead><tr><th>${esc(t("report.col.stage"))}</th><th>${esc(t("report.col.answered"))}</th><th>${esc(t("status.met"))}</th><th>${esc(t("status.partial"))}</th><th>${esc(t("status.notmet"))}</th><th>${esc(t("report.col.score"))}</th></tr></thead><tbody>
    ${STAGES.map(s=>{const cnt=k=>s.items.filter(it=>(S.items[it.id]||{}).status===k).length; const sc=scoreOf(s.items);
      return `<tr><td>${s.n}. ${esc(stageTitle(s))}</td><td>${sc.answered}/${sc.total}</td><td>${cnt("met")}</td><td>${cnt("partial")}</td><td>${cnt("notmet")}</td><td><b>${sc.pct}%</b></td></tr>`;}).join("")}
    </tbody></table></div>
    <h2>${esc(t("report.checkpoints"))}</h2>
    <div class="r-wrap"><table class="rtable"><thead><tr><th>${esc(t("report.col.checkpoint"))}</th><th>${esc(t("gate.decision"))}</th><th>${esc(t("gate.by"))}</th><th>${esc(t("report.col.date"))}</th><th>${esc(t("gate.rationale"))}</th></tr></thead><tbody>
    ${Object.keys(GATES).map(k=>{const g=S.gates[k]||{}; return `<tr><td>${esc(gateTitle(k))}<br><span style="color:var(--muted);font-size:12px">${esc(gateQuestion(k))}</span></td><td>${g.decision?`<b>${esc(optionText(g.decision))}</b>`:`<span style="color:var(--muted)">${esc(t("report.notDecided"))}</span>`}</td><td>${bdi(g.by||"")}${g.signedBy?`<br><span style="color:var(--muted);font-size:12px">${tHtml("report.recordedBy",{},{who:nm(g.signedBy)})}</span>`:""}</td><td>${esc(g.date||"")}</td><td style="white-space:pre-wrap">${bdi(g.rationale||"")}</td></tr>`;}).join("")}
    </tbody></table></div>
    <h2>${esc(t("report.gaps"))}</h2>
    ${gaps.length?`<div class="r-wrap"><table class="rtable"><thead><tr><th>${esc(t("report.col.stage"))}</th><th>${esc(t("report.col.criterion"))}</th><th>${esc(t("report.col.principle"))}</th><th>${esc(t("report.status"))}</th><th>${esc(t("ci.owner"))}</th><th>${esc(t("ci.due"))}</th></tr></thead><tbody>
      ${gaps.map(it=>{const d=S.items[it.id]||{}; const late=d.due&&parseDay(d.due)<parseDay(TODAY()); return `<tr><td>${it.stage.n}</td><td>${esc(itemText(it))}${d.evidence?`<br><span style="color:var(--muted);font-size:12.5px;white-space:pre-wrap">${bdi(d.evidence)}</span>`:""}</td><td>${esc(principleName(it.p))}</td><td>${tag(d.status)}</td><td>${bdi(d.owner||"–")}</td><td${late?' style="color:var(--red);font-weight:700"':""}>${esc(d.due||"–")}</td></tr>`;}).join("")}
    </tbody></table></div>`:`<p>${esc(t("report.noGaps"))}</p>`}
    <h2>${esc(t("card.title"))}</h2>
    <div style="max-width:560px">${labelHTML()}</div>
    <h2>${esc(t("report.history"))}</h2>
    ${logWindowNote()?`<p style="color:var(--muted);font-size:13px"><strong>${esc(logWindowNote())}</strong></p>`:""}
    ${LOG.length?`<div class="r-wrap"><table class="rtable"><tbody>${LOG.map(e=>`<tr><td style="width:120px">${esc(fmtDay((e.at||"").slice(0,10)))}</td><td>${bdi(e.text)}</td><td>${nm(e.by)}</td></tr>`).join("")}</tbody></table></div>`:`<p>${esc(t("report.noEvents"))}</p>`}
    <h2>${esc(t("report.appendix"))}</h2>
    ${STAGES.map(s=>`<h3 style="font-size:15px;margin:18px 0 6px">${s.n}. ${esc(stageTitle(s))}</h3><div class="r-wrap"><table class="rtable"><tbody>
      ${s.items.map(it=>{const d=S.items[it.id]||{}; return `<tr><td style="width:46px"><span class="pchip">${it.p}</span></td><td>${esc(itemText(it))}${d.evidence?`<br><span style="color:var(--muted);font-size:12.5px;white-space:pre-wrap">${bdi(d.evidence)}</span>`:""}</td><td style="width:110px">${tag(d.status)}</td></tr>`;}).join("")}
    </tbody></table></div>`).join("")}
    <p class="disclaimer">${esc(t("report.disclaimer"))}</p>`;
}
function renderReport(){
  return `<div class="report">
    <div class="r-actions" id="ractions">
      <button class="btn primary" data-act="dl-html">${esc(t("report.dlHtml"))}</button>
      <button class="btn" data-act="dl-pdf">${esc(t("report.dlPdf"))}</button>
      <button class="btn" data-act="dl-md">${esc(t("report.dlMd"))}</button>
      <button class="btn" data-act="dl-json">${esc(t("report.dlJson"))}</button>
      <button class="btn ghost" data-act="print">${esc(t("report.print"))}</button>
    </div>
    ${reportBody()}
    ${pager()}
  </div>`;
}
