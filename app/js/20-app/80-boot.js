/* ============================================================
   Boot
   ============================================================ */
applyStaticI18n(document);
{ const pick = document.getElementById(HeaderControl.LANGUAGE); if(pick) pick.innerHTML = localeOptions(); }
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
  if(db){
    STORE=new DbStore(db); MODE=Mode.ARTIFACT;
    if(RO) setMode(t("mode.viewOnly"),"ro"); else setModeFor(MODE);
    showArtifactNotice();
  }
  else {
    // Self-hosted backend, if this page is served by one. Checked only when
    // there is no artifact database, so the artifact path costs nothing.
    const api = await detectApi("/api");

    if(api.verdict === "ok"){
      rememberApiHere();
      STORE=new ApiStore("/api"); MODE=Mode.API; CAN_DELETE=true;
      setModeFor(MODE);
      showScopeNotice();
      startSession(api.health);   // sign-out link and idle lock, as the server configured
      // Identity is established by the proxy, so the browser cannot choose it.
      try{
        const me = await fetch("/api/me",{credentials:"same-origin"}).then(r=>r.json());
        if(me && me.id){ ME.id=me.id; if(me.name) NAMES[me.id]=me.name; }
      }catch(e){}
    }
    else if(api.verdict === "denied"){
      // The server knows who you are and said no. Falling back here would
      // hand a denied user a working private workspace -- access control
      // failing open into a usable app. Stop instead.
      fatalError(t("fatal.denied.title"), t("fatal.denied.detail"),
        {mode:t("mode.noAccess"), hint:t("fatal.denied.hint")});
      return;
    }
    else if(api.verdict === "error" || api.verdict === "unreachable" || apiSeenHere()){
      // This origin has served a real API before, or something is there and
      // failing. Either way this is a deployment with a server, and browser-
      // local storage is not a substitute for it: the work would be invisible
      // to colleagues, absent from the audit log, and stranded on this machine.
      fatalError(t("fatal.unreachable.title"), t("fatal.unreachable.detail"),
        {hint:t("fatal.unreachable.hint")});
      return;
    }
    else {
      // Nothing API-shaped at this origin and none ever seen: a genuinely
      // static host. localStorage is the intended mode here.
      STORE=new LocalStore(); MODE=Mode.LOCAL; CAN_DELETE=true;
      setModeFor(MODE);
      showStorageWarning();
    }
  }
  document.body.classList.toggle("ro",RO);
  STORE.subscribeAll(onProjects,onDbError);
})();
