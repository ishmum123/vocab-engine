// App checks for the characters stage in engine/app.html (docs/HSK_MERGE.md §2.5, §2.7,
// §3, rows B4 and B5): path strip, choice card, unit Learn with teach cards, the 4 unit item
// renderers, the Start-today snapshot, unified Review/Recall, sentence ruby by tier; B5:
// Test "Characters N", Progress stage rows and order/mix chips, reset, legacy import, the
// boot migration hook (§4, core.js "legacy migration" contract) and passage ruby.
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
const PACK = loadConst(path.join(ZH, "pack.js"), "PACK");
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
  legacyNotice: () => legacyNotice,
  sentenceRowHTML, sentenceRevealBlock, readSentence, charDrillItem, passageSentenceHTML, hasChars: () => HAS_CHARACTERS,
};`;
  const names = ["document","window","navigator","location","localStorage","matchMedia","requestAnimationFrame","Audio","confirm","alert","PACK","WORDS","SENTENCES","LESSONS","PASSAGES"];
  const args = [document, window, { userAgent:"CharsAppChecks/1.0" }, undefined, localStorage, () => ({ matches:false }), fn => setTimeout(fn, 0),
    function(){ return { play(){ return Promise.resolve(); }, pause(){} }; }, () => true, () => {}, pack, WORDS, SENTENCES, LESSONS, o.passages || PASSAGES];
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
const stripTags = h => h.replace(/<rt>[\s\S]*?<\/rt>/g, "").replace(/<[^>]+>/g, "").replace(/&lt;/g,"<").replace(/&gt;/g,">").replace(/&quot;/g,'"').replace(/&#39;/g,"'").replace(/&amp;/g,"&");

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
    check("before any unit record: Review line is 20 items (characters started)", /1\. Review<\/td><td>20 items, weakest first, words and 字/.test(h));

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
    api.el("go").click();
    const D = api.getD();
    const items = [api.getCur(), ...D.q];
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
    check(`bare at/above bare: ${s.t.slice(tb[0], tb[1])} renders plain`, !row.includes(`<ruby>${s.t.slice(tb[0], tb[1])}<rt>`));
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
    const offRow = off.api.sentenceRowHTML(s);
    p.showPron = false; const noPron = api.sentenceRowHTML(s); p.showPron = true;
    off.api.getProg().showPron = false; const offNoPron = off.api.sentenceRowHTML(s);
    check("showPron off hides all ruby (same markup as without characters)", !/<ruby>/.test(noPron) && noPron === offNoPron);
    p.chars.mix = false;
    check("mix off: sentence renders exactly as without characters", api.sentenceRowHTML(s) === offRow);
    p.chars.mix = true;
    api.setProg(VC.normalizeProg({ sets: { "1": 2 } }, PACK));
    check("characters not started: sentence renders exactly as without characters", api.sentenceRowHTML(s) === offRow);
    check("gap items are unchanged (no ruby in the gap stimulus)", !/hasruby/.test(appHtml.match(/function gapSentence[\s\S]*?\n}\n/)[0]));
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
    api.setProg(seedB()); api.goto("test");
    check("no unit recorded: no Characters test", !/id="tChars"/.test(api.html("panel")));
    const p5 = seedB(); VC.answerCharChoice(p5, true);
    VC.charStageUnits(["1","2","3"], CHARACTERS, PACK).slice(0, 5).forEach(u => { p5.chars.c[u.id] = { r:1, w:0, s:1 }; });
    api.setProg(p5); api.goto("test");
    check("5 recorded units: Characters 5", /id="tChars">Characters 5</.test(api.html("panel")));
    api.setProg(seedC()); api.goto("test");
    check("40 recorded units: Characters 20 (capped like the other free tests)", /id="tChars">Characters 20</.test(api.html("panel")));
    api.el("tChars").click();
    const items = [api.getCur(), ...api.getD().q];
    const recs = api.getProg().chars.c;
    check("Characters test: 20 unit items, all recorded units, reviewKinds (form stimulus)",
      items.length === 20 && items.every(x => x.key.startsWith("c:") && recs[x.key.slice(2)] && /class="big wd"/.test(x.html)));
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
    const st2 = memStorage({ [LKEY]: JSON.stringify(LSEED_C) }, { throwGet: k => k === LKEY });
    err = null; try{ r = await boot({ storage: st2, legacy: true }); }catch(e){ err = e; }
    check("legacy key unreadable: no migration, no writes to it or the backup, Today renders", !err && Object.keys(r.api.getProg().w).length === 0 && !st2.writes.includes(BAK) && /id="go"/.test(r.api.html("panel")));
    const st3 = memStorage({ [LKEY]: JSON.stringify(LSEED_C) }, { throwSet: true });
    err = null; try{ r = await boot({ storage: st3, legacy: true }); }catch(e){ err = e; }
    check("storage writes throwing: backup can't be secured, so no migration; no crash", !err && Object.keys(r.api.getProg().w).length === 0 && /id="go"/.test(r.api.html("panel")) && !r.api.legacyNotice());
    const stB = memStorage({ [LKEY]: JSON.stringify(LSEED_C), [BAK]: "FIRST" }, { throwGet: k => k === BAK });
    err = null; try{ r = await boot({ storage: stB, legacy: true }); }catch(e){ err = e; }
    check("backup key unreadable: no migration (it might hold a backup), nothing written", !err && Object.keys(r.api.getProg().w).length === 0 && stB.map.get(BAK) === "FIRST" && !stB.writes.length);
    const st4 = memStorage({ [LKEY]: JSON.stringify({ v:3 }) });
    r = await boot({ storage: st4, legacy: true });
    check("unconvertible legacy record: not migrated, nothing written", Object.keys(r.api.getProg().w).length === 0 && !st4.map.has(BAK) && !st4.map.has(SKEY));
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
    check(`at bare: ${B} renders plain`, new RegExp(`data-pw="${tb[3]}"[^>]*>${B}</span>`).test(h));
    check("ruby line box class on the passage text", /class="ptxt hasruby"/.test(h) && !/hasruby/.test(h0));
    check("tap spans unchanged and text intact under ruby", count(h, /data-pw=/g) === count(h0, /data-pw=/g) && stripTags((h.match(/<div class="ptxt[^"]*"[^>]*>([\s\S]*?)<\/div>/) || [])[1] || "") === s.t);
    let bad = 0;
    withRuby.sentences.forEach((x, i) => { const r = on.api.passageSentenceHTML(x, i, false); if(stripTags((r.match(/<div class="ptxt[^"]*"[^>]*>([\s\S]*?)<\/div>/) || [])[1] || "") !== x.t) bad++; });
    check(`every sentence of the passage renders to its own text (${bad} bad)`, bad === 0);
    on.api.getProg().chars.mix = false;
    check("mix off: passage sentence renders exactly as without ruby", on.api.passageSentenceHTML(s, si, false) === h0);
    on.api.getProg().chars.mix = true; on.api.getProg().showPron = false;
    check("showPron off: no ruby", on.api.passageSentenceHTML(s, si, false) === h0);
    check("no characters stage: passage ruby ignored", off.api.passageSentenceHTML(s, si, false) === plain.api.passageSentenceHTML(s0, si, false));
    check("CSS: passage ruby line box overrides the passage line height", /\.psent \.ptxt\.hasruby\{line-height:2\.3\}/.test(appHtml));
  }

  console.log(`\n${fails ? "FAILED" : "ALL PASSED"}: ${passes} passed, ${fails} failed`);
  process.exit(fails ? 1 : 0);
})().catch(e => { console.log(`FAIL  harness threw: ${e.stack}`); process.exit(1); });
