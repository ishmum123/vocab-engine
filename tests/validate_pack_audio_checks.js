// Node checks for tools/validate_pack.py's recorded-audio rules (docs/AUDIO.md,
// docs/PACK_SCHEMA.md): pack.audio {voice, version}, words[].audio,
// passages[].sentences[].audio, and the cross-file notes (pack.audio with no clip;
// relative clips without pack.audio). The synthetic pack is the fa fixture from
// tests/fixtures/script_packs.js plus one sentence and one passage; each negative case
// breaks one rule. The shipped sibling packs must report no audio lines at all.
// Run: node tests/validate_pack_audio_checks.js   (PYTHON3 overrides the interpreter)
"use strict";
const fs = require("fs");
const path = require("path");
const os = require("os");
const cp = require("child_process");

const ROOT = path.join(__dirname, "..");
const PY = process.env.PYTHON3 || "python3";
const FX = require(path.join(__dirname, "fixtures", "script_packs.js"));

let fails = 0, passes = 0;
function check(name, cond, extra){
  if(cond){ passes++; console.log(`PASS  ${name}`); }
  else { fails++; console.log(`FAIL  ${name}`); if(extra) console.log("    " + String(extra).replace(/\n/g, "\n    ").slice(0, 1200)); }
}
const tmpDirs = [];
function fixture(){
  const fx = FX.fa();
  const w0 = fx.words[0], w1 = fx.words[1];
  fx.sentences = [{ id: "s1", t: `${w0.w} ${w1.w}`, en: "a b", lv: "A1", words: [w0.id, w1.id] }];
  fx.passages = [{ id: "p1", lv: "A1", title: "t", text: `${w0.w}. ${w1.w}.`,
    sentences: [{ t: `${w0.w}.`, en: "a", words: [w0.id] }, { t: `${w1.w}.`, en: "b", words: [w1.id] }],
    questions: [{ q: "q", type: "tf", options: null, answer: true, words: [w0.id], sentence: 0 }] }];
  return fx;
}
// A language-repo layout: <tmp>/pack/*.json, and every relative clip URL in the fixture
// written as a file under <tmp>/ (the built page's directory) unless noFiles lists it.
function mkPack(fx, noFiles){
  const repo = fs.mkdtempSync(path.join(os.tmpdir(), "ve_audiopack_")); tmpDirs.push(repo);
  const dir = path.join(repo, "pack"); fs.mkdirSync(dir);
  const urls = [...fx.words, ...fx.sentences, ...fx.passages.flatMap(p => p.sentences), ...fx.script.units]
    .map(x => x && x.audio).filter(u => typeof u === "string" && u && !/^[a-z][a-z0-9+.-]*:/i.test(u));
  urls.filter(u => !(noFiles || []).includes(u)).forEach(u => { const f = path.join(repo, u); fs.mkdirSync(path.dirname(f), { recursive: true }); fs.writeFileSync(f, "clip"); });
  const w = (stem, data) => fs.writeFileSync(path.join(dir, stem + ".json"), JSON.stringify(data));
  w("pack", fx.pack); w("words", fx.words); w("sentences", fx.sentences); w("passages", fx.passages); w("script", fx.script);
  return dir;
}
function runValidate(dir){
  cp.spawnSync(PY, [path.join(ROOT, "tools", "jsonify_pack.py"), dir], { cwd: ROOT });
  const r = cp.spawnSync(PY, [path.join(ROOT, "tools", "validate_pack.py"), dir], { cwd: ROOT, encoding: "utf8" });
  return { status: r.status, out: (r.stdout || "") + (r.stderr || "") };
}
const audioLines = out => out.split("\n").filter(l => /^(ERROR|WARN)/.test(l) && /audio/.test(l));
function expectError(name, mutate, re){
  const fx = fixture(); mutate(fx);
  const r = runValidate(mkPack(fx));
  check(`${name}: fails`, r.status === 1 && re.test(r.out), r.out);
}
function expectWarn(name, mutate, re){
  const fx = fixture(); mutate(fx);
  const r = runValidate(mkPack(fx));
  check(`${name}: passes with a warning`, r.status === 0 && audioLines(r.out).length === 1 && re.test(r.out), r.out);
}
const withClips = fx => {
  fx.pack.audio = { voice: "fa_IR-ganji_adabi-medium", version: 1 };
  fx.words[0].audio = `audio/w/${fx.words[0].id}.opus`;
  fx.sentences[0].audio = "audio/s/s1.opus";
  fx.passages[0].sentences[1].audio = "audio/p/p1-1.opus";
  fx.script.units[0].audio = `audio/x/${fx.script.units[0].id}.opus`;
};

