// Node checks for the characters stage in engine/core.js (docs/HSK_MERGE.md §2-3).
// hsk tests/pinyin_checks.js checks 20-32 ported onto two synthetic packs (a zh-like and
// a ja-like pack, tests/fixtures/chars_packs.js), plus the flag-off proof that the plan
// builders and progress functions match the pre-characters engine exactly.
// Run: node tests/characters_checks.js     (no dependencies; needs git for [33])
"use strict";
const fs = require("fs");
const path = require("path");
const os = require("os");
const cp = require("child_process");
const util = require("util");

const ROOT = path.join(__dirname, "..");
const VC = require(path.join(ROOT, "engine", "core.js"));
const { zhLike, jaLike } = require(path.join(__dirname, "fixtures", "chars_packs.js"));
// The engine before the characters stage (main at the design commit). [33] loads its
// core.js from git and compares outputs.
const BASE_REV = process.env.CHARS_BASE_REV || "ee67120";

let fails = 0, passes = 0;
function check(name, cond){
  if(cond){ passes++; console.log(`PASS  ${name}`); }
  else { fails++; console.log(`FAIL  ${name}`); }
}
function mulberry32(seed){
  let a = seed >>> 0;
  return function(){ a = (a + 0x6D2B79F5) >>> 0; let t = a; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
}
const clone = x => JSON.parse(JSON.stringify(x));
const byIdOf = words => Object.fromEntries(words.map(w => [w.id, w]));
const rec = (s, w) => ({ r: s + (w||0), w: w || 0, s });
const stripChars = pack => { const p = Object.assign({}, pack); delete p.characters; return p; };
// Runs fn with Math.random replaced by a seeded generator (for code that doesn't take rng).
function withSeed(seed, fn){
  const orig = Math.random; Math.random = mulberry32(seed);
  try{ return fn(); } finally { Math.random = orig; }
}

// Expected path labels per fixture: default order and deferred order.
const LBL = st => st ? (st.kind === "words" ? st.lv : `${st.label}[${st.key}]`) : "null";
const EXPECT_PATH = {
  "zh-like": { def: "1 2 3 字[1+2+3] 4 字4[4]", defer: "1 2 3 4 字[1+2+3+4]" },
  "ja-like": { def: "A1 A2 漢字[A1+A2] B1 漢字B1[B1] B2", defer: "A1 A2 B1 漢字[A1+A2+B1] B2" },
};

function suite(F){
  const { pack, words, units } = F;
  const byId = byIdOf(words);
  const cfg = VC.charsConfig(pack);
  const ids = VC.levelIds(pack), idx = VC.levelIndexMap(pack);
  const byLv = VC.wordsByLevel(words, pack);
  const N = {}; ids.forEach(lv => { N[lv] = VC.nSets(byLv[lv], VC.setSizeOf(pack)); });
  const full = upTo => { const s = {}; ids.forEach((lv, i) => { s[lv] = i <= upTo ? N[lv] : 0; }); return s; };
  const i1 = idx[cfg.stages[0].after], i2 = idx[cfg.stages[cfg.stages.length-1].after];
  const stageLv = cfg.stages.map(st => st.levels);
  const recAll = levels => { const c = {}; units.filter(u => levels.includes(u.lv)).forEach(u => { c[u.id] = rec(1); }); return c; };
  const P = (sets, c, extra) => VC.normalizeProg({ sets, chars: Object.assign({ c: c || {} }, extra || {}) }, pack);
  const tag = s => `${F.name}: ${s}`;
  console.log(`\n================ ${F.name}: ${words.length} words, ${units.length} units, levels ${ids.join(",")}, sets ${JSON.stringify(N)}`);

  // ------------------------------------------------------------ [20] progress migration
  (function(){
    const u0 = units[0].id, u1 = units[1].id;
    const pre = { v:1, w:{ [words[0].id]: {r:3,w:1,s:1,prov:1}, [words[1].id]: {r:2,w:0,s:2,d:1} }, s:{}, sets: full(0), lessons:{a:1}, sessions:4, theme:"dark", showPron:false, placedOnce:true };
    const partial = Object.assign(clone(pre), { chars: { c: { [u0]: {r:4,w:1,s:6} } } });
    const fullC = Object.assign(clone(pre), { chars: { v:1, c: { [u0]: {r:4,w:1,s:6} }, defer:false, choiceSeen:false, mix:false } });
    const flags = Object.assign(clone(pre), { chars: { v:1, c: { [u1]: {r:1,w:0,s:1} }, defer:true, choiceSeen:true, mix:true } });
    const future = Object.assign(clone(pre), { chars: { v:2, c:{}, extra:"kept" } });
    const DEF = VC.defaultCharsProg();
    const allowed = new Set([...Object.keys(VC.defaultProg(pack)), "chars"]);
    let bad = 0;
    [["pre-characters", pre], ["chars.c only", partial], ["full chars, mix off", fullC], ["defer + choiceSeen", flags], ["future chars.v + unknown key", future]].forEach(([label, orig]) => {
      const val = VC.validateProgShape(clone(orig), ids);
      const m = VC.normalizeProg(val.data, pack);
      const preserved = Object.keys(orig).filter(k => k !== "v" && k !== "chars").every(k => util.isDeepStrictEqual(m[k], orig[k]));
      const oc = orig.chars || {};
      const charsOk = typeof m.chars === "object" && Object.keys(oc).every(k => util.isDeepStrictEqual(m.chars[k], oc[k]))
        && Object.keys(DEF).every(k => k in oc || util.isDeepStrictEqual(m.chars[k], DEF[k]))
        && Object.keys(m.chars).every(k => k in oc || k in DEF);
      const onlyAllowed = Object.keys(m).filter(k => !(k in orig)).every(k => allowed.has(k));
      const rt = VC.validateProgShape(clone(m), ids);
      const idem = rt.ok && util.isDeepStrictEqual(VC.normalizeProg(rt.data, pack), m);
      const ok = val.ok && m.v === 1 && preserved && charsOk && onlyAllowed && idem;
      if(!ok){ bad++; console.log(`    BAD ${label}: validated=${val.ok} v=${m.v} preserved=${preserved} chars=${charsOk} onlyAllowed=${onlyAllowed} roundTrip=${idem}`); }
    });
    const bare = stripChars(pack);
    const noChars = VC.normalizeProg(clone(pre), bare);
    const carried = VC.normalizeProg(clone(fullC), bare);
    const flagOff = !("chars" in noChars) && !("chars" in VC.defaultProg(bare)) && util.isDeepStrictEqual(carried.chars, fullC.chars);
    const fresh = VC.defaultProg(pack);
    console.log(`\n[20] ${F.name}: 5 progress shapes, ${5-bad} clean; flag-off pack adds no chars and carries an existing one untouched: ${flagOff}`);
    check(tag("normalizeProg keeps every field (pre-characters, partial, full, flags, future chars.v), adds only chars defaults, v stays 1, round-trips"), bad === 0);
    check(tag("defaultProg has chars {v:1,c:{},defer:false,choiceSeen:false,mix:true}; a pack without characters gets no chars key"), flagOff && util.isDeepStrictEqual(fresh.chars, {v:1,c:{},defer:false,choiceSeen:false,mix:true}) && fresh.v === 1);
  })();

  // ------------------------------------------------------------ [21] chars validation
  (function(){
    const good = [ {chars:{}}, {chars:{c:{}}}, {chars:{c:{c0001:{r:1,w:0,s:1}}}}, {chars:{mix:true}}, {chars:{mix:false}}, {chars:{c:{c0001:{}}}}, {chars:{v:1}}, {chars:{v:3}} ];
    const badShapes = [ {chars:null}, {chars:[]}, {chars:"x"}, {chars:{c:null}}, {chars:{c:[]}}, {chars:{c:"x"}}, {chars:{c:{c0001:null}}}, {chars:{c:{c0001:[]}}},
      {chars:{c:{c0001:{s:"3"}}}}, {chars:{mix:1}}, {chars:{mix:"true"}}, {chars:{mix:null}}, {chars:{v:0}}, {chars:{v:"1"}}, {chars:{v:1.5}} ];
    const g = good.filter(d => VC.validateProgShape(d, ids).ok).length, b = badShapes.filter(d => !VC.validateProgShape(d, ids).ok).length;
    const boot = VC.bootProg(JSON.stringify({ sets:{}, chars:{ c:{ x:{ s:"1" } } } }), pack);
    console.log(`\n[21] ${F.name}: ${g}/${good.length} good accepted, ${b}/${badShapes.length} bad rejected; malformed chars at boot is backed up: ${boot.backupRaw !== null}`);
    check(tag("validateProgShape accepts well-formed chars / c / mix / v"), g === good.length);
    check(tag("validateProgShape rejects malformed chars / c / mix / v, and boot backs such a record up"), b === badShapes.length && boot.backupRaw !== null);
  })();

  // ------------------------------------------------------------ [22] character options
  (function(){
    const uIds = new Set(units.map(u => u.id));
    const gk = u => VC.normKey(VC.unitGloss(u, byId)), rk = u => VC.normKey(VC.unitReading(u, byId));
    let bad = 0, total = 0, sameLv = 0; const ex = [];
    for(let t=0; t<3; t++) units.forEach(u => {
      const ds = VC.charOpts(u, units, byId);
      const surf = new Set([VC.normKey(u.t), ...VC.surfaces(byId[u.words[0]])]);
      const ok = ds.length === 3 && new Set([u.t, ...ds.map(d => d.t)]).size === 4 && ds.every(d => uIds.has(d.id))
        && ds.every(d => gk(d) !== gk(u) && rk(d) !== rk(u) && !surf.has(VC.normKey(d.t)) && !VC.samePron(byId[d.words[0]], byId[u.words[0]]))
        && new Set(ds.map(gk)).size === 3;
      if(!ok){ bad++; if(ex.length < 3) ex.push({ u:u.id, ds: ds.map(d => d.id) }); }
      ds.forEach(d => { total++; if(d.lv === u.lv) sameLv++; });
    });
    ex.forEach(e => console.log("    BAD", JSON.stringify(e)));
    // charSound: readings never a homophone of the answer nor a reading of its homographs.
    let sBad = 0, sLenBad = 0;
    units.forEach(u => {
      const rs = VC.charSoundOpts(u, units, byId);
      const forbid = new Set(units.filter(v => VC.normKey(v.t) === VC.normKey(u.t)).map(rk));
      words.forEach(w => { if(VC.surfaces(w).includes(VC.normKey(u.t))) forbid.add(VC.normKey(w.pron)); });
      if(!(rs.length === 3 && new Set(rs.map(VC.normKey)).size === 3 && rs.every(r => !forbid.has(VC.normKey(r))))) sBad++;
      const len = [...u.t].length;
      const sameLenCands = new Set(units.filter(v => v.id !== u.id && VC.normKey(v.t) !== VC.normKey(u.t) && [...v.t].length === len && !forbid.has(rk(v))).map(rk));
      const got = rs.filter(r => units.some(v => rk(v) === VC.normKey(r) && [...v.t].length === len)).length;
      if(got < Math.min(3, sameLenCands.size)) sLenBad++;
    });
    // charRead: meanings, never the gloss of a word the form could also be.
    let rBad = 0;
    units.forEach(u => {
      const ds = VC.charReadOpts(u, words, byId);
      const own = new Set(words.filter(w => VC.surfaces(w).includes(VC.normKey(u.t))).map(w => VC.normKey(w.en)));
      if(!(ds.length === 3 && ds.every(d => !own.has(VC.normKey(d.en))) && new Set(ds.map(d => VC.normKey(d.en))).size === 3)) rBad++;
    });
    // Every item kind: 4 unique options, the answer exactly once, the right stimulus.
    let iBad = 0; const rng = mulberry32(22);
    const SHOW = { charRead:"t", charSound:"t", charPick:"reading", charRecall:"gloss" };
    units.forEach(u => VC.CHAR_KINDS.forEach(kind => {
      const it = VC.charItem(kind, u, { units, words, byId, rng });
      const ok = it.options.length === 4 && new Set(it.options).size === 4 && it.options.filter(o => o === it.answer).length === 1
        && it.show === SHOW[kind] && it.key === "c:" + u.id && it.audio === (kind === "charPick") && it.wordId === u.words[0];
      if(!ok) iBad++;
    }));
    console.log(`\n[22] ${F.name}: charOpts ${units.length*3-bad}/${units.length*3} clean, same-level ${(sameLv/total).toFixed(2)}; charSoundOpts ${units.length-sBad}/${units.length} clean, same-length shortfalls ${sLenBad}; charReadOpts ${units.length-rBad}/${units.length}; items bad ${iBad}`);
    check(tag("charOpts: 3 distinct unit distractors; never the answer's form/surface, gloss, reading or a homophone"), bad === 0);
    check(tag("charOpts prefers the same level (>= 0.95 of distractors)"), sameLv / total >= 0.95);
    check(tag("charSoundOpts: 3 distinct readings, never a homophone or a homograph's reading; same form length first"), sBad === 0 && sLenBad === 0);
    check(tag("charReadOpts: 3 distinct meanings, never a gloss of a word sharing the form"), rBad === 0);
    check(tag("charItem: every kind x unit has 4 unique options, the answer once, the right stimulus and key"), iBad === 0);
  })();

  // ------------------------------------------------------------ [23] tiers
  (function(){
    const ms = cfg.mastered, bs = cfg.bare;
    let bad = 0;
    for(let st=0; st<=9; st++){
      [[true,true],[true,false],[false,true],[false,false]].forEach(([started, mix]) => {
        const exp = !(started && mix) ? null : st >= bs ? "bare" : "ruby";
        if(VC.sentenceTokenTier(st, started, mix, pack) !== exp) bad++;
        const expPF = !(started && mix) ? null : st >= bs ? "bare" : st >= ms ? "ruby" : "pron";
        if(VC.sentenceTokenTier(st, started, mix, Object.assign({}, pack, { pronFirst:true })) !== expPF) bad++;
      });
    }
    const tierOk = VC.charTier(0, pack) === "pron" && VC.charTier(ms-1, pack) === "pron" && VC.charTier(ms, pack) === "ruby"
      && VC.charTier(bs-1, pack) === "ruby" && VC.charTier(bs, pack) === "bare" && VC.charTier(undefined, pack) === "pron";
    const custom = Object.assign({}, pack, { characters: Object.assign({}, pack.characters, { mastered:2, bare:4 }) });
    const customOk = VC.charTier(1, custom) === "pron" && VC.charTier(2, custom) === "ruby" && VC.charTier(4, custom) === "bare";
    const [ua, ub] = units.filter(u => u.lv === ids[0]);
    const sent = { t: ua.t + ub.t, ruby: [[0, ua.t.length, "ra", ua.words[0]], [ua.t.length, ua.t.length + ub.t.length, "rb", ub.words[0]], [0, 0, "x", "nope"]] };
    const pr = P(full(0), { [ua.id]: rec(bs), [ub.id]: rec(0) });
    const rt = VC.rubyTiers(sent, units, pr, pack, true);
    const rubyOk = rt && rt[0].tier === "bare" && rt[0].unitId === ua.id && rt[1].tier === "ruby" && rt[2].unitId === null && rt[2].tier === "ruby"
      && VC.rubyTiers(sent, units, pr, pack, false) === null
      && VC.rubyTiers(sent, units, P(full(0), {}, { mix:false }), pack, true) === null
      && VC.rubyTiers({ t: "x" }, units, pr, pack, true) === null
      && VC.rubyTiers(sent, units, pr, stripChars(pack), true) === null;
    console.log(`\n[23] ${F.name}: tier decision ${80-bad}/80 cases; charTier boundaries ${tierOk}; custom thresholds ${customOk}; rubyTiers ${!!rubyOk}`);
    check(tag("sentenceTokenTier: null unless started and mix on; ruby below bare, bare at/above; pronFirst adds pron below mastered"), bad === 0);
    check(tag("charTier boundaries follow pack thresholds (defaults and custom)"), tierOk && customOk);
    check(tag("rubyTiers: per-token tier from the unit whose words[0] is the token's word; null when off, unstarted, no ruby or no characters"), !!rubyOk);
  })();

  // ------------------------------------------------------------ [24] gate and placement
  (function(){
    const st = VC.strata(words, pack.placement, VC.setSizeOf(pack));
    const lastEndsAtN = ids.every(lv => { const b = st.filter(x => x.lv === lv); return b[b.length-1].s1 === N[lv]; });
    const passed = st.filter(b => idx[b.lv] <= i1).length;
    const placed = VC.applyPlacement(VC.defaultProg(pack), st, passed, words, pack);
    const ns = VC.nextStage(pack, words, units, placed);
    const startedAfter = VC.charsUnlocked(pack, words, placed) && ns && ns.kind === "chars" && ns.key === stageLv[0].join("+") && VC.charsStarted(pack, words, units, placed);
    const short = Object.assign(full(i1), { [ids[i1]]: N[ids[i1]] - 1 });
    const pShort = P(short, {});
    const notShort = !VC.charsUnlocked(pack, words, pShort) && !VC.charsStarted(pack, words, units, pShort) && !VC.charsUnlocked(pack, words, VC.defaultProg(pack));
    console.log(`\n[24] ${F.name}: last stratum ends at nSets ${lastEndsAtN}; placement through ${ids[i1]} -> unlocked + first character stage current + started ${!!startedAfter}; one set short stays locked ${notShort}`);
    check(tag("placement strata end exactly at nSets per level"), lastEndsAtN);
    check(tag("placement through the first stage's level unlocks and starts characters; one set short does not"), !!startedAfter && notShort);
  })();

  // ------------------------------------------------------------ [25] newCharUnits
  (function(){
    const uOf = w => units.find(u => u.words[0] === w.id);
    const hi = byLv[ids[2]].filter(uOf).slice(0, 3), lo = byLv[ids[0]].filter(uOf).slice(0, 5);
    const kanaOnly = words.filter(w => !uOf(w)).slice(0, 2); // ja-like: words without a unit are skipped
    const learned = [...hi, ...kanaOnly, ...lo.slice().reverse()];
    const pr = P(full(-1), { [uOf(lo[0]).id]: rec(1) });
    const got = VC.newCharUnits(units, learned, pr, pack, 6).map(u => u.id);
    const exp = [lo[1], lo[2], lo[3], lo[4], hi[0], hi[1]].map(w => uOf(w).id);
    console.log(`\n[25] ${F.name}: newCharUnits ${JSON.stringify(got)}`);
    check(tag("newCharUnits skips recorded units and words without one, orders by level then file, caps at n"), util.isDeepStrictEqual(got, exp));
  })();

  // ------------------------------------------------------------ [26] path flags
  (function(){
    const good = [ {chars:{defer:true}}, {chars:{defer:false}}, {chars:{choiceSeen:true}}, {chars:{choiceSeen:false}}, {chars:{}} ];
    const badShapes = [ {chars:{defer:1}}, {chars:{defer:"true"}}, {chars:{defer:null}}, {chars:{choiceSeen:0}}, {chars:{choiceSeen:"no"}}, {chars:{choiceSeen:{}}} ];
    const goodOk = good.every(d => VC.validateProgShape(d, ids).ok), badOk = badShapes.every(d => !VC.validateProgShape(d, ids).ok);
    const m = VC.normalizeProg({ chars:{ c:{ [units[0].id]: rec(6) }, mix:false } }, pack);
    const kept = VC.normalizeProg({ chars:{ defer:true, choiceSeen:true } }, pack);
    const flagsOk = m.chars.defer === false && m.chars.choiceSeen === false && m.chars.mix === false && kept.chars.defer === true && kept.chars.choiceSeen === true && kept.chars.mix === true;
    console.log(`\n[26] ${F.name}: flags good ${goodOk}, bad rejected ${badOk}, defaults/kept ${flagsOk}`);
    check(tag("validateProgShape accepts boolean / rejects non-boolean chars.defer and chars.choiceSeen"), goodOk && badOk);
    check(tag("normalizeProg defaults defer/choiceSeen false, keeps set values and mix"), flagsOk);
  })();

  // ------------------------------------------------------------ [27] stage sequencing
  (function(){
    const firstKey = stageLv[0].join("+"), lastKey = stageLv[stageLv.length-1].join("+");
    const allStage = [].concat(...stageLv);
    const lbl = p => { const s = VC.nextStage(pack, words, units, p); return s ? (s.kind === "words" ? s.lv : s.key) : "null"; };
    const cases = [
      ["mid level 2", P(Object.assign(full(0), { [ids[1]]: 1 }), {}), ids[1]],
      ["first stage's level done", P(full(i1), {}), firstKey],
      ["first stage partly recorded", P(full(i1), recAll([ids[0]])), firstKey],
      ["first stage recorded", P(full(i1), recAll(stageLv[0])), ids[i1+1]],
      ["through the last stage's level", P(full(i2), recAll(stageLv[0])), lastKey],
      ["defer, first stage's level done", P(full(i1), {}, { defer:true }), ids[i1+1]],
      ["defer, through the last stage's level", P(full(i2), {}, { defer:true }), allStage.join("+")],
      ["all done", P(full(ids.length-1), recAll(allStage)), "null"],
      ["all done (defer)", P(full(ids.length-1), recAll(allStage), { defer:true }), "null"],
    ];
    let bad = 0;
    cases.forEach(([label, p, exp]) => { const got = lbl(p); if(got !== exp){ bad++; console.log(`    BAD ${label}: got ${got}, expected ${exp}`); } });
    const pathDef = VC.stagePath(pack, words, units, P({}, {})).map(LBL).join(" ");
    const pathDefer = VC.stagePath(pack, words, units, P({}, {}, { defer:true })).map(LBL).join(" ");
    const orderOk = pathDef === EXPECT_PATH[F.name].def && pathDefer === EXPECT_PATH[F.name].defer;
    const half = VC.stagePath(pack, words, units, P(full(i1), recAll([ids[0]]))).find(s => s.kind === "chars");
    const nFirst = units.filter(u => stageLv[0].includes(u.lv)).length, nL0 = units.filter(u => u.lv === ids[0]).length;
    const w0 = VC.stagePath(pack, words, units, P({ [ids[0]]: 2 }, {}))[0];
    const fracOk = Math.abs(half.frac - nL0/nFirst) < 1e-9 && half.nunits === nFirst && half.nsets === Math.ceil(nFirst/cfg.setSize) && w0.frac === 2/N[ids[0]] && w0.set === 2;
    const started = (p) => VC.charsStarted(pack, words, units, p);
    const startedOk = !started(P({ [ids[0]]: 1 }, {})) && started(P({ [ids[0]]: 1 }, { [units[0].id]: rec(1) }))
      && started(P(full(i1), {})) && !started(P(full(i1), {}, { defer:true })) && !VC.charsStarted(stripChars(pack), words, units, P(full(i1), { [units[0].id]: rec(1) }));
    console.log(`\n[27] ${F.name}: ${cases.length-bad}/${cases.length} nextStage cases; path "${pathDef}" / "${pathDefer}"; fractions ${fracOk}; charsStarted ${startedOk}`);
    check(tag("nextStage: word level / first stage / next level / later stage / deferred / all done -> null"), bad === 0);
    check(tag("stagePath order (default and deferred), labels and stage fractions"), orderOk && fracOk);
    check(tag("charsStarted = any record OR the current stage is characters (never without pack.characters)"), startedOk);
  })();

  // ------------------------------------------------------------ [28] character sets
  (function(){
    const fileIdx = new Map(units.map((u, i) => [u.id, i]));
    const sets = VC.charSets(stageLv[0], units, pack); const flat = [].concat(...sets);
    const sizesOk = sets.slice(0, -1).every(s => s.length === cfg.setSize) && sets[sets.length-1].length >= 1 && sets[sets.length-1].length <= cfg.setSize;
    const orderOk = flat.every((u, i) => i === 0 || idx[flat[i-1].lv] < idx[u.lv] || (flat[i-1].lv === u.lv && fileIdx.get(flat[i-1].id) < fileIdx.get(u.id)));
    const coverOk = flat.length === units.filter(u => stageLv[0].includes(u.lv)).length && flat[0].lv === ids[0] && sets.length === Math.ceil(flat.length/cfg.setSize);
    const s0 = sets[0]; const c = {}; s0.slice(0, -1).forEach(u => { c[u.id] = rec(1); });
    const pr = P(full(i1), c);
    const partNot = !VC.charSetTaught(s0, pr);
    pr.chars.c[s0[s0.length-1].id] = rec(0, 1);
    const fullYes = VC.charSetTaught(s0, pr);
    const nx = VC.nextCharSet(stageLv[0], units, pack, pr);
    const nextOk = nx && nx.index === 1 && util.isDeepStrictEqual(nx.units.map(u => u.id), sets[1].map(u => u.id)) && nx.total === sets.length;
    const last = VC.charSets(stageLv[stageLv.length-1], units, pack);
    const onlyLast = [].concat(...last).every(u => stageLv[stageLv.length-1].includes(u.lv));
    console.log(`\n[28] ${F.name}: ${sets.length} sets in the first stage (last ${sets[sets.length-1].length}); sizes ${sizesOk}, order ${orderOk}, coverage ${coverOk}; taught iff all recorded ${partNot && fullYes}; nextCharSet ${!!nextOk}; later stage only its levels ${onlyLast}`);
    check(tag("charSets: chunks of setSize, level order then file order, cover exactly the stage's levels"), sizesOk && orderOk && coverOk && onlyLast);
    check(tag("a set is taught iff every unit has a record; nextCharSet returns the first untaught"), partNot && fullYes && !!nextOk);
  })();

  // ------------------------------------------------------------ [29] unified ranking
  (function(){
    const [a, b, c2] = words.slice(0, 3); const [d, e, f] = units.slice(3, 6);
    const wrecs = { [a.id]: {r:2,w:1,s:0}, [b.id]: {r:5,w:0,s:4}, [c2.id]: {r:3,w:0,s:3} };
    const crecs = { [d.id]: {r:1,w:0,s:1}, [e.id]: {r:2,w:0,s:2}, [f.id]: {r:1,w:2,s:0} };
    const rng = mulberry32(29); let bad = 0;
    for(let t=0; t<50; t++){
      const r = VC.rankUnified([a, b, c2], wrecs, [d, e, f], crecs, 6, pack, rng).map(x => x.kind + ":" + x.entry.id);
      const pos = k => r.indexOf(k);
      if(!(pos("c:"+f.id) === 0 && pos("w:"+a.id) < pos("c:"+d.id) && pos("w:"+a.id) < pos("c:"+e.id)
        && Math.max(pos("c:"+d.id), pos("c:"+e.id)) < Math.min(pos("w:"+b.id), pos("w:"+c2.id)))) bad++;
    }
    const capped = VC.rankUnified([a, b, c2], wrecs, [d, e, f], crecs, 2, pack, rng).length === 2;
    const scoreOk = VC.weakScore({w:2,s:1}) === 5 && VC.weakScore(undefined) === 0
      && VC.charReviewScore({r:1,w:0,s:1}, pack) === 0 && VC.charReviewScore({r:2,w:0,s:2}, pack) === 0
      && VC.charReviewScore({r:4,w:0,s:4}, pack) === -4 && VC.charReviewScore({r:1,w:2,s:0}, pack) === 6;
    const g = words.slice(6, 16); let cFirst = 0, wFirst = 0;
    for(let t=0; t<200; t++){ const top = VC.rankUnified(g, {}, [d], crecs, 1, pack, rng)[0]; if(top.kind === "c") cFirst++; else wFirst++; }
    console.log(`\n[29] ${F.name}: ${50-bad}/50 trials ordered (missed unit > missed word > fresh units > mastered words); cap ${capped}; scores ${scoreOk}; fresh unit vs 10 never-drilled words top slot ${cFirst}/${wFirst}`);
    check(tag("rankUnified: missed unit > missed word > fresh units > mastered words; capped at n"), bad === 0 && capped && scoreOk);
    check(tag("charReviewScore: unmastered units clamp to 0 and tie (random tie-break) with never-drilled words"), cFirst > 0 && wFirst > 0);
  })();

  // ------------------------------------------------------------ [30] recall options
  (function(){
    const byT = new Map(); units.forEach(u => { if(!byT.has(u.t)) byT.set(u.t, []); byT.get(u.t).push(u); });
    let bad = 0;
    units.forEach(u => {
      const opts = VC.recallCharOpts(u, units, byId);
      const others = opts.filter(t => t !== u.t).map(t => byT.get(t) || []);
      const ok = opts.length === 4 && new Set(opts).size === 4 && opts[0] === u.t && others.length === 3
        && others.every(list => list.length && list.every(o => VC.normKey(VC.unitGloss(o, byId)) !== VC.normKey(VC.unitGloss(u, byId)) && VC.normKey(VC.unitReading(o, byId)) !== VC.normKey(VC.unitReading(u, byId))));
      if(!ok) bad++;
    });
    console.log(`\n[30] ${F.name}: recallCharOpts ${units.length-bad}/${units.length} clean`);
    check(tag("recallCharOpts: 4 distinct forms, answer first, no distractor shares gloss or reading"), bad === 0);
  })();

  // ------------------------------------------------------------ [31] choice card
  (function(){
    const one = { [units.find(u => u.lv === ids[ids.length-1] || !stageLv[0].includes(u.lv)).id]: rec(1) };
    const cases = [
      ["first stage's level done, no records, unseen", P(full(i1), {}), true],
      ["records elsewhere, unseen", P(full(i1), one), true],
      ["first stage all recorded", P(full(i1), recAll(stageLv[0])), false],
      ["choice seen", P(full(i1), one, { choiceSeen:true }), false],
      ["deferred", P(full(i1), {}, { defer:true }), false],
      ["later levels up to the last stage done", P(full(i2), {}), false],
      ["one set short", P(Object.assign(full(i1), { [ids[i1]]: N[ids[i1]] - 1 }), {}), false],
    ];
    let bad = 0;
    cases.forEach(([label, p, exp]) => { const got = VC.showCharChoice(pack, words, units, p); if(got !== exp){ bad++; console.log(`    BAD ${label}: got ${got}, expected ${exp}`); } });
    // A single-stage pack has nothing to skip to: the choice never shows.
    const single = Object.assign({}, pack, { characters: Object.assign({}, pack.characters, { stages: [pack.characters.stages[0]] }) });
    const singleOk = !VC.showCharChoice(single, words, units, P(full(i1), {})) && !VC.showCharChoice(stripChars(pack), words, units, P(full(i1), {}));
    console.log(`\n[31] ${F.name}: choice-card gating ${cases.length-bad}/${cases.length} cases; single-stage / no-characters pack never shows ${singleOk}`);
    check(tag("showCharChoice: unseen, not deferred, levels before the first stage done, that stage incomplete, a later level to skip to"), bad === 0 && singleOk);
  })();

  // ------------------------------------------------------------ [32] learning-order flip
  (function(){
    const p = P(full(i1), { [units[0].id]: rec(2, 1) });
    p.w = { [words[0].id]: rec(3) };
    const before = clone(p);
    const pathB = VC.stagePath(pack, words, units, p), stB = VC.nextStage(pack, words, units, p);
    VC.setCharOrder(p, true);
    const pathA = VC.stagePath(pack, words, units, p), stA = VC.nextStage(pack, words, units, p);
    VC.setCharOrder(p, false);
    const pathBack = VC.stagePath(pack, words, units, p), stBack = VC.nextStage(pack, words, units, p);
    const untouched = util.isDeepStrictEqual(p.chars.c, before.chars.c) && util.isDeepStrictEqual(p.w, before.w) && util.isDeepStrictEqual(p.sets, before.sets) && p.chars.choiceSeen === before.chars.choiceSeen;
    const flipped = pathB.map(LBL).join(" ") !== pathA.map(LBL).join(" ") && stB.kind !== stA.kind;
    const back = util.isDeepStrictEqual(pathB, pathBack) && util.isDeepStrictEqual(stB, stBack);
    const q1 = VC.answerCharChoice(P(full(i1), {}), true), q2 = VC.answerCharChoice(P(full(i1), {}), false);
    const choiceOk = q1.chars.choiceSeen && !q1.chars.defer && q2.chars.choiceSeen && q2.chars.defer
      && VC.nextStage(pack, words, units, q1).kind === "chars" && VC.nextStage(pack, words, units, q2).lv === ids[i1+1];
    console.log(`\n[32] ${F.name}: flip records untouched ${untouched}, order flips ${flipped}, round-trips ${back}; choice start/skip ${choiceOk}`);
    check(tag("setCharOrder re-derives stagePath/nextStage from the flag alone; records, sets and choiceSeen untouched; round-trips"), untouched && flipped && back);
    check(tag("answerCharChoice: start keeps the order, skip defers; both mark the card seen"), choiceOk);
  })();

  // ------------------------------------------------------------ [34] unified plans, snapshot, learn
  (function(){
    // A learner past the first stage's level with some units recorded.
    const c = {}; VC.charStageUnits(stageLv[0], units, pack).slice(0, 12).forEach((u, i) => { c[u.id] = rec(i % 5, i % 3 === 0 ? 1 : 0); });
    const p = P(full(i1), c);
    const lw = VC.learnedWords(words, pack, p);
    lw.slice(0, 7).forEach((w, i) => { p.w[w.id] = { r:1, w:0, s:1, prov: i < 3 ? 1 : undefined }; if(i >= 3) delete p.w[w.id].prov; });
    const snap = VC.todaySnapshot(pack, words, units, p);
    const rng = mulberry32(34);
    let bad = 0, sawBoth = 0;
    for(let t=0; t<40; t++){
      const plan = VC.buildReviewPlan(lw, p, pack, { units, size: snap.reviewSize, rng });
      const ws = plan.filter(x => x.word), us = plan.filter(x => x.unit);
      const prod = ws.filter(x => VC.PRODUCTION_KINDS.includes(x.kind)).length;
      const pv = lw.filter(w => p.w[w.id] && p.w[w.id].prov);
      const ok = plan.length === 20 && prod >= Math.ceil(ws.length * 0.4 - 1e-9) && us.every(x => cfg.reviewKinds.includes(x.kind) && c[x.unit.id])
        && new Set(plan.map(x => (x.word ? "w:" + x.word.id : "c:" + x.unit.id))).size === 20 && pv.every(w => ws.some(x => x.word.id === w.id));
      if(!ok) bad++;
      if(ws.length && us.length) sawBoth++;
    }
    const rc = VC.buildRecallPlan(lw, p, pack, 8, { units, rng });
    const recallOk = rc.length === 8 && rc.every(x => x.word ? VC.PRODUCTION_KINDS.includes(x.kind) : (x.kind === "charRecall" && c[x.unit.id]));
    // recall is weakest-first: a missed unit always makes the cut
    const missed = Object.keys(c).find(k => c[k].w > 0);
    const recallWeak = [0,1,2,3,4].every(() => VC.buildRecallPlan(lw, p, pack, 8, { units, rng }).some(x => x.unit && x.unit.id === missed));
    const snapOk = snap.stage.kind === "chars" && snap.cset && snap.cset.index === 1 && snap.charsStarted === true && snap.reviewSize === VC.REVIEW_SIZE_CHARS && snap.choice === true;
    const fresh = VC.todaySnapshot(pack, words, units, P({}, {}));
    const freshOk = fresh.stage.kind === "words" && fresh.stage.lv === ids[0] && fresh.cset === null && fresh.charsStarted === false && fresh.reviewSize === VC.REVIEW_SIZE && fresh.choice === false;
    const lp = VC.learnCharPlan(snap.cset.units, pack);
    const learnOk = lp.length === snap.cset.units.length * cfg.learnKinds.length && lp.every((x, i) => x.kind === cfg.learnKinds[i % cfg.learnKinds.length] && x.unit === snap.cset.units[Math.floor(i / cfg.learnKinds.length)])
      && VC.learnCharPlan(snap.cset.units, stripChars(pack)).length === 0;
    const mp = P({}, {}); const wBefore = clone(mp.w), sBefore = clone(mp.s);
    VC.markChar(mp, units[0].id, true); VC.markChar(mp, units[0].id, false); VC.markChar(mp, units[1].id, true);
    const markOk = util.isDeepStrictEqual(mp.chars.c, { [units[0].id]: {r:1,w:1,s:0}, [units[1].id]: {r:1,w:0,s:1} }) && util.isDeepStrictEqual(mp.w, wBefore) && util.isDeepStrictEqual(mp.s, sBefore);
    const imp = VC.applyImport(P({}, {}, { mix:false }), JSON.stringify({ sets:{} }), pack);
    const imp2 = VC.applyImport(P({}, {}, { mix:false }), JSON.stringify({ sets:{}, chars:{ mix:true } }), pack);
    const importOk = imp.ok && imp.prog.chars.mix === false && imp2.ok && imp2.prog.chars.mix === true;
    console.log(`\n[34] ${F.name}: unified Review ${40-bad}/40 well-formed, both kinds in ${sawBoth}/40; Recall ${recallOk}/${recallWeak}; snapshot ${snapOk}/${freshOk}; learn plan ${learnOk}; markChar ${markOk}; import mix ${importOk}`);
    check(tag("unified Review: 20 items once started, provisional words kept, >= 40% word production, units get reviewKinds, no duplicates"), bad === 0 && sawBoth > 30);
    check(tag("unified Recall: 8 weakest-first, words recall/type, units charRecall"), recallOk && recallWeak);
    check(tag("todaySnapshot: stage + next set + started + review size + choice; fresh learner is word-only"), snapOk && freshOk);
    check(tag("learnCharPlan: one item per learnKind per unit, in order; nothing without pack.characters"), learnOk);
    check(tag("markChar writes prog.chars.c only; applyImport keeps the mix preference when the import lacks it"), markOk && importOk);
  })();
}

// ------------------------------------------------------------ [33] flag-off equality
function flagOffEquality(){
  console.log("\n================ [33] plans and progress equal the pre-characters engine when there is no unit pool");
  let OLD = null;
  try{
    const src = cp.execSync(`git show ${BASE_REV}:engine/core.js`, { cwd: ROOT, stdio: ["ignore", "pipe", "pipe"] }).toString();
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "chars_base_"));
    fs.writeFileSync(path.join(dir, "core.js"), src);
    OLD = require(path.join(dir, "core.js"));
    fs.rmSync(dir, { recursive: true, force: true });
  }catch(e){ console.log(`    cannot load ${BASE_REV}:engine/core.js: ${e.message}`); }
  check(`base engine ${BASE_REV} loads from git`, !!OLD);
  if(!OLD) return;
  const loadConst = (file, name) => new Function(fs.readFileSync(file, "utf8") + `\nreturn ${name};`)();
  const ZH = path.join(ROOT, "packs", "zh");
  const real = { name: "zh (real pack)", pack: loadConst(path.join(ZH, "pack.js"), "PACK"), words: loadConst(path.join(ZH, "words.js"), "WORDS"), units: [] };
  const z = zhLike(), j = jaLike();
  // Variants: [label, pack, words, units passed to the plan builders, whether to give records]
  const variants = [
    ["real zh, characters stripped, no units", stripChars(real.pack), real.words, undefined, false],
    ["zh-like stripped, units with records passed", stripChars(z.pack), z.words, z.units, true],
    ["ja-like stripped, units with records passed", stripChars(j.pack), j.words, j.units, true],
    ["zh-like with characters, no records", z.pack, z.words, z.units, false],
    ["ja-like with characters, empty unit pool", j.pack, j.words, [], true],
    ["ja-like with characters, units omitted", j.pack, j.words, undefined, true],
  ];
  const planKey = plan => JSON.stringify(plan.map(x => [x.kind, x.word ? x.word.id : "U" + x.unit.id]));
  variants.forEach(([label, pack, words, units, withRecs]) => {
    const ids = VC.levelIds(pack), byLv = VC.wordsByLevel(words, pack);
    const gen = mulberry32(label.length * 7919);
    let revBad = 0, recBad = 0, progBad = 0, pathBad = 0;
    for(let t=0; t<150; t++){
      const sets = {}; ids.forEach(lv => { sets[lv] = Math.floor(gen() * (VC.nSets(byLv[lv], 10) + 1)); });
      const raw = { sets, w:{}, sessions: t };
      words.forEach(w => { if(gen() < 0.3) raw.w[w.id] = { r: Math.floor(gen()*5), w: Math.floor(gen()*3), s: Math.floor(gen()*5), prov: gen() < 0.2 ? 1 : undefined }; });
      Object.values(raw.w).forEach(r => { if(r.prov === undefined) delete r.prov; });
      if(withRecs && units && units.length){ raw.chars = { c:{} }; units.forEach(u => { if(gen() < 0.3) raw.chars.c[u.id] = { r:1, w: Math.floor(gen()*2), s: Math.floor(gen()*4) }; }); }
      // progress functions (the chars key, when a stripped pack sees one, is carried untouched by both)
      const oldP = OLD.normalizeProg(clone(raw), pack), newP = VC.normalizeProg(clone(raw), pack);
      const packHasChars = !!VC.charsConfig(pack);
      const expectP = packHasChars ? Object.assign({}, oldP, { chars: VC.normalizeCharsProg(raw.chars) }) : oldP;
      if(!util.isDeepStrictEqual(newP, expectP)) progBad++;
      if(!packHasChars && !util.isDeepStrictEqual(VC.defaultProg(pack), OLD.defaultProg(pack))) progBad++;
      if(!util.isDeepStrictEqual(VC.validateProgShape(clone(raw), ids), OLD.validateProgShape(clone(raw), ids))) progBad++;
      const bootNew = VC.bootProg(JSON.stringify(raw), pack), bootOld = OLD.bootProg(JSON.stringify(raw), pack);
      if(!packHasChars && !util.isDeepStrictEqual(bootNew, bootOld)) progBad++;
      const impNew = VC.applyImport(oldP, JSON.stringify(raw), pack), impOld = OLD.applyImport(oldP, JSON.stringify(raw), pack);
      if(!packHasChars && !util.isDeepStrictEqual(impNew, impOld)) progBad++;
      // plans
      const prog = newP; const learned = VC.learnedWords(words, pack, prog);
      if(!util.isDeepStrictEqual(learned, OLD.learnedWords(words, pack, prog))) revBad++;
      [undefined, 20].forEach(size => {
        const seed = t * 31 + (size || 0);
        const o = withSeed(seed, () => OLD.buildReviewPlan(learned, prog, pack, { size, rng: mulberry32(seed + 1) }));
        const n = withSeed(seed, () => VC.buildReviewPlan(learned, prog, pack, { size, rng: mulberry32(seed + 1), units }));
        if(planKey(o) !== planKey(n)) revBad++;
      });
      [8, 20].forEach(nItems => {
        const seed = t * 17 + nItems;
        const o = withSeed(seed, () => OLD.buildRecallPlan(learned, prog, pack, nItems));
        const n = withSeed(seed, () => VC.buildRecallPlan(learned, prog, pack, nItems, { units }));
        if(planKey(o) !== planKey(n)) recBad++;
      });
      // path: without characters the strip is the level list and nextStage is nextNewSet
      if(!packHasChars){
        const sp = VC.stagePath(pack, words, units || [], prog);
        const strip = ids.map(lv => ({ label: VC.levelLabel(pack, lv), frac: VC.nSets(byLv[lv], 10) ? (prog.sets[lv]||0)/VC.nSets(byLv[lv], 10) : 1 }));
        const nn = OLD.nextNewSet(words, pack, prog), ns = VC.nextStage(pack, words, units || [], prog);
        const snap = VC.todaySnapshot(pack, words, units || [], prog);
        if(!util.isDeepStrictEqual(sp.map(s => ({ label: s.label, frac: s.frac })), strip) || sp.some(s => s.kind !== "words")
          || (nn ? !(ns && ns.lv === nn.lv && ns.set === nn.set) : ns !== null)
          || snap.cset !== null || snap.charsStarted || snap.reviewSize !== OLD.REVIEW_SIZE || snap.choice) pathBad++;
      }
    }
    console.log(`    ${label}: review diffs ${revBad}, recall diffs ${recBad}, progress diffs ${progBad}, path diffs ${pathBad} (150 progs)`);
    check(`[33] ${label}: buildReviewPlan/buildRecallPlan byte-identical to ${BASE_REV}`, revBad === 0 && recBad === 0);
    check(`[33] ${label}: normalizeProg/defaultProg/validateProgShape/bootProg/applyImport match ${BASE_REV} (plus chars only with pack.characters)`, progBad === 0);
    if(!VC.charsConfig(pack)) check(`[33] ${label}: stagePath is the level strip, nextStage is nextNewSet, snapshot is word-only`, pathBad === 0);
  });
}

suite(zhLike());
suite(jaLike());
flagOffEquality();

console.log(`\n${fails === 0 ? "ALL PASSED" : "FAILED"}: ${passes} passed, ${fails} failed`);
process.exit(fails === 0 ? 0 : 1);
