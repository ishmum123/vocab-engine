// Node checks for engine/core.js against the real zh pack plus synthetic packs.
// Run: /opt/homebrew/bin/node tests/engine_checks.js     (no dependencies)
"use strict";
const fs = require("fs");
const path = require("path");
const os = require("os");
const cp = require("child_process");
const util = require("util");

const ROOT = path.join(__dirname, "..");
const VC = require(path.join(ROOT, "engine", "core.js"));
const ZH = path.join(ROOT, "packs", "zh");

function loadConst(file, name){
  return new Function(fs.readFileSync(file, "utf8") + `\nreturn ${name};`)();
}
const PACK = loadConst(path.join(ZH, "pack.js"), "PACK");
const WORDS = loadConst(path.join(ZH, "words.js"), "WORDS");
const SENTENCES = loadConst(path.join(ZH, "sentences.js"), "SENTENCES");
const LESSONS = loadConst(path.join(ZH, "lessons.js"), "LESSONS");
const BY_ID = {}; WORDS.forEach(w=>{ BY_ID[w.id] = w; });
console.log(`Loaded zh pack: ${WORDS.length} words, ${SENTENCES.length} sentences, ${LESSONS.length} lessons`);

let fails = 0, passes = 0;
function check(name, cond){
  if(cond){ passes++; console.log(`PASS  ${name}`); }
  else { fails++; console.log(`FAIL  ${name}`); }
}
const sample = (arr, n) => Array.from({length:n}, ()=>arr[Math.floor(Math.random()*arr.length)]);

// ------------------------------------------------------------ [0] stale-build guard
(function(){
  // Every other check runs against source files; this one proves dist/zh.html is what
  // build.sh produces from them right now (rebuild to scratch, byte-compare).
  const tmp = path.join(os.tmpdir(), `vocab_engine_stalecheck_${process.pid}.html`);
  try{
    cp.execSync(`sh build.sh packs/zh "${tmp}"`, { cwd: ROOT, stdio: "pipe" });
    const built = fs.readFileSync(tmp, "utf8");
    const shipped = fs.existsSync(path.join(ROOT, "dist", "zh.html")) ? fs.readFileSync(path.join(ROOT, "dist", "zh.html"), "utf8") : null;
    console.log(`\n[0] stale-build guard: fresh build ${built.length} chars; dist/zh.html ${shipped===null ? "MISSING" : shipped.length+" chars"}`);
    check("dist/zh.html matches a fresh ./build.sh packs/zh output (not stale)", built === shipped);
    const srcs = [...built.matchAll(/<script[^>]*\ssrc=/g)].length;
    const links = [...built.matchAll(/<link[^>]*href="([^"]+)"/g)].map(m=>m[1]).filter(h=>!/^https:\/\/fonts\.(googleapis|gstatic)\.com/.test(h));
    check("built file is self-contained (no <script src>, only Google Fonts links)", srcs === 0 && links.length === 0);
    check("built file has no leftover dev pack loader", !built.includes("PACK-BEGIN") && !built.includes("document.write"));
  }catch(e){
    console.log(`\n[0] build.sh failed: ${e.message}`);
    check("build.sh runs cleanly", false);
  }finally{ try{ fs.unlinkSync(tmp); }catch(e){} }
})();

// ------------------------------------------------------------ [1] pack validation
(function(){
  console.log("\n[1] validate_pack.py packs/zh");
  const r = cp.spawnSync("python3", [path.join(ROOT, "tools", "validate_pack.py"), ZH], { encoding: "utf8" });
  const last = (r.stdout || "").trim().split("\n").pop();
  console.log("    " + last + (r.stderr ? `\n    stderr: ${r.stderr.trim()}` : ""));
  check("validate_pack.py passes on packs/zh", r.status === 0);
  check("zh pack has 1193 words, 882 sentences, 12 lessons", WORDS.length === 1193 && SENTENCES.length === 882 && LESSONS.length === 12);
  const unresolved = SENTENCES.flatMap(s => s.words.filter(id => !BY_ID[id]).map(id => `${s.id}:${id}`));
  check("every sentence word id resolves to a word", unresolved.length === 0);
  const lvIds = new Set(VC.levelIds(PACK));
  check("every word/sentence lv is a pack level", WORDS.every(w=>lvIds.has(w.lv)) && SENTENCES.every(s=>lvIds.has(s.lv)));
  check("lesson items: answer is one of the options", LESSONS.every(l => l.items.every(it => it.opts.includes(it.a))));
})();

// ------------------------------------------------------------ [2] wordOpts
(function(){
  console.log("\n[2] wordOpts (recall/gap distractors)");
  let bad = 0; const badEx = [];
  sample(WORDS, 400).forEach(e=>{
    const ds = VC.wordOpts(e, WORDS);
    const ws = [e.w, ...ds.map(d=>d.w)].map(VC.normKey);
    const f2 = VC.firstTwoWords(e.en);
    const ok = ds.length === 3 && new Set(ws).size === 4 && ds.every(d => d.id !== e.id &&
      VC.normKey(d.en) !== VC.normKey(e.en) && !(f2 && VC.firstTwoWords(d.en) === f2));
    if(!ok){ bad++; if(badEx.length<5) badEx.push({w:e.w, en:e.en, ds:ds.map(d=>[d.w,d.en])}); }
  });
  badEx.forEach(b=>console.log("    ", JSON.stringify(b)));
  check("zh: 3 distractors, answer never repeated, no same-gloss / same-first-two-words distractor (400 samples)", bad === 0);

  // synthetic pool: preference order pos+lv > lv > pos > anything
  const mk = (id, w, en, lv, pos) => ({ id, w, en, lv, pos });
  const ans = mk("a", "correre", "to run", "A1", "v");
  const pool = [ans,
    mk("b1","mangiare","to eat","A1","v"), mk("b2","bere","to drink","A1","v"), mk("b3","dormire","to sleep","A1","v"), mk("b4","parlare","to speak","A1","v"),
    mk("c1","casa","house","A1","n"), mk("c2","gatto","cat","A1","n"),
    mk("d1","nuotare","to swim","A2","v"), mk("e1","libro","book","A2","n"),
    mk("x1","correre","to run (fast)","A2","v"), mk("x2","scappare","to run away","A1","v"), mk("x3","fuggire","to run","A2","v")];
  let prefOk = true, neverBad = true;
  for(let i=0;i<200;i++){
    const ds = VC.wordOpts(ans, pool);
    if(!ds.every(d=>d.pos==="v" && d.lv==="A1")) prefOk = false;
    if(ds.some(d=>d.id.startsWith("x"))) neverBad = false;
  }
  check("synthetic: all 3 picks are same pos AND same level when 3+ exist", prefOk);
  check("synthetic: never picks same surface form, same gloss, or same first-two gloss words", neverBad);
  const pool2 = [ans, mk("b1","mangiare","to eat","A1","v"), mk("c1","casa","house","A1","n"), mk("c2","gatto","cat","A1","n"),
    mk("d1","nuotare","to swim","A2","v"), mk("e1","libro","book","A2","n"), mk("e2","rosso","red","A2","adj")];
  let tierOk = true;
  for(let i=0;i<200;i++){
    const ids = VC.wordOpts(ans, pool2).map(d=>d.id).sort();
    if(!util.isDeepStrictEqual(ids, ["b1","c1","c2"])) tierOk = false;
  }
  check("synthetic: falls back to same level (any pos) before other levels", tierOk);
  const tiny = [ans, mk("t1","x","one thing","A1"), mk("t2","y","one thing more","A1")];
  const td = VC.wordOpts(ans, tiny);
  check("synthetic: tiny pool returns what it can without duplicates", td.length === 2 && new Set(td.map(d=>d.w)).size === 2);
})();

// ------------------------------------------------------------ [3] typing normaliser
(function(){
  console.log("\n[3] typing normaliser");
  const P = { levels:[{id:"A1",label:"A1"},{id:"A2",label:"A2"},{id:"B1",label:"B1"},{id:"B2",label:"B2"}],
    typing:{ caseSensitive:false, accents:"lenient", strictFromLevel:"B1" } };
  const A1 = { id:"1", w:"perché", en:"why", lv:"A1" };
  const B1 = Object.assign({}, A1, { lv:"B1" });
  const B2 = Object.assign({}, A1, { lv:"B2" });
  const tu = { id:"2", w:"tu", en:"you", lv:"A1", alt:["te", "Lei"] };
  const cases = [
    [P, A1, "perche", true, "A1 lenient: accent-less accepted"],
    [P, A1, "PERCHÉ", true, "case-insensitive"],
    [P, A1, "  perché  ", true, "trimmed"],
    [P, A1, "perchè", true, "wrong accent folded when lenient"],
    [P, B1, "perche", false, "B1 (= strictFromLevel): accents required"],
    [P, B2, "perche", false, "B2 (after strictFromLevel): accents required"],
    [P, B1, "Perché", true, "B1: exact accents, case still folded"],
    [P, B1, "perchè", false, "B1: wrong accent rejected"],
    [P, tu, "te", true, "alt form accepted"],
    [P, tu, "lei", true, "alt form case-folded"],
    [P, tu, "voi", false, "wrong word rejected"],
    [P, tu, "   ", false, "blank rejected"],
    [Object.assign({}, P, {typing:{caseSensitive:true, accents:"lenient", strictFromLevel:null}}), A1, "Perche", false, "caseSensitive: capital rejected"],
    [Object.assign({}, P, {typing:{caseSensitive:true, accents:"lenient", strictFromLevel:null}}), B2, "perche", true, "strictFromLevel null: lenient at every level"],
    [Object.assign({}, P, {typing:{caseSensitive:false, accents:"strict", strictFromLevel:null}}), A1, "perche", false, "accents strict: never folded"],
    [P, { id:"3", w:"l’acqua", en:"the water", lv:"A1" }, "l'acqua", true, "typographic apostrophe unified"],
    [P, { id:"4", w:"über", en:"over", lv:"A1" }, "uber", true, "umlaut folded when lenient"],
    [P, { id:"5", w:"niño", en:"child", lv:"B1" }, "nino", false, "tilde kept when strict level"],
  ];
  let ok = true;
  cases.forEach(([pack, entry, input, expect, why])=>{
    const got = VC.acceptTyped(input, entry, pack);
    if(got !== expect) ok = false;
    console.log(`    ${got===expect?"ok ":"BAD"} ${why}: acceptTyped(${JSON.stringify(input)}, ${entry.w}@${entry.lv}) = ${got}`);
  });
  check("typing normaliser: case, accents lenient vs strict per level, alt forms", ok);
  check("cloze typed answer accepts the literal surface form passed as extra", VC.acceptTyped("sono", {id:"e",w:"essere",en:"to be",lv:"A1"}, P, ["sono"]));
  check("typingEnabled false for zh (typing:null)", VC.typingEnabled(PACK) === false);
})();

// ------------------------------------------------------------ [4] placement ports
(function(){
  console.log("\n[4] strata / placementStopIndex");
  const st = VC.strata(WORDS, PACK.placement, PACK.setSize);
  const counts = st.map((b,i)=>VC.placementItemCount(i));
  const total = counts.reduce((a,b)=>a+b, 0);
  console.log(`    ${st.length} buckets, ${total} items; words per bucket: ${st.map(b=>b.words.length).join(",")}`);
  check("zh placement: 16 buckets totalling 40 items", st.length === 16 && total === 40);
  check("every bucket has enough words for its item count", st.every((b,i)=>b.words.length >= counts[i]));
  const byLv = VC.wordsByLevel(WORDS, PACK);
  const lastEnds = PACK.placement.every(([lv])=>{ const bs = st.filter(b=>b.lv===lv); return bs[bs.length-1].s1 === VC.nSets(byLv[lv], PACK.setSize); });
  check("each level's last bucket ends exactly at its set count", lastEnds);
  check("strata honours a non-10 setSize", (()=>{ const s = VC.strata(WORDS, [["1",2]], 5); return s.length===2 && s[1].s1 === Math.ceil(byLv["1"].length/5); })());
  const allRight = Array.from({length:6}, ()=>({r:3,n:3}));
  check("all buckets correct -> null", VC.placementStopIndex(allRight) === null);
  check("bucket 3 entirely wrong -> stops at 3", VC.placementStopIndex([{r:3,n:3},{r:3,n:3},{r:3,n:3},{r:0,n:3},{r:3,n:3},{r:3,n:3}]) === 3);
  check("a single miss in a big-enough bucket 0 still passes", VC.placementStopIndex([{r:3,n:4},{r:3,n:3},{r:3,n:3},{r:3,n:3}]) === null);
})();

// ------------------------------------------------------------ [5] progress shape
(function(){
  console.log("\n[5] progress shape (pack-supplied levels)");
  const L = VC.levelIds(PACK);
  const bad = [{w:null}, {sets:null}, {lessons:null}, [1,2], {v:2}, {sets:{"5":1}}, {sets:{"1":"x"}}, {w:{w0001:{r:"1"}}},
    {s:{s0001:null}}, {showPron:"yes"}, {theme:"blue"}, {soundsOpened:"x"}, {w:{w0001:{prov:"x"}}}];
  let allRejected = true;
  bad.forEach(b=>{ const v = VC.validateProgShape(b, L); if(v.ok) allRejected = false; console.log(`    ${v.ok?"BAD":"ok "} rejects ${JSON.stringify(b)}${v.ok?"":" -> "+v.reason}`); });
  check("validateProgShape rejects malformed shapes", allRejected);
  const good = { v:1, w:{w0001:{r:2,w:1,s:1,prov:1}, w0002:{r:0,w:0,s:0,d:1}}, s:{s0001:{r:1,w:0,s:1}}, sets:{"1":3,"2":0},
    lessons:{tones:1}, sessions:4, theme:null, showPron:false, placedOnce:true, soundsOpened:true };
  check("validateProgShape accepts a real export shape", VC.validateProgShape(good, L).ok === true);
  check("sets keys are checked against the pack's own levels", VC.validateProgShape({sets:{"A1":1}}, ["A1","A2"]).ok && !VC.validateProgShape({sets:{"1":1}}, ["A1","A2"]).ok);
  const n = VC.normalizeProg(good, PACK);
  check("normalizeProg keeps data and fills every pack level's sets counter", n.v===1 && n.sets["1"]===3 && n.sets["4"]===0 && n.w.w0001.s===1 && n.showPron===false && n.lessons.tones===1);
  const d = VC.normalizeProg({}, PACK);
  check("normalizeProg({}) gives full defaults", util.isDeepStrictEqual(d, VC.defaultProg(PACK)) && d.showPron === true);
  check("storage key is vocab_<pack.key>", VC.storageKey(PACK) === "vocab_zh");
  const m = {}; VC.markRec(m, "k", true, true); VC.markRec(m, "k", true, true); VC.markRec(m, "k", false, true);
  check("markRec counts right/wrong and resets streak on a miss", m.k.r===2 && m.k.w===1 && m.k.s===0);
  const pv = { k:{r:1,w:0,s:1,prov:1} }; VC.markRec(pv, "k", false, true);
  check("markRec clears provisional on a miss", pv.k.prov === undefined);
})();

