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
  check("testGates: a pack with 0 sentences is not blocked on sentences", VC.testGates(20, 0, 0).needPlacement === false && VC.testGates(20, 0, 50).needPlacement === true && VC.testGates(5, 50, 50).needPlacement === true);

  // speech
  const voices = [{lang:"en-US"}, {lang:"zh_TW"}, {lang:"it-IT"}];
  check("pickVoice: exact locale, else same language, else null", VC.pickVoice(voices, "it-IT").lang === "it-IT" && VC.pickVoice(voices, "zh-CN").lang === "zh_TW" && VC.pickVoice(voices, "es-ES") === null);
  check("speechUsable: no API -> false; unknown voice list -> true; list without the language -> false",
    !VC.speechUsable(false, voices, "it-IT") && VC.speechUsable(true, [], "es-ES") && !VC.speechUsable(true, voices, "es-ES") && VC.speechUsable(true, voices, "it-IT"));
  check("escapeHtml escapes single quotes", VC.escapeHtml(`a'b"<`) === "a&#39;b&quot;&lt;");
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

console.log(`\n${fails ? "FAILED" : "ALL PASSED"}: ${passes} passed, ${fails} failed`);
process.exit(fails ? 1 : 0);
