// Checks for branch engine-listen-mode (docs/PACK_SCHEMA.md "passages.json", Listening
// pass): VC.readPassMode / VC.listenAudioOnly / markPassageDone's l:1 in core.js, and in
// app.html the Today plan row, the listening passage screen (hidden text, play rows, Play
// all, Show text), audio-only questions behind "Show question", the results lines, and a
// no-voice/no-clip control whose markup is byte-identical to the base branch
// (engine-passage-audio, pinned sha BASE). Fake-DOM boot copied from tests/passage_audio_checks.js.
// Run: node tests/listen_mode_checks.js
"use strict";
const fs = require("fs");
const path = require("path");
const cp = require("child_process");

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
// [6] control baseline, pinned like pron_aids_checks.js MAIN: engine-passage-audio at
// ea5dcbc (its fix round, merged into this branch), the engine before listen mode.
const BASE = "ea5dcbc";

let fails = 0, passes = 0;
function check(name, cond, detail){
  if(cond){ passes++; console.log(`PASS  ${name}`); }
  else { fails++; console.log(`FAIL  ${name}${detail ? "  -- " + detail : ""}`); }
}

// ------------------------------------------------------------------ fake DOM (copied from pron_aids_checks.js)
let appHtml = fs.readFileSync(path.join(ROOT, "engine", "app.html"), "utf8");
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
const sleep = ms => new Promise(r => setTimeout(r, ms));
const DEFER = VC.TTS_TIMING.deferMs + 30;
function mulberry32(a){ return () => { a = (a + 0x6D2B79F5) >>> 0; let t = a; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; }

// opts: voices (default a zh-CN voice), passages, html (app.html source, default the
// working tree's). utts: every utterance
// handed to speechSynthesis.speak; audio: the one shared Audio element (clips), plays: srcs.
async function boot(opts){
  const o = opts || {};
  const src = o.html || appHtml;
  const document = makeFakeDom();
  const spoken = [], utts = [], plays = [];
  let audio = null;
  const ss = {
    speaking: false, pending: false,
    getVoices: () => o.voices !== undefined ? o.voices : [{ lang: "zh-CN", name: "x" }],
    onvoiceschanged: null,
    cancels: 0,
    cancel(){ ss.cancels++; ss.speaking = false; ss.pending = false; },
    speak(u){ spoken.push(u.text); utts.push(u); ss.speaking = true; },
  };
  if(o.ssHook) o.ssHook(ss, spoken, utts);
  const window = { VocabCore: VC, speechSynthesis: ss, SpeechSynthesisUtterance: function(t){ this.text = t; }, addEventListener(){} };
  const localStorage = { getItem(){ return null; }, setItem(){} };
  const fnBody = scriptOf(src) + `
return {
  html: id => { const e = document.getElementById(id); return e ? e.innerHTML : null; },
  el: id => document.getElementById(id),
  setProg: p => { prog = p; }, getProg: () => prog,
  startPassage: (p, today, mode) => { tab = today ? "today" : "read"; startPassage(p, today, mode); },
  today: () => { tab = "today"; render(); },
  enterTodayStep: (step, read) => { tab = "today"; todayStepState = read === undefined ? { step } : { step, read }; todayStep(); },
  rd: () => RD,
  rerender: () => render(),
};`;
  const names = ["SpeechSynthesisUtterance","document","window","navigator","location","localStorage","matchMedia","requestAnimationFrame","Audio","confirm","alert","PACK","WORDS","SENTENCES","LESSONS","PASSAGES","CHARACTERS"];
  const args = [window.SpeechSynthesisUtterance, document, window, { userAgent:"ListenModeChecks/1.0" }, undefined, localStorage, () => ({ matches:false }), fn => setTimeout(fn, 0),
    function(){ audio = { onended: null, onerror: null, play(){ plays.push(this.src); return Promise.resolve(); }, pause(){} }; return audio; }, () => true, () => {}, PACK, WORDS, SENTENCES, LESSONS, o.passages || PASSAGES, CHARACTERS];
  const api = new Function(...names, fnBody)(...args);
  await tick(); await tick();
  return { api, document, spoken, utts, plays, ss, audio: () => audio };
}

const iso = d => `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,"0")}-${String(d.getDate()).padStart(2,"0")}`;
const daysAgo = n => { const t = new Date(); return iso(new Date(t.getFullYear(), t.getMonth(), t.getDate() - n)); };
// Every passage done 8 days ago with full marks except passage `missed` (a spaced re-read).
function rereadProg(passages, missed, extra){
  const pr = VC.normalizeProg({ sets: {}, placedOnce: true, sessions: 5 }, PACK);
  pr.read = { unlocked: Object.fromEntries(PACK.levels.map(l => [l.id, 1])),
    done: Object.fromEntries(passages.map(p => [p.id, { sc: p.questions.length, n: p.questions.length, d: daysAgo(8), x: 1 }])) };
  pr.read.done[missed.id].sc = 0;
  Object.assign(pr.read.done[missed.id], extra || {});
  return pr;
}
const planRow = (h, label) => (h.match(new RegExp(`<tr><td>6\\. ${label}</td><td>([\\s\\S]*?)</td></tr>`)) || [])[1];
const answerAll = (api, p, wrong) => {
  for(let qi = api.rd().qi; qi < p.questions.length; qi++){
    const q = p.questions[qi], os = api.el("o").children;
    (wrong ? os.find(b => b.dataset.v !== String(q.answer)) : os.find(b => b.dataset.v === String(q.answer))).click();
    api.el("nx").click();
  }
};
const fire = (ss, u) => { ss.speaking = false; u.onend({}); };

(async function main(){
  const P = PASSAGES[5];
  // ---------------------------------------------------------------- [1] core
  console.log("\n[1] core: readPassMode, listenAudioOnly, markPassageDone l:1, progress shape");
  {
    const pr = rereadProg(PASSAGES, P);
    const rr = { p: P, reason: "reread" }, nw = { p: P, reason: "new" };
    check("first pass (reason new) is a reading pass even when listening is possible", VC.readPassMode(nw, pr, true) === "read");
    check("spaced re-read + canListen -> listen", VC.readPassMode(rr, pr, true) === "listen");
    check("spaced re-read without canListen -> read", VC.readPassMode(rr, pr, false) === "read");
    check("null item -> read", VC.readPassMode(null, pr, true) === "read");
    pr.read.done[P.id].l = 1;
    check("alternation: latest attempt was a listening pass (l:1) -> read", VC.readPassMode(rr, pr, true) === "read");
    delete pr.read.done[P.id].l;
    check("nextReadItem still reports reason reread for it", (VC.nextReadItem(PASSAGES, WORDS, PACK, pr, daysAgo(0)) || {}).reason === "reread");
    const a = VC.listenAudioOnly("p0006", 1, 5);
    check("listenAudioOnly: ceil(n/2) distinct ascending indexes in range", a.length === 3 && new Set(a).size === 3 && a.every((x, i) => x >= 0 && x < 5 && (i === 0 || a[i-1] < x)));
    check("listenAudioOnly: deterministic for the same id + attempt count", JSON.stringify(a) === JSON.stringify(VC.listenAudioOnly("p0006", 1, 5)));
    const sets = [0,1,2,3,4,5,6,7,8,9].map(x => JSON.stringify(VC.listenAudioOnly("p0006", x, 5)));
    check(`listenAudioOnly n=5, attempts 0..9: no two consecutive sets equal`, sets.every((x, i) => i === 0 || x !== sets[i-1]), sets.join(" "));
    const allIds = PASSAGES.every(p => { const n = p.questions.length; return [0,1,2,3,4,5].every(x => JSON.stringify(VC.listenAudioOnly(p.id, x, n)) !== JSON.stringify(VC.listenAudioOnly(p.id, x + 1, n))); });
    check("listenAudioOnly: for every zh passage, attempts x and x+1 (x=0..5) never pick the same set", allIds);
    check("listenAudioOnly n=2: alternates between the two questions", JSON.stringify([0,1,2].map(x => VC.listenAudioOnly("q", x, 2))) === JSON.stringify([VC.listenAudioOnly("q", 0, 2), VC.listenAudioOnly("q", 1, 2), VC.listenAudioOnly("q", 0, 2)]) && VC.listenAudioOnly("q", 0, 2)[0] !== VC.listenAudioOnly("q", 1, 2)[0]);
    check("listenAudioOnly: n=4 -> 2, n=1 -> 1, n=0 -> []", VC.listenAudioOnly("x", 0, 4).length === 2 && VC.listenAudioOnly("x", 0, 1).length === 1 && VC.listenAudioOnly("x", 0, 0).length === 0);
    const q = VC.normalizeProg({}, PACK);
    const r1 = VC.markPassageDone(q, "p1", 2, 5, "2026-09-27", true);
    check("markPassageDone listen -> {sc,n,d,x,l:1}", JSON.stringify(r1) === JSON.stringify({ sc:2, n:5, d:"2026-09-27", x:1, l:1 }));
    const r2 = VC.markPassageDone(q, "p1", 3, 5, "2026-10-05");
    check("markPassageDone read after a listen -> no l (record replaced), x counts on", JSON.stringify(r2) === JSON.stringify({ sc:3, n:5, d:"2026-10-05", x:2 }));
    check("validateProgShape accepts done.l:1 and a record without l", VC.validateProgShape({ read: { done: { a: { sc:1, n:2, d:"2026-01-01", x:1, l:1 }, b: { sc:1, n:2, d:"2026-01-01", x:1 } } } }, []).ok);
    check("validateProgShape rejects a non-number l", !VC.validateProgShape({ read: { done: { a: { sc:1, n:2, l:"yes" } } } }, []).ok);
  }

  // ---------------------------------------------------------------- [2] Today plan + mode
  console.log("\n[2] Today: Listen row for a listenable re-read, Read row otherwise");
  try{
    const b = await boot();
    b.api.setProg(rereadProg(PASSAGES, P)); b.api.today();
    const lrow = planRow(b.api.html("panel"), "Listen");
    check(`voice usable: plan row "6. Listen" names the passage (${lrow && lrow.replace(/<[^>]+>/g, "")})`, !!lrow && lrow.startsWith("1 passage to listen to: ") && lrow.includes(VC.escapeHtml(P.title)) && !planRow(b.api.html("panel"), "Read"));
    b.api.enterTodayStep(5);
    check("step 5 runs it as a listening pass (RD.mode listen, Skip today present)", b.api.rd() && b.api.rd().mode === "listen" && b.api.rd().p === P && /id="rskip"/.test(b.api.html("panel")));
    const nv = await boot({ voices: [{ lang: "en-US", name: "en" }] });
    nv.api.setProg(rereadProg(PASSAGES, P)); nv.api.today();
    const rrow = planRow(nv.api.html("panel"), "Read");
    check("no voice, no clips: plain Read row (1 passage to re-read)", !!rrow && rrow.startsWith("1 passage to re-read: ") && !planRow(nv.api.html("panel"), "Listen"));
    nv.api.enterTodayStep(5);
    check("no voice, no clips: step 5 is a reading pass (no RD.mode)", nv.api.rd() && nv.api.rd().mode === undefined && /id="rdone">Done reading/.test(nv.api.html("panel")));
    const b2 = await boot();
    b2.api.setProg(rereadProg(PASSAGES, P, { l: 1 })); b2.api.today();
    check("voice usable but the last attempt was a listening pass: Read row", !!planRow(b2.api.html("panel"), "Read") && !planRow(b2.api.html("panel"), "Listen"));
    // The voice goes between the plan and step 5: re-checked, runs as a reading pass.
    const b3 = await boot({ voices: [{ lang: "en-US", name: "en" }] });
    b3.api.setProg(rereadProg(PASSAGES, P));
    b3.api.enterTodayStep(5, { p: P, reason: "reread", mode: "listen" });
    check("planned listen but no voice at step 5 (no clips): reading pass", b3.api.rd() && b3.api.rd().mode === undefined);
    // Clips on every sentence, no voice: listenable.
    const CP = JSON.parse(JSON.stringify(P)); CP.sentences.forEach((s, i) => { s.audio = `audio/p/${i}.mp3`; });
    const ps = PASSAGES.map(p => p.id === P.id ? CP : p);
    const c = await boot({ voices: [{ lang: "en-US", name: "en" }], passages: ps });
    c.api.setProg(rereadProg(ps, CP)); c.api.today();
    check("no voice but every sentence has a clip: Listen row", !!planRow(c.api.html("panel"), "Listen"));
    const HP = JSON.parse(JSON.stringify(CP)); delete HP.sentences[1].audio;
    const ps2 = PASSAGES.map(p => p.id === P.id ? HP : p);
    const c2 = await boot({ voices: [{ lang: "en-US", name: "en" }], passages: ps2 });
    c2.api.setProg(rereadProg(ps2, HP)); c2.api.today();
    check("no voice, one sentence without a clip: Read row", !!planRow(c2.api.html("panel"), "Read") && !planRow(c2.api.html("panel"), "Listen"));
  }catch(e){ check(`section threw: ${e.stack}`, false); }

  // ---------------------------------------------------------------- [3] listen screen
  console.log("\n[3] listening passage screen: text hidden, n play rows, Show text logged");
  try{
    const b = await boot();
    b.api.setProg(rereadProg(PASSAGES, P));
    b.api.startPassage(P, true, "listen");
    // The fake DOM keeps markup on #panel only (ids are registered, children empty).
    const pbox = b.api.html("panel").split('id="pbox">')[1].split('<div class="actions">')[0], n = P.sentences.length;
    const rows = pbox.match(/<button type="button" class="ghost lsay" id="ls\d+" aria-label="Play sentence \d+">▶ Sentence \d+<\/button>/g) || [];
    check(`${n} play rows, numbered in order`, rows.length === n && rows.every((r, i) => r.includes(`id="ls${i}"`) && r.includes(`▶ Sentence ${i+1}<`)));
    check("no sentence text, no word taps, no translation in the listening rows", !/data-pw|class="ptxt"/.test(pbox) && P.sentences.every(s => !pbox.includes(VC.escapeHtml(s.t)) && !pbox.includes(VC.escapeHtml(s.en))));
    check("Play all, Show text, Done listening present", /id="lplay">Play all</.test(b.api.html("panel")) && /id="ltext" aria-expanded="false">Show text</.test(b.api.html("panel")) && /id="rdone">Done listening</.test(b.api.html("panel")));
    const k = b.spoken.length;
    b.api.el("ls2").click();
    check("a play row speaks its sentence", b.spoken.slice(k).join() === P.sentences[2].t);
    check("peekText false before Show text", b.api.rd().peekText === false);
    b.api.el("ltext").click();
    const shown = b.api.html("pbox");
    check("Show text: the ordinary passage rows (tap-to-gloss) replace the play rows, peekText logged",
      b.api.rd().peekText === true && /data-pw/.test(shown) && !/class="ghost lsay"/.test(shown) && (shown.match(/class="psent/g) || []).length === n && b.api.el("ltext").textContent === "Hide text");
    b.api.el("ltext").click();
    check("Hide text: play rows back, peekText stays logged", /class="ghost lsay"/.test(b.api.html("pbox")) && b.api.rd().peekText === true);
  }catch(e){ check(`section threw: ${e.stack}`, false); }

  // ---------------------------------------------------------------- [4] Play all
  console.log("\n[4] Play all: n sentences in order, each after the last ends; stops on Done listening");
  try{
    const b = await boot();
    b.api.setProg(rereadProg(PASSAGES, P));
    b.api.startPassage(P, true, "listen");
    const n = P.sentences.length;
    b.api.el("lplay").click();
    check("Play all starts sentence 1 and becomes Stop", b.spoken.length === 1 && b.spoken[0] === P.sentences[0].t && b.api.el("lplay").textContent === "Stop");
    for(let i = 1; i < n; i++){ fire(b.ss, b.utts[b.utts.length - 1]); await sleep(5); }
    check(`${n} speak calls, in sentence order`, b.spoken.length === n && b.spoken.every((t, i) => t === P.sentences[i].t), JSON.stringify(b.spoken.slice(0, 3)));
    fire(b.ss, b.utts[b.utts.length - 1]); await sleep(5);
    check("after the last sentence: nothing more, button back to Play all", b.spoken.length === n && b.api.el("lplay").textContent === "Play all");
    // A cancelled utterance (error "canceled") is not an end: the chain waits.
    b.api.el("lplay").click();
    const k0 = b.spoken.length;
    b.ss.speaking = false; b.utts[b.utts.length - 1].onerror({ error: "canceled" }); await sleep(5);
    check("a canceled utterance does not advance Play all", b.spoken.length === k0);
    fire(b.ss, b.utts[b.utts.length - 1]); await sleep(5);
    const k1 = b.spoken.length;
    check("its real end does (sentence 2 follows)", k1 === k0 + 1 && b.spoken[k1 - 1] === P.sentences[1].t);
    b.api.el("rdone").click(); await sleep(DEFER);
    const k2 = b.spoken.length; // the first question speaks on mount
    fire(b.ss, b.utts.find(u => u.text === P.sentences[1].t && b.utts.indexOf(u) === k1 - 1)); await sleep(DEFER);
    check("Done listening stops the chain: sentence 2's late end plays nothing more", b.spoken.length === k2 && b.spoken.slice(k1).every(t => !P.sentences.some(s => s.t === t)));
    // Stop button, and a row tap, end the chain.
    const c = await boot();
    c.api.setProg(rereadProg(PASSAGES, P)); c.api.startPassage(P, true, "listen");
    c.api.el("lplay").click(); c.api.el("lplay").click();
    const j = c.spoken.length; fire(c.ss, c.utts[c.utts.length - 1]); await sleep(5);
    check("Stop: nothing further plays", c.spoken.length === j && c.api.el("lplay").textContent === "Play all");
    c.api.el("lplay").click(); c.api.el("ls3").click(); await sleep(DEFER);
    const j2 = c.spoken.length; fire(c.ss, c.utts[c.utts.length - 1]); await sleep(DEFER);
    check("a row tap during Play all plays that row and ends the chain", c.spoken[j2 - 1] === P.sentences[3].t && c.spoken.length === j2);
    // A tab switch (render() calls stopSpeaking) ends the chain and the current sentence at once.
    const t = await boot();
    t.api.setProg(rereadProg(PASSAGES, P)); t.api.startPassage(P, false, "listen");
    t.api.el("lplay").click();
    const cur = t.utts[t.utts.length - 1], c0 = t.ss.cancels, t0 = t.spoken.length;
    t.document.querySelectorAll('#tabs button[data-t="words"]')[0].click();
    check("tab switch: the playing sentence is cancelled at once", t.ss.cancels === c0 + 1 && t.api.rd() === null);
    fire(t.ss, cur); await sleep(DEFER);
    check("tab switch: the cancelled sentence's late end starts nothing", t.spoken.length === t0);
    // A re-render of the listening screen (readRender stops speech) resets Play all.
    const r = await boot();
    r.api.setProg(rereadProg(PASSAGES, P)); r.api.startPassage(P, false, "listen");
    r.api.el("lplay").click(); const rc = r.utts[r.utts.length - 1];
    r.api.rerender();
    check("re-render mid Play all: speech stopped, button back to Play all, RD.playing false", r.api.el("lplay").textContent !== "Stop" && /id="lplay">Play all</.test(r.api.html("panel")) && r.api.rd().playing === false);
    const r0 = r.spoken.length; fire(r.ss, rc); await sleep(DEFER);
    check("re-render: the stopped sentence's late end starts nothing", r.spoken.length === r0);
    // Engine that fires onend (not an error) on cancel(), and never starts sentence 2's
    // first utterance: ttsDriver cancels it and retries. The cancel's stale onend must not
    // advance Play all, or sentence 2 would be skipped.
    {
      const P3 = JSON.parse(JSON.stringify(P)); P3.sentences = P3.sentences.slice(0, 3);
      let stalled = false;
      const hook = (ss, spoken, utts) => {
        ss.speak = u => {
          spoken.push(u.text); utts.push(u);
          if(u.text === P3.sentences[1].t && !stalled){ stalled = true; ss.stalledU = u; return; } // never starts
          ss.speaking = true;
          setTimeout(() => { if(u.done) return; u.done = true; ss.speaking = false; if(u.onend) u.onend({}); }, 15);
        };
        ss.cancel = () => { ss.cancels++; ss.speaking = false; ss.pending = false; utts.forEach(u => { if(!u.done){ u.done = true; if(u.onend) u.onend({}); } }); };
      };
      const e = await boot({ ssHook: hook });
      e.api.setProg(rereadProg(PASSAGES, P)); e.api.startPassage(P3, false, "listen");
      e.api.el("lplay").click();
      await sleep(VC.TTS_TIMING.watchMs + VC.TTS_TIMING.pollMs * 2 + VC.TTS_TIMING.deferMs + 400);
      const want = [P3.sentences[0].t, P3.sentences[1].t, P3.sentences[1].t, P3.sentences[2].t];
      check("onend-on-cancel engine + one retry: all 3 sentences in order, the stalled one retried, each once after its end", JSON.stringify(e.spoken) === JSON.stringify(want) && e.api.el("lplay").textContent === "Play all", JSON.stringify(e.spoken.map(t => P3.sentences.findIndex(x => x.t === t))));
    }
    // Clips, no voice: the chain runs on the shared Audio element's onended.
    const CP = JSON.parse(JSON.stringify(P)); CP.sentences.forEach((s, i) => { s.audio = `audio/p/${i}.mp3`; });
    const d = await boot({ voices: [{ lang: "en-US", name: "en" }], passages: PASSAGES.map(p => p.id === P.id ? CP : p) });
    d.api.setProg(rereadProg(PASSAGES, P)); d.api.startPassage(CP, true, "listen");
    d.api.el("lplay").click();
    for(let i = 1; i < n; i++){ d.audio().onended(); await sleep(5); }
    check(`clips: ${n} plays in order, no TTS`, d.plays.length === n && d.plays.every((s, i) => s === `audio/p/${i}.mp3`) && d.spoken.length === 0);
  }catch(e){ check(`section threw: ${e.stack}`, false); }

  // ---------------------------------------------------------------- [5] questions + results
  console.log("\n[5] questions: seeded half audio-only behind Show question; results lines; done record l:1");
  try{
    const b = await boot();
    const pr = rereadProg(PASSAGES, P); b.api.setProg(pr);
    b.api.startPassage(P, true, "listen");
    const ao = b.api.rd().audioOnly, n = P.questions.length;
    check(`audioOnly = VC.listenAudioOnly(id, previous attempts=1, ${n}) (${ao.join(",")})`, JSON.stringify(ao) === JSON.stringify(VC.listenAudioOnly(P.id, 1, n)) && ao.length === Math.ceil(n / 2));
    b.api.el("ltext").click();
    b.api.el("rdone").click();
    const tapIdx = ao[0], lateIdx = ao.length > 1 ? ao[1] : null;
    let hiddenOk = true, shownOk = true, spokeOk = true, tapOk = false, lateOk = lateIdx === null;
    for(let qi = 0; qi < n; qi++){
      const q = P.questions[qi], h = b.api.html("panel");
      spokeOk = spokeOk && b.spoken[b.spoken.length - 1] === q.q;
      if(ao.indexOf(qi) >= 0){
        hiddenOk = hiddenOk && /id="qsh"[^>]*>Show question</.test(h) && !/class="med wd"/.test(h) && !/id="qtr"/.test(h) && /id="rpa"/.test(h) && !(q.en && h.includes(VC.escapeHtml(q.en)));
        if(qi === tapIdx){
          b.api.el("qsh").click();
          const w = b.api.html("qshwrap");
          tapOk = b.api.rd().answers[qi].qh === true && /class="med wd"/.test(w) && (!q.en || /id="qtr"/.test(w));
          if(q.en){ b.api.el("qtr").click(); tapOk = tapOk && b.api.rd().answers[qi].tr === true; }
        }
      } else shownOk = shownOk && /class="med wd"/.test(h) && !/id="qsh"/.test(h);
      const os = b.api.el("o").children;
      os.find(x => x.dataset.v === String(q.answer)).click();
      if(qi === lateIdx){ const w = b.api.html("qshwrap"); lateOk = !b.api.rd().answers[qi].qh && /class="med wd"/.test(w) && !/id="qsh"/.test(w) && (!q.en || /id="qtr"/.test(w)); }
      b.api.el("nx").click(); await sleep(DEFER);
    }
    check("audio-only questions: text, translation button hidden behind #qsh; Replay present", hiddenOk);
    check("other questions show their text as in a reading pass", shownOk);
    check("every question is spoken on mount (both kinds)", spokeOk);
    check("Show question before answering: reveals text + translation button, logs qh", tapOk);
    check("answering an audio-only question reveals its text + translation button (#qsh gone), qh not logged", lateOk);
    const res = b.api.html("panel");
    const lines = [...res.matchAll(/(?:✓|✗) Question (\d+)[^<]*/g)].map(m => m[0]);
    check("results: 'Listening pass' and 'Text shown while listening'", /id="lmode"[^>]*>Listening pass<br>Text shown while listening</.test(res));
    check("results: ' · question shown' only on the tapped question's line", lines.length === n && lines.every((l, i) => l.includes("· question shown") === (i === tapIdx)));
    const rec = pr.read.done[P.id];
    check("done record: l:1, x counts on, full score", rec.l === 1 && rec.x === 2 && rec.sc === n && rec.n === n);
    // A listen pass without Show text: header line only.
    const c = await boot(); c.api.setProg(rereadProg(PASSAGES, P)); c.api.startPassage(P, true, "listen");
    c.api.el("rdone").click(); answerAll(c.api, P, false);
    check("results without Show text: 'Listening pass' alone", /id="lmode"[^>]*>Listening pass<\/p>/.test(c.api.html("panel")));
    // A reading pass: no l, no listen lines.
    const r = await boot(); const pr2 = rereadProg(PASSAGES, P); r.api.setProg(pr2);
    r.api.startPassage(P, false); r.api.el("rdone").click(); answerAll(r.api, P, true);
    check("reading pass: done record has no l, no listening lines", !("l" in pr2.read.done[P.id]) && !/Listening pass|question shown/.test(r.api.html("panel")));
    // No voice + clips: audio-only needs the question spoken, so none are hidden.
    const CP = JSON.parse(JSON.stringify(P)); CP.sentences.forEach((s, i) => { s.audio = `audio/p/${i}.mp3`; });
    const d = await boot({ voices: [{ lang: "en-US", name: "en" }], passages: PASSAGES.map(p => p.id === P.id ? CP : p) });
    d.api.setProg(rereadProg(PASSAGES, P)); d.api.startPassage(CP, true, "listen");
    d.api.el("rdone").click();
    let noneHidden = true;
    for(let qi = 0; qi < n; qi++){ noneHidden = noneHidden && !/id="qsh"/.test(d.api.html("panel")) && /class="med wd"/.test(d.api.html("panel")); const os = d.api.el("o").children; os[0].click(); d.api.el("nx").click(); }
    check("clips but no voice: the questions cannot be spoken, so none is audio-only", noneHidden);
  }catch(e){ check(`section threw: ${e.stack}`, false); }

  // ---------------------------------------------------------------- [6] control vs base branch
  console.log(`\n[6] control: no voice, no clips -> Today + reading pass markup byte-identical to ${BASE}`);
  try{
    let baseHtml = null;
    try{ baseHtml = cp.execSync(`git show ${BASE}:engine/app.html`, { cwd: ROOT, encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] }); }catch(e){}
    check(`base ${BASE} engine/app.html loaded from git (a missing sha is a failure)`, !!baseHtml);
    if(baseHtml){
      const NV = [{ lang: "en-US", name: "en" }];
      const run = async html => {
        const b = await boot({ voices: NV, html });
        const pr = rereadProg(PASSAGES, P); b.api.setProg(pr);
        const out = [];
        b.api.today(); out.push(b.api.html("panel"));
        b.api.enterTodayStep(5); out.push(b.api.html("panel"));
        b.api.el("rdone").click();
        for(let qi = 0; qi < P.questions.length; qi++){
          out.push(b.api.html("panel"));
          const os = b.api.el("o").children; os[qi % os.length].click(); out.push(b.api.html("rv")); b.api.el("nx").click();
        }
        out.push(b.api.html("panel"));
        out.push(JSON.stringify(pr.read.done[P.id]));
        return out;
      };
      // The app's shuffles (core.js shuffle) use the global Math.random: seed it per run.
      const real = Math.random;
      const seeded = async html => { Math.random = mulberry32(11); try{ return await run(html); } finally { Math.random = real; } };
      const cur = await seeded(appHtml), base = await seeded(baseHtml);
      const diff = cur.findIndex((h, i) => h !== base[i]);
      check(`Today plan, passage, ${P.questions.length} questions + reveals, results, done record: identical (${cur.length} captures)`, cur.length === base.length && diff < 0, diff >= 0 ? `first diff at capture ${diff}` : "");
    }
  }catch(e){ check(`section threw: ${e.stack}`, false); }

  console.log(`\n${fails === 0 ? "ALL PASSED" : "FAILED"}: ${passes} passed, ${fails} failed`);
  process.exit(fails === 0 ? 0 : 1);
})().catch(e => { console.error(e); process.exit(1); });
