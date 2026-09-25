// Flag-off golden harness (HSK_MERGE.md §6 row B0, "Flag-off proof").
//
// The hsk/characters merge (see docs/HSK_MERGE.md) must be a no-op for every pack
// that never sets pack.characters. Since engine code is inlined into dist/*.html and
// sw.js carries a build id, literal dist bytes always change on any engine edit —
// so the flag-off proof is behavioural instead:
//   1. flag-off pack sources (and the fields their generated .js encode) are
//      unchanged, once the `characters`/`ruby`/`legacy` fields the merge adds exist;
//   2. defaultProg, normalizeProg and the plan builders deep-equal goldens captured
//      here, under a seeded random generator;
//   3. a fake-DOM boot of engine/app.html (the same technique as engine_checks.js
//      check [23]) renders Today, Words, Test, Progress and Read byte-identically,
//      for 3 seeded progress states across 4 packs.
//
// Run: /opt/homebrew/bin/node tests/flagoff_snapshot.js --capture   (writes tests/golden/)
//      /opt/homebrew/bin/node tests/flagoff_snapshot.js --check     (compares; exit 1 on drift)
//
// core.js's own plan builders (buildReviewPlan, buildRecallPlan, sentenceKind, and the
// weakFirst/kindMix/shuffle they call internally) take an optional `rng` — but
// buildRecallPlan does not thread it down (core.js:835-839 call weakFirst/kindMix with
// no rng arg), so it always falls back to the global Math.random. engine_checks.js
// itself never seeds Math.random: its "seeded" checks (e.g. buildReviewPlan's
// weakest-first ordering) are statistical, run 30x over the real Math.random and
// asserted on invariants, not on a captured deterministic value. There is no seeding
// convention to reuse here, so this harness substitutes the global Math.random with a
// small seeded PRNG (mulberry32) for the duration of every capture/check, which makes
// every call site — explicit `rng` param or not — deterministic.
"use strict";
const fs = require("fs");
const path = require("path");
const cp = require("child_process");
const util = require("util");
const crypto = require("crypto");

const ROOT = path.join(__dirname, "..");
const GOLDEN_DIR = path.join(__dirname, "golden");
const VC = require(path.join(ROOT, "engine", "core.js"));

const MODE = process.argv[2];
if (MODE !== "--capture" && MODE !== "--check") {
  console.error("usage: node tests/flagoff_snapshot.js --capture|--check");
  process.exit(2);
}

let fails = 0, passes = 0, notCapturable = [];
function check(name, cond) {
  if (cond) { passes++; console.log(`PASS  ${name}`); }
  else { fails++; console.log(`FAIL  ${name}`); }
}
function note(msg) { notCapturable.push(msg); console.log(`NOTE  ${msg}`); }

