/* ============================================================
   CHAI: its own screens (plug-ins)
   The key metrics at stage 4, the T&E picker, the applied model card's
   form and its label. Stages, checkpoints and the report are the
   engine's (01-engine/20-views.js).
   ============================================================ */

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
