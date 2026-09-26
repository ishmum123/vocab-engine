"""Tests for the Japanese passage hooks (langs/ja.py) and the generic
passage-tagging cache guard (spec.passage_tagging, core.util.derived_write_ok,
passages.Linker.pretag's tripwire): declared names joined into one PROPN,
grammar tokens not counted, passage_lemma_alias from pack alt spellings,
pickling a spec that holds an unpicklable tokenizer, and no derived-cache
write while passage texts are tagged. Sudachi is not needed. Stdlib only.

    python3 -m pytest -q tools/packbuilder/tests/test_passage_ja.py     (from vocab-engine/)
"""
import json
import pickle
import sys
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))   # vocab-engine/tools

from packbuilder import passages  # noqa: E402
from packbuilder.core.util import derived_write_ok  # noqa: E402
from packbuilder.langs import get_spec  # noqa: E402


def spec(repo="/nonexistent-ja-repo"):
    return get_spec("ja", repo, load=False)


def T(text, lemma=None, upos="NOUN", pos=""):
    return [text, lemma or text, upos, f"Pos={pos}" if pos else ""]


class Names(unittest.TestCase):
    def test_split_name_joined_into_one_propn(self):
        toks = [T("あおば"), T("町", pos="名詞-普通名詞"), T("に", upos="ADP"), T("住む", upos="VERB")]
        out = spec().passage_retag(toks, frozenset({"あおば町"}))
        self.assertEqual([t[:3] for t in out], [["あおば町", "あおば町", "PROPN"], ["に", "に", "ADP"],
                                                ["住む", "住む", "VERB"]])

    def test_single_token_name_is_propn_not_pack_word(self):
        out = spec().passage_retag([T("あかり", "明かり"), T("は", upos="ADP")], frozenset({"あかり"}))
        self.assertEqual(out[0][:3], ["あかり", "あかり", "PROPN"])

    def test_no_names_unchanged(self):
        toks = [T("あかり", "明かり")]
        self.assertIs(spec().passage_retag(toks, frozenset()), toks)

    def test_longest_declared_name_wins(self):
        out = spec().passage_retag([T("田中"), T("さん")], frozenset({"田中", "田中さん"}))
        self.assertEqual([t[0] for t in out], ["田中さん"])


TE = "Pos=助詞-接続助詞"


class QARules(unittest.TestCase):
    """Passage QA rules (a)-(g): passage_retag and passage_post_resolve."""

    def upos(self, toks, names=frozenset()):
        return [(t[0], t[2]) for t in spec().passage_retag(toks, names)]

    def test_a_auxiliary_after_te(self):
        toks = [T("なっ", "なる", "VERB"), ["て", "て", "PART", TE], T("いく", "行く", "VERB")]
        self.assertEqual(self.upos(toks)[2], ("いく", "X"))
        toks = [T("来", "来る", "VERB"), ["て", "て", "PART", TE], T("ほしい", "欲しい", "ADJ")]
        self.assertEqual(self.upos(toks)[2], ("ほしい", "X"))
        toks = [T("聞こえ", "聞こえる", "VERB"), ["て", "て", "PART", TE], T("き", "来る", "VERB")]
        self.assertEqual(self.upos(toks)[2], ("き", "X"))
        # kanji 行く after the te-form is the motion verb; で "by" is no te-form
        toks = [T("歩い", "歩く", "VERB"), ["て", "て", "PART", TE], T("行き", "行く", "VERB")]
        self.assertEqual(self.upos(toks)[2], ("行き", "VERB"))
        toks = [T("車"), ["で", "で", "PART", "Pos=助詞-格助詞"], T("くる", "来る", "VERB")]
        self.assertEqual(self.upos(toks)[2], ("くる", "VERB"))

    def test_b_to_iu(self):
        toks = [T("減る", upos="VERB"), T("と", upos="PART"), T("いう", "言う", "VERB"), T("問題")]
        self.assertEqual(self.upos(toks), [("減る", "VERB"), ("と", "X"), ("いう", "X"), ("問題", "NOUN")])
        toks = [T("と", upos="PART"), T("言い", "言う", "VERB")]          # 「…」と言いました: the verb
        self.assertIs(spec().passage_retag(toks, frozenset()), toks)

    def test_c_mae_after_duration(self):
        sp = spec()
        toks = [T("3", "", "NUM"), T("年", "〜年"), T("前"), T("に", upos="PART")]
        self.assertEqual(sp.passage_post_resolve(toks, [None, ("〜年", "NOUN"), ("前に", "ADV"), None]),
                         [None, ("〜年", "NOUN"), ("前", "NOUN"), ("に", "PART")])
        toks = [T("400", "", "NUM"), T("年", "〜年"), T("以上"), T("前"), T("に", upos="PART")]
        out = sp.passage_post_resolve(toks, [None, ("〜年", "NOUN"), ("以上", "NOUN"), ("前に", "ADV"), None])
        self.assertEqual(out[3:], [("前", "NOUN"), ("に", "PART")])
        toks = [T("寝る", upos="VERB"), T("前"), T("に", upos="PART")]      # 寝る前に: unchanged
        self.assertEqual(sp.passage_post_resolve(toks, [("寝る", "VERB"), ("前に", "ADV"), None])[1], ("前に", "ADV"))

    def test_d_go_after_sono_or_duration(self):
        self.assertEqual(self.upos([T("その", upos="DET"), T("後", "後（ご）")])[1], ("後", "X"))
        self.assertEqual(self.upos([T("1", "", "NUM"), T("ヶ月", "〜ヶ月"), T("後", "")])[2], ("後", "X"))
        toks = [T("食べ", "食べる", "VERB"), T("た", upos="AUX"), T("後")]      # 食べた後 (あと) stays
        self.assertIs(spec().passage_retag(toks, frozenset()), toks)

    def test_e_numeral_tsu_one_unit(self):
        out = spec().passage_retag([T("一", "一（ひと）", "NUM"), T("つ", "〜つ"), T("は", upos="PART")], frozenset())
        self.assertEqual(out[0][:3], ["一つ", "〜つ", "NOUN"])
        # a digit numeral does not join (_passage_join): つ links on its own, no
        # irregular reading to preserve (test_no_join_for_digits_non_headwords_or_other_pos)
        out = spec().passage_retag([T("3", "", "NUM"), T("つ", "〜つ")], frozenset())
        self.assertEqual([t[0] for t in out], ["3", "つ"])

    def test_f_counter_prefers_lower_level_plain_noun(self):
        sp = spec()
        sp._passage_lv = {"点": "A1", "〜点": "B1", "〜回": "A1", "回": "B1"}
        toks = [T("3", "", "NUM"), T("点", "〜点")]
        self.assertEqual(sp.passage_post_resolve(toks, [None, ("〜点", "NOUN")])[1], ("点", "NOUN"))
        toks = [T("2", "", "NUM"), T("回", "〜回")]                  # the counter is the lower level: kept
        self.assertEqual(sp.passage_post_resolve(toks, [None, ("〜回", "NOUN")])[1], ("〜回", "NOUN"))
        toks = [T("点", "〜点")]                                     # no numeral before: kept
        self.assertEqual(sp.passage_post_resolve(toks, [("〜点", "NOUN")])[0], ("〜点", "NOUN"))

    def test_g_name_suffix(self):
        # the joined form is itself declared: absorbed into the name token
        out = spec().passage_retag([T("松本"), T("城", "城", "NUM"), T("は", upos="PART")],
                                    frozenset({"松本", "松本城"}))
        self.assertEqual([t[:3] for t in out][0], ["松本城", "松本城", "PROPN"])
        # only the plain name declared (松本城の見学案内, the shipped passage): 城
        # stays its own token and links the pack word "castle", as shipped
        out = spec().passage_retag([T("松本"), T("城", "城", "NUM"), T("は", upos="PART")], frozenset({"松本"}))
        self.assertEqual([t[:3] for t in out], [["松本", "松本", "PROPN"], ["城", "城", "NUM"], ["は", "は", "PART"]])
        out = spec().passage_retag([T("城"), T("の", upos="PART")], frozenset({"松本"}))
        self.assertEqual(out[0][0], "城")                            # the noun castle stays


