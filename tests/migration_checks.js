// Node checks for migrateLegacy in engine/core.js (hsk_pinyin -> vocab_zh, docs/HSK_MERGE.md §4)
// and tools/diff_hsk_migration.js. Synthetic hsk records: seeds A-E plus every hsk record
// version shape (v1, v2, v2.1, v2.2, HEAD), idempotence, the unmapped list, rejections.
// Where the hsk checkout sits beside this repo (../chinese, formerly ../hsk), each seed is also checked against
// hsk's own validateProgShape and the tool's derived-view diff; otherwise those are skipped.
// Run: node tests/migration_checks.js     (no dependencies)
"use strict";
const fs = require("fs");
const path = require("path");
const util = require("util");

const ROOT = path.join(__dirname, "..");
const VC = require(path.join(ROOT, "engine", "core.js"));
const { diffMigration } = require(path.join(ROOT, "tools", "diff_hsk_migration.js"));
const ZH = path.join(ROOT, "packs", "zh");
const HSK = process.env.HSK_DIR || path.join(ROOT, "..", "chinese");
const readJSON = f => JSON.parse(fs.readFileSync(path.join(ZH, f), "utf8"));
const PACK = readJSON("pack.json"), WORDS = readJSON("words.json"), LEGACY = readJSON("legacy.json");
const HSK_CORE = path.join(HSK, "src", "pinyin_core.js");
const PC = fs.existsSync(HSK_CORE) ? require(HSK_CORE) : null;

let fails = 0, passes = 0, skips = 0;
function check(name, cond){
  if(cond){ passes++; console.log(`PASS  ${name}`); }
  else { fails++; console.log(`FAIL  ${name}`); }
}
const skip = name => { skips++; console.log(`SKIP  ${name}`); };
const clone = x => JSON.parse(JSON.stringify(x));
const eq = util.isDeepStrictEqual;

// hanzi per level, in pack (= hsk VOCAB) order.
const hanziOf = {}; Object.keys(LEGACY.w).forEach(h => { hanziOf[LEGACY.w[h]] = h; });
const byLv = { 1:[], 2:[], 3:[], 4:[] };
WORDS.forEach(w => byLv[w.lv].push(hanziOf[w.id]));
const nsets = lv => Math.ceil(byLv[lv].length / 10);
const SENTS = Object.keys(LEGACY.s);
const rec = (r, w, s, extra) => Object.assign({ r, w, s }, extra || {});
const words = (lv, n, f) => { const o = {}; byLv[lv].slice(0, n).forEach((h, i) => { o[h] = f(i); }); return o; };

