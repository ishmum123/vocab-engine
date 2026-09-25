// App checks for the characters stage in engine/app.html (docs/HSK_MERGE.md §2.5, §2.7,
// §3, rows B4 and B5): path strip, choice card, unit Learn with teach cards, the 4 unit item
// renderers, the Start-today snapshot, unified Review/Recall, sentence ruby by tier; B5:
// Test "Characters N", Progress stage rows and order/mix chips, reset, legacy import, the
// boot migration hook (§4, core.js "legacy migration" contract) and passage ruby; [14]
// pack.pronFirst (brief BP): pinyin wherever a word appears until its unit is mastered.
// Boots app.html's inline script for real against the zh pack WITH its characters.js,
// using the same fake DOM as tests/engine_checks.js check [23] (id registry + regex
// scan of innerHTML; no jsdom, no dependencies).
// Seeds: A = fresh; B = levels 1-3 taught, nothing recorded; C = B + choice answered
// + unit records (characters started).
// Run: node tests/characters_app_checks.js
"use strict";
const fs = require("fs");
const path = require("path");

const ROOT = path.join(__dirname, "..");
const VC = require(path.join(ROOT, "engine", "core.js"));
const ZH = path.join(ROOT, "packs", "zh");
function loadConst(file, name){ return new Function(fs.readFileSync(file, "utf8") + `\nreturn ${name};`)(); }
function tryLoadConst(file, name){ try{ return loadConst(file, name); }catch(e){ return undefined; } }
// The zh pack is pronunciation-first (pack.pronFirst, brief BP). Sections [1]-[13] check
// the word-first characters stage, which every characters pack without pronFirst gets,
// on the same data with pronFirst off; [14] checks the pack as shipped (PACK_ZH).
const PACK_ZH = loadConst(path.join(ZH, "pack.js"), "PACK");
const PACK = Object.assign({}, PACK_ZH, { pronFirst: false });
const WORDS = loadConst(path.join(ZH, "words.js"), "WORDS");
const SENTENCES = loadConst(path.join(ZH, "sentences.js"), "SENTENCES");
const PASSAGES = tryLoadConst(path.join(ZH, "sentences.js"), "PASSAGES") || [];
const LESSONS = loadConst(path.join(ZH, "lessons.js"), "LESSONS");
const CHARACTERS = loadConst(path.join(ZH, "characters.js"), "CHARACTERS");
const LEGACY = loadConst(path.join(ZH, "legacy.js"), "LEGACY");
const BY_ID = Object.fromEntries(WORDS.map(w => [w.id, w]));
const CFG = VC.charsConfig(PACK);
console.log(`Loaded zh pack: ${WORDS.length} words, ${SENTENCES.length} sentences, ${CHARACTERS.length} units, label ${CFG.label}`);

let fails = 0, passes = 0;
function check(name, cond){
  if(cond){ passes++; console.log(`PASS  ${name}`); }
  else { fails++; console.log(`FAIL  ${name}`); }
}

// ------------------------------------------------------------------ fake DOM (engine_checks [23])
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
  };
}
const tick = () => new Promise(r => setTimeout(r, 0));
// Boots the app. opts: chars false = no CHARACTERS const at all; units = the CHARACTERS
// array to pass (default the zh units); pack = the PACK to pass (default zh, with its
// characters block). Test hooks are appended to the script text.
async function boot(opts){
  const o = opts || {};
  const document = makeFakeDom();
  const ss = { getVoices: () => [{ lang:"zh-CN", name:"x" }], onvoiceschanged: null, cancel(){}, speak(){} };
  const window = { VocabCore: VC, speechSynthesis: ss, SpeechSynthesisUtterance: function(){}, addEventListener(){} };
  const localStorage = o.storage || { getItem(){ return null; }, setItem(){} };
  const pack = o.pack || PACK;
  const fnBody = appSrc + `
let __cur = null;
const __mc = renderMcItem;
renderMcItem = function(it){ __cur = it; return __mc(it); };
return {
  html: id => { const e = document.getElementById(id); return e ? e.innerHTML : null; },
  el: id => document.getElementById(id),
  getProg: () => prog, setProg: p => { prog = p; },
  today: () => { tab = "today"; render(); },
  getD: () => D, getCur: () => __cur, getState: () => todayStepState,
  stepFrom: step => { todayStepState.step = step; todayStep(); },
  enterStep: step => { todayStepState = { step }; todayStep(); },
  goto: t => { tab = t; testSel = null; RD = null; render(); },
  legacyNotice: () => legacyNotice, legacyFail: () => legacyFail, readOnly: () => storeReadOnly, getPrep: () => todayPrep,
  rubyTextHTML, sentenceRowHTML, sentenceRevealBlock, readSentence, charDrillItem, passageSentenceHTML, hasChars: () => HAS_CHARACTERS,
  onShowWritten, gapSentence, recallItem, readItem, hearItem, revealBlock, wordRowHTML, glossHTML, passagePlainHTML, charTeach, revealWritten, pronFirst: () => PRON_FIRST,
  panelListeners: () => document.getElementById("panel")._listeners.click || [],
  wordsSearch: q => { tab = "words"; wordsQuery = q; render(); }, startPassage: p => { tab = "read"; startPassage(p); },
};`;
  const names = ["document","window","navigator","location","localStorage","matchMedia","requestAnimationFrame","Audio","confirm","alert","PACK","WORDS","SENTENCES","LESSONS","PASSAGES"];
  const args = [document, window, { userAgent:"CharsAppChecks/1.0" }, undefined, localStorage, () => ({ matches:false }), fn => setTimeout(fn, 0),
    function(){ return { play(){ return Promise.resolve(); }, pause(){} }; }, () => true, () => {}, pack, o.words || WORDS, o.sentences || SENTENCES, o.lessons || LESSONS, o.passages || PASSAGES];
  if(o.chars !== false){ names.push("CHARACTERS"); args.push(o.units || CHARACTERS); }
  if(o.legacy){ names.push("LEGACY"); args.push(o.legacy === true ? LEGACY : o.legacy); }
  const api = new Function(...names, fnBody)(...args);
  await tick(); await tick();
  return { api, document };
}

