// Recorded audio checks (docs/AUDIO.md, phase 2): core.js wordAudio / packAudio and the
// script primer's example-word clips; engine/app.html word call sites (sayWord /
// canHearWord), the no-voice notices under pack.audio, speak()'s clip -> TTS -> hint
// fallback; build.sh's audio cache version; sw.js's audio cache (cache on play, Range
// slices, cap, offline, activate keeps it).
// The app is booted against the Persian pack (../persian/pack; skipped when absent) with
// 3 clips added: the example words of the primer's "be" unit. Fake DOM as in
// tests/characters_app_checks.js (engine_checks.js check [23]).
// Run: node tests/audio_checks.js
"use strict";
const fs = require("fs");
const os = require("os");
const path = require("path");
const cp = require("child_process");

const ROOT = path.join(__dirname, "..");
const VC = require(path.join(ROOT, "engine", "core.js"));
const FA = path.join(ROOT, "..", "persian", "pack");
function loadConst(file, name){ return new Function(fs.readFileSync(file, "utf8") + `\nreturn ${name};`)(); }
function tryLoadConst(file, name){ try{ return loadConst(file, name); }catch(e){ return undefined; } }

let fails = 0, passes = 0;
function check(name, cond){
  if(cond){ passes++; console.log(`PASS  ${name}`); }
  else { fails++; console.log(`FAIL  ${name}`); }
}
const tick = () => new Promise(r => setTimeout(r, 0));

// ------------------------------------------------------------------ fake DOM (characters_app_checks)
const appHtml = fs.readFileSync(path.join(ROOT, "engine", "app.html"), "utf8");
const scriptBlocks = [...appHtml.matchAll(/<script>([\s\S]*?)<\/script>/g)];
const appSrc = scriptBlocks[scriptBlocks.length - 1][1];
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
      this.onclick = null; this._listeners = {}; this._children = [];
      if(this._attrs.id) registry.set(this._attrs.id, this);
    }
    get id(){ return this._attrs.id || ""; }
    set id(v){ this._attrs.id = v; registry.set(v, this); }
    get className(){ return [...this._classes].join(" "); }
    set className(v){ this._classes = new Set(String(v).split(/\s+/).filter(Boolean)); }
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
    appendChild(c){ this._children.push(c); c.parentNode = this; return c; }
    insertAdjacentHTML(){}
    remove(){ if(this.parentNode){ const k = this.parentNode._children; const i = k.indexOf(this); if(i >= 0) k.splice(i, 1); this.parentNode = null; } if(registry.get(this.id) === this) registry.delete(this.id); }
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
    El, title: "", head: { appended: [], appendChild(c){ this.appended.push(c); return c; } }, body: new El("body", {}), documentElement: new El("html", {}),
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