// ---- seeds
const HSK_FRESH = { v:2, w:{}, sets:{1:0,2:0,3:0,4:0}, lessons:{}, sessions:0, theme:null, showChars:false, s:{}, c:{}, mixChars:true, charsAfterHsk4:false, charsChoiceSeen:false };
const midW = Object.assign(words(1, byLv[1].length, i => rec(3 + i % 4, i % 3, i % 5)), words(2, 30, i => rec(1 + i % 3, i % 2, i % 4, i % 7 === 0 ? { prov:1 } : null)));
const hsk3done = { 1: nsets(1), 2: nsets(2), 3: nsets(3), 4: 0 };
const allLv = [1,2,3].flatMap(lv => byLv[lv]);
const charsSome = {}; allLv.slice(0, 25).forEach((h, i) => { charsSome[h] = rec(1 + i % 3, i % 2, i % 4); });
const SEEDS = {
  "A empty": {},
  "B fresh": clone(HSK_FRESH),
  "C mid-HSK2": Object.assign(clone(HSK_FRESH), { w: midW, sets:{1:nsets(1),2:3,3:0,4:0}, sessions: 14, theme:"dark", placedOnce:true,
    lessons:{ tones:1, "finals-simple":1 }, s: Object.fromEntries(SENTS.slice(0, 12).map((z, i) => [z, rec(2, i % 2, i % 3)])),
    w_d: undefined }),
  "D1 chars started, card answered: start": Object.assign(clone(HSK_FRESH), { w: midW, sets: hsk3done, sessions: 40, c: charsSome, charsChoiceSeen:true }),
  "D2 chars started, card answered: skip": Object.assign(clone(HSK_FRESH), { w: midW, sets: hsk3done, sessions: 40, c: charsSome, charsChoiceSeen:true, charsAfterHsk4:true }),
  "D3 learning order flipped from Progress": Object.assign(clone(HSK_FRESH), { w: midW, sets:{1:nsets(1),2:nsets(2),3:nsets(3),4:4}, c: charsSome, charsAfterHsk4:true, charsChoiceSeen:true, mixChars:false }),
  "E HSK4 complete": Object.assign(clone(HSK_FRESH), { w: Object.fromEntries(Object.keys(LEGACY.w).map((h, i) => [h, rec(5 + i % 3, i % 2, 3 + i % 4)])),
    sets:{1:nsets(1),2:nsets(2),3:nsets(3),4:nsets(4)}, s: Object.fromEntries(SENTS.map((z, i) => [z, rec(3, i % 2, 2)])),
    c: Object.fromEntries(Object.keys(LEGACY.c).map((h, i) => [h, rec(2 + i % 2, 0, 3)])), charsChoiceSeen:true, sessions: 200, soundsOpened:1, placedOnce:1 }),
  // record version shapes (what each hsk release stored)
  "v1": { v:1, w:{ [byLv[1][0]]: rec(2,1,1), [byLv[1][1]]: rec(1,0,1,{prov:true}) }, sets:{1:3}, lessons:{ tones:1 }, sessions:2, theme:"light" },
  "v2": { v:2, w:{ [byLv[1][0]]: rec(4,0,4) }, sets:{1:2,2:0,3:0,4:0}, lessons:{}, sessions:3, theme:null, showChars:true, dismissedSoundsHint:true },
  "v2.1 sentences": { v:2, w:{ [byLv[1][2]]: rec(1,1,0,{d:1}) }, s:{ [SENTS[0]]: rec(1,0,1) }, sets:{1:1,2:0,3:0,4:0}, lessons:{}, sessions:5, theme:null, showChars:false },
  "v2.2 characters": Object.assign({ v:2, w: midW, s:{}, sets: hsk3done, lessons:{}, sessions:30, theme:null, showChars:true }, { c: charsSome, mixChars:false }),
  "HEAD": Object.assign(clone(HSK_FRESH), { w: midW, sets: hsk3done, c: charsSome, charsChoiceSeen:false, placedOnce:true, soundsOpened:true, dismissedSoundsHint:1 }),
};
delete SEEDS["C mid-HSK2"].w_d;

