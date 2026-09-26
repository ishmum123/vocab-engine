"""Tests for the Chinese passage linker (langs/zh.py ZhLinker) and the generic
passage hooks it uses in passages.run (flat pack layout, spec.passage_linker,
declared units, n_words, passage_join). A synthetic pack; stdlib only
(jieba is optional and report-only, so no test depends on it).

    python3 -m pytest -q tools/packbuilder/tests/test_passage_zh.py     (from vocab-engine/)
"""
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))   # vocab-engine/tools

from packbuilder import passages  # noqa: E402
from packbuilder.langs import get_spec  # noqa: E402
from packbuilder.langs.zh import ZhLinker  # noqa: E402

# headword, level, gloss
WORDS = [("一", "1", "one"), ("三", "1", "three"), ("八", "1", "eight"), ("九", "1", "nine"), ("十", "1", "ten"),
         ("两", "2", "two"), ("个", "1", "classifier"), ("岁", "1", "years old"), ("块", "1", "lump; piece"),
         ("他", "1", "he"), ("你", "1", "you"), ("这", "1", "this"), ("我", "1", "I; me"), ("朋友", "1", "friend"),
         ("看", "1", "to see; to look at"), ("看见", "1", "to see; to catch sight of"), ("听", "1", "to listen"),
         ("高兴", "1", "happy"), ("休息", "2", "to rest"), ("吃", "1", "to eat"), ("了", "1", "(completed action marker)"),
         ("不", "1", "no; not"), ("没", "1", "not"), ("有", "1", "to have"), ("去", "1", "to go"),
         ("是", "1", "to be"), ("的", "1", "of"), ("来", "1", "to come"), ("昨天", "1", "yesterday"),
         ("老师", "1", "teacher"), ("小", "1", "small"), ("上", "1", "up"), ("海", "3", "sea"),
         ("过", "4", "to cross; to go over"), ("马路", "3", "road"), ("十分", "4", "very"), ("分钟", "1", "minute"),
         ("钟", "3", "clock"), ("书", "1", "book"), ("喜欢", "1", "to like"), ("点", "1", "point; dot"),
         ("面", "2", "face"), ("爸爸", "1", "dad"), ("地", "3", "-ly"), ("跑", "2", "to run"),
         ("越", "3", "to exceed"), ("开", "1", "to open"), ("车", "1", "car"), ("生日", "2", "birthday"),
         ("下午", "1", "afternoon"), ("早上", "2", "early morning"), ("课", "2", "lesson"), ("卖", "2", "to sell"),
         ("水", "1", "water"), ("商店", "1", "shop"), ("钱", "1", "money"), ("好", "1", "good"), ("下", "1", "down")]
SHIPPED = {f"w{i + 1:04d}": {"id": f"w{i + 1:04d}", "w": w, "lv": lv, "en": en, "pron": ""}
           for i, (w, lv, en) in enumerate(WORDS)}
ID = {v["w"]: k for k, v in SHIPPED.items()}
COMPOUNDS = ["他们", "你们", "这个", "这儿"]


def lk():
    return ZhLinker(SHIPPED, COMPOUNDS)


def seg(text, names=(), oop=None):
    L = lk()
    decl = L.declared({"names": list(names), "oop": oop or {}})
    return L, L.tag(text, "", decl)


def view(toks):
    """[(surface, linked headword or None, kind)] without punctuation."""
    return [(t[0], SHIPPED[t[3]["wid"]]["w"] if t[3]["wid"] else None, t[3]["kind"]) for t in toks
            if t[3]["kind"] != "punct"]


