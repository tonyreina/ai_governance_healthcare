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
