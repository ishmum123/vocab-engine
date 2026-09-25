// Synthetic script-primer packs for tests/script_checks.js and
// tests/validate_pack_script_checks.js (docs/SCRIPT_PRIMER.md §6). Three shapes:
//   ko: one stage, blocks composed from letters (compose, a sound:false unit, an `alt`
//       romanisation that clashes with another unit's roman);
//   fa: right-to-left, joining letters (`joins`), letters sharing a roman (ت/ط, س/ص/ث,
//       ز/ذ), pack.script.tts false (no voice);
//   ja: two stages (hira then kata), a pair sharing roman and say (じ/ぢ), a silent unit
//       (っ), dakuten `base`.
// No real pack data: the script tables are S2's. Each export is a fresh deep copy:
// {pack, words, script} with script = the script.json object ({units, notes}).
"use strict";

function lvWords(prefix, lv, list){
  return list.map(([w, en, pron], i) => Object.assign({ id: `${prefix}${lv}_${String(i + 1).padStart(2, "0")}`, w, en, lv }, pron ? { pron } : {}));
}
function basePack(key, tts, extra){
  return Object.assign({ key, name: key, tts, levels: [{ id: "A1", label: "A1" }, { id: "A2", label: "A2" }],
    placement: [["A1", 2], ["A2", 2]], typing: null, showPron: false, hasLessons: false }, extra);
}

// ------------------------------------------------------------------ ko-like
function ko(){
  const A1 = lvWords("k", "A1", [["아이","child"],["나","I"],["너","you"],["우유","milk"],["오이","cucumber"],["이","tooth"],["누나","older sister"],
    ["나라","country"],["머리","head"],["바다","sea"],["소","cow"],["가구","furniture"],["어머니","mother"]]);
  const A2 = lvWords("k", "A2", [["가게","shop"],["고기","meat"],["구두","shoes"],["다리","leg"],["도시","city"],["라디오","radio"],["마음","heart"],
    ["버스","bus"],["사자","lion"],["시계","clock"],["모자","hat"],["우리","we"],["지도","map"]]);
  const id = w => [...A1, ...A2].find(x => x.w === w).id;
  const V = (sid, t, roman, say, confuse, ex) => ({ id: sid, st: "hangul", set: 1, group: "vowel", t, name: say, roman, say, confuse, ex });
  const C = (set, group, sid, t, roman, say, extra) => Object.assign({ id: sid, st: "hangul", set, group, t, roman, say }, extra);
  const units = [
    V("ko-a", "ㅏ", "a", "아", ["ko-eo"], [[id("나"), "na"]]),
    V("ko-eo", "ㅓ", "eo", "어", ["ko-a"], [[id("너"), "neo"]]),
    V("ko-o", "ㅗ", "o", "오", ["ko-u"], [[id("오이"), "oi"]]),
    V("ko-u", "ㅜ", "u", "우", ["ko-o", "ko-eu"], [[id("우유"), "uyu"]]),
    V("ko-eu", "ㅡ", "eu", "으", ["ko-u"], [[id("버스"), "beoseu"]]),
    V("ko-i", "ㅣ", "i", "이", [], [[id("이"), "i"]]),
    C(2, "consonant", "ko-g", "ㄱ", "g", "가", { alt: ["k"], confuse: ["ko-k"], ex: [[id("가구"), "gagu"]], syll: [{ t: "가", parts: ["ㄱ","ㅏ"], roman: "ga" }] }),
    C(2, "consonant", "ko-n", "ㄴ", "n", "나", { ex: [[id("나"), "na"], [id("누나"), "nuna"]], syll: [{ t: "나", parts: ["ㄴ","ㅏ"], roman: "na" }, { t: "너", parts: ["ㄴ","ㅓ"], roman: "neo" }] }),
    C(2, "consonant", "ko-d", "ㄷ", "d", "다", { ex: [[id("바다"), "bada"]], syll: [{ t: "다", parts: ["ㄷ","ㅏ"], roman: "da" }] }),
    C(2, "consonant", "ko-r", "ㄹ", "r", "라", { alt: ["l"], ex: [[id("나라"), "nara"]], syll: [{ t: "라", parts: ["ㄹ","ㅏ"], roman: "ra" }] }),
    C(2, "consonant", "ko-m", "ㅁ", "m", "마", { ex: [[id("머리"), "meori"]], syll: [{ t: "머", parts: ["ㅁ","ㅓ"], roman: "meo" }] }),
    C(2, "consonant", "ko-b", "ㅂ", "b", "바", { ex: [[id("바다"), "bada"]], syll: [{ t: "바", parts: ["ㅂ","ㅏ"], roman: "ba" }] }),
    C(2, "consonant", "ko-s", "ㅅ", "s", "사", { ex: [[id("소"), "so"]], syll: [{ t: "소", parts: ["ㅅ","ㅗ"], roman: "so" }] }),
    { id: "ko-ng", st: "hangul", set: 2, group: "consonant", t: "ㅇ", roman: "ng", sound: false, note: "silent at the start of a block", ex: [[id("아이"), "ai"]] },
    C(3, "aspirated", "ko-j", "ㅈ", "j", "자", { confuse: ["ko-ch"], ex: [[id("모자"), "moja"]] }),
    C(3, "aspirated", "ko-ch", "ㅊ", "ch", "차", { confuse: ["ko-j"] }),
    C(3, "aspirated", "ko-k", "ㅋ", "k", "카", { confuse: ["ko-g"] }),
    C(3, "aspirated", "ko-t", "ㅌ", "t", "타", {}),
    C(3, "aspirated", "ko-p", "ㅍ", "p", "파", {}),
    C(3, "aspirated", "ko-h", "ㅎ", "h", "하", {}),
  ];
  const pack = basePack("synthko", "ko-KR", { script: { stages: [{ key: "hangul", label: "한글" }], setsPerSession: 2, mastered: 3, tts: true,
    learnKinds: ["symSound","compose"], reviewKinds: ["symSound","soundSym","compose","wordRead"],
    testKinds: { symSound: 35, soundSym: 25, wordRead: 25, symType: 15 } } });
  return { pack, words: [...A1, ...A2], script: { units, notes: [{ st: "hangul", set: 2, h: "Silent ㅇ", body: "ㅇ at the start of a block is silent." }] } };
}

