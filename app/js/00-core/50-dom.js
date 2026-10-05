/* ============================================================
   Core: DOM helpers
   Form fields, focus preservation and small formatters. No
   knowledge of any framework.
   ============================================================ */
const get = (path)=> path.split(".").reduce((o,k)=>o==null?undefined:o[k], S);
function field(path,label,hint,long,opts){
  const v=esc(get(path)||""); const id="f_"+path.replace(/\./g,"_");
  let input;
  if(opts) input=`<select id="${id}" data-bind="${path}"><option value="">Choose…</option>${opts.map(o=>`<option${get(path)===o?" selected":""}>${esc(o)}</option>`).join("")}</select>`;
  else if(long) input=`<textarea id="${id}" data-bind="${path}" rows="3">${v}</textarea>`;
  else input=`<input type="text" id="${id}" data-bind="${path}" value="${v}">`;
  return `<div class="field${long?" wide":""}"><label for="${id}">${esc(label)}</label>${hint?`<span class="hint">${esc(hint)}</span>`:""}${input}</div>`;
}
function pager(){
  // Views come from the registry, so the pager walks whatever the active
  // frameworks contributed. `short` lets a view give the pager a terser name
  // than its rail label; otherwise the label is used.
  const views=activeViews();
  const i=views.findIndex(v=>v.id===UI.view);
  const prev=views[i-1], next=views[i+1];
  const name=v=>v?(v.short||v.label||""):"";
  return `<div class="pager">${prev?`<button class="btn" data-go="${prev.id}">Back to ${esc(name(prev))}</button>`:`<button class="btn" data-home="1">Back to all projects</button>`}${next?`<button class="btn primary" data-go="${next.id}">Continue to ${esc(name(next))}</button>`:""}</div>`;
}
function focusKey(el){
  if(!el||!el.dataset) return null; const d=el.dataset;
  if(d.set) return `[data-set="${d.set}"][data-s="${d.s}"]`;
  if(d.gate) return `[data-gate="${d.gate}"][data-d="${CSS.escape(d.d)}"]`;
  if(d.toggle) return `[data-toggle="${d.toggle}"]`;
  if(d.act) return `[data-act="${d.act}"]`;
  return null;
}
function editingInMain(){ const a=document.activeElement, m=document.getElementById("main"); return a && m.contains(a) && /^(INPUT|TEXTAREA|SELECT)$/.test(a.tagName); }
function syncInputs(){
  document.querySelectorAll("#main [data-bind]").forEach(el=>{ if(el===document.activeElement) return; const v=get(el.dataset.bind)??""; if(el.value!==v) el.value=v; });
  document.querySelectorAll("#main [data-set]").forEach(b=>b.setAttribute("aria-pressed",String((S.items[b.dataset.set]||{}).status===b.dataset.s)));
}
function barCls(p){ return p>=80?"":p>=50?"mid":"low"; }
