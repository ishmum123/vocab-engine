// Checks for branch engine-passage-audio (docs/PACK_SCHEMA.md "Flow" for passages):
// readQuestionScreen speaks the question (TTS only, no per-question clip in the schema)
// and shows the same Replay pattern every other spoken site uses (REPLAY_STAGE #rpa on
// mount, REVEAL_REPLAY #rvp on reveal); the reveal plays the source sentence (its clip
// else TTS, same resolution as saySentence/wirePassage's data-say handler) and cancels
// the question's own utterance first; readResults shows a Replay per source sentence
// with no autoplay. Fake-DOM boot copied from tests/pron_aids_checks.js (id registry +
// regex scan of innerHTML), against the zh pack as shipped.
// Run: node tests/passage_audio_checks.js
"use strict";
const fs = require("fs");
const path = require("path");

const ROOT = path.join(__dirname, "..");
const VC = require(path.join(ROOT, "engine", "core.js"));
const ZH = path.join(ROOT, "packs", "zh");
function loadConst(file, name){ return new Function(fs.readFileSync(file, "utf8") + `\nreturn ${name};`)(); }
const PACK = loadConst(path.join(ZH, "pack.js"), "PACK");
const WORDS = loadConst(path.join(ZH, "words.js"), "WORDS");
const SENTENCES = loadConst(path.join(ZH, "sentences.js"), "SENTENCES");
const PASSAGES = loadConst(path.join(ZH, "sentences.js"), "PASSAGES");
const LESSONS = loadConst(path.join(ZH, "lessons.js"), "LESSONS");
const CHARACTERS = loadConst(path.join(ZH, "characters.js"), "CHARACTERS");
console.log(`Loaded zh pack: ${WORDS.length} words, ${SENTENCES.length} sentences, ${PASSAGES.length} passages`);

let fails = 0, passes = 0;
function check(name, cond){
  if(cond){ passes++; console.log(`PASS  ${name}`); }
  else { fails++; console.log(`FAIL  ${name}`); }
}

// ------------------------------------------------------------------ fake DOM (copied from pron_aids_checks.js)
const appHtml = fs.readFileSync(path.join(ROOT, "engine", "app.html"), "utf8");
const scriptOf = html => { const b = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)]; return b[b.length - 1][1]; };
function extractAttrs(tag){
  const attrs = {}; const re = /([a-zA-Z_:][-a-zA-Z0-9_:.]*)(?:\s*=\s*"([^"]*)")?/g;
  let m; while((m = re.exec(tag))){ if(m[1]) attrs[m[1]] = m[2] !== undefined ? m[2] : ""; }
  return attrs;
}
function makeFakeDom(){
  const registry = new Map(); const tabButtons = [];
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
      return new Proxy({}, { get(_, k){ return attrs["data-" + toKebab(String(k))]; }, set(_, k, v){ attrs["data-" + toKebab(String(k))] = String(v); return true; } });
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
    let m; while((m = re.exec(html))){ const attrs = extractAttrs(m[2]); if(attrs.id) new El(m[1], attrs); }
  }
  const tabsMatch = appHtml.match(/<nav[^>]*id="tabs"[^>]*>([\s\S]*?)<\/nav>/);
  const btnRe = /<button([^>]*)>/g;
  let bm; while((bm = btnRe.exec(tabsMatch[1]))){ tabButtons.push(new El("button", extractAttrs(bm[1]))); }
  registerIdsFromHtml(appHtml.slice(appHtml.indexOf("<body>"), appHtml.indexOf("<nav")));
  return {
    title: "", head: { appended: [], appendChild(c){ this.appended.push(c); return c; } }, body: new El("body", {}), documentElement: new El("html", {}),
    write(){}, createElement(tag){ return new El(tag, {}); },
    getElementById(id){ return registry.get(id) || null; },
    querySelector(sel){ return this.querySelectorAll(sel)[0] || null; },
    querySelectorAll(sel){
      const m = sel.match(/^#tabs\s+button(?:\[data-t="([^"]+)"\])?$/);
      if(m) return m[1] ? tabButtons.filter(b=>b.dataset.t===m[1]) : tabButtons.slice();
      return [];
    },
    _listeners: {},
    addEventListener(t,f){ (this._listeners[t]=this._listeners[t]||[]).push(f); },
  };
}
const tick = () => new Promise(r => setTimeout(r, 0));