const count = m => Object.keys(m || {}).length;
console.log("[1] seeds and version shapes");
for(const [name, old] of Object.entries(SEEDS)){
  if(PC) check(`${name}: hsk's own validateProgShape accepts the seed`, PC.validateProgShape(clone(old)).ok);
  const res = VC.migrateLegacy(PACK, LEGACY, clone(old));
  check(`${name}: ok, not already migrated`, res.ok && res.already === false);
  if(!res.ok) continue;
  const p = res.prog;
  check(`${name}: nothing unmapped`, res.unmapped.length === 0);
  const expDropped = ["showChars","dismissedSoundsHint"].filter(f => old[f] !== undefined);
  check(`${name}: dropped = ${JSON.stringify(expDropped)}`, eq(res.dropped.map(d => d.path), expDropped));
  check(`${name}: validateProgShape accepts the output`, VC.validateProgShape(p, VC.levelIds(PACK)).ok);
  check(`${name}: normalizeProg accepts the output unchanged`, eq(VC.normalizeProg(clone(p), PACK), p));
  const boot = VC.bootProg(JSON.stringify(p), PACK);
  check(`${name}: bootProg keeps it (no backup, nothing dropped)`, eq(boot.prog, p) && boot.backupRaw === null && !boot.dropped.length);
  const imp = VC.applyImport(VC.defaultProg(PACK), JSON.stringify(p), PACK);
  check(`${name}: applyImport accepts it`, imp.ok && eq(imp.prog, p));
  check(`${name}: v and marker`, p.v === VC.PROG_VERSION && eq(p.legacy, { key:"hsk_pinyin", format:"hsk-v2" }));
  check(`${name}: w/s/c record counts carried`, count(p.w) === count(old.w) && count(p.s) === count(old.s) && count(p.chars.c) === count(old.c));
  const wOk = Object.keys(old.w || {}).every(h => eq(p.w[LEGACY.w[h]], old.w[h]));
  const sOk = Object.keys(old.s || {}).every(z => eq(p.s[LEGACY.s[z]], old.s[z]));
  const cOk = Object.keys(old.c || {}).every(h => eq(p.chars.c[LEGACY.c[h]], old.c[h]));
  check(`${name}: every record verbatim under its new id`, wOk && sOk && cOk);
  const sets = { 1:0, 2:0, 3:0, 4:0, ...(old.sets || {}) };
  check(`${name}: sets`, eq(p.sets, Object.fromEntries(Object.entries(sets).map(([k, v]) => [String(k), v]))));
  check(`${name}: lessons, sessions, theme, placedOnce, soundsOpened`, eq(p.lessons, old.lessons || {}) && p.sessions === (old.sessions || 0)
    && p.theme === (old.theme === undefined ? null : old.theme) && p.placedOnce === (old.placedOnce === undefined ? false : old.placedOnce)
    && p.soundsOpened === old.soundsOpened);
  check(`${name}: chars flags (mix, defer, choiceSeen)`, p.chars.mix === (old.mixChars === undefined ? true : old.mixChars)
    && p.chars.defer === !!old.charsAfterHsk4 && p.chars.choiceSeen === !!old.charsChoiceSeen && p.chars.v === VC.CHARS_PROG_VERSION);
  check(`${name}: showPron takes the pack default, hsk-only fields gone`, p.showPron === (PACK.showPron !== false)
    && ["showChars","dismissedSoundsHint","mixChars","charsAfterHsk4","charsChoiceSeen","c"].every(f => p[f] === undefined));
  const again = VC.migrateLegacy(PACK, LEGACY, clone(p));
  check(`${name}: idempotent (second run already=true, same prog)`, again.ok && again.already === true && eq(again.prog, p) && !again.unmapped.length);
  const fromStr = VC.migrateLegacy(PACK, LEGACY, JSON.stringify(old));
  check(`${name}: string input gives the same result`, fromStr.ok && eq(fromStr.prog, p));
  const rep = diffMigration(clone(old), ZH, PC ? HSK : null);
  check(`${name}: tool roundtrip diff empty`, rep.ok && rep.roundtrip.length === 0);
  check(`${name}: tool totals before = after`, rep.ok && rep.totals.every(t => eq(t.before, t.after)));
  if(PC) check(`${name}: tool derived views match hsk (${rep.derived ? rep.derived.filter(d => !d.same).map(d => d.name).join(", ") || "all same" : "none"})`, rep.ok && rep.derived && rep.derived.every(d => d.same) && rep.pass);
  else skip(`${name}: derived views (no hsk checkout at ${HSK})`);
}

// hsk PINYIN_SPEC seed E (deferred, mid-HSK 4): sentence availability differs only by the
// accepted s0823 (分之 merged by pack_from_hsk; docs/HSK_MERGE.md §8), and the tool passes.
{
  const E = Object.assign(clone(HSK_FRESH), { sets:{1:nsets(1),2:nsets(2),3:nsets(3),4:7}, theme:"light", sessions:3, placedOnce:true, soundsOpened:true, charsAfterHsk4:true, charsChoiceSeen:true });
  if(PC){
    const rep = diffMigration(clone(E), ZH, HSK), v = rep.derived && rep.derived.find(d => /^available sentences/.test(d.name));
    check(`walk seed E: sentence availability compared, only s0823 differs (${v ? v.name : "missing"}), tool passes`,
      !!v && eq(v.hsk, ["s0823"]) && eq(v.engine, []) && v.same && rep.pass);
  } else skip("walk seed E: sentence availability (no hsk checkout)");
}