// Recording fakes: Audio (one object per construction; the app makes one via audioSlot)
// and speechSynthesis. ctl.play(a) decides what play() returns (default: resolves).
function fakes(voices, online){
  const log = { played: [], spoken: [], ctl: { play: null } };
  const ss = { getVoices: () => voices, onvoiceschanged: null, cancel(){}, speak(u){ log.spoken.push(u.text); } };
  function Utt(t){ this.text = t; }
  const window = { VocabCore: VC, speechSynthesis: ss, SpeechSynthesisUtterance: Utt, addEventListener(){} };
  function Audio(){ const a = { src: "", onended: null, onerror: null, pause(){},
    play(){ log.played.push(a.src); return log.ctl.play ? log.ctl.play(a) : Promise.resolve(); } }; return a; }
  return { log, window, Utt, Audio, navigator: { userAgent: "AudioChecks/1.0", onLine: online !== false } };
}
async function boot(data, opts){
  const o = opts || {};
  const document = makeFakeDom();
  const f = fakes(o.voices || [{ lang: "en-US", name: "en" }], o.online);
  const fnBody = appSrc + `
return {
  html: id => { const e = document.getElementById(id); return e ? e.innerHTML : null; },
  el: id => document.getElementById(id),
  goto: t => { tab = t; testSel = null; RD = null; render(); },
  hearItem, readItem, recallItem, typeItem, revealBlock, vocabTeach, wordListInto, speechNotice, speak, sayWord, canHearWord,
  scriptDrillItem, scriptTeachHTML, scriptRevealBlock, unit: id => SUNIT_BY_ID[id], packAudio: () => PACK_AUDIO, hasSpeech: () => hasSpeech,
  panelListeners: () => document.getElementById("panel")._listeners.click || [],
};`;
  const names = ["document","window","SpeechSynthesisUtterance","navigator","location","localStorage","matchMedia","requestAnimationFrame","Audio","confirm","alert","PACK","WORDS","SENTENCES","LESSONS","PASSAGES","SCRIPT"];
  const args = [document, f.window, f.Utt, f.navigator, undefined, { getItem(){ return null; }, setItem(){} }, () => ({ matches:false }), fn => setTimeout(fn, 0),
    f.Audio, () => true, () => {}, data.pack, data.words, data.sentences, [], data.passages, data.script];
  const api = new Function(...names, fnBody)(...args);
  await tick(); await tick();
  return { api, document, log: f.log };
}

// ------------------------------------------------------------------ [1] core.js
function coreChecks(){
  console.log("\n[1] core.js: wordAudio, packAudio, script primer example-word clips");
  check("wordAudio: a word's non-empty audio string", VC.wordAudio({ w: "x", audio: "audio/w/w1.opus" }) === "audio/w/w1.opus");
  check("wordAudio: undefined for no field, empty string, non-string, non-object",
    [{ w: "x" }, { audio: "" }, { audio: 3 }, null, undefined, "x"].every(w => VC.wordAudio(w) === undefined));
  check("packAudio: true only for audio {voice: non-empty string}",
    VC.packAudio({ audio: { voice: "v", version: 1 } }) === true &&
    [{}, { audio: true }, { audio: {} }, { audio: { voice: "" } }, null].every(p => VC.packAudio(p) === false));
  // A synthetic 5-unit script (4 options needed) whose unit "u-b" has 2 example words.
  const words = [1,2,3,4,5,6].map(i => ({ id: "w" + i, w: "ب" + "ا".repeat(i), en: "g" + i, lv: "A1" }));
  const units = ["ب","ت","ث","ن","ی"].map((t, i) => ({ id: "u-" + i, st: "s", set: 1, t, roman: "r" + i, say: t + "َ",
    ex: i === 0 ? [["w1", "ba"], ["w2", "baa"]] : [["w" + (i + 2), "x" + i]] }));
  const byIdPlain = Object.fromEntries(words.map(w => [w.id, w]));
  const byIdRec = Object.fromEntries(words.map(w => [w.id, Object.assign({}, w, w.id === "w1" || w.id === "w2" ? { audio: `audio/w/${w.id}.opus` } : {})]));
  const byIdHalf = Object.fromEntries(words.map(w => [w.id, Object.assign({}, w, w.id === "w1" ? { audio: "audio/w/w1.opus" } : {})]));
  const ctx = (byId, tts) => ({ units, byId, tts, rng: () => 0 });
  const plain = VC.scriptItem("wordHear", units[0], ctx(byIdPlain, false));
  check("no voice, no clips: wordHear becomes wordRead with no audio (unchanged)", plain.kind === "wordRead" && plain.audio === null && plain.audioUrl === null);
  const rec = VC.scriptItem("wordHear", units[0], ctx(byIdRec, false));
  check("no voice, every example word has a clip: wordHear stays, plays the clip before, no TTS text",
    rec.kind === "wordHear" && rec.audio === "before" && rec.audioUrl === `audio/w/${rec.wordId}.opus` && rec.say === null);
  const half = VC.scriptItem("wordHear", units[0], ctx(byIdHalf, false));
  check("no voice, only some example words have clips: wordHear becomes wordRead", half.kind === "wordRead");
  const rd = VC.scriptItem("wordRead", units[0], ctx(byIdRec, false));
  check("wordRead with a clip and no voice: the clip plays after answering", rd.audio === "after" && /^audio\/w\/w[12]\.opus$/.test(rd.audioUrl));
  const both = VC.scriptItem("wordHear", units[0], ctx(byIdRec, true));
  check("with a voice: TTS text kept as the fallback, the clip beats it", both.say === both.answer && !!both.audioUrl);
  const withVoicePlain = VC.scriptItem("wordHear", units[0], ctx(byIdPlain, true));
  check("with a voice, no clips: exactly as before (say = word, no audioUrl)", withVoicePlain.say === withVoicePlain.answer && withVoicePlain.audioUrl === null);
  check("scriptKindFor keeps wordHear for pack.script tts false when every example word has a clip",
    VC.scriptKindFor("wordHear", units[0], { tts: false }, { units, byId: byIdRec }) === "wordHear" &&
    VC.scriptKindFor("wordHear", units[0], { tts: false }, { units, byId: byIdPlain }) === "wordRead");
}

