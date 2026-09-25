#!/usr/bin/env node
// Acceptance evidence for the hsk_pinyin -> vocab_zh switch (design: docs/HSK_MERGE.md §4).
// Migrates an hsk Progress -> Export file with core.js migrateLegacy and prints:
//   1. per record type (w, s, c): old count, mapped, unmapped
//   2. flags and scalars: old value -> new path and value
//   3. r/w/s totals (right, wrong, streak) per record type, before vs after
//   4. roundtrip: prog reverse-mapped to the hsk shape, diffed against the export
//   5. a sample of 10 mapped words
//   6. derived views, when the hsk checkout is found: hsk src/pinyin_core.js on the old
//      record vs core.js on the new one (learned words and mastered counts per level,
//      the stage path, next stage, characters started, choice card, available sentences:
//      hsk's pinyin_app.html rule re-stated over data/hsk_sentences.js vs VC.availableSentences)
// Exit 0 only when nothing is unmapped and the roundtrip and derived diffs are empty.
//
// Usage: node tools/diff_hsk_migration.js <hsk_pinyin_progress.json> [packdir] [--hsk <hsk repo>] [--json]
//   packdir defaults to packs/zh; --hsk defaults to ../hsk beside this repo (skipped if absent).
"use strict";
const fs = require("fs");
const path = require("path");
const util = require("util");

const ROOT = path.join(__dirname, "..");
const VC = require(path.join(ROOT, "engine", "core.js"));
const USAGE = "usage: node tools/diff_hsk_migration.js <hsk_pinyin_progress.json> [packdir] [--hsk <hsk repo>] [--json]";

const readJSON = f => JSON.parse(fs.readFileSync(f, "utf8"));
function loadPack(dir){
  const opt = f => fs.existsSync(path.join(dir, f)) ? readJSON(path.join(dir, f)) : [];
  return { pack: readJSON(path.join(dir, "pack.json")), words: readJSON(path.join(dir, "words.json")),
    units: opt("characters.json"), sentences: opt("sentences.json"), legacy: readJSON(path.join(dir, "legacy.json")) };
}
function loadHsk(dir){
  if(!dir) return null;
  const core = path.join(dir, "src", "pinyin_core.js"), vocab = path.join(dir, "data", "hsk_vocab.json");
  if(!fs.existsSync(core) || !fs.existsSync(vocab)) return null;
  const sf = path.join(dir, "data", "hsk_sentences.js");
  const S = fs.existsSync(sf) ? new Function(fs.readFileSync(sf, "utf8") + "\nreturn { SENTENCES, SENTENCE_EXTRA };")() : null;
  return { PC: require(core), VOCAB: readJSON(vocab), SENTENCES: S && S.SENTENCES, SENTENCE_EXTRA: S && S.SENTENCE_EXTRA };
}
const invert = m => { const o = {}; for(const k of Object.keys(m || {})) o[m[k]] = k; return o; };
const isObj = x => !!x && typeof x === "object" && !Array.isArray(x);

// prog back into the hsk record shape (dropped fields and the marker left out).
function reverseMap(prog, legacy){
  const iw = invert(legacy.w), is = invert(legacy.s), ic = invert(legacy.c);
  const back = (src, inv) => { const o = {}; for(const id of Object.keys(src || {})) o[inv[id] !== undefined ? inv[id] : "?" + id] = src[id]; return o; };
  const out = { w: back(prog.w, iw), s: back(prog.s, is), sets: prog.sets, lessons: prog.lessons, sessions: prog.sessions,
    theme: prog.theme, placedOnce: prog.placedOnce };
  if(prog.soundsOpened !== undefined) out.soundsOpened = prog.soundsOpened;
  if(prog.chars){ out.c = back(prog.chars.c, ic); out.mixChars = prog.chars.mix; out.charsAfterHsk4 = prog.chars.defer; out.charsChoiceSeen = prog.chars.choiceSeen; }
  return out;
}
// Old fields absent from the export take hsk's own defaults (PC.migrateProg), so a v1
// record compares against what hsk itself would show; defaults the new side adds for a
// field hsk never had (placedOnce) compare against the engine default.
const HSK_DEFAULTS = { w:{}, s:{}, c:{}, sets:{1:0,2:0,3:0,4:0}, lessons:{}, sessions:0, theme:null, placedOnce:false,
  mixChars:true, charsAfterHsk4:false, charsChoiceSeen:false };