console.log("\n[2] seed-specific derived state on the engine side");
const W = WORDS, U = readJSON("characters.json");
const mig = n => VC.migrateLegacy(PACK, LEGACY, clone(SEEDS[n])).prog;
check("A empty: equals defaultProg plus the marker", eq(mig("A empty"), Object.assign(VC.defaultProg(PACK), { legacy: { key:"hsk_pinyin", format:"hsk-v2" } })));
check("C mid-HSK2: next stage is HSK 2 set 3", (s => s && s.kind === "words" && s.lv === "2" && s.set === 3)(VC.nextStage(PACK, W, U, mig("C mid-HSK2"))));
check("HEAD (HSK 1-3 done, card unanswered): choice card shows", VC.showCharChoice(PACK, W, U, mig("HEAD")) === true);
check("D1 (answered start): no card, next stage is characters 1-3", !VC.showCharChoice(PACK, W, U, mig("D1 chars started, card answered: start"))
  && (s => s && s.kind === "chars" && eq(s.levels, ["1","2","3"]))(VC.nextStage(PACK, W, U, mig("D1 chars started, card answered: start"))));
check("D2 (answered skip): no card, next stage is HSK 4", !VC.showCharChoice(PACK, W, U, mig("D2 chars started, card answered: skip"))
  && (s => s && s.kind === "words" && s.lv === "4")(VC.nextStage(PACK, W, U, mig("D2 chars started, card answered: skip"))));
check("D3 (order flipped): one deferred characters stage 1-4 after HSK 4", (p => { const cs = VC.stagePath(PACK, W, U, p).filter(s => s.kind === "chars"); return cs.length === 1 && eq(cs[0].levels, ["1","2","3","4"]); })(mig("D3 learning order flipped from Progress")));
check("E HSK4 complete: every stage done, characters started", VC.nextStage(PACK, W, U, mig("E HSK4 complete")) === null && VC.charsStarted(PACK, W, U, mig("E HSK4 complete")));
check("E HSK4 complete: all 1193 words learned", VC.learnedWords(W, PACK, mig("E HSK4 complete")).length === W.length);

console.log("\n[3] unmapped list");
{
  const [h1, h2] = byLv[1];
  const bad = { v:2, w:{ [h1]: { r:2, w:"1", s:1, x:9 }, "不存在的词": rec(1,0,1), [h2]: 5 },
    s:{ [SENTS[0]]: rec(1,0,1), "不存在的句子。": rec(1,0,1) }, c:{ [h1]: rec(1,0,1), "龘": rec(1,0,1) },
    sets:{ 1:2.5, 2:1, 5:1 }, theme:"blue", sessions:"7", mixChars:"yes", placedOnce:true, foo:{ bar:1 }, showChars:true };
  const res = VC.migrateLegacy(PACK, LEGACY, clone(bad));
  const paths = res.ok ? res.unmapped.map(u => u.path).sort() : [];
  const expect = [`w.${h1}.w`, `w.${h1}.x`, "w.不存在的词", `w.${h2}`, "s.不存在的句子。", "c.龘", "sets.1", "sets.5", "theme", "sessions", "mixChars", "foo"].sort();
  check(`unmapped lists exactly the bad parts (${paths.length})`, eq(paths, expect));
  check("each unmapped entry carries its original value and a reason", res.ok && res.unmapped.every(u => typeof u.reason === "string" && u.reason && eq(u.value, u.path.split(".").reduce((x, k) => x[k], bad))));
  check("valid parts of a partly bad record survive", res.ok && eq(res.prog.w[LEGACY.w[h1]], { r:2, s:1 }) && res.prog.sets["2"] === 1 && res.prog.sets["1"] === 0);
  check("the rest still maps (s, c, placedOnce) and output validates", res.ok && count(res.prog.s) === 1 && count(res.prog.chars.c) === 1 && res.prog.placedOnce === true && VC.validateProgShape(res.prog, VC.levelIds(PACK)).ok);
  check("defaults fill the unmapped scalars", res.ok && res.prog.theme === null && res.prog.sessions === 0 && res.prog.chars.mix === true);
  check("dropped is separate from unmapped", res.ok && eq(res.dropped, [{ path:"showChars", value:true }]));
  const notObj = VC.migrateLegacy(PACK, LEGACY, { w: [], s: "x", lessons: 3 });
  check("non-object buckets are reported whole", notObj.ok && eq(notObj.unmapped.map(u => u.path).sort(), ["lessons","s","w"]));
  const proto = VC.migrateLegacy(PACK, LEGACY, JSON.parse('{"w":{"__proto__":{"r":1}},"__proto__":{"x":1}}'));
  check("__proto__ keys are unmapped, never merged", proto.ok && eq(proto.unmapped.map(u => u.path).sort(), ["__proto__","w.__proto__"]) && ({}).r === undefined);
  const dupMap = { w: { a:"w0001", b:"w0001" }, s:{}, c:{} };
  const dup = VC.migrateLegacy(PACK, dupMap, { w:{ a: rec(1,0,1), b: rec(2,0,2) } });
  check("two keys on one id: the second is unmapped, the first kept", dup.ok && eq(dup.prog.w.w0001, rec(1,0,1)) && eq(dup.unmapped.map(u => u.path), ["w.b"]));
  const noChars = Object.assign(clone(PACK)); delete noChars.characters;
  const nc = VC.migrateLegacy(noChars, LEGACY, clone(SEEDS["D1 chars started, card answered: start"]));
  check("pack without characters: c and the three flags unmapped, no chars key", nc.ok && nc.prog.chars === undefined
    && eq(nc.unmapped.map(u => u.path).sort(), ["c","charsAfterHsk4","charsChoiceSeen","mixChars"]) && nc.unmapped.every(u => /characters/.test(u.reason)));
  const failRep = diffMigration(clone(bad), ZH, null);
  check("tool FAILs when anything is unmapped", failRep.ok && failRep.pass === false && failRep.unmapped.length === expect.length);
}

