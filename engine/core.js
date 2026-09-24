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
// pack (optional): word class. Distractors come from the answer's class: a content-word
// answer never gets a pack.functionWords distractor (a learner rules those out on sight,
// and in a cloze one may even fit the blank); a function-word answer prefers other
// function words, then falls back to content words.
// prefer (optional predicate): matching candidates come first, ahead of the tiers above
// (used by gapChoices for article agreement); the rest follow when fewer than 3 match.
function wordOpts(entry, pool, showOf, pack, prefer){
  const show = showOf || (e => e.w);
  const ansGloss = normKey(entry.en), ansF2 = firstTwoWords(entry.en);
  const hasPos = !!entry.pos;
  const fw = new Set((pack && pack.functionWords) || []);
  const ansFw = fw.has(entry.id);
  const cands = (pool||[]).filter(v =>
    v.id!==entry.id && !sharesSurface(v, entry) && normKey(v.en)!==ansGloss && !(ansF2 && firstTwoWords(v.en)===ansF2) &&
    (ansFw || !fw.has(v.id)));
  const samePos = v => hasPos && v.pos===entry.pos;
  const t1 = cands.filter(v=>v.lv===entry.lv && samePos(v));
  const t2 = cands.filter(v=>v.lv===entry.lv && !samePos(v));
  const t3 = cands.filter(v=>v.lv!==entry.lv && samePos(v));
  const t4 = cands.filter(v=>v.lv!==entry.lv && !samePos(v));
  const tiered = [...shuffle(t1), ...shuffle(t2), ...shuffle(t3), ...shuffle(t4)];
  const byClass = ansFw ? [...tiered.filter(v=>fw.has(v.id)), ...tiered.filter(v=>!fw.has(v.id))] : tiered;
  const ordered = prefer ? [...byClass.filter(v => prefer(v)), ...byClass.filter(v => !prefer(v))] : byClass;
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
// Accent folding (lenient typing, Words search). Rule: drop only marks that are optional
// accents, stress or vowel pointing for their script. A mark that makes a different
// letter is never dropped. Each precomposed code point is decomposed (NFD), its
// foldable marks removed, then recomposed (NFC), so a kept mark re-forms its letter.
// Per script (FOLD_SCRIPTS):
//  - Latin/Greek/Cyrillic combining diacritics: folded (é -> e, ñ -> n, stress о́ -> о,
//    ё -> е). Kept as letters: Cyrillic й, ї, ў (FOLD_KEEP).
//  - Arabic script: harakat, Quranic marks, superscript alef and tatweel folded. The
//    hamza marks U+0653-0655 are kept, so أ إ آ ؤ ئ ۀ never collapse to their base.
//  - Hebrew: niqqud and cantillation folded.
//  - Devanagari/Bengali etc.: nothing folded. Nukta (ज़ vs ज), virama and vowel signs
//    make distinct letters or syllables.
//  - Kana voicing marks (が vs か, ぱ vs は): never folded.
//  - ZWNJ/ZWJ: dropped (Persian می‌روم = میروم).
const FOLD_SCRIPTS = {
  latinGreekCyrillic: "\u0300-\u036f\u1ab0-\u1aff\u1dc0-\u1dff\u20d0-\u20ff\ufe20-\ufe2f",
  hebrew: "\u0591-\u05bd\u05bf\u05c1\u05c2\u05c4\u05c5\u05c7",
  arabic: "\u0610-\u061a\u064b-\u0652\u0656-\u065f\u0670\u06d6-\u06dc\u06df-\u06e4\u06e7\u06e8\u06ea-\u06ed\u0640",
  joiners: "\u200c\u200d",
};
const FOLD_MARKS = new RegExp("[" + Object.values(FOLD_SCRIPTS).join("") + "]", "g");
const FOLD_KEEP = new Set(["\u0439","\u0419","\u0457","\u0407","\u045e","\u040e"]); // й Й ї Ї ў Ў
function foldAccents(s){
  return String(s).normalize("NFC").replace(/[^\u0000-\u007f]/gu, c => FOLD_KEEP.has(c) ? c : c.normalize("NFD").replace(FOLD_MARKS, "").normalize("NFC"));
}
// Arabic-script keyboard variants that look alike and are typed interchangeably:
// Arabic kaf/yeh vs their Persian/Urdu forms. Always unified (both sides), like apostrophes.
// Deliberately NOT unified or folded: ة (teh marbuta) vs ه, and ى (alef maksura) vs ي/ی.
// These are distinct letters in Arabic spelling (على "on" vs علي "Ali"), not keyboard
// variants, so ي maps to Persian ی but ى stays its own letter.
const ARABIC_VARIANTS = { "\u0643":"\u06a9", "\u064a":"\u06cc" };
// opts: {caseSensitive, foldAccents}. Trims, collapses inner whitespace, unifies
// typographic apostrophes, casefolds unless caseSensitive, accent-folds if asked.
function normalizeTyped(s, opts){
  const o = opts || {};
  let out = String(s == null ? "" : s).normalize("NFC").replace(/[\u2018\u2019\u02bc`]/g, "'").replace(/[\u0643\u064a]/g, c => ARABIC_VARIANTS[c]).replace(/\s+/g, " ").trim();
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
// ZWNJ/ZWJ count as word-internal (Persian می‌روم is one word), so "می" never matches
// inside it. spaced=false (scripts written without spaces, e.g. Chinese): plain substring.
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
  const lb = isApos(cps[0]) ? "" : "(?<![\\p{L}\\p{M}\\p{N}\\u200c\\u200d])";
  const la = isApos(cps[cps.length-1]) ? "" : "(?![\\p{L}\\p{M}\\p{N}\\u200c\\u200d])";
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
// Design rule: the blank never includes an article. When the located form carries one
// ("l'église", "la iglesia", "Il conto", an alt like "l'acqua"), the article stays
// visible before the blank ("allons à l'____", "vamos a la ____") and the blank covers
// the bare rest (articleCut). Uniqueness and spannedByLonger are judged on the full hit.
// The bare form is searched too, so a "le/la médecin" with no alt is still found.
// Only pack articles are ever cut. A span that still starts with something its option
// label drops (a reflexive clitic: "se lever" labelled "lever"; an elided article the pack
// does not list) is not a legal blank: null. Returns {start, end, text, article}, where
// article is the pack article visible right before the blank ("la", "l'", "den"), or "".
function gapMatch(sentence, entry, wordsById, pack){
  const arts = packArticles(wordsById), bare = bareForm(entry, arts);
  const forms = [entry.w, ...(entry.alt||[])];
  const m = locateWord(sentence, forms.includes(bare) ? entry : Object.assign({}, entry, { alt: [...forms.slice(1), bare] }), pack);
  if(!m || spannedByLonger(sentence, m, wordsById, pack)) return null;
  const cut = articleCut(m.text, arts, entry), text = m.text.slice(cut);
  if(trailingCut(text, bare)) return null;
  const start = m.start + cut;
  return { start, end: m.end, text, article: visibleArticle(String(sentence.t).slice(0, start), arts, pack) };
}
// The article token ending `before` (the sentence text before a blank): an elided one
// ("l'", "dell'") or a word followed by whitespace, surf-keyed; "" unless it is a pack
// article or a key of the pack's article-agreement table (contractions: du, al, dem).
function visibleArticle(before, arts, pack){
  const m = before.match(/(\p{L}+['\u2019\u02bc])$/u) || before.match(/(\p{L}+)\s+$/u);
  if(!m) return "";
  const k = surfKey(m[1]);
  return (arts.has(k) || Object.prototype.hasOwnProperty.call(articleAgreement(pack), k)) ? k : "";
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
// The pack's articles: w and every alt of each pos "art" word (le/la/l'/les, el/la/los,
// il/lo/l'/gli, un/une...), surf-keyed. Built from the word list (array or id map) and
// cached per list object. Empty for packs without articles (zh), which disables every
// article rule below.
const ART_CACHE = new WeakMap();
function packArticles(words){
  if(!words || typeof words !== "object") return new Set();
  let set = ART_CACHE.get(words);
  if(!set){
    set = new Set();
    (Array.isArray(words) ? words : Object.values(words)).forEach(v => {
      if(v && v.pos === "art") [v.w, ...(v.alt||[])].forEach(a => { if(a) set.add(surfKey(a)); });
    });
    ART_CACHE.set(words, set);
  }
  return set;
}
// Length of a leading article in `text`: a pack article (or an a/b pair of them, as in
// "le/la médecin") followed by whitespace, or an elided article ending in an apostrophe
// ("l'église", "un'amica"). 0 when there is none, when the rest is itself an article
// ("l'un"), or, given `entry`, unless the word is a noun or its alt[0] is the rest: fixed
// expressions that start with an article-like word ("un peu", "les uns les autres",
// "tout le monde") are never cut.
const NOUN_POS = /^(noun|n|propn)$/i;
function articleCut(text, arts, entry){
  if(!arts || !arts.size) return 0;
  const t = String(text);
  const m = t.match(/^(\S+?)(\s+|(?<=['\u2019\u02bc]))(?=\S)/u);
  if(!m || !m[1].split("/").every(a => a && arts.has(surfKey(a)))) return 0;
  const rest = t.slice(m[0].length);
  if(arts.has(surfKey(rest))) return 0;
  if(entry){
    const a0 = entry.alt && entry.alt[0];
    if(!NOUN_POS.test(entry.pos || "") && !(a0 && surfKey(a0) === surfKey(rest))) return 0;
  }
  return m[0].length;
}
// Length of the prefix of `text` that leaves exactly `tail` as a whole trailing token
// (after a space or an apostrophe); 0 when `tail` is not such a token of `text`.
function trailingCut(text, tail){
  const t = String(text), b = String(tail || "");
  if(!b || b.length >= t.length) return 0;
  const cut = t.length - b.length, sep = t[cut - 1] || "";
  return (surfKey(t.slice(cut)) === surfKey(b) && (/\s/.test(sep) || isApos(sep))) ? cut : 0;
}
// A word's bare form (what gap options show). Pack convention: when `w` carries an
// article or clitic ("il gioco", "l'anno", "le/la médecin", "se lever"), alt[0] is the
// bare lemma. alt[0] counts as the bare form only when it is a whole trailing token of
// `w` (trailingCut), so alts that are other forms (il -> lo, bello -> bella) or longer
// elided forms (acqua -> l'acqua) never replace `w`. Otherwise, given the pack's
// articles (packArticles), a leading article is stripped from `w` (articleCut); else `w`.
function bareForm(e, arts){
  const w = String((e && e.w) || ""), a0 = e && e.alt && e.alt[0];
  if(a0 && trailingCut(w, a0)) return String(a0);
  const k = articleCut(w, arts, e);
  return k ? w.slice(k) : w;
}
// The articles a word is cited with: the parts of its leading article ("le/la médecin"
// -> ["le","la"]), surf-keyed; [] for a word without one.
// Cached per word object and article set.
const CIT_CACHE = new WeakMap();
function citationArticles(v, arts){
  if(!v || typeof v !== "object") return [];
  const hit = CIT_CACHE.get(v);
  if(hit && hit.arts === arts) return hit.list;
  const w = String(v.w || ""), k = articleCut(w, arts, v);
  const list = k ? w.slice(0, k).trim().split("/").map(surfKey) : [];
  CIT_CACHE.set(v, { arts, list });
  return list;
}
// Which citation articles each visible article agrees with, by language (targetLang).
// A visible article before a blank tells gender (la, die), elision (l') or case form
// (den, dem); distractors cited with an agreeing article are preferred so the article
// never gives the answer away. l' agrees with l' (either gender); plural and indefinite
// forms agree with every citation article they can stand for; German case forms map to
// their gender(s). pack.articleAgreement ({visible: [citation...]}) replaces the default;
// an article missing from the table agrees only with itself.
const ARTICLE_AGREEMENT = {
  fr: { le:["le"], la:["la"], "l'":["l'"], les:["le","la","l'"], un:["le","l'"], une:["la","l'"], du:["le"], au:["le"],
        des:["le","la","l'"], aux:["le","la","l'"] },
  es: { el:["el"], la:["la"], los:["el"], las:["la"], un:["el"], una:["la"], del:["el"], al:["el"] },
  it: { il:["il"], lo:["lo"], la:["la"], "l'":["l'"], i:["il"], gli:["lo","l'"], le:["la","l'"], un:["il","lo","l'"], uno:["lo"],
        una:["la"], "un'":["l'"],
        del:["il"], al:["il"], dal:["il"], nel:["il"], sul:["il"], dello:["lo"], allo:["lo"], dallo:["lo"], nello:["lo"], sullo:["lo"],
        della:["la"], alla:["la"], dalla:["la"], nella:["la"], sulla:["la"], "dell'":["l'"], "all'":["l'"], "dall'":["l'"], "nell'":["l'"], "sull'":["l'"],
        dei:["il"], ai:["il"], dai:["il"], nei:["il"], sui:["il"], degli:["lo","l'"], agli:["lo","l'"], dagli:["lo","l'"], negli:["lo","l'"], sugli:["lo","l'"],
        delle:["la","l'"], alle:["la","l'"], dalle:["la","l'"], nelle:["la","l'"], sulle:["la","l'"] },
  de: { der:["der","die"], die:["die"], das:["das"], den:["der"], dem:["der","das"], des:["der","das"], ein:["der","das"], eine:["die"],
        einen:["der"], einem:["der","das"], einer:["die"], eines:["der","das"], im:["der","das"], am:["der","das"], zum:["der","das"],
        zur:["die"], vom:["der","das"], beim:["der","das"], ins:["das"] },
};
function articleAgreement(pack){
  const own = pack && pack.articleAgreement;
  return (own && typeof own === "object") ? own : (ARTICLE_AGREEMENT[targetLang(pack)] || {});
}
// MC options for a gap item. Every option (answer and distractors) is shown by its
// bareForm, never with an article: the blank never includes the article (gapMatch), so
// an articled option would clash with the sentence ("le ____" offering "la loi") and a
// mix of bare and articled options would give the answer away. When an article is
// visible before the blank (match.article), distractors cited with an agreeing article
// come first (articleAgreement), so "la ____" offers other la-nouns; wordOpts falls back
// to the rest when fewer than 3 agree.
// Returns { opts, a, byLabel } with byLabel mapping each label to its word.
function gapChoices(entry, match, pool, pack){
  const arts = packArticles(pool);
  const show = e => bareForm(e, arts);
  const vis = match && match.article;
  let prefer = null;
  if(vis){
    const ok = new Set(articleAgreement(pack)[vis] || [vis]);
    prefer = v => citationArticles(v, arts).some(a => ok.has(a));
  }
  const ds = wordOpts(entry, pool, show, pack, prefer);
  const byLabel = {}; [entry, ...ds].forEach(e => { byLabel[show(e)] = e; });
  return { opts: [show(entry), ...ds.map(show)], a: show(entry), byLabel };
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
// Example-sentence highlighting: splits sentence text into [{text, hit}] segments where
// hit marks each place the taught word is visible. Every form (w and each alt) is
// searched as findSurface does for the pack; overlapping hits merge into one (the
// widest, e.g. "l'acqua" over "acqua"); a hit inside a longer pack word or compound
// (本 inside 日本, 为 inside 为什么) is dropped, as for cloze. Not visible anywhere:
// one segment, no hit. Joining every segment's text always gives back sentence.t.
function highlightParts(sentence, entry, wordsById, pack){
  const t = String((sentence && sentence.t) || "");
  const spaced = !pack || pack.spaced !== false;
  const forms = [...new Set([entry && entry.w, ...((entry && entry.alt) || [])].filter(Boolean))];
  const hits = [];
  forms.forEach(f => findSurface(t, f, spaced).forEach(m => hits.push(m)));
  hits.sort((a,b)=>a.start-b.start || b.end-a.end);
  const clusters = [];
  for(const h of hits){
    const c = clusters[clusters.length-1];
    if(c && h.start < c.end){ c.end = Math.max(c.end, h.end); if(h.end-h.start > c.best.end-c.best.start) c.best = h; }
    else clusters.push({ end: h.end, best: h });
  }
  const keep = clusters.map(c=>c.best).filter(m => !spannedByLonger({ t }, m, wordsById || {}, pack));
  const out = []; let at = 0;
  keep.forEach(m => { if(m.start > at) out.push({ text: t.slice(at, m.start), hit: false }); out.push({ text: t.slice(m.start, m.end), hit: true }); at = m.end; });
  if(at < t.length || !out.length) out.push({ text: t.slice(at), hit: false });
  return out;
}

// ------------------------------------------------------------------ pron display
// The pron worth showing next to x (a word or sentence): x.pron, or "" when it repeats
// the text itself (Russian "в" / "в"). Compared NFC, case-folded and trimmed. A pron that
// differs only by stress marks (де́лать for делать) is kept: the stress is the point.
function pronShown(x){
  const p = x && x.pron; if(!p) return "";
  const k = s => String(s == null ? "" : s).normalize("NFC").trim().toLowerCase();
  return k(p) === k(x.w != null ? x.w : x.t) ? "" : String(p);
}

// ------------------------------------------------------------------ Words search
// Words-tab search: a word matches when the query occurs in its w, any alt, its pron or
// its gloss, compared case-folded and accent-folded (foldAccents: Latin accents, stress
// marks, harakat, ZWNJ) on both sides. Whitespace is also ignored as a second chance, so
// "nihao" finds "nǐ hǎo" and "ni hao" finds "nihao". Ranking (stable, pack order within
// a tier): 0 = the query is the word itself (w, an alt or pron, whole), 1 = it is one
// whole gloss sense ("book" in "book, volume"), 2 = w/alt/pron starts with it, 3 = the
// rest. So "делать" lists делать before сделать.
// Folded search fields are computed once per word (SEARCH_CACHE, rebuilt if the word's
// text changes), so a keystroke only compares strings.
const SEARCH_CACHE = new WeakMap();
function searchFields(v){
  const src = [v.w, v.pron, v.en, ...(v.alt||[])].join("\u0001");
  let r = SEARCH_CACHE.get(v);
  if(r && r.src === src) return r;
  const norm = x => x ? normalizeTyped(x, { foldAccents: true }) : "";
  const pack = x => { const f = norm(x); return { f, ns: f.replace(/\s/g, "") }; };
  const target = [v.w, v.pron, ...(v.alt||[])].filter(Boolean).map(pack);
  const g = gloss(v);
  const senses = g.split(/[,;]/).flatMap(x => [x, x.replace(/^\s*to\s+/i, "")]).map(pack);
  r = { src, target, gloss: pack(g), senses };
  SEARCH_CACHE.set(v, r);
  return r;
}
function searchWords(words, query, limit){
  const q = normalizeTyped(query, { foldAccents: true }), qs = q.replace(/\s/g, "");
  if(!q) return [];
  const hit = x => x.f.includes(q) || (!!qs && x.ns.includes(qs));
  const same = x => x.f === q || (!!qs && x.ns === qs);
  const tiers = [[], [], [], []];
  (words||[]).forEach(v => {
    const r = searchFields(v);
    if(!(r.target.some(hit) || hit(r.gloss))) return;
    const t = r.target.some(same) ? 0 : r.senses.some(same) ? 1 : r.target.some(x => x.f.startsWith(q)) ? 2 : 3;
    tiers[t].push(v);
  });
  const out = [...tiers[0], ...tiers[1], ...tiers[2], ...tiers[3]];
  return limit ? out.slice(0, limit) : out;
}

// ------------------------------------------------------------------ script display
// How target-language text is marked up (docs/PACK_SCHEMA.md "Script display").
// lang: pack.langTag, else the language part of pack.tts ("fa-IR" -> "fa").
function targetLang(pack){
  const tag = pack && typeof pack.langTag === "string" && /^[A-Za-z]{2,8}(-[A-Za-z0-9]{1,8})*$/.test(pack.langTag) ? pack.langTag : "";
  return tag || (String((pack && pack.tts) || "").split(/[-_]/)[0].toLowerCase() || "und");
}
// pack.fontFamily is a CSS font-family list ('"Noto Nastaliq Urdu", serif'). Anything
// that could leave the declaration (; { } < > \ or a url()) is refused: null.
function fontFamilyOf(pack){
  const f = pack && typeof pack.fontFamily === "string" ? pack.fontFamily.trim() : "";
  if(!f || /[;{}<>\\]|url\s*\(|\/\*/i.test(f)) return null;
  return f;
}
// pack.lineHeight: unitless number 1..4, else null (the stylesheet's own line-heights).
function lineHeightOf(pack){
  const n = pack && pack.lineHeight;
  return (typeof n === "number" && isFinite(n) && n >= 1 && n <= 4) ? n : null;
}
// Google Fonts is the only external resource a page may load. pack.fonts lists family
// names, optionally with a css2 axis spec ("Noto Naskh Arabic:wght@400;700"). Returns
// {href, rejected}: href is a fonts.googleapis.com css2 URL (null when nothing valid),
// rejected lists entries that failed the name/axis pattern and were left out.
const FONT_NAME_RE = /^[A-Za-z0-9][A-Za-z0-9 ]{0,60}(:[a-z,]+@[0-9.,;]+)?$/;
function fontsHref(pack){
  const list = (pack && Array.isArray(pack.fonts)) ? pack.fonts : [];
  const ok = [], rejected = [];
  list.forEach(f => { (typeof f === "string" && FONT_NAME_RE.test(f.trim()) ? ok : rejected).push(f); });
  if(!ok.length) return { href: null, rejected };
  const fam = ok.map(f => "family=" + f.trim().replace(/ +/g, "+")).join("&");
  return { href: `https://fonts.googleapis.com/css2?${fam}&display=swap`, rejected };
}
// Everything the UI needs to mark target-language text: {lang, rtl, fontFamily, lineHeight}.
function scriptDisplay(pack){
  return { lang: targetLang(pack), rtl: !!(pack && pack.rtl === true), fontFamily: fontFamilyOf(pack), lineHeight: lineHeightOf(pack) };
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
  if(data.read !== undefined){ const e = validateReadShape(data.read); if(e) return {ok:false, reason:e}; }
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

// ------------------------------------------------------------------ reading passages
// Optional pack data (passages.json, docs/PACK_SCHEMA.md "passages.json"). A level's
// passages unlock once READ_UNLOCK of that level's words are learned; the unlock is
// stored in prog.read.unlocked so it survives later changes. Reading state lives in
// prog.read = { unlocked: {levelId: 1}, done: {passageId: {sc, n, d, x}} } and is absent
// until the learner first meets a passage, so older stored progress needs no migration.
const READ_UNLOCK = 0.7;
// Weights for "Weak words from this passage": misses added to prog.w[id].w.
const READ_WEIGHT = { tapped: 2, wrong: 2, reopened: 1 };
function readState(prog){
  if(!isObj(prog.read)) prog.read = {};
  if(!isObj(prog.read.unlocked)) prog.read.unlocked = {};
  if(!isObj(prog.read.done)) prog.read.done = {};
  return prog.read;
}
// Per pack level: {lv, total, learned, need, frac, met, unlocked, count}. count = passages
// at that level; need = learned words the threshold asks for (ceil(70% of total)).
function readingLevels(passages, words, pack, prog){
  const learned = learnedWords(words, pack, prog);
  const byLv = wordsByLevel(words, pack);
  const stored = (isObj(prog.read) && isObj(prog.read.unlocked)) ? prog.read.unlocked : {};
  return levelIds(pack).map(lv => {
    const total = byLv[lv].length, got = learned.filter(w => w.lv === lv).length;
    const need = Math.ceil(total * READ_UNLOCK - 1e-9);
    const met = total > 0 && got >= need;
    return { lv, total, learned: got, need, frac: total ? got/total : 0, met, unlocked: met || !!stored[lv],
      count: (passages||[]).filter(p => p.lv === lv).length };
  });
}
// Records newly met thresholds in prog.read.unlocked (sticky). Only levels that have
// passages are recorded. Returns the level ids unlocked by this call.
function updateReadUnlocks(passages, words, pack, prog){
  const fresh = readingLevels(passages, words, pack, prog).filter(l => l.met && l.count > 0 && !(isObj(prog.read) && isObj(prog.read.unlocked) && prog.read.unlocked[l.lv]));
  if(fresh.length){ const st = readState(prog); fresh.forEach(l => { st.unlocked[l.lv] = 1; }); }
  return fresh.map(l => l.lv);
}
// Today's suggestion: the first not-done passage in pack order at an unlocked level, or null.
function suggestPassage(passages, words, pack, prog){
  const open = new Set(readingLevels(passages, words, pack, prog).filter(l => l.unlocked).map(l => l.lv));
  const done = (isObj(prog.read) && isObj(prog.read.done)) ? prog.read.done : {};
  return (passages||[]).find(p => open.has(p.lv) && !done[p.id]) || null;
}
// Length in words: whitespace tokens for spaced scripts, linked word tokens otherwise.
function passageLength(p, pack){
  if(!pack || pack.spaced !== false) return String((p && p.text) || "").trim().split(/\s+/).filter(Boolean).length;
  return ((p && p.sentences) || []).reduce((n, s) => n + ((s.words || []).length), 0);
}
// Sentence text split into tappable pieces: [{text, id}] where id is the linked word
// found there (null for plain text), plus `unplaced`, the linked ids not visible in the
// text, which the UI lists under the sentence so every linked word stays tappable.
// Builder spans come first: s.spans = [[start, end, wordId]] (UTF-16 offsets into s.t,
// the token each word was read from, so inflected forms like mele or va are tappable).
// A span is used when its bounds are valid, it covers non-blank text without splitting a
// surrogate pair, its id is in s.words and known, and it does not overlap an earlier span. Ids in s.words with no span fall back to surface matching:
// w, every alt and its bare form, as findSurface does for the pack; overlapping hits keep
// the longest (per start, earliest first), so 为什么 wins over 为, and never cover a span.
// A pack without spans behaves exactly as before. Joining every piece's text gives s.t.
// True when UTF-16 index i falls between the two halves of a surrogate pair.
function splitsPair(t, i){ return i > 0 && i < t.length && t.codePointAt(i - 1) > 0xFFFF; }
function passageSegments(s, wordsById, pack){
  const t = String((s && s.t) || "");
  const spaced = !pack || pack.spaced !== false;
  const by = wordsById || {};
  const arts = packArticles(by);
  const ids = [...new Set((s && s.words) || [])];
  const idSet = new Set(ids);
  const keep = [], spanned = new Set();
  ((s && Array.isArray(s.spans)) ? s.spans : [])
    .filter(x => Array.isArray(x) && Number.isInteger(x[0]) && Number.isInteger(x[1]) && x[0] >= 0 && x[0] < x[1] && x[1] <= t.length && idSet.has(x[2]) && by[x[2]]
      && t.slice(x[0], x[1]).trim() && !splitsPair(t, x[0]) && !splitsPair(t, x[1]))
    .map(x => ({ start: x[0], end: x[1], id: x[2] }))
    .sort((a,b) => a.start - b.start)
    .forEach(h => { if(!keep.some(k => h.start < k.end && k.start < h.end)){ keep.push(h); spanned.add(h.id); } });
  const hits = [];
  ids.forEach(id => {
    const e = by[id]; if(!e || spanned.has(id)) return;
    const forms = [...new Set([e.w, ...(e.alt || []), bareForm(e, arts)].filter(Boolean))];
    forms.forEach(f => findSurface(t, f, spaced).forEach(m => hits.push({ start: m.start, end: m.end, id })));
  });
  hits.sort((a,b) => (b.end - b.start) - (a.end - a.start) || a.start - b.start);
  hits.forEach(h => { if(!keep.some(k => h.start < k.end && k.start < h.end)) keep.push(h); });
  keep.sort((a,b) => a.start - b.start);
  const parts = []; let at = 0;
  keep.forEach(h => { if(h.start > at) parts.push({ text: t.slice(at, h.start), id: null }); parts.push({ text: t.slice(h.start, h.end), id: h.id }); at = h.end; });
  if(at < t.length || !parts.length) parts.push({ text: t.slice(at), id: null });
  const placed = new Set(keep.map(h => h.id));
  return { parts, unplaced: ids.filter(id => !placed.has(id) && by[id]) };
}
// Grades one answer: mc = option index, tf = boolean. Anything else is wrong.
function gradeQuestion(q, answer){
  if(!q) return false;
  if(q.type === "tf") return typeof answer === "boolean" && answer === q.answer;
  return Number.isInteger(answer) && answer === q.answer;
}
// "Weak words from this passage". log = {tapped: [wordId], answers: [{ok, reopened}] by
// question index}. Tapped words and the words of wrongly answered questions weigh
// READ_WEIGHT.tapped / .wrong (2); the words of questions answered while the passage was
// reopened weigh .reopened (1). A word with several reasons takes the largest weight,
// never the sum. Order: tapped first (tap order), then question order. Returns
// [{id, weight, why: ["tapped"|"wrong"|"reopened"]}]; ids not in wordsById are dropped.
function passageWeakWords(passage, log, wordsById){
  const out = new Map();
  const add = (id, why) => {
    if(wordsById && !wordsById[id]) return;
    const e = out.get(id) || { id, weight: 0, why: [] };
    if(e.why.indexOf(why) < 0) e.why.push(why);
    e.weight = Math.max(e.weight, READ_WEIGHT[why]);
    out.set(id, e);
  };
  ((log && log.tapped) || []).forEach(id => add(id, "tapped"));
  const qs = (passage && passage.questions) || [];
  ((log && log.answers) || []).forEach((a, i) => {
    if(!a || !qs[i]) return;
    if(!a.ok) (qs[i].words || []).forEach(id => add(id, "wrong"));
    if(a.reopened) (qs[i].words || []).forEach(id => add(id, "reopened"));
  });
  return [...out.values()];
}
// Applies chosen weak words to progress in place: misses (rec.w) += weight, streak reset,
// provisional flag cleared, as a miss in markRec does, so weakScore ranks them first in
// the next review. A word not yet learned is flagged `d` (as a Words-tab drill ahead
// does), so learnedWords, and with it Today's review, includes it. Side effect, accepted:
// a `d` word counts as learned everywhere learnedWords is used, including the READ_UNLOCK
// threshold, exactly as a Words-tab drill-ahead does.
function applyWeakWords(prog, entries, words, pack){
  const learned = new Set(learnedWords(words, pack, prog).map(w => w.id));
  (entries || []).forEach(e => {
    if(!e || !(e.weight > 0)) return;
    const p = prog.w[e.id] || { r:0, w:0, s:0 };
    p.w = (p.w || 0) + e.weight; p.s = 0;
    if(p.prov) delete p.prov;
    if(!learned.has(e.id)) p.d = 1;
    prog.w[e.id] = p;
  });
  return prog;
}
// Records a finished passage: sc right of n questions on date d ("YYYY-MM-DD"); x counts
// attempts. The latest attempt's score is kept.
function markPassageDone(prog, pid, sc, n, d){
  const st = readState(prog); const prev = st.done[pid];
  st.done[pid] = { sc, n, d: String(d), x: ((prev && prev.x) || 0) + 1 };
  return st.done[pid];
}
// Progress tab: per level with passages {lv, total, done, avg} where avg is the mean
// latest score in percent over done passages (null when none).
function readingStats(passages, pack, prog){
  const done = (isObj(prog.read) && isObj(prog.read.done)) ? prog.read.done : {};
  return levelIds(pack).map(lv => {
    const ps = (passages||[]).filter(p => p.lv === lv);
    const d = ps.filter(p => done[p.id]).map(p => done[p.id]);
    const pct = d.filter(r => r.n > 0).map(r => r.sc / r.n * 100);
    return { lv, total: ps.length, done: d.length, avg: pct.length ? Math.round(pct.reduce((a,b)=>a+b,0) / pct.length) : null };
  }).filter(r => r.total > 0);
}
function validateReadShape(r){
  if(!isObj(r)) return "read must be an object";
  if(r.unlocked !== undefined){
    if(!isObj(r.unlocked)) return "read.unlocked must be an object";
    for(const k of Object.keys(r.unlocked)) if(typeof r.unlocked[k] !== "number" && typeof r.unlocked[k] !== "boolean") return `read.unlocked.${k} must be a number or boolean`;
  }
  if(r.done !== undefined){
    if(!isObj(r.done)) return "read.done must be an object";
    for(const k of Object.keys(r.done)){
      const p = r.done[k];
      if(!isObj(p)) return `read.done.${k} must be an object`;
      for(const f of ["sc","n","x"]) if(p[f] !== undefined && typeof p[f] !== "number") return `read.done.${k}.${f} must be a number`;
      if(p.d !== undefined && typeof p.d !== "string") return `read.done.${k}.d must be a string`;
    }
  }
  return null;
}

// ------------------------------------------------------------------ export
const API = { shuffle, escapeHtml, gloss, firstTwoWords, normKey,
  levelIds, levelIndexMap, levelLabel, setSizeOf, wordsByLevel, nSets,
  meaningOpts, wordOpts, gapOpts, sentenceOpts, bareForm, packArticles, articleCut, trailingCut, citationArticles, articleAgreement, visibleArticle, gapChoices, exampleSentences, highlightParts, searchWords, pronShown, audioSlot, TEST_MIN_WORDS,
  targetLang, fontFamilyOf, lineHeightOf, fontsHref, scriptDisplay,
  foldAccents, normalizeTyped, typingEnabled, typingLenientFor, acceptTyped,
  surfaces, sharesSurface, samePron,
  findSurface, locateWord, packSurfaces, spannedByLonger, gapMatch, gapCandidateIndices, blankSentence,
  strata, placementItemCount, placementStopIndex, applyPlacement, dedupeMisses,
  parseStored, dropUnknownSets, bootProg, lessonItemKey, lessonSayMode, applyImport, todayGates, testGates, pickVoice, speechUsable,
  PROG_VERSION, WORD_MASTERED, SENTENCE_MASTERED, storageKey, defaultProg, validateProgShape, normalizeProg,
  markRec, weakScore, weakFirst, provPick, learnedWords, nextNewSet, currentLevelIndex, availableSentences,
  PRODUCTION_KINDS, REVIEW_SIZE, REVIEW_PRODUCTION_SHARE, kindMix, buildReviewPlan, buildRecallPlan, sentenceKind,
  READ_UNLOCK, READ_WEIGHT, readState, readingLevels, updateReadUnlocks, suggestPassage, passageLength, passageSegments,
  gradeQuestion, passageWeakWords, applyWeakWords, markPassageDone, readingStats };
if(typeof module!=="undefined" && module.exports) module.exports = API;
if(root) root.VocabCore = API;
})(typeof window!=="undefined" ? window : (typeof globalThis!=="undefined" ? globalThis : null));