// Boots an app. opts: voices (speechSynthesis.getVoices(), default a matching zh-CN voice
// so hasSpeech is true; [] or a mismatched lang makes hasSpeech false). spoken: every
// text passed to speechSynthesis.speak (u.text). cancelCount: how many times the mock's
// ss.cancel() ran (ttsDriver only calls it while ss.speaking/pending is true, so this only
// increments when a new speak() interrupts one already "in flight" -- see ss.speak below,
// which sets speaking=true and leaves it true until cancel() or the test fires u.onend).
async function boot(opts){
  const o = opts || {};
  const document = makeFakeDom();
  const spoken = [];
  let cancelCount = 0;
  const ss = {
    speaking: false, pending: false,
    getVoices: () => o.voices !== undefined ? o.voices : [{ lang: "zh-CN", name: "x" }],
    onvoiceschanged: null,
    cancel(){ cancelCount++; ss.speaking = false; ss.pending = false; },
    speak(u){ spoken.push(u.text); ss.speaking = true; },
  };
  const window = { VocabCore: VC, speechSynthesis: ss, SpeechSynthesisUtterance: function(t){ this.text = t; }, addEventListener(){} };
  const localStorage = { getItem(){ return null; }, setItem(){} };
  const fnBody = scriptOf(appHtml) + `
return {
  html: id => { const e = document.getElementById(id); return e ? e.innerHTML : null; },
  el: id => document.getElementById(id),
  setProg: p => { prog = p; },
  startPassage: p => { tab = "read"; startPassage(p); },
  rd: () => RD,
};`;
  const names = ["SpeechSynthesisUtterance","document","window","navigator","location","localStorage","matchMedia","requestAnimationFrame","Audio","confirm","alert","PACK","WORDS","SENTENCES","LESSONS","PASSAGES","CHARACTERS"];
  const args = [window.SpeechSynthesisUtterance, document, window, { userAgent:"PassageAudioChecks/1.0" }, undefined, localStorage, () => ({ matches:false }), fn => setTimeout(fn, 0),
    function(){ return { play(){ return Promise.resolve(); }, pause(){} }; }, () => true, () => {}, o.pack || PACK, o.words || WORDS, o.sentences || SENTENCES, LESSONS, o.passages || PASSAGES, o.units || CHARACTERS];
  const api = new Function(...names, fnBody)(...args);
  await tick(); await tick();
  return { api, document, spoken, cancelCount: () => cancelCount, ss };
}

const seedPF = () => VC.normalizeProg({ sets: {}, placedOnce: true, sessions: 5 }, PACK);
const RPA = /<button class="replay" id="rpa" aria-label="Replay">/;
const RVP = /<button type="button" class="replay" id="rvp" aria-label="Replay">/;
// Every speak() after one whose mock utterance is still "speaking" (nothing here ever
// fires onend) goes through ttsDriver's stop-then-defer path (docs/AUDIO.md "Playback
// reliability"): the next utterance is created deferMs later, on a real timer. sleep()
// waits it out, as tests/audio_checks.js's TTS section does.
const sleep = ms => new Promise(r => setTimeout(r, ms));
const DEFER = VC.TTS_TIMING.deferMs + 30;

