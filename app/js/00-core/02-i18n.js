/* ============================================================
   Core: languages (#80)
   Every string a person reads comes from a message catalog, app/i18n/<locale>.json,
   embedded by the build as I18N_CATALOGS. English is the source; a key missing from
   another catalog falls back to it. t() returns plain text: callers still esc() it
   into markup, and a catalog never holds HTML.

   Safety-bearing strings (the patient-data notice, the storage-mode banners, listed
   under "@meta".safety in en.json) are shown in English until a reviewer fluent in
   the language is recorded for them in that catalog's "@meta".reviewers. A wrong
   translation of a warning is worse than an English one (D-59).
   ============================================================ */
const Locale = Object.freeze({
  EN: "en", ES: "es", FR: "fr", DE: "de", HI: "hi", RU: "ru", ZH_HANS: "zh-Hans",
  HE: "he",
  PSEUDO: "en-XA",   // accented and padded English: shows what is still hard-coded
});
/* What the picker offers, each named in its own language. PSEUDO is not offered. */
const LOCALE_CHOICES = Object.freeze([
  Locale.EN, Locale.ES, Locale.FR, Locale.DE, Locale.HI, Locale.RU, Locale.ZH_HANS,
  Locale.HE,
]);
/* Languages written right to left. The layout uses logical properties
   (margin-inline-start, text-align:start), so setting <html dir> mirrors it;
   check-i18n refuses a left or right that would not (D-63). */
const RTL_LOCALES = new Set([Locale.HE]);
const localeDir = loc => (RTL_LOCALES.has(loc) ? "rtl" : "ltr");  // enum-ok: HTML dir attribute values
const LOCALE_KEY = "chai-locale";
/* The header's language picker, by element id, for the input handler. */
const HeaderControl = Object.freeze({ LANGUAGE: "lang" });

const catalogOf = loc => I18N_CATALOGS[loc] || null;
const SAFETY_KEYS = new Set(((I18N_CATALOGS[Locale.EN]["@meta"] || {}).safety) || []);

function isLocale(v){ return Object.values(Locale).includes(v); }

/* A saved choice, then the browser's languages, then English. zh-TW and zh-HK are
   Traditional Chinese, which this does not have, so they do not match zh-Hans. */
function resolveLocale(){
  try{ const saved = localStorage.getItem(LOCALE_KEY); if(isLocale(saved)) return saved; }catch(e){}
  const wanted = (navigator.languages && navigator.languages.length ? navigator.languages : [navigator.language || ""]);
  for(const raw of wanted){
    const tag = String(raw || "").toLowerCase();
    if(/^zh(-hans|-cn|-sg|$)/.test(tag) || tag.startsWith("zh-hans")) return Locale.ZH_HANS;  // enum-ok: BCP 47 subtags from navigator.languages
    if(tag.startsWith("zh")) continue;  // enum-ok: BCP 47 subtag; Traditional Chinese is not offered
    const primary = tag.split("-")[0] === "iw" ? Locale.HE : tag.split("-")[0];  // enum-ok: "iw" is the retired ISO 639 code for Hebrew, still sent by some browsers
    const hit = LOCALE_CHOICES.find(l => l === primary);
    if(hit) return hit;
  }
  return Locale.EN;
}
let LOCALE = resolveLocale();

/* The tag Intl understands for the current locale. */
const intlTag = () => (LOCALE === Locale.PSEUDO ? Locale.EN : LOCALE);

/* Accented, bracketed and about a third longer, with {placeholders} left intact. */
const PSEUDO_MAP = Object.freeze({a:"á",b:"ƀ",c:"ç",d:"đ",e:"é",f:"ƒ",g:"ĝ",h:"ĥ",i:"í",j:"ĵ",k:"ķ",l:"ĺ",
  m:"ɱ",n:"ñ",o:"ó",p:"þ",r:"ŕ",s:"š",t:"ţ",u:"ú",w:"ŵ",y:"ý",z:"ž",A:"Á",B:"Ɓ",C:"Ç",D:"Đ",E:"É",
  F:"Ƒ",G:"Ĝ",H:"Ĥ",I:"Í",J:"Ĵ",K:"Ķ",L:"Ĺ",N:"Ñ",O:"Ó",P:"Þ",R:"Ŕ",S:"Š",T:"Ţ",U:"Ú",W:"Ŵ",Y:"Ý",Z:"Ž"});
function pseudoize(s){
  const parts = String(s).split(/(\{\w+\})/);
  const body = parts.map(p => /^\{\w+\}$/.test(p) ? p : [...p].map(c => PSEUDO_MAP[c] || c).join("")).join("");
  return `[${body}${"~".repeat(Math.ceil(String(s).length * 0.3))}]`;
}

/* Is this key's translation in this locale allowed to show? */
function reviewedFor(loc, key){
  if(!SAFETY_KEYS.has(key)) return true;
  const meta = (catalogOf(loc) || {})["@meta"] || {};
  return Boolean((meta.reviewers || {})[key]);
}

/* The raw catalog entry for a key, and the locale it came from. */
function entryFor(key){
  if(LOCALE === Locale.PSEUDO) return [I18N_CATALOGS[Locale.EN][key], Locale.PSEUDO];
  const own = catalogOf(LOCALE);
  if(own && own[key] !== undefined && reviewedFor(LOCALE, key)) return [own[key], LOCALE];
  return [I18N_CATALOGS[Locale.EN][key], Locale.EN];
}

