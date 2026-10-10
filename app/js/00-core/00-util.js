/* ============================================================
   Utilities
   ============================================================ */
const esc = s => String(s ?? "").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
/* What a person typed, escaped and isolated: <bdi> takes its direction from its own
   text, so an English name keeps its punctuation in a Hebrew page and a Hebrew one
   in an English page (D-63). For element content only, never an attribute. */
const bdi = s => `<bdi>${esc(s)}</bdi>`;
/* The default of a switch over a closed set: a member added without a case here
   fails the first time it runs, not by quietly rendering nothing. */
function assertNever(v){ throw new Error("unhandled member: " + String(v)); }
/* Fields of an item or answer that this code branches on by name. */
const Field = Object.freeze({ REFS: "refs" });
const clone = o => o==null ? o : JSON.parse(JSON.stringify(o));
const isObj = v => v && typeof v==="object" && !Array.isArray(v);
/* Keys that reach an object's prototype instead of a property of its own. JSON.parse
   makes "__proto__" an ordinary own key, so a document that carries one would, on a
   naive merge or path assignment, write into Object.prototype for every object on the
   page (CodeQL js/prototype-pollution-utility, #124). Every helper that walks or
   writes by key skips them. */
const UNSAFE_KEYS = Object.freeze(new Set(["__proto__", "constructor", "prototype"]));
const safeKey = k => !UNSAFE_KEYS.has(k);
function deepMerge(t,src){ for(const k in src){ if(!Object.hasOwn(src,k) || !safeKey(k)) continue; if(isObj(src[k]) && isObj(t[k])) deepMerge(t[k],src[k]); else t[k]=clone(src[k]); } return t; }
function pad(n){return String(n).padStart(2,"0");}
function ymd(d){ return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}`; }
const TODAY = ()=> ymd(new Date());
function parseDay(s){ if(!s||!/^\d{4}-\d{2}-\d{2}/.test(s)) return null; const d=new Date(s.slice(0,10)+"T00:00:00"); return isNaN(d)?null:d; }
function addDays(d,n){ const x=new Date(d); x.setDate(x.getDate()+n); return x; }
function addMonths(d,n){ const x=new Date(d); x.setMonth(x.getMonth()+n); return x; }
function daysBetween(a,b){ return Math.round((b-a)/86400000); }
/* Dates and relative times in the reader's chosen language (02-i18n.js), not the
   browser's, so the text around a date and the date itself cannot disagree. */
function fmtDay(s){ const d=parseDay(s); return d? new Intl.DateTimeFormat(intlTag(),{year:"numeric",month:"short",day:"numeric"}).format(d) : ""; }
function ago(iso){ if(!iso) return ""; const d=new Date(iso); if(isNaN(d)) return ""; const m=Math.round((Date.now()-d)/60000);
  const rel=new Intl.RelativeTimeFormat(intlTag(),{numeric:"auto"});
  if(m<1) return rel.format(0,"minute"); if(m<60) return rel.format(-m,"minute"); const h=Math.round(m/60); if(h<24) return rel.format(-h,"hour"); const dd=Math.round(h/24); if(dd<45) return rel.format(-dd,"day"); return fmtDay(iso.slice(0,10)); }
let _idSeq = 0;
const newId = ()=> "p"+Date.now().toString(36)+Math.random().toString(36).slice(2,7)+(_idSeq++).toString(36);