(async function main(){
  // ---------------------------------------------------------------- (a) question speaks once at mount
  console.log("\n[1] readQuestionScreen: mounting speaks q.q exactly once, Replay button (#rpa) present");
  try{
    const { api, spoken } = await boot();
    api.setProg(seedPF());
    const p = PASSAGES[0];
    api.startPassage(p);
    api.el("rdone").click();
    const q0 = p.questions[0];
    check("question screen mount speaks q.q exactly once", spoken.length === 1 && spoken[0] === q0.q);
    check("Replay button (#rpa) present on the question (a voice is usable)", RPA.test(api.html("panel")));
    const k = spoken.length;
    api.el("rpa").click();
    await sleep(DEFER);
    check("Replay (#rpa) speaks the question again", spoken.slice(k).join() === q0.q);
  }catch(e){ check(`section threw: ${e.stack}`, false); }

  // ---------------------------------------------------------------- (b) reveal plays the source sentence, cancels the question
  console.log("\n[2] reveal: plays the source sentence once (s.audio else TTS), cancels the question utterance first");
  try{
    const { api, spoken, cancelCount } = await boot();
    api.setProg(seedPF());
    const p = PASSAGES.find(x => x.questions.some(q => x.sentences[q.sentence])) || PASSAGES[0];
    api.startPassage(p);
    api.el("rdone").click();
    const q0 = p.questions[0];
    const s0 = p.sentences[q0.sentence];
    check("setup: source sentence has no clip in this pack (TTS path)", !s0.audio);
    const beforeCancel = cancelCount();
    const k = spoken.length;
    const opts = api.el("o").children;
    const right = opts.find(b => b.dataset.v === String(q0.answer));
    right.click();
    await sleep(DEFER);
    check("reveal shows Replay (#rvp)", RVP.test(api.html("rv")));
    check("reveal plays the source sentence text once", spoken.slice(k).join() === s0.t);
    check("the question's own (still 'speaking') utterance was cancelled before the sentence played", cancelCount() === beforeCancel + 1);
    const k2 = spoken.length;
    api.el("rvp").click();
    await sleep(DEFER);
    check("Replay (#rvp) speaks the source sentence again", spoken.slice(k2).join() === s0.t);
  }catch(e){ check(`section threw: ${e.stack}`, false); }

  // ---------------------------------------------------------------- (c) replay button present iff a voice or clip exists
  console.log("\n[3] no voice: no Replay button anywhere, nothing spoken");
  try{
    const { api, spoken } = await boot({ voices: [{ lang: "en-US", name: "en" }] }); // wrong lang for zh pack.tts
    api.setProg(seedPF());
    const p = PASSAGES[0];
    api.startPassage(p);
    api.el("rdone").click();
    check("question screen: no Replay (#rpa), nothing spoken at mount (no voice for this language)", !RPA.test(api.html("panel")) && spoken.length === 0);
    const q0 = p.questions[0];
    const opts = api.el("o").children;
    const right = opts.find(b => b.dataset.v === String(q0.answer));
    right.click();
    check("reveal: no Replay (#rvp), nothing spoken (source sentence has no clip either)", !RVP.test(api.html("rv")) && spoken.length === 0);
  }catch(e){ check(`section threw: ${e.stack}`, false); }

  console.log("\n[4] readResults: a Replay button per source sentence, no autoplay");
  try{
    const { api, spoken } = await boot();
    api.setProg(seedPF());
    const p = PASSAGES[0];
    api.startPassage(p);
    api.el("rdone").click();
    for(let qi = 0; qi < p.questions.length; qi++){
      const q = p.questions[qi];
      const opts = api.el("o").children;
      const btn = opts.find(b => b.dataset.v === String(q.answer)) || opts[0];
      btn.click(); await sleep(DEFER);
      api.el("nx").click(); await sleep(DEFER);
    }
    const k = spoken.length;
    const html = api.html("panel");
    check("results screen: nothing autoplays", spoken.length === k);
    let allPresent = true;
    p.questions.forEach((q, i) => { if(!new RegExp(`id="rr${i}"`).test(html)) allPresent = false; });
    check(`results screen: a Replay button per question's source sentence (${p.questions.length} questions)`, allPresent);
    const s0 = p.sentences[p.questions[0].sentence];
    const k2 = spoken.length;
    api.el("rr0").click();
    await sleep(DEFER);
    check("results Replay speaks that question's source sentence", spoken.slice(k2).join() === s0.t);
  }catch(e){ check(`section threw: ${e.stack}`, false); }

  // ---------------------------------------------------------------- (d) generation guard: a late onstart from a replaced question is ignored
  console.log("\n[5] Next -> a previous question's late TTS onstart never marks the new question's button");
  try{
    const { api, ss } = await boot();
    // Capture every utterance handed to speechSynthesis.speak() (speak() -> speakTTS() ->
    // ss.speak(u)); the mock never fires onstart itself (a real engine fires it async), so
    // question 1's utterance is still pending once question 2 has mounted.
    const captured = [];
    const realSpeak = ss.speak.bind(ss);
    ss.speak = u => { captured.push(u); realSpeak(u); };
    api.setProg(seedPF());
    const p = PASSAGES.find(x => x.questions.length > 1) || PASSAGES[0];
    check("setup: a passage with more than one question", p.questions.length > 1);
    api.startPassage(p);
    api.el("rdone").click(); // question 1 mounts: captured[0]
    const q0 = p.questions[0];
    const oldBtn = api.el("rpa"); // question 1's button, before any answer/Next
    const opts0 = api.el("o").children;
    const right0 = opts0.find(b => b.dataset.v === String(q0.answer));
    right0.click(); await sleep(DEFER); // reveal's sentence: captured[1]
    api.el("nx").click(); await sleep(DEFER); // -> question 2 mounts, re-rendering #rpa as a new element: captured[2]
    const newBtn = api.el("rpa");
    check("Next re-renders a fresh #rpa element (not the same object)", newBtn && oldBtn && newBtn !== oldBtn);
    // Fire question 1's utterance's onstart late, now that question 2 is showing.
    const stale = captured[0];
    check("setup: question 1's utterance was captured before it could fire onstart", !!stale && typeof stale.onstart === "function" && !newBtn.classList.contains("speaking"));
    stale.onstart();
    check("a late onstart from question 1's utterance does not mark question 2's button 'speaking'", !newBtn.classList.contains("speaking"));
  }catch(e){ check(`section threw: ${e.stack}`, false); }

  console.log(`\n${fails === 0 ? "ALL PASSED" : "FAILED"}: ${passes} passed, ${fails} failed`);
  process.exit(fails === 0 ? 0 : 1);
})().catch(e => { console.error(e); process.exit(1); });
