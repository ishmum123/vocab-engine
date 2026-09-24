"""Tests for the shared tagging entry point (core.tag.tag_docs / doc_tokens),
its use by passages.Linker, and fold-aware span alignment
(passages.token_offsets with spec.span_fold / span_joiners). Stdlib only.

    python3 -m unittest discover -s tools/packbuilder/tests -t tools     (from vocab-engine/)
"""
import re
import sys
import tempfile
import types
import unittest
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))   # vocab-engine/tools

from packbuilder.core import tag as coretag  # noqa: E402
from packbuilder.langs import get_spec  # noqa: E402
from packbuilder.passages import Linker, token_offsets  # noqa: E402

TMP = tempfile.mkdtemp()


class BlockSpacy:
    """Make `import spacy` raise ImportError inside the block."""

    def __enter__(self):
        self.saved = sys.modules.get("spacy", "absent")
        sys.modules["spacy"] = None
        return self

    def __exit__(self, *a):
        if self.saved == "absent":
            sys.modules.pop("spacy", None)
        else:
            sys.modules["spacy"] = self.saved


class FakeSpacy:
    """A stand-in `spacy` module: load() returns an nlp whose pipe() yields
    docs of fake tokens, recording the call."""

    def __enter__(self):
        self.calls = []
        mod = types.ModuleType("spacy")
        calls = self.calls

        class T:
            def __init__(self, text, space=False):
                self.text, self.lemma_, self.pos_, self.is_space = text, text.lower(), "X", space
                self.morph = types.SimpleNamespace(to_dict=lambda: {"Number": "Sing", "Foo": "Bar"})

        class NLP:
            def pipe(self, texts, batch_size, n_process):
                calls.append(("pipe", list(texts), n_process))
                return [[T(w) for w in t.split(" ")] + [T(" ", space=True)] for t in texts]

        def load(name, exclude):
            calls.append(("load", name, tuple(exclude)))
            return NLP()

        mod.load = load
        self.saved = sys.modules.get("spacy", "absent")
        sys.modules["spacy"] = mod
        return self

    def __exit__(self, *a):
        if self.saved == "absent":
            sys.modules.pop("spacy", None)
        else:
            sys.modules["spacy"] = self.saved


class FakeSpec:
    """The spec surface tag_docs / doc_tokens / Linker.pretag use."""
    homograph_by_translation = False
    word_re = re.compile(r"\w+")
    morph_keep = ("Number",)
    spacy_n_process = 4
    truecase_after = ""
    truecase_after_end = ""

    def __init__(self, tagger, spacy_model=None):
        self.tagger, self.spacy_model = tagger, spacy_model
        self.batches, self.setup = [], 0

    def tag_text(self, t):
        return t

    def setup_nlp(self, nlp):
        self.setup += 1

    def tag_texts(self, texts):
        self.batches.append(list(texts))
        return [[(w, w.lower(), "NOUN", {"Number": "Plur", "Other": "x"}) for w in t.split(" ")] for t in texts]

    def fix_token(self, tok):
        return [tok[0], tok[1] + "*", tok[2], tok[3]]

    def fix_sentence(self, toks, row, doc):
        return toks + [["<" + row[3] + ">", "", "PUNCT", ""]]


class TagDocsDispatch(unittest.TestCase):
    def test_stanza_spec_uses_tag_texts_without_spacy(self):
        sp = FakeSpec("stanza")
        with BlockSpacy():
            docs, fields = coretag.tag_docs(sp, ["a b"])
            toks = [coretag.doc_tokens(sp, d, fields, ["s", "a b", None, "en", None, None]) for d in docs]
        self.assertEqual(sp.batches, [["a b"]])
        self.assertEqual(toks, [[["a", "a*", "NOUN", "Number=Plur"], ["b", "b*", "NOUN", "Number=Plur"],
                                 ["<en>", "", "PUNCT", ""]]])

    def test_spacy_model_none_means_spec_tagger(self):
        sp = FakeSpec("spacy", spacy_model=None)
        with BlockSpacy():
            docs, _ = coretag.tag_docs(sp, ["x"])
        self.assertEqual(sp.batches, [["x"]])

    def test_spacy_spec_uses_spacy(self):
        sp = FakeSpec("spacy", spacy_model="xx_fake_sm")
        with FakeSpacy() as fs:
            docs, fields = coretag.tag_docs(sp, ["A b"], n_process=1)
            toks = [coretag.doc_tokens(sp, d, fields, ["s", "A b", None, "", None, None]) for d in docs]
        self.assertEqual(sp.batches, [])
        self.assertEqual(sp.setup, 1)
        self.assertEqual(fs.calls[0], ("load", "xx_fake_sm", ("parser", "ner")))
        self.assertEqual(fs.calls[1], ("pipe", ["A b"], 1))
        # space tokens dropped, morph kept per morph_keep
        self.assertEqual(toks, [[["A", "a*", "X", "Number=Sing"], ["b", "b*", "X", "Number=Sing"],
                                 ["<>", "", "PUNCT", ""]]])

    def test_spacy_n_process_default_from_spec(self):
        sp = FakeSpec("spacy", spacy_model="xx_fake_sm")
        with FakeSpacy() as fs:
            coretag.tag_docs(sp, ["a"])
        self.assertEqual(fs.calls[1][2], 4)

    def test_real_specs_pick_their_tagger(self):
        for lang in ("fa", "id"):
            sp = get_spec(lang, TMP)
            self.assertEqual((sp.tagger, sp.spacy_model), ("stanza", None), lang)
            sp.tag_texts = lambda texts: [[(t, t, "X", {})] for t in texts]
            with BlockSpacy():
                docs, fields = coretag.tag_docs(sp, ["w"])
                self.assertEqual([list(fields(d)) for d in docs], [[("w", "w", "X", {})]])
        for lang in ("it", "es", "fr", "de", "ru"):
            sp = get_spec(lang, TMP)
            self.assertEqual(sp.tagger, "spacy", lang)
            self.assertTrue(sp.spacy_model, lang)
            sp.setup_nlp = lambda nlp: None     # fr's hook needs real spaCy symbols
            with FakeSpacy() as fs:
                coretag.tag_docs(sp, ["w"], n_process=1)
            self.assertEqual(fs.calls[0][1], sp.spacy_model, lang)


