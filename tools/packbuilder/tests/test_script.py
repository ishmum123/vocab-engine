"""Script primer emitter (core/script.py, docs/SCRIPT_PRIMER.md ss3 and ss6 check
12): unit counts per language, determinism, every ex word readable by its
unit's set or flagged in the stats, ja ex roman == romaji(pron), and the
validator clean on the shipped sibling packs (skipped when a sibling repo is
absent). Synthetic cases need no sibling repo."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(TOOLS))   # vocab-engine/tools

from packbuilder.core.script import build_script, _prune_syll  # noqa: E402
from packbuilder.core.script_opts import option_counts  # noqa: E402
from packbuilder.core.util import strip_audio  # noqa: E402
from packbuilder.langs import get_spec  # noqa: E402
from packbuilder.langs.ja import romaji  # noqa: E402

SIBLINGS = TOOLS.parents[1]
REPOS = {"ko": "korean", "ru": "russian", "fa": "persian", "ja": "japanese"}
COUNTS = {"ko": {"hangul": (47, 7)}, "ru": {"cyr": (33, 6)}, "fa": {"abjad": (33, 6)},
          "ja": {"hira": (108, 12), "kata": (121, 13)}}


def spec(code):
    return get_spec(code, SIBLINGS / REPOS[code], load=False)


def pack_words(code):
    p = SIBLINGS / REPOS[code] / "pack" / "words.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


class Tables(unittest.TestCase):
    """The hand tables alone: counts, sets contiguous, ids unique, refs resolve."""

    def test_counts_and_refs(self):
        for code, stages in COUNTS.items():
            sp = spec(code)
            units = sp.script_units()
            ids = [u["id"] for u in units]
            self.assertEqual(len(ids), len(set(ids)), code)
            self.assertEqual([s["key"] for s in sp.script["stages"]], list(stages), code)
            for st, (n, nsets) in stages.items():
                us = [u for u in units if u["st"] == st]
                self.assertEqual(len(us), n, (code, st))
                self.assertEqual(sorted({u["set"] for u in us}), list(range(1, nsets + 1)), (code, st))
                sets = [u["set"] for u in us]
                self.assertEqual(sets, sorted(sets), (code, st, "file order is teaching order"))
            for u in units:
                for c in u.get("confuse", []):
                    self.assertIn(c, ids, (code, u["id"]))
                if "base" in u:
                    self.assertIn(u["base"], ids, (code, u["id"]))

    def test_say_one_function(self):
        """say comes from spec.script_say only; silent units have none."""
        for code in COUNTS:
            sp = spec(code)
            for u in sp.script_units():
                say = sp.script_say(u)
                if u.get("sound") is False:
                    self.assertIsNone(say, (code, u["id"]))
                else:
                    self.assertTrue(say, (code, u["id"]))

    def test_ja_kana_scheme(self):
        """ja roman per kana matches romaji(); は/へ/を say avoids the particle readings."""
        sp = spec("ja")
        for u in sp.script_units():
            if u.get("sound") is not False and u["group"] not in ("extended", "small"):
                self.assertEqual(romaji(u["t"]), u["roman"], u["id"])
        by_t = {u["t"]: u for u in sp.script_units()}
        self.assertEqual(sp.script_say(by_t["は"]), "ハ")
        self.assertEqual(sp.script_say(by_t["を"]), "お")
        # small kana are units, taught the set before the first yōon set
        small = by_t["ゃ"]
        self.assertEqual((small["roman"], small["group"]), ("ya", "small"))
        self.assertIn(by_t["や"]["id"], small["confuse"])
        first_yoon = min(u["set"] for u in sp.script_units() if u["st"] == "hira" and u["group"] == "yoon")
        for k in "ゃゅょっ":
            self.assertEqual(by_t[k]["set"], first_yoon - 1, k)
        for k in "ャュョッ":
            self.assertEqual(by_t[k]["set"], first_yoon - 1, k)
        self.assertIs(by_t["っ"].get("sound"), False)
        self.assertNotIn("sound", small)
        self.assertEqual(sp.script_say(small), "や")

    def test_ja_yoon_tokens(self):
        """きゃ names its yōon unit (example only) and is read from き + ゃ."""
        sp = spec("ja")
        toks = sp.script_tokens("きゃく")
        self.assertEqual([t[0] for t in toks], ["ja-kya", "ja-ki", "ja-small-ya", "ja-ku"])
        self.assertEqual(toks[0][3], False)
        self.assertEqual(sp.script_syllables("きゃく"), [("きゃ", ["ja-ki", "ja-small-ya"], "kya", ["ja-kya", "ja-small-ya"]),
                                                  ("キャ", ["ja-kata-ki", "ja-kata-small-ya"], "kya",
                                                   ["ja-kata-kya", "ja-kata-small-ya"])])

    def test_ko_ieung_first(self):
        units = spec("ko").script_units()
        self.assertEqual((units[0]["id"], units[0]["set"]), ("ko-ieung", 1))

    def test_ko_romanize(self):
        from packbuilder.langs.ko import ko_romanize
        for w, r in [("나", "na"), ("우리", "uri"), ("가다", "gada"), ("먹어", "meogeo"), ("빨리", "ppalli"),
                     ("좋아", "joa"), ("있어", "isseo"), ("한국", "hanguk")]:
            self.assertEqual(ko_romanize(w), r, w)


class Synthetic(unittest.TestCase):
    """Tier rules on a hand word list (ru): readable first level first, then the
    second level (flagged), then one unknown unit (flagged); never two unknowns."""

    def words(self):
        W = lambda i, w, lv: {"id": f"w{i:04d}", "w": w, "lv": lv}
        return [W(1, "кот", "A1"), W(2, "там", "A1"), W(3, "мама", "A1"), W(4, "так", "A1"),
                W(5, "вот", "A1"), W(6, "тема", "A2"), W(7, "книга", "A1"), W(8, "кто-то", "A1"),
                W(9, "мост", "A2")]

    def test_tiers(self):
        doc, st = build_script(spec("ru"), self.words())
        by = {u["id"]: u for u in doc["units"]}
        self.assertEqual(by["ru-m"]["ex"], [["w0003", "mama"], ["w0002", "tam"]])  # initial position first
        self.assertEqual(by["ru-ye"]["ex"], [["w0006", "tema"]])                   # second level, flagged
        self.assertIn("ru-ye", st["ex_fallback_second_level"])
        self.assertEqual(by["ru-v"]["ex"], [["w0005", "vot"]])                     # set 2 unit, set-2 word
        self.assertNotIn("ru-v", st["ex_one_unknown_unit"])
        self.assertEqual(by["ru-s"]["ex"], [["w0009", "most"]])                    # only A2 word
        self.assertEqual(by["ru-g"]["ex"], [["w0007", "kniga"]])                   # set 3: н и г taught
        self.assertEqual(by["ru-k"]["ex"], [["w0001", "kot"], ["w0004", "tak"]])   # книга: 3 unknowns at set 1
        self.assertNotIn("ex", by["ru-zh"])
        self.assertIn("ru-zh", st["ex_none"])
        self.assertFalse(any("w0008" in (e[0] for e in u.get("ex", [])) for u in doc["units"]))  # hyphen: never
        doc2, st2 = build_script(spec("ru"), self.words())
        self.assertEqual(json.dumps(doc, ensure_ascii=False), json.dumps(doc2, ensure_ascii=False))

    def test_one_unknown_fallback(self):
        W = lambda i, w: {"id": f"w{i:04d}", "w": w, "lv": "A1"}
        doc, st = build_script(spec("ru"), [W(1, "нам"), W(2, "там")])
        by = {u["id"]: u for u in doc["units"]}
        self.assertEqual(by["ru-a"]["ex"], [["w0002", "tam"]])       # readable beats one-unknown
        self.assertEqual(by["ru-n"]["ex"], [["w0001", "nam"]])       # set 2 н: readable at set 2
        self.assertNotIn("ru-n", st["ex_one_unknown_unit"])
        doc, st = build_script(spec("ru"), [W(1, "нам")])
        by = {u["id"]: u for u in doc["units"]}
        self.assertEqual(by["ru-a"]["ex"], [["w0001", "nam"]])       # н unknown at set 1: flagged
        self.assertIn("ru-a", st["ex_one_unknown_unit"])


class ShippedPacks(unittest.TestCase):
    """Against the sibling repos' shipped words.json (skipped when absent)."""

    def each(self):
        for code in COUNTS:
            words = pack_words(code)
            if words is None:
                continue
            yield code, spec(code), words

    def test_deterministic(self):
        n = 0
        for code, sp, words in self.each():
            a, _ = build_script(sp, words)
            b, _ = build_script(spec(code), json.loads(json.dumps(words)))
            self.assertEqual(json.dumps(a, ensure_ascii=False), json.dumps(b, ensure_ascii=False), code)
            n += 1
        if not n:
            self.skipTest("no sibling packs")

    def test_counts(self):
        for code, sp, words in self.each():
            doc, st = build_script(sp, words)
            self.assertEqual(st["units"], {k: v[0] for k, v in COUNTS[code].items()}, code)
            self.assertEqual(st["sets"], {k: v[1] for k, v in COUNTS[code].items()}, code)

    def test_ex_readable_or_flagged(self):
        for code, sp, words in self.each():
            doc, st = build_script(sp, words)
            by_w = {w["id"]: w for w in words}
            stages = [s["key"] for s in sp.script["stages"]]
            rank = {u["id"]: (stages.index(u["st"]), u["set"]) for u in doc["units"]}
            first, second = sp.level_ids[0], sp.level_ids[1]
            for u in doc["units"]:
                ex = u.get("ex", [])
                if not ex:
                    self.assertIn(u["id"], st["ex_none"], (code, u["id"]))
                for wid, roman in ex:
                    w = by_w[wid]
                    toks = sp.script_tokens(sp.script_text(w))
                    self.assertTrue(any(t[0] == u["id"] and t[1] for t in toks), (code, u["id"], wid))
                    unknown = {t[0] if t[0] else ("?", i) for i, t in enumerate(toks)
                               if (len(t) < 4 or t[3]) and (t[0] is None or rank[t[0]] > rank[u["id"]])}
                    max_unknown, n_levels = sp.script_ex_policy(u)
                    self.assertLessEqual(len(unknown), max_unknown, (code, u["id"], wid))
                    if len(unknown) == 1:
                        self.assertIn(u["id"], st["ex_one_unknown_unit"], (code, u["id"], wid))
                    if len(unknown) == 2:
                        self.assertIn(u["id"], st["ex_two_unknown_units"], (code, u["id"], wid))
                    self.assertIn(w["lv"], sp.level_ids[:n_levels], (code, u["id"], wid))
                    if w["lv"] == second:
                        self.assertIn(u["id"], st["ex_fallback_second_level"], (code, u["id"], wid))
                    elif w["lv"] != first:
                        self.assertEqual(u["st"], "kata", (code, u["id"], wid))
                        self.assertIn(u["id"], st["ex_fallback_third_level"], (code, u["id"], wid))
                    self.assertTrue(roman, (code, u["id"], wid))
                    if code == "ja":
                        self.assertEqual(roman, romaji(w["pron"]), (u["id"], wid))
                    if code == "fa":
                        self.assertEqual(roman, w["pron"], (u["id"], wid))

    def test_every_unit_kind_has_four_options(self):
        """Every unit x kind it can carry (symType aside: typed) gets 4 distinct options
        with every unit of its stage taught, over many shuffles: the Python mirror of
        engine scriptItem (tests/script_app_checks.js "every unit x fitting kind")."""
        n = 0
        for code, sp, words in self.each():
            doc, _ = build_script(sp, words)
            counts = option_counts(doc["units"], words, sp.script.get("tts", True))
            short = {k: v for k, v in counts.items() if v < 4}
            self.assertEqual(short, {}, code)
            if code == "ja":
                kata_compose = [k for k in counts if k[1] == "compose" and k[0].startswith("ja-kata-")]
                self.assertTrue(any(k[0] == "ja-kata-small-yu" for k in kata_compose), kata_compose)
                self.assertTrue(any(k[0] == "ja-kata-nyu" for k in kata_compose), kata_compose)
            n += 1
        if not n:
            self.skipTest("no sibling packs")

    def test_validator_clean_on_shipped(self):
        """The shipped pack/ (written by `packbuilder script`) validates with 0 errors
        and matches what the emitter makes now. `packbuilder script` knows nothing about
        recorded audio (docs/AUDIO.md; `packbuilder audio` runs after it and re-links
        units[].audio from its manifest), so both sides are compared with audio fields
        stripped -- this is a staleness check on the emitter's own output, not a check
        that audio is still linked (packbuilder/tests/test_audio.py covers that)."""
        n = 0
        for code, sp, words in self.each():
            pack = SIBLINGS / REPOS[code] / "pack"
            if not (pack / "script.json").exists():
                continue
            doc, _ = build_script(sp, words)
            shipped = json.loads((pack / "script.json").read_text(encoding="utf-8"))
            self.assertEqual(strip_audio(shipped), strip_audio(doc),
                             f"{code}: pack/script.json is stale (rerun packbuilder script)")
            r = subprocess.run([sys.executable, str(TOOLS / "validate_pack.py"), str(pack)],
                               capture_output=True, text=True)
            # script-primer errors only: another pack file being mid-edit (a stale
            # sentences.js while passages.json changes) is not this emitter's defect
            errs = [ln for ln in (r.stdout + r.stderr).splitlines()
                    if ln.startswith("ERROR") and ("script" in ln or "pack.json" in ln or "pack.js" in ln)]
            self.assertEqual(errs, [], code)
            n += 1
        if not n:
            self.skipTest("no sibling packs with script.json")