// ------------------------------------------------------------ [6] gap candidates
(function(){
  console.log("\n[6] cloze gap candidates");
  const fw = new Set(PACK.functionWords);
  let fwHits = 0, offLevel = 0, notLocatable = 0, withGap = 0, repeatHits = 0;
  const LONGER_SURFACES = [...new Set([...WORDS.flatMap(w=>[w.w, ...(w.alt||[])]), ...(PACK.compounds||[])])];
  SENTENCES.forEach(s=>{
    const idxs = VC.gapCandidateIndices(s, BY_ID, PACK);
    if(idxs.length) withGap++;
    idxs.forEach(i=>{
      const id = s.words[i], e = BY_ID[id];
      if(fw.has(id)) fwHits++;
      if(e.lv !== s.lv) offLevel++;
      if(s.words.filter(x=>x===id).length > 1) repeatHits++;
      // Independent re-derivation (not via gapMatch): the blank must cover exactly one
      // surface of the word, the rest of the text must be untouched, the surface must
      // occur once, and (spaced=false) no longer pack word/compound may span it.
      const m = VC.gapMatch(s, e, BY_ID, PACK);
      const forms = [e.w, ...(e.alt||[])];
      const b = m && VC.blankSentence(s, m);
      const exact = !!m && m.end > m.start && forms.includes(m.text) && b.before + m.text + b.after === s.t
        && s.t.split(m.text).length === 2;
      const longer = LONGER_SURFACES.filter(x => x.length > (m ? m.text.length : 0) && m && x.includes(m.text));
      const spanned = !!m && longer.some(x => { let i = s.t.indexOf(x); while(i >= 0){ if(i <= m.start && i + x.length >= m.end) return true; i = s.t.indexOf(x, i+1); } return false; });
      if(!exact || spanned) notLocatable++;
    });
  });
  console.log(`    ${withGap} / ${SENTENCES.length} zh sentences have >=1 legal blank`);
  check("zh: no gap candidate is a pack function word", fwHits === 0);
  check("zh: no gap candidate is off-level or repeated in its sentence", offLevel === 0 && repeatHits === 0);
  check("zh: every gap blank covers exactly one occurrence of the word's surface, rest of text intact, not inside a longer pack word/compound", notLocatable === 0);
  check("zh: a meaningful share of sentences can be gapped (>=50%)", withGap / SENTENCES.length >= 0.5);

  const P = { levels:[{id:"A1",label:"A1"}], functionWords:["io","uno"] };
  const W = { io:{id:"io",w:"io",en:"I",lv:"A1"}, essere:{id:"essere",w:"essere",en:"to be",lv:"A1",alt:["sono"]},
    uno:{id:"uno",w:"uno",en:"a",lv:"A1"}, studente:{id:"studente",w:"studente",en:"student",lv:"A1"},
    casa:{id:"casa",w:"casa",en:"house",lv:"A1"} };
  const s1 = { id:"s1", t:"Io sono uno studente.", en:"I am a student.", lv:"A1", words:["io","essere","uno","studente"] };
  check("spaced: function words excluded; alt surface form locates inflected word", util.isDeepStrictEqual(VC.gapCandidateIndices(s1, W, P), [1,3]));
  const s2 = { id:"s2", t:"La studentessa è qui.", en:"x", lv:"A1", words:["studente"] };
  check("spaced: whole-word match only (studente not found inside studentessa)", VC.gapCandidateIndices(s2, W, P).length === 0);
  const s3 = { id:"s3", t:"Casa mia è la tua casa.", en:"x", lv:"A1", words:["casa","casa"] };
  check("repeated word is never a candidate", VC.gapCandidateIndices(s3, W, P).length === 0);
  const s4 = { id:"s4", t:"Casa!", en:"x", lv:"A1", words:["casa"] };
  const m4 = VC.locateWord(s4, W.casa, P);
  check("spaced: match is case-insensitive and blank keeps surrounding text", m4 && VC.blankSentence(s4, m4).after === "!" && m4.text === "Casa");
})();

// ------------------------------------------------------------ [7] Today composition
(function(){
  console.log("\n[7] Today item plans");
  const typingPack = Object.assign({}, PACK, { typing:{caseSensitive:false, accents:"lenient", strictFromLevel:null} });
  let shareOk = true, sizeOk = true, dupOk = true, typeSeen = false, noTypeWhenOff = true, minShare = 1;
  [5, 6, 9, 15, 16, 40, 200].forEach(n=>{
    const learned = WORDS.slice(0, n);
    const prog = VC.defaultProg(PACK);
    learned.slice(0, 7).forEach(w=>{ prog.w[w.id] = {r:1,w:0,s:1,prov:1}; });
    [PACK, typingPack].forEach(pk=>{
      for(let rep=0; rep<50; rep++){
        const plan = VC.buildReviewPlan(learned, prog, pk);
        const prod = plan.filter(p=>VC.PRODUCTION_KINDS.includes(p.kind)).length;
        const share = prod / plan.length; minShare = Math.min(minShare, share);
        if(share < VC.REVIEW_PRODUCTION_SHARE) shareOk = false;
        if(plan.length !== Math.min(VC.REVIEW_SIZE, n)) sizeOk = false;
        if(new Set(plan.map(p=>p.word.id)).size !== plan.length) dupOk = false;
        if(plan.some(p=>p.kind==="type")){ if(pk===PACK) noTypeWhenOff = false; else typeSeen = true; }
      }
    });
  });
  console.log(`    min production share observed: ${minShare.toFixed(3)}`);
  check("review step: production (recall/type) share >= 40% for every pool size", shareOk);
  check("review step: size = min(15, learned) with no repeated word", sizeOk && dupOk);
  check("review step: type items only when the pack has typing", typeSeen && noTypeWhenOff);
  const prog = VC.defaultProg(PACK);
  const learned = WORDS.slice(0, 30);
  learned.slice(0, 3).forEach(w=>{ prog.w[w.id] = {r:1,w:0,s:1,prov:1}; });
  const hasProv = VC.buildReviewPlan(learned, prog, PACK).filter(p=>prog.w[p.word.id] && prog.w[p.word.id].prov).length;
  check("review step: provisional (placement-guessed) words are always included", hasProv === 3);
  learned.slice(10, 13).forEach(w=>{ prog.w[w.id] = {r:0,w:5,s:0}; });
  let weakIn = true;
  for(let i=0;i<30;i++){ const ids = new Set(VC.buildReviewPlan(learned, prog, PACK).map(p=>p.word.id)); if(!learned.slice(10,13).every(w=>ids.has(w.id))) weakIn = false; }
  check("review step: weakest words are always included", weakIn);
  const rp = VC.buildRecallPlan(learned, prog, typingPack, 8);
  check("recall step: 8 items, all production, recall+type mixed when typing on", rp.length === 8 && rp.every(p=>VC.PRODUCTION_KINDS.includes(p.kind)) && rp.some(p=>p.kind==="type") && rp.some(p=>p.kind==="recall"));
  check("recall step: recall only when typing off", VC.buildRecallPlan(learned, prog, PACK, 8).every(p=>p.kind==="recall"));
  const km = VC.kindMix(15, 0.4, false);
  check("kindMix(15): exactly 6 production, hear:read 2:1 over the rest", km.filter(k=>k==="recall").length===6 && km.filter(k=>k==="hear").length===6 && km.filter(k=>k==="read").length===3);
  const counts = {hear:0, read:0, gap:0, gapType:0};
  for(let i=0;i<4000;i++) counts[VC.sentenceKind(PACK)]++;
  check("sentence kinds ~50/25/25 hear/read/gap; no typed gap without typing", Math.abs(counts.hear/4000-0.5)<0.04 && Math.abs(counts.gap/4000-0.25)<0.04 && counts.gapType===0);
})();

// ------------------------------------------------------------ [8] meaningOpts / sentenceOpts ports
(function(){
  console.log("\n[8] meaningOpts / sentenceOpts");
  let bad = 0;
  sample(WORDS, 300).forEach(e=>{
    const ds = VC.meaningOpts(e, WORDS);
    const g = [e, ...ds].map(x=>VC.normKey(x.en));
    const f2 = ds.map(d=>VC.firstTwoWords(d.en)).filter(Boolean);
    const af2 = VC.firstTwoWords(e.en);
    if(!(ds.length===3 && new Set(g).size===4 && ds.every(d=>d.id!==e.id) && !f2.includes(af2 || "\u0000") && new Set(f2).size===f2.length)) bad++;
  });
  check("meaningOpts: 3 distinct glosses, no near-synonym (first two words) distractors (300 samples)", bad === 0);
  let sbad = 0;
  sample(SENTENCES, 300).forEach(s=>{
    const ds = VC.sentenceOpts(s, SENTENCES);
    const en = [s, ...ds].map(x=>VC.normKey(x.en));
    if(!(ds.length===3 && new Set(en).size===4 && ds.every(d=>d.id!==s.id))) sbad++;
  });
  check("sentenceOpts: 3 distinct other sentences (300 samples)", sbad === 0);
})();

// ------------------------------------------------------------ [9] learned / unlock
(function(){
  console.log("\n[9] learned words, set unlock, sentence availability");
  const prog = VC.normalizeProg({ sets:{"1":2} }, PACK);
  const lw = VC.learnedWords(WORDS, PACK, prog);
  check("sets {1:2} -> first 20 level-1 words learned", lw.length === 20 && lw.every(w=>w.lv==="1"));
  check("nextNewSet -> level 1, set index 2", util.isDeepStrictEqual(VC.nextNewSet(WORDS, PACK, prog), {lv:"1", set:2}));
  const byLv = VC.wordsByLevel(WORDS, PACK);
  const doneL1 = VC.normalizeProg({ sets:{"1": VC.nSets(byLv["1"], 10)} }, PACK);
  check("level 1 complete -> next set is level 2 set 0", util.isDeepStrictEqual(VC.nextNewSet(WORDS, PACK, doneL1), {lv:"2", set:0}));
  const all = {}; VC.levelIds(PACK).forEach(lv=>{ all[lv] = VC.nSets(byLv[lv], 10); });
  const doneAll = VC.normalizeProg({ sets: all }, PACK);
  check("everything complete -> nextNewSet null, all words learned", VC.nextNewSet(WORDS, PACK, doneAll) === null && VC.learnedWords(WORDS, PACK, doneAll).length === WORDS.length);
  const avail = VC.availableSentences(SENTENCES, WORDS, PACK, doneL1);
  check("past level 1 -> every level-1 sentence available", SENTENCES.filter(s=>s.lv==="1").every(s=>avail.includes(s)));
  const lwSet = new Set(VC.learnedWords(WORDS, PACK, prog).map(w=>w.id));
  check("availability otherwise requires every word learned", VC.availableSentences(SENTENCES, WORDS, PACK, prog).every(s=>s.words.every(id=>lwSet.has(id))));
  const ahead = VC.normalizeProg({ w:{ [byLv["3"][0].id]:{r:1,w:0,s:1,d:1} } }, PACK);
  check("drilled-ahead (d) words count as learned", VC.learnedWords(WORDS, PACK, ahead).some(w=>w.id===byLv["3"][0].id));
})();

// ------------------------------------------------------------ [10] engine is language-agnostic
(function(){
  console.log("\n[10] no pinyin/tone/character logic in engine/");
  // Allowed: the HTML charset declaration only.
  const ALLOW = [/<meta charset="utf-8">/];
  const hits = [];
  ["core.js", "app.html"].forEach(f=>{
    fs.readFileSync(path.join(ROOT, "engine", f), "utf8").split("\n").forEach((line, i)=>{
      if(/tone|pinyin|cjk|char|hsk/i.test(line) && !ALLOW.some(re=>re.test(line))) hits.push(`${f}:${i+1}: ${line.trim().slice(0,100)}`);
    });
  });
  hits.forEach(h=>console.log("    " + h));
  check("engine/ has no tone/pinyin/CJK/char/hsk references (besides <meta charset>)", hits.length === 0);
})();

// ------------------------------------------------------------ [11] homographs / homophones (review major 1)
(function(){
  console.log("\n[11] distractor homograph / homophone guards");
  const P = { levels:[{id:"1",label:"L1"},{id:"2",label:"L2"}] };
  const ans = { id:"a1", w:"banco", en:"bench", lv:"1", pron:"BAN-ko", alt:["banchi"] };
  const pool = [ans,
    { id:"a2", w:"banco", en:"bank (money)", lv:"2", pron:"BAN-ko2" },         // homograph, other level
    { id:"a3", w:"panca", en:"pew", lv:"1", alt:["BANCHI"] },                   // shares an alt surface
    { id:"a4", w:"vanco", en:"gap", lv:"1", pron:"ban-ko" },                    // homophone (same pron)
    { id:"b1", w:"casa", en:"house", lv:"1" }, { id:"b2", w:"gatto", en:"cat", lv:"1" },
    { id:"b3", w:"libro", en:"book", lv:"1" }, { id:"b4", w:"rosso", en:"red", lv:"2" } ];
  let meanOk = true, wordOk = true;
  for(let i=0;i<300;i++){
    const m = VC.meaningOpts(ans, pool).map(d=>d.id);
    if(m.some(id=>["a2","a3","a4"].includes(id)) || m.length !== 3) meanOk = false;
    const w = VC.wordOpts(ans, pool).map(d=>d.id);
    if(w.some(id=>["a2","a3"].includes(id)) || w.length !== 3) wordOk = false;
  }
  check("meaningOpts never offers a homograph (same w, any level), alt-sharing word, or same-pron word", meanOk);
  check("wordOpts never offers a word sharing a w/alt surface with the answer", wordOk);
  const zhHomophone = WORDS.filter(w=>w.pron).slice(0, 400).every(e => VC.meaningOpts(e, WORDS).every(d => !VC.samePron(d, e) && !VC.sharesSurface(d, e)));
  check("zh: no meaningOpts distractor shares pron or surface with the answer (400 words)", zhHomophone);
})();

// ------------------------------------------------------------ [12] cloze boundaries (minor 6, 11)
(function(){
  console.log("\n[12] cloze: longer-word spans, compounds, alt leaks, apostrophes");
  const Z = { levels:[{id:"1",label:"1"}], spaced:false, functionWords:[], compounds:["这个"] };
  const ZW = { wei:{id:"wei",w:"为",en:"for",lv:"1"}, weish:{id:"weish",w:"为什么",en:"why",lv:"1"},
    zhe:{id:"zhe",w:"这",en:"this",lv:"1"}, hao:{id:"hao",w:"好",en:"good",lv:"1"} };
  const z1 = { id:"z1", t:"你为什么好？", en:"x", lv:"1", words:["wei","hao"] };
  check("spaced=false: 为 inside 为什么 (a longer pack word) is not blankable; 好 still is", util.isDeepStrictEqual(VC.gapCandidateIndices(z1, ZW, Z), [1]));
  const z2 = { id:"z2", t:"这个好。", en:"x", lv:"1", words:["zhe","hao"] };
  check("spaced=false: 这 inside pack.compounds 这个 is not blankable", util.isDeepStrictEqual(VC.gapCandidateIndices(z2, ZW, Z), [1]));
  const z3 = { id:"z3", t:"为你好。", en:"x", lv:"1", words:["wei","hao"] };
  check("spaced=false: 为 on its own is blankable", util.isDeepStrictEqual(VC.gapCandidateIndices(z3, ZW, Z), [0,1]));

  const I = { levels:[{id:"A1",label:"A1"}], functionWords:[] };
  const IW = { essere:{id:"essere",w:"essere",en:"to be",lv:"A1",alt:["sono","è"]}, lo:{id:"lo",w:"l'",en:"the",lv:"A1",alt:["lo"]},
    acqua:{id:"acqua",w:"acqua",en:"water",lv:"A1"}, per:{id:"per",w:"per",en:"for",lv:"A1"},
    perfav:{id:"perfav",w:"per favore",en:"please",lv:"A1"}, grazie:{id:"grazie",w:"grazie",en:"thanks",lv:"A1"} };
  const i1 = { id:"i1", t:"Sono qui, ed è bello.", en:"x", lv:"A1", words:["essere"] };
  check("alt leak: word visible twice via different forms (sono ... è) is not blankable", VC.gapCandidateIndices(i1, IW, I).length === 0);
  const i2 = { id:"i2", t:"Bevo l’acqua.", en:"x", lv:"A1", words:["lo","acqua"] };
  const m2 = VC.locateWord(i2, IW.lo, I);
  check("apostrophe-final surface l' matches before a letter and across ’/' variants", !!m2 && m2.text === "l’" && util.isDeepStrictEqual(VC.gapCandidateIndices(i2, IW, I), [0,1]));
  const i3 = { id:"i3", t:"Per favore, grazie per tutto.", en:"x", lv:"A1", words:["perfav","grazie","per"] };
  check("spaced: a word occurring once standalone but also inside a multi-word pack entry is rejected (two occurrences)", !VC.gapCandidateIndices(i3, IW, I).includes(2));
  const i4 = { id:"i4", t:"Per favore, grazie.", en:"x", lv:"A1", words:["perfav","per","grazie"] };
  check("spaced: per inside the multi-word entry 'per favore' is not blankable", util.isDeepStrictEqual(VC.gapCandidateIndices(i4, IW, I), [0,2]));
  const m4 = VC.gapMatch(i4, IW.perfav, IW, I);
  const b4 = VC.blankSentence(i4, m4);
  check("blank covers exactly the located surface", b4.before === "" && b4.answer === "Per favore" && b4.after === ", grazie.");
})();