class Segmentation(unittest.TestCase):
    def test_compound_links_base(self):
        # pack.json compounds policy: 他们 -> 他, one token
        self.assertEqual(view(seg("他们来了。")[1])[0], ("他们", "他", "compound"))

    def test_men_plural(self):
        self.assertEqual(view(seg("朋友们")[1]), [("朋友们", "朋友", "derived")])

    def test_reduplication(self):
        self.assertEqual(view(seg("看看书")[1]), [("看看", "看", "derived"), ("书", "书", "word")])
        self.assertEqual(view(seg("看一看")[1]), [("看一看", "看", "derived")])
        self.assertEqual(view(seg("看了看")[1]), [("看了看", "看", "derived")])
        self.assertEqual(view(seg("高高兴兴")[1]), [("高高兴兴", "高兴", "derived")])
        self.assertEqual(view(seg("休息休息")[1]), [("休息休息", "休息", "derived")])
        self.assertEqual(view(seg("爸爸")[1]), [("爸爸", "爸爸", "word")])   # a pack word is not reduplication

    def test_le_after_verb(self):
        self.assertEqual(view(seg("我吃了。")[1]), [("我", "我", "word"), ("吃", "吃", "word"), ("了", "了", "word")])

    def test_numerals_and_measure_words(self):
        L, toks = seg("三个朋友，八十九块，5岁，两个")
        v = view(toks)
        self.assertEqual(v[:2], [("三", "三", "num"), ("个", "个", "word")])
        self.assertEqual(v[3:7], [("八", "八", "num"), ("十", "十", "num"), ("九", "九", "num"), ("块", "块", "word")])
        self.assertEqual(v[7:9], [("5", None, "digit"), ("岁", "岁", "word")])
        counted = [c[0] for c in L.classify(toks)]
        self.assertEqual(counted, ["个", "朋友", "块", "岁", "个"])     # numerals are not counted
        self.assertEqual(L.n_words(toks), 8)    # 三 个 朋友 八十九 块 岁 两 个: one word per numeral run; 5 not
        ids, _cl, spans, _c = L.links_all(toks, "三个朋友，八十九块，5岁，两个", "")
        self.assertIn(ID["八"], ids)            # numerals link (one span each)
        self.assertEqual([s[:2] for s in spans if s[2] == ID["十"]], [[6, 7]])

    def test_negation(self):
        self.assertEqual(view(seg("我不去")[1]), [("我", "我", "word"), ("不", "不", "word"), ("去", "去", "word")])
        self.assertEqual(view(seg("没有")[1]), [("没", "没", "word"), ("有", "有", "word")])

    def test_resultative(self):
        self.assertEqual(view(seg("看见")[1]), [("看见", "看见", "word")])
        self.assertEqual(view(seg("听见")[1]), [("听见", "听", "derived")])     # 见 is no pack word

    def test_shi_de(self):
        v = view(seg("我是昨天来的。")[1])
        self.assertEqual([x[1] for x in v], ["我", "是", "昨天", "来", "的"])

    def test_declared_names(self):
        L, toks = seg("王明是我的老师。王老师和小王。", names=["王明"])
        v = view(toks)
        self.assertEqual(v[0], ("王明", None, "name"))
        self.assertIn(("王", None, "name"), v)       # surname before a title
        self.assertIn(("老师", "老师", "word"), v)
        self.assertIn(("小王", None, "name"), v)
        self.assertNotIn("王明", [c[0] for c in L.classify(toks)])

    def test_place_name_not_split(self):
        # 上海 declared: not 上 + 海 (two pack words)
        L, toks = seg("我去上海。", names=["上海"])
        self.assertEqual(view(toks)[2], ("上海", None, "name"))
        L, toks = seg("我去上海。")
        self.assertEqual([x[1] for x in view(toks)], ["我", "去", "上", "海"])

    def test_declared_oop_is_a_counted_unit(self):
        L, toks = seg("我喜欢熊猫。", oop={"熊猫": "panda, not in HSK 1-4"})
        self.assertEqual(view(toks)[2], ("熊猫", None, "oop"))
        self.assertEqual([(c[1], c[2]) for c in L.classify(toks)][-1], ("熊猫", None))

    def test_unknown_run_merges(self):
        L, toks = seg("我喜欢熊猫。")
        self.assertEqual(view(toks)[2], ("熊猫", None, "unk"))
        self.assertEqual(L.classify(toks)[-1][:3], ("熊猫", "熊猫", None))

    def test_guo_aspect_after_verb(self):
        L, toks = seg("我去过。他过马路。")
        v = view(toks)
        self.assertEqual(v[2], ("过", None, "particle"))
        self.assertEqual(v[4], ("过", "过", "word"))      # after 他: the verb "to cross"
        self.assertNotIn("过", [c[0] for c in L.classify(toks)][:2])

    def test_reverse_maximum_matching_tie(self):
        self.assertEqual([x[1] for x in view(seg("十分钟")[1])], ["十", "分钟"])

    def test_locative_and_erhua(self):
        self.assertEqual(view(seg("上面")[1]), [("上面", "上", "derived")])
        self.assertEqual(view(seg("这儿")[1]), [("这儿", "这", "compound")])
        self.assertEqual(view(seg("点儿")[1]), [("点儿", "点", "derived")])

    def test_spans_utf16(self):
        text = "𠀀我看书"          # U+20000 is two UTF-16 code units
        L, toks = seg(text)
        _ids, _cl, spans, _c = L.links_all(toks, text, "")
        self.assertEqual(spans, [[2, 3, ID["我"]], [3, 4, ID["看"]], [4, 5, ID["书"]]])

    def test_one_span_per_compound(self):
        text = "他们看看朋友们。"
        L, toks = seg(text)
        ids, _cl, spans, _c = L.links_all(toks, text, "")
        self.assertEqual(spans, [[0, 2, ID["他"]], [2, 4, ID["看"]], [4, 7, ID["朋友"]]])
        self.assertEqual(ids, [ID["他"], ID["看"], ID["朋友"]])

    def test_deterministic(self):
        a = lk().segment("我们去过上海，他们看看朋友们。", frozenset({"上海"}))
        b = lk().segment("我们去过上海，他们看看朋友们。", frozenset({"上海"}))
        self.assertEqual(a, b)


