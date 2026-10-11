/* ============================================================
   Data arrival
   ============================================================ */
function onProjects(list){
  PROJECTS=new Map(list.map(p=>[p.id,normalizeStored(p)]));
  const first=!LOADED; LOADED=true;
  if(first && UI.project && PROJECTS.has(UI.project) && !CUR){ openProject(UI.project,UI.view); return; }
  if(CUR){
    const r=PROJECTS.get(CUR);
    if(!r){ toast(t("toast.deletedElsewhere")); goHome(); return; }
    S=normalizeStored(deepMerge(clone(storedRecord(r)), clone(pending[CUR]||{})));
    softRefresh();
  } else updateDashboard();
}
function onDbError(e){
  if(e&&e.code==="revoked"){ setReadOnly(true); setMode(t("mode.accessEnded"),"ro"); }
  else { setMode(t("mode.disconnected"),"ro"); }
}