function roundtripDiff(old, prog, legacy, skipPaths){
  const back = reverseMap(prog, legacy), diffs = [];
  const skip = p => skipPaths.some(s => p === s || p.startsWith(s + "."));
  for(const k of Object.keys(back)){
    let a = old[k] !== undefined ? old[k] : HSK_DEFAULTS[k];
    const b = back[k];
    if(k === "sets"){ a = Object.assign({}, HSK_DEFAULTS.sets, a || {}); }
    if(isObj(a) && isObj(b) && ["w","s","c","sets","lessons"].includes(k)){
      for(const r of new Set([...Object.keys(a), ...Object.keys(b)])){
        const p = `${k}.${r}`; if(skip(p)) continue;
        if(!util.isDeepStrictEqual(a[r], b[r])){
          if(isObj(a[r]) && isObj(b[r])){
            const fa = Object.assign({}, a[r]), fb = Object.assign({}, b[r]);
            for(const f of Object.keys(fa)) if(skip(`${p}.${f}`)) delete fa[f];
            if(util.isDeepStrictEqual(fa, fb)) continue;
          }
          diffs.push({ path: p, old: a[r], back: b[r] });
        }
      }
    } else if(!skip(k) && !util.isDeepStrictEqual(a, b)) diffs.push({ path: k, old: a, back: b });
  }
  return diffs;
}
const sumRWS = recs => { const t = { n:0, r:0, w:0, s:0 }; for(const k of Object.keys(recs || {})){ const p = recs[k] || {}; t.n++; for(const f of ["r","w","s"]) if(typeof p[f] === "number") t[f] += p[f]; } return t; };

// hsk pinyin_core.js on the old record vs core.js on the new one.
function derivedDiff(old, prog, P, hsk){
  const { PC, VOCAB } = hsk, L = P.legacy;
  const hp = PC.migrateProg(JSON.parse(JSON.stringify(old)));
  const levelList = lv => VOCAB.filter(v => v.lv === lv);
  const nsets = {}; [1,2,3,4].forEach(lv => { nsets[lv] = Math.ceil(levelList(lv).length / 10); });
  const hskLearned = () => { const out = []; [1,2,3,4].forEach(lv => out.push(...levelList(lv).slice(0, (hp.sets[lv]||0)*10)));
    const seen = new Set(out.map(v => v.w)); VOCAB.forEach(v => { if(!seen.has(v.w) && hp.w[v.w] && hp.w[v.w].d){ out.push(v); seen.add(v.w); } }); return out; };
  const views = [];
  const cmp = (name, a, b) => views.push({ name, hsk: a, engine: b, same: util.isDeepStrictEqual(a, b) });
  const hL = hskLearned().map(v => L.w[v.w] || "?" + v.w), eL = VC.learnedWords(P.words, P.pack, prog).map(w => w.id);
  cmp("learned words (ordered ids)", hL, eL);
  const lvOf = {}; P.words.forEach(w => { lvOf[w.id] = String(w.lv); });
  const perLv = (ids, recs) => { const o = {}; VC.levelIds(P.pack).forEach(l => { o[l] = { learned:0, mastered:0 }; });
    ids.forEach(id => { const l = lvOf[id]; if(!o[l]) return; o[l].learned++; if(((recs[id]||{}).s||0) >= VC.WORD_MASTERED) o[l].mastered++; }); return o; };
  const hRecs = {}; Object.keys(hp.w).forEach(k => { if(L.w[k]) hRecs[L.w[k]] = hp.w[k]; });
  cmp("learned / mastered per level", perLv(hL, hRecs), perLv(eL, prog.w));
  const hStage = s => s && (s.kind === "words" ? { kind:"words", lv:String(s.lv), frac:s.frac, done:s.done } : { kind:"chars", levels:s.levels.map(String), frac:s.frac, done:s.done });
  cmp("stage path (kind, levels, fraction, done)", PC.stagePath(hp, nsets, VOCAB).map(hStage), VC.stagePath(P.pack, P.words, P.units, prog).map(hStage));
  cmp("next stage", hStage(PC.nextStage(hp, nsets, VOCAB)), hStage(VC.nextStage(P.pack, P.words, P.units, prog)));
  cmp("characters started", PC.charsStarted(hp, nsets, VOCAB), VC.charsStarted(P.pack, P.words, P.units, prog));
  cmp("choice card shown", PC.showCharChoice(hp, nsets, VOCAB), VC.showCharChoice(P.pack, P.words, P.units, prog));
  if(hsk.SENTENCES){
    // hsk pinyin_app.html availableSentences: every word learned (a SENTENCE_EXTRA compound
    // counts via its base) or the current level (first level with an untaught set, 5 when
    // none) is past the sentence's. Compared as the set of engine sentence ids.
    const lw = new Set(hskLearned().map(v => v.w)), EX = hsk.SENTENCE_EXTRA || {};
    const nn = [1,2,3,4].find(lv => (hp.sets[lv]||0) < nsets[lv]), curLv = nn || 5;
    const ok = s => (s.words||[]).every(w => lw.has(w) || (EX[w] && lw.has(EX[w].base))) || curLv > s.lv;
    const hA = new Set(hsk.SENTENCES.filter(ok).map(s => L.s[s.zh] || "?" + s.zh));
    const eA = new Set(VC.availableSentences(P.sentences, P.words, P.pack, prog).map(s => s.id));
    const only = (a, b) => [...a].filter(x => !b.has(x)).sort();
    const diff = { hskOnly: only(hA, eA), engineOnly: only(eA, hA) };
    // Accepted (docs/HSK_MERGE.md §8): pack_from_hsk merges 分+之 into the HSK 4 word 分之,
    // so s0823 needs 分之 learned in the engine and only 分 and 之 in hsk.
    const ACCEPTED = new Set(["s0823"]);
    const unexplained = [...diff.hskOnly, ...diff.engineOnly].filter(id => !ACCEPTED.has(id));
    views.push({ name: `available sentences (hsk ${hA.size}, engine ${eA.size}; accepted: s0823 分之)`, hsk: diff.hskOnly, engine: diff.engineOnly, same: unexplained.length === 0 });
  }
  return views;
}