// ------------------------------------------------------------------ [2]-[5] app
function faData(withAudio){
  const pack = loadConst(path.join(FA, "pack.js"), "PACK");
  const words = loadConst(path.join(FA, "words.js"), "WORDS");
  const sentences = loadConst(path.join(FA, "sentences.js"), "SENTENCES");
  const passages = tryLoadConst(path.join(FA, "sentences.js"), "PASSAGES") || [];
  const script = loadConst(path.join(FA, "script.js"), "SCRIPT");
  const be = script.units.find(u => u.id === "fa-be");
  const clipIds = be.ex.map(e => e[0]);
  if(withAudio){
    words.forEach(w => { if(clipIds.includes(w.id)) w.audio = `audio/w/${w.id}.opus`; });
    if(withAudio !== "clipsOnly") pack.audio = { voice: "fa_IR-ganji_adabi-medium", version: 1 };
  }
  const byId = Object.fromEntries(words.map(w => [w.id, w]));
  return { pack, words, sentences, passages, script, clipIds, byId };
}
const NOVOICE = [{ lang: "en-US", name: "en" }], FAVOICE = [{ lang: "fa-IR", name: "fa" }];

async function appChecks(){
  if(!fs.existsSync(path.join(FA, "pack.js"))){ console.log("\nNOTE  ../persian/pack missing: app checks skipped"); return; }
  const D = faData(true);
  const [c1, c2, c3] = D.clipIds.map(id => D.byId[id]);
  const plain = D.words.find(w => !w.audio && w.lv === "A1");
  console.log(`\n[2] no voice, pack.audio + 3 clips (${D.clipIds.join(", ")}): word sites play clips`);
  {
    const { api, log } = await boot(D, { voices: NOVOICE });
    check("setup: no usable voice, PACK_AUDIO on", api.hasSpeech() === false && api.packAudio() === true);
    check("canHearWord: true for a word with a clip, false for one without", api.canHearWord(c1) && !api.canHearWord(plain));
    const h = api.hearItem(c1);
    check("hearItem (Listen) with a clip: a hear item with the speaker, not the read fallback", /id="sp"/.test(h.html) && !h.needsNotice);
    const h2 = api.hearItem(plain);
    check("hearItem without a clip: read fallback flagged needsNotice (as before)", h2.needsNotice === true && !/id="sp"/.test(h2.html));
    check("speechNotice is empty when the pack ships audio", api.speechNotice() === "");
    log.played.length = 0;
    api.el("panel").innerHTML = h.html; h.mount();
    check("hearItem mount plays the word's clip, no TTS", log.played.join() === c1.audio && log.spoken.length === 0);
    log.played.length = 0; api.readItem(c2).mount();
    check("readItem mount plays the clip", log.played.join() === c2.audio);
    log.played.length = 0; api.recallItem(c3).onReveal(); api.typeItem(c1).onReveal();
    check("recallItem / typeItem reveal play the clips", log.played.join() === [c3.audio, c1.audio].join());
    log.played.length = 0; api.readItem(plain).mount();
    check("a word without a clip and no voice: nothing plays", log.played.length === 0 && log.spoken.length === 0);
    check("revealBlock: tappable (data-wid + icon) with a clip, not without",
      new RegExp(`data-wid="${c1.id}"`).test(api.revealBlock(c1)) && !/data-wid=/.test(api.revealBlock(plain)));
    // The panel's delegated tap listener: a data-wid target speaks the word (tap on reveal / teach).
    log.played.length = 0;
    const target = { dataset: { wid: c2.id } };
    api.panelListeners().forEach(f => f({ target: { closest: sel => /data-wid/.test(sel) ? target : null } }));
    check("panel data-wid tap plays the clip", log.played.join() === c2.audio);
    // Teach rows and the hint.
    api.vocabTeach([c1, plain], "A1", () => {});
    check("vocabTeach: 'Tap a word to hear it.' shown when a listed word has a clip", /Tap a word to hear it\./.test(api.html("panel")));
    const tl = api.el("tl");
    log.played.length = 0; tl.children[0].onclick && tl.children[0].onclick();
    check("vocabTeach: a clip word's row is clickable and plays it; a plain word's row is not",
      typeof tl.children[0].onclick === "function" && log.played.join() === c1.audio && tl.children.filter(r => r.className === "rowset")[1].onclick === null);
    const wl = { _c: [], appendChild(c){ this._c.push(c); return c; } };
    // wordListInto builds rows with document.createElement; pass a stub list container.
    api.wordListInto(wl, [plain, c3]);
    log.played.length = 0; wl._c[1].onclick();
    check("Words tab rows: clickable and playing only for a word with a clip", wl._c[0].onclick === null && log.played.join() === c3.audio);
    api.goto("progress");
    check("Progress: no 'No text-to-speech voice' warning when the pack ships audio", !/No text-to-speech voice/.test(api.html("panel")));
    // Script primer: every example word of fa-be has a clip, so wordHear survives without a voice.
    const be = api.unit("fa-be");
    const it = api.scriptDrillItem("wordHear", be);
    check("primer wordHear (no voice, all fa-be example words recorded): stays a hear item", /id="sp"/.test(it.html) && it.label === "Which word do you hear?");
    log.played.length = 0; api.el("panel").innerHTML = it.html; it.mount();
    check("primer wordHear mount plays the example word's clip", log.played.length === 1 && D.clipIds.some(id => log.played[0] === `audio/w/${id}.opus`));
    check("primer teach card: example words with clips are tappable (data-xw)", D.clipIds.every(id => new RegExp(`data-xw="${id}"`).test(api.scriptTeachHTML(be))));
    log.played.length = 0;
    const xt = { dataset: { xw: c1.id } };
    api.panelListeners().forEach(f => f({ target: { closest: sel => /data-xw/.test(sel) ? xt : null } }));
    check("primer example-word tap (data-xw) plays the clip without a voice", log.played.join() === c1.audio);
    const other = api.unit("fa-te");
    check("primer wordHear for a unit without recorded examples still becomes wordRead", api.scriptDrillItem("wordHear", other).label !== "Which word do you hear?");
  }

  console.log("\n[3] speak(): clip, else TTS, else hint; stale failures ignored");
  {
    const { api, log, document } = await boot(D, { voices: FAVOICE });
    check("setup: a Persian voice", api.hasSpeech() === true);
    api.sayWord(c1);
    check("with a voice, a word with a clip plays the clip (no TTS)", log.played.join() === c1.audio && log.spoken.length === 0);
    api.sayWord(plain);
    check("with a voice, a word without a clip uses TTS", log.spoken.join() === plain.w);
    log.played.length = 0; log.spoken.length = 0;
    log.ctl.play = () => Promise.reject(Object.assign(new Error("x"), { name: "NotSupportedError" }));
    api.sayWord(c2); await tick();
    check("a clip that fails to load falls back to TTS of the same word", log.played.join() === c2.audio && log.spoken.join() === c2.w);
    log.spoken.length = 0;
    log.ctl.play = () => Promise.reject(Object.assign(new Error("x"), { name: "AbortError" }));
    api.sayWord(c2); await tick();
    check("an interrupted clip (AbortError) does not fall back", log.spoken.length === 0);
    log.ctl.play = () => Promise.reject(Object.assign(new Error("x"), { name: "NotAllowedError" }));
    api.sayWord(c2); await tick();
    check("a blocked autoplay (NotAllowedError) does not fall back", log.spoken.length === 0);
    let rejectA; log.ctl.play = () => new Promise((_, rej) => { rejectA = rejectA || rej; });
    api.sayWord(c1); log.ctl.play = null; api.sayWord(c3);
    rejectA(Object.assign(new Error("x"), { name: "NetworkError" })); await tick();
    check("a failure from a clip a later speak() replaced is ignored", log.spoken.length === 0);
    check("no hint shown while a voice exists", document.getElementById("audiohint") === null);
  }
  {
    const { api, log, document } = await boot(D, { voices: NOVOICE, online: false });
    log.ctl.play = a => { setTimeout(() => a.onerror && a.onerror(), 0); return new Promise(() => {}); };
    api.sayWord(c1); await tick(); await tick();
    const hint = document.getElementById("audiohint");
    check("no voice, offline, uncached clip: an 'Offline' hint toast, no TTS", !!hint && /Offline/.test(hint.textContent) && log.spoken.length === 0);
    api.sayWord(c1); await tick(); await tick();
    check("the hint is shown once at a time (replaced, not stacked)", document.body.children.filter(c => c.id === "audiohint").length === 1);
  }

  console.log("\n[4] clips without pack.audio: they play, the notices still show");
  {
    const { api, log } = await boot(faData("clipsOnly"), { voices: NOVOICE });
    check("PACK_AUDIO off without pack.audio", api.packAudio() === false);
    api.readItem(c1).mount();
    check("a word clip still plays", log.played.join() === c1.audio);
    check("speechNotice shows (pack does not declare audio)", /no text-to-speech voice/.test(api.speechNotice()));
  }

  console.log("\n[5] flag-off: the Persian pack as shipped (no audio) behaves as before");
  {
    const P = faData(false);
    const { api, log } = await boot(P, { voices: NOVOICE });
    const w0 = P.byId[P.clipIds[0]];
    check("no pack audio: PACK_AUDIO off, canHearWord false without a voice", api.packAudio() === false && api.canHearWord(w0) === false);
    check("hearItem degrades to read with the notice", api.hearItem(w0).needsNotice === true);
    check("speechNotice shown", /no text-to-speech voice/.test(api.speechNotice()));
    api.goto("progress");
    check("Progress warning shown", /No text-to-speech voice/.test(api.html("panel")));
    api.readItem(w0).mount();
    check("nothing plays", log.played.length === 0 && log.spoken.length === 0);
    check("primer wordHear without a voice becomes wordRead (unchanged)", api.scriptDrillItem("wordHear", api.unit("fa-be")).label !== "Which word do you hear?");
  }
  {
    const P = faData(false);
    const { api, log } = await boot(P, { voices: FAVOICE });
    api.readItem(P.byId[P.clipIds[0]]).mount();
    check("flag-off with a voice: TTS of the word, no Audio", log.spoken.join() === P.byId[P.clipIds[0]].w && log.played.length === 0);
  }
}

