"""Mandarin (zh): a passage-only spec.

The zh pack (packs/zh) is built by tools/pack_from_hsk.py, not by the
packbuilder pipeline: there is no corpus, tagger or lexicon cache. This spec
serves only `python3 -m packbuilder passages` (spec.passage_only). Its
`passage_linker` replaces passages.Linker with ZhLinker, a dictionary-driven
segmenter over the pack itself. See packbuilder/README.md "Chinese (zh)
passages" for the rules; tests/test_passage_zh.py covers them.

Segmentation of a hanzi run: every candidate unit at every position, then the
path with the fewest unknown characters, then the fewest tokens; on a tie the
path whose last token is longest (reverse maximum matching: 十 + 分钟, not
十分 + 钟), then the higher-priority unit kind. Units:
  - a pack headword (`w`): links that word;
  - a pack.json `compounds` entry (他们, 这个, 哪儿, 春天): links its longest
    pack-word prefix, the base (他, 这, 哪, 春), the pack's own compound policy;
  - a declared name (source "names", or an "oop" key whose reason starts with
    "name"): not counted, not linked;
  - a declared out-of-pack word (other "oop" keys): counted, not linked;
  - derived units, one token and one span, linking a base pack word, only
    where the whole string is not itself a pack word:
      X们 (plural: 朋友们 -> 朋友), X儿 (erhua: 点儿 -> 点),
      a locative + 面/边 (上面 -> 上), reduplication AA / A一A / A了A
      (看看, 看一看, 看了看 -> 看), AABB (高高兴兴 -> 高兴), ABAB
      (休息休息 -> 休息), a perception verb + bound complement 见 when 见 is
      no pack word (听见 -> 听; 看见 stays the pack word);
  - a numeral character (〇零一二三四五六七八九十百千万亿两) and 第 before one:
    not counted (as numerals everywhere), each linked to its pack word if any
    (八十九 -> 八 + 十 + 九, one span each). 一 inside a pack word (一起, 一样)
    is that word;
  - a surname of a declared name (the first character of a 2-3 character
    name) before a title (老师, 先生 ...) or after 小/老 (小王): a name;
  - anything else: one unknown character; adjacent unknown characters merge
    into one out-of-pack token, reported by surface.
  - a phrase unit (PHRASES: 越来越, 开车, 一下, 有点 ...): one token and one
    span linking its head word, with the phrase's gloss on the span (guards
    in PHRASES' comment);
After segmentation: 没有 before a verb, 在 or 和 (no 的 later in the clause)
is one span linking 没 ("did not"). 过 right after a verb (a pack word whose gloss starts
"to ") is the experiential aspect particle, not the level-4 verb "to cross":
not counted, not linked. 了, 着, 的, 地, 得, 不, 没, 是 are pack words and link
as themselves (没有 = 没 + 有, 不去 = 不 + 去, 是 ... 的 = 是 + 的).
Latin letters are one counted token (out of pack unless declared); ASCII or
full-width digits are numerals; everything else is punctuation.

Spans may carry a 4th element, a display-only gloss: the phrase's gloss, else
the word's entry in gloss_display.json beside pack.json (docs/PACK_SCHEMA.md).

jieba (optional, tools/packbuilder/requirements-zh.txt) is report-only: a
proper noun jieba finds (nr/ns/nt/nz) that the pack segmentation split into
linked pack words (小红 -> 小 + 红) is listed in the report notes, so the author
can declare it. Without jieba the check is skipped with one line on stderr.
Segmentation and passages.json never depend on jieba.

Readings (`ruby`, docs/PACK_SCHEMA.md passages.json): with pack.characters,
ZhLinker.passage_ruby gives every segmenter token holding a hanzi a reading
tuple, in every passage sentence (`sentences[].ruby`), title (`titleRuby`),
question (`questions[].ruby`) and option (`questions[].optionsRuby`), so the
pronunciation-first display never shows a hanzi or drops a syllable (这个 is
zhège, not the linked 这's zhè). Sources, in order (token_reading):
  1. whole-surface overrides (SURFACE_READINGS: 长大, 草地, 便宜), the aspect
     particle 过 (guo);
  2. the pack: a token spelled as its linked word reads that word's `pron`;
     a surface sentences.json `ruby` reads differently from its word (这个
     zhège, 他们 tāmen, harvested); otherwise the surface is cut into pack
     words (words.json `pron`, characters.json `reading`) and harvested
     surfaces, fewest uncovered characters first, then fewest pieces, then the
     linked word kept whole; a suffix 儿 after a pack piece is the erhua r
     (哪儿 nǎr). In an unlinked token (a name, an oop word) a single pack
     character is used only when pypinyin knows one reading for it, so a
     heteronym in a name follows pypinyin's phrase reading (成都 chéngdū,
     not the pack's 都 dōu);
  3. every other character: CHAR_READINGS for a one-character token (HSK-context
     readings of common heteronyms; a lone 地 after a pack word is de, else dì), else
     pypinyin (Style.TONE, heteronym off) over the whole token, so its phrase
     dictionary gives the context reading. These characters are counted in the
     report.
Syllables join without spaces, with an apostrophe before a/o/e (as words.json
writes nǚ'ér); a name's reading is capitalised, a surname in SURNAMES split
from the given name (Zhōu Tíng, Shànghǎi, Xiǎo Wáng). A token with a linked
word carries its id; a token without one (a name, an oop word, 过, 第)
carries null. Tone sandhi (一, 不) and neutral tones in reduplication (看看
kànkàn) are not applied: each piece keeps its dictionary reading.
"""
import re

