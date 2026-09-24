"""Passage spans own trailing combining marks (Unicode Mn/Mc) and never start
on one (passages._mark_bounds via make_spans). Stdlib only.

    python3 -m pytest -q tools/packbuilder/tests/test_passage_spans_marks.py     (from vocab-engine/)
"""
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))   # vocab-engine/tools

from packbuilder.passages import _mark_bounds, make_spans, token_offsets  # noqa: E402

FA_FOLD = lambda s: re.sub("[ً-ٰٟ]", "", s)      # noqa: E731  tanwin/harakat off, as fa span_fold


def tok(w):
    return [w, w, "X", ""]


def spans(text, words, fold=None):
    toks = [tok(w) for w in words]
    offs = token_offsets(text, toks, fold)
    recs = [("tok", i, i, f"w{i}") for i, w in enumerate(words) if w.isalpha()]
    return make_spans(text, offs, recs, [r[3] for r in recs])


class Tanwin(unittest.TestCase):
    def test_lotfan_span_covers_tanwin(self):
        text = "لطفاً بنشینید."
        sp = spans(text, ["لطفا", "بنشینید", "."], FA_FOLD)
        self.assertEqual([text[a:b] for a, b, _ in sp], ["لطفاً", "بنشینید"])
        self.assertEqual(sp[0][:2], [0, 5])

    def test_no_span_is_followed_by_a_mark(self):
        text = "او حتماً و تقریباً همیشه قبلاً می‌آمد."
        sp = spans(text, ["او", "حتما", "و", "تقریبا", "همیشه", "قبلا", "می‌آمد", "."], FA_FOLD)
        for a, b, _ in sp:
            self.assertFalse(b < len(text) and re.match("[ً-ٟ]", text[b]), text[a:b])
            self.assertFalse(re.match("[ً-ٟ]", text[a]), text[a:b])

    def test_never_starts_on_a_mark(self):
        text = "لطفاً"
        self.assertEqual(_mark_bounds(text, 4, 5), (5, 5))       # a mark alone: empty, dropped
        self.assertEqual(_mark_bounds(text, 0, 4), (0, 5))


class LatinUnchanged(unittest.TestCase):
    def test_nfc_french_sentence_unchanged(self):
        text = "Il est déjà là, près de l'école."
        words = ["il", "est", "déjà", "là", ",", "près", "de", "l'", "école", "."]
        toks = [tok(w) for w in words]
        offs = token_offsets(text, toks)
        recs = [("tok", i, i, f"w{i}") for i, w in enumerate(words) if w[0].isalpha()]
        sp = make_spans(text, offs, recs, [r[3] for r in recs])
        self.assertEqual(sp, [[a, b, r[3]] for r, (a, b) in zip(recs, (offs[r[1]] for r in recs))])

    def test_cyrillic_unchanged(self):
        text = "Я читаю книгу."
        sp = spans(text, ["я", "читаю", "книгу", "."])
        self.assertEqual([text[a:b] for a, b, _ in sp], ["Я", "читаю", "книгу"])

    def test_nfd_accent_joins_its_word(self):
        text = "Un café noir."
        sp = spans(text, ["un", "cafe", "noir", "."])
        self.assertEqual([text[a:b] for a, b, _ in sp], ["Un", "café", "noir"])


if __name__ == "__main__":
    unittest.main()
