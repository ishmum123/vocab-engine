// Node checks for the script primer's tooling (docs/SCRIPT_PRIMER.md §6 check 10, brief
// S1): tools/validate_pack.py's script.json / pack.script rules, tools/jsonify_pack.py
// emitting script.js, and build.sh inlining it. Synthetic packs from
// tests/fixtures/script_packs.js are written to temp dirs; each negative case breaks one
// rule of an otherwise valid pack.
// Run: node tests/validate_pack_script_checks.js   (PYTHON3 overrides the interpreter)
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
function mkPack({ pack, words, script }){
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "ve_scriptpack_")); tmpDirs.push(dir);
  const w = (stem, data) => fs.writeFileSync(path.join(dir, stem + ".json"), JSON.stringify(data));
  w("pack", pack); w("words", words); w("sentences", []);
  if(script !== undefined) w("script", script);
  return dir;
}
function runValidate(dir){
  cp.spawnSync(PY, [path.join(ROOT, "tools", "jsonify_pack.py"), dir], { cwd: ROOT });
  const r = cp.spawnSync(PY, [path.join(ROOT, "tools", "validate_pack.py"), dir], { cwd: ROOT, encoding: "utf8" });
  return { status: r.status, out: (r.stdout || "") + (r.stderr || "") };
}
// Breaks one thing in a fresh fixture and expects an ERROR line matching `re`.
function expectError(name, fixture, mutate, re){
  const fx = FX[fixture](); mutate(fx);
  const r = runValidate(mkPack(fx));
  check(`${name}: fails`, r.status === 1 && re.test(r.out), r.out);
}
const unit = (fx, id) => fx.script.units.find(u => u.id === id);

console.log("Checking tools/validate_pack.py script primer cases (Node harness, spawns python3)\n");

