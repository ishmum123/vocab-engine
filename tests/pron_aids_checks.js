// Checks for brief BP2, the pronunciation aids (docs/PACK_SCHEMA.md "Pronunciation aids",
// docs/HSK_MERGE.md §8): [1] tone colouring (pack.tones), [2] typed reading (pack.typing
// "pron"), [3] word taps inside sentences (sentences with ruby), [4] the Sounds Reference
// card (pack.soundsReference), [5] phrase-span readings and popover heads in passages, [6]
// sentence-start capitals, [7] control: with the BP2 fields absent the HTML is byte-identical
// to main 55c843e's engine for a Today walk, sentence rows, a Words page and a Read passage.
// Boots engine/app.html's inline script against the zh pack as shipped with the same fake
// DOM as tests/characters_app_checks.js (id registry + regex scan of innerHTML).
// Run: node tests/pron_aids_checks.js
"use strict";
const fs = require("fs");
const path = require("path");
const cp = require("child_process");

const ROOT = path.join(__dirname, "..");
const VC = require(path.join(ROOT, "engine", "core.js"));
const ZH = path.join(ROOT, "packs", "zh");
const MAIN = "55c843e"; // BP merged: the engine before BP2
function loadConst(file, name){ return new Function(fs.readFileSync(file, "utf8") + `\nreturn ${name};`)(); }
const PACK = loadConst(path.join(ZH, "pack.js"), "PACK");
const WORDS = loadConst(path.join(ZH, "words.js"), "WORDS");
const SENTENCES = loadConst(path.join(ZH, "sentences.js"), "SENTENCES");
const PASSAGES = loadConst(path.join(ZH, "sentences.js"), "PASSAGES");
const LESSONS = loadConst(path.join(ZH, "lessons.js"), "LESSONS");
const CHARACTERS = loadConst(path.join(ZH, "characters.js"), "CHARACTERS");
const BY_ID = Object.fromEntries(WORDS.map(w => [w.id, w]));
console.log(`Loaded zh pack: ${WORDS.length} words, ${SENTENCES.length} sentences, ${PASSAGES.length} passages, ${CHARACTERS.length} units`);

let fails = 0, passes = 0;
function check(name, cond){
  if(cond){ passes++; console.log(`PASS  ${name}`); }
  else { fails++; console.log(`FAIL  ${name}`); }
}