from .base import LanguageSpec

NUMERALS = frozenset("〇零一二三四五六七八九十百千万亿两")
LOCATIVES = frozenset("上下里外左右前后东西南北旁")
PERCEPTION_JIAN = frozenset("听遇碰梦瞧")      # + 见 when 见 is no pack word
TITLES = ("老师", "先生", "小姐", "太太", "女士", "医生", "同学", "经理", "校长", "阿姨", "叔叔", "师傅", "教授")
HAN_RE = re.compile(r"[㐀-䶿一-鿿豈-﫿\U00020000-\U0003134f]+")
LATIN_RE = re.compile(r"[A-Za-zＡ-Ｚａ-ｚ]+")
DIGIT_RE = re.compile(r"[0-9０-９]+(?:[.,][0-9０-９]+)*")
# same-span priority (lower wins): a numeral character is a numeral even when
# it is a pack word; a pack word beats a declared name or oop spelled the same
PRIORITY = {"num": 0, "word": 1, "phrase": 2, "compound": 3, "name": 4, "oop": 5, "derived": 6, "unk": 7}
# Phrase units: surface -> (head pack word, span gloss). One token and one span
# linking the head, with a display-only gloss on the span (spans[i][3]); used
# only where the surface is no pack word. Guards (PHRASE_OK): a phrase never
# starts where its first character completes a pack word with the character
# before (早上课 is 早上 + 课, 所有的 is 所有 + 的) nor ends where its last
# character starts a pack word with the next (一下午 is 一 + 下午); one
# starting with 一 never follows a numeral (十一点); 一点/有点 never precede a
# clock word (一点钟, 一点半) nor follow a time word (下午一点).
PHRASES = {
    "一点": ("点", "a little; a bit"), "一点儿": ("点", "a little; a bit"),
    "有点": ("点", "a bit; somewhat (有点+adj)"), "有点儿": ("点", "a bit; somewhat (有点+adj)"),
    "有一点": ("点", "a bit; somewhat (有一点+adj)"), "有一点儿": ("点", "a bit; somewhat (有一点+adj)"),
    "一下": ("下", "(V+一下) briefly, a bit"),
    "有的": ("有", "some (有的…有的)"), "有时候": ("有", "sometimes"),
    "只有": ("只", "only (只有…才)"), "还好": ("还", "fortunately; not bad"),
    "下班": ("下", "to finish work; to get off work"), "上下班": ("上", "to go to and from work"),
    "上课": ("上", "to go to class; class begins"), "下课": ("下", "class is over; to finish class"),
    "开会": ("开", "to hold a meeting; to be in a meeting"), "长大": ("长", "(zhǎng) to grow up"),
    "草地": ("地", "(dì) lawn; grass (草地)"), "越来越": ("越", "more and more"),
    "开车": ("开", "to drive (a car)"), "红包": ("包", "red envelope (of money)"),
    "过生日": ("过", "to celebrate a birthday"), "别的": ("别", "other (别的)"),
    "不用": ("用", "need not; no need to"), "找钱": ("找", "to give change"),
    "交朋友": ("交", "to make friends"), "老人": ("老", "old people; the elderly"),
}
CLOCK_AFTER = frozenset("钟半多零") | NUMERALS
CLOCK_BEFORE = ("上午", "下午", "中午", "早上", "晚上", "凌晨", "今天", "明天", "昨天", "每天", "从", "到")   # 下午一点: 1 p.m.
MEIYOU_GLOSS = "did not; have not (没有+V)"     # 没有 before a verb, 在 or 和 (no 的 later in the clause): one span linking 没
JIEBA_NAME_FLAGS = ("nr", "ns", "nt", "nz")
JIEBA_MIN_FREQ = 100      # jieba dictionary entries tagged nr below this are phrases (太贵 17, 张老师 3)

