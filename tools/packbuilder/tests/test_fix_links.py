"""spec.fix_links: sentence-links-only corrections (sentences.json links and
example choice; never the frequency pass). Stdlib only."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))   # vocab-engine/tools

from packbuilder.langs import get_spec  # noqa: E402
from packbuilder.langs.base import LanguageSpec  # noqa: E402

K2I = {("کمکم", "ADV"): "kam", ("کمک", "NOUN"): "help_n", ("کمک کردن", "VERB"): "help_v",
       ("کردن", "VERB"): "kardan"}


def toks(text):
    # tagged tokens carry no ZWNJ (fa tag_text); punctuation split off
    return [[w, w, "PUNCT" if w in ".!؟" else "X", ""] for w in text.replace("‌", "").split()]


def row(text):
    return [1, text, "", "", None, None]


class Default(unittest.TestCase):
    def test_base_is_noop(self):
        links = ["w1", "w2"]
        self.assertIs(LanguageSpec.fix_links(None, row("x"), [], links, {}), links)
        self.assertEqual(LanguageSpec.example_rows(None, None), [])

    def test_other_specs_inherit_noop(self):
        for code in ("it", "es", "fr", "de", "ru", "id", "ko", "ja"):
            self.assertIs(type(get_spec(code, None)).fix_links, LanguageSpec.fix_links, code)


class PersianKamkam(unittest.TestCase):
    def setUp(self):
        self.sp = get_spec("fa", None)

    def fix(self, text, links):
        return self.sp.fix_links(row(text), toks(text), links, K2I)

    def test_after_be_is_help_noun(self):
        self.assertEqual(self.fix("هیچ کس به کمکم نیامد .", ["a", "b", "kam", "c"]), ["a", "b", "help_n", "c"])

    def test_before_kardan_is_compound_and_kardan_absorbed(self):
        self.assertEqual(self.fix("منتظرم تا کسی کمکم کند .", ["a", "kam", "kardan"]), ["a", "help_v"])
        self.assertEqual(self.fix("کمکم کن .", ["kam", "kardan"]), ["help_v"])

    def test_future_aux_and_harakat(self):
        self.assertEqual(self.fix("این کُمکَم نخواهد کرد .", ["a", "kam", "kardan"]), ["a", "help_v"])

    def test_other_kardan_keeps_its_link(self):
        self.assertEqual(self.fix("کمکم کن و کار کن .", ["kam", "kardan"]), ["help_v", "kardan"])

    def test_gradually_untouched(self):
        for text in ("هوا کمکم گرم میشود .", "هوا کم‌کم گرم میشود .", "کم‌کم به خانه رسیدیم ."):
            self.assertEqual(self.fix(text, ["a", "kam", "b"]), ["a", "kam", "b"], text)

    def test_zwnj_written_after_be_stays_gradual(self):
        self.assertEqual(self.fix("به کم‌کم عادت کرد .", ["kam", "kardan"]), ["kam", "kardan"])

    def test_mixed_keeps_gradual_link(self):
        self.assertEqual(self.fix("کمکم هوا سرد شد و او به کمکم آمد .", ["kam", "x"]), ["kam", "help_n", "x"])

    def test_no_kamkam_link_or_word_is_noop(self):
        links = ["a", "b"]
        self.assertIs(self.fix("به کمکم آمد .", links), links)
        self.assertIs(self.fix("او آمد .", links), links)


if __name__ == "__main__":
    unittest.main()
