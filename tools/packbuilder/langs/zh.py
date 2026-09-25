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
After segmentation: 过 right after a verb (a pack word whose gloss starts
"to ") is the experiential aspect particle, not the level-4 verb "to cross":
not counted, not linked. 了, 着, 的, 地, 得, 不, 没, 是 are pack words and link
as themselves (没有 = 没 + 有, 不去 = 不 + 去, 是 ... 的 = 是 + 的).
Latin letters are one counted token (out of pack unless declared); ASCII or
full-width digits are numerals; everything else is punctuation.

jieba (optional, tools/packbuilder/requirements-zh.txt) is report-only: a
proper noun jieba finds (nr/ns/nt/nz) that the pack segmentation split into
linked pack words (小红 -> 小 + 红) is listed in the report notes, so the author
can declare it. Without jieba the check is skipped with one line on stderr.
Segmentation and passages.json never depend on jieba.
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
PRIORITY = {"num": 0, "word": 1, "compound": 2, "name": 3, "oop": 4, "derived": 5, "unk": 6}
JIEBA_NAME_FLAGS = ("nr", "ns", "nt", "nz")
JIEBA_MIN_FREQ = 100      # jieba dictionary entries tagged nr below this are phrases (太贵 17, 张老师 3)


class Spec(LanguageSpec):
    code = "zh"
    name_en = "Mandarin"
    pack_name = "Mandarin (HSK 1–4)"
    tts = "zh-CN"
    passage_only = True             # no build pipeline: passages only (test_spec skips build fields)
    level_ids = ["1", "2", "3", "4"]
    passage_join = ""               # passage text = sentences joined without spaces
    passage_unspaced = True         # report ws_words = linked words (the count the app shows)

    def load(self):
        return self

    def passage_linker(self, shipped, pack_dir):
        import json
        pack = json.loads((pack_dir / "pack.json").read_text())
        return ZhLinker(shipped, pack.get("compounds", []))


SPEC = Spec


def _is_verb(word):
    en = word.get("en", "")
    return en.startswith("to ") or "; to " in en


class ZhLinker:
    """The passages.Linker interface (pretag, tag, classify, links_all,
    lemma_of, lemma_ids, num_ids, lowered) over the pack's own dictionary,
    plus declared (per-passage units), n_words and passage_notes."""

    def __init__(self, shipped, compounds=()):
        self.shipped = shipped
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
            if t[0] == "过" and t[3]["kind"] == "word" and prev[3]["e"] == t[3]["s"] and prev[3]["wid"] and \
                    prev[3]["kind"] in ("word", "compound", "derived") and _is_verb(self.shipped[prev[3]["wid"]]):
                t[1], t[2] = "过", "PART"
                t[3] = dict(t[3], wid=None, kind="particle")
        return toks

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
            toks.append([surf, lemma if kind != "unk" else surf, upos,
                         {"s": a + i, "e": a + e, "wid": wid, "kind": kind, "oopname": on}])
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
            spans.append([utf16_index(text, t[3]["s"]), utf16_index(text, t[3]["e"]), wid])
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
