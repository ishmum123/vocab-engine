"""Tests for zh passage readings (langs/zh.py ZhLinker.passage_ruby / token_reading)
and the validator rules for passages.json ruby fields (null wordId, titleRuby,
questions[].ruby, questions[].optionsRuby). Needs pypinyin (requirements-zh.txt).
The real-pack checks run against packs/zh when it is there.

    python3 -m pytest -q tools/packbuilder/tests/test_passage_zh_ruby.py     (from vocab-engine/)
"""
import io
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(TOOLS))   # vocab-engine/tools

import validate_pack  # noqa: E402
from packbuilder import passages  # noqa: E402
from packbuilder.langs import get_spec  # noqa: E402
from packbuilder.langs.zh import ZhLinker  # noqa: E402

try:
    import pypinyin  # noqa: F401
    HAVE_PYPINYIN = True
except ImportError:
    HAVE_PYPINYIN = False

# headword, gloss, pron
WORDS = [("这", "this", "zhè"), ("个", "classifier", "gè"), ("他", "he", "tā"), ("是", "to be", "shì"),
         ("我", "I", "wǒ"), ("的", "of", "de"), ("朋友", "friend", "péngyou"), ("去", "to go", "qù"),
         ("了", "(particle)", "le"), ("看", "to look", "kàn"), ("书", "book", "shū"), ("长", "long", "cháng"),
         ("大", "big", "dà"), ("地", "-ly", "de"), ("草", "grass", "cǎo"), ("越", "to exceed", "yuè"),
         ("来", "to come", "lái"), ("高兴", "happy", "gāoxìng"), ("哪", "which", "nǎ"), ("点", "a little", "diǎn"),
         ("一", "one", "yī"), ("下", "down", "xià"), ("过", "to cross", "guò"), ("都", "all", "dōu"),
         ("老师", "teacher", "lǎoshī"), ("小", "small", "xiǎo"), ("便宜", "cheap", "piányi"), ("女儿", "daughter", "nǚ'ér"),
         ("在", "at", "zài"), ("上", "up", "shàng")]
SHIPPED = {f"w{i + 1:04d}": {"id": f"w{i + 1:04d}", "w": w, "lv": "1", "en": en, "pron": py}
           for i, (w, en, py) in enumerate(WORDS)}
ID = {v["w"]: k for k, v in SHIPPED.items()}
COMPOUNDS = ["他们", "这个", "哪儿", "哪个"]
# sentences.json ruby surfaces that read otherwise than their word (passage_linker harvests these)
READINGS = {"这个": "zhège", "他们": "tāmen"}
# Script=Han as the engine tests it (core.js HAN_RE), incl. 〇 and the compatibility block
HAN = re.compile(r"[⺀-⿟々〇〡-〩〸-〻㐀-䶿一-鿿"
                 r"豈-﫿\U00020000-\U0003134f]")


def lk():
    return ZhLinker(SHIPPED, COMPOUNDS, None, dict(READINGS))


def ruby(text, names=(), oop=None):
    L = lk()
    decl = L.declared({"names": list(names), "oop": oop or {}})
    return [(text[a:b], r, w) for a, b, r, w in L.text_ruby(text, L.tag(text, "", decl))], L