class Compose(unittest.TestCase):
    def test_prune_short_stage(self):
        """A stage whose syllables cannot give a compose item 4 options loses them."""
        S = lambda t, r: {"t": t, "parts": [t[0]], "roman": r}
        units = [{"id": "x-a", "st": "a", "syll": [S("ka", "ka"), S("ki", "ki")]},
                 {"id": "x-b", "st": "b", "syll": [S("ma", "ma"), S("mi", "mi"), S("mu", "mu"), S("me", "me")]},
                 {"id": "x-c", "st": "b", "syll": [S("mo", "me")]}]      # same roman as me: never its distractor
        dropped = _prune_syll(units)
        self.assertEqual(units[0]["syll"], [])
        self.assertEqual(len(units[1]["syll"]), 4)
        self.assertEqual(sorted(dropped), [["x-a", "ka"], ["x-a", "ki"]])

    def test_ja_kata_twin(self):
        sp = spec("ja")
        self.assertEqual(sp.script_syllables("しゃしん")[1],
                         ("シャ", ["ja-kata-shi", "ja-kata-small-ya"], "sha", ["ja-kata-sha", "ja-kata-small-ya"]))


class Cli(unittest.TestCase):
    """`python -m packbuilder script` on a copy of a pack: writes only script.json,
    script.js, pack.json and pack.js; a second run is byte-identical."""

    def test_cli_twice(self):
        src = SIBLINGS / "korean" / "pack"
        if not (src / "words.json").exists():
            self.skipTest("no korean pack")
        with tempfile.TemporaryDirectory() as d:
            pack = Path(d) / "pack"
            pack.mkdir()
            for f in ("words.json", "pack.json", "sentences.js"):
                shutil.copy(src / f, pack / f)
            pack_json = json.loads((src / "pack.json").read_text(encoding="utf-8"))
            pack_json.pop("script", None)
            (pack / "pack.json").write_text(json.dumps(pack_json, ensure_ascii=False, indent=2) + "\n")
            sentences_js = (pack / "sentences.js").read_bytes()
            env = {**os.environ, "PYTHONPATH": str(TOOLS)}

            def run():
                r = subprocess.run([sys.executable, "-m", "packbuilder", "script", "--lang", "ko", d],
                                   capture_output=True, text=True, env=env)
                self.assertEqual(r.returncode, 0, r.stderr)
                return {p.name: p.read_bytes() for p in sorted(pack.iterdir())}

            one = run()
            self.assertEqual(sorted(one), ["pack.js", "pack.json", "script.js", "script.json",
                                           "sentences.js", "words.json"])
            self.assertEqual(one["sentences.js"], sentences_js)
            self.assertIn("script", json.loads(one["pack.json"]))
            self.assertEqual(run(), one)


if __name__ == "__main__":
    unittest.main()