// ------------------------------------------------------------ [13] progress robustness (majors 2, 3; minors 4, 9; nit 12)
(function(){
  console.log("\n[13] boot / import / placement / gates");
  const L = VC.levelIds(PACK);
  check("validateProgShape rejects non-integer and negative sets values", !VC.validateProgShape({sets:{"1":1.5}}, L).ok && !VC.validateProgShape({sets:{"1":-1}}, L).ok);
  check("parseStored rejects array / string / number / null / invalid JSON", ["[1]", '"x"', "3", "null", "{bad"].every(r => !VC.parseStored(r).ok));
  const b0 = VC.bootProg(null, PACK);
  check("boot: nothing stored -> defaults, no backup", b0.backupRaw === null && util.isDeepStrictEqual(b0.prog, VC.defaultProg(PACK)));
  const b1 = VC.bootProg("{not json", PACK);
  check("boot: unparseable -> defaults + raw string handed back for invalid_backup", b1.backupRaw === "{not json" && b1.prog.sessions === 0);
  const b2 = VC.bootProg("[1,2]", PACK);
  check("boot: non-object JSON -> backup, not Object.assign'ed", b2.backupRaw === "[1,2]" && !Array.isArray(b2.prog));
  const renamed = JSON.stringify({ v:1, w:{w0001:{r:3,w:0,s:3}}, sets:{"1":4,"HSK5":2}, sessions:9, lessons:{tones:1} });
  const b3 = VC.bootProg(renamed, PACK);
  check("boot: unknown sets key (renamed level) dropped, everything else kept, no backup", b3.backupRaw === null && util.isDeepStrictEqual(b3.dropped, ["HSK5"]) && b3.prog.sets["1"] === 4 && b3.prog.sessions === 9 && b3.prog.w.w0001.s === 3 && !("HSK5" in b3.prog.sets));
  const b4 = VC.bootProg(JSON.stringify({ w:{x:{r:"bad"}} }), PACK);
  check("boot: otherwise-invalid shape -> backup + defaults", b4.backupRaw !== null && Object.keys(b4.prog.w).length === 0);
  const prev = Object.assign(VC.defaultProg(PACK), { theme:"dark", showPron:false, sessions:3 });
  const im1 = VC.applyImport(prev, JSON.stringify({ sets:{"1":2}, sessions:7 }), PACK);
  check("import: valid -> normalised, keeps current theme/showPron when absent", im1.ok && im1.prog.sessions === 7 && im1.prog.sets["4"] === 0 && im1.prog.theme === "dark" && im1.prog.showPron === false);
  const im2 = VC.applyImport(prev, JSON.stringify({ sets:{"HSK5":1} }), PACK);
  check("import: stays strict (unknown level rejected)", !im2.ok && /unknown level/.test(im2.reason));
  check("import: non-object rejected", !VC.applyImport(prev, "[]", PACK).ok);

  // applyPlacement
  const st = VC.strata(WORDS, PACK.placement, PACK.setSize);
  const before = VC.normalizeProg({ w:{ w0001:{r:5,w:0,s:4}, w0002:{r:1,w:0,s:1,prov:1}, w0600:{r:0,w:0,s:0,d:1}, w0003:{r:2,w:0,s:2,prov:1} }, sets:{"1":1} }, PACK);
  const snapshot = JSON.stringify(before);
  const after = VC.applyPlacement(before, st, 4, WORDS, PACK);
  check("applyPlacement is pure (input untouched)", JSON.stringify(before) === snapshot);
  check("applyPlacement: sets = max(existing, furthest passed bucket end) per level", after.sets["1"] === st[2].s1 && after.sets["2"] === st[3].s1 && after.sets["3"] === 0 && after.placedOnce === true);
  check("applyPlacement: every existing record kept unchanged (mastered, provisional, drilled-ahead)",
    util.isDeepStrictEqual(after.w.w0001, before.w.w0001) && util.isDeepStrictEqual(after.w.w0002, before.w.w0002) &&
    util.isDeepStrictEqual(after.w.w0600, before.w.w0600) && util.isDeepStrictEqual(after.w.w0003, before.w.w0003));
  check("applyPlacement: every newly covered word without a record seeded provisional (flags only added)",
    VC.learnedWords(WORDS, PACK, after).every(w => after.w[w.id]) &&
    Object.keys(after.w).filter(k => !before.w[k]).every(k => after.w[k].prov === 1));
  // Regression (browser verification): a poor retake wiped session-learned words.
  const advanced = VC.normalizeProg({ sets:{"1":14,"2":3}, w:{ w0141:{r:4,w:1,s:3} } }, PACK);
  const learnedBefore = VC.learnedWords(WORDS, PACK, advanced).map(w=>w.id);
  const poor = VC.applyPlacement(advanced, st, 1, WORDS, PACK);
  check("applyPlacement: a poor retake never lowers any level's sets", VC.levelIds(PACK).every(lv => poor.sets[lv] >= advanced.sets[lv]) && poor.sets["1"] === 14 && poor.sets["2"] === 3);
  check("applyPlacement: a poor retake keeps every learned word and its record", learnedBefore.every(id => VC.learnedWords(WORDS, PACK, poor).some(w=>w.id===id)) && util.isDeepStrictEqual(poor.w.w0141, advanced.w.w0141));
  check("applyPlacement: nothing passed on a fresh learner -> all sets 0, no records", Object.values(VC.applyPlacement(VC.defaultProg(PACK), st, 0, WORDS, PACK).sets).every(n => n === 0));

  // dedupeMisses (Today "Missed" list)
  const miss = [{key:"w:a", reveal:"hearA"}, {key:"w:b", reveal:"readB"}, {key:"w:a", reveal:"readA"}, {key:"s:1", reveal:"s"}, {key:"w:a", reveal:"recallA"}, {reveal:"nokey"}];
  const dm = VC.dedupeMisses(miss);
  check("dedupeMisses: one entry per key (word missed as hear+read+recall shows once), most-missed first",
    dm.length === 4 && dm[0].item.reveal === "hearA" && dm[0].count === 3 && dm.slice(1).map(d=>d.item.reveal).join(",") === "readB,s,nokey");

  // gates
  check("todayGates: review needs 5, listen/recall 4, sentences 8, learn needs a next set",
    util.isDeepStrictEqual(VC.todayGates(4, true, 7), {review:false, learn:true, listen:true, recall:true, sentences:false}) &&
    util.isDeepStrictEqual(VC.todayGates(5, false, 8), {review:true, learn:false, listen:true, recall:true, sentences:true}));
  check("testGates: learn-first notice gates on learned words only (>= TEST_MIN_WORDS), never on sentences",
    VC.TEST_MIN_WORDS === 8 && VC.testGates(8, 0).needPlacement === false && VC.testGates(10, 0).needPlacement === false &&
    VC.testGates(7, 50).needPlacement === true && VC.testGates(10, 0).sentences === false && VC.testGates(10, 8).sentences === true && VC.testGates(10, 0).words === true);

  // speech
  const voices = [{lang:"en-US"}, {lang:"zh_TW"}, {lang:"it-IT"}];
  check("pickVoice: exact locale, else same language, else null", VC.pickVoice(voices, "it-IT").lang === "it-IT" && VC.pickVoice(voices, "zh-CN").lang === "zh_TW" && VC.pickVoice(voices, "es-ES") === null);
  check("speechUsable: no API -> false; unknown voice list -> true; list without the language -> false",
    !VC.speechUsable(false, voices, "it-IT") && VC.speechUsable(true, [], "es-ES") && !VC.speechUsable(true, voices, "es-ES") && VC.speechUsable(true, voices, "it-IT"));
  check("escapeHtml escapes single quotes", VC.escapeHtml(`a'b"<`) === "a&#39;b&quot;&lt;");
  check("isSamsungBrowser: matches SamsungBrowser UA case-insensitively, not other Android/Chrome UAs",
    VC.isSamsungBrowser("Mozilla/5.0 (Linux; Android 13) SamsungBrowser/23.0 Chrome/115.0.0.0 Mobile Safari/537.36") &&
    VC.isSamsungBrowser("...samsungbrowser/1.0...") &&
    !VC.isSamsungBrowser("Mozilla/5.0 (Linux; Android 13) Chrome/115.0.0.0 Mobile Safari/537.36") &&
    !VC.isSamsungBrowser(undefined));
})();

// ------------------------------------------------------------ [14] validator (minor 7, nit 15)
(function(){
  console.log("\n[14] validate_pack.py parity and level checks");
  const r = cp.spawnSync("python3", [path.join(ROOT, "tools", "validate_pack.py"), ZH, "--dump-strata"], { encoding:"utf8" });
  const py = JSON.parse(r.stdout || "[]");
  const js = VC.strata(WORDS, PACK.placement, PACK.setSize).map(b=>({lv:b.lv, s0:b.s0, s1:b.s1, n:b.words.length}));
  check("validator strata == core.js strata on zh (bucket bounds and sizes)", util.isDeepStrictEqual(py, js));
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "vocab_pack_"));
  const run = (pack, words) => {
    fs.writeFileSync(path.join(tmp, "pack.json"), JSON.stringify(pack));
    fs.writeFileSync(path.join(tmp, "words.json"), JSON.stringify(words));
    fs.writeFileSync(path.join(tmp, "sentences.json"), "[]");
    cp.spawnSync("python3", [path.join(ROOT, "tools", "jsonify_pack.py"), tmp]);
    return cp.spawnSync("python3", [path.join(ROOT, "tools", "validate_pack.py"), tmp], { encoding:"utf8" });
  };
  const base = { key:"t", name:"T", tts:"it-IT", levels:[{id:"A1",label:"A1"},{id:"A2",label:"A2"}], placement:[["A1",2]], typing:null, showPron:false, hasLessons:false };
  const mkw = (n, lv, off) => Array.from({length:n}, (_,i)=>({ id:`${lv}${i+(off||0)}`, w:`w${lv}${i}`, en:`gloss ${lv} ${i}`, lv }));
  const ok = run(base, [...mkw(20,"A1"), ...mkw(12,"A2")]);
  check("synthetic pack (setSize/typing defaults) validates", ok.status === 0);
  const empty = run(base, mkw(20,"A1"));
  check("level with no words is an error", empty.status === 1 && /level 'A2' has no words/.test(empty.stdout));
  const thin = run(base, [...mkw(20,"A1"), ...mkw(4,"A2")]);
  check("level with fewer words than one set is a warning, not an error", thin.status === 0 && /fewer than one set/.test(thin.stdout));
  const small = run(Object.assign({}, base, { setSize:2, placement:[["A1",3]] }), [...mkw(5,"A1"), ...mkw(12,"A2")]);
  check("placement bucket with < 3 words (set-boundary math) is an error", small.status === 1 && /needs >= 3/.test(small.stdout));
  fs.rmSync(tmp, { recursive:true, force:true });
})();

// ------------------------------------------------------------ [15] final round (N1-N4)
(function(){
  console.log("\n[15] lesson keys, lesson no-speech mode, wordOpts alt dedupe, read-error boot");
  // N1: distinct lesson items never merge in the Missed list, even with the same q.
  const keys = LESSONS.flatMap(l => l.items.map((it, i) => VC.lessonItemKey(l.id, i)));
  check("lesson item keys are unique across all zh lessons", new Set(keys).size === keys.length);
  const sameQ = LESSONS[0].items.filter(it => it.q === LESSONS[0].items[0].q).length;
  const miss = LESSONS[0].items.map((it, i) => ({ key: VC.lessonItemKey(LESSONS[0].id, i), reveal: it.rv || "" }));
  check(`distinct lesson items with the same question (${sameQ} share "${LESSONS[0].items[0].q}") are not merged`, sameQ > 1 && VC.dedupeMisses(miss).length === miss.length);
  // N2
  const it = (q, say, a) => ({ t:"mc", q, say, a, opts:[a, "x"] });
  check("lessonSayMode: speech ok -> audio; no say -> audio",
    VC.lessonSayMode(it("Which tone?", "妈", "1"), true) === "audio" && VC.lessonSayMode(it("Which tone?", undefined, "1"), false) === "audio");
  check("lessonSayMode: no speech + q contains say -> inq", VC.lessonSayMode(it("In 你好吗, what tone is 吗?", "你好吗", "neutral"), false) === "inq");
  check("lessonSayMode: no speech + say contains answer -> skip", VC.lessonSayMode(it("Which syllable?", "mā", "mā"), false) === "skip" && VC.lessonSayMode(it("Final?", "Wǒ", "wǒ"), false) === "skip");
  check("lessonSayMode: no speech + neither -> show text", VC.lessonSayMode(it("Which tone do you hear?", "妈", "1"), false) === "text");
  // N3
  const ans = { id:"a", w:"andare", en:"to go", lv:"A1", pos:"v" };
  const pool = [ans, ...["mangiare:to eat","bere:to drink","dormire:to sleep","parlare:to speak"].map((x,i)=>{ const [w,en] = x.split(":"); return { id:"d"+i, w, en, lv:"A1", pos:"v", alt:["shared-alt"] }; })];
  let three = true; for(let i=0;i<100;i++) if(VC.wordOpts(ans, pool).length !== 3) three = false;
  check("wordOpts: distractors sharing an alt with each other are fine (returns 3)", three);
  const ansAlt = Object.assign({}, ans, { alt:["shared-alt"] });
  check("wordOpts: a distractor sharing an alt with the ANSWER is still excluded", VC.wordOpts(ansAlt, [ansAlt, ...pool.slice(1)]).length === 0);
  // N4
  const ro = VC.bootProg(null, PACK, true);
  check("bootProg: storage read error -> read-only defaults, no backup write", ro.readOnly === true && ro.backupRaw === null && util.isDeepStrictEqual(ro.prog, VC.defaultProg(PACK)));
  check("bootProg: normal read is not read-only", VC.bootProg(null, PACK).readOnly === false && VC.bootProg('{"sessions":2}', PACK).readOnly === false);
})();