@unittest.skipUnless(HAVE_PYPINYIN, "pypinyin not installed (requirements-zh.txt)")
class Readings(unittest.TestCase):
    def test_linked_word_reads_its_pron(self):
        r, _ = ruby("他是我的朋友。")
        self.assertEqual(r, [("他", "tā", ID["他"]), ("是", "shì", ID["是"]), ("我", "wǒ", ID["我"]),
                             ("的", "de", ID["的"]), ("朋友", "péngyou", ID["朋友"])])

    def test_compound_reads_whole_not_its_base(self):
        # the defect class: a span longer than its word lost syllables (这个 -> zhè)
        r, _ = ruby("这个是他们的书。")
        self.assertEqual(r[0], ("这个", "zhège", ID["这"]))
        self.assertEqual(r[2], ("他们", "tāmen", ID["他"]))

    def test_phrase_and_reduplication_compose_pack_pieces(self):
        r, _ = ruby("他越来越高兴地看看书。")
        self.assertIn(("越来越", "yuèláiyuè", ID["越"]), r)
        self.assertIn(("看看", "kànkàn", ID["看"]), r)
        self.assertIn(("地", "de", ID["地"]), r)

    def test_erhua(self):
        r, _ = ruby("他去哪儿？")
        self.assertIn(("哪儿", "nǎr", ID["哪"]), r)

    def test_surface_overrides_beat_the_head_word_pron(self):
        # 长 is cháng and 地 is de in the pack; the phrases read zhǎng and dì
        r, _ = ruby("他长大了。")
        self.assertEqual(r[1], ("长大", "zhǎngdà", ID["长"]))
        r, _ = ruby("他在草地上。")
        self.assertIn(("草地", "cǎodì", ID["地"]), r)

    def test_aspect_guo_is_neutral_and_unlinked(self):
        r, _ = ruby("他去过。")
        self.assertEqual(r[2], ("过", "guo", None))

    def test_names_capitalised_null_word_heteronym_by_pypinyin(self):
        r, L = ruby("王明去成都。", names=["王明", "成都"])
        self.assertEqual(r[0], ("王明", "Wáng Míng", None))
        self.assertEqual(r[2], ("成都", "Chéngdū", None))       # not the pack's 都 dōu
        self.assertIn("明", L.ruby_fallback)
        r, _ = ruby("小王是老师。", names=["王明"])
        self.assertEqual(r[0], ("小王", "Xiǎo Wáng", None))

    def test_char_overrides_for_a_lone_uncovered_character(self):
        # a one-character oop token: the HSK-context table, counted as an override
        L = ZhLinker({}, (), None, {})
        toks = L.tag("了", "", L.declared({"oop": {"了": "x"}}))
        self.assertEqual(L.text_ruby("了", toks)[0][2], "le")
        self.assertEqual(L.ruby_override, {"了": 1})
        self.assertEqual(L.ruby_fallback, {})
        # inside a longer oop word pypinyin's phrase reading wins (着急 zháojí)
        toks = L.tag("着急", "", L.declared({"oop": {"着急": "x"}}))
        self.assertEqual(L.text_ruby("着急", toks)[0][2], "zháojí")

    def test_di_rule(self):
        L = ZhLinker({ID["高兴"]: SHIPPED[ID["高兴"]]}, (), None, {})
        toks = L.tag("高兴地", "", L.declared({"oop": {"地": "x"}}))
        self.assertEqual(L.text_ruby("高兴地", toks)[1][2], "de")
        toks = L.tag("地", "", L.declared({"oop": {"地": "x"}}))
        self.assertEqual(L.text_ruby("地", toks)[0][2], "dì")

    def test_apostrophe_between_syllables(self):
        L = ZhLinker({}, (), None, {})
        toks = L.tag("西安", "", L.declared({"names": ["西安"]}))
        self.assertEqual(L.text_ruby("西安", toks)[0][2], "Xī'ān")

    def test_punctuation_digits_latin_get_none_and_utf16(self):
        L = lk()
        text = "𠀀他3个ABC，这。"
        toks = L.tag(text, "", frozenset())
        r = L.text_ruby(text, toks)
        # 𠀀 (U+20000) is two UTF-16 units: 他 starts at 2
        self.assertEqual([x[:2] for x in r], [[0, 2], [2, 3], [4, 5], [9, 10]])
        self.assertEqual(r[1][2], "tā")

    def test_no_characters_stage_no_ruby(self):
        L = ZhLinker(SHIPPED, COMPOUNDS)
        ps = [{"title": "他", "sentences": [{"t": "他。", "en": "He."}], "questions": []}]
        self.assertEqual(L.passage_ruby(ps, [frozenset()]), [])
        self.assertNotIn("ruby", ps[0]["sentences"][0])
        self.assertNotIn("titleRuby", ps[0])