class SpanGlosses(unittest.TestCase):
    def test_bare_headword_and_lemma_pos_keys(self):
        sh = {"a": {"w": "高い", "lemma": "高い", "pos": "adj"}, "b": {"w": "点", "lemma": "点", "pos": "noun"},
              "c": {"w": "猫", "lemma": "猫", "pos": "noun"}}
        table = {"高い": "high, tall; expensive", "点|noun": "point(s)"}
        spans = [[0, 2, "a"], [2, 3, "b"], [3, 4, "c"], [4, 5, "a", "own gloss"]]
        self.assertEqual(passages.span_glosses(spans, table, sh),
                         [[0, 2, "a", "high, tall; expensive"], [2, 3, "b", "point(s)"], [3, 4, "c"], [4, 5, "a", "own gloss"]])

    def test_flag_owners(self):
        self.assertTrue(spec().passage_span_glosses)
        self.assertFalse(get_spec("ko", None, load=False).passage_span_glosses)   # ko merges its table into en at build


class Uncounted(unittest.TestCase):
    def test_grammar_tokens(self):
        toks = [T("勉強", upos="NOUN"), T("し", "する", "VERB"), T("て", upos="SCONJ"),
                T("いる", "いる", "VERB", "動詞-非自立可能"), T("ん", upos="PART"), T("です", upos="AUX"),
                T("食べる", upos="VERB", pos="動詞-一般")]
        resolved = [("勉強", "NOUN"), None, None, None, None, None, ("食べる", "VERB")]
        self.assertEqual(spec().passage_uncounted(toks, resolved), {1, 3, 4, 5})

    def test_linked_suru_after_noun_counts_when_resolved(self):
        toks = [T("勉強"), T("する", upos="VERB")]
        self.assertEqual(spec().passage_uncounted(toks, [("勉強", "NOUN"), ("する", "VERB")]), set())

    def test_classify_skips_uncounted_only_when_unlinked(self):
        # the classify hook: a token in passage_uncounted with no pack id is dropped
        src = Path(passages.__file__).read_text()
        self.assertIn("if wid is None and i in uncounted:", src)