// ------------------------------------------------------------ [16] Italian browser-verify round
(function(){
  console.log("\n[16] gap option bare forms, example-sentence chooser, audio slot");
  const I = { levels:[{id:"A1",label:"A1"}], functionWords:[], spaced:true };
  const nouns = [["gioco","game"],["padre","father"],["libro","book"],["treno","train"],["cane","dog"],["mare","sea"]]
    .map(([b,en],i)=>({ id:"n"+i, w:(i%2?"la ":"il ")+b, en, lv:"A1", pos:"n", alt:[b, b+"s"] }));
  const anno = { id:"anno", w:"l'anno", en:"year", lv:"A1", pos:"n", alt:["anno"] };
  const acqua = { id:"acqua", w:"acqua", en:"water", lv:"A1", pos:"n", alt:["l'acqua"] };
  const art = { id:"il", w:"il", en:"the", lv:"A1", pos:"art", alt:["lo","la"] };
  const bello = { id:"bello", w:"bello", en:"beautiful", lv:"A1", pos:"adj", alt:["bella"] };
  const W = [...nouns, anno, acqua, art, bello];
  const BY = {}; W.forEach(w=>{ BY[w.id] = w; });
  check("bareForm: alt[0] when it is a whole trailing token of w (il gioco -> gioco, l'anno -> anno)",
    VC.bareForm(nouns[0]) === "gioco" && VC.bareForm(anno) === "anno" && VC.bareForm({w:"l’anno",alt:["anno"]}) === "anno");
  check("bareForm: w otherwise (acqua/l'acqua, il/lo, bello/bella, no alt)",
    VC.bareForm(acqua) === "acqua" && VC.bareForm(art) === "il" && VC.bareForm(bello) === "bello" && VC.bareForm({w:"casa"}) === "casa");
  // Blank = alt (bare): "È un ____ di parole." must not offer "il padre".
  const s1 = { id:"s1", t:"È un gioco di parole.", en:"x", lv:"A1", words:["n0"] };
  const m1 = VC.gapMatch(s1, nouns[0], BY, I);
  let bareOk = !!m1 && m1.text === "gioco";
  for(let i=0;i<50;i++){
    const gc = VC.gapChoices(nouns[0], m1, W, I);
    const bad = gc.opts.some(o => /^(il|la|l') ?/.test(o) && o !== "il" && o !== "la") || gc.a !== "gioco" || gc.opts[0] !== gc.a ||
      new Set(gc.opts).size !== gc.opts.length || gc.opts.some(o => !gc.byLabel[o]) || gc.byLabel[gc.a] !== nouns[0];
    if(bad){ bareOk = false; console.log("    BAD", JSON.stringify(gc.opts)); break; }
  }
  check("gapChoices: blank matched an alt -> answer and every distractor shown bare, distinct, mapped back", bareOk);
  // Inflected alt also triggers bare mode (answer shown by lemma).
  const s1b = { id:"s1b", t:"Due giocos qui.", en:"x", lv:"A1", words:["n0"] };
  const gcb = VC.gapChoices(nouns[0], VC.gapMatch(s1b, nouns[0], BY, I), W, I);
  check("gapChoices: inflected alt blank -> bare labels too", gcb.a === "gioco" && gcb.opts.every(o => !/^(il|la) /.test(o)));
  // Blank found via w ("Il gioco"): the article stays visible, blank + options are bare
  // (rule changed in [19]; before, options showed w here).
  const s2 = { id:"s2", t:"Il gioco è bello.", en:"x", lv:"A1", words:["n0"] };
  const m2 = VC.gapMatch(s2, nouns[0], BY, I);
  const gc2 = VC.gapChoices(nouns[0], m2, W, I);
  check("gapChoices: blank found via w -> article outside blank, every option bare", !!m2 && m2.text === "gioco" && gc2.a === "gioco" && gc2.opts.every(o => !/^(il|la) /.test(o)));
  // Elided alt (acqua -> blank l'acqua): answer stays bare w, distractors bare.
  const s3 = { id:"s3", t:"Bevo l'acqua.", en:"x", lv:"A1", words:["acqua"] };
  const gc3 = VC.gapChoices(acqua, VC.gapMatch(s3, acqua, BY, I), W, I);
  check("gapChoices: elided alt blank (l'acqua) -> answer 'acqua', distractors bare", gc3.a === "acqua" && gc3.opts.every(o => !/^(il|la) /.test(o)));
  // zh: no alts -> unchanged behaviour (labels are w).
  const zs = SENTENCES.find(s => VC.gapCandidateIndices(s, BY_ID, PACK).length);
  const ze = BY_ID[zs.words[VC.gapCandidateIndices(zs, BY_ID, PACK)[0]]];
  const zgc = VC.gapChoices(ze, VC.gapMatch(zs, ze, BY_ID, PACK), WORDS, PACK);
  check("gapChoices on zh: labels are w, answer is w", zgc.a === ze.w && zgc.opts.every(o => BY_ID[zgc.byLabel[o].id].w === o));

  // exampleSentences: only sentences listing the id; visible-w first, then visible-alt, then rest; pack order within tiers.
  const S = [
    { id:"e1", t:"Giochi sempre.", en:"x", lv:"A1", words:["n0"] },          // headword not visible
    { id:"e2", t:"Un gioco nuovo.", en:"x", lv:"A1", words:["n0"] },         // alt visible
    { id:"e3", t:"Il padre dorme.", en:"x", lv:"A1", words:["n1"] },         // other word
    { id:"e4", t:"La gioco? Il gioco!", en:"x", lv:"A1", words:["n0"] },     // w visible
    { id:"e5", t:"Il gioco è qui.", en:"x", lv:"A1", words:["n0"] }          // w visible
  ];
  const ex = VC.exampleSentences(nouns[0], S, I, 2).map(s=>s.id);
  const exAll = VC.exampleSentences(nouns[0], S, I, 10).map(s=>s.id);
  check("exampleSentences: prefers sentences showing w, then an alt, then the rest; never other words' sentences",
    util.isDeepStrictEqual(ex, ["e4","e5"]) && util.isDeepStrictEqual(exAll, ["e4","e5","e2","e1"]));
  const zex = VC.exampleSentences(ze, SENTENCES, PACK, 2);
  check("exampleSentences on zh: every example lists the word id and shows its w",
    zex.length > 0 && zex.every(s => s.words.includes(ze.id) && s.t.includes(ze.w)));

  // audioSlot: one audio object for any number of plays; previous paused before each new play.
  let made = 0, pauses = 0;
  const slot = VC.audioSlot(() => { made++; return { src:"", pause(){ pauses++; } }; });
  const a1 = slot.play("x.mp3"); slot.play("y.mp3"); slot.play("y.mp3"); slot.stop();
  const a4 = slot.play("z.mp3");
  check("audioSlot: 4 plays -> 1 audio object, previous paused each time, src updated", made === 1 && a1 === a4 && pauses === 4 && a4.src === "z.mp3");
  const fresh = VC.audioSlot(() => { made++; return { pause(){} }; }); fresh.stop();
  check("audioSlot: stop() before any play creates nothing", made === 1);
})();

// ------------------------------------------------------------ [17] scripts: RTL, no-space, readings
(function(){
  console.log("\n[17] script display, RTL / no-space synthetic packs, highlight, search, folding");
  const join = parts => parts.map(x=>x.text).join("");
  const hitsOf = parts => parts.filter(x=>x.hit).map(x=>x.text);

  // --- script display props
  const zd = VC.scriptDisplay(PACK);
  check("zh script display: lang from tts ('zh'), LTR, no font/lineHeight overrides, no font link",
    zd.lang === "zh" && zd.rtl === false && zd.fontFamily === null && zd.lineHeight === null && VC.fontsHref(PACK).href === null);
  check("langTag overrides tts; invalid langTag falls back to tts language part",
    VC.targetLang({tts:"ur-PK", langTag:"ur-Arab"}) === "ur-Arab" && VC.targetLang({tts:"fa-IR", langTag:'"><x'}) === "fa" && VC.targetLang({}) === "und");
  check("rtl only when pack.rtl === true", VC.scriptDisplay({tts:"fa-IR", rtl:true}).rtl === true && VC.scriptDisplay({tts:"fa-IR", rtl:"yes"}).rtl === false);
  check("fontFamily: CSS family list accepted; declaration-escaping values refused",
    VC.fontFamilyOf({fontFamily:'"Noto Nastaliq Urdu", serif'}) === '"Noto Nastaliq Urdu", serif' &&
    ["x; color:red", "a}b", "url(http://e/x)", "a<b", "a\\b", "a/*b"].every(f => VC.fontFamilyOf({fontFamily:f}) === null));
  check("lineHeight: number in 1..4 only", VC.lineHeightOf({lineHeight:2.2}) === 2.2 && [0.5, 9, "2", NaN, null].every(n => VC.lineHeightOf({lineHeight:n}) === null));
  const fh = VC.fontsHref({fonts:["Noto Nastaliq Urdu", "Noto Naskh Arabic:wght@400;700", "x&family=y", '"><script>', "a/b", 7]});
  check("fontsHref: only fonts.googleapis.com css2, names +-joined, axis spec kept, unsafe entries rejected and absent from URL",
    fh.href === "https://fonts.googleapis.com/css2?family=Noto+Nastaliq+Urdu&family=Noto+Naskh+Arabic:wght@400;700&display=swap" &&
    fh.rejected.length === 4 && !/script|&family=y|a\/b/.test(fh.href));

  // --- synthetic RTL (Persian-like) pack, typing:null, spaced
  const FA = { key:"fa_t", name:"fa", tts:"fa-IR", rtl:true, levels:[{id:"A1",label:"A1"}], setSize:10, placement:[["A1",1]],
    functionWords:["man"], typing:null, showPron:true, hasLessons:false };
  const FW = [
    { id:"man", w:"من", en:"I", lv:"A1", pron:"man" },
    { id:"ketab", w:"کتاب", en:"book", lv:"A1", pron:"ketâb" },
    { id:"khan", w:"خواندن", en:"to read", lv:"A1", pron:"xândan", alt:["می‌خوانم"] },
    { id:"ab", w:"آب", en:"water", lv:"A1", pron:"âb" },
    { id:"abi", w:"آبی", en:"blue", lv:"A1", pron:"âbi" },
    { id:"mi", w:"می", en:"(continuous prefix)", lv:"A1" },
    { id:"khub", w:"خوب", en:"good", lv:"A1" }
  ];
  const FB = {}; FW.forEach(w=>{ FB[w.id] = w; });
  const f1 = { id:"f1", t:"من کتاب را می‌خوانم.", en:"I read the book.", lv:"A1", words:["man","ketab","khan"] };
  const f2 = { id:"f2", t:"آب آبی است.", en:"The water is blue.", lv:"A1", words:["ab","abi"] };
  const f3 = { id:"f3", t:"من می‌خوانم.", en:"I am reading.", lv:"A1", words:["man","mi"] };
  check("RTL: gap candidates skip function word; alt with ZWNJ (می‌خوانم) locates the verb", util.isDeepStrictEqual(VC.gapCandidateIndices(f1, FB, FA), [1,2]));
  const fm = VC.gapMatch(f1, FB.ketab, FB, FA), fb = VC.blankSentence(f1, fm);
  check("RTL: blank splits logical text exactly (before + answer + after = t)", fb.before === "من " && fb.answer === "کتاب" && fb.before + fb.answer + fb.after === f1.t);
  check("RTL: whole-word match (آب not inside آبی)", util.isDeepStrictEqual(VC.gapCandidateIndices(f2, FB, FA), [0,1]) && VC.gapMatch(f2, FB.ab, FB, FA).start === 0);
  check("RTL: ZWNJ is word-internal (می never matches inside می‌خوانم)", VC.findSurface(f3.t, "می", true).length === 0 && VC.gapCandidateIndices(f3, FB, FA).length === 0);
  let noType = true; for(let i=0;i<50;i++){
    const learned = FW.slice();
    if(VC.buildReviewPlan(learned, {w:{}}, FA).some(p=>p.kind==="type") || VC.buildRecallPlan(learned, {w:{}}, FA, 8).some(p=>p.kind!=="recall")) noType = false;
  }
  const kinds = new Set(); for(let i=0;i<2000;i++) kinds.add(VC.sentenceKind(FA));
  const rp = VC.buildReviewPlan(FW, {w:{}}, FA);
  check("RTL typing:null: no type items (review/recall use recall), >=40% production, no typed gap",
    noType && !kinds.has("gapType") && kinds.has("gap") && rp.filter(p=>p.kind==="recall").length / rp.length >= 0.4);
  check("RTL highlight: taught verb bolded via its ZWNJ alt; text round-trips",
    util.isDeepStrictEqual(hitsOf(VC.highlightParts(f1, FB.khan, FB, FA)), ["می‌خوانم"]) && join(VC.highlightParts(f1, FB.khan, FB, FA)) === f1.t);
  // typed answers for an RTL pack with typing on (keyboard variants, harakat, ZWNJ)
  const FAT = Object.assign({}, FA, { typing:{ accents:"lenient" } }), FAS = Object.assign({}, FA, { typing:{ accents:"strict" } });
  check("Arabic-script typing: Arabic kaf/yeh = Persian forms (always); harakat and ZWNJ forgiven only when lenient",
    VC.acceptTyped("كتاب", FB.ketab, FAS) && VC.acceptTyped("کِتاب", FB.ketab, FAT) && !VC.acceptTyped("کِتاب", FB.ketab, FAS) &&
    VC.acceptTyped("میخوانم", FB.khan, FAT) && !VC.acceptTyped("میخوانم", FB.khan, FAS) && !VC.acceptTyped("کتب", FB.ketab, FAT));

  // --- synthetic Japanese-like pack: spaced:false, compounds, kana readings
  const JA = { key:"ja_t", name:"ja", tts:"ja-JP", levels:[{id:"N5",label:"N5"}], setSize:10, placement:[["N5",1]],
    functionWords:["watashi"], typing:null, showPron:true, hasLessons:false, spaced:false, compounds:["日本語"] };
  const JW = [
    { id:"watashi", w:"私", en:"I", lv:"N5", pron:"わたし" },
    { id:"nihon", w:"日本", en:"Japan", lv:"N5", pron:"にほん" },
    { id:"hon", w:"本", en:"book", lv:"N5", pron:"ほん" },
    { id:"gakusei", w:"学生", en:"student", lv:"N5", pron:"がくせい" },
    { id:"yomu", w:"読む", en:"to read", lv:"N5", pron:"よむ", alt:["読みます"] },
    { id:"daigaku", w:"大学", en:"university", lv:"N5", pron:"だいがく" }
  ];
  const JB = {}; JW.forEach(w=>{ JB[w.id] = w; });
  const j1 = { id:"j1", t:"私は日本の学生です。", en:"I am a Japanese student.", lv:"N5", words:["watashi","nihon","gakusei"], pron:"わたしはにほんのがくせいです。" };
  const j2 = { id:"j2", t:"日本語の本を読みます。", en:"I read a Japanese book.", lv:"N5", words:["nihon","hon","yomu"] };
  const j3 = { id:"j3", t:"本を読む。", en:"Read a book.", lv:"N5", words:["hon","yomu"] };
  check("no-space: substring cloze; function word skipped", util.isDeepStrictEqual(VC.gapCandidateIndices(j1, JB, JA), [1,2]));
  check("no-space: 日本 inside compound 日本語 never blanked; 本 visible twice never blanked; alt 読みます blanks",
    util.isDeepStrictEqual(VC.gapCandidateIndices(j2, JB, JA), [2]) && VC.gapMatch(j2, JB.yomu, JB, JA).text === "読みます");
  check("no-space: single visible 本 is blankable", util.isDeepStrictEqual(VC.gapCandidateIndices(j3, JB, JA), [0,1]));
  const hj = VC.highlightParts(j2, JB.hon, JB, JA);
  check("no-space highlight: only the standalone 本 (not the one inside 日本語), at the right offset",
    util.isDeepStrictEqual(hitsOf(hj), ["本"]) && hj[0].text === "日本語の" && join(hj) === j2.t);
  check("no-space highlight: word visible only inside a compound -> no highlight",
    hitsOf(VC.highlightParts(j2, JB.nihon, JB, JA)).length === 0 && join(VC.highlightParts(j2, JB.nihon, JB, JA)) === j2.t);
  check("no-space typing:null: recall only, no typed gap",
    VC.buildRecallPlan(JW, {w:{}}, JA, 6).every(p=>p.kind==="recall") && (()=>{ for(let i=0;i<500;i++) if(VC.sentenceKind(JA)==="gapType") return false; return true; })());

  // --- highlight: spaced Latin, and zh sweep
  const IT = { spaced:true }, gioco = { id:"g", w:"il gioco", alt:["gioco"] };
  check("highlight (spaced): every occurrence, widest form, case-insensitive; absent -> one plain segment",
    util.isDeepStrictEqual(hitsOf(VC.highlightParts({t:"Il gioco è qui, il gioco!"}, gioco, {}, IT)), ["Il gioco","il gioco"]) &&
    util.isDeepStrictEqual(VC.highlightParts({t:"Giochi sempre."}, gioco, {}, IT), [{text:"Giochi sempre.", hit:false}]));
  let zRound = 0, zCut = 0, zHit = 0, zN = 0;
  WORDS.slice(0, 300).forEach(w => VC.exampleSentences(w, SENTENCES, PACK, 2).forEach(s => {
    zN++;
    const parts = VC.highlightParts(s, w, BY_ID, PACK);
    if(join(parts) !== s.t) zRound++;
    let at = 0; parts.forEach(x => { if(x.hit){ zHit++; if(x.text !== w.w || VC.spannedByLonger(s, {start:at, end:at+x.text.length, text:x.text}, BY_ID, PACK)) zCut++; } at += x.text.length; });
  }));
  check(`zh highlight sweep (${zN} examples): text round-trips, hits are the word and never inside a longer word/compound, most examples highlighted`,
    zRound === 0 && zCut === 0 && zHit >= zN * 0.8);

  // --- Words search
  const SW = [
    { id:"a", w:"молоко́", en:"milk", pron:"malakó" },
    { id:"b", w:"کتاب", en:"Book", pron:"ketâb" },
    { id:"c", w:"خواندن", en:"to read", alt:["می‌خوانم"] },
    { id:"d", w:"你好", en:"hello", pron:"nǐ hǎo" },
    { id:"e", w:"perché", en:"why; because" }
  ];
  const sIds = q => VC.searchWords(SW, q).map(v=>v.id).join(",");
  check("search: target text (stress-folded, Arabic kaf variant, ZWNJ-folded), pron (accent/space-folded), gloss (case), alt",
    sIds("молоко") === "a" && sIds("كتاب") === "b" && sIds("میخوانم") === "c" && sIds("nihao") === "d" && sIds("ni hao") === "d" &&
    sIds("BOOK") === "b" && sIds("perche") === "e" && sIds("malako") === "a" && sIds("   ") === "" && sIds("zzz") === "");
  const zw = WORDS.find(w => w.pron && VC.foldAccents(w.pron) !== w.pron);
  check("search on zh: toneless pron finds the word; hanzi finds it", !!zw && VC.searchWords(WORDS, VC.foldAccents(zw.pron)).includes(zw) && VC.searchWords(WORDS, zw.w).includes(zw));
  check("search limit caps results", VC.searchWords(WORDS, "a", 5).length === 5);

  // --- folding keeps letters that marks distinguish
  check("foldAccents: stress/ё folded; й, Devanagari vowel signs, nukta and kana voicing kept (nukta rule changed in [20])",
    VC.foldAccents("молоко́") === "молоко" && VC.foldAccents("ёж") === "еж" && VC.foldAccents("мой") === "мой" &&
    VC.foldAccents("कि") === "कि" && VC.foldAccents("ज़रा") === "ज़रा" && VC.foldAccents("が") === "が" && VC.foldAccents("perché") === "perche");

  // --- showPron default comes from the pack
  check("showPron default comes from pack.showPron", VC.defaultProg({levels:[], showPron:false}).showPron === false && VC.defaultProg({levels:[], showPron:true}).showPron === true);

  // --- app.html render-site guard: every target-text element carries ${TA} (lang/dir/font)
  const app = fs.readFileSync(path.join(ROOT, "engine", "app.html"), "utf8");
  const bare = [...app.matchAll(/class="(big wd|med wd|wd|st|rw)"(?!\$\{TA\})/g)].map(m=>m[0]);
  const optsW = [...app.matchAll(/optHtml: wordOptHtml\([^)]*\)(, optsT: true)?/g)];
  check("app.html: every target-text element (big/med/wd/st/rw) carries ${TA}; every word-option item sets optsT",
    bare.length === 0 && optsW.length >= 2 && optsW.every(m=>!!m[1]) && /id="tin"[^>]*\$\{TA\}/.test(app));
})();

// ------------------------------------------------------------ [18] validator script fields; distractor word class
(function(){
  console.log("\n[18] validate_pack.py script-display fields; word-option distractors keep the answer's word class");
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "vocab_pack_"));
  const run = pack => {
    const words = Array.from({length:20}, (_,i)=>({ id:`a${i}`, w:`w${i}`, en:`gloss ${i}`, lv:"A1" }));
    fs.writeFileSync(path.join(tmp, "pack.json"), JSON.stringify(pack));
    fs.writeFileSync(path.join(tmp, "words.json"), JSON.stringify(words));
    fs.writeFileSync(path.join(tmp, "sentences.json"), "[]");
    cp.spawnSync("python3", [path.join(ROOT, "tools", "jsonify_pack.py"), tmp]);
    return cp.spawnSync("python3", [path.join(ROOT, "tools", "validate_pack.py"), tmp], { encoding:"utf8" });
  };
  const base = { key:"t", name:"T", tts:"fa-IR", levels:[{id:"A1",label:"A1"}], placement:[["A1",2]], typing:null, showPron:false, hasLessons:false };
  const good = run(Object.assign({}, base, { rtl:true, langTag:"fa", fontFamily:'"Noto Naskh Arabic", serif', fonts:["Noto Naskh Arabic:wght@400;700"], lineHeight:2 }));
  check("validator: valid rtl/langTag/fontFamily/fonts/lineHeight -> 0 errors, no rtl-font warning", good.status === 0 && !/rtl is true/.test(good.stdout));
  const bad = run(Object.assign({}, base, { rtl:"yes", langTag:'"><x', fontFamily:"x; color:red", fonts:["x&family=y"], lineHeight:9 }));
  const need = [/pack\.rtl must be a boolean/, /pack\.langTag must be/, /pack\.fontFamily must not contain/, /pack\.fonts\[0\]/, /pack\.lineHeight must be/];
  check("validator: each invalid script field is its own error", bad.status === 1 && need.every(re => re.test(bad.stdout)));
  const warn = run(Object.assign({}, base, { rtl:true }));
  check("validator: rtl without fontFamily/fonts is a warning, not an error", warn.status === 0 && /rtl is true but neither fontFamily nor fonts/.test(warn.stdout));
  fs.rmSync(tmp, { recursive:true, force:true });

  // Distractor word class (recall and gap share wordOpts).
  const P = { functionWords:["f0","f1","f2","f3"] };
  const W = [
    ...[["il","the"],["di","of"],["e","and"],["che","that"]].map(([w,en],i)=>({ id:`f${i}`, w, en, lv:"A1", pos:"x" })),
    ...[["casa","house"],["cane","dog"],["gatto","cat"],["libro","book"],["sole","sun"]].map(([w,en],i)=>({ id:`c${i}`, w, en, lv:"A1", pos:"n" }))
  ];
  let contentOk = true, fnOk = true;
  for(let i=0;i<200;i++){
    if(VC.wordOpts(W[4], W, null, P).some(d => P.functionWords.includes(d.id))) contentOk = false;
    if(!VC.wordOpts(W[0], W, null, P).every(d => P.functionWords.includes(d.id))) fnOk = false;
  }
  check("wordOpts: content-word answer never gets a function-word distractor; function-word answer gets function words first", contentOk && fnOk);
  const tinyFn = [W[0], W[1], ...W.slice(4)];
  check("wordOpts: function-word answer falls back to content words when too few function words", VC.wordOpts(W[0], tinyFn, null, P).length === 3);
  const s = { id:"s", t:"Il cane e il gatto.", en:"x", lv:"A1", words:["f0","c1","f2","c2"] };
  const BY = {}; W.forEach(w=>{ BY[w.id] = w; });
  let gapOk = true;
  for(let i=0;i<100;i++){ const gc = VC.gapChoices(BY.c1, VC.gapMatch(s, BY.c1, BY, P), W, P); if(gc.opts.some(o => ["il","di","e","che"].includes(o)) || gc.opts.length !== 4) gapOk = false; }
  check("gapChoices: 4 options, none a function word, for a content-word blank", gapOk);
  let zhFw = 0; const zfw = new Set(PACK.functionWords);
  SENTENCES.slice(0, 300).forEach(zs => VC.gapCandidateIndices(zs, BY_ID, PACK).forEach(ix => {
    const e = BY_ID[zs.words[ix]]; const gc = VC.gapChoices(e, VC.gapMatch(zs, e, BY_ID, PACK), WORDS, PACK);
    if(Object.values(gc.byLabel).some(v => v.id !== e.id && zfw.has(v.id))) zhFw++;
  }));
  check("zh gap sweep (300 sentences): no function-word distractor in any cloze", zhFw === 0);
})();

