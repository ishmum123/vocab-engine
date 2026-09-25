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