// ------------------------------------------------------------------ fake DOM (copied from characters_app_checks.js)
let appHtml = fs.readFileSync(path.join(ROOT, "engine", "app.html"), "utf8");
const CUR_HTML = appHtml;
const scriptOf = html => { const b = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)]; return b[b.length - 1][1]; };
function extractAttrs(tag){
  const attrs = {}; const re = /([a-zA-Z_:][-a-zA-Z0-9_:.]*)(?:\s*=\s*"([^"]*)")?/g;
  let m; while((m = re.exec(tag))){ if(m[1]) attrs[m[1]] = m[2] !== undefined ? m[2] : ""; }
  return attrs;
}
function makeFakeDom(){
  const registry = new Map(); const tabButtons = [];
  class El {
    constructor(tag, attrs){
      this.tagName = (tag||"div").toUpperCase();
      this._attrs = Object.assign({}, attrs);
      this._classes = new Set((this._attrs.class||"").split(/\s+/).filter(Boolean));
      this._html = ""; this._text = "";
      this.style = { setProperty(k,v){ this[k]=v; } };
      this.hidden = false; this.disabled = false; this.value = "";
      this.onclick = null; this.oninput = null; this.onchange = null;
      this._listeners = {}; this._children = [];
      if(this._attrs.id) registry.set(this._attrs.id, this);
    }
    get id(){ return this._attrs.id || ""; }
    set id(v){ this._attrs.id = v; registry.set(v, this); }
    get classList(){
      const s = this._classes;
      return { add:(...c)=>c.forEach(x=>s.add(x)), remove:(...c)=>c.forEach(x=>s.delete(x)),
        toggle:(c,f)=>{ if(f===undefined){ s.has(c)?s.delete(c):s.add(c); } else { f?s.add(c):s.delete(c); } },
        contains:c=>s.has(c) };
    }
    get dataset(){
      const attrs = this._attrs; const toKebab = k => k.replace(/[A-Z]/g, m => "-" + m.toLowerCase());
      return new Proxy({}, { get(_, k){ return attrs["data-" + toKebab(String(k))]; }, set(_, k, v){ attrs["data-" + toKebab(String(k))] = String(v); return true; } });
    }
    get children(){ return this._children; }
    get innerHTML(){ return this._html; }
    set innerHTML(h){ this._html = h; this._children = []; registerIdsFromHtml(h); }
    get textContent(){ return this._text; }
    set textContent(t){ this._text = String(t); this._html = String(t); }
    setAttribute(k,v){ this._attrs[k]=String(v); if(k==="id") registry.set(v,this); }
    getAttribute(k){ return this._attrs[k]; }
    addEventListener(t,f){ (this._listeners[t]=this._listeners[t]||[]).push(f); }
    removeEventListener(){}
    appendChild(c){ this._children.push(c); return c; }
    remove(){}
    focus(){}
    click(){ if(this.onclick) this.onclick({}); (this._listeners.click||[]).forEach(f=>f({})); }
    closest(){ return null; }
    querySelector(){ return null; }
    querySelectorAll(){ return []; }
  }
  function registerIdsFromHtml(html){
    const re = /<([a-zA-Z0-9]+)((?:\s+[a-zA-Z_:][-a-zA-Z0-9_:.]*(?:\s*=\s*"[^"]*")?)*)\s*\/?>/g;
    let m; while((m = re.exec(html))){ const attrs = extractAttrs(m[2]); if(attrs.id) new El(m[1], attrs); }
  }
  const tabsMatch = appHtml.match(/<nav[^>]*id="tabs"[^>]*>([\s\S]*?)<\/nav>/);
  const btnRe = /<button([^>]*)>/g;
  let bm; while((bm = btnRe.exec(tabsMatch[1]))){ tabButtons.push(new El("button", extractAttrs(bm[1]))); }
  registerIdsFromHtml(appHtml.slice(appHtml.indexOf("<body>"), appHtml.indexOf("<nav")));
  return {
    title: "", head: { appended: [], appendChild(c){ this.appended.push(c); return c; } }, body: new El("body", {}), documentElement: new El("html", {}),
    write(){}, createElement(tag){ return new El(tag, {}); },
    getElementById(id){ return registry.get(id) || null; },
    querySelector(sel){ return this.querySelectorAll(sel)[0] || null; },
    querySelectorAll(sel){
      const m = sel.match(/^#tabs\s+button(?:\[data-t="([^"]+)"\])?$/);
      if(m) return m[1] ? tabButtons.filter(b=>b.dataset.t===m[1]) : tabButtons.slice();
      return [];
    },
    _listeners: {},
    addEventListener(t,f){ (this._listeners[t]=this._listeners[t]||[]).push(f); },
  };
}
const tick = () => new Promise(r => setTimeout(r, 0));
function mulberry32(seed){
  let a = seed >>> 0;
  return function(){ a |= 0; a = (a + 0x6D2B79F5) | 0; let t = Math.imul(a ^ (a >>> 15), 1 | a); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
}
// Boots an app. opts: html (app.html text, default this tree's), core (VocabCore, default
// this tree's), pack, words, sentences, passages, units (false: no CHARACTERS), seed
// (Math.random is replaced by a seeded generator for the boot and everything after it,
// until the next boot). spoken: every text passed to speechSynthesis.speak.
const REAL_RANDOM = Math.random;
async function boot(opts){
  const o = opts || {};
  Math.random = o.seed ? mulberry32(o.seed) : REAL_RANDOM;
  appHtml = o.html || CUR_HTML;
  const document = makeFakeDom();
  const spoken = [];
  const ss = { getVoices: () => o.voices || [{ lang:"zh-CN", name:"x" }], onvoiceschanged: null, cancel(){}, speak(u){ spoken.push(u.text); } };
  const window = { VocabCore: o.core || VC, speechSynthesis: ss, SpeechSynthesisUtterance: function(t){ this.text = t; }, addEventListener(){} };
  const localStorage = { getItem(){ return null; }, setItem(){} };
  const hook = n => `typeof ${n} === "function" ? ${n} : null`;
  const fnBody = scriptOf(appHtml) + `
let __cur = null;
const __mc = renderMcItem; renderMcItem = function(it){ __cur = it; return __mc(it); };
const __ty = renderTypeItem; renderTypeItem = function(it){ __cur = it; return __ty(it); };
return {
  html: id => { const e = document.getElementById(id); return e ? e.innerHTML : null; },
  el: id => document.getElementById(id),
  getProg: () => prog, setProg: p => { prog = p; },
  today: () => { tab = "today"; render(); }, goto: t => { tab = t; testSel = null; RD = null; soundsSel = null; render(); },
  getD: () => D, getCur: () => __cur, panelListeners: t => document.getElementById("panel")._listeners[t || "click"] || [],
  startPassage: p => { tab = "read"; startPassage(p); }, rd: () => RD,
  sentenceRowHTML, sentenceRevealBlock, readSentence, gapSentence, passageSentenceHTML, passagePlainHTML, glossHTML, revealBlock, recallItem, readItem, wordRowHTML, charTeach, charDrillItem,
  itemFromPlan: ${hook("itemFromPlan")}, tokTap: ${hook("tokTap")}, onTok: ${hook("onTok")}, tokOwns: ${hook("tokOwns")}, docListeners: t => document._listeners[t] || [], soundsRefGroups: ${hook("soundsRefGroups")},
  drill1: it => drill([it], () => {}, null),
  wordsPage: (lv, set) => { tab = "words"; wordsQuery = ""; wordsLv = lv; wordsSet = set; render(); },
};`;
  const names = ["SpeechSynthesisUtterance","document","window","navigator","location","localStorage","matchMedia","requestAnimationFrame","Audio","confirm","alert","PACK","WORDS","SENTENCES","LESSONS","PASSAGES"];
  const args = [window.SpeechSynthesisUtterance, document, window, { userAgent:"PronAidsChecks/1.0" }, undefined, localStorage, () => ({ matches:false }), fn => setTimeout(fn, 0),
    function(){ return { play(){ return Promise.resolve(); }, pause(){} }; }, () => true, () => {}, o.pack || PACK, o.words || WORDS, o.sentences || SENTENCES, LESSONS, o.passages || PASSAGES];
  if(o.units !== false){ names.push("CHARACTERS"); args.push(o.units || CHARACTERS); }
  const api = new Function(...names, fnBody)(...args);
  await tick(); await tick();
  return { api, document, spoken };
}

// ------------------------------------------------------------------ helpers
const stripTags = h => h.replace(/<rt[^>]*>[\s\S]*?<\/rt>/g, "").replace(/<[^>]+>/g, "").replace(/&lt;/g,"<").replace(/&gt;/g,">").replace(/&quot;/g,'"').replace(/&#39;/g,"'").replace(/&amp;/g,"&");
const unesc = t => t.replace(/&lt;/g,"<").replace(/&gt;/g,">").replace(/&quot;/g,'"').replace(/&#39;/g,"'").replace(/&amp;/g,"&");
const MARKED = /[āáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜ]/i;
const HAN = /\p{Script=Han}/u;
const hanCount = t => [...String(t)].filter(c => HAN.test(c)).length;
// English text of the pack (glosses, translations, span glosses, questions): some glosses
// quote a reading ("also pr. [shuí]"); that text is a gloss, not a displayed reading.
const ENGLISH = [...WORDS.map(w => w.en), ...SENTENCES.map(s => s.en),
  ...PASSAGES.flatMap(p => [p.title, ...p.sentences.flatMap(s => [s.en, ...(s.spans || []).map(x => x[3] || "")]), ...p.questions.flatMap(q => [q.q, q.en || "", ...(q.options || [])])]),
  ...LESSONS.flatMap(l => [l.title, l.blurb, ...l.cards.flatMap(c => [c.h, c.body, ...(c.rows || []).flat()]), ...l.items.flatMap(it => [it.q, it.rv || "", ...(it.opts || [])])])].join("\n");
// Text nodes that show a tone-marked letter outside a <span class="tN"> (a reading shown
// uncoloured). Text that occurs in the pack's English is a gloss, not a reading.
function uncoloured(html){
  const h = String(html).replace(/<span class="t[1-5]">[^<]*<\/span>/g, "");
  return h.split(/<[^>]+>/).map(unesc).map(x => x.trim()).filter(x => x && MARKED.test(x) && !ENGLISH.includes(x));
}
const tspans = h => (String(h).match(/<span class="t[1-5]">/g) || []).length;
const syllables = t => VC.splitReading(t).filter(p => p.tone).reduce((n, p) => n + (/r$/i.test(VC.stripMarks(p.text)) && !/^er$/i.test(VC.stripMarks(p.text)) && !VC.splitSyllable(VC.stripMarks(p.text)) ? 2 : 1), 0);
const byLv = VC.wordsByLevel(WORDS, PACK);
const NS = lv => VC.nSets(byLv[lv], VC.setSizeOf(PACK));
const seedPF = () => VC.normalizeProg({ sets: { "1": NS("1"), "2": 2 }, placedOnce: true, sessions: 5 }, PACK);
// Plays the active flow: answers every item right (mc: the answer option; type: the
// word's pron), presses Continue / Drill / Next; records every screen, option and reveal.
function walk(api, stopAt){
  const seen = [];
  for(let i = 0; i < 600; i++){
    const P = api.html("panel");
    if(api.getD()){
      const it = api.getCur();
      if(it.kind === "type"){
        seen.push({ where: it.key, kind: "type", it, html: P });
        const w = BY_ID[it.key.slice(2)];
        api.el("tin").value = it.label === "Type the pinyin" ? w.pron : w.w; api.el("submit").click();
        seen.push({ where: it.key + " reveal", html: api.html("rv") }); api.el("nx").click(); continue;
      }
      const btns = api.el("o").children;
      seen.push({ where: it.key, kind: "mc", it, html: P + btns.map(b => b.innerHTML).join("|"), opts: btns.map(b => b.innerHTML) });
      const btn = btns.find(b => b.dataset.v === it.a); if(!btn) throw new Error("no answer option " + it.key);
      btn.click(); seen.push({ where: it.key + " reveal", html: api.html("rv") }); api.el("nx").click(); continue;
    }
    seen.push({ where: "screen", html: P });
    if(stopAt && stopAt.test(P)) return seen;
    if(/id="ok"/.test(P)){ api.el("ok").click(); continue; }
    if(/id="dr"/.test(P)){ const tl = api.el("tl"); if(tl) seen.push({ where: "teach", html: tl.children.map(c => c.innerHTML).join("|") }); api.el("dr").click(); continue; }
    return seen;
  }
  throw new Error("walk did not finish");
}

(async function main(){
  // ---------------------------------------------------------------- [1] tones: core
  console.log("\n[1] tone colouring: core helpers (pack.tones)");
  try {
    check("zh pack.json ships tones \"pinyin\", typing \"pron\", soundsReference true", PACK.tones === "pinyin" && PACK.typing === "pron" && PACK.soundsReference === true);
    check("tonesOn: only a non-empty string turns it on", VC.tonesOn(PACK) && !VC.tonesOn({}) && !VC.tonesOn({ tones: "" }) && !VC.tonesOn({ tones: true }) && !VC.tonesOn(null));
    // Every reading in the pack splits into syllables, one per written character (an
    // r-suffixed syllable is two: 一点儿 yìdiǎnr).
    let bad = [];
    WORDS.forEach(w => { if(hanCount(w.w) !== syllables(w.pron)) bad.push(`${w.w} ${w.pron}`); });
    SENTENCES.forEach(s => (s.ruby || []).forEach(r => { if(hanCount(s.t.slice(r[0], r[1])) !== syllables(r[2])) bad.push(`${s.id} ${r[2]}`); }));
    CHARACTERS.forEach(u => { if(hanCount(u.t) !== syllables(u.reading)) bad.push(`${u.id} ${u.reading}`); });
    check(`every word pron, sentence ruby reading and unit reading splits into one syllable per character (${bad.length} bad${bad[0] ? ": " + bad.slice(0, 3).join(", ") : ""})`, bad.length === 0);
    // markSyllable (the ported placement rule) rebuilds every syllable from its letters and tone.
    let mb = 0;
    WORDS.forEach(w => VC.splitReading(w.pron).filter(p => p.tone && p.tone < 5).forEach(p => { if(VC.markSyllable(VC.stripMarks(p.text), p.tone) !== p.text) mb++; }));
    check(`markSyllable re-marks every toned syllable of every word pron exactly (${mb} bad)`, mb === 0);
    check("splitSyllable: initial/final split, null outside the inventory", JSON.stringify(VC.splitSyllable("zhuang")) === '{"initial":"zh","final":"uang"}' && JSON.stringify(VC.splitSyllable("er")) === '{"initial":"","final":"er"}' && VC.splitSyllable("xo") === null);
    check("toneHTML: one span per syllable, tone from the mark, neutral t5, text between runs as is",
      VC.toneHTML("Nǐ hǎo, xuésheng!") === '<span class="t3">Nǐ</span> <span class="t3">hǎo</span>, <span class="t2">xué</span><span class="t5">sheng</span>!');
    check("toneHTML: apostrophe kept between syllables (Xī'ān), r-suffix one syllable (diǎnr)",
      VC.toneHTML("Xī'ān") === '<span class="t1">Xī</span>&#39;<span class="t1">ān</span>' && VC.toneHTML("yìdiǎnr") === '<span class="t4">yì</span><span class="t3">diǎnr</span>');
    check("toneHTML escapes everything and leaves non-readings uncoloured", VC.toneHTML('<b>"OK"</b> 我') === "&lt;b&gt;&quot;OK&quot;&lt;/b&gt; 我");
    check("splitReading: a run with a/o/e inside prefers the apostrophe-less split (fāngàn = fān|gàn)", VC.splitReading("fāngàn").map(p => p.text).join("|") === "fān|gàn");
  } catch(e){ check(`section threw: ${e.message}`, false); }

  // ---------------------------------------------------------------- [2] typed reading: core
  console.log("\n[2] typed reading: core (pack.typing \"pron\")");
  try {
    const T = [
      ["xuésheng", "xuésheng", "ok"], ["XUÉSHENG", "xuésheng", "ok"], ["xue2sheng5", "xuésheng", "ok"], ["xue2sheng0", "xuésheng", "ok"], ["xue2sheng", "xuésheng", "ok"],
      ["xue2 sheng5", "xuésheng", "ok"], ["xué sheng", "xuésheng", "ok"], ["xuesheng", "xuésheng", "tones"], ["xue sheng", "xuésheng", "tones"],
      ["xue2sheng1", "xuésheng", "tonesDiff"], ["xue3sheng", "xuésheng", "tonesDiff"], ["xuexi", "xuésheng", "wrong"], ["xueshen", "xuésheng", "wrong"],
      ["nǐhǎo", "nǐ hǎo", "ok"], ["nihao", "nǐ hǎo", "tones"], ["ni3hao3", "nǐ hǎo", "ok"], ["ni2hao3", "nǐ hǎo", "tonesDiff"], ["nihao5", "nǐ hǎo", "tonesDiff"], ["níhǎo", "nǐ hǎo", "tonesDiff"], ["nihaoo", "nǐ hǎo", "wrong"],
      ["yi1hui4r5", "yīhuìr", "ok"], ["yihuir", "yīhuìr", "tones"], ["yi2hui4r", "yīhuìr", "tonesDiff"], ["yi1hui4", "yīhuìr", "wrong"], ["lv3", "lǜ", "tonesDiff"],
      ["lv4", "lǜ", "ok"], ["lu:4", "lǜ", "ok"], ["lü4", "lǜ", "ok"], ["lu4", "lǜ", "wrong"], ["qu4", "qù", "ok"], ["qü4", "qù", "ok"],
      ["yi4dian3r", "yìdiǎnr", "ok"], ["yi4dianr3", "yìdiǎnr", "ok"], ["yidianr", "yìdiǎnr", "tones"],
      ["xi1an1", "Xī'ān", "ok"], ["Xī’ān", "Xī'ān", "ok"], ["xian", "Xī'ān", "tones"], ["ma", "ma", "ok"], ["ma5", "ma", "ok"], ["", "ma", "wrong"], ["  ", "nǐ", "wrong"],
    ];
    const badT = T.filter(([i, p, e]) => VC.checkPronTyped(i, p) !== e);
    check(`checkPronTyped: marked, numbered (neutral 5/0/none, r before/after digit), ü as v/u:, case/apostrophe/space-insensitive; toneless = "tones", other tones = "tonesDiff", other letters = "wrong" (${badT.length} bad${badT[0] ? ": " + JSON.stringify(badT[0]) : ""})`, badT.length === 0);
    // Every word: its pron, its generated numbered form and its toneless form.
    let nb = 0;
    WORDS.forEach(w => {
      const nums = VC.numberedForms(w.pron);
      const toneless = VC.stripMarks(w.pron);
      const allNeutral = VC.splitReading(w.pron).filter(p => p.tone).every(p => p.tone === 5);
      if(!nums.length || VC.checkPronTyped(w.pron, w.pron) !== "ok" || VC.checkPronTyped(nums[0], w.pron) !== "ok" || VC.checkPronTyped(toneless, w.pron) !== (allNeutral ? "ok" : "tones")) nb++;
    });
    check(`every word: pron and a numbered form accepted, the toneless form is "tones" (${nb} bad)`, nb === 0);
    check("typingEnabled stays on (the production slot alternates recall/type); pronTypingOn only for \"pron\"", VC.typingEnabled(PACK) && VC.pronTypingOn(PACK) && !VC.pronTypingOn({ typing: {} }) && !VC.pronTypingOn({}));
    let gapType = 0; for(let i = 0; i < 2000; i++) if(VC.sentenceKind(PACK) === "gapType") gapType++;
    const objPack = Object.assign({}, PACK, { typing: {} }); let objGap = 0; for(let i = 0; i < 2000; i++) if(VC.sentenceKind(objPack) === "gapType") objGap++;
    check(`sentenceKind: never gapType (typing a written blank) for typing "pron" (${gapType}/2000); unchanged for a typing object (${objGap}/2000)`, gapType === 0 && objGap > 0);
    const learned = WORDS.slice(0, 40); const prog = VC.defaultProg(PACK);
    let typeSeen = 0, recallSeen = 0; for(let i = 0; i < 20; i++) VC.buildReviewPlan(learned, prog, PACK).forEach(p => { if(p.kind === "type") typeSeen++; if(p.kind === "recall") recallSeen++; });
    const rc = VC.buildRecallPlan(learned, prog, PACK, 8);
    check(`Review/Recall plans: the production slots alternate recall and type as for other typing packs (review type ${typeSeen}, recall ${recallSeen}; recall step ${rc.map(p => p.kind).join(",")})`,
      typeSeen > 0 && recallSeen > 0 && rc.filter(p => p.kind === "type").length === 4 && rc.filter(p => p.kind === "recall").length === 4);
  } catch(e){ check(`section threw: ${e.message}`, false); }

  // ---------------------------------------------------------------- [3] app: tones everywhere, typed items, taps
  console.log("\n[3] app: colouring on every screen, the typed-reading item");
  try {
    const { api } = await boot({ seed: 7 });
    check("CSS: .t1-.t5 use --t1..--t5, defined for light, dark (media) and data-theme dark",
      /\.t1\{color:var\(--t1\)\} \.t2\{color:var\(--t2\)\} \.t3\{color:var\(--t3\)\} \.t4\{color:var\(--t4\)\} \.t5\{color:var\(--t5\)\}/.test(appHtml)
      && (appHtml.match(/--t1:#[0-9A-F]{6};--t2:#[0-9A-F]{6};--t3:#[0-9A-F]{6};--t4:#[0-9A-F]{6};--t5:#[0-9A-F]{6};/g) || []).length === 3);
    api.setProg(seedPF()); api.today();
    api.el("go").click();
    let seen = [], err = null;
    try{ seen = walk(api, /id="again"/); }catch(e){ err = e; }
    const unc = seen.map(x => ({ where: x.where, u: uncoloured(x.html) })).filter(x => x.u.length);
    check(`Today walk (Review, Learn teach + drill, Listen, Recall, Sentences): every reading is coloured (${seen.length} screens/items; ${unc.length} with an uncoloured reading${unc[0] ? `: ${unc[0].where} ${JSON.stringify(unc[0].u.slice(0, 2))}` : ""})${err ? " ERROR " + err.message : ""}`,
      !err && unc.length === 0 && seen.filter(x => tspans(x.html)).length > seen.length / 2);
    const teach = seen.filter(x => x.where === "teach");
    check(`teach rows colour the reading (${teach.length} teach screens)`, teach.length > 0 && teach.every(x => tspans(x.html) >= 10));
    // Options: every word-choice option label (recall, gap) is coloured.
    const wordOpts = seen.filter(x => x.kind === "mc" && /opts-w/.test(x.html)).flatMap(x => x.opts);
    check(`word-choice options are coloured readings (${wordOpts.length} labels)`, wordOpts.length > 0 && wordOpts.every(o => tspans(o) > 0 && !uncoloured(o).length));
    // Typed items reached the walk (the production slot) and played through: both kinds,
    // alternating in each plan (reading first), never a written blank.
    const typed = seen.filter(x => x.kind === "type");
    const tLabels = typed.map(x => x.it.label);
    // The walk's words are all below their character tier (shown by their reading), so
    // every type slot is the pinyin item: characters never asked before they were shown.
    const walkProg = api.getProg();
    const belowBad = typed.filter(x => VC.displayForm(BY_ID[x.it.key.slice(2)], CHARACTERS, walkProg, PACK).isPron && x.it.label !== "Type the pinyin");
    check(`typed items appear in the Today walk's production slots, only word keys; a below-tier word never gets "Type the characters" (${tLabels.filter(l => l === "Type the pinyin").length} pinyin, ${tLabels.filter(l => l === "Type the characters").length} characters, ${belowBad.length} bad)`,
      typed.length > 1 && tLabels.every(l => l === "Type the pinyin" || l === "Type the characters") && belowBad.length === 0 && typed.every(x => x.it.key.startsWith("w:")));
    check("no typed gap item (gapType) in the walk", !seen.some(x => x.kind === "type" && x.it.key.startsWith("s:")));
    const w = BY_ID["w0077"]; // 学生 xuésheng
    // At tier: the word's character unit has a mastered record, so its written form shows.
    const wUnit = CHARACTERS.find(u => (u.words || []).includes(w.id));
    const atTier = () => { const pm = seedPF(); VC.ensureChars(pm).c[wUnit.id] = { r: 5, w: 0, s: 5 }; return pm; };
    const below = seedPF();
    api.setProg(below);
    const bPlan = [{ kind: "type", word: w }, { kind: "type", word: w }, { kind: "type", word: w }];
    check("below tier (shown by its reading): every type slot gives Type the pinyin, never the characters",
      VC.displayForm(w, CHARACTERS, below, PACK).isPron && bPlan.map(api.itemFromPlan).every(x => x.label === "Type the pinyin"));
    api.setProg(atTier());
    check("at tier: the written form is on display", !VC.displayForm(w, CHARACTERS, api.getProg(), PACK).isPron);
    // Plan order picks the item: 1st type slot pinyin, 2nd characters, 3rd pinyin.
    const tPlan = [{ kind: "type", word: w }, { kind: "recall", word: w }, { kind: "type", word: w }, { kind: "type", word: w }];
    const tItems = tPlan.map(api.itemFromPlan);
    check("itemFromPlan as a map callback: type slots alternate Type the pinyin / Type the characters in plan order",
      tItems.map(x => x.label).join("|") === "Type the pinyin|Which word is this?|Type the characters|Type the pinyin");
    const it = api.itemFromPlan({ kind: "type", word: w });
    check("pinyin item: gloss stimulus, 'pinyin · tones optional' tag, no audio markup (no replay/speaker, no mount), no written form, Latin input (lang=en)",
      it.kind === "type" && it.label === "Type the pinyin" && it.html.includes(VC.escapeHtml(VC.gloss(w))) && /class="ktag"><b>pinyin<\/b> · tones optional</.test(it.html)
      && !/id="rp2"|id="sp"|class="replay|class="speaker|data-wid/.test(it.html) && !it.mount && !HAN.test(stripTags(it.html)) && it.inputTA === ' lang="en"' && it.placeholder === "pinyin, tones optional…");
    check("pinyin check: marked, numbered, toneless and other tones right; other letters wrong", it.check("xuésheng") && it.check("xue2sheng") && it.check("xuesheng") && it.check("xue2sheng1") && it.check("XUE3 SHENG") && !it.check("xuexi") && !it.check("xueshen"));
    check("pinyin feedback: toneless or other tones -> a 'tones:' note with the coloured marked form; none when exact or wrong",
      it.feedback("xuesheng") === `<div class="diff">tones: <span class="tpron">${VC.toneHTML(w.pron)}</span></div>` && it.feedback("xue4sheng") === it.feedback("xuesheng") && it.feedback("xuexi") === "" && it.feedback("xue2sheng") === "" && it.feedback("xuésheng") === "");
    const wi = tItems[2];
    check("characters item: gloss stimulus, 'characters' tag, replay button + autoplay mount, target-language input (no lang=en), characters placeholder",
      wi.kind === "type" && wi.label === "Type the characters" && wi.html.includes(VC.escapeHtml(VC.gloss(w))) && /class="ktag"><b>characters<\/b>/.test(wi.html)
      && /id="rp2"/.test(wi.html) && typeof wi.mount === "function" && !HAN.test(stripTags(wi.html)) && wi.inputTA === undefined && wi.placeholder === "characters…");
    check("characters check: the written form (and alt forms) right, the reading or another word wrong", wi.check(w.w) && wi.check(" " + w.w + " ") && !wi.check(w.pron) && !wi.check("学习") && (w.alt || []).every(a => wi.check(a)));
    // Drive both items through the renderer, with the spoken log.
    const { api: a2, spoken } = await boot({ seed: 3 });
    a2.setProg(atTier());
    const s0 = spoken.length;
    const r = runTyped(a2, w, "xuesheng", 0, spoken);
    check("renderer, pinyin: nothing spoken before the answer; toneless counted right, no 'you typed', tones note + coloured reading",
      r.spokenBefore === 0 && !r.wrong && !/you typed/.test(r.rv) && /tones: /.test(r.rv) && r.rv.includes(VC.toneHTML(w.pron)) && /placeholder="pinyin, tones optional…"/.test(r.html) && /id="tin"[^>]*lang="en"/.test(r.html) && !/id="rp2"/.test(r.html));
    const r2 = runTyped(a2, w, "xue4sheng1", 0, spoken);
    check("renderer, pinyin: other tones counted right with the tones note", !r2.wrong && /tones: /.test(r2.rv) && r2.spokenBefore === 0);
    const r3 = runTyped(a2, w, "xue2sheng5", 0, spoken);
    check("renderer, pinyin: numbered answer counted right, no note", !r3.wrong && !/tones: /.test(r3.rv));
    const r4 = runTyped(a2, w, "xuexi", 0, spoken);
    check("renderer, pinyin: other letters counted wrong, 'you typed' shown", r4.wrong && /you typed: xuexi/.test(r4.rv));
    const r5 = runTyped(a2, w, w.w, 1, spoken);
    check(`renderer, characters: the word spoken once on mount (autoplay), zh input attributes, placeholder; written form counted right (spoken before answer: ${r5.spokenBefore})`,
      r5.spokenBefore === 1 && r5.spokenText[0] === w.w && !r5.wrong && /id="rp2"/.test(r5.html) && /id="tin"[^>]*data-tl lang="zh[^"]*"/.test(r5.html) && /placeholder="characters…"/.test(r5.html) && s0 >= 0);
    const r6 = runTyped(a2, w, w.pron, 1, spoken);
    check("renderer, characters: typing the reading counted wrong", r6.wrong);
    // A word with no pron gets the characters item in either slot.
    const np = Object.assign({}, w, { pron: "" });
    a2.setProg(below);
    check("below tier, characters slot rendered: the pinyin item, nothing spoken before the answer", (() => { const r7 = runTyped(a2, w, "xuesheng", 1, spoken); return /Type the pinyin/.test(r7.html) && r7.spokenBefore === 0 && !r7.wrong; })());
    a2.setProg(atTier());
    check("no pron: both type slots give the characters item", [0, 1].every(i => a2.itemFromPlan({ kind: "type", word: np }, i, [{ kind: "type" }, { kind: "type" }]).label === "Type the characters"));

  } catch(e){ check(`section threw: ${e.message}`, false); }

  // ---------------------------------------------------------------- [3j] typed items, ja-like (no tones, kana prons)
  // pronFirst, no pack.tones, kana prons: the reading item is silent and checks kana by
  // plainPronKey (katakana = hiragana, ー and small kana exact); the written item is spoken
  // and takes w, alts and the form without its affix mark 〜; the below-tier gate holds.
  console.log("\n[3j] typed items without tones (ja-like: kana readings)");
  try {
    const { jaLike } = require(path.join(__dirname, "fixtures", "chars_packs.js"));
    const J = jaLike();
    const jp = Object.assign({}, J.pack, { pronFirst: true, tts: "ja-JP", typing: "pron" });
    const g = J.words.find(w => J.units.some(u => u.words[0] === w.id) && w.lv === "A1" && w.id !== "w0001" && w.id !== "w0003");
    g.alt = [g.pron]; // the kana spelling as an alt (分かる / わかる)
    const kata = { id: "w9001", w: "コーヒー", pron: "コーヒー", en: "coffee", lv: "A1" };
    const affix = { id: "w9002", w: "〜濿", pron: "〜ねん", en: "year (counter)", lv: "A1" };
    const words = [...J.words, kata, affix];
    const units = [...J.units, { id: "c9002", t: affix.w, words: [affix.id], lv: "A1" }];
    const P = { typing: "pron" };
    const T = [
      ["exact hiragana", "たべる", "たべる", "ok"], ["katakana typed for a hiragana pron", "タベル", "たべる", "ok"],
      ["hiragana typed for a katakana pron", "こーひー", "コーヒー", "ok"], ["exact katakana", "コーヒー", "コーヒー", "ok"],
      ["half-width katakana", "ｺｰﾋｰ", "コーヒー", "ok"], ["spaces around/inside", " たべ る ", "たべる", "ok"],
      ["affix mark omitted", "ねん", "〜ねん", "ok"], ["affix mark typed", "〜ねん", "〜ねん", "ok"],
      ["standalone voicing mark ゛ (U+309B, not the combining U+3099) recomposes with its base kana", "は゛す", "バス", "ok"],
      ["ー missing (long vowel spelled out)", "こうひい", "コーヒー", "wrong"], ["ー missing", "コヒー", "コーヒー", "wrong"],
      ["extra ー", "たべるー", "たべる", "wrong"], ["small kana as full size", "きやく", "きゃく", "wrong"], ["full size as small", "きゃく", "きやく", "wrong"],
      ["voicing mark missing", "はす", "バス", "wrong"], ["other kana", "たべた", "たべる", "wrong"], ["prefix only", "たべ", "たべる", "wrong"],
      ["tone digit (pinyin path would accept)", "たべる1", "たべる", "wrong"], ["romaji", "taberu", "たべる", "wrong"], ["empty", "", "たべる", "wrong"],
    ];
    const badK = T.filter(([, i, p, e]) => VC.checkPronTyped(i, p, P) !== e);
    check(`checkPronTyped without tones (kana table, ${T.length} rows): katakana = hiragana, half-width folded, spaces/〜 ignored; ー, small kana, voicing exact; digits and romaji wrong (${badK.length} bad${badK[0] ? ": " + JSON.stringify(badK[0]) : ""})`, badK.length === 0);
    check("checkPronTyped with a tones pack (zh) or no pack: the pinyin path, unchanged",
      VC.checkPronTyped("xue2sheng", "xuésheng", PACK) === "ok" && VC.checkPronTyped("xuesheng", "xuésheng", PACK) === "tones" && VC.checkPronTyped("xue4sheng", "xuésheng") === "tonesDiff" && VC.checkPronTyped("たべる1", "たべる") === "tonesDiff");
    check("affixBare: 〜/～/- stripped at either end only; no mark: unchanged", VC.affixBare("〜年") === "年" && VC.affixBare("～さん") === "さん" && VC.affixBare("お〜") === "お" && VC.affixBare("年〜年") === "年〜年" && VC.affixBare("学生") === "学生"
      && VC.affixBare("-이다") === "이다" && VC.affixBare("가-") === "가" && VC.affixBare("-이/가") === "이/가");
    check("affixBare: an inner hyphen (not at either edge) is a real character, never stripped",
      VC.affixBare("धीरे-धीरे") === "धीरे-धीरे" && VC.affixBare("कौन-सा") === "कौन-सा");
    check("affixAlts: no affix mark -> []; 〜 word -> bare form only; ko hyphen word with no slash -> bare form only",
      VC.affixAlts("学生").length === 0 && VC.affixAlts("धीरे-धीरे").length === 0
      && VC.affixAlts("〜年").length === 1 && VC.affixAlts("〜年")[0] === "年"
      && VC.affixAlts("-이다").length === 1 && VC.affixAlts("-이다")[0] === "이다");
    check("affixAlts: ko slash word -> bare slash form plus each alternative on its own, entry.w itself not repeated",
      JSON.stringify(VC.affixAlts("-이/가")) === JSON.stringify(["이/가", "이", "가"])
      && JSON.stringify(VC.affixAlts("-은/는")) === JSON.stringify(["은/는", "은", "는"]));
    check("affixAlts: ko real parenthetical-optional words -> bare, with-syllable and without-syllable forms",
      JSON.stringify(VC.affixAlts("-(으)로")) === JSON.stringify(["(으)로", "으로", "로"])
      && JSON.stringify(VC.affixAlts("-(이)나")) === JSON.stringify(["(이)나", "이나", "나"])
      && JSON.stringify(VC.affixAlts("-(이)랑")) === JSON.stringify(["(이)랑", "이랑", "랑"]));
    check("affixAlts: a hypothetical word combining a slash and a parenthetical group per alternative still yields both bare alternatives, so a learner can type either without its optional syllable",
      (() => { const a = VC.affixAlts("-(으)로/(이)나"); return a.includes("(으)로") && a.includes("(이)나") && a.includes("으로") && a.includes("로") && a.includes("이나") && a.includes("나"); })());
    check("writtenTypedFold: NFKC-folds half-width kana to full-width and unifies ～ to 〜; katakana/hiragana untouched (unlike kanaFold)",
      VC.writtenTypedFold("ﾃﾚﾋﾞ") === "テレビ" && VC.writtenTypedFold("～年") === "〜年" && VC.writtenTypedFold("〜年") === "〜年"
      && VC.writtenTypedFold("テレビ") === "テレビ" && VC.writtenTypedFold("てれび") === "てれび");
    check("acceptTyped: a no-tones written item accepts half-width kana and either affix tilde once writtenTypedFold is applied to the typed value (as writtenTypeItem now does)",
      (() => {
        const jaPack = { typing: { caseSensitive: false, accents: "lenient" } };
        const tv = { id: "w9010", w: "テレビ", alt: null };
        const affixWord = { id: "w9011", w: "〜年", alt: null };
        return VC.acceptTyped(VC.writtenTypedFold("ﾃﾚﾋﾞ"), tv, jaPack, VC.affixAlts(tv.w)) === true
          && VC.acceptTyped("ﾃﾚﾋﾞ", tv, jaPack, VC.affixAlts(tv.w)) === false // unfolded half-width does not match on its own
          && VC.acceptTyped(VC.writtenTypedFold("～年"), affixWord, jaPack, VC.affixAlts(affixWord.w)) === true;
      })());
    {
      const KO_WORDS = path.join(ROOT, "..", "korean", "pack", "words.json");
      if(fs.existsSync(KO_WORDS)){
        const koWords = JSON.parse(fs.readFileSync(KO_WORDS, "utf8"));
        const withParens = koWords.filter(x => typeof x.w === "string" && (x.w.includes("(") || x.w.includes(")"))).map(x => x.w).sort();
        const expected = ["-(으)로", "-(이)나", "-(이)랑"].sort();
        check(`no korean pack word other than the 3 parenthetical-optional ones carries a parenthesis in w (${withParens.length} found)`,
          JSON.stringify(withParens) === JSON.stringify(expected));
      } else console.log("NOTE  ../korean/pack missing: korean parenthesis-guard check skipped");
    }
    check("acceptTyped: a Korean-shaped word ('typing' object, no 'pron') accepts w, the affix-bare form and each slash alternative, but not an unrelated string",
      (() => {
        const koPack = { typing: { caseSensitive: false, accents: "lenient" } };
        const entry = { w: "-이/가", alt: null };
        const extra = VC.affixAlts(entry.w);
        return VC.acceptTyped("-이/가", entry, koPack, extra) === true
          && VC.acceptTyped("이/가", entry, koPack, extra) === true
          && VC.acceptTyped("이", entry, koPack, extra) === true
          && VC.acceptTyped("가", entry, koPack, extra) === true
          && VC.acceptTyped("나", entry, koPack, extra) === false;
      })());
    const { api: aj, spoken } = await boot({ pack: jp, words, sentences: [], units, passages: [], voices: [{ lang: "ja-JP", name: "j" }] });
    const base = () => VC.normalizeProg({ sets: { A1: 3 }, placedOnce: true, sessions: 5 }, jp);
    const atTier = ids => { const pm = base(); ids.forEach(id => { const u = units.find(x => x.words[0] === id); VC.ensureChars(pm).c[u.id] = { r: 5, w: 0, s: 5 }; }); return pm; };
    // Below tier: a glyph word is shown by its kana, so both slots give the reading item.
    aj.setProg(base());
    const two = [{ kind: "type" }, { kind: "type" }];
    check("below tier (glyph word shown by its kana): both type slots give Type the reading",
      VC.displayForm(g, units, aj.getProg(), jp).isPron && [0, 1].every(i => aj.itemFromPlan({ kind: "type", word: g }, i, two).label === "Type the reading"));
    const rb = runTyped(aj, g, g.pron, 1, spoken);
    check("below tier, written slot rendered: the reading item, nothing spoken, the kana counted right", /Type the reading/.test(rb.html) && rb.spokenBefore === 0 && !rb.wrong);
    check("a kana-only word (no unit, shown as written): slots alternate reading / characters",
      !VC.displayForm(kata, units, aj.getProg(), jp).isPron && [0, 1].map(i => aj.itemFromPlan({ kind: "type", word: kata }, i, two).label).join("|") === "Type the reading|Type the characters");
    // At tier: the written form is on display; slots alternate.
    aj.setProg(atTier([g.id, affix.id]));
    const ri = aj.itemFromPlan({ kind: "type", word: g }, 0, two), wi = aj.itemFromPlan({ kind: "type", word: g }, 1, two);
    check("at tier: slots alternate Type the reading / Type the characters", !VC.displayForm(g, units, aj.getProg(), jp).isPron && ri.label === "Type the reading" && wi.label === "Type the characters");
    check("reading item: gloss stimulus, tag 'reading' (no tones note), placeholder 'reading…', target-language input (not lang=en), no audio markup, no mount",
      ri.html.includes(VC.escapeHtml(VC.gloss(g))) && /class="ktag"><b>reading<\/b><\/div>/.test(ri.html) && ri.placeholder === "reading…" && ri.inputTA === undefined
      && !/id="rp2"|id="sp"|class="replay|class="speaker|data-wid/.test(ri.html) && !ri.mount && !stripTags(ri.html).includes(g.w) && !stripTags(ri.html).includes(g.pron));
    const kataPron = [...g.pron].map(c => String.fromCharCode(c.charCodeAt(0) + 0x60)).join("");
    check("reading item check: hiragana and its katakana right, the written form and other kana wrong; no feedback note",
      ri.check(g.pron) && ri.check(kataPron) && !ri.check(g.w) && !ri.check(g.pron + "ー") && !ri.check(g.pron.slice(1)) && [g.pron, kataPron, "x"].every(v => ri.feedback(v) === ""));
    const r1 = runTyped(aj, g, kataPron, 0, spoken);
    check("renderer, reading: nothing spoken before the answer; katakana counted right; kana input (data-tl lang=ja), no replay",
      r1.spokenBefore === 0 && !r1.wrong && /id="tin"[^>]*data-tl lang="ja[^"]*"/.test(r1.html) && !/id="tin"[^>]*lang="en"/.test(r1.html) && /placeholder="reading…"/.test(r1.html) && !/id="rp2"/.test(r1.html));
    const r2 = runTyped(aj, g, g.pron + "ー", 0, spoken);
    check("renderer, reading: wrong kana counted wrong, 'you typed' shown", r2.wrong && /you typed/.test(r2.rv));
    const r3 = runTyped(aj, g, g.w, 1, spoken);
    check(`renderer, characters: the word spoken once on mount, replay button, ja input; the written form right (spoken before answer: ${r3.spokenBefore})`,
      r3.spokenBefore === 1 && !r3.wrong && /id="rp2"/.test(r3.html) && /id="tin"[^>]*data-tl lang="ja[^"]*"/.test(r3.html) && /placeholder="characters…"/.test(r3.html));
    check("characters check: w and its kana alt right (分かる / わかる), another word's form wrong", wi.check(g.w) && wi.check(g.pron) && !wi.check(J.words.find(w => w.id !== g.id && w.w !== g.w && w.w !== g.pron).w));
    const ka = aj.itemFromPlan({ kind: "type", word: kata }, 1, two), kr = aj.itemFromPlan({ kind: "type", word: kata }, 0, two);
    check("katakana word: reading accepts こーひー and コーヒー, rejects こうひい; characters takes the spelling コーヒー only (not こーひー)",
      kr.check("こーひー") && kr.check("コーヒー") && !kr.check("こうひい") && ka.check("コーヒー") && !ka.check("こーひー"));
    const aw = aj.itemFromPlan({ kind: "type", word: affix }, 1, two), ar = aj.itemFromPlan({ kind: "type", word: affix }, 0, two);
    check("affix word 〜X: characters accepts X and 〜X, reading accepts ねん and 〜ねん", aw.label === "Type the characters" && aw.check("濿") && aw.check(affix.w) && !aw.check("〜") && ar.check("ねん") && ar.check("〜ねん"));
  } catch(e){ check(`section threw: ${e.message}`, false); }

  // ---------------------------------------------------------------- [3b] word taps
  console.log("\n[3b] app: word taps inside sentences (sentences with ruby)");
  try {
    const { api, spoken } = await boot({ seed: 7 });
    // Word taps inside sentences: rows, reveals, teach examples, passage reveals.
    api.setProg(seedPF());
    let rowsBad = 0, revBad = 0, stimBad = 0, tapN = 0;
    SENTENCES.forEach(s => {
      const row = api.sentenceRowHTML(s);
      const toks = (row.match(/data-tok="[^"]+"/g) || []).length; tapN += toks;
      const tokWords = s.ruby.filter(r => BY_ID[r[3]]).length;
      if(toks !== tokWords || /class="sent[^"]*" data-sent=/.test(row) || !/class="replay ssay" data-sent="\d+"/.test(row) || !/data-tokbox/.test(row)) rowsBad++;
      const rv = api.sentenceRevealBlock(s);
      if((rv.match(/data-tok="/g) || []).length !== tokWords || !/data-tokbox/.test(rv)) revBad++;
      const g = api.gapSentence(s, false);
      if(/data-tok=/.test(api.readSentence(s).html) || (g && (/data-tok=/.test(g.html) || g.opts.some(o => /data-tok=/.test(g.optHtml(o)))))) stimBad++;
    });
    check(`every sentence row: one word tap per ruby token with a word (${tapN} taps), no whole-row data-sent, a speaker button, a popover box (${rowsBad} bad)`, rowsBad === 0 && tapN > 0);
    check(`every sentence reveal block: word taps + popover box (${revBad} bad)`, revBad === 0);
    check(`question stimuli (read, gap) and answer options never carry word taps (${stimBad} bad)`, stimBad === 0);
    // A tap: popover (glossHTML) into the row's box, the word spoken, nothing recorded.
    const s0 = SENTENCES[0]; const wid = s0.ruby[4][3]; const tw0 = BY_ID[wid];
    const appended = []; const cls = new Set();
    const box = { querySelectorAll: () => [], querySelector: () => null, appendChild(c){ appended.push(c); return c; } };
    const tok = { dataset: { tok: wid }, closest: sel => sel === "[data-tokbox]" ? box : null, classList: { add: c => cls.add(c), remove(){} } };
    const progBefore = JSON.stringify(api.getProg()); spoken.length = 0;
    api.tokTap(tok);
    check(`tap on ${s0.t.slice(s0.ruby[4][0], s0.ruby[4][1])}: popover = the Read-tab popover of the word, inside the row, token marked on`,
      appended.length === 1 && /gloss tokgloss/.test(appended[0].className) && appended[0].innerHTML === api.glossHTML(wid, "", null) && cls.has("on") && appended[0].hidden === false);
    check("the popover shows the coloured reading, the show-written tap and the gloss", tspans(appended[0].innerHTML) > 0 && /data-showw="学生"/.test(appended[0].innerHTML) && appended[0].innerHTML.includes(VC.escapeHtml(VC.gloss(tw0))));
    check(`the tap speaks the word only (${JSON.stringify(spoken)}), progress unchanged`, spoken.length === 1 && spoken[0] === tw0.w && JSON.stringify(api.getProg()) === progBefore);
    check("keyboard: one keydown listener on #panel (Enter/Space on a tap); drill shortcuts skip a focused tap",
      api.panelListeners("keydown").length === 1 && api.onTok({ target: { closest: s => s === "[data-tok]" ? {} : null } }) && /!onShowWritten\(e\) && !tokOwns\(e\)\) drillKeyHandler/.test(appHtml));
    check("click delegation: still one bubbling click listener + the show-written capture listener", api.panelListeners("click").length === 2);
    // Multi-token pack word highlight (hindi/TODO.md live check: "के लिए links as one
    // entry but only the tapped half highlights"). PACK_SCHEMA.md sentences/passages
    // spans: "a word may have several spans, one per occurrence" — a multi-token entry's
    // builder-emitted spans are one .tk per token, all sharing data-tok. A tap on either
    // token must mark every token of that word "on", not just the one tapped, and must
    // still clear an unrelated word's highlight from a previous tap.
    {
      const mk = tokv => {
        const e = { dataset: { tok: tokv }, _on: false, classList: {} };
        e.classList.add = c => { if(c === "on") e._on = true; };
        e.classList.remove = c => { if(c === "on") e._on = false; };
        return e;
      };
      const half1 = mk(wid), half2 = mk(wid), other = mk("__other__"); other._on = true; // simulates a previous tap left `other` on
      const mtBox = {
        querySelectorAll(sel){
          const all = [half1, half2, other];
          if(sel === ".tk.on") return all.filter(x => x._on);
          if(sel === ".tk") return all;
          return [];
        },
        querySelector: () => null, appendChild(c){ return c; },
      };
      half1.closest = sel => sel === "[data-tokbox]" ? mtBox : null;
      half2.closest = sel => sel === "[data-tokbox]" ? mtBox : null;
      api.tokTap(half1);
      check("multi-token word tap: tapping one token of a multi-token word highlights every token sharing its data-tok",
        half1._on === true && half2._on === true);
      check("multi-token word tap: a previous, unrelated tap's highlight is cleared", other._on === false);
      // Tapping the word's OTHER token independently also lights up both (order-independent).
      half1._on = false; half2._on = false;
      api.tokTap(half2);
      check("multi-token word tap: tapping the second token highlights both the same way",
        half1._on === true && half2._on === true);
    }
    // Teach examples (charTeach) and Words-list examples carry taps too.
    const cs = VC.nextCharSet(["1","2","3"], CHARACTERS, PACK, VC.normalizeProg({}, PACK));
    api.charTeach(cs, { label: "字" }, () => {});
    const ct = api.html("panel");
    check("character teach cards: example sentences carry word taps; unit readings coloured", /data-tok="/.test(ct) && !uncoloured(ct).length && tspans(ct) >= 10);
    // Character-stage items: the reading options (charSound), the reading stimulus (charPick), reveals.
    let cb = 0;
    cs.units.forEach(u => ["charRead","charSound","charPick","charRecall"].forEach(k => {
      const it = api.charDrillItem(k, u);
      const h = it.html + (it.optHtml ? it.opts.map(o => it.optHtml(o)).join("|") : "") + it.reveal;
      if(uncoloured(h).length || !tspans(it.reveal) || (k === "charSound" && !it.opts.every(o => tspans(it.optHtml(o)))) || (k === "charPick" && !tspans(it.html))) cb++;
    }));
    check(`character items: reading options, reading stimulus and reveals coloured (${cs.units.length * 4} items, ${cb} bad)`, cb === 0);
    // Words list rows and the popover of every word.
    api.wordsPage("1", 0);
    const wl = api.el("wl").children.map(c => c.innerHTML);
    check(`Words list rows show coloured readings (${wl.length} rows)`, wl.length === 10 && wl.every(h => tspans(h) > 0 && !uncoloured(h).length));
    const pb = WORDS.filter(w => { const g = api.glossHTML(w.id, "", null); return !tspans(g) || uncoloured(g).length; });
    check(`popover of every word: reading coloured (${pb.length} bad)`, pb.length === 0);
  } catch(e){ check(`section threw: ${e.message}`, false); }

  // ---------------------------------------------------------------- [4] Sounds Reference card
  console.log("\n[4] Sounds Reference card (pack.soundsReference)");
  try {
    const { api } = await boot();
    api.goto("sounds");
    const h = api.html("panel");
    const groups = api.soundsRefGroups();
    const cells = groups.flatMap(g => g.cells);
    check(`Sounds tab: a collapsed Reference card below the lessons (${groups.length} groups, ${cells.length} cells)`, /<details class="refcard"><summary>Reference: every sound in the lessons<\/summary>/.test(h) && h.indexOf("refcard") > h.indexOf('class="plist"'));
    check("each cell: the coloured reading, speaks its one-character text (data-rs)", cells.length >= 40 && cells.every(c => h.includes(`<button type="button" data-rs="${c.say}" aria-label="${VC.escapeHtml(c.label)}">${VC.toneHTML(c.label)}</button>`)));
    const all = new Set(cells.map(c => VC.stripMarks(c.label).toLowerCase()));
    const inits = ["b","p","m","f","d","t","n","l","g","k","h","j","q","x","zh","ch","sh","r","z","c","s"];
    const missI = inits.filter(i => ![...all].some(l => { const sp = VC.splitSyllable(l); return sp && sp.initial === i; }));
    const tonesSeen = new Set(cells.map(c => VC.splitReading(c.label).find(p => p.tone).tone));
    check(`covers all 21 initials (missing ${missI.join(",") || "none"}) and tones 1-4`, missI.length === 0 && [1,2,3,4].every(t => tonesSeen.has(t)));
    // Finals as written in the cells (zero-initial y/w spellings and j/q/x ü-as-u included).
    const finalsSeen = new Set([...all].map(l => { const sp = VC.splitSyllable(l); return sp ? sp.final : null; }).filter(Boolean));
    const need = ["a","o","e","i","u","ü","ai","ei","ao","ou","an","en","ang","eng","ong","ia","ie","ua","uo","ue","ian","in","iang","ing","iao","iu","uai","ui","uan","un","uang","er"];
    const zeroMap = { yi:"i", wu:"u", yu:"ü", wen:"en", wo:"o" };
    [...all].forEach(l => { if(zeroMap[l]) finalsSeen.add(zeroMap[l]); });
    const missF = need.filter(f => !finalsSeen.has(f));
    check(`covers the finals the lessons teach (${need.length}; missing ${missF.join(",") || "none"})`, missF.length === 0);
    check("no duplicate reading; every cell is one character", new Set(cells.map(c => c.label)).size === cells.length && cells.every(c => [...c.say].length === 1));
    const { api: off } = await boot({ pack: Object.assign({}, PACK, { soundsReference: undefined }) });
    off.goto("sounds");
    check("without soundsReference: no card", !/refcard/.test(off.html("panel")));
  } catch(e){ check(`section threw: ${e.message}`, false); }

  // ---------------------------------------------------------------- [5] passages: phrase spans
  console.log("\n[5a] passages: rendered sentences keep every character");
  try {
    const { api } = await boot();
    api.setProg(seedPF());
    let n = 0, bad = [];
    PASSAGES.forEach(p => p.sentences.forEach((s, si) => {
      const h = api.passageSentenceHTML(s, si, false); n++;
      const vis = stripTags(h.replace(/<button[\s\S]*?<\/button>/g, "").replace(/<div class="pchips">[\s\S]*$/, ""));
      const visHan = hanCount(vis), visSyl = syllables(vis);
      if(visHan + visSyl !== hanCount(s.t)) bad.push(`${p.id}:${si} rendered ${visSyl}+${visHan} != ${hanCount(s.t)} (${vis})`);
    }));
    check(`every rendered passage sentence: syllables + characters left written = its characters (${n} sentences, ${bad.length} bad${bad[0] ? ": " + bad.slice(0, 2).join(" | ") : ""})`, bad.length === 0);
  } catch(e){ check(`section threw: ${e.message}`, false); }

  console.log("\n[5] passage spans longer than their word; popover heads");
  try {
    const { api } = await boot();
    api.setProg(seedPF());
    // Every span of every passage sentence: its rendered reading + written text accounts
    // for every character (syllables + characters left written = characters of the span).
    let spans = 0, longer = 0, bad = [];
    PASSAGES.forEach(p => p.sentences.forEach((s, si) => {
      const seg = VC.passageSegments(s, BY_ID, PACK);
      let at = 0;
      seg.parts.forEach(x => {
        const a = at; at += x.text.length; if(!x.id) return; spans++;
        const w = BY_ID[x.id]; if(x.text !== w.w) longer++;
        const comp = VC.composeSpanReading(x.text, w, c => { const u = CHARACTERS.find(u => u.t === c); return u ? u.reading : ""; }, PACK);
        const covered = comp.map(q => x.text.slice(q.start, q.end)).join("");
        const syl = comp.filter(q => q.reading).reduce((n, q) => n + syllables(q.reading), 0);
        const written = comp.filter(q => !q.reading).reduce((n, q) => n + hanCount(x.text.slice(q.start, q.end)), 0);
        if(covered !== x.text || syl + written !== hanCount(x.text)) bad.push(`${p.id}:${si} ${x.text}`);
      });
    }));
    check(`every passage span (${spans}, ${longer} longer than their word): its composed reading + written text accounts for every character (${bad.length} bad${bad[0] ? ": " + bad.slice(0, 2).join(" | ") : ""})`, spans > 0 && longer > 100 && bad.length === 0);
    let pc = 0, pn = 0;
    PASSAGES.forEach(p => p.sentences.forEach((s, si) => { pn++; const h = api.passageSentenceHTML(s, si, false) + api.passagePlainHTML(s); if(uncoloured(h).length || !tspans(h)) pc++; }));
    check(`Read passages, question reveals and results: every reading coloured (${pn} sentences, ${pc} bad)`, pc === 0);
    const find = t => { for(const p of PASSAGES) for(let si = 0; si < p.sentences.length; si++) if(p.sentences[si].t.includes(t)) return { p, s: p.sentences[si], si }; return null; };
    const f1 = find("我来介绍一下我的家人"), f2 = find("越来越好");
    const t1 = f1 && stripTags(api.passageSentenceHTML(f1.s, f1.si, false).replace(/<button[\s\S]*?<\/button>/g, ""));
    const t2 = f2 && stripTags(api.passageSentenceHTML(f2.s, f2.si, false).replace(/<button[\s\S]*?<\/button>/g, ""));
    check(`我来介绍一下我的家人: 一下 reads yīxià, nothing dropped (${t1})`, !!t1 && /yīxià/.test(t1) && /jièshào/.test(t1) && !HAN.test(t1));
    check(`越来越好: 越来越 reads yuèláiyuè (${t2})`, !!t2 && /yuèláiyuè hǎo/i.test(t2));
    // Popover head: the tapped surface with its reading; show-written gives the surface.
    const h2 = api.passageSentenceHTML(f2.s, f2.si, false);
    const m = h2.match(/<span class="pw" data-pw="([^"]+)"[^>]*data-ts="越来越" data-tr="([^"]*)"/);
    check(`越来越 span carries its surface and reading for the popover (${m && m[2]})`, !!m && m[2] === "yuèláiyuè");
    const g = api.glossHTML(m[1], "", { surface: "越来越", reading: m[2] });
    check("popover head: the phrase's coloured reading + show-written of the phrase, then the gloss", g.startsWith(`<span class="gw" data-tl lang="zh">${VC.toneHTML("yuèláiyuè")}<button type="button" class="showw" data-showw="越来越"`));
    const plain = api.glossHTML(m[1], "", null);
    check("a span equal to its word keeps the word's own headword", plain.startsWith(`<span class="gw" data-tl lang="zh">${VC.toneHTML(BY_ID[m[1]].pron)}`));
    // Question reveals / results: word taps (data-tok, not logged), same readings.
    const rp = api.passagePlainHTML(f2.s);
    check("question reveal/results sentence: word taps (data-tok) with the phrase head, no data-pw (not logged as tapped)", /data-tok="[^"]+" data-ts="越来越" data-tr="yuèláiyuè"/.test(rp) && !/data-pw=/.test(rp) && /yuèláiyuè/.test(stripTags(rp)));
    // Mastered word: the span shows written (no reading composed).
    const pm = seedPF(); VC.ensureChars(pm).c["c" + m[1].slice(1)] = { r: 5, w: 0, s: 5 }; api.setProg(pm);
    const h3 = stripTags(api.passageSentenceHTML(f2.s, f2.si, false).replace(/<button[\s\S]*?<\/button>/g, ""));
    check(`linked word mastered: the span is written as a whole (${h3})`, /越来越/.test(h3));
  } catch(e){ check(`section threw: ${e.message}`, false); }

  // ---------------------------------------------------------------- [6] capitals
  console.log("\n[6] a reading that starts a sentence is capitalised");
  try {
    const toks = [{ start: 0, end: 1, tier: "pron", reading: "hǎo" }, { start: 1, end: 2, tier: "pron", reading: "ba" }, { start: 3, end: 4, tier: "pron", reading: "nǐ" }, { start: 4, end: 5, tier: "pron", reading: "huì" }, { start: 6, end: 7, tier: "pron", reading: "shì" }, { start: 8, end: 9, tier: "pron", reading: "duì" }];
    const line = VC.sentencePieces({ t: "好吧！你会？是。对" }, toks).map(p => p.pre + p.text).join("");
    check(`after a sentence-internal ! ? . the next reading is capitalised (${line})`, line === "Hǎo ba! Nǐ huì? Shì. Duì");
    const q = VC.sentencePieces({ t: "“好”" }, [{ start: 1, end: 2, tier: "pron", reading: "hǎo" }]).map(p => p.pre + p.text).join("");
    check(`after an opening quote the first reading is capitalised (${q})`, /Hǎo/.test(q));
    const c = VC.sentencePieces({ t: "好，好" }, [{ start: 0, end: 1, tier: "pron", reading: "hǎo" }, { start: 2, end: 3, tier: "pron", reading: "hǎo" }]).map(p => p.pre + p.text).join("");
    check(`after a comma: not capitalised (${c})`, c === "Hǎo, hǎo");
    const { api } = await boot(); api.setProg(seedPF());
    let n = 0, badCap = [];
    PASSAGES.forEach(p => p.sentences.forEach((s, si) => {
      if(!/[！？。][^”’」]/.test(s.t.slice(0, -1))) return; n++;
      const vis = stripTags(api.passageSentenceHTML(s, si, false).replace(/<button[\s\S]*?<\/button>/g, "").replace(/<div class="pchips">[\s\S]*$/, ""));
      const m = vis.match(/[.!?]\s+([\p{L}])/gu) || [];
      if(m.some(x => { const ch = x.slice(-1); return ch === ch.toLowerCase() && !HAN.test(ch); })) badCap.push(vis);
    }));
    check(`passage sentences with an internal . ! ? (${n}): every reading after one is capitalised (${badCap.length} bad${badCap[0] ? ": " + badCap[0] : ""})`, n > 0 && badCap.length === 0);
  } catch(e){ check(`section threw: ${e.message}`, false); }

  // ---------------------------------------------------------------- [8] titles, questions, options (ruby)
  console.log("\n[8] passage titleRuby, questions[].ruby, optionsRuby under pronFirst; no hanzi in the Read tab");
  try {
    const withTR = PASSAGES.filter(p => Array.isArray(p.titleRuby) && p.titleRuby.length).length;
    const withQR = PASSAGES.flatMap(p => p.questions).filter(q => Array.isArray(q.ruby)).length;
    check(`zh passages carry titleRuby (${withTR}/${PASSAGES.length}) and question ruby (${withQR})`, withTR === PASSAGES.length && withQR > 0);
    const { api } = await boot({ seed: 5 });
    const pr = seedPF(); pr.read = { unlocked: PASSAGES.map(p => p.lv).filter((v, i, a) => a.indexOf(v) === i) }; api.setProg(VC.normalizeProg(pr, PACK));
    // Today read hint: the suggested passage's title by its reading.
    api.today();
    const hint = (api.html("panel").match(/<div class="stmt" id="readHintBox">([\s\S]*?)<button class="next"/) || [])[1];
    check(`Today read hint: the title reads by its ruby, coloured, with a show-written tap (${hint ? stripTags(hint).slice(0, 60) : "no hint"})`, !!hint && !HAN.test(stripTags(hint)) && tspans(hint) > 0 && /data-showw=/.test(hint));
    // Passage list: titles as readings inside the list buttons, no show-written inside a button.
    api.goto("read");
    const list = api.html("panel");
    const btns = [...list.matchAll(/<button data-pid="[^"]*"[^>]*>([\s\S]*?)<\/button>/g)].map(m => m[1]);
    check(`Read list: every title button shows the title's reading, coloured, no show-written or tap inside (${btns.length} buttons)`,
      btns.length > 0 && btns.every(b => !HAN.test(stripTags(b)) && tspans(b) > 0 && !/data-showw|data-tok/.test(b)));
    // Every passage: heading, passage, every question and its options, reveals, results.
    let screens = 0, hanBad = [], colBad = 0, optBad = 0, qBad = 0;
    const scan = (where, h) => { screens++; const t = stripTags(String(h).replace(/<button type="button" class="showw"[^>]*>[^<]*<\/button>/g, "")); if(HAN.test(t)) hanBad.push(`${where}: ${t.match(/[\s\S]{0,15}\p{Script=Han}+[\s\S]{0,5}/u)[0]}`); if(uncoloured(h).length) colBad++; };
    for(const p of PASSAGES){
      api.startPassage(p);
      const ps = api.html("panel"); scan(p.id + " passage", ps);
      const h2 = (ps.match(/<h2 class="ptitle"[^>]*>([\s\S]*?)<\/h2>/) || [])[1] || "";
      if(!(tspans(h2) && h2.includes(`data-showw="${VC.escapeHtml(p.title)}"`))) qBad++;
      api.el("rdone").click();
      for(let qi = 0; qi < p.questions.length; qi++){
        const q = p.questions[qi];
        const qs = api.html("panel"); scan(`${p.id} q${qi}`, qs);
        const qh = (qs.match(/<div class="med wd"[^>]*>([\s\S]*?)<\/div>/) || [])[1] || "";
        if(Array.isArray(q.ruby) && !(tspans(qh) && qh.includes(`data-showw="${VC.escapeHtml(q.q)}"`))) qBad++;
        const opts = api.el("o").children;
        opts.forEach(b => { scan(`${p.id} q${qi} option`, b.innerHTML); if(q.type === "mc" && (!tspans(b.innerHTML) || /data-showw|data-tok/.test(b.innerHTML))) optBad++; });
        const right = opts.find(b => b.dataset.v === String(q.answer));
        right.click(); scan(`${p.id} q${qi} reveal`, api.html("rv")); api.el("nx").click();
      }
      scan(p.id + " results", api.html("panel"));
    }
    check(`passage headings and question texts: reading-first, coloured, with a show-written tap (${qBad} bad)`, qBad === 0);
    check(`mc option buttons: coloured readings, no show-written, no word taps (${optBad} bad)`, optBad === 0);
    check(`no hanzi anywhere in the Read tab before characters are mastered: list, passages, questions, options, reveals, results of all ${PASSAGES.length} passages (${screens} screens, ${hanBad.length} with hanzi${hanBad[0] ? ": " + hanBad.slice(0, 3).join(" | ") : ""})`, hanBad.length === 0 && screens > 500);
    check(`every reading on those screens is tone-coloured (${colBad} screens with an uncoloured reading)`, colBad === 0);
    // Names (null wordId) show their reading.
    const q0 = PASSAGES[0].questions[0];
    const qn = q0.ruby.find(r => r[3] === null);
    api.startPassage(PASSAGES[0]); api.el("rdone").click();
    const q0h = api.html("panel");
    check(`a null-wordId token (a name) shows its reading (${qn && qn[2]} in "${stripTags((q0h.match(/<div class="med wd"[^>]*>([\s\S]*?)<\/div>/) || [])[1] || "").slice(0, 40)}")`, !!qn && stripTags((q0h.match(/<div class="med wd"[^>]*>([\s\S]*?)<\/div>/) || [])[1] || "").startsWith(qn[2]));
    // Ruby first: 越来越 / 一下 read from the passage ruby (as the builder wrote it); the
    // composed reading is only the fallback when a sentence has no ruby.
    const find = t => { for(const p of PASSAGES) for(let si = 0; si < p.sentences.length; si++) if(p.sentences[si].t.includes(t)) return { p, s: p.sentences[si], si }; return null; };
    const f = find("我来介绍一下我的家人");
    const i = f.s.t.indexOf("一下");
    const alt = Object.assign({}, f.s, { ruby: f.s.ruby.map(r => r[0] === i && r[1] === i + 2 ? [r[0], r[1], "yíxià", r[3]] : r) });
    api.setProg(seedPF());
    const vRuby = stripTags(api.passageSentenceHTML(alt, f.si, false).replace(/<button[\s\S]*?<\/button>/g, ""));
    const noRuby = Object.assign({}, f.s); delete noRuby.ruby;
    const vComp = stripTags(api.passageSentenceHTML(noRuby, f.si, false).replace(/<button[\s\S]*?<\/button>/g, ""));
    const head = api.passageSentenceHTML(alt, f.si, false).match(/data-ts="一下" data-tr="([^"]*)"/);
    check(`一下 reads from the sentence ruby (ruby says yíxià -> "${vRuby}"; popover head ${head && head[1]})`, /yíxià/.test(vRuby) && !!head && head[1] === "yíxià");
    check(`without ruby the composed fallback applies (-> "${vComp}")`, /yīxià/.test(vComp));
    const f2 = find("越来越好");
    check(`shipped ruby: 越来越 is one ruby token reading ${JSON.stringify(f2.s.ruby.find(r => f2.s.t.slice(r[0], r[1]) === "越来越"))}`, !!f2.s.ruby.find(r => f2.s.t.slice(r[0], r[1]) === "越来越" && r[2] === "yuèláiyuè"));
    // Flag off (no pronFirst): titles, questions and options stay written, as before.
    const off = Object.assign({}, PACK); delete off.pronFirst;
    const { api: a3 } = await boot({ pack: off });
    a3.setProg(VC.normalizeProg(seedPF(), off)); a3.goto("read");
    const offList = [...a3.html("panel").matchAll(/<button data-pid="([^"]*)"[^>]*>([\s\S]*?)<\/button>/g)];
    check(`without pronFirst the list titles stay written, ruby unused (${offList.length} titles)`, offList.length > 0 && offList.every(m => m[2].includes(PASSAGES.find(p => p.id === m[1]).title) && !tspans(m[2])));
    a3.startPassage(PASSAGES[0]); a3.el("rdone").click();
    check("without pronFirst the heading, question and options stay written", a3.el("o").children.some(b => b.innerHTML.includes(PASSAGES[0].questions[0].options[0])) && a3.html("panel").includes(VC.escapeHtml(PASSAGES[0].questions[0].q)));
  } catch(e){ check(`section threw: ${e.message}`, false); }

  // ---------------------------------------------------------------- [9] phrase tokens in sentences
  console.log("\n[9] sentence tokens longer than their word (这个 for 这): popover head and speech");
  try {
    const { api, spoken } = await boot();
    api.setProg(seedPF());
    const tokHTML = (h) => [...h.matchAll(/<span class="tk" data-tok="([^"]+)"( data-ts="([^"]*)" data-tr="([^"]*)")? role="button"/g)].map(m => ({ id: m[1], ts: m[3], tr: m[4] }));
    const popFor = (tk) => {
      const appended = []; const box = { querySelectorAll: () => [], querySelector: () => null, appendChild(c){ appended.push(c); return c; } };
      const ds = { tok: tk.id }; if(tk.ts !== undefined){ ds.ts = tk.ts; ds.tr = tk.tr; }
      spoken.length = 0;
      api.tokTap({ dataset: ds, closest: sel => sel === "[data-tokbox]" ? box : null, classList: { add(){}, remove(){} } });
      const g = appended[0] ? appended[0].innerHTML : "";
      const gw = (g.match(/<span class="gw"[^>]*>([\s\S]*?)<\/span> <span class="ge"/) || [])[1] || "";
      return { head: stripTags(gw.replace(/<button[\s\S]*?<\/button>/g, "")), showw: (gw.match(/data-showw="([^"]*)"/) || [])[1], said: spoken.slice() };
    };
    let phrase = 0, plainN = 0, bad = [];
    SENTENCES.forEach(snt => {
      const toks = snt.ruby.filter(r => BY_ID[r[3]]);
      const got = tokHTML(api.sentenceRowHTML(snt));
      if(got.length !== toks.length){ bad.push(`${snt.id} count`); return; }
      toks.forEach((r, i) => {
        const surf = snt.t.slice(r[0], r[1]), w = BY_ID[r[3]], tk = got[i];
        const isPhrase = surf !== w.w && surf.includes(w.w);
        const pop = popFor(tk);
        if(isPhrase){ phrase++;
          if(tk.ts !== surf || tk.tr !== r[2] || pop.head !== r[2] || pop.showw !== surf || pop.said[0] !== surf) bad.push(`${snt.id} ${surf}: head ${pop.head}/${pop.showw}, said ${pop.said}`);
        } else { plainN++;
          if(tk.ts !== undefined || pop.head !== w.pron || pop.showw !== w.w || pop.said[0] !== w.w) bad.push(`${snt.id} ${surf}: ${pop.head}/${pop.showw}`);
        }
      });
    });
    check(`every zh sentence ruby token: a phrase token (${phrase}) heads its popover with the surface's reading, show-written = the surface, speaks the surface; the rest (${plainN}) keep the word (${bad.length} bad${bad[0] ? ": " + bad.slice(0, 3).join(" | ") : ""})`, phrase >= 140 && bad.length === 0);
    // The same through the reveal block and through the word-first ruby path (rubyTextHTML).
    const s这个 = SENTENCES.find(x => x.ruby.some(r => x.t.slice(r[0], r[1]) === "这个"));
    check("reveal block: 这个 carries its head", /data-ts="这个" data-tr="[^"]+"/.test(api.sentenceRevealBlock(s这个)));
    const wf = Object.assign({}, PACK); delete wf.pronFirst;
    const { api: a2 } = await boot({ pack: wf });
    const pc = VC.normalizeProg({ sets: { "1": NS("1"), "2": NS("2"), "3": NS("3") }, placedOnce: true, sessions: 30 }, wf); VC.answerCharChoice(pc, true);
    VC.charStageUnits(["1","2","3"], CHARACTERS, wf).slice(0, 5).forEach(u => { pc.chars.c[u.id] = { r: 1, w: 0, s: 1 }; });
    a2.setProg(pc);
    check("word-first characters pack (rubyTextHTML): 这个 carries its head too", /data-ts="这个" data-tr="[^"]+"/.test(a2.sentenceRowHTML(s这个)));
    // ja-like: ruby over the written stem only (食 of 食べた) keeps the word; a token longer
    // than the word (the word + a kana suffix) heads with its surface and kana reading.
    const { jaLike } = require(path.join(__dirname, "fixtures", "chars_packs.js"));
    const J = jaLike(); const jp = Object.assign({}, J.pack, { pronFirst: true, tts: "ja-JP" });
    const jw = J.words.filter(w => J.units.some(u => u.words[0] === w.id) && /[ぁ-ゟ]$/.test(w.w)).slice(0, 4);
    const jsents = [];
    jw.forEach((w, i) => {
      const stem = w.w.replace(/[ぁ-ゟ]+$/, "");
      jsents.push({ id: "js" + i + "a", t: w.w + "です", en: "x", lv: w.lv, words: [w.id], ruby: [[0, stem.length, w.pron.slice(0, 2), w.id]] });
      jsents.push({ id: "js" + i + "b", t: w.w + "たち", en: "y", lv: w.lv, words: [w.id], ruby: [[0, w.w.length + 2, w.pron + "たち", w.id]] });
    });
    const { api: aj } = await boot({ pack: jp, words: J.words, sentences: jsents, units: J.units, passages: [] });
    aj.setProg(VC.normalizeProg({ sets: { A1: 3 }, placedOnce: true }, jp));
    let jb = [];
    jsents.forEach((x, i) => {
      const t = tokHTML(aj.sentenceRowHTML(x))[0]; const w = jw[Math.floor(i / 2)];
      if(i % 2 === 0 ? t.ts !== undefined : (t.ts !== x.t || t.tr !== w.pron + "たち")) jb.push(x.t);
    });
    check(`ja-like: a stem-only token keeps the word's headword; a token longer than the word heads with its surface and kana reading (${jsents.length} sentences, ${jb.length} bad)`, jw.length === 4 && jb.length === 0);
  } catch(e){ check(`section threw: ${e.message}`, false); }

  // ---------------------------------------------------------------- [11] characters.compose
  // A span longer than its word composes per-character readings only with
  // pack.characters.compose (zh); without it (ja: 時 reads じ in 6時, とき alone) the other
  // characters stay written. ja-like fixture: span = two other single-glyph units + the word.
  console.log("\n[11] per-character span readings only with pack.characters.compose");
  try {
    const { jaLike } = require(path.join(__dirname, "fixtures", "chars_packs.js"));
    const J = jaLike();
    const one = J.units.filter(u => [...u.t].length === 1 && J.words.find(w => w.id === u.words[0]).pron);
    const [uw, u2, u3] = one; const JB = Object.fromEntries(J.words.map(w => [w.id, w]));
    const w = JB[uw.words[0]], r2 = JB[u2.words[0]].pron, r3 = JB[u3.words[0]].pron;
    const span = u2.t + u3.t + w.w;
    const readingOf = c => { const u = J.units.find(u => u.t === c); return u ? JB[u.words[0]].pron : ""; };
    const off = Object.assign({}, J.pack, { pronFirst: true, tts: "ja-JP" });
    const on = Object.assign({}, off, { characters: Object.assign({}, off.characters, { compose: true }) });
    const cOff = VC.composeSpanReading(span, w, readingOf, off), cOn = VC.composeSpanReading(span, w, readingOf, on);
    check(`ja-like, compose unset: other characters written, the word read (${JSON.stringify(cOff)})`,
      JSON.stringify(cOff) === JSON.stringify([{ start: 0, end: 2, reading: "" }, { start: 2, end: 3, reading: w.pron }]) && VC.spanReadingText(span, w, readingOf, off) === u2.t + u3.t + w.pron);
    check(`ja-like, compose true: every character read (${VC.spanReadingText(span, w, readingOf, on)})`,
      JSON.stringify(cOn) === JSON.stringify([{ start: 0, end: 3, reading: r2 + r3 + w.pron }]) && VC.spanReadingText(span, w, readingOf, on) === r2 + r3 + w.pron);
    check("compose: only boolean true opts in; no characters -> off", VC.charsConfig(Object.assign({}, off, { characters: Object.assign({}, off.characters, { compose: "yes" }) })).compose === false
      && VC.spanReadingText(span, w, readingOf, { tones: null }) === u2.t + u3.t + w.pron);
    check("zh pack as shipped sets characters.compose", VC.charsConfig(PACK).compose === true);
    // App (pfPassage, no ruby): the rendered span, both branches.
    const psg = [{ id: "jp1", title: "t", sentences: [{ t: span + "です。", en: "x", words: [w.id], spans: [[0, span.length, w.id]] }], questions: [] }];
    const render = async pk => { const { api } = await boot({ pack: pk, words: J.words, sentences: [], units: J.units, passages: psg }); api.setProg(VC.normalizeProg({ sets: { A1: 3 }, placedOnce: true }, pk)); return stripTags(api.passageSentenceHTML(psg[0].sentences[0], 0, false).replace(/<button[\s\S]*?<\/button>/g, "")); };
    const hOff = await render(off), hOn = await render(on);
    check(`app, compose unset: ${hOff}`, hOff.includes(u2.t + u3.t + w.pron) && !hOff.includes(r2));
    check(`app, compose true: ${hOn}`, hOn.includes(r2 + r3 + w.pron) && !hOn.includes(u2.t));
    // zh sentence with its ruby removed (so spans compose), compose on vs removed.
    const zo = Object.assign({}, PACK, { characters: Object.assign({}, PACK.characters) }); delete zo.characters.compose;
    const f = (() => { for(const p of PASSAGES) for(let si = 0; si < p.sentences.length; si++) if(p.sentences[si].t.includes("我来介绍一下我的家人")){ const x = Object.assign({}, p.sentences[si]); delete x.ruby; return { s: x, si }; } return null; })();
    if(f){
      const { api } = await boot({ pack: zo }); api.setProg(seedPF());
      const t = stripTags(api.passageSentenceHTML(f.s, f.si, false).replace(/<button[\s\S]*?<\/button>/g, ""));
      check(`zh without compose: 一下 keeps 一 written, xià read (${t})`, /一 ?xià/.test(t) && !/yīxià/.test(t));
      const { api: a1 } = await boot({ pack: PACK }); a1.setProg(seedPF());
      const t1 = stripTags(a1.passageSentenceHTML(f.s, f.si, false).replace(/<button[\s\S]*?<\/button>/g, ""));
      check(`zh with compose (as shipped): 一下 reads yīxià (${t1})`, /yīxià/.test(t1));
    } else check("zh 我来介绍一下 passage sentence found", false);
  } catch(e){ check(`section threw: ${e.stack}`, false); }

  // ---------------------------------------------------------------- [10] review nits
  console.log("\n[10] r-suffix numbered forms, Escape on a tap, quotes and ellipsis");
  try {
    const w = WORDS.find(x => x.w === "一会儿");
    check(`一会儿 (${w.pron}): yi1hui4r5, yi1hui4r0, yi1hui4r, yi1huir4 accepted as hsk did; yi1hui4 not`,
      ["yi1hui4r5", "yi1hui4r0", "yi1hui4r", "yi1huir4"].every(i => VC.checkPronTyped(i, w.pron) === "ok") && VC.checkPronTyped("yi1hui4", w.pron) === "wrong");
    const { api } = await boot(); api.setProg(seedPF());
    const kd = api.panelListeners("keydown")[0];
    let hidden = null; const cleared = [];
    const g = { hidden: false }; const on = { classList: { remove: c => cleared.push(c) } };
    const box = { querySelectorAll: () => [on], querySelector: () => g };
    const tk = { dataset: { tok: "w0028" }, closest: sel => sel === "[data-tok]" ? tk : sel === "[data-tokbox]" ? box : null };
    kd({ key: "Escape", target: tk, preventDefault(){} }); hidden = g.hidden;
    check("Escape on a focused tap hides the popover and clears the highlight", hidden === true && cleared.includes("on"));
    check("... and is consumed: the drill shortcuts skip that Escape (Enter/Space on a tap too)",
      /!onShowWritten\(e\) && !tokOwns\(e\)\) drillKeyHandler/.test(appHtml) && api.tokOwns({ key: "Enter", target: tk }) && !api.tokOwns({ key: "Escape", target: tk }));
    // Bubbling order inside a drill: #panel's keydown listener, then the document's.
    const dks = api.docListeners("keydown");
    const esc = () => { const ev = { key: "Escape", target: tk2, preventDefault(){} }; kd(ev); dks.forEach(f => f(ev)); };
    let onSet = [{ classList: { remove(){ onSet = []; } } }]; const g2 = { hidden: false };
    const box2 = { querySelectorAll: () => onSet, querySelector: () => g2 };
    const tk2 = { dataset: { tok: "w0028" }, closest: sel => sel === "[data-tok]" ? tk2 : sel === "[data-tokbox]" ? box2 : null };
    const rw = WORDS.slice(0, 2);
    api.drill1(api.itemFromPlan({ kind: "read", word: rw[0] }));
    const key0 = api.getCur() && api.getCur().key;
    esc();
    check(`in a drill, Escape with an open popover closes it and leaves the drill on the same item (${key0})`,
      dks.length === 1 && api.getD() !== null && api.getCur().key === key0 && g2.hidden === true && onSet.length === 0);
    esc();
    check("... a second Escape (nothing open) quits the drill as before", api.getD() === null);
    const L = (t, r) => VC.sentencePieces({ t }, r.map(([a, b, x]) => ({ start: a, end: b, tier: "pron", reading: x }))).map(p => p.pre + p.text).join("");
    const q1 = L("他说：“好。”", [[0,1,"tā"],[1,2,"shuō"],[4,5,"hǎo"]]);
    check(`capital after a colon and an opening quote (${q1})`, q1 === "Tā shuō: “Hǎo.”");
    const q2 = L("好……好", [[0,1,"hǎo"],[3,4,"hǎo"]]);
    check(`ellipsis kept as written (no "..."), no capital after it (${q2})`, q2 === "Hǎo…… hǎo");
  } catch(e){ check(`section threw: ${e.message}`, false); }

  // ---------------------------------------------------------------- [7] control vs main
  console.log(`\n[7] control: BP2 fields absent -> HTML byte-identical to main ${MAIN}`);
  {
    let mainHtml = null, mainCore = null;
    try{
      mainHtml = cp.execSync(`git -C "${ROOT}" show ${MAIN}:engine/app.html`, { encoding: "utf8", maxBuffer: 1 << 26 });
      const src = cp.execSync(`git -C "${ROOT}" show ${MAIN}:engine/core.js`, { encoding: "utf8", maxBuffer: 1 << 26 });
      const m = { exports: {} }; new Function("module", "exports", "window", "globalThis", src)(m, m.exports, undefined, {}); mainCore = m.exports;
    }catch(e){ console.log("    cannot read main: " + e.message); }
    check(`main ${MAIN} engine loaded from git`, !!mainHtml && !!mainCore && typeof mainCore.sentencePieces === "function");
    // The fields BP2 gates on: pack.tones, typing "pron", soundsReference, sentence ruby (word
    // taps), and pronFirst (phrase-span readings in passages). Characters block kept.
    const offPack = Object.assign({}, PACK, { typing: null }); delete offPack.tones; delete offPack.soundsReference; delete offPack.pronFirst;
    const offSent = SENTENCES.map(s => { const c = Object.assign({}, s); delete c.ruby; return c; });
    const offPass = PASSAGES.map(p => Object.assign({}, p, { sentences: p.sentences.map(s => { const c = Object.assign({}, s); delete c.ruby; return c; }) }));
    async function screens(html, core, pack, sents, passages, seed){
      const { api } = await boot({ html, core, pack, sentences: sents, passages, seed });
      const out = {};
      api.setProg(seedPF()); api.today(); out.today = api.html("panel");
      api.el("go").click();
      let walked = []; try{ walked = walk(api, /id="again"/); }catch(e){ walked = [{ where: "ERR", html: e.message }]; }
      out.walk = walked.map(x => x.where + "\n" + x.html).join("\n----\n");
      api.setProg(seedPF());
      out.rows = sents.slice(0, 120).map(s => api.sentenceRowHTML(s, BY_ID[(s.words || [])[0]])).join("\n");
      api.wordsPage("1", 0); out.words = api.html("panel") + api.html("wbody") + api.el("wl").children.map(c => c.innerHTML).join("|");
      api.startPassage(passages[0]); out.read = api.html("panel");
      out.sounds = (api.goto("sounds"), api.html("panel"));
      return out;
    }
    if(mainHtml && mainCore){
      const cases = [["zh, BP2 fields + ruby + pronFirst absent", offPack, offSent, offPass]];
      for(const [name, pk, ss, ps] of cases){
        const a = await screens(mainHtml, mainCore, pk, ss, ps, 11);
        const b = await screens(CUR_HTML, VC, pk, ss, ps, 11);
        for(const k of Object.keys(a)){
          const same = a[k] === b[k];
          let at = -1; if(!same){ for(let i = 0; i < Math.max(a[k].length, b[k].length); i++) if(a[k][i] !== b[k][i]){ at = i; break; } }
          check(`${name}: ${k} byte-identical to main (${a[k].length} chars)${same ? "" : ` first diff at ${at}: main ${JSON.stringify(a[k].slice(at - 40, at + 60))} vs ${JSON.stringify(b[k].slice(at - 40, at + 60))}`}`, same && a[k].length > 50);
        }
      }
    }
  }

  Math.random = REAL_RANDOM;
  console.log(`\n${fails === 0 ? "ALL PASSED" : "FAILED"}: ${passes} passed, ${fails} failed`);
  process.exit(fails === 0 ? 0 : 1);
})().catch(e => { console.error(e); process.exit(1); });

// Runs the typed item for word w as a one-item drill through the app's renderer and
// answers `value`: the rendered item, the reveal, and whether it counted wrong.
// slot (optional): 0 = the pinyin item (the default), 1 = the characters item.
// spoken (optional): the boot's spoken log; spokenBefore counts what was spoken between
// mount and the answer (autoplay), spokenText what it was.
function runTyped(api, w, value, slot, spoken){
  const plan = [{ kind: "type", word: w }, { kind: "type", word: w }];
  const k0 = spoken ? spoken.length : 0;
  api.drill1(api.itemFromPlan(plan[slot || 0], slot || 0, plan));
  const html = api.html("panel");
  const spokenText = spoken ? spoken.slice(k0) : [];
  api.el("tin").value = value; api.el("submit").click();
  return { html, rv: api.html("rv"), wrong: api.getD().miss.length > 0, spokenBefore: spokenText.length, spokenText };
}