// ------------------------------------------------------------ [19] gap articles: blank never includes the article, options always bare
(function(){
  console.log("\n[19] gap article rule (fr/es browser-verify)");
  const F = { levels:[{id:"A1",label:"A1"}], functionWords:["le","un"], spaced:true, typing:{ enabled:true, accents:"lenient" } };
  const W = [
    { id:"le", w:"le", en:"the", lv:"A1", pos:"art", alt:["la","l'","les"] },
    { id:"un", w:"un", en:"a", lv:"A1", pos:"art", alt:["une"] },
    { id:"eg", w:"l'église", en:"church", lv:"A1", pos:"noun", alt:["église","églises"] },
    { id:"fr", w:"le fruit", en:"fruit", lv:"A1", pos:"noun", alt:["fruit","fruits"] },
    { id:"lo", w:"la loi", en:"law", lv:"A1", pos:"noun", alt:["loi","lois"] },
    { id:"oe", w:"l'œuf", en:"egg", lv:"A1", pos:"noun", alt:["œuf","œufs"] },
    { id:"se", w:"le/la secrétaire", en:"secretary", lv:"A1", pos:"noun", alt:["secrétaire","secrétaires"] },
    { id:"me", w:"le/la médecin", en:"doctor", lv:"A1", pos:"noun" },                 // no alt: article list strips it
    { id:"di", w:"dimanche", en:"Sunday", lv:"A1", pos:"noun" },
    { id:"ga", w:"la gare", en:"station", lv:"A1", pos:"noun" },                        // no alt
  ];
  const BY = {}; W.forEach(w => { BY[w.id] = w; });
  const ARTED = /^(le|la|les|l'|l’|un|une)(\/(le|la))?( |(?<='))/i;
  const sweep = (entry, sent, n) => { const out = []; for(let i=0;i<(n||60);i++) out.push(VC.gapChoices(entry, VC.gapMatch(sent, entry, BY, F), W, F)); return out; };
  // Class 1: sentence form carries the article -> article stays visible, blank bare.
  const s1 = { id:"s1", t:"Ce soir nous allons à l'église.", en:"x", lv:"A1", words:["le","eg"] };
  const m1 = VC.gapMatch(s1, BY.eg, BY, F), b1 = VC.blankSentence(s1, m1);
  check("articled blank (l'église): elided article stays before the blank, blank = église", !!m1 && m1.text === "église" && b1.before === "Ce soir nous allons à l'");
  const s1b = { id:"s1b", t:"La gare est loin.", en:"x", lv:"A1", words:["le","ga"] };
  const m1b = VC.gapMatch(s1b, BY.ga, BY, F), b1b = VC.blankSentence(s1b, m1b);
  check("articled blank, word without alt (La gare): 'La ' visible, blank = gare", !!m1b && m1b.text === "gare" && b1b.before === "La ");
  check("articled blank: still a gap candidate (article outside blank does not count as a longer surface)", VC.gapCandidateIndices(s1, BY, F).length === 1);
  check("articled blank: every option bare, answer église",
    sweep(BY.eg, s1).every(gc => gc.a === "église" && gc.opts.length === 4 && gc.opts.every(o => !ARTED.test(o)) && gc.byLabel["église"] === BY.eg));
  // Class 2: bare blank ("le ____" for dimanche) never mixes in articled distractors.
  const s2 = { id:"s2", t:"Je travaille même le dimanche.", en:"x", lv:"A1", words:["le","di"] };
  const m2 = VC.gapMatch(s2, BY.di, BY, F);
  check("mixed options: bare blank -> no articled distractor (le fruit / la loi / l'œuf shown bare)",
    !!m2 && m2.text === "dimanche" && sweep(BY.di, s2, 100).every(gc => gc.opts.length === 4 && gc.opts.every(o => !ARTED.test(o))));
  // Class 3: double-article words are shown bare, with or without alt[0].
  check("double article: bareForm(le/la secrétaire) = secrétaire; without alt, le/la médecin -> médecin via pack articles",
    VC.bareForm(BY.se) === "secrétaire" && VC.bareForm(BY.me, VC.packArticles(W)) === "médecin" && VC.bareForm(BY.me) === "le/la médecin");
  let dbl = true; for(let i=0;i<100;i++){ const gc = VC.gapChoices(BY.di, m2, W, F); if(gc.opts.some(o => o.includes("/"))) dbl = false; }
  check("double article: never shown verbatim as a gap option", dbl);
  const s3 = { id:"s3", t:"Le médecin arrive.", en:"x", lv:"A1", words:["le","me"] };
  const m3 = VC.gapMatch(s3, BY.me, BY, F);
  check("double-article word blanked in a sentence: 'Le ' visible, blank médecin, answer médecin",
    !!m3 && m3.text === "médecin" && VC.gapChoices(BY.me, m3, W, F).a === "médecin");
  // articleCut only strips pack articles, never an ordinary apostrophe word.
  const A = VC.packArticles(W);
  check("articleCut: le/l'/les/le-la strip; aujourd'hui, 'lecture', bare 'le' untouched",
    VC.articleCut("le fruit", A) === 3 && VC.articleCut("l’œuf", A) === 2 && VC.articleCut("le/la secrétaire", A) === 6 &&
    VC.articleCut("aujourd'hui", A) === 0 && VC.articleCut("lecture", A) === 0 && VC.articleCut("le", A) === 0 && VC.articleCut("le fruit", new Set()) === 0);
  // Typed gap: the bare blank, alt forms and w are all accepted.
  const extra = [m1.text];
  check("gap-type: accepts bare blank, alt forms, w; rejects a distractor",
    VC.acceptTyped("église", BY.eg, F, extra) && VC.acceptTyped("eglise", BY.eg, F, extra) && VC.acceptTyped("églises", BY.eg, F, extra) &&
    VC.acceptTyped("l'église", BY.eg, F, extra) && !VC.acceptTyped("gare", BY.eg, F, extra));
  // zh (no articles): gap matches unchanged.
  let zhSame = true;
  SENTENCES.slice(0, 200).forEach(zs => VC.gapCandidateIndices(zs, BY_ID, PACK).forEach(ix => {
    const e = BY_ID[zs.words[ix]], m = VC.gapMatch(zs, e, BY_ID, PACK), l = VC.locateWord(zs, e, PACK);
    if(!l || m.start !== l.start || m.end !== l.end || VC.gapChoices(e, m, WORDS, PACK).a !== e.w) zhSame = false;
  }));
  check("zh (no articles): gap span = located span, answer label = w", zhSame);
})();

