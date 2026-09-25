// Synthetic packs for tests/characters_checks.js: a zh-like pack (every word is a unit,
// read by its pron) and a ja-like pack (only words written with non-kana glyphs are
// units, read by kana; one level has no characters stage). Deterministic, no RNG.
// Deliberate hazards: homophones (same pron, different form), a homograph pair (same
// form, different reading and gloss), a shared gloss, a word with an alt, unit files in
// non-level order, level sizes that are not multiples of the set size.
"use strict";

const ADJ = ["red","blue","green","old","new","big","small","fast","slow","hot","cold","dark","light","soft","hard","long","short","wide","deep","high","quiet","loud","sweet","sour"];
const NOUN = ["cup","box","road","tree","door","bird","fish","book","coat","hill","lamp","rope","shoe","ship","wall","well","yard","bell","coin","desk","drum","flag","gate","horn"];
const glossAt = k => `${ADJ[k % ADJ.length]} ${NOUN[Math.floor(k / ADJ.length) % NOUN.length]}`;
const cp = n => String.fromCodePoint(n);

// ---------------------------------------------------------------- zh-like
function zhLike(){
  const SYL = ["ba","po","mi","fu","de","ti","nu","le","ge","ka","he","ji","qu","xi","zhi","chi","shi","ri","zi","ci","si","ya","wo","yu"];
  const TONES = ["̄","́","̌","̀"]; // macron, acute, caron, grave
  const counts = { "1":24, "2":21, "3":30, "4":17 };
  const words = []; let k = 0, glyph = 0x4e00;
  Object.keys(counts).forEach(lv => {
    for(let i=0; i<counts[lv]; i++, k++){
      const len = [1,2,1,2,3,2][k % 6];
      let w = "", pron = "";
      for(let j=0; j<len; j++){
        w += cp(glyph++);
        // first syllable is unique per word (24 syllables x 4 tones), the rest vary
        const s = j === 0 ? SYL[k % SYL.length] : SYL[(k*5 + j*7) % SYL.length];
        const t = j === 0 ? Math.floor(k / SYL.length) % 4 : (k + j) % 4;
        pron += (s + TONES[t]).normalize("NFC");
      }
      words.push({ id: "w" + String(k+1).padStart(4, "0"), w, en: glossAt(k), lv, pron });
    }
  });
  const byId = id => words.find(w => w.id === id);
  // Homophones: same pron and form length, different form and gloss (level 1 and level 2).
  byId("w0004").pron = byId("w0002").pron;
  byId("w0030").pron = byId("w0028").pron;
  // Shared gloss across two forms (a synonym pair, level 3).
  byId("w0050").en = byId("w0048").en;
  // An alt surface.
  byId("w0060").alt = [byId("w0060").w + cp(0x9fa0)];
  // Units: one per word, t = w. File order: level 4 first, then 3, 2, 1 (word order
  // within a level), so stage ordering has to sort by level.
  const units = [];
  ["4","3","2","1"].forEach(lv => words.filter(w => w.lv === lv).forEach(w => units.push({ t: w.w, words: [w.id], lv })));
  // ids follow word order (c0001 = w0001), independent of file order
  units.forEach(u => { u.id = "c" + u.words[0].slice(1); });
  const pack = {
    key: "zhlike", name: "zh-like", tts: "zh-CN",
    levels: [{id:"1",label:"L1"},{id:"2",label:"L2"},{id:"3",label:"L3"},{id:"4",label:"L4"}],
    setSize: 10, placement: [["1",2],["2",2],["3",3],["4",3]], functionWords: [], typing: null,
    showPron: true, spaced: false,
    characters: { label: "字", stages: [{after:"3", levels:["1","2","3"]}, {after:"4", levels:["4"]}],
      setSize: 10, mastered: 3, bare: 6, learnKinds: ["charPick","charRead"], reviewKinds: ["charRead","charSound"] },
  };
  return { name: "zh-like", pack, words, units };
}

// ---------------------------------------------------------------- ja-like
function jaLike(){
  const KANA = ["か","き","く","け","こ","さ","し","す","せ","そ","た","ち","つ","て","と","な","に","ぬ","ね","の","は","ひ","ふ","へ","ほ","ま","み","む","め","も"];
  const spec = { A1:[30,20], A2:[26,18], B1:[22,15], B2:[15,10] }; // [words, of which glyph words]
  const words = []; const units = []; let k = 0, glyph = 0x6000;
  Object.keys(spec).forEach(lv => {
    const [n, nk] = spec[lv];
    for(let i=0; i<n; i++, k++){
      const kanaLen = 2 + (k % 3);
      // first two kana are unique per word (30 x 30), the rest vary
      let pron = KANA[k % KANA.length] + KANA[Math.floor(k / KANA.length) % KANA.length];
      for(let j=2; j<kanaLen; j++) pron += KANA[(k*7 + j*11) % KANA.length];
      const id = "w" + String(k+1).padStart(4, "0");
      // Every third-ish word is kana-only; the rest are glyph words (1-2 glyphs, maybe okurigana).
      const isGlyph = i < nk;
      let w;
      if(isGlyph){
        const g = (k % 4 === 0) ? 2 : 1;
        w = ""; for(let j=0; j<g; j++) w += cp(glyph++);
        if(k % 5 === 0) w += KANA[k % KANA.length]; // okurigana tail
      } else w = pron;
      words.push({ id, w, en: glossAt(k + 7), lv, pron });
      if(isGlyph) units.push({ id: "c" + id.slice(1), t: w, words: [id], lv });
    }
  });
  const byId = id => words.find(w => w.id === id);
  const unitOf = id => units.find(u => u.words[0] === id);
  // Homograph pair: w0003 takes w0001's form (different pron and gloss), both units.
  byId("w0003").w = byId("w0001").w; unitOf("w0003").t = byId("w0001").w;
  // Homophones: two different glyph words with the same kana reading (A1 and A2).
  byId("w0006").pron = byId("w0005").pron;
  byId("w0034").pron = byId("w0033").pron;
  // An explicit unit reading that differs from its word's pron field formatting.
  unitOf("w0040").reading = byId("w0040").pron;
  const pack = {
    key: "jalike", name: "ja-like", tts: "ja-JP",
    levels: [{id:"A1",label:"A1"},{id:"A2",label:"A2"},{id:"B1",label:"B1"},{id:"B2",label:"B2"}],
    setSize: 10, placement: [["A1",2],["A2",2],["B1",2],["B2",2]], functionWords: [], typing: null,
    showPron: true, spaced: false,
    characters: { label: "漢字", stages: [{after:"A2", levels:["A1","A2"]}, {after:"B1", levels:["B1"]}],
      learnKinds: ["charSound","charRead"] }, // setSize/mastered/bare/reviewKinds default
  };
  return { name: "ja-like", pack, words, units };
}

module.exports = { zhLike, jaLike };
