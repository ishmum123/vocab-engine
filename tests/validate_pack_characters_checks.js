// Node checks for the "characters" stage tooling added by brief B1
// (docs/PACK_SCHEMA.md "characters" / "pack/characters.json" / sentences.json "ruby" /
// "legacy.json"): tools/validate_pack.py's new cases, tools/jsonify_pack.py emitting
// characters.js, and build.sh inlining it. These are schema/tooling checks only; the
// actual character-stage runtime logic (engine/core.js) is a later brief.
// Run: node tests/validate_pack_characters_checks.js
"use strict";
const fs = require("fs");
const path = require("path");
const os = require("os");
const cp = require("child_process");

const ROOT = path.join(__dirname, "..");
const PY = process.env.PYTHON3 || "python3";

let fails = 0, passes = 0;
function check(name, cond, extra){
  if(cond){ passes++; console.log(`PASS  ${name}`); }
  else { fails++; console.log(`FAIL  ${name}`); if(extra) console.log("    " + String(extra).replace(/\n/g, "\n    ")); }
}

function writeJSON(dir, stem, data){
  fs.writeFileSync(path.join(dir, stem + ".json"), JSON.stringify(data));
}

// A minimal, otherwise-valid base pack: 2 levels, 13 words each (enough for a 2-bucket
// placement with setSize 10: one set of 10, one set of 3), no sentences needed unless a
// test adds them.
function baseWords(){
  const words = [];
  for(const lv of ["1", "2"]){
    for(let i = 1; i <= 13; i++){
      words.push({ id: `w${lv}_${i}`, w: `word${lv}_${i}`, en: `gloss${lv}_${i}`, lv });
    }
  }
  return words;
}
function basePack(extra){
  return Object.assign({
    key: "synthchar", name: "Synth", tts: "en-US",
    levels: [{ id: "1", label: "One" }, { id: "2", label: "Two" }],
    placement: [["1", 2], ["2", 2]],
    showPron: false, hasLessons: false,
  }, extra);
}
function baseCharUnits(words, extra){
  return [
    Object.assign({ id: "c0001", t: "字A", words: [words[0].id], lv: "1" }, {}),
    Object.assign({ id: "c0002", t: "字B", words: [words[13].id], lv: "2" }, {}),
  ].map((u, i) => Object.assign(u, (extra || [])[i] || {}));
}
function baseCharacters(){
  return {
    label: "字", setSize: 10, mastered: 3, bare: 6,
    stages: [{ after: "1", levels: ["1"] }, { after: "2", levels: ["2"] }],
    learnKinds: ["charRead"], reviewKinds: ["charRead", "charSound"],
  };
}

function mkPack({ pack, words, sentences, characters, legacy } = {}){
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "ve_charpack_"));
  writeJSON(dir, "pack", pack !== undefined ? pack : basePack());
  writeJSON(dir, "words", words !== undefined ? words : baseWords());
  writeJSON(dir, "sentences", sentences !== undefined ? sentences : []);
  if(characters !== undefined) writeJSON(dir, "characters", characters);
  if(legacy !== undefined) writeJSON(dir, "legacy", legacy);
  return dir;
}

function runValidate(dir){
  // Regenerate the .js consts first, as a real workflow would: validate_pack.py itself
  // only checks they're in sync, it doesn't write them.
  cp.spawnSync(PY, [path.join(ROOT, "tools", "jsonify_pack.py"), dir], { cwd: ROOT });
  const r = cp.spawnSync(PY, [path.join(ROOT, "tools", "validate_pack.py"), dir], { cwd: ROOT, encoding: "utf8" });
  return { status: r.status, out: (r.stdout || "") + (r.stderr || "") };
}

console.log("Checking tools/validate_pack.py characters/legacy/ruby cases (Node harness, spawns python3)\n");

// ------------------------------------------------------------ valid baseline
(function(){
  const words = baseWords();
  const pack = basePack({ characters: baseCharacters() });
  const dir = mkPack({ pack, words });
  fs.writeFileSync(path.join(dir, "characters.json"), JSON.stringify(baseCharUnits(words)));
  const r = runValidate(dir);
  check("valid pack + characters.json + pack.characters validates cleanly", r.status === 0, r.out);
})();