// ------------------------------------------------------------ [20] Russian browser-verify round
(function(){
  console.log("\n[20] script-aware fold, pron display, search ranking");
  const F = VC.foldAccents, same = (a, b) => F(a) === F(b);
  // A. Marks that make a distinct letter never fold, in any script; accents/stress/pointing do.
  check("fold keeps distinct letters: й≠и, ї≠і, ў≠у (also after NFD input, re-composed)",
    !same("й","и") && !same("ї","і") && !same("ў","у") && !same("Й","И") && F("мои\u0306") === "мой");
  check("lenient typing: твои/мои rejected for твой/мой; stress-less делать and е-for-ё accepted", (() => {
    const P = { typing:{ accents:"lenient" } };
    return !VC.acceptTyped("твои", { w:"твой" }, P) && !VC.acceptTyped("мои", { w:"мой" }, P) &&
      VC.acceptTyped("делать", { w:"де́лать" }, P) && VC.acceptTyped("еж", { w:"ёж" }, P) && VC.acceptTyped("твой", { w:"твой" }, P);
  })());
  check("fold: Arabic hamza letters stay distinct (أ إ آ ؤ ئ ۀ vs base); harakat and tatweel fold",
    !same("أ","ا") && !same("إ","ا") && !same("آ","ا") && !same("ؤ","و") && !same("ئ","ي") && !same("ۀ","ه") &&
    F("كَتَبَ") === "كتب" && F("كـتاب") === "كتاب" && F("سؤال") === "سؤال");
  check("fold: Devanagari nukta/virama and kana (han)dakuten stay distinct",
    !same("ज़","ज") && !same("ड़","ड") && !same("क्","क") && !same("が","か") && !same("ぱ","は") && !same("ば","は"));
  check("fold: Latin accents, Cyrillic stress/ё, Hebrew niqqud, ZWNJ still fold",
    F("perché") === "perche" && F("ñ") === "n" && F("моло́ко") === "молоко" && F("ё") === "е" && F("שָׁלוֹם") === "שלום" && F("می\u200cروم") === "میروم");
  check("lenient typing: ещё/еще both ways; fully vocalised Arabic = unvocalised; か rejected for が; ا rejected for أ", (() => {
    const P = { typing:{ accents:"lenient" } };
    return VC.acceptTyped("еще", { w:"ещё" }, P) && VC.acceptTyped("ещё", { w:"еще" }, P) &&
      VC.acceptTyped("مدرسة", { w:"مَدْرَسَةٌ" }, P) && VC.acceptTyped("مَدْرَسَةٌ", { w:"مدرسة" }, P) &&
      !VC.acceptTyped("か", { w:"が" }, P) && !VC.acceptTyped("امس", { w:"أمس" }, P) && VC.acceptTyped("أَمْس", { w:"أمس" }, P);
  })());
  // C. pron hidden when it only repeats the text.
  check("pronShown: hidden when pron = w (в/в, case/NFC-insensitive) or = sentence text; stress-marked pron kept",
    VC.pronShown({ w:"в", pron:"в" }) === "" && VC.pronShown({ w:"Я", pron:"я" }) === "" && VC.pronShown({ t:"да", pron:"да" }) === "" &&
    VC.pronShown({ w:"делать", pron:"де́лать" }) === "де́лать" && VC.pronShown({ w:"你好", pron:"nǐ hǎo" }) === "nǐ hǎo" && VC.pronShown({ w:"x" }) === "");
  // D. exact match ranks first, then whole gloss sense, then prefix, then the rest (pack order within tiers).
  const SW = [
    { id:"sd", w:"сделать", pron:"сде́лать", en:"to do (pf.)" },
    { id:"pd", w:"переделать", en:"to redo" },
    { id:"dl", w:"делать", pron:"де́лать", en:"to do (impf.)" },
    { id:"dv", w:"дело", en:"matter, deal" },
    { id:"bk", w:"книжка", en:"booklet" },
    { id:"bo", w:"книга", en:"book, volume" },
  ];
  const ids = q => VC.searchWords(SW, q).map(v => v.id).join(",");
  check("search ranking: exact lemma first (делать before сделать), stress-folded pron counts as exact",
    ids("делать") === "dl,sd,pd" && ids("де́лать") === "dl,sd,pd" && ids("book") === "bo,bk" && ids("дел") === "dl,dv,sd,pd");
  // Pack-sized synthetic fixture (not the live ../russian pack): exact lemma beats the
  // many words that contain it, whatever their pack order.
  const RW = [...Array.from({ length: 300 }, (_, i) => ({ id:"f"+i, w:"пере"+"делать".slice(0, 1 + i % 6)+i, en:"filler "+i })),
    { id:"sd2", w:"сделать", pron:"сде́лать", en:"to do (pf.)" }, { id:"dl2", w:"делать", pron:"де́лать", en:"to do (impf.)" }];
  check("search ranking on a 302-word fixture: exact делать first although last in pack order; сделать still listed", (() => { const r = VC.searchWords(RW, "делать"); return r[0].id === "dl2" && r.some(v => v.id === "sd2"); })());
  // Folded fields are cached per word but refreshed when the word's text changes.
  const mut = [{ id:"m", w:"кот", en:"cat" }];
  const firstHit = VC.searchWords(mut, "кот").length; mut[0].w = "пёс";
  check("search cache: a changed word is re-folded (old text no longer matches, new does)", firstHit === 1 && VC.searchWords(mut, "кот").length === 0 && VC.searchWords(mut, "пес").length === 1);
})();

