// App checks for the script primer in engine/app.html (docs/SCRIPT_PRIMER.md §1, §2, §5,
// check 11 of §6, brief S3): the choice card, script Learn (teach cards, drill, "One more
// set"), the 12-item Review, Progress on/off chips (and per-stage chips), the one-time
// existing-learner notice, one boot check per item kind, the no-voice path (tts:false and
// no browser voice), teach-card rows (forms strip, compose, base -> variant, italic), the
// Script tab chart and practice, flag-off (no pack.script: no script markup), and a 390px
// width proxy for the teach card and the chart.
// Boots app.html's inline script for real against the synthetic packs in
// tests/fixtures/script_packs.js (plus a small ru-like pack below), with the same fake DOM
// as tests/characters_app_checks.js (id registry + regex scan of innerHTML; no jsdom).
// Run: node tests/script_app_checks.js
"use strict";
const fs = require("fs");
const path = require("path");

const ROOT = path.join(__dirname, "..");
const VC = require(path.join(ROOT, "engine", "core.js"));
const FX = require(path.join(__dirname, "fixtures", "script_packs.js"));

let fails = 0, passes = 0;
function check(name, cond, detail){
  if(cond){ passes++; console.log(`PASS  ${name}`); }
  else { fails++; console.log(`FAIL  ${name}${detail ? `\n      ${detail}` : ""}`); }
}

// A ru-like pack: one stage, "upper lower" glyphs, an italic form that differs.
function ru(){
  const A1 = [["мама","mum"],["да","yes"],["дом","house"],["там","there"],["кот","cat"],["как","how"]].map(([w, en], i) => ({ id:`rA1_0${i+1}`, w, en, lv:"A1" }));
  const U = (set, sid, t, roman, say, extra) => Object.assign({ id: sid, st:"cyr", set, group:"g", t, name: say, roman, say }, extra);
  const units = [
    U(1, "ru-a", "А а", "a", "а", { ex: [["rA1_01","mama"]] }), U(1, "ru-m", "М м", "m", "мэ", { ex: [["rA1_01","mama"]] }),
    U(1, "ru-t", "Т т", "t", "тэ", { italic: "т", ex: [["rA1_04","tam"]] }), U(1, "ru-o", "О о", "o", "о", { ex: [["rA1_05","kot"]] }),
    U(1, "ru-k", "К к", "k", "ка", { ex: [["rA1_05","kot"]] }),
    U(2, "ru-d", "Д д", "d", "дэ", { italic: "д", ex: [["rA1_02","da"],["rA1_03","dom"]] }),
  ];
  const pack = { key:"synthru", name:"synthru", tts:"ru-RU", levels:[{ id:"A1", label:"A1" }], placement:[["A1", 2]], typing:null, showPron:false, hasLessons:false,
    script: { stages:[{ key:"cyr", label:"Кириллица" }], learnKinds:["symSound","soundSym"], reviewKinds:["symSound","soundSym","wordRead","wordHear"] } };
  return { pack, words: A1, script: { units, notes: [] } };
}

// ------------------------------------------------------------------ fake DOM (characters_app_checks)
const appHtml = fs.readFileSync(path.join(ROOT, "engine", "app.html"), "utf8");
const scriptBlocks = [...appHtml.matchAll(/<script>([\s\S]*?)<\/script>/g)];
const appSrc = scriptBlocks[scriptBlocks.length - 1][1];
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
    addEventListener(){},
    tabButtons,
  };
}
const NOVOICE = [{ lang:"en-US", name:"e" }];
const tick = () => new Promise(r => setTimeout(r, 0));
function memStore(init){ const m = new Map(Object.entries(init || {})); return { getItem: k => m.has(k) ? m.get(k) : null, setItem: (k, v) => { m.set(k, String(v)); }, map: m }; }
// Boots the app on a fixture {pack, words, script}. opts: script false = no SCRIPT const
// (flag-off data), voices (default: one voice for the pack's tts lang; NOVOICE = a voice
// list without the pack's language, which is how "no voice" shows: an empty list counts as
// "voices still loading", VC.speechUsable),
// storage (a memStore).
async function boot(fx, opts){
  const o = opts || {};
  const document = makeFakeDom();
  const spoken = [], played = [];
  const voices = o.voices || [{ lang: fx.pack.tts, name: "v" }];
  const ss = { getVoices: () => voices, onvoiceschanged: null, cancel(){}, speak(u){ spoken.push(u.text); } };
  const window = { VocabCore: VC, speechSynthesis: ss, SpeechSynthesisUtterance: function(t){ this.text = t; }, addEventListener(){} };
  const localStorage = o.storage || memStore();
  const fnBody = appSrc + `
let __cur = null;
const __mc = renderMcItem, __ty = renderTypeItem;
renderMcItem = function(it){ __cur = it; return __mc(it); };
renderTypeItem = function(it){ __cur = it; return __ty(it); };
return {
  html: id => { const e = document.getElementById(id); return e ? e.innerHTML : null; },
  el: id => document.getElementById(id),
  getProg: () => prog, setProg: p => { prog = p; },
  today: () => { tab = "today"; render(); },
  getD: () => D, getCur: () => __cur, getState: () => todayStepState,
  goto: t => { tab = t; testSel = null; RD = null; render(); },
  hasScript: () => HAS_SCRIPT, scriptTab: () => SCRIPT_TAB, byId: () => SCRIPT_BYID,
  scriptDrillItem, scriptCtx, kindCtx: () => scriptKindCtx(), scriptTeachHTML, scriptChartHTML, scriptHL, drill,
  panelListeners: () => document.getElementById("panel")._listeners.click || [],
  ui, tf, glossHTML, glossBox, revealBlock, wordRowHTML, readItem, recallItem, typeItem, sentenceRowHTML, sentenceRevealBlock, startPlacement,
};`;
  const names = ["document","window","SpeechSynthesisUtterance","navigator","location","localStorage","matchMedia","requestAnimationFrame","Audio","confirm","alert","PACK","WORDS","SENTENCES","LESSONS","PASSAGES"];
  const args = [document, window, window.SpeechSynthesisUtterance, { userAgent:"ScriptAppChecks/1.0" }, undefined, localStorage, () => ({ matches:false }), fn => setTimeout(fn, 0),
    function(){ return { play(){ played.push(this.src); return Promise.resolve(); }, pause(){} }; }, () => true, () => {}, fx.pack, fx.words, [], [], []];
  if(o.script !== false){ names.push("SCRIPT"); args.push(fx.script); }
  Object.keys(o.extra || {}).forEach(k => { names.push(k); args.push(o.extra[k]); });
  if(o.console){ names.push("console"); args.push(o.console); }
  const api = new Function(...names, fnBody)(...args);
  await tick(); await tick();
  return { api, document, spoken, played, storage: localStorage };
}