// ------------------------------------------------------------ bad stage list / thresholds
(function(){
  const words = baseWords();
  const cases = [
    ["stages empty", { stages: [] }],
    ["stages missing 'levels'", { stages: [{ after: "1" }] }],
    ["stage.after not a pack level", { stages: [{ after: "9", levels: ["1"] }, { after: "2", levels: ["2"] }] }],
    ["stage.levels has unknown level", { stages: [{ after: "1", levels: ["1", "9"] }, { after: "2", levels: ["2"] }] }],
    ["a level covered by two stages", { stages: [{ after: "1", levels: ["1"] }, { after: "2", levels: ["1", "2"] }] }],
    ["stages out of pack.levels order", { stages: [{ after: "2", levels: ["2"] }, { after: "1", levels: ["1"] }] }],
    ["bare not greater than mastered", { mastered: 6, bare: 3 }],
    ["mastered not a positive int", { mastered: 0 }],
    ["learnKinds empty", { learnKinds: [] }],
    ["learnKinds has an unknown kind", { learnKinds: ["notAKind"] }],
    ["reviewKinds not a list", { reviewKinds: "charRead" }],
  ];
  for(const [name, patch] of cases){
    const characters = Object.assign(baseCharacters(), patch);
    const pack = basePack({ characters });
    const dir = mkPack({ pack, words });
    fs.writeFileSync(path.join(dir, "characters.json"), JSON.stringify(baseCharUnits(words)));
    const r = runValidate(dir);
    check(`rejects: ${name}`, r.status !== 0, r.out);
  }
})();

// ------------------------------------------------------------ dangling word ids in units
(function(){
  const words = baseWords();
  const dir = mkPack({ pack: basePack({ characters: baseCharacters() }), words });
  const units = baseCharUnits(words, [{ words: ["no_such_word"] }]);
  fs.writeFileSync(path.join(dir, "characters.json"), JSON.stringify(units));
  const r = runValidate(dir);
  check("rejects: characters.json unit with a dangling word id", r.status !== 0 && /unknown ids/.test(r.out), r.out);
})();

(function(){
  // unit.lv valid pack level but not covered by any stage
  const words = baseWords();
  const characters = Object.assign(baseCharacters(), { stages: [{ after: "1", levels: ["1"] }] }); // "2" uncovered
  const dir = mkPack({ pack: basePack({ characters }), words });
  fs.writeFileSync(path.join(dir, "characters.json"), JSON.stringify(baseCharUnits(words))); // unit c0002 has lv "2"
  const r = runValidate(dir);
  check("rejects: characters.json unit at a level no stage covers", r.status !== 0, r.out);
})();

// ------------------------------------------------------------ characters.json <-> pack.characters presence
(function(){
  const words = baseWords();
  const dir1 = mkPack({ pack: basePack({ characters: baseCharacters() }), words }); // block, no file
  const r1 = runValidate(dir1);
  check("rejects: pack.characters set but characters.json missing", r1.status !== 0 && /characters\.json is missing/.test(r1.out), r1.out);

  const dir2 = mkPack({ pack: basePack(), words }); // file, no block
  fs.writeFileSync(path.join(dir2, "characters.json"), JSON.stringify(baseCharUnits(words)));
  const r2 = runValidate(dir2);
  check("rejects: characters.json present but pack.characters not set", r2.status !== 0 && /pack\.characters is not set/.test(r2.out), r2.out);
})();