// ------------------------------------------------------------------ fa-like
function fa(){
  const A1 = lvWords("f", "A1", [["بابا","father","bâbâ"],["نان","bread","nân"],["در","door","dar"],["آب","water","âb"],["پدر","father","pedar"],
    ["تب","fever","tab"],["ثبت","registration","sabt"],["سر","head","sar"],["صبر","patience","sabr"],["طب","medicine","tebb"],["زن","woman","zan"],
    ["ذرت","corn","zorrat"],["مادر","mother","mâdar"]]);
  const A2 = lvWords("f", "A2", [["کتاب","book","ketâb"],["گل","flower","gol"],["خانه","house","khâne"],["شب","night","shab"],["روز","day","ruz"],
    ["دل","heart","del"],["کار","work","kâr"],["راه","road","râh"],["شهر","city","shahr"],["چای","tea","chây"],["ماه","moon","mâh"],["سال","year","sâl"],["دوست","friend","dust"]]);
  const id = w => [...A1, ...A2].find(x => x.w === w).id;
  const U = (set, group, sid, t, name, roman, joins, confuse, ex) => ({ id: sid, st: "abjad", set, group, t, name, roman, joins, confuse, ex });
  const units = [
    U(1, "alef", "fa-alef", "ا", "alef", "â", "right", [], [[id("بابا"), "bâbâ"]]),
    U(1, "be", "fa-be", "ب", "be", "b", "dual", ["fa-pe","fa-te","fa-se"], [[id("بابا"), "bâbâ"], [id("تب"), "tab"]]),
    U(1, "be", "fa-pe", "پ", "pe", "p", "dual", ["fa-be"], [[id("پدر"), "pedar"]]),
    U(1, "be", "fa-te", "ت", "te", "t", "dual", ["fa-be","fa-se"], [[id("تب"), "tab"]]),
    U(1, "be", "fa-se", "ث", "se", "s", "dual", ["fa-te","fa-be"], [[id("ثبت"), "sabt"]]),
    U(1, "dal", "fa-dal", "د", "dal", "d", "right", ["fa-zal"], [[id("در"), "dar"]]),
    U(1, "re", "fa-re", "ر", "re", "r", "right", ["fa-ze"], [[id("در"), "dar"]]),
    U(1, "mim", "fa-mim", "م", "mim", "m", "dual", [], [[id("مادر"), "mâdar"]]),
    U(1, "nun", "fa-nun", "ن", "nun", "n", "dual", [], [[id("نان"), "nân"]]),
    U(2, "sin", "fa-sin", "س", "sin", "s", "dual", ["fa-sad","fa-se"], [[id("سر"), "sar"]]),
    U(2, "sad", "fa-sad", "ص", "sad", "s", "dual", ["fa-sin"], [[id("صبر"), "sabr"]]),
    U(2, "ta", "fa-ta", "ط", "tâ", "t", "dual", ["fa-te"], [[id("طب"), "tebb"]]),
    U(2, "re", "fa-ze", "ز", "ze", "z", "right", ["fa-re","fa-zal"], [[id("زن"), "zan"]]),
    U(2, "dal", "fa-zal", "ذ", "zal", "z", "right", ["fa-dal","fa-ze"], [[id("ذرت"), "zorrat"]]),
  ];
  const pack = basePack("synthfa", "fa-IR", { rtl: true, langTag: "fa", fontFamily: "Vazirmatn, sans-serif",
    script: { stages: [{ key: "abjad", label: "الفبا" }], tts: false,
      learnKinds: ["symSound","formFind"], reviewKinds: ["symSound","formMatch","formFind","wordRead","wordHear"],
      testKinds: { symSound: 40, formMatch: 30, wordRead: 30 } } });
  return { pack, words: [...A1, ...A2], script: { units, notes: [{ st: "abjad", set: 1, h: "Short vowels", body: "Short vowels are not written." }] } };
}