const count = (s, re) => (s.match(re) || []).length;
const { rtlAudit, elsMarkup } = require("./fixtures/rtl_audit.js");
const optsMarkup = api => elsMarkup(api.el("o") ? api.el("o").children : []);
const stripTags = h => h.replace(/<[^>]+>/g, "").replace(/&lt;/g,"<").replace(/&gt;/g,">").replace(/&quot;/g,'"').replace(/&#39;/g,"'").replace(/&amp;/g,"&");
const segsOf = h => [...h.matchAll(/<div class="seg">[\s\S]*?<\/i><\/div>([\s\S]*?)<\/div>/g)].map(m => stripTags(m[1]));
const learnLine = h => stripTags((h.match(/2\. Learn<\/td><td>([\s\S]*?)<\/td>/) || [])[1] || "");
const reviewLine = h => stripTags((h.match(/1\. Review<\/td><td>([\s\S]*?)<\/td>/) || [])[1] || "");
// Answers the current item right (mc: the button with the answer; type: the first accepted
// string) or wrong (the first other option). Returns the item.
function answer(api, right){
  const it = api.getCur();
  if(it.kind === "type"){ const t = api.el("tin"); t.value = right === false ? "zzz" : it.__accept; api.el("submit").click(); return it; }
  const btn = api.el("o").children.find(b => right === false ? b.dataset.v !== it.a : b.dataset.v === it.a);
  if(!btn) throw new Error(`no option to click for ${it.key}`);
  btn.click(); return it;
}
// Plays the active drill to the end answering right, then leaves the end screen as is
// (the caller presses Continue or One more set). Returns every item shown.
const ROMAN_OF = {};
[FX.ko(), FX.fa(), FX.ja()].forEach(fx => fx.script.units.forEach(u => { ROMAN_OF["x:" + u.id] = u.roman; }));
function playDrill(api, maxItems){
  const shown = [];
  for(let i = 0; i < (maxItems || 300); i++){
    if(!api.getD()) return shown;
    const it = api.getCur(); shown.push(it);
    if(it.kind === "type") it.__accept = ROMAN_OF[it.key];
    answer(api, true); api.el("nx").click();
  }
  throw new Error("drill did not finish");
}

// Clicks the teach screen's drill button, plays the drill, and leaves its end screen.
function playDrillFrom(api, btnId){ api.el(btnId).click(); return playDrill(api).length; }
(async function main(){
  const KO = FX.ko();
  const koSets = VC.scriptSets("hangul", KO.script.units);

  // ---------------------------------------------------------------- [1] fresh ko: choice card
  console.log("\n[1] fresh ko-like seed: the choice card, the strip, the Script tab");
  {
    const { api, document } = await boot(KO);
    check("HAS_SCRIPT on with pack.script + SCRIPT", api.hasScript() && api.scriptTab());
    const h = api.html("panel");
    check("fresh learner: the script choice card shows, Start today is replaced", /id="scriptChoice"/.test(h) && !/id="go"/.test(h));
    check("choice card offers Learn the script / I can read it, skip", /id="scriptLearn"[^>]*>Learn the script</.test(h) && /id="scriptSkip"[^>]*>I can read it, skip</.test(h));
    check("choice card sits above the placement hint", h.indexOf('id="scriptChoice"') < h.indexOf("Take the placement test") && h.indexOf("Take the placement test") > 0);
    check(`strip starts with the script stage (got ${segsOf(h).join(" | ")})`, segsOf(h).join("|") === "한글|A1|A2");
    check("script stage label carries the target-language markup", /<bdi data-tl lang="[^"]+">한글<\/bdi>/.test(h));
    check(`Learn line names the sets (got "${learnLine(h)}")`, learnLine(h) === `한글, sets 1–2 of ${koSets.length}`);
    check(`Review line: skipped until a set is learned (got "${reviewLine(h)}")`, reviewLine(h) === "skipped until a set is learned");
    check("no existing-learner notice on a fresh seed", !/id="scriptNotice"/.test(h));
    const sb = document.tabButtons.find(b => b.dataset.t === "sounds");
    check("the Sounds slot is the Script tab: shown, labelled from the first stage", sb.hidden === false && /<bdi data-tl[^>]*>한글<\/bdi>/.test(sb.innerHTML) && />ㅏ<\/span>/.test(sb.innerHTML));
    api.el("scriptLearn").click();
    const p = api.getProg();
    check("Learn the script: choiceSeen, primer on", p.script.choiceSeen === true && p.script.skipped === false && /id="go"/.test(api.html("panel")) && !/id="scriptChoice"/.test(api.html("panel")));
  }

  // ---------------------------------------------------------------- [2] Learn runs 2 sets
  console.log("\n[2] ko: Start today, Learn set 1, One more set, set 2, finish");
  let afterLearn = null;
  {
    const { api } = await boot(KO);
    api.el("scriptLearn").click();
    api.el("go").click();
    const st = api.getState();
    check("snapshot: script stage, 2 sets (setsPerSession), reviewSize 12", st.snap.stage.kind === "script" && st.snap.ssets.length === 2 && st.snap.reviewSize === 12);
    let h = api.html("panel");
    check("Review skipped (nothing recorded, no words): straight to set 1 teach cards", count(h, /class="xteach"/g) === koSets[0].length && !api.getD());
    check("teach heading: stage label, set position, count", /<bdi[^>]*>한글<\/bdi>, set 1 of 3: 6 new symbols\./.test(h));
    check("teach cards: every set-1 glyph, bold roman, play button (voice)", koSets[0].every(u => h.includes(`>${u.t}</span>`) && h.includes(`<b class="xrm">${u.roman}</b>`)) && count(h, /class="replay xplay"/g) === 6);
    api.el("dr").click();
    const items1 = [api.getCur(), ...api.getD().q];
    check(`set 1 drill: one symSound per unit (${items1.length} items; compose needs syll)`, items1.length === 6 && items1.every(x => x.key.startsWith("x:")));
    let shown = [], err = null;
    try{ shown = playDrill(api); }catch(e){ err = e; }
    check(`set 1 drill plays through${err ? ` (${err.message})` : ""}`, !err && shown.length === 6);
    h = api.html("panel");
    check("end screen offers One more set and Continue", /id="moreSet"[^>]*>One more set</.test(h) && /id="ok"/.test(h));
    check("set 1 recorded in prog.script.u only", koSets[0].every(u => api.getProg().script.u[u.id]) && Object.keys(api.getProg().w).length === 0);
    api.el("moreSet").click();
    h = api.html("panel");
    check("One more set: set 2 teach cards, its rule note first", count(h, /class="xteach"/g) === koSets[1].length && /class="card-teach xnote"><h3>Silent ㅇ<\/h3>/.test(h) && h.indexOf("xnote") < h.indexOf("xteach"));
    check("set 2 card: compose strip ㄴ + ㅏ = 나", /<bdi[^>]*>ㄴ<\/bdi> \+ <bdi[^>]*>ㅏ<\/bdi> = <bdi[^>]*>나<\/bdi>/.test(h));
    check("silent ㅇ card: no play button, its note", /class="xteach"><div class="xhead"><span class="cform xg"[^>]*>ㅇ<\/span><span class="info" dir="ltr"><b class="xrm">ng<\/b><span class="en">silent at the start of a block<\/span><\/span><\/div>/.test(h));
    api.el("dr").click();
    const items2 = [api.getCur(), ...api.getD().q];
    check(`set 2 drill: symSound + compose per consonant, wordRead for silent ㅇ (${items2.length} items)`, items2.length === 15 && items2.filter(x => x.key === "x:ko-ng").length === 1);
    shown = []; err = null;
    try{ shown = playDrill(api); }catch(e){ err = e; }
    check(`set 2 drill plays through${err ? ` (${err.message})` : ""}`, !err && shown.length === 15);
    h = api.html("panel");
    check("no third set offered (setsPerSession 2)", !/id="moreSet"/.test(h));
    api.el("ok").click();
    h = api.html("panel");
    check("Continue: Listen/Recall/Sentences skip without words, session finishes", /Session done/.test(h) && api.getProg().sessions === 1);
    check("both sets recorded (14 units)", Object.keys(api.getProg().script.u).length === 14);
    afterLearn = JSON.parse(JSON.stringify(api.getProg()));
    api.today();
    h = api.html("panel");
    check(`next Today: Learn is set 3 (got "${learnLine(h)}")`, learnLine(h) === "한글, set 3 of 3");
    check(`next Today: Review is 12 script items (got "${reviewLine(h)}")`, reviewLine(h) === "12 items, weakest first, script");
    api.el("go").click();
    const rv = [api.getCur(), ...api.getD().q];
    check("Review drill: 12 script items, every one a script key", rv.length === 12 && rv.every(x => x.key.startsWith("x:")));
    err = null; try{ playDrill(api); }catch(e){ err = e; }
    check(`Review drill plays through${err ? ` (${err.message})` : ""}`, !err);
  }

  // ---------------------------------------------------------------- [3] Progress chips
  console.log("\n[3] Progress: primer off moves Learn to A1 set 1; on brings the script back");
  {
    const { api } = await boot(KO);
    api.setProg(JSON.parse(JSON.stringify(afterLearn)));
    api.goto("progress");
    let h = api.html("panel");
    check("Progress row: 14 / 20 taught · 0 mastered", /<bdi[^>]*>한글<\/bdi><\/td><td>14 \/ 20 taught · 0 mastered<\/td>/.test(h));
    check("chip pair on/off, on pressed, the explanatory line", /id="xOn" aria-pressed="true">Script primer on</.test(h) && /id="xOff" aria-pressed="false">Script primer off</.test(h) && /Changes what Today's Learn step teaches next\. Nothing you've learned is lost\./.test(h));
    check("single-stage pack: no per-stage chips", !/id="xSt0"/.test(h));
    const before = JSON.stringify({ w: api.getProg().w, sets: api.getProg().sets, u: api.getProg().script.u });
    api.el("xOff").click();
    check("off: skipped flag only; records and sets untouched", api.getProg().script.skipped === true && JSON.stringify({ w: api.getProg().w, sets: api.getProg().sets, u: api.getProg().script.u }) === before);
    api.today();
    h = api.html("panel");
    check(`off: Learn is A1 set 1 (got "${learnLine(h)}"), strip without the script stage`, learnLine(h) === "A1, set 1" && segsOf(h).join("|") === "A1|A2");
    check("off: Review has no script items (skipped until words)", reviewLine(h) === "skipped until 5+ words are learned");
    api.goto("progress"); api.el("xOn").click(); api.today();
    h = api.html("panel");
    check(`on again: script stage first, Learn set 3 (got "${learnLine(h)}")`, segsOf(h)[0] === "한글" && learnLine(h) === "한글, set 3 of 3");
    // all mastered: the Script mastered line
    const q = api.getProg(); KO.script.units.forEach(u => { q.script.u[u.id] = { r:3, w:0, s:3 }; });
    api.goto("progress"); h = api.html("panel");
    check("every unit mastered: Script mastered line", /id="xMastered"><td colspan="2">Script mastered<\/td>/.test(h) && /20 \/ 20 taught · 20 mastered/.test(h));
  }

  // ---------------------------------------------------------------- [4] skip
  console.log("\n[4] skip on the choice card");
  {
    const { api } = await boot(KO);
    api.el("scriptSkip").click();
    const h = api.html("panel");
    check("skip: choiceSeen + skipped, Learn is A1 set 1, Start today back", api.getProg().script.skipped === true && api.getProg().script.choiceSeen === true && learnLine(h) === "A1, set 1" && /id="go"/.test(h));
  }

  // ---------------------------------------------------------------- [5] item kinds
  console.log("\n[5] one boot check per item kind");
  const one = async (fx, kind, unitId, opts) => {
    const b = await boot(fx, opts);
    const u = fx.script.units.find(x => x.id === unitId);
    const p = b.api.getProg(); fx.script.units.forEach(x => { p.script.u[x.id] = { r:1, w:0, s:1 }; });
    const it = b.api.scriptDrillItem(kind, u, b.api.scriptCtx());
    b.api.drill([it], () => {});
    return Object.assign(b, { it, u, h: b.api.html("panel") });
  };
  {
    const FA = FX.fa(), JA = FX.ja();
    let r = await one(KO, "symSound", "ko-eo");
    check("symSound: the glyph at 64px class, 4 roman options, no audio before answering", /class="big wd xg"[^>]*>ㅓ</.test(r.h) && r.api.el("o").children.length === 4 && r.spoken.length === 0);
    answer(r.api, true);
    check("symSound: answering plays say once, records the unit, reveal shows name and roman", r.spoken.join("|") === "어" && r.api.getProg().script.u["ko-eo"].s === 2 && /<b>eo<\/b>/.test(r.api.html("rv")));
    r = await one(KO, "soundSym", "ko-a");
    check("soundSym (voice): a speaker, say played before answering, glyph options 2x2", /id="sp"/.test(r.h) && r.spoken[0] === "아" && /class="opts opts-hero opts-w opts-g"/.test(r.h) && r.api.el("o").children.length === 4);
    r = await one(KO, "symType", "ko-g");
    check("symType: glyph + a typed input", /class="big wd xg"[^>]*>ㄱ</.test(r.h) && /id="tin"/.test(r.h) && /placeholder="type the sound"/.test(r.h));
    r.api.el("tin").value = "K"; r.api.el("submit").click();
    check("symType: an alt (k) is accepted, case-insensitive", r.api.getProg().script.u["ko-g"].s === 2);
    r = await one(KO, "compose", "ko-n");
    check("compose: parts joined with +, syllable options", /class="big wd xg"[^>]*>ㄴ \+ ㅏ<|class="big wd xg"[^>]*>ㄴ \+ ㅓ</.test(r.h) && r.api.el("o").children.length >= 2);
    answer(r.api, true);
    check("compose: reveal shows parts = block", /<div class="rw xrs"><bdi[^>]*>ㄴ<\/bdi> \+ <bdi[^>]*>ㅏ|ㅓ/.test(r.api.html("rv")));
    r = await one(FA, "formFind", "fa-be");
    check("formFind: letter + its name, word options (target markup, rtl)", /class="big wd xg"[^>]*>ب</.test(r.h) && /<div class="pron">be<\/div>/.test(r.h) && r.api.el("o").children.every(b => b.dir === "rtl"));
    r = await one(FA, "formMatch", "fa-be");
    check("formMatch: a joined form with ZWJ and its form name, glyph options", /class="big wd xg"[^>]*>[^<]*‍[^<]*</.test(r.h) && /<div class="pron">(initial|medial|final) form<\/div>/.test(r.h));
    r = await one(KO, "wordRead", "ko-a");
    check("wordRead: the word, roman options, no audio before", /class="big wd xg"[^>]*>나</.test(r.h) && r.spoken.length === 0);
    answer(r.api, true);
    check("wordRead: word audio after, reveal has the word, roman and gloss", r.spoken.join("|") === "나" && /class="rw"[^>]*>나/.test(r.api.html("rv")) && />I<\/div>/.test(r.api.html("rv")));
    r = await one(JA, "wordHear", "ja-ga");
    check("wordHear (voice): speaker, the word spoken before, word options", /id="sp"/.test(r.h) && r.spoken[0] === "がか" && r.api.el("o").children.length >= 2);
    check("ja: a word written with symbols the primer does not teach is shown by its kana pron", r.api.byId()[JA.words.find(w => w.w === "画家").id].w === "がか" && r.api.byId()[JA.words.find(w => w.w === "アイス").id].w === "アイス");
  }

  // ---------------------------------------------------------------- [6] no voice
  console.log("\n[6] no-voice path: fa (tts:false legacy hard off), ko and fa with voices stubbed out");
  {
    const FA = FX.fa();
    let r = await one(FA, "soundSym", "fa-be");
    check("fa soundSym: the roman as text, no speaker, nothing spoken", /<div class="med"[^>]*>b<\/div>/.test(r.h) && !/id="sp"/.test(r.h) && r.spoken.length === 0);
    r = await one(FA, "wordHear", "fa-be");
    check("fa wordHear becomes wordRead", r.it.key === "x:fa-be" && /How is it read\?/.test(r.h) && !/id="sp"/.test(r.h));
    const tb = await boot(FA);
    const card = tb.api.scriptTeachHTML(FA.script.units.find(u => u.id === "fa-be"));
    check("fa teach card: no play button, no word taps", !/xplay/.test(card) && !/data-xw/.test(card));
    r = await one(KO, "soundSym", "ko-a", { voices: NOVOICE });
    check("ko with no browser voice: soundSym shows the roman", /<div class="med"[^>]*>a<\/div>/.test(r.h) && !/id="sp"/.test(r.h));
    r = await one(KO, "wordHear", "ko-a", { voices: NOVOICE });
    check("ko with no browser voice: wordHear becomes wordRead", /How is it read\?/.test(r.h));
    const withAudio = FX.fa(); withAudio.script.units.find(u => u.id === "fa-be").audio = "audio/be.mp3";
    r = await one(withAudio, "soundSym", "fa-be");
    check(`a recorded audio clip plays even with tts:false (speaker shown, clip played: ${JSON.stringify(r.played)})`, /id="sp"/.test(r.h) && r.played.length === 1 && r.spoken.length === 0);

    // a fa-like pack with tts true + carriers (fa itself ships tts false): whether it speaks
    // is decided by getVoices() having a voice for the pack's lang, never by an utterance
    // "succeeding" (onend fires silently for a lang-tag-only request with no voice)
    const faLive = () => { const f = FX.fa(); f.pack.script.tts = true;
      f.script.units.forEach(u => { u.say = "اآوی".includes(u.t) ? u.t : u.t + "\u064E"; }); return f; };
    r = await one(faLive(), "soundSym", "fa-be");
    check(`fa tts:true with an fa-IR voice: soundSym has the speaker and speaks the carrier (${JSON.stringify(r.spoken)})`, /id="sp"/.test(r.h) && r.spoken.join("|") === "بَ");
    r = await one(faLive(), "wordHear", "fa-be");
    check("fa tts:true with an fa-IR voice: wordHear stays a listening item", r.it.key === "x:fa-be" && !/How is it read\?/.test(r.h) && /id="sp"/.test(r.h));
    const lb = await boot(faLive());
    check("fa tts:true with an fa-IR voice: teach card has the play button", /xplay/.test(lb.api.scriptTeachHTML(faLive().script.units.find(u => u.id === "fa-be"))));
    r = await one(faLive(), "soundSym", "fa-be", { voices: NOVOICE });
    check("fa tts:true, voice list without fa: soundSym degrades to the roman, nothing spoken", /<div class="med"[^>]*>b<\/div>/.test(r.h) && !/id="sp"/.test(r.h) && r.spoken.length === 0);
    r = await one(faLive(), "wordHear", "fa-be", { voices: NOVOICE });
    check("fa tts:true, voice list without fa: wordHear becomes wordRead", /How is it read\?/.test(r.h) && !/id="sp"/.test(r.h));
    const nb = await boot(faLive(), { voices: NOVOICE });
    check("fa tts:true, voice list without fa: teach card has no play button", !/xplay/.test(nb.api.scriptTeachHTML(faLive().script.units.find(u => u.id === "fa-be"))));
    r = await one(faLive(), "soundSym", "fa-be", { voices: [] });
    check("fa tts:true, empty voice list = not loaded yet: sound items stay on", /id="sp"/.test(r.h));
    // the stub's speak() "succeeds" for any utterance; a voice list without fa must still be no voice
    const LANGLESS = [{ lang:"en-US", name:"e" }, { lang:"", name:"Google" }, { name:"x" }, { lang:"far", name:"f" }];
    r = await one(faLive(), "soundSym", "fa-be", { voices: LANGLESS });
    check("fa tts:true, voices without an fa lang (lang-less/unrelated only): no speaker, nothing spoken", !/id="sp"/.test(r.h) && r.spoken.length === 0);
    check("speechUsable: a lang-tag-only request is not a voice (no fa in getVoices -> false; fa or fa-IR -> true)",
      VC.speechUsable(true, LANGLESS, "fa-IR") === false && VC.speechUsable(true, [{ lang:"fa" }], "fa-IR") === true
      && VC.speechUsable(true, [{ lang:"fa_IR" }], "fa-IR") === true && VC.pickVoice(LANGLESS, "fa-IR") === null);
  }

  // ---------------------------------------------------------------- [7] teach-card rows
  console.log("\n[7] teach-card rows: forms strip, base -> variant, italic, highlight");
  {
    const FA = FX.fa(), JA = FX.ja(), RU = ru();
    const fb = await boot(FA);
    const be = fb.api.scriptTeachHTML(FA.script.units.find(u => u.id === "fa-be"));
    const cells = h => count(h, /class="xfc"/g);
    check("fa dual joiner: 4-cell forms strip, right to left, isolated first", /class="xforms" dir="rtl"/.test(be) && cells(be) === 4 && /class="xff"[^>]*>ب<\/span><span class="xfl" dir="ltr">isolated/.test(be));
    check("fa forms rendered with ZWJ (init L+ZWJ, medi ZWJ+L+ZWJ, fina ZWJ+L)", be.includes(">ب‍<") && be.includes(">‍ب‍<") && be.includes(">‍ب<"));
    const dal = fb.api.scriptTeachHTML(FA.script.units.find(u => u.id === "fa-dal"));
    check("fa right joiner: 2 cells (isolated, final)", cells(dal) === 2 && /isolated[\s\S]*final/.test(dal));
    check("fa head is right-to-left (glyph on the right)", /<div class="xhead" dir="rtl">/.test(be));
    check("fa example: the letter tinted by a wrapping span inside the word", /<span class="wd"[^>]*><span class="xhl">ب<\/span>ا<span class="xhl">ب<\/span>ا<\/span>/.test(be));
    const jb = await boot(JA);
    const ka = jb.api.scriptTeachHTML(JA.script.units.find(u => u.id === "ja-ka-a"));
    check("ja kata: base -> variant row (あ → ア)", /<bdi[^>]*>あ<\/bdi> → <bdi[^>]*>ア<\/bdi>/.test(ka));
    const ga = jb.api.scriptTeachHTML(JA.script.units.find(u => u.id === "ja-ga"));
    check("ja dakuten: か → が, example shown in kana with が tinted", /<bdi[^>]*>か<\/bdi> → <bdi[^>]*>が<\/bdi>/.test(ga) && /<span class="xhl">が<\/span>か/.test(ga));
    const rb = await boot(RU);
    const d = rb.api.scriptTeachHTML(RU.script.units.find(u => u.id === "ru-d"));
    check("ru: upper and lower on the card, italic form in italic", /class="cform xg"[^>]*>Д д</.test(d) && /class="xit"[^>]*>д</.test(d));
    const kb = await boot(KO);
    const n = kb.api.scriptTeachHTML(KO.script.units.find(u => u.id === "ko-n"));
    check("ko: the jamo tints its whole block in the example (나)", /<span class="xhl">나<\/span>/.test(n));
    check("ko batchim: final ㄱ (U+11A8) tints its block (책), initial too (국)", kb.api.scriptHL("책", "ㄱ") === '<span class="xhl">책</span>'
      && kb.api.scriptHL("한국", "ㄱ") === '한<span class="xhl">국</span>' && kb.api.scriptHL("몸", "ㅁ") === '<span class="xhl">몸</span>');
    check("fold also covers case and آ (Москва м, آب ا)", kb.api.scriptHL("Москва", "м") === '<span class="xhl">М</span>осква' && kb.api.scriptHL("آب", "ا") === '<span class="xhl">آ</span>ب');
    const esc = FX.ko(); esc.script.units[0].note = "<img src=x onerror=alert(1)>"; esc.script.units[0].name = "<b>"; esc.script.notes[0].body = "<script>x</script>";
    const eb = await boot(esc);
    const eh = eb.api.scriptTeachHTML(esc.script.units[0]);
    check("pack text is escaped (note, name)", !/<img/.test(eh) && eh.includes("&lt;img") && eh.includes("&lt;b&gt;"));

    // Shaping clusters: a tint never puts an element boundary inside a mandatory ligature
    // (Arabic-script lam + alef) or a Brahmic conjunct (consonant + virama + consonant).
    // Every letter of every word is tried as the glyph; the tint must still be there.
    const HL = fb.api.scriptHL;
    const LAM = "ل", ALEFS = "اأإآٱ", VIR = "्";
    // true when a tag sits between lam(+marks) and an alef, right after a virama(+ZWJ), or before a mark
    const splits = h => new RegExp(`${LAM}[\\u064b-\\u065f\\u0670]*<[^>]*>(?:<[^>]*>)*[${ALEFS}]`).test(h) || new RegExp(`${VIR}\\u200d?<[^>]*>`).test(h) || /<[^>]*>[\p{M}\u200c\u200d]/u.test(h); // or a mark cut off its base
    const sweep = words => words.flatMap(w => [...new Set([...w].filter(c => !/[ً-़्ٰٟ‍]/.test(c)))].map(g => ({ w, g, h: HL(w, g) })));
    const AR = ["لا", "سلام", "الأب", "سلآم", "إلى", "لإس", "لَا", "الٱبن"];
    const FAW = ["کلاس", "لاله", "بلا", "بابا"];
    const HI = ["क्षमा", "स्त्री", "पर्व", "विद्या"];
    const arS = sweep(AR), faS = sweep(FAW), hiS = sweep(HI);
    check(`ar: no element boundary between lam and alef for any tinted letter (${arS.length} word/letter pairs)`, arS.every(x => !splits(x.h) && x.h.includes('class="xhl"')), arS.filter(x => splits(x.h)).map(x => x.h).join(" | "));
    check(`fa: same for Persian words (کلاس, لاله, بلا, بابا; ${faS.length} pairs)`, faS.every(x => !splits(x.h) && x.h.includes('class="xhl"')), faS.filter(x => splits(x.h)).map(x => x.h).join(" | "));
    check(`hi: no element boundary after a virama (क्ष, स्त्री, र्व, द्या; ${hiS.length} pairs)`, hiS.every(x => !splits(x.h) && x.h.includes('class="xhl"')), hiS.filter(x => splits(x.h)).map(x => x.h).join(" | "));
    check("ar: tinting ل or ا in لا tints the whole ligature; سلام tints لا only; بابا still tints each ب alone",
      HL("لا", "ل") === '<span class="xhl">لا</span>' && HL("لا", "ا") === '<span class="xhl">لا</span>'
      && HL("سلام", "ل") === 'س<span class="xhl">لا</span>م' && HL("بابا", "ب") === '<span class="xhl">ب</span>ا<span class="xhl">ب</span>ا');
    check("ar: a haraka stays inside its letter's tint (بَاب: ب tint holds the fatha)", HL("بَاب", "ب") === '<span class="xhl">بَ</span>ا<span class="xhl">ب</span>');
    check("hi: क in क्षमा tints the conjunct क्ष; ZWNJ after the virama (explicit halant) splits",
      HL("क्षमा", "क") === '<span class="xhl">क्ष</span>मा' && VC.shapingClusters("क्‌ष").length === 2 && VC.shapingClusters("क्ष").length === 1);
    check("ar: a ZWJ between lam and alef keeps them one cluster (shapers ligate through ZWJ)", VC.shapingClusters("\u0644\u200d\u0627").length === 1 && HL("\u0644\u200d\u0627\u0645", "\u0627") === '<span class="xhl">\u0644\u200d\u0627</span>\u0645');
    check("browser layer: the ::highlight tint also recolours the glyph (thin joined letters stay visible without the span's spread)", /::highlight\(xhl\)\{background-color:var\(--ok-bg\);color:var\(--ok\)\}/.test(appHtml));
    check("ar: tatweel between lam and alef blocks the ligature, so they are separate clusters", VC.shapingClusters("لـا").length >= 2);
    check("browser layer: paintScriptHL runs after both teach-card insertions and a ::highlight(xhl) rule exists",
      /paintScriptHL\(\$\("xtl"\)\)/.test(appSrc) && /c\.innerHTML = scriptTeachHTML\(u\);\s*paintScriptHL\(c\);/.test(appSrc) && /::highlight\(xhl\)\{background-color:var\(--ok-bg\)/.test(appHtml));
    // Note equal to the roman is not shown twice ("b | b"); a real note still is.
    const dup = FX.fa(); const bu = dup.script.units.find(u => u.id === "fa-be"); bu.note = " " + String(bu.roman).toUpperCase() + " ";
    const db = await boot(dup);
    const dh = db.api.scriptTeachHTML(bu);
    const dItem = VC.scriptItem("symSound", bu, { units: dup.script.units, words: dup.words });
    check("teach card and answer screen drop a note that only repeats the roman", !/<span class="en">/.test(dh.match(/<div class="xhead"[\s\S]*?<\/div>/)[0]) && dItem.reveal.note === "");
    const rn = FX.fa(); const ru2 = rn.script.units.find(u => u.id === "fa-be"); ru2.note = "as in boy";
    const rb2 = await boot(rn);
    check("... a note that says more is kept on both", /<span class="en">as in boy<\/span>/.test(rb2.api.scriptTeachHTML(ru2)) && VC.scriptItem("symSound", ru2, { units: rn.script.units, words: rn.words }).reveal.note === "as in boy");
    // Head name equal to the roman is not shown twice ("ka | ka"); a real name still is.
    const dupN = FX.fa(); const nu = dupN.script.units.find(u => u.id === "fa-be"); nu.name = String(nu.roman);
    const dbN = await boot(dupN);
    const dhN = dbN.api.scriptTeachHTML(nu);
    const nItem = VC.scriptItem("symSound", nu, { units: dupN.script.units, words: dupN.words });
    check("teach card and answer screen drop a head name that only repeats the roman",
      !/class="xnm"/.test(dhN.match(/<div class="xhead"[\s\S]*?<\/div>/)[0]) && nItem.reveal.name === "");
    const rnN = FX.fa(); const ru3 = rnN.script.units.find(u => u.id === "fa-be"); ru3.name = "be";
    const rbN = await boot(rnN);
    // (A Latin name in an RTL pack is UI text: plain, no dir=rtl / pack-font bdi; RTL rendering rules.)
    check("... a head name that differs from the roman is kept on both",
      /class="xnm">be<\/span>/.test(rbN.api.scriptTeachHTML(ru3)) && VC.scriptItem("symSound", ru3, { units: rnN.script.units, words: rnN.words }).reveal.name === "be");
    // RTL answer block: one edge for every line (root flag + rule), LTR packs untouched.
    check("rtl pack: root carries data-tlrtl, and .reveal/.rvb align right under it", fb.document.documentElement._attrs["data-tlrtl"] === "" && /:root\[data-tlrtl\] \.reveal,:root\[data-tlrtl\] \.rvb\{text-align:right\}/.test(appHtml));
    check("ltr pack (ko): no data-tlrtl on the root", kb.document.documentElement._attrs["data-tlrtl"] === undefined);
  }

  // ---------------------------------------------------------------- [8] existing learner
  console.log("\n[8] existing learner: boots skipped, the notice once");
  {
    const key = VC.storageKey(KO.pack);
    const w = KO.words[0].id;
    const stored = { v:1, w: { [w]: { r:2, w:0, s:2 } }, s:{}, sets: { A1: 1 }, lessons:{}, sessions: 3, placedOnce: true };
    const storage = memStore({ [key]: JSON.stringify(stored) });
    let b = await boot(KO, { storage });
    let h = b.api.html("panel");
    check("stored progress with words, no script field: primer skipped, choice answered", b.api.getProg().script.skipped === true && b.api.getProg().script.choiceSeen === true);
    check("the notice shows once on Today, no choice card, no script stage", count(h, /id="scriptNotice"/g) === 1 && /A script primer is available\. Turn it on in Progress\./.test(h) && !/scriptChoice/.test(h) && segsOf(h)[0] === "A1");
    b.api.el("scriptNoticeOk").click();
    h = b.api.html("panel");
    check("dismissed: gone, stored notice false", !/scriptNotice/.test(h) && JSON.parse(storage.getItem(key)).script.notice === false);
    b = await boot(KO, { storage });
    check("after a reload: still gone", !/scriptNotice/.test(b.api.html("panel")));
    // Not dismissed, but the primer turned on from Progress and off again: the notice is
    // cleared (stored false), so it does not come back.
    const storage2 = memStore({ [key]: JSON.stringify(stored) });
    b = await boot(KO, { storage: storage2 });
    check("second learner: notice pending", /id="scriptNotice"/.test(b.api.html("panel")));
    b.api.goto("progress"); b.api.el("xOn").click();
    check("turned on from Progress: stored notice false", JSON.parse(storage2.getItem(key)).script.notice === false && b.api.getProg().script.skipped === false);
    b.api.el("xOff").click(); b.api.today();
    check("turned off again: the notice does not come back", b.api.getProg().script.skipped === true && !/scriptNotice/.test(b.api.html("panel")));
    b = await boot(KO, { storage: storage2 });
    check("after a reload: still no notice", !/scriptNotice/.test(b.api.html("panel")));
    const fresh = await boot(KO);
    check("fresh learner: never the notice", !/scriptNotice/.test(fresh.api.html("panel")));
  }

  // ---------------------------------------------------------------- [9] Script tab
  console.log("\n[9] Script tab: chart, one utterance per tap, practice");
  {
    const b = await boot(KO);
    const p = b.api.getProg(); VC.answerScriptChoice(p, true);
    koSets[0].forEach((u, i) => { p.script.u[u.id] = i < 2 ? { r:3, w:0, s:3 } : { r:1, w:0, s:1 }; });
    b.api.goto("sounds");
    const h = b.api.html("panel");
    check("htitle is the stage label", b.api.el("htitle").textContent === "한글");
    check("chart: every unit a cell, grouped by set", count(h, /data-xopen/g) === KO.script.units.length && count(h, /class="xset"/g) === koSets.length);
    check("chart marks: 2 mastered, 4 taught", count(h, /<button type="button" class="xm"/g) === 2 && count(h, /<button type="button" class="xt"/g) === 4);
    check("Practise weakest N (the recorded units)", /id="xPractise"[^>]*>Practise weakest 6</.test(h));
    const lis = b.api.panelListeners();
    const cell = { dataset: { xs: "ko-eo", xopen: "" }, classList: { add(){}, remove(){} } };
    const n0 = b.spoken.length;
    lis.forEach(f => f({ target: { closest: () => cell } }));
    check(`a cell tap plays exactly one utterance (${b.spoken.length - n0}) and opens its teach card`, b.spoken.length - n0 === 1 && b.spoken[b.spoken.length - 1] === "어" && /class="xteach"/.test(b.api.html("xcard")));
    check("exactly one panel click listener handles it", lis.length === 1);
    b.api.el("xPractise").click();
    const q = [b.api.getCur(), ...b.api.getD().q];
    check("practice drill: the 6 recorded units", q.length === 6 && q.every(x => x.key.startsWith("x:")));
    let err = null; try{ playDrill(b.api); }catch(e){ err = e; }
    check(`practice drill (with symType) plays through${err ? ` (${err.message})` : ""}`, !err);
  }

  // ---------------------------------------------------------------- [10] ja two stages
  console.log("\n[10] ja: two stages, per-stage chips");
  {
    const JA = FX.ja();
    const b = await boot(JA);
    let h = b.api.html("panel");
    check("choice card names both stages", /<bdi[^>]*>ひらがな<\/bdi> and <bdi[^>]*>カタカナ<\/bdi> first/.test(h));
    check(`strip: ひらがな, カタカナ, A1, A2 (got ${segsOf(h).join(" | ")})`, segsOf(h).join("|") === "ひらがな|カタカナ|A1|A2");
    b.api.el("scriptLearn").click();
    b.api.goto("progress"); h = b.api.html("panel");
    check("per-stage chips while the primer is on", /id="xSt0" aria-pressed="true"><bdi[^>]*>ひらがな/.test(h) && /id="xSt1" aria-pressed="true"><bdi[^>]*>カタカナ/.test(h));
    b.api.el("xSt0").click();
    check("hira chip off: skip.hira only", b.api.getProg().script.skip.hira === true && b.api.getProg().script.skipped === false);
    b.api.today(); h = b.api.html("panel");
    check(`hira off: the path starts with カタカナ, Learn is kata sets (got "${learnLine(h)}")`, segsOf(h)[0] === "カタカナ" && learnLine(h) === "カタカナ, sets 1–2 of 2");
  }

  // ---------------------------------------------------------------- [11] flag-off
  console.log("\n[11] flag-off: no pack.script, no script markup");
  {
    const off = FX.ko(); delete off.pack.script;
    const b = await boot(off, { script: false });
    const h = b.api.html("panel");
    const sb = b.document.tabButtons.find(x => x.dataset.t === "sounds");
    check("no pack.script: HAS_SCRIPT off, Sounds hidden (no lessons), no choice card, strip is the levels", !b.api.hasScript() && sb.hidden === true && !/script/i.test(h.replace(/<\/?script/g, "")) && segsOf(h).join("|") === "A1|A2" && /id="go"/.test(h));
    const noData = await boot(KO, { script: false });
    check("pack.script without script.js: primer off, no choice card", !noData.api.hasScript() && !/scriptChoice/.test(noData.api.html("panel")));
    check("engine/app.html: dev loader lists script.js", /\["pack","words","sentences","lessons","characters","script","legacy"\]/.test(appHtml));
  }
  // pack.script without its data, on a characters pack (the crash that
  // characters_app_checks [15] hit on ../japanese/pack): the primer is off everywhere,
  // one console warning, never a crash; the Today snapshot equals the flag-off one.
  {
    const ZH = path.join(ROOT, "packs", "zh");
    const ld = (f, n) => new Function(fs.readFileSync(path.join(ZH, f), "utf8") + `\nreturn ${n};`)();
    const zp = ld("pack.js", "PACK"), zw = ld("words.js", "WORDS"), zc = ld("characters.js", "CHARACTERS");
    const withScript = Object.assign({}, zp, { script: FX.ko().pack.script });
    for(const [what, data] of [["no script.js", false], ["empty units", { units: [], notes: [] }]]){
      const warns = [];
      const con = Object.assign(Object.create(console), { warn: (...a) => warns.push(a.join(" ")) });
      let b = null, err = null, hs = {};
      try{
        b = await boot({ pack: withScript, words: zw, script: data || undefined }, { script: data ? undefined : false, extra: { CHARACTERS: zc }, console: con });
        b.api.today(); hs.today = b.api.html("panel");
        b.api.goto("progress"); hs.progress = b.api.html("panel");
        b.api.goto("sounds"); hs.sounds = b.api.html("panel");
        b.api.today(); b.api.el("go").click(); hs.snap = b.api.getState().snap;
      }catch(e){ err = e; }
      const flagOff = VC.todaySnapshot(zp, zw, zc, VC.defaultProg(zp));
      check(`pack.script + ${what} on a characters pack: boots, Today/Progress/Sounds render, no crash${err ? ` (${err.message})` : ""}`, !err && /id="go"|id="charChoice"/.test(hs.today) && !!hs.progress);
      check(`... primer off everywhere: no choice card, notice, chips or script stage; one warning (${warns.length})`,
        !err && !b.api.hasScript() && !/scriptChoice|scriptNotice|scriptCtl|xtab/.test(hs.today + hs.progress + hs.sounds) && warns.length === 1 && /script primer is off/.test(warns[0]));
      check(`... the Today snapshot equals the flag-off snapshot`, !err && JSON.stringify(hs.snap) === JSON.stringify(flagOff));
    }
    check("core: scriptActive needs config and units; path/choice/snapshot ignore pack.script without units",
      VC.scriptActive(withScript, FX.ko().script.units) && !VC.scriptActive(withScript, []) && !VC.scriptActive(withScript, undefined) && !VC.scriptActive(zp, FX.ko().script.units)
      && JSON.stringify(VC.stagePath(withScript, zw, zc, VC.defaultProg(withScript))) === JSON.stringify(VC.stagePath(zp, zw, zc, VC.defaultProg(zp)))
      && VC.showScriptChoice(withScript, [], VC.defaultProg(withScript)) === false);
  }
  // The built page runs every inline <script> in one global scope: script.js's
  // `const SCRIPT` must not collide with anything the app declares.
  {
    const os = require("os"), vm = require("vm"), cp = require("child_process");
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "ve-s3-")), pk = path.join(dir, "pack");
    fs.mkdirSync(pk);
    const K = FX.ko();
    fs.writeFileSync(path.join(pk, "pack.js"), `const PACK=${JSON.stringify(K.pack)};\n`);
    fs.writeFileSync(path.join(pk, "words.js"), `const WORDS=${JSON.stringify(K.words)};\n`);
    fs.writeFileSync(path.join(pk, "sentences.js"), "const SENTENCES=[];\n");
    fs.writeFileSync(path.join(pk, "script.js"), `const SCRIPT=${JSON.stringify(K.script)};\n`);
    const out = path.join(dir, "ko.html");
    const b = cp.spawnSync("sh", [path.join(ROOT, "build.sh"), pk, out], { encoding: "utf8" });
    let err = null, has = null;
    try{
      const html = fs.readFileSync(out, "utf8");
      const blocks = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]);
      const document = makeFakeDom();
      const ss = { getVoices: () => [{ lang:"ko-KR", name:"v" }], onvoiceschanged: null, cancel(){}, speak(){} };
      const win = { speechSynthesis: ss, SpeechSynthesisUtterance: function(){}, addEventListener(){}, matchMedia: () => ({ matches:false }) };
      const ctx = vm.createContext(Object.assign(win, { document, navigator: { userAgent:"x", serviceWorker: undefined }, location: { protocol:"file:", search:"" },
        localStorage: memStore(), requestAnimationFrame: fn => setTimeout(fn, 0), Audio: function(){ return { play(){ return Promise.resolve(); }, pause(){} }; }, confirm: () => true, alert(){}, console, setTimeout }));
      ctx.window = ctx;
      blocks.forEach(src => vm.runInContext(src, ctx));
      await tick(); await tick();
      has = vm.runInContext("HAS_SCRIPT && typeof DISP === 'object' && /scriptChoice/.test(document.getElementById('panel').innerHTML)", ctx);
    }catch(e){ err = e; }
    check(`built page with script.js: every inline script runs in one scope, primer on${err ? ` (${err.message})` : ""}`, b.status === 0 && !err && has === true, `status ${b.status} has ${has} ${b.stderr}`);
    fs.rmSync(dir, { recursive: true, force: true });
  }

  // ---------------------------------------------------------------- [12] 390px width proxy
  // No layout engine here: widths are estimated from the markup and the CSS rules that
  // bound them. Content width at 390px = 390 - 2 x 16px .wrap padding = 358px. A glyph is
  // taken as 1em wide per code point (wide scripts), a Latin letter 0.6em.
  console.log("\n[12] 390px width proxy: teach card and chart");
  {
    const W = 358;
    const css = (sel) => { const m = appHtml.match(new RegExp(sel.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + "\\{([^}]*)\\}")); return m ? m[1] : ""; };
    const px = (s, prop) => { const m = s.match(new RegExp("(?:^|;)" + prop + ":(\\d+)px")); return m ? +m[1] : null; };
    const cform = css(".xhead .cform"), info = css(".xhead .info"), fc = css(".xfc"), ff = css(".xff"), cellsCss = css(".refcells"), cellBtn = css(".xcells button");
    check("teach head: glyph bounded (max-width 50%, overflow-wrap), info column shrinks (min-width 0)", /max-width:50%/.test(cform) && /overflow-wrap:anywhere/.test(cform) && /min-width:0/.test(info) && /overflow-wrap:anywhere/.test(css(".xhead .en")));
    check("forms strip cells shrink (flex 1 1 0, min-width 0); chart cells wrap", /flex:1 1 0/.test(fc) && /min-width:0/.test(fc) && /flex-wrap:wrap/.test(cellsCss));
    const glyphPx = px(cform, "font-size"), formPx = px(ff, "font-size");
    let worst = { w: 0 }, strip = 0;
    for(const fx of [FX.ko(), FX.fa(), FX.ja(), ru()]){
      for(const u of fx.script.units){
        const t = String(u.t);
        const gw = [...t].length * glyphPx; // the glyph box before its 50% cap
        const need = Math.min(gw, W * 0.5) + 14 + 64 + 14 + 44; // glyph, gap, info min, gap, play
        if(need > worst.w) worst = { w: need, id: u.id };
        if(u.joins){ const n = u.joins === "dual" ? 4 : 2; strip = Math.max(strip, n * (formPx * 1.2 + 4 + 2) + (n - 1) * 6); }
      }
    }
    check(`teach head fits 358px at 390 (worst ${Math.round(worst.w)}px, ${worst.id})`, worst.w <= W);
    check(`fa forms strip fits 358px (4 cells: ${Math.round(strip)}px)`, strip > 0 && strip <= W);
    // Chart: the widest single cell (glyph + roman stacked) must fit the row beside the set number.
    let wideCell = 0;
    for(const fx of [FX.ko(), FX.fa(), FX.ja(), ru()]) for(const u of fx.script.units){
      const w = Math.max(px(cellBtn, "min-width"), Math.max([...VC.scriptGlyph(u)].length * 20, String(u.roman).length * 11 * 0.6) + 16 + 2);
      if(w > wideCell) wideCell = w;
    }
    check(`chart: the widest cell (${Math.round(wideCell)}px) fits beside the set number (${W - 14 - 8}px)`, wideCell <= W - 14 - 8);
    check("glyph options: 2 columns of minmax(0,1fr) (never wider than the row)", /grid-template-columns:repeat\(2,minmax\(0,1fr\)\)/.test(css(".opts-g")));
  }

  // ---------------------------------------------------------------- [13] real sibling packs
  // S2's data (../{korean,russian,persian,japanese}/pack) when present; skipped otherwise
  // (the data lives in the sibling repos, not here). Read-only.
  console.log("\n[13] real sibling packs (when present): boot, two Learn sets, every unit x kind, width proxy");
  for(const lang of ["korean","russian","persian","japanese"]){
    const dir = path.join(ROOT, "..", lang, "pack");
    const f = n => path.join(dir, n + ".js");
    if(![f("pack"), f("words"), f("script")].every(x => fs.existsSync(x))){ console.log(`SKIP  ${lang}: no pack/script.js`); continue; }
    const load = (file, name) => new Function(fs.readFileSync(file, "utf8") + `\nreturn ${name};`)();
    const pack = load(f("pack"), "PACK");
    if(!pack.script){ console.log(`SKIP  ${lang}: pack.js has no script block`); continue; }
    const fx = { pack, words: load(f("words"), "WORDS"), script: load(f("script"), "SCRIPT") };
    const units = fx.script.units;
    const b = await boot(fx);
    let h = b.api.html("panel");
    check(`${lang}: fresh boot shows the choice card (${units.length} units)`, /id="scriptChoice"/.test(h) && b.api.hasScript());
    b.api.el("scriptLearn").click(); b.api.el("go").click();
    let err = null, n = 0;
    try{
      n += playDrillFrom(b.api, "dr");
      if(b.api.el("moreSet") && /id="moreSet"/.test(b.api.html("panel"))){ b.api.el("moreSet").click(); n += playDrillFrom(b.api, "dr"); }
    }catch(e){ err = e; }
    const sets = VC.scriptSets(pack.script.stages[0].key, units);
    check(`${lang}: Learn runs sets 1 and 2 (${n} items)${err ? ` (${err.message})` : ""}`, !err && [...sets[0], ...sets[1]].every(u => b.api.getProg().script.u[u.id]));
    // Every unit x every kind it can carry: item builds, renders, has >= 2 options (mc).
    const p = b.api.getProg(); units.forEach(u => { p.script.u[u.id] = { r:1, w:0, s:1 }; });
    const bad = [], kctx = b.api.kindCtx(); let unfit = 0;
    units.forEach(u => VC.SCRIPT_KINDS.forEach(k => {
      const kk = k === "wordHear" && kctx.tts === false ? "wordRead" : k;
      if(!VC.scriptKindShape(kk, u)) return;
      if(!VC.scriptKindFits(kk, u, kctx)){ unfit++; return; }
      try{
        const it = b.api.scriptDrillItem(k, u, b.api.scriptCtx());
        if(it.kind === "mc" && !(it.opts.length >= 4 && it.opts.includes(it.a) && new Set(it.opts).size === it.opts.length)) bad.push(`${u.id}/${k}: opts ${JSON.stringify(it.opts)}`);
        b.api.drill([it], () => {});
      }catch(e){ bad.push(`${u.id}/${k}: ${e.message}`); }
    }));
    check(`${lang}: every unit x kind that fits (4-option rule; ${unfit} shaped but unfit) builds and renders with >= 4 distinct options holding the answer (${bad.length} bad)`, bad.length === 0, bad.slice(0, 5).join("; "));
    const plans = [...VC.learnScriptPlan(units, pack, kctx), ...VC.scriptTestPlan(units, b.api.getProg(), pack, 500, undefined, kctx)];
    check(`${lang}: Learn and practice plans pick only kinds that fit (${plans.length} entries)`, plans.every(x => x.kind === "symType" || VC.scriptKindFits(x.kind, x.unit, kctx)));
    let cardErr = null, heads = 0;
    try{ units.forEach(u => { const c = b.api.scriptTeachHTML(u); if(/class="xhead/.test(c)) heads++; }); }catch(e){ cardErr = e; }
    check(`${lang}: every unit's teach card renders${cardErr ? ` (${cardErr.message})` : ""}`, !cardErr && heads === units.length);
    const wide = units.map(u => ({ id: u.id, w: Math.min([...String(u.t)].length * 64, 179) + 14 + 64 + 14 + 44 })).sort((x, y) => y.w - x.w)[0];
    const cell = Math.max(...units.map(u => Math.max(48, Math.max([...VC.scriptGlyph(u)].length * 20, String(u.roman).length * 11 * 0.6) + 18)));
    check(`${lang}: 390px proxy: teach head ${wide.w}px (${wide.id}) and widest chart cell ${Math.round(cell)}px fit`, wide.w <= 358 && cell <= 336);
    b.api.goto("sounds");
    check(`${lang}: Script tab chart has every unit`, count(b.api.html("panel"), /data-xopen/g) === units.length);
  }

  // ---------------------------------------------------------------- [14] RTL rendering rules
  console.log("\n[14] RTL rendering rules: bidi isolation and pack font on rendered markup (fa-like)");
  {
    const FA = FX.fa();
    FA.words.forEach(w => { w.en = `${w.en} (${w.w} / ${w.w})`; });
    const bk = FA.words.find(w => w.w === "کتاب"); bk.en = "book (کتاب‌ها: books)";
    FA.script.notes[0].body = "Short vowels are not written: کتاب is read ketâb.";
    const b = await boot(FA); const api = b.api;
    const rr = api.ui(bk.en);
    check("ui(): each RTL run in a gloss is its own <bdi data-tl lang dir=rtl class=tlf>, the English around it escaped, text unchanged",
      rr === 'book (<bdi data-tl lang="fa" dir="rtl" class="tlf">کتاب‌ها</bdi>: books)' && stripTags(rr) === bk.en);
    check("ui(): a Latin-only string is exactly escapeHtml", api.ui("a <b> & 'c'") === VC.escapeHtml("a <b> & 'c'"));
    check("VC.rtlRuns: runs join back to the input, spaces/ZWNJ inside a run kept, none for Latin",
      VC.rtlRuns("x حروفِ تہجی, y").map(r => r.t).join("") === "x حروفِ تہجی, y" && VC.rtlRuns("x حروفِ تہجی, y").filter(r => r.rtl).length === 1 &&
      VC.rtlRuns("abc").length === 1 && !VC.rtlRuns("abc")[0].rtl && VC.rtlRuns("").length === 0 && VC.rtlRuns("(bound: لـ)")[1].t === "لـ");
    const rtlOnly = x => VC.rtlRuns(x).filter(r => r.rtl).map(r => r.t);
    const oneRun = (x, run) => { const r = rtlOnly(x); return r.length === 1 && r[0] === run && VC.rtlRuns(x).map(q => q.t).join("") === x; };
    check("VC.rtlRuns: neutrals between RTL letters (..., …, /, spaces) stay inside one run, so a phrase keeps its order",
      oneRun("to hate (از ... متنفرم: I hate)", "از ... متنفرم") && oneRun("of (کا/کی/کے)", "کا/کی/کے") && oneRun("only (لا … إلا)", "لا … إلا") &&
      oneRun("still (ما زال / لا يزال)", "ما زال / لا يزال") && oneRun("either (إما…أو) or", "إما…أو"));
    check("VC.rtlRuns: a Latin letter ends the run, trailing neutrals stay outside",
      JSON.stringify(VC.rtlRuns("near; (میرے پاس: I have)")) === JSON.stringify([{ t: "near; (", rtl: false }, { t: "میرے پاس", rtl: true }, { t: ": I have)", rtl: false }]) &&
      JSON.stringify(rtlOnly("کا and کی")) === JSON.stringify(["کا", "کی"]));
    check("VC.fontStackOf: quote-aware split (a quoted family with a comma is one family)",
      VC.fontStackOf({ fontFamily: '"Foo, Bar", serif, Baz' }) === '"Foo, Bar", Baz' && VC.fontStackOf({ fontFamily: "'A,B'" }) === "'A,B'");
    check("VC.fontStackOf: generic families dropped (Latin falls to the UI stack), null when none named",
      VC.fontStackOf({ fontFamily: '"Noto Nastaliq Urdu", serif' }) === '"Noto Nastaliq Urdu"' && VC.fontStackOf({ fontFamily: "Vazirmatn, \"Noto Naskh Arabic\", sans-serif" }) === 'Vazirmatn, "Noto Naskh Arabic"' &&
      VC.fontStackOf({ fontFamily: "serif" }) === null && VC.scriptDisplay(FA.pack).fontStack === "Vazirmatn");
    const sites = {};
    sites.gloss = api.glossHTML(bk.id);
    sites.glossBox = api.glossBox();
    sites.reveal = api.revealBlock(bk);
    sites.wordRow = api.wordRowHTML(bk, "wl");
    api.drill([api.readItem(bk)], () => {});
    sites.meaningItem = api.html("panel") + optsMarkup(api);
    answer(api, true); sites.meaningReveal = api.html("rv");
    api.drill([api.recallItem(bk)], () => {});
    sites.recallItem = api.html("panel") + optsMarkup(api);
    api.drill([api.typeItem(bk)], () => {});
    sites.typeItem = api.html("panel");
    // A sentence whose translation embeds an RTL phrase with an ellipsis (one run).
    const sent = { t: "این کتاب من است", en: "This is my book (کتاب ... من).", w: [bk.id] };
    sites.sentenceRow = api.sentenceRowHTML(sent, bk);
    sites.sentenceReveal = api.sentenceRevealBlock(sent);
    const unit = FA.script.units.find(u => u.id === "fa-be");
    sites.teachCard = api.scriptTeachHTML(unit);
    VC.answerScriptChoice(api.getProg(), true); api.today();
    sites.today = api.html("panel");
    api.el("go").click();
    sites.scriptTeach = api.html("panel");
    api.goto("sounds"); sites.scriptTab = api.html("panel");
    api.goto("progress"); sites.progress = api.html("panel");
    api.goto("test"); sites.testTab = api.html("panel");
    api.goto("words"); sites.wordsTab = api.html("panel") + (api.html("wbody") || "");
    api.startPlacement(); sites.placement = api.html("panel") + optsMarkup(api);
    check("script notes render on the teach screen with their RTL fragment in the pack font (the fixture note is live)",
      /Short vowels are not written: <bdi data-tl lang="fa" dir="rtl" class="tlf">کتاب<\/bdi> is read ketâb\./.test(sites.scriptTeach));
    check("sentence translation: an RTL phrase with an ellipsis is one isolated run",
      /\(<bdi data-tl lang="fa" dir="rtl" class="tlf">کتاب \.\.\. من<\/bdi>\)/.test(sites.sentenceRow) && /class="tlf">کتاب \.\.\. من</.test(sites.sentenceReveal));
    const TLF = 'class="tlf">الفبا</bdi>';
    check("stage label as a pack fragment in UI lines is tf() (class tlf) at every site: Today plan + path strip, teach heading, Script chart, Progress row",
      sites.today.split(TLF).length - 1 >= 2 && sites.scriptTeach.includes(TLF) && sites.scriptTab.includes(TLF) && sites.progress.includes(TLF));
    check("placement options: meaning glosses with RTL fragments rendered through ui()", /class="tlf">/.test(optsMarkup(api)));
    Object.keys(sites).forEach(k => { const bad = rtlAudit(sites[k]); check(`rtl audit: ${k} has no bidi/font violations (${bad.length})`, bad.length === 0, bad.slice(0, 4).join("; ")); });
    check("gloss popover box is an LTR line (dir=ltr), the word inside it an isolated dir=rtl span", /^<div class="gloss" id="gloss" dir="ltr" hidden>/.test(sites.glossBox) && /<span class="gw" data-tl lang="fa" dir="rtl">/.test(sites.gloss));
    check("Today Learn line: the stage label is a tf() fragment (pack font, capped line-height)", /2\. Learn<\/td><td><bdi data-tl lang="fa" dir="rtl" class="tlf">الفبا<\/bdi>, set/.test(sites.today));
    check("meaning options with an RTL fragment: button stays LTR, fragment isolated", /<button><b class="num">\d<\/b>book \(<bdi data-tl lang="fa" dir="rtl" class="tlf">/.test(optsMarkup(api)) || /book \(<bdi[^>]*class="tlf">/.test(sites.meaningItem));
    // Deliberately broken markup trips the audit (the audit itself is live).
    check("rtl audit catches Latin in a dir=rtl block, RTL outside data-tl, and Latin inside data-tl",
      rtlAudit('<div dir="rtl">79 words</div>').length === 1 && rtlAudit('<button dir="rtl"><span>✓ 3 / 4</span></button>').length === 1 && rtlAudit('<div dir="rtl">3 / 4 <bdi>x</bdi></div>').length === 1 && rtlAudit("<p>learn کتاب</p>").length === 2 && rtlAudit('<div data-tl lang="fa" dir="rtl">ketâb</div>').length === 2);
    // LTR packs: the helpers are the old markup.
    const kb = await boot(FX.ko());
    // pack font stack: generic keywords are dropped for RTL packs only; an LTR pack's
    // --wfont is exactly pack.fontFamily + the base stack, as before.
    const koF = FX.ko(); koF.pack.fontFamily = '"Noto Sans KR", sans-serif';
    const kf = await boot(koF);
    check("LTR pack: --wfont is pack.fontFamily unchanged (generic sans-serif kept) + var(--wbase)", kf.document.documentElement.style["--wfont"] === '"Noto Sans KR", sans-serif, var(--wbase)');
    const faF = FX.fa(); faF.pack.fontFamily = '"Noto Nastaliq Urdu", serif';
    const ff = await boot(faF);
    check("RTL pack: --wfont drops the generic serif", ff.document.documentElement.style["--wfont"] === '"Noto Nastaliq Urdu", var(--wbase)');
    check("app.html: the placeholder font rule is scoped to RTL packs", /:root\[data-tlrtl\] input\[data-tl\]::placeholder\{font-family:var\(--font\)\}/.test(appHtml) && (appHtml.match(/[^\n]*::placeholder[^\n]*/g) || []).every(l => /^\s*:root\[data-tlrtl\] /.test(l)));
    check("LTR pack: ui() is escapeHtml, tf() is tw(), glossBox has no dir", kb.api.ui("x (아이)") === "x (아이)" && kb.api.tf("아이") === '<bdi data-tl lang="ko">아이</bdi>' && !/dir=/.test(kb.api.glossBox()));
  }

  console.log(`\n${fails ? "FAILED" : "ALL PASSED"}: ${passes} passed, ${fails} failed`);
  process.exit(fails ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
