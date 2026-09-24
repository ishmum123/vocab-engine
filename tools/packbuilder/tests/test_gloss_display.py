"""core.words.apply_gloss_display: the optional tools/gloss_display.json
("lemma|pos" -> en) replaces the shipped gloss of the matching words.json
entries and nothing else; no file, no change. Stdlib only."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from packbuilder.core.words import apply_gloss_display  # noqa: E402


def words():
    return [{"id": "w0001", "w": "orang", "lemma": "orang", "pos": "noun", "en": "person", "lv": "A1", "rank": 1},
            {"id": "w0002", "w": "salah", "lemma": "salah", "pos": "adj", "en": "wrong", "lv": "A1", "rank": 2},
            {"id": "w0003", "w": "orang", "lemma": "orang", "pos": "verb", "en": "x", "lv": "B1", "rank": 3}]


class GlossDisplay(unittest.TestCase):
    def test_no_file_is_a_no_op(self):
        with tempfile.TemporaryDirectory() as d:
            ws = words()
            self.assertEqual(apply_gloss_display(d, ws), ([], []))
            self.assertEqual(ws, words())

    def test_replaces_en_only_by_lemma_and_pos(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "tools").mkdir()
            (Path(d) / "tools" / "gloss_display.json").write_text(json.dumps({
                "_note": "comment", "orang|noun": "person; (orang tua) parents", "nope|noun": "unused"}))
            ws = words()
            applied, unused = apply_gloss_display(d, ws)
            self.assertEqual(applied, ["orang|noun"])
            self.assertEqual(unused, ["nope|noun"])
            self.assertEqual(ws[0]["en"], "person; (orang tua) parents")
            base = words()
            base[0]["en"] = ws[0]["en"]
            self.assertEqual(ws, base)       # same ids, order, lv, rank; the verb orang untouched


if __name__ == "__main__":
    unittest.main()