def _passage(pid):
    sents = [["这个是他们的书。", "This is their book."], ["王明去过上海。", "Wang Ming has been to Shanghai."]]
    qs = [{"q": "这个是哪个的书？", "en": "Whose book?", "type": "mc", "options": ["他们的", "我的", "朋友的", "这个"],
           "answer": 0, "words": ["他"], "sentence": 0}] + \
         [{"q": "王明去过上海。", "en": "x", "type": "tf", "options": None, "answer": True, "words": ["去"], "sentence": 1}] * 3
    return {"id": pid, "lv": "1", "title": "他们的书", "names": ["王明", "上海"], "oop": {}, "sentences": sents, "questions": qs}


@unittest.skipUnless(HAVE_PYPINYIN, "pypinyin not installed (requirements-zh.txt)")
class EndToEnd(unittest.TestCase):
    RULES = {"coverage": {"1": 0.5, "2": 0.5, "3": 0.5, "4": 0.5},
             "budget": {"1": ["2", 1], "2": ["3", 3], "3": ["4", 3], "4": [None, 0]},
             "words_per_passage": {"1": [3, 60], "2": [3, 60], "3": [3, 60], "4": [3, 60]},
             "questions": [4, 5]}

    def build(self, d, characters):
        d = Path(d)
        pack = {"key": "zh", "compounds": COMPOUNDS}
        if characters:
            pack["characters"] = {"label": "字", "stages": [{"after": "1", "levels": ["1"]}]}
            (d / "characters.json").write_text(json.dumps(
                [{"id": f"c{k}", "t": w["w"], "words": [k], "lv": "1", "reading": w["pron"]} for k, w in SHIPPED.items()],
                ensure_ascii=False))
            (d / "sentences.json").write_text(json.dumps(
                [{"id": "s1", "t": "这个人", "en": "x", "lv": "1", "words": [ID["这"]], "ruby": [[0, 2, "zhège", ID["这"]]]}],
                ensure_ascii=False))
        (d / "words.json").write_text(json.dumps(list(SHIPPED.values()), ensure_ascii=False))
        (d / "pack.json").write_text(json.dumps(pack, ensure_ascii=False))
        (d / "passages_src.json").write_text(json.dumps({"rules": self.RULES, "passages": [_passage("p1")]}, ensure_ascii=False))
        buf = io.StringIO()
        rc = passages.run(get_spec("zh", str(d)), False, buf)
        self.assertEqual(rc, 0, buf.getvalue())
        return json.loads((d / "passages.json").read_text()), (d / "REPORT_passages.md").read_text()

    def test_fields_written_with_characters_only(self):
        with tempfile.TemporaryDirectory() as d:
            data, report = self.build(d, False)
            self.assertNotIn("titleRuby", data[0])
            self.assertNotIn("ruby", data[0]["sentences"][0])
            self.assertNotIn("Readings", report)
        with tempfile.TemporaryDirectory() as d:
            data, report = self.build(d, True)
            p = data[0]
            self.assertEqual(p["sentences"][0]["ruby"][0], [0, 2, "zhège", ID["这"]])   # harvested from sentences.json
            self.assertEqual(p["sentences"][1]["ruby"][0], [0, 2, "Wáng Míng", None])
            self.assertEqual([r[2] for r in p["titleRuby"]], ["tāmen", "de", "shū"])
            self.assertEqual(len(p["questions"][0]["optionsRuby"]), 4)
            self.assertNotIn("optionsRuby", p["questions"][1])
            self.assertIn("pypinyin readings with no override:", report)


