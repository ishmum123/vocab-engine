// core.js — language-agnostic vocab trainer logic shared by engine/app.html and the
// node checks. No DOM dependency (runs under Node for tests); exports VocabCore via
// window or module.exports. Everything language-specific comes from the pack
// (see docs/PACK_SCHEMA.md): levels, set size, placement buckets, function words,
// typing rules, TTS locale.
(function(root){
"use strict";

// ------------------------------------------------------------------ utils
function shuffle(a, rng){
  const r = rng || Math.random;
  for(let i=a.length-1;i>0;i--){ const j=Math.floor(r()*(i+1)); [a[i],a[j]]=[a[j],a[i]]; }
  return a;
}
function escapeHtml(s){ return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;").replace(/'/g,"&#39;"); }
const normKey = s => String(s == null ? "" : s).trim().toLowerCase();

// Every render site that shows a word's meaning goes through gloss(), so a future
// pack-level display rule has exactly one place to live.
function gloss(entry){ return String((entry && entry.en) || "").replace(/\s+/g, " ").trim(); }

// first two whitespace-separated words of a gloss, lowercased and stripped of
// punctuation — used to reject near-synonym distractors (two "to eat"-ish glosses).
// Returns "" for a gloss with no latin letters; callers treat "" as "no signal".
function firstTwoWords(en){
  return String(en).toLowerCase().replace(/[^a-z\s]/g,"").trim().split(/\s+/).slice(0,2).join(" ");
}

// ------------------------------------------------------------------ levels
function levelIds(pack){ return (pack.levels||[]).map(l=>String(l.id)); }
function levelIndexMap(pack){ const m = {}; levelIds(pack).forEach((id,i)=>{ m[id] = i; }); return m; }
function levelLabel(pack, id){ const l = (pack.levels||[]).find(x=>String(x.id)===String(id)); return l ? l.label : String(id); }
function setSizeOf(pack){ return pack.setSize || 10; }
function wordsByLevel(words, pack){
  const out = {}; levelIds(pack).forEach(id=>{ out[id] = []; });
  (words||[]).forEach(w=>{ if(out[w.lv]) out[w.lv].push(w); });
  return out;
}
function nSets(list, setSize){ return Math.ceil(list.length / (setSize||10)); }

// ------------------------------------------------------------------ distractors
// Shared "would this distractor also be a right answer?" guards. A word's surfaces are
// its `w` plus every `alt`; two words sharing any surface are homographs to the learner.
function surfaces(e){ return [e.w, ...((e && e.alt) || [])].map(normKey).filter(Boolean); }
function sharesSurface(a, b){ const s = new Set(surfaces(a)); return surfaces(b).some(x=>s.has(x)); }
// Same pronunciation (when both carry pron): indistinguishable in a hear item.
function samePron(a, b){ return !!(a && b && a.pron && b.pron) && normKey(a.pron) === normKey(b.pron); }
// entry: a word; pool: WORDS. Up to 3 other words whose gloss is a plausible wrong
// answer: never the same gloss, never sharing the first two gloss words with the
// answer or with each other, same level preferred over other levels. Never a
// homograph of the answer (shared w/alt surface: the read stimulus would fit both)
// or a homophone (same pron: the hear stimulus would fit both).
function meaningOpts(entry, pool){
  const ansKey = normKey(entry.en);
  const ansFirst2 = firstTwoWords(entry.en);
  const candidates = (pool||[]).filter(v=>v.id!==entry.id && normKey(v.en)!==ansKey && !sharesSurface(v, entry) && !samePron(v, entry));
  const ordered = [...shuffle(candidates.filter(v=>v.lv===entry.lv)), ...shuffle(candidates.filter(v=>v.lv!==entry.lv))];
  function pass(strict){
    const chosen = []; const usedFirst2 = new Set(ansFirst2 ? [ansFirst2] : []); const usedGloss = new Set([ansKey]);
    ordered.forEach(v=>{
      if(chosen.length>=3) return;
      const f2 = firstTwoWords(v.en), g = normKey(v.en);
      if(usedGloss.has(g)) return; // two identical option labels would make the answer ambiguous
      if(strict && f2 && usedFirst2.has(f2)) return;
      chosen.push(v); usedGloss.add(g); if(f2) usedFirst2.add(f2);
    });
    return chosen;
  }
  let chosen = pass(true);
  if(chosen.length<3) chosen = pass(false); // small-pool fallback: keep "not the answer" only
  return chosen.slice(0,3);
}

// entry: a word; pool: WORDS. Up to 3 other words to show as wrong answers when the
// learner sees a meaning and must pick the word (recall, gap). Never the answer's own
// surface form, never a word whose gloss (or first two gloss words) matches the
// answer's — that distractor would also be a correct answer. Preference order:
// same pos AND same level, then same level, then same pos elsewhere, then anything.
// Distractors have distinct displayed `w`; a strict pass also keeps their glosses'
// first two words distinct from each other, relaxed only for tiny pools.
// showOf (optional, default e => e.w): the label each option is displayed by. Distractor
// labels are kept distinct from each other and from every answer surface under it.
function wordOpts(entry, pool, showOf){
  const show = showOf || (e => e.w);
  const ansGloss = normKey(entry.en), ansF2 = firstTwoWords(entry.en);
  const hasPos = !!entry.pos;
  const cands = (pool||[]).filter(v =>
    v.id!==entry.id && !sharesSurface(v, entry) && normKey(v.en)!==ansGloss && !(ansF2 && firstTwoWords(v.en)===ansF2));
  const samePos = v => hasPos && v.pos===entry.pos;
  const t1 = cands.filter(v=>v.lv===entry.lv && samePos(v));
  const t2 = cands.filter(v=>v.lv===entry.lv && !samePos(v));
  const t3 = cands.filter(v=>v.lv!==entry.lv && samePos(v));
  const t4 = cands.filter(v=>v.lv!==entry.lv && !samePos(v));
  const ordered = [...shuffle(t1), ...shuffle(t2), ...shuffle(t3), ...shuffle(t4)];
  function pass(strict){
    // Every answer surface is already excluded from `cands`; among distractors only
    // the displayed `w` must differ (their alts are never shown, so sharing one is fine).
    const chosen = []; const usedW = new Set([...surfaces(entry), normKey(show(entry))]); const usedF2 = new Set();
    for(const v of ordered){
      if(chosen.length>=3) break;
      const k = normKey(show(v)), f2 = firstTwoWords(v.en);
      if(usedW.has(k)) continue;
      if(strict && f2 && usedF2.has(f2)) continue;
      chosen.push(v); usedW.add(k); if(f2) usedF2.add(f2);
    }
    return chosen;
  }
  let chosen = pass(true);
  if(chosen.length<3) chosen = pass(false);
  return chosen;
}
// Cloze distractors use the same rules as recall: plausible words, never a second right answer.
const gapOpts = wordOpts;

// sentence: a SENTENCES entry; pool: SENTENCES. Up to 3 other sentences of the same
// level with a different English gloss, preferring ones that share a word id with
// the answer (a plausible near-miss); widens past the level only for tiny pools.
function sentenceOpts(sentence, pool){
  const ansKey = normKey(sentence.en);
  const wordSet = new Set(sentence.words || []);
  const shares = s => (s.words||[]).some(w=>wordSet.has(w));
  const candidates = (pool || []).filter(s => s.id !== sentence.id && s.lv === sentence.lv && normKey(s.en) !== ansKey);
  const chosen = []; const seenEn = new Set([ansKey]);
  function addFrom(list){
    list.forEach(s=>{
      if(chosen.length>=3) return;
      const key = normKey(s.en);
      if(seenEn.has(key)) return;
      seenEn.add(key); chosen.push(s);
    });
  }
  addFrom(shuffle(candidates.filter(shares))); addFrom(shuffle(candidates.filter(s=>!shares(s))));
  if(chosen.length<3) addFrom(shuffle((pool||[]).filter(s=>s.id!==sentence.id)));
  return chosen.slice(0,3);
}

// ------------------------------------------------------------------ typing
// Accent folding: NFD-decompose and drop combining marks (é -> e, ñ -> n, ü -> u).
function foldAccents(s){ return String(s).normalize("NFD").replace(/[\u0300-\u036f\u1ab0-\u1aff\u1dc0-\u1dff\u20d0-\u20ff\ufe20-\ufe2f]/g, "").normalize("NFC"); }
// opts: {caseSensitive, foldAccents}. Trims, collapses inner whitespace, unifies
// typographic apostrophes, casefolds unless caseSensitive, accent-folds if asked.
function normalizeTyped(s, opts){
  const o = opts || {};
  let out = String(s == null ? "" : s).normalize("NFC").replace(/[\u2018\u2019\u02bc`]/g, "'").replace(/\s+/g, " ").trim();
  if(!o.caseSensitive) out = out.toLowerCase();
  if(o.foldAccents) out = foldAccents(out);
  return out;
}
function typingEnabled(pack){ return !!(pack && pack.typing); }
// Accents are forgiven when the pack says "lenient" and the word's level is before
// typing.strictFromLevel (or there is no strict level). "strict" never forgives.
function typingLenientFor(entry, pack){
  const t = (pack && pack.typing) || {};
  if((t.accents || "lenient") !== "lenient") return false;
  if(t.strictFromLevel == null) return true;
  const idx = levelIndexMap(pack);
  const strictAt = idx[String(t.strictFromLevel)];
  if(strictAt === undefined) return true;
  const at = idx[String(entry.lv)];
  return at === undefined ? true : at < strictAt;
}
// Accepts entry.w or any entry.alt (plus any `extra` surfaces, e.g. the literal form a
// cloze blank had in its sentence), compared after normalising both sides.
function acceptTyped(input, entry, pack, extra){
  const t = (pack && pack.typing) || {};
  const opts = { caseSensitive: !!t.caseSensitive, foldAccents: typingLenientFor(entry, pack) };
  const got = normalizeTyped(input, opts);
  if(!got) return false;
  const targets = [entry.w, ...(entry.alt||[]), ...(extra||[])];
  return targets.some(x => normalizeTyped(x, opts) === got);
}

// ------------------------------------------------------------------ sentences
const escapeRe = s => String(s).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
// Apostrophe variants treated as the same symbol when matching sentence text:
// ASCII ', right single quote, modifier letter apostrophe.
const APOS = String.fromCodePoint(39, 0x2019, 0x02bc);
const isApos = c => APOS.indexOf(c) >= 0;
// All occurrences of `surface` in `text`. spaced=true (default): whole-word,
// case-insensitive, apostrophe-variant-insensitive matches; a letter/mark/digit on
// either side disqualifies, except that an apostrophe-final surface ("l'") may run
// straight into the next word and an apostrophe-initial one may follow a letter.
// spaced=false (scripts written without spaces, e.g. Chinese): plain substring.
function findSurface(text, surface, spaced){
  const out = []; const t = String(text), s = String(surface||"");
  if(!s) return out;
  if(spaced === false){
    let i = t.indexOf(s);
    while(i >= 0){ out.push({ start:i, end:i+s.length, text:s }); i = t.indexOf(s, i + s.length); }
    return out;
  }
  const cps = [...s];
  const body = cps.map(c => isApos(c) ? `[${APOS}]` : escapeRe(c)).join("");
  const lb = isApos(cps[0]) ? "" : "(?<![\\p{L}\\p{M}\\p{N}])";
  const la = isApos(cps[cps.length-1]) ? "" : "(?![\\p{L}\\p{M}\\p{N}])";
  const re = new RegExp(lb + body + la, "giu");
  let m; while((m = re.exec(t))){ out.push({ start:m.index, end:m.index+m[0].length, text:m[0] }); }
  return out;
}
// Where word `entry` sits in sentence text. Every form (w and each alt) is searched;
// overlapping hits are one occurrence (e.g. alt "acqua" inside w "l'acqua"). Returns
// the widest hit when there is exactly one occurrence, else null: absent, or visible
// more than once (blanking one occurrence would leave the answer — or an alt form of
// it — in plain sight elsewhere).
function locateWord(sentence, entry, pack){
  const spaced = !pack || pack.spaced !== false;
  const forms = [...new Set([entry.w, ...(entry.alt||[])].filter(Boolean))];
  const hits = [];
  forms.forEach(f => findSurface(sentence.t, f, spaced).forEach(m => hits.push(m)));
  if(!hits.length) return null;
  hits.sort((a,b)=>a.start-b.start || b.end-a.end);
  const clusterEnd = hits[0].end;
  let best = hits[0], end = clusterEnd;
  for(const h of hits.slice(1)){
    if(h.start >= end) return null; // a second, separate occurrence
    end = Math.max(end, h.end);
    if(h.end - h.start > best.end - best.start) best = h;
  }
  return best;
}
// Every surface string a cloze blank must not cut into: all pack words' w/alt plus
// pack.compounds (multi-word or multi-glyph units that aren't drillable words, e.g.
// zh 这个). Cached per wordsById object.
const SURFACE_CACHE = new WeakMap();
function packSurfaces(wordsById, pack){
  let c = SURFACE_CACHE.get(wordsById);
  if(!c || c.pack !== pack){
    const set = new Set();
    Object.values(wordsById).forEach(w => [w.w, ...(w.alt||[])].forEach(x => { if(x) set.add(String(x)); }));
    ((pack && pack.compounds) || []).forEach(x => { if(x) set.add(String(x)); });
    c = { pack, list: [...set] };
    SURFACE_CACHE.set(wordsById, c);
  }
  return c.list;
}
// True if some longer pack surface containing match.text occurs in the sentence
// covering the match's position (为 inside 为什么, 这 inside 这个, per inside "per favore").
function spannedByLonger(sentence, match, wordsById, pack){
  const spaced = !pack || pack.spaced !== false;
  const inner = normKey(match.text);
  for(const s of packSurfaces(wordsById, pack)){
    if(s.length <= match.text.length || normKey(s).indexOf(inner) < 0) continue;
    for(const m of findSurface(sentence.t, s, spaced)){
      if(m.start <= match.start && m.end >= match.end) return true;
    }
  }
  return false;
}
// The blankable match for `entry` in `sentence`, or null (see locateWord and
// spannedByLonger). The one place both gap-candidate selection and the app's gap
// item use, so they can never disagree.
function gapMatch(sentence, entry, wordsById, pack){
  const m = locateWord(sentence, entry, pack);
  if(!m || spannedByLonger(sentence, m, wordsById, pack)) return null;
  return m;
}
// Indices into sentence.words that are legal cloze blanks: a known word at the
// sentence's own level, not a pack function word, not repeated in the sentence (by id),
// and with a gapMatch (visible exactly once, not inside a longer pack word/compound).
function gapCandidateIndices(sentence, wordsById, pack){
  const fw = new Set((pack && pack.functionWords) || []);
  const words = sentence.words || [];
  const counts = {}; words.forEach(w=>{ counts[w] = (counts[w]||0) + 1; });
  const out = [];
  words.forEach((id,i)=>{
    if(fw.has(id) || counts[id] > 1) return;
    const entry = wordsById[id];
    if(!entry || entry.lv !== sentence.lv) return;
    if(!gapMatch(sentence, entry, wordsById, pack)) return;
    out.push(i);
  });
  return out;
}
function blankSentence(sentence, match){
  const t = String(sentence.t);
  return { before: t.slice(0, match.start), after: t.slice(match.end), answer: match.text };
}
// Surface key that also folds apostrophe variants (l’anno = l'anno).
const surfKey = s => normKey(s).replace(/[\u2019\u02bc]/g, "'");
// A word's bare form. Pack convention: when `w` carries an article or clitic
// ("il gioco", "l'anno"), alt[0] is the bare lemma ("gioco", "anno"). alt[0] counts as
// the bare form only when it is a whole trailing token of `w` (after a space or an
// apostrophe), so alts that are other forms (il -> lo, bello -> bella) or longer
// elided forms (acqua -> l'acqua) never replace `w`.
function bareForm(e){
  const w = String((e && e.w) || ""), a0 = e && e.alt && e.alt[0];
  if(!a0 || a0.length >= w.length) return w;
  const cut = w.length - a0.length, sep = w[cut - 1] || "";
  return (surfKey(w.slice(cut)) === surfKey(a0) && (/\s/.test(sep) || isApos(sep))) ? String(a0) : w;
}
// MC options for a gap item. When the blank covers `w` itself, every option shows its
// `w`. When the sentence used another form (an alt: bare or inflected, e.g. "gioco" for
// "il gioco"), every option shows its bareForm instead, so article-carrying options never
// sit inside the sentence's own article context ("È un ____" offering "il padre").
// Returns { opts, a, byLabel } with byLabel mapping each label to its word.
function gapChoices(entry, match, pool, pack){
  const useBare = !!match && surfKey(match.text) !== surfKey(entry.w);
  const show = useBare ? bareForm : (e => e.w);
  const ds = wordOpts(entry, pool, show);
  const byLabel = {}; [entry, ...ds].forEach(e => { byLabel[show(e)] = e; });
  return { opts: [show(entry), ...ds.map(show)], a: show(entry), byLabel, bare: useBare };
}
// Up to n example sentences for `entry` (sentences whose `words` list its id), in pack
// order within tiers: sentences where `w` is visible as a whole token first, then ones
// where an alt is, then the rest (the headword isn't shown as written, e.g. inflected).
function exampleSentences(entry, sentences, pack, n){
  const spaced = !pack || pack.spaced !== false;
  const seen = s => findSurface(s.t, entry.w, spaced).length ? 0
    : (entry.alt||[]).some(a => a && findSurface(s.t, a, spaced).length) ? 1 : 2;
  const tiers = [[], [], []];
  (sentences||[]).forEach(s => { if((s.words||[]).indexOf(entry.id) >= 0) tiers[seen(s)].push(s); });
  return [...tiers[0], ...tiers[1], ...tiers[2]].slice(0, n);
}

// ------------------------------------------------------------------ placement
// Splits a word pool into placement buckets: bucketSpec = [[levelId, bucketCount], ...]
// (pack.placement). Each bucket covers a contiguous run of sets s0..s1 within its level.
function strata(pool, bucketSpec, setSize){
  const size = setSize || 10;
  const out = [];
  (bucketSpec||[]).forEach(([lv,nb])=>{
    const list = pool.filter(v=>v.lv===lv);
    const nsets = Math.ceil(list.length/size);
    const per = nsets/nb;
    for(let b=0;b<nb;b++){
      const s0 = Math.floor(b*per), s1 = Math.max(s0+1, Math.floor((b+1)*per));
      out.push({lv, s0, s1, words: list.slice(s0*size, s1*size)});
    }
  });
  return out;
}
// Items drawn per bucket: alternating 2 and 3 (16 buckets -> 40 items).
const placementItemCount = bucketIndex => bucketIndex%2===0 ? 2 : 3;

// Where placement stops, given per-bucket results res=[{r,n},...] in bucket order.
// Bucket i passes if the rolling window (it plus up to two predecessors) is >=75%
// correct AND bucket i itself has at least 1 right. Returns the first failing
// index, or null if every bucket passed.
function placementStopIndex(res){
  for(let i=0;i<res.length;i++){
    const lo = Math.max(0, i-2);
    let wr = 0, wn = 0;
    for(let j=lo;j<=i;j++){ wr += res[j].r; wn += res[j].n; }
    const windowAcc = wn ? wr/wn : 1;
    if(!(windowAcc >= 0.75 && res[i].r >= 1)) return i;
  }
  return null;
}

// Applies a finished placement to progress (returns a new object; input untouched).
// passed = number of leading buckets passed. Placement only ever moves a learner
// forward: each level's counter becomes max(existing, furthest passed bucket end),
// and no existing word record is removed or downgraded (learned, mastered and
// drilled-ahead state all survive a poor retake). Levels before the first placement
// level count as fully known once anything passed. Words newly covered and without a
// record are seeded provisional; provisional flags are only ever added.
function applyPlacement(prog, st, passed, words, pack){
  const out = Object.assign({}, prog, { w: {} });
  Object.keys(prog.w||{}).forEach(k => { out.w[k] = Object.assign({}, prog.w[k]); });
  out.sets = Object.assign({}, defaultProg(pack).sets, prog.sets||{});
  for(let i=0;i<passed;i++){ const b = st[i]; out.sets[b.lv] = Math.max(out.sets[b.lv]||0, b.s1); }
  const ids = levelIds(pack), byLv = wordsByLevel(words, pack), size = setSizeOf(pack);
  const firstIdx = ids.indexOf(String(((pack.placement||[])[0]||[])[0]));
  if(passed > 0 && firstIdx > 0) ids.slice(0, firstIdx).forEach(lv => { out.sets[lv] = Math.max(out.sets[lv]||0, nSets(byLv[lv], size)); });
  learnedWords(words, pack, out).forEach(w => { if(!out.w[w.id]) out.w[w.id] = {r:1,w:0,s:1,prov:1}; });
  out.placedOnce = true;
  return out;
}

// Groups a drill's missed items by their `key` (one word or sentence, whatever
// question type it was missed as), keeping the first item seen as the representative.
// Returns [{item, count}] ordered by count desc, then first-miss order.
function dedupeMisses(miss){
  const by = new Map();
  (miss||[]).forEach((m, i) => {
    const k = m.key != null ? m.key : `#${i}`;
    const e = by.get(k);
    if(e) e.count++; else by.set(k, { item: m, count: 1, order: by.size });
  });
  return [...by.values()].sort((a,b)=>b.count-a.count || a.order-b.order).map(({item, count})=>({item, count}));
}

// ------------------------------------------------------------------ progress
const PROG_VERSION = 1;
const WORD_MASTERED = 3;      // word streak for "mastered"
const SENTENCE_MASTERED = 2;  // sentences draw on several known words at once: lower bar
function storageKey(pack){ return `vocab_${pack.key}`; }
function defaultProg(pack){
  const sets = {}; levelIds(pack).forEach(id=>{ sets[id] = 0; });
  return { v:PROG_VERSION, w:{}, s:{}, sets, lessons:{}, sessions:0, theme:null, showPron: pack.showPron !== false, placedOnce:false };
}
const isObj = x => !!x && typeof x === "object" && !Array.isArray(x);
function validateRecMap(m, name, allowWordFlags){
  if(!isObj(m)) return `${name} must be an object`;
  for(const k of Object.keys(m)){
    const p = m[k];
    if(!isObj(p)) return `${name}.${k} must be an object`;
    for(const f of ["r","w","s"]) if(p[f] !== undefined && typeof p[f] !== "number") return `${name}.${k}.${f} must be a number`;
    if(allowWordFlags){
      for(const f of ["prov","d"]) if(p[f] !== undefined && typeof p[f] !== "number" && typeof p[f] !== "boolean") return `${name}.${k}.${f} must be a number or boolean`;
    }
  }
  return null;
}
// Validates imported progress JSON before it replaces the live object.
// levelIdList: the pack's level ids (sets keys must be among them).
// Returns {ok:true, data} or {ok:false, reason}.
function validateProgShape(data, levelIdList){
  if(!isObj(data)) return {ok:false, reason:"not a JSON object"};
  if(data.v !== undefined && data.v !== PROG_VERSION) return {ok:false, reason:`unknown progress version ${data.v}`};
  for(const b of ["w","s"]){
    if(data[b] === undefined) continue;
    const e = validateRecMap(data[b], b, b === "w"); if(e) return {ok:false, reason:e};
  }
  if(data.sets !== undefined){
    if(!isObj(data.sets)) return {ok:false, reason:"sets must be an object"};
    const allowed = new Set((levelIdList||[]).map(String));
    for(const k of Object.keys(data.sets)){
      if(!allowed.has(k)) return {ok:false, reason:`sets has unknown level "${k}"`};
      if(!Number.isInteger(data.sets[k]) || data.sets[k] < 0) return {ok:false, reason:`sets.${k} must be a non-negative integer`};
    }
  }
  if(data.lessons !== undefined && !isObj(data.lessons)) return {ok:false, reason:"lessons must be an object"};
  if(data.sessions !== undefined && typeof data.sessions !== "number") return {ok:false, reason:"sessions must be a number"};
  if(data.showPron !== undefined && typeof data.showPron !== "boolean") return {ok:false, reason:"showPron must be a boolean"};
  if(data.placedOnce !== undefined && typeof data.placedOnce !== "boolean" && typeof data.placedOnce !== "number") return {ok:false, reason:"placedOnce must be a boolean or number"};
  if(data.soundsOpened !== undefined && typeof data.soundsOpened !== "boolean" && typeof data.soundsOpened !== "number") return {ok:false, reason:"soundsOpened must be a boolean or number"};
  if(data.theme !== undefined && data.theme !== null && data.theme !== "light" && data.theme !== "dark") return {ok:false, reason:"theme must be null, \"light\" or \"dark\""};
  return {ok:true, data};
}
// Fills every missing field of validated (or stored) progress from the pack's
// defaults, and gives every pack level a sets counter. Fields present are kept.
function normalizeProg(data, pack){
  const base = defaultProg(pack);
  const merged = Object.assign({}, base, data||{}, {v:PROG_VERSION});
  merged.sets = Object.assign({}, base.sets, (data && data.sets) || {});
  for(const k of ["w","s","lessons"]) if(!isObj(merged[k])) merged[k] = {};
  return merged;
}
// Parses a stored/imported progress string. Only a JSON object is progress;
// arrays, strings, numbers, null are rejected rather than Object.assign'ed.
function parseStored(raw){
  let data;
  try{ data = JSON.parse(raw); }catch(e){ return {ok:false, reason:"not valid JSON"}; }
  if(!isObj(data)) return {ok:false, reason:"not a JSON object"};
  return {ok:true, data};
}
// Boot-time leniency: a pack that renamed/removed a level must not wipe everything
// else. Drops `sets` keys that aren't current pack levels (reported in `dropped`),
// leaving the rest for strict validation. Manual import stays strict.
function dropUnknownSets(data, levelIdList){
  const allowed = new Set((levelIdList||[]).map(String));
  if(!isObj(data) || !isObj(data.sets)) return { data, dropped: [] };
  const dropped = Object.keys(data.sets).filter(k=>!allowed.has(k));
  if(!dropped.length) return { data, dropped };
  const sets = {}; Object.keys(data.sets).forEach(k=>{ if(allowed.has(k)) sets[k] = data.sets[k]; });
  return { data: Object.assign({}, data, { sets }), dropped };
}
// Decides boot progress from the raw stored string (null = nothing stored).
// Returns {prog, backupRaw, dropped, reason}: backupRaw non-null means the stored
// value was unusable and must be preserved under the invalid-backup key before the
// defaults replace it on the next save.
// readError: the storage backend threw on read. Nothing is known about what is stored,
// so the session runs read-only (defaults, never saved) rather than risk a save
// clobbering real progress that merely failed to load.
function bootProg(raw, pack, readError){
  const out = { prog: defaultProg(pack), backupRaw: null, dropped: [], reason: null, readOnly: false };
  if(readError){ out.readOnly = true; out.reason = "storage read failed"; return out; }
  if(raw == null || raw === "") return out;
  const p = parseStored(raw);
  if(!p.ok){ out.backupRaw = String(raw); out.reason = p.reason; return out; }
  const d = dropUnknownSets(p.data, levelIds(pack));
  const v = validateProgShape(d.data, levelIds(pack));
  if(!v.ok){ out.backupRaw = String(raw); out.reason = v.reason; return out; }
  out.dropped = d.dropped;
  out.prog = normalizeProg(d.data, pack);
  return out;
}
// Manual import (strict). prev = current progress: its theme/showPron survive when
// the import doesn't carry them. Returns {ok, prog} or {ok:false, reason}.
function applyImport(prev, text, pack){
  const p = parseStored(text);
  if(!p.ok) return p;
  const v = validateProgShape(p.data, levelIds(pack));
  if(!v.ok) return v;
  const prog = normalizeProg(v.data, pack);
  if(v.data.theme === undefined) prog.theme = prev ? prev.theme : null;
  if(v.data.showPron === undefined && prev && prev.showPron !== undefined) prog.showPron = prev.showPron;
  return {ok:true, prog};
}
function markRec(map, key, ok, isWord){
  const p = map[key] || {r:0,w:0,s:0};
  if(ok){ p.r++; p.s++; } else { p.w++; p.s=0; }
  if(isWord && p.prov && (p.s>=WORD_MASTERED || !ok)) delete p.prov;
  map[key] = p; return p;
}
const weakScore = rec => { const p = rec || {r:0,w:0,s:0}; return (p.w||0)*3 - (p.s||0); };
// Weakest first with jitter (ties and near-ties shuffle so reviews don't repeat).
function weakFirst(list, n, recs, keyOf, rng){
  const r = rng || Math.random; const key = keyOf || (x=>x.id);
  return list.map(x=>({x, k: weakScore((recs||{})[key(x)]) + (r()-0.5)})).sort((a,b)=>b.k-a.k).slice(0,n).map(o=>o.x);
}
function provPick(list, n, wrecs){
  return shuffle(list.filter(x=>{ const p = (wrecs||{})[x.id]; return p && p.prov && (p.s||0) < WORD_MASTERED; })).slice(0,n);
}

// Words from completed sets (per level, in pack order), plus any word flagged `d`
// (drilled ahead of its set from the Words tab).
function learnedWords(words, pack, prog){
  const size = setSizeOf(pack); const byLv = wordsByLevel(words, pack);
  const out = [];
  levelIds(pack).forEach(lv=>{ out.push(...byLv[lv].slice(0, ((prog.sets||{})[lv]||0)*size)); });
  const seen = new Set(out.map(w=>w.id));
  (words||[]).forEach(v=>{ if(!seen.has(v.id) && prog.w[v.id] && prog.w[v.id].d){ out.push(v); seen.add(v.id); } });
  return out;
}
// Next unlearned set, iterating levels in pack order: {lv, set} or null.
function nextNewSet(words, pack, prog){
  const size = setSizeOf(pack); const byLv = wordsByLevel(words, pack);
  for(const lv of levelIds(pack)){
    const done = (prog.sets||{})[lv]||0;
    if(done < nSets(byLv[lv], size)) return {lv, set: done};
  }
  return null;
}
// Index of the level nextNewSet() would teach from, or levels.length when all done.
function currentLevelIndex(words, pack, prog){
  const nn = nextNewSet(words, pack, prog);
  return nn ? levelIndexMap(pack)[nn.lv] : levelIds(pack).length;
}
// A sentence is available once every word id in it is learned, or once the learner
// has moved past the sentence's level entirely.
function availableSentences(sentences, words, pack, prog){
  const lw = new Set(learnedWords(words, pack, prog).map(w=>w.id));
  const cur = currentLevelIndex(words, pack, prog); const idx = levelIndexMap(pack);
  return (sentences||[]).filter(s => cur > idx[s.lv] || (s.words||[]).every(id=>lw.has(id)));
}

// ------------------------------------------------------------------ Today item plans
// Plans are [{kind, word}] (words) or [{kind, sentence}] — the app turns each into a
// drill item. Kept here, DOM-free, so composition rules are testable under Node.
const PRODUCTION_KINDS = ["recall","type"];
const REVIEW_SIZE = 15, REVIEW_PROV = 5, REVIEW_PRODUCTION_SHARE = 0.4;
// Assigns kinds to n slots: ceil(share*n) production (recall/type alternating when
// typing is on, else all recall), the rest receptive hear:read at 2:1.
function kindMix(n, share, typing, rng){
  const nProd = Math.ceil(n*share - 1e-9);
  const kinds = [];
  for(let i=0;i<nProd;i++) kinds.push(typing && i%2===1 ? "type" : "recall");
  for(let i=0;i<n-nProd;i++) kinds.push(i%3===2 ? "read" : "hear");
  return shuffle(kinds, rng);
}
// Review step: up to REVIEW_PROV provisional (placement-guessed) words plus the
// weakest learned words, REVIEW_SIZE total, >= REVIEW_PRODUCTION_SHARE production.
function buildReviewPlan(learned, prog, pack, opts){
  const o = opts || {}; const n = o.size || REVIEW_SIZE;
  const pv = provPick(learned, Math.min(REVIEW_PROV, n), prog.w);
  const pvSet = new Set(pv.map(w=>w.id));
  const rest = weakFirst(learned.filter(x=>!pvSet.has(x.id)), n - pv.length, prog.w, null, o.rng);
  const pool = shuffle([...rest, ...pv], o.rng);
  const kinds = kindMix(pool.length, REVIEW_PRODUCTION_SHARE, typingEnabled(pack), o.rng);
  return pool.map((word,i)=>({ kind: kinds[i], word }));
}
// Recall step: weakest n learned words, all production (recall/type mix).
function buildRecallPlan(learned, prog, pack, n){
  const pool = weakFirst(learned, n, prog.w);
  const kinds = kindMix(pool.length, 1, typingEnabled(pack));
  return pool.map((word,i)=>({ kind: kinds[i], word }));
}
// Sentence kind: hear 50 / read 25 / gap 25. Gap is "gapType" (type the blank) half
// the time when the pack has typing, else multiple choice.
function sentenceKind(pack, rng){
  const r = (rng || Math.random)();
  if(r < 0.5) return "hear";
  if(r < 0.75) return "read";
  return typingEnabled(pack) && (rng || Math.random)() < 0.5 ? "gapType" : "gap";
}

// ------------------------------------------------------------------ lessons
// Miss-dedupe key for a lesson item: its lesson id plus its index in lesson.items
// (question text is reused across items, so it can't be the key).
const lessonItemKey = (lessonId, index) => `l:${lessonId}#${index}`;
// How a lesson item with `say` (audio) runs when speech may be unavailable:
//   "audio"  speech works (or the item has no say): play it as authored
//   "inq"    no speech, but the question text already contains the say text: run as is
//   "text"   no speech: show the say text in place of the audio
//   "skip"   no speech, and the say text would give the answer away (contains it)
function lessonSayMode(item, speechOK){
  if(!item || !item.say || speechOK) return "audio";
  const say = normKey(item.say), q = normKey(item.q), a = normKey(item.a);
  if(q.indexOf(say) >= 0) return "inq";
  if(a && say.indexOf(a) >= 0) return "skip";
  return "text";
}

// Which Today steps run, given the learned-word count, whether a new set remains,
// and the available-sentence count. Shared by the Today plan table and the runner.
function todayGates(learnedCount, hasNextSet, availSentCount){
  return { review: learnedCount >= 5, learn: !!hasNextSet, listen: learnedCount >= 4, recall: learnedCount >= 4, sentences: availSentCount >= 8 };
}
// Test tab: free word tests need TEST_MIN_WORDS learned words; the sentence test needs
// 8 available sentences. The "learn first" notice depends on learned words only
// (placement itself needs no sentences); the sentence button simply stays hidden.
const TEST_MIN_WORDS = 8;
function testGates(learnedCount, availSentCount){
  const words = learnedCount >= TEST_MIN_WORDS, sentences = availSentCount >= 8;
  return { words, sentences, needPlacement: !words };
}

// ------------------------------------------------------------------ speech
const normLang = s => String(s||"").replace(/_/g,"-").toLowerCase();
// Best voice for a BCP-47 locale: exact locale, else same base language, else null.
function pickVoice(voices, lang){
  const want = normLang(lang), base = want.split("-")[0];
  const vs = voices || [];
  return vs.find(v=>normLang(v.lang)===want) || vs.find(v=>normLang(v.lang).split("-")[0]===base) || null;
}
// Whether listening items can play: needs the API, and — once the browser has
// reported its voice list — a voice for the pack's language (a zh word read by an
// English voice is worse than showing it). An empty list means "not loaded yet /
// unknown": optimistic, since some browsers never populate it but still speak.
function speechUsable(apiPresent, voices, lang){
  if(!apiPresent) return false;
  if(!voices || !voices.length) return true;
  return !!pickVoice(voices, lang);
}

// ------------------------------------------------------------------ audio
// One shared playback slot for recorded audio. play(url) pauses whatever the slot played
// last and reuses a single audio object (created once via make()), so repeated or
// duplicated taps can never stack parallel players or requests.
function audioSlot(make){
  let a = null;
  return {
    play(url){
      if(!a) a = make(); else { try{ a.pause(); }catch(e){} }
      a.src = url;
      return a;
    },
    stop(){ if(a){ try{ a.pause(); }catch(e){} } }
  };
}

// ------------------------------------------------------------------ export
const API = { shuffle, escapeHtml, gloss, firstTwoWords, normKey,
  levelIds, levelIndexMap, levelLabel, setSizeOf, wordsByLevel, nSets,
  meaningOpts, wordOpts, gapOpts, sentenceOpts, bareForm, gapChoices, exampleSentences, audioSlot, TEST_MIN_WORDS,
  foldAccents, normalizeTyped, typingEnabled, typingLenientFor, acceptTyped,
  surfaces, sharesSurface, samePron,
  findSurface, locateWord, packSurfaces, spannedByLonger, gapMatch, gapCandidateIndices, blankSentence,
  strata, placementItemCount, placementStopIndex, applyPlacement, dedupeMisses,
  parseStored, dropUnknownSets, bootProg, lessonItemKey, lessonSayMode, applyImport, todayGates, testGates, pickVoice, speechUsable,
  PROG_VERSION, WORD_MASTERED, SENTENCE_MASTERED, storageKey, defaultProg, validateProgShape, normalizeProg,
  markRec, weakScore, weakFirst, provPick, learnedWords, nextNewSet, currentLevelIndex, availableSentences,
  PRODUCTION_KINDS, REVIEW_SIZE, REVIEW_PRODUCTION_SHARE, kindMix, buildReviewPlan, buildRecallPlan, sentenceKind };
if(typeof module!=="undefined" && module.exports) module.exports = API;
if(root) root.VocabCore = API;
})(typeof window!=="undefined" ? window : (typeof globalThis!=="undefined" ? globalThis : null));