// ------------------------------------------------------------------ [6] build.sh + sw.js
function swSim(src, scope){
  const store = new Map();
  const cacheFor = n => { if(!store.has(n)) store.set(n, new Map()); const m = store.get(n);
    const key = k => typeof k === "string" ? k : k.url;
    return { match: async k => { const r = m.get(key(k)); return r ? r.clone() : undefined; },
             put: async (k, r) => { m.delete(key(k)); m.set(key(k), r); },
             keys: async () => [...m.keys()].map(url => ({ url })), delete: async k => m.delete(key(k)) }; };
  const sim = { store, fetched: [], net: null, L: {} };
  sim.caches = { open: async n => cacheFor(n), keys: async () => [...store.keys()], delete: async n => store.delete(n) };
  const fetch = async req => { const u = typeof req === "string" ? req : req.url; sim.fetched.push(u);
    if(!sim.net) throw new TypeError("Failed to fetch"); return sim.net(u); };
  class Req { constructor(u, init){ this.url = u; this.cache = init && init.cache; } }
  const self = { location: new URL(scope + "sw.js"), registration: { scope },
    addEventListener: (t, f) => { sim.L[t] = f; }, skipWaiting: async () => {}, clients: { claim: async () => {} } };
  new Function("self", "caches", "fetch", "Request", "Response", "URL", src)(self, sim.caches, fetch, Req, Response, URL);
  sim.until = async t => { let w; sim.L[t]({ waitUntil: p => { w = p; } }); await w; };
  sim.go = async (u, range) => { let r = null;
    sim.L.fetch({ request: { url: u, method: "GET", mode: "no-cors", headers: { get: k => k.toLowerCase() === "range" ? (range || null) : null } }, respondWith: p => { r = p; } });
    return r ? await r : undefined; };
  return sim;
}
async function swChecks(){
  console.log("\n[6] build.sh audio version + sw.js audio cache");
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "vocab_engine_audio_"));
  try{
    cp.execSync(`sh build.sh packs/zh "${path.join(dir, "index.html")}"`, { cwd: ROOT, stdio: "pipe" });
    const src0 = fs.readFileSync(path.join(dir, "sw.js"), "utf8");
    check("pack without audio: sw.js audio cache version 0", src0.includes(`const AUDIO_CACHE = PREFIX + "audio:v" + "0";`) && !/__VE_/.test(src0));
    const pk = path.join(dir, "pack"); fs.cpSync(path.join(ROOT, "packs", "zh"), pk, { recursive: true });
    const pj = JSON.parse(fs.readFileSync(path.join(pk, "pack.json"), "utf8")); pj.audio = { voice: "v", version: 3 };
    fs.writeFileSync(path.join(pk, "pack.json"), JSON.stringify(pj, null, 2) + "\n");
    cp.execSync(`python3 tools/jsonify_pack.py "${pk}"`, { cwd: ROOT, stdio: "pipe" });
    const d2 = path.join(dir, "b2"); fs.mkdirSync(d2);
    cp.execSync(`sh build.sh "${pk}" "${path.join(d2, "index.html")}"`, { cwd: ROOT, stdio: "pipe" });
    const src = fs.readFileSync(path.join(d2, "sw.js"), "utf8");
    check("pack.audio.version 3: sw.js audio cache version 3", src.includes(`const AUDIO_CACHE = PREFIX + "audio:v" + "3";`));
    check("sw.js install precaches only the page (no audio route in install)", !/audio/.test((src.match(/addEventListener\("install"[\s\S]*?\n\}\);/) || [""])[0]));

    const ORIGIN = "https://ishmum123.github.io", SCOPE = ORIGIN + "/persian/";
    const sim = swSim(src, SCOPE);
    const PREFIX = "ve:/persian/:", AUDIO = PREFIX + "audio:v3";
    const clip = Buffer.from("0123456789");
    let nets = 0;
    sim.net = u => { nets++; return /missing/.test(u) ? new Response("nf", { status: 404 }) : new Response(clip, { status: 200, headers: { "Content-Type": "audio/ogg" } }); };
    const r1 = await sim.go(SCOPE + "audio/w/w1.opus", "bytes=0-");
    check("first play, Range bytes=0-: 206 with Content-Range over the whole clip",
      r1 && r1.status === 206 && r1.headers.get("content-range") === "bytes 0-9/10" && (await r1.text()) === "0123456789");
    check("the full clip is fetched once without Range and stored in the audio cache", sim.fetched.join() === SCOPE + "audio/w/w1.opus" && sim.store.get(AUDIO).has(SCOPE + "audio/w/w1.opus"));
    sim.net = null;
    const r2 = await sim.go(SCOPE + "audio/w/w1.opus", "bytes=2-5");
    check("offline replay from the cache: Range bytes=2-5 -> 206 '2345'", r2.status === 206 && (await r2.text()) === "2345" && r2.headers.get("content-range") === "bytes 2-5/10");
    const r3 = await sim.go(SCOPE + "audio/w/w1.opus");
    check("offline replay without Range: 200, whole clip", r3.status === 200 && (await r3.text()) === "0123456789");
    const r4 = await sim.go(SCOPE + "audio/w/w1.opus", "bytes=-3");
    check("suffix range bytes=-3 -> last 3 bytes", r4.status === 206 && (await r4.text()) === "789");
    const r5 = await sim.go(SCOPE + "audio/w/w1.opus", "bytes=20-");
    check("unsatisfiable range -> 416", r5.status === 416);
    let offlineMiss = null; try{ await sim.go(SCOPE + "audio/w/w2.opus"); }catch(e){ offlineMiss = e; }
    check("offline, uncached clip: the request fails (the page then hints / uses TTS)", offlineMiss !== null);
    sim.net = u => /missing/.test(u) ? new Response("nf", { status: 404 }) : new Response(clip, { status: 200 });
    const r6 = await sim.go(SCOPE + "audio/w/missing.opus");
    check("a 404 passes through and is not cached", r6.status === 404 && !sim.store.get(AUDIO).has(SCOPE + "audio/w/missing.opus"));
    const other = await sim.go(ORIGIN + "/german/audio/w/w1.opus");
    check("another site's audio is not intercepted", other === undefined);
    // Cap: 805 more distinct clips -> the cache holds 800, the oldest (w1, then c0..) evicted.
    for(let i = 0; i < 805; i++) await sim.go(SCOPE + `audio/s/c${i}.opus`);
    const keys = [...sim.store.get(AUDIO).keys()];
    check(`cache capped at 800 clips, oldest evicted first (size ${keys.length})`,
      keys.length === 800 && !keys.includes(SCOPE + "audio/w/w1.opus") && !keys.includes(SCOPE + "audio/s/c4.opus") && keys.includes(SCOPE + "audio/s/c5.opus") && keys[799] === SCOPE + "audio/s/c804.opus");
    // activate: keeps this version's audio cache and the current build, drops other builds and audio versions.
    const BUILD = (src.match(/const BUILD = "([^"]+)"/) || [])[1];
    ["ve:/persian/:old-build", PREFIX + "audio:v2", "ve:/german/:audio:v1", PREFIX + BUILD].forEach(n => sim.store.set(n, new Map()));
    await sim.until("activate");
    const left = [...sim.store.keys()].sort();
    check("activate keeps the audio cache of this version across builds, deletes older audio versions and builds, keeps other sites",
      left.includes(AUDIO) && left.includes(PREFIX + BUILD) && left.includes("ve:/german/:audio:v1") && !left.includes(PREFIX + "audio:v2") && !left.includes("ve:/persian/:old-build"));
  }catch(e){ check(`sw/build audio checks do not throw (got: ${e.stack})`, false); }
  finally{ fs.rmSync(dir, { recursive: true, force: true }); }
}

(async function main(){
  console.log("Checking recorded audio (docs/AUDIO.md)");
  coreChecks();
  await appChecks();
  await swChecks();
  console.log(`\n${fails ? "FAILED" : "ALL PASSED"}: ${passes} passed, ${fails} failed`);
  process.exit(fails ? 1 : 0);
})();
