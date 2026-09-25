"""Characters stage data (docs/HSK_MERGE.md ss2.3): ja per-token ruby and
kanji-word units, and the writer's no-hook path for every other language."""
import json
import re
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

from packbuilder.core.pipeline import characters_pack_fields, write_characters
from packbuilder.langs import spec_class
from packbuilder.langs.base import LanguageSpec
from packbuilder.langs.ja import Japanese, KANJI_RE, KANA_ONLY_RE

LANGS = sorted(p.stem for p in (Path(__file__).parent.parent / "langs").glob("*.py")
               if p.stem not in ("__init__", "base"))


def ja():
    sp = Japanese.__new__(Japanese)        # no repo state: only the ruby/unit code runs
    sp.stats = Counter()
    sp._kana_pieces = {}
    sp.bands = [("A1", 1), ("A2", 1), ("B1", 1)]
    return sp


def u16slice(t, a, b):
    return t.encode("utf-16-le")[2 * a:2 * b].decode("utf-16-le")


class Ruby(unittest.TestCase):
    def ruby(self, text, surfaces, segs, where, words=None):
        sp = ja()
        sp._kana_pieces[1] = segs
        rec = {"t": text, "words": words or sorted({w[3] for w in where})}
        return sp, sp.sentence_ruby(1, rec, surfaces, where)

    def check(self, text, ruby):
        prev = 0
        for a, b, rd, wid in ruby:
            self.assertLessEqual(prev, a)
            self.assertLess(a, b)
            prev = b
            self.assertTrue(KANJI_RE.search(u16slice(text, a, b)), (a, b))
            self.assertTrue(KANA_ONLY_RE.match(rd), rd)

    def test_offsets_match_text_and_okurigana_left_out(self):
        text = "明日帰ったら電話します。"
        surfaces = ["明日", "帰っ", "たら", "電話", "し", "ます", "。"]
        segs = [("明日", "あした"), ("帰", "かえ"), ("ったら", None), ("電話", "でんわ"), ("します。", None)]
        where = [("tok", 0, 0, "w1"), ("tok", 1, 1, "w2"), ("tok", 3, 3, "w3"), ("tok", 4, 4, "w4")]
        _, ruby = self.ruby(text, surfaces, segs, where)
        self.assertEqual(ruby, [[0, 2, "あした", "w1"], [2, 3, "かえ", "w2"], [6, 8, "でんわ", "w3"]])
        self.check(text, ruby)

    def test_sudachi_whole_token_reading_is_trimmed(self):
        # a Sudachi segment reads the whole token, kana included: お金 おかね, 行きます いきます
        text = "お金を取りに行きます。"
        surfaces = ["お金", "を", "取り", "に", "行き", "ます", "。"]
        segs = [("お金", "おかね"), ("を", None), ("取り", "とり"), ("に", None), ("行き", "いき"), ("ます。", None)]
        where = [("tok", 0, 0, "w1"), ("tok", 2, 2, "w2"), ("tok", 4, 4, "w3")]
        _, ruby = self.ruby(text, surfaces, segs, where)
        self.assertEqual(ruby, [[1, 2, "かね", "w1"], [3, 4, "と", "w2"], [6, 7, "い", "w3"]])
        self.check(text, ruby)

    def test_segment_across_token_boundary_is_skipped(self):
        # [一人|ひとり] over the tokens 一|人: the reading cannot be cut per token
        text = "一人で来た。"
        surfaces = ["一", "人", "で", "来", "た", "。"]
        segs = [("一人", "ひとり"), ("で", None), ("来", "き"), ("た。", None)]
        where = [("tok", 1, 1, "w1"), ("tok", 3, 3, "w2")]
        sp, ruby = self.ruby(text, surfaces, segs, where)
        self.assertEqual(ruby, [[3, 4, "き", "w2"]])
        self.assertEqual(sp.stats["ruby: tokens skipped (reading crosses a token boundary)"], 1)

    def test_digits_trimmed_and_non_kana_reading_skipped(self):
        text = "３年前、二人。"
        surfaces = ["３年", "前", "、", "二人", "。"]
        # ３年 keeps its digit (さん not written): the ruby covers 年 only;
        # 二人 has no kana reading in the line: skipped
        segs = [("３", None), ("年", "ねん"), ("前", "まえ"), ("、", None), ("二人", None), ("。", None)]
        where = [("tok", 0, 0, "w1"), ("tok", 1, 1, "w2"), ("tok", 3, 3, "w3")]
        sp, ruby = self.ruby(text, surfaces, segs, where)
        self.assertEqual(ruby, [[1, 2, "ねん", "w1"], [2, 3, "まえ", "w2"]])
        self.assertEqual(sp.stats["ruby: tokens skipped (kanji without a reading)"], 1)

    def test_utf16_offsets_after_astral_character(self):
        # 🍎 is two UTF-16 units: offsets after it are JavaScript string indices
        text = "🍎を食べた先生。"
        surfaces = ["🍎", "を", "食べ", "た", "先生", "。"]
        segs = [("🍎を", None), ("食", "た"), ("べた", None), ("先生", "せんせい"), ("。", None)]
        where = [("tok", 2, 2, "w1"), ("tok", 4, 4, "w2")]
        _, ruby = self.ruby(text, surfaces, segs, where)
        self.assertEqual(ruby, [[3, 4, "た", "w1"], [6, 8, "せんせい", "w2"]])
        self.assertEqual(u16slice(text, 6, 8), "先生")
        self.check(text, ruby)

    def test_kana_tokens_dropped_links_and_mismatch(self):
        text = "いつ行く。"
        surfaces = ["いつ", "行く", "。"]
        segs = [("いつ", None), ("行く", "いく"), ("。", None)]
        # いつ has no kanji; w9 is not in the sentence's words (a dropped link)
        where = [("tok", 0, 0, "w1"), ("tok", 1, 1, "w9")]
        _, ruby = self.ruby(text, surfaces, segs, where, words=["w1"])
        self.assertIsNone(ruby)
        sp, ruby = self.ruby(text, ["いつ", "行"], segs, where)
        self.assertIsNone(ruby)         # tokens do not spell the text
        self.assertEqual(sp.stats["ruby: sentences skipped (tokens or kana segments do not spell the text)"], 1)

    def test_chars_records_and_overlap(self):
        text = "日本語です。"
        surfaces = ["日本", "語", "です", "。"]
        segs = [("日本", "にほん"), ("語", "ご"), ("です。", None)]
        where = [("chars", 0, 3, "w1"), ("tok", 1, 1, "w2")]
        sp, ruby = self.ruby(text, surfaces, segs, where)
        self.assertEqual(ruby, [[0, 3, "にほんご", "w1"]])
        self.assertEqual(sp.stats["ruby: tokens skipped (overlaps the previous token's ruby)"], 1)