# ---- readings (passage_ruby): HSK-context overrides for what the pack does not cover
# Whole surfaces whose reading is not their pieces' (a phrase whose head word's pack
# pron is the other reading: 长 cháng, 地 de) or a fixed neutral tone.
SURFACE_READINGS = {"长大": "zhǎngdà", "草地": "cǎodì", "便宜": "piányi"}
# A one-character token outside the pack's coverage (not a name): its HSK-context
# reading instead of pypinyin's, which has no context for a lone character. Inside a
# longer token pypinyin's phrase reading is used. 地 is handled in _char_reading
# (a lone 地 after a pack word is de, else dì: POS is out of reach).
CHAR_READINGS = {"了": "le", "的": "de", "得": "de", "着": "zhe", "行": "xíng", "都": "dōu", "还": "hái",
                 "觉": "jué", "切": "qiē"}
# Common surnames: a name token starting with one is written "Surname Given"
# (Zhōu Tíng). Left out on purpose: characters that start the pack's place names
# or transliterations (上 广 成 美 法 安 玛).
SURNAMES = frozenset("王李张刘陈杨黄赵吴周徐孙马朱胡郭何高林罗郑梁谢宋唐许韩冯邓曹彭曾肖田董袁潘于蒋蔡余杜叶"
                     "程苏魏吕丁任沈姚卢姜崔钟谭陆汪范金石廖贾夏韦付方白邹孟熊秦邱江尹薛闫段雷侯龙史陶黎贺顾毛"
                     "郝龚邵万钱严覃武戴莫孔向汤")
_VOWEL_START = re.compile(r"^[aoeāáǎàōóǒòēéěè]", re.I)


class Spec(LanguageSpec):
    code = "zh"
    name_en = "Mandarin"
    pack_name = "Mandarin (HSK 1–4)"
    tts = "zh-CN"
    passage_only = True             # no build pipeline: passages only (test_spec skips build fields)
    level_ids = ["1", "2", "3", "4"]
    passage_join = ""               # passage text = sentences joined without spaces
    passage_unspaced = True         # report ws_words = linked words (the count the app shows)
    gloss_display_file = "gloss_display.json"     # beside pack.json: {headword w: display gloss for spans}

    def load(self):
        return self

    def passage_linker(self, shipped, pack_dir):
        import json
        import sys

        from ..core.words import load_gloss_display
        pack = json.loads((pack_dir / "pack.json").read_text())
        display = load_gloss_display(pack_dir, self.gloss_display_file)
        known = {w["w"] for w in shipped.values()}
        unused = sorted(k for k in display if k not in known)
        if unused:
            print(f"zh passages: {self.gloss_display_file}: {len(unused)} keys match no pack word: {unused[:10]}",
                  file=sys.stderr)
        # readings (passage_ruby) only for a pack with a characters stage: sentences.json
        # ruby surfaces that read otherwise than their word (这个 zhège) and characters.json
        # unit readings
        readings = None
        if pack.get("characters"):
            readings = {}
            byid = {w["id"]: w for w in shipped.values()}
            sp = pack_dir / "sentences.json"
            for s in (json.loads(sp.read_text()) if sp.exists() else []):
                for a, b, r, wid in s.get("ruby") or ():
                    surf = s["t"][a:b]     # zh sentences are BMP text: UTF-16 offsets are indices
                    if r and wid in byid and surf != byid[wid]["w"]:
                        readings.setdefault(surf, {}).setdefault(r, 0)
                        readings[surf][r] += 1
            readings = {k: max(v, key=lambda r: (v[r], r)) for k, v in readings.items()}
            cp = pack_dir / "characters.json"
            for u in (json.loads(cp.read_text()) if cp.exists() else []):
                if u.get("reading") and u.get("t"):
                    readings.setdefault(("unit", u["t"]), u["reading"])
        return ZhLinker(shipped, pack.get("compounds", []), display, readings)


SPEC = Spec


def _is_verb(word):
    en = word.get("en", "")
    return en.startswith("to ") or "; to " in en


