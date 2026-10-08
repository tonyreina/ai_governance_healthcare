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
  persist(){
    try{ localStorage.setItem(this.k,JSON.stringify(this.d)); return true; }
    catch(e){
      // A full or blocked browser store used to fail here without a word, so the
      // user kept working in a session that was not saving (#40). Say so.
      if(typeof toast==="function") toast(t("toast.storageFull"));
      return false;
    }
  }
  emit(){ const list=Object.entries(this.d.projects).map(([id,v])=>({id,...clone(v)})); this.subs.forEach(f=>setTimeout(()=>f(list))); }
  subscribeAll(cb){ this.subs.push(cb); this.emit(); return ()=>{ this.subs=this.subs.filter(x=>x!==cb); }; }
  async create(id,data){ this.d.projects[id]=clone(data); this.persist(); this.emit(); }
  async update(id,patch){ if(!this.d.projects[id]) throw {code:"invalid_argument"}; deepMerge(this.d.projects[id],patch); this.persist(); this.emit(); }
  async remove(id){ delete this.d.projects[id]; delete this.d.logs[id]; this.persist(); this.emit(); }
  /* Keeps every entry. It used to keep 100 and DELETE the rest, so in browser-only
     mode entry 101 was not hidden from a view, it was gone (#40). The browser's
     own quota is the limit, and persist() says when it is reached. */
  async log(id,e){ const l=(this.d.logs[id]||(this.d.logs[id]=[])); l.unshift(e); this.persist(); this.emitLog(id); }
  emitLog(id){ (this.logSubs[id]||[]).forEach(f=>setTimeout(()=>{ const l=clone(this.d.logs[id]||[]); f(l,{total:l.length}); })); }
  subscribeLog(id,cb){ (this.logSubs[id]||(this.logSubs[id]=[])).push(cb); setTimeout(()=>{ const l=clone(this.d.logs[id]||[]); cb(l,{total:l.length}); }); return ()=>{ this.logSubs[id]=(this.logSubs[id]||[]).filter(x=>x!==cb); }; }
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
/* A row of a project's litigation-hold history (server/app/retention.py HoldAction). */
const HoldAction = Object.freeze({ PLACE: "place", LIFT: "lift" });

class ApiStore{
  constructor(base){ this.base=base||"/api"; this.es=null; this.cbs=[]; this.cache=[]; this.logDepth={}; this.logPulls={}; }

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
      // EventSource reconnects by itself while readyState is CONNECTING. It gives
      // up (CLOSED) when the server answers the reconnect with an error, which is
      // what a session that has ended looks like: the front door refuses it. That
      // used to be swallowed, so the page went on looking live and never updated
      // again (#49). Report it, so the app can say it is disconnected.
      const ES_CLOSED = 2;  // enum-ok: EventSource's own readyState value
      this.es.onerror = ()=>{ if(this.es && this.es.readyState===ES_CLOSED && err) err({code:"stream_closed"}); };
    }
    return ()=>{ this.cbs = this.cbs.filter(f=>f!==cb); };
  }

  create(id,data){ return this.req(`/projects/${encodeURIComponent(id)}`,{method:"POST",body:JSON.stringify(data)}); }
  update(id,patch){ return this.req(`/projects/${encodeURIComponent(id)}`,{method:"PATCH",body:JSON.stringify(patch)}); }
  remove(id){ return this.req(`/projects/${encodeURIComponent(id)}`,{method:"DELETE"}); }
  /* Destroy the content of every retained revision AND of the audit log. Owner
     only, irreversible, and a SEPARATE step from remove(): deleting a project keeps
     its version history on purpose, so deletion alone is not erasure (#36). Only
     this store has it, because only the server keeps a history; the dialog offers
     the choice when, and only when, this method exists. */
  purgeVersions(id){ return this.req(`/projects/${encodeURIComponent(id)}/versions`,{method:"DELETE"}); }
  log(id,e){ return this.req(`/projects/${encodeURIComponent(id)}/log`,{method:"POST",body:JSON.stringify(e)}); }
  /* Litigation holds (#57, R-56): whether disposal at the end of the retention
     period is stopped for this project. Owner only, and only here, because only
     the server ever disposes of anything. */
  getHold(id){ return this.req(`/projects/${encodeURIComponent(id)}/hold`); }
  setHold(id,action,reason){ return this.req(`/projects/${encodeURIComponent(id)}/hold`,{method:"POST",body:JSON.stringify({action,reason})}); }

  /* The log arrives as a WINDOW: the newest page, with the project's total in
     X-Log-Total so a view or an export can say "newest 60 of 412". showOlderLog
     asks for a deeper page, up to the server's cap (500); older than that is
     reached through the API's `before` cursor, not through this view (#40). */
  subscribeLog(id,cb){
    let stop=false;
    const pull = async ()=>{
      try{
        const depth = this.logDepth[id];
        const r = await fetch(this.base+`/projects/${encodeURIComponent(id)}/log`+(depth?`?limit=${depth}`:""),
          {headers:{"Content-Type":"application/json"}, credentials:"same-origin"});
        if(!r.ok) return;
        const rows = await r.json();
        const total = parseInt(r.headers.get("X-Log-Total"),10);
        if(!stop && Array.isArray(rows)) cb(rows,{total:Number.isFinite(total)?total:null});
      }catch(e){}
    };
    this.logPulls[id] = pull;
    pull();
    // The log is append-only and low-traffic, so it rides the same change
    // signal as the project list rather than opening a second stream.
    const onChange = ()=> pull();
    this.cbs.push(onChange);
    return ()=>{ stop=true; delete this.logPulls[id]; this.cbs = this.cbs.filter(f=>f!==onChange); };
  }
  /* Names for identity ids, in the shape the Claude runtime's profiles() answers
     so resolveNames needs no second path: {id: {name, email, isMe}}. The server
     answers only for people the caller can already see on a project they can read,
     and omits the rest, so an absent id is "unknown", not an error. Batches are
     capped by the server (100). (#39) */
  async profiles(ids){
    const out={};
    const unique=[...new Set((ids||[]).filter(Boolean))];
    for(let i=0;i<unique.length;i+=100){
      const chunk=unique.slice(i,i+100);
      const rows=await this.req(`/principals?ids=${encodeURIComponent(chunk.join(","))}`);
      (Array.isArray(rows)?rows:[]).forEach(p=>{ out[p.id]={name:p.name||"", email:p.email||"", isMe:p.id===ME.id}; });
    }
    return out;
  }
  /* Tell the server an export was produced (#33). Exports are built here from data
     already fetched, so it cannot see one happen; this is the record of ordinary
     use, not a control, because a client can omit it. id is null for the portfolio
     CSV. */
  recordExport(id,format){
    const path = id ? `/projects/${encodeURIComponent(id)}/exports` : "/exports";
    return this.req(path,{method:"POST",body:JSON.stringify({format})});
  }
  showOlderLog(id){
    this.logDepth[id] = Math.min(500, (this.logDepth[id]||60) + 60);
    const pull = this.logPulls[id];
    return pull ? pull() : Promise.resolve();
  }
}