// ------------------------------------------------------------------ seeded RNG
function mulberry32(seed) {
  let a = seed >>> 0;
  return function () {
    a |= 0; a = (a + 0x6D2B79F5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
function withSeededRandom(seed, fn) {
  const orig = Math.random;
  Math.random = mulberry32(seed);
  try { return fn(); } finally { Math.random = orig; }
}
async function withSeededRandomAsync(seed, fn) {
  const orig = Math.random;
  Math.random = mulberry32(seed);
  try { return await fn(); } finally { Math.random = orig; }
}

// ------------------------------------------------------------------ golden I/O
function goldenPath(name) { return path.join(GOLDEN_DIR, name + ".json"); }
function writeGolden(name, data) {
  fs.mkdirSync(GOLDEN_DIR, { recursive: true });
  fs.writeFileSync(goldenPath(name), JSON.stringify(data, null, 1) + "\n");
}
function readGolden(name) {
  const p = goldenPath(name);
  if (!fs.existsSync(p)) return { __missing: true };
  return JSON.parse(fs.readFileSync(p, "utf8"));
}
function checkGolden(name, actual) {
  const expected = readGolden(name);
  if (expected.__missing) { check(`golden/${name}.json exists`, false); return; }
  check(`golden/${name}.json deep-equals current output`, util.isDeepStrictEqual(expected, actual));
}
function handleGolden(name, actual) {
  if (MODE === "--capture") writeGolden(name, actual);
  else checkGolden(name, actual);
}

// ================================================================== [1] flag-off
// pack sources unchanged. "Unchanged" for a field that the merge adds (pack.json's
// `characters`, `legacy`, `pronFirst`, `tones`, `soundsReference` and typing "pron", a
// sentence's `ruby`) means the merge is not allowed to change the
// value of any field that predates it — so this strips those fields (once they
// exist) from the current file before comparing to the pre-merge golden, rather
// than requiring a literal empty `git diff` (which the merge itself will violate by
// design once B1/B3/B7 add those fields). See HSK_MERGE.md §6 "Flag-off proof" item 1
// and its "packs/zh with a stripped characters block once it exists" parenthetical.
const FLAGOFF_PACKS = [
  { name: "zh", dir: path.join(ROOT, "packs", "zh") },
  { name: "italian", dir: path.join(ROOT, "..", "italian", "pack") },
  { name: "spanish", dir: path.join(ROOT, "..", "spanish", "pack") },
  { name: "french", dir: path.join(ROOT, "..", "french", "pack") },
  { name: "german", dir: path.join(ROOT, "..", "german", "pack") },
  { name: "russian", dir: path.join(ROOT, "..", "russian", "pack") },
  { name: "persian", dir: path.join(ROOT, "..", "persian", "pack") },
  { name: "indonesian", dir: path.join(ROOT, "..", "indonesian", "pack") },
  { name: "korean", dir: path.join(ROOT, "..", "korean", "pack") },
  { name: "japanese", dir: path.join(ROOT, "..", "japanese", "pack") },
];
function readJsonIfPresent(p) { return fs.existsSync(p) ? JSON.parse(fs.readFileSync(p, "utf8")) : null; }
function stripFlagOnFields(packJson, wordsJson, sentencesJson) {
  const pack = packJson ? Object.assign({}, packJson) : null;
  if (pack) {
    delete pack.characters; delete pack.legacy; delete pack.pronFirst;
    // BP2 pronunciation aids (docs/PACK_SCHEMA.md): tones and soundsReference are new
    // fields; typing "pron" replaced the pre-merge typing: null (typed reading is flag-on).
    delete pack.tones; delete pack.soundsReference;
    if (pack.typing === "pron") pack.typing = null;
  }
  const sentences = Array.isArray(sentencesJson)
    ? sentencesJson.map(s => { const c = Object.assign({}, s); delete c.ruby; return c; })
    : sentencesJson;
  return { pack, words: wordsJson, sentences };
}
function flagOffSnapshotOf(dir) {
  return stripFlagOnFields(
    readJsonIfPresent(path.join(dir, "pack.json")),
    readJsonIfPresent(path.join(dir, "words.json")),
    readJsonIfPresent(path.join(dir, "sentences.json"))
  );
}
// Content hash rather than the raw JSON: these packs run 350KB-1.5MB of JSON each,
// and this golden only ever needs to answer "did it change", not "what changed" (a
// real diff, if this fails, is one `git diff -- <sibling>/pack` away).
function sha256(obj) { return crypto.createHash("sha256").update(JSON.stringify(obj)).digest("hex"); }
function runFlagOffPackChecks() {
  console.log("\n[1] flag-off pack sources unchanged (characters/ruby stripped, once they exist)");
  FLAGOFF_PACKS.forEach(({ name, dir }) => {
    if (!fs.existsSync(dir)) { note(`flag-off pack "${name}": ${dir} does not exist, skipped`); return; }
    handleGolden(`flagoff_pack_${name}`, { sha256: sha256(flagOffSnapshotOf(dir)) });
  });
  // Synthetic packs kept as standalone files under tests/ (as opposed to the inline
  // pack objects engine_checks.js builds in-memory, e.g. its FA/JA/RP consts, which
  // have no file to diff): none exist on this HEAD, so there is nothing to snapshot
  // yet. A future synthetic-pack directory under tests/ should be added here.
  const testsSynthetic = path.join(__dirname, "packs");
  if (fs.existsSync(testsSynthetic)) note(`found ${testsSynthetic} — wire it into FLAGOFF_PACKS`);
  else note('no standalone synthetic pack files under tests/ on this HEAD (engine_checks.js\' synthetic packs are inline JS objects, not files) — nothing to snapshot for that part of proof item 1');
}

// ================================================================== [2] pure-function goldens
function loadConst(file, name) {
  return new Function(fs.readFileSync(file, "utf8") + `\nreturn ${name};`)();
}
function tryLoadConst(file, name) {
  if (!fs.existsSync(file)) return undefined;
  try { return loadConst(file, name); } catch (e) { return undefined; }
}
const REAL_PACKS = [
  { name: "zh", dir: path.join(ROOT, "packs", "zh") },
  { name: "italian", dir: path.join(ROOT, "..", "italian", "pack") },
  { name: "korean", dir: path.join(ROOT, "..", "korean", "pack") },
  { name: "japanese", dir: path.join(ROOT, "..", "japanese", "pack") },
];
function loadPack(dir) {
  const pack = loadConst(path.join(dir, "pack.js"), "PACK");
  const words = loadConst(path.join(dir, "words.js"), "WORDS");
  const sentences = loadConst(path.join(dir, "sentences.js"), "SENTENCES");
  const lessons = tryLoadConst(path.join(dir, "lessons.js"), "LESSONS") || [];
  const passages = tryLoadConst(path.join(dir, "sentences.js"), "PASSAGES") || [];
  // Flag-off view: the goldens were captured before the characters merge, so the
  // fields it adds (pack.characters, pack.legacy, sentence ruby) are stripped here too.
  const off = stripFlagOnFields(pack, words, sentences);
  return { pack: off.pack, words: off.words, sentences: off.sentences, lessons, passages };
}

// A deterministic (non-random) fixture: level 0 = untouched defaults, level 1 =
// partial (one set into the first level, a couple of weak/strong word records, one
// provisional flag), level 2 = mature (several sets across levels, sentence records,
// closer to every Today gate being open). Built from each pack's own words/sentences
// so it scales to any level/set-size shape without per-pack tuning.
function buildFixtureProg(level, pack, words, sentences) {
  const prog = VC.defaultProg(pack);
  if (level === 0) return prog;
  const byLv = VC.wordsByLevel(words, pack);
  const lvIds = VC.levelIds(pack);
  const size = VC.setSizeOf(pack);
  const setsPerLevel = level === 1 ? 1 : 3;
  lvIds.forEach((lv, i) => {
    if (level === 1 && i > 0) return;
    const avail = VC.nSets(byLv[lv], size);
    prog.sets[lv] = Math.min(setsPerLevel, avail);
  });
  const learned = VC.learnedWords(words, pack, prog);
  learned.slice(0, 5).forEach(w => { prog.w[w.id] = { r: 5, w: 0, s: 5 }; });
  learned.slice(5, 8).forEach(w => { prog.w[w.id] = { r: 1, w: 3, s: 0 }; });
  if (learned.length > 8) prog.w[learned[8].id] = { r: 0, w: 0, s: 0, prov: true };
  if (level === 2) {
    const avail = VC.availableSentences(sentences, words, pack, prog);
    avail.slice(0, 4).forEach(s => { prog.s[s.id] = { r: 2, w: 0, s: 2 }; });
  }
  prog.sessions = level === 1 ? 2 : 7;
  prog.placedOnce = true;
  return prog;
}

function planRepr(plan) { return plan.map(p => ({ kind: p.kind, id: p.word ? p.word.id : (p.sentence ? p.sentence.id : null) })); }

function runPureFunctionGoldens() {
  console.log("\n[2] defaultProg/normalizeProg/plan-builder goldens, seeded");
  REAL_PACKS.forEach(({ name, dir }) => {
    const { pack, words, sentences } = loadPack(dir);
    const golden = { pack: name, defaultProg: VC.defaultProg(pack), normalizeProgSamples: [], seeds: [] };
    // normalizeProg: additive-migration behaviour on a handful of shapes, incl. an
    // empty object, a partial object, and one with a `sets` key for an unknown level
    // (dropUnknownSets is exercised separately by engine_checks.js; normalizeProg
    // itself just needs to fill in missing fields without dropping known ones).
    const lv0 = VC.levelIds(pack)[0];
    [{}, { w: { [words[0].id]: { r: 2, w: 1, s: 1 } } }, { sets: { [lv0]: 1 }, sessions: 4, theme: "dark" }]
      .forEach(input => { golden.normalizeProgSamples.push({ input, output: VC.normalizeProg(input, pack) }); });
    [1, 2, 3].forEach(seed => {
      const fixture = buildFixtureProg(seed === 1 ? 0 : seed === 2 ? 1 : 2, pack, words, sentences);
      const learned = VC.learnedWords(words, pack, fixture);
      withSeededRandom(seed, () => {
        const seedGolden = {
          seed,
          fixtureProg: fixture,
          reviewPlan: planRepr(VC.buildReviewPlan(learned, fixture, pack, { rng: Math.random })),
          recallPlan: planRepr(VC.buildRecallPlan(learned, fixture, pack, 8)),
          sentenceKindSequence: Array.from({ length: 40 }, () => VC.sentenceKind(pack, Math.random)),
        };
        golden.seeds.push(seedGolden);
      });
    });
    handleGolden(`pure_${name}`, golden);
  });
  note('stagePath(pack, words, chars, prog) (HSK_MERGE.md §2.4) does not exist on this pre-merge HEAD — the nearest counterpart is app.html\'s pathStrip(), a DOM-closure (not a pure core.js function) that stagePath is meant to generalize. It is not separately golden-tested here; its rendered <div class="path"> markup is covered byte-for-byte as part of every Today-tab render captured in section [3].');
}

// ================================================================== [3] fake-DOM boot
// Ported from engine_checks.js check [23]'s fake DOM (id-registry + innerHTML regex
// scan), generalized to take any pack's WORDS/SENTENCES/LESSONS/PASSAGES rather than
// hard-coding the zh pack, and extended with app.html's own Today-step/tab-render
// closures (learnedWords, nextNewSet, availableSentences, itemFromPlan, todayStep,
// todayStepState) so a step's content can be captured without having to play an
// entire session through fake clicks.
function extractAttrs(tag) {
  const attrs = {}; const re = /([a-zA-Z_:][-a-zA-Z0-9_:.]*)(?:\s*=\s*"([^"]*)")?/g;
  let m; while ((m = re.exec(tag))) { if (m[1]) attrs[m[1]] = m[2] !== undefined ? m[2] : ""; }
  return attrs;
}
function makeFakeDom(appHtml) {
  const registry = new Map();
  const tabButtons = [];
  class El {
    constructor(tag, attrs) {
      this.tagName = (tag || "div").toUpperCase();
      this._attrs = Object.assign({}, attrs);
      this._classes = new Set((this._attrs.class || "").split(/\s+/).filter(Boolean));
      this._html = ""; this._text = "";
      this.style = { setProperty(k, v) { this[k] = v; } };
      this.hidden = false; this.disabled = false; this.value = "";
      this.onclick = null; this.oninput = null; this.onchange = null;
      this._listeners = {}; this._children = [];
      if (this._attrs.id) registry.set(this._attrs.id, this);
    }
    get id() { return this._attrs.id || ""; }
    set id(v) { this._attrs.id = v; registry.set(v, this); }
    get classList() {
      const s = this._classes;
      return { add: (...c) => c.forEach(x => s.add(x)), remove: (...c) => c.forEach(x => s.delete(x)),
        toggle: (c, f) => { if (f === undefined) { s.has(c) ? s.delete(c) : s.add(c); } else { f ? s.add(c) : s.delete(c); } },
        contains: c => s.has(c) };
    }
    get dataset() {
      const attrs = this._attrs; const toKebab = k => k.replace(/[A-Z]/g, m => "-" + m.toLowerCase());
      return new Proxy({}, {
        get(_, k) { return attrs["data-" + toKebab(String(k))]; },
        set(_, k, v) { attrs["data-" + toKebab(String(k))] = String(v); return true; },
      });
    }
    get children() { return this._children; }
    get innerHTML() { return this._html; }
    set innerHTML(h) { this._html = h; this._children = []; registerIdsFromHtml(h); }
    get textContent() { return this._text; }
    set textContent(t) { this._text = String(t); this._html = String(t); }
    setAttribute(k, v) { this._attrs[k] = String(v); if (k === "id") registry.set(v, this); }
    getAttribute(k) { return this._attrs[k]; }
    addEventListener(t, f) { (this._listeners[t] = this._listeners[t] || []).push(f); }
    removeEventListener() {}
    appendChild(c) { this._children.push(c); return c; }
    remove() {}
    focus() {}
    click() { if (this.onclick) this.onclick({}); (this._listeners.click || []).forEach(f => f({})); }
    closest() { return null; }
    querySelector() { return null; }
    querySelectorAll() { return []; }
  }
  function registerIdsFromHtml(html) {
    const re = /<([a-zA-Z0-9]+)((?:\s+[a-zA-Z_:][-a-zA-Z0-9_:.]*(?:\s*=\s*"[^"]*")?)*)\s*\/?>/g;
    let m;
    while ((m = re.exec(html))) { const attrs = extractAttrs(m[2]); if (attrs.id) new El(m[1], attrs); }
  }
  const tabsMatch = appHtml.match(/<nav[^>]*id="tabs"[^>]*>([\s\S]*?)<\/nav>/);
  const btnRe = /<button([^>]*)>/g;
  let bm; while ((bm = btnRe.exec(tabsMatch[1]))) { tabButtons.push(new El("button", extractAttrs(bm[1]))); }
  const bodySection = appHtml.slice(appHtml.indexOf("<body>"), appHtml.indexOf("<nav"));
  registerIdsFromHtml(bodySection);
  return {
    title: "", head: { appended: [], appendChild(c) { this.appended.push(c); return c; } }, body: new El("body", {}), documentElement: new El("html", {}),
    write() {}, createElement(tag) { return new El(tag, {}); },
    getElementById(id) { return registry.get(id) || null; },
    querySelector(sel) { return this.querySelectorAll(sel)[0] || null; },
    querySelectorAll(sel) {
      const m = sel.match(/^#tabs\s+button(?:\[data-t="([^"]+)"\])?$/);
      if (m) return m[1] ? tabButtons.filter(b => b.dataset.t === m[1]) : tabButtons.slice();
      return [];
    },
    addEventListener() {},
  };
}
const tick = () => new Promise(r => setTimeout(r, 0));
function bootAppSync(appHtml, appSrc, pack, words, sentences, lessons, passages, getVoicesResult) {
  const document = makeFakeDom(appHtml);
  const ss = { getVoices: () => getVoicesResult, onvoiceschanged: null };
  const window = {
    VocabCore: VC, speechSynthesis: ss, SpeechSynthesisUtterance: function () {},
    _l: {}, addEventListener(t, f) { (this._l[t] = this._l[t] || []).push(f); },
    fire(t) { (this._l[t] || []).forEach(f => f({})); },
  };
  const navigator = { userAgent: "FlagoffSnapshot/1.0" };
  const setItemCalls = [];
  const localStorage = { getItem() { return null; }, setItem(k, v) { setItemCalls.push([k, v]); } };
  const matchMedia = () => ({ matches: false });
  const requestAnimationFrame = fn => setTimeout(fn, 0);
  const fnBody = appSrc + `
return {
  getHtml: id => { const e = document.getElementById(id); return e ? e.innerHTML : null; },
  getText: id => { const e = document.getElementById(id); return e ? e.textContent : null; },
  clickTab: t => { document.querySelectorAll('#tabs button[data-t="' + t + '"]').forEach(b=>b.click()); },
  isTabHidden: t => { const b = document.querySelectorAll('#tabs button[data-t="' + t + '"]')[0]; return b ? !!b.hidden : true; },
  enterTodayStep: step => { todayStepState = { step }; todayStep(); },
  getProg: () => prog,
};`;
  const fn = new Function("document", "window", "navigator", "location", "localStorage", "matchMedia", "requestAnimationFrame", "PACK", "WORDS", "SENTENCES", "LESSONS", "PASSAGES", fnBody);
  const api = fn(document, window, navigator, undefined, localStorage, matchMedia, requestAnimationFrame, pack, words, sentences, lessons, passages);
  return { api, document, setItemCalls };
}
async function bootApp(appHtml, appSrc, pack, words, sentences, lessons, passages, getVoicesResult) {
  const boot = bootAppSync(appHtml, appSrc, pack, words, sentences, lessons, passages, getVoicesResult);
  await tick(); await tick();
  return boot;
}

const TODAY_STEP_NAMES = ["Review", "Learn", "Listen", "Recall", "Sentences"];

async function captureBootGolden(seed, pack, words, sentences, lessons, passages, appHtml, appSrc) {
  const fixtureLevel = seed === 1 ? 0 : seed === 2 ? 1 : 2;
  const fixture = buildFixtureProg(fixtureLevel, pack, words, sentences);
  const seedRaw = JSON.stringify(fixture);
  return withSeededRandomAsync(seed, async () => {
    const boot = await bootApp(appHtml, appSrc, pack, words, sentences, lessons, passages, [{ lang: "zh-CN", name: "x" }]);
    // Boot always starts from defaultProg (fake localStorage.getItem returns null);
    // overwrite prog in place with the seeded fixture, then re-render Today so the
    // fixture — not the boot default — drives every capture below.
    Object.assign(boot.api.getProg(), fixture);
    boot.api.clickTab("today");
    const out = { seed, pack: pack.key, seedProgRaw: seedRaw, tabs: {}, todaySteps: [] };
    ["today", "words", "test", "progress", "read"].forEach(t => {
      if (boot.api.isTabHidden(t) && t !== "today") { out.tabs[t] = null; return; }
      boot.api.clickTab(t);
      out.tabs[t] = boot.api.getHtml("panel");
    });
    boot.api.clickTab("today");
    TODAY_STEP_NAMES.forEach((label, i) => {
      boot.api.enterTodayStep(i);
      out.todaySteps.push({ step: i, label, html: boot.api.getHtml("panel") });
    });
    out.savedProgressStrings = boot.setItemCalls.map(([k, v]) => ({ key: k, value: v }));
    return out;
  });
}

async function runBootGoldens() {
  console.log("\n[3] fake-DOM boot goldens (Today/Words/Test/Progress/Read, 3 seeds x 4 packs)");
  const appHtml = fs.readFileSync(path.join(ROOT, "engine", "app.html"), "utf8");
  const scriptBlocks = [...appHtml.matchAll(/<script>([\s\S]*?)<\/script>/g)];
  if (scriptBlocks.length < 2) { check("app.html has the inline app script (2 plain <script> tags)", false); return; }
  const appSrc = scriptBlocks[scriptBlocks.length - 1][1];
  for (const { name, dir } of REAL_PACKS) {
    const { pack, words, sentences, lessons, passages } = loadPack(dir);
    for (const seed of [1, 2, 3]) {
      try {
        const golden = await captureBootGolden(seed, pack, words, sentences, lessons, passages, appHtml, appSrc);
        handleGolden(`boot_${name}_seed${seed}`, golden);
      } catch (e) {
        check(`boot golden ${name} seed ${seed} does not throw (got: ${e.stack})`, false);
      }
    }
  }
}

// ================================================================== main
(async function main() {
  runFlagOffPackChecks();
  runPureFunctionGoldens();
  await runBootGoldens();
  if (notCapturable.length) {
    console.log(`\n${notCapturable.length} item(s) not capturable (see NOTE lines above)`);
  }
  console.log(`\n${fails ? "FAILED" : "ALL PASSED"}: ${passes} passed, ${fails} failed (mode: ${MODE})`);
  process.exit(fails ? 1 : 0);
})();
