/* ============================================================
   Exports
   ============================================================ */
const STANDALONE_CSS = () => {
  const css=[...document.styleSheets].flatMap(sh=>{try{return [...sh.cssRules]}catch(e){return []}})
    .filter(r=>r.selectorText && /^(\.label|\.r-|\.overall|\.bars|\.bar|\.rtable|\.tag|\.pchip|\.disclaimer|\.eyebrow|\.gaplist|h1|h2|\.report)/.test(r.selectorText))
    .map(r=>r.cssText).join("\n");
  return `:root{--paper:#fff;--surface:#fff;--sunk:#EEF2F3;--ink:#13233A;--muted:#55667A;--rule:#C9D3D9;--teal:#0E6E66;--amber:#9A5806;--amber-soft:#F7E8CF;--red:#B42318;--red-soft:#F8DCD9;--green:#1F7A3E;--green-soft:#D7EEDD;--sans:"Public Sans","Segoe UI",system-ui,sans-serif;--display:"Archivo","Arial Narrow",Arial,sans-serif}
body{margin:0;background:#fff;color:var(--ink);font:15px/1.55 var(--sans)}main{max-width:900px;margin:0 auto;padding:32px 24px 60px}.r-wrap{overflow-x:auto}
@media print{main{padding:0}h2{break-after:avoid}.label{break-inside:avoid}}
${css}`;
};
function exportHTML(){
  return `<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>${esc(S.meta.solution||"AI solution")} – CHAI assurance review</title>
<link href="https://fonts.googleapis.com/css2?family=Archivo:wdth,wght@62..125,400..900&family=Public+Sans:wght@400;600;700&display=swap" rel="stylesheet">
<style>${STANDALONE_CSS()}</style></head><body><main class="report">${reportBody(true)}</main></body></html>`;
}
function exportMD(){
  const all=allItems(), ov=scoreOf(all), m=S.meta, L=[];
  const st=s=>s?STATUS[s]:"Unanswered";
  const line=s=>String(s||"").replace(/\n+/g," ").replace(/\|/g,"\\|");
  const nm=id=>id?(NAMES[id]||"someone"):"someone";
  L.push(`# ${m.solution||"Untitled AI solution"}: CHAI assurance review`,"");
  L.push(`- **Status:** ${statusOf(S).label}`,`- **Lifecycle phase:** ${phase(S).label}`,`- **Organization:** ${m.org||"–"}`,`- **Developer:** ${m.developer||"–"}`,`- **Sourcing:** ${m.sourcing||"–"}`,`- **Risk tier:** ${m.riskTier||"–"}`,`- **Clinical sponsor:** ${m.sponsor||"–"}`,`- **Next periodic review:** ${nextReview(S)||"–"}`,`- **Review team:** ${line(m.reviewers)||"–"}`,`- **Scope:** ${line(m.scope)||"–"}`,`- **Generated:** ${TODAY()}`,"");
  const F=flags(S); L.push("## Compliance flags",""); if(F.length) F.forEach(f=>L.push(`- **${f.sev==="red"?"Out of compliance":"Needs update"}:** ${f.text}`)); else L.push("None."); L.push("");
  L.push(`## Readiness`,"",`Overall: **${ov.pct}%** of applicable criteria met (${ov.answered}/${ov.total} answered).`,"","| Principle | Score |","|---|---|");
  Object.entries(PRINCIPLES).forEach(([k,p])=>L.push(`| ${p.name} | ${scoreOf(all.filter(it=>it.p===k)).pct}% |`));
  L.push("","## Checkpoint decisions","","| Checkpoint | Decision | Decided by | Date | Rationale |","|---|---|---|---|---|");
  Object.entries(GATES).forEach(([k,G])=>{const g=S.gates[k]||{}; L.push(`| ${G.title}: ${G.q} | ${g.decision||"Not decided"} | ${line(g.by)}${g.signedBy?` (recorded by ${line(nm(g.signedBy))})`:""} | ${line(g.date)} | ${line(g.rationale)} |`);});
  L.push("","## Open gaps","");
  const gaps=all.filter(it=>{const s=(S.items[it.id]||{}).status; return !s||s==="notmet"||s==="partial";});
  if(gaps.length){ L.push("| Stage | Criterion | Status | Owner | Due |","|---|---|---|---|---|"); gaps.forEach(it=>{const d=S.items[it.id]||{}; L.push(`| ${it.stage.n} | ${line(it.text)} | ${st(d.status)} | ${line(d.owner)} | ${line(d.due)} |`);}); }
  else L.push("None.");
  L.push("","## Applied model card","");
  CARD.forEach(sec=>{L.push(`### ${sec.sec}`,""); sec.fields.forEach(f=>L.push(`- **${f[1]}:** ${line(cardValOf(S,f[0]))||"_Not provided_"}`)); L.push("");
    if(sec.sec==="Trust ingredients"){ L.push("### Key metrics",""); if(S.metrics.length){L.push("| Category | Metric | Value | 95% CI | Population |","|---|---|---|---|---|"); S.metrics.forEach(x=>L.push(`| ${x.cat} | ${line(x.name)} | ${line(x.value)} | ${line(x.ci)} | ${line(x.pop)} |`));} else L.push("_None entered_"); L.push("");}});
  L.push("## Sign-off history",""); if(LOG.length) LOG.forEach(e=>L.push(`- ${(e.at||"").slice(0,10)}: ${line(e.text)} (${line(nm(e.by))})`)); else L.push("None."); L.push("");
  L.push("## Appendix: full checklist","");
  STAGES.forEach(s=>{L.push(`### ${s.n}. ${s.title}`,""); s.items.forEach(it=>{const d=S.items[it.id]||{}; L.push(`- [${it.p}] ${it.text}: **${st(d.status)}**${d.evidence?` (${line(d.evidence)})`:""}`);}); L.push("");});
  L.push("---","_Structured around the CHAI six-stage lifecycle and Applied Model Card. Checklist wording is paraphrased; this is an internal governance record, not a CHAI certification._");
  return L.join("\n");
}
function projectJSON(p){
  const all=allItems();
  const state=clone(p); delete state.id;
  return {
    schema:"chai-review/2", generated:new Date().toISOString(),
    status:statusOf(p).label, phase:phase(p).label, next_review:nextReview(p), flags:flags(p),
    meta:p.meta, gates:p.gates, metrics:p.metrics,
    model_card:Object.fromEntries(CARD_FIELDS.map(k=>[k,cardValOf(p,k)])),
    checklist:all.map(it=>({id:it.id,stage:it.stage.n,principle:it.p,criterion:it.text,...(({status,evidence,owner,due})=>({status:status||null,evidence:evidence||"",owner:owner||"",due:due||""}))(p.items[it.id]||{})})),
    scores:{overall:scoreOf(all,p.items).pct,...Object.fromEntries(Object.keys(PRINCIPLES).map(k=>[k,scoreOf(all.filter(it=>it.p===k),p.items).pct]))},
    _state:state
  };
}
function exportCSV(){
  const q=v=>`"${String(v??"").replace(/"/g,'""')}"`;
  const head=["Project","Developer","Clinical sponsor","Risk tier","Lifecycle phase","Status","Readiness %","Next review","Flags","Archived","Last updated"];
  const rows=dashData().map(r=>[r.p.meta.solution,r.p.meta.developer,r.p.meta.sponsor,r.p.meta.riskTier,phase(r.p).label,r.st.label,r.score,r.nr||"",r.f.map(f=>f.text).join("; "),r.p.archived?"yes":"",(r.p.updatedAt||"").slice(0,10)]);
  return [head,...rows].map(r=>r.map(q).join(",")).join("\r\n");
}
const slug = s=> (s||"ai-solution").toLowerCase().replace(/[^a-z0-9]+/g,"-").replace(/^-|-$/g,"").slice(0,60) || "ai-solution";