class Units(unittest.TestCase):
    WORDS = [
        {"id": "w0001", "w": "の", "lv": "A1", "pron": "の"},
        {"id": "w0003", "w": "勉強", "lv": "A2", "pron": "べんきょう"},
        {"id": "w0002", "w": "行く", "lv": "A1", "pron": "いく"},
        {"id": "w0004", "w": "〜年", "lv": "A1", "pron": "〜ねん"},
        {"id": "w0005", "w": "テレビ", "lv": "B1", "pron": "てれび"},
        {"id": "w0006", "w": "経済", "lv": "B1", "pron": "けいざい"},
    ]

    def test_units_contain_kanji_in_level_order(self):
        units = ja().character_units(self.WORDS)
        self.assertEqual([u["t"] for u in units], ["行く", "〜年", "勉強", "経済"])
        # ids follow word ids (w0002 -> c0002), never positions: kana-only words leave gaps
        self.assertEqual([u["id"] for u in units], ["c0002", "c0004", "c0003", "c0006"])
        for u in units:
            self.assertTrue(KANJI_RE.search(u["t"]))
            self.assertTrue(KANA_ONLY_RE.match(u["reading"]))
            self.assertEqual(len(u["words"]), 1)
        self.assertEqual(units[1]["reading"], "ねん")          # 〜 is no part of the reading
        self.assertEqual(units[0], {"id": "c0002", "t": "行く", "words": ["w0002"], "lv": "A1", "reading": "いく"})

    def test_unit_ids_stable_when_words_are_added(self):
        before = {u["t"]: u["id"] for u in ja().character_units(self.WORDS)}
        more = [{"id": "w0007", "w": "食べる", "lv": "A1", "pron": "たべる"}] + self.WORDS
        after = {u["t"]: u["id"] for u in ja().character_units(more)}
        self.assertEqual(after["食べる"], "c0007")
        self.assertEqual({t: after[t] for t in before}, before)

    def test_unit_id_needs_w_digits_word_id(self):
        with self.assertRaises(ValueError):
            ja().character_units([{"id": "x12", "w": "行く", "lv": "A1", "pron": "いく"}])

    def test_config_matches_design(self):
        ch = Japanese.characters
        self.assertEqual(ch["stages"], [{"after": "A2", "levels": ["A1", "A2"]}, {"after": "B1", "levels": ["B1"]}])
        self.assertEqual(ch["learnKinds"], ["charSound", "charRead"])
        self.assertTrue(Japanese.emit_ruby)