// ------------------------------------------------------------ valid baselines
for(const k of ["ko", "fa", "ja"]){
  const dir = mkPack(FX[k]()); const r = runValidate(dir);
  check(`${k}-like fixture validates clean (0 errors)`, r.status === 0 && / 0 errors/.test(r.out), r.out);
  check(`${k}-like: OK line counts script units`, /\d+ script units;/.test(r.out), r.out);
  check(`${k}-like: script.js generated as const SCRIPT`, fs.existsSync(path.join(dir, "script.js")) && /^const SCRIPT=\{/m.test(fs.readFileSync(path.join(dir, "script.js"), "utf8")));
}
{
  const r = runValidate(path.join(ROOT, "packs", "zh"));
  check("shipped packs/zh passes with no script line", r.status === 0 && !/script/i.test(r.out), r.out);
}
for(const name of ["korean", "russian", "persian", "japanese"]){
  const dir = path.join(ROOT, "..", name, "pack");
  if(!fs.existsSync(path.join(dir, "pack.json"))){ console.log(`NOTE  ../${name}/pack missing, skipped`); continue; }
  const pack = JSON.parse(fs.readFileSync(path.join(dir, "pack.json"), "utf8"));
  const r = cp.spawnSync(PY, [path.join(ROOT, "tools", "validate_pack.py"), dir], { cwd: ROOT, encoding: "utf8" });
  const out = (r.stdout || "") + (r.stderr || "");
  // Sibling packs are validated read-only (no jsonify). Only the script rules are judged
  // here: no script error on a pack without pack.script and without script.json.
  check(`sibling ${name}: no script-primer error (pack.script ${"script" in pack ? "set" : "absent"})`, !/ERROR .*script/i.test(out), out.split("\n").filter(l => /script/i.test(l)).join("\n"));
}

// ------------------------------------------------------------ §6 check 10 cases
expectError("dangling confuse id", "ko", fx => { unit(fx, "ko-a").confuse = ["ko-nope"]; }, /ERROR script unit ko-a\.confuse has unknown or self ids \['ko-nope'\]/);
expectError("ex glyph not in the word", "ko", fx => { unit(fx, "ko-a").ex = [[fx.words.find(w => w.w === "너").id, "neo"]]; }, /ERROR script unit ko-a\.ex\[0\]: the unit's glyph 'ㅏ' does not occur/);
expectError("syll.parts from a later set", "ko", fx => { unit(fx, "ko-n").syll = [{ t: "나", parts: ["ㄴ", "ㅋ"], roman: "na" }]; }, /ERROR script unit ko-n\.syll\[0\]\.parts \['ㅋ'\] are not glyphs of units at or before set 2/);
expectError("non-contiguous set", "ko", fx => { fx.script.units.filter(u => u.set === 3).forEach(u => { u.set = 4; }); }, /ERROR script stage 'hangul' sets \[1, 2, 4\] are not contiguous from 1/);
expectError("joins in a non-RTL pack", "ko", fx => { unit(fx, "ko-a").joins = "dual"; }, /ERROR script unit ko-a\.joins is set but pack\.rtl is not true/);
expectError("script.json without pack.script", "ko", fx => { delete fx.pack.script; }, /ERROR script\.json is present but pack\.script is not set/);
// further §3 rules
expectError("pack.script without script.json", "ko", fx => { fx.script = undefined; }, /ERROR pack\.script is set but script\.json is missing/);
expectError("duplicate unit id", "ko", fx => { unit(fx, "ko-eo").id = "ko-a"; }, /ERROR script unit id 'ko-a' duplicated/);
expectError("bad unit id pattern", "ko", fx => { unit(fx, "ko-a").id = "Korean_A"; }, /ERROR script unit id 'Korean_A' must match/);
expectError("unknown stage key", "ko", fx => { unit(fx, "ko-a").st = "latin"; }, /ERROR script unit ko-a\.st 'latin' is not a pack\.script\.stages key/);
expectError("set not a positive int", "ko", fx => { unit(fx, "ko-a").set = 0; }, /ERROR script unit ko-a\.set must be an integer >= 1/);
expectError("empty roman", "ko", fx => { unit(fx, "ko-a").roman = ""; }, /ERROR script unit ko-a\.roman must be a non-empty string/);
expectError("sound not a bool", "ko", fx => { unit(fx, "ko-ng").sound = "no"; }, /ERROR script unit ko-ng\.sound must be a boolean/);
expectError("unknown base", "ja", fx => { unit(fx, "ja-ga").base = "ja-zz"; }, /ERROR script unit ja-ga\.base 'ja-zz' is not a known unit id/);
expectError("ex word unknown", "ko", fx => { unit(fx, "ko-a").ex = [["nope", "na"]]; }, /ERROR script unit ko-a\.ex\[0\] word 'nope' is not a word id/);
expectError("ex word after the second level", "ko", fx => {
  fx.pack.levels.push({ id: "B1", label: "B1" }); fx.words.forEach((w, i) => { if(w.lv === "A2" && i % 2) w.lv = "B1"; });
  const w = fx.words.find(x => x.lv === "B1" && x.w.includes("아") === false && /[나다라마바사]/.test(x.w)) || fx.words.find(x => x.lv === "B1");
  w.w = "나" + w.w; unit(fx, "ko-a").ex = [[w.id, "na"]];
}, /ERROR script unit ko-a\.ex\[0\] word \S+ is level 'B1', after the second level/);
// A later stage (ja katakana) may take a third-level example as a last resort:
// a warning there, still an error for a first-stage unit.
function jaWithB1(){
  const fx = FX.ja(); fx.pack.levels.push({ id: "B1", label: "B1" });
  fx.words.push({ id: "jB1_01", w: "カメラ", en: "camera", lv: "B1", pron: "カメラ" },
                { id: "jB1_02", w: "傘", en: "umbrella", lv: "B1", pron: "かさ" });
  return fx;
}
expectError("ex word from the third level on a first-stage unit", "ja", fx => {
  Object.assign(fx, jaWithB1()); unit(fx, "ja-ka").ex = [["jB1_02", "kasa"]];
}, /ERROR script unit ja-ka\.ex\[0\] word jB1_02 is level 'B1', after the second level/);
{
  const fx = jaWithB1(); unit(fx, "ja-ka-ka").ex = [["jB1_01", "kamera"]];
  const r = runValidate(mkPack(fx));
  check("later stage: ex word from the third level is a warning", r.status === 0 &&
    /WARN  script unit ja-ka-ka\.ex\[0\] word jB1_01 is from level 'B1', the third level/.test(r.out) && !/ERROR/.test(r.out), r.out);
}
// A later stage's syllable may be attested in the other kana (キャ by きゃく); the first
// stage's may not.
function jaWithKyaku(){
  const fx = FX.ja(); fx.words.push({ id: "jA1_kyaku", w: "客", en: "guest", lv: "A1", pron: "きゃく" }); return fx;
}
expectError("first-stage syll.t only in the other kana", "ja", fx => {
  Object.assign(fx, jaWithKyaku()); unit(fx, "ja-ki").syll = [{ t: "キャ", parts: ["き"], roman: "kya" }];
}, /ERROR script unit ja-ki\.syll\[0\]\.t 'キャ' does not occur in any first-level word/);
{
  const fx = jaWithKyaku(); unit(fx, "ja-ka-ki").syll = [{ t: "キャ", parts: ["キ"], roman: "kya" }];
  const r = runValidate(mkPack(fx));
  check("later stage: syll.t attested in the other kana passes", r.status === 0 && !/syll/.test(r.out), r.out);
}
expectError("syll.t not in a first-level word", "ko", fx => { unit(fx, "ko-n").syll = [{ t: "노", parts: ["ㄴ", "ㅗ"], roman: "no" }]; }, /ERROR script unit ko-n\.syll\[0\]\.t '노' does not occur in any first-level word/);
expectError("joins bad value", "fa", fx => { unit(fx, "fa-be").joins = "left"; }, /ERROR script unit fa-be\.joins must be one of/);
expectError("note on an unknown stage set", "ko", fx => { fx.script.notes.push({ st: "hangul", set: 9, h: "x", body: "y" }); }, /ERROR script notes\[1\] \('hangul', set 9\) is not a known stage set/);
expectError("stage with no units", "ja", fx => { fx.pack.script.stages.push({ key: "extra", label: "Extra" }); }, /ERROR pack\.script stage 'extra' has no units in script\.json/);
expectError("unknown learnKind", "ko", fx => { fx.pack.script.learnKinds = ["charRead"]; }, /ERROR pack\.script\.learnKinds must be a non-empty list drawn from/);
expectError("tts not a bool", "ko", fx => { fx.pack.script.tts = "no"; }, /ERROR pack\.script\.tts must be a boolean/);
expectError("duplicate stage key", "ja", fx => { fx.pack.script.stages[1].key = "hira"; }, /ERROR pack\.script\.stages key 'hira' duplicated/);
expectError("script.json unknown key", "ko", fx => { fx.script.extra = 1; }, /ERROR script\.json has unknown keys \['extra'\]/);

// ------------------------------------------------------------ warnings
{
  const fx = FX.ko(); delete unit(fx, "ko-a").say;
  const r = runValidate(mkPack(fx));
  check("warning: say missing on a sound:true unit (tts on)", r.status === 0 && /WARN  script unit ko-a has sound but no say/.test(r.out), r.out);
  const fa = FX.fa(); const r2 = runValidate(mkPack(fa));
  check("no say warning when pack.script.tts is false", r2.status === 0 && !/has sound but no say/.test(r2.out), r2.out);
  const ja = FX.ja(); unit(ja, "ja-ji").confuse = []; unit(ja, "ja-dji").confuse = [];
  const r3 = runValidate(mkPack(ja));
  check("warning: same group and roman with no confuse link", r3.status === 0 && /WARN  script units ja-ji and ja-dji share group 'dakuten' and roman 'ji' with no confuse link/.test(r3.out), r3.out);
  check("warning: a unit with no ex", /WARN  script unit ko-ch has no ex example words/.test(r.out), r.out);
  check("warning: one-way alt equal to a sibling's roman (ko ㄱ alt k = ㅋ)", /WARN  script unit ko-g alt 'k' is the roman of ko-k/.test(r.out), r.out);
  const fq = FX.fa();
  const gh = { id: "fa-ghein", st: "abjad", set: 2, group: "gh", t: "غ", name: "ghein", roman: "gh", alt: ["q"], joins: "dual", confuse: ["fa-qaf"] };
  const qf = { id: "fa-qaf", st: "abjad", set: 2, group: "gh", t: "ق", name: "qaf", roman: "q", alt: ["gh"], joins: "dual", confuse: ["fa-ghein"] };
  fq.script.units.push(gh, qf);
  const r5 = runValidate(mkPack(fq));
  check("no alt warning for mutual alts (homophones غ/ق)", !/alt '(q|gh)' is the roman/.test(r5.out), r5.out);
  qf.alt = [];
  const r6 = runValidate(mkPack(fq));
  check("alt warning once the pair is one-way (غ alt q, ق no alt)", /WARN  script unit fa-ghein alt 'q' is the roman of fa-qaf/.test(r6.out) && !/fa-qaf alt/.test(r6.out), r6.out);
  const lv2 = /WARN  script unit ko-eu\.ex\[0\] word kA2_08 is from level 'A2', not the first level/.test(r.out);
  check("warning: ex word from the second level", lv2, r.out);
}

// ------------------------------------------------------------ glyph fold parity
// core.js scriptGlyphKeys/scriptGlyphIn (formFind, the app's example tint) and
// validate_pack.py glyph_keys/glyph_in (ex words) must agree: same equivalence classes over
// every Hangul jamo block and sample letters, same glyph_in verdicts.
{
  const VC = require(path.join(ROOT, "engine", "core.js"));
  const chars = [];
  for(const [a, b] of [[0x1100, 0x1112], [0x1161, 0x1175], [0x11A8, 0x11C2], [0x3131, 0x3163]]) for(let c = a; c <= b; c++) chars.push(String.fromCharCode(c));
  chars.push(..."آاأإبپﺏﺐがかぱはМмЁёЕеÉé");
  const pairs = [["ا", "آب"], ["ㄱ", "책"], ["ㄱ", "가구"], ["ㄳ", "몫"], ["ㅘ", "과"], ["м", "Москва"], ["е", "ёж"], ["か", "が"], ["きゃ", "きゃく"], ["きゃ", "きやく"], ["پ", "آب"], ["ب", "ﺐ"]];
  const py = cp.spawnSync(PY, ["-c", `import sys, json; sys.path.insert(0, ${JSON.stringify(path.join(ROOT, "tools"))}); import validate_pack as v
d = json.load(sys.stdin); print(json.dumps({"keys": [v.glyph_keys(c) for c in d["chars"]], "in": [v.glyph_in(g, t) for g, t in d["pairs"]]}))`],
    { input: JSON.stringify({ chars, pairs }), encoding: "utf8" });
  let res = null; try{ res = JSON.parse(py.stdout); }catch(e){}
  if(!res){ check("glyph fold parity: python ran", false, py.stderr); }
  else {
    const pk = res.keys.map(k => JSON.stringify(k)), jk = chars.map(c => JSON.stringify(VC.scriptGlyphKeys(c)));
    const bad = [];
    for(let i = 0; i < chars.length; i++) for(let j = i + 1; j < chars.length; j++) if((pk[i] === pk[j]) !== (jk[i] === jk[j])) bad.push(chars[i] + "/" + chars[j]);
    check(`glyph fold parity: same classes over ${chars.length} letters (jamo blocks, forms, kana, case)`, bad.length === 0, bad.slice(0, 10).join(" "));
    const badIn = pairs.filter(([g, t], i) => VC.scriptGlyphIn(g, t) !== res.in[i]).map(p => p.join(" in "));
    check(`glyph fold parity: glyph_in agrees on ${pairs.length} cases`, badIn.length === 0, badIn.join("; "));
  }
}

// ------------------------------------------------------------ jsonify --check and build.sh
{
  const dir = mkPack(FX.ja()); runValidate(dir);
  const sj = path.join(dir, "script.json"); const data = JSON.parse(fs.readFileSync(sj, "utf8"));
  data.units[0].note = "changed"; fs.writeFileSync(sj, JSON.stringify(data));
  const r = cp.spawnSync(PY, [path.join(ROOT, "tools", "validate_pack.py"), dir], { cwd: ROOT, encoding: "utf8" });
  check("stale script.js fails validation", r.status === 1 && /stale or missing generated file: \S*script\.js/.test(r.stdout), r.stdout);
  cp.spawnSync(PY, [path.join(ROOT, "tools", "jsonify_pack.py"), dir], { cwd: ROOT });
  const out = path.join(dir, "out", "ja.html");
  const b = cp.spawnSync("sh", [path.join(ROOT, "build.sh"), dir, out], { cwd: ROOT, encoding: "utf8" });
  const html = b.status === 0 ? fs.readFileSync(out, "utf8") : "";
  check("build.sh inlines script.js (const SCRIPT=) after the pack consts", b.status === 0 && /<script>\n\/\/ generated[^\n]*\nconst SCRIPT=\{/.test(html) && html.indexOf("const SCRIPT=") > html.indexOf("const WORDS="), b.stderr);
  if(fs.existsSync(path.join(dir, "script.js"))) fs.unlinkSync(path.join(dir, "script.js"));
  const b2 = cp.spawnSync("sh", [path.join(ROOT, "build.sh"), dir, out], { cwd: ROOT, encoding: "utf8" });
  check("build.sh warns when pack.script is set but script.js is missing", b2.status === 0 && /script block but \S+script\.js is missing/.test(b2.stderr) && !/const SCRIPT=/.test(fs.readFileSync(out, "utf8")), b2.stderr);
  const zhOut = path.join(dir, "out", "zh.html");
  cp.spawnSync("sh", [path.join(ROOT, "build.sh"), path.join(ROOT, "packs", "zh"), zhOut], { cwd: ROOT, encoding: "utf8" });
  check("build.sh on a pack without script.js: no SCRIPT const", fs.existsSync(zhOut) && !/const SCRIPT=/.test(fs.readFileSync(zhOut, "utf8")));
}

tmpDirs.forEach(d => { try{ fs.rmSync(d, { recursive: true, force: true }); }catch(e){} });
console.log(`\n${fails ? "FAILED" : "ALL PASSED"}: ${passes} passed, ${fails} failed`);
process.exit(fails ? 1 : 0);