class PhrasesAndGlosses(unittest.TestCase):
    def spans(self, text, display=None):
        L = ZhLinker(SHIPPED, COMPOUNDS)
        toks = L.tag(text, "", frozenset())
        sp = L.links_all(toks, text, "")[2]
        return passages.span_glosses(sp, display, SHIPPED) if display else sp

    def test_phrase_one_span_with_gloss(self):
        self.assertEqual(self.spans("越来越好"), [[0, 3, ID["越"], "more and more"], [3, 4, ID["好"]]])
        self.assertEqual(self.spans("开车"), [[0, 2, ID["开"], "to drive (a car)"]])
        self.assertEqual(self.spans("过生日"), [[0, 3, ID["过"], "to celebrate a birthday"]])
        self.assertEqual(self.spans("看一下"), [[0, 1, ID["看"]], [1, 3, ID["下"], "(V+一下) briefly, a bit"]])
        self.assertEqual(self.spans("有点")[0][:3], [0, 2, ID["点"]])

    def test_phrase_guards(self):
        v = lambda t: [x[0] for x in seg(t)[1] if x[3]["kind"] != "punct"]      # noqa: E731
        self.assertEqual(v("一点钟"), ["一", "点", "钟"])            # clock, not "a little"
        self.assertEqual(v("下午一点"), ["下午", "一", "点"])
        self.assertEqual(v("十一点"), ["十", "一", "点"])
        self.assertEqual(v("一下午"), ["一", "下午"])               # 下午 is a pack word
        self.assertEqual(v("早上课"), ["早上", "课"])               # 早上 wins over 上课
        self.assertEqual(v("放一点"), ["放", "一点"])

    def test_meiyou_before_verb(self):
        self.assertEqual(self.spans("没有去"), [[0, 2, ID["没"], "did not; have not (没有+V)"], [2, 3, ID["去"]]])
        self.assertEqual(self.spans("没有和我")[0], [0, 2, ID["没"], "did not; have not (没有+V)"])
        self.assertEqual(self.spans("没有在")[0], [0, 2, ID["没"], "did not; have not (没有+V)"])
        self.assertEqual(self.spans("没有钱"), [[0, 1, ID["没"]], [1, 2, ID["有"]], [2, 3, ID["钱"]]])
        # 没有 + V ... 的 + N: "there is no shop that sells water", two words
        self.assertEqual([s[2] for s in self.spans("没有卖水的商店")][:2], [ID["没"], ID["有"]])

    def test_display_gloss_on_every_span_of_the_word(self):
        sp = self.spans("我看书，他们看看。", {"看": "to see; to read (display)"})
        self.assertEqual(sp, [[0, 1, ID["我"]], [1, 2, ID["看"], "to see; to read (display)"], [2, 3, ID["书"]],
                              [4, 6, ID["他"]], [6, 8, ID["看"], "to see; to read (display)"]])

    def test_phrase_gloss_beats_display(self):
        self.assertEqual(self.spans("开车", {"开": "to open (display)"}), [[0, 2, ID["开"], "to drive (a car)"]])

    def test_q_words_visible(self):
        sh = {"a": {"w": "猫"}, "b": {"w": "狗"}}

        class L:
            lemma_of = {"a": {"猫"}, "b": {"狗"}}
        self.assertTrue(passages._q_words_in_sentence(L, sh, ["a"], {"t": "我有猫", "spans": []}))
        self.assertTrue(passages._q_words_in_sentence(L, sh, ["b"], {"t": "我有猫", "spans": [[2, 3, "b"]]}))
        self.assertFalse(passages._q_words_in_sentence(L, sh, ["b"], {"t": "我有猫", "spans": [[2, 3, "a"]]}))


def _passage(pid, lv, sents, q_words, names=(), oop=None, n=4):
    return {"id": pid, "lv": lv, "title": "我的朋友", "names": list(names), "oop": oop or {},
            "sentences": sents,
            "questions": [{"q": "他是我的朋友。", "en": "He is my friend.", "type": "tf", "options": None,
                           "answer": True, "words": q_words, "sentence": 0}] * n}


