/* ============================================================
   Read-only handling, mode badge
   ============================================================ */
function setMode(text,cls){ const el=document.getElementById("mode"); el.textContent=text; el.className="mode "+(cls||""); }
function setReadOnly(v){ RO=v; document.body.classList.toggle("ro",v); if(v) setMode("View only","ro"); if(CUR) renderMain(false); else if(document.getElementById("plistHost")) renderDashboardShell(); }
function applyRO(root){
  if(!RO) return;
  root.querySelectorAll("input:not([type=search]),textarea,select").forEach(e=>{ if(!e.closest(".fallback")) e.disabled=true; });
  root.querySelectorAll("[data-set],[data-gate],[data-delmetric]").forEach(e=>e.disabled=true);
}