// ------------------------------------------------------------ overlapping / out-of-range ruby offsets
(function(){
  const words = baseWords();
  const pack = basePack({ characters: baseCharacters() });
  const sentences = (ruby) => [{ id: "s0001", t: "AB", en: "ab", lv: "1", words: [words[0].id, words[13].id], ruby }];
  const units = baseCharUnits(words); // words[0].id and words[13].id are words[0] of a unit each

  const cases = [
    ["out of range end", [[0, 5, "r", words[0].id]]],
    ["start >= end", [[1, 1, "r", words[0].id]]],
    ["overlapping ruby tuples", [[0, 2, "r1", words[0].id], [1, 2, "r2", words[13].id]]],
    ["ruby wordId not in sentence.words", [[0, 1, "r", "w1_99"]]],
    ["ruby wordId not words[0] of any unit", [[0, 1, "r", "w1_5"]]],
    ["ruby entry missing reading", [[0, 1, "", words[0].id]]],
  ];
  for(const [name, ruby] of cases){
    const dir = mkPack({ pack, words, sentences: sentences(ruby) });
    fs.writeFileSync(path.join(dir, "characters.json"), JSON.stringify(units));
    const r = runValidate(dir);
    check(`rejects: ${name}`, r.status !== 0, r.out);
  }

  // valid ruby, sorted and non-overlapping, both point at real unit words[0]s
  const dirOk = mkPack({ pack, words, sentences: sentences([[0, 1, "r1", words[0].id], [1, 2, "r2", words[13].id]]) });
  fs.writeFileSync(path.join(dirOk, "characters.json"), JSON.stringify(units));
  const rOk = runValidate(dirOk);
  check("accepts: valid, sorted, non-overlapping ruby", rOk.status === 0, rOk.out);
})();

// ------------------------------------------------------------ legacy.json
(function(){
  const words = baseWords();
  const pack1 = basePack({ legacy: { key: "old_app", format: "hsk-v2" } });
  const dir1 = mkPack({ pack: pack1, words }); // block, no file
  const r1 = runValidate(dir1);
  check("rejects: pack.legacy set but legacy.json missing", r1.status !== 0 && /legacy\.json is missing/.test(r1.out), r1.out);

  const dir2 = mkPack({ pack: basePack(), words, legacy: { w: { hanzi: words[0].id } } }); // file, no block
  const r2 = runValidate(dir2);
  check("rejects: legacy.json present but pack.legacy not set", r2.status !== 0 && /pack\.legacy is not set/.test(r2.out), r2.out);

  const dir3 = mkPack({ pack: pack1, words, legacy: { w: { hanzi: "no_such_word" } } });
  const r3 = runValidate(dir3);
  check("rejects: legacy.json.w maps to an unknown word id", r3.status !== 0, r3.out);

  const dir4 = mkPack({ pack: pack1, words, legacy: { w: { hanzi: words[0].id, hanzi2: words[0].id } } });
  const r4 = runValidate(dir4);
  check("warns (not error) on legacy.json.w mapping two keys to one id", r4.status === 0 && /WARN.*maps more than one key/.test(r4.out), r4.out);

  const dir5 = mkPack({ pack: pack1, words, legacy: { x: {} } });
  const r5 = runValidate(dir5);
  check("rejects: legacy.json with an unknown top-level key", r5.status !== 0, r5.out);
})();

// ------------------------------------------------------------ jsonify_pack.py emits characters.js
(function(){
  const words = baseWords();
  const dir = mkPack({ pack: basePack({ characters: baseCharacters() }), words });
  const units = baseCharUnits(words);
  fs.writeFileSync(path.join(dir, "characters.json"), JSON.stringify(units));
  const r = cp.spawnSync(PY, [path.join(ROOT, "tools", "jsonify_pack.py"), dir], { cwd: ROOT, encoding: "utf8" });
  const jsPath = path.join(dir, "characters.js");
  check("jsonify_pack.py writes characters.js when characters.json exists", r.status === 0 && fs.existsSync(jsPath), r.stdout + r.stderr);
  const body = fs.existsSync(jsPath) ? fs.readFileSync(jsPath, "utf8") : "";
  check("characters.js declares const CHARACTERS=", /const CHARACTERS=/.test(body));
  // a pack without characters.json gets no characters.js
  const dirNo = mkPack({ pack: basePack(), words });
  const r2 = cp.spawnSync(PY, [path.join(ROOT, "tools", "jsonify_pack.py"), dirNo], { cwd: ROOT, encoding: "utf8" });
  check("jsonify_pack.py emits no characters.js when characters.json is absent",
    r2.status === 0 && !fs.existsSync(path.join(dirNo, "characters.js")), r2.stdout + r2.stderr);
})();

