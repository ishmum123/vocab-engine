"""Korean (ko): everything Korean-specific in the pack pipeline.

Tagger: spaCy ko_core_news_sm (UD Korean Kaist). It tags whole eojeols (the
written word between spaces, stem plus attached particles or endings: 학교에서,
먹었어요) and often leaves irregular forms unsplit, so fix_sentence re-reads
every eojeol with KoMorph, an analyser over the kaikki (English Wiktionary)
lexicon:

- noun / pronoun / adverb + a particle chain (학교에서는 = 학교 + 에서 + 는);
- noun + copula 이다 (학생이에요, 의사예요, 학생이었어요);
- noun + 하다 when X하다 is not a headword (운동해요 -> 운동 + 하다);
- verbs and adjectives: the conjugation tables Wiktionary gives for every
  verb (먹었어요, 들었어요, 아세요) plus stem + ending analysis over three stem
  bases taken from those tables (raw 먹-, infinitive 먹어-, "eu" 먹으-), so
  irregular stems (듣다 들어, 알다 아세요, 춥다 추워) come from the dictionary.
  The lemma is the -다 form; spaCy's tag class and a wordfreq prior choose
  between readings.

Each eojeol becomes consecutive substring tokens: the content word, then one
token per particle / copula, tagged X so sentence length counts eojeols;
post_resolve links them to fixed keys (-은/는, -이/가, -에서, -이다 ...).
Fused forms (내가, 난, 이건, 거예요) come from a hand table. Sino-Korean
numerals (keys "일:num" ...) and the native determiner forms (한 두 세 네)
link only before a counter. A few noun homographs (눈 eye/snow, 차 car/tea)
are split by the English translation.

wordfreq tokenises Korean with mecab-ko, which the build does not install:
zipf_frequency(w, "ko") is routed to the wordfreq ko list itself (ko_zipf).

The A1 core list, gloss overrides and generated sentences live in the
korean repo (tools/).
"""
import gzip
import json
import math
import re
from collections import Counter, defaultdict

from .base import LanguageSpec, SENSITIVE_EN, SENSITIVE_GLOSS_EN, TATOEBA_ENG, TATOEBA_AUDIO, DEFAULT_GROUP_KPOS, drop_all_re

# =============================================================================
# Hangul and the eojeol analyser
# =============================================================================
S0, NV, NT = 0xAC00, 21, 28
T_JAMO = ["", "ㄱ", "ㄲ", "ㄳ", "ㄴ", "ㄵ", "ㄶ", "ㄷ", "ㄹ", "ㄺ", "ㄻ", "ㄼ", "ㄽ", "ㄾ", "ㄿ", "ㅀ", "ㅁ", "ㅂ",
          "ㅄ", "ㅅ", "ㅆ", "ㅇ", "ㅈ", "ㅊ", "ㅋ", "ㅌ", "ㅍ", "ㅎ"]
T_IDX = {j: i for i, j in enumerate(T_JAMO) if j}
HANGUL_RE = re.compile(r"^[가-힣]+$")


def is_syl(c):
    return "가" <= c <= "힣"


def fin(c):
    return (ord(c) - S0) % NT if is_syl(c) else 0


