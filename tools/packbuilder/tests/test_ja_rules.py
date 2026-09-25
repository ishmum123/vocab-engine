"""Japanese context rules that need no tagger (packbuilder/langs/ja.py)."""
import unittest

from packbuilder.langs.ja import Japanese


def spec():
    return Japanese.__new__(Japanese)       # the rules below read no repo state


class DayCounts(unittest.TestCase):
    def line(self, pieces):
        sp = spec()
        from collections import Counter
        sp.stats = Counter()
        sp._day_counts(pieces)
        return "".join(sp._kana_digits(b, r) for b, r in pieces)

    def test_native_day_counts(self):
        # [3|みっ][日|か]: a digit segment of its own always printed the digit (3かぶん)
        self.assertEqual(self.line([["3", ["みっ"]], ["日", ["か"]], ["分", ["ぶん"]]]), "みっかぶん")
        self.assertEqual(self.line([["２", None], ["日", ["にち"]], ["で", None]]), "ふつかで")
        self.assertEqual(self.line([["６", None], ["月", ["がつ"]], ["１０", None], ["日", ["にち"]]]), "６がつとおか")

    def test_first_of_month_and_one_day(self):
        self.assertEqual(self.line([["７", None], ["月", ["がつ"]], ["１日", ["いちにち"]]]), "７がつついたち")
        self.assertEqual(self.line([["１日", ["ついたち"]], ["に", None]]), "１にちに")

    def test_other_numbers_take_nichi(self):
        self.assertEqual(self.line([["２２", None], ["日", ["にち"]]]), "２２にち")
        self.assertEqual(self.line([["二三", None], ["日", ["にち"]]]), "二三にち")      # "two or three": untouched

    def test_kanji_numbers(self):
        self.assertEqual(Japanese._kanji_int("二十四"), 24)
        self.assertEqual(Japanese._kanji_int("十"), 10)
        self.assertIsNone(Japanese._kanji_int("二三"))


class Minutes(unittest.TestCase):
    def line(self, pieces):
        sp = spec()
        from collections import Counter
        sp.stats = Counter()
        sp._minute_counts(pieces)
        return "".join(sp._kana_digits(b, r) for b, r in pieces)

    def test_minutes(self):
        self.assertEqual([Japanese._minute_reading(n) for n in (1, 2, 10, 45)],
                         ["いっぷん", "にふん", "じゅっぷん", "よんじゅうごふん"])
        self.assertEqual(self.line([["１１", None], ["時", ["じ"]], ["４５", None], ["分", ["ぶん"]], ["の", None]]),
                         "１１じ４５ふんの")

    def test_fraction_and_enough(self):
        self.assertEqual(self.line([["４", None], ["分", ["ぶん"]], ["の", None], ["３", None]]), "４ぶんの３")
        self.assertEqual(self.line([["一", ["いち"]], ["分", ["ぶん"]], ["の", None], ["六十", ["ろくじゅう"]],
                                    ["分", ["ぶん"]], ["の", None], ["一", ["いち"]]]), "いっぷんのろくじゅうぶんのいち")
        self.assertEqual(self.line([["十分", ["じゅうぶん"]], ["な", None]]), "じゅうぶんな")


class OtherKana(unittest.TestCase):
    def test_person_count_in_compound(self):
        sp = spec()
        from collections import Counter
        sp.stats = Counter()
        pieces = [["一", ["いち"]], ["人当たり", ["ひとあたり"]]]
        sp._person_counts(pieces)
        self.assertEqual("".join("".join(r) for _, r in pieces), "ひとりあたり")

    def test_naka_heads(self):
        sp = spec()
        from collections import Counter
        sp.stats = Counter()
        pieces = [["一日", ["いちにち"]], ["中", ["ちゅう"]], ["午前", ["ごぜん"]], ["中", ["じゅう"]]]
        sp._naka(pieces, "")
        self.assertEqual([r[0] for _, r in pieces], ["いちにち", "じゅう", "ごぜん", "ちゅう"])


class Words(unittest.TestCase):
    def test_same_okuri(self):
        self.assertTrue(Japanese._same_okuri("詰まらない", "詰らない"))
        self.assertFalse(Japanese._same_okuri("見えない", "見っともない"))

    def test_en_words(self):
        w = Japanese._en_words("I am playing the guitar; he went there")
        self.assertIn("play", w)
        self.assertIn("go", w)

    def test_fused_unlink(self):
        toks = [["何", "何", "PRON", ""], ["も", "も", "PART", ""], ["かも", "", "PART", ""],
                ["奪っ", "奪う", "VERB", ""]]
        self.assertEqual(spec()._fused_unlink(toks), {0})


if __name__ == "__main__":
    unittest.main()