/* A message, in the current language, with {name} placeholders filled. A plural
   message is an object keyed by Intl.PluralRules category and picks by params.count. */
function t(key, params){
  let [entry, from] = entryFor(key);
  if(entry && typeof entry === "object"){
    const tag = from === Locale.PSEUDO ? Locale.EN : from;
    const n = params && typeof params.count === "number" ? params.count : 0;
    entry = entry[new Intl.PluralRules(tag).select(n)] ?? entry.other;
  }
  if(typeof entry !== "string") return key;   // a missing key shows itself; tests catch it
  let out = from === Locale.PSEUDO ? pseudoize(entry) : entry;
  out = out.replace(/\{(\w+)\}/g, (m, k) => (params && k in params ? String(params[k]) : m));
  // English shown in a right-to-left page (an unreviewed warning, a missing key) is
  // isolated left to right, so its punctuation stays where English puts it (D-63).
  return from === Locale.EN && RTL_LOCALES.has(LOCALE) ? `\u2066${out}\u2069` : out;
}

/* A message as HTML: the text is escaped, and each `html` param (markup the caller
   built and escaped itself, such as a person's name tag) is placed where its
   {placeholder} was. */
function tHtml(key, params, html){
  const p = Object.assign({}, params);
  const marks = Object.keys(html || {}).map((k, i) => { const m = `\u0001${i}\u0001`; p[k] = m; return [m, html[k]]; });
  let out = esc(t(key, p));
  for(const [m, h] of marks) out = out.split(m).join(h);
  return out;
}

/* Framework content (CHAI, OPTICA): the English lives in the definitions, which stay
   the source of truth; FRAMEWORK_I18N[locale][key] translates it (D-60). A key with
   no translation shows the English. Stored values never go through this. */
function tf(key, english){
  if(LOCALE === Locale.EN) return english;
  if(LOCALE === Locale.PSEUDO) return pseudoize(english);
  const own = (typeof FRAMEWORK_I18N === "object" && FRAMEWORK_I18N[LOCALE]) || {};
  if(typeof own[key] === "string" && own[key]) return own[key];
  // A framework with no translation into this language shows its English, isolated
  // left to right in a right-to-left page as t() does (D-63).
  return RTL_LOCALES.has(LOCALE) ? `\u2066${english}\u2069` : english;
}
/* Is framework wording on screen a translation? Then it says so (D-60). */
const frameworkTranslated = () => LOCALE !== Locale.EN && LOCALE !== Locale.PSEUDO;
/* Which languages each framework in this build is translated into (the build fills
   FRAMEWORK_LOCALES). A developer's framework may bring only English (R-65). */
const frameworkHasLocale = (id, loc) =>
  ((typeof FRAMEWORK_LOCALES === "object" && FRAMEWORK_LOCALES[id]) || []).includes(loc);
/* The note under translated framework wording, per framework: its own (CHAI's and
   OPTICA's name their zh-Hans reviewer), or the engine's neutral one; and, when the
   framework has no translation into the reader's language, a note that its words
   are shown in English. */
const fwNoteHTML = F => {
  if(!frameworkTranslated()) return "";
  const fac = F || primaryFramework().facade;
  const key = frameworkHasLocale(fac.id, LOCALE) ? fac.slot(UiSlot.FW_NOTE) : "engine.fw.untranslated";
  return `<p class="fw-note small" role="note">${esc(t(key))}</p>`;
};

/* English whatever the reader chose: for machine contracts (JSON, CSV headers) and
   anything an export must keep stable. */
function tEn(key, params){ return withLocale(Locale.EN, () => t(key, params)); }

/* Run `fn` as if the reader had chosen `loc`: an export renders in English whatever
   the screen shows, until exports are translated in their own right (R-55). */
function withLocale(loc, fn){
  const saved = LOCALE; LOCALE = loc;
  try{ return fn(); } finally { LOCALE = saved; }
}

/* Static markup in app/index.html names its keys: data-i18n for text, and
   data-i18n-aria / data-i18n-placeholder / data-i18n-title for attributes. */
function applyStaticI18n(root){
  (root || document).querySelectorAll("[data-i18n]").forEach(el => { el.textContent = t(el.dataset.i18n); });
  (root || document).querySelectorAll("[data-i18n-aria]").forEach(el => el.setAttribute("aria-label", t(el.dataset.i18nAria)));
  (root || document).querySelectorAll("[data-i18n-placeholder]").forEach(el => el.setAttribute("placeholder", t(el.dataset.i18nPlaceholder)));
  (root || document).querySelectorAll("[data-i18n-title]").forEach(el => el.setAttribute("title", t(el.dataset.i18nTitle)));
  document.documentElement.lang = LOCALE;
  document.documentElement.dir = localeDir(LOCALE);
}

/* The language picker's options: each name in its own language, marked as such. */
function localeOptions(){
  return LOCALE_CHOICES.map(loc => {
    const name = ((catalogOf(loc) || {})["@meta"] || {}).name || loc;
    return `<option value="${esc(loc)}" lang="${esc(loc)}"${loc === LOCALE ? " selected" : ""}>${esc(name)}</option>`;
  }).join("");
}

function setLocale(loc){
  if(!isLocale(loc)) return;
  LOCALE = loc;
  try{ localStorage.setItem(LOCALE_KEY, loc); }catch(e){}
}