// ------------------------------------------------------------------ ja-like
function ja(){
  const A1 = lvWords("j", "A1", [["愛","love","あい"],["家","house","いえ"],["上","above","うえ"],["青","blue","あお"],["顔","face","かお"],["池","pond","いけ"],
    ["聞く","to hear","きく"],["酒","sake","さけ"],["寿司","sushi","すし"],["画家","painter","がか"],["火事","fire","かじ"],["鼻血","nosebleed","はなぢ"],
    ["切手","stamp","きって"],["アイス","ice cream","アイス"],["ケーキ","cake","ケーキ"]]);
  const A2 = lvWords("j", "A2", [["空","sky","そら"],["海","sea","うみ"],["山","mountain","やま"],["川","river","かわ"],["花","flower","はな"],["雨","rain","あめ"],
    ["雪","snow","ゆき"],["夜","night","よる"],["朝","morning","あさ"],["道","road","みち"],["駅","station","えき"],["店","shop","みせ"],["窓","window","まど"]]);
  const id = w => [...A1, ...A2].find(x => x.w === w).id;
  const H = (set, group, sid, t, roman, extra) => Object.assign({ id: sid, st: "hira", set, group, t, roman, say: t }, extra);
  const K = (set, group, sid, t, roman, extra) => Object.assign({ id: sid, st: "kata", set, group, t, roman, say: t }, extra);
  const units = [
    H(1, "vowel", "ja-a", "あ", "a", { confuse: ["ja-o"], ex: [[id("愛"), "ai"]] }),
    H(1, "vowel", "ja-i", "い", "i", { ex: [[id("家"), "ie"]] }),
    H(1, "vowel", "ja-u", "う", "u", { ex: [[id("上"), "ue"]] }),
    H(1, "vowel", "ja-e", "え", "e", { ex: [[id("家"), "ie"]] }),
    H(1, "vowel", "ja-o", "お", "o", { confuse: ["ja-a"], ex: [[id("青"), "ao"]] }),
    H(2, "k", "ja-ka", "か", "ka", { ex: [[id("顔"), "kao"]] }),
    H(2, "k", "ja-ki", "き", "ki", { confuse: ["ja-sa"], ex: [[id("聞く"), "kiku"]] }),
    H(2, "k", "ja-ku", "く", "ku", { ex: [[id("聞く"), "kiku"]] }),
    H(2, "k", "ja-ke", "け", "ke", { ex: [[id("池"), "ike"]] }),
    H(2, "k", "ja-ko", "こ", "ko", {}),
    H(3, "s", "ja-sa", "さ", "sa", { confuse: ["ja-ki"], ex: [[id("酒"), "sake"]] }),
    H(3, "s", "ja-shi", "し", "shi", { ex: [[id("寿司"), "sushi"]] }),
    H(3, "s", "ja-su", "す", "su", { ex: [[id("寿司"), "sushi"]] }),
    H(3, "s", "ja-se", "せ", "se", {}),
    H(3, "s", "ja-so", "そ", "so", {}),
    H(4, "dakuten", "ja-ga", "が", "ga", { base: "ja-ka", ex: [[id("画家"), "gaka"]] }),
    H(4, "dakuten", "ja-ji", "じ", "ji", { base: "ja-shi", confuse: ["ja-dji"], ex: [[id("火事"), "kaji"]] }),
    H(4, "dakuten", "ja-dji", "ぢ", "ji", { say: "じ", confuse: ["ja-ji"], ex: [[id("鼻血"), "hanaji"]] }),
    { id: "ja-tsu-small", st: "hira", set: 4, group: "small", t: "っ", roman: "(double)", sound: false, note: "doubles the next consonant", ex: [[id("切手"), "kitte"]] },
    K(1, "vowel", "ja-ka-a", "ア", "a", { base: "ja-a", ex: [[id("アイス"), "aisu"]] }),
    K(1, "vowel", "ja-ka-i", "イ", "i", { base: "ja-i", ex: [[id("アイス"), "aisu"]] }),
    K(1, "vowel", "ja-ka-u", "ウ", "u", { base: "ja-u" }),
    K(1, "vowel", "ja-ka-e", "エ", "e", { base: "ja-e" }),
    K(1, "vowel", "ja-ka-o", "オ", "o", { base: "ja-o" }),
    K(2, "k", "ja-ka-ka", "カ", "ka", { base: "ja-ka" }),
    K(2, "k", "ja-ka-ki", "キ", "ki", { base: "ja-ki", ex: [[id("ケーキ"), "kēki"]] }),
    K(2, "k", "ja-ka-ku", "ク", "ku", { base: "ja-ku" }),
    K(2, "k", "ja-ka-ke", "ケ", "ke", { base: "ja-ke", ex: [[id("ケーキ"), "kēki"]] }),
    K(2, "k", "ja-ka-ko", "コ", "ko", { base: "ja-ko" }),
  ];
  const pack = basePack("synthja", "ja-JP", { script: { stages: [{ key: "hira", label: "ひらがな" }, { key: "kata", label: "カタカナ" }],
    learnKinds: ["symSound","soundSym"], reviewKinds: ["symSound","soundSym","wordRead"] } });
  return { pack, words: [...A1, ...A2], script: { units, notes: [{ st: "hira", set: 4, h: "Small tsu", body: "っ doubles the next consonant." }] } };
}

module.exports = { ko, fa, ja };
