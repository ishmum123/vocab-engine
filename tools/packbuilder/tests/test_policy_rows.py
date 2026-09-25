"""Cross-pack policy: hand-reviewed example rows are exempt from
drop_all_levels (build and check), and the word-level ceiling
(spec.word_ceiling_re) keeps sensitive glosses at the top level. Stdlib only.

    python3 -m pytest -q tools/packbuilder/tests/test_policy_rows.py     (from vocab-engine/)
"""
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))   # vocab-engine/tools

from packbuilder.langs import get_spec  # noqa: E402
from packbuilder.langs.base import LanguageSpec, EXAMPLE_SID_BASE, make_word_ceiling_re  # noqa: E402
from packbuilder.core.sentences import dropped_everywhere  # noqa: E402
from packbuilder.core.words import apply_word_ceiling, assign_levels  # noqa: E402
from packbuilder.qa.check import drop_all_violation, word_ceiling_violation  # noqa: E402

LANGS = ("it", "es", "fr", "de", "ru", "fa", "id", "ko", "ja")
TEXT, EN = "Il giornale parla della prevenzione del suicidio.", "The newspaper talks about suicide prevention."


class ExampleRows(unittest.TestCase):
    def test_reads_tsv(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "tools").mkdir()
            (Path(d) / "tools" / "generated_examples.tsv").write_text(
                "# comment\n\n" + TEXT + "\t" + EN + "\nUno.\tOne.\n", encoding="utf-8")
            rows = LanguageSpec.example_rows(None, SimpleNamespace(repo=Path(d)))
        self.assertEqual(rows, [[EXAMPLE_SID_BASE, TEXT, "", EN, None, None],
                                [EXAMPLE_SID_BASE + 1, "Uno.", "", "One.", None, None]])

    def test_no_file(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(LanguageSpec.example_rows(None, SimpleNamespace(repo=Path(d))), [])

    def test_build_bypass_only_for_example_sids(self):
        sp = get_spec("it", None)
        examples = {EXAMPLE_SID_BASE: [EXAMPLE_SID_BASE, TEXT, "", EN, None, None]}
        self.assertFalse(dropped_everywhere(sp, EXAMPLE_SID_BASE, TEXT, EN, examples))     # example row: kept
        self.assertTrue(dropped_everywhere(sp, 12345, TEXT, EN, examples))                 # corpus row, same text
        self.assertTrue(dropped_everywhere(sp, 90_000_001, TEXT, EN, examples))            # fa-style gen corpus row
        self.assertFalse(dropped_everywhere(sp, 12345, "Mangio una mela.", "I eat an apple.", examples))

    def test_check_bypass_only_for_example_rows(self):
        sp = get_spec("it", None)
        examples = {(TEXT, EN)}
        self.assertFalse(drop_all_violation(sp, {"t": TEXT, "en": EN, "src": "gen"}, examples))
        self.assertTrue(drop_all_violation(sp, {"t": TEXT, "en": EN}, examples))            # not marked gen
        self.assertTrue(drop_all_violation(sp, {"t": TEXT, "en": EN, "src": "gen"}, set()))  # gen, not an example row
        self.assertTrue(drop_all_violation(sp, {"t": "Si è ucciso.", "en": "He killed himself.", "src": "gen"},
                                           examples))


def _spec():
    return SimpleNamespace(bands=[("A1", 600), ("A2", 700), ("B1", 700)], level_ids=["A1", "A2", "B1"],
                           level_floor={}, level_ceiling={}, word_ceiling_re=make_word_ceiling_re())


class WordCeiling(unittest.TestCase):
    def run_ceiling(self, glosses):
        sp = _spec()
        chosen = [(f"k{i}", "NOUN") for i in range(2000)]
        records = {k: {"lemma": k[0], "en": glosses.get(i, f"thing {i}")} for i, k in enumerate(chosen)}
        level_of = assign_levels([], chosen, sp.bands)
        new_chosen, new_level = apply_word_ceiling(records, [], chosen, level_of, sp)
        return chosen, level_of, new_chosen, new_level

    def test_kill_moves_fill_and_light_blue_stay(self):
        chosen, old, _, new = self.run_ceiling({49: "to kill", 50: "to fill", 51: "light-blue"})
        self.assertEqual(old[chosen[49]], "A1")
        self.assertEqual(new[chosen[49]], "B1")       # rank 50 "to kill": top level
        self.assertEqual(new[chosen[50]], "A1")       # "to fill"
        self.assertEqual(new[chosen[51]], "A1")       # "light-blue"
        for lv, n in _spec().bands:                   # band sizes kept
            self.assertEqual(sum(1 for v in new.values() if v == lv), n)
        moved = [k for k in chosen if old[k] != new[k]]
        # only the flagged word and the band-edge words it displaces change level
        self.assertEqual(sorted(moved), sorted([chosen[49], chosen[600], chosen[1300]]))

    def test_no_hit_is_noop(self):
        chosen, old, new_chosen, new = self.run_ceiling({})
        self.assertIs(new_chosen, chosen)
        self.assertEqual(old, new)

    def test_every_spec_has_shared_ceiling(self):
        for code in LANGS:
            rx = get_spec(code, None).word_ceiling_re
            for g in ("to kill", "murder, homicide", "weapon, arms", "blood", "sex", "drug", "drugs (narcotics)",
                      "pistol, handgun", "dead body, corpse"):
                self.assertTrue(rx.search(g), (code, g))
            for g in ("to fill", "light-blue", "skill", "medicine, drug, medication", "to sell", "bloodhound"):
                self.assertFalse(rx.search(g), (code, g))

    def test_check_flags_below_top(self):
        sp = get_spec("it", None)
        self.assertTrue(word_ceiling_violation(sp, {"lv": "A1", "en": "to kill"}))
        self.assertFalse(word_ceiling_violation(sp, {"lv": "B1", "en": "to kill"}))
        self.assertFalse(word_ceiling_violation(sp, {"lv": "A1", "en": "to fill"}))


if __name__ == "__main__":
    unittest.main()