class EndToEnd(unittest.TestCase):
    RULES = {"coverage": {"1": 0.9, "2": 0.9, "3": 0.9, "4": 0.9},
             "budget": {"1": ["2", 1], "2": ["3", 3], "3": ["4", 3], "4": [None, 0]},
             "words_per_passage": {"1": [5, 60], "2": [5, 60], "3": [5, 60], "4": [5, 60]},
             "questions": [4, 5]}

    def make(self, d, ps):
        d = Path(d)
        (d / "words.json").write_text(json.dumps(list(SHIPPED.values()), ensure_ascii=False))
        (d / "pack.json").write_text(json.dumps({"key": "zh", "compounds": COMPOUNDS}, ensure_ascii=False))
        (d / "passages_src.json").write_text(json.dumps({"rules": self.RULES, "passages": ps}, ensure_ascii=False))
        return d

    def run_pack(self, d, check=False):
        buf = io.StringIO()
        rc = passages.run(get_spec("zh", str(d)), check, buf)
        return rc, buf.getvalue()

    def test_flat_layout_writes_and_is_deterministic(self):
        ps = [_passage("p1", "1", [["他们是我的朋友。", "They are my friends."],
                                   ["王明看看书，他去过上海。", "Wang Ming reads a bit; he has been to Shanghai."]],
                       ["他", "朋友"], names=["王明", "上海"])]
        with tempfile.TemporaryDirectory() as d:
            d = self.make(d, ps)
            self.assertEqual(passages.layout(d), (d, d))
            rc, out = self.run_pack(d)
            self.assertEqual(rc, 0, out)
            first = (d / "passages.json").read_bytes()
            rc, _ = self.run_pack(d)
            self.assertEqual((d / "passages.json").read_bytes(), first)       # byte-identical rebuild
            data = json.loads(first)
            s0 = data[0]["sentences"][0]
            self.assertEqual(s0["words"], [ID["他"], ID["是"], ID["我"], ID["的"], ID["朋友"]])
            self.assertEqual(s0["spans"][0], [0, 2, ID["他"]])
            self.assertEqual(data[0]["text"], "他们是我的朋友。王明看看书，他去过上海。")   # passage_join ""
            self.assertEqual(data[0]["questions"][0]["words"], [ID["他"], ID["朋友"]])
            report = (d / "REPORT_passages.md").read_text()
            self.assertIn("1 may use <=1 2 lemmas and nothing above", report)
            self.assertIn("from `passages_src.json`", report)

    def test_flat_layout_gloss_display_and_self_checks(self):
        p = _passage("p1", "1", [["他们是我的朋友。", "They are my friends."], ["他开车去商店。", "He drives to the shop."]],
                     ["他"], n=3)
        p["questions"].append({"q": "他去商店。", "en": "He goes to the shop.", "type": "mc",
                               "options": ["开车去商店", "朋友", "书", "水"], "answer": 0, "words": ["开"], "sentence": 1})
        with tempfile.TemporaryDirectory() as d:
            d = self.make(d, [p])
            (d / "gloss_display.json").write_text(json.dumps({"_note": "x", "朋友": "friend (display)"}, ensure_ascii=False))
            rc, out = self.run_pack(d)
            self.assertEqual(rc, 0, out)
            s0, s1 = json.loads((d / "passages.json").read_text())[0]["sentences"]
            self.assertIn([5, 7, ID["朋友"], "friend (display)"], s0["spans"])
            self.assertIn([1, 3, ID["开"], "to drive (a car)"], s1["spans"])
            self.assertIn("self-check: level 1: 1/1 mc keys verbatim in the passage text (>=4 chars, numerals exempt): "
                          "p1 q3 '开车去商店'", out)
            self.assertNotIn("none of its words", out)

    def test_budget_and_oop_errors_with_hsk_levels(self):
        ps = [_passage("p1", "1", [["他们是我的朋友。", "."], ["我喜欢休息，喜欢跑，喜欢熊猫。", "."]],
                       ["他"]),
              _passage("p2", "1", [["他们是我的朋友。", "."], ["他十分喜欢海。", "."]], ["他"])]
        with tempfile.TemporaryDirectory() as d:
            d = self.make(d, ps)
            rc, out = self.run_pack(d, check=True)
            self.assertEqual(rc, 1)
            self.assertIn("2 2 words > 1", out)                          # 休息, 跑 at level 1
            self.assertIn("out-of-pack lemmas without a reason: ['熊猫']", out)
            self.assertIn("3 words not allowed at 1: ['海']", out)
            self.assertIn("4 words not allowed at 1: ['十分']", out)
            self.assertFalse((d / "passages.json").exists())


if __name__ == "__main__":
    unittest.main()
