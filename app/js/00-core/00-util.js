/* ============================================================
   Utilities
   ============================================================ */
const esc = s => String(s ?? "").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const clone = o => o==null ? o : JSON.parse(JSON.stringify(o));
const isObj = v => v && typeof v==="object" && !Array.isArray(v);
function deepMerge(t,src){ for(const k in src){ if(isObj(src[k]) && isObj(t[k])) deepMerge(t[k],src[k]); else t[k]=clone(src[k]); } return t; }
function pad(n){return String(n).padStart(2,"0");}
function ymd(d){ return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}`; }
const TODAY = ()=> ymd(new Date());
function parseDay(s){ if(!s||!/^\d{4}-\d{2}-\d{2}/.test(s)) return null; const d=new Date(s.slice(0,10)+"T00:00:00"); return isNaN(d)?null:d; }
function addDays(d,n){ const x=new Date(d); x.setDate(x.getDate()+n); return x; }
function addMonths(d,n){ const x=new Date(d); x.setMonth(x.getMonth()+n); return x; }
function daysBetween(a,b){ return Math.round((b-a)/86400000); }
function fmtDay(s){ const d=parseDay(s); return d? d.toLocaleDateString(undefined,{year:"numeric",month:"short",day:"numeric"}) : ""; }
function ago(iso){ if(!iso) return ""; const d=new Date(iso); if(isNaN(d)) return ""; const m=Math.round((Date.now()-d)/60000);
  if(m<1) return "just now"; if(m<60) return `${m} min ago`; const h=Math.round(m/60); if(h<24) return `${h} h ago`; const dd=Math.round(h/24); if(dd<45) return `${dd} days ago`; return fmtDay(iso.slice(0,10)); }
let _idSeq = 0;
const newId = ()=> "p"+Date.now().toString(36)+Math.random().toString(36).slice(2,7)+(_idSeq++).toString(36);