console.log("Checking tools/validate_pack.py recorded-audio rules (Node harness, spawns python3)\n");
{
  const r = runValidate(mkPack(fixture()));
  check("baseline fixture (no audio) validates with no audio lines", r.status === 0 && audioLines(r.out).length === 0, r.out);
  const fx = fixture(); withClips(fx);
  const r2 = runValidate(mkPack(fx));
  check("pack.audio + word, sentence, passage-sentence and unit clips: 0 errors, no audio lines", r2.status === 0 && audioLines(r2.out).length === 0, r2.out);
  const fx3 = fixture(); fx3.sentences[0].audio = "https://audio.tatoeba.org/sentences/pes/1.mp3";
  const r3 = runValidate(mkPack(fx3));
  check("an absolute (Tatoeba) sentence URL without pack.audio: no audio lines", r3.status === 0 && audioLines(r3.out).length === 0, r3.out);
}
expectError("pack.audio not an object", fx => { withClips(fx); fx.pack.audio = "ganji"; }, /pack\.audio must be an object/);
expectError("pack.audio.voice empty", fx => { withClips(fx); fx.pack.audio.voice = ""; }, /pack\.audio\.voice must be a non-empty string/);
expectError("pack.audio.voice missing", fx => { withClips(fx); delete fx.pack.audio.voice; }, /pack\.audio\.voice must be a non-empty string/);
for(const v of [0, "1", true, 1.5, null]){
  expectError(`pack.audio.version ${JSON.stringify(v)}`, fx => { withClips(fx); fx.pack.audio.version = v; }, /pack\.audio\.version must be an integer >= 1/);
}
expectWarn("pack.audio with an unknown key", fx => { withClips(fx); fx.pack.audio.bitrate = "24k"; }, /pack\.audio has unknown keys \['bitrate'\]/);
expectError("words[].audio empty string", fx => { fx.words[2].audio = ""; }, /word \S+\.audio must be a non-empty string/);
expectError("words[].audio not a string", fx => { fx.words[2].audio = 7; }, /word \S+\.audio must be a non-empty string/);
expectError("sentences[].audio empty string", fx => { fx.sentences[0].audio = ""; }, /sentence\S*\.audio must be a non-empty string|\.audio must be a non-empty string/);
expectError("passages[].sentences[].audio not a string", fx => { fx.passages[0].sentences[0].audio = ["x"]; }, /passage p1\.sentences\[0\]\.audio must be a non-empty string/);
expectWarn("pack.audio set but no clip anywhere", fx => { fx.pack.audio = { voice: "v", version: 1 }; }, /pack\.audio is set but no word, sentence or script unit has audio/);
expectWarn("relative clips without pack.audio", fx => { withClips(fx); delete fx.pack.audio; }, /relative audio URLs but pack\.audio is not set/);
{
  const fx = fixture(); withClips(fx);
  const r = runValidate(mkPack(fx, [fx.words[0].audio, "audio/s/s1.opus"]));
  check("relative clips whose file is missing beside the site page: passes with one warning naming them",
    r.status === 0 && audioLines(r.out).length === 1 && /2 relative audio URLs have no file beside the site page/.test(r.out) && r.out.includes(fx.words[0].audio), r.out);
  const fx2 = fixture(); fx2.pack.audio = { voice: "v", version: 1 }; fx2.script.units[0].audio = `audio/x/${fx2.script.units[0].id}.0123abcd.opus`;
  const r2 = runValidate(mkPack(fx2));
  check("pack.audio with only script-unit clips (an x-only render): no 'no clip' warning", r2.status === 0 && audioLines(r2.out).length === 0, r2.out);
}

// Shipped sibling packs: the new rules add nothing (none ships generated audio yet).
for(const name of ["italian", "spanish", "french", "german", "russian", "persian", "indonesian", "korean", "japanese"]){
  const dir = path.join(ROOT, "..", name, "pack");
  if(!fs.existsSync(path.join(dir, "pack.json"))){ console.log(`NOTE  ../${name}/pack missing, skipped`); continue; }
  const r = cp.spawnSync(PY, [path.join(ROOT, "tools", "validate_pack.py"), dir], { cwd: ROOT, encoding: "utf8" });
  const out = (r.stdout || "") + (r.stderr || "");
  check(`shipped ../${name}/pack: valid, no audio lines`, r.status === 0 && audioLines(out).length === 0, out.split("\n").slice(-3).join("\n"));
}
{
  const r = runValidate(path.join(ROOT, "packs", "zh"));
  check("shipped packs/zh: valid, no audio lines", r.status === 0 && audioLines(r.out).length === 0, r.out);
}

tmpDirs.forEach(d => fs.rmSync(d, { recursive: true, force: true }));
console.log(`\n${fails ? "FAILED" : "ALL PASSED"}: ${passes} passed, ${fails} failed`);
process.exit(fails ? 1 : 0);
