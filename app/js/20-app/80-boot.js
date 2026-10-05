/* ============================================================
   Boot
   ============================================================ */
renderDashboardShell();
(async()=>{
  let db=null, user=null;
  const hasClaude = window.claude && typeof window.claude.use==="function";
  if(hasClaude){
    const dlP = window.claude.use("downloads").then(d=>{DL=d;}).catch(()=>{}).finally(()=>{dlChecked=true; updateDlUI();});
    [db,user] = await Promise.all([window.claude.use("db").catch(()=>null), window.claude.use("user").catch(()=>null)]);
  } else { dlChecked=true; }
  USER=user;
  if(user){
    try{ ME.id = await user.id(); }catch(e){}
    try{ const c=await user.can("data.write"); if(db && c===false) RO=true; }catch(e){}
    try{ CAN_DELETE = (await user.canEdit()) || (await user.isOwner()); }catch(e){ CAN_DELETE=false; }
  }
  if(db){ STORE=new DbStore(db); MODE="shared"; setMode(RO?"View only":"Shared workspace", RO?"ro":"shared"); }
  else { STORE=new LocalStore(); MODE="local"; CAN_DELETE=true; setMode("This browser only",""); }
  document.body.classList.toggle("ro",RO);
  STORE.subscribeAll(onProjects,onDbError);
})();
