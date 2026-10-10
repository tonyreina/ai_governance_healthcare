/* ============================================================
   CHAI: its own controls
   The metric buttons and the use-case picker belong to CHAI's
   stage 4 and model card. The shell offers each click and change
   to the active frameworks first (#168); these return true when
   they handled it.
   ============================================================ */
const ChaiAct = Object.freeze({ ADD_METRIC: "addmetric" });

function chaiClick(btn){
  // Add a CHAI-recommended metric. Name and category only: the value, the
  // interval and the population are measurements the organization has to make,
  // and pre-filling them would be inventing results.
  if(btn.dataset.te && !RO){
    const name=btn.dataset.te;
    if(!S.metrics.some(m=>(m.name||"").trim().toLowerCase()===name.trim().toLowerCase())){
      S.metrics.push({cat:btn.dataset.teCat||METRIC_CATS[0],name,value:"",ci:"",pop:""});
      saveMetrics();
    }
    renderMain(false); renderPanel();
    // Put the cursor where the user now has to type.
    const rows=[...document.querySelectorAll('.mtable input[data-bind$=".name"]')];
    const row=rows.find(i=>i.value===name);
    if(row) row.closest("tr").querySelector('input[data-bind$=".value"]').focus();
    return true;
  }
  if(btn.dataset.delmetric!=null && !RO){ S.metrics.splice(+btn.dataset.delmetric,1); saveMetrics(); renderMain(false); renderPanel(); return true; }
  if(btn.dataset.act===ChaiAct.ADD_METRIC && !RO){
    S.metrics.push({cat:METRIC_CATS[0],name:"",value:"",ci:"",pop:""}); saveMetrics(); renderMain(false);
    const ins=document.querySelectorAll('.mtable input[data-bind$=".name"]'); ins[ins.length-1]?.focus();
    return true;
  }
  return false;
}

/* The use-case picker is stored on the project, so the chosen framework
   persists and the suggestions are there next time someone opens stage 4. */
function chaiChange(el){
  if(el.dataset && el.dataset.teUse!=null && S && !RO){ edit("meta.chaiUseCase", el.value); renderMain(false); return true; }
  return false;
}
