"""Smoke tests for packbuilder (stdlib only; no spaCy/wordfreq needed).

    python3 -m unittest discover -s tools/packbuilder/tests -t tools     (from vocab-engine/)
    python3 tools/packbuilder/tests/test_spec.py
"""
import importlib
import pkgutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))   # vocab-engine/tools

from packbuilder import langs  # noqa: E402
from packbuilder.langs import get_spec  # noqa: E402
from packbuilder.langs.base import LanguageSpec, parse_forced_file  # noqa: E402
from packbuilder.core.words import assign_levels, assign_ids  # noqa: E402

REQUIRED = ["code", "name_en", "pack_name", "tts", "stt", "tatoeba_code", "tagger_attribution",
            "subtitles_file", "kaikki_file", "sentences_file", "report_title"]


def language_modules():
    return sorted(m.name for m in pkgutil.iter_modules(langs.__path__) if m.name not in ("base",))


class SpecFields(unittest.TestCase):
    def check_spec(self, sp):
        for f in REQUIRED:
            self.assertTrue(getattr(sp, f), f"{sp.code}: {f} is empty")
        # the tagger: a spaCy model, or a Stanza language (fa) whose spec tags the texts itself
        # (a spec with spacy_model None and its own tag_texts is a custom tagger: id)
        self.assertIn(sp.tagger, ("spacy", "stanza"), f"{sp.code}: unknown tagger")
        if sp.tagger == "stanza":
            self.assertTrue(sp.stanza_lang, f"{sp.code}: stanza_lang is empty")
        if not (sp.tagger == "spacy" and sp.spacy_model):
            self.assertIsNot(type(sp).tag_texts, LanguageSpec.tag_texts, f"{sp.code}: no spacy_model and no tag_texts")
            self.assertIsNot(type(sp).tagger_desc, LanguageSpec.tagger_desc, f"{sp.code}: no spacy_model and no tagger_desc")
        for role in ("subtitles_file", "kaikki_file", "sentences_file", "eng_file", "links_file", "audio_file"):
            self.assertIn(getattr(sp, role), sp.sources, f"{sp.code}: {role} has no source url")
        self.assertEqual(set(sp.versions), {"corpus", "tag", "lex"})
        self.assertEqual(set(sp.tagger_attribution), {"source", "licence", "note"})
        self.assertEqual([p[0] for p in sp.placement], sp.level_ids)
        for table in (sp.target_len, sp.min_len):
            self.assertEqual(set(table), set(sp.level_ids))
        if sp.typing is not None:       # null turns typed production off (fa)
            self.assertIn(sp.typing.get("strictFromLevel"), sp.level_ids + [None])
        for w, g in sp.forced_closed:
            self.assertTrue(w and g.isupper(), (w, g))
        for k in sp.fixed_word:
            self.assertIn(k, sp.fixed_gloss, f"fixed word {k} needs a fixed gloss")
        if sp.definite_article:
            self.assertIn(sp.definite_article, sp.article_forms)

    def test_every_language_module(self):
        mods = language_modules()
        self.assertIn("it", mods)
        for code in mods:
            sp = importlib.import_module(f"packbuilder.langs.{code}").SPEC()
            self.assertTrue(issubclass(type(sp), LanguageSpec))
            self.assertEqual(sp.code, code)
            if getattr(sp, "passage_only", False):
                # a passage-only spec (zh: pack built outside the packbuilder)
                # has no build pipeline fields; it needs levels and its linker
                self.assertTrue(sp.level_ids, f"{code}: passage-only spec without level_ids")
                self.assertTrue(hasattr(sp, "passage_linker"), f"{code}: passage-only spec without passage_linker")
                continue
            self.check_spec(sp)

    def test_italian(self):
        sp = get_spec("it")
        self.assertEqual(sp.n_words, 2000)
        self.assertEqual(sp.bands, [("A1", 600), ("A2", 700), ("B1", 700)])
        self.assertEqual(sp.versions, {"corpus": "c2", "tag": "t3", "lex": "l6"})
        self.assertEqual(sp.all_article_forms, {"il", "lo", "la", "l'", "i", "gli", "le", "un", "uno", "una", "un'"})
        self.assertTrue(sp.is_verb_lemma("parlare") and not sp.is_verb_lemma("casa"))
        self.assertEqual(sp.pronominal_base("lamentarsi"), "lamentare")
        self.assertIsNone(sp.pronominal_base("parlare"))
        self.assertEqual(sp.pronominal_form("porre"), "porsi")
        self.assertTrue(sp.is_profane("cazzata") and not sp.is_profane("casa"))
        self.assertEqual(sp.noun_display("zio", "m", False, "uncle"), ("lo zio", "uncle"))
        self.assertEqual(sp.noun_display("acqua", "f", False, "water"), ("l'acqua", "water (f)"))
        self.assertEqual(sp.noun_display("collega", "mf", False, "colleague"), ("il/la collega", "colleague"))
        self.assertEqual(sp.noun_display("soldi", "m", True, "money"), ("i soldi", "money"))
        self.assertEqual(sp.parse_gender("f,m<l:archaic>"), ("f", False))
        self.assertIsNone(sp.check_word({"id": "w1", "pos": "noun", "w": "lo zio", "lemma": "zio", "alt": ["zio"]}))
        self.assertIsNotNone(sp.check_word({"id": "w1", "pos": "noun", "w": "il zio", "lemma": "zio", "alt": ["zio"]}))
        self.assertIsNotNone(sp.check_word({"id": "w1", "pos": "noun", "w": "i libri", "lemma": "libri"}))

    def test_repo_data_files(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "tools").mkdir()
            (Path(d) / "tools" / "forced_a1.txt").write_text("# c\n[NOUN]\ncasa porta  # x\nacqua\n\n[VERB]\nessere\n")
            (Path(d) / "tools" / "gloss_overrides.json").write_text('{"_note": "x", "stare|verb": "to stay"}')
            sp = get_spec("it", d)
            self.assertEqual(sp.a1_core, {"NOUN": ["casa", "porta", "acqua"], "VERB": ["essere"]})
            self.assertEqual(sp.forced[-4:], [("casa", "NOUN"), ("porta", "NOUN"), ("acqua", "NOUN"), ("essere", "VERB")])
            self.assertEqual(sp.forced[:len(sp.forced_closed)], sp.forced_closed)
            self.assertEqual(sp.gloss_overrides, {"stare|verb": "to stay"})
        with self.assertRaises(ValueError):
            parse_forced_file("casa\n[NOUN]\n")

    def test_forced_file_level_annotation(self):
        # word@LEVEL (ur: ماموں@A2) strips the level from the word list and records it
        # separately; a plain word (no @) behaves exactly as before (backwards compatible)
        parsed = parse_forced_file("[NOUN]\ncasa mamma@A2\n[VERB]\nessere@B1\n")
        self.assertEqual(dict(parsed), {"NOUN": ["casa", "mamma"], "VERB": ["essere"]})
        self.assertEqual(parsed.levels, {("mamma", "NOUN"): "A2", ("essere", "VERB"): "B1"})
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "tools").mkdir()
            (Path(d) / "tools" / "forced_a1.txt").write_text("[NOUN]\ncasa mamma@A2\n")
            sp = get_spec("it", d)
            self.assertEqual(sp.a1_core, {"NOUN": ["casa", "mamma"]})
            self.assertEqual(sp.forced_level, {("mamma", "NOUN"): "A2"})
            self.assertIn(("mamma", "NOUN"), sp.forced)