def fake_linker(spec):
    c = {"lexicon": None, "groups": None, "truecase": (Counter(), Counter()), "words": []}
    return Linker(spec, c, {})


class LinkerTagging(unittest.TestCase):
    def test_stanza_linker_never_imports_spacy_and_batches(self):
        sp = FakeSpec("stanza")
        with BlockSpacy():
            lk = fake_linker(sp)
            lk.pretag([("x y", "e1"), ("z", ""), ("x y", "e1")])
            self.assertEqual(lk.tag("x y", "e1"), [["x", "x*", "NOUN", "Number=Plur"], ["y", "y*", "NOUN", "Number=Plur"],
                                                   ["<e1>", "", "PUNCT", ""]])
            self.assertEqual(lk.tag("z"), [["z", "z*", "NOUN", "Number=Plur"], ["<>", "", "PUNCT", ""]])
            lk.tag("new")                   # a miss tags on demand
        self.assertEqual(sp.batches, [["x y", "z"], ["new"]])

    def test_spacy_linker_loads_once_per_batch(self):
        sp = FakeSpec("spacy", spacy_model="xx_fake_sm")
        with FakeSpacy() as fs:
            lk = fake_linker(sp)
            self.assertEqual(fs.calls, [])          # no model load at construction
            lk.pretag([("a", ""), ("b c", "")])
            lk.tag("a")
        self.assertEqual([c[0] for c in fs.calls], ["load", "pipe"])
        self.assertEqual(fs.calls[1][2], 1)          # passages tag in-process


def t(w):
    return [w, w, "X", ""]


class FoldedOffsets(unittest.TestCase):
    """token_offsets with fa's span_fold/span_joiners: fix_token surfaces are
    folded (ZWNJ dropped, Arabic yeh/kaf -> Persian) and tag_text joined
    detached affixes; offsets must still point into the original text."""

    @classmethod
    def setUpClass(cls):
        cls.sp = get_spec("fa", TMP)

    def offs(self, text, words):
        return token_offsets(text, [t(w) for w in words], self.sp.span_fold, self.sp.span_joiners)

    def test_zwnj_folded_surface(self):
        text = "من کتاب‌ها را دارم."
        o = self.offs(text, ["من", "کتابها", "را", "دارم", "."])
        self.assertEqual(text[o[1][0]:o[1][1]], "کتاب‌ها")
        self.assertEqual(text[o[4][0]:o[4][1]], ".")

    def test_arabic_yeh_kaf(self):
        text = "ديروز پدرم يك ماشين خريد."
        o = self.offs(text, ["دیروز", "پدرم", "یک", "ماشین", "خرید", "."])
        self.assertEqual([text[a:b] for a, b in o], ["ديروز", "پدرم", "يك", "ماشين", "خريد", "."])

    def test_detached_prefix_joined_by_tagger(self):
        text = "هر روز به کار می روم."
        o = self.offs(text, ["هر", "روز", "به", "کار", "میروم", "."])
        self.assertEqual(text[o[4][0]:o[4][1]], "می روم")

    def test_at_most_one_joiner(self):
        # a surface may not swallow two spaces: "می رو م" is not the token میروم
        text = "می رو م"
        self.assertEqual(self.offs(text, ["میروم"]), [None])

    def test_zwnj_is_a_word_boundary_letters_are_not(self):
        self.assertFalse("‌".isalnum())
        for ch in "ابپکگیيكءآ":
            self.assertTrue(ch.isalnum(), ch)
        # resync after an unlocated token may not end mid-word (کتاب inside کتابها)
        text = "من کتاب‌ها"
        o = self.offs(text, ["xx", "کتاب"])
        self.assertEqual(o, [None, None])
        # nor start inside one
        text = "دوستم را دیدم"
        o = self.offs(text, ["دوستم", "تم"])
        self.assertIsNone(o[1])

    def test_multichar_fold_rules_inside_a_word(self):
        # fold's "ائ" -> "ای" and word-final "اء" -> "ا" need the whole word
        text = "پائین رفتم."
        o = self.offs(text, ["پایین", "رفتم", "."])
        self.assertEqual([text[a:b] for a, b in o], ["پائین", "رفتم", "."])
        text = "از ابتداء گفتم."
        o = self.offs(text, ["از", "ابتدا", "گفتم", "."])
        self.assertEqual([text[a:b] for a, b in o], ["از", "ابتداء", "گفتم", "."])

    def test_offsets_map_back_across_dropped_chars(self):
        text = "‌من‌ رفتم"
        o = self.offs(text, ["من", "رفتم"])
        self.assertEqual([text[a:b] for a, b in o], ["من", "رفتم"])


class ExactOffsets(unittest.TestCase):
    def test_punctuation_after_unlocated_word(self):
        # an unlocated word no longer blocks the punctuation right after it
        text = "Ciao bello."
        o = token_offsets(text, [t("Ciao"), t("bellissimo"), t(".")])
        self.assertEqual(o, [(0, 4), None, (10, 11)])

    def test_no_fold_is_exact(self):
        self.assertEqual(token_offsets("ديروز", [t("دیروز")]), [None])


if __name__ == "__main__":
    unittest.main()
