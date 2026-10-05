/* ============================================================
   Stores: shared database, or this browser as a fallback
   ============================================================ */
class DbStore{
  constructor(db){ this.db=db; }
  col(){ return this.db.collection("projects"); }
  subscribeAll(cb,err){ return this.col().onSnapshot(s=>cb(s.docs.map(d=>({id:d.id,...clone(d.data())}))),err); }
  create(id,data){ return this.col().doc(id).set(data); }
  update(id,patch){ return this.col().doc(id).update(patch); }
  remove(id){ return this.col().doc(id).delete(); }
  log(id,e){ return this.db.collection(`projects/${id}/log`).add(e); }
  subscribeLog(id,cb){ return this.db.collection(`projects/${id}/log`).orderBy("at","desc").limit(60).onSnapshot(s=>cb(s.docs.map(d=>clone(d.data()))),()=>{}); }
}
class LocalStore{
  constructor(){ this.k="chai-portfolio-local-v1"; this.d=this.load(); this.subs=[]; this.logSubs={}; }
  load(){ try{ return JSON.parse(localStorage.getItem(this.k)) || {projects:{},logs:{}}; }catch(e){ return {projects:{},logs:{}}; } }
  persist(){ try{ localStorage.setItem(this.k,JSON.stringify(this.d)); }catch(e){} }
  emit(){ const list=Object.entries(this.d.projects).map(([id,v])=>({id,...clone(v)})); this.subs.forEach(f=>setTimeout(()=>f(list))); }
  subscribeAll(cb){ this.subs.push(cb); this.emit(); return ()=>{ this.subs=this.subs.filter(x=>x!==cb); }; }
  async create(id,data){ this.d.projects[id]=clone(data); this.persist(); this.emit(); }
  async update(id,patch){ if(!this.d.projects[id]) throw {code:"invalid_argument"}; deepMerge(this.d.projects[id],patch); this.persist(); this.emit(); }
  async remove(id){ delete this.d.projects[id]; delete this.d.logs[id]; this.persist(); this.emit(); }
  async log(id,e){ const l=(this.d.logs[id]||(this.d.logs[id]=[])); l.unshift(e); this.d.logs[id]=l.slice(0,100); this.persist(); (this.logSubs[id]||[]).forEach(f=>setTimeout(()=>f(clone(this.d.logs[id])))); }
  subscribeLog(id,cb){ (this.logSubs[id]||(this.logSubs[id]=[])).push(cb); setTimeout(()=>cb(clone(this.d.logs[id]||[]))); return ()=>{ this.logSubs[id]=(this.logSubs[id]||[]).filter(x=>x!==cb); }; }
}

/* ApiStore: a self-hosted backend over REST + Server-Sent Events.

   Selected at boot when /api/health answers, which is true when the app is
   served by the Docker Compose stack and false for the GitHub Pages copy, so
   one build covers both. Identity comes from /api/me, established by the
   reverse proxy -- the browser cannot influence who it is, which is what makes
   a checkpoint sign-off here mean something that a localStorage one does not.

   Live updates: the server sends ids, not documents, so a change notification
   is small and never races a larger body. Each event triggers one refetch of
   the list. For a governance tool with tens of projects that is cheaper than
   reconciling partial state, and it cannot drift. */
class ApiStore{
  constructor(base){ this.base=base||"/api"; this.es=null; this.cbs=[]; this.cache=[]; }

  async req(path,opts){
    const r = await fetch(this.base+path, Object.assign({
      headers:{"Content-Type":"application/json"}, credentials:"same-origin"
    }, opts||{}));
    if(!r.ok){
      // Surface the API's own code so onDbError can tell a permission problem
      // from a conflict; the app already distinguishes them.
      const err = new Error(`${r.status} ${r.statusText}`);
      err.code = r.status===403||r.status===401 ? "permission_denied"
               : r.status===409 ? "already_exists"
               : r.status===404 ? "not_found" : "unavailable";
      throw err;
    }
    return r.status===204 ? null : r.json();
  }

  async refresh(){
    const list = await this.req("/projects");
    this.cache = Array.isArray(list) ? list : [];
    this.cbs.forEach(f=>{ try{ f(clone(this.cache)); }catch(e){} });
  }

  subscribeAll(cb,err){
    this.cbs.push(cb);
    this.refresh().catch(e=>{ if(err) err(e); });
    if(!this.es){
      this.es = new EventSource(this.base+"/events");
      // The server sends NAMED events ("event: project.created"). EventSource
      // fires onmessage only for events with no name, so a handler attached
      // there never runs and the page silently stops updating -- it still
      // works, because every local write re-renders, so the failure only shows
      // when a COLLEAGUE makes a change. Each name needs its own listener.
      ApiStore.EVENTS.forEach(name=>{
        this.es.addEventListener(name, ()=>{ this.refresh().catch(()=>{}); });
      });
      // EventSource reconnects on its own; a refresh on reopen closes the gap
      // of anything missed while disconnected.
      this.es.onopen = ()=>{ this.refresh().catch(()=>{}); };
      this.es.onerror = ()=>{};
    }
    return ()=>{ this.cbs = this.cbs.filter(f=>f!==cb); };
  }

  create(id,data){ return this.req(`/projects/${encodeURIComponent(id)}`,{method:"POST",body:JSON.stringify(data)}); }
  update(id,patch){ return this.req(`/projects/${encodeURIComponent(id)}`,{method:"PATCH",body:JSON.stringify(patch)}); }
  remove(id){ return this.req(`/projects/${encodeURIComponent(id)}`,{method:"DELETE"}); }
  log(id,e){ return this.req(`/projects/${encodeURIComponent(id)}/log`,{method:"POST",body:JSON.stringify(e)}); }

  subscribeLog(id,cb){
    let stop=false;
    const pull = ()=> this.req(`/projects/${encodeURIComponent(id)}/log`)
      .then(rows=>{ if(!stop && Array.isArray(rows)) cb(rows); }).catch(()=>{});
    pull();
    // The log is append-only and low-traffic, so it rides the same change
    // signal as the project list rather than opening a second stream.
    const onChange = ()=> pull();
    this.cbs.push(onChange);
    return ()=>{ stop=true; this.cbs = this.cbs.filter(f=>f!==onChange); };
  }
}

/* Event names the API emits. Keep in step with server/app/events.py. */
ApiStore.EVENTS = ["project.created","project.updated","project.deleted","log.appended","resync"];

/* Is a self-hosted backend serving this page? Short timeout: on GitHub Pages
   the request 404s immediately, and the user should not wait on it. */
async function detectApi(base){
  try{
    const ctl = new AbortController();
    const t = setTimeout(()=>ctl.abort(), 2500);
    const r = await fetch((base||"/api")+"/health",{signal:ctl.signal,credentials:"same-origin"});
    clearTimeout(t);
    if(!r.ok) return null;
    const j = await r.json();
    return j && j.status==="ok" ? j : null;
  }catch(e){ return null; }
}