// Report object for one export (also used by tests/migration_checks.js).
function diffMigration(raw, packDir, hskDir){
  const P = loadPack(packDir);
  const old = typeof raw === "string" ? JSON.parse(raw) : raw;
  const res = VC.migrateLegacy(P.pack, P.legacy, old);
  if(!res.ok) return { ok:false, reason: res.reason };
  const prog = res.prog;
  const unmappedBy = b => res.unmapped.filter(u => u.path === b || u.path.startsWith(b + ".")).length;
  const recordKeysUnmapped = b => res.unmapped.filter(u => u.path.split(".").length === 2 && u.path.startsWith(b + ".")).length;
  const records = ["w","s","c"].map(b => {
    const n = isObj(old[b]) ? Object.keys(old[b]).length : 0;
    const after = b === "c" ? (prog.chars ? prog.chars.c : {}) : prog[b];
    return { type: b, old: n, mapped: Object.keys(after || {}).length, unmappedRecords: recordKeysUnmapped(b), unmappedPaths: unmappedBy(b) };
  });
  const flagRows = [
    ["v","v"], ["sets","sets"], ["lessons","lessons"], ["sessions","sessions"], ["theme","theme"], ["placedOnce","placedOnce"],
    ["soundsOpened","soundsOpened"], ["mixChars","chars.mix"], ["charsAfterHsk4","chars.defer"], ["charsChoiceSeen","chars.choiceSeen"],
    ["showChars","(dropped)"], ["dismissedSoundsHint","(dropped)"], [null,"showPron"], [null,"legacy"],
  ].map(([o, n]) => {
    const get = p => p.split(".").reduce((x, k) => x == null ? undefined : x[k], prog);
    return { old: o, oldValue: o ? old[o] : undefined, new: n, newValue: n.startsWith("(") ? undefined : get(n) };
  });
  const totals = ["w","s","c"].map(b => ({ type: b, before: sumRWS(old[b]), after: sumRWS(b === "c" ? (prog.chars||{}).c : prog[b]) }));
  const skipPaths = [...res.unmapped.map(u => u.path)];
  const roundtrip = roundtripDiff(old, prog, P.legacy, skipPaths);
  const byId = {}; P.words.forEach(w => { byId[w.id] = w; });
  const sample = Object.keys(isObj(old.w) ? old.w : {}).filter(k => P.legacy.w[k]).slice(0, 10)
    .map(k => ({ hanzi: k, id: P.legacy.w[k], en: (byId[P.legacy.w[k]] || {}).en, old: old.w[k], new: prog.w[P.legacy.w[k]] }));
  const hsk = loadHsk(hskDir);
  const derived = hsk ? derivedDiff(old, prog, P, hsk) : null;
  const pass = res.unmapped.length === 0 && roundtrip.length === 0 && (!derived || derived.every(d => d.same));
  return { ok:true, pass, records, flags: flagRows, totals, unmapped: res.unmapped, dropped: res.dropped, roundtrip, sample,
    derived, derivedSkipped: !hsk, already: res.already, prog };
}

