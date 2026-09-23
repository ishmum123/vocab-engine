"""Tests for the flagged link helpers in core/sentences.py (stdlib only).

    python3 -m unittest discover -s tools/packbuilder/tests -t tools     (from vocab-engine/)
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))   # vocab-engine/tools

from packbuilder.core.sentences import homograph_table, phrase_spans  # noqa: E402
from packbuilder.langs import get_spec  # noqa: E402
from packbuilder.langs.base import LanguageSpec  # noqa: E402


def toks(text):
    out = []
    for w in text.replace(",", " ,").replace(".", " .").split():
        out.append([w, w.lower(), "PUNCT" if w in ",." else "X", ""])
    return out


class PhraseSpans(unittest.TestCase):
    def setUp(self):
        self.sp = get_spec("es", tempfile.mkdtemp())
        self.k2i = {(p, "PHRASE"): f"p_{p}" for p in self.sp.multiword}

    def test_contraction_split_and_article_left_over(self):
        t = toks("A pesar del mal tiempo, salimos.")
        ids, consumed, partial = phrase_spans(t, self.sp, self.k2i)
        self.assertEqual(ids, ["p_a pesar de"])
        self.assertEqual(consumed, {0, 1})            # a, pesar
        self.assertEqual(partial, {2: ["el"]})        # del -> de (phrase) + el

    def test_part_outside_phrase_stays(self):
        t = toks("Por favor toma un descanso por unos días.")
        ids, consumed, partial = phrase_spans(t, self.sp, self.k2i)
        self.assertEqual(ids, ["p_por favor"])
        self.assertEqual(consumed, {0, 1})            # the second "por" is not consumed

    def test_no_match_across_punctuation(self):
        t = toks("Dijo por, favor.")
        self.assertEqual(phrase_spans(t, self.sp, self.k2i)[0], [])

    def test_longest_phrase_first(self):
        t = toks("Muchas gracias.")
        ids, consumed, _ = phrase_spans(t, self.sp, self.k2i)
        self.assertEqual(ids, ["p_muchas gracias"])
        self.assertEqual(consumed, {0, 1})


class HomographTable(unittest.TestCase):
    def test_cues_from_gloss_and_spec(self):
        sp = get_spec("es", tempfile.mkdtemp())
        words = [{"id": "w1", "_key": ("solo", "ADV"), "pos": "adv", "en": "only"},
                 {"id": "w2", "_key": ("solo", "ADJ"), "pos": "adj", "en": "alone, by oneself"},
                 {"id": "w3", "_key": ("casa", "NOUN"), "pos": "noun", "en": "house"}]
        t = homograph_table(words, sp)
        self.assertEqual(set(t), {"solo"})
        cues = dict(t["solo"])
        self.assertIn("just", cues["w1"])              # spec homograph_cues
        self.assertIn("alone", cues["w2"])
        self.assertNotIn("by", cues["w2"])             # stopword


class DefaultsAreOff(unittest.TestCase):
    def test_base_flags_default_off(self):
        sp = LanguageSpec
        self.assertFalse(sp.phrase_token_spans)
        self.assertFalse(sp.homograph_by_translation)
        self.assertFalse(sp.initial_noun_verb_homograph)
        self.assertEqual(sp.closed_surfaces, {})
        self.assertEqual(sp.propn_lowercase_rescue, 0)
        self.assertIsNone(sp.sensitive_re)
        self.assertFalse(sp.prefer_headword_sentence)
        self.assertEqual(sp.derived_form_tags, set())
        self.assertEqual(sp.fallback_rarity_margin, 0)
        self.assertEqual(LanguageSpec.sense_tags(None, ["Mexico"]), ["Mexico"])


class SpanishHooks(unittest.TestCase):
    def setUp(self):
        self.sp = get_spec("es", tempfile.mkdtemp())

    def test_widespread_regional_sense_is_standard(self):
        self.assertEqual(self.sp.sense_tags(["Cuba", "Mexico", "Peru", "feminine"]), ["feminine"])
        self.assertEqual(self.sp.sense_tags(["Philippines", "Spain"]), ["Spain"])
        self.assertEqual(self.sp.sense_tags(["Mexico"]), ["Mexico"])

    def test_translation_gender_mismatch(self):
        lo = [["Lo", "lo", "PRON", ""], ["vi", "ver", "VERB", ""]]
        self.assertTrue(self.sp.translation_mismatch(lo, "I saw her."))
        self.assertFalse(self.sp.translation_mismatch(lo, "I saw him."))
        self.assertFalse(self.sp.translation_mismatch(lo, "I saw it."))

    def test_sensitive(self):
        self.assertTrue(self.sp.sensitive_re.search("He committed suicide."))
        self.assertTrue(self.sp.sensitive_re.search("Te voy a matar."))
        self.assertTrue(self.sp.sensitive_re.search("I want you dead."))
        self.assertFalse(self.sp.sensitive_re.search("Me gustan las matemáticas."))
        self.assertFalse(self.sp.sensitive_re.search("Sussex is in England."))


if __name__ == "__main__":
    unittest.main()
