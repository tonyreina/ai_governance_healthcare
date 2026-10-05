/* ============================================================
   Data arrival
   ============================================================ */
function onProjects(list){
  PROJECTS=new Map(list.map(p=>[p.id,normalize(p)]));
  const first=!LOADED; LOADED=true;
  if(first && UI.project && PROJECTS.has(UI.project) && !CUR){ openProject(UI.project,UI.view); return; }
  if(CUR){
    const r=PROJECTS.get(CUR);
    if(!r){ toast("This project was deleted"); goHome(); return; }
    S=normalize(deepMerge(clone(r), clone(pending[CUR]||{})));
    softRefresh();
  } else updateDashboard();
}
function onDbError(e){
  if(e&&e.code==="revoked"){ setReadOnly(true); setMode("Access ended","ro"); }
  else { setMode("Disconnected: reload to reconnect","ro"); }
}