class ZhLinker:
    """The passages.Linker interface (pretag, tag, classify, links_all,
    lemma_of, lemma_ids, num_ids, lowered) over the pack's own dictionary,
    plus declared (per-passage units), n_words and passage_notes."""

    def __init__(self, shipped, compounds=(), display=None, readings=None):
        self.shipped = shipped
        # passage_ruby: None = no characters stage, no ruby written. Else the reading
        # lexicon (_reading_lexicon): surface -> reading from words.json pron, then
        # characters.json unit readings ("unit", t) and sentences.json ruby surfaces
        self.readings = readings
        self._lex = None
        self.ruby_fallback = {}     # char -> count read by pypinyin with no override (report)
        self.ruby_override = {}     # char or surface -> count read from an override table
        # display-only glosses by headword (gloss_display.json): written on every
        # span of the word (spans[i][3]); links, counts and words.json never see them
        self.display = dict(display or {})
        self.id_of = {}
        for wid in sorted(shipped):
            self.id_of.setdefault(shipped[wid]["w"], wid)
        self.lemma_ids = dict(self.id_of)
        self.lemma_of = {wid: {w["w"]} for wid, w in shipped.items()}
        self.num_ids = {c: self.id_of[c] for c in NUMERALS if c in self.id_of}
        self.compound_base = {}
        for c in sorted(compounds):
            if c in self.id_of:
                continue
            for k in range(len(c) - 1, 0, -1):
                if c[:k] in self.id_of:
                    self.compound_base[c] = self.id_of[c[:k]]
                    break
        self.phrases = {u: (self.id_of[h], g) for u, (h, g) in PHRASES.items()
                        if u not in self.id_of and h in self.id_of}
        self.maxlen = max([len(w) for w in self.id_of] + [len(c) for c in self.compound_base] + [1])
        self.tagged = {}
        self.lowered = {}           # the Linker's truecase bookkeeping: always empty here
        self._jieba = None

    # ---- per-passage declarations -------------------------------------------
    @staticmethod
    def declared(p):
        """The passage's segmentation units, as passages.run's `names`:
        plain strings are declared names; ("oop", k) a declared out-of-pack
        word; ("oopname", k) an oop key whose reason starts with "name"."""
        out = set(w for n in p.get("names", []) for w in n.split())
        for k, why in p.get("oop", {}).items():
            out.add(("oopname", k) if str(why).startswith("name") else ("oop", k))
        return frozenset(out)

    # ---- segmentation -------------------------------------------------------
    def pretag(self, items):
        for k in items:
            self.tag(k[0], k[1], k[2] if len(k) > 2 else frozenset())

    def tag(self, text, en="", names=frozenset()):
        key = (text, en, frozenset(names))
        if key not in self.tagged:
            self.tagged[key] = self.segment(text, key[2])
        return self.tagged[key]

    def segment(self, text, names=frozenset()):
        """[surface, lemma, upos, info] per token; info = {"s", "e", "wid", "kind"}.
        upos: PUNCT, NUM, PROPN (declared names), PART (aspect 过), X."""
        names_s = {n for n in names if isinstance(n, str)}
        oop = {n[1] for n in names if isinstance(n, tuple) and n[0] == "oop"}
        oopname = {n[1] for n in names if isinstance(n, tuple) and n[0] == "oopname"}
        units = {}
        for n in sorted(names_s | oopname):
            units.setdefault(n, ("name", None, n in oopname))
        for n in sorted(oop):
            units.setdefault(n, ("oop", None, False))
        surnames = {n[0] for n in names_s | oopname if 2 <= len(n) <= 3 and HAN_RE.fullmatch(n)}
        toks = []
        i = 0
        while i < len(text):
            m = HAN_RE.match(text, i)
            if m:
                toks += self._segment_run(text, m.start(), m.end(), units, surnames)
                i = m.end()
                continue
            m = DIGIT_RE.match(text, i)
            if m:
                toks.append([m.group(0), m.group(0), "NUM", {"s": m.start(), "e": m.end(), "wid": None, "kind": "digit"}])
                i = m.end()
                continue
            m = LATIN_RE.match(text, i)
            if m:
                s = m.group(0)
                kind, wid = ("word", self.id_of[s]) if s in self.id_of else \
                    ("name", None) if s in names_s or s in oopname else ("oop" if s in oop else "unk", None)
                upos = "PROPN" if kind == "name" else "X"
                toks.append([s, s, upos, {"s": m.start(), "e": m.end(), "wid": wid, "kind": kind,
                                          "oopname": s in oopname}])
                i = m.end()
                continue
            if not text[i].isspace():
                toks.append([text[i], text[i], "PUNCT", {"s": i, "e": i + 1, "wid": None, "kind": "punct"}])
            i += 1
        # 过 after a verb: the experiential aspect particle (去过), not "to cross"
        for j in range(1, len(toks)):
            t, prev = toks[j], toks[j - 1]
            if t[0] == "过" and t[3]["kind"] == "word" and prev[3]["e"] == t[3]["s"] and self._verbal(prev):
                t[1], t[2] = "过", "PART"
                t[3] = dict(t[3], wid=None, kind="particle")
        # 没有 before a verb, 在 or 和 ("did not"): one token and span linking 没
        mei = self.id_of.get("没")
        j = 0
        while mei and j + 2 < len(toks):
            a, b, c = toks[j], toks[j + 1], toks[j + 2]
            if a[0] == "没" and b[0] == "有" and a[3]["kind"] == b[3]["kind"] == "word" and \
                    a[3]["e"] == b[3]["s"] and b[3]["e"] == c[3]["s"] and (c[0] in ("在", "和") or self._verbal(c)) \
                    and not self._de_in_clause(toks, j + 2):
                toks[j:j + 2] = [["没有", "没", "X", {"s": a[3]["s"], "e": b[3]["e"], "wid": mei, "kind": "phrase",
                                                    "oopname": False, "gloss": MEIYOU_GLOSS}]]
            j += 1
        return toks

    @staticmethod
    def _de_in_clause(toks, j):
        """A 的 after toks[j] before the clause ends: 没有 + V ... 的 + N is
        "there is no N that V" (那里没有卖水的商店), so 没 + 有 stay two words."""
        for t in toks[j:]:
            if t[3]["kind"] == "punct":
                return False
            if t[0] == "的":
                return True
        return False

    def _verbal(self, tok):
        """A token read as a verb: a linked pack word (or unit on one) whose
        gloss (the phrase's own gloss for a phrase unit) starts with "to"."""
        info = tok[3]
        if not info.get("wid") or info["kind"] not in ("word", "compound", "derived", "phrase"):
            return False
        if info["kind"] == "phrase" and info.get("gloss"):
            return info["gloss"].startswith("to ")
        return _is_verb(self.shipped[info["wid"]])

    def _candidates(self, s, i, units, surnames):
        """(end, kind, wid, lemma, oopname) units starting at s[i]."""
        out = []
        n = len(s)
        ch = s[i]
        if ch in NUMERALS:
            out.append((i + 1, "num", self.num_ids.get(ch), ch, False))
        if ch == "第" and i + 1 < n and s[i + 1] in NUMERALS and "第" not in self.id_of:
            out.append((i + 1, "num", None, ch, False))
        for L in range(1, min(self.maxlen, n - i) + 1):
            u = s[i:i + L]
            if u in self.id_of:
                out.append((i + L, "word", self.id_of[u], u, False))
            elif u in self.compound_base:
                b = self.compound_base[u]
                out.append((i + L, "compound", b, self.shipped[b]["w"], False))
        for u, (wid, _g) in self.phrases.items():
            if s.startswith(u, i) and self._phrase_ok(s, i, i + len(u)):
                out.append((i + len(u), "phrase", wid, self.shipped[wid]["w"], False))
        for u, (kind, _w, on) in units.items():
            if s.startswith(u, i):
                out.append((i + len(u), kind, None, u, on))
        # surname of a declared name before a title, or after 小/老 (小王)
        if ch in surnames and any(s.startswith(t, i + 1) for t in TITLES):
            out.append((i + 1, "name", None, ch, False))
        if ch in "小老" and i + 1 < n and s[i + 1] in surnames:
            out.append((i + 2, "name", None, s[i:i + 2], False))
        # derived units: X们, X儿, locative + 面/边, 听见
        bases = [(e, wid) for e, k, wid, _l, _o in out if k in ("word", "compound") and wid]
        for e, wid in bases:
            if e < n and s[e] in "们儿" and s[i:e + 1] not in self.id_of:
                out.append((e + 1, "derived", wid, self.shipped[wid]["w"], False))
        if ch in LOCATIVES and ch in self.id_of and i + 1 < n and s[i + 1] in "面边" and s[i:i + 2] not in self.id_of:
            out.append((i + 2, "derived", self.id_of[ch], ch, False))
        if ch in PERCEPTION_JIAN and ch in self.id_of and s.startswith("见", i + 1) and "见" not in self.id_of \
                and s[i:i + 2] not in self.id_of:
            out.append((i + 2, "derived", self.id_of[ch], ch, False))
        # reduplication of a pack word (not a numeral)
        if ch in self.id_of and ch not in NUMERALS:
            if i + 1 < n and s[i + 1] == ch and s[i:i + 2] not in self.id_of:
                out.append((i + 2, "derived", self.id_of[ch], ch, False))          # 看看
            if i + 2 < n and s[i + 1] in "一了" and s[i + 2] == ch and s[i:i + 3] not in self.id_of:
                out.append((i + 3, "derived", self.id_of[ch], ch, False))          # 看一看, 看了看
        if i + 3 < n:
            a, b = s[i], s[i + 2]
            if s[i + 1] == a and s[i + 3] == b and a != b and a + b in self.id_of and s[i:i + 4] not in self.id_of:
                out.append((i + 4, "derived", self.id_of[a + b], a + b, False))  # 高高兴兴
            ab = s[i:i + 2]
            if s[i + 2:i + 4] == ab and ab in self.id_of and s[i:i + 4] not in self.id_of:
                out.append((i + 4, "derived", self.id_of[ab], ab, False))        # 休息休息
        out.append((i + 1, "unk", None, ch, False))
        return out

    def _phrase_ok(self, s, i, e):
        """PHRASES guards (see there)."""
        if i and s[i - 1:i + 1] in self.id_of:
            return False
        if e < len(s) and s[e - 1:e + 1] in self.id_of:
            return False
        if s[i] == "一" and i and (s[i - 1] in NUMERALS or s[i - 1] == "第"):
            return False
        if s[i:e] in ("一点", "有点", "有一点") and e < len(s) and s[e] in CLOCK_AFTER:
            return False
        if s[i:e] == "一点" and s[:i].endswith(CLOCK_BEFORE):
            return False
        return True

    def _segment_run(self, text, a, b, units, surnames):
        s = text[a:b]
        n = len(s)
        # best[j]: (cost, tie, path) for s[:j]; cost = (unknown chars, tokens),
        # tie = (-(last token length), its kind's priority)
        best = [None] * (n + 1)
        best[0] = ((0, 0), (0, 0), ())
        for i in range(n):
            if best[i] is None:
                continue
            (unk, nt), _tie, path = best[i]
            for e, kind, wid, lemma, on in self._candidates(s, i, units, surnames):
                cost = (unk + (e - i if kind == "unk" else 0), nt + 1)
                tie = (-(e - i), PRIORITY[kind])
                cur = best[e]
                if cur is None or (cost, tie) < (cur[0], cur[1]):
                    best[e] = (cost, tie, path + ((i, e, kind, wid, lemma, on),))
        path = list(best[n][2])
        # adjacent unknown characters: one out-of-pack token
        merged = []
        for seg in path:
            if merged and seg[2] == "unk" and merged[-1][2] == "unk":
                p = merged[-1]
                merged[-1] = (p[0], seg[1], "unk", None, s[p[0]:seg[1]], False)
            else:
                merged.append(seg)
        toks = []
        for i, e, kind, wid, lemma, on in merged:
            surf = s[i:e]
            upos = {"num": "NUM", "name": "PROPN"}.get(kind, "X")
            info = {"s": a + i, "e": a + e, "wid": wid, "kind": kind, "oopname": on}
            if kind == "phrase":
                info["gloss"] = self.phrases[surf][1]
            toks.append([surf, lemma if kind != "unk" else surf, upos, info])
        return toks

    # ---- the Linker interface -------------------------------------------------
    def classify(self, toks, en=None, lowered=()):
        """Counted tokens: (surface, lemma, word id or None, True, index).
        Not counted: punctuation, numerals (digits, numeral characters, 第),
        declared names (except oop "name" keys, which passages.run skips
        itself), the aspect particle 过."""
        out = []
        for i, t in enumerate(toks):
            k = t[3]["kind"]
            if k in ("punct", "digit", "num", "particle"):
                continue
            if k == "name" and not t[3].get("oopname"):
                continue
            out.append((t[0], t[1], t[3]["wid"], True, i))
        return out

    def links_all(self, toks, text, en, names=frozenset()):
        from ..passages import utf16_index
        ids, spans, claimed = [], [], set()
        for i, t in enumerate(toks):
            wid = t[3]["wid"]
            if not wid:
                continue
            claimed.add(i)
            if wid not in ids:
                ids.append(wid)
            span = [utf16_index(text, t[3]["s"]), utf16_index(text, t[3]["e"]), wid]
            # optional 4th element, display-only: the phrase's gloss, else the
            # word's gloss_display.json text (the app falls back to the word's en)
            g = t[3].get("gloss") or self.display.get(self.shipped[wid]["w"])
            if g:
                span.append(g)
            spans.append(span)
        return ids, self.classify(toks, en), spans, claimed

    def n_words(self, toks):
        """Words of one sentence: its tokens after segmentation, without
        punctuation or digits; a numeral run (八十九, 第一) is one word."""
        n, prev_num_end = 0, None
        for t in toks:
            k = t[3]["kind"]
            if k in ("punct", "digit"):
                prev_num_end = None
                continue
            if k == "num":
                if prev_num_end != t[3]["s"]:
                    n += 1
                prev_num_end = t[3]["e"]
                continue
            prev_num_end = None
            n += 1
        return n

    def passage_notes(self, texts, names=frozenset()):
        """Report only: a proper noun jieba finds (posseg nr/ns/nt/nz, HMM on,
        so unseen names like 小红 or 张伟 are found) that the pack segmentation
        split into single characters, at least one linked (小 + 红, 张 + 伟). Words the split already
        reports (a declared name, an out-of-pack piece) and multi-character
        pieces (张老师 = 张 + 老师, 喝咖啡) are left out, as are jieba dictionary
        entries rarer than JIEBA_MIN_FREQ (太贵, 谢谢您: tagged nr in its
        dictionary). Empty without jieba."""
        pseg = self._jieba_pseg()
        if pseg is None:
            return []
        import jieba
        declared = {n if isinstance(n, str) else n[1] for n in names}
        notes = []
        for si, t in enumerate(texts):
            toks = self.segment(t, frozenset(names))
            at = 0
            for w, flag in pseg.lcut(t, HMM=True):
                s = t.find(w, at)
                if s < 0:
                    continue
                e = at = s + len(w)
                if len(w) < 2 or not flag.startswith(JIEBA_NAME_FLAGS) or w in declared or w in self.id_of:
                    continue
                freq = jieba.dt.FREQ.get(w)
                if freq and freq < JIEBA_MIN_FREQ:
                    continue
                inner = [tk for tk in toks if s <= tk[3]["s"] and tk[3]["e"] <= e]
                if sum(len(tk[0]) for tk in inner) != len(w) or len(inner) < 2:
                    continue        # a token crosses the word's edge
                if all(len(tk[0]) == 1 for tk in inner) and any(tk[3]["wid"] for tk in inner):
                    notes.append(f"s{si} {w!r}: jieba reads a proper noun ({flag}), linked as "
                                 f"{' + '.join(tk[0] for tk in inner)}; declare it in names if it is one")
        return notes

    # ---- readings (ruby, docs/PACK_SCHEMA.md passages.json) ---------------------
    def passage_ruby(self, passages, names_of):
        """passages.run hook, before writing: with a characters stage (self.readings
        not None) adds `ruby` to every sentence that has a hanzi, `titleRuby`, and
        per question `ruby` and (mc) `optionsRuby`, one list per option. Every token
        holding a hanzi gets [start, end, reading, wordId or None] in UTF-16 offsets
        (token_reading). names_of: each passage's declared units, as run's `names`.
        Returns the report lines (counts and the pypinyin fallback characters)."""
        if self.readings is None:
            return []
        self.ruby_fallback, self.ruby_override = {}, {}
        n = {"sent": 0, "sent_tok": 0, "linked": 0, "other": 0}

        def ruby(text, en, names, where):
            toks = self.tag(text, en, names)
            out = self.text_ruby(text, toks)
            if where:
                n[where] += len(out)
                if where == "sent_tok":
                    n["linked"] += sum(1 for r in out if r[3])
            return out

        for p, names in zip(passages, names_of):
            for s in p["sentences"]:
                r = ruby(s["t"], s["en"], names, "sent_tok")
                n["sent"] += 1
                if r:
                    s["ruby"] = r
            p["titleRuby"] = ruby(p["title"], "", names, "other")
            for q in p["questions"]:
                q["ruby"] = ruby(q["q"], "", names, "other")
                if q.get("options"):
                    q["optionsRuby"] = [ruby(o, "", names, "other") for o in q["options"]]
        fb = sorted(self.ruby_fallback.items(), key=lambda x: (-x[1], x[0]))
        ov = sorted(self.ruby_override.items(), key=lambda x: (-x[1], x[0]))
        return ["Readings (`ruby`, langs/zh.py passage_ruby): "
                f"{n['sent_tok']} reading tokens over {n['sent']} sentences ({n['linked']} on a linked word, "
                f"{n['sent_tok'] - n['linked']} without one: names, oop words, 过, 第), "
                f"{n['other']} in titles, questions and options.",
                f"pypinyin readings with no override: {sum(v for _k, v in fb)} characters, {len(fb)} distinct"
                + (": " + ", ".join(f"{k} x{v}" for k, v in fb[:30]) if fb else "") + (" ..." if len(fb) > 30 else "") + ".",
                "Override readings used (SURFACE_READINGS, CHAR_READINGS, 地 rule, aspect 过): "
                + (", ".join(f"{k} x{v}" for k, v in ov) if ov else "none") + "."]

    def text_ruby(self, text, toks):
        """[[start, end, reading, wordId or None]] (UTF-16) for every token of
        `text` (its segment() tokens) that holds a hanzi."""
        from ..passages import utf16_index
        out = []
        for i, t in enumerate(toks):
            if not HAN_RE.search(t[0]):
                continue
            out.append([utf16_index(text, t[3]["s"]), utf16_index(text, t[3]["e"]),
                        self.token_reading(t, toks[i - 1] if i else None), t[3].get("wid") or None])
        return out

    def _reading_lexicon(self):
        """surface -> reading: words.json pron, then characters.json unit readings,
        then sentences.json ruby surfaces (self.readings)."""
        if self._lex is None:
            lex = {}
            for wid in sorted(self.shipped):
                w = self.shipped[wid]
                if w.get("pron"):
                    lex.setdefault(w["w"], w["pron"])
            rd = self.readings or {}
            for k in sorted((k for k in rd if isinstance(k, tuple)), key=lambda k: k[1]):
                lex.setdefault(k[1], rd[k])
            for k in sorted(k for k in rd if isinstance(k, str)):
                lex.setdefault(k, rd[k])
            self._lex = (lex, max([len(k) for k in lex] + [1]))
        return self._lex

    _hetero = {}

    @classmethod
    def _heteronym(cls, ch):
        """pypinyin knows more than one reading for this character."""
        if ch not in cls._hetero:
            from pypinyin import Style
            cls._hetero[ch] = len(set(_pypinyin()(ch, style=Style.TONE, heteronym=True)[0])) > 1
        return cls._hetero[ch]

    def token_reading(self, tok, prev=None):
        """The reading of one token holding a hanzi (module docstring, "Readings")."""
        surf, info = tok[0], tok[3]
        kind, wid = info["kind"], info.get("wid")
        if kind == "particle" and surf == "过":
            self._bump(self.ruby_override, "过 (aspect)")
            return "guo"
        if surf in SURFACE_READINGS:
            self._bump(self.ruby_override, surf)
            return SURFACE_READINGS[surf]
        word = self.shipped.get(wid) if wid else None
        if word and surf == word["w"] and word.get("pron"):
            return word["pron"]
        lex, maxlen = self._reading_lexicon()
        linked = bool(word)
        n = len(surf)
        # best[j]: (cost, pieces) for surf[:j]; cost = (uncovered chars, pieces, -head pieces)
        best = [None] * (n + 1)
        best[0] = ((0, 0, 0), ())
        head = word["w"] if word else None
        for i in range(n):
            if best[i] is None:
                continue
            cost, path = best[i]
            cands = []
            for L in range(min(maxlen, n - i), 0, -1):
                u = surf[i:i + L]
                if u in lex and (linked or L > 1 or not self._heteronym(u)):
                    cands.append((i + L, ("lex", u)))
            if surf[i] == "儿" and i and path and path[-1][0] == "lex":
                cands.append((i + 1, ("er", "儿")))
            cands.append((i + 1, ("fb", surf[i])))
            for e, pc in cands:
                c = (cost[0] + (pc[0] == "fb"), cost[1] + 1, cost[2] - (pc[0] == "lex" and pc[1] == head))
                if best[e] is None or c < best[e][0]:
                    best[e] = (c, path + (pc,))
        pieces = best[n][1]
        py = None
        out = []
        at = 0
        for k, u in pieces:
            if k == "lex":
                r = lex[u]
            elif k == "er":
                out.append("r")
                at += 1
                continue
            else:
                r = self._char_reading(surf, at, u, prev, kind)
                if r is None:
                    if py is None:
                        from pypinyin import Style
                        py = [x[0] for x in _pypinyin()(surf, style=Style.TONE, heteronym=False)]
                        if len(py) != n:        # not one entry per character: read the character alone
                            py = [_pypinyin()(c, style=Style.TONE, heteronym=False)[0][0] for c in surf]
                    r = py[at]
                    self._bump(self.ruby_fallback, u)
            out.append(("'" if out and _VOWEL_START.match(r) else "") + r)
            at += len(u)
        if kind == "name":
            return _name_case(surf, pieces, out)
        return "".join(out)

    def _char_reading(self, surf, at, ch, prev, kind):
        """An override reading for a character outside the pack's coverage, or None."""
        if ch == "地":
            # a lone 地 right after a pack word is the adverbial de (高兴地); inside a
            # longer token (草地, 地铁) or after anything else, the noun dì
            r = "de" if len(surf) == 1 and prev is not None and prev[3].get("wid") else "dì"
            self._bump(self.ruby_override, f"地 ({r})")
            return r
        # a lone character only: inside a longer token (a name: 成都, an oop word: 着急)
        # pypinyin's phrase dictionary knows the reading better than a fixed table
        if ch in CHAR_READINGS and len(surf) == 1 and kind != "name":
            self._bump(self.ruby_override, ch)
            return CHAR_READINGS[ch]
        return None

    @staticmethod
    def _bump(d, k):
        d[k] = d.get(k, 0) + 1

    def _jieba_pseg(self):
        if self._jieba is None:
            try:
                import logging

                import jieba
                import jieba.posseg as pseg
                jieba.setLogLevel(logging.WARNING)
                self._jieba = pseg
            except ImportError:
                import sys
                print("zh passages: jieba not installed, proper-noun cross-check skipped "
                      "(pip install -r tools/packbuilder/requirements-zh.txt)", file=sys.stderr)
                self._jieba = False
        return self._jieba or None


def _pypinyin():
    """pypinyin.pinyin (tools/packbuilder/requirements-zh.txt); required for zh
    passage readings with a characters stage."""
    try:
        from pypinyin import pinyin
    except ImportError:
        raise SystemExit("zh passages: pypinyin is required for passage readings "
                         "(pip install -r tools/packbuilder/requirements-zh.txt)")
    return pinyin


def _cap(r):
    return r[:1].upper() + r[1:]


def _name_case(surf, pieces, out):
    """A name's reading: capitalised; a surname in SURNAMES (or 小/老 + surname)
    written apart from what follows (Zhōu Tíng, Xiǎo Wáng)."""
    out = [x.lstrip("'") for x in out]
    if len(pieces) > 1 and len(surf) <= 3 and (
            (len(pieces[0][1]) == 1 and surf[0] in SURNAMES) or
            (len(surf) == 2 and surf[0] in "小老" and surf[1] in SURNAMES)):
        return _cap(out[0]) + " " + _cap("".join(("'" if i and _VOWEL_START.match(x) else "") + x
                                                for i, x in enumerate(out[1:])))
    return _cap("".join(("'" if i and _VOWEL_START.match(x) else "") + x for i, x in enumerate(out)))