/* Event names the API emits. Keep in step with server/app/events.py. */
ApiStore.EVENTS = ["project.created","project.updated","project.deleted","log.appended","resync"];

/* Is a self-hosted backend serving this page, and if not, WHY not?

   This used to return null for every failure, and boot treated null as
   "no server here, use localStorage". That conflated three situations that
   must not be treated alike:

     - a genuinely static host (GitHub Pages, a file:// open) -- localStorage
       is correct;
     - a self-hosted stack whose API is restarting, slow, or behind a proxy
       having a bad minute -- falling back silently strands the user's work in
       a browser-local store their colleagues cannot see and no audit log
       records;
     - a self-hosted stack that AUTHENTICATED the user and said NO (401/403) --
       falling back hands a denied user a working private workspace, which is
       access control failing open.

   So the verdict is explicit and boot decides. Verdicts:

     ok          a healthy API answered; `health` carries its payload
     denied      the front door or the API refused this user (401/403)
     unreachable something is there but did not answer in time
     error       something answered with a server error
     absent      nothing API-shaped here; a static host

   Short timeout because on a static host the request 404s immediately and the
   user should not wait on it. */
async function detectApi(base){
  base = base || "/api";
  try{
    const ctl = new AbortController();
    const t = setTimeout(()=>ctl.abort(), 2500);
    const r = await fetch(base+"/health",{signal:ctl.signal,credentials:"same-origin"});
    clearTimeout(t);
    if(r.status===401 || r.status===403) return {verdict:"denied", status:r.status};
    if(r.status>=500) return {verdict:"error", status:r.status};
    if(!r.ok) return {verdict:"absent", status:r.status};
    // A static host serving an HTML 404 page with a 200, or anything else
    // that is not our health payload, lands in the catch below or here.
    const j = await r.json();
    return j && j.status==="ok" ? {verdict:"ok", health:j} : {verdict:"absent"};
  }catch(e){
    // AbortError means the timeout fired: something may well be there. A
    // network TypeError or a JSON parse failure means there is nothing
    // API-shaped at this origin.
    return {verdict: (e && e.name==="AbortError") ? "unreachable" : "absent"};
  }
}

/* Has this origin ever served a working API to this browser?

   Without this, a self-hosted deployment whose API is down for thirty seconds
   is indistinguishable from GitHub Pages, and the safe choice would be to
   refuse to start anywhere -- including on the static host where localStorage
   is the whole point. Remembering that we have seen a real API here lets the
   app refuse in the one place refusing is right.

   A per-origin key, because the same build is served from both. */
const API_SEEN_KEY = "chai-api-origin-seen";
function apiSeenHere(){
  try{ return localStorage.getItem(API_SEEN_KEY) === location.origin; }
  catch(e){ return false; }
}
function rememberApiHere(){
  try{ localStorage.setItem(API_SEEN_KEY, location.origin); }catch(e){}
}
