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
  const pf = pronFirstOn(pack); // pron display: no option may sound like another (pronClash)
  const cands = (pool||[]).filter(v =>
    v.id!==entry.id && !sharesSurface(v, entry) && normKey(v.en)!==ansGloss && !(ansF2 && firstTwoWords(v.en)===ansF2) &&
    (ansFw || !fw.has(v.id)) && !(pf && pronClash(v, entry)));
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
    // With a label fn (showOf) the label is not the written form, so distractors must
    // also differ in every written surface: two same-w words with different labels
    // (homographs read differently) would otherwise both be picked as one written word.
    const chosen = []; const usedW = new Set([...surfaces(entry), normKey(show(entry))]); const usedF2 = new Set();
    for(const v of ordered){
      if(chosen.length>=3) break;
      const k = normKey(show(v)), f2 = firstTwoWords(v.en);
      if(usedW.has(k)) continue;
      if(showOf && surfaces(v).some(x => usedW.has(x))) continue;
      if(pf && chosen.some(c => pronClash(c, v))) continue;
      if(strict && f2 && usedF2.has(f2)) continue;
      chosen.push(v); usedW.add(k); if(showOf) surfaces(v).forEach(x => usedW.add(x)); if(f2) usedF2.add(f2);
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
// and with a gapMatch (visible exactly once, not inside a longer pack word/compound)
// that leaves some letter or digit outside the blank (a one-word sentence such as
// "不客气。" blanked whole is "____。", no cloze at all).
function gapCandidateIndices(sentence, wordsById, pack){
  const fw = new Set((pack && pack.functionWords) || []);
  const words = sentence.words || [];
  const counts = {}; words.forEach(w=>{ counts[w] = (counts[w]||0) + 1; });
  const out = [];
  words.forEach((id,i)=>{
    if(fw.has(id) || counts[id] > 1) return;
    const entry = wordsById[id];
    if(!entry || entry.lv !== sentence.lv) return;
    const m = gapMatch(sentence, entry, wordsById, pack);
    if(!m) return;
    const t = String(sentence.t || "");
    if(!/[\p{L}\p{N}]/u.test(t.slice(0, m.start) + t.slice(m.end))) return;
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
// Arabic script (ar/fa/ur): search is more lenient than typed-answer checking
// (normalizeTyped keeps ة/ى distinct there, on purpose). A search key also folds the
// letters learners routinely type without their marks or in a keyboard variant: hamza
// and madda on a carrier (أ إ آ ؤ ئ ۀ ۂ -> ا و ی ه ہ, by dropping U+0653..U+0655 after
// decomposition), alef wasla ٱ -> ا, teh marbuta ة -> ہ, alef maksura ى -> ی (ي is
// already ی). Harakat, tatweel and ZWNJ go in foldAccents; ي/ك -> ی/ک in normalizeTyped.
// Urdu spelling variants fold to the same canonical letter as Urdu heh goal (ہ): Arabic
// heh ه, Urdu teh marbuta goal ۃ, and the Arabic-preset heh+hamza ۀ. Do-chashmi heh ھ
// (a distinct phoneme, aspiration) is deliberately never folded into ہ. Urdu bari ye ے
// (almost always word-final) also folds to ی at a word boundary, so a masculine/feminine
// pair spelled with ے vs ی (بڑے/بڑی) search as one: a known, accepted tradeoff — an
// exact-glyph reveal still shows the pack's own spelling, only search is lenient.
// Anything without an Arabic-script letter is left exactly as normalizeTyped folds it.
// Order matters: stripping a carrier's hamza can expose a letter normalizeTyped already
// unified on the typed side (ئ = Arabic ي + hamza), so the keyboard-variant map
// (ARABIC_VARIANTS: ي -> ی, ك -> ک) is applied again last: one canonical yeh and kaf.
// ٲ ٳ ٵ / ٶ ٷ / ٸ (hamza/wavy-hamza letters with no canonical decomposition) map directly.
const AR_SEARCH_MAP = { "ٱ":"ا", "ٲ":"ا", "ٳ":"ا", "ٵ":"ا", "ٶ":"و", "ٷ":"و", "ٸ":"ی",
  "ة":"ہ", "ى":"ی", "ۀ":"ہ", "ۃ":"ہ", "ه":"ہ" };
// Devanagari (hi): search is more lenient than typed-answer checking (normalizeTyped
// leaves nukta and chandrabindu alone there — नुक्ता makes a distinct letter and ँ/ं are
// a real phonemic contrast for typed answers, on purpose). A search key folds nukta
// away (जरूर finds ज़रूर, लडका finds लड़का) — decomposing first (NFD) so a precomposed
// nukta letter (क़ ख़ ग़ ज़ ड़ ढ़ फ़ य़, U+0958-095F) is caught the same as a bare base+nukta
// pair — and unifies chandrabindu ँ into anusvara ं (हैँ finds हैं), a common informal
// spelling swap. ZWJ/ZWNJ are already dropped for every script by foldAccents.
function foldDevanagari(f){
  return f.normalize("NFD").replace(/़/g, "").replace(/ँ/g, "ं").normalize("NFC");
}
// A reduplicated or doubled-word query or entry ("dhīre dhīre", "धीरे धीरे", "kabhī
// kabhī") folds to its single token, so search treats a reduplicated spelling, its
// hyphenated form (already turned to a space above) and the bare word as one and the
// same phrase in both directions: the bare form is a substring of the doubled one either
// way once both are folded down to one token, and a doubled query still matches an entry
// stored bare. Consecutive identical whitespace-delimited tokens collapse to one; this
// runs after every script fold (so accents/nukta/Arabic variants are already unified and
// two spellings of "the same" token compare equal) and is a no-op for scripts written
// without spaces (zh/ja/ko han text has no tokens to collapse).
function foldReduplication(f){
  const parts = f.split(" ");
  const out = [];
  parts.forEach(p => { if(!out.length || out[out.length - 1] !== p) out.push(p); });
  return out.join(" ");
}
function searchFold(s){
  // Nasal tildes over a romanised vowel (kahā̃) are how this pack's roman pron marks
  // nasalisation; loose ASCII typing spells that with a trailing n (kahan), so convert
  // the combining tilde (U+0303) to a literal "n" before foldAccents would otherwise
  // just discard it. A hyphen is folded to a space so a reduplicated/hyphenated lemma
  // (धीरे-धीरे) and its unhyphenated spelling (धीरे धीरे) search as the same phrase.
  const pre = String(s == null ? "" : s).normalize("NFD").replace(/̃/g, "n").normalize("NFC").replace(/-/g, " ");
  let f = normalizeTyped(pre, { foldAccents: true });
  if(/[ऀ-ॿ]/.test(f)) f = foldDevanagari(f);
  if(/[؀-ۿ]/.test(f)){
    f = f.replace(/[ٱ-ٳٵ-ٸةىۀۃه]/g, c => AR_SEARCH_MAP[c]).normalize("NFD").replace(/[ٓ-ٕ]/g, "")
      .replace(/[كي]/g, c => ARABIC_VARIANTS[c]).replace(/ے(?=\s|$)/g, "ی").normalize("NFC");
  }
  return foldReduplication(f);
}
// The Arabic definite article: a word-initial ال before at least two more letters is
// optional in search (كتاب finds الكتاب, and الكتاب finds كتاب). Applied to folded text.
const stripArabicArticle = f => f.replace(/(^|\s)ال(?=\S{2,})/g, "$1");
// A field's search forms: the folded text and, when it differs, the article-free text;
// each with a whitespace-free copy (ns).
function searchForms(x){
  const f = x ? searchFold(x) : "";
  return [...new Set([f, stripArabicArticle(f)])].map(v => ({ f: v, ns: v.replace(/\s/g, "") }));
}
const SEARCH_CACHE = new WeakMap();
function searchFields(v){
  const src = [v.w, v.pron, v.en, ...(v.alt||[])].join("\u0001");
  let r = SEARCH_CACHE.get(v);
  if(r && r.src === src) return r;
  const target = [v.w, v.pron, ...(v.alt||[])].filter(Boolean).flatMap(searchForms);
  const g = gloss(v);
  const senses = g.split(/[,;]/).flatMap(x => [x, x.replace(/^\s*to\s+/i, "")]).flatMap(searchForms);
  r = { src, target, gloss: searchForms(g), senses };
  SEARCH_CACHE.set(v, r);
  return r;
}
function searchWords(words, query, limit){
  const qv = searchForms(query).filter(x => x.f).map(x => ({ q: x.f, qs: x.ns }));
  if(!qv.length) return [];
  const hit = x => qv.some(({ q, qs }) => x.f.includes(q) || (!!qs && x.ns.includes(qs)));
  const same = x => qv.some(({ q, qs }) => x.f === q || (!!qs && x.ns === qs));
  const starts = x => qv.some(({ q }) => x.f.startsWith(q));
  const tiers = [[], [], [], []];
  (words||[]).forEach(v => {
    const r = searchFields(v);
    if(!(r.target.some(hit) || r.gloss.some(hit))) return;
    const t = r.target.some(same) ? 0 : r.senses.some(same) ? 1 : r.target.some(starts) ? 2 : 3;
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
// The pack font stack the UI prepends to its own (--wfont = <this>, UI stack): the named
// families of fontFamilyOf with generic keywords (serif, sans-serif, ...) dropped, so a
// Latin run inside target text (pron, roman, a number) falls through to the UI font
// instead of a generic serif. null when no named family is left. The list is split on
// commas outside quotes, so a quoted family name holding a comma stays one family. The UI
// uses it for pack.rtl packs only; LTR packs keep fontFamily as given.
const GENERIC_FAMILY_RE = /^(serif|sans-serif|monospace|cursive|fantasy|system-ui|math|emoji|fangsong|ui-serif|ui-sans-serif|ui-monospace|ui-rounded)$/i;
function fontStackOf(pack){
  const f = fontFamilyOf(pack); if(!f) return null;
  const parts = []; let cur = "", q = "";
  for(const ch of f){
    if(q){ cur += ch; if(ch === q) q = ""; }
    else if(ch === '"' || ch === "'"){ cur += ch; q = ch; }
    else if(ch === ","){ parts.push(cur); cur = ""; }
    else cur += ch;
  }
  parts.push(cur);
  const named = parts.map(x => x.trim()).filter(x => x && !GENERIC_FAMILY_RE.test(x));
  return named.length ? named.join(", ") : null;
}
// Everything the UI needs to mark target-language text: {lang, rtl, fontFamily, fontStack, lineHeight}.
function scriptDisplay(pack){
  return { lang: targetLang(pack), rtl: !!(pack && pack.rtl === true), fontFamily: fontFamilyOf(pack), fontStack: fontStackOf(pack), lineHeight: lineHeightOf(pack) };
}
// RTL packs (docs/PACK_SCHEMA.md "RTL rendering"): a UI/English string (gloss, note,
// label) split into runs, each run of right-to-left script (Hebrew/Arabic blocks) flagged
// rtl, so the UI can isolate it in its own <bdi> and the English around it keeps its
// order. A run spans from an RTL letter to the last RTL letter reachable without crossing
// a strong-LTR letter: everything between (spaces, ZWNJ, "...", "…", "/", commas, digits,
// brackets) is neutral or weak and, as in the Unicode bidi algorithm, takes the
// direction of the RTL text on both sides, so a phrase such as "از ... متنفرم" or
// "کا/کی/کے" stays one run in its own order. Trailing neutrals (": I have)") stay
// outside. Joined, the runs' text is the input. [] for "" / null.
const RTL_CH = "\u0590-\u08FF\uFB1D-\uFDFF\uFE70-\uFEFF";
const RTL_RUN_RE = new RegExp(`[${RTL_CH}](?:(?:[${RTL_CH}]|[^\\p{L}\\p{M}])*[${RTL_CH}])?`, "gu");
function rtlRuns(s){
  const str = s == null ? "" : String(s), out = [];
  let i = 0, m; RTL_RUN_RE.lastIndex = 0;
  while((m = RTL_RUN_RE.exec(str))){
    if(m.index > i) out.push({ t: str.slice(i, m.index), rtl: false });
    out.push({ t: m[0], rtl: true }); i = m.index + m[0].length;
  }
  if(i < str.length) out.push({ t: str.slice(i), rtl: false });
  return out;
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
  const p = { v:PROG_VERSION, w:{}, s:{}, sets, lessons:{}, sessions:0, theme:null, showPron: pack.showPron !== false, placedOnce:false };
  if(charsConfig(pack)) p.chars = defaultCharsProg(); // absent without pack.characters: flag-off shape unchanged
  if(scriptConfig(pack)) p.script = defaultScriptProg(); // absent without pack.script: likewise
  return p;
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
  if(data.chars !== undefined){ const e = validateCharsShape(data.chars); if(e) return {ok:false, reason:e}; }
  if(data.script !== undefined){ const e = validateScriptShape(data.script); if(e) return {ok:false, reason:e}; }
  return {ok:true, data};
}
// Fills every missing field of validated (or stored) progress from the pack's
// defaults, and gives every pack level a sets counter. Fields present are kept.
function normalizeProg(data, pack){
  const base = defaultProg(pack);
  const merged = Object.assign({}, base, data||{}, {v:PROG_VERSION});
  merged.sets = Object.assign({}, base.sets, (data && data.sets) || {});
  for(const k of ["w","s","lessons"]) if(!isObj(merged[k])) merged[k] = {};
  if(charsConfig(pack)) merged.chars = normalizeCharsProg(data && data.chars);
  if(scriptConfig(pack)) merged.script = normalizeScriptProg(data && data.script, data);
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
  // The characters mix preference survives an import that doesn't carry it, like theme.
  if(prog.chars && !(isObj(v.data.chars) && v.data.chars.mix !== undefined) && prev && isObj(prev.chars) && typeof prev.chars.mix === "boolean") prog.chars.mix = prev.chars.mix;
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
// opts.units (optional): the pack's character units. When the pack has a characters
// block and some unit has a record, Review is unified (see unifiedReviewPlan); with no
// such unit the code below runs unchanged, so the output is identical to a word-only plan.
// opts.scriptCtx (optional): {byId | words, tts} for scriptKindFits, so a script unit
// never gets a kind with fewer than 4 options (the units are opts.script).
// opts.script (optional): the pack's script units (pack.script). Recorded ones join the
// same unified ranking as kind "x" (scriptReviewScore); none recorded, or the primer
// skipped, leaves the plan as above.
function buildReviewPlan(learned, prog, pack, opts){
  const o = opts || {}; const n = o.size || REVIEW_SIZE;
  const ru = recordedUnits(o.units, prog, pack);
  const rs = recordedScriptUnits(o.script, prog, pack);
  if(ru.length || rs.length) return unifiedReviewPlan(learned, ru, prog, pack, n, o.rng, rs, Object.assign({ units: o.script }, o.scriptCtx || {}));
  const pv = provPick(learned, Math.min(REVIEW_PROV, n), prog.w);
  const pvSet = new Set(pv.map(w=>w.id));
  const rest = weakFirst(learned.filter(x=>!pvSet.has(x.id)), n - pv.length, prog.w, null, o.rng);
  const pool = shuffle([...rest, ...pv], o.rng);
  const kinds = kindMix(pool.length, REVIEW_PRODUCTION_SHARE, typingEnabled(pack), o.rng);
  return pool.map((word,i)=>({ kind: kinds[i], word }));
}
// Recall step: weakest n learned words, all production (recall/type mix).
// opts.units / opts.rng: as buildReviewPlan. Recorded units join the same weakest-first
// ranking as charRecall items; with none the word-only code below runs unchanged.
function buildRecallPlan(learned, prog, pack, n, opts){
  const o = opts || {};
  const ru = recordedUnits(o.units, prog, pack);
  if(ru.length) return unifiedRecallPlan(learned, ru, prog, pack, n, o.rng);
  const pool = weakFirst(learned, n, prog.w);
  const kinds = kindMix(pool.length, 1, typingEnabled(pack));
  return pool.map((word,i)=>({ kind: kinds[i], word }));
}
// Sentence kind: hear 50 / read 25 / gap 25. Gap is "gapType" (type the blank) half
// the time when the pack types written words, else multiple choice. A pack that types
// the reading (typing "pron", pronTypingOn) never gets gapType: the blank is written.
function sentenceKind(pack, rng){
  const r = (rng || Math.random)();
  if(r < 0.5) return "hear";
  if(r < 0.75) return "read";
  return typingEnabled(pack) && !pronTypingOn(pack) && (rng || Math.random)() < 0.5 ? "gapType" : "gap";
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
// scriptCount (optional, pack.script): recorded script units; any opens Review, since a
// learner in the primer has no learned words yet.
function todayGates(learnedCount, hasNextSet, availSentCount, scriptCount){
  return { review: learnedCount >= 5 || (scriptCount || 0) > 0, learn: !!hasNextSet, listen: learnedCount >= 4, recall: learnedCount >= 4, sentences: availSentCount >= 8 };
}
// How many of the Listen step's 12 words will actually be served as a Listen item, so
// the Today plan line agrees with the session: app.html's hearItem() falls back to a
// Read item (canHearWord false — no TTS voice and no recorded clip for that word), so a
// word that can't be heard is not a Listen item even though the same 12 words are
// drilled either way. canHear(word) is the caller's canHearWord.
// Deliberately not weakFirst(learned, 12): app.html calls weakFirst(lw,12) with no recs,
// so its "weakest first" is really an unweighted jitter shuffle that draws from the
// global Math.random — calling it again here, purely to render a plan line, would burn
// extra draws on every Today render and shift every later shuffle/weakFirst call in the
// same session (the review/recall word picks, seeded-RNG test goldens, ...). A plain
// slice is just as representative a sample of the unweighted pool, with no such
// side effect.
function listenPlanCount(learned, canHear){
  return (learned || []).slice(0, 12).filter(canHear).length;
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
// Only getVoices() counts as evidence: an utterance with just a lang tag and no
// installed voice still fires onstart/onend on Android Chrome, silently.
function speechUsable(apiPresent, voices, lang){
  if(!apiPresent) return false;
  if(!voices || !voices.length) return true;
  return !!pickVoice(voices, lang);
}
// Samsung Internet on Android reports a voice via speechSynthesis for most
// languages but never actually plays audio through it, so speechUsable()
// (which only checks voice availability) misses it. Pure UA check, no pack
// involvement: shown regardless of hasSpeech, every visit, no dismiss —
// unlike the no-voice notice, the problem persists until the browser changes.
function isSamsungBrowser(ua){
  return /SamsungBrowser/i.test(String(ua||""));
}

// ------------------------------------------------------------------ audio
// Recorded clips (docs/AUDIO.md). wordAudio: a word's clip URL (words[].audio), or
// undefined. packAudio: whether pack.json declares shipped recordings (audio {voice,
// version}); the app then hides its no-voice notices. Both are false/undefined for every
// pack without the new fields, which is what keeps those packs byte-identical.
function wordAudio(w){
  return isObj(w) && typeof w.audio === "string" && w.audio ? w.audio : undefined;
}
function packAudio(pack){
  return isObj(pack) && isObj(pack.audio) && typeof pack.audio.voice === "string" && !!pack.audio.voice;
}
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
// A span may carry an optional 4th element, a display-only gloss string (zh: a phrase
// such as 越来越 "more and more", or a sense of the word shown on tap); its piece then
// has `gloss`, which the popover shows instead of the word's gloss. Pieces without one
// are unchanged.
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
    .map(x => (typeof x[3] === "string" && x[3].trim() ? { start: x[0], end: x[1], id: x[2], gloss: x[3] } : { start: x[0], end: x[1], id: x[2] }))
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
  keep.forEach(h => { if(h.start > at) parts.push({ text: t.slice(at, h.start), id: null }); parts.push(h.gloss ? { text: t.slice(h.start, h.end), id: h.id, gloss: h.gloss } : { text: t.slice(h.start, h.end), id: h.id }); at = h.end; });
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

// ------------------------------------------------------------------ characters
// Optional characters stage (design: the merge plan in docs/, §2-3). Nothing here runs for a pack
// without a `characters` block. A character unit is the written form of a known word:
// {id, t, words:[wordId,...], lv, reading?} (pack characters.js). words[0] supplies the
// gloss, the audio and the default reading. Progress lives in prog.chars =
// {v, c:{[unitId]:{r,w,s}}, defer, choiceSeen, mix}; scoring writes prog.chars.c only.
// Language-agnostic: the pack decides what a unit is (zh: every word, read by its pron;
// ja: words written with non-kana glyphs, read by their kana pron).
const CHARS_PROG_VERSION = 1;
const CHAR_SET_SIZE = 10, CHAR_MASTERED = 3, CHAR_BARE = 6;
const REVIEW_SIZE_CHARS = 20; // Review once characters have started (15 before)
const CHAR_KINDS = ["charRead","charSound","charPick","charRecall"];
const hasOwn = (o, k) => Object.prototype.hasOwnProperty.call(o, k);
const cpLen = s => [...String(s == null ? "" : s)].length;
// pack.characters with defaults filled, or null when the pack has none.
function charsConfig(pack){
  const c = pack && pack.characters;
  if(!isObj(c)) return null;
  const kinds = (k, d) => { const f = Array.isArray(k) ? k.filter(x => CHAR_KINDS.includes(x)) : []; return f.length ? f : d; };
  return {
    label: c.label != null ? String(c.label) : "",
    stages: (Array.isArray(c.stages) ? c.stages : []).filter(isObj)
      .map(st => ({ after: String(st.after), levels: (Array.isArray(st.levels) ? st.levels : []).map(String) })),
    setSize: Number.isInteger(c.setSize) && c.setSize > 0 ? c.setSize : CHAR_SET_SIZE,
    mastered: typeof c.mastered === "number" ? c.mastered : CHAR_MASTERED,
    bare: typeof c.bare === "number" ? c.bare : CHAR_BARE,
    learnKinds: kinds(c.learnKinds, ["charPick","charRead"]),
    reviewKinds: kinds(c.reviewKinds, ["charRead","charSound"]),
    testKinds: testKinds(c.testKinds),
    compose: c.compose === true,
  };
}
// pack.characters.testKinds: {kind: weight} for the Test tab's Characters N (the predecessor app's mix,
// charRead 40 / charSound 30 / charPick 30, by default). Unknown kinds and non-positive
// or non-finite weights are dropped; nothing left means the default.
const CHAR_TEST_KINDS = { charRead:40, charSound:30, charPick:30 };
// kinds/def (optional): the known kinds and default map (pack.script passes its own).
function testKinds(tk, kinds, def){
  const out = {};
  if(isObj(tk)) for(const k of (kinds || CHAR_KINDS)) if(typeof tk[k] === "number" && isFinite(tk[k]) && tk[k] > 0) out[k] = tk[k];
  return Object.keys(out).length ? out : Object.assign({}, def || CHAR_TEST_KINDS);
}
// One kind drawn from a {kind: weight} map (rng in [0, 1)).
function pickWeighted(weights, rng){
  const ks = Object.keys(weights); const total = ks.reduce((a, k) => a + weights[k], 0);
  let x = (rng || Math.random)() * total;
  for(const k of ks){ x -= weights[k]; if(x < 0) return k; }
  return ks[ks.length - 1];
}

// ---- progress (prog.chars)
function defaultCharsProg(){ return { v:CHARS_PROG_VERSION, c:{}, defer:false, choiceSeen:false, mix:true }; }
// Returns an error string or null. Validated whenever present, pack or no pack.
// chars.v is its own version: any positive integer is accepted and kept, so a newer
// chars shape never invalidates (and so resets) the whole progress record.
function validateCharsShape(ch){
  if(!isObj(ch)) return "chars must be an object";
  if(ch.v !== undefined && !(Number.isInteger(ch.v) && ch.v >= 1)) return "chars.v must be a positive integer";
  if(ch.c !== undefined){ const e = validateRecMap(ch.c, "chars.c", false); if(e) return e; }
  for(const f of ["defer","choiceSeen","mix"]) if(ch[f] !== undefined && typeof ch[f] !== "boolean") return `chars.${f} must be a boolean`;
  return null;
}
// Missing fields filled from defaults; fields present are kept.
function normalizeCharsProg(ch){
  const out = Object.assign(defaultCharsProg(), isObj(ch) ? ch : {});
  if(!isObj(out.c)) out.c = {};
  return out;
}
function ensureChars(prog){
  if(!isObj(prog.chars)) prog.chars = defaultCharsProg();
  if(!isObj(prog.chars.c)) prog.chars.c = {};
  return prog.chars;
}
function charRecs(prog){ return (prog && isObj(prog.chars) && isObj(prog.chars.c)) ? prog.chars.c : {}; }
const hasCharRec = (recs, id) => hasOwn(recs, id) && !!recs[id];
// Scores one character item (writes prog.chars.c only).
function markChar(prog, unitId, ok){ return markRec(ensureChars(prog).c, unitId, ok, false); }
// The one-time choice card: start characters now, or defer them past the later levels.
function answerCharChoice(prog, start){
  const ch = ensureChars(prog); ch.choiceSeen = true; if(!start) ch.defer = true; return prog;
}
// The reversible learning-order switch (Progress): flips the flag only. The path is
// re-derived from it; no record, set counter or choice state is touched.
function setCharOrder(prog, defer){ ensureChars(prog).defer = !!defer; return prog; }

// ---- units
function unitWord(unit, byId){ return (byId || {})[((unit && unit.words) || [])[0]] || null; }
function unitReading(unit, byId){
  if(unit && unit.reading != null && unit.reading !== "") return String(unit.reading);
  const w = unitWord(unit, byId); return w && w.pron ? String(w.pron) : "";
}
function unitGloss(unit, byId){ return gloss(unitWord(unit, byId)); }
// wordId -> the unit whose words[0] it is (the unit a sentence ruby token follows).
const UNIT_BY_WORD = new WeakMap();
function unitByWord(units){
  if(!Array.isArray(units)) return new Map();
  let m = UNIT_BY_WORD.get(units);
  if(!m){ m = new Map(); units.forEach(u => { const w = (u.words || [])[0]; if(w != null && !m.has(w)) m.set(w, u); }); UNIT_BY_WORD.set(units, m); }
  return m;
}
// Units with a character record: the pool unified Review and Recall draw from.
function recordedUnits(units, prog, pack){
  if(!charsConfig(pack) || !Array.isArray(units) || !units.length) return [];
  const recs = charRecs(prog);
  return units.filter(u => hasCharRec(recs, u.id));
}

// ---- stages and sets
// A stage's units: level order (pack order), then file order.
function charStageUnits(levels, units, pack){
  const want = new Set((levels || []).map(String)); const idx = levelIndexMap(pack);
  const at = lv => idx[lv] !== undefined ? idx[lv] : Infinity;
  return (units || []).map((u, i) => ({u, i})).filter(x => want.has(String(x.u.lv)))
    .sort((a, b) => (at(String(a.u.lv)) - at(String(b.u.lv))) || (a.i - b.i)).map(x => x.u);
}
function charSets(levels, units, pack){
  const cfg = charsConfig(pack); const size = cfg ? cfg.setSize : CHAR_SET_SIZE;
  const list = charStageUnits(levels, units, pack); const out = [];
  for(let i=0; i<list.length; i+=size) out.push(list.slice(i, i+size));
  return out;
}
// A set is taught once every unit in it has a record (no separate counter).
function charSetTaught(set, prog){ const r = charRecs(prog); return (set || []).every(u => hasCharRec(r, u.id)); }
// First untaught set of the stage: {index, units, total} or null.
function nextCharSet(levels, units, pack, prog){
  const sets = charSets(levels, units, pack);
  for(let i=0; i<sets.length; i++) if(!charSetTaught(sets[i], prog)) return { index:i, units:sets[i], total:sets.length };
  return null;
}
// Character stages in path order for this learner: the configured stages, or with
// prog.chars.defer one stage covering all their levels after the latest `after` level.
// A stage whose `after` is not a pack level sits after the last level.
// Each: {after, levels, label}. Later stages append their last level id to the label.
function charStages(pack, prog){
  const cfg = charsConfig(pack); if(!cfg || !cfg.stages.length) return [];
  const ids = levelIds(pack), idx = levelIndexMap(pack);
  if(!ids.length) return [];
  const pos = a => idx[a] !== undefined ? idx[a] : ids.length - 1;
  if(prog && isObj(prog.chars) && prog.chars.defer === true){
    const lv = new Set(); cfg.stages.forEach(st => st.levels.forEach(l => lv.add(l)));
    const levels = [...ids.filter(l => lv.has(l)), ...[...lv].filter(l => idx[l] === undefined)];
    return [{ after: ids[Math.max(...cfg.stages.map(st => pos(st.after)))], levels, label: cfg.label }];
  }
  return cfg.stages.map((st, i) => ({ after: ids[pos(st.after)], levels: st.levels,
    label: i === 0 ? cfg.label : cfg.label + (st.levels.length ? st.levels[st.levels.length-1] : "") }));
}
// Every stage in path order. Word stage: {kind:"words", lv, label, set, nsets, frac,
// done} (set = the level's sets counter, as nextNewSet reports it). Character stage:
// {kind:"chars", key, levels, label, recorded, nunits, nsets, frac, done}.
// Without pack.characters this is exactly the level strip: one word stage per level.
// sunits (optional, pack.script): the script units. With pack.script and the primer not
// skipped, one script stage per pack.script.stages entry comes first (scriptStages).
function stagePath(pack, words, units, prog, sunits){
  const p = prog || {}; const sets = p.sets || {};
  const size = setSizeOf(pack), byLv = wordsByLevel(words, pack), recs = charRecs(p);
  const cfg = charsConfig(pack); const cs = charStages(pack, p);
  const out = [];
  levelIds(pack).forEach(lv => {
    const n = nSets(byLv[lv], size), k = sets[lv] || 0;
    out.push({ kind:"words", lv, label: levelLabel(pack, lv), set: k, nsets: n, frac: n ? k/n : 1, done: k >= n });
    cs.filter(st => st.after === lv).forEach(st => {
      const list = charStageUnits(st.levels, units, pack);
      const rec = list.filter(u => hasCharRec(recs, u.id)).length;
      out.push({ kind:"chars", key: st.levels.join("+"), levels: st.levels, label: st.label, recorded: rec,
        nunits: list.length, nsets: Math.ceil(list.length / cfg.setSize), frac: list.length ? rec/list.length : 1, done: rec >= list.length });
    });
  });
  const sc = scriptStages(pack, sunits, p);
  return sc.length ? [...sc, ...out] : out;
}
function nextStage(pack, words, units, prog, sunits){ return stagePath(pack, words, units, prog, sunits).find(s => !s.done) || null; }
// Every level up to the first character stage's `after` is taught: the point the
// learning-order switch becomes available.
function charsUnlocked(pack, words, prog){
  const cfg = charsConfig(pack); if(!cfg || !cfg.stages.length) return false;
  const path = stagePath(pack, words, [], Object.assign({}, prog, { chars: Object.assign({}, (prog && prog.chars) || {}, { defer:false }) }));
  const first = path.findIndex(s => s.kind === "chars");
  return first > 0 && path.slice(0, first).every(s => s.done);
}
// Characters have started: any character record exists, or the current stage is a
// character stage. Gates every character surface outside the path strip.
function charsStarted(pack, words, units, prog, sunits){
  if(!charsConfig(pack)) return false;
  if(Object.keys(charRecs(prog)).length) return true;
  const st = nextStage(pack, words, units, prog, sunits);
  return !!(st && st.kind === "chars");
}
// The one-time choice card shows iff it is unanswered, the order is not deferred, every
// level before the first character stage is taught, that stage is incomplete (records
// elsewhere don't matter), and a later word level that deferring would put first (up to
// the latest stage's `after`) is still incomplete. Otherwise the choice changes nothing.
function showCharChoice(pack, words, units, prog, sunits){
  const cfg = charsConfig(pack); if(!cfg || !cfg.stages.length) return false;
  const ch = (prog && isObj(prog.chars)) ? prog.chars : {};
  if(ch.choiceSeen === true || ch.defer === true) return false;
  const path = stagePath(pack, words, units, prog, sunits);
  const first = path.findIndex(s => s.kind === "chars");
  if(first < 0 || path[first].done || !path.slice(0, first).every(s => s.done)) return false;
  const idx = levelIndexMap(pack), ids = levelIds(pack);
  const last = Math.max(...cfg.stages.map(st => idx[st.after] !== undefined ? idx[st.after] : ids.length - 1));
  return path.slice(first + 1).some(s => s.kind === "words" && idx[s.lv] <= last && !s.done);
}

// ---- tiers
// Streak -> tier: "pron" below mastered, "ruby" (written form with its reading above)
// from mastered, "bare" (written form alone) from bare.
function charTier(streak, pack){
  const cfg = charsConfig(pack); const s = +streak || 0;
  if(s >= (cfg ? cfg.bare : CHAR_BARE)) return "bare";
  if(s >= (cfg ? cfg.mastered : CHAR_MASTERED)) return "ruby";
  return "pron";
}
// Per sentence token: null (no mixing: the sentence renders as it does without
// characters) unless characters have started and the mix preference is on. Then "ruby"
// below bare and "bare" at or above it. Word-first packs show the written form from day
// one, so "pron" only exists for a pack.pronFirst pack (reading-only below mastered).
function sentenceTokenTier(streak, started, mix, pack){
  if(!started || !mix) return null;
  const t = charTier(streak, pack);
  return t === "pron" && !(pack && pack.pronFirst === true) ? "ruby" : t;
}
// sentence.ruby tokens with their tiers: [{start, end, reading, wordId, unitId, tier}],
// or null when the sentence has no ruby or mixing is off (see sentenceTokenTier).
// pack.pronFirst: tiers are always returned for a sentence with ruby (every token is
// "pron" before characters start or with mix off: the reading replaces the written form,
// as in the predecessor app's reading-only sentences), and follow sentenceTokenTier once
// characters have started with mix on.
function rubyTiers(sentence, units, prog, pack, started){
  const mix = !!(prog && isObj(prog.chars) && prog.chars.mix !== false);
  const pf = pronFirstOn(pack);
  if(!charsConfig(pack) || !sentence || !Array.isArray(sentence.ruby)) return null;
  if(!pf && (!started || !mix)) return null;
  const byWord = unitByWord(units), recs = charRecs(prog);
  return sentence.ruby.map(([start, end, reading, wordId]) => {
    const u = byWord.get(wordId) || null; const rec = u && hasCharRec(recs, u.id) ? recs[u.id] : null;
    const tier = pf && !(started && mix) ? "pron" : sentenceTokenTier(rec ? rec.s : 0, true, true, pack);
    return { start, end, reading, wordId, unitId: u ? u.id : null, tier };
  });
}

// ---- pronunciation-first (pack.pronFirst, docs/PACK_SCHEMA.md "pronFirst")
// On only for pack.pronFirst === true with a characters stage: a word whose unit is below
// the mastered tier is shown by its reading (pron) wherever its written form would appear
// outside the characters stage, which is where the written form is learned.
function pronFirstOn(pack){ return !!(pack && pack.pronFirst === true && charsConfig(pack)); }
// word -> {text, isPron, written}: text is what to display for the word, written its `w`.
// isPron when pronFirstOn, the word has a pron and a unit (unitByWord: the unit whose
// words[0] it is) and that unit's streak is below mastered (charTier "pron"). A word with
// no unit (kana/latin word) or no pron is shown as written. DOM-free, no side effects.
function displayForm(word, units, prog, pack){
  const written = String((word && word.w) || "");
  const out = { text: written, isPron: false, written };
  if(!word || !pronFirstOn(pack) || !word.pron) return out;
  const u = unitByWord(units).get(word.id);
  if(!u) return out;
  const recs = charRecs(prog); const rec = hasCharRec(recs, u.id) ? recs[u.id] : null;
  if(charTier(rec ? rec.s : 0, pack) !== "pron") return out;
  return { text: String(word.pron), isPron: true, written };
}
// What a learner hears/reads for a word under pron display: its pron, else its w.
const sayKey = e => normKey((e && (e.pron || e.w)) || "");
// Homophone guard for pron display: two words that sound the same (same pron, or one's
// written form is the other's reading, e.g. a word spelled in its reading and one read alike) are
// indistinguishable once both are shown by their reading.
function pronClash(a, b){ return !!(a && b) && sayKey(a) !== "" && sayKey(a) === sayKey(b); }

const LATIN_RE = /\p{Script=Latin}/u;
const HAN_RE = /\p{Script=Han}/u;
// Full-width punctuation next to a Latin-script reading, as the reading line writes it.
const ASCII_PUNCT = { "\uff0c":", ", "\u3001":", ", "\u3002":". ", "\uff01":"! ", "\uff1f":"? ", "\uff1a":": ", "\uff1b":"; ", "\uff08":" (", "\uff09":") ",
  "\u201c":" \u201c", "\u201d":"\u201d ", "\u2018":" \u2018", "\u2019":"\u2019 ", "\u300a":" \u201c", "\u300b":"\u201d ", "\u2026":"\u2026 ", "\u2014":" \u2014 " };
// Display pieces of a sentence under pron display, in order: ruby tokens (rubyTiers, or
// any [{start, end, tier, reading, wordId}] non-overlapping and sorted) and the text
// around them. A "pron"-tier token shows its reading instead of its written form.
// blank (optional {start, end}): that range, widened to every token it overlaps, becomes
// one {kind:"blank"} piece. cuts (optional offsets): text pieces are also split there
// (passage tap-span edges). When any shown reading is Latin script, adjacent
// tokens with a reading or blank between them are spaced (pre " ") and full-width punctuation
// touching a reading or blank is shown in ASCII form with a space; readings in a
// script written without spaces need neither. Piece: {kind:"text"|"tok"|"blank", start, end, text, pre, tier?, reading?,
// wordId?, unitId?}. Joining pre+text of every piece gives the displayed line.
function sentencePieces(sentence, toks, blank, cuts){
  const t = String((sentence && sentence.t) || "");
  const valid = []; let pos = 0;
  (toks || []).forEach(k => { if(k && k.start >= pos && k.end > k.start && k.end <= t.length){ valid.push(k); pos = k.end; } });
  let b = null;
  if(blank && blank.end > blank.start){
    b = { start: blank.start, end: blank.end };
    valid.forEach(k => { if(k.start < b.end && k.end > b.start){ b.start = Math.min(b.start, k.start); b.end = Math.max(b.end, k.end); } });
  }
  const cutSet = [...new Set(cuts || [])].sort((x, y) => x - y);
  const out = [];
  const text = (a, z) => {
    if(z <= a) return;
    const cs = [a, ...cutSet.filter(c => c > a && c < z), z];
    for(let i = 0; i < cs.length - 1; i++) out.push({ kind:"text", start: cs[i], end: cs[i+1], text: t.slice(cs[i], cs[i+1]), pre:"" });
  };
  const putBlank = () => { out.push({ kind:"blank", start: b.start, end: b.end, text:"____", pre:"" }); };
  pos = 0; let blankDone = !b;
  valid.forEach(k => {
    if(b && k.start < b.end && k.end > b.start) return;
    if(!blankDone && b.end <= k.start){ text(pos, b.start); putBlank(); pos = b.end; blankDone = true; }
    text(pos, k.start);
    const pr = k.tier === "pron";
    const piece = { kind:"tok", start: k.start, end: k.end, text: pr ? String(k.reading == null ? "" : k.reading) : t.slice(k.start, k.end), pre:"", tier: k.tier, reading: k.reading };
    if(k.wordId !== undefined) piece.wordId = k.wordId;
    if(k.unitId !== undefined) piece.unitId = k.unitId;
    out.push(piece); pos = k.end;
  });
  if(!blankDone){ text(pos, b.start); putBlank(); pos = b.end; }
  text(pos, t.length);
  const shown = p => (p.kind === "tok" && p.tier === "pron") || p.kind === "blank";
  if(!out.some(p => p.kind === "tok" && p.tier === "pron" && LATIN_RE.test(p.text))) return out;
  // Latin line: full-width punctuation in ASCII form; a reading or blank is spaced from
  // a neighbour that meets it with a letter or digit (a token, or text such as a name).
  const edgeL = p => p.kind !== "text" || /^[\p{L}\p{N}]/u.test(p.text);
  const edgeR = p => p.kind !== "text" || /[\p{L}\p{N}]$/u.test(p.text);
  out.forEach(p => { if(p.kind === "text") p.text = p.text.replace(/[\uff0c\u3001\u3002\uff01\uff1f\uff1a\uff1b\uff08\uff09\u201c\u201d\u2018\u2019\u300a\u300b\u2026\u2014]/g, c => ASCII_PUNCT[c]).replace(/\s+(?=[\u201d\u2019)\u2026,.!?:;])/g, ""); });
  // A reading that starts a sentence is capitalised: the first one when only opening
  // punctuation precedes it, the first after a sentence-internal . ! or ? (ba! Ni...), and
  // the first inside a quote opened after a colon (Ta shuo: "Ni..."). An ellipsis (…) stays
  // as written and starts nothing.
  let atStart = true;
  out.forEach(p => {
    if(p.kind === "tok" && p.tier === "pron"){ if(atStart) p.text = p.text.charAt(0).toUpperCase() + p.text.slice(1); atStart = false; }
    else if(p.kind !== "text") atStart = false;
    else if(/[.!?][\s"'\u201d\u2019)]*$/.test(p.text) || /:\s*["'\u201c\u2018(]+\s*$/.test(p.text)) atStart = true;
    else if(!/^[\s"'\u201c\u2018(]*$/.test(p.text)) atStart = false;
  });
  out.forEach((p, i) => { const prev = out[i-1]; if(prev && (shown(p) || shown(prev)) && edgeL(p) && edgeR(prev)) p.pre = " "; });
  // tidy: no doubled or edge spaces
  let last = "";
  out.forEach((p, i) => {
    if(/\s$/.test(last)){ p.pre = ""; p.text = p.text.replace(/^\s+/, ""); }
    if(i === 0){ p.pre = ""; p.text = p.text.replace(/^\s+/, ""); }
    p.text = p.text.replace(/\s{2,}/g, " ");
    last = p.pre + p.text || last;
  });
  for(let i = out.length - 1; i >= 0; i--){ const p = out[i]; if(p.kind === "text"){ p.text = p.text.replace(/\s+$/, ""); if(p.text) break; } else break; }
  return out;
}
// Whether ruby tokens ([{start, end}], UTF-16 offsets) cover every Han character of text t:
// the characters that need a reading to be shown with ruby. Kana, Latin letters, digits and
// punctuation are readable as written. sentenceDisplay shows a sentence with ruby only when
// this holds; unitExampleSentences prefers such sentences.
function rubyCovers(t, toks){
  const cov = new Array(t.length).fill(false);
  (toks || []).forEach(k => { for(let i = Math.max(0, k.start); i < Math.min(t.length, k.end); i++) cov[i] = true; });
  for(let i = 0; i < t.length; i++){ if(!cov[i]){ const cp = t.codePointAt(i); if(HAN_RE.test(String.fromCodePoint(cp))) return false; if(cp > 0xFFFF) i++; } }
  return true;
}
// A characters-stage teach card's examples for unit (its word `word`): exampleSentences'
// order within three tiers. First, sentences with a ruby token of the unit's own word
// (unit.words) whose ruby covers every Han character (rubyCovers): they can show the
// unit written with its reading, under pack.pronFirst too. Then sentences with the
// unit's token but uncovered characters, then the rest. Without pack.characters it is
// exampleSentences.
function unitExampleSentences(unit, word, sentences, pack, n){
  if(!word) return [];
  const all = exampleSentences(word, sentences, pack, Infinity);
  if(!charsConfig(pack)) return all.slice(0, n);
  const own = new Set((unit && unit.words) || []);
  const tiers = [[], [], []];
  all.forEach(s => {
    const r = Array.isArray(s.ruby) ? s.ruby.filter(Array.isArray) : [];
    const tk = r.map(k => ({ start: k[0], end: k[1] }));
    tiers[!r.some(k => own.has(k[3])) ? 2 : rubyCovers(String(s.t || ""), tk) ? 0 : 1].push(s);
  });
  return [...tiers[0], ...tiers[1], ...tiers[2]].slice(0, n);
}
// A sentence under pack.pronFirst: how to show it. null when pron display is off (the
// caller renders as without it). Else {mode, pieces?, text?}:
//  "pieces": ruby tokens by tier (sentencePieces), when every Han character of the text
//    lies inside a ruby token;
//  "pron": the sentence's own reading line (sentence.pron), when written characters
//    would otherwise show outside any token (a name, a word with no unit) or the sentence
//    has no ruby; never used for a blank (null then: the sentence cannot be a gap item);
//  "text": the text as is (it has no Han characters: kana or Latin only).
// written (optional, word ids): tokens of these words show at least the ruby tier (the
// written form with its reading): the unit a characters-stage teach card is teaching.
function sentenceDisplay(sentence, units, prog, pack, started, blank, written){
  if(!pronFirstOn(pack) || !sentence) return null;
  const t = String(sentence.t || "");
  const ws = new Set(written || []);
  const rt = rubyTiers(sentence, units, prog, pack, started);
  const toks = rt && rt.map(k => k.tier === "pron" && ws.has(k.wordId) ? Object.assign({}, k, { tier:"ruby" }) : k);
  if(toks && rubyCovers(t, toks)) return { mode:"pieces", pieces: sentencePieces(sentence, toks, blank) };
  if(!HAN_RE.test(t)) return { mode:"text" };
  if(blank) return null;
  return sentence.pron ? { mode:"pron", text: String(sentence.pron) } : { mode:"text" };
}

// ---- options
// Written-form distractors (charPick: reading+audio -> form; charRecall: meaning -> form).
// Up to 3 other units, never a second right answer: not the answer's form or any surface
// of its word, not the same reading (a homophone fits the pick stimulus), not the same
// gloss or first two gloss words (fits the recall stimulus). Pairwise distinct forms and
// glosses; a strict pass also keeps first-two-gloss-words distinct, relaxed for tiny pools.
// Preference: same level and form length, then same level, then any.
function charOpts(unit, units, byId){
  const aw = unitWord(unit, byId);
  const ansG = normKey(unitGloss(unit, byId)), ansF2 = firstTwoWords(unitGloss(unit, byId)), ansR = normKey(unitReading(unit, byId));
  const ansForms = new Set([normKey(unit.t), ...(aw ? surfaces(aw) : [])]);
  const len = cpLen(unit.t);
  const cands = (units || []).filter(v => {
    if(v.id === unit.id || ansForms.has(normKey(v.t))) return false;
    const g = unitGloss(v, byId), vw = unitWord(v, byId);
    if(normKey(g) === ansG || (ansF2 && firstTwoWords(g) === ansF2)) return false;
    if(ansR && normKey(unitReading(v, byId)) === ansR) return false;
    return !(aw && vw && samePron(aw, vw));
  });
  const t1 = cands.filter(v => v.lv === unit.lv && cpLen(v.t) === len);
  const t2 = cands.filter(v => v.lv === unit.lv && cpLen(v.t) !== len);
  const t3 = cands.filter(v => v.lv !== unit.lv);
  const ordered = [...shuffle(t1), ...shuffle(t2), ...shuffle(t3)];
  function pass(strict){
    const chosen = []; const usedT = new Set(ansForms), usedG = new Set([ansG]), usedF2 = new Set();
    for(const v of ordered){
      if(chosen.length >= 3) break;
      const t = normKey(v.t), g = unitGloss(v, byId), gk = normKey(g), f2 = firstTwoWords(g);
      if(usedT.has(t) || usedG.has(gk)) continue;
      if(strict && f2 && usedF2.has(f2)) continue;
      chosen.push(v); usedT.add(t); usedG.add(gk); if(f2) usedF2.add(f2);
    }
    return chosen;
  }
  let chosen = pass(true);
  if(chosen.length < 3) chosen = pass(false);
  return chosen;
}
// charRecall options: the answer's form plus the charOpts distractors' forms.
function recallCharOpts(unit, units, byId){ return [unit.t, ...charOpts(unit, units, byId).map(v => v.t)]; }
// Reading distractors for charSound (form -> reading): up to 3 readings of other units,
// never a homophone of the answer and never a reading the answer's form also has (a
// homograph unit or word with the same form). Pairwise distinct. Preference: same level
// and form length, then same form length, then same level, then any.
function charSoundOpts(unit, units, byId){
  const ansT = normKey(unit.t), ansR = normKey(unitReading(unit, byId));
  const forbid = new Set([ansR]);
  (units || []).forEach(v => { if(normKey(v.t) === ansT){ const r = normKey(unitReading(v, byId)); if(r) forbid.add(r); } });
  Object.keys(byId || {}).forEach(k => { const w = byId[k]; if(w && w.pron && surfaces(w).includes(ansT)) forbid.add(normKey(w.pron)); });
  const len = cpLen(unit.t);
  const cands = (units || []).filter(v => v.id !== unit.id && normKey(v.t) !== ansT && unitReading(v, byId) && !forbid.has(normKey(unitReading(v, byId))));
  const sameLen = v => cpLen(v.t) === len, sameLv = v => v.lv === unit.lv;
  const ordered = [...shuffle(cands.filter(v => sameLv(v) && sameLen(v))), ...shuffle(cands.filter(v => !sameLv(v) && sameLen(v))),
    ...shuffle(cands.filter(v => sameLv(v) && !sameLen(v))), ...shuffle(cands.filter(v => !sameLv(v) && !sameLen(v)))];
  const out = []; const used = new Set(forbid);
  for(const v of ordered){
    if(out.length >= 3) break;
    const r = unitReading(v, byId), k = normKey(r);
    if(used.has(k)) continue;
    used.add(k); out.push(r);
  }
  return out;
}
// Meaning distractors for charRead (form alone -> meaning): meaningOpts on the unit's
// word, with every word the form could also be read as removed from the pool.
function charReadOpts(unit, words, byId){
  const w = unitWord(unit, byId); if(!w) return [];
  const t = normKey(unit.t);
  return meaningOpts(w, (words || []).filter(v => v.id === w.id || !surfaces(v).includes(t)));
}
// One drill item for a unit, DOM-free: {kind, key, unitId, wordId, t, reading, gloss,
// show, audio, options, answer}. show is the stimulus field ("t", "reading" or "gloss");
// audio: play words[0]. options are shuffled strings that include answer.
// ctx: {units, words, byId?, rng?}.
function charItem(kind, unit, ctx){
  const c = ctx || {}; const byId = c.byId || Object.fromEntries((c.words || []).map(w => [w.id, w]));
  const w = unitWord(unit, byId), t = String(unit.t), reading = unitReading(unit, byId), g = unitGloss(unit, byId);
  const base = { kind, key: "c:" + unit.id, unitId: unit.id, wordId: w ? w.id : null, t, reading, gloss: g };
  let show, audio = false, answer, others;
  if(kind === "charRead"){ show = "t"; answer = g; others = charReadOpts(unit, c.words, byId).map(gloss); }
  else if(kind === "charSound"){ show = "t"; answer = reading; others = charSoundOpts(unit, c.units, byId); }
  else if(kind === "charPick"){ show = "reading"; audio = true; answer = t; others = charOpts(unit, c.units, byId).map(v => String(v.t)); }
  else if(kind === "charRecall"){ show = "gloss"; answer = t; others = charOpts(unit, c.units, byId).map(v => String(v.t)); }
  else throw new Error(`unknown character item kind ${kind}`);
  return Object.assign(base, { show, audio, answer, options: shuffle([answer, ...others], c.rng) });
}

// ---- plans
// Learn step for a character set: each unit gets one item per pack learnKinds, in order.
function learnCharPlan(set, pack){
  const cfg = charsConfig(pack); if(!cfg) return [];
  const out = []; (set || []).forEach(unit => cfg.learnKinds.forEach(kind => out.push({ kind, unit })));
  return out;
}
// Unified weakness score: words keep weakScore; an unmastered unit (s < mastered)
// scores at least 0, tying with never-drilled words so fresh units aren't starved by a
// large pool of unrecorded words. Mastered units keep w*3 - s.
function charReviewScore(rec, pack){
  const cfg = charsConfig(pack); const p = rec || {}; const sc = weakScore(p);
  return (p.s || 0) < (cfg ? cfg.mastered : CHAR_MASTERED) ? Math.max(sc, 0) : sc;
}
// One ranking over words and units: the n weakest as [{kind:"w"|"c"|"x", entry, score}],
// with weakFirst's jitter (below 1, so it only reorders equal scores). sunits/srecs
// (optional): script units and their records, kind "x" (scriptReviewScore).
function rankUnified(words, wrecs, units, crecs, n, pack, rng, sunits, srecs){
  const r = rng || Math.random;
  const pool = [...(words || []).map(e => ({ kind:"w", entry:e, score: weakScore((wrecs || {})[e.id]) })),
    ...(units || []).map(u => ({ kind:"c", entry:u, score: charReviewScore((crecs || {})[u.id], pack) })),
    ...(sunits || []).map(u => ({ kind:"x", entry:u, score: scriptReviewScore((srecs || {})[u.id], pack) }))];
  return pool.map(x => ({ x, k: x.score + (r() - 0.5) })).sort((a, b) => b.k - a.k).slice(0, n).map(o => o.x);
}
// Unified Review: provisional words as before, then the weakest words and recorded units
// under one ranking, n total. Word items keep the >= 40% production mix; each unit gets
// a random pack reviewKind. Items: {kind, word} or {kind, unit}. rs (optional): recorded
// script units; each gets a random pack.script reviewKind that fits it (pickScriptKind).
function unifiedReviewPlan(learned, ru, prog, pack, n, rng, rs, sctx){
  const cfg = charsConfig(pack), scfg = scriptConfig(pack); const r = rng || Math.random;
  const pv = provPick(learned, Math.min(REVIEW_PROV, n), prog.w);
  const pvSet = new Set(pv.map(w => w.id));
  const ranked = rankUnified(learned.filter(x => !pvSet.has(x.id)), prog.w, ru, charRecs(prog), n - pv.length, pack, rng, rs, scriptRecs(prog));
  const pool = shuffle([...ranked, ...pv.map(w => ({ kind:"w", entry:w }))], rng);
  const kinds = kindMix(pool.filter(x => x.kind === "w").length, REVIEW_PRODUCTION_SHARE, typingEnabled(pack), rng);
  let wi = 0;
  const out = pool.map(x => x.kind === "w" ? { kind: kinds[wi++], word: x.entry }
    : x.kind === "c" ? { kind: cfg.reviewKinds[Math.floor(r() * cfg.reviewKinds.length)], unit: x.entry }
    : { kind: pickScriptKind(scfg.reviewKinds, x.entry, scfg, r, sctx), unit: x.entry });
  return out.filter(it => it.kind);
}
// Unified Recall: the n weakest words and recorded units, weakest first; words as
// recall/type, units as charRecall.
function unifiedRecallPlan(learned, ru, prog, pack, n, rng){
  const ranked = rankUnified(learned, prog.w, ru, charRecs(prog), n, pack, rng);
  const kinds = kindMix(ranked.filter(x => x.kind === "w").length, 1, typingEnabled(pack), rng);
  let wi = 0;
  return ranked.map(x => x.kind === "w" ? { kind: kinds[wi++], word: x.entry } : { kind:"charRecall", unit: x.entry });
}
// Taken at "Start today" and kept for the whole session, so finishing a stage mid-session
// changes neither what Learn teaches nor Review/Recall's mode: {stage, cset, charsStarted,
// reviewSize, choice}. choice true means the choice card replaces Start today.
// Without pack.characters: the next word stage, cset null, charsStarted false, REVIEW_SIZE.
// sunits (optional, pack.script): the script units. With pack.script the snapshot also has
// ssets: the script sets Learn teaches (nextScriptSets, up to setsPerSession) while a
// script stage is next, else []; reviewSize is REVIEW_SIZE_SCRIPT then; and choice is
// "script" while the script choice card shows (it comes before the characters card).
function todaySnapshot(pack, words, units, prog, sunits){
  const stage = nextStage(pack, words, units, prog, sunits);
  const cset = stage && stage.kind === "chars" ? nextCharSet(stage.levels, units, pack, prog) : null;
  const started = charsStarted(pack, words, units, prog, sunits);
  const snap = { stage, cset, charsStarted: started, reviewSize: started ? REVIEW_SIZE_CHARS : REVIEW_SIZE, choice: showCharChoice(pack, words, units, prog, sunits) };
  const scfg = scriptActive(pack, sunits) ? scriptConfig(pack) : null; // no units: the flag-off snapshot
  if(scfg){
    const onScript = !!(stage && stage.kind === "script");
    snap.ssets = onScript ? nextScriptSets(stage.key, sunits, pack, prog, scfg.setsPerSession) : [];
    if(onScript) snap.reviewSize = REVIEW_SIZE_SCRIPT;
    if(showScriptChoice(pack, sunits, prog)) snap.choice = "script";
  }
  return snap;
}
// Learned words' units without a record, level order then file order, at most n.
function newCharUnits(units, learned, prog, pack, n){
  const ids = new Set((learned || []).map(w => w.id)); const recs = charRecs(prog);
  const ok = new Set((units || []).filter(u => ids.has((u.words || [])[0]) && !hasCharRec(recs, u.id)).map(u => u.id));
  return charStageUnits(levelIds(pack), (units || []).filter(u => ok.has(u.id)), pack).slice(0, n);
}
// Test tab's Characters N (the predecessor app's test): the n weakest recorded units,
// topped up to n with learned words' unrecorded units (newCharUnits: level order, then
// file order); each gets a kind drawn from pack.characters.testKinds. [{kind, unit}].
function charTestPlan(units, learned, prog, pack, n, rng){
  const cfg = charsConfig(pack); if(!cfg) return [];
  const rec = weakFirst(recordedUnits(units, prog, pack), n, charRecs(prog), undefined, rng);
  const pool = rec.length >= n ? rec : rec.concat(newCharUnits(units, learned, prog, pack, n - rec.length));
  return pool.map(unit => ({ kind: pickWeighted(cfg.testKinds, rng), unit }));
}

// ------------------------------------------------------------------ script primer
// Pack-gated (pack.script + pack/script.json, docs/SCRIPT_PRIMER.md, docs/PACK_SCHEMA.md
// "Script primer"): one stage per pack.script.stages entry, before the first word level,
// teaches a writing system symbol by symbol. A unit is one symbol (or a symbol in one
// role); `st` names its stage and `set` its teaching set. Progress lives in prog.script =
// {v, u:{[unitId]:{r,w,s}}, skipped, skip:{[stageKey]:bool}, choiceSeen, notice}; skipped
// switches the whole primer off, skip one stage. Scoring writes prog.script.u only. Taught, done and mastered are derived from records, never stored. Without
// pack.script every function here returns its empty value and nothing else changes.
// Item keys are "x:" + unitId (the character stage uses "c:"). All pure and DOM-free.
const SCRIPT_PROG_VERSION = 1;
const SCRIPT_MASTERED = 3, SCRIPT_SETS_PER_SESSION = 2, REVIEW_SIZE_SCRIPT = 12;
const SCRIPT_KINDS = ["symSound","soundSym","symType","compose","formFind","formMatch","wordRead","wordHear"];
const SCRIPT_SOUND_KINDS = ["symSound","soundSym","symType"]; // never asked of a sound:false unit
const SCRIPT_TEST_KINDS = { symSound:35, soundSym:25, wordRead:25, symType:15 };
const ZWJ = "‍";
// pack.script with defaults filled (known kinds only), or null when the pack has none.
// stages: [{key, label}] with unique non-empty keys, in path order.
function scriptConfig(pack){
  const c = pack && pack.script;
  if(!isObj(c)) return null;
  const kinds = (k, d) => { const f = Array.isArray(k) ? k.filter(x => SCRIPT_KINDS.includes(x)) : []; return f.length ? [...new Set(f)] : d; };
  const seen = new Set(); const stages = [];
  (Array.isArray(c.stages) ? c.stages : []).forEach(st => {
    if(!isObj(st) || typeof st.key !== "string" || !st.key || seen.has(st.key)) return;
    seen.add(st.key); stages.push({ key: st.key, label: st.label != null && st.label !== "" ? String(st.label) : st.key });
  });
  return {
    stages,
    setsPerSession: Number.isInteger(c.setsPerSession) && c.setsPerSession > 0 ? c.setsPerSession : SCRIPT_SETS_PER_SESSION,
    mastered: typeof c.mastered === "number" && c.mastered > 0 ? c.mastered : SCRIPT_MASTERED,
    tts: c.tts !== false,
    learnKinds: kinds(c.learnKinds, ["symSound","soundSym"]),
    reviewKinds: kinds(c.reviewKinds, ["symSound","soundSym","wordRead"]),
    testKinds: testKinds(c.testKinds, SCRIPT_KINDS, SCRIPT_TEST_KINDS),
  };
}

// ---- progress (prog.script)
function defaultScriptProg(){ return { v:SCRIPT_PROG_VERSION, u:{}, skipped:false, skip:{}, choiceSeen:false, notice:false }; }
// Error string or null. Validated whenever present, pack or no pack; script.v is its own
// version (any positive integer is kept, like chars.v).
function validateScriptShape(sc){
  if(!isObj(sc)) return "script must be an object";
  if(sc.v !== undefined && !(Number.isInteger(sc.v) && sc.v >= 1)) return "script.v must be a positive integer";
  if(sc.u !== undefined){ const e = validateRecMap(sc.u, "script.u", false); if(e) return e; }
  for(const f of ["skipped","choiceSeen","notice"]) if(sc[f] !== undefined && typeof sc[f] !== "boolean") return `script.${f} must be a boolean`;
  if(sc.skip !== undefined){
    if(!isObj(sc.skip)) return "script.skip must be an object";
    for(const k of Object.keys(sc.skip)) if(typeof sc.skip[k] !== "boolean") return `script.skip.${k} must be a boolean`;
  }
  return null;
}
const hasWordRecords = data => isObj(data) && isObj(data.w) && Object.keys(data.w).length > 0;
// Missing fields filled from defaults; fields present are kept. Stored progress with a
// word record and no script field predates the primer: that learner is already reading,
// so the primer starts skipped (choice answered) with a one-time notice pending, instead
// of sending them back before their next word set. Fresh progress starts unskipped.
function normalizeScriptProg(sc, data){
  if(isObj(sc)){ const out = Object.assign(defaultScriptProg(), sc); if(!isObj(out.u)) out.u = {}; if(!isObj(out.skip)) out.skip = {}; return out; }
  const out = defaultScriptProg();
  if(hasWordRecords(data)) Object.assign(out, { skipped:true, choiceSeen:true, notice:true });
  return out;
}
function ensureScript(prog){
  if(!isObj(prog.script)) prog.script = defaultScriptProg();
  if(!isObj(prog.script.u)) prog.script.u = {};
  if(!isObj(prog.script.skip)) prog.script.skip = {};
  return prog.script;
}
function scriptRecs(prog){ return (prog && isObj(prog.script) && isObj(prog.script.u)) ? prog.script.u : {}; }
// The whole primer is off (no key), or that stage is off (the primer, or the stage alone).
function scriptSkipped(prog, key){
  const sc = prog && isObj(prog.script) ? prog.script : null;
  if(!sc) return false;
  if(sc.skipped === true) return true;
  return key != null && isObj(sc.skip) && sc.skip[key] === true;
}
// The reversible on/off switch (Progress): flips one flag only, the primer's or (with key)
// one stage's. The path is re-derived from it; no record or set counter is touched.
// Turning a stage on while the whole primer is off leaves the primer off. Turning the
// primer or a stage on also clears the pending notice (the learner has found the switch),
// so turning it off again does not bring the notice back.
function setScriptSkipped(prog, skipped, key){
  const sc = ensureScript(prog);
  if(key == null) sc.skipped = !!skipped; else sc.skip[String(key)] = !!skipped;
  if(!skipped) sc.notice = false;
  return prog;
}
// The choice card's answer: learn (primer on) or skip (primer off).
function answerScriptChoice(prog, learn){ const sc = ensureScript(prog); sc.choiceSeen = true; sc.skipped = !learn; return prog; }
// The one-time "a primer is available" line for learners who predate it.
function scriptNotice(pack, prog){ return !!scriptConfig(pack) && !!(prog && isObj(prog.script) && prog.script.notice === true); }
function dismissScriptNotice(prog){ ensureScript(prog).notice = false; return prog; }
// Scores one script item (writes prog.script.u only).
function markScript(prog, unitId, ok){ return markRec(ensureScript(prog).u, unitId, ok, false); }
function scriptMastered(rec, pack){ const cfg = scriptConfig(pack); return ((rec && rec.s) || 0) >= (cfg ? cfg.mastered : SCRIPT_MASTERED); }

// ---- units, sets, stages
// A stage's units: `set` order, then file order.
function scriptStageUnits(key, units){
  return (Array.isArray(units) ? units : []).map((u, i) => ({u, i})).filter(x => isObj(x.u) && x.u.st === key)
    .sort((a, b) => ((+a.u.set || 0) - (+b.u.set || 0)) || (a.i - b.i)).map(x => x.u);
}
// [[unit]] grouped by `set`, ascending.
function scriptSets(key, units){
  const out = []; let cur = null, last;
  scriptStageUnits(key, units).forEach(u => { if(!cur || u.set !== last){ cur = []; out.push(cur); last = u.set; } cur.push(u); });
  return out;
}
// A set is taught once every unit in it has a record (the characters rule).
function scriptSetTaught(set, prog){ const r = scriptRecs(prog); return (set || []).every(u => hasCharRec(r, u.id)); }
// Up to n (default setsPerSession) first untaught sets of the stage: [{index, units, total}].
function nextScriptSets(key, units, pack, prog, n){
  const cfg = scriptConfig(pack); if(!cfg) return [];
  const k = n == null ? cfg.setsPerSession : n;
  const sets = scriptSets(key, units); const out = [];
  for(let i=0; i<sets.length && out.length<k; i++) if(!scriptSetTaught(sets[i], prog)) out.push({ index:i, units:sets[i], total:sets.length });
  return out;
}
// Script stages for this learner, in path order ([] when skipped or without pack.script):
// {kind:"script", key, label, recorded, nunits, nsets, frac, done}. done = every unit
// recorded, so a missed review never pulls the stage back into the path.
// The primer runs only with a config AND its units: pack.script without script.js data
// (absent or empty units) is the primer off everywhere, exactly the flag-off output.
function scriptActive(pack, units){ return !!scriptConfig(pack) && Array.isArray(units) && units.length > 0; }
function scriptStages(pack, units, prog){
  const cfg = scriptConfig(pack); if(!cfg || !scriptActive(pack, units) || scriptSkipped(prog)) return [];
  const recs = scriptRecs(prog);
  return cfg.stages.filter(st => !scriptSkipped(prog, st.key)).map(st => {
    const list = scriptStageUnits(st.key, units);
    const rec = list.filter(u => hasCharRec(recs, u.id)).length;
    return { kind:"script", key: st.key, label: st.label, recorded: rec, nunits: list.length,
      nsets: scriptSets(st.key, units).length, frac: list.length ? rec/list.length : 1, done: rec >= list.length };
  });
}
// Units with a script record, of a configured stage that is on: the pool Review and Test
// draw from. Empty while the primer is skipped.
function recordedScriptUnits(units, prog, pack){
  const cfg = scriptConfig(pack);
  if(!cfg || scriptSkipped(prog) || !Array.isArray(units) || !units.length) return [];
  const recs = scriptRecs(prog); const keys = new Set(cfg.stages.filter(s => !scriptSkipped(prog, s.key)).map(s => s.key));
  return units.filter(u => isObj(u) && keys.has(u.st) && hasCharRec(recs, u.id));
}
// Recorded units plus the set being taught: the distractor pool of a Learn item.
function scriptPool(units, prog, set){
  const recs = scriptRecs(prog); const cur = new Set((set || []).map(u => u.id));
  return (Array.isArray(units) ? units : []).filter(u => isObj(u) && (cur.has(u.id) || hasCharRec(recs, u.id)));
}
// The choice card shows while it is unanswered, the primer is not switched off, and no
// script record exists. Placement does not answer it (it tests words, not the script).
function showScriptChoice(pack, units, prog){
  const cfg = scriptConfig(pack); if(!cfg || !cfg.stages.length || !scriptActive(pack, units)) return false;
  const sc = (prog && isObj(prog.script)) ? prog.script : {};
  if(sc.choiceSeen === true || sc.skipped === true) return false;
  const recs = scriptRecs(prog);
  return !Object.keys(recs).some(id => hasCharRec(recs, id));
}

// ---- item kinds
const hasEx = u => Array.isArray(u.ex) && u.ex.some(e => Array.isArray(e) && e[0] != null);
// Whether a unit has the fields a kind needs (structure only; scriptItem's own check).
function scriptKindShape(kind, unit){
  if(!isObj(unit)) return false;
  if(SCRIPT_SOUND_KINDS.includes(kind)) return unit.sound !== false && !!unit.roman;
  if(kind === "compose") return Array.isArray(unit.syll) && unit.syll.some(s => isObj(s) && s.t && Array.isArray(s.parts) && s.parts.length);
  if(kind === "formMatch") return unit.joins === "dual" || unit.joins === "right";
  if(kind === "formFind" || kind === "wordRead" || kind === "wordHear") return hasEx(unit);
  return false;
}
const SCRIPT_MIN_OPTIONS = 4;
// Whether a unit can carry an item of this kind. ctx (optional) = {units (every script
// unit), byId | words, tts}: with it, an option kind (all but symType) also needs at least
// SCRIPT_MIN_OPTIONS distinct options when distractors may come from every unit, else it
// does not fit and the pickers move on to another kind. Word kinds are counted only when
// ctx has the words (byId/words); without them only the structure is checked, as it is
// without ctx.
function scriptKindFits(kind, unit, ctx){
  if(!scriptKindShape(kind, unit)) return false;
  if(!isObj(ctx) || !Array.isArray(ctx.units) || kind === "symType") return true;
  const hasWords = !!(ctx.byId || ctx.words);
  if(!hasWords && (kind === "formFind" || kind === "wordRead" || kind === "wordHear")) return true;
  const it = scriptItem(kind, unit, { units: ctx.units, pool: ctx.units, byId: ctx.byId, words: ctx.words, tts: ctx.tts, rng: () => 0 });
  return Array.isArray(it.options) && it.options.length >= SCRIPT_MIN_OPTIONS;
}
// The kind actually asked: wordHear is wordRead when the pack has no voice (tts false, or
// ctx.tts false); null when the unit cannot carry it (scriptKindFits, with ctx).
// A wordHear stays wordHear without a voice when every example word of the unit has a
// recorded clip (exRecorded; needs ctx words).
function scriptKindFor(kind, unit, cfg, ctx){
  const byId = isObj(ctx) ? (ctx.byId || (Array.isArray(ctx.words) ? Object.fromEntries(ctx.words.map(w => [w.id, w])) : null)) : null;
  const k = kind === "wordHear" && ((cfg && !cfg.tts) || (isObj(ctx) && ctx.tts === false)) && !exRecorded(unit, byId) ? "wordRead" : kind;
  return scriptKindFits(k, unit, ctx) ? k : null;
}
// One fitting kind from `kinds` at random; else the first fitting of wordRead, symSound,
// formMatch; else null (the unit is left out).
function pickScriptKind(kinds, unit, cfg, rng, ctx){
  const fit = [...new Set((kinds || []).map(k => scriptKindFor(k, unit, cfg, ctx)).filter(Boolean))];
  if(fit.length) return fit[Math.floor((rng || Math.random)() * fit.length)];
  return ["wordRead","symSound","formMatch"].find(k => scriptKindFits(k, unit, ctx)) || null;
}
// A text's writing system: the Unicode script of its first letter that has one of these
// (Hiragana and Katakana are two), or "" when none does. Compose distractors never cross it.
const SCRIPT_FAMILIES = ["Hangul","Hiragana","Katakana","Han","Cyrillic","Greek","Arabic","Hebrew","Devanagari","Bengali","Gurmukhi","Gujarati","Tamil","Telugu","Kannada","Malayalam","Thai","Lao","Georgian","Armenian","Ethiopic","Latin"]
  .map(n => [n, new RegExp(`\\p{Script=${n}}`, "u")]);
function scriptFamily(text){
  for(const ch of String(text || "")){ const f = SCRIPT_FAMILIES.find(([, re]) => re.test(ch)); if(f) return f[0]; }
  return "";
}

// ---- options
// The glyph an item shows: the last space-separated form of `t` (a teach card may show
// "upper lower"; items use the lower form).
function scriptGlyph(unit){ const p = String((unit && unit.t) || "").trim().split(/\s+/); return p[p.length - 1]; }
// "Does this symbol occur in that text", the same rule as tools/validate_pack.py glyph_in
// (which checks every ex word): lower case, compatibility decomposition (presentation forms
// and composed syllables split into letters, آ = ا + madda, dakuten split off), and a
// positional Hangul letter (initial U+1100.., medial U+1161.., final U+11A8..) keyed as
// its compatibility letter, so the batchim ㄱ of 책 is the letter ㄱ. A match is a
// contiguous run of keys.
const HANGUL_POS_KEY = (() => {
  const m = {}, put = (base, letters) => [...letters].forEach((c, i) => { m[String.fromCharCode(base + i)] = c; });
  put(0x1100, "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ");
  put(0x1161, "ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ");
  put(0x11A8, "ㄱㄲㄳㄴㄵㄶㄷㄹㄺㄻㄼㄽㄾㄿㅀㅁㅂㅄㅅㅆㅇㅈㅊㅋㅌㅍㅎ");
  m["\u111A"] = "ㅀ"; m["\u1121"] = "ㅄ"; // ㅀ and ㅄ decompose to these (archaic) initials
  return m;
})();
function scriptGlyphKeys(s){ return [...String(s == null ? "" : s).toLowerCase().normalize("NFKD")].map(ch => HANGUL_POS_KEY[ch] || ch); }
function scriptGlyphIn(glyph, text){
  const g = scriptGlyphKeys(glyph), t = scriptGlyphKeys(text);
  if(!g.length) return false;
  for(let i = 0; i + g.length <= t.length; i++) if(g.every((k, j) => t[i + j] === k)) return true;
  return false;
}
// Shaping clusters: the smallest runs of a word that may be split into separate elements
// without changing how the word renders. Browsers shape each element's text separately
// (joining context survives a boundary, a ligature does not), so a highlight or any other
// element boundary inside a word must fall between clusters. A cluster is a grapheme
// (base + marks: a haraka stays on its letter, a matra/nukta on its consonant), and then:
//  - Arabic script: lam + alef (ل with ا أ إ آ ٱ ٲ ٳ ٵ, marks or a ZWJ between allowed: shapers ligate
//    through ZWJ) is one
//    mandatory ligature (لا). Tatweel between them blocks the ligature, so it splits.
//  - Brahmic scripts: a grapheme ending in a virama (Devanagari ्, and the Bengali ..
//    Sinhala viramas) joins the next one (क्ष, स्त्र, reph र्क). A ZWNJ after the virama
//    asks for no conjunct and so splits (ZWJ still joins: the half form is shaped with it).
// Nastaliq (ur) and fonts with discretionary ligatures can join more than this; the app
// avoids element boundaries inside words entirely where the browser allows it
// (app.html scriptHL), and this is the fallback granularity.
const GRAPHEMES = typeof Intl !== "undefined" && Intl.Segmenter ? new Intl.Segmenter(undefined, { granularity: "grapheme" }) : null;
function graphemes(s){
  const t = String(s == null ? "" : s);
  if(GRAPHEMES) return [...GRAPHEMES.segment(t)].map(x => x.segment);
  const out = [];
  for(const ch of t){ if(out.length && /[\p{M}‌‍]/u.test(ch)) out[out.length - 1] += ch; else out.push(ch); }
  return out;
}
const LAM_END = /ل[ً-ٰٟ‍]*$/, ALEF_START = /^[اآأإٱٲٳٵ]/;
const VIRAMA_END = /[्্੍્୍்్್്්]‍?$/;
function shapingClusters(s){
  const out = [];
  for(const g of graphemes(s)){
    const prev = out[out.length - 1];
    if(prev !== undefined && ((LAM_END.test(prev) && ALEF_START.test(g)) || VIRAMA_END.test(prev))) out[out.length - 1] = prev + g;
    else out.push(g);
  }
  return out;
}
// A unit's note as shown on its teach card and answer screen: none when it only repeats
// the roman ("b" | "b"), compared trimmed and case-insensitively (normKey).
function scriptUnitNote(unit){
  const n = unit && unit.note != null ? String(unit.note) : "";
  return n && normKey(n) !== normKey(String((unit && unit.roman) || "")) ? n : "";
}
// A unit's name as shown on its teach card head and reveal ("name | roman"): none when
// it only repeats the roman ("ka" | "ka", "kṣa" | "kṣa"), compared the same way as
// scriptUnitNote (trimmed, case-insensitive normKey).
function scriptUnitHeadName(unit){
  const n = unit && unit.name != null ? String(unit.name) : "";
  return n && normKey(n) !== normKey(String((unit && unit.roman) || "")) ? n : "";
}
// True when a word (its w or pron) contains any of the unit's glyphs (upper and lower).
function scriptWordHas(unit, word){
  const gs = String((unit && unit.t) || "").trim().split(/\s+/).filter(Boolean);
  const texts = [word && word.w, word && word.pron].filter(t => typeof t === "string" && t);
  return gs.some(g => texts.some(t => scriptGlyphIn(g, t)));
}
const scriptRomans = u => [u.roman, ...(Array.isArray(u.alt) ? u.alt : [])].map(normKey).filter(Boolean);
// True when `cand` would be a second right answer to `unit`'s option item: the same glyph,
// the same `say`, the same roman, or homophones by `alt` (each accepts the other's roman:
// fa غ gh/q and ق q/gh). A one-way alt is a contrast to drill, not a second answer: ko ㄱ
// accepts "k" (its final sound) yet ㄱ/ㅋ are offered against each other, likewise ru Е
// (alt "e") and Э. Typed answers (symType) still accept roman + alt.
function scriptSecondRight(unit, cand, kind){
  if(cand.id === unit.id) return true;
  if(normKey(scriptGlyph(cand)) === normKey(scriptGlyph(unit))) return true;
  if(unit.say && cand.say && normKey(unit.say) === normKey(cand.say)) return true;
  const ur = normKey(unit.roman), cr = normKey(cand.roman);
  if(ur && ur === cr) return true;
  return !!(ur && cr) && scriptRomans(unit).includes(cr) && scriptRomans(cand).includes(ur);
}
// Up to 3 distractor units for a symbol item. Candidates share the unit's stage (units of
// two stages never mix), are never a second right answer (scriptSecondRight), and are
// pairwise distinct in glyph and roman; sound kinds skip sound:false units. Preference
// within `pool` (recorded units plus the current set): the unit's `confuse` list, same
// group, same set, any. Then padding from all units of the stage: `confuse` first even
// when untaught, then same group, then any, so a set-1 item still gets 4 options.
function scriptOpts(unit, pool, all, kind, rng){
  const every = Array.isArray(all) ? all : (Array.isArray(pool) ? pool : []);
  const inPool = Array.isArray(pool) ? pool : every;
  const sound = SCRIPT_SOUND_KINDS.includes(kind);
  const ok = v => isObj(v) && v.st === unit.st && !!v.roman && !(sound && v.sound === false) && !scriptSecondRight(unit, v, kind);
  const confuse = new Set(Array.isArray(unit.confuse) ? unit.confuse : []);
  const sameGroup = v => unit.group != null && v.group === unit.group;
  const cands = inPool.filter(ok), rest = every.filter(ok);
  const tiers = [cands.filter(v => confuse.has(v.id)), cands.filter(sameGroup), cands.filter(v => v.set === unit.set), cands,
    rest.filter(v => confuse.has(v.id)), rest.filter(sameGroup), rest];
  const out = [], ids = new Set([unit.id]), usedG = new Set([normKey(scriptGlyph(unit))]), usedR = new Set([normKey(unit.roman)]);
  for(const tier of tiers){
    for(const v of shuffle(tier.slice(), rng)){
      if(out.length >= 3) return out;
      const g = normKey(scriptGlyph(v)), r = normKey(v.roman);
      if(ids.has(v.id) || usedG.has(g) || usedR.has(r)) continue;
      out.push(v); ids.add(v.id); usedG.add(g); usedR.add(r);
    }
  }
  return out;
}
// symSound options: the distractors' romans.
function scriptRomanOpts(unit, pool, all, rng){ return scriptOpts(unit, pool, all, "symSound", rng).map(v => String(v.roman)); }
// A unit's example words that exist in the pack: [{id, w, roman, unitId}].
function exRecorded(unit, byId){
  if(!byId || !isObj(unit)) return false;
  const ex = scriptExamples(unit, byId);
  return ex.length > 0 && ex.every(e => !!wordAudio(byId[e.id]));
}
function scriptExamples(unit, byId){
  return (Array.isArray(unit && unit.ex) ? unit.ex : []).filter(e => Array.isArray(e) && byId[e[0]] && byId[e[0]].w)
    .map(e => ({ id: e[0], w: String(byId[e[0]].w), roman: String(e[1] == null ? "" : e[1]), unitId: unit.id }));
}
function editDistance(a, b){
  const x = [...String(a)], y = [...String(b)];
  let prev = y.map((_, j) => j + 1); prev.unshift(0);
  for(let i=1; i<=x.length; i++){
    const cur = [i];
    for(let j=1; j<=y.length; j++) cur[j] = Math.min(prev[j] + 1, cur[j-1] + 1, prev[j-1] + (x[i-1] === y[j-1] ? 0 : 1));
    prev = cur;
  }
  return prev[y.length];
}
// Up to 3 distractor words for a word item (ans = {id, w, roman}): example words of the
// same stage's units in `pool` (taught), padded from `all`; never the answer's word or a
// word with its roman, pairwise distinct in word and roman. Nearest first: edit distance
// to the answer (a word differing in one symbol comes first), then same length.
function scriptWordOpts(unit, ans, pool, all, byId, rng){
  const every = Array.isArray(all) ? all : (Array.isArray(pool) ? pool : []);
  const inPool = Array.isArray(pool) ? pool : every;
  const b = byId || {}; const len = cpLen(ans.w);
  const gather = list => list.filter(u => isObj(u) && u.st === unit.st).flatMap(u => scriptExamples(u, b))
    .filter(e => e.id !== ans.id && normKey(e.w) !== normKey(ans.w) && e.roman && normKey(e.roman) !== normKey(ans.roman));
  const rank = list => shuffle(list, rng).map((e, i) => ({ e, d: editDistance(e.w, ans.w), l: cpLen(e.w) === len ? 0 : 1, i }))
    .sort((p, q) => (p.d - q.d) || (p.l - q.l) || (p.i - q.i)).map(o => o.e);
  const out = [], usedW = new Set([normKey(ans.w)]), usedR = new Set([normKey(ans.roman)]);
  for(const tier of [rank(gather(inPool)), rank(gather(every))]){
    for(const e of tier){
      if(out.length >= 3) return out;
      if(usedW.has(normKey(e.w)) || usedR.has(normKey(e.roman))) continue;
      out.push(e); usedW.add(normKey(e.w)); usedR.add(normKey(e.roman));
    }
  }
  return out;
}
// Joined forms for formMatch: dual joiners have initial, medial and final; right joiners
// only final. Unicode shaping draws them from the letter plus a zero-width joiner.
function scriptJoinedForms(unit){
  const L = scriptGlyph(unit);
  if(unit && unit.joins === "dual") return [{ form:"init", t: L + ZWJ }, { form:"medi", t: ZWJ + L + ZWJ }, { form:"fina", t: ZWJ + L }];
  if(unit && unit.joins === "right") return [{ form:"fina", t: ZWJ + L }];
  return [];
}
// One drill item for a unit, DOM-free: {kind, key, unitId, show, hint, form, audio, say,
// audioUrl, wordId, options, answer, accept, reveal}.
//  - show: the stimulus text, or null for a sound-only stimulus.
//  - audio: "before" (the stimulus), "after" (played on answering) or null. say is the
//    TTS text, audioUrl a recorded clip that beats it; both null when audio is null.
//  - options: shuffled strings including answer (null for symType, which checks typed
//    input against accept).
//  - reveal: {t, glyph, name, roman, note, word} for the answer screen (gloss lives on
//    the word, never in the stimulus).
// ctx: {units (all script units), pool (distractor pool; default units), words | byId,
// tts (false: no usable voice, so soundSym shows the roman and wordHear becomes wordRead),
// rng}. Throws on an unknown kind or a unit that cannot carry it.
function scriptItem(kind, unit, ctx){
  const c = ctx || {}; const r = c.rng || Math.random;
  const all = Array.isArray(c.units) ? c.units : []; const pool = Array.isArray(c.pool) ? c.pool : all;
  const byId = c.byId || Object.fromEntries((c.words || []).map(w => [w.id, w]));
  const voice = c.tts !== false;
  if(!SCRIPT_KINDS.includes(kind)) throw new Error(`unknown script item kind ${kind}`);
  const k = kind === "wordHear" && !voice && !exRecorded(unit, byId) ? "wordRead" : kind;
  if(!scriptKindShape(k, unit)) throw new Error(`script unit ${unit && unit.id} cannot carry a ${k} item`);
  const glyph = scriptGlyph(unit), roman = String(unit.roman || "");
  const unitSay = voice && unit.say ? String(unit.say) : null, unitUrl = unit.audio ? String(unit.audio) : null;
  const unitAudio = !!(unitSay || unitUrl);
  const exs = scriptExamples(unit, byId);
  const pickEx = () => exs[Math.floor(r() * exs.length)];
  const wordOf = e => { const w = byId[e.id] || {}; return { id: e.id, w: e.w, roman: e.roman, en: gloss(w) }; };
  const reveal = { t: String(unit.t), glyph, name: scriptUnitHeadName(unit), roman, note: scriptUnitNote(unit), word: null };
  const it = { kind: k, key: "x:" + unit.id, unitId: unit.id, show: null, hint: null, form: null, audio: null, say: null, audioUrl: null,
    wordId: null, options: null, answer: null, accept: null, reveal };
  const unitSound = when => { if(unitAudio){ it.audio = when; it.say = unitSay; it.audioUrl = unitUrl; } };
  // An example word's clip (words[].audio) beats TTS and plays with no voice, as unitSound.
  const wordSound = (when, e) => { const url = wordAudio(byId[e.id]); if(voice || url){ it.audio = when; it.say = voice ? e.w : null; it.audioUrl = url || null; } };
  let others = [];
  if(k === "symSound"){ it.show = glyph; it.answer = roman; others = scriptRomanOpts(unit, pool, all, r); unitSound("after"); }
  else if(k === "soundSym"){
    it.answer = glyph; others = scriptOpts(unit, pool, all, k, r).map(scriptGlyph);
    if(unitAudio) unitSound("before"); else it.show = roman;
  }
  else if(k === "symType"){ it.show = glyph; it.answer = roman; it.accept = [roman, ...(Array.isArray(unit.alt) ? unit.alt.map(String) : [])]; unitSound("after"); }
  else if(k === "compose"){
    const sy = unit.syll.filter(s => isObj(s) && s.t && Array.isArray(s.parts) && s.parts.length);
    const s = sy[Math.floor(r() * sy.length)];
    it.show = s.parts.map(String).join(" + "); it.answer = String(s.t);
    reveal.roman = String(s.roman || ""); reveal.syll = { t: String(s.t), parts: s.parts.map(String), roman: String(s.roman || "") };
    // Distractor syllables, widening scope: the same set, the same stage, then any stage
    // written in the same script (hiragana and katakana never mix). Within a scope: taught
    // (pool) sharing a part, taught, any sharing a part, any.
    const parts = new Set(s.parts.map(String)), fam = scriptFamily(it.answer);
    const scopes = [u => u.st === unit.st && u.set === unit.set, u => u.st === unit.st, () => true];
    const cand = (list, sc) => list.filter(u => isObj(u) && Array.isArray(u.syll) && sc(u)).flatMap(u => u.syll)
      .filter(x => isObj(x) && x.t && String(x.t) !== it.answer && scriptFamily(x.t) === fam && !(s.roman && x.roman && normKey(x.roman) === normKey(s.roman)));
    const shares = x => Array.isArray(x.parts) && x.parts.some(p => parts.has(String(p)));
    const used = new Set([it.answer]), usedR = new Set([normKey(s.roman || "")]);
    for(const list of scopes.flatMap(sc => [cand(pool, sc).filter(shares), cand(pool, sc), cand(all, sc).filter(shares), cand(all, sc)])){
      for(const x of shuffle(list.slice(), r)){ if(others.length >= 3) break; const xr = normKey(x.roman || ""); if(!used.has(String(x.t)) && !(xr && usedR.has(xr))){ used.add(String(x.t)); if(xr) usedR.add(xr); others.push(String(x.t)); } }
    }
    if(voice){ it.audio = "after"; it.say = it.answer; }
  }
  else if(k === "formFind"){
    const e = pickEx(); it.show = glyph; it.hint = reveal.name || null; it.answer = e.w; it.wordId = e.id; reveal.word = wordOf(e);
    const used = new Set([normKey(e.w)]);
    const gather = list => list.filter(u => isObj(u) && u.st === unit.st).flatMap(u => scriptExamples(u, byId)).filter(x => !scriptWordHas(unit, byId[x.id]));
    for(const list of [gather(pool), gather(all)]){
      for(const x of shuffle(list, r)){ if(others.length >= 3) break; if(!used.has(normKey(x.w))){ used.add(normKey(x.w)); others.push(x.w); } }
    }
    wordSound("after", e);
  }
  else if(k === "formMatch"){
    const fs = scriptJoinedForms(unit); const f = fs[Math.floor(r() * fs.length)];
    it.show = f.t; it.form = f.form; it.answer = glyph; others = scriptOpts(unit, pool, all, k, r).map(scriptGlyph);
  }
  else if(k === "wordRead"){
    const e = pickEx(); it.show = e.w; it.answer = e.roman; it.wordId = e.id; reveal.word = wordOf(e);
    others = scriptWordOpts(unit, e, pool, all, byId, r).map(x => x.roman); wordSound("after", e);
  }
  else if(k === "wordHear"){
    const e = pickEx(); it.answer = e.w; it.wordId = e.id; reveal.word = wordOf(e);
    others = scriptWordOpts(unit, e, pool, all, byId, r).map(x => x.w); wordSound("before", e);
  }
  if(k !== "symType") it.options = shuffle([it.answer, ...others], r);
  return it;
}

// ---- plans
// Learn step for a script set: per unit one item per pack learnKind that fits it. A
// sound:false unit gets wordRead in place of the sound kinds; compose needs `syll`. A unit
// no learnKind fits gets its first fitting kind, so every unit of the set is asked.
// ctx (optional): as scriptKindFits; with it, a kind that cannot get 4 options is skipped.
function learnScriptPlan(set, pack, ctx){
  const cfg = scriptConfig(pack); if(!cfg) return [];
  const out = [];
  (set || []).forEach(unit => {
    const seen = new Set();
    cfg.learnKinds.forEach(k0 => {
      let k = scriptKindFor(k0, unit, cfg, ctx);
      if(!k && SCRIPT_SOUND_KINDS.includes(k0) && isObj(unit) && unit.sound === false) k = scriptKindFits("wordRead", unit, ctx) ? "wordRead" : null;
      if(k && !seen.has(k)){ seen.add(k); out.push({ kind: k, unit }); }
    });
    if(!seen.size){ const k = pickScriptKind(SCRIPT_KINDS, unit, cfg, () => 0, ctx); if(k) out.push({ kind: k, unit }); }
  });
  return out;
}
// Review weakness score, the characters rule with pack.script.mastered: an unmastered
// unit scores at least 0; mastered units keep w*3 - s and sink.
function scriptReviewScore(rec, pack){
  const cfg = scriptConfig(pack); const p = rec || {}; const sc = weakScore(p);
  return (p.s || 0) < (cfg ? cfg.mastered : SCRIPT_MASTERED) ? Math.max(sc, 0) : sc;
}
// Test tab's script practice: the n weakest recorded units, each with a kind drawn from
// pack.script.testKinds among the kinds that fit it. [{kind, unit}]. ctx (optional): as
// scriptKindFits; its units default to `units`, so option kinds are always counted.
function scriptTestPlan(units, prog, pack, n, rng, ctx){
  const cfg = scriptConfig(pack); if(!cfg) return [];
  const kctx = Object.assign({ units }, ctx || {});
  const rec = weakFirst(recordedScriptUnits(units, prog, pack), n, scriptRecs(prog), undefined, rng);
  const out = [];
  rec.forEach(unit => {
    const w = {}; Object.keys(cfg.testKinds).forEach(k => { const f = scriptKindFor(k, unit, cfg, kctx); if(f) w[f] = (w[f] || 0) + cfg.testKinds[k]; });
    const kind = Object.keys(w).length ? pickWeighted(w, rng) : pickScriptKind(cfg.reviewKinds, unit, cfg, rng, kctx);
    if(kind) out.push({ kind, unit });
  });
  return out;
}

// ------------------------------------------------------------------ pronunciation aids
// Pack-gated helpers (docs/PACK_SCHEMA.md "Pronunciation aids"), all pure. Off for every
// pack without the field, so no other pack's output changes.
//  - pack.tones: the reading is Latin letters with tone marks on a vowel (macron 1, acute
//    2, caron 3, grave 4, unmarked 5 = neutral). The validator admits one mark system,
//    whose syllable inventory is SYL_FINALS below; toneHTML colours each syllable.
//  - pack.typing === "pron": typed production of the reading (checkPronTyped).
//  - composeSpanReading: the reading of a tap span longer than its word.
const TONE_MARKS = {
  a: ["a","\u0101","\u00e1","\u01ce","\u00e0"],
  e: ["e","\u0113","\u00e9","\u011b","\u00e8"],
  i: ["i","\u012b","\u00ed","\u01d0","\u00ec"],
  o: ["o","\u014d","\u00f3","\u01d2","\u00f2"],
  u: ["u","\u016b","\u00fa","\u01d4","\u00f9"],
  "\u00fc": ["\u00fc","\u01d6","\u01d8","\u01da","\u01dc"],
};
const MARK_OF = {}; // marked (or plain) vowel -> [plain vowel, tone 1-4, or 0 for none]
Object.keys(TONE_MARKS).forEach(v => TONE_MARKS[v].forEach((c, t) => { MARK_OF[c] = [v, t]; }));
function tonesOn(pack){ return !!(pack && typeof pack.tones === "string" && pack.tones); }
// A reading with its tone marks removed, case and everything else kept.
function stripMarks(s){
  return [...String(s == null ? "" : s).normalize("NFC")].map(c => {
    const m = MARK_OF[c.toLowerCase()]; if(!m) return c;
    return c === c.toLowerCase() ? m[0] : m[0].toUpperCase();
  }).join("");
}
// Tone of a marked letter string: the tone of its (first) marked vowel, 5 when unmarked.
function syllableTone(s){
  for(const c of String(s || "")){ const m = MARK_OF[c.toLowerCase()]; if(m && m[1]) return m[1]; }
  return 5;
}
const markCount = s => [...String(s || "")].filter(c => { const m = MARK_OF[c.toLowerCase()]; return !!(m && m[1]); }).length;
// Mark placement: a, else e, else o, else the last of i/u/ü. tone 0 or 5: unmarked.
function markVowelIndex(letters){
  const lower = String(letters).toLowerCase();
  for(const v of ["a","e","o"]){ const i = lower.indexOf(v); if(i >= 0) return i; }
  for(let i = lower.length - 1; i >= 0; i--) if("iu\u00fc".indexOf(lower[i]) >= 0) return i;
  return -1;
}
function markSyllable(letters, tone){
  const s = String(letters); const i = markVowelIndex(s); const t = +tone;
  if(i < 0 || !(t >= 1 && t <= 4)) return s;
  const c = s[i]; const m = MARK_OF[c.toLowerCase()];
  const out = TONE_MARKS[m ? m[0] : c.toLowerCase()][t];
  return s.slice(0, i) + (c !== c.toLowerCase() ? out.toUpperCase() : out) + s.slice(i + 1);
}
// Syllable inventory: initial -> finals, spelled as written (zero initial uses y/w forms;
// j/q/x/y write ü as u). "" holds the zero-initial syllables.
const SYL_FINALS = {
  b: "a ai an ang ao o ei en eng i ie iao ian in iang ing u",
  p: "a ai an ang ao o ei en eng ou i ie iao ian in iang ing u",
  m: "a ai an ang ao o ei en eng ou i ie iao iu ian in iang ing u e",
  f: "a an ang ei en eng ou u o",
  d: "a ai an ang ao e ei en eng ong i ia ie iao iu ian ing ou u uo ui uan un",
  t: "a ai an ang ao e eng ong i ian iao ie ing ou u uo ui uan un",
  n: "a ai an ang ao e ei en eng i ian iang iao ie in ing iu ong ou u uan uo \u00fc \u00fce",
  l: "a ai an ang ao e ei eng i ia ian iang iao ie in ing iu ong ou u uan un uo \u00fc \u00fce o",
  g: "a ai an ang ao e ei en eng ong ou u ua uai uan uang ui un uo",
  k: "a ai an ang ao e ei en eng ong ou u ua uai uan uang ui un uo",
  h: "a ai an ang ao e ei en eng ong ou u ua uai uan uang ui un uo",
  j: "i ia ian iang iao ie in ing iong iu u uan ue un",
  q: "i ia ian iang iao ie in ing iong iu u uan ue un",
  x: "i ia ian iang iao ie in ing iong iu u uan ue un",
  zh: "a ai an ang ao e ei en eng i ong ou u ua uai uan uang ui un uo",
  ch: "a ai an ang ao e en eng i ong ou u ua uai uan uang ui un uo",
  sh: "a ai an ang ao e ei en eng i ou u ua uai uan uang ui un uo",
  r: "an ang ao e en eng i ong ou u ua uan ui un uo",
  z: "a ai an ang ao e ei en eng i ong ou u uan ui un uo",
  c: "a ai an ang ao e en eng i ong ou u uan ui un uo",
  s: "a ai an ang ao e en eng i ong ou u uan ui un uo",
  "": "a o e ai ei ao ou an en ang eng er yi ya ye yao you yan yin yang ying yong wu wa wo wai wei wan wen wang weng yu yue yuan yun yo",
};
const SYL_SET = {}; Object.keys(SYL_FINALS).forEach(k => { SYL_SET[k] = new Set(SYL_FINALS[k].split(" ")); });
const SYL_INITIALS = Object.keys(SYL_FINALS).filter(Boolean).sort((a, b) => b.length - a.length);
// Toneless syllable -> {initial, final}, or null when it is not in the inventory.
function splitSyllable(toneless){
  const s = String(toneless || "").toLowerCase();
  for(const ini of SYL_INITIALS) if(s.indexOf(ini) === 0 && SYL_SET[ini].has(s.slice(ini.length))) return { initial: ini, final: s.slice(ini.length) };
  return SYL_SET[""].has(s) ? { initial: "", final: s } : null;
}
// A syllable with a trailing r-suffix ("r" after a full syllable, not "er" itself).
const isRSuffixed = s => s.length > 1 && s[s.length - 1] === "r" && s !== "er" && !!splitSyllable(s.slice(0, -1));
const SYL_MAX = 7;
// One run of letters -> syllables [{text, tone, r}] or null when it does not split into
// the inventory with at most one mark each. Fewest syllables wins; a syllable starting
// with a/o/e inside the run (where the writing would put an apostrophe) costs extra;
// among equals the longest first syllable wins (the usual left-to-right reading).
function splitRun(run){
  const chars = [...run]; const n = chars.length;
  const bare = chars.map(c => { const m = MARK_OF[c.toLowerCase()]; return m ? m[0] : c.toLowerCase(); });
  const best = new Array(n + 1).fill(null); best[n] = { cost: 0, next: -1 };
  for(let i = n - 1; i >= 0; i--){
    for(let j = Math.min(n, i + SYL_MAX); j > i; j--){
      if(!best[j]) continue;
      const b = bare.slice(i, j).join("");
      const r = !splitSyllable(b) && isRSuffixed(b);
      if(!r && !splitSyllable(b)) continue;
      if(markCount(chars.slice(i, j).join("")) > 1) continue;
      const cost = best[j].cost + 1 + (r ? 0.5 : 0) + (i > 0 && /^[aoe]/.test(b) ? 10 : 0);
      if(!best[i] || cost < best[i].cost) best[i] = { cost, next: j, r };
    }
  }
  if(!best[0]) return null;
  const out = []; let i = 0;
  while(i < n){ const j = best[i].next; const text = chars.slice(i, j).join(""); out.push({ text, tone: syllableTone(text), r: !!best[i].r }); i = j; }
  return out;
}
// Reading -> pieces [{text, tone?}]: each syllable of each letter run with its tone; text
// between runs (spaces, punctuation, other scripts) has no tone. A run that does not split
// is one piece, toned only when it carries exactly one mark.
const LETTER_RUN = /[\p{Script=Latin}\u0300-\u036f]+/gu;
function splitReading(text){
  const t = String(text == null ? "" : text).normalize("NFC");
  const out = []; let pos = 0;
  for(const m of t.matchAll(LETTER_RUN)){
    if(m.index > pos) out.push({ text: t.slice(pos, m.index) });
    const syl = splitRun(m[0]);
    if(syl) syl.forEach(x => out.push({ text: x.text, tone: x.tone }));
    else out.push(markCount(m[0]) === 1 ? { text: m[0], tone: syllableTone(m[0]) } : { text: m[0] });
    pos = m.index + m[0].length;
  }
  if(pos < t.length) out.push({ text: t.slice(pos) });
  return out;
}
// Escaped HTML of a reading, each syllable in <span class="t1".."t5">.
function toneHTML(text){
  return splitReading(text).map(p => p.tone ? `<span class="t${p.tone}">${escapeHtml(p.text)}</span>` : escapeHtml(p.text)).join("");
}
// ---- typed reading (pack.typing === "pron")
function pronTypingOn(pack){ return !!(pack && pack.typing === "pron"); }
// Comparison key: case-folded, v and u: as ü, ü after j/q/x/y as u (the writing drops
// the dots there), apostrophes, hyphens, spaces and punctuation removed; marks and digits kept.
function pronKey(s){
  return String(s == null ? "" : s).normalize("NFC").toLowerCase()
    .replace(/u:/g, "\u00fc").replace(/v/g, "\u00fc")
    .replace(/[^\p{L}\p{N}]/gu, "")
    .replace(/([jqxy])([\u00fc\u01d6\u01d8\u01da\u01dc])/g, (m, a, b) => a + TONE_MARKS.u[MARK_OF[b][1]]);
}
const NUMBERED_MAX = 64;
// Every numbered spelling of pron: syllable letters + tone digit; a neutral syllable as
// 5, 0 or no digit; an r-suffixed syllable with its digit after the r, or before it with
// the r bare, r5 or r0.
// [] when pron does not split into syllables (then only the marked form is accepted).
function numberedForms(pron){
  const runs = String(pron || "").normalize("NFC").match(LETTER_RUN) || [];
  let combos = [""];
  for(const run of runs){
    const syl = splitRun(run); if(!syl) return [];
    for(const x of syl){
      const b = stripMarks(x.text).toLowerCase();
      const d = x.tone === 5 ? ["5", "0", ""] : [String(x.tone)];
      const opts = [];
      // r-suffix: the digit also before the r, the r then bare or as its own neutral
      // chunk ("yi1hui4r5", "hui4r0": how the predecessor app stored 一会儿).
      d.forEach(k => { opts.push(b + k); if(x.r && k) ["r", "r5", "r0"].forEach(rr => opts.push(b.slice(0, -1) + k + rr)); });
      const next = []; combos.forEach(c => opts.forEach(o => next.push(c + o)));
      if(next.length > NUMBERED_MAX) return [];
      combos = next;
    }
  }
  return runs.length ? combos.map(pronKey) : [];
}
// Typed reading vs a word's pron: "ok" (marked, or numbered per numberedForms, case and
// apostrophes ignored), "tones" (right letters, no tone marks or digits), "tonesDiff"
// (right letters, tones given but not all right, e.g. ni2hao3 or nihao5) or "wrong"
// (the letters differ). Tones are optional: the typed-reading item accepts every verdict
// but "wrong" and notes the marked form after "tones" or "tonesDiff".
// pack (optional): a pack without `tones` (e.g. ja: kana readings) takes the plain path
// instead, plainPronKey equality, "ok" or "wrong" only; no pack keeps the tonal path.
const pronLetters = s => pronKey(stripMarks(s)).replace(/\p{N}/gu, "");
function checkPronTyped(input, pron, pack){
  if(pack && !tonesOn(pack)){ const k = plainPronKey(input); return k && pron && k === plainPronKey(pron) ? "ok" : "wrong"; }
  const got = pronKey(input);
  if(!got || !pron) return "wrong";
  if(got === pronKey(pron) || numberedForms(pron).indexOf(got) >= 0) return "ok";
  if(pronLetters(got) !== pronLetters(pron)) return "wrong";
  return !/\p{N}/u.test(got) && markCount(got) === 0 ? "tones" : "tonesDiff";
}
// Kana fold for readings: NFKC (half-width kana to full width), then katakana to hiragana
// (U+30A1-30F6 to U+3041-3096, the iteration marks ヽヾ to ゝゞ), so a katakana reading
// may be typed in hiragana and the reverse. The long-vowel mark ー, small kana (ゃ is not
// や) and voicing marks are kept: they spell a different reading.
function kanaFold(s){
  return String(s == null ? "" : s).normalize("NFKC").replace(/[\u30a1-\u30f6\u30fd\u30fe]/g, c => String.fromCharCode(c.charCodeAt(0) - 0x60));
}
// Comparison key for a reading typed without tones: kanaFold, normalizeTyped (case,
// whitespace, apostrophes), then everything but letters, marks and digits removed (spaces,
// the affix mark 〜 of 〜ねん, the middle dot ・).
function plainPronKey(s){ return normalizeTyped(kanaFold(s)).replace(/[^\p{L}\p{M}\p{N}]/gu, ""); }
// A written form without its affix mark: 〜年 -> 年 (wave dash or full-width tilde at
// either end), so a typed suffix/prefix word needs no 〜. The form itself when it has none.
// Affix marks in the written form a learner should not have to type: Japanese \u301c/\uff5e
// (noun-modifier tilde) and the ASCII hyphen (Korean particle words like -\uc774\ub2e4, -\uc774/\uac00).
// Only a leading or trailing run is an affix mark; stripped from either end, never both
// meanings at once mattering since the anchors are independent. An inner hyphen (Hindi
// \u0927\u0940\u0930\u0947-\u0927\u0940\u0930\u0947, \u0915\u094c\u0928-\u0938\u093e) or inner tilde (\u5e74\u301c\u5e74) is a real character, never touched.
function affixBare(w){ return String(w == null ? "" : w).replace(/^[\u301c\uff5e-]+|[\u301c\uff5e-]+$/g, ""); }
// Extra accepted written forms for a word whose display form carries a leading/trailing
// affix mark (see affixBare): the bare form with the affix stripped, plus \u2014 when that
// bare form is itself a "/"-separated set of alternatives (Korean particle pairs like
// -\uc774/\uac00 -> \uc774/\uac00 -> \uc774, \uac00) \u2014 each alternative on its own. Returns [] when the word has
// no affix mark (bare === original), so callers can splice this straight into acceptTyped's
// `extra` list without conditionals. entry.w itself (with its affix mark, e.g. -\uc774/\uac00) is
// already checked by acceptTyped, so it is not repeated here.
function affixAlts(w){
  const s = String(w == null ? "" : w);
  const bare = affixBare(s);
  if(bare === s) return [];
  return bare.indexOf("/") >= 0 ? [bare, ...bare.split("/")] : [bare];
}
// pack.typing "pron": the typed item a plan's "type" slot (a word's production slot) is.
// The type slots alternate in plan order, reading first: "pron" (type the reading, silent,
// tones optional), then "written" (type the characters, the word's audio played). Plan
// order is already fixed by the plan builders' rng, so no randomness is added and every
// plan is unchanged; i undefined (a lone item) is "pron".
// The app still gives a "written" slot the reading item when the word's written form is
// not on display (pronFirst: a word below its character tier is shown by its reading).
function typeSlotKind(plan, i){
  let n = 0;
  for(let j = 0; j < (i || 0); j++) if(plan && plan[j] && plan[j].kind === "type") n++;
  return n % 2 ? "written" : "pron";
}
// ---- span reading
// Joins two readings: with pack.tones an apostrophe goes before a syllable starting with
// a/o/e (the writing's syllable-boundary rule), otherwise they are simply concatenated.
function joinReadings(a, b, pack){
  if(!a) return b; if(!b) return a;
  return tonesOn(pack) && /^[aoe]/i.test(stripMarks(b)) && /[\p{L}]$/u.test(a) ? a + "'" + b : a + b;
}
// The reading of a tap span whose text may be longer than its word (越来越 for 越, 一下 for
// 下). Returns pieces [{start, end, reading}] covering text in order, offsets relative to
// text: each occurrence of the word's written form gets word.pron. Every other character
// gets readingOf(char) (e.g. its single-character unit's reading) only when the pack opts
// in with pack.characters.compose (a character reads the same in every word, as each
// character unit has one reading); otherwise, and for a character with no reading, it gets
// reading "" (shown written): a reading is never guessed. Adjacent read pieces are merged
// with joinReadings, as are adjacent written ones. No character is ever dropped.
function composeSpanReading(text, word, readingOf, pack){
  const t = String(text == null ? "" : text); const w = String((word && word.w) || ""); const wp = String((word && word.pron) || "");
  const cfg = charsConfig(pack); if(!(cfg && cfg.compose)) readingOf = null;
  const raw = []; let i = 0;
  while(i < t.length){
    if(w && wp && t.startsWith(w, i)){ raw.push({ start: i, end: i + w.length, reading: wp }); i += w.length; continue; }
    const cp = t.codePointAt(i); const c = String.fromCodePoint(cp);
    const r = readingOf ? String(readingOf(c) || "") : "";
    raw.push({ start: i, end: i + c.length, reading: r }); i += c.length;
  }
  const out = [];
  raw.forEach(p => {
    const last = out[out.length - 1];
    if(last && !!last.reading === !!p.reading){ last.end = p.end; last.reading = p.reading ? joinReadings(last.reading, p.reading, pack) : ""; }
    else out.push(Object.assign({}, p));
  });
  return out;
}
// The reading line of a span as one string: composeSpanReading's readings, with a written
// piece's own text in place.
function spanReadingText(text, word, readingOf, pack){
  const t = String(text == null ? "" : text);
  return composeSpanReading(t, word, readingOf, pack).map(p => p.reading || t.slice(p.start, p.end)).join("");
}

// ------------------------------------------------------------------ legacy migration
// One-way import of a predecessor app's progress into this pack's shape (design: the
// merge plan in docs/, §4). zh: the hsk trainer's "hsk_pinyin" record. Every hsk release
// (v1, v2, v2.1 sentences, v2.2 characters, v2.3/HEAD path flags) stored v:1 or v:2 and
// only ever added fields, so one reader covers them all. Pure and DOM-free.
//
// legacyMap is the pack's LEGACY const (legacy.js): {w: hanzi -> word id, s: sentence
// text -> sentence id, c: hanzi -> character unit id}.
//
// migrateLegacy(pack, legacyMap, oldRecord), oldRecord an object or its JSON string:
//   {ok:false, reason}  not a JSON object, an unknown legacy version, or no pack.legacy
//   {ok:true, prog, unmapped, dropped, already}
//     prog      normalizeProg output carrying the marker prog.legacy = {key, format}
//     unmapped  [{path, value, reason}]: every part of the old record with no place in
//               prog (a key the maps lack, an unknown field, a value of the wrong type).
//               Nothing is discarded silently. Acceptance for the real switch: empty.
//     dropped   [{path, value}]: fields retired on purpose (LEGACY_DROPPED).
//     already   true when oldRecord carries the marker, i.e. it is already migrated:
//               prog = normalizeProg(oldRecord) and both lists empty. A second run is a no-op.
// Field mapping: v -> PROG_VERSION; w[hanzi] -> w[wordId] and s[text] -> s[sentId] with
// r/w/s (and w's prov/d) verbatim; c[hanzi] -> chars.c[unitId]; sets, lessons, sessions,
// theme, placedOnce, soundsOpened as-is; mixChars/charsAfterHsk4/charsChoiceSeen ->
// chars.mix/defer/choiceSeen; showPron takes the pack default.
//
// Caller contract (boot hook and import path, not in this file):
// - Boot: migrate only when pack.legacy is set, storageKey(pack) holds nothing and the
//   legacy key (pack.legacy.key) holds a record. Never write or delete the legacy key.
// - Before the first save of prog, copy the raw legacy string to legacyBackupKey(pack),
//   unless that key already holds something (the first backup is never overwritten).
// - Report a non-empty unmapped list to the learner; those parts survive in the backup.
// - Import: isLegacyRecord() tells a legacy export from native progress.
const LEGACY_DROPPED = ["showChars","dismissedSoundsHint"];
const LEGACY_ONLY_FIELDS = ["showChars","dismissedSoundsHint","c","mixChars","charsAfterHsk4","charsChoiceSeen"];
const NATIVE_ONLY_FIELDS = ["chars","showPron","read"];
function legacyBackupKey(pack){ return `${pack.legacy.key}.bak`; }
function legacyMarker(pack){ return { key: String(pack.legacy.key || ""), format: String(pack.legacy.format || "") }; }
function hasLegacyMarker(data){ return isObj(data) && isObj(data.legacy) && typeof data.legacy.key === "string"; }
// True when data looks like a legacy export rather than this engine's own progress.
function isLegacyRecord(pack, legacyMap, data){
  if(!isObj(pack && pack.legacy) || !isObj(data) || hasLegacyMarker(data)) return false;
  if(NATIVE_ONLY_FIELDS.some(f => data[f] !== undefined)) return false;
  if(data.v === 2 && PROG_VERSION !== 2) return true;
  if(LEGACY_ONLY_FIELDS.some(f => data[f] !== undefined)) return true;
  const known = b => isObj(data[b]) && isObj(legacyMap && legacyMap[b]) && Object.keys(data[b]).some(k => hasOwn(legacyMap[b], k));
  return known("w") || known("s");
}
function migrateLegacy(pack, legacyMap, oldRecord){
  if(!isObj(pack) || !isObj(pack.legacy)) return {ok:false, reason:"pack has no legacy block"};
  let data = oldRecord;
  if(typeof data === "string"){ const p = parseStored(data); if(!p.ok) return p; data = p.data; }
  if(!isObj(data)) return {ok:false, reason:"not a JSON object"};
  const lv = levelIds(pack);
  if(hasLegacyMarker(data)){
    const v = validateProgShape(data, lv); if(!v.ok) return v;
    return {ok:true, already:true, prog: normalizeProg(data, pack), unmapped:[], dropped:[]};
  }
  if(data.v !== undefined && data.v !== 1 && data.v !== 2) return {ok:false, reason:`unknown legacy progress version ${data.v}`};
  const maps = isObj(legacyMap) ? legacyMap : {};
  const unmapped = [], dropped = [];
  const miss = (path, value, reason) => { unmapped.push({path, value, reason}); };
  const cfg = charsConfig(pack);
  const isNum = x => typeof x === "number" && isFinite(x);
  const numOrBool = x => isNum(x) || typeof x === "boolean";
  // One record bucket: keys through the map, known fields verbatim, the rest reported.
  function recMap(bucket, map, wordFlags){
    const src = data[bucket], dst = {};
    if(src === undefined) return dst;
    if(!isObj(src)){ miss(bucket, src, "not an object"); return dst; }
    const m = isObj(map) ? map : {};
    for(const k of Object.keys(src)){
      const rec = src[k], path = `${bucket}.${k}`;
      if(!hasOwn(m, k)){ miss(path, rec, "key not in the legacy map"); continue; }
      if(!isObj(rec)){ miss(path, rec, "record is not an object"); continue; }
      const id = m[k];
      if(hasOwn(dst, id)){ miss(path, rec, `maps to ${id}, already taken`); continue; }
      const r = {};
      for(const f of Object.keys(rec)){
        const val = rec[f];
        if(["r","w","s"].includes(f)){ if(isNum(val)) r[f] = val; else miss(`${path}.${f}`, val, "not a number"); }
        else if(wordFlags && (f === "prov" || f === "d")){ if(numOrBool(val)) r[f] = val; else miss(`${path}.${f}`, val, "not a number or boolean"); }
        else miss(`${path}.${f}`, val, "unknown record field");
      }
      dst[id] = r;
    }
    return dst;
  }
  const out = { legacy: legacyMarker(pack) };
  const handled = new Set(["v","w","s","c","sets","lessons","sessions","theme","placedOnce","soundsOpened",
    "mixChars","charsAfterHsk4","charsChoiceSeen", ...LEGACY_DROPPED]);
  out.w = recMap("w", maps.w, true);
  out.s = recMap("s", maps.s, false);
  out.sets = {};
  if(data.sets !== undefined){
    if(!isObj(data.sets)) miss("sets", data.sets, "not an object");
    else for(const k of Object.keys(data.sets)){
      const n = data.sets[k];
      if(!lv.includes(k)) miss(`sets.${k}`, n, "not a pack level");
      else if(!Number.isInteger(n) || n < 0) miss(`sets.${k}`, n, "not a non-negative integer");
      else out.sets[k] = n;
    }
  }
  if(data.lessons !== undefined){ if(isObj(data.lessons)) out.lessons = Object.assign({}, data.lessons); else miss("lessons", data.lessons, "not an object"); }
  if(data.sessions !== undefined){ if(isNum(data.sessions)) out.sessions = data.sessions; else miss("sessions", data.sessions, "not a number"); }
  if(data.theme !== undefined){ if(data.theme === null || data.theme === "light" || data.theme === "dark") out.theme = data.theme; else miss("theme", data.theme, "not null, light or dark"); }
  for(const f of ["placedOnce","soundsOpened"]) if(data[f] !== undefined){ if(numOrBool(data[f])) out[f] = data[f]; else miss(f, data[f], "not a boolean or number"); }
  const flagMap = { mixChars:"mix", charsAfterHsk4:"defer", charsChoiceSeen:"choiceSeen" };
  if(cfg){
    out.chars = { v:CHARS_PROG_VERSION, c: recMap("c", maps.c, false) };
    for(const f of Object.keys(flagMap)) if(data[f] !== undefined){ if(typeof data[f] === "boolean") out.chars[flagMap[f]] = data[f]; else miss(f, data[f], "not a boolean"); }
  } else {
    for(const f of ["c", ...Object.keys(flagMap)]) if(data[f] !== undefined) miss(f, data[f], "pack has no characters stage");
  }
  for(const f of LEGACY_DROPPED) if(data[f] !== undefined) dropped.push({path:f, value:data[f]});
  for(const k of Object.keys(data)) if(!handled.has(k)) miss(k, data[k], "unknown field");
  const prog = normalizeProg(out, pack);
  const v = validateProgShape(prog, lv);
  if(!v.ok) return {ok:false, reason:`migrated progress is invalid: ${v.reason}`};
  return {ok:true, already:false, prog, unmapped, dropped};
}

// ------------------------------------------------------------------ export
const API = { shuffle, escapeHtml, gloss, firstTwoWords, normKey,
  levelIds, levelIndexMap, levelLabel, setSizeOf, wordsByLevel, nSets,
  meaningOpts, wordOpts, gapOpts, sentenceOpts, bareForm, packArticles, articleCut, trailingCut, citationArticles, articleAgreement, visibleArticle, gapChoices, exampleSentences, unitExampleSentences, rubyCovers, highlightParts, searchWords, pronShown, audioSlot, TEST_MIN_WORDS,
  targetLang, fontFamilyOf, fontStackOf, lineHeightOf, fontsHref, scriptDisplay, rtlRuns,
  foldAccents, normalizeTyped, typingEnabled, typingLenientFor, acceptTyped,
  surfaces, sharesSurface, samePron,
  findSurface, locateWord, packSurfaces, spannedByLonger, gapMatch, gapCandidateIndices, blankSentence,
  strata, placementItemCount, placementStopIndex, applyPlacement, dedupeMisses,
  parseStored, dropUnknownSets, bootProg, lessonItemKey, lessonSayMode, applyImport, todayGates, testGates, listenPlanCount, pickVoice, speechUsable, isSamsungBrowser, wordAudio, packAudio,
  PROG_VERSION, WORD_MASTERED, SENTENCE_MASTERED, storageKey, defaultProg, validateProgShape, normalizeProg,
  markRec, weakScore, weakFirst, provPick, learnedWords, nextNewSet, currentLevelIndex, availableSentences,
  PRODUCTION_KINDS, REVIEW_SIZE, REVIEW_PRODUCTION_SHARE, kindMix, buildReviewPlan, buildRecallPlan, sentenceKind,
  READ_UNLOCK, READ_WEIGHT, readState, readingLevels, updateReadUnlocks, suggestPassage, passageLength, passageSegments,
  gradeQuestion, passageWeakWords, applyWeakWords, markPassageDone, readingStats,
  CHARS_PROG_VERSION, CHAR_SET_SIZE, CHAR_MASTERED, CHAR_BARE, REVIEW_SIZE_CHARS, CHAR_KINDS, charsConfig,
  defaultCharsProg, validateCharsShape, normalizeCharsProg, ensureChars, charRecs, markChar, answerCharChoice, setCharOrder,
  unitWord, unitReading, unitGloss, unitByWord, recordedUnits,
  charStageUnits, charSets, charSetTaught, nextCharSet, charStages, stagePath, nextStage, charsUnlocked, charsStarted, showCharChoice,
  charTier, sentenceTokenTier, rubyTiers, pronFirstOn, displayForm, pronClash, sentencePieces, sentenceDisplay, charOpts, recallCharOpts, charSoundOpts, charReadOpts, charItem,
  learnCharPlan, charReviewScore, rankUnified, unifiedReviewPlan, unifiedRecallPlan, todaySnapshot, newCharUnits, charTestPlan, pickWeighted,
  SCRIPT_PROG_VERSION, SCRIPT_MASTERED, SCRIPT_SETS_PER_SESSION, REVIEW_SIZE_SCRIPT, SCRIPT_KINDS, scriptConfig,
  defaultScriptProg, validateScriptShape, normalizeScriptProg, ensureScript, scriptRecs, scriptSkipped, setScriptSkipped, answerScriptChoice,
  scriptNotice, dismissScriptNotice, markScript, scriptMastered, scriptStageUnits, scriptSets, scriptSetTaught, nextScriptSets, scriptStages,
  recordedScriptUnits, scriptActive, scriptPool, showScriptChoice, scriptKindShape, scriptKindFits, scriptKindFor, pickScriptKind, scriptFamily, SCRIPT_MIN_OPTIONS, scriptGlyph, scriptGlyphKeys, scriptGlyphIn, scriptWordHas, graphemes, shapingClusters, scriptUnitNote, scriptUnitHeadName, searchFold, scriptSecondRight,
  scriptOpts, scriptRomanOpts, scriptExamples, scriptWordOpts, scriptJoinedForms, scriptItem, learnScriptPlan, scriptReviewScore, scriptTestPlan,
  tonesOn, stripMarks, syllableTone, markSyllable, splitSyllable, splitReading, toneHTML, pronTypingOn, pronKey, numberedForms, checkPronTyped, kanaFold, plainPronKey, affixBare, affixAlts, typeSlotKind, joinReadings, composeSpanReading, spanReadingText,
  LEGACY_DROPPED, legacyBackupKey, isLegacyRecord, migrateLegacy };
if(typeof module!=="undefined" && module.exports) module.exports = API;
if(root) root.VocabCore = API;
})(typeof window!=="undefined" ? window : (typeof globalThis!=="undefined" ? globalThis : null));