def vowel(c):
    return ((ord(c) - S0) // NT) % NV


def set_fin(c, t):
    return chr(ord(c) - fin(c) + t)


def join(a, e):
    """a + ending, where an ending may start with a batchim jamo (ㄴ ㄹ ㅁ ㅂ ㅆ)
    that merges into a's last syllable: join("가", "ㅂ니다") = 갑니다."""
    if not e:
        return a
    if e[0] in T_IDX:
        if not a or not is_syl(a[-1]) or fin(a[-1]):
            return None
        return a[:-1] + set_fin(a[-1], T_IDX[e[0]]) + e[1:]
    return a + e


def splits(E):
    """(base, rest) pairs of an eojeol: at every syllable boundary, and inside
    a syllable at its batchim (갔어요 -> 가 + ㅆ어요)."""
    out = []
    for k in range(1, len(E) + 1):
        out.append((E[:k], E[k:]))
        t = fin(E[k - 1])
        if t:
            out.append((E[:k - 1] + set_fin(E[k - 1], 0), T_JAMO[t] + E[k:]))
    return out


def has_batchim(w):
    return bool(w) and fin(w[-1]) != 0


# ---- endings ----------------------------------------------------------------
# after the raw stem (먹-, 가-, 알-): connective, adnominal, sentence endings
RAW_E = """고 고요 고서 고는 지 지요 죠 지만 지도 지는 지를 지않 는 는데 는데요 는지 는지요 는구나 는군요 는다 는다고
는다는 는대 는대요 는다면 는가 는가요 는걸 는걸요 다 다가 다고 다는 다니 다면 다니까 던 던데 던데요 던가 게 게끔
겠다 겠어 겠어요 겠습니다 겠습니까 겠네요 겠네 겠지 겠지요 겠죠 겠는데 겠는데요 겠고 겠지만 겠니 겠냐 겠군요 겠구나
겠다고 겠다는 겠어서 기 기가 기를 기는 기도 기에 기로 기만 기까지 기엔 기에는 기보다 길 길요 게는 대 대요 잖니 진 네 네요 자 자고 자마자 자면
거나 거든 거든요 도록 든지 든가 잖아 잖아요 잖아요 느냐 냐 나 나요 니 습니다 습니까 습니다만 구나 군요 군 더라 더라고
더라고요 더니 더라도 곤 길래 소 는가 ㄴ다 ㄴ다고 ㄴ다는 ㄴ대 ㄴ대요 ㄴ다면""".split()
# past-tense tails after -었/-았/-였 (joined as ㅆ + tail onto the infinitive base)
PAST_T = """다 어 어요 어서 어도 어야 습니다 습니까 는데 는데요 지만 고 을 을까 을까요 을지 을걸 던 던데 겠다 겠어 겠어요
겠네요 겠지 겠죠 네 네요 잖아 잖아요 죠 지 지요 니 냐 나 나요 는지 더라 더라고요 군요 구나 으면 으니까 거든 거든요
대 대요 다고 다는 다가 다면 기 기에 기도 기를 기가 으나 으며 음 는가 소 을때 을텐데""".split()
# after the infinitive (먹어-, 가-, 해-, 들어-)
A_E = ["요", "서", "서요", "서는", "서도", "선", "도", "도요", "야", "야지", "야지요", "야죠", "야겠다", "야겠어요",
       "야겠어", "야겠네", "야겠네요", "야겠지", "야겠습니다", "야돼", "야돼요", "라",
       "라고", "라는", "봐요"] + ["ㅆ" + t for t in PAST_T] + ["ㅆ었" + t for t in ("다", "어요", "는데", "어")]
# after the "eu" stem (먹으-, 가-, 들으-, 아- for 알다)
U_E = """니까 니까요 니 면 면서 면요 며 러 려 려고 려고요 려면 려는 려나 라 세요 셔요 셔서 셨어요 셨다 셨어 셨습니다
셨습니까 셨나요 셨는데 셨죠 셨지만 셨고 셨으면 셨을 셨던 셨네요 셨잖아요 시 시고 시는 시다 시지 시지요 시죠 시지만
시네요 시면 시니까 시겠어요 시겠습니까 시겠습니다 시겠다 시겠지요 시겠죠 시거나 시기 시길 시는데 시다가 시러
시려고 십시오 십니다 십니까 신 실 심 ㅂ시다 ㅂ니다 ㅂ니까 ㄴ ㄴ데 ㄴ데요 ㄴ지 ㄴ지요 ㄴ가 ㄴ가요 ㄴ가봐요 ㄴ걸
ㄴ걸요 ㄴ적 ㄴ후 ㄴ다 ㄴ다고 ㄴ다는 ㄴ대 ㄴ대요 ㄴ다면 ㄴ다니 ㄴ다니까 ㄹ ㄹ게 ㄹ게요 ㄹ까 ㄹ까요 ㄹ래 ㄹ래요 ㄹ거야
ㄹ거예요 ㄹ겁니다 ㄹ걸 ㄹ걸요 ㄹ지 ㄹ지도 ㄹ지요 ㄹ수록 ㄹ때 ㄹ텐데 ㄹ테니까 ㄹ께 ㄹ께요 ㄹ라 ㄹ라고 ㄹ려고 ㅁ
ㅁ으로 오 오니 오면""".split()
# honorific -시- between the "eu" stem and any ending (가시고, 드셨어요, 좋아하시나요)
HON_E = sorted({x for x in [join("시", e) for e in RAW_E] + [join("셔", e) for e in A_E] +
                [join("시", e) for e in U_E if not e.startswith(("시", "셔", "셨", "세", "십"))] +
                ["세요", "세", "셔요", "십시오", "세요?"] if x})
A_E_SET = set(A_E)
RAW_E_SET = set(RAW_E)
U_E_SET = set(U_E) | set(HON_E)

# copula 이다 after a noun: the tail after 이 (consonant-final nouns write 이;
# vowel-final nouns drop or contract it: 의사예요, 의사였어요, 의사라서)
COP_T = """다 에요 ㅂ니다 ㅂ니까 야 었어요 었다 었어 었습니다 었습니까 었는데 었지만 었고 었으면 었을 었던 었나요 었죠
었잖아요 었네요 고 지만 지 지요 죠 ㄴ데 ㄴ데요 ㄴ ㄹ 라서 라고 라는 란 라도 라면 면 니까 네요 네 세요 신 시다
어서 ㄴ지 ㄴ지요 ㄴ가 ㄴ가요 ㄹ까 ㄹ까요 ㄹ거예요 ㄹ거야 ㄹ겁니다 ㄹ지도 겠지 겠죠 겠네요 겠지요 잖아요 잖아 거든요
거든 며 나 나요 든지 기 기도 기에 ㅁ 다고 다는 냐 니 군요 구나 던 ㄴ가봐요 에요? 십니다 십니까 셨어요 셨습니다
시죠""".split()


def _copula_forms():
    cons, vow = set(), set()
    for t in COP_T:
        f = join("이", t)
        if f:
            cons.add(f)
            vow.add(f)
    for t in COP_T:
        if t[0] in T_IDX or t.startswith(("에", "었", "어")):
            continue
        vow.add(t)            # 의사라서, 의사죠, 의사야
    for f in list(cons):
        if f.startswith("이에"):
            vow.add("예" + f[2:])            # 의사예요
        elif f.startswith("이었"):
            vow.add("였" + f[2:])            # 의사였어요
        elif f.startswith("이어"):
            vow.add("여" + f[2:])            # 의사여서
    return cons, vow


COP_CONS, COP_VOW = _copula_forms()

# particles: surface -> (key lemma, allomorph condition): C after a consonant,
# V after a vowel, VL after a vowel or ㄹ, None any
PARTICLES = {
    "이": ("-이/가", "C"), "가": ("-이/가", "V"),
    "은": ("-은/는", "C"), "는": ("-은/는", "V"),
    "을": ("-을/를", "C"), "를": ("-을/를", "V"),
    "과": ("-와/과", "C"), "와": ("-와/과", "V"),
    "으로": ("-(으)로", "C-L"), "로": ("-(으)로", "VL"),
    "이랑": ("-(이)랑", "C"), "랑": ("-(이)랑", "V"),
    "이나": ("-(이)나", "C"), "나": ("-(이)나", "V"),
    "이라도": ("-(이)라도", "C"), "라도": ("-(이)라도", "V"),
    "에": ("-에", None), "에서": ("-에서", None), "에게": ("-에게", None), "한테": ("-한테", None),
    "께": ("-께", None), "께서": ("-께서", None), "의": ("-의", None), "도": ("-도", None),
    "만": ("-만", None), "부터": ("-부터", None), "까지": ("-까지", None), "보다": ("-보다", None),
    "처럼": ("-처럼", None), "하고": ("-하고", None), "마다": ("-마다", None), "밖에": ("-밖에", None),
    "씩": ("-씩", None),
    "조차": ("-조차", None), "마저": ("-마저", None), "요": ("-요", None), "에게서": ("-에게서", None),
    "한테서": ("-한테서", None), "으로서": ("-(으)로서", "C-L"), "로서": ("-(으)로서", "VL"),
    "으로부터": ("-(으)로부터", "C-L"), "로부터": ("-(으)로부터", "VL"), "같이": ("-같이", None),
    "만큼": ("-만큼", None), "대로": ("-대로", None), "뿐": ("-뿐", None), "쯤": ("-쯤", None),
    "들": ("-들", None), "엔": ("-에", None), "에선": ("-에서", None), "에겐": ("-에게", None),
    "한텐": ("-한테", None), "든": ("-든지", None), "든지": ("-든지", None), "이든": ("-든지", "C"),
    "이든지": ("-든지", "C"), "아": ("-아/야", "C"),
}
# "서" = 에서 only after these place words (여기서, 어디서)
SEO_HOSTS = {"여기", "거기", "저기", "어디", "이곳", "그곳", "저곳", "혼자", "둘이", "셋이", "데"}
# particles after which only -요 may follow (학생이에요 is not 학생 + 이 + 에 + 요)
TERMINAL = {"이", "가", "은", "는", "을", "를", "의", "도", "이나", "나", "라도", "이라도", "든", "든지", "이든",
            "이든지", "아", "엔", "에선", "에겐", "한텐", "요"}
# particles that may follow another particle (에서는, 에도, 까지만, 에게서도)
SECOND = {"은", "는", "도", "만", "요", "의", "가", "를", "을", "이", "까지", "부터", "에", "에서", "이나", "나",
          "라도", "이라도", "으로", "로"}
ADV_PARTICLES = {"요", "도", "는", "은", "만", "씩", "까지", "부터", "은요", "는요", "도요", "만요", "나", "이나", "만은",
                 "까지는", "부터는", "까지도"}


def _agree(host, surf, cond):
    if cond is None:
        return True
    last = host[-1] if host else ""
    b = fin(last) if last and is_syl(last) else 0
    if cond == "C":
        return b != 0
    if cond == "V":
        return b == 0
    if cond == "VL":
        return b == 0 or b == T_IDX["ㄹ"]
    if cond == "C-L":
        return b != 0 and b != T_IDX["ㄹ"]
    return True


def particle_chains(host, rest, depth=0):
    """Ways to read `rest` as particles after `host`: [[(surface, key), ...]]."""
    if not rest:
        return [[]]
    if depth >= 3:
        return []
    out = []
    for k in range(1, len(rest) + 1):
        p = rest[:k]
        if p == "서" and depth == 0 and host in SEO_HOSTS:
            info = ("-에서", None)
        else:
            info = PARTICLES.get(p)
        # the plural 들 takes any particle after it (사람들에게)
        if not info or (depth and p not in SECOND and p != "요" and not (depth == 1 and host == "들")):
            continue
        if depth and host in TERMINAL and p != "요":
            continue
        if not _agree(host, p, info[1]):
            continue
        if p == "아" and len(host) < 2:
            continue          # the vocative follows a name or kin word (작아 is 작다, not 작 + 아)
        for tail in particle_chains(p, rest[k:], depth + 1):
            out.append([(p, info[0])] + tail)
    return out


# ---- regular infinitive for verbs Wiktionary gives no table for --------------
def regular_infinitive(stem):
    if not stem:
        return None
    if stem.endswith("하"):
        return stem[:-1] + "해"
    last = stem[-1]
    v = vowel(last)
    b = fin(last)
    bright = v in (0, 8)            # ㅏ ㅗ
    if b:
        return stem + ("아" if bright else "어")
    # vowel stems contract: 가+아 = 가, 오+아 = 와, 주+어 = 줘, 쓰+어 = 써, 마시+어 = 마셔
    base = ord(last) - S0 - (v * NT)
    table = {0: 0, 4: 4, 8: 9, 13: 14, 18: 4, 20: 6, 1: 1, 5: 5, 11: 11}
    if v in table:
        return stem[:-1] + chr(S0 + base + table[v] * NT)
    return stem + ("아" if bright else "어")


def regular_eu(stem):
    if not stem:
        return None
    b = fin(stem[-1])
    return stem + "으" if b and b != T_IDX["ㄹ"] else stem


# grammatical form-of glosses (not a word of its own); "humble form of 주다"
# (드리다) and "honorific form of" lines are words
NONLEMMA_GLOSS_RE = re.compile(r"\b(?:alternative|obsolete|archaic|dialectal|nonstandard|misspelled|eye dialect) "
                               r"(?:form|spelling) of\b|\b(?:infinitive|adnominal|determiner|nominal|sequential|"
                               r"conjunctive|connective|past|present|future|imperative|hortative|interrogative|"
                               r"declarative|polite|formal|plain|intimate)(?: \w+){0,3} (?:form )?of\b|"
                               r"^(?:contraction|abbreviation|clipping|short) (?:of|for)\b|^(?:form|inflection) of\b",
                               re.I)
# verbs that turn a noun into a verb when written onto it (부탁드립니다,
# 해고당했다, 제공됩니다, 사랑받고): noun + verb, both linked
NOUN_VERBS = {"하다", "되다", "받다", "당하다", "드리다", "시키다"}
# standalone spellings read only through the closed table (이 = this, not
# kaikki's "tooth" or the Sino numeral two, which links only before a counter)
CLOSED_ONLY = {"이", "그", "저"}
# verbs never read (homographs of commoner forms: 마 "don't" is 말다, not 마다
# "to refuse"; 입니다 is the copula, not 이다 "to carry on the head";
# 해야하다 is 해야 하다 written together; 저런 is 저렇다)
DROP_VERBS = {"마다", "이다", "해야하다", "저리하다", "이리하다", "그리하다", "그을다", "끼이다", "데다", "고다", "때다"}
AUX_AFTER_INF = {"보다", "주다", "드리다", "버리다", "놓다", "두다", "내다", "가다", "오다", "있다", "지다", "대다"}
KPOS_GROUP = {"noun": "NOUN", "counter": "NOUN", "pron": "PRON", "num": "NUM", "adv": "ADV", "det": "DET",
              "intj": "INTJ", "verb": "VERB", "adj": "ADJ", "conj": "ADV"}
NOMINAL_POS = ("noun", "counter", "pron", "num")
HON_FORM = {"humble", "honorific"}      # 드리다 (humble 주다) is "form-of" but a word of its own
SKIP_SENSE_TAGS = {"form-of", "alt-of", "misspelling", "obsolete", "archaic", "dialectal", "North-Korea",
                   "Middle-Korean", "Early", "abbreviation", "Gyeongsang", "Jeolla", "Jeju", "Hamgyong",
                   "Pyongan", "Chungcheong", "Gangwon", "Yukjin", "Hwanghae", "nonstandard", "Internet"}
SKIP_FORM_TAGS = {"romanization", "hanja", "table-tags", "inflection-template", "class", "alternative",
                  "dialectal", "Gyeongsang", "Jeolla", "North-Korea", "nonstandard", "misspelling", "Early",
                  "Modern"}




class KoMorph:
    """Eojeol analyser over the kaikki lexicon: analyse(eojeol, hint) -> (kind, pieces).

    `hand`: eojeol -> pieces (fused pronoun/것 contractions, greetings);
    `closed`: word -> [(lemma key, group)] closed-class readings (numerals,
    demonstratives) tried like dictionary words; `canon`: lemma -> group, the
    one group a closed or time word is always given (오늘 is never split into
    a noun and an adverb word); `zipf`: morpheme -> wordfreq zipf, the prior
    between readings (먹지 "blotting paper" vs 먹다, 마시다 vs honorific 마다)."""

    def __init__(self, kaikki_path, hand=None, closed=None, canon=None, zipf=None):
        self.pos = defaultdict(set)          # headword -> kaikki POS set (usable senses)
        self.names = set()                   # kaikki proper-name headwords
        self.alias = {}                      # contraction headword -> full headword (갖다 -> 가지다)
        self.first_pos = {}                  # headword -> the POS Wiktionary lists first
        self.pos_order = defaultdict(list)   # headword -> its POS in Wiktionary order
        self.forms = defaultdict(dict)       # conjugated form -> {lemma: cost}
        self.raw = defaultdict(set)          # stem base -> {lemma}
        self.inf = defaultdict(set)          # infinitive base (먹어, 가, 들어) -> {lemma}
        self.eu = defaultdict(set)           # "eu" base (먹으, 가, 들으, 아) -> {lemma}
        self.raw_l = defaultdict(set)        # ㄹ-dropped stem (아- of 알다, 힘드- of 힘들다) -> {lemma}
        self.hand = hand or {}
        self.closed = closed or {}
        self.canon = canon or {}
        self.zipf = zipf or (lambda w: 0.0)
        self.surface_counts = None           # subtitle list {eojeol: count} (set_evidence)
        self.lemma_forms = defaultdict(set)  # verb lemma -> its conjugation-table forms
        self.gloss_en = defaultdict(set)     # verb/adjective headword -> English words of its first senses
        self.noun_en = defaultdict(set)      # noun/adverb headword -> English words of its first senses
        self._ev = {}
        self._cache = {}
        self._load(kaikki_path)

    CONTRACTION_RE = re.compile(r"^(?:contraction|short|abbreviation|clipping|colloquial form) (?:of|for) ([가-힣]+)")

    def _alias_target(self, d):
        """A headword whose every sense is "contraction of X" (갖다 of 가지다,
        재밌다 of 재미있다, 얘기 of 이야기): its forms count as X."""
        ss = [s for s in d.get("senses", []) if s.get("glosses")]
        tg = set()
        for s in ss:
            m = self.CONTRACTION_RE.match(s["glosses"][-1])
            if not m:
                return None
            tg.add(m.group(1))
        return tg.pop() if len(tg) == 1 else None

    def _load(self, path):
        verbs = {}
        aliased = []
        with gzip.open(path, "rt", encoding="utf-8") as f:
            for line in f:
                d = json.loads(line)
                w, p = d.get("word", ""), d.get("pos", "")
                if not HANGUL_RE.match(w):
                    continue
                if p == "noun" and any(h.get("name") == "ko-pos" and (h.get("args") or {}).get("1") == "ideophone"
                                       for h in d.get("head_templates") or ()):
                    p = "adv"           # Wiktionary files ideophones (딱, 점점, 깜짝) as nouns; they work as adverbs
                if p == "name":
                    self.names.add(w)
                    continue
                if p not in KPOS_GROUP:
                    continue
                al = self._alias_target(d)
                if al:
                    self.alias[w] = al
                    if p in ("verb", "adj") and w.endswith("다"):
                        aliased.append((w, al, d.get("forms", [])))
                    continue
                senses = [s for s in d.get("senses", []) if s.get("glosses") and
                          not (set(s.get("tags", [])) & (SKIP_SENSE_TAGS - {"form-of"}
                                                          if set(s.get("tags", [])) & HON_FORM else SKIP_SENSE_TAGS)) and
                          (not s.get("form_of") or set(s.get("tags", [])) & HON_FORM) and
                          not s.get("alt_of") and not NONLEMMA_GLOSS_RE.search(s["glosses"][-1])]
                if not senses:
                    continue
                self.pos[w].add(p)
                if p in ("verb", "adj", "noun", "adv"):
                    for sn in senses[:3]:
                        (self.gloss_en if p in ("verb", "adj") else self.noun_en)[w] |= set(
                            re.findall(r"[a-z]+", re.sub(r"\(.*?\)", "", sn["glosses"][-1].lower())))
                self.first_pos.setdefault(w, p)
                if p not in self.pos_order[w]:
                    self.pos_order[w].append(p)
                if p in ("verb", "adj") and w in DROP_VERBS:
                    self.pos[w].discard(p)
                    if not self.pos[w]:
                        del self.pos[w]
                    continue
                if p in ("verb", "adj") and w.endswith("다") and len(w) >= 2:
                    verbs.setdefault(w, []).extend(d.get("forms", []))
        for w, tgt, fs in aliased:
            if tgt in verbs:
                verbs.setdefault(w, []).extend(fs)
        # a contraction entry beside real ones (새 "new" beside 새 = 사이, 목 "neck"
        # beside 목 = 목요일) is not read as the contraction
        self.alias = {w: t for w, t in self.alias.items() if t in self.pos and
                      (w.endswith("다") or not (self.pos.get(w, set()) - {"verb", "adj"}))}
        for head, fs in sorted(verbs.items()):
            lem = self.alias.get(head, head)
            stem = head[:-1]
            self.raw[stem].add(lem)
            infs, eus = set(), set()
            for x in fs:
                form, tags = x.get("form", ""), set(x.get("tags", []))
                if not HANGUL_RE.match(form) or tags & SKIP_FORM_TAGS:
                    continue
                hon = form.startswith(stem + "시") or form.startswith(stem + "셔") or form.startswith(stem + "셨") \
                    or form.startswith(stem + "십") or form.startswith(stem + "신") or \
                    any(form.startswith(u + s) for u in eus for s in ("시", "셔", "셨", "십", "신", "세"))
                c = 0.5 if hon and not lem.endswith("시다") else 0
                if form not in self.forms or lem not in self.forms[form] or c < self.forms[form][lem]:
                    self.forms[form][lem] = c
                if "determiner" not in tags:
                    self.lemma_forms[lem].add(form)     # evidence: not the 집을-like adnominal forms
                if "infinitive" in tags:
                    infs.add(form)
                elif "sequential" in tags and form.endswith("니"):
                    eus.add(form[:-1])
                elif "conditional" in tags and "formal" in tags and form.endswith("면"):
                    eus.add(form[:-1])
                elif "determiner" in tags and "present" in tags and form.endswith("는"):
                    if not form[:-1].endswith("시") and form[:-1] != stem:
                        self.raw_l[form[:-1]].add(lem)    # 아는 -> 아- (ㄹ drops before ㄴ/ㅂ/ㅅ)
                elif "determiner" in tags and "past" in tags and fin(stem[-1]) == T_IDX["ㄹ"] and \
                        len(form) == len(stem) and fin(form[-1]) == T_IDX["ㄴ"]:
                    self.raw_l[form[:-1] + set_fin(form[-1], 0)].add(lem)   # 힘든 -> 힘드- (힘드네요)
                elif "past" in tags and "formal" in tags and "indicative" in tags and form.endswith("다") \
                        and len(form) >= 2 and fin(form[-2]) == T_IDX["ㅆ"] and not form[:-2].endswith("시"):
                    infs.add(form[:-2] + set_fin(form[-2], 0))      # 알았다 -> 알아
            if not infs:
                ri = regular_infinitive(stem)
                if ri:
                    infs.add(ri)
            if not eus:
                eus.add(regular_eu(stem))
            for a in infs:
                if not (a.endswith("시어") or a.endswith("셔")) or lem.endswith("시다"):
                    self.inf[a].add(lem)
            for u in eus:
                if not u.endswith("시") or lem.endswith("시다"):
                    self.eu[u].add(lem)

    # ---- lookups -----------------------------------------------------------
    def verb_group(self, lem, hint=None):
        """VERB or ADJ: the listed group of a closed/core word, else the only
        one Wiktionary has, else the tagger's (paa: adjective), else the
        first Wiktionary lists (크다 "to be big" before "to grow")."""
        if lem in self.canon:
            return self.canon[lem]
        ps = self.pos.get(lem, set())
        if "verb" in ps and "adj" in ps:
            if hint == "pa":
                return "ADJ"
            if hint == "pv":
                return "VERB"
            return "ADJ" if self.first_pos.get(lem) == "adj" else "VERB"
        return "ADJ" if "adj" in ps else "VERB"

    def set_evidence(self, surface_counts):
        self.surface_counts = surface_counts
        self._ev = {}
        self._cache = {}

    def prior(self, lem, group):
        """log10 of the subtitle-list evidence for a reading (see evidence);
        without a subtitle list, wordfreq zipf of the morpheme."""
        if self.surface_counts is not None:
            return self.evidence(lem, group)
        return self.zipf_prior(lem, group)

    NOUN_TAILS = ("", "에", "에서", "의", "도", "만", "까지", "한테", "에게", "처럼", "보다", "하고")
    NOUN_TAILS_C = ("이", "은", "을", "으로", "과", "이에요", "이야", "이랑")
    NOUN_TAILS_V = ("가", "는", "를", "로", "와", "예요", "야", "랑")

    def evidence(self, lem, group):
        """How often the subtitle list writes a reading, read off plain
        spellings (no analysis): a noun alone and with common particles (집,
        집에, 집이, 집으로 - 먹 "inkstick" almost never), a verb by the forms
        of its conjugation table (먹었어, 먹고, 먹어요). Scaled to zipf-like
        units (x1.33 per log10 count)."""
        key = (lem, group in ("VERB", "ADJ"))
        if key not in self._ev:
            sc = self.surface_counts
            if key[1] and lem.endswith("다"):
                # a form spelled like a noun (때 of 때다, 개 of 개다) is no evidence
                n = sum(sc.get(f, 0) for f in self.lemma_forms.get(lem, ()) if not self.nounish(f))
            else:
                w = lem.split(":")[0].lstrip("-")
                tails = self.NOUN_TAILS + (self.NOUN_TAILS_C if has_batchim(w) else self.NOUN_TAILS_V)
                if len(w) == 1 or any(self.pos.get(w[:k], set()) & {"noun", "pron"} and particle_chains(w[:k], w[k:])
                                      for k in range(1, len(w))):
                    # a lone syllable (도, 사, 작) is mostly a split-off piece; a
                    # spelling that is also noun + particle (목이 = 목 + 이) counts
                    # only with its own particles (목이를), not bare
                    tails = tails[1:]
                # ... and a spelling that is a form of another stem's verb (먹지 of
                # 먹다 is no evidence for the noun 먹지; 집을 still counts for 집)
                n = sum(sc.get(w + t, 0) for t in tails
                        if not any(l2[:-1] != w for l2, c in self.verb_readings(w + t) if c < 3))
            self._ev[key] = 1.33 * math.log10(1 + n)
        return self._ev[key]

    def pos_rank(self, w, p):
        order = self.pos_order.get(w, [])
        return order.index(p) if p in order else len(order)

    def nounish(self, f):
        """f is a nominal headword or a nominal + particles (개, 개는, 데서)."""
        if self.pos.get(f, set()) - {"verb", "adj"}:
            return True
        for k in range(1, len(f)):
            if self.pos.get(f[:k], set()) & {"noun", "pron", "num", "counter"} and particle_chains(f[:k], f[k:]):
                return True
        return False

    def zipf_prior(self, lem, group):
        """wordfreq zipf of the reading's morpheme: a verb's stem (먹-), a
        noun itself; X하다 verbs by X (mecab splits 공부+하)."""
        verb = group in ("VERB", "ADJ") and lem.endswith("다")
        w = lem[:-1] if verb else lem.split(":")[0].lstrip("-")
        z = self.zipf(w)
        if not z and len(w) >= 2 and (verb or lem in self.canon):
            # mecab splits a verb stem or a closed-set word (죽이- = 죽 + 이,
            # 공부하- = 공부 + 하, 그들 = 그 + 들): the rarer part's zipf, less 0.5
            z = max(min(self.zipf(w[:k]), self.zipf(w[k:])) for k in range(1, len(w))) - 0.5
        return max(z, 0.0)

    def group_for(self, w, p, hint=None):
        g = self.canon.get(w)
        return g if g else KPOS_GROUP[p]

    # ---- candidate generation ---------------------------------------------------
    def verb_readings(self, E):
        """[(lemma, cost)] for E as one conjugated verb/adjective word."""
        out = {}

        def add(lem, c):
            if lem not in out or c < out[lem]:
                out[lem] = c
        for lem, c in self.forms.get(E, {}).items():
            add(lem, c)
        for base, rest in splits(E):
            if rest in RAW_E_SET:
                for lem in self.raw.get(base, ()):
                    add(lem, 1)
                if rest.startswith(("는", "네", "니", "ㄴ", "ㅂ")):
                    for lem in self.raw_l.get(base, ()):
                        add(lem, 1)
            if rest in A_E_SET:
                for lem in self.inf.get(base, ()):
                    add(lem, 1)
            if rest in U_E_SET:
                for lem in self.eu.get(base, ()):
                    add(lem, 1)
            if rest == "":
                for lem in self.inf.get(base, ()):
                    add(lem, 1)           # bare infinitive = intimate style (먹어, 가)
                for lem in self.raw.get(base, ()):
                    add(lem, 3)           # bare stem: a morpheme (wordfreq), never a written word
        return sorted(out.items())

    def compound_readings(self, E):
        """A main verb and an auxiliary written as one word: infinitive + 보다/
        주다/버리다... (가봐요, 해줘, 알려주세요 -> the main verb), stem-고 +
        있다/싶다 (알고있어), an adjective's infinitive + 하다 (싶어해요 -> 싶다)."""
        out = {}
        for k in range(1, len(E)):
            x, y = E[:k], E[k:]
            ys = {lem for lem, c in self.verb_readings(y) if c < 3}
            if not ys:
                continue
            if ys & AUX_AFTER_INF:
                for lem in self.inf.get(x, ()):
                    out[lem] = 2
            if ys & {"하다"}:
                for lem in self.inf.get(x, ()):
                    if self.verb_group(lem) == "ADJ":
                        out[lem] = 2
            if x.endswith("고") and ys & {"있다", "싶다", "계시다"}:
                for lem in self.raw.get(x[:-1], ()):
                    out[lem] = 2
            if x.endswith("지") and ys & {"말다", "않다", "못하다"}:
                for lem in self.raw.get(x[:-1], ()):
                    out[lem] = 2          # 하지마, 걱정마 (-지 마: don't)
            if x.endswith("야") and ys & {"되다", "하다"}:
                for lem in self.inf.get(x[:-1], ()):
                    out[lem] = 2          # 해야된다
        return sorted(out.items())

    def hosts(self, host):
        """Nominal/adverb readings of a particle host: [(lemma, group)]."""
        out = []
        # a pronoun or 것 already fused with its particle (날 = 나를, 건 = 것은) hosts
        # nothing: 날이 is the noun "day" + 이
        for lem, g in self.closed.get(host, ()) if host not in FUSED else ():
            if g in ("PRON", "NUM", "NOUN", "ADV"):
                out.append((lem, g))
        if host in self.alias and self.alias[host] in self.pos:
            t = self.alias[host]
            for p in sorted(self.pos[t]):
                if p in NOMINAL_POS:
                    out.append((t, self.canon.get(t, KPOS_GROUP[p])))
                    break
        seen = set()
        for p in sorted(self.pos.get(host, ()) if host not in CLOSED_ONLY else ()):
            if p == "num":
                continue          # numerals come only from the closed tables (자 is not a numeral)
            if p in NOMINAL_POS or p == "adv":
                g = "ADV" if p == "adv" else self.group_for(host, p)
                if g == "ADV" and p != "adv":
                    g = KPOS_GROUP[p]
                if (host, g) not in seen:
                    seen.add((host, g))
                    # (the adverb 안 "not" is canon ADV, but 안에서 is the noun "inside")
                    out.append((host, g if p in NOMINAL_POS else self.canon.get(host, g)))
        return out

    def candidates(self, E, hint=None):
        """All parses of E: (cost, kind, pieces), pieces [(surface, lemma, group)]."""
        C = []
        if E in self.hand:
            C.append((-5, "hand", [tuple(p) for p in self.hand[E]]))
        for lem, g in self.closed.get(E, ()):
            C.append((-0.5, "closed", [(E, lem, g)]))
        seen = {g for _, g in self.closed.get(E, ())}      # 이: the closed 이:det, not kaikki's det 이
        split = any(self.pos.get(E[:k], set()) & {"noun", "pron", "num"} and particle_chains(E[:k], E[k:]) for k in range(1, len(E)))
        for p in sorted(self.pos.get(E, ()) if E not in CLOSED_ONLY else (), key=lambda p: self.pos_rank(E, p)):
            if p in ("verb", "adj", "num"):
                continue          # numerals come only from the closed tables
            g = self.group_for(E, p)
            if g not in seen:
                seen.add(g)
                # (저는 is 저 + 는, not a rare headword "저는")
                # (a dictionary word of 3+ syllables beats a split: 절대로 is not 절 + 대로)
                C.append(((1 if split else 0) + 0.1 * self.pos_rank(E, p) - (0.5 if len(E) >= 3 else 0),
                          "exact", [(E, E, g)]))
        # a detached particle agrees with whatever came before: try both allomorph hosts
        detached = particle_chains("", E) or particle_chains("각", E) or particle_chains("가", E)
        if E in COP_CONS and E[0] in "이입인일임였예" and not detached:
            C.append((0.6, "cop", [(E, "-이다", "PART")]))      # a copula written apart (이란, 이세요)
        for ch in detached:
            if ch:
                # 까지는 alone; a detached (이)-particle (게임 이나, 친구 이랑) is the particle
                C.append((-0.5 if E[0] == "이" else 0.5, "part", [(s, key, "PART") for s, key in ch]))
        if E in self.alias and not E.endswith("다"):
            t = self.alias[E]
            for p in sorted(self.pos.get(t, ())):
                if p not in ("verb", "adj"):
                    C.append((0, "exact", [(E, t, self.group_for(t, p))]))
                    break
        vr = self.verb_readings(E)
        # a one-syllable open-class host before a particle loses to a real verb form of the
        # whole eojeol (도와 = 돕다, not 도 + 와; 사요 = 사다; 작아 = 작다)
        verbish = 1 if any(c <= 1 for _, c in vr) else 0
        # a longer literal stem beats an ㄹ-dropped one: 마시겠습니까 is 마시다, not the
        # honorific 마시- of 말다 (a tie, 사세요 = 사다 or 살다, stays with the scores)
        lit = max((len(l) - 1 for l, c in vr if E.startswith(l[:-1])), default=0)
        for lem, c in vr:
            st = lem[:-1]
            if (st and not E.startswith(st) and "가" <= st[-1] <= "힣"
                    and (ord(st[-1]) - 0xAC00) % 28 == 8 and lit > len(st)):
                c += 1
            C.append((c, "verb", [(E, lem, self.verb_group(lem, hint))]))
        if not vr:
            for lem, c in self.compound_readings(E):
                C.append((c, "verb", [(E, lem, self.verb_group(lem, hint))]))
        for k in range(1, len(E)):
            host, rest = E[:k], E[k:]
            for hl, hg in self.hosts(host):
                if self.canon.get(host) == "ADV" and hg != "ADV" and rest in ADV_PARTICLES:
                    hg = "ADV"      # 지금은, 조금만: the adverb; 안에서, 모두를: the noun
                if hg == "ADV":
                    if rest in ADV_PARTICLES:
                        for ch in particle_chains(host, rest):
                            C.append((0.8, "adv+p", [(host, hl, hg)] + [(s, key, "PART") for s, key in ch]))
                    continue
                whole = bool(self.pos.get(E, set()) & {"noun", "pron", "adv"})
                if len(E) >= 3 and (k == 1 and whole or "adv" in self.pos.get(E, set())):
                    continue    # 절대로, 정말로: the dictionary word, not 절 + 대로 or 정말 + 로
                for ch in particle_chains(host, rest):
                    if ch and ch[0][0] == "들" and (host + "들") in self.pos:
                        continue          # 그들은 = 그들 + 은
                    # (동의 is the noun "agreement", not 동 + 의)
                    short = verbish if k == 1 and host not in self.closed else 0
                    if ch and ch[0][0] == "하고" and (host + "하다") in self.pos:
                        short += 4      # 결혼하고 is 결혼하다, not 결혼 + the particle 하고
                    C.append((0.2 + 0.3 * len(ch) + ((2 if len(E) >= 3 else 1) if whole else 0) + short, "noun+p",
                              [(host, hl, hg)] + [(s, key, "PART") for s, key in ch]))
                cop = COP_CONS if has_batchim(host) else COP_VOW
                if rest in cop and (len(host) >= 2 or host in self.closed or
                                    rest.startswith(("이", "입", "인", "일", "임", "예", "였", "여"))):
                    # (a one-syllable host takes the copula with its 이/예/였: 조지 is not 조 + 지)
                    C.append((1.2, "noun+cop", [(host, hl, hg), (rest, "-이다", "PART")]))
                elif hg == "NOUN" or hl == "뭐":
                    for lem, c in self.verb_readings(rest):
                        if lem in NOUN_VERBS and c < 3 and (host + lem) not in self.pos:
                            C.append((2, "noun+hada", [(host, hl, hg), (rest, lem, "VERB")]))
                            break
        if len(E) >= 2 and E[0] in "안못" and not C:
            for lem, c in self.verb_readings(E[1:]):
                if c < 3:
                    C.append((2, "neg+verb", [(E[0], E[0], "ADV"), (E[1:], lem, self.verb_group(lem, hint))]))
        if not C:
            for k in range(1, len(E)):
                host, rest = E[:k], E[k:]
                if "adv" in self.pos.get(host, ()) and rest in (COP_CONS if has_batchim(host) else COP_VOW):
                    C.append((2, "adv+cop", [(host, host, "ADV"), (rest, "-이다", "PART")]))
        if not C:
            # two nouns written as one word (아침식사를, 여름방학을, 신용카드를)
            for k in range(1, len(E) - 1):
                a = E[:k]
                if not (self.pos.get(a, set()) & {"noun"}) or len(a) < 2:
                    continue
                for c2, kind2, p2 in self.candidates(E[k:]) if len(E) - k >= 2 else ():
                    if kind2 in ("noun+p", "noun+cop", "exact") and p2[0][2] == "NOUN" and len(p2[0][0]) >= 2:
                        C.append((3, "noun+noun", [(a, a, "NOUN")] + p2))
        return C

    def cues(self, lem):
        """English words that attest verb/adjective `lem` in a translation: the
        hand cue table plus the inflections of its Wiktionary gloss words."""
        c = self._cue_cache.get(lem) if hasattr(self, "_cue_cache") else None
        if c is None:
            if not hasattr(self, "_cue_cache"):
                self._cue_cache = {}
            c = set(VERB_CUES.get(lem, ()))
            for w in self.gloss_en.get(lem, ()):
                if len(w) >= 3 and w not in CUE_STOP:
                    c |= en_forms(w)
            self._cue_cache[lem] = c
        return c

    def noun_cues(self, lem):
        """English words that attest noun `lem` in a translation (its Wiktionary
        gloss words, inflected)."""
        c = set()
        for w in self.noun_en.get(lem.split(":")[0], ()):
            if len(w) >= 3 and w not in CUE_STOP:
                c |= en_forms(w)
        return c

    def analyse(self, E, hint=None):
        """Best parse of eojeol E, or None. hint: spaCy's first tag class
        ('n' nominal, 'p' predicate, 'hv' predicative noun + 하다/되다,
        'a' adverb, 'd' determiner, 'i' interjection, 'j' particle)."""
        key = (E, hint)
        if key in self._cache:
            return self._cache[key]
        best = None
        for cost, kind, pieces in self.candidates(E, hint):
            if kind == "hand":
                self._cache[key] = (kind, pieces)      # hand readings are fixed: no hint or prior overrides them
                return self._cache[key]
            g = pieces[0][2]
            sc = cost
            if hint:
                if hint == "n" and g in ("NOUN", "PRON", "NUM"):
                    sc -= 2
                elif hint in ("pa", "pv", "hv") and g in ("VERB", "ADJ"):
                    sc -= 2
                elif hint == "hv" and kind in ("noun+hada", "noun+cop"):
                    sc -= 1.5
                elif hint == "a" and g == "ADV":
                    sc -= 2
                elif hint == "d" and g in ("DET", "NUM"):
                    sc -= 2
                elif hint == "j" and kind == "part":
                    sc -= 2         # the tagger's particle, detached (게임 이나, 친구 도)
                elif hint == "i" and g == "INTJ":
                    sc -= 2
                elif hint == "n" and g == "ADV" and kind in ("exact", "adv+p"):
                    sc -= 1
                else:
                    sc += 0.5
            if kind == "exact" and pieces[0][1] in self.canon:
                sc -= 1                                   # closed-set words as listed (어떻게 = how, not 어떻다)
            sc -= 0.5 * self.prior(pieces[0][1], g)       # the commoner reading
            cand = (round(sc, 4), len(pieces), pieces[0][1], g, kind, pieces)
            if best is None or cand[:4] < best[:4]:
                best = cand
        res = None if best is None else (best[4], best[5])
        self._cache[key] = res
        return res


def hint_of(xpos):
    """spaCy ko_core_news_sm tag_ (KAIST tag set) -> analysis hint class."""
    if not xpos:
        return None
    t = xpos.split("+")
    a = t[0]
    if a.startswith("nq"):
        return "q"
    if a in ("ncpa", "ncps") and len(t) > 1 and t[1] in ("xsv", "xsa"):
        return "hv"
    if a.startswith(("nc", "nb", "np", "nn")):
        return "n"
    if a.startswith("pa"):
        return "pa"
    if a.startswith(("pv", "px")):
        return "pv"
    if a.startswith("ma"):
        return "a"
    if a.startswith("mm"):
        return "d"
    if a.startswith("ii"):
        return "i"
    if a.startswith("j"):
        return "j"
    return None


# =============================================================================
# closed sets and keys
# =============================================================================
DAYS = "월요일 화요일 수요일 목요일 금요일 토요일 일요일".split()
MONTHS = "일월 이월 삼월 사월 오월 유월 칠월 팔월 구월 시월 십일월 십이월".split()
# Sino-Korean numerals share their spelling with common words (일 "work", 이
# "this", 팔 "arm", 천 "cloth"): keyed "<word>:num", shown as the word.
SINO = [("영", "zero"), ("일", "one"), ("이", "two"), ("삼", "three"), ("사", "four"), ("오", "five"),
        ("육", "six"), ("칠", "seven"), ("팔", "eight"), ("구", "nine"), ("십", "ten"), ("백", "hundred"),
        ("천", "thousand"), ("만", "ten thousand")]
# native numerals; the determiner forms before a counter (한 개, 두 명) link them
NATIVE = [("하나", "one", "한"), ("둘", "two", "두"), ("셋", "three", "세"), ("넷", "four", "네"),
          ("다섯", "five", None), ("여섯", "six", None), ("일곱", "seven", None), ("여덟", "eight", None),
          ("아홉", "nine", None), ("열:num", "ten", None), ("스물", "twenty", "스무"),
          ("서른", "thirty", None), ("마흔", "forty", None), ("쉰", "fifty", None), ("예순", "sixty", None),
          ("일흔", "seventy", None), ("여든", "eighty", None), ("아흔", "ninety", None)]
NUM_KEY = {**{w: (f"{w}:num", "NUM") for w, _ in SINO}, **{(n.split(":")[0]): (n, "NUM") for n, _, _ in NATIVE},
           **{d: (n, "NUM") for n, _, d in NATIVE if d}}
# words capped at A2 by hand (colour adjectives beside the A1 colour nouns;
# 남동생 beside 여동생)
HAND_CEILING_A2 = [("빨갛다", "ADJ"), ("파랗다", "ADJ"), ("노랗다", "ADJ"), ("하얗다", "ADJ"), ("까맣다", "ADJ"),
                   ("남동생", "NOUN"), ("여동생", "NOUN")]
def speech_register(toks):
    """Speech level of a tagged sentence from its clause-final predicates (the
    last word before . ? ! or the end): "polite" (-요, -니다, -니까, -시오),
    "plain" (written -다), "banmal" (들어, 뭐야, 먹자, 할까) or "none" (no
    predicate: 하나, 둘, 셋.). The least polite clause decides."""
    finals, prev = [], None
    for t in toks:
        if t[2] == "PUNCT":
            if prev is not None and re.search(r"[.?!…]", t[0]):
                finals.append(prev)
                prev = None
            continue
        prev = t
    if prev is not None:
        finals.append(prev)
    rank = {"polite": 0, "none": 1, "plain": 2, "banmal": 3}
    worst = None
    for t in finals:
        w = t[0]
        g = re.search(r"G=([A-Z]+)", t[3] or "")
        g = g.group(1) if g else t[2]
        if POLITE_END_RE.search(w):
            r = "polite"
        elif g in ("NOUN", "PRON", "NUM", "PROPN", "INTJ", "ADV", "DET") and t[1] != "-이다":
            r = "none"
        elif w.endswith("다"):
            r = "plain"
        else:
            r = "banmal"
        if worst is None or rank[r] > rank[worst]:
            worst = r
    return worst or "none"


# endings shared by verb forms and noun + particle/copula readings: never routed to the noun
VERBISH_TAILS = {"요", "고", "지", "죠", "네", "면", "서", "나", "니", "다", "지요", "네요", "고요"}
# bound nouns after a verb's modifier form (할 수, 둘 곳, 온 적)
def limit_modifier(tok):
    """A modifier before the noun 한 "as long as / limit": a verb's -는 form
    (살아 있는 한) or an adjective's -(으)ㄴ form (가능한 한)."""
    if tok[2] not in ("VERB", "ADJ") or not tok[0]:
        return False
    return tok[0].endswith("는") or (tok[2] == "ADJ" and is_syl(tok[0][-1]) and fin(tok[0][-1]) == T_IDX["ㄴ"])


BOUND_AFTER_MOD = ("수", "것", "거", "때", "줄", "곳", "적", "리", "뻔", "만큼", "데", "뿐", "예정", "계획")
# nouns a verb modifier 한 (하다 "did") stands before, never a native numeral's counter
VERB_MOD_NOUNS = {"일", "말", "짓", "것", "거", "적", "게", "줄", "건", "걸", "얘기", "이야기", "약속", "생각"}
# counters and units a numeral stands before (삼 년, 두 명, 다섯 시, 천 원)
COUNTERS = set("""개 명 사람 분 살 시 시간 초 번 점 마리 권 잔 병 장 대 층 년 월 일 원 달 주 주일 개월 세 달러 킬로 미터
킬로미터 센티 호 쪽 번째 가지 벌 켤레 송이 그릇 인분 학년 등 배 척 채 곳 군데 줄 조각 박스 통 봉지 컵 번지 페이지
주년 년대 퍼센트 도 인 명의 달간 시간째 일째 층짜리""".split())
# counters take one numeral series: a one-digit Sino-Korean spelling (이, 일, 사, 오...)
# before a native-series counter is a word (이 사람 = this person, 일 년 = one year);
# a native determiner before a Sino-series counter likewise (한 일 = the thing done)
NATIVE_SERIES = set("개 명 사람 마리 권 잔 병 장 대 살 시 시간 달 가지 벌 켤레 송이 그릇 곳 군데 줄 조각 박스 통 봉지 컵 척 채".split())
SINO_SERIES = set("년 월 일 원 층 초 달러 킬로 미터 킬로미터 센티 호 쪽 번지 페이지 주년 년대 퍼센트 도 인분 학년 등 개월 주일 세 인".split())
SINO_DIGITS = set("일 이 삼 사 오 육 칠 팔 구".split())
COUNTER_EN = {"일": r"days?", "년": r"years?", "분": r"minutes?", "초": r"seconds?", "층": r"floors?|storeys?|stories",
              "월": r"months?", "개월": r"months?", "주일": r"weeks?", "원": r"won", "달러": r"dollars?",
              "킬로": r"kilos?|kilograms?|kilometers?|kilometres?", "미터": r"meters?|metres?", "퍼센트": r"percent|%"}
NATIVE_DETS = {"한", "두", "세", "네", "다섯", "여섯", "일곱", "여덟", "아홉", "열", "스무", "서른", "마흔", "쉰",
               "예순", "일흔", "여든", "아흔"}
PRONOUNS = "저 나 우리 저희 너 당신 그 그녀 그들".split()
THINGS = "이것 그것 저것 여기 거기 저기".split()
DEMONSTR = [("이:det", "this (+ noun)"), ("그:det", "that (+ noun: near you, or already mentioned)"),
            ("저:det", "that (+ noun: over there)")]
# adnominal determiners: the whole spelling is the det entry, never the
# modifier form of 어떻다/이렇다/그렇다/저렇다/아무렇다 (same meaning, one word)
ADNOMINAL_DET = {"어떤": "what kind of; some, a certain", "이런": "like this, such (+ noun)",
                 "그런": "like that, such (+ noun)", "저런": "like that (+ noun: over there)",
                 "아무런": "any (+ noun, with a negative)"}
QUESTION = [("누구", "PRON"), ("무엇", "PRON"), ("뭐", "PRON"), ("어디", "PRON"), ("언제", "PRON"),
            ("왜", "ADV"), ("어떻게", "ADV"), ("얼마", "NOUN"), ("몇", "DET"), ("어느", "DET"), ("어떤", "DET"),
            ("무슨", "DET")]
TIME = [("오늘", "NOUN"), ("내일", "NOUN"), ("어제", "NOUN"), ("지금", "ADV"), ("아침", "NOUN"), ("점심", "NOUN"),
        ("저녁", "NOUN"), ("밤", "NOUN"), ("낮", "NOUN"), ("주말", "NOUN"), ("오전", "NOUN"), ("오후", "NOUN"),
        ("시", "NOUN"), ("분", "NOUN"), ("시간", "NOUN"), ("년", "NOUN"), ("해", "NOUN"), ("달", "NOUN"),
        ("주", "NOUN"), ("날", "NOUN"), ("요일", "NOUN"), ("매일", "ADV"), ("모레", "NOUN")]
COLOURS = "빨간색 파란색 노란색 초록색 검은색 흰색 색".split()
PARTICLE_GLOSS = {
    "-씩": "each, apiece (하나씩: one each; 조금씩: little by little)",
    "-이/가": "subject marker", "-은/는": "topic marker (as for ...); contrast",
    "-을/를": "object marker", "-에": "at, in, on; to (place, time)", "-에서": "at, in (where something happens); from",
    "-의": "'s, of (possessive)", "-도": "also, too; even", "-만": "only, just",
    "-와/과": "and; with", "-하고": "and; with (spoken)", "-(이)랑": "and; with (casual)",
    "-(으)로": "to, toward; by, with (means)", "-에게": "to (a person)", "-한테": "to (a person, spoken); by",
    "-께서": "subject marker (honorific)", "-께": "to (a respected person: honorific -에게)", "-부터": "from (a starting point)", "-까지": "until, up to, to",
    "-보다": "than", "-처럼": "like, as", "-마다": "every, each", "-밖에": "only, nothing but (with a negative)",
    "-(이)나": "or; as many as", "-요": "polite particle (makes a phrase polite)",
    "-이다": "to be (copula: N-이다 = is N)",
}
PHRASES = {"안녕히 가세요": "goodbye (to someone leaving)", "안녕히 계세요": "goodbye (to someone staying)",
           "만나서 반갑습니다": "nice to meet you", "처음 뵙겠습니다": "how do you do (first meeting)",
           "잘 먹겠습니다": "thank you for the meal (before eating)",
           "잘 먹었습니다": "thank you for the meal (after eating)"}
GREETINGS = {"안녕하세요": "hello (polite)", "안녕하십니까": "hello (formal)", "감사합니다": "thank you (formal)",
             "고맙습니다": "thank you", "죄송합니다": "I'm sorry (formal apology)", "미안합니다": "I'm sorry",
             "네": "yes", "예": "yes (formal)", "아니요": "no", "아뇨": "no", "안녕": "hi; bye (casual)",
             "여보세요": "hello (on the phone)", "실례합니다": "excuse me"}
# greeting spellings folded into one word (아뇨 = 아니요)
GREETING_KEY = {"아뇨": "아니요", "안녕하십니까": "안녕하세요"}

# eojeol -> pieces: fused pronoun + particle forms and greeting words
HAND = {
    "내가": [("내", "나", "PRON"), ("가", "-이/가", "PART")],
    "제가": [("제", "저", "PRON"), ("가", "-이/가", "PART")],
    "네가": [("네", "너", "PRON"), ("가", "-이/가", "PART")],
    "니가": [("니", "너", "PRON"), ("가", "-이/가", "PART")],
    "누가": [("누", "누구", "PRON"), ("가", "-이/가", "PART")],
    "난": [("난", "나", "PRON")], "넌": [("넌", "너", "PRON")], "우린": [("우린", "우리", "PRON")],
    "우릴": [("우릴", "우리", "PRON")], "저흰": [("저흰", "저희", "PRON")],
    "이건": [("이건", "이것", "PRON")], "그건": [("그건", "그것", "PRON")], "저건": [("저건", "저것", "PRON")],
    "이걸": [("이걸", "이것", "PRON")], "그걸": [("그걸", "그것", "PRON")], "저걸": [("저걸", "저것", "PRON")],
    "이게": [("이게", "이것", "PRON")], "그게": [("그게", "그것", "PRON")], "저게": [("저게", "저것", "PRON")],
    "겁니다": [("겁니다", "것", "NOUN")], "겁니까": [("겁니까", "것", "NOUN")],
    "뭘": [("뭘", "뭐", "PRON")], "우와": [("우와", "우와", "INTJ")],
    # 말다 "don't" after -지 (하지 마, 가지 마라)
    **{f: [(f, "말다", "VERB")] for f in ("마", "마라", "마요", "마세요", "마십시오")},
    # the copula written apart from its noun (수도 입니다)
    **{f: [(f, "-이다", "PART")] for f in ("입니다", "입니까", "이에요", "예요", "이야", "이다", "였습니다", "이었습니다",
                                             "였어요", "이었어요", "였다", "이었다", "였어", "이었어", "이죠", "이지")},
    # 것 fused with the copula or a particle (갈 거지, 한 건데)
    **{f: [(f[0], "것", "NOUN"), (f[1:], "-이다", "PART")] for f in ("거지", "거죠", "거고", "거라고", "거라면",
                                                                   "거면", "거니까", "거라서", "거란", "거라는", "거야", "거예요",
                                                                   "거에요", "거였어", "거였어요", "거잖아", "거잖아요",
                                                                   "거네", "거네요", "거지요", "거냐", "거니")},
    # the spoken spelling 꺼 of 거 (네 꺼야, 할 꺼예요), never 끄다 "to turn off" here
    **{f: [(f[0], "것", "NOUN"), (f[1:], "-이다", "PART")] for f in ("꺼야", "꺼예요", "꺼에요", "꺼냐", "꺼니")},
    **{f: [(f, "뭐", "PRON")] for f in ("뭔지", "뭔데", "뭔데요", "뭔가요", "뭔지요")},
    "이젠": [("이젠", "이제", "NOUN")],
    "거": [("거", "것", "NOUN")],   # spoken 것; Wiktionary's alias 거 = 거기 never wins
    "이를": [("이", "이", "PRON"), ("를", "-을/를", "PART")],
    # place pronoun + 는/를 contracted (여긴 "here (topic)", 거길 "there (object)"), not 여기다 "regard"
    **{p + t: [(p + t, p + "기", "PRON")] for p in ("여", "거", "저") for t in ("긴", "길")},   # "this"/"teeth" + object marker; 이르다 "early" is 이른/이릅니다
    "어떻게": [("어떻게", "어떻게", "ADV")],      # "how": the question adverb, not 어떻다 + -게
    # adnominal determiners (어떤, 그런): the det entry, never 어떻다/그렇다
    **{w: [(w, w, "DET")] for w in ADNOMINAL_DET},
    # native numerals the dictionary splits (여든 is not 여 + 든); 쉰 stays open (쉬다)
    **{w: [(w, w, "NUM")] for w in ("스물", "서른", "마흔", "예순", "일흔", "여든", "아흔", "다섯", "여섯", "일곱",
                                    "여덟", "아홉")},
    "아무도": [("아무", "아무", "PRON"), ("도", "-도", "PART")],
    # the humble pronoun, never the verb 절다 "to limp"
    **{"저" + p: [("저", "저", "PRON"), (p, k, "PART")] for p, k in (("는", "-은/는"), ("도", "-도"), ("를", "-을/를"),
                                                                    ("의", "-의"), ("한테", "-한테"), ("에게", "-에게"))},
    "아무것도": [("아무것", "아무것", "NOUN"), ("도", "-도", "PART")],
    # 도와 (돕다) is not 도 "province" + 와, whatever the tagger says
    **{f: [(f, "돕다", "VERB")] for f in ("도와", "도와요", "도와줘", "도와줘요", "도와서")},
    **{f: [(f, "것", "NOUN")] for f in ("건데", "건데요", "건가", "건가요", "건지", "건지도", "건가봐요")},
    "누군지": [("누군지", "누구", "PRON")], "어딨어": [("어딨어", "어디", "PRON")],
    "어딨어요": [("어딨어요", "어디", "PRON")], "말야": [("말", "말", "NOUN"), ("야", "-이다", "PART")],
    "더이상": [("더", "더", "ADV"), ("이상", "이상", "NOUN")], "하루종일": [("하루", "하루", "NOUN"), ("종일", "종일", "ADV")],
    "둘다": [("둘", "둘", "NUM"), ("다", "다", "ADV")],
    # 아니다 before -라 (아니라, 아니라고: "not X but ...", quoting)
    **{f: [(f, "아니다", "ADJ")] for f in ("아니라", "아니라고", "아니라서", "아니라면", "아니란", "아니라는", "아니래요")},
    # bound grammar words after a -ㄹ form (갈 텐데): no link, no block
    **{f: [(f, "-터", "PART")] for f in ("텐데", "텐데요", "테니까", "테니", "테지만")},
    **{g: [(g, GREETING_KEY.get(g, g), "INTJ")] for g in GREETINGS if g not in ("네", "예", "안녕")},
}
# closed readings tried like dictionary words (the tagger's hint and the
# frequency prior choose): fused pronouns that are also nouns (날 "day", 전
# "before"), 것 spellings (거 건 걸 게), demonstrative determiners
FUSED = {"날", "널", "절", "전", "건", "걸", "게"}
CLOSED = {
    "날": [("나", "PRON")], "널": [("너", "PRON")], "절": [("저", "PRON")], "전": [("저", "PRON")],
    "내": [("나", "PRON")], "제": [("저", "PRON")], "네": [("너", "PRON")], "니": [("너", "PRON")],
    "거": [("것", "NOUN")], "건": [("것", "NOUN")], "걸": [("것", "NOUN")], "게": [("것", "NOUN")],
    "이거": [("이것", "PRON")], "그거": [("그것", "PRON")], "저거": [("저것", "PRON")],
    "이": [("이:det", "DET")], "그": [("그:det", "DET"), ("그", "PRON")],
    "저": [("저:det", "DET"), ("저", "PRON")],
    "뭔": [("뭐", "PRON")], "뭐": [("뭐", "PRON")], "뭔가": [("뭔가", "PRON")], "누군가": [("누군가", "PRON")],
    "이걸로": [("이것", "PRON")], "그걸로": [("그것", "PRON")], "저걸로": [("저것", "PRON")], "내게": [("나", "PRON")], "제게": [("저", "PRON")],
    "네게": [("너", "PRON")],
    "막": [("막", "ADV")],          # "just (now)": the adverb, not 막 "tent"
}
# names Tatoeba uses in nearly every other sentence (Tom, Mary), which the
# tagger reads as common nouns; other names: a host Wiktionary lacks, in a
# sentence whose English names someone (see Korean.fix_sentence)
NAMES = {"톰": "Tom", "탐": "Tom", "메리": "Mary", "매리": "Mary", "존": "John", "켄": "Ken", "제인": "Jane",
         "잭": "Jack", "리사": "Lisa", "앨리스": "Alice", "마이크": "Mike", "루시": "Lucy", "빌": "Bill",
         "토니": "Tony", "피터": "Peter", "마리아": "Maria", "존슨": "Johnson", "스미스": "Smith", "조지": "George",
         "제임스": "James", "데이비드": "David", "폴": "Paul", "사라": "Sarah", "에밀리": "Emily", "케이트": "Kate",
         "로라": "Laura", "다나카": "Tanaka", "요시다": "Yoshida", "켄지": "Kenji", "마사코": "Masako",
         "나발니": "Navalny", "피트": "Pete", "짐": "Jim", "마리": "Marie"}
EN_NAME_STOP = {"I", "I'm", "I'll", "I've", "I'd", "OK", "Mr", "Mrs", "Ms", "Dr", "TV"}
# given names Tatoeba English uses (a sentence-initial capitalised word is a
# name only when listed here; mid-sentence ones are names anyway)
EN_GIVEN_NAMES = set("""Tom Mary John Bob Ken Jane Jack Lisa Alice Mike Lucy Bill Tony Peter Maria Marie George James
David Paul Sarah Emily Kate Laura Jim Pete Nancy Susan Betty Judy Linda Anna Ann Dan Sam Ben Tim Nick Rick Chris
Mark Steve Kevin Brian Fred Harry Henry Robert Richard Charles Thomas William Michael Emma Olivia Sophie Jessica
Jennifer Karen Helen Kathy Taro Hanako Yuki Ziri Rima Sami Layla Skura Yanni Mennad Baya Muiriel Tanaka Yoshida
Kenji Masako Jon Joe Jimmy Johnny Jenny Julia Julie Kim Lee Park Cookie Rex Max Bella Lily Rose Molly""".split())
# sentence-initial English words that are not names
EN_COMMON_CAPS = set("""the a an he she it we you they i this that these those what where when why how who whom whose
which is are was were am be been do does did don doesn didn can could would should will shall may might must
please let there here my your his her our their its if but and so no yes not never always sometimes often
all every each some any many much most more few one two three four five six seven eight nine ten
tomorrow today yesterday tonight now then after before since because while although though as at in on
of for from to by with about into over under up down out off again just only even also still already
thank thanks sorry hello hi goodbye bye excuse oh ah well okay ok yeah hey wow please whatever everyone
everybody someone somebody nobody nothing something everything anything anyone who's what's it's that's
there's here's let's i'm you're we're they're he's she's i've i'll i'd you'll you've we'll we've they'll
don't doesn't didn't can't couldn't won't wouldn't isn't aren't wasn't weren't haven't hasn't hadn't
shouldn't mustn't go come look listen stop wait give take tell ask help show keep leave try make put
get see call sit stand eat drink read write open close turn bring run walk be have do say think know
sunday monday tuesday wednesday thursday friday saturday january february march april may june july
august september october november december english korean japanese chinese french german spanish
christmas god sir madam mom mum dad mother father grandma grandpa teacher doctor""".split())
# native numerals (하나, 둘 ... 아흔) and every numeral key: never a name, and
# preferred over a same-spelled verb form (둘 중 = two, not 두다)
NUM_WORDS = {n for n, _, _ in NATIVE}
NUM_WORDS_ALL = NUM_WORDS | {f"{w}:num" for w, _ in SINO} | {w for w, _ in SINO}
_KO_L = ["k", "k", "n", "t", "t", "l", "m", "p", "p", "s", "s", "", "j", "j", "j", "k", "t", "p", "h"]
_KO_T = ["", "k", "k", "k", "n", "n", "n", "t", "l", "k", "m", "l", "l", "l", "p", "l", "m", "p", "p", "t", "t", "n",
         "t", "t", "k", "t", "p", "t"]


def _squeeze(cs):
    out = []
    for c in cs:
        if c and (not out or out[-1] != c):
            out.append(c)
    return "".join(out)


def name_key_ko(w):
    """Consonant skeleton of a Hangul spelling (마리 -> ml, 톰 -> tm), for
    matching a name in the English translation."""
    cs, prev_final = [], False
    for i, ch in enumerate(w):
        if not is_syl(ch):
            return ""
        o = ord(ch) - 0xAC00
        L, T = o // 588, o % 28
        c = _KO_L[L]
        if c == "h" and i:
            c = ""
        if c and cs and cs[-1] == c and prev_final:
            c = ""                  # 앨리스: final ㄹ + initial ㄹ is one l
        cs += [x for x in (c, _KO_T[T]) if x]
        prev_final = bool(_KO_T[T])
    k = "".join(cs)
    return k if len(k) >= 2 else ""


def name_key(w):
    """Consonant skeleton of an English name (Mary -> ml, Tom -> tm)."""
    x = re.sub(r"(.)\1", r"\1", w.lower())       # doubled letters (Anna, Bill)
    for a, b in (("ph", "f"), ("th", "t"), ("ck", "k"), ("sh", "s"), ("ch", "j"), ("x", "ks"), ("qu", "kw"),
                 ("ng", "n")):
        x = x.replace(a, b)
    x = re.sub(r"c(?=[eiy])", "s", x)
    x = re.sub(r"g(?=[eiy])", "j", x)
    x = x[0] + re.sub(r"h", "", x[1:]) if x else x
    cls = {"c": "k", "g": "k", "q": "k", "k": "k", "d": "t", "t": "t", "b": "p", "p": "p", "f": "p", "v": "p",
           "r": "l", "l": "l", "m": "m", "n": "n", "s": "s", "z": "s", "j": "j", "h": "h"}
    k = "".join(cls.get(c, "") for c in x)
    return k if len(k) >= 2 else "-"
# the one group a closed/time word is given (no noun/adverb split of 오늘)
CANON = {**{w: g for w, g in QUESTION + TIME}, **{w: "PRON" for w in PRONOUNS + THINGS},
         **{w: "NOUN" for w in DAYS + MONTHS + COLOURS}, "네": "INTJ", "예": "INTJ", "안녕": "INTJ",
         **{n.split(":")[0]: "NUM" for n, _, _ in NATIVE if ":" not in n},
         "지치다": "VERB"}      # "to get tired": Wiktionary lists it first as an adjective
# homographs taught as two words when the translation names the second sense
# (a word of its own only when it holds >=20% of the spelling's corpus uses;
# see TODO.md): lemma -> [(second key, gloss, English cue words)]
# verb readings of one spelling (살 = 사다 "buy" + -ㄹ, or 살다 "live"; 들어 =
# 듣다 or 들다; 걸어 = 걷다 or 걸다): when the analyser offers several verbs, the
# one whose English cue is in the sentence's translation wins; with no cue,
# or cues for more than one, the analyser's choice stands
VERB_CUES = {
    "사다": {"buy", "buys", "bought", "buying", "purchase", "purchased", "afford"},
    "살다": {"live", "lives", "lived", "living", "life", "alive", "reside"},
    "듣다": {"hear", "hears", "heard", "hearing", "listen", "listens", "listened", "listening", "obey", "obeys",
             "obeyed", "sounds", "sounded"},
    "들다": {"cost", "costs", "like", "likes", "liked", "enter", "entered", "join", "joined", "hold", "holds", "held",
             "lift", "lifted", "raise", "raised", "contain", "contains", "bruise", "bruised", "robbed", "doubt",
             "example", "instance", "interrupt", "interrupting", "lately", "recently", "days", "cut", "cuts"},
    "트다": {"chapped", "chap", "chaps", "cracked", "crack", "sprout", "sprouted", "dawn", "dawned"},
    "틀다": {"play", "plays", "played", "playing", "switch", "switched", "turn", "turned", "twist", "twisted"},
    "신다": {"wear", "wears", "wore", "worn", "wearing", "shoes", "socks", "boots"},
    "두다": {"put", "puts", "putting", "place", "placed", "leave", "left", "keep", "kept"},
    "날다": {"fly", "flies", "flew", "flying", "flown"},
    "팔다": {"sell", "sells", "sold", "selling", "sale"},
    "파다": {"dig", "digs", "dug", "digging"},
    "걷다": {"walk", "walks", "walked", "walking", "foot"},
    "걸다": {"hang", "hung", "call", "called", "calling", "phone", "phoned", "bet", "hook"},
    "갈다": {"grind", "sharpen", "replace", "replaced", "change", "changed"},
    "짓다": {"build", "built", "building", "make", "made", "cook", "cooked", "name", "named", "smile", "smiled"},
    "비다": {"empty", "vacant", "free"},
    "빌다": {"pray", "prayed", "wish", "wished", "beg", "begged"},
}

# English inflections for gloss-derived cues (buy -> bought)
EN_IRREG = {"buy": "bought", "hear": "heard", "go": "went gone", "come": "came", "see": "saw seen",
            "take": "took taken", "give": "gave given", "eat": "ate eaten", "drink": "drank drunk",
            "sell": "sold", "wear": "wore worn", "leave": "left", "make": "made", "know": "knew known",
            "get": "got gotten", "say": "said", "tell": "told", "think": "thought", "bring": "brought",
            "teach": "taught", "catch": "caught", "fly": "flew flown flies", "sleep": "slept", "feel": "felt",
            "find": "found", "run": "ran", "sit": "sat", "stand": "stood", "write": "wrote written",
            "speak": "spoke spoken", "break": "broke broken", "lose": "lost", "meet": "met", "pay": "paid",
            "send": "sent", "spend": "spent", "build": "built", "hold": "held", "keep": "kept", "win": "won",
            "begin": "began begun", "swim": "swam", "sing": "sang sung", "drive": "drove driven",
            "ride": "rode ridden", "fall": "fell fallen", "hang": "hung", "dig": "dug", "throw": "threw thrown",
            "grow": "grew grown", "draw": "drew drawn", "wake": "woke woken", "choose": "chose chosen",
            "forget": "forgot forgotten", "hide": "hid hidden", "lie": "lay lain lying", "die": "dying",
            "steal": "stole stolen", "shoot": "shot", "fight": "fought", "seek": "sought", "lend": "lent",
            "feed": "fed", "lead": "led", "bite": "bit bitten", "shake": "shook shaken", "tear": "tore torn",
            "freeze": "froze frozen", "burn": "burnt"}
# gloss words too generic to tell one reading from another
CUE_STOP = {"to", "be", "a", "an", "the", "of", "one", "one's", "someone", "something", "oneself", "up", "out",
            "off", "on", "in", "into", "at", "for", "with", "by", "as", "or", "and", "not", "it", "so", "very",
            "do", "make", "have", "get", "become", "is", "are", "this", "that", "some", "way", "more", "much",
            "able", "also", "about", "from", "over", "down", "back", "well", "good", "place", "time", "thing",
            "things", "person", "people", "somewhere", "state", "act", "use", "used", "being", "come", "go",
            "take", "put", "let", "give", "say"}


def en_forms(w):
    """English inflections of a gloss word (buy -> buys, buying, bought)."""
    out = {w, w + "s", w + "es", w + "ed", w + "d", w + "ing"}
    if w.endswith("e"):
        out.add(w[:-1] + "ing")
    if w.endswith("y") and len(w) > 2:
        out |= {w[:-1] + "ies", w[:-1] + "ied"}
    if len(w) >= 3 and w[-1] not in "aeiouwxy" and w[-2] in "aeiou" and w[-3] not in "aeiou":
        out |= {w + w[-1] + "ed", w + w[-1] + "ing"}
    out |= set(EN_IRREG.get(w, "").split())
    return out


HOMOGRAPHS = {
    "눈": [("눈:snow", "snow", {"snow", "snowing", "snowed", "snowy", "snowfall", "snows", "snowman"})],
    "차": [("차:tea", "tea", {"tea", "teas"})],
    "배": [("배:ship", "ship, boat", {"ship", "ships", "boat", "boats", "sail", "sailing", "ferry"}),
          ("배:pear", "pear", {"pear", "pears"})],
    "말": [("말:horse", "horse", {"horse", "horses", "pony"})],
    "다리": [("다리:bridge", "bridge", {"bridge", "bridges"})],
    "밤": [("밤:chestnut", "chestnut", {"chestnut", "chestnuts"})],
    "사과": [("사과:apology", "apology", {"apology", "apologize", "apologise", "apologized", "apologies",
                                           "apologizing", "sorry"})],
}

SENSITIVE_KO = (r"죽이|죽여|죽였|죽일|죽인|살인|살해|섹스|성관계|자살|시체|총을|총으로|총에|쏘|쐈|칼로|칼을|폭탄|"
                r"마약|피를|피가|피투성이|유혈|벗은|알몸|매춘|창녀|콘돔|전쟁|죽었|죽는|죽을|죽어|죽음")
# English terms, matched as whole words only (soldier is not "die", software not "war")
SENSITIVE_KO_EN = r"die|dies|dying|died|weapons?|guns?|knife|bombs?|drugs?|blood\w*|corpses?|war"
# suicide and self-harm lines are dropped at every level too (QA 2026-09-25)
# Non-standard spellings a learner must not copy: colloquial 너가 (standard 네가),
# -어죠 (standard -었죠/-지요), 께 for 게 (할께), 되요 for 돼요, 꺼 for 거 (할꺼야),
# 몇일, 왠만, 어떻해, 않되, 역활, 금새. Dropped at every level.
NONSTANDARD_KO = re.compile(r"\s너가|[었았였]어죠|[할갈줄볼]께|(?:\s|안)되요|[할갈볼줄]꺼|몇일|왠만|어떻해|않되|역활|금새")
DROP_ALL_KO = r"강간|성폭행|성추행|성폭력|아동 학대|자살|자해|목숨을 끊|죽어 버리고 싶|죽고 싶"
DROP_ALL_KO_EN = (r"rape[ds]?|raping|rapist\w*|molest\w*|sexual(?:ly)? abus\w*|child abuse|pedophil\w*|"
                  r"suicid\w*|self-harm\w*|kill (?:myself|yourself|himself|herself|themselves|ourselves)|"
                  r"take (?:my|his|her|their|your) own life|end (?:my|his|her|their|your) (?:own )?life|want to die")   # whole words (grapes)
# vulgar 반말 the pack never shows
VULGAR_KO = r"씨발|시발|씨팔|좆|존나|졸라|개새끼|새끼|병신|지랄|닥쳐|꺼져|엿 먹어|미친놈|미친년|년아|놈아|빌어먹을|젠장"
POLITE_END_RE = re.compile(r"(요|니다|니까|십시오|ㅂ시다|시오)$")


class _PassageAlias(dict):
    """passage_lemma_alias for Korean: the hand entries, then an X하다 or X되다
    verb or adjective the pack lacks falls back to its noun X (운동하다 ->
    운동, 요리하다 -> 요리, 중독되다 -> 중독) when X is a pack word (classify
    checks that): one tap on the eojeol, as a compound the pack lacks links
    its first word."""
    def get(self, k, d=None):
        if k in self:
            return self[k]
        if isinstance(k, str) and len(k) > 2 and k.endswith(("하다", "되다")) and HANGUL_RE.match(k):
            return k[:-2]
        return d


# ---- script primer (docs/SCRIPT_PRIMER.md ss3) -------------------------------
# Hangul: 47 units in 7 sets; the silent ㅇ comes first, with the vowels, so
# set 1 already spells words (아이, 오, 우유). One jamo in two roles is two units (ㄱ initial,
# ㄱ final). Blocks are split by Unicode arithmetic; example romanisation is
# Revised Romanization block by block (a final moves onto a following ㅇ, ㄹㄹ is
# ll; no other sound change -- the ex ranking avoids finals before the last block).
HANGUL_L = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ"
HANGUL_V = "ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ"
HANGUL_T = ["", "ㄱ", "ㄲ", "ㄳ", "ㄴ", "ㄵ", "ㄶ", "ㄷ", "ㄹ", "ㄺ", "ㄻ", "ㄼ", "ㄽ", "ㄾ", "ㄿ", "ㅀ",
            "ㅁ", "ㅂ", "ㅄ", "ㅅ", "ㅆ", "ㅇ", "ㅈ", "ㅊ", "ㅋ", "ㅌ", "ㅍ", "ㅎ"]
RR_L = dict(zip(HANGUL_L, "g kk n d tt r m b pp s ss - j jj ch k t p h".split()))
RR_L["ㅇ"] = ""
RR_V = dict(zip(HANGUL_V, "a ae ya yae eo e yeo ye o wa wae oe yo u wo we wi yu eu ui i".split()))
RR_T = {"": "", "ㄱ": "k", "ㄲ": "k", "ㄳ": "k", "ㄴ": "n", "ㄵ": "n", "ㄶ": "n", "ㄷ": "t", "ㄹ": "l",
        "ㄺ": "k", "ㄻ": "m", "ㄼ": "l", "ㄽ": "l", "ㄾ": "l", "ㄿ": "p", "ㅀ": "l", "ㅁ": "m", "ㅂ": "p",
        "ㅄ": "p", "ㅅ": "t", "ㅆ": "t", "ㅇ": "ng", "ㅈ": "t", "ㅊ": "t", "ㅋ": "k", "ㅌ": "t", "ㅍ": "p", "ㅎ": "t"}
# a final before a ㅇ-initial block moves over: (stays, moves)
KO_LIAISON = {"ㄳ": ("ㄱ", "ㅅ"), "ㄵ": ("ㄴ", "ㅈ"), "ㄶ": ("ㄴ", "ㅎ"), "ㄺ": ("ㄹ", "ㄱ"), "ㄻ": ("ㄹ", "ㅁ"),
              "ㄼ": ("ㄹ", "ㅂ"), "ㄽ": ("ㄹ", "ㅅ"), "ㄾ": ("ㄹ", "ㅌ"), "ㄿ": ("ㄹ", "ㅍ"), "ㅀ": ("ㄹ", "ㅎ"),
              "ㅄ": ("ㅂ", "ㅅ")}

# (set, group, slug, glyph, name, roman, alt, confuse slugs, note)
KO_SCRIPT = [
    (1, "consonant", "ieung", "ㅇ", "이응", "(silent)", [], ["h", "m"],
     "silent at the start of a block (아 = a); ng at the end"),
    (1, "vowel", "a", "ㅏ", "아", "a", [], ["eo", "ya"], "a as in 'father'"),
    (1, "vowel", "eo", "ㅓ", "어", "eo", [], ["a", "yeo"], "open o, like 'u' in 'cut'"),
    (1, "vowel", "o", "ㅗ", "오", "o", [], ["u", "yo"], "o as in 'go', no glide"),
    (1, "vowel", "u", "ㅜ", "우", "u", [], ["o", "yu"], "oo as in 'moon'"),
    (1, "vowel", "eu", "ㅡ", "으", "eu", [], ["i", "u"], "'oo' with the lips spread flat"),
    (1, "vowel", "i", "ㅣ", "이", "i", [], ["eu", "a"], "ee as in 'see'"),
    (2, "consonant", "g", "ㄱ", "기역", "g", ["k"], ["k", "n"], "soft g/k; k at the end of a syllable"),
    (2, "consonant", "n", "ㄴ", "니은", "n", [], ["d", "r"], "n"),
    (2, "consonant", "d", "ㄷ", "디귿", "d", ["t"], ["t", "n"], "soft d/t"),
    (2, "consonant", "r", "ㄹ", "리을", "r", ["l"], ["d", "m"], "a light tap r between vowels, l at the end"),
    (2, "consonant", "m", "ㅁ", "미음", "m", [], ["b", "ieung"], "m"),
    (2, "consonant", "b", "ㅂ", "비읍", "b", ["p"], ["p", "m"], "soft b/p"),
    (2, "consonant", "s", "ㅅ", "시옷", "s", [], ["j", "ss"], "s; sh before ㅣ"),
    (3, "consonant", "j", "ㅈ", "지읒", "j", [], ["ch", "s"], "soft j/ch"),
    (3, "consonant", "ch", "ㅊ", "치읓", "ch", [], ["j", "h"], "ch with a puff of air"),
    (3, "consonant", "k", "ㅋ", "키읔", "k", [], ["g", "kk"], "k with a puff of air"),
    (3, "consonant", "t", "ㅌ", "티읕", "t", [], ["d", "tt"], "t with a puff of air"),
    (3, "consonant", "p", "ㅍ", "피읖", "p", [], ["b", "pp"], "p with a puff of air"),
    (3, "consonant", "h", "ㅎ", "히읗", "h", [], ["ieung", "ch"], "h"),
    (4, "vowel", "ya", "ㅑ", "야", "ya", [], ["a", "yeo"], "ya: ㅏ with an extra stroke adds y"),
    (4, "vowel", "yeo", "ㅕ", "여", "yeo", [], ["eo", "ya"], "yeo"),
    (4, "vowel", "yo", "ㅛ", "요", "yo", [], ["o", "yu"], "yo"),
    (4, "vowel", "yu", "ㅠ", "유", "yu", [], ["u", "yo"], "yu"),
    (4, "vowel", "ae", "ㅐ", "애", "ae", [], ["e", "a"], "e as in 'bed' (said like ㅔ today)"),
    (4, "vowel", "e", "ㅔ", "에", "e", [], ["ae", "eo"], "e as in 'bed'"),
    (5, "tense", "kk", "ㄲ", "쌍기역", "kk", [], ["g", "k"], "tight k, no puff of air"),
    (5, "tense", "tt", "ㄸ", "쌍디귿", "tt", [], ["d", "t"], "tight t, no puff of air"),
    (5, "tense", "pp", "ㅃ", "쌍비읍", "pp", [], ["b", "p"], "tight p, no puff of air"),
    (5, "tense", "ss", "ㅆ", "쌍시옷", "ss", [], ["s", "jj"], "tight, hissed s"),
    (5, "tense", "jj", "ㅉ", "쌍지읒", "jj", [], ["j", "ch"], "tight j, no puff of air"),
    (6, "vowel", "yae", "ㅒ", "얘", "yae", [], ["ye", "ae"], "ye (like ㅖ)"),
    (6, "vowel", "ye", "ㅖ", "예", "ye", [], ["yae", "e"], "ye"),
    (6, "vowel", "wa", "ㅘ", "와", "wa", [], ["wo", "wae"], "ㅗ + ㅏ = wa"),
    (6, "vowel", "wae", "ㅙ", "왜", "wae", [], ["we", "oe"], "ㅗ + ㅐ = we"),
    (6, "vowel", "oe", "ㅚ", "외", "oe", [], ["wae", "we"], "said 'we' today"),
    (6, "vowel", "wo", "ㅝ", "워", "wo", [], ["wa", "we"], "ㅜ + ㅓ = wo"),
    (6, "vowel", "we", "ㅞ", "웨", "we", [], ["wae", "oe"], "ㅜ + ㅔ = we"),
    (6, "vowel", "wi", "ㅟ", "위", "wi", [], ["ui", "wo"], "ㅜ + ㅣ = wi"),
    (6, "vowel", "ui", "ㅢ", "의", "ui", [], ["wi", "eu"], "ㅡ + ㅣ = ui"),
    (7, "final", "g-fin", "ㄱ", "기역 받침", "k", ["g"], ["b-fin", "ng-fin"], "unreleased k (also ㅋ ㄲ)"),
    (7, "final", "n-fin", "ㄴ", "니은 받침", "n", [], ["l-fin", "ng-fin"], "n"),
    (7, "final", "d-fin", "ㄷ", "디귿 받침", "t", ["d"], ["n-fin", "g-fin"], "unreleased t (also ㅅ ㅆ ㅈ ㅊ ㅌ ㅎ)"),
    (7, "final", "l-fin", "ㄹ", "리을 받침", "l", ["r"], ["n-fin", "d-fin"], "l"),
    (7, "final", "m-fin", "ㅁ", "미음 받침", "m", [], ["b-fin", "ng-fin"], "m"),
    (7, "final", "b-fin", "ㅂ", "비읍 받침", "p", ["b"], ["m-fin", "g-fin"], "unreleased p (also ㅍ)"),
    (7, "final", "ng-fin", "ㅇ", "이응 받침", "ng", [], ["n-fin", "m-fin"], "ng as in 'sing'"),
]
KO_SCRIPT_NOTES = [
    {"st": "hangul", "set": 1, "h": "Blocks",
     "body": "Hangul is written in syllable blocks. A vowel never stands alone: a block with no "
             "consonant sound starts with a silent ㅇ, so ㅏ is written 아 and 아이 is ai."},
    {"st": "hangul", "set": 2, "h": "Building a block",
     "body": "The consonant goes left of a tall vowel (나, 이) or on top of a flat one (노, 누)."},
    {"st": "hangul", "set": 5, "h": "Three kinds of consonant",
     "body": "Plain ㄱ ㄷ ㅂ ㅈ are soft, aspirated ㅋ ㅌ ㅍ ㅊ carry a puff of air, and doubled "
             "ㄲ ㄸ ㅃ ㅉ ㅆ are tight with no air."},
    {"st": "hangul", "set": 7, "h": "Final consonants (batchim)",
     "body": "A consonant under the block closes the syllable. Only seven sounds end a syllable: "
             "k n t l m p ng, so ㅅ ㅆ ㅈ ㅊ ㅌ ㅎ at the end sound t. Before a vowel the final "
             "moves over: 먹어 is said meo-geo."},
]
_KO_FIN_UNIT = {"ㄱ": "g-fin", "ㄴ": "n-fin", "ㄷ": "d-fin", "ㄹ": "l-fin", "ㅁ": "m-fin", "ㅂ": "b-fin",
                "ㅇ": "ng-fin"}
_KO_FIN_READ = {"ㄲ": "g-fin", "ㅋ": "g-fin", "ㅍ": "b-fin",
                **{c: "d-fin" for c in "ㅅㅆㅈㅊㅌㅎ"}}
_KO_INIT_UNIT = {u[3]: u[2] for u in KO_SCRIPT if u[1] != "final" and u[3] in HANGUL_L}
_KO_VOWEL_UNIT = {u[3]: u[2] for u in KO_SCRIPT if u[3] in HANGUL_V}


def hangul_split(ch):
    """A composed Hangul syllable -> (initial, vowel, final) compatibility jamo
    (final "" when open); None for anything else."""
    n = ord(ch) - 0xAC00
    if not 0 <= n < 11172:
        return None
    return HANGUL_L[n // 588], HANGUL_V[n % 588 // 28], HANGUL_T[n % 28]


def hangul_join(l, v, t=""):
    return chr(0xAC00 + HANGUL_L.index(l) * 588 + HANGUL_V.index(v) * 28 + HANGUL_T.index(t))


def ko_romanize(text):
    """Revised Romanization, block by block, with the final moved onto a
    following ㅇ-initial block and ㄹㄹ as ll; None when text has a non-block."""
    blocks = [hangul_split(c) for c in text]
    if not blocks or None in blocks:
        return None
    out = []
    for i, (l, v, t) in enumerate(blocks):
        nxt = blocks[i + 1] if i + 1 < len(blocks) else None
        init = RR_L[l]
        if i and l == "ㄹ" and blocks[i - 1][2] == "ㄹ":
            init = "l"
        elif i and l == "ㅇ" and blocks[i - 1][2] not in ("", "ㅇ"):
            prev = blocks[i - 1][2]
            moved = KO_LIAISON.get(prev, (None, prev))[1]
            init = RR_L.get(moved, "")
            if moved in ("ㅇ", "ㅎ"):    # 좋아 joa: ㅎ drops before a vowel
                init = ""
        fin = RR_T[t]
        if nxt and t not in ("", "ㅇ") and nxt[0] == "ㅇ":
            fin = RR_T[KO_LIAISON[t][0]] if t in KO_LIAISON else ""
        out.append(init + RR_V[v] + fin)
    return "".join(out)



class Korean(LanguageSpec):
    code = "ko"
    name_en = "Korean"
    pack_name = "Korean (A1–B1)"
    tts = "ko-KR"
    stt = "ko-KR"
    tatoeba_code = "kor"
    simplemma_code = "en"        # simplemma has no Korean; "en" returns the surface, fallback_lemma analyses it

    spacy_model = "ko_core_news_sm"
    spacy_n_process = 1
    tagger_attribution = {
        "source": "spaCy ko_core_news_sm 3.8.0 (trained on UD Korean Kaist), plus an eojeol analyser over the "
                  "kaikki.org Wiktionary conjugation tables (packbuilder langs/ko.py)",
        "licence": "CC BY-SA 4.0 (model); MIT (spaCy)",
        "note": "Used at build time only; the pack ships no model files.",
    }

    subtitles_file = "ko_full.txt"
    kaikki_file = "kaikki_ko.jsonl.gz"
    sentences_file = "kor_sentences_detailed.tsv.bz2"
    links_file = "kor-eng_links.tsv.bz2"
    sources = {
        "ko_full.txt": "https://raw.githubusercontent.com/hermitdave/FrequencyWords/master/content/2018/ko/ko_full.txt",
        "kaikki_ko.jsonl.gz": "https://kaikki.org/dictionary/Korean/kaikki.org-dictionary-Korean.jsonl.gz",
        "kor_sentences_detailed.tsv.bz2":
            "https://downloads.tatoeba.org/exports/per_language/kor/kor_sentences_detailed.tsv.bz2",
        "kor-eng_links.tsv.bz2": "https://downloads.tatoeba.org/exports/per_language/kor/kor-eng_links.tsv.bz2",
        TATOEBA_ENG[0]: TATOEBA_ENG[1],
        TATOEBA_AUDIO[0]: TATOEBA_AUDIO[1],
        # NIKL 한국어 학습용 어휘 목록 (2003) grades A/B/C, merged with the TOPIK list by
        # julienshim/combined_korean_vocabulary_list (MIT code; the NIKL list itself is
        # KOGL Type 1). Build-time level floors only; never shipped.
        "nikl_results.tsv":
            "https://raw.githubusercontent.com/julienshim/combined_korean_vocabulary_list/master/results.tsv",
    }
    nikl_file = "nikl_results.tsv"
    versions = {"corpus": "c1", "tag": "t2", "lex": "l1"}

    # typed production on: caseSensitive is irrelevant (no case in Hangul),
    # accents lenient is a no-op (no combining marks to fold), strictFromLevel
    # null since there is nothing lenient-only folds to stop folding at any level.
    typing = {"caseSensitive": False, "accents": "lenient", "strictFromLevel": None}
    show_pron = False            # Hangul is phonetic
    use_audio = False            # 25 permissive clips: TTS ko-KR throughout
    target_len = {"A1": 4, "A2": 5, "B1": 6}      # eojeols (a Korean sentence has few, long words)
    min_len = {"A1": 3, "A2": 3, "B1": 5}
    untranslated_rows = True     # all Tatoeba sentences tagged for frequency/lemma evidence
    extra_corpus_files = ("tools/generated_sentences.tsv",)
    corpus_rank_weight = 1.5     # the subtitle list is colloquial and eojeol-based: corpus counts weigh more
    refill_unexampled = False    # frequency decides the words; generated sentences fill the gaps
    example_shows_word = True
    prefer_headword_sentence = True
    numeral_verb_rule = False
    caps_mark_names = False      # Hangul has no case
    caps_proper_pool = False
    rare_zipf = -1.0             # no rare-reading override: the analyser already chose by frequency
    keep_unseen_keys = False     # a pack word is attested in the tagged corpus (Tatoeba + generated sentences)
    min_corpus_tokens = 2        # ... at least twice (a one-off analysis is no evidence)
    phrase_token_spans = True
    verb_endings = None

    word_re = re.compile(r"[가-힣A-Za-z]+")
    lex_word_re = re.compile(r"^[가-힣]+$")
    sub_token_re = re.compile(r"^[가-힣]+$")
    form_target_re = re.compile(r"\bof ([가-힣]+)")
    fem_of_re = re.compile(r"(?!)")

    group_kpos = dict(DEFAULT_GROUP_KPOS, **{
        "NOUN": ["noun", "counter", "num"], "PRON": ["pron", "noun"], "NUM": ["num", "noun"],
        "VERB": ["verb"], "ADJ": ["adj"], "ADV": ["adv", "conj", "noun"], "DET": ["det", "num"],
        "INTJ": ["intj", "phrase"], "PART": ["particle"], "PROPN": ["name"],
    })
    morph_keep = ()

    forced_closed = ([(w, "NOUN") for w in DAYS + MONTHS + COLOURS] +
                     [(f"{w}:num", "NUM") for w, _ in SINO] + [(n, "NUM") for n, _, _ in NATIVE] +
                     [(w, "PRON") for w in PRONOUNS + THINGS] + [(k, "DET") for k, _ in DEMONSTR] +
                     [(k, "DET") for k in ("이런", "그런", "저런")] +
                     QUESTION + TIME +
                     [(k, "PART") for k in PARTICLE_GLOSS] +
                     [(g, "INTJ") for g in GREETINGS if g not in GREETING_KEY] +
                     [(p, "PHRASE") for p in PHRASES])
    allowed_num = {f"{w}:num" for w, _ in SINO} | {n for n, _, _ in NATIVE}
    multiword = {p: tuple(p.split()) for p in PHRASES}
    fixed_gloss = {**{(k, "PART"): g for k, g in PARTICLE_GLOSS.items()},
                   **{(p, "PHRASE"): g for p, g in PHRASES.items()},
                   **{(g, "INTJ"): gl for g, gl in GREETINGS.items() if g not in GREETING_KEY},
                   **{(f"{w}:num", "NUM"): f"{g} (Sino-Korean)" for w, g in SINO},
                   **{(n, "NUM"): f"{g} (native Korean)" for n, g, _ in NATIVE},
                   **{(k, "DET"): g for k, g in DEMONSTR},
                   **{(k, "DET"): g for k, g in ADNOMINAL_DET.items()},
                   **{(k2, "NOUN"): gl for hs in HOMOGRAPHS.values() for k2, gl, _ in hs},
                   # forced words whose Wiktionary entry is unusable (literary-only, a contraction)
                   ("그들", "PRON"): "they", ("뭐", "PRON"): "what (spoken)"}
    function_lemmas = set(PARTICLE_GLOSS) | {k for k, _ in DEMONSTR}
    # homograph second entries below a 20% share of their spelling's tagged
    # corpus tokens (measured 2026-09-24: 말:horse 10%, 차:tea 8%, 사과:apology 4%,
    # 밤:chestnut 0%, 배:pear 0%) are not taught; their tokens stay unlinked
    # rather than linking to the wrong sense. Kept: 눈:snow 29%, 배:ship 23%, 다리:bridge 40%.
    # everyday words ranked just past the 2000 cut, kept by hand: 졸리다 "sleepy",
    # 이빨 "tooth" (the pack has no other tooth word), 베개, 습관, 여우
    keep_keys = frozenset({("졸리다", "VERB"), ("이빨", "NOUN"), ("베개", "NOUN"), ("습관", "NOUN"), ("여우", "NOUN")})
    drop_keys = {**{(k, "NOUN"): None for k in ("말:horse", "차:tea", "사과:apology", "밤:chestnut", "배:pear")},
                 # split-off syllables and names the analyser can still produce
                 **{(k, "NOUN"): None for k in ("존", "라", "동", "고", "엿", "여", "진", "새미", "사", "도",
                                                "자", "이")},
                 ("고", "DET"): None,
                 ("거지", "NOUN"): ("것", "NOUN"), ("거야", "NOUN"): ("것", "NOUN"),
                 ("작", "NOUN"): ("작다", "ADJ"), ("추", "NOUN"): ("추다", "VERB"),
                 ("뭔지", "NOUN"): ("뭐", "PRON"), ("이젠", "NOUN"): ("이제", "NOUN"),
                 ("원래", "NOUN"): ("원래", "ADV"), ("참", "NOUN"): ("참", "ADV"),
                 ("천", "NOUN"): ("천:num", "NUM"),
                 ("드릴", "NOUN"): ("드리다", "VERB"),
                 ("아무도", "PRON"): ("아무", "PRON"), ("아무것도", "PRON"): ("아무것", "NOUN"),            # 전해 드릴게요
                 ("미안", "NOUN"): ("미안하다", "ADJ"),           # bare 미안 is 반말
                 **{(k, "NOUN"): None for k in ("마크", "피트", "데이", "모", "유", "한데", "나치")},
                 ("맘", "NOUN"): ("마음", "NOUN"),
                 ("불구하다", "VERB"): None,     # only in the grammar pattern -에도 불구하고 "despite"
                 # low-rank NIKL 고급 abstractions give their places to everyday words (keep_keys)
                 **{(k, "NOUN"): None for k in ("공공", "경향", "관점", "이래", "수면")},
                 # suicide lines are dropped at every level (policy), so these are not taught
                 ("자살", "NOUN"): None, ("자살하다", "VERB"): None,
                 ("해도", "NOUN"): None,        # 해도 "chart": the analyser's reading of 해도 "even if (one) does"
                 # verb forms Wiktionary also lists as rare nouns (위해 "harm", 해서 "sea-west")
                 ("위해", "NOUN"): ("위하다", "VERB"), ("해서", "NOUN"): ("하다", "VERB"),
                 # id map v1 is frozen: these X하다 verbs (counted once 연구하고 stopped
                 # splitting as 연구 + 하고) would displace 졸리다 at the cut; the noun
                 # carries the sense and their tokens link there
                 ("연구하다", "VERB"): ("연구", "NOUN"), ("산책하다", "VERB"): ("산책", "NOUN"),
                 # the honorific 드시다 "to eat, to drink" (드세요) is taught as 먹다, as 드리다 is as 주다
                 ("드시다", "VERB"): ("먹다", "VERB"),
                 # the spoken 이거/그거/저거 are shown as 이것/그것/저것 (their tokens link there)
                 ("이거", "PRON"): ("이것", "PRON"), ("그거", "PRON"): ("그것", "PRON"), ("저거", "PRON"): ("저것", "PRON"),
                 ("일다", "VERB"): None,
                 ("가", "NOUN"): ("가다", "VERB"),              # 저리 가, 가 본 적: the verb
                 ("걸", "NOUN"): ("것", "NOUN"),                # 다른 걸로 = 것으로
                 # humble forms the shared lexicon drops as "form of": linked to the plain verb
                 ("드리다", "VERB"): ("주다", "VERB"), ("도와드리다", "VERB"): ("돕다", "VERB")}   # names, 발렌타인 데이

    bad_text_re = re.compile(VULGAR_KO)
    drop_all_levels = drop_all_re(r"(?:" + DROP_ALL_KO + r")|(?<![A-Za-z])(?:" + DROP_ALL_KO_EN + r")(?![A-Za-z])")
    sensitive_re = re.compile(r"(?:" + SENSITIVE_KO + r")|(?<![A-Za-z])(?:" + SENSITIVE_EN + "|" + SENSITIVE_KO_EN +
                              r")(?![A-Za-z])", re.I)
    sensitive_gloss_re = re.compile(r"\b(" + SENSITIVE_GLOSS_EN + r")\b", re.I)
    lower_level_gloss_re = re.compile(r"\b(kill\w*|murder\w*|rape[ds]?|raping|rapist|shoot\w*|stab\w*|"
                                      r"porn\w*|prostitut\w*|suicid\w*|bomb\w*|explod\w*|explosi\w*|"
                                      r"poison\w*|blood\w*|corpse\w*|dead body)\b", re.I)

    report_title = "Korean A1-B1 pack (corpus-tagged)"
    forced_description = ("days, months, Sino-Korean and native numerals, pronouns, demonstratives, question "
                          "words, time words, colours, particles and the copula, greetings and set phrases, "
                          "A1 core list")
    numeral_exclusion = "numeral outside the taught number words"

    qa_closed_sets = {
        "days": " ".join(DAYS), "months": " ".join(MONTHS),
        "sino numerals": " ".join(f"{w}:num" for w, _ in SINO), "native numerals": " ".join(n for n, _, _ in NATIVE),
        "pronouns": " ".join(PRONOUNS + THINGS), "demonstratives": " ".join(k for k, _ in DEMONSTR),
        "question": " ".join(w for w, _ in QUESTION), "time": " ".join(w for w, _ in TIME),
        "particles": " ".join(PARTICLE_GLOSS), "greetings": " ".join(g for g in GREETINGS if g not in GREETING_KEY),
        "colours": " ".join(COLOURS),
    }

    GEN_BASE = 1_000_000_000

    def __init__(self, repo=None):
        super().__init__(repo)
        self._morph = None
        self._wf = None
        self._hermit = None
        self.post_stats = Counter()
        self._mispaired = None

    # ---- frequency ------------------------------------------------------------
    def ko_zipf(self, w):
        """zipf of a Korean word from wordfreq's ko list without its mecab
        tokenizer: the list's own entry, a verb/adjective by its stem (먹다 ->
        먹), an X하다 verb by X less 0.5."""
        if self._wf is None:
            from wordfreq import get_frequency_dict
            self._wf = get_frequency_dict("ko")
        f = self._wf.get(w)
        if not f and w.endswith("다") and len(w) >= 2:
            f = self._wf.get(w[:-1])
            if not f and w.endswith("하다") and len(w) >= 3 and self._wf.get(w[:-2]):
                return max(round(math.log10(self._wf[w[:-2]] * 1e9) - 0.5, 2), 0.0)
        return round(math.log10(f * 1e9), 2) if f else 0.0

    def _patch_wordfreq(self):
        """wordfreq tokenises Korean with mecab-ko (not a dependency): route
        zipf_frequency(w, "ko") to ko_zipf; other languages are untouched."""
        import wordfreq
        if getattr(wordfreq.zipf_frequency, "_ko_route", None) is not None:
            wordfreq.zipf_frequency._ko_route[0] = self
            return
        orig = wordfreq.zipf_frequency
        route = [self]

        def zipf_frequency(word, lang, *a, **k):
            if lang == "ko":
                return route[0].ko_zipf(word)
            return orig(word, lang, *a, **k)
        zipf_frequency._ko_route = route
        wordfreq.zipf_frequency = zipf_frequency

    def bind_lexicon(self, lexicon):
        self._patch_wordfreq()       # before any zipf lookup (the tag stage may be cached)
        self.level_floor = self.nikl_floors()
        self.level_ceiling = self.nikl_ceilings()
        self._override_entries(lexicon)

    def _override_entries(self, lexicon):
        """A hand gloss (tools/gloss_overrides.json) becomes the entry of a word
        Wiktionary files under another part of speech only (지치다: Wiktionary
        adj, a verb in use and in CANON). Without it core finds no entry for
        the corpus POS and drops the word."""
        for key in sorted(self.gloss_overrides or {}):
            lem, _, lab = key.rpartition("|")
            kp = self.group_kpos.get(lab.upper())
            if not lem or not kp or not lexicon.E.get(lem) or lexicon.usable_entries(lem, kp):
                continue
            lexicon.E[lem].append({"p": kp[0],
                          "s": [[self.gloss_overrides[key], "", [], ""]], "ht": set()})

    def nikl_floors(self):
        """NIKL grade as a level floor: a word graded 중급 (B) only is never
        A1, one graded 고급 (C) only never below B1 (a word graded at several
        homographs takes its lowest grade). Ungraded words keep their
        frequency band."""
        p = self.repo / ".cache" / self.nikl_file
        if not p.exists():
            return {}
        grade = {}
        self.nikl_grades = defaultdict(set)
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines()):
            f = line.split("\t")
            if i == 0 or len(f) < 6 or f[5] not in ("A", "B", "C"):
                continue
            w = re.sub(r"\d+$", "", f[1]).strip()
            grade[w] = min(grade.get(w, "C"), f[5])
            self.nikl_grades[w].add(f[5])
        floor = {}
        for w, gr in grade.items():
            if gr == "A":
                continue
            lv = "A2" if gr == "B" else "B1"
            for g in ("NOUN", "VERB", "ADJ", "ADV", "PRON", "DET", "NUM", "INTJ"):
                floor[(w, g)] = lv
        self.nikl_grade = grade
        return floor

    def nikl_ceilings(self):
        """NIKL grade as a level ceiling too: a word graded 초급 (A) only is never
        B1. The colour adjectives and 남동생 (beside 여동생) are capped at A2 by
        hand."""
        ceil = {}
        for w, grs in getattr(self, "nikl_grades", {}).items():
            if grs == {"A"}:
                for g in ("NOUN", "VERB", "ADJ", "ADV", "PRON", "DET", "NUM", "INTJ"):
                    ceil[(w, g)] = "A2"
        for w, g in HAND_CEILING_A2:
            ceil[(w, g)] = "A2"
        return ceil

    def morph(self):
        if self._morph is None:
            self._patch_wordfreq()
            # the forced lists fix the group of their words (없다 ADJ, 있다 VERB)
            canon = dict(CANON)
            for w, g in self.forced:
                if g in ("NOUN", "VERB", "ADJ", "ADV", "PRON", "NUM", "DET") and ":" not in w:
                    canon.setdefault(w, g)
            self._morph = KoMorph(self.repo / ".cache" / self.kaikki_file, HAND, CLOSED, canon, self.ko_zipf)
            sub = self.repo / ".cache" / self.subtitles_file
            if sub.exists():
                counts = {}
                with open(sub, encoding="utf-8") as f:
                    for i, line in enumerate(f):
                        if i >= 200000:
                            break
                        parts = line.split()
                        if len(parts) == 2:
                            counts[parts[0]] = int(parts[1])
                self._morph.set_evidence(counts)
        return self._morph

    def subtitle_lemmas(self):
        """lemma -> subtitle count: every frequency-list eojeol (top 100k)
        analysed, counted for its first piece (학교에서 for 학교, 시작했어 for
        시작하다)."""
        if self._hermit is None:
            mo = self.morph()
            h = Counter()
            with open(self.repo / ".cache" / self.subtitles_file, encoding="utf-8") as f:
                for i, line in enumerate(f):
                    if i >= 100000:
                        break
                    parts = line.split()
                    if len(parts) != 2 or not HANGUL_RE.match(parts[0]):
                        continue
                    a = mo.analyse(parts[0])
                    if a and a[1][0][2] not in ("PART", "PROPN"):
                        h[a[1][0][1]] += int(parts[1])
            self._hermit = h
        return self._hermit

    def extra_wordfreq(self, raw):
        """wordfreq's Korean list counts mecab morphemes: endings and suffixes
        (고, 기, 적, 성), verb stems (먹, 하) and the noun half of X하다 verbs
        (시작 in 시작했어요). Each surface's count is split over its readings
        by their subtitle-list counts: the noun X, the verb X다 (key "X다"),
        the verb X하다; a morpheme no subtitle word reads as a word is
        dropped, and none gets more than 4x the typical wordfreq/subtitle
        ratio (a grammatical 고 is not the noun "height")."""
        mo = self.morph()
        h = self.subtitle_lemmas()
        plans = {}
        for x, v in raw.items():
            if x in mo.hand or len(x) > 6:
                continue
            reads = {}
            for lem, g in mo.hosts(x) + [(l2, g2) for l2, g2 in mo.closed.get(x, ())]:
                reads[lem] = h.get(lem, 0)
            for p in mo.pos.get(x, ()):
                if p not in ("verb", "adj"):
                    reads[x] = h.get(x, 0)
            for lem in mo.raw.get(x, ()):
                reads[lem] = h.get(lem, 0)
            # mecab keeps a contracted stem + ending as one surface: the
            # infinitive (해, 와) and the past stem (끝났, 다쳤, 했)
            for lem in mo.inf.get(x, ()):
                reads[lem] = h.get(lem, 0)
            if fin(x[-1]) == T_IDX["ㅆ"]:
                for lem in mo.inf.get(x[:-1] + set_fin(x[-1], 0), ()):
                    reads[lem] = h.get(lem, 0)
            if x + "하다" in mo.pos:
                reads[x + "하다"] = h.get(x + "하다", 0)
            plans[x] = reads
        ratios = sorted(v / sum(plans[x].values()) for x, v in raw.items()
                        if x in plans and sum(plans[x].values()) > 0 and len(plans[x]) == 1)
        cap = 4 * ratios[len(ratios) // 2] if ratios else float("inf")
        st = Counter()
        for x, reads in sorted(plans.items()):
            v = raw.pop(x)
            tot = sum(reads.values())
            if not tot:
                if x in reads and (len(x) >= 2 or "det" in mo.pos.get(x, ())):
                    raw[x] = v          # a word of its own the subtitle analysis reads otherwise (여러, 새)
                    st["kept as its own headword"] += 1
                    continue
                st["dropped (no subtitle word reads it)"] += 1
                continue
            v = min(v, cap * tot)
            for lem, c in sorted(reads.items()):
                if c:
                    k = lem if lem != x else x
                    raw[k] = raw.get(k, 0) + v * c / tot
            st["split"] += 1
        # a verb mecab splits into other morphemes (끝나다 = 끝 + 나, 오래되다 =
        # 오래 + 되) has no wordfreq count: estimated from its subtitle count at
        # the median wordfreq/subtitle ratio
        med = ratios[len(ratios) // 2] if ratios else 0
        for lem, c in sorted(h.items()):
            if lem.endswith("다") and mo.pos.get(lem, set()) & {"verb", "adj"} and lem not in raw and c >= 20:
                raw[lem] = c * med
                st["verb estimated from subtitles (no wordfreq morpheme)"] += 1
        self.post_stats.update({f"wordfreq {k}": n for k, n in st.items()})

    def fallback_lemma(self, surface, lemma):
        """A frequency-list surface the corpus never shows: an eojeol from the
        subtitle list (학교에서 -> 학교, 먹었어요 -> 먹다) or a wordfreq
        morpheme (먹 -> 먹다)."""
        a = self.morph().analyse(surface)
        return a[1][0][1] if a else surface

    # ---- tagging ------------------------------------------------------------------
    def fix_sentence(self, toks, row, doc):
        """spaCy's eojeol tokens -> analysed pieces. A noun + particles eojeol
        becomes the noun token plus one token per particle; the copula and the
        하다 of an unlisted X하다 are tokens of their own. Pieces after the
        first are tagged X (not counted in sentence length; post_resolve links
        them); names (nq) are PROPN."""
        mo = self.morph()
        dt = [t for t in doc if not t.is_space]
        # one eojeol the tokenizer cut in two before a comma (안녕하세 + 요 + ,) is
        # joined back: pieces with no space between them, both Hangul
        merged, tags = [], []
        for j, tk in enumerate(toks):
            ws = dt[j].whitespace_ if j < len(dt) else " "
            tag = dt[j].tag_ if j < len(dt) else ""
            if merged and not merged[-1][1] and HANGUL_RE.match(tk[0]) and HANGUL_RE.match(merged[-1][0][0]):
                a = merged[-1][0]
                merged[-1] = ((a[0] + tk[0], a[1] + tk[1], a[2], a[3]), ws)
                continue
            merged.append((tuple(tk), ws))
            tags.append(tag)
        toks = [m[0] for m in merged]
        en_words = set(re.findall(r"[a-z]+", (row[3] or "").lower()))
        # the English names someone: a capitalised word after the first
        # (sentence-initial words are capitalised anyway), "I" aside
        names_en = any(w not in EN_NAME_STOP for w in re.findall(r"(?<=[^.!?\"]\s)[A-Z][a-z']+", row[3] or ""))
        # every eojeol analysed first, so a reading can look at its neighbours
        pre = {}
        for j, (text, lemma, upos, ms) in enumerate(toks):
            if upos in ("PUNCT", "SYM", "SPACE") or not re.search(r"[가-힣]", text) or not HANGUL_RE.match(text):
                pre[j] = None
                continue
            h = hint_of(tags[j] if j < len(tags) else "")
            pre[j] = (h, mo.analyse(text, h))
        en_names = self._en_names(row[3] or "")
        if en_names:
            # a name already written as a non-dictionary word (도쿄 for Tokyo)
            # is not claimed again by a dictionary word (대학)
            taken = set()
            for j2, t2 in enumerate(toks):
                e2 = t2[0]
                if pre.get(j2) is None:
                    continue
                splits = [k2 for k2 in range(len(e2), 0, -1)
                          if k2 == len(e2) or particle_chains(e2[:k2], e2[k2:]) or
                          e2[k2:] in (COP_CONS if has_batchim(e2[:k2]) else COP_VOW)]
                if pre[j2][1] or any(e2[:k2] in mo.pos for k2 in splits):
                    continue                    # a word the analyser reads (+ particles): not a written name
                taken |= {name_key_ko(e2[:k2]) for k2 in splits}
            en_names = {w for w in en_names if name_key(w) not in taken}
        out = []
        pend = []           # (index in out, surface) of analysed numeral candidates
        for j, (text, lemma, upos, ms) in enumerate(toks):
            xpos = tags[j] if j < len(tags) else ""
            if upos in ("PUNCT", "SYM", "SPACE") or not re.search(r"[가-힣A-Za-z0-9]", text):
                out.append([text, text, "PUNCT", ""])
                continue
            if re.search(r"[0-9]", text):
                out.append([text, text, "NUM", "Ko=digit"])
                continue
            if re.search(r"[A-Za-z]", text) or not HANGUL_RE.match(text):
                out.append([text, text, "PROPN", "Ko=latin|G=PROPN"])
                continue
            hint = hint_of(xpos)
            pieces = None
            kind = None
            if hint == "q":
                pieces = self._name_pieces(text)
                kind = "name" if pieces else None
            if pieces is None:
                a = self._route(j, toks, pre, en_words)
                if a:
                    kind, pieces = a
            if pieces and en_names and kind not in ("name", "hand", "closed") and len(pieces) > 1 and len(pieces[0][0]) == 1:
                # 대만은 "Taiwan": a Wiktionary name longer than the one-syllable noun the analyser split off (대 + 만)
                for k in range(len(text), 1, -1):
                    host, rest = text[:k], text[k:]
                    if host not in mo.names or host in mo.pos:
                        continue
                    ch = particle_chains(host, rest) if rest else [[]]
                    if ch:
                        kind, pieces = "name", [(host, host, "PROPN")] + [(s2, key, "PART") for s2, key in ch[0]]
                        break
                    if rest in (COP_CONS if has_batchim(host) else COP_VOW):
                        kind, pieces = "name", [(host, host, "PROPN"), (rest, "-이다", "PART")]
                        break
            if pieces and en_names and kind != "name":
                np_ = self._en_named(text, pieces, en_names)
                if np_:
                    kind, pieces = "name", np_
            named = [n for n in NAMES if text.startswith(n) and re.search(r"\b" + NAMES[n] + r"\b", row[3] or "")
                     and (n == text or particle_chains(n, text[len(n):]) or
                          text[len(n):] in (COP_CONS if has_batchim(n) else COP_VOW))]
            if pieces is None or named:
                np_ = self._unknown_name(text, names_en, row[3] or "")
                if np_:
                    kind, pieces = "name", np_
            if pieces is None:
                g = upos if upos in ("NOUN", "VERB", "ADJ", "ADV") else "X"
                out.append([text, text, g, f"Ko=unk|X={xpos}"])
                continue
            for n, (s, lem, g) in enumerate(pieces):
                if n and kind == "noun+hada" and lem == "되다":
                    out.append([s, s, "X", "Ko=gram"])     # 제공됩니다: the passive 되다 of X하다, not "to become"
                    continue
                if n == 0 and g == "NOUN" and lem in HOMOGRAPHS and en_words:
                    for k2, _, cues in HOMOGRAPHS[lem]:
                        if en_words & cues:
                            lem = k2
                            break
                up = g if n == 0 and g != "PART" else "X"      # particles never count toward length
                if g == "PROPN":
                    up = "PROPN"
                out.append([s, lem, up, f"Ko={kind}|G={g}|X={xpos}"])
                if n == 0:
                    pend.append((len(out) - 1, text))
        # -ㄹ지도 모르다 "might": the 지도 before 모르다 is grammar, not 지도 "map"
        for i, t in enumerate(out):
            if t[0] == "지도" and t[2] != "PUNCT":
                nxt = next((u for u in out[i + 1:] if u[2] != "PUNCT"), None)
                if nxt and nxt[0].startswith(("모르", "모른", "몰라", "몰랐", "몰랑")):
                    out[i] = [t[0], t[0], "X", "Ko=gram"]
            # -고 나서 "after doing": 나서 is grammar, not 나서다 "to step forward"
            if t[0] in ("나서", "나서는", "나서도", "나서야") and i and out[i - 1][0].endswith("고"):
                out[i] = [t[0], t[0], "X", "Ko=gram"]
        # numerals: a numeral spelling right before a counter (삼 년, 두 명, 천 원)
        # or one the tagger reads as a numeral (nn*: 두 나라, 한 부분, 오 곱하기 오)
        # is the number; elsewhere 이/일/팔 keep their word reading
        words = [i for i, t in enumerate(out) if t[2] != "PUNCT" and (t[2] != "X" or "Ko=unk" in t[3])]
        # 건/걸/게 after a verb's modifier form (잊어버린 건, 하는 게, 한 걸) is 것 + particle, not 걸다
        prev = None
        for i, t in enumerate(out):
            if t[2] == "PUNCT":
                prev = None
                continue
            nxt_noun = i + 1 < len(out) and out[i + 1][2] in ("NOUN", "NUM")
            if t[0] == "한" and t[1] == "한" and not (prev is not None and limit_modifier(out[prev]) and not nxt_noun):
                out[i] = [t[0], "하다", "VERB", f"Ko=verb|G=VERB|{t[3].split('|')[-1]}"]   # 한 말: did, not -는 한
            if t[0] in ("건", "걸", "게") and t[1] != "것" and prev is not None:
                p = out[prev]
                last = p[0][-1]
                if p[2] in ("VERB", "ADJ") and "가" <= last <= "힣" and (ord(last) - 0xAC00) % 28 in (4, 8):
                    out[i] = [t[0], "것", "NOUN", f"Ko=closed|G=NOUN|{t[3].split('|')[-1]}"]
            if t[2] != "X" or "Ko=unk" in t[3]:
                prev = i
        # 네 "yes" stands first or before punctuation; inside a clause (이건 네 것이다) it is 너의 "your"
        words0 = [i for i, t in enumerate(out) if t[2] != "PUNCT"]
        for n, i in enumerate(words0):
            t = out[i]
            if t[0] == "네" and t[1] == "네" and n > 0 and i + 1 < len(out) and out[i + 1][2] != "PUNCT":
                out[i] = [t[0], "너", "PRON", f"Ko=closed|G=PRON|{t[3].split('|')[-1]}"]
            elif t[0] == "네" and n == 0 and (i + 1 >= len(out) or out[i + 1][2] == "PUNCT"):
                out[i] = [t[0], "네", "INTJ", f"Ko=closed|G=INTJ|{t[3].split('|')[-1]}"]    # 네, ... = yes
        # 네 before a noun is 넷 "four" or 너의 "your": the translation decides when it has one
        en_raw = (row[3] or "").lower()
        ne_four = bool(re.search(r"\b(four|fourth|4)\b", en_raw)) if en_raw else None
        for a, b in zip(words, words[1:] + [None]):
            t = out[a]
            if t[0] == "네" and ne_four is False and "Ko=" in t[3]:
                continue                                          # 네 고양이 = your cat
            if (t[0] == "네" and ne_four and "Ko=" in t[3] and b is not None
                    and out[b][2] in ("NOUN", "NUM")):
                key, g = NUM_KEY[t[0]]
                out[a] = [t[0], key, "NUM", f"Ko=num|G=NUM|{t[3].split('|')[-1]}"]
                continue                                          # 네 계절 = four seasons
            if t[0] == "이" and en_raw and b is not None:
                cw = COUNTER_EN.get(out[b][0], r"\w+")
                if not re.search(r"\b(two|2)[- ](" + cw + r")\b|\bsecond\b|\b2nd\b", en_raw):
                    continue                # 이 일 = this work, 이 분 = this person: "two" only when the English counts it
            pw = words[words.index(a) - 1] if words.index(a) else None
            if t[0] == "한" and pw is not None and limit_modifier(out[pw]) and not (b is not None and out[b][2] in ("NOUN", "NUM")):
                continue                    # 살아 있는 한, 가능한 한 "as long as": the noun 한
            if t[0] == "한" and b is not None and out[b][0] in VERB_MOD_NOUNS:
                continue                    # 네가 한 일, 톰이 한 말: 하다 "did", never "one"
            if b is not None and ((t[0] in SINO_DIGITS and out[b][0] in NATIVE_SERIES) or
                                  (t[0] in NATIVE_DETS and out[b][0] in SINO_SERIES)):
                continue
            if t[0] in NUM_KEY and "Ko=" in t[3] and ("|X=nn" in t[3] or (b is not None and out[b][1] in COUNTERS)):
                key, g = NUM_KEY[t[0]]
                out[a] = [t[0], key, "NUM", f"Ko=num|G=NUM|{t[3].split('|')[-1]}"]
                # the counter after a numeral is the counter noun (한 잔 = one cup, not 자다)
                if (b is not None and out[b][0] in COUNTERS and out[b][1] != out[b][0]
                        and out[b][0] in mo.pos and mo.pos[out[b][0]] & {"noun"}):
                    out[b] = [out[b][0], out[b][0], "NOUN", f"Ko=closed|G=NOUN|{out[b][3].split('|')[-1]}"]
        return out

    # ---- reading choice in context ------------------------------------------------
    def _route(self, j, toks, pre, en_words):
        """The analyser's reading of eojeol j, revised with its neighbours and
        the English translation:
        - a verb reading whose cue (hand table or Wiktionary gloss) is in the
          English wins over another verb reading (살 = 사다 "buy" / 살다);
          들어/들었 is 들다 unless the English hears or listens;
        - a frequent noun or numeral spelled like the verb form, alone before a
          noun or with a particle or copula (사고 때문에, 신고는, 노래야, 둘 중),
          is the noun when no verb reading is attested by the English;
        - 온 before a noun is "whole" when the English says so;
        - 하나(요) ending a question or a clause is 하다."""
        mo = self.morph()
        if not pre.get(j):
            return None
        if not pre[j][1]:
            nom = self._nominal(toks[j][0], pre[j][0])     # 넷, 다섯이: a numeral the analyser has no entry for
            return nom if nom and nom[1][0][2] == "NUM" else None
        hint, (kind, pieces) = pre[j]
        text = toks[j][0]
        g, lem = pieces[0][2], pieces[0][1]
        nxt_g, nxt_t, nx = "END", "", None
        if j + 1 < len(toks):
            nxt_t = toks[j + 1][0]
            nx = pre.get(j + 1)
            nxt_g = nx[1][1][0][2] if nx and nx[1] else ("PUNCT" if nx is None else "UNK")
        nominal_next = nxt_g in ("NOUN", "PRON", "NUM", "DET")
        # a noun + copula next is a predicate (아빠 차는 초록색이에요): 는 before it is the topic marker
        nominal_arg_next = nominal_next and not (nx and nx[1] and nx[1][0] == "noun+cop")
        clause_end = nxt_g in ("PUNCT", "END") and ("?" in nxt_t or "," in nxt_t)
        prev_obj = False
        if j and pre.get(j - 1) and pre[j - 1][1]:
            prev_obj = pre[j - 1][1][1][-1][1] in ("-을/를", "-에", "-에게", "-한테", "-(으)로", "-에서")
        verbs = {}
        for c, k2, p in mo.candidates(text, hint):
            if k2 == "verb" and c <= 1:
                verbs.setdefault(p[0][1], list(p))
        if text in ("하나", "하나요") and clause_end and "하다" in verbs:
            return "verb", verbs["하다"]
        if text == "온" and nominal_next and en_words & {"whole", "entire", "all", "every", "everyone", "everybody"}:
            return "closed", [("온", "온", "DET")]
        if len(pieces) == 2 and pieces[0][1] in ("안", "못") and pieces[1][2] in ("VERB", "ADJ"):
            # 안들어요 written without the space: the verb part follows the translation too
            sub = text[len(pieces[0][0]):]
            vs = {}
            for c, k2, p in mo.candidates(sub, hint):
                if k2 == "verb" and c <= 1:
                    vs.setdefault(p[0][1], list(p))
            hit = [v for v in sorted(vs) if mo.cues(v) & en_words]
            if len(hit) == 1 and hit[0] != pieces[1][1]:
                return kind, [pieces[0]] + vs[hit[0]]
            if pieces[1][1] == "듣다" and "들다" in vs and not (mo.cues("듣다") & en_words):
                return kind, [pieces[0]] + vs["들다"]
        if kind == "hand" and len(pieces) == 1 and pieces[0][2] == "PRON" and is_syl(text[-1]) \
                and fin(text[-1]) in (T_IDX["ㄴ"], T_IDX["ㄹ"]) and nxt_t.startswith(BOUND_AFTER_MOD):
            vv = sorted(v for v in verbs if verbs[v][0][0] == text)
            if vv:                         # 화가 난 것: 나다's modifier before a bound noun, not 난 = 나는
                return "verb", verbs[vv[0]]
        if kind == "noun+cop" and pieces[0][2] == "NOUN":
            tail = "".join(x[0] for x in pieces[1:])
            if tail.startswith("기"):
                if verbs and not (mo.noun_cues(lem) & en_words):
                    # 배우기 쉽다: the verb + nominaliser -기, not 배우 "actor" + copula
                    hit = [v for v in sorted(verbs) if mo.cues(v) & en_words]
                    return "verb", verbs[(hit or sorted(verbs))[0]]
        if kind == "noun+p" and pieces[0][2] in ("NOUN", "PRON") and not (mo.noun_cues(lem) & en_words):
            for c, k2, p in mo.candidates(text, hint):
                if k2 == "exact" and p[0][2] == "NOUN" and mo.noun_cues(p[0][1]) & en_words:
                    return k2, list(p)     # 철도 "railway", not 철 "iron" + 도, when the English says so
        if g not in ("VERB", "ADJ"):
            return kind, pieces
        if kind == "verb":
            verbs.setdefault(lem, list(pieces))
        hits = [v for v in sorted(verbs) if mo.cues(v) & en_words]
        last = text[-1]
        adnominal = (is_syl(last) and fin(last) in (T_IDX["ㄴ"], T_IDX["ㄹ"])) or text.endswith(("는", "던"))
        if adnominal and not hits and nxt_g in ("VERB", "ADJ", "ADV"):
            # a modifier needs a noun after it: 이를 닦으세요, 그를 믿어요 are noun + case particle
            for c, k2, p in mo.candidates(text, hint):
                if k2 in ("noun+p", "exact", "hand") and len(p) > 1 and all(x[2] == "PART" for x in p[1:]) \
                        and p[-1][1] in ("-을/를", "-은/는") and (p[0][2] == "PRON" or (
                            p[0][2] == "NOUN" and len(p[0][0]) >= 2 and self.ko_zipf(p[0][1]) >= 3.5)):
                    return k2, list(p)
        if len(hits) == 1 and hits[0] != lem:
            kind, pieces, lem = "verb", verbs[hits[0]], hits[0]
        elif lem == "듣다" and "들다" in verbs and not (mo.cues("듣다") & en_words):
            pieces, lem = verbs["들다"], "들다"
        if hits:
            return kind, pieces
        if not hits:
            # 다시는 "again" + topic, not 달다 + honorific -시- + -는: a frequent
            # adverb/noun host with particles wins when the English attests it
            for c, k2, p in mo.candidates(text, hint):
                if k2 in ("adv+p", "noun+p") and p[0][2] in ("ADV", "NOUN") and len(p) > 1 \
                        and all(x[2] == "PART" for x in p[1:]) and self.ko_zipf(p[0][1]) >= 4.5 \
                        and mo.noun_cues(p[0][1]) & en_words:
                    return k2, list(p)
        nom = self._nominal(text, hint)
        if not nom:
            return kind, pieces
        if nom[1][0][2] == "NOUN" and nom[1][-1][1] == "-이다" and text.endswith("시다") and not lem.endswith("시다"):
            return nom                     # 남한의 도시다: 도시 + plain copula, not 돌다 + honorific -시다
        if nom[1][0][2] != "NUM" and mo.noun_cues(nom[1][0][1]) & en_words:
            return nom                     # 북한의 도시다 "a city": the English attests the noun, not the verb
        if nom[1][0][2] == "NUM":
            if clause_end or (adnominal and nxt_t.startswith(BOUND_AFTER_MOD)):
                return kind, pieces        # 열 수 있어요, 둘 곳: the verb's modifier
            return nom
        if len(nom[1]) == 1:
            if adnominal or prev_obj or not nominal_next:
                return kind, pieces        # 살 수, 영화를 보고, 가게 되다: the verb form
            return nom
        if nom[1][-1][0] in ("는", "은") and nominal_arg_next:
            return kind, pieces            # 가지는 사람: the verb's modifier
        tail = "".join(x[0] for x in nom[1][1:])
        if tail in VERBISH_TAILS or tail.endswith("요") or (tail == "하고" and verbs):
            return kind, pieces            # 가세요, 가지고: a verb ending, not noun + 요 / copula 고
        return nom

    def _nominal(self, E, hint):
        """The best reading of E as a frequent noun, pronoun or numeral, alone or
        with particles/copula (2+ syllable host, or a native numeral)."""
        mo = self.morph()
        best = None
        for k in range(1, len(E) + 1):
            host, rest = E[:k], E[k:]
            if host in NUM_KEY and NUM_KEY[host][0] in NUM_WORDS and host not in NATIVE_DETS:
                ch = particle_chains(host, rest) if rest else [[]]
                if ch:
                    return "closed", [(host, NUM_KEY[host][0], "NUM")] + [(s2, key, "PART") for s2, key in ch[0]]
                if rest in (COP_CONS if has_batchim(host) else COP_VOW):
                    return "closed", [(host, NUM_KEY[host][0], "NUM"), (rest, "-이다", "PART")]   # 셋이에요
        for c, k2, p in mo.candidates(E, hint):
            if k2 not in ("exact", "closed", "noun+p", "noun+cop", "hand") or p[0][2] not in ("NOUN", "PRON", "NUM"):
                continue
            host, key = p[0][0], p[0][1]
            if any(x[2] != "PART" for x in p[1:]):
                continue
            if key not in NUM_WORDS and (len(host) < 2 or self.ko_zipf(key) < 3.5):
                continue
            if best is None or c < best[0]:
                best = (c, k2, [tuple(x) for x in p])
        return (best[1], best[2]) if best else None

    # ---- names the English carries (마리 = Mary) ---------------------------------------
    def _en_names(self, en):
        """Capitalised English words that may be names: mid-sentence ones, and a
        sentence-initial one that is not a common English word."""
        out = set()
        for m in re.finditer(r"(?:^|(?<=[\s\"'(]))([A-Z][a-z]+)", en):
            w = m.group(1)
            if w in EN_NAME_STOP or w.lower() in EN_COMMON_CAPS:
                continue
            initial = not en[:m.start()].strip() or re.search(r"[.!?\"]\s*$", en[:m.start()])
            if initial and w not in EN_GIVEN_NAMES:
                continue            # "Tteok is ...": a sentence-initial word is a name only when it is a known one
            out.add(w)
        return out

    def _en_named(self, E, pieces, en_names):
        """Name pieces when E is (host + particles/copula) and the host sounds
        like a name in the English (마리 = Mary, 켄 = Ken)."""
        if pieces[0][2] not in ("NOUN", "NUM") or pieces[0][1] in NUM_WORDS_ALL:
            return None
        keys = {}
        for w in en_names:
            keys.setdefault(name_key(w), []).append(len(re.findall(r"[aeiouy]+", w.lower())) or 1)
        for k in range(len(E), 0, -1):
            host, rest = E[:k], E[k:]
            nk = name_key_ko(host)
            # a transliteration adds syllables only with the epenthetic ㅡ (스미스):
            # 도움 (two full syllables) is not Tom
            full = sum(1 for ch in host if is_syl(ch) and (ord(ch) - 0xAC00) // 28 % 21 != 18)
            if nk not in keys or full > max(keys[nk]):
                continue
            chains = particle_chains(host, rest) if rest else [[]]
            if chains:
                return [(host, host, "PROPN")] + [(s, key, "PART") for s, key in chains[0]]
            if rest in (COP_CONS if has_batchim(host) else COP_VOW):
                return [(host, host, "PROPN"), (rest, "-이다", "PART")]
        return None

    def _name_pieces(self, E):
        """A name the tagger marked (nq): the name plus any particles (톰은 ->
        톰 + 은). A spelling Wiktionary lists only as a common word (한국어,
        영어) is not a name: None, and the analyser reads it."""
        mo = self.morph()
        whole = None
        for k in range(len(E), 0, -1):
            # a common word inside (영화 + 에는) or the whole a verb or set form
            # (일했어요, 안녕하세요): the tagger's nq is wrong
            host, rest = E[:k], E[k:]
            if host in mo.pos and host not in mo.names and mo.pos[host] - {"verb", "adj"} and \
                    (not rest or particle_chains(host, rest) or rest in (COP_CONS if has_batchim(host) else COP_VOW)):
                return None
        a = mo.analyse(E)
        if a and a[0] in ("hand", "closed", "verb"):
            return None
        for k in range(len(E), 0, -1):
            host, rest = E[:k], E[k:]
            chains = particle_chains(host, rest) if rest else [[]]
            cop = rest and rest in (COP_CONS if has_batchim(host) else COP_VOW)
            if not chains and not cop:
                continue
            if host in mo.pos and host not in mo.names and mo.pos[host] & {"noun", "pron"}:
                return None
            if not rest:
                whole = [(E, E, "PROPN")]
                continue
            if chains:
                return [(host, host, "PROPN")] + [(s, key, "PART") for s, key in chains[0]]
            return [(host, host, "PROPN"), (rest, "-이다", "PART")]
        return whole

    def _unknown_name(self, E, names_en, en=""):
        """A name the tagger missed: a listed Tatoeba name, a Wiktionary proper
        name, or (when the English names someone) a word Wiktionary lacks, plus
        any particles or copula after it (톰은, 메리한테, 캐나다에, 톰이야)."""
        mo = self.morph()
        for k in range(len(E), 0, -1):
            host, rest = E[:k], E[k:]
            known = host in mo.pos or host in mo.alias or host in HAND or host in CLOSED
            if not ((host in NAMES and re.search(r"\b" + NAMES[host] + r"\b", en)) or
                    (host in mo.names and host not in mo.pos) or (names_en and not known)):
                continue
            chains = particle_chains(host, rest) if rest else [[]]
            if chains:
                return [(host, host, "PROPN")] + [(s, key, "PART") for s, key in chains[0]]
            cop = COP_CONS if has_batchim(host) else COP_VOW
            if rest in cop:
                return [(host, host, "PROPN"), (rest, "-이다", "PART")]
        return None

    def post_resolve(self, toks, out):
        res = []
        for t, r in zip(toks, out):
            ms = t[3]
            if not ms.startswith("Ko=") or ms.startswith("Ko=digit"):
                res.append(r)
                continue
            if ms.startswith("Ko=gram"):
                res.append(None)        # a grammar pattern piece (-ㄹ지도 모르다): no word
                continue
            if ms.startswith("Ko=unk"):
                # an eojeol the analyser cannot read: a content word outside the
                # dictionary (blocks the sentence), never a pack word
                res.append(("?" + t[0], t[2]) if t[2] in ("NOUN", "VERB", "ADJ", "ADV") else None)
                continue
            g = re.search(r"G=([A-Z]+)", ms)
            g = g.group(1) if g else t[2]
            if g == "PROPN":
                res.append((t[0], "PROPN"))
            else:
                res.append((t[1], g))
        return res

    def translation_mismatch(self, toks, en):
        """A Tatoeba pair whose English translates another sentence (멍이
        들었습니다 / "Are you waiting for me to do something?"): listed by hand
        in tools/mispaired.tsv (Korean<TAB>English), found by the gloss-overlap
        scan (see TODO.md)."""
        if self._mispaired is None:
            self._mispaired = set()
            p = self.repo / "tools" / "mispaired.tsv"
            if p.exists():
                for line in p.read_text(encoding="utf-8").splitlines():
                    if "\t" in line and not line.startswith("#"):
                        ko_t, en_t = line.split("\t", 1)
                        self._mispaired.add((re.sub(r"\s+", "", ko_t), en_t.strip()))
        if NONSTANDARD_KO.search(" " + " ".join(t[0] for t in toks)):
            return True                   # 너가, 왔어죠: non-standard spelling taught as Korean
        return (re.sub(r"\s+", "", "".join(t[0] for t in toks)), (en or "").strip()) in self._mispaired

    # ---- corpus rows: sentences written for the pack ----------------------------
    def sentence_fields(self, row):
        return {"src": "gen"} if row[0] >= self.GEN_BASE else {}

    def extra_corpus_rows(self, env):
        import bz2
        p = env.repo / "tools" / "generated_sentences.tsv"
        rows = []
        if not p.exists():
            return rows
        # a generated sentence repeating a Tatoeba one (or an earlier generated
        # one) is dropped: the pack never ships the same text twice
        seen = set()
        data = bz2.decompress((env.cache / self.sentences_file).read_bytes()).decode("utf-8")
        for line in data.split("\n"):
            q = line.split("\t")
            if len(q) >= 3 and q[1] == self.tatoeba_code:
                seen.add(q[2].strip())
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines()):
            if not line.strip() or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) < 3:
                raise ValueError(f"generated_sentences.tsv line {i+1}: need key<TAB>text<TAB>english")
            if parts[1].strip() in seen:
                continue
            seen.add(parts[1].strip())
            rows.append([self.GEN_BASE + i, parts[1].strip(), "", parts[2].strip(), None, None])
        return rows

    def extra_attribution(self, env, sentences):
        n = sum(1 for s in sentences if s.get("src") == "gen")
        return {"generated_sentences": {
            "source": "written for this pack (tools/generated_sentences.tsv), marked \"src\": \"gen\"",
            "licence": "CC-BY-SA-4.0", "count": n, "audio": "none (TTS)"}}

    def pack_json_extra(self):
        return {"spaced": True, "rtl": False, "langTag": "ko",
                "fontFamily": '"Apple SD Gothic Neo", "Noto Sans KR", "Malgun Gothic", sans-serif',
                "fonts": ["Noto Sans KR:wght@400;700"]}

    # ---- sentences ------------------------------------------------------------------
    def sentence_rank(self, toks, lv):
        """Polite style (해요체 / 합쇼체) first, then plain written (-다), and a
        반말 sentence (들어, 뭐야, 먹자) last by a wide margin at every level:
        a B1 word may pick an A2-level sentence, so a level-dependent penalty
        let 반말 back into A2."""
        return {"polite": 0, "plain": 1, "none": 1}.get(speech_register(toks), 4)

    # ---- words ------------------------------------------------------------------------
    def eojeol_forms(self, ctx, words):
        """{word key: Counter(written eojeol)}: every whole written word of a
        translated corpus sentence whose first piece resolves to the key
        (학교에서 for 학교, 먹었어요 for 먹다)."""
        from ..core.tag import iter_tagged
        rows = ctx["rows_by_sid"]
        keys = {w["_key"] for w in words}
        seen = defaultdict(Counter)
        for sid, toks in iter_tagged(ctx["tagged"]):
            row = rows.get(sid)
            if not row or not row[3]:
                continue
            text = row[1]
            res = self.post_resolve(toks, [None] * len(toks))
            cur = 0
            for t, r in zip(toks, res):
                at = text.find(t[0], cur) if t[0].strip() else -1
                if at < 0:
                    continue
                start = at
                cur = at + len(t[0])
                if t[2] in ("X", "PUNCT") or r is None or r not in keys:
                    continue
                a, b = start, cur
                while a and text[a - 1] not in " \t\n":
                    a -= 1
                while b < len(text) and text[b] not in " \t\n":
                    b += 1
                form = re.sub(r"^[^가-힣]+|[^가-힣]+$", "", text[a:b])
                if form and HANGUL_RE.match(form):
                    seen[r][form] += 1
        return seen

    def finalize_words(self, env, ctx, words):
        forms = self.eojeol_forms(ctx, words)
        owner = Counter(f for c in forms.values() for f in c)
        heads = {w["w"] for w in words}
        for w in words:
            k = w["_key"]
            if ":" in w["lemma"]:
                w["w"] = w["lemma"].split(":")[0]
            c = forms.get(k, Counter())
            alts = [f for f, _ in sorted(c.items(), key=lambda x: (-x[1], x[0]))
                    if owner[f] == 1 and f != w["w"] and f not in heads and self.alt_ok(w, f)]
            if k[1] == "PART" or k[1] == "PHRASE":
                alts = []
            if k == ("아니요", "INTJ"):
                alts = ["아뇨"] + alts
            if alts:
                w["alt"] = alts
            elif "alt" in w:
                del w["alt"]

    def surface_link_ok(self, tok):
        """No sentence-initial spelling link for a token read as a name (밥은 =
        Bob, when the English names him): Hangul has no capitals to mislead."""
        return "Ko=name" not in (tok[3] or "")

    def alt_ok(self, w, f):
        """An eojeol is an alt of word w only as w itself inflected:
        - a noun/pronoun/numeral: w + particles or the copula (학교에서, 학생이에요);
          never a bare contraction (거, 난), a light-verb form (인상했다 is not
          인상 "impression"), a compound (나비넥타이) or a spelling that is a
          headword of its own (대만, 대로 for the counter 대);
        - a verb/adjective: a conjugated form of w, alone or fused with an
          auxiliary (빌려줄게요), that is not a headword itself (사고
          "accident" is not an alt of 사다);
        - a determiner: none."""
        mo = self.morph()
        k = w["_key"]
        if k[1] == "DET":
            return False
        if f in mo.names or (f in mo.pos and mo.alias.get(f) != k[0]):
            return False
        if k[1] in ("NOUN", "PRON", "NUM"):
            # some reading (not only the context-free best one) is w + particles:
            # 남을, 숨을, 세상에 are also verb/interjection readings, and the
            # sentence link has already chosen the noun
            if not any(kind in ("hand", "closed", "noun+p", "noun+cop", "exact") and len(p) >= 2
                       and p[0][1] in (k[0], k[0].split(":")[0]) and all(x[2] == "PART" for x in p[1:])
                       for c, kind, p in mo.candidates(f)):
                return False
            h = w["w"]
            for k2 in range(len(f), len(h), -1):
                # a longer headword or name spans the eojeol (대만은, 대대로 are not 대 + particles)
                big, tail = f[:k2], f[k2:]
                if (big in mo.pos or big in mo.names) and (not tail or particle_chains(big, tail)
                                                           or tail in (COP_CONS if has_batchim(big) else COP_VOW)):
                    return False
            rest = f[len(h):] if f.startswith(h) else None
            return rest is not None and bool(particle_chains(h, rest) or rest in (COP_CONS if has_batchim(h) else COP_VOW))
        if k[1] in ("VERB", "ADJ"):
            # cost 2 = the verb fused with an auxiliary (빌려줄게요, 누워있어): still a form of w
            return any(kind == "verb" and p[0][1] == k[0] and c <= 2 for c, kind, p in mo.candidates(f))
        return True

    def check_word(self, w):
        if w["pos"] == "part":
            if not re.fullmatch(r"-[가-힣()/]+", w["w"]):
                return f"word {w['id']} {w['w']!r}: particle not written -X"
            return None
        if not re.fullmatch(r"[가-힣]+(?: [가-힣]+)*", w["w"]):
            return f"word {w['id']} {w['w']!r}: not a Hangul word"
        if w["pos"] in ("verb", "adj") and not w["w"].endswith("다"):
            return f"word {w['id']} {w['w']!r}: verb/adjective not in its -다 form"
        return None


    # ---- reading passages only (passages.Linker; the corpus build never calls these) ----
    passage_retag_names = True      # passage_retag also gets the declared names
    # suppletive honorific verbs link the plain verb, as 드시다 -> 먹다 does in the build
    passage_lemma_alias = _PassageAlias({"주무시다": "자다", "잡수시다": "먹다"})
    SINO_NUM_RE = re.compile(r"^[일이삼사오육칠팔구십백천만]{2,}$")
    NATIVE_TENS = frozenset("열 스물 스무 서른 마흔 쉰 예순 일흔 여든 아흔".split())
    NATIVE_UNITS = frozenset("한 하나 두 둘 세 셋 네 넷 다섯 여섯 일곱 여덟 아홉".split())
    NATIVE_NUM_RE = re.compile(r"^(?:열|스물|스무|서른|마흔|쉰|예순|일흔|여든|아흔)(?:한|하나|두|둘|세|셋|네|넷|다섯|여섯|일곱|여덟|아홉)$")

    def _passage_name_pieces(self, n, tail, morph):
        """A declared name n and the rest of its eojeol -> tokens, or None:
        the name (PROPN) plus a particle chain (민수는, 지영에게), the copula
        (민수예요, 지영이에요), or, after a final consonant, the familiar
        suffix -이 (no word) plus particles (지영이는, 지영이가)."""
        name = [n, n, "PROPN", f"Ko=name|G=PROPN|{morph}"]
        if not tail:
            return [name]
        if tail in (COP_CONS if has_batchim(n) else COP_VOW):
            return [name, [tail, "-이다", "X", f"Ko=name|G=PART|{morph}"]]
        ch = particle_chains(n, tail)
        if ch:
            return [name] + [[s, key, "X", f"Ko=name|G=PART|{morph}"] for s, key in ch[0]]
        if has_batchim(n) and tail.startswith("이") and len(tail) > 1:
            ch = particle_chains(n + "이", tail[1:])
            if ch:
                return [name, ["이", "이", "X", "Ko=gram"]] + \
                    [[s, key, "X", f"Ko=name|G=PART|{morph}"] for s, key in ch[0]]
        return None

    def _passage_pack(self):
        """(pack lemmas, pack nouns/pronouns) from pack/words.json, homograph
        suffixes dropped (눈:snow -> 눈): the passage repairs below only fire
        when they land on a pack word."""
        if getattr(self, "_ppack", None) is None:
            import json
            ws = json.loads((self.repo / "pack" / "words.json").read_text(encoding="utf-8"))
            self._ppack = ({w["lemma"].split(":")[0] for w in ws},
                           {w["lemma"].split(":")[0] for w in ws if w["pos"] in ("noun", "pron")})
        return self._ppack

    def _passage_numerals(self, toks):
        """Numeral compounds link every part (one span per part): a Sino-Korean
        compound before a counter splits per syllable (이천 원 -> 이 + 천, 오십만
        -> 오 + 십 + 만), a native tens + unit compound anywhere splits in two
        (열여섯 -> 열 + 여섯, 스물여섯, 열두 -> 열 + 둘), and a Sino digit the
        tagger cut from 만/백/천 (삼 + -만 in 삼만 원) takes that part as a numeral
        too. Numerals are not counted, as digits are not."""
        num = lambda s, k: [s, NUM_KEY[k][0], "NUM", "Ko=num|G=NUM|X="]      # noqa: E731
        out = []
        for j, t in enumerate(toks):
            nxt = toks[j + 1] if j + 1 < len(toks) else None
            m = self.NATIVE_NUM_RE.match(t[0])
            if m and t[1] not in ("열:num",):
                for tens in sorted(self.NATIVE_TENS, key=len, reverse=True):
                    if t[0].startswith(tens) and t[0][len(tens):] in self.NATIVE_UNITS:
                        out += [num(tens, tens), num(t[0][len(tens):], t[0][len(tens):])]
                        break
                continue
            # the counter must be a word (도 "degree" is also the particle -도: 사이도)
            # and the compound no word the analyser knows (이천, 오십만 come out
            # unknown or as a numeral; 사이 "between" is a noun)
            ctr = nxt is not None and nxt[0] in COUNTERS and nxt[2] != "X"
            if self.SINO_NUM_RE.match(t[0]) and (t[2] == "NUM" or "Ko=unk" in (t[3] or "")) and ctr:
                out += [num(c, c) for c in t[0]]
                continue
            if out and t[0] in ("만", "천", "백", "십") and t[2] == "X" and out[-1][2] == "NUM" and \
                    out[-1][0] in SINO_DIGITS | {"십", "백", "천"} and ctr:
                out.append(num(t[0], t[0]))
                continue
            out.append(t)
        return out

    def passage_retag(self, toks, names=frozenset()):
        """Passage-only token repairs (the corpus build never calls this):
        - numeral compounds link every part (_passage_numerals): 이천 원 ->
          이 + 천, 삼만 -> 삼 + 만, 열여섯 -> 열 + 여섯; not counted, as digits
          are not;
        - a declared Hangul name is PROPN wherever it stands, and its eojeol
          splits into the name plus particles or the copula, also where the
          tagger read it as one unknown word (민수는), cut it wrongly (김민수예
          + 요) or split the name itself (유 + 나). Hangul has no capitals, so
          the core rule for declared names never fires; the passage also
          declares the name in oop as "name", so it is neither counted nor
          reported;
        - a noun + particle split whose eojeol is a pack verb form is that
          verb (같이 자요, 책을 사요, 못 자는: not 자 "ruler" / 사 + -요, -는),
          when the noun is no pack noun;
        - a whole-eojeol dictionary word the pack lacks is read as a pack
          verb form when it is one (사면, 사신: 사다, not the nouns), else as
          a pack noun plus particles (앞에서: 앞 + -에서, not the adverb),
          also with the honorific suffix -님 (교수님이: 교수 + -님 + -이;
          -님 links nothing);
        - context: a native tens + unit numeral written as two tokens (열 + 한)
          is two numerals; the counter after a numeral is the counter noun
          (열네 살: not 살다); 저 before a declared name is the pronoun (저
          수아예요), not "that", and before a bare noun that is no copula
          predicate is "that" (저 빵도 주세요); 자기 before 전 "before" or after 잠 is 자다
          (자기 전에, 잠을 자기가), not the noun 자기 "oneself"; 날 read as the
          fused 나 + 를 is the noun "day"; 알려/알렸/알린 are 알리다, not 알다
          (알려고/알려면 excepted); 번 before a noun, with no numeral before
          it, is 벌다 "earned" (번 돈); X + -하고 is the pack verb X하다 when
          no noun follows (시작하고 여섯 시에); an eojeol the analyser cannot
          read that is a pack X하다/X되다 verb form links it (발견되었거나)."""
        self._patch_wordfreq()      # a cached link context never ran bind_lexicon: route zipf lookups
        toks = self._passage_numerals(toks)
        ns = sorted({n for n in names if HANGUL_RE.match(n)}, key=len, reverse=True)
        out, i = [], 0
        while i < len(toks):
            hit = None
            for n in ns if toks[i][2] != "PUNCT" else ():
                cat = ""
                for k in range(1, 5):
                    if i + k > len(toks) or toks[i + k - 1][2] == "PUNCT":
                        break
                    cat += toks[i + k - 1][0]
                    if len(cat) < len(n):
                        if not n.startswith(cat):
                            break
                        continue
                    if not cat.startswith(n):
                        break
                    t3 = toks[i][3] or ""
                    pieces = self._passage_name_pieces(n, cat[len(n):], t3.split("|")[-1] if "X=" in t3 else "X=")
                    if pieces:
                        hit = (k, pieces)
                        break
                if hit:
                    break
            if hit:
                out += hit[1]
                i += hit[0]
            else:
                out.append(toks[i])
                i += 1
        toks = out
        mo = self.morph()
        pack, nouns = self._passage_pack()
        out, i = [], 0
        while i < len(toks):
            t = toks[i]
            nxt = toks[i + 1] if i + 1 < len(toks) else None
            if t[2] == "NOUN" and nxt is not None and nxt[2] == "X" and nxt[1].startswith("-") and t[1].split(":")[0] not in nouns:
                a = mo.analyse(t[0] + nxt[0], "pv")
                if a and len(a[1]) == 1 and a[1][0][2] in ("VERB", "ADJ") and a[1][0][1] in pack:
                    g = a[1][0][2]
                    out.append([t[0] + nxt[0], a[1][0][1], g, f"Ko=verb|G={g}|X="])
                    i += 2
                    continue
            if t[2] not in ("PUNCT", "PROPN", "X", "NUM") and t[1] == t[0] and t[0] not in pack and len(t[0]) > 1:
                # a pack verb form first (물건을 사면, 표를 사신: not the nouns 사면, 사신)
                vs = sorted((c, pc[0][1], pc[0][2]) for c, kind, pc in mo.candidates(t[0])
                            if len(pc) == 1 and pc[0][2] in ("VERB", "ADJ") and pc[0][1] in pack)
                if vs:
                    out.append([t[0], vs[0][1], vs[0][2], f"Ko=verb|G={vs[0][2]}|X="])
                    i += 1
                    continue
                split = None
                for k in range(len(t[0]) - 1, 0, -1):
                    host, rest = t[0][:k], t[0][k:]
                    hon = host.endswith("님") and host[:-1] in nouns      # 교수님이: 교수 + -님 + -이
                    ch = particle_chains(host, rest) if (host in nouns or hon) and rest else []
                    if ch or (hon and not rest):
                        split = ([[host[:-1], host[:-1], "NOUN", "Ko=noun|G=NOUN|X="], ["님", "님", "X", "Ko=gram"]]
                                 if hon else [[host, host, "NOUN", "Ko=noun|G=NOUN|X="]]) + \
                            [[s2, key, "X", "Ko=noun|G=PART|X="] for s2, key in (ch[0] if ch else [])]
                        break
                if split:
                    out += split
                    i += 1
                    continue
            out.append(t)
            i += 1
        # context repairs over the rebuilt tokens
        for j, t in enumerate(out):
            if t is None:
                continue
            prv = out[j - 1] if j else None
            nxt = next((x for x in out[j + 1:] if x is not None and x[2] != "X"), None)
            if t[0] == "날" and t[1] == "나":
                # 날 read as the fused 나 + 를: the noun "day" (어느 날, 다음 날); a 나다
                # reading (사고가 날 위험) stays
                out[j] = [t[0], "날", "NOUN", "Ko=closed|G=NOUN|X="]
            elif t[1] == "알다" and t[0].startswith(("알려", "알렸", "알립", "알린", "알리")) and \
                    not t[0].startswith(("알려고", "알려면")) and "알리다" in pack:
                # 알려 드립니다, 알려 준대요: 알리다 "to inform", not 알다
                out[j] = [t[0], "알리다", "VERB", "Ko=verb|G=VERB|X="]
            elif t[0] == "번" and t[1] == "번" and (prv is None or prv[2] not in ("NUM", "DET")) and \
                    j + 1 < len(out) and out[j + 1][2] == "NOUN" and "벌다" in pack:
                # 번 돈: the modifier of 벌다 "earned" before a noun; the counter 번
                # follows a numeral (한 번, 몇 번)
                out[j] = [t[0], "벌다", "VERB", "Ko=verb|G=VERB|X="]
            elif t[2] == "NOUN" and j + 1 < len(out) and out[j + 1][1] == "-하고" and t[1] + "하다" in pack and \
                    (nxt is None or nxt[2] not in ("NOUN", "PRON", "PROPN")):
                # 시작하고 여섯 시에: the X하다 verb + -고 when the pack has it, not X + the
                # particle -하고 "and" (공부하고 운동을 좋아해요 keeps the particle)
                out[j] = [t[0] + out[j + 1][0], t[1] + "하다", "VERB", "Ko=verb|G=VERB|X="]
                out[j + 1] = None
            elif "Ko=unk" in (t[3] or ""):
                # 발견되었거나: an X하다/X되다 pack verb the analyser cannot read
                for k in range(len(t[0]) - 1, 0, -1):
                    host, rest = t[0][:k], t[0][k:]
                    for lv, heads in (("하다", ("하", "해", "했", "합", "한", "할")), ("되다", ("되", "돼", "됐", "됩", "된", "될"))):
                        if host + lv in pack and rest.startswith(heads):
                            out[j] = [t[0], host + lv, "VERB", "Ko=verb|G=VERB|X="]
                            break
                    else:
                        continue
                    break
        out = [t for t in out if t is not None]
        for j in range(len(out) - 1):
            t, nxt = out[j], out[j + 1]
            if t[0] in self.NATIVE_TENS and nxt[0] in self.NATIVE_UNITS:
                # 열 + 한 (열한 시): a native tens + unit numeral is one number, both numerals
                out[j] = [t[0], NUM_KEY[t[0]][0], "NUM", "Ko=num|G=NUM|X="]
                out[j + 1] = [nxt[0], NUM_KEY[nxt[0]][0], "NUM", "Ko=num|G=NUM|X="]
        for j in range(len(out) - 1):
            t, nxt = out[j], out[j + 1]
            if t[2] == "NUM" and nxt[0] in COUNTERS and nxt[0] in nouns and nxt[1] != nxt[0]:
                # the counter after a numeral is the counter noun (열네 살: not 살다)
                out[j + 1] = [nxt[0], nxt[0], "NOUN", "Ko=closed|G=NOUN|X="]
            if t[0] == "저" and t[1] == "저:det" and nxt[2] == "PROPN" and nxt[0] in ns:
                # 저 before a declared name is the pronoun (저 수아예요: it's me, Sua), not "that"
                out[j] = [t[0], "저", "PRON", "Ko=closed|G=PRON|X="]
            elif t[0] == "저" and t[1] == "저" and nxt[2] == "NOUN" and \
                    (j + 2 >= len(out) or out[j + 2][1] != "-이다"):
                # 저 before a bare noun that is no copula predicate is "that" (저 빵도
                #주세요); 저 학생이에요 keeps the pronoun
                out[j] = [t[0], "저:det", "DET", "Ko=closed|G=DET|X="]
            if t[0] == "자기" and (any(x[0] == "전" for x in out[j + 1:j + 4]) or
                                   any(x[0] == "잠" for x in out[max(0, j - 2):j])):
                # 자기 (한 시간) 전, 잠을 자기: the -기 form of 자다 before 전 "before"
                # or after its object 잠, not the noun 자기
                out[j] = [t[0], "자다", "VERB", "Ko=verb|G=VERB|X="]
        return out

    # ---- script primer ------------------------------------------------------
    script = {"stages": [{"key": "hangul", "label": "한글"}],
              "setsPerSession": 2, "mastered": 3, "tts": True,
              "learnKinds": ["symSound", "compose"],
              "reviewKinds": ["symSound", "soundSym", "compose", "wordRead"],
              "testKinds": {"symSound": 30, "soundSym": 20, "compose": 20, "wordRead": 20, "symType": 10}}

    def script_units(self):
        out = []
        for st, group, slug, t, name, roman, alt, confuse, note in KO_SCRIPT:
            u = {"id": "ko-" + slug, "st": "hangul", "set": st, "group": group, "t": t, "name": name,
                 "roman": roman, "alt": alt, "note": note, "confuse": ["ko-" + c for c in confuse]}
            if slug == "ieung":
                u["sound"] = False
            out.append(u)
        return out

    def script_notes(self):
        return KO_SCRIPT_NOTES

    def script_tokens(self, text):
        toks = []
        for i, ch in enumerate(text):
            b = hangul_split(ch)
            if b is None:
                return None
            l, v, t = b
            toks += [("ko-" + _KO_INIT_UNIT[l], True, i), ("ko-" + _KO_VOWEL_UNIT[v], True, i)]
            if t in _KO_FIN_UNIT:
                toks.append(("ko-" + _KO_FIN_UNIT[t], True, i))
            elif t in _KO_FIN_READ:      # read as that final, spelled with a known consonant
                toks += [("ko-" + _KO_FIN_READ[t], False, i), ("ko-" + _KO_INIT_UNIT[t], False, i)]
            elif t:                      # double final (ㄺ, ㅄ ...): no unit
                toks.append((None, False, i))
        return toks

    def script_ex_roman(self, word, text, toks):
        return ko_romanize(text)

    def script_ex_penalty(self, toks):
        """1 when a final consonant sits before the last block (liaison and sound
        changes start there), so open-syllable words (나, 우리, 가다) come first."""
        last = toks[-1][2]
        return int(any(uid is None or uid.endswith("-fin") for uid, _, p in toks if p < last))

    def script_syllables(self, text):
        out = []
        for ch in text:
            b = hangul_split(ch)
            if b is None:
                continue
            l, v, t = b
            if t and t not in _KO_FIN_UNIT:
                continue
            parts = ["ko-" + _KO_INIT_UNIT[l], "ko-" + _KO_VOWEL_UNIT[v]] + (["ko-" + _KO_FIN_UNIT[t]] if t else [])
            out.append((ch, parts, ko_romanize(ch)))
        return out

    def script_say(self, unit):
        """Carrier syllables (docs/SCRIPT_PRIMER.md ss5 default: bare jamo are read as
        names or not at all): a vowel after silent ㅇ (아), a consonant before ㅏ (가),
        a final under 아 (악). Silent ㅇ has none."""
        if unit.get("sound") is False:
            return None
        g = unit["t"]
        if unit["group"] == "final":
            return hangul_join("ㅇ", "ㅏ", g)
        if g in HANGUL_V:
            return hangul_join("ㅇ", g)
        return hangul_join(g, "ㅏ")


SPEC = Korean