class Validator(unittest.TestCase):
    def check(self, p, char_word0=frozenset({"w1"})):
        rep = validate_pack.Report()
        validate_pack.check_passages([p], {"1"}, {"w1": {}, "w2": {}}, rep, char_word0=set(char_word0))
        return rep

    def passage(self):
        return {"id": "p1", "lv": "1", "title": "他书", "text": "他书。",
                "sentences": [{"t": "他书。", "en": "x", "words": ["w1"], "ruby": [[0, 1, "tā", "w1"], [1, 2, "shū", None]]}],
                "questions": [{"q": "他？", "type": "mc", "options": ["他", "书", "a", "b"], "answer": 0, "words": ["w1"],
                               "sentence": 0, "ruby": [[0, 1, "tā", "w1"]],
                               "optionsRuby": [[[0, 1, "tā", "w1"]], [[0, 1, "shū", None]], [], []]}],
                "titleRuby": [[0, 1, "tā", "w1"], [1, 2, "shū", None]]}

    def test_valid_with_null_word_ids(self):
        rep = self.check(self.passage())
        self.assertEqual(rep.errors, [])

    def test_sentences_json_still_rejects_null(self):
        rep = validate_pack.Report()
        validate_pack.check_ruby([[0, 1, "tā", None]], "他", ["w1"], {"w1"}, "sentence s1", rep)
        self.assertTrue(rep.errors)

    def test_bad_fields(self):
        p = self.passage()
        p["titleRuby"] = [[0, 3, "tā", "w1"]]                        # out of bounds
        p["questions"][0]["optionsRuby"] = [[]]                      # one list per option
        p["questions"][0]["ruby"] = [[0, 1, "tā", "w2"]]             # not a unit's words[0]
        p["sentences"][0]["ruby"] = [[1, 2, "shū", None], [0, 1, "tā", "w1"]]   # unsorted
        errs = " | ".join(self.check(p).errors)
        self.assertIn("title.ruby[0] [0, 3] out of bounds", errs)
        self.assertIn("optionsRuby must be a list with one ruby list per option", errs)
        self.assertIn("q.ruby[0] word 'w2' is not words[0]", errs)
        self.assertIn("before the previous ruby's end", errs)


PACK = TOOLS.parent / "packs" / "zh"


@unittest.skipUnless((PACK / "passages.json").exists(), "packs/zh not present")
class RealPack(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ps = json.loads((PACK / "passages.json").read_text())
        cls.words = {w["id"]: w for w in json.loads((PACK / "words.json").read_text())}

    def texts(self):
        for p in self.ps:
            yield p["title"], p.get("titleRuby")
            for s in p["sentences"]:
                yield s["t"], s.get("ruby")
            for q in p["questions"]:
                yield q["q"], q.get("ruby")
                for o, r in zip(q.get("options") or (), q.get("optionsRuby") or [None] * 4):
                    yield o, r

    @staticmethod
    def u16(t):
        """UTF-16 index -> the code point index of every unit boundary."""
        out, n = {}, 0
        for i, ch in enumerate(t):
            out[n] = i
            n += 2 if ord(ch) > 0xFFFF else 1
        out[n] = len(t)
        return out

    def test_every_hanzi_has_a_reading(self):
        missing = []
        for t, r in self.texts():
            m = self.u16(t)
            cov = set()
            for a, b, reading, _w in r or ():
                self.assertTrue(reading)
                cov.update(range(m[a], m[b]))
            missing += [(t, ch) for i, ch in enumerate(t) if HAN.match(ch) and i not in cov]
        self.assertEqual(missing, [])

    def test_offsets_and_word_ids_valid(self):
        rep = validate_pack.Report()
        units = json.loads((PACK / "characters.json").read_text())
        validate_pack.check_passages(self.ps, {"1", "2", "3", "4"}, self.words, rep,
                                     char_word0={u["words"][0] for u in units})
        self.assertEqual(rep.errors, [])

    def test_linked_spans_read_their_word_pron(self):
        bad = []
        for p in self.ps:
            for s in p["sentences"]:
                rb = {(a, b): (r, w) for a, b, r, w in s.get("ruby", ())}
                for a, b, wid, *_g in s["spans"]:
                    got = rb.get((a, b))
                    self.assertIsNotNone(got, (s["t"], a, b))      # every span is one ruby token
                    self.assertEqual(got[1], wid)
                    if s["t"][a:b] == self.words[wid]["w"] and got[0] != self.words[wid]["pron"]:
                        bad.append((s["t"][a:b], got[0]))
        self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main()