class Alias(unittest.TestCase):
    def test_alias_from_single_owner_alts(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "pack").mkdir()
            words = [{"id": "w1", "w": "皆", "lemma": "皆", "alt": ["みんな", "みな"]},
                     {"id": "w2", "w": "ところ", "lemma": "ところ", "alt": ["所"]},
                     {"id": "w3", "w": "明かり", "lemma": "明かり", "alt": ["あかり"]},
                     {"id": "w4", "w": "頃", "lemma": "頃", "alt": []},
                     {"id": "w5", "w": "会う", "lemma": "会う", "alt": ["あう"]},
                     {"id": "w6", "w": "合う", "lemma": "合う", "alt": ["あう"]}]
            (Path(d) / "pack" / "words.json").write_text(json.dumps(words, ensure_ascii=False))
            sp = spec(d)
            self.assertEqual(sp.passage_text("テキスト", frozenset({"あかり"}), None), "テキスト")
            a = sp.passage_lemma_alias
            self.assertEqual(a["みんな"], "皆")
            self.assertEqual(a["所"], "ところ")
            self.assertEqual(a["ごろ"], "頃")                 # 7時ごろ: the pack's 頃
            self.assertNotIn("あう", a)                       # two owners: ambiguous
            self.assertNotIn("あかり", a)                     # a declared name is never a pack word
            self.assertEqual(spec().passage_lemma_alias, {})  # the class default stays empty


class Pickling(unittest.TestCase):
    def test_spec_with_tokenizer_pickles_through_getstate(self):
        sp = spec()
        sp._tok = threading.Lock()                          # stands in for the Sudachi tokenizer
        with self.assertRaises(TypeError):
            pickle.dumps(sp.__dict__)
        state = {k: v for k, v in sp.__getstate__().items() if k != "repo"}   # as passages.load_context
        back = pickle.loads(pickle.dumps(state))
        self.assertIsNone(back["_tok"])
        self.assertIsNotNone(sp._tok)                       # the live spec keeps its tokenizer
        self.assertIsNone(pickle.loads(pickle.dumps(sp))._tok)

    def test_other_specs_state_is_their_dict(self):
        sp = get_spec("it", None, load=False)
        self.assertEqual(sp.__getstate__(), sp.__dict__)