// ------------------------------------------------------------ [21] review round: article agreement, fixed expressions, clitics
(function(){
  console.log("\n[21] gap article agreement, articleCut on fixed expressions, reflexive clitics");
  const mk = (id, w, en, pos, alt) => ({ id, w, en, lv:"A1", pos: pos || "noun", alt: alt || [String(w).replace(/^(il\/la|il|lo|la|l') ?/, "")] });
  const IT = { tts:"it-IT", levels:[{id:"A1",label:"A1"}], functionWords:["il","un"], spaced:true };
  const W = [
    { id:"il", w:"il", en:"the", lv:"A1", pos:"art", alt:["lo","la","l'","i","gli","le"] },
    { id:"un", w:"un", en:"a", lv:"A1", pos:"art", alt:["uno","una","un'"] },
    mk("mela","la mela","apple"), mk("casa","la casa","house"), mk("sedia","la sedia","chair"), mk("porta","la porta","door"), mk("strada","la strada","road"),
    mk("conto","il conto","bill"), mk("gior","il giornale","newspaper"), mk("libro","il libro","book"), mk("treno","il treno","train"), mk("cane","il cane","dog"),
    mk("amico","l'amico","friend"), mk("acqua","l'acqua","water"), mk("isola","l'isola","island"), mk("uovo","l'uovo","egg"),
    mk("zaino","lo zaino","backpack"), mk("coll","il/la collega","colleague"),
    mk("peu","un po'","a bit","adv", []), mk("luno","l'uno","the one","pron", []),
    { id:"alz", w:"alzarsi", en:"to get up", lv:"A1", pos:"verb" },
  ];
  const BY = {}; W.forEach(w => { BY[w.id] = w; });
  const A = VC.packArticles(W);
  const run = (entry, t, n) => { const s = { id:"x", t, en:"x", lv:"A1", words:[entry.id] }; const m = VC.gapMatch(s, entry, BY, IT);
    const out = []; for(let i=0;i<(n||80);i++){ const gc = VC.gapChoices(entry, m, W, IT); out.push(gc.opts.slice(1).map(o => gc.byLabel[o])); } return { m, out }; };
  const agrees = (ds, ok) => ds.every(v => VC.citationArticles(v, A).some(a => ok.includes(a)));
  const la = run(BY.mela, "Mangio la mela.");
  check("agreement: 'la ____' -> every distractor a la-noun (or le/la), over 80 draws", la.m && la.m.article === "la" && la.out.every(ds => ds.length === 3 && agrees(ds, ["la"])));
  const el = run(BY.amico, "Vedo l'amico.");
  check("agreement: elided 'l'____' -> every distractor an l'-noun (either gender)", el.m && el.m.article === "l'" && el.out.every(ds => ds.length === 3 && agrees(ds, ["l'"])));
  const il = run(BY.conto, "Pago il conto.");
  check("agreement: 'il ____' -> il-nouns (il/la collega counts)", il.out.every(ds => agrees(ds, ["il"])));
  const lo = run(BY.zaino, "Porto lo zaino.");
  check("agreement fallback: 'lo ____' with no other lo-noun still gets 3 distractors", lo.m.article === "lo" && lo.out.every(ds => ds.length === 3));
  const none = run(BY.mela, "Mela!");
  check("no visible article -> article '' and 3 distractors", none.m && none.m.article === "" && none.out.every(ds => ds.length === 3));
  // German case forms via the default table (de): den -> masculine citation (der).
  const DE = { tts:"de-DE", levels:[{id:"A1",label:"A1"}], functionWords:["der"], spaced:true };
  const G = [{ id:"der", w:"der", en:"the", lv:"A1", pos:"art", alt:["die","das","den","dem","des"] },
    ...[["hund","der Hund"],["tisch","der Tisch"],["baum","der Baum"],["stuhl","der Stuhl"],["katze","die Katze"],["tür","die Tür"],["haus","das Haus"],["buch","das Buch"]]
      .map(([id,w]) => ({ id, w, en:id, lv:"A1", pos:"noun", alt:[w.split(" ")[1]] }))];
  const GB = {}; G.forEach(w => { GB[w.id] = w; }); const GA = VC.packArticles(G);
  const gm = VC.gapMatch({ id:"g", t:"Ich sehe den Hund.", en:"x", lv:"A1", words:["hund"] }, GB.hund, GB, DE);
  let deOk = gm && gm.article === "den" && gm.text === "Hund";
  for(let i=0;i<60 && deOk;i++){ const gc = VC.gapChoices(GB.hund, gm, G, DE); deOk = gc.opts.slice(1).every(o => VC.citationArticles(gc.byLabel[o], GA).includes("der")); }
  check("agreement (de): 'den ____' -> der-nouns only (Tisch, Baum, Stuhl)", deOk);
  check("pack.articleAgreement overrides the default table", (() => { const P2 = Object.assign({}, IT, { articleAgreement:{ la:["il"] } });
    const m = VC.gapMatch({ id:"y", t:"Mangio la mela.", en:"x", lv:"A1", words:["mela"] }, BY.mela, BY, P2);
    const gc = VC.gapChoices(BY.mela, m, W, P2); return gc.opts.slice(1).every(o => VC.citationArticles(gc.byLabel[o], A).includes("il")); })());
  // Fixed expressions: never cut.
  const FA = new Set(["le","la","l'","les","un","une"]);
  check("articleCut: 'un peu', 'l'un', 'les uns les autres', 'tout le monde' unchanged for their entries",
    VC.articleCut("un peu", FA, { w:"un peu", pos:"adv" }) === 0 && VC.articleCut("l'un", FA) === 0 && VC.articleCut("l'un", FA, { w:"l'un", pos:"pron" }) === 0 &&
    VC.articleCut("les uns les autres", FA, { w:"les uns les autres", pos:"pron" }) === 0 && VC.articleCut("tout le monde", FA) === 0 &&
    VC.bareForm({ w:"un peu", pos:"adv" }, FA) === "un peu" && VC.bareForm({ w:"les uns les autres", pos:"pron" }, FA) === "les uns les autres" &&
    VC.articleCut("le fruit", FA, { w:"le fruit", pos:"noun" }) === 3 && VC.articleCut("la plupart", FA, { w:"la plupart", pos:"adv", alt:["plupart"] }) === 3);
  check("gap: 'un po'' (adv) is blanked whole, never 'un ____'", (() => { const m = VC.gapMatch({ id:"p", t:"Aspetta un po'.", en:"x", lv:"A1", words:["peu"] }, BY.peu, BY, IT); return !!m && m.text === "un po'"; })());
  // Reflexive clitics are never cut: a span that keeps a clitic its label would drop is no blank.
  const F = { tts:"fr-FR", levels:[{id:"A1",label:"A1"}], functionWords:["le"], spaced:true };
  const FW = [{ id:"le", w:"le", en:"the", lv:"A1", pos:"art", alt:["la","l'","les"] },
    { id:"lev", w:"se lever", en:"to get up", lv:"A1", pos:"verb", alt:["lever","lève"] },
    { id:"ass", w:"s'asseoir", en:"to sit down", lv:"A1", pos:"verb", alt:["asseoir"] }, mk("gare","la gare","station")];
  const FB = {}; FW.forEach(w => { FB[w.id] = w; });
  check("clitic: 'se lever' / 's'asseoir' found verbatim -> no blank (never 'se ____' or 's'____')",
    VC.gapMatch({ id:"c1", t:"Il faut se lever tôt.", en:"x", lv:"A1", words:["lev"] }, FB.lev, FB, F) === null &&
    VC.gapMatch({ id:"c2", t:"Tu vas s'asseoir ici.", en:"x", lv:"A1", words:["ass"] }, FB.ass, FB, F) === null);
  check("clitic: bare form in the sentence is still a blank ('Je me lève' -> blank lève, label lever)", (() => {
    const m = VC.gapMatch({ id:"c3", t:"Je me lève tôt.", en:"x", lv:"A1", words:["lev"] }, FB.lev, FB, F);
    return !!m && m.text === "lève" && m.article === "" && VC.gapChoices(FB.lev, m, FW, F).a === "lever"; })());
})();

// ------------------------------------------------------------ [22] reading passages
(function(){
  console.log("\n[22] reading passages: unlock, grading, weak words, progress, validator");
  const RP = { key:"rp", name:"RP", tts:"it-IT", levels:[{id:"A1",label:"A1"},{id:"A2",label:"A2"}], placement:[["A1",2]], typing:null, showPron:false, hasLessons:false };
  const RW = [...Array.from({length:20}, (_,i)=>({ id:`a${i}`, w:`parola${i}`, en:`word a ${i}`, lv:"A1" })),
              ...Array.from({length:10}, (_,i)=>({ id:`b${i}`, w:`voce${i}`, en:`word b ${i}`, lv:"A2" }))];
  RW[0].w = "casa"; RW[1].w = "andare"; RW[1].alt = ["vado"]; RW[2].w = "il gatto"; RW[2].alt = ["gatto"]; RW[3].w = "correre";
  const RB = {}; RW.forEach(w => { RB[w.id] = w; });
  const q = (type, answer, words, sentence) => ({ q:"Domanda?", type, options: type === "mc" ? ["uno","due","tre","quattro"] : null, answer, words, sentence });
  const P1 = { id:"p0001", lv:"A1", title:"La casa", text:"Vado a casa. Il gatto dorme.", src:"gen",
    sentences:[{ t:"Vado a casa.", en:"I go home.", words:["a1","a0","a3"] }, { t:"Il gatto dorme.", en:"The cat sleeps.", words:["a2"] }],
    questions:[q("mc", 1, ["a0"], 0), q("tf", true, ["a2"], 1), q("mc", 3, ["a1"], 0)] };
  const P2 = { id:"p0002", lv:"A1", title:"Il gatto", text:"Il gatto dorme.", sentences:[{ t:"Il gatto dorme.", en:"The cat sleeps.", words:["a2"] }], questions:[q("tf", false, ["a2"], 0)] };
  const P3 = { id:"p0003", lv:"A2", title:"Voce", text:"voce0 voce1.", sentences:[{ t:"voce0 voce1.", en:"x", words:["b0","b1"] }], questions:[q("tf", true, ["b0"], 0)] };
  const PS = [P1, P2, P3];

  // unlock thresholds
  const prog = VC.normalizeProg({}, RP);
  const lv0 = VC.readingLevels(PS, RW, RP, prog);
  check("fresh learner: no level unlocked; A1 needs ceil(0.7*20)=14", lv0.every(l => !l.unlocked) && lv0[0].need === 14 && lv0[0].count === 2 && lv0[1].need === 7);
  prog.sets.A1 = 1;
  check("10/20 learned (50%) -> A1 still locked, suggestion null", !VC.readingLevels(PS, RW, RP, prog)[0].unlocked && VC.suggestPassage(PS, RW, RP, prog) === null);
  prog.w.a10 = { r:1, w:0, s:1, d:1 }; prog.w.a11 = { r:1, w:0, s:1, d:1 }; prog.w.a12 = { r:1, w:0, s:1, d:1 };
  check("13/20 (65%) -> locked", !VC.readingLevels(PS, RW, RP, prog)[0].met);
  prog.w.a13 = { r:1, w:0, s:1, d:1 };
  check("14/20 (70%) -> A1 unlocked", VC.readingLevels(PS, RW, RP, prog)[0].met);
  check("updateReadUnlocks records A1 once (sticky in prog.read.unlocked)", util.isDeepStrictEqual(VC.updateReadUnlocks(PS, RW, RP, prog), ["A1"]) && prog.read.unlocked.A1 === 1 && VC.updateReadUnlocks(PS, RW, RP, prog).length === 0);
  const dropped = JSON.parse(JSON.stringify(prog)); dropped.sets.A1 = 0;
  check("stored unlock survives a drop below the threshold", VC.readingLevels(PS, RW, RP, dropped)[0].unlocked && !VC.readingLevels(PS, RW, RP, dropped)[0].met);
  check("A2 stays locked (0 learned)", !VC.readingLevels(PS, RW, RP, prog)[1].unlocked);
  check("suggestPassage -> first not-done passage at an unlocked level", VC.suggestPassage(PS, RW, RP, prog) === P1);

  // grading
  check("gradeQuestion mc: right index true, wrong index / string / bool false",
    VC.gradeQuestion(P1.questions[0], 1) && !VC.gradeQuestion(P1.questions[0], 0) && !VC.gradeQuestion(P1.questions[0], "1") && !VC.gradeQuestion(P1.questions[0], true));
  check("gradeQuestion tf: bool compare, non-bool false",
    VC.gradeQuestion(P1.questions[1], true) && !VC.gradeQuestion(P1.questions[1], false) && !VC.gradeQuestion(P1.questions[1], 1) && VC.gradeQuestion(P2.questions[0], false));

  // weak words: tapped a3 + a0; q0 wrong (a0: tapped and wrong -> 2, not 4); q1 right after reopening (a2 -> 1);
  // q2 right (a1 not weak). Unknown ids dropped.
  const log = { tapped:["a3","a0","zz"], answers:[{ ok:false, reopened:false }, { ok:true, reopened:true }, { ok:true, reopened:false }] };
  const weak = VC.passageWeakWords(P1, log, RB);
  const W = {}; weak.forEach(e => { W[e.id] = e; });
  check("weak words = tapped ∪ wrong-question words ∪ reopened-question words", util.isDeepStrictEqual(weak.map(e => e.id), ["a3","a0","a2"]));
  check("weights: tapped 2, tapped+wrong 2 (max, not sum), reopened only 1", W.a3.weight === 2 && W.a0.weight === 2 && W.a2.weight === 1 && util.isDeepStrictEqual(W.a0.why, ["tapped","wrong"]));
  check("wrong + reopened on the same question -> 2", VC.passageWeakWords(P1, { tapped:[], answers:[{ ok:false, reopened:true }] }, RB)[0].weight === 2);
  check("all right, nothing tapped or reopened -> no weak words", VC.passageWeakWords(P1, { tapped:[], answers:[{ok:true},{ok:true},{ok:true}] }, RB).length === 0);

  // apply to progress: learned word (a0) and unlearned words (a2 is in set 1: learned; a3 learned) — use a19 (unlearned) too.
  const before = JSON.parse(JSON.stringify(prog));
  prog.w.a0 = { r:3, w:0, s:3, prov:1 };
  VC.applyWeakWords(prog, [...weak, { id:"a19", weight:2 }, { id:"a18", weight:0 }], RW, RP);
  check("applyWeakWords: misses += weight, streak reset, prov cleared", prog.w.a0.w === 2 && prog.w.a0.s === 0 && !prog.w.a0.prov && prog.w.a2.w === 1 && prog.w.a3.w === 2);
  check("applyWeakWords: unlearned word flagged d (joins review pool); learned word not flagged; weight 0 ignored",
    prog.w.a19.d === 1 && prog.w.a19.w === 2 && !prog.w.a0.d && !prog.w.a18 && before.w.a19 === undefined);
  check("weakScore ranks applied words above untouched ones", VC.weakScore(prog.w.a0) > 0 && VC.weakScore(prog.w.a2) > 0 && VC.weakScore(prog.w.a5) <= 0);
  const lw = VC.learnedWords(RW, RP, prog);
  let inReview = true;
  for(let i=0;i<30;i++){ const ids = new Set(VC.buildReviewPlan(lw, prog, RP).map(p => p.word.id)); if(!["a0","a2","a3","a19"].every(id => ids.has(id))) inReview = false; }
  check("Today's review plan includes every applied weak word (30 draws)", inReview);

  // passage done + stats
  VC.markPassageDone(prog, "p0001", 2, 3, "2026-09-24");
  check("markPassageDone stores {sc,n,d,x}", util.isDeepStrictEqual(prog.read.done.p0001, { sc:2, n:3, d:"2026-09-24", x:1 }));
  check("suggestPassage moves to the next not-done passage", VC.suggestPassage(PS, RW, RP, prog) === P2);
  VC.markPassageDone(prog, "p0002", 1, 1, "2026-09-25");
  check("all unlocked passages done -> no suggestion", VC.suggestPassage(PS, RW, RP, prog) === null);
  VC.markPassageDone(prog, "p0001", 3, 3, "2026-09-26");
  const st = VC.readingStats(PS, RP, prog);
  check("readingStats: A1 2/2 done, avg of latest scores (100%, 100%); A2 0/1, avg null", st.length === 2 && st[0].done === 2 && st[0].total === 2 && st[0].avg === 100 && st[1].done === 0 && st[1].avg === null && prog.read.done.p0001.x === 2);

  // progress shape and round trip
  const L = VC.levelIds(RP);
  check("validateProgShape accepts prog with read state", VC.validateProgShape(JSON.parse(JSON.stringify(prog)), L).ok);
  check("validateProgShape accepts old progress without read", VC.validateProgShape({ w:{}, sets:{A1:1} }, L).ok);
  const badRead = [{ read:[] }, { read:{ done:[] } }, { read:{ unlocked:{ A1:"yes" } } }, { read:{ done:{ p:{ sc:"2" } } } }, { read:{ done:{ p:{ d:20260924 } } } }, { read:{ done:{ p:1 } } }];
  check("validateProgShape rejects malformed read shapes", badRead.every(b => !VC.validateProgShape(b, L).ok));
  const imp = VC.applyImport(VC.normalizeProg({}, RP), JSON.stringify(prog), RP);
  check("export -> import round trip keeps read state and word records", imp.ok && util.isDeepStrictEqual(imp.prog.read, prog.read) && util.isDeepStrictEqual(imp.prog.w, prog.w));
  const boot = VC.bootProg(JSON.stringify(prog), RP);
  check("boot from stored progress keeps read state", boot.backupRaw === null && util.isDeepStrictEqual(boot.prog.read, prog.read));
  const oldBoot = VC.bootProg(JSON.stringify({ v:1, w:{ a0:{r:1,w:0,s:1} }, sets:{ A1:1 } }), RP);
  check("boot from old progress (no read keys) is fine; read state created lazily", oldBoot.backupRaw === null && oldBoot.prog.read === undefined &&
    VC.readingLevels(PS, RW, RP, oldBoot.prog).length === 2 && VC.suggestPassage(PS, RW, RP, oldBoot.prog) === null);

  // segments + length
  const seg = VC.passageSegments(P1.sentences[0], RB, RP);
  check("passageSegments: alt 'vado' and w 'casa' tappable; invisible 'correre' listed as unplaced; text rejoins",
    seg.parts.map(p => p.text).join("") === P1.sentences[0].t && util.isDeepStrictEqual(seg.parts.filter(p => p.id).map(p => [p.text, p.id]), [["Vado","a1"],["casa","a0"]]) && util.isDeepStrictEqual(seg.unplaced, ["a3"]));
  const seg2 = VC.passageSegments(P1.sentences[1], RB, RP);
  check("passageSegments: articled w 'il gatto' spans the article (longest hit)", util.isDeepStrictEqual(seg2.parts.filter(p => p.id).map(p => p.text), ["Il gatto"]));
  const ZP = { spaced:false }, ZB = { x:{ id:"x", w:"为", en:"for" }, y:{ id:"y", w:"为什么", en:"why" }, z:{ id:"z", w:"你", en:"you" } };
  const zs = VC.passageSegments({ t:"你为什么来？", words:["z","x","y"] }, ZB, ZP);
  check("passageSegments unspaced: 为什么 wins over the 为 inside it; 为 then listed as unplaced (not visible on its own)",
    util.isDeepStrictEqual(zs.parts.filter(p => p.id).map(p => p.id), ["z","y"]) && util.isDeepStrictEqual(zs.unplaced, ["x"]));
  // builder spans: [[start, end, wordId]] UTF-16 offsets; ids without a span fall back to surface matching
  const SB = { g:{ id:"g", w:"il gatto", alt:["gatto"], en:"cat" }, c:{ id:"c", w:"comprare", en:"buy" }, m:{ id:"m", w:"la mela", alt:["mela"], en:"apple" },
               v:{ id:"v", w:"andare", en:"go" }, x:{ id:"x", w:"casa", en:"home" } };
  const ST = "Il gatto compra le mele e va a casa.";
  const ids = seg => seg.parts.filter(p => p.id).map(p => [p.text, p.id]);
  const rejoins = (seg, t) => seg.parts.map(p => p.text).join("") === t;
  const s1 = VC.passageSegments({ t:ST, words:["g","c","m","v","x"], spans:[[3,8,"g"],[9,15,"c"],[19,23,"m"],[26,28,"v"]] }, SB, RP);
  check("passageSegments spans: inflected compra/mele/va tappable in place; span 'gatto' beats the longer surface 'Il gatto'; casa (no span) by surface; no chips",
    rejoins(s1, ST) && util.isDeepStrictEqual(ids(s1), [["gatto","g"],["compra","c"],["mele","m"],["va","v"],["casa","x"]]) && util.isDeepStrictEqual(s1.unplaced, []));
  const s2 = VC.passageSegments({ t:ST, words:["g","c","m","v"], spans:[[9,15,"c"]] }, SB, RP);
  check("passageSegments mixed: span for compra; g by surface ('Il gatto'); m ('mele' matches no form) and v listed as unplaced",
    rejoins(s2, ST) && util.isDeepStrictEqual(ids(s2), [["Il gatto","g"],["compra","c"]]) && util.isDeepStrictEqual(s2.unplaced, ["m","v"]));
  const s3 = VC.passageSegments({ t:ST, words:["g","c"], spans:[[3,15,"c"]] }, SB, RP);
  check("passageSegments: a surface hit overlapping a span is dropped (g listed as unplaced), pieces never overlap",
    rejoins(s3, ST) && util.isDeepStrictEqual(ids(s3), [["gatto compra","c"]]) && util.isDeepStrictEqual(s3.unplaced, ["g"]));
  const s4 = VC.passageSegments({ t:ST, words:["c","m","x","q"], spans:[[9,15,"c"],[12,18,"m"],[31,99,"x"],[0,2,"zz"],[16,18,"q"],"bad",[5,5,"c"]] }, SB, RP);
  check("passageSegments ignores invalid spans (overlapping, out of bounds, id not in words, unknown id, malformed, empty) and falls back per id",
    rejoins(s4, ST) && util.isDeepStrictEqual(ids(s4), [["compra","c"],["casa","x"]]) && util.isDeepStrictEqual(s4.unplaced, ["m"]));
  const s6 = VC.passageSegments({ t:ST, words:["x"], spans:[[30,31,"x"]] }, SB, RP);
  check("passageSegments ignores a whitespace-only span (casa then found by surface)", rejoins(s6, ST) && util.isDeepStrictEqual(ids(s6), [["casa","x"]]));
  const s7 = VC.passageSegments({ t:"\u{1F642} va!", words:["v"], spans:[[1,5,"v"]] }, SB, RP);
  check("passageSegments ignores a span splitting a surrogate pair (andare then unplaced: va matches no form)", rejoins(s7, "\u{1F642} va!") && util.isDeepStrictEqual(ids(s7), []) && util.isDeepStrictEqual(s7.unplaced, ["v"]));
  const old = { t:ST, words:["g","c","m","v","x"] };
  check("passageSegments: no spans and spans:[] behave exactly as the surface-only path",
    util.isDeepStrictEqual(VC.passageSegments(old, SB, RP), VC.passageSegments({ ...old, spans:[] }, SB, RP)) &&
    util.isDeepStrictEqual(ids(VC.passageSegments(old, SB, RP)), [["Il gatto","g"],["casa","x"]]) && util.isDeepStrictEqual(VC.passageSegments(old, SB, RP).unplaced, ["c","m","v"]));
  const s5 = VC.passageSegments({ t:"\u{1F642} va!", words:["v"], spans:[[3,5,"v"]] }, SB, RP);
  check("passageSegments: span offsets are UTF-16 code units (an emoji before counts 2)", rejoins(s5, "\u{1F642} va!") && util.isDeepStrictEqual(ids(s5), [["va","v"]]));
  check("passageLength: spaced = whitespace tokens; unspaced = linked words", VC.passageLength(P1, RP) === 6 && VC.passageLength({ sentences:[{ words:["a","b"] },{ words:["c"] }] }, ZP) === 3);

  // validate_pack.py + jsonify on a temp pack with passages
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "vocab_passages_"));
  fs.writeFileSync(path.join(tmp, "pack.json"), JSON.stringify(RP));
  fs.writeFileSync(path.join(tmp, "words.json"), JSON.stringify(RW));
  fs.writeFileSync(path.join(tmp, "sentences.json"), "[]");
  const runP = passages => {
    const pf = path.join(tmp, "passages.json");
    if(passages === null){ if(fs.existsSync(pf)) fs.unlinkSync(pf); } else fs.writeFileSync(pf, JSON.stringify(passages));
    cp.spawnSync("python3", [path.join(ROOT, "tools", "jsonify_pack.py"), tmp]);
    return cp.spawnSync("python3", [path.join(ROOT, "tools", "validate_pack.py"), tmp], { encoding:"utf8" });
  };
  const none = runP(null);
  const sjsNone = fs.readFileSync(path.join(tmp, "sentences.js"), "utf8");
  check("pack without passages.json validates; sentences.js has no PASSAGES", none.status === 0 && !/PASSAGES/.test(sjsNone) && !/\d+ passages/.test(none.stdout));
  const good = runP(PS);
  const sjs = fs.readFileSync(path.join(tmp, "sentences.js"), "utf8");
  check("valid passages.json validates (3 passages) and is appended to sentences.js as PASSAGES", good.status === 0 && /3 passages/.test(good.stdout) &&
    util.isDeepStrictEqual(new Function(sjs + "\nreturn PASSAGES;")(), PS) && util.isDeepStrictEqual(new Function(sjs + "\nreturn SENTENCES;")(), []));
  const mut = f => { const c = JSON.parse(JSON.stringify(PS)); f(c); return c; };
  const bad = [
    ["duplicate passage id", c => { c[1].id = "p0001"; }, /duplicated/],
    ["unknown level", c => { c[0].lv = "C2"; }, /not in pack\.levels/],
    ["unknown sentence word id", c => { c[0].sentences[0].words.push("nope"); }, /unknown ids \['nope'\]/],
    ["unknown question word id", c => { c[0].questions[0].words = ["nope"]; }, /questions\[0\]\.words has unknown ids/],
    ["sentence index out of range", c => { c[0].questions[0].sentence = 2; }, /sentence must be an index/],
    ["mc with 3 options", c => { c[0].questions[0].options.pop(); }, /4 distinct/],
    ["mc with duplicate options", c => { c[0].questions[0].options[3] = "uno"; }, /4 distinct/],
    ["mc answer out of range", c => { c[0].questions[0].answer = 4; }, /index 0\.\.3/],
    ["mc answer bool", c => { c[0].questions[0].answer = true; }, /index 0\.\.3/],
    ["tf answer not bool", c => { c[0].questions[1].answer = 1; }, /true or false/],
    ["tf with options", c => { c[0].questions[1].options = ["a","b","c","d"]; }, /null or absent/],
    ["unknown question type", c => { c[0].questions[0].type = "open"; }, /"mc" or "tf"/],
    ["no questions", c => { c[0].questions = []; }, /questions must be a non-empty list/],
    ["no sentences", c => { c[0].sentences = []; }, /sentences must be a non-empty list/],
    ["spans not a list", c => { c[0].sentences[0].spans = {}; }, /spans must be a list/],
    ["span malformed", c => { c[0].sentences[0].spans = [[0,"4","a1"]]; }, /integer offsets/],
    ["span out of bounds", c => { c[0].sentences[0].spans = [[7,99,"a0"]]; }, /out of bounds/],
    ["spans overlapping", c => { c[0].sentences[0].spans = [[0,4,"a1"],[2,6,"a0"]]; }, /sorted and not overlap/],
    ["spans unsorted", c => { c[0].sentences[0].spans = [[7,11,"a0"],[0,4,"a1"]]; }, /sorted and not overlap/],
    ["span word not in the sentence's words", c => { c[0].sentences[0].spans = [[0,4,"b0"]]; }, /not in the sentence's words/],
    ["span over whitespace", c => { c[0].sentences[0].spans = [[4,5,"a1"]]; }, /only whitespace/],
    ["span splitting a surrogate pair", c => { c[0].sentences[0].t = "\u{1F642} vado."; c[0].sentences[0].spans = [[1,2,"a1"]]; }, /surrogate pair/],
  ];
  bad.forEach(([name, f, re]) => { const r = runP(mut(f)); check(`validate_pack rejects passages: ${name}`, r.status === 1 && re.test(r.stdout)); });
  const spanned = runP(mut(c => { c[0].sentences[0].spans = [[0,4,"a1"],[7,11,"a0"]]; c[0].sentences[1].spans = []; }));
  check("passages with valid spans (and an empty spans list) validate", spanned.status === 0 && !/spans/.test(spanned.stdout));
  const warnOnly = runP(mut(c => { c[0].sentences[0].t = "Non nel testo."; c[0].questions[0].words = []; }));
  check("sentence not in text / empty question words are warnings only", warnOnly.status === 0 && /does not appear in the passage text/.test(warnOnly.stdout) && /words is empty/.test(warnOnly.stdout));
  runP(PS);
  fs.unlinkSync(path.join(tmp, "passages.json"));
  const stale = cp.spawnSync("python3", [path.join(ROOT, "tools", "validate_pack.py"), tmp], { encoding:"utf8" });
  check("removing passages.json without regenerating -> stale sentences.js error", stale.status === 1 && /out of sync/.test(stale.stdout));
  fs.rmSync(tmp, { recursive:true, force:true });
})();

// ------------------------------------------------------------ [23] app.html boot: voice-probe TDZ, notice timing, ko word-break
// engine/app.html's inline script is booted for real (no jsdom — this file has no
// dependencies): a minimal DOM stub gives it just enough `document`/`window` to run
// its top-level code and the boot IIFE. The stub is an id-registry + regex scan of
// each innerHTML assignment (not a real parser/tree), which is enough to reach the
// Today tab and one rendered drill item without needing the rest of the DOM surface.
const appBootChecks = (async function(){
  console.log("\n[23] app.html boot: voice-probe TDZ guard, notice-on-first-shown, ko word-break");
  const appHtml = fs.readFileSync(path.join(ROOT, "engine", "app.html"), "utf8");
  const scriptBlocks = [...appHtml.matchAll(/<script>([\s\S]*?)<\/script>/g)];
  if(scriptBlocks.length < 2){ check("app.html has the inline app script (2 plain <script> tags)", false); return; }
  const appSrc = scriptBlocks[scriptBlocks.length - 1][1];

  // Attribute value is optional: a bare attribute (e.g. `data-tl`, no `="..."`) is
  // valid HTML (TA emits ` data-tl lang="..."`) and must still be picked up, or the
  // whole-tag scan below fails to close at `>` and the element never registers.
  function extractAttrs(tag){
    const attrs = {}; const re = /([a-zA-Z_:][-a-zA-Z0-9_:.]*)(?:\s*=\s*"([^"]*)")?/g;
    let m; while((m = re.exec(tag))){ if(m[1]) attrs[m[1]] = m[2] !== undefined ? m[2] : ""; }
    return attrs;
  }
  function makeFakeDom(){
    const registry = new Map();
    const tabButtons = [];
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
        return new Proxy({}, {
          get(_, k){ return attrs["data-" + toKebab(String(k))]; },
          set(_, k, v){ attrs["data-" + toKebab(String(k))] = String(v); return true; },
        });
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
      let m;
      while((m = re.exec(html))){
        const attrs = extractAttrs(m[2]);
        if(attrs.id) new El(m[1], attrs);
      }
    }
    // Seed the static ids/tab buttons from the real markup, so document.getElementById
    // and the two top-level document.querySelector(All) calls (tab wiring) resolve.
    const tabsMatch = appHtml.match(/<nav[^>]*id="tabs"[^>]*>([\s\S]*?)<\/nav>/);
    const btnRe = /<button([^>]*)>/g;
    let bm; while((bm = btnRe.exec(tabsMatch[1]))){ tabButtons.push(new El("button", extractAttrs(bm[1]))); }
    const bodySection = appHtml.slice(appHtml.indexOf("<body>"), appHtml.indexOf("<nav"));
    registerIdsFromHtml(bodySection);
    return {
      title: "", head: { appendChild(){} }, documentElement: new El("html", {}),
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
  const tick = () => new Promise(r=>setTimeout(r,0));
  // Runs app.html's inline script (synchronously) against the real zh pack with a fake
  // speechSynthesis whose getVoices() returns synchronously (the Firefox/Windows case
  // that crashed). Returns before the async boot IIFE's continuation (after its first
  // await) has run, so callers can inspect pre-boot state; call tick() twice (one for
  // store.load()'s await, one for the microtask it schedules) to let boot finish.
  // getRenderCalls/ss/setItemCalls/setQueueAndNext/hearItem/hearSentence/dnext/
  // getHasSpeech are test-only hooks added by appending to the script text below, not
  // present in app.html itself.
  function bootAppSync(getVoicesResult){
    const document = makeFakeDom();
    const ss = { getVoices: () => getVoicesResult, onvoiceschanged: null };
    const window = {
      VocabCore: VC,
      speechSynthesis: ss,
      SpeechSynthesisUtterance: function(){},
    };
    const navigator = { userAgent: "EngineChecks/1.0" };
    const setItemCalls = [];
    const localStorage = { getItem(){ return null; }, setItem(k,v){ setItemCalls.push([k,v]); } };
    const matchMedia = () => ({ matches:false });
    const requestAnimationFrame = fn => setTimeout(fn, 0);
    const fnBody = appSrc + `
let __renderCalls = 0;
const __wrappedRender = render;
render = function(){ __renderCalls++; return __wrappedRender.apply(this, arguments); };
return {
  getHasSpeech:()=>hasSpeech, getRenderCalls:()=>__renderCalls, hearItem, hearSentence, readItem, typeItem, dnext,
  setHasSpeech: v => { hasSpeech = v; },
  setQueueAndNext:(items, onDone) => { D = { q: items.slice(), right:0, seen:0, miss:[], onDone: onDone||(()=>{}), summary:null }; dnext(); },
};`;
    const fn = new Function("document","window","navigator","localStorage","matchMedia","requestAnimationFrame","PACK","WORDS","SENTENCES","LESSONS", fnBody);
    const api = fn(document, window, navigator, localStorage, matchMedia, requestAnimationFrame, PACK, WORDS, SENTENCES, LESSONS);
    return { api, document, ss, setItemCalls };
  }
  async function bootApp(getVoicesResult){
    const boot = bootAppSync(getVoicesResult);
    await tick();
    await tick();
    return boot;
  }

  // (a) non-empty voice list, no voice for the pack's language (zh-CN): the Firefox/
  // Windows repro that crashed with "Cannot access 'D' before initialization".
  try{
    const { api, document } = await bootApp([{ lang:"en-US", name:"x" }]);
    check("voice probe: non-empty voice list, no match -> no throw, page renders Today", document.getElementById("htitle").textContent === "Today");
    check("voice probe: non-empty voice list, no match -> hasSpeech false", api.getHasSpeech() === false);
  }catch(e){ check(`voice probe (non-empty, no match) does not throw (got: ${e.message})`, false); }

  // (b) a matching voice present.
  try{
    const { api, document } = await bootApp([{ lang:"zh-CN", name:"x" }]);
    check("voice probe: matching voice -> no throw, page renders Today", document.getElementById("htitle").textContent === "Today");
    check("voice probe: matching voice -> hasSpeech true", api.getHasSpeech() === true);
  }catch(e){ check(`voice probe (matching voice) does not throw (got: ${e.message})`, false); }

  // (c) empty voice list (not yet loaded / never populated): speechUsable is optimistic.
  try{
    const { api, document } = await bootApp([]);
    check("voice probe: empty voice list -> no throw, page renders Today", document.getElementById("htitle").textContent === "Today");
    check("voice probe: empty voice list -> hasSpeech true", api.getHasSpeech() === true);
  }catch(e){ check(`voice probe (empty voice list) does not throw (got: ${e.message})`, false); }

  // Boot gating: a voice-probe re-render must not run before boot has rendered once
  // (prog isn't loaded yet — a pre-boot render could refreshReadUnlocks() -> store.save()
  // the not-yet-loaded default prog, clobbering real saved progress before store.load()
  // ever reads it back), and a voice change after boot must still re-render.
  try{
    const boot = bootAppSync([{ lang:"en-US", name:"x" }]); // probe fires sync, pre-boot
    check("pre-boot voice probe does not render", boot.api.getRenderCalls() === 0);
    check("pre-boot voice probe does not save progress", boot.setItemCalls.length === 0);
    await tick(); await tick(); // let the boot IIFE's own render() run
    check("boot renders exactly once", boot.api.getRenderCalls() === 1);
    check("after boot, page has rendered Today", boot.document.getElementById("htitle").textContent === "Today");
    boot.ss.getVoices = () => [{ lang:"zh-CN", name:"y" }]; // now matches -> hasSpeech flips false->true
    boot.ss.onvoiceschanged();
    check("a voice change after boot flips hasSpeech", boot.api.getHasSpeech() === true);
    check("a voice change after boot re-renders", boot.api.getRenderCalls() === 2);
  }catch(e){ check(`boot-gating scenario does not throw (got: ${e.message})`, false); }

  // Notice timing: the item built first must not be the one that gets the one-time
  // no-voice notice if a later-built item is the one actually shown first (shuffle),
  // an item that never needs it (type / plain read) never shows it, and the notice is
  // skipped even for a flagged item if hasSpeech has since flipped true.
  try{
    const { api, document } = await bootApp([{ lang:"en-US", name:"x" }]); // hasSpeech=false
    const builtFirst = api.hearItem(WORDS[5]);
    const builtSecond = api.hearItem(WORDS[6]);
    check("hear items without speech are flagged needsNotice at build time (not shown yet)",
      builtFirst.needsNotice === true && builtSecond.needsNotice === true);
    const typeItem = api.typeItem(WORDS[7]); // never a hear item; needsNotice must be unset
    check("a plain type item is never flagged needsNotice", !typeItem.needsNotice);
    api.setQueueAndNext([typeItem, builtSecond, builtFirst], () => {});
    const typeHtml = document.getElementById("panel").innerHTML;
    check("no notice on a type item shown first", !typeHtml.includes("no text-to-speech voice"));
    api.dnext(); // advance past the type item straight to the queue's next entry (bypassing its input UI)
    const shownFirstHtml = document.getElementById("panel").innerHTML;
    check("notice appears on the first hear item actually shown (built second, after the type item)", shownFirstHtml.includes("no text-to-speech voice"));
    document.getElementById("o").children[0].click();
    document.getElementById("nx").click();
    const shownSecondHtml = document.getElementById("panel").innerHTML;
    check("notice does not repeat on the item shown second (built first)", !shownSecondHtml.includes("no text-to-speech voice"));
  }catch(e){ check(`notice-timing scenario does not throw (got: ${e.message})`, false); }

  try{
    const { api, document } = await bootApp([{ lang:"en-US", name:"x" }]); // hasSpeech=false
    const flagged = api.hearItem(WORDS[8]);
    api.setHasSpeech(true); // voice arrives between build and display
    api.setQueueAndNext([flagged], () => {});
    const html = document.getElementById("panel").innerHTML;
    check("a needsNotice item shows no notice if hasSpeech flips true before it's shown", !html.includes("no text-to-speech voice"));
  }catch(e){ check(`hasSpeech-flips-before-show scenario does not throw (got: ${e.message})`, false); }

  try{
    const { api, document } = await bootApp([{ lang:"en-US", name:"x" }]); // hasSpeech=false
    const plainRead = api.readItem(WORDS[9]);
    api.setQueueAndNext([plainRead], () => {});
    const html = document.getElementById("panel").innerHTML;
    check("a plain read item (not hearItem's no-speech fallback) never shows the notice", !html.includes("no text-to-speech voice"));
  }catch(e){ check(`plain read item scenario does not throw (got: ${e.message})`, false); }

  // ko word-break:keep-all: scoped to the lang attribute TA sets from pack.langTag, not
  // a blanket [data-tl] rule (which would also wrap ja/zh, which have no spaces, mid-word).
  // [lang|="ko"] semantics: matches exactly "ko" or "ko-*", not other ko-prefixed codes
  // (kok, kos) that ^= would wrongly match.
  const matchesLangDash = lang => lang === "ko" || lang.startsWith("ko-");
  const koLang = VC.scriptDisplay({ langTag: "ko-KR" }).lang;
  const jaLang = VC.scriptDisplay({ langTag: "ja" }).lang;
  const zhLang = VC.scriptDisplay({ tts: "zh-CN" }).lang;
  const kokLang = VC.scriptDisplay({ langTag: "kok" }).lang; // Konkani: ^= would false-match, |= must not
  check('langTag ko-KR resolves to a lang [lang|="ko"] matches', matchesLangDash(koLang));
  check('ja, zh and kok (Konkani) do not match [lang|="ko"]', !matchesLangDash(jaLang) && !matchesLangDash(zhLang) && !matchesLangDash(kokLang));
  check('app.html: word-break:keep-all is scoped to [data-tl][lang|="ko"], not a blanket [data-tl] rule',
    /\[data-tl\]\[lang\|="ko"\]\s*\{[^}]*word-break\s*:\s*keep-all/.test(appHtml) &&
    !/\[data-tl\]\s*\{[^}]*word-break/.test(appHtml));
})();

appBootChecks.catch(e => { console.error("app boot checks crashed:", e); fails++; }).then(() => {
  console.log(`\n${fails ? "FAILED" : "ALL PASSED"}: ${passes} passed, ${fails} failed`);
  process.exit(fails ? 1 : 0);
});