// ------------------------------------------------------------ build.sh with/without characters.js
(function(){
  const words = baseWords();
  // Without: a valid pack with no characters block/file builds, and the output has no
  // CHARACTERS const (mirrors the existing PASSAGES/LESSONS convention).
  const dirNo = mkPack({ pack: basePack(), words });
  cp.spawnSync(PY, [path.join(ROOT, "tools", "jsonify_pack.py"), dirNo], { cwd: ROOT });
  const outNo = path.join(dirNo, "out.html");
  const rNo = cp.spawnSync("sh", [path.join(ROOT, "build.sh"), dirNo, outNo], { cwd: ROOT, encoding: "utf8" });
  check("build.sh succeeds for a pack without characters.js", rNo.status === 0 && fs.existsSync(outNo), rNo.stdout + rNo.stderr);
  const htmlNo = fs.existsSync(outNo) ? fs.readFileSync(outNo, "utf8") : "";
  check("built page has no CHARACTERS const when characters.js is absent", !/const CHARACTERS=/.test(htmlNo));

  // With: a valid pack with a characters block/file builds, and CHARACTERS is inlined.
  const pack = basePack({ characters: baseCharacters() });
  const dirYes = mkPack({ pack, words });
  fs.writeFileSync(path.join(dirYes, "characters.json"), JSON.stringify(baseCharUnits(words)));
  cp.spawnSync(PY, [path.join(ROOT, "tools", "jsonify_pack.py"), dirYes], { cwd: ROOT });
  const outYes = path.join(dirYes, "out.html");
  const rYes = cp.spawnSync("sh", [path.join(ROOT, "build.sh"), dirYes, outYes], { cwd: ROOT, encoding: "utf8" });
  check("build.sh succeeds for a pack with characters.js", rYes.status === 0 && fs.existsSync(outYes), rYes.stdout + rYes.stderr);
  const htmlYes = fs.existsSync(outYes) ? fs.readFileSync(outYes, "utf8") : "";
  check("built page inlines the CHARACTERS const when characters.js is present", /const CHARACTERS=/.test(htmlYes));
  check("built page's dev pack loader is gone (self-contained, as for any pack)", !htmlYes.includes("PACK-BEGIN"));

  // Real packs/zh (no characters.json) still builds identically either way: covered by
  // tests/engine_checks.js's [0] stale-build guard against dist/zh.html.
})();