class PassageTaggingGuard(unittest.TestCase):
    def test_derived_write_ok_follows_the_flag(self):
        sp = spec()
        self.assertTrue(derived_write_ok(sp))
        sp.passage_tagging = True
        self.assertFalse(derived_write_ok(sp))

    def test_ja_groups_file_not_written_while_tagging_passages(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "ja_groups_t22_x.json.gz"
            sp = spec()
            with mock.patch.object(type(sp), "_kaikki_alias", lambda self: {"alias": {}}), \
                    mock.patch.object(type(sp), "_groups_path", lambda self: path):
                sp.passage_tagging = True
                sp._build_groups({})
                self.assertFalse(path.exists())
                sp.passage_tagging = False
                sp._build_groups({})
                self.assertTrue(path.exists())           # the corpus build still saves it

    def fake_linker(self, repo, write):
        sp = types.SimpleNamespace(repo=Path(repo), passage_tagging=False)
        seen = {}

        def _pretag(todo):
            seen["flag"] = sp.passage_tagging
            if write:
                (Path(repo) / ".cache" / "derived" / "groups.json.gz").write_bytes(b"passage-only")
        return types.SimpleNamespace(spec=sp, tagged={}, _pretag=_pretag), seen

    def test_pretag_sets_the_flag_and_restores_it(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / ".cache" / "derived").mkdir(parents=True)
            lk, seen = self.fake_linker(d, write=False)
            passages.Linker.pretag(lk, [("文", "text")])
            self.assertTrue(seen["flag"])
            self.assertFalse(lk.spec.passage_tagging)

    def test_tripwire_fails_on_any_derived_write(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / ".cache" / "derived").mkdir(parents=True)
            lk, _ = self.fake_linker(d, write=True)
            with self.assertRaises(SystemExit) as e:
                passages.Linker.pretag(lk, [("文", "text")])
            self.assertIn("groups.json.gz", str(e.exception))
            self.assertFalse(lk.spec.passage_tagging)      # restored even when it fails


def M(text, lemma=None, upos="NOUN", pos="", read="", conj="", dic=None, ctr=False):
    """A token with Sudachi-style features (Dict, Read, Pos, Conj, Ctr)."""
    f = [f"Dict={dic or lemma or text}", f"Read={read or text}", f"Pos={pos}"]
    if conj:
        f.append(f"Conj={conj}")
    if ctr:
        f.append("Ctr=1")
    return [text, lemma or text, upos, "|".join(f)]


def ja_spec(heads=None):
    sp = spec()
    from collections import defaultdict
    sp._passage_heads = defaultdict(set, {k: set(v) for k, v in (heads or {}).items()})
    return sp


class Joins(unittest.TestCase):
    """passage_retag: tokens Sudachi splits that are one pack word."""

    def test_kanji_numeral_and_tsu_is_one_counter_token(self):
        for num, rd in (("一", "ヒト"), ("三", "ミッ"), ("四", "ヨッ")):
            out = ja_spec().passage_retag([M(num, upos="NUM", read=rd), M("つ", "〜つ", pos="接尾辞-名詞的-助数詞", read="ツ")])
            self.assertEqual([t[:3] for t in out], [[num + "つ", "〜つ", "NOUN"]])
            self.assertIn(f"Read={rd}ツ", out[0][3])

    def test_determiner_or_numeral_plus_noun_joins_to_a_pack_headword(self):
        sp = ja_spec({"その後": {"NOUN"}, "一番": {"ADV"}})
        out = sp.passage_retag([M("その", upos="DET"), M("後", "後（ご）", read="ゴ"), M("、", upos="PUNCT")])
        self.assertEqual(out[0][:3], ["その後", "その後", "NOUN"])
        out = sp.passage_retag([M("一", upos="NUM"), M("番", "〜番"), M("人気")])
        self.assertEqual([t[:3] for t in out], [["一番", "一番", "ADV"], ["人気", "人気", "NOUN"]])

    def test_no_join_for_digits_non_headwords_or_other_pos(self):
        sp = ja_spec({"一番": {"ADV"}, "体": {"NOUN"}, "一日": set()})
        for toks in ([M("1", upos="NUM"), M("番", "〜番")],                 # 1番: the counter
                     [M("２", upos="NUM"), M("つ", "〜つ")],                   # digits stay as they are
                     [M("一", upos="NUM"), M("日", "〜日")],                   # 一日 is no headword here
                     [M("から", upos="PART"), M("だ", upos="AUX")]):          # からだ is not 体
            self.assertIs(sp.passage_retag(toks, frozenset()), toks)

    def test_counter_heads_never_join(self):
        sp = ja_spec({"一つ": set()})         # an alt, not a headword with a content group
        out = sp.passage_retag([M("一", upos="NUM"), M("冊", "〜冊")])
        self.assertEqual(len(out), 2)


class PostResolve(unittest.TestCase):
    """passage_post_resolve: passage-only readings."""

    def pr(self, toks, out=None, heads=None):
        sp = ja_spec(heads)
        out = out or [(t[1], t[2]) for t in toks]
        return sp, sp.passage_post_resolve(toks, out)

    def test_te_hoshii_is_grammar(self):
        toks = [M("見", "見る", "VERB"), M("て", upos="PART"), M("ほしい", "欲しい", "ADJ", "形容詞-非自立可能")]
        sp, out = self.pr(toks)
        self.assertEqual(out[2], ("てほしい", "GRAM"))
        self.assertIn(2, sp.passage_uncounted(toks, out))
        # the adjective itself (靴が欲しい) keeps its reading
        toks = [M("靴"), M("が", upos="PART"), M("欲しい", "欲しい", "ADJ", "形容詞-非自立可能")]
        self.assertEqual(self.pr(toks)[1][2], ("欲しい", "ADJ"))

    def test_toiu_before_a_noun_is_grammar(self):
        attr = [M("先生"), M("と", upos="PART"), M("いう", "言う", "VERB", "動詞-一般", conj="連体形-一般"), M("先生")]
        self.assertEqual(self.pr(attr)[1][2], ("という", "GRAM"))
        tte = [M("ハルカ"), M("って", upos="PART"), M("いう", "言う", "VERB", "動詞-一般", conj="連体形-一般"), M("映画")]
        self.assertEqual(self.pr(tte)[1][2], ("という", "GRAM"))
        final = [M("だ", upos="AUX"), M("と", upos="PART"), M("いう", "言う", "VERB", "動詞-一般", conj="終止形-一般"),
                 M("。", upos="PUNCT")]
        self.assertEqual(self.pr(final)[1][2], ("言う", "VERB"))        # hearsay: "they say"
        kanji = [M("と", upos="PART"), M("言う", "言う", "VERB", "動詞-一般", conj="連体形-一般"), M("人")]
        self.assertEqual(self.pr(kanji)[1][1], ("言う", "VERB"))        # と言う人 "people who say"

    def test_mae_after_a_time_amount_is_the_noun(self):
        for pre in ([M("3", upos="NUM"), M("年", "〜年", ctr=True)],
                    [M("400", upos="NUM"), M("年", "〜年", ctr=True), M("以上")],
                    [M("1", upos="NUM"), M("時間", "〜時間", ctr=True)],
                    [M("三", upos="NUM"), M("日", "〜日（か）", ctr=True)],
                    [M("どの", upos="DET"), M("くらい", upos="PART")]):
            toks = pre + [M("前"), M("に", upos="PART"), M("来", "来る", "VERB")]
            out = [(t[1], t[2]) for t in toks]
            out[len(pre)], out[len(pre) + 1] = ("前に", "ADV"), None      # the build's Xに reading
            _, res = self.pr(toks, out)
            self.assertEqual(res[len(pre):len(pre) + 2], [("前", "NOUN"), ("に", "PART")], toks[0][0])

    def test_mae_elsewhere_unchanged(self):
        toks = [M("場所"), M("を", upos="PART"), M("前"), M("に", upos="PART"), M("決め", "決める", "VERB")]
        out = [("場所", "NOUN"), ("を", "PART"), ("前に", "ADV"), None, ("決める", "VERB")]
        sp, res = self.pr(toks, out)
        self.assertEqual(res[2:4], [("前に", "ADV"), None])
        self.assertEqual(sp.passage_phrase_ranges(toks), [(2, 3, 2)])    # one span over 前に

    def test_ni_adverb_is_one_range(self):
        toks = [M("一緒"), M("に", upos="PART"), M("行く", upos="VERB")]
        sp, _ = self.pr(toks, [("一緒に", "ADV"), None, ("行く", "VERB")])
        self.assertEqual(sp.passage_phrase_ranges(toks), [(0, 1, 0)])
        toks2 = [M("駅"), M("の", upos="PART"), M("前"), M("に", upos="PART")]
        sp2, _ = self.pr(toks2, [("駅", "NOUN"), ("の", "PART"), ("前", "NOUN"), ("に", "PART")])
        self.assertEqual(sp2.passage_phrase_ranges(toks2), [])           # 駅の前に: the noun and に

    def test_go_suffix_is_not_ato(self):
        toks = [M("1", upos="NUM"), M("ヶ月", "〜ヶ月", ctr=True), M("後", "", "NUM", "接尾辞-名詞的-副詞可能", read="ゴ"),
                M("に", upos="PART")]
        sp, res = self.pr(toks, [None, ("〜ヶ月", "NOUN"), None, ("に", "PART")])
        self.assertEqual(res[2], ("〜後", "GRAM"))
        self.assertIn(2, sp.passage_uncounted(toks, res))
        self.assertFalse(sp.passage_fallback_ok(None, res[2], {"w": "後"}))
        toks = [M("映画"), M("の", upos="PART"), M("後", read="アト")]
        self.assertEqual(self.pr(toks)[1][2], ("後", "NOUN"))             # 映画の後: あと

    def test_kurai_spelled_i(self):
        toks = [M("どれ", upos="PRON"), M("位", read="クライ")]
        self.assertEqual(self.pr(toks)[1][1], ("くらい", "PART"))
        toks = [M("三", upos="NUM"), M("日", "〜日（か）", ctr=True), M("位", "", "NUM", read="イ")]
        self.assertEqual(self.pr(toks)[1][2], ("くらい", "PART"))
        toks = [M("3", upos="NUM"), M("位", "〜位", read="イ")]
        self.assertEqual(self.pr(toks)[1][1], ("〜位", "NOUN"))           # 3位 "third place"

    def test_conjunction_links_the_pack_adverb(self):
        toks = [M("ただ", upos="CCONJ", pos="接続詞"), M("、", upos="PUNCT")]
        _, res = self.pr(toks, [("ただ", "CONJ"), None], heads={"ただ": {"ADV", "NOUN"}})
        self.assertEqual(res[0], ("ただ", "ADV"))
        _, res = self.pr(toks, [("ただ", "CONJ"), None], heads={"ただ": {"ADV", "CONJ"}})
        self.assertEqual(res[0], ("ただ", "CONJ"))                        # the pack has the conjunction

    def test_kana_word_folded_into_another_is_out_of_pack(self):
        toks = [M("たった", "ただ", "ADV", "副詞", dic="たった")]
        sp, res = self.pr(toks)
        self.assertEqual(res[0], ("たった", "NOWORD"))
        self.assertNotIn(0, sp.passage_uncounted(toks, res))            # counted: an oop word
        self.assertFalse(sp.passage_fallback_ok(None, res[0], {"w": "ただ"}))
        self.assertTrue(sp.passage_fallback_ok(None, ("ただ", "ADV"), {"w": "ただ"}))


if __name__ == "__main__":
    unittest.main()


# ---- readings (Japanese.passage_ruby / text_ruby / _counter_sounds) --------------------
from collections import Counter, defaultdict  # noqa: E402
import re  # noqa: E402

from packbuilder.langs.ja import KANJI_RE, KANA_ONLY_RE  # noqa: E402

try:
    import sudachipy  # noqa: F401
    HAVE_SUDACHI = True
except ImportError:
    HAVE_SUDACHI = False


def rspec(segs=None, readings=None, pack=None):
    """A ja spec whose Sudachi pieces and per-span readings are fixtures."""
    sp = spec()
    sp.stats = Counter()
    if segs is not None:
        sp._passage_segments = lambda text, en: segs[text]
    if readings is not None:
        sp._span_reading = lambda s: readings.get(s, s)
    sp._pack_rd = defaultdict(list, pack or {})
    return sp


def covered(text, ruby):
    """Every kanji of text inside a token (ruby offsets in UTF-16 code units)."""
    cov = set()
    for a, b, _r, _w in ruby:
        cov |= set(range(a, b))
    at = 0
    for ch in text:
        if KANJI_RE.match(ch) and at not in cov:
            return False
        at += 2 if ord(ch) > 0xFFFF else 1
    return True


def u16(t, a, b):
    return t.encode("utf-16-le")[2 * a:2 * b].decode("utf-16-le")


class CounterSounds(unittest.TestCase):
    def run_(self, pieces):
        sp = rspec()
        pieces = [list(p) for p in pieces]
        sp._counter_sounds(pieces)
        return [(b, "".join(r) if r is not None else None) for b, r in pieces]

    def test_kanji_numeral_and_counter(self):
        self.assertEqual(self.run_([["一", ["いち"]], ["杯", ["ばい"]]]), [("一", "いっ"), ("杯", "ぱい")])
        self.assertEqual(self.run_([["一", ["いち"]], ["週間", ["しゅうかん"]]]),
                         [("一", "いっ"), ("週間", "しゅうかん")])
        self.assertEqual(self.run_([["三", ["さん"]], ["階", ["かい"]]]), [("三", "さん"), ("階", "がい")])
        self.assertEqual(self.run_([["三", ["さん"]], ["本", ["ほん"]]]), [("三", "さん"), ("本", "ぼん")])
        self.assertEqual(self.run_([["六", ["ろく"]], ["冊", ["さつ"]]]), [("六", "ろく"), ("冊", "さつ")])
        self.assertEqual(self.run_([["六", ["ろく"]], ["回", ["かい"]]]), [("六", "ろっ"), ("回", "かい")])
        self.assertEqual(self.run_([["十", ["じゅう"]], ["匹", ["ひき"]]]), [("十", "じゅっ"), ("匹", "ぴき")])
        self.assertEqual(self.run_([["一", ["いち"]], ["ヶ月", ["かげつ"]]]), [("一", "いっ"), ("ヶ月", "かげつ")])
        self.assertEqual(self.run_([["六", ["ろく"]], ["ヶ月", ["かげつ"]]]), [("六", "ろっ"), ("ヶ月", "かげつ")])
        self.assertEqual(self.run_([["二十", ["にじゅう"]], ["冊", ["さつ"]]]), [("二十", "にじゅっ"), ("冊", "さつ")])

    def test_digit_keeps_the_digit_counter_changes(self):
        self.assertEqual(self.run_([["1", None], ["杯", ["ばい"]]]), [("1", None), ("杯", "ぱい")])
        self.assertEqual(self.run_([["8", None], ["本", ["ほん"]]]), [("8", None), ("本", "ぽん")])
        self.assertEqual(self.run_([["4", None], ["杯", ["はい"]]]), [("4", None), ("杯", "はい")])

    def test_nan_and_native_tsu(self):
        self.assertEqual(self.run_([["何", ["なん"]], ["本", ["ほん"]]]), [("何", "なん"), ("本", "ぼん")])
        self.assertEqual(self.run_([["四", ["よん"]], ["つ", None]]), [("四", "よっ"), ("つ", None)])
        self.assertEqual(self.run_([["三", ["みっ"]], ["つ", None]]), [("三", "みっ"), ("つ", None)])

    def test_other_counters_untouched(self):
        p = [["五", ["ご"]], ["時", ["じ"]], ["百", ["ひゃく"]], ["人", ["にん"]]]
        self.assertEqual(self.run_(p), [("五", "ご"), ("時", "じ"), ("百", "ひゃく"), ("人", "にん")])


class TextRuby(unittest.TestCase):
    def ruby(self, text, segs, spans, readings=None, ok=lambda w: True, pack=None):
        sp = rspec({text: segs}, readings or {}, pack)
        log = defaultdict(list)
        r = sp.text_ruby(text, "", spans, ok, log)
        prev = 0
        for a, b, rd, _w in r:                      # offsets valid, sorted, readings kana
            self.assertTrue(prev <= a < b <= len(text.encode("utf-16-le")) // 2)
            self.assertTrue(KANA_ONLY_RE.match(rd), rd)
            prev = b
        self.assertTrue(covered(text, r), r)
        return r, log

    def test_okurigana_only_over_the_stem(self):
        r, _ = self.ruby("行く", [(0, 2, "いく")], [(0, 2, "w1")])
        self.assertEqual(r, [[0, 1, "い", "w1"]])
        r, _ = self.ruby("悪かった", [(0, 3, "わるかっ"), (3, 4, None)], [(0, 3, "w2")])
        self.assertEqual(r, [[0, 1, "わる", "w2"]])
        r, _ = self.ruby("働いて", [(0, 2, "はたらい"), (2, 3, None)], [(0, 3, "w3")])
        self.assertEqual(r, [[0, 1, "はたら", "w3"]])

    def test_digit_counter(self):
        r, _ = self.ruby("朝6時に", [(0, 1, "あさ"), (1, 2, None), (2, 3, "じ"), (3, 4, None)],
                         [(0, 1, "w1"), (2, 3, "w2"), (3, 4, "w3")])
        self.assertEqual(r, [[0, 1, "あさ", "w1"], [2, 3, "じ", "w2"]])

    def test_counter_whole_in_one_span_or_cut_at_a_span_edge(self):
        segs = [(0, 1, "いっ"), (1, 3, "しゅうかん")]
        r, _ = self.ruby("一週間", segs, [(0, 3, "w1")])
        self.assertEqual(r, [[0, 3, "いっしゅうかん", "w1"]])
        r, _ = self.ruby("一週間", segs, [(1, 3, "w2")])
        self.assertEqual(r, [[0, 1, "いっ", None], [1, 3, "しゅうかん", "w2"]])

    def test_segment_crossing_a_span_edge_is_split(self):
        # one Sudachi segment 一杯 over two spans: cut where one side's reading fits
        r, log = self.ruby("一杯", [(0, 2, "いっぱい")], [(0, 1, "w1"), (1, 2, "w2")],
                           readings={"一": "いち", "杯": "はい"}, pack={"一": ["いっ"]})
        self.assertEqual(r, [[0, 1, "いっ", "w1"], [1, 2, "ぱい", "w2"]])
        self.assertFalse(log["split"][0][-1])
        # rendaku on the right side (杯 はい ~ ぱい)
        r, log = self.ruby("一杯", [(0, 2, "いっぱい")], [(0, 1, "w1"), (1, 2, "w2")],
                           readings={"一": "いち", "杯": "はい"})
        self.assertEqual(r, [[0, 1, "いっ", "w1"], [1, 2, "ぱい", "w2"]])
        # nothing fits: each side's own reading, logged as the fallback
        r, log = self.ruby("大人", [(0, 2, "おとな")], [(0, 1, "w1"), (1, 2, "w2")],
                           readings={"大": "だい", "人": "じん"})
        self.assertEqual(r, [[0, 1, "だい", "w1"], [1, 2, "じん", "w2"]])
        self.assertTrue(log["split"][0][-1])

    def test_names_and_unlinked_kanji_get_null(self):
        r, _ = self.ruby("田中さんは", [(0, 2, "たなか"), (2, 4, None), (4, 5, None)], [(2, 4, "w59"), (4, 5, "w2")])
        self.assertEqual(r, [[0, 2, "たなか", None]])

    def test_linked_word_reading_after_another_span_not_after_a_name(self):
        words = {"w1": {"w": "外", "pron": "そと"}, "w2": {"w": "毎日", "pron": "まいにち"},
                 "w3": {"w": "城", "pron": "しろ"}}
        segs = {"毎日外で": [(0, 2, "まいにち"), (2, 3, "がい"), (3, 4, None)],
                "松本城": [(0, 2, "まつもと"), (2, 3, "じょう")],
                "外で": [(0, 1, "がい"), (1, 2, None)]}
        sp = rspec(segs, {})
        log = defaultdict(list)
        # 毎日|外: 外 is its own span after the span 毎日: the word's そと
        r = sp.text_ruby("毎日外で", "", [(0, 2, "w2"), (2, 3, "w1")], lambda w: True, log, words)
        self.assertEqual(r, [[0, 2, "まいにち", "w2"], [2, 3, "そと", "w1"]])
        # 松本 (a name, no span) + 城: the suffix reading stays
        r = sp.text_ruby("松本城", "", [(2, 3, "w3")], lambda w: True, log, words)
        self.assertEqual(r, [[0, 2, "まつもと", None], [2, 3, "じょう", "w3"]])
        # at a text start the word's reading wins
        r = sp.text_ruby("外で", "", [(0, 1, "w1")], lambda w: True, log, words)
        self.assertEqual(r, [[0, 1, "そと", "w1"]])

    def test_word_id_only_when_allowed(self):
        r, _ = self.ruby("会社", [(0, 2, "かいしゃ")], [(0, 2, "w1")], ok=lambda w: False)
        self.assertEqual(r, [[0, 2, "かいしゃ", None]])

    def test_kanji_without_a_reading_falls_back_to_sudachi(self):
        r, log = self.ruby("鬱だ", [(0, 1, None), (1, 2, None)], [], readings={"鬱": "うつ"})
        self.assertEqual(r, [[0, 1, "うつ", None]])

    def test_utf16_offsets(self):
        t = "😀会社"
        r, _ = self.ruby(t, [(0, 1, None), (1, 3, "かいしゃ")], [(1, 3, "w1")])
        self.assertEqual(r, [[2, 4, "かいしゃ", "w1"]])
        self.assertEqual(u16(t, 2, 4), "会社")


class StubLinker:
    """lk.tag + lk.links_all for titles, questions and options: one span per
    fixture word found in the text (UTF-16 == code points here)."""
    def __init__(self, words):
        self.words = words

    def tag(self, text, en="", names=frozenset()):
        return [[text, text, "X", ""]]

    def links_all(self, toks, text, en, names=frozenset()):
        spans = []
        for w, wid in self.words.items():
            i = text.find(w)
            if i >= 0:
                spans.append([i, i + len(w), wid])
        return [s[2] for s in spans], [], sorted(spans), set()


class PassageRuby(unittest.TestCase):
    SEGS = {"会社で働きます。": [(0, 2, "かいしゃ"), (2, 3, None), (3, 5, "はたらき"), (5, 8, None)],
            "田中の会社": [(0, 2, "たなか"), (2, 3, None), (3, 5, "かいしゃ")],
            "どこで働きますか。": [(0, 2, None), (2, 3, None), (3, 5, "はたらき"), (5, 9, None)],
            "会社": [(0, 2, "かいしゃ")], "家": [(0, 1, "いえ")], "駅": [(0, 1, "えき")], "店": [(0, 1, "みせ")]}

    def build(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "pack").mkdir()
            (Path(d) / "pack" / "characters.json").write_text(json.dumps(
                [{"id": "c1", "t": "会社", "words": ["w1"]}, {"id": "c2", "t": "働く", "words": ["w2"]},
                 {"id": "c3", "t": "家", "words": ["w3"]}]))
            sp = rspec(self.SEGS, {})
            sp.repo = Path(d)
            ps = [{"id": "p1", "title": "田中の会社",
                   "sentences": [{"t": "会社で働きます。", "en": "x", "words": ["w1", "w2"],
                                  "spans": [[0, 2, "w1"], [3, 5, "w2"]]}],
                   "questions": [{"q": "どこで働きますか。", "en": "Where?", "type": "mc",
                                  "options": ["会社", "家", "駅", "店"]},
                                 {"q": "会社", "type": "tf", "options": None}]}]
            lines = sp.passage_ruby(StubLinker({"会社": "w1", "働き": "w2", "家": "w3", "駅": "w4"}),
                                    ps, [frozenset({"田中"})])
            return ps, lines

    def test_fields(self):
        ps, lines = self.build()
        p = ps[0]
        self.assertEqual(p["sentences"][0]["ruby"], [[0, 2, "かいしゃ", "w1"], [3, 4, "はたら", "w2"]])
        self.assertEqual(p["titleRuby"], [[0, 2, "たなか", None], [3, 5, "かいしゃ", "w1"]])
        q = p["questions"][0]
        self.assertEqual(q["ruby"], [[3, 4, "はたら", "w2"]])
        # 駅 is linked but no characters.json unit's words[0]: null
        self.assertEqual(q["optionsRuby"], [[[0, 2, "かいしゃ", "w1"]], [[0, 1, "いえ", "w3"]],
                                            [[0, 1, "えき", None]], [[0, 1, "みせ", None]]])
        self.assertNotIn("optionsRuby", p["questions"][1])
        self.assertEqual(p["questions"][1]["ruby"], [[0, 2, "かいしゃ", "w1"]])
        self.assertIn("## Readings", lines)
        self.assertTrue(any(ln.startswith("Kanji outside every token: 0") for ln in lines))

    def test_double_build_identical(self):
        a, la = self.build()
        b, lb = self.build()
        self.assertEqual(json.dumps(a, ensure_ascii=False), json.dumps(b, ensure_ascii=False))
        self.assertEqual(la, lb)

    def test_no_characters_stage_no_ruby(self):
        sp = rspec(self.SEGS, {})
        sp.repo = Path("/nonexistent-ja-repo")
        ps = [{"title": "会社", "sentences": [{"t": "会社", "en": "", "spans": []}], "questions": []}]
        self.assertEqual(sp.passage_ruby(StubLinker({}), ps, [frozenset()]), [])
        self.assertNotIn("titleRuby", ps[0])

    def test_hook_called_for_a_spec_passage_ruby(self):
        src = Path(passages.__file__).read_text()
        self.assertIn('spec.passage_ruby(lk, passages, pnames) if hasattr(spec, "passage_ruby")', src)


@unittest.skipUnless(HAVE_SUDACHI, "SudachiPy not installed")
class SudachiReadings(unittest.TestCase):
    def segs(self, text, en=""):
        sp = spec()
        return [(text[a:b], r) for a, b, r in sp._passage_segments(text, en)]

    def test_counters(self):
        s = self.segs("コーヒーも一杯飲みます。")
        self.assertIn(("一", "いっ"), s)
        self.assertIn(("杯", "ぱい"), s)
        s = self.segs("一週間に一度")
        self.assertIn(("一", "いっ"), s)
        self.assertIn(("週間", "しゅうかん"), s)
        s = self.segs("旅行は4日だけでした。")
        self.assertIn(("4日", "よっか"), s)
        sp = spec()
        r = sp.text_ruby("旅行は4日だけ", "", [], lambda w: True, defaultdict(list))
        self.assertIn([3, 5, "よっか", None], r)
        s = self.segs("朝6時に起きます。")
        self.assertIn(("6", None), s)
        self.assertIn(("時", "じ"), s)

    def test_real_text_ruby(self):
        sp = spec()
        log = defaultdict(list)
        t = "悪かったと言わないで、もう一度考えてください。"
        r = sp.text_ruby(t, "", [], lambda w: True, log)
        self.assertTrue(covered(t, r))
        got = {t[a:b]: rd for a, b, rd, _w in r}
        self.assertEqual(got["悪"], "わる")
        self.assertEqual(got["言"], "い")
        self.assertEqual(got["一度"], "いちど")
        self.assertEqual(got["考"], "かんが")
        self.assertFalse(log["fallback"])


JA_PACK = Path(__file__).resolve().parents[4] / "japanese" / "pack"


@unittest.skipUnless((JA_PACK / "passages.json").exists() and (JA_PACK / "characters.json").exists(),
                     "japanese pack not beside vocab-engine")
class RealPack(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ps = json.loads((JA_PACK / "passages.json").read_text())
        cls.word0 = {c["words"][0] for c in json.loads((JA_PACK / "characters.json").read_text())}
        if not any("ruby" in s for p in cls.ps for s in p["sentences"]):
            raise unittest.SkipTest("japanese passages.json has no ruby yet")

    def fields(self):
        for p in self.ps:
            for s in p["sentences"]:
                yield s["t"], s.get("ruby", []), set(s["words"])
            yield p["title"], p["titleRuby"], None
            for q in p["questions"]:
                yield q["q"], q["ruby"], None
                for o, r in zip(q.get("options") or [], q.get("optionsRuby") or []):
                    yield o, r, None
                if q.get("options"):
                    self.assertEqual(len(q["optionsRuby"]), len(q["options"]))

    def test_every_kanji_inside_a_token(self):
        bad = [t for t, r, _ in self.fields() if not covered(t, r)]
        self.assertEqual(bad, [])

    def test_offsets_readings_word_ids(self):
        for t, r, ws in self.fields():
            prev = 0
            for a, b, rd, w in r:
                self.assertTrue(prev <= a < b <= len(t.encode("utf-16-le")) // 2, (t, a, b))
                self.assertTrue(KANJI_RE.search(u16(t, a, b)), (t, a, b))
                self.assertTrue(KANA_ONLY_RE.match(rd), (t, rd))
                self.assertTrue(w is None or (w in self.word0 and (ws is None or w in ws)), (t, w))
                prev = b

    def test_no_token_crosses_a_span_edge(self):
        for p in self.ps:
            for s in p["sentences"]:
                cuts = {x for sp_ in s["spans"] for x in sp_[:2]}
                for a, b, _rd, _w in s.get("ruby", []):
                    self.assertFalse([c for c in cuts if a < c < b], (s["t"], a, b))