function print(rep){
  const j = x => x === undefined ? "-" : JSON.stringify(x);
  console.log("Records");
  rep.records.forEach(r => console.log(`  ${r.type}: ${r.old} old, ${r.mapped} mapped, ${r.unmappedRecords} unmapped records, ${r.unmappedPaths} unmapped paths`));
  console.log("Flags and scalars");
  rep.flags.forEach(f => console.log(`  ${f.old || "(new)"} ${j(f.oldValue)} -> ${f.new} ${j(f.newValue)}`));
  console.log("Totals (records, right, wrong, streak)");
  rep.totals.forEach(t => console.log(`  ${t.type}: before n=${t.before.n} r=${t.before.r} w=${t.before.w} s=${t.before.s} | after n=${t.after.n} r=${t.after.r} w=${t.after.w} s=${t.after.s}${util.isDeepStrictEqual(t.before, t.after) ? "" : "  DIFFERS"}`));
  console.log(`Unmapped: ${rep.unmapped.length}`);
  rep.unmapped.slice(0, 20).forEach(u => console.log(`  ${u.path} = ${j(u.value)} (${u.reason})`));
  if(rep.unmapped.length > 20) console.log(`  ... ${rep.unmapped.length - 20} more`);
  console.log(`Dropped on purpose: ${rep.dropped.map(d => `${d.path}=${j(d.value)}`).join(", ") || "none"}`);
  console.log(`Roundtrip differences: ${rep.roundtrip.length}`);
  rep.roundtrip.slice(0, 20).forEach(d => console.log(`  ${d.path}: old ${j(d.old)} back ${j(d.back)}`));
  console.log("Sample mapped words");
  rep.sample.forEach(s => console.log(`  ${s.hanzi} -> ${s.id} (${s.en}): ${j(s.old)} -> ${j(s.new)}`));
  if(rep.derivedSkipped) console.log("Derived views: skipped (hsk checkout not found, pass --hsk <dir>)");
  else { console.log("Derived views (hsk pinyin_core.js vs core.js)"); rep.derived.forEach(d => console.log(`  ${d.same ? "same" : "DIFF"}  ${d.name}${d.same ? "" : `\n    hsk    ${j(d.hsk)}\n    engine ${j(d.engine)}`}`)); }
  if(rep.already) console.log("Note: the file already carries the migration marker; migrateLegacy returned it unchanged.");
  console.log(rep.pass ? "RESULT: PASS" : "RESULT: FAIL");
}

if(require.main === module){
  const args = process.argv.slice(2);
  const flag = n => { const i = args.indexOf(n); if(i < 0) return null; const v = args[i+1]; args.splice(i, 2); return v; };
  const asJson = args.includes("--json"); if(asJson) args.splice(args.indexOf("--json"), 1);
  const hskArg = flag("--hsk");
  if(!args.length || args.length > 2){ console.error(USAGE); process.exit(2); }
  const packDir = path.resolve(args[1] || path.join(ROOT, "packs", "zh"));
  const hskDir = hskArg ? path.resolve(hskArg) : path.join(ROOT, "..", "hsk");
  let raw; try { raw = fs.readFileSync(args[0], "utf8"); } catch(e){ console.error(`cannot read ${args[0]}: ${e.message}`); process.exit(2); }
  let rep; try { rep = diffMigration(raw, packDir, hskDir); } catch(e){ console.error(`failed: ${e.message}`); process.exit(2); }
  if(!rep.ok){ console.error(`migrateLegacy refused the file: ${rep.reason}`); process.exit(1); }
  if(asJson){ const o = Object.assign({}, rep); delete o.prog; console.log(JSON.stringify(o, null, 1)); } else print(rep);
  process.exit(rep.pass ? 0 : 1);
}
module.exports = { diffMigration, reverseMap, USAGE };
