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
    try{ const c=await user.can("data.write"); if(db && c===false) WORKSPACE_RO=RO=true; }catch(e){}
    try{ CAN_DELETE = (await user.canEdit()) || (await user.isOwner()); }catch(e){ CAN_DELETE=false; }
  }
  if(db){ STORE=new DbStore(db); MODE="shared"; setMode(RO?"View only":"Shared workspace", RO?"ro":"shared"); }
  else {
    // Self-hosted backend, if this page is served by one. Checked only when
    // there is no artifact database, so the artifact path costs nothing.
    const api = await detectApi("/api");
    if(api){
      STORE=new ApiStore("/api"); MODE="api"; CAN_DELETE=true;
      setMode("Shared workspace","shared");
      // Identity is established by the proxy, so the browser cannot choose it.
      try{
        const me = await fetch("/api/me",{credentials:"same-origin"}).then(r=>r.json());
        if(me && me.id){ ME.id=me.id; if(me.name) NAMES[me.id]=me.name; }
      }catch(e){}
    } else {
      STORE=new LocalStore(); MODE="local"; CAN_DELETE=true; setMode("This browser only","");
    }
  }
  document.body.classList.toggle("ro",RO);
  STORE.subscribeAll(onProjects,onDbError);
})();