console.log("\n[4] rejections and helpers");
check("unknown legacy version rejected", (r => !r.ok && /version 3/.test(r.reason))(VC.migrateLegacy(PACK, LEGACY, { v:3 })));
check("array, null, number, bad JSON rejected", [[], null, 4, "{nope"].every(x => !VC.migrateLegacy(PACK, LEGACY, x).ok));
const noLegacy = clone(PACK); delete noLegacy.legacy;
check("pack without legacy rejected", !VC.migrateLegacy(noLegacy, LEGACY, {}).ok);
check("marked record that fails validation rejected, not re-migrated", !VC.migrateLegacy(PACK, LEGACY, { legacy:{ key:"hsk_pinyin" }, sets:{ 9:1 } }).ok);
check("legacyBackupKey is hsk_pinyin.bak", VC.legacyBackupKey(PACK) === "hsk_pinyin.bak");
check("storage keys differ (vocab_zh vs hsk_pinyin vs backup)", new Set([VC.storageKey(PACK), PACK.legacy.key, VC.legacyBackupKey(PACK)]).size === 3);
check("isLegacyRecord: every seed but A empty is legacy", Object.entries(SEEDS).filter(([n]) => n !== "A empty").every(([, s]) => VC.isLegacyRecord(PACK, LEGACY, s)));
check("isLegacyRecord: native and migrated progress are not", !VC.isLegacyRecord(PACK, LEGACY, VC.defaultProg(PACK)) && !VC.isLegacyRecord(PACK, LEGACY, mig("C mid-HSK2"))
  && !VC.isLegacyRecord(PACK, LEGACY, { v:1, w:{ w0001: rec(1,0,1) }, sets:{ 1:1 } }));
check("isLegacyRecord: false for a pack without legacy", !VC.isLegacyRecord(noLegacy, LEGACY, SEEDS["C mid-HSK2"]));
check("input record is not mutated", (() => { const o = clone(SEEDS["HEAD"]); VC.migrateLegacy(PACK, LEGACY, o); return eq(o, SEEDS["HEAD"]); })());

console.log(`\n${passes} passed, ${fails} failed, ${skips} skipped`);
process.exit(fails ? 1 : 0);