// ------------------------------------------------------------ B8: stage levels vs after, unit lv vs words[0]
(function(){
  const words = baseWords();
  // A stage covering a level taught after its own position: levels ["1","2"] after "1".
  const late = Object.assign(baseCharacters(), { stages: [{ after: "1", levels: ["1", "2"] }] });
  const d1 = mkPack({ pack: basePack({ characters: late }), words });
  fs.writeFileSync(path.join(d1, "characters.json"), JSON.stringify(baseCharUnits(words)));
  const r1 = runValidate(d1);
  check("rejects: stage.levels entry after stage.after in pack.levels order", r1.status !== 0 && /after the stage's own position/.test(r1.out), r1.out);
  // Same levels, stage at the later level: fine.
  const ok = Object.assign(baseCharacters(), { stages: [{ after: "2", levels: ["1", "2"] }] });
  const d2 = mkPack({ pack: basePack({ characters: ok }), words });
  fs.writeFileSync(path.join(d2, "characters.json"), JSON.stringify(baseCharUnits(words)));
  const r2 = runValidate(d2);
  check("accepts: stage.levels all at or before stage.after", r2.status === 0, r2.out);
  // unit.lv differs from its words[0]'s level (both covered by a stage).
  const d3 = mkPack({ pack: basePack({ characters: baseCharacters() }), words });
  fs.writeFileSync(path.join(d3, "characters.json"), JSON.stringify(baseCharUnits(words, [null, { words: [words[1].id] }])));
  const r3 = runValidate(d3);
  check("rejects: unit.lv differs from the level of its words[0]", r3.status !== 0 && /c0002\.lv '2' differs from the level of its words\[0\] w1_2 \('1'\)/.test(r3.out), r3.out);
})();

// ------------------------------------------------------------ B8: pack.characters.testKinds
(function(){
  const words = baseWords();
  const run = tk => {
    const d = mkPack({ pack: basePack({ characters: Object.assign(baseCharacters(), { testKinds: tk }) }), words });
    fs.writeFileSync(path.join(d, "characters.json"), JSON.stringify(baseCharUnits(words)));
    return runValidate(d);
  };
  const good = run({ charRead: 40, charSound: 30, charPick: 30 });
  check("accepts: testKinds {charRead:40, charSound:30, charPick:30}", good.status === 0, good.out);
  for(const [name, tk] of [["an unknown kind", { charRead: 1, nope: 1 }], ["a zero weight", { charRead: 0 }], ["a list", ["charRead"]], ["empty", {}], ["a string weight", { charRead: "40" }]]){
    const r = run(tk);
    check(`rejects: testKinds with ${name}`, r.status !== 0 && /testKinds/.test(r.out), r.out);
  }
})();

// ------------------------------------------------------------ B8: passages[].sentences[].ruby
(function(){
  const words = baseWords();
  const pack = basePack({ characters: baseCharacters() });
  const units = baseCharUnits(words);
  const passage = ruby => [{ id: "p1", lv: "1", title: "T", text: "AB",
    sentences: [{ t: "AB", en: "ab", words: [words[0].id, words[13].id], ruby }],
    questions: [{ type: "tf", q: "q", answer: true, words: [words[0].id], sentence: 0 }] }];
  const runP = (ruby, pk) => {
    const d = mkPack({ pack: pk || pack, words });
    fs.writeFileSync(path.join(d, "characters.json"), JSON.stringify(units));
    fs.writeFileSync(path.join(d, "passages.json"), JSON.stringify(passage(ruby)));
    return runValidate(d);
  };
  const ok = runP([[0, 1, "r1", words[0].id], [1, 2, "r2", words[13].id]]);
  check("accepts: passage sentence with valid ruby", ok.status === 0, ok.out);
  const cases = [
    ["out of range end", [[0, 5, "r", words[0].id]], /out of bounds/],
    ["overlapping", [[0, 2, "r1", words[0].id], [1, 2, "r2", words[13].id]], /sorted and not overlap/],
    ["wordId not in the sentence's words", [[0, 1, "r", "w1_5"]], /not in the sentence's words/],
    ["missing reading", [[0, 1, "", words[0].id]], /non-empty strings/],
    ["not a list", "x", /must be a list/],
  ];
  for(const [name, ruby, re] of cases){
    const r = runP(ruby);
    check(`rejects: passage ruby ${name} (named at passage p1.sentences[0])`, r.status !== 0 && re.test(r.out) && /passage p1\.sentences\[0\]\.ruby/.test(r.out), r.out);
  }
  // A unit-less word in passage ruby: w1_5 in the sentence's words but no unit's words[0].
  const d = mkPack({ pack, words });
  fs.writeFileSync(path.join(d, "characters.json"), JSON.stringify(units));
  const p5 = passage([[0, 1, "r", "w1_5"]]); p5[0].sentences[0].words.push("w1_5");
  fs.writeFileSync(path.join(d, "passages.json"), JSON.stringify(p5));
  const r5 = runValidate(d);
  check("rejects: passage ruby wordId not words[0] of any unit", r5.status !== 0 && /not words\[0\] of any characters\.json unit/.test(r5.out), r5.out);
  // Without pack.characters: a warning, like sentences.json ruby.
  const d6 = mkPack({ pack: basePack(), words });
  fs.writeFileSync(path.join(d6, "passages.json"), JSON.stringify(passage([[0, 1, "r1", words[0].id]])));
  const r6 = runValidate(d6);
  check("warns: passage ruby without pack.characters is never rendered", r6.status === 0 && /WARN.*p1\.sentences\[0\]\.ruby present but pack\.characters is absent/.test(r6.out), r6.out);
})();

console.log(`\n${fails === 0 ? "ALL PASSED" : "FAILED"}: ${passes} passed, ${fails} failed`);
process.exit(fails === 0 ? 0 : 1);
