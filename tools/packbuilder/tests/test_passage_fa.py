"""Tests for the Persian passage-only rules (langs/fa.py): passage_retag
(نه nine/not, در + آن/این + را as the noun, infinitive + clitic as a verb),
passage_post_resolve (a whole pack noun X+ی kept only when the English names
it, marked by fix_sentence on passage rows; a noun+noun compound links its
head). The dictionary, verbs and pack are stubbed. Stdlib only.

    python3 -m pytest -q tools/packbuilder/tests/test_passage_fa.py     (from vocab-engine/)
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))   # vocab-engine/tools

from packbuilder.langs import get_spec  # noqa: E402

TMP = tempfile.mkdtemp()
PACK = {"ماه": {"noun"}, "ماهی": {"noun"}, "گوش": {"noun"}, "گوشی": {"noun"}, "دوست": {"noun"},
        "دوستی": {"noun"}, "ثبت": {"noun"}, "نام": {"noun"}, "در": {"prep", "noun"}, "کردن": {"verb"},
        "هفته": {"noun"}, "سال": {"noun"}, "نفر": {"noun"}}
GLOSS = {"ماهی": "fish", "گوشی": "mobile phone, smartphone", "دوستی": "friendship", "ماه": "month; moon",
         "گوش": "ear", "دوست": "friend"}


def fa_spec():
    sp = get_spec("fa", TMP)
    sp._info_cache = {}
    sp._verb_cache = ({"کردن", "خوردن"}, {})
    sp._p_pack = PACK
    sp._p_gloss = GLOSS
    return sp


def T(text, upos, lemma=None, morph=""):
    return [text, lemma or text, upos, morph]


def row(en):
    return ["passage", "", None, en, None, None]


class Nine(unittest.TestCase):
    def upos(self, toks):
        return [t[2] for t in fa_spec().passage_retag([list(t) for t in toks])]

    def test_not_before_a_unit_with_ezafe_ye(self):
        toks = [T("،", "PUNCT"), T("نه", "NUM"), T("هفتهای", "NOUN", "هفته"), T("یک", "NUM"), T("بار", "NOUN")]
        self.assertEqual(self.upos(toks)[1], "ADV")

    def test_nine_before_a_bare_unit(self):
        for unit in ("سال", "نفر"):
            toks = [T("او", "PRON"), T("نه", "NUM"), T(unit, "NOUN"), T("دارد", "VERB", "داشتن")]
            self.assertEqual(self.upos(toks)[1], "NUM", unit)

    def test_nine_as_a_time_or_range(self):
        self.assertEqual(self.upos([T("ساعت", "NOUN"), T("نه", "NUM")])[1], "NUM")
        toks = [T("از", "ADP"), T("نه", "NUM"), T("تا", "ADP"), T("پنج", "NUM")]
        self.assertEqual(self.upos(toks)[1], "NUM")


class DoorBeforeObject(unittest.TestCase):
    def test_dar_an_ra_is_the_noun(self):
        toks = [T("و", "CCONJ"), T("در", "ADP"), T("آن", "PRON"), T("را", "ADP"), T("ببندید", "VERB", "بستن")]
        out = fa_spec().passage_retag(toks)
        self.assertEqual(out[1][1:3], ["در", "NOUN"])

    def test_dar_as_preposition_stays(self):
        toks = [T("در", "ADP"), T("آن", "PRON"), T("خانه", "NOUN")]
        self.assertEqual(fa_spec().passage_retag(toks)[0][2], "ADP")


class InfinitiveClitic(unittest.TestCase):
    def test_kardanash_is_a_verb(self):
        toks = [T("درست", "ADJ"), T("کردنش", "NOUN", "کردن")]
        self.assertEqual(fa_spec().passage_retag(toks)[1][2], "VERB")

    def test_bare_infinitive_noun_untouched(self):
        toks = [T("کردن", "NOUN", "کردن")]
        self.assertEqual(fa_spec().passage_retag(toks)[0][2], "NOUN")


class WholePackNoun(unittest.TestCase):
    def resolve(self, words, stems, en):
        sp = fa_spec()
        toks = sp.fix_sentence([T(w, "NUM" if w == "یک" else "NOUN") for w in words], row(en), None)
        out = [(s, "NOUN") if s else None for s in stems]
        return sp.passage_post_resolve(toks, out)

    def test_fish_kept_when_the_english_says_fish(self):
        self.assertEqual(self.resolve(["یک", "ماهی"], [None, "ماه"], "Buy a large fish.")[1], ("ماهی", "NOUN"))

    def test_phone_kept_when_the_english_says_phone(self):
        self.assertEqual(self.resolve(["یک", "گوشی"], [None, "گوش"], "How much is a new phone?")[1],
                         ("گوشی", "NOUN"))

    def test_indefinite_friend_is_the_stem(self):
        self.assertEqual(self.resolve(["یک", "دوستی"], [None, "دوست"], "I have a friend there.")[1],
                         ("دوست", "NOUN"))

    def test_mahi_once_a_month_is_the_stem(self):
        self.assertEqual(self.resolve(["ماهی", "یک"], ["ماه", None], "Once a month.")[0], ("ماه", "NOUN"))

    def test_corpus_rows_are_never_marked(self):
        sp = fa_spec()
        toks = sp.fix_sentence([T("ماهی", "NOUN")], ["s1", "", None, "a fish", None, None], None)
        self.assertNotIn("EnGloss", toks[0][3])


class CompoundHead(unittest.TestCase):
    def test_noun_noun_compound_links_its_head(self):
        sp = fa_spec()
        out = sp.passage_post_resolve([T("ثبتنام", "NOUN")], [None])
        self.assertEqual(out[0], ("ثبت", "NOUN"))

    def test_a_pack_word_is_never_split(self):
        sp = fa_spec()
        out = sp.passage_post_resolve([T("دوستی", "NOUN")], [("دوستی", "NOUN")])
        self.assertEqual(out[0], ("دوستی", "NOUN"))


if __name__ == "__main__":
    unittest.main()