class Writer(unittest.TestCase):
    def run_writer(self, spec, sentences, words):
        with tempfile.TemporaryDirectory() as d:
            env = SimpleNamespace(spec=spec, pack=Path(d))
            units = write_characters(env, words, sentences)
            f = Path(d) / "characters.json"
            return units, (json.loads(f.read_text()) if f.exists() else None)

    def test_ruby_cut_to_unit_words(self):
        words = Units.WORDS
        sents = [{"t": "の行く", "words": ["w0001", "w0002"], "ruby": [[1, 2, "い", "w0002"], [0, 1, "x", "w0001"]]},
                 {"t": "テレビ", "words": ["w0005"], "ruby": [[0, 3, "てれび", "w0005"]]}]
        units, on_disk = self.run_writer(ja(), sents, words)
        self.assertEqual(on_disk, units)
        self.assertEqual(sents[0]["ruby"], [[1, 2, "い", "w0002"]])
        self.assertNotIn("ruby", sents[1])

    def test_pron_first_only_with_units(self):
        sp = ja()
        self.assertTrue(Japanese.pron_first)
        self.assertEqual(characters_pack_fields(sp, [{"id": "c0001"}]), {"characters": Japanese.characters, "pronFirst": True})
        self.assertEqual(characters_pack_fields(sp, []), {})

    def test_no_per_character_compose(self):
        # A kanji's reading depends on its word (時: じ in 6時, とき alone), so ja never
        # opts in to per-character span readings (docs/PACK_SCHEMA.md "characters").
        self.assertNotIn("compose", characters_pack_fields(ja(), [{"id": "c0001"}])["characters"])

    def test_no_hook_no_ruby_no_file(self):
        sents = [{"t": "a b", "words": ["w0001"]}]
        before = json.dumps(sents)
        units, on_disk = self.run_writer(LanguageSpec.__new__(LanguageSpec), sents, Units.WORDS)
        self.assertEqual(units, [])
        self.assertIsNone(on_disk)
        self.assertEqual(json.dumps(sents), before)

    def test_other_languages_have_no_hook(self):
        self.assertIn("ja", LANGS)
        for code in LANGS:
            if code == "ja":
                continue
            cls = spec_class(code)
            sp = cls.__new__(cls)
            self.assertFalse(cls.emit_ruby, code)
            self.assertFalse(cls.pron_first, code)
            self.assertEqual(characters_pack_fields(sp, []), {}, code)
            self.assertIsNone(cls.characters, code)
            self.assertIsNone(sp.character_units(Units.WORDS), code)
            self.assertIsNone(sp.sentence_ruby(1, {"t": "x", "words": []}, ["x"], []), code)


if __name__ == "__main__":
    unittest.main()
