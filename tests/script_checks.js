// Node checks for the script primer's engine logic (docs/SCRIPT_PRIMER.md §6 checks 1-9,
// brief S1): stage insertion, the choice card, existing-learner normalize, distractor
// rules, Learn plans, the no-voice path, script units in Review, and the flag-off strip.
// Synthetic packs: tests/fixtures/script_packs.js (ko-like, fa-like, ja-like).
// Each section runs inside try/catch, so on a core.js without the primer every check
// reports FAIL instead of the file crashing.
// Run: node tests/script_checks.js
"use strict";
const fs = require("fs");
const path = require("path");
const util = require("util");

const ROOT = path.join(__dirname, "..");
const VC = require(path.join(ROOT, "engine", "core.js"));
const FX = require(path.join(__dirname, "fixtures", "script_packs.js"));

let fails = 0, passes = 0;
function check(name, cond, extra){
  if(cond){ passes++; console.log(`PASS  ${name}`); }
  else { fails++; console.log(`FAIL  ${name}`); if(extra !== undefined) console.log("    " + String(extra).slice(0, 400)); }
}
function section(title, fn){
  console.log(`\n${title}`);
  try{ fn(); }catch(e){ check(`${title}: runs without throwing (${String(e && e.message).slice(0, 160)})`, false); }
}
const eq = (a, b) => util.isDeepStrictEqual(a, b);
const clone = x => JSON.parse(JSON.stringify(x));
function mulberry32(seed){
  let a = seed >>> 0;
  return function(){ a |= 0; a = (a + 0x6D2B79F5) | 0; let t = Math.imul(a ^ (a >>> 15), 1 | a); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
}
function noScript(pack){ const p = Object.assign({}, pack); delete p.script; return p; }
const byUid = units => Object.fromEntries(units.map(u => [u.id, u]));
const glyph = u => VC.scriptGlyph(u);

// ------------------------------------------------------------ [1] stage path
section("[1] stagePath: script stages first; skipped equals the flag-off path; reversible", () => {
  const { pack, words, script } = FX.ko(); const units = script.units;
  const prog = VC.defaultProg(pack);
  const p0 = VC.stagePath(pack, words, [], prog, units);
  check("ko: first stage is the script stage", p0[0].kind === "script" && p0[0].key === "hangul" && p0[0].label === "한글", JSON.stringify(p0[0]));
  check("ko: script stage counts 20 units in 3 sets, not done", p0[0].nunits === 20 && p0[0].nsets === 3 && p0[0].recorded === 0 && p0[0].done === false && p0[0].frac === 0);
  check("ko: then the word levels, unchanged", eq(p0.slice(1), VC.stagePath(noScript(pack), words, [], VC.defaultProg(noScript(pack)))));
  check("ko: nextStage is the script stage", VC.nextStage(pack, words, [], prog, units).kind === "script");
  VC.markRec(prog.w, words[0].id, true, true); prog.sets.A1 = 1; VC.markScript(prog, "ko-a", true);
  const before = clone({ w: prog.w, sets: prog.sets, u: prog.script.u });
  VC.setScriptSkipped(prog, true);
  const offPath = VC.stagePath(noScript(pack), words, [], Object.assign({}, prog, { script: undefined }));
  check("skipped: path equals the flag-off path", eq(VC.stagePath(pack, words, [], prog, units), offPath));
  check("skipped: w, sets and script.u untouched", eq(before, clone({ w: prog.w, sets: prog.sets, u: prog.script.u })));
  check("skipped: nextStage is A1", VC.nextStage(pack, words, [], prog, units).lv === "A1");
  VC.setScriptSkipped(prog, false);
  const p2 = VC.stagePath(pack, words, [], prog, units);
  check("unskipped: the script stage is back first, recorded 1", p2[0].kind === "script" && p2[0].recorded === 1 && VC.nextStage(pack, words, [], prog, units).kind === "script");
  check("unskipped: w, sets and script.u still untouched", eq(before, clone({ w: prog.w, sets: prog.sets, u: prog.script.u })));
  prog.script.notice = true; VC.setScriptSkipped(prog, true);
  check("setScriptSkipped off keeps a pending notice", prog.script.notice === true);
  VC.setScriptSkipped(prog, false);
  check("setScriptSkipped on clears the notice (not only hides it)", prog.script.notice === false);
  prog.script.notice = true; VC.setScriptSkipped(prog, false, "hangul"); VC.setScriptSkipped(prog, true);
  check("turning a stage on clears the notice too", prog.script.notice === false);
  VC.setScriptSkipped(prog, false); prog.script.skip = {};
  // derived done: every unit recorded (a later miss never un-does it)
  units.forEach(u => VC.markScript(prog, u.id, true)); VC.markScript(prog, "ko-a", false);
  const p3 = VC.stagePath(pack, words, [], prog, units);
  check("done once every unit has a record, even after a miss", p3[0].done === true && p3[0].frac === 1 && VC.nextStage(pack, words, [], prog, units).lv === "A1");
  check("done is not stored", !("done" in prog.script) && Object.keys(prog.script).sort().join() === "choiceSeen,notice,skip,skipped,u,v");
  // ja: two stages, hira then kata, before A1
  const J = FX.ja(); const jp = VC.defaultProg(J.pack);
  const jpath = VC.stagePath(J.pack, J.words, [], jp, J.script.units);
  check("ja: hira then kata, both before A1", jpath[0].key === "hira" && jpath[1].key === "kata" && jpath[2].kind === "words" && jpath[2].lv === "A1"
    && jpath[0].nunits === 19 && jpath[1].nunits === 10, JSON.stringify(jpath.slice(0, 3).map(s => [s.kind, s.key || s.lv, s.nunits])));
  J.script.units.filter(u => u.st === "hira").forEach(u => VC.markScript(jp, u.id, true));
  check("ja: hira taught, next stage is kata", VC.nextStage(J.pack, J.words, [], jp, J.script.units).key === "kata");
  const snap = VC.todaySnapshot(J.pack, J.words, [], jp, J.script.units);
  // each ja stage skippable on its own
  const js = VC.defaultProg(J.pack);
  VC.setScriptSkipped(js, true, "hira");
  const jsp = VC.stagePath(J.pack, J.words, [], js, J.script.units);
  check("ja: hira alone off: kata then A1", jsp[0].key === "kata" && jsp[1].lv === "A1" && js.script.skipped === false);
  VC.setScriptSkipped(js, true, "kata");
  check("ja: both off: A1 first", VC.nextStage(J.pack, J.words, [], js, J.script.units).lv === "A1");
  VC.setScriptSkipped(js, false, "hira");
  check("ja: hira back on: hira first again", VC.nextStage(J.pack, J.words, [], js, J.script.units).key === "hira");
  VC.markScript(js, "ja-ka-a", true); VC.markScript(js, "ja-a", true);
  check("ja: an off stage's units leave Review", eq(VC.recordedScriptUnits(J.script.units, js, J.pack).map(u => u.id), ["ja-a"]));
  check("ja snapshot on kata: 2 sets, reviewSize 12", snap.stage.key === "kata" && snap.ssets.length === 2 && snap.ssets[0].index === 0 && snap.ssets[0].total === 2 && snap.reviewSize === VC.REVIEW_SIZE_SCRIPT && VC.REVIEW_SIZE_SCRIPT === 12);
  check("ja snapshot: ssets only kata units", snap.ssets.every(s => s.units.every(u => u.st === "kata")));
  check("nextScriptSets: skips taught sets, capped at n", (() => {
    const p = VC.defaultProg(pack); units.filter(u => u.set === 1).forEach(u => VC.markScript(p, u.id, true));
    const s = VC.nextScriptSets("hangul", units, pack, p, 5); return s.length === 2 && s[0].index === 1 && s[1].index === 2 && VC.nextScriptSets("hangul", units, pack, p).length === 2 && VC.nextScriptSets("hangul", units, pack, p, 1).length === 1;
  })());
});

// ------------------------------------------------------------ [2] choice card
section("[2] showScriptChoice", () => {
  const { pack, words, script } = FX.ko(); const units = script.units;
  const fresh = () => VC.defaultProg(pack);
  check("fresh progress: shown", VC.showScriptChoice(pack, units, fresh()) === true);
  check("fresh snapshot: choice is \"script\"", VC.todaySnapshot(pack, words, [], fresh(), units).choice === "script");
  const a = VC.answerScriptChoice(fresh(), true);
  check("after Learn: hidden, primer on", VC.showScriptChoice(pack, units, a) === false && a.script.choiceSeen === true && a.script.skipped === false);
  const b = VC.answerScriptChoice(fresh(), false);
  check("after Skip: hidden, primer off, next stage A1", VC.showScriptChoice(pack, units, b) === false && b.script.skipped === true && VC.nextStage(pack, words, [], b, units).lv === "A1");
  const c = fresh(); VC.markScript(c, "ko-i", false);
  check("any script record: hidden", VC.showScriptChoice(pack, units, c) === false);
  check("snapshot after answering: choice not \"script\"", VC.todaySnapshot(pack, words, [], a, units).choice === false);
  check("no pack.script: never shown", VC.showScriptChoice(noScript(pack), units, fresh()) === false);
  const placed = fresh(); placed.sets.A1 = 2; placed.placedOnce = true;
  check("placement past A1 does not answer it", VC.showScriptChoice(pack, units, placed) === true);
});

// ------------------------------------------------------------ [3] normalize
section("[3] normalizeProg: existing learners default skipped with a notice", () => {
  const { pack } = FX.ko();
  const stored = { v: 1, w: { kA1_01: { r: 2, w: 0, s: 2 } }, s: {}, sets: { A1: 1, A2: 0 }, sessions: 3 };
  const n = VC.normalizeProg(clone(stored), pack);
  check("stored w records, no script: skipped, choiceSeen, notice", n.script && n.script.skipped === true && n.script.choiceSeen === true && n.script.notice === true && eq(n.script.u, {}));
  check("scriptNotice true, dismiss clears it once", VC.scriptNotice(pack, n) === true && VC.scriptNotice(pack, VC.dismissScriptNotice(n)) === false && n.script.skipped === true);
  const f = VC.normalizeProg({}, pack);
  check("fresh (empty) progress: skipped false, no notice", f.script.skipped === false && f.script.choiceSeen === false && f.script.notice === false);
  check("defaultProg: skipped false", VC.defaultProg(pack).script.skipped === false);
  const kept = VC.normalizeProg({ w: { kA1_01: { r: 1, w: 0, s: 1 } }, script: { u: { "ko-a": { r: 1, w: 0, s: 1 } } } }, pack);
  check("stored script field kept as is (filled)", kept.script.skipped === false && kept.script.u["ko-a"].r === 1 && kept.script.v === 1);
  check("bootProg: existing learner boots skipped", VC.bootProg(JSON.stringify(stored), pack).prog.script.skipped === true);
  check("no pack.script: no script field", !("script" in VC.normalizeProg(clone(stored), noScript(pack))) && !("script" in VC.defaultProg(noScript(pack))));
  const lv = VC.levelIds(pack);
  check("validateProgShape accepts a script field", VC.validateProgShape({ script: { v: 1, u: { "ko-a": { r: 1, w: 0, s: 1 } }, skipped: true, choiceSeen: true, notice: false } }, lv).ok);
  check("validateProgShape rejects bad script shapes", ["x", { v: 0 }, { u: [] }, { u: { a: { r: "1" } } }, { skipped: "yes" }, { notice: 1 }, { skip: [] }, { skip: { hira: 1 } }]
    .every(sc => !VC.validateProgShape({ script: sc }, lv).ok));
});

// ------------------------------------------------------------ [4] no second right answer
section("[4] scriptOpts never offers a same-roman or same-say unit", () => {
  const F = FX.fa(), J = FX.ja(), K = FX.ko();
  const fu = byUid(F.script.units), ju = byUid(J.script.units), ku = byUid(K.script.units);
  // `bad` goes to the front of the unit's confuse list, so every bad unit sits in the first
  // tier and would be offered if scriptSecondRight did not exclude it (the checks bite).
  const runs = (u0, units, kind, bad) => {
    const u = Object.assign({}, u0, { confuse: [...bad, ...(u0.confuse || [])] });
    for(let s = 1; s <= 200; s++){ const o = VC.scriptOpts(u, units, units, kind, mulberry32(s)); if(o.some(v => bad.includes(v.id))) return false; }
    return true;
  };
  const offered = (u, units, kind, want, seeds) => { for(let s = 1; s <= seeds; s++) if(VC.scriptOpts(u, units, units, kind, mulberry32(s)).some(v => v.id === want)) return true; return false; };
  check("fa soundSym ت: never ط", runs(fu["fa-te"], F.script.units, "soundSym", ["fa-ta"]));
  check("fa soundSym ط: never ت", runs(fu["fa-ta"], F.script.units, "soundSym", ["fa-te"]));
  check("fa soundSym س: never ص or ث", runs(fu["fa-sin"], F.script.units, "soundSym", ["fa-sad", "fa-se"]));
  check("fa soundSym ث: never س or ص", runs(fu["fa-se"], F.script.units, "soundSym", ["fa-sin", "fa-sad"]));
  check("fa formMatch ز: never ذ", runs(fu["fa-ze"], F.script.units, "formMatch", ["fa-zal"]));
  check("ja soundSym じ: never ぢ, and ぢ never じ", runs(ju["ja-ji"], J.script.units, "soundSym", ["ja-dji"]) && runs(ju["ja-dji"], J.script.units, "soundSym", ["ja-ji"]));
  // A one-way alt is a contrast, not a second answer: ㄱ accepts "k" but ㅋ does not accept
  // "g", so ㄱ/ㅋ are drilled against each other. Mutual alts are homophones (fa غ/ق).
  check("ko symSound ㄱ (accepts g, k): ㅋ (k) among the distractors within 50 seeds", offered(ku["ko-g"], K.script.units, "symSound", "ko-k", 50));
  check("ko soundSym ㅋ: ㄱ (accepts k) among the distractors within 50 seeds", offered(ku["ko-k"], K.script.units, "soundSym", "ko-g", 50));
  check("scriptSecondRight: one-way alt is not a second answer (ru Е ye/e vs Э e)",
    !VC.scriptSecondRight({ id: "ye", t: "е", roman: "ye", alt: ["e"] }, { id: "e", t: "э", roman: "e" }, "symSound")
    && !VC.scriptSecondRight({ id: "e", t: "э", roman: "e" }, { id: "ye", t: "е", roman: "ye", alt: ["e"] }, "soundSym"));
  const gh = { id: "fa-ghein", st: "abjad", set: 2, group: "gh", t: "غ", name: "ghein", roman: "gh", alt: ["q"], joins: "dual", confuse: ["fa-qaf"] };
  const qf = { id: "fa-qaf", st: "abjad", set: 2, group: "gh", t: "ق", name: "qaf", roman: "q", alt: ["gh"], joins: "dual", confuse: ["fa-ghein"] };
  const FQ = [...F.script.units, gh, qf];
  check("fa mutual alts (غ gh/q, ق q/gh): never offered against each other", ["symSound", "soundSym", "formMatch"]
    .every(k => runs(gh, FQ, k, ["fa-qaf"]) && runs(qf, FQ, k, ["fa-ghein"])));
  let dup = 0;
  [F, J, K].forEach(P => P.script.units.forEach(u => ["symSound", "soundSym", "formMatch"].forEach(kind => {
    const o = VC.scriptOpts(u, P.script.units, P.script.units, kind, mulberry32(7));
    const rs = [u, ...o].map(v => VC.normKey(v.roman)), gs = [u, ...o].map(glyph);
    if(new Set(rs).size !== rs.length || new Set(gs).size !== gs.length) dup++;
  })));
  check("every unit, every symbol kind: options pairwise distinct in roman and glyph", dup === 0, dup);
  check("symSound options never include a silent unit", K.script.units.every(u => VC.scriptOpts(u, K.script.units, K.script.units, "symSound", mulberry32(3)).every(v => v.sound !== false)));
});

// ------------------------------------------------------------ [5] set-1 pool, stage mixing
section("[5] 4 options from set 1, padded from confuse; stages never mix", () => {
  const K = FX.ko(), J = FX.ja(), F = FX.fa();
  let short = 0;
  [K, J, F].forEach(P => P.script.units.forEach(u => {
    const o = VC.scriptOpts(u, [u], P.script.units, "soundSym", mulberry32(11));
    if(u.sound !== false && o.length !== 3) short++;
  }));
  check("pool of the unit alone: still 3 distractors (4 options) for every sounded unit", short === 0, short);
  const ka = byUid(K.script.units)["ko-a"];
  const first = [];
  for(let s = 1; s <= 50; s++) first.push(VC.scriptOpts(ka, [ka], K.script.units, "symSound", mulberry32(s))[0].id);
  check("padding takes the confuse list first (ㅏ -> ㅓ)", first.every(id => id === "ko-eo"), first.slice(0, 5));
  const set1 = VC.scriptSets("hangul", K.script.units)[0];
  const pool = VC.scriptPool(K.script.units, VC.defaultProg(K.pack), set1);
  check("scriptPool on fresh progress = the set", eq(pool.map(u => u.id), set1.map(u => u.id)));
  let fromPool = 0;
  set1.forEach(u => { const o = VC.scriptOpts(u, pool, K.script.units, "symSound", mulberry32(5)); if(o.length === 3 && o.every(v => v.set === 1)) fromPool++; });
  check("set 1 of 6 vowels: all 3 distractors come from the set", fromPool === set1.length);
  let mixed = 0;
  J.script.units.forEach(u => ["symSound", "soundSym"].forEach(kind => {
    for(let s = 1; s <= 20; s++) if(VC.scriptOpts(u, J.script.units, J.script.units, kind, mulberry32(s)).some(v => v.st !== u.st)) mixed++;
  }));
  check("hira and kata never mix in one item's options", mixed === 0, mixed);
  const words = J.words, byId = Object.fromEntries(words.map(w => [w.id, w]));
  let itemMixed = 0;
  J.script.units.forEach(u => ["symSound", "soundSym", "wordRead"].forEach(kind => {
    if(!VC.scriptKindFits(kind, u)) return;
    const it = VC.scriptItem(kind, u, { units: J.script.units, byId, tts: true, rng: mulberry32(2) });
    const sameSt = J.script.units.filter(v => v.st === u.st);
    const ok = kind === "symSound" ? it.options.every(o => sameSt.some(v => v.roman === o))
      : kind === "soundSym" ? it.options.every(o => sameSt.some(v => glyph(v) === o))
      : it.options.every(o => sameSt.some(v => (v.ex || []).some(e => e[1] === o)));
    if(!ok) itemMixed++;
  }));
  check("hira and kata never mix in items (symSound, soundSym, wordRead)", itemMixed === 0, itemMixed);
});

// ------------------------------------------------------------ [6] Learn plan
section("[6] learnScriptPlan covers every unit; silent units get no sound kinds", () => {
  const K = FX.ko(), J = FX.ja(), F = FX.fa();
  let uncovered = 0, silentBad = 0, composeBad = 0;
  [K, J, F].forEach(P => P.pack.script.stages.forEach(st => VC.scriptSets(st.key, P.script.units).forEach(set => {
    const plan = VC.learnScriptPlan(set, P.pack);
    set.forEach(u => {
      const mine = plan.filter(x => x.unit.id === u.id);
      if(!mine.length) uncovered++;
      if(u.sound === false && mine.some(x => ["symSound", "soundSym", "symType"].includes(x.kind))) silentBad++;
      if(mine.some(x => x.kind === "compose") && !(u.syll && u.syll.length)) composeBad++;
    });
  })));
  check("every unit of every set has at least one Learn item", uncovered === 0, uncovered);
  check("sound:false units get no symSound/soundSym/symType", silentBad === 0, silentBad);
  check("compose only for units with syll", composeBad === 0, composeBad);
  const u = byUid(K.script.units);
  const set2 = VC.scriptSets("hangul", K.script.units)[1];
  const plan2 = VC.learnScriptPlan(set2, K.pack);
  check("ko ㅇ (silent) gets wordRead", eq(plan2.filter(x => x.unit.id === "ko-ng").map(x => x.kind), ["wordRead"]));
  check("ko ㄴ gets symSound + compose", eq(plan2.filter(x => x.unit.id === "ko-n").map(x => x.kind), ["symSound", "compose"]));
  const set1 = VC.scriptSets("hangul", K.script.units)[0];
  check("ko set 1 (no syll): symSound only", VC.learnScriptPlan(set1, K.pack).every(x => x.kind === "symSound") && VC.learnScriptPlan(set1, K.pack).length === 6);
  const jsmall = VC.learnScriptPlan([byUid(J.script.units)["ja-tsu-small"]], J.pack);
  check("ja っ (silent) gets wordRead only", eq(jsmall.map(x => x.kind), ["wordRead"]));
  check("no pack.script: empty plan", VC.learnScriptPlan(set1, noScript(K.pack)).length === 0);
  void u;
});

// ------------------------------------------------------------ [7] no voice
section("[7] tts false: soundSym shows the roman; wordHear becomes wordRead", () => {
  const F = FX.fa(), K = FX.ko();
  const fById = Object.fromEntries(F.words.map(w => [w.id, w])), kById = Object.fromEntries(K.words.map(w => [w.id, w]));
  const fte = byUid(F.script.units)["fa-te"];
  const it = VC.scriptItem("soundSym", fte, { units: F.script.units, byId: fById, tts: false, rng: mulberry32(1) });
  check("fa soundSym (no voice): show is the roman, no audio", it.show === "t" && it.audio === null && it.say === null && it.answer === "ت" && it.options.length === 4 && it.options.includes("ت"));
  const wh = VC.scriptItem("wordHear", fte, { units: F.script.units, byId: fById, tts: false, rng: mulberry32(1) });
  check("fa wordHear (no voice) is a wordRead item", wh.kind === "wordRead" && wh.show === "تب" && wh.answer === "tab" && wh.audio === null);
  const fcfg = VC.scriptConfig(F.pack);
  check("pack tts false: no wordHear is ever picked", fcfg.tts === false && F.script.units.every(u => { for(let s = 1; s <= 30; s++){ if(VC.pickScriptKind(fcfg.reviewKinds, u, fcfg, mulberry32(s)) === "wordHear") return false; } return true; }));
  const kg = byUid(K.script.units)["ko-g"];
  const kOff = VC.scriptItem("soundSym", kg, { units: K.script.units, byId: kById, tts: false, rng: mulberry32(4) });
  check("ko soundSym with voices stubbed out: roman text", kOff.show === "g" && kOff.audio === null);
  const kOn = VC.scriptItem("soundSym", kg, { units: K.script.units, byId: kById, tts: true, rng: mulberry32(4) });
  check("ko soundSym with a voice: sound before, no text", kOn.show === null && kOn.audio === "before" && kOn.say === "가");
  const withClip = Object.assign({}, fte, { audio: "https://example.invalid/te.mp3" });
  const clip = VC.scriptItem("soundSym", withClip, { units: F.script.units, byId: fById, tts: false, rng: mulberry32(1) });
  check("a recorded audio URL plays even with no voice", clip.show === null && clip.audio === "before" && clip.audioUrl === withClip.audio && clip.say === null);
  const kwh = VC.scriptItem("wordHear", byUid(K.script.units)["ko-n"], { units: K.script.units, byId: kById, tts: false, rng: mulberry32(1) });
  check("ko wordHear with no voice: wordRead", kwh.kind === "wordRead");
});

// ------------------------------------------------------------ [8] Review
section("[8] Review: 12 script items with no learned words; none when skipped", () => {
  const { pack, words, script } = FX.ko(); const units = script.units;
  const prog = VC.defaultProg(pack); VC.answerScriptChoice(prog, true);
  units.filter(u => u.set <= 2).forEach((u, i) => VC.markScript(prog, u.id, i % 3 !== 0));
  const snap = VC.todaySnapshot(pack, words, [], prog, units);
  check("snapshot: script stage next, reviewSize 12, set 3 to learn", snap.stage.kind === "script" && snap.reviewSize === 12 && snap.ssets.length === 1 && snap.ssets[0].index === 2);
  const plan = VC.buildReviewPlan([], prog, pack, { script: units, size: snap.reviewSize, rng: mulberry32(9) });
  check("12 items, all script units with a script kind", plan.length === 12 && plan.every(x => x.unit && VC.SCRIPT_KINDS.includes(x.kind) && x.unit.st === "hangul"), JSON.stringify(plan.map(x => x.kind)));
  check("12 distinct recorded units", new Set(plan.map(x => x.unit.id)).size === 12 && plan.every(x => prog.script.u[x.unit.id]));
  check("each item's kind fits its unit (ㅇ never symSound)", plan.every(x => VC.scriptKindFits(x.kind, x.unit)));
  check("todayGates: recorded script units open Review with 0 words", VC.todayGates(0, true, 0, 14).review === true && VC.todayGates(0, true, 0).review === false && VC.todayGates(0, true, 0, 0).review === false);
  const items = plan.map(x => VC.scriptItem(x.kind, x.unit, { units, pool: VC.scriptPool(units, prog, []), words, tts: true, rng: mulberry32(3) }));
  check("every Review item builds: answer among options", items.every(it => it.options === null || it.options.includes(it.answer)));
  VC.setScriptSkipped(prog, true);
  check("skipped: no script items, empty plan with no words", VC.buildReviewPlan([], prog, pack, { script: units, size: 12, rng: mulberry32(9) }).length === 0);
  check("skipped: scriptTestPlan empty", VC.scriptTestPlan(units, prog, pack, 20, mulberry32(1)).length === 0);
  VC.setScriptSkipped(prog, false);
  const learned = words.filter(w => w.lv === "A1").slice(0, 8);
  learned.forEach(w => VC.markRec(prog.w, w.id, true, true));
  const mix = VC.buildReviewPlan(learned, prog, pack, { script: units, size: 15, rng: mulberry32(9) });
  check("with learned words: one unified plan of words and script units", mix.length === 15 && mix.some(x => x.word) && mix.some(x => x.unit));
  const tp = VC.scriptTestPlan(units, prog, pack, 20, mulberry32(1));
  check("scriptTestPlan: recorded units only, fitting kinds", tp.length === 14 && tp.every(x => prog.script.u[x.unit.id] && VC.scriptKindFits(x.kind, x.unit)));
});

// ------------------------------------------------------------ [9] flag-off
section("[9] flag-off: pack.script stripped by the harness; outputs unchanged without it", () => {
  // The harness is loaded in a child process: a harness without the module export runs
  // (and exits) on require, which must fail this check, not end this file.
  const cp = require("child_process");
  const r = cp.spawnSync(process.execPath, ["-e", `const m = require(${JSON.stringify(path.join(__dirname, "flagoff_snapshot.js"))});
    process.stdout.write(JSON.stringify({ ok: typeof m.stripFlagOnFields === "function", src: m.stripFlagOnFields ? String(m.stripFlagOnFields) : "", packs: m.FLAGOFF_PACKS || [] }));`], { encoding: "utf8" });
  let mod = null; try{ mod = JSON.parse(r.stdout); }catch(e){ mod = null; }
  check("flagoff_snapshot.js exports stripFlagOnFields when required", !!(mod && mod.ok), (r.stdout || "") + (r.stderr || ""));
  if(!(mod && mod.ok)) return;
  const stripFlagOnFields = new Function(`return (${mod.src});`)(); const FLAGOFF_PACKS = mod.packs;
  const synth = FX.ko().pack.script;
  const sunits = FX.ko().script.units;
  let checked = 0;
  FLAGOFF_PACKS.forEach(({ name, dir }) => {
    const pj = path.join(dir, "pack.json");
    if(!fs.existsSync(pj)){ console.log(`NOTE  ${name}: ${dir} missing, skipped`); return; }
    const pack = JSON.parse(fs.readFileSync(pj, "utf8"));
    const words = JSON.parse(fs.readFileSync(path.join(dir, "words.json"), "utf8"));
    const withScript = Object.assign({}, pack, { script: synth });
    check(`${name}: strip removes pack.script (same flag-off view as without it)`, eq(stripFlagOnFields(withScript, null, null).pack, stripFlagOnFields(pack, null, null).pack));
    const base = noScript(pack);
    const prog = VC.defaultProg(base);
    const learned = words.slice(0, 30); learned.forEach((w, i) => VC.markRec(prog.w, w.id, i % 4 !== 0, true));
    const same = eq(VC.defaultProg(base), VC.defaultProg(noScript(base)))
      && !("script" in VC.defaultProg(base)) && !("script" in VC.normalizeProg(clone(prog), base))
      && eq(VC.stagePath(base, words, [], prog, sunits), VC.stagePath(base, words, [], prog))
      && eq(VC.buildReviewPlan(learned, prog, base, { script: sunits, rng: mulberry32(5) }), VC.buildReviewPlan(learned, prog, base, { rng: mulberry32(5) }))
      && eq(VC.todaySnapshot(base, words, [], prog, sunits), VC.todaySnapshot(base, words, [], prog))
      && !("ssets" in VC.todaySnapshot(base, words, [], prog, sunits));
    check(`${name}: without pack.script, script units change no output`, same);
    checked++;
  });
  check("at least zh was checked", checked >= 1);
});

// ------------------------------------------------------------ items: every kind builds
section("[items] scriptItem: every fitting kind, every fixture unit", () => {
  let bad = [], built = 0;
  [FX.ko(), FX.fa(), FX.ja()].forEach(P => {
    const byId = Object.fromEntries(P.words.map(w => [w.id, w]));
    P.script.units.forEach(u => VC.SCRIPT_KINDS.forEach(kind => {
      if(!VC.scriptKindFits(kind, u)) return;
      for(const tts of [true, false]){
        const it = VC.scriptItem(kind, u, { units: P.script.units, byId, tts, rng: mulberry32(built + 1) }); built++;
        const why = it.key !== "x:" + u.id ? "key" : it.options === null ? (kind === "symType" && it.accept.includes(u.roman) ? null : "accept")
          : !it.options.includes(it.answer) ? "answer not in options" : new Set(it.options).size !== it.options.length ? "duplicate options"
          : it.options.length < 2 ? "too few options" : (it.show != null && it.show === it.answer) ? "stimulus shows the answer" : null;
        if(why) bad.push(`${u.id}/${kind}/${tts}: ${why}`);
      }
    }));
  });
  check(`every item well-formed (${built} built)`, bad.length === 0, bad.slice(0, 5).join("; "));
  const K = FX.ko(), kById = Object.fromEntries(K.words.map(w => [w.id, w]));
  const comp = VC.scriptItem("compose", byUid(K.script.units)["ko-n"], { units: K.script.units, byId: kById, rng: mulberry32(1) });
  check("compose: parts joined with +, answer the syllable", /^ㄴ \+ ㅏ$|^ㄴ \+ ㅓ$/.test(comp.show) && ["나", "너"].includes(comp.answer) && comp.options.length === 4);
  const F = FX.fa(), fById = Object.fromEntries(F.words.map(w => [w.id, w]));
  const fm = VC.scriptItem("formMatch", byUid(F.script.units)["fa-be"], { units: F.script.units, byId: fById, tts: false, rng: mulberry32(1) });
  check("formMatch: a joined form with ZWJ, answer the isolated letter", fm.show.includes("‍") && fm.answer === "ب" && ["init", "medi", "fina"].includes(fm.form) && fm.audio === null);
  const right = VC.scriptJoinedForms(byUid(F.script.units)["fa-re"]);
  check("right joiner: final form only", right.length === 1 && right[0].form === "fina");
  const ff = VC.scriptItem("formFind", byUid(F.script.units)["fa-pe"], { units: F.script.units, byId: fById, tts: false, rng: mulberry32(1) });
  check("formFind: answer contains the letter, distractors do not", ff.answer.includes("پ") && ff.options.filter(o => o !== ff.answer).every(o => !o.includes("پ")) && ff.hint === "pe");
  // "Contains" is the validator's glyph_in fold: آ contains ا, a batchim (final U+11A8)
  // is the letter ㄱ, case folds. A word that holds the letter only in a folded form is
  // never a formFind distractor.
  check("scriptGlyphIn: آ has ا, 책 has ㄱ (final), Москва has м; ب not in آب's madda", VC.scriptGlyphIn("ا", "آب") && VC.scriptGlyphIn("ㄱ", "책")
    && VC.scriptGlyphIn("ㄱ", "\u11A8") && VC.scriptGlyphIn("м", "Москва") && !VC.scriptGlyphIn("پ", "آب") && VC.scriptGlyphIn("きゃ", "きゃく") && !VC.scriptGlyphIn("きゃ", "きやく"));
  {
    const madde = { id: "fa-alef-madde", st: "abjad", set: 1, group: "alef", t: "آ", name: "alef madde", roman: "â", joins: "right", ex: [[F.words.find(w => w.w === "آب").id, "âb"]] };
    const us = [...F.script.units, madde];
    let leak = 0;
    for(let sd = 1; sd <= 50; sd++){
      const it = VC.scriptItem("formFind", byUid(us)["fa-alef"], { units: us, byId: fById, tts: false, rng: mulberry32(sd) });
      if(it.options.some(o => o !== it.answer && o === "آب")) leak++;
    }
    check("formFind ا: آب (ا + madda) never a distractor (50 seeds)", leak === 0, leak);
    const kw = [...K.words, { id: "kx_chaek", lv: "A1", w: "책", en: ["book"] }, { id: "kx_mom", lv: "A1", w: "몸", en: ["body"] }];
    const kb = Object.fromEntries(kw.map(w => [w.id, w]));
    const fin = { id: "ko-g-fin", st: K.script.units[0].st, set: 2, group: "final", t: "ㄱ", roman: "k", ex: [["kx_chaek", "chaek"]] };
    const nx = { id: "ko-m-x", st: K.script.units[0].st, set: 2, group: "final", t: "ㅁ", roman: "m", ex: [["kx_mom", "mom"]] };
    const kus = [...K.script.units, fin, nx];
    let kleak = 0;
    for(let sd = 1; sd <= 50; sd++){
      const it = VC.scriptItem("formFind", byUid(kus)["ko-g"], { units: kus, byId: kb, tts: false, rng: mulberry32(sd) });
      if(it.options.some(o => o !== it.answer && o === "책")) kleak++;
    }
    check("formFind ㄱ: 책 (batchim ㄱ) never a distractor (50 seeds)", kleak === 0, kleak);
  }
  const wr = VC.scriptItem("wordRead", byUid(K.script.units)["ko-b"], { units: K.script.units, byId: kById, rng: mulberry32(1) });
  check("wordRead: no gloss in stimulus, gloss in reveal", wr.show === "바다" && wr.answer === "bada" && wr.reveal.word.en === "sea" && wr.audio === "after");
  let threw = false; try{ VC.scriptItem("nope", byUid(K.script.units)["ko-a"], { units: K.script.units }); }catch(e){ threw = true; }
  check("unknown kind throws", threw);
  const cfg = VC.scriptConfig(K.pack);
  check("scriptConfig: defaults and known kinds only", cfg.setsPerSession === 2 && cfg.mastered === 3 && cfg.tts === true
    && eq(VC.scriptConfig({ script: { stages: [{ key: "x" }], learnKinds: ["bogus"] } }).learnKinds, ["symSound", "soundSym"]) && VC.scriptConfig({}) === null);
  check("scriptMastered: streak >= mastered", VC.scriptMastered({ r: 3, w: 0, s: 3 }, K.pack) && !VC.scriptMastered({ r: 2, w: 0, s: 2 }, K.pack));
});

section("[min] an option kind needs 4 options or it does not fit; compose pads set, stage, then same-script stages", () => {
  // Synthetic: hiragana stage with yōon syllables in sets 1-2; a katakana stage whose only
  // compose unit is one syllable (ニュ); a stage of two symbols with no confuse; a second
  // Hangul stage whose one compose unit can only pad from the first Hangul stage.
  const U = (id, st, set, t, roman, extra) => Object.assign({ id, st, set, group: "g", t, roman, say: t }, extra);
  const Y = (t, parts, roman) => [{ t, parts, roman }];
  const units = [
    U("xx-ki", "hira", 1, "き", "ki", { syll: Y("きゃ", ["き","ゃ"], "kya") }), U("xx-kyu", "hira", 1, "ゅ", "yu", { syll: Y("きゅ", ["き","ゅ"], "kyu") }),
    U("xx-shi", "hira", 2, "し", "shi", { syll: Y("しゃ", ["し","ゃ"], "sha") }), U("xx-chi", "hira", 2, "ち", "chi", { syll: Y("ちゃ", ["ち","ゃ"], "cha") }),
    U("xx-ni", "hira", 2, "に", "ni", { syll: Y("にゃ", ["に","ゃ"], "nya") }),
    U("xx-kni", "kata", 1, "ニ", "ni", { syll: Y("ニュ", ["ニ","ュ"], "nyu") }), U("xx-kka", "kata", 1, "カ", "ka"), U("xx-kki", "kata", 1, "キ", "ki"), U("xx-kku", "kata", 1, "ク", "ku"),
    U("xx-p1", "pair", 1, "ㅂ", "b"), U("xx-p2", "pair", 1, "ㅍ", "p"),
    U("xx-ga", "han1", 1, "ㄱ", "g", { syll: Y("가", ["ㄱ","ㅏ"], "ga") }), U("xx-na", "han1", 1, "ㄴ", "n", { syll: Y("나", ["ㄴ","ㅏ"], "na") }),
    U("xx-da", "han1", 1, "ㄷ", "d", { syll: Y("다", ["ㄷ","ㅏ"], "da") }),
    U("xx-ma", "han2", 1, "ㅁ", "m", { syll: Y("마", ["ㅁ","ㅏ"], "ma") }),
  ];
  const pack = { key: "synthmin", levels: [{ id: "A1" }], script: { stages: ["hira","kata","pair","han1","han2"].map(key => ({ key, label: key })),
    learnKinds: ["compose","symSound"], reviewKinds: ["compose","symSound"], testKinds: { compose: 90, symSound: 10 } } };
  const cfg = VC.scriptConfig(pack), ctx = { units, words: [] }, by = byUid(units);
  check("katakana ニュ: compose has the right shape (structure only, no ctx)", VC.scriptKindFits("compose", by["xx-kni"]) && VC.scriptKindShape("compose", by["xx-kni"]));
  const lone = VC.scriptItem("compose", by["xx-kni"], { units, rng: mulberry32(1) });
  check(`... but only ${lone.options.length} option exists: hiragana syllables never pad a katakana item`, lone.options.length === 1 && lone.options[0] === "ニュ");
  check("with ctx: compose does not fit ニュ", !VC.scriptKindFits("compose", by["xx-kni"], ctx) && VC.scriptKindFor("compose", by["xx-kni"], cfg, ctx) === null);
  let picked = new Set(); for(let i = 0; i < 40; i++) picked.add(VC.pickScriptKind(cfg.reviewKinds, by["xx-kni"], cfg, mulberry32(i), ctx));
  check(`pickScriptKind falls to the next kind (${[...picked]})`, eq([...picked], ["symSound"]));
  const lp = VC.learnScriptPlan([by["xx-kni"]], pack, ctx);
  check("learnScriptPlan with ctx: no compose for ニュ", lp.length === 1 && lp[0].kind === "symSound");
  const tp = VC.scriptTestPlan(units, { script: { u: Object.fromEntries(units.map(u => [u.id, { r: 1, w: 1, s: 0 }])) } }, pack, 20, mulberry32(3));
  check("scriptTestPlan counts options from its own units (no ctx): never compose for ニュ, never a kind for the pair stage's letters", tp.every(x => !(x.unit.id === "xx-kni" && x.kind === "compose")) && !tp.some(x => x.unit.st === "pair"));
  const prog = { w: {}, script: { u: Object.fromEntries(units.map(u => [u.id, { r: 1, w: 1, s: 0 }])) } };
  let rvBad = 0; for(let i = 0; i < 20; i++) VC.buildReviewPlan([], prog, pack, { size: 12, script: units, rng: mulberry32(i) }).forEach(x => { if(x.unit.id === "xx-kni" && x.kind === "compose") rvBad++; });
  check("buildReviewPlan (units from opts.script): never compose for ニュ", rvBad === 0);
  check("symSound/soundSym with only 2 symbols in a stage: do not fit with ctx", !VC.scriptKindFits("symSound", by["xx-p1"], ctx) && !VC.scriptKindFits("soundSym", by["xx-p1"], ctx) && VC.scriptKindFits("symSound", by["xx-p1"]));
  let setFirst = true, famOk = true, n4 = true;
  for(let i = 0; i < 30; i++){
    const it = VC.scriptItem("compose", by["xx-ki"], { units, pool: [by["xx-ki"]], rng: mulberry32(i) });
    if(it.answer === "きゃ" && !it.options.includes("きゅ")) setFirst = false;
    if(it.options.some(o => VC.scriptFamily(o) !== "Hiragana")) famOk = false;
    if(it.options.length !== 4) n4 = false;
  }
  check("hiragana きゃ: same-set きゅ always offered first, then same-stage syllables; 4 options, all hiragana", setFirst && famOk && n4 && VC.scriptKindFits("compose", by["xx-ki"], ctx));
  const m = VC.scriptItem("compose", by["xx-ma"], { units, rng: mulberry32(2) });
  check(`a stage's lone syllable pads from another stage in the same script (마 with ${m.options.join(" ")})`, m.options.length === 4 && ["가","나","다"].every(x => m.options.includes(x)) && VC.scriptKindFits("compose", by["xx-ma"], ctx));
  // Every fixture: every kind that fits with ctx builds 4 distinct options under any rng.
  const bad = [];
  ["ko","fa","ja"].forEach(k => {
    const fx = FX[k](); const c2 = { units: fx.script.units, words: fx.words, tts: VC.scriptConfig(fx.pack).tts };
    fx.script.units.forEach(u => VC.SCRIPT_KINDS.forEach(kind => {
      if(kind === "symType" || !VC.scriptKindFits(kind, u, c2)) return;
      for(let i = 0; i < 5; i++){
        const it = VC.scriptItem(kind, u, Object.assign({ rng: mulberry32(i) }, c2));
        if(it.options.length < 4 || new Set(it.options).size !== it.options.length) bad.push(`${u.id}/${kind}: ${it.options}`);
      }
    }));
  });
  check(`fixtures: every kind that fits with ctx gets 4 distinct options (${bad.length} bad)`, bad.length === 0, bad.slice(0, 4).join("; "));
});

console.log(`\n${fails ? "FAILED" : "ALL PASSED"}: ${passes} passed, ${fails} failed`);
process.exit(fails ? 1 : 0);