// ------------------------------------------------------------------ seeds
const byLv = VC.wordsByLevel(WORDS, PACK);
const NS = lv => VC.nSets(byLv[lv], VC.setSizeOf(PACK));
function seedB(){ return VC.normalizeProg({ sets: { "1": NS("1"), "2": NS("2"), "3": NS("3"), "4": 0 }, placedOnce: true, sessions: 30 }, PACK); }
// Seed C: B + choice answered, the first 40 stage-1 units recorded: 10 weak (w=3, s=0,
// outranking the unrecorded learned words) and 30 mastered (s=3, ranked below them), so
// the unified Review mixes units and words.
function seedC(){
  const p = seedB(); VC.answerCharChoice(p, true);
  VC.charStageUnits(["1","2","3"], CHARACTERS, PACK).slice(0, 40).forEach((u, i) => { p.chars.c[u.id] = i < 10 ? { r:3, w:3, s:0 } : { r:3, w:0, s:3 }; });
  return p;
}
const count = (s, re) => (s.match(re) || []).length;
// Plays the active drill to the end answering right (the current item's `a`), then
// presses Continue. Returns every item shown (by key), or throws on a stuck drill.
function playDrill(api, maxItems){
  const shown = [];
  for(let i = 0; i < (maxItems || 200); i++){
    const D = api.getD();
    if(!D){ const ok = api.el("ok"); if(ok) ok.click(); return shown; }
    const it = api.getCur();
    shown.push(it);
    const btn = api.el("o").children.find(b => b.dataset.v === it.a);
    if(!btn) throw new Error(`no option matches the answer for ${it.key}`);
    btn.click(); api.el("nx").click();
  }
  throw new Error("drill did not finish");
}
const stripTags = h => h.replace(/<rt[^>]*>[\s\S]*?<\/rt>/g, "").replace(/<[^>]+>/g, "").replace(/&lt;/g,"<").replace(/&gt;/g,">").replace(/&quot;/g,'"').replace(/&#39;/g,"'").replace(/&amp;/g,"&");

(async function main(){
  // ---------------------------------------------------------------- [1] strip
  console.log("\n[1] path strip uses stagePath");
  {
    const { api } = await boot();
    check("HAS_CHARACTERS is on for zh + characters.js", api.hasChars());
    const h = api.html("panel");
    const segs = [...h.matchAll(/<div class="seg">[\s\S]*?<\/i><\/div>([\s\S]*?)<\/div>/g)].map(m => stripTags(m[1]));
    check(`strip is the stage path HSK 1, HSK 2, HSK 3, ${CFG.label}, HSK 4, ${CFG.label}4 (got ${segs.join(" | ")})`,
      segs.join("|") === ["HSK 1","HSK 2","HSK 3",CFG.label,"HSK 4",CFG.label+"4"].join("|"));
    check("character stage labels carry the target-language markup", /<bdi data-tl lang="[^"]+">字<\/bdi>/.test(h));
    check("fresh learner: no choice card, Start today shown", !/id="charChoice"/.test(h) && /id="go"/.test(h));
  }

  // ---------------------------------------------------------------- [2] choice card
  console.log("\n[2] seed B: the one-time choice card");
  {
    const { api } = await boot();
    api.setProg(seedB()); api.today();
    let h = api.html("panel");
    check("seed B (levels 1-3 taught) shows the choice card", /id="charChoice"/.test(h));
    check("the choice card replaces Start today", !/id="go"/.test(h));
    check("choice card offers the stage and the next word level", /Start <bdi[^>]*>字<\/bdi>/.test(h) && /Skip to HSK 4/.test(h));
    check("Learn line names the character set", /2\. Learn<\/td><td>字, set 1 of \d+/.test(h));
    api.el("choiceStart").click();
    h = api.html("panel");
    check("characters next: choiceSeen set, not deferred", api.getProg().chars.choiceSeen === true && api.getProg().chars.defer === false);
    check("after answering: card gone, Start today back", !/id="charChoice"/.test(h) && /id="go"/.test(h));
    check("before any unit record: Review line is 20 items, words only (no unit in the plan yet)", /1\. Review<\/td><td>20 items, weakest first, words<\/td>/.test(h) && !api.getPrep().review.some(x => x.unit));

    // Start today: snapshot taken, Review (word-only: no records yet) is 20 items.
    api.el("go").click();
    const st = api.getState();
    check("Start today stores the snapshot (stage = the character stage, reviewSize 20)",
      st.snap && st.snap.stage.kind === "chars" && st.snap.reviewSize === 20 && st.snap.cset.index === 0);
    const D = api.getD();
    check("Review with no unit records: 20 word items", D && D.q.length + 1 === 20 && [api.getCur(), ...D.q].every(x => x.key.startsWith("w:")));

    // Learn: teach cards for the snapshot's set, then 2 learnKinds items per unit.
    api.stepFrom(1);
    h = api.html("panel");
    const cs = st.snap.cset;
    check("Learn teaches a unit set with 10 teach cards", count(h, /class="charteach"/g) === 10 && cs.units.length === 10);
    check("teach card: written form, reading and gloss of every unit",
      cs.units.every(u => h.includes(`>${u.t}</span>`) && h.includes(VC.unitReading(u, BY_ID)) && h.includes(VC.escapeHtml(VC.unitGloss(u, BY_ID)))));
    const withEx = cs.units.filter(u => VC.exampleSentences(BY_ID[u.words[0]], SENTENCES, PACK, 1).length).length;
    check(`teach cards carry the linked word's example sentence (${withEx} of 10 have one)`, count(h, /class="sent"/g) === withEx && withEx > 0);
    check("teach heading uses the stage label and set position", /<bdi[^>]*>字<\/bdi>, set 1 of \d+: the written form/.test(h));
    api.el("dr").click();
    const first = api.getD();
    const items = [api.getCur(), ...first.q];
    check("Learn drill: 20 items, charPick + charRead per unit", items.length === 20 &&
      cs.units.every(u => items.filter(x => x.key === "c:" + u.id).length === 2));
    let err = null, shown = [];
    try{ shown = playDrill(api); }catch(e){ err = e; }
    check(`Learn drill plays through without error${err ? ` (${err.message})` : ""}`, !err && shown.length === 20);
    const recs = api.getProg().chars.c;
    check("every taught unit is recorded in prog.chars.c (s=2), prog.w untouched by unit items",
      cs.units.every(u => recs[u.id] && recs[u.id].s === 2) && Object.keys(recs).length === 10);
    check("the drill's Continue moved on to the Listen step", api.getState().step === 3 && api.getD() && api.getCur().key.startsWith("w:"));
    check("next unit set is now set 2", VC.nextCharSet(["1","2","3"], CHARACTERS, PACK, api.getProg()).index === 1);
    check("the Start-today snapshot persists across steps (same object, still set 1, stage unchanged, reviewSize 20)",
      api.getState().snap === st.snap && st.snap.cset.index === 0 && st.snap.stage.kind === "chars" && st.snap.reviewSize === 20);
    api.stepFrom(4);
    check("... and still after Recall/Sentences steps", api.getState().snap === st.snap && st.snap.cset.index === 0);
  }
  {
    const { api } = await boot();
    api.setProg(seedB()); api.today();
    api.el("choiceSkip").click();
    const h = api.html("panel");
    const segs = [...h.matchAll(/<div class="seg">[\s\S]*?<\/i><\/div>([\s\S]*?)<\/div>/g)].map(m => stripTags(m[1]));
    check("skip: deferred, card gone, Learn is HSK 4 set 1", api.getProg().chars.defer === true && !/id="charChoice"/.test(h) && /2\. Learn<\/td><td>HSK 4, set 1</.test(h));
    check(`skip: strip puts one merged stage last (got ${segs.join(" | ")})`, segs.join("|") === ["HSK 1","HSK 2","HSK 3","HSK 4",CFG.label].join("|"));
  }

  // ---------------------------------------------------------------- [3] item renderers
  console.log("\n[3] the four unit item renderers");
  {
    const { api } = await boot();
    api.setProg(seedC());
    const u = CHARACTERS.find(x => x.lv === "1" && VC.unitReading(x, BY_ID) && !api.getProg().chars.c[x.id]);
    const reading = VC.unitReading(u, BY_ID), g = VC.unitGloss(u, BY_ID);
    const mk = k => api.charDrillItem(k, u);
    const rd = mk("charRead"), sd = mk("charSound"), pk = mk("charPick"), rc = mk("charRecall");
    check("charRead: form only (no reading, no speaker), 4 meaning options, answer = gloss",
      rd.html.includes(u.t) && !rd.html.includes(reading) && !/speaker/.test(rd.html) && rd.opts.length === 4 && rd.a === g && !rd.mount);
    check("charSound: form only, 4 reading options, answer = reading", sd.html.includes(u.t) && !sd.html.includes(reading) && sd.opts.length === 4 && sd.a === reading);
    check("charPick: reading + speaker (audio), 4 written-form options, answer = form",
      pk.html.includes(reading) && /id="sp"/.test(pk.html) && pk.opts.length === 4 && pk.a === u.t && typeof pk.mount === "function");
    check("charRecall: meaning shown, 4 written-form options, answer = form", rc.html.includes(VC.escapeHtml(g)) && rc.opts.length === 4 && rc.a === u.t && !rc.html.includes(reading));
    check("all four: key c:<unit>, reveal has form + reading + gloss", [rd, sd, pk, rc].every(x => x.key === "c:" + u.id && x.reveal.includes(u.t) && x.reveal.includes(reading)));
    const before = JSON.stringify(api.getProg().w);
    rd.onAnswer(true); sd.onAnswer(false);
    const r = api.getProg().chars.c[u.id];
    check("answer marking writes prog.chars.c only", r && r.r === 1 && r.w === 1 && r.s === 0 && JSON.stringify(api.getProg().w) === before);
  }

  // ---------------------------------------------------------------- [4] unified Review / Recall
  console.log("\n[4] seed C: unified Review (20) and Recall with unit items");
  {
    const { api } = await boot();
    api.setProg(seedC()); api.today();
    const h = api.html("panel");
    check("seed C: no choice card, Review line 20 items with units", !/id="charChoice"/.test(h) && /20 items, weakest first, words and 字/.test(h));
    const prep = api.getPrep().review;
    api.el("go").click();
    const D = api.getD();
    const items = [api.getCur(), ...D.q];
    const keyOf = x => x.unit ? "c:" + x.unit.id : "w:" + x.word.id;
    check("Start today runs exactly the Review plan the line was computed from", items.map(x => x.key).sort().join() === prep.map(keyOf).sort().join() && api.getState().review === null);
    const nUnit = items.filter(x => x.key.startsWith("c:")).length;
    check(`Review builds 20 items containing unit items (${nUnit} unit, ${20 - nUnit} word)`, items.length === 20 && nUnit > 0 && nUnit < 20);
    check("Review unit items use the pack reviewKinds (form stimulus)", items.filter(x => x.key.startsWith("c:")).every(x => /class="big wd"/.test(x.html)));
    let err = null, shown = [];
    try{ shown = playDrill(api); }catch(e){ err = e; }
    check(`Review renders and plays every item without error${err ? ` (${err.message})` : ""}`, !err && shown.length === 20);

    // Recall (step 3) from the same snapshot.
    api.stepFrom(3);
    const R = api.getD();
    const ritems = [api.getCur(), ...R.q];
    check(`Recall: 8 items, unit items are charRecall (${ritems.filter(x => x.key.startsWith("c:")).length} unit)`,
      ritems.length === 8 && ritems.filter(x => x.key.startsWith("c:")).every(x => x.label === "How is it written?" && !/class="big/.test(x.html)));
    err = null;
    try{ shown = playDrill(api); }catch(e){ err = e; }
    check(`Recall plays through without error${err ? ` (${err.message})` : ""}`, !err && shown.length === 8);
  }
  {
    // Characters started and units recorded, but every recorded unit is bare (well below
    // the learned words in the ranking): the plan holds no unit, so the line says "words".
    const { api } = await boot();
    const q = seedB(); VC.answerCharChoice(q, true);
    VC.charStageUnits(["1","2","3"], CHARACTERS, PACK).slice(0, 40).forEach(u => { q.chars.c[u.id] = { r:9, w:0, s:9 }; });
    api.setProg(q); api.today();
    const h = api.html("panel"), prep = api.getPrep().review;
    check("units recorded but crowded out of the plan: Review line says words only", VC.recordedUnits(CHARACTERS, q, PACK).length === 40 && !prep.some(x => x.unit) && /1\. Review<\/td><td>20 items, weakest first, words<\/td>/.test(h));
  }
  {
    // Snapshot keeps Review word-only when it was taken before characters started.
    const { api } = await boot();
    const p = VC.normalizeProg({ sets: { "1": 2 }, placedOnce: true }, PACK);
    api.setProg(p); api.today();
    check("before characters: Review line is 15 items", /1\. Review<\/td><td>15 items, weakest first</.test(api.html("panel")));
    api.el("go").click();
    check("before characters: snapshot reviewSize 15, Review 15 word items",
      api.getState().snap.reviewSize === 15 && [api.getCur(), ...api.getD().q].length === 15 && [api.getCur(), ...api.getD().q].every(x => x.key.startsWith("w:")));
  }

  // ---------------------------------------------------------------- [5] sentence ruby
  console.log("\n[5] sentence ruby by tier");
  {
    const off = await boot({ chars: false });
    const { api } = await boot();
    const ubw = VC.unitByWord(CHARACTERS);
    const s = SENTENCES.find(x => Array.isArray(x.ruby) && x.ruby.filter(r => ubw.get(r[3])).length >= 2);
    const [ta, tb] = s.ruby.filter(r => ubw.get(r[3]));
    const p = seedC(); p.chars.c[ubw.get(ta[3]).id] = { r:1, w:0, s:1 }; p.chars.c[ubw.get(tb[3]).id] = { r:6, w:0, s:6 };
    api.setProg(p);
    const row = api.sentenceRowHTML(s);
    check(`ruby below bare: ${s.t.slice(ta[0], ta[1])} gets <ruby> with its reading`, row.includes(`<ruby>${s.t.slice(ta[0], ta[1])}<rt>${ta[2]}</rt></ruby>`));
    check(`bare at/above bare: ${s.t.slice(tb[0], tb[1])} keeps its <rt>, hidden (class "bare")`, !row.includes(`<ruby>${s.t.slice(tb[0], tb[1])}<rt>`) && row.includes(`<ruby class="bare">${s.t.slice(tb[0], tb[1])}<rt>${tb[2]}</rt></ruby>`));
    check("CSS: a bare token's <rt> is visibility:hidden (keeps its width)", /\.hasruby ruby\.bare rt\{visibility:hidden\}/.test(appHtml));
    check("ruby replaces the pron line (no .sp), line box class set", !/class="sp"/.test(row) && /class="st hasruby"/.test(row));
    check("reveal block and read item also render ruby", /<ruby>/.test(api.sentenceRevealBlock(s)) && /<ruby>/.test(api.readSentence(s).html));
    // Every sentence renders back to its own text (ruby readings aside), with and without a highlighted word.
    let bad = 0;
    SENTENCES.forEach(x => {
      const e = BY_ID[(x.words || [])[0]];
      const r1 = api.sentenceRowHTML(x), r2 = api.sentenceRowHTML(x, e);
      const t1 = stripTags((r1.match(/<div class="st[^"]*"[^>]*>([\s\S]*?)<\/div>/) || [])[1] || "");
      const t2 = stripTags((r2.match(/<div class="st[^"]*"[^>]*>([\s\S]*?)<\/div>/) || [])[1] || "");
      if(t1 !== x.t || t2 !== x.t) bad++;
    });
    check(`all ${SENTENCES.length} sentences render to their own text under ruby, with and without highlight (${bad} bad)`, bad === 0);
    // B8 (390px rewrap): a token's width must not change across tiers. Width proxy: the
    // number of <ruby> elements, the <rt> contents and the base text; the markup may differ
    // only by class="bare". All units below bare, all bare, and a mix (by unit parity).
    {
      const allUnits = f => { const q = seedC(); CHARACTERS.forEach((u, i) => { q.chars.c[u.id] = f(i); }); return q; };
      const below = allUnits(() => ({ r:1, w:0, s:1 })), bare = allUnits(() => ({ r:6, w:0, s:6 })), mixed = allUnits(i => i % 2 ? { r:6, w:0, s:6 } : { r:1, w:0, s:1 });
      const proxy = h => `${count(h, /<ruby[ >]/g)}#${[...h.matchAll(/<rt>([\s\S]*?)<\/rt>/g)].map(m => m[1]).join("|")}#${stripTags(h)}`;
      const norm = h => h.replace(/<ruby class="bare">/g, "<ruby>");
      let nRuby = 0, varied = 0, bareSeen = 0;
      SENTENCES.forEach(x => {
        if(!Array.isArray(x.ruby) || !x.ruby.length) return;
        nRuby++;
        const e = BY_ID[(x.words || [])[0]];
        const out = [below, bare, mixed].flatMap(q => { api.setProg(q); return [api.sentenceRowHTML(x), api.sentenceRowHTML(x, e)]; });
        if(/<ruby class="bare">/.test(out[2])) bareSeen++;
        if(!(proxy(out[0]) === proxy(out[2]) && proxy(out[0]) === proxy(out[4]) && proxy(out[1]) === proxy(out[3]) && proxy(out[1]) === proxy(out[5])
          && norm(out[0]) === norm(out[2]) && norm(out[0]) === norm(out[4]) && norm(out[1]) === norm(out[3]) && norm(out[1]) === norm(out[5]))) varied++;
      });
      check(`all ${SENTENCES.length} zh sentences (${nRuby} with ruby): ruby count, <rt> contents and text are tier-invariant, markup differs only by class="bare" (${varied} varied)`,
        nRuby > 0 && varied === 0 && bareSeen === nRuby);
      api.setProg(p);
    }
    const offRow = off.api.sentenceRowHTML(s);
    p.showPron = false; const noPron = api.sentenceRowHTML(s); p.showPron = true;
    off.api.getProg().showPron = false; const offNoPron = off.api.sentenceRowHTML(s);
    check("showPron off hides all ruby (same markup as without characters)", !/<ruby>/.test(noPron) && noPron === offNoPron);
    p.chars.mix = false;
    check("mix off: sentence renders exactly as without characters", api.sentenceRowHTML(s) === offRow);
    p.chars.mix = true;
    api.setProg(VC.normalizeProg({ sets: { "1": 2 } }, PACK));
    check("characters not started: sentence renders exactly as without characters", api.sentenceRowHTML(s) === offRow);
    check("word-first gap items are unchanged (ruby in the gap stimulus only on the pack.pronFirst branch)",
      !/hasruby/.test(appHtml.match(/function gapSentence[\s\S]*?\n}\n/)[0].replace(/pf\.ruby \? " hasruby" : ""/g, "")));
  }

  // ---------------------------------------------------------------- [6] flag-off
  console.log("\n[6] flag-off: no characters -> Today identical");
  {
    const stripped = Object.assign({}, PACK); delete stripped.characters;
    for(const prog of [VC.normalizeProg({}, stripped), seedB()]){
      const a = await boot({ chars: false, pack: stripped });
      const b = await boot({ chars: true, pack: stripped });          // characters.js but no pack block
      const c = await boot({ chars: true, pack: PACK, units: [] });   // pack block but no units
      const pr = () => JSON.parse(JSON.stringify(prog));
      [a, b, c].forEach(x => { x.api.setProg(pr()); x.api.today(); });
      const ha = a.api.html("panel");
      check(`Today identical without characters (block-only / units-only / neither), sets ${JSON.stringify(prog.sets)}`,
        !a.api.hasChars() && !b.api.hasChars() && !c.api.hasChars() && b.api.html("panel") === ha && c.api.html("panel") === ha && !/charChoice|<ruby>/.test(ha));
    }
  }


  // ================================================================ B5
  // Legacy seeds C and D1, built exactly as tests/migration_checks.js builds them.
  const hanziOf = {}; Object.keys(LEGACY.w).forEach(h => { hanziOf[LEGACY.w[h]] = h; });
  const hByLv = { 1:[], 2:[], 3:[], 4:[] }; WORDS.forEach(w => hByLv[w.lv].push(hanziOf[w.id]));
  const hNsets = lv => Math.ceil(hByLv[lv].length / 10);
  const SENTS = Object.keys(LEGACY.s);
  const rec = (r, w, s, extra) => Object.assign({ r, w, s }, extra || {});
  const hWords = (lv, n, f) => { const o = {}; hByLv[lv].slice(0, n).forEach((h, i) => { o[h] = f(i); }); return o; };
  const clone = x => JSON.parse(JSON.stringify(x));
  const HSK_FRESH = { v:2, w:{}, sets:{1:0,2:0,3:0,4:0}, lessons:{}, sessions:0, theme:null, showChars:false, s:{}, c:{}, mixChars:true, charsAfterHsk4:false, charsChoiceSeen:false };
  const midW = Object.assign(hWords(1, hByLv[1].length, i => rec(3 + i % 4, i % 3, i % 5)), hWords(2, 30, i => rec(1 + i % 3, i % 2, i % 4, i % 7 === 0 ? { prov:1 } : null)));
  const charsSome = {}; [1,2,3].flatMap(lv => hByLv[lv]).slice(0, 25).forEach((h, i) => { charsSome[h] = rec(1 + i % 3, i % 2, i % 4); });
  const LSEED_C = Object.assign(clone(HSK_FRESH), { w: midW, sets:{1:hNsets(1),2:3,3:0,4:0}, sessions: 14, theme:"dark", placedOnce:true,
    lessons:{ tones:1, "finals-simple":1 }, s: Object.fromEntries(SENTS.slice(0, 12).map((z, i) => [z, rec(2, i % 2, i % 3)])) });
  const LSEED_D1 = Object.assign(clone(HSK_FRESH), { w: clone(midW), sets:{1:hNsets(1),2:hNsets(2),3:hNsets(3),4:0}, sessions: 40, c: charsSome, charsChoiceSeen:true });
  const LKEY = PACK.legacy.key, BAK = VC.legacyBackupKey(PACK), SKEY = VC.storageKey(PACK);
  function memStorage(init, opt){
    const o = opt || {}; const map = new Map(Object.entries(init || {})); const writes = [];
    return { map, writes,
      getItem(k){ if(o.throwGet && o.throwGet(k)) throw new Error("SecurityError"); return map.has(k) ? map.get(k) : null; },
      setItem(k, v){ if(o.throwSet) throw new Error("QuotaExceededError"); writes.push(k); map.set(k, String(v)); } };
  }
  // Plays the active drill answering right; returns {shown, result} where result is the
  // result-screen HTML captured before Continue is pressed.
  function playToResult(api){
    const shown = [];
    for(let i = 0; i < 200; i++){
      if(!api.getD()) return { shown, result: api.html("panel") };
      const it = api.getCur(); shown.push(it);
      api.el("o").children.find(b => b.dataset.v === it.a).click(); api.el("nx").click();
    }
    throw new Error("drill did not finish");
  }
  const segsOf = h => [...h.matchAll(/<div class="seg">[\s\S]*?<\/i><\/div>([\s\S]*?)<\/div>/g)].map(m => stripTags(m[1]));

  // ---------------------------------------------------------------- [7] Test: Characters N
  console.log("\n[7] Test tab: Characters N");
  {
    const { api } = await boot();
    const deferred = seedB(); VC.answerCharChoice(deferred, false);
    api.setProg(deferred); api.goto("test");
    check("unlocked but deferred (not started): no Characters test", VC.charsUnlocked(PACK, WORDS, deferred) && !VC.charsStarted(PACK, WORDS, CHARACTERS, deferred) && !/id="tChars"/.test(api.html("panel")));
    api.setProg(seedB()); api.goto("test");
    check("started, no unit recorded yet: Characters 20 (hsk parity: shown once started)", /id="tChars">Characters 20</.test(api.html("panel")));
    api.el("tChars").click();
    let items = [api.getCur(), ...api.getD().q];
    const lw0 = VC.learnedWords(WORDS, PACK, seedB());
    const fresh = VC.newCharUnits(CHARACTERS, lw0, seedB(), PACK, 20);
    check("no records: the pool is the first 20 learned words' units, level then file order (VC.newCharUnits)",
      items.length === 20 && fresh.length === 20 && fresh.every(u => items.some(x => x.key === "c:" + u.id)));
    api.goto("test");
    const p5 = seedB(); VC.answerCharChoice(p5, true);
    const rec5 = VC.charStageUnits(["1","2","3"], CHARACTERS, PACK).slice(100, 105);
    rec5.forEach(u => { p5.chars.c[u.id] = { r:1, w:0, s:1 }; });
    api.setProg(p5); api.goto("test");
    check("5 recorded units: Characters 20 (topped up with learned words' unrecorded units)", /id="tChars">Characters 20</.test(api.html("panel")));
    api.el("tChars").click();
    items = [api.getCur(), ...api.getD().q];
    const top = VC.newCharUnits(CHARACTERS, VC.learnedWords(WORDS, PACK, p5), p5, PACK, 15);
    check("5 recorded: all 5 first, then the 15 first unrecorded units",
      items.length === 20 && rec5.every(u => items.some(x => x.key === "c:" + u.id)) && top.every(u => items.some(x => x.key === "c:" + u.id)) && top.every(u => !p5.chars.c[u.id]));
    api.goto("test");
    api.setProg(seedC()); api.goto("test");
    check("40 recorded units: Characters 20 (capped like the other free tests)", /id="tChars">Characters 20</.test(api.html("panel")));
    api.el("tChars").click();
    items = [api.getCur(), ...api.getD().q];
    const recs = api.getProg().chars.c;
    check("Characters test: 20 unit items, all recorded units", items.length === 20 && items.every(x => x.key.startsWith("c:") && recs[x.key.slice(2)]));
    check("Characters test kinds come from testKinds (charRead, charSound, charPick; never charRecall)",
      items.every(x => x.label === "What does it mean?" || x.label === "How is it said?" || (x.label === "How is it written?" && /hear-stage|class="med"/.test(x.html) && !x.html.includes(VC.escapeHtml(VC.unitGloss(CHARACTERS.find(u => "c:" + u.id === x.key), BY_ID))))));
    check("Characters test draws the weakest first (all 10 weak units included)",
      VC.charStageUnits(["1","2","3"], CHARACTERS, PACK).slice(0, 10).every(u => items.some(x => x.key === "c:" + u.id)));
    let err = null, r = null;
    try{ r = playToResult(api); }catch(e){ err = e; }
    check(`Characters test plays to the shared result screen (20 / 20, Continue)${err ? ` (${err.message})` : ""}`,
      !err && r.shown.length === 20 && /<div class="done"><h2>20 \/ 20<\/h2>/.test(r.result) && /id="ok"/.test(r.result));
    api.el("ok").click();
    check("Continue returns to the Test tab", /id="tChars"/.test(api.html("panel")));
  }

  // ---------------------------------------------------------------- [8] Progress
  console.log("\n[8] Progress: stage rows, order chips, mix chip, choice card line");
  {
    const { api } = await boot();
    api.goto("progress");
    let h = api.html("panel");
    check("fresh learner: stage rows shown, no order/mix controls", /<td><bdi[^>]*>字<\/bdi><\/td><td>0 \/ \d+ taught · 0 recorded · 0 mastered · 0 bare<\/td>/.test(h) && !/id="charCtl"/.test(h));
    api.setProg(seedC()); api.goto("progress");
    h = api.html("panel");
    const n1 = VC.charStageUnits(["1","2","3"], CHARACTERS, PACK).length, n4 = VC.charStageUnits(["4"], CHARACTERS, PACK).length;
    check(`seed C rows: 字 40 / ${n1} taught · 40 recorded · 30 mastered · 0 bare; 字4 0 / ${n4}`,
      h.includes(`>字</bdi></td><td>40 / ${n1} taught · 40 recorded · 30 mastered · 0 bare</td>`) && h.includes(`>字4</bdi></td><td>0 / ${n4} taught · 0 recorded · 0 mastered · 0 bare</td>`));
    const p = seedC(); const us = VC.charStageUnits(["1","2","3"], CHARACTERS, PACK);
    p.chars.c[us[0].id] = { r:6, w:0, s:6 }; delete p.chars.c[us[39].id]; p.chars.c[us[45].id] = { r:1, w:0, s:1 };
    api.setProg(p); api.goto("progress");
    check("taught counts whole sets only, recorded every record, bare by streak",
      api.html("panel").includes(`>字</bdi></td><td>30 / ${n1} taught · 40 recorded · 30 mastered · 1 bare</td>`));
    api.setProg(seedB()); api.goto("progress");
    h = api.html("panel");
    check("levels 1-3 taught: order chips 'Characters before/after HSK 4' + mix chip + strip", /id="ordBefore"[^>]*>Characters before HSK 4</.test(h) && /id="ordAfter"[^>]*>Characters after HSK 4</.test(h) && /id="toggleMix"/.test(h) && /id="charCtl"/.test(h));
    check("default order: 'before' on, strip has 字 before HSK 4", /class="chip on" id="ordBefore"/.test(h) && segsOf(h).join("|") === "HSK 1|HSK 2|HSK 3|字|HSK 4|字4");
    const before = JSON.stringify({ w: api.getProg().w, sets: api.getProg().sets, c: api.getProg().chars.c, cs: api.getProg().chars.choiceSeen });
    api.el("ordAfter").click();
    h = api.html("panel");
    check("order chip 'after': defer on, strip re-rendered with one merged stage last", api.getProg().chars.defer === true && /class="chip on" id="ordAfter"/.test(h) && segsOf(h).join("|") === "HSK 1|HSK 2|HSK 3|HSK 4|字");
    check("deferred with no unit record (unlocked, not started): order chips but no mix chip", !VC.charsStarted(PACK, WORDS, CHARACTERS, api.getProg()) && /id="ordBefore"/.test(h) && !/id="toggleMix"/.test(h));
    api.goto("today");
    check("deferred: Today's Learn is HSK 4 set 1", /2\. Learn<\/td><td>HSK 4, set 1</.test(api.html("panel")));
    api.goto("progress"); api.el("ordBefore").click();
    h = api.html("panel");
    check("order chip 'before': reversible, strip back", api.getProg().chars.defer === false && segsOf(h).join("|") === "HSK 1|HSK 2|HSK 3|字|HSK 4|字4");
    check("order flips touch no record, set counter or choice state", JSON.stringify({ w: api.getProg().w, sets: api.getProg().sets, c: api.getProg().chars.c, cs: api.getProg().chars.choiceSeen }) === before);
    // mix chip toggles ruby in a sentence row
    api.setProg(seedC());
    const ubw = VC.unitByWord(CHARACTERS);
    const s = SENTENCES.find(x => Array.isArray(x.ruby) && x.ruby.some(r => ubw.get(r[3])));
    check("mix on (default): sentence row has ruby", /<ruby>/.test(api.sentenceRowHTML(s)));
    api.goto("progress"); api.el("toggleMix").click();
    check("mix chip off: prog.chars.mix false, chip off, sentence row has no ruby", api.getProg().chars.mix === false && /class="chip " id="toggleMix" aria-pressed="false"/.test(api.html("panel")) && !/<ruby>/.test(api.sentenceRowHTML(s)));
    api.el("toggleMix").click();
    check("mix chip on again: ruby back", api.getProg().chars.mix === true && /<ruby>/.test(api.sentenceRowHTML(s)));
    api.setProg(seedB()); api.goto("today");
    check("choice card says 'You can change this later in Progress.'", /id="charChoice"[\s\S]*You can change this later in Progress\./.test(api.html("panel")));
  }

  // ---------------------------------------------------------------- [9] reset
  console.log("\n[9] reset clears chars, never touches the legacy keys");
  {
    const st = memStorage({ [BAK]: "OLD", [LKEY]: "{}" });
    const { api } = await boot({ storage: st, legacy: true });
    st.writes.length = 0;
    const p = seedC(); p.chars.mix = false; p.chars.defer = true; api.setProg(p);
    api.goto("progress"); api.el("reset").click(); await tick();
    const ch = api.getProg().chars;
    check("reset: prog.chars back to defaults (no records, order/choice/mix reset)", JSON.stringify(ch) === JSON.stringify(VC.defaultCharsProg()));
    check("reset backup holds the old chars", Object.keys(JSON.parse(st.map.get(SKEY + "_reset_backup")).chars.c).length === 40);
    check(`reset writes only ${SKEY} and its _reset_backup (legacy key and ${BAK} untouched)`, st.writes.every(k => k === SKEY || k === SKEY + "_reset_backup") && st.map.get(BAK) === "OLD" && st.map.get(LKEY) === "{}");
  }

  // ---------------------------------------------------------------- [10] legacy import
  console.log("\n[10] Progress import of legacy exports (seeds C and D1)");
  for(const [name, seed] of [["C", LSEED_C], ["D1", LSEED_D1]]){
    const st = memStorage({});
    const { api } = await boot({ storage: st, legacy: true });
    const exp = VC.migrateLegacy(PACK, LEGACY, clone(seed));
    // The learner's own showPron (pack default: on) survives the import (hsk has none).
    const SHOWPRON_BEFORE = name === "C" ? false : true;
    api.getProg().showPron = SHOWPRON_BEFORE;
    api.goto("progress");
    const prev = JSON.stringify(api.getProg());
    api.el("imptxt").value = JSON.stringify(seed);
    api.el("doimport").click(); await tick();
    const sum = api.el("impSum");
    const sh = sum.innerHTML;
    check(`seed ${name}: summary shown before applying, progress not yet replaced`, sum.style.display === "block" && JSON.stringify(api.getProg()) === prev && /id="impApply"/.test(sh));
    check(`seed ${name}: summary counts words, sentences, units, sets, sessions`,
      sh.includes(`${Object.keys(exp.prog.w).length} word records`) && sh.includes(`${Object.keys(exp.prog.s).length} sentence records`) &&
      sh.includes(`${Object.keys(exp.prog.chars.c).length} <bdi`) && sh.includes(`${seed.sessions} sessions`) && !/id="legacyUnmapped"/.test(sh));
    check(`seed ${name}: retired settings listed`, /left out: showChars/.test(sh));
    api.el("impApply").click(); await tick();
    const p = api.getProg();
    check(`seed ${name}: legacy import keeps the current showPron (${p.showPron})`, p.showPron === SHOWPRON_BEFORE);
    check(`seed ${name}: applied: records keyed by id, chars/flags mapped, theme kept`,
      JSON.stringify(p.w) === JSON.stringify(exp.prog.w) && JSON.stringify(p.chars.c) === JSON.stringify(exp.prog.chars.c) && JSON.stringify(p.sets) === JSON.stringify(exp.prog.sets)
      && p.chars.choiceSeen === seed.charsChoiceSeen && p.theme === seed.theme);
    check(`seed ${name}: pre-import backup written, saved as ${SKEY}, legacy keys untouched`,
      st.map.has(SKEY + "_pre_import_backup") && JSON.parse(st.map.get(SKEY)).sessions === seed.sessions && !st.writes.includes(LKEY) && !st.writes.includes(BAK));
  }
  {
    const { api } = await boot({ legacy: true });
    api.goto("progress");
    const bad = Object.assign(clone(LSEED_D1), { foo: 1 }); bad.w["不存在的词"] = rec(1, 0, 1);
    api.el("imptxt").value = JSON.stringify(bad);
    api.el("doimport").click(); await tick();
    const sh = api.el("impSum").innerHTML;
    check("unmapped parts are listed in the import summary", /id="legacyUnmapped"/.test(sh) && sh.includes("<bdi>foo</bdi>: unknown field") && sh.includes("不存在的词") && /2 parts of the old record have no place here/.test(sh));
    api.el("impCancel").click();
    check("Cancel hides the summary and applies nothing", api.el("impSum").style.display === "none" && Object.keys(api.getProg().w).length === 0);
    // native export: straight through applyImport, no summary
    api.el("imptxt").value = JSON.stringify(seedC());
    api.el("doimport").click(); await tick();
    check("native export imports directly (no legacy summary), chars kept", Object.keys(api.getProg().chars.c).length === 40 && !/id="impApply"/.test(api.html("panel")));
    api.goto("progress");
    api.el("imptxt").value = JSON.stringify({ v:3, sets:{} });
    api.el("doimport").click(); await tick();
    check("an invalid record still gets the normal import error", api.el("impErr").style.display === "block");
  }

  // ---------------------------------------------------------------- [11] boot migration hook
  console.log("\n[11] boot migration hook");
  {
    const oldRec = Object.assign(clone(LSEED_D1), { foo: 1 });
    const raw = JSON.stringify(oldRec);
    const st = memStorage({ [LKEY]: raw });
    const exp = VC.migrateLegacy(PACK, LEGACY, raw);
    const { api } = await boot({ storage: st, legacy: true });
    const p = api.getProg();
    check("legacy key present, own key absent: migrated at boot", JSON.stringify(p.w) === JSON.stringify(exp.prog.w) && Object.keys(p.chars.c).length === 25 && p.legacy && p.legacy.key === LKEY);
    check(`saved as ${SKEY}; raw copied once to ${BAK}; legacy key never written`,
      st.map.has(SKEY) && st.map.get(BAK) === raw && st.writes.filter(k => k === BAK).length === 1 && !st.writes.includes(LKEY) && st.map.get(LKEY) === raw);
    const h = api.html("panel");
    check("one-time notice on Today: counts and the unmapped list", /id="legacyNotice"/.test(h) && h.includes(`${Object.keys(exp.prog.w).length} word records`) && h.includes("<bdi>foo</bdi>: unknown field") && h.includes(`kept in ${BAK}`));
    api.el("legacyOk").click();
    check("notice dismissed: gone from Today", !/id="legacyNotice"/.test(api.html("panel")) && api.legacyNotice() === null);
    const saved = st.map.get(SKEY);
    st.writes.length = 0;
    const again = await boot({ storage: st, legacy: true });
    check("second boot: own key present, no re-migration, no notice, backup not rewritten",
      JSON.stringify(again.api.getProg()) === JSON.stringify(JSON.parse(saved)) && !st.writes.includes(BAK) && !/id="legacyNotice"/.test(again.api.html("panel")) && st.map.get(BAK) === raw);
  }
  {
    const raw = JSON.stringify(LSEED_C);
    const st = memStorage({ [LKEY]: raw, [BAK]: "FIRST" });
    const { api } = await boot({ storage: st, legacy: true });
    check("an existing backup is never overwritten (migration still runs)", st.map.get(BAK) === "FIRST" && Object.keys(api.getProg().w).length === Object.keys(LSEED_C.w).length && st.map.has(SKEY));
  }
  {
    let err = null, r;
    try{ r = await boot({ storage: memStorage({ [LKEY]: JSON.stringify(LSEED_C) }, { throwGet: () => true }), legacy: true }); }catch(e){ err = e; }
    check(`localStorage throwing on every read: boot completes read-only, renders Today${err ? ` (${err.message})` : ""}`, !err && /id="go"|id="charChoice"/.test(r.api.html("panel")) && Object.keys(r.api.getProg().w).length === 0);
    // Failure paths (B8): a legacy record is (or may be) there but was not imported. Today
    // says so and why, and the session saves nothing, so a later boot can still migrate.
    const failCase = async (name, st, why, expectWrites) => {
      let e = null, x = null;
      try{ x = await boot({ storage: st, legacy: true }); }catch(err){ e = err; }
      if(e){ check(`${name}: boot completes (${e.message})`, false); return null; }
      const h0 = x.api.html("panel");
      check(`${name}: no migration, Today renders with the not-imported notice (${why.source})`,
        Object.keys(x.api.getProg().w).length === 0 && /id="go"/.test(h0) && /id="legacyFail"/.test(h0) && /found but not imported/.test(h0) && why.test(h0) && x.api.readOnly());
      const before = st.writes.slice();
      x.api.el("themebtn").click(); await tick();
      x.api.getProg().sessions = 5; x.api.today();
      check(`${name}: nothing persisted this session (no ${SKEY}; writes ${JSON.stringify(expectWrites)})`,
        !st.map.has(SKEY) && JSON.stringify(st.writes) === JSON.stringify(expectWrites) && JSON.stringify(before) === JSON.stringify(expectWrites) && !st.writes.includes(LKEY));
      return x;
    };
    const st2 = memStorage({ [LKEY]: JSON.stringify(LSEED_C) }, { throwGet: k => k === LKEY });
    await failCase("legacy key unreadable", st2, /could not be read \(storage error\)/, []);
    const st3 = memStorage({ [LKEY]: JSON.stringify(LSEED_C) }, { throwSet: true });
    await failCase("backup write throwing", st3, /safety copy \([^)]*\) could not be saved/, []);
    const stB = memStorage({ [LKEY]: JSON.stringify(LSEED_C), [BAK]: "FIRST" }, { throwGet: k => k === BAK });
    await failCase("backup key unreadable", stB, /safety copy \([^)]*\) could not be checked/, []);
    check("backup key unreadable: the existing backup is untouched", stB.map.get(BAK) === "FIRST");
    const st4 = memStorage({ [LKEY]: JSON.stringify({ v:3 }) });
    const x4 = await failCase("unconvertible legacy record", st4, /could not be converted \(/, []);
    // A later boot can still migrate: the legacy key becomes readable again.
    const st2b = memStorage(Object.fromEntries(st2.map));
    const later = await boot({ storage: st2b, legacy: true });
    check("after a failed boot, a later boot migrates (own key still empty)", Object.keys(later.api.getProg().w).length === Object.keys(LSEED_C.w).length && st2b.map.has(SKEY) && /id="legacyNotice"/.test(later.api.html("panel")) && !later.api.legacyFail());
    // "Start without it": lifts the hold, saves from here on, old record untouched.
    x4.api.el("legacySkip").click(); await tick();
    check("Start without it: notice gone, session saves, legacy key untouched",
      !/id="legacyFail"/.test(x4.api.html("panel")) && !x4.api.readOnly() && st4.map.has(SKEY) && st4.map.get(LKEY) === JSON.stringify({ v:3 }) && !st4.map.has(BAK));
    const st5 = memStorage({ [LKEY]: JSON.stringify(LSEED_C) });
    r = await boot({ storage: st5 });
    check("no legacy.js: the legacy key is ignored", Object.keys(r.api.getProg().w).length === 0 && !st5.map.has(BAK));
  }

  // ---------------------------------------------------------------- [12] passage ruby
  console.log("\n[12] passage ruby in the Read tab");
  {
    const ubw = VC.unitByWord(CHARACTERS);
    // A passage whose sentences carry sentences.json-style ruby, built from its spans.
    const src = PASSAGES.find(p => p.sentences.some(s => (s.spans || []).filter(x => ubw.get(x[2])).length >= 2));
    const withRuby = clone(src);
    withRuby.sentences.forEach(s => { s.ruby = (s.spans || []).filter(x => ubw.get(x[2])).map(x => [x[0], x[1], VC.unitReading(ubw.get(x[2]), BY_ID), x[2]]); });
    const si = withRuby.sentences.findIndex(s => s.ruby.length >= 2 && new Set(s.ruby.map(r => ubw.get(r[3]).id)).size >= 2);
    const s = withRuby.sentences[si], s0 = src.sentences[si];
    const [ta] = s.ruby; const tb = s.ruby.find(r => ubw.get(r[3]).id !== ubw.get(ta[3]).id);
    const p = seedC(); p.chars.c[ubw.get(ta[3]).id] = { r:1, w:0, s:1 }; p.chars.c[ubw.get(tb[3]).id] = { r:6, w:0, s:6 };
    const on = await boot({ passages: [withRuby] }), plain = await boot({ passages: [src] }), off = await boot({ chars: false, passages: [withRuby] });
    [on, plain, off].forEach(x => x.api.setProg(JSON.parse(JSON.stringify(p))));
    const h = on.api.passageSentenceHTML(s, si, false), h0 = plain.api.passageSentenceHTML(s0, si, false);
    const A = s.t.slice(ta[0], ta[1]), B = s.t.slice(tb[0], tb[1]);
    check(`below bare: ${A} renders <ruby> with its reading inside its tap span`, new RegExp(`data-pw="${ta[3]}"[^>]*><ruby>${A}<rt>${ta[2]}</rt></ruby></span>`).test(h));
    check(`at bare: ${B} keeps its reading hidden (class "bare") inside its tap span`, new RegExp(`data-pw="${tb[3]}"[^>]*><ruby class="bare">${B}<rt>${tb[2]}</rt></ruby></span>`).test(h));
    {
      // Passage tokens: the same width invariance across tiers as sentence rows.
      const q1 = JSON.parse(JSON.stringify(p)), q2 = JSON.parse(JSON.stringify(p));
      withRuby.sentences.forEach(x => (x.ruby || []).forEach(r => { const u = ubw.get(r[3]); q1.chars.c[u.id] = { r:1, w:0, s:1 }; q2.chars.c[u.id] = { r:6, w:0, s:6 }; }));
      let varied = 0;
      withRuby.sentences.forEach((x, i) => { on.api.setProg(q1); const a = on.api.passageSentenceHTML(x, i, false); on.api.setProg(q2); const b = on.api.passageSentenceHTML(x, i, false); if(a !== b.replace(/<ruby class="bare">/g, "<ruby>")) varied++; });
      check(`passage: every sentence's markup is the same below bare and at bare apart from class="bare" (${varied} varied)`, varied === 0);
      on.api.setProg(p);
    }
    check("ruby line box class on the passage text", /class="ptxt hasruby"/.test(h) && !/hasruby/.test(h0));
    check("tap spans unchanged and text intact under ruby", count(h, /data-pw=/g) === count(h0, /data-pw=/g) && stripTags((h.match(/<div class="ptxt[^"]*"[^>]*>([\s\S]*?)<\/div>/) || [])[1] || "") === s.t);
    let bad = 0;
    withRuby.sentences.forEach((x, i) => { const r = on.api.passageSentenceHTML(x, i, false); if(stripTags((r.match(/<div class="ptxt[^"]*"[^>]*>([\s\S]*?)<\/div>/) || [])[1] || "") !== x.t) bad++; });
    check(`every sentence of the passage renders to its own text (${bad} bad)`, bad === 0);
    {
      // Span display glosses (spans[i][3]) survive the ruby render: each glossed tap span
      // carries the same data-pg with and without ruby.
      const pgs = h => [...h.matchAll(/data-pw="([^"]+)" data-pg="([^"]*)"/g)].map(m => m[1] + "=" + m[2]).join("|");
      let pgBad = 0, pgN = 0;
      withRuby.sentences.forEach((x, i) => {
        const r = pgs(on.api.passageSentenceHTML(x, i, false)), r0 = pgs(plain.api.passageSentenceHTML(src.sentences[i], i, false));
        const want = (x.spans || []).filter(k => typeof k[3] === "string" && k[3].trim()).length;
        pgN += want; if(r !== r0 || (r ? r.split("|").length : 0) !== want) pgBad++;
      });
      check(`passage ruby: tap spans keep their span gloss (data-pg) under ruby (${pgN} glossed spans, ${pgBad} sentences off)`, pgN > 0 && pgBad === 0);
    }
    on.api.getProg().chars.mix = false;
    check("mix off: passage sentence renders exactly as without ruby", on.api.passageSentenceHTML(s, si, false) === h0);
    on.api.getProg().chars.mix = true; on.api.getProg().showPron = false;
    check("showPron off: no ruby", on.api.passageSentenceHTML(s, si, false) === h0);
    check("no characters stage: passage ruby ignored", off.api.passageSentenceHTML(s, si, false) === plain.api.passageSentenceHTML(s0, si, false));
    check("CSS: passage ruby line box overrides the passage line height", /\.psent \.ptxt\.hasruby\{line-height:2\.3\}/.test(appHtml));
  }

  // ---------------------------------------------------------------- [13] B8 nits
  console.log("\n[13] astral ruby, HAS_CHARACTERS from charsConfig");
  {
    const { api } = await boot();
    // 𠮷 is one astral character, two UTF-16 code units: offsets are code units.
    const t = "𠮷a𠮷b";
    const toks = [{ start:0, end:2, reading:"jí", tier:"ruby" }, { start:3, end:5, reading:"jí2", tier:"bare" }];
    const h = api.rubyTextHTML({ t }, toks);
    check(`rubyTextHTML: astral characters keep whole pairs (got ${h})`, h === `<ruby>𠮷<rt>jí</rt></ruby>a<ruby class="bare">𠮷<rt>jí2</rt></ruby>b`);
    const hb = api.rubyTextHTML({ t }, [{ start:1, end:3, reading:"x", tier:"ruby" }]);
    check("rubyTextHTML: a token over the whole text renders its text back", stripTags(api.rubyTextHTML({ t }, [{ start:0, end:5, reading:"x", tier:"ruby" }])) === t && stripTags(hb) === t);
  }
  {
    const odd = Object.assign({}, PACK, { characters: true });
    let err = null, r = null;
    try{ r = await boot({ pack: odd }); }catch(e){ err = e; }
    check("pack.characters not an object (true): HAS_CHARACTERS off (charsConfig null), no crash", !err && !r.api.hasChars() && !/charChoice|<ruby/.test(r.api.html("panel")));
  }

  // ---------------------------------------------------------------- [14] pronFirst
  console.log("\n[14] pronunciation-first (pack.pronFirst, brief BP): the zh pack as shipped");
  // Visible written characters in markup: Han outside the show-written tap's hidden form.
  // (data-pg: a span's display gloss, shown only in the popover, may quote its headword.)
  const visHan = h => (String(h == null ? "" : h).replace(/data-(showw|pg)="[^"]*"/g, "").match(/\p{Script=Han}/gu) || []).join("");
  const onlyLabel = h => /^字*$/.test(visHan(h)); // the stage label 字 / 字4 (path strip, Progress rows)
  const PF_ZH = PACK_ZH;
  const NSZ = lv => VC.nSets(VC.wordsByLevel(WORDS, PF_ZH)[lv], VC.setSizeOf(PF_ZH));
  const seedPF = () => VC.normalizeProg({ sets: { "1": NSZ("1"), "2": 2 }, placedOnce: true, sessions: 5 }, PF_ZH);
  check("zh pack.json ships pronFirst: true", PF_ZH.pronFirst === true);
  // Walks the active screen flow: answers every drill item right, presses Continue /
  // Drill / Next, and records every screen, option label and reveal.
  function walk(api, stopAt){
    const seen = [];
    for(let i = 0; i < 600; i++){
      const P = api.html("panel");
      if(api.getD()){
        const it = api.getCur(); const btns = api.el("o").children;
        seen.push({ where: it.key, html: P + btns.map(b => b.innerHTML).join("|") });
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
  {
    const { api } = await boot({ pack: PF_ZH });
    check("PRON_FIRST on for zh, show-written capture listener attached", api.pronFirst() && api.panelListeners().length === 2);
    api.setProg(seedPF()); api.today();
    // The Read hint names a passage by its title, which has no reading data (reported residual).
    const todayH = api.html("panel").replace(/<div class="stmt" id="readHintBox">[\s\S]*?<\/div>/, "");
    check(`Today: no written form besides the stage label and the Read hint's passage title (${visHan(todayH)})`, onlyLabel(todayH));
    api.el("go").click();
    let seen = [], err = null;
    try{ seen = walk(api, /id="again"/); }catch(e){ err = e; }
    const bad = seen.filter(x => visHan(x.html));
    const kinds = new Set(seen.map(x => x.where.split(":")[0]));
    check(`Today, no unit recorded: Review, Learn (teach + drill), Listen, Recall, Sentences show no hanzi (${seen.length} screens/items; ${bad.length} bad${bad[0] ? `: ${bad[0].where} ${visHan(bad[0].html)}` : ""})${err ? " " + err.message : ""}`,
      !err && bad.length === 0 && kinds.has("w") && kinds.has("s") && kinds.has("teach") && /id="again"/.test(api.html("panel")));
    const w0 = BY_ID["w0028"]; // 你 nǐ
    check("readItem: the stimulus is the reading, with a show-written tap carrying the written form",
      api.readItem(w0).html.includes(`>${w0.pron}<button type="button" class="showw" data-showw="${w0.w}"`));
    // Every sentence: row, read item, reveal; gap items where legal.
    let sb = 0, gb = 0, gn = 0, rb = 0;
    SENTENCES.forEach(s => {
      if(visHan(api.sentenceRowHTML(s)) || visHan(api.readSentence(s).html) || visHan(api.sentenceRevealBlock(s))) sb++;
      const g = api.gapSentence(s, false);
      if(g){ gn++; if(visHan(g.html) || g.opts.some(o => visHan(g.optHtml(o))) || !/class="blank"/.test(g.html)) gb++; }
    });
    check(`all ${SENTENCES.length} sentences: row, read item and reveal read as pinyin (${sb} bad)`, sb === 0);
    check(`gap items: blanked pinyin sentence, pinyin options (${gn} built, ${gb} bad)`, gn > 100 && gb === 0);
    const oneWord = SENTENCES.filter(x => ["不客气。","对不起。","没关系。"].includes(x.t));
    check(`one-word sentences (${oneWord.map(x => x.t).join(" ")}) are never gap items, word-first or pron-first; the read item stands in`,
      oneWord.length === 3 && oneWord.every(x => VC.gapCandidateIndices(x, BY_ID, PF_ZH).length === 0 && VC.gapCandidateIndices(x, BY_ID, PACK).length === 0 && api.gapSentence(x, false) === null));
    check("every gap item leaves a letter outside its blank", SENTENCES.every(x => { const g = api.gapSentence(x, false); return !g || /[\p{L}\p{N}]/u.test(stripTags(g.html.split('<div class="q">')[0]).replace(/____|show written/g, "")); }));
    WORDS.forEach(w => { if(visHan(api.wordRowHTML(w)) || visHan(api.revealBlock(w)) || visHan(api.glossHTML(w.id))) rb++; });
    check(`all ${WORDS.length} words: Words-list row, reveal and passage popover show pinyin (${rb} bad)`, rb === 0);
    // Words tab list and search.
    api.goto("words");
    const rows = () => api.el("wl").children.map(c => c.innerHTML);
    check("Words tab: set rows are pinyin", rows().length === 10 && rows().every(h => !visHan(h)));
    api.wordsSearch("hao");
    check(`Words search "hao": ${rows().length} rows, all pinyin`, rows().length > 0 && rows().every(h => !visHan(h)));
    // Test: Listen and Recall; placement.
    api.goto("test");
    api.el("tRecall").click();
    seen = walk(api);
    check(`Test Recall ${seen.filter(x => x.where.startsWith("w:") && !x.where.endsWith("reveal")).length}: pinyin options and reveals`, seen.length > 20 && seen.every(x => !visHan(x.html)));
    api.goto("test"); api.el("tListen").click(); seen = walk(api);
    check("Test Listen: no hanzi in reveals or the result screen", seen.length > 20 && seen.every(x => !visHan(x.html)));
    api.goto("test"); api.el("pl").click(); api.el("go").click();
    let pbad = 0, pn = 0;
    for(let i = 0; i < 100 && /id="o"/.test(api.html("panel")); i++){ pn++; if(visHan(api.html("panel"))) pbad++; api.el("o").children[0].click(); }
    check(`Placement: ${pn} items, no hanzi (${pbad} bad)`, pn > 10 && pbad === 0);
    // Progress: weak rows.
    const pw = seedPF(); ["w0028","w0091","w0099"].forEach(id => { pw.w[id] = { r:1, w:3, s:0 }; });
    api.setProg(pw); api.goto("progress");
    check("Progress: weakest-word rows in pinyin", onlyLabel(api.html("panel")) && api.html("panel").includes(BY_ID["w0091"].pron));
    // Read: tap spans and question reveals.
    if(PASSAGES.length){
      api.startPassage(PASSAGES[0]);
      const box = api.html("panel").split('id="pbox">')[1] || ""; // the fake DOM keeps markup on the panel only
      const spans = [...box.matchAll(/<span class="pw" data-pw="[^"]*"(?: data-pg="[^"]*")? role="button" tabindex="0">([\s\S]*?)<\/span>/g)].map(m => m[1]);
      check(`Read: every tap span of "${PASSAGES[0].title}" reads as pinyin (${spans.length} spans)`, spans.length > 10 && spans.every(h => !visHan(h)));
      const left = visHan(box);
      const unlinked = PASSAGES[0].sentences.map(x => VC.passageSegments(x, BY_ID, PF_ZH).parts.filter(q => !q.id).map(q => q.text).join("")).join("");
      check(`Read: the only hanzi left in the passage are text no word links (names: ${left})`, left === visHan(unlinked));
      const qs = PASSAGES[0].sentences.map(x => api.passagePlainHTML(x));
      check("Read: question reveal sentences use the same display (tap spans in pinyin)", qs.every(h => h.includes(VC.escapeHtml(BY_ID["w0091"].pron)) || !h.includes("我")));
    }
  }
  {
    // Mastered unit: its word shows written; sentences give it ruby, the rest stay pinyin.
    const { api } = await boot({ pack: PF_ZH });
    const p = seedPF(); VC.answerCharChoice(p, true);
    const uWo = VC.unitByWord(CHARACTERS).get("w0091"); // 我
    p.chars.c[uWo.id] = { r:3, w:0, s:3 };
    api.setProg(p);
    const wo = BY_ID["w0091"], ni = BY_ID["w0028"];
    check("mastered unit (streak = mastered): its word renders written with its pron beside it",
      new RegExp(`^<span class="wd" data-tl lang="[^"]+">${wo.w}</span>`).test(api.wordRowHTML(wo)) && api.wordRowHTML(wo).includes(`>${wo.pron}<`) && !/data-showw/.test(api.wordRowHTML(wo)));
    check("an unmastered word next to it still renders its reading", !visHan(api.wordRowHTML(ni)));
    check("row layout: a reading-shown word gets class pf (one line with its tap), a written one does not",
      /^<span class="wd pf"/.test(api.wordRowHTML(ni)) && /^<span class="wd"/.test(api.wordRowHTML(wo)) && /\.wl \.wd\.pf,\.rowset \.wd\.pf\{white-space:nowrap;max-width:75%\}/.test(appHtml));
    const s0 = SENTENCES[0]; // 你好，我是学生。
    const row = api.sentenceRowHTML(s0);
    check(`sentence: the mastered token as ruby, the rest pinyin (${stripTags(row)})`, row.includes(`<ruby>${wo.w}<rt>${wo.pron}</rt></ruby>`) && visHan(row) === wo.w);
    p.chars.c[uWo.id].s = 6;
    check("at bare: the token is bare (reading hidden)", api.sentenceRowHTML(s0).includes(`<ruby class="bare">${wo.w}<rt>`));
    p.chars.mix = false;
    check("mix off: the sentence is reading-only again, the word itself stays written", !visHan(api.sentenceRowHTML(s0)) && api.wordRowHTML(wo).includes(`>${wo.w}<`));
    p.chars.mix = true;
    // Characters stage: teach cards and char items keep the written form.
    const cu = VC.charStageUnits(["1","2","3"], CHARACTERS, PF_ZH)[0];
    const ci = api.charDrillItem("charRead", cu);
    check("characters stage: a charRead item still shows the written form", ci.html.includes(`>${cu.t}<`));
    // Teach cards: the taught unit's own token in its example sentence is written (ruby).
    const cs = VC.nextCharSet(["1","2","3"], CHARACTERS, PF_ZH, VC.normalizeProg({}, PF_ZH));
    api.setProg(seedPF()); api.charTeach(cs, { label: "字" }, () => {});
    const cards = api.html("panel").split('<div class="charteach">').slice(1);
    let withEx = 0, bad = 0;
    cs.units.forEach((u, i) => {
      const exPart = (cards[i] || "").split('<div class="sent"')[1];
      if(!exPart) return; withEx++;
      const others = visHan(exPart.replace(new RegExp(`<ruby>${u.t}<rt>[^<]*</rt></ruby>`, "g"), ""));
      if(!exPart.includes(`<ruby>${u.t}<rt>${VC.unitReading(u, BY_ID)}</rt></ruby>`) || others) bad++;
    });
    check(`teach cards: the taught unit's token is written with ruby in its example, the rest pinyin (${withEx} examples, ${bad} bad)`, withEx > 0 && bad === 0);
  }
  {
    // The show-written tap: swaps itself for the written form, item only, no progress change.
    const { api, document } = await boot({ pack: PF_ZH });
    api.setProg(seedPF());
    const before = JSON.stringify(api.getProg());
    let focused = null; const mk = document.createElement;
    document.createElement = tag => { const el = mk.call(document, tag); el.focus = () => { focused = el; }; return el; };
    const b = { dataset: { showw: "你" }, replaceWith(...xs){ this.gap = xs[0]; this.by = xs[xs.length - 1]; } };
    document.activeElement = b; // keyboard user: the button has focus
    let stopped = false, prevented = false;
    const cap = api.panelListeners()[1];
    cap({ target: { closest: sel => sel === "[data-showw]" ? b : null }, preventDefault(){ prevented = true; }, stopPropagation(){ stopped = true; } });
    const sp = b.by;
    check("show-written tap swaps the button for the written form in place", sp && sp.className === "wwr" && sp.textContent === "你" && sp.getAttribute("lang") && stopped && prevented);
    check("a thin space separates the reading from the revealed written form", b.gap === "\u2009" && /\.wwr\{[^}]*margin-inline-start:3px/.test(appHtml));
    check("the revealed span keeps keyboard focus (tabindex -1, focused)", sp && sp.getAttribute("tabindex") === "-1" && focused === sp);
    const b2 = { dataset: { showw: "好" }, replaceWith(...xs){ this.gap = xs[0]; this.by = xs[xs.length - 1]; } }; focused = null; document.activeElement = null;
    api.revealWritten(b2);
    check("a mouse tap (button not focused) does not move focus", b2.by && focused === null);
    document.createElement = mk;
    check("keys on a show-written button never reach the drill shortcuts (Enter = Next)",
      api.onShowWritten({ target: { closest: s => s === "[data-showw]" ? b : null } }) && !api.onShowWritten({ target: { closest: () => null } }) && /if\(drillKeyHandler && !onShowWritten\(e\)\) drillKeyHandler\(e\)/.test(appHtml));
    check("announce() drops the show-written button label from the live-region text", /querySelectorAll\("\[data-showw\]"\)\.forEach\(x => x\.remove\(\)\)/.test(appHtml.match(/function announce[\s\S]*?\n}\n/)[0]));
    let other = false;
    cap({ target: { closest: () => null }, preventDefault(){ other = true; }, stopPropagation(){ other = true; } });
    check("the tap has no progress effect; other clicks pass through untouched", JSON.stringify(api.getProg()) === before && !other);
  }
  {
    // Homophone distractors in the recall item, on the real pack.
    const { api } = await boot({ pack: PF_ZH });
    api.setProg(seedPF());
    const homs = WORDS.filter(a => WORDS.some(b => b.id !== a.id && VC.pronClash(a, b)));
    let bad = 0;
    for(let r = 0; r < 10; r++) homs.forEach(w => {
      const it = api.recallItem(w); const labels = it.opts.map(o => stripTags(it.optHtml(o)));
      const ents = it.opts.map(o => BY_ID[o]);
      if(new Set(labels).size !== labels.length || ents.some((a, i) => ents.some((b, j) => i < j && VC.pronClash(a, b)))) bad++;
    });
    check(`recall items for ${homs.length} zh words with a homophone: 4 distinct pinyin labels, no two alike in sound (${bad} bad)`, homs.length > 30 && bad === 0);
  }
  {
    // Flag-off: a characters pack without pronFirst renders byte-identically to pronFirst:false.
    const noKey = Object.assign({}, PF_ZH); delete noKey.pronFirst;
    const a = await boot({ pack: PACK }), b = await boot({ pack: noKey });
    a.api.setProg(seedC()); b.api.setProg(seedC());
    const pages = api => ["today","words","test","progress","read"].map(t => { api.goto(t); return api.html("panel") + (api.el("wl") ? api.el("wl").children.map(c => c.innerHTML).join("") : ""); });
    check("pronFirst absent = pronFirst false: every tab identical, no show-written tap anywhere", JSON.stringify(pages(a.api)) === JSON.stringify(pages(b.api)) && !pages(b.api).some(h => /data-showw/.test(h)) && a.api.panelListeners().length === 1);
  }
  {
    // ja-like synthetic pack: kanji words read in kana, kana words as they are.
    const { jaLike } = require(path.join(__dirname, "fixtures", "chars_packs.js"));
    const J = jaLike(); const jp = Object.assign({}, J.pack, { pronFirst: true });
    const { api } = await boot({ pack: jp, words: J.words, units: J.units, sentences: [], lessons: [], passages: [] });
    api.goto("words");
    const list = api.el("wl").children.map(c => c.innerHTML);
    const a1 = J.words.filter(w => w.lv === "A1").slice(0, 10);
    const glyphRows = a1.filter(w => VC.unitByWord(J.units).get(w.id));
    check(`ja-like: Words rows show kana (${glyphRows.length} kanji words by reading, ${a1.length - glyphRows.length} kana words as written), no kanji visible`,
      list.length === 10 && list.every(h => !visHan(h)) && glyphRows.every(w => list.some(h => h.includes(`>${w.pron}<button type="button" class="showw" data-showw="${w.w}"`))));
    let dup = 0, runs = 0;
    for(let r = 0; r < 10; r++) J.words.forEach(w => {
      runs++; const it = api.recallItem(w); const labels = it.opts.map(o => stripTags(it.optHtml(o)));
      const ws = it.opts.map(o => J.words.find(x => x.id === o).w);
      if(new Set(it.opts).size !== it.opts.length || new Set(labels).size !== labels.length || new Set(ws).size !== ws.length) dup++;
    });
    const hg = J.words.filter(a => J.words.some(b => b.id !== a.id && b.w === a.w)).length;
    check(`ja-like recall (${hg} same-form words read differently, ${runs} items): no duplicate option, label or written form (${dup} bad)`, hg >= 2 && dup === 0);
    const k = J.words.find(w => !VC.unitByWord(J.units).get(w.id));
    check("ja-like: a kana word has no show-written tap", !/data-showw/.test(api.wordRowHTML(k)) && api.wordRowHTML(k).includes(`>${k.w}<`));
  }

  console.log(`\n${fails ? "FAILED" : "ALL PASSED"}: ${passes} passed, ${fails} failed`);
  process.exit(fails ? 1 : 0);
})().catch(e => { console.log(`FAIL  harness threw: ${e.stack}`); process.exit(1); });