let DL=null, dlChecked=false;
const STANDALONE = !(window.claude && typeof window.claude.use==="function");
function updateDlUI(){
  const fb=document.getElementById("dlFallback"); if(!fb) return;
  const btns=[...document.querySelectorAll('#ractions [data-act^="dl-"]')];
  if(DL||STANDALONE){ btns.forEach(b=>b.hidden=false); fb.innerHTML=""; return; }
  if(!dlChecked) return;
  btns.forEach(b=>b.hidden=true);
  fb.innerHTML=`<details class="fallback"><summary style="cursor:pointer;font-size:14px;font-weight:600">Downloads aren't available in this view. Copy the export instead.</summary>
    <p style="font-size:13px;color:var(--muted)">Markdown pastes into most wikis and docs; JSON can be imported here or read from Python.</p>
    <label class="vh" for="fbmd">Markdown</label><textarea id="fbmd" readonly>${esc(exportMD())}</textarea>
    <label class="vh" for="fbjs">JSON</label><textarea id="fbjs" readonly style="margin-top:8px">${esc(JSON.stringify(projectJSON(S),null,2))}</textarea></details>`;
}
async function download(filename,data){
  if(STANDALONE){
    const types={html:"text/html",md:"text/markdown",json:"application/json",csv:"text/csv"};
    const ext=filename.split(".").pop();
    const url=URL.createObjectURL(new Blob([data],{type:(types[ext]||"text/plain")+";charset=utf-8"}));
    const a=document.createElement("a"); a.href=url; a.download=filename; document.body.appendChild(a); a.click(); a.remove();
    setTimeout(()=>URL.revokeObjectURL(url),1000); toast("Saved "+filename); return;
  }
  if(!DL){ toast("Downloads aren't available here"); return; }
  try{ const r=await DL.save({filename,data}); if(r&&r.status==="saved") toast("Saved "+filename); }
  catch(e){
    const c=e&&e.code;
    if(c==="declined") return;
    if(c==="rate_limited") toast("A save prompt is already open");
    else if(c==="extension_not_enabled") toast("That file type isn't available here");
    else { DL=null; updateDlUI(); toast("Downloads aren't available here"); }
  }
}