class LevelsAndIds(unittest.TestCase):
    BANDS = [("A1", 4), ("A2", 3), ("B1", 3)]

    def test_levels(self):
        forced = [("f1", "NOUN"), ("f2", "NUM")]
        chosen = [(f"c{i}", "NOUN") for i in range(8)]
        lv = assign_levels(forced, chosen, self.BANDS)
        self.assertEqual([lv[k] for k in forced], ["A1", "A1"])
        # 4 A1 slots - 2 forced = 2 chosen at A1, then 3 A2, then the rest B1
        self.assertEqual([lv[k] for k in chosen], ["A1", "A1", "A2", "A2", "A2", "B1", "B1", "B1"])

    def test_levels_match_legacy_formula(self):
        bands = [("A1", 600), ("A2", 700), ("B1", 700)]
        forced = [(f"f{i}", "X") for i in range(286)]
        chosen = [(f"c{i}", "X") for i in range(1714)]
        lv = assign_levels(forced, chosen, bands)
        a1_rest = 600 - 286
        for i, k in enumerate(chosen):
            self.assertEqual(lv[k], "A1" if i < a1_rest else ("A2" if i < a1_rest + 700 else "B1"))

    def test_levels_more_bands(self):
        bands = [("L1", 2), ("L2", 2), ("L3", 2), ("L4", 1)]
        chosen = [(f"c{i}", "X") for i in range(8)]
        lv = assign_levels([], chosen, bands)
        self.assertEqual([lv[k] for k in chosen], ["L1", "L1", "L2", "L2", "L3", "L3", "L4", "L4"])

    def test_levels_forced_level(self):
        # a forced key with a forced_level entry (ur: ماموں@A2) ships at that level
        # instead of bands[0][0]; it also gives up its A1 slot, and takes an A2 one,
        # so the chosen split shifts accordingly. Omitting forced_level (or an empty
        # dict) reproduces the plain-forced formula exactly (test_levels above).
        forced = [("f1", "NOUN"), ("f2", "NUM")]
        chosen = [(f"c{i}", "NOUN") for i in range(8)]
        lv = assign_levels(forced, chosen, self.BANDS, {("f2", "NUM"): "A2"})
        self.assertEqual([lv[k] for k in forced], ["A1", "A2"])
        # 4 A1 - 1 forced-A1 = 3 chosen at A1; 3 A2 - 1 forced-A2 = 2 chosen at A2; rest B1
        self.assertEqual([lv[k] for k in chosen], ["A1", "A1", "A1", "A2", "A2", "B1", "B1", "B1"])
        self.assertEqual(assign_levels(forced, chosen, self.BANDS, {}), assign_levels(forced, chosen, self.BANDS))

    def test_ids(self):
        words = [{"lemma": "casa", "pos": "noun"}, {"lemma": "casa", "pos": "noun"},
                 {"lemma": "nuovo", "pos": "adj"}, {"lemma": "andare", "pos": "verb"}]
        idmap = {"casa|noun": "w0007", "andare|verb": "w0002", "vecchio|adj": "w1999"}
        reused = assign_ids(words, idmap)
        self.assertEqual(reused, 2)
        # first claimant keeps the frozen id; the duplicate and the new word get
        # fresh ids above the map maximum, in list order
        self.assertEqual([w["id"] for w in words], ["w0007", "w2000", "w2001", "w0002"])

    def test_ids_empty_map(self):
        words = [{"lemma": "a", "pos": "x"}, {"lemma": "b", "pos": "x"}]
        self.assertEqual(assign_ids(words, {}), 0)
        self.assertEqual([w["id"] for w in words], ["w0001", "w0002"])


if __name__ == "__main__":
    unittest.main()
