// App checks for the characters stage in engine/app.html (docs/HSK_MERGE.md §2.5, §2.7,
// §3, row B4): path strip, choice card, unit Learn with teach cards, the 4 unit item
// renderers, the Start-today snapshot, unified Review/Recall, sentence ruby by tier.
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
  const localStorage = { getItem(){ return null; }, setItem(){} };
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
  sentenceRowHTML, sentenceRevealBlock, readSentence, charDrillItem, hasChars: () => HAS_CHARACTERS,
};`;
  const names = ["document","window","navigator","location","localStorage","matchMedia","requestAnimationFrame","Audio","PACK","WORDS","SENTENCES","LESSONS","PASSAGES"];
  const args = [document, window, { userAgent:"CharsAppChecks/1.0" }, undefined, localStorage, () => ({ matches:false }), fn => setTimeout(fn, 0),
    function(){ return { play(){ return Promise.resolve(); }, pause(){} }; }, pack, WORDS, SENTENCES, LESSONS, PASSAGES];
  if(o.chars !== false){ names.push("CHARACTERS"); args.push(o.units || CHARACTERS); }
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

  console.log(`\n${fails ? "FAILED" : "ALL PASSED"}: ${passes} passed, ${fails} failed`);
  process.exit(fails ? 1 : 0);
})().catch(e => { console.log(`FAIL  harness threw: ${e.stack}`); process.exit(1); });
