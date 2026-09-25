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


if __name__ == "__main__":
    unittest.main()
