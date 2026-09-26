"""`packbuilder audio` (packbuilder/audio.py, docs/AUDIO.md) against a synthetic repo with a
stub renderer (no Piper, no ffmpeg): URLs and manifest, idempotent reruns, hash keys,
Tatoeba URLs untouched, spoken-text overrides and their stale keys, --check / --prune /
--only / --limit, and the validator clean on the result."""
import datetime
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

TOOLS = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(TOOLS))   # vocab-engine/tools

from packbuilder import audio  # noqa: E402
from packbuilder.langs import get_spec  # noqa: E402

TATOEBA = "https://audio.tatoeba.org/sentences/fas/123.mp3"
T0 = datetime.datetime(2026, 9, 26, 12, 0, tzinfo=datetime.timezone.utc)


class Stub:
    """Writes 'short|spoken' as the clip, so tests can read what was 'said'."""
    def __init__(self):
        self.calls = []

    def render(self, text, short, out):
        self.calls.append(text)
        Path(out).write_text(f"{int(short)}|{text}", encoding="utf-8")


def spec(**kw):
    a = {"voice": "xx-test-medium", "version": 1, "licence": "CC0"}
    a.update(kw)
    return SimpleNamespace(code="xx", AUDIO=a)


def make_repo():
    root = Path(tempfile.mkdtemp(prefix="ve_audio_"))
    pack = root / "pack"
    pack.mkdir()
    (root / "tools").mkdir()
    w = lambda name, obj, indent=False: (pack / name).write_text(  # noqa: E731
        (json.dumps(obj, ensure_ascii=False, indent=2) if indent else
         json.dumps(obj, ensure_ascii=False, separators=(",", ":"))) + "\n", encoding="utf-8")
    w("pack.json", {"key": "xx", "name": "Test", "tts": "fa-IR", "levels": [{"id": "A1", "label": "A1"}],
                    "setSize": 2, "placement": [["A1", 1]]}, indent=True)
    w("words.json", [{"id": "w1", "w": "کتاب", "en": "book", "lv": "A1"},
                     {"id": "w2", "w": "خانه", "en": "house", "lv": "A1"},
                     {"id": "w3", "w": "گل", "en": "flower", "lv": "A1"}])
    w("sentences.json", [{"id": "s1", "t": "کتاب من", "en": "my book", "lv": "A1", "words": ["w1"]},
                         {"id": "s2", "t": "خانه بزرگ", "en": "big house", "lv": "A1", "words": ["w2"],
                          "audio": TATOEBA}])
    w("passages.json", [{"id": "p1", "lv": "A1", "title": "t", "text": "پارک بزرگ شهر. گل.",
                         "sentences": [{"t": "پارک بزرگ شهر.", "en": "a", "words": []},
                                       {"t": "گل.", "en": "b", "words": ["w3"]}],
                         "questions": []}])
    w("script.json", {"units": [{"id": "xx-te", "t": "ت", "say": "تَ"},
                                {"id": "xx-mute", "t": "ـ", "sound": False, "say": "ـ"},
                                {"id": "xx-nosay", "t": "ع"}], "notes": []})
    subprocess.run([sys.executable, str(TOOLS / "jsonify_pack.py"), str(pack)], check=True, capture_output=True)
    return root


def snapshot(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


class AudioBuild(unittest.TestCase):
    def setUp(self):
        self.root = make_repo()
        self.log = []

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def run_audio(self, sp=None, stub=None, **kw):
        stub = stub or Stub()
        rc = audio.run(self.root, sp or spec(), renderer=stub, now=T0, out=self.log.append, **kw)
        return rc, stub

    def pack(self, name):
        return json.loads((self.root / "pack" / name).read_text(encoding="utf-8"))

    def test_first_run_renders_and_links(self):
        rc, stub = self.run_audio()
        self.assertEqual(rc, 0)
        # 3 words + 1 sentence (s2 is Tatoeba) + 2 passage sentences + 1 unit (mute and no-say skipped)
        self.assertEqual(len(stub.calls), 7)
        self.assertEqual([w["audio"] for w in self.pack("words.json")],
                         ["audio/w/w1.opus", "audio/w/w2.opus", "audio/w/w3.opus"])
        s = self.pack("sentences.json")
        self.assertEqual(s[0]["audio"], "audio/s/s1.opus")
        self.assertEqual(s[1]["audio"], TATOEBA)
        ps = self.pack("passages.json")[0]["sentences"]
        self.assertEqual([x["audio"] for x in ps], ["audio/p/p1-0.opus", "audio/p/p1-1.opus"])
        units = {u["id"]: u for u in self.pack("script.json")["units"]}
        self.assertEqual(units["xx-te"]["audio"], "audio/x/xx-te.opus")
        self.assertNotIn("audio", units["xx-mute"])
        self.assertNotIn("audio", units["xx-nosay"])
        self.assertEqual(self.pack("pack.json")["audio"], {"voice": "xx-test-medium", "version": 1})
        m = json.loads((self.root / "audio" / "manifest.json").read_text())
        self.assertEqual((m["voice"], m["version"], m["count"], m["generated"], m["licence"]),
                         ("xx-test-medium", 1, 7, "2026-09-26T12:00:00Z", "CC0"))
        self.assertEqual(set(m["files"]), {"w/w1.opus", "w/w2.opus", "w/w3.opus", "s/s1.opus",
                                           "p/p1-0.opus", "p/p1-1.opus", "x/xx-te.opus"})
        # short items (words, carriers) vs sentences
        self.assertEqual((self.root / "audio/w/w1.opus").read_text(), "1|کتاب")
        self.assertEqual((self.root / "audio/s/s1.opus").read_text(), "0|کتاب من")
        # generated .js regenerated: words.js carries the URL, pack.js the audio key
        self.assertIn('"audio":"audio/w/w1.opus"', (self.root / "pack/words.js").read_text())
        self.assertIn('"audio":{"voice":"xx-test-medium","version":1}', (self.root / "pack/pack.js").read_text())
        self.assertIn('"audio":"audio/p/p1-0.opus"', (self.root / "pack/sentences.js").read_text())

    def test_rerun_is_idempotent(self):
        self.run_audio()
        before = snapshot(self.root)
        rc, stub = self.run_audio()
        self.assertEqual((rc, stub.calls), (0, []))
        self.assertEqual(snapshot(self.root), before)

    def test_version_bump_rerenders_everything(self):
        self.run_audio()
        _, stub = self.run_audio(sp=spec(version=2))
        self.assertEqual(len(stub.calls), 7)
        self.assertEqual(self.pack("pack.json")["audio"]["version"], 2)

    def test_text_edit_rerenders_only_that_item(self):
        self.run_audio()
        words = self.pack("words.json")
        words[2]["w"] = "گلها"
        (self.root / "pack/words.json").write_text(json.dumps(words, ensure_ascii=False, separators=(",", ":")) + "\n")
        _, stub = self.run_audio()
        self.assertEqual(stub.calls, ["گلها"])

    def test_override_changes_spoken_text_only(self):
        self.run_audio()
        words_before = (self.root / "pack/words.json").read_bytes()
        (self.root / "tools/audio_say.json").write_text(json.dumps(
            {"پارک بزرگ شهر.": "پارکِ بزرگِ شهر.", "کتاب": "کِتاب"}, ensure_ascii=False))
        _, stub = self.run_audio()
        self.assertEqual(sorted(stub.calls), sorted(["پارکِ بزرگِ شهر.", "کِتاب"]))
        self.assertEqual((self.root / "audio/p/p1-0.opus").read_text(), "0|پارکِ بزرگِ شهر.")
        self.assertEqual((self.root / "pack/words.json").read_bytes(), words_before)   # pack text unchanged
        self.assertEqual(self.pack("passages.json")[0]["sentences"][0]["t"], "پارک بزرگ شهر.")

    def test_check_flags_stale_override_keys_and_letter_changes(self):
        self.run_audio()
        (self.root / "tools/audio_say.json").write_text(json.dumps(
            {"no such text": "x", "گل": "گلی"}, ensure_ascii=False))
        self.log.clear()
        rc, _ = self.run_audio(check=True)
        self.assertEqual(rc, 1)
        text = "\n".join(self.log)
        self.assertIn("stale override key: no such text", text)
        self.assertIn("override changes letters, not just marks: 'گل'", text)
        self.assertNotIn("stale override key: گل", text)

    def test_override_must_be_a_string(self):
        (self.root / "tools/audio_say.json").write_text(json.dumps({"گل": ""}))
        rc, stub = self.run_audio()
        self.assertEqual((rc, stub.calls), (1, []))

    def test_check_clean_then_missing_orphan_dangling(self):
        self.run_audio()
        before = snapshot(self.root)
        self.assertEqual(self.run_audio(check=True)[0], 0)
        self.assertEqual(snapshot(self.root), before)          # --check writes nothing
        (self.root / "audio/w/w2.opus").unlink()                # missing + its URL now dangles
        (self.root / "audio/s/s99.opus").write_text("old")      # orphan
        self.log.clear()
        self.assertEqual(self.run_audio(check=True)[0], 1)
        text = "\n".join(self.log)
        self.assertIn("missing: w/w2.opus", text)
        self.assertIn("orphan: s/s99.opus", text)
        self.assertIn("dangling URL: w2: audio/w/w2.opus", text)

    def test_stale_clip_detected_and_rerendered(self):
        self.run_audio()
        m = json.loads((self.root / "audio/manifest.json").read_text())
        m["files"]["w/w1.opus"] = "0" * 40
        (self.root / "audio/manifest.json").write_text(json.dumps(m))
        self.log.clear()
        self.assertEqual(self.run_audio(check=True)[0], 1)
        self.assertIn("stale: w/w1.opus", "\n".join(self.log))
        _, stub = self.run_audio()
        self.assertEqual(stub.calls, ["کتاب"])

    def test_prune_deletes_orphans_only_when_asked(self):
        self.run_audio()
        (self.root / "audio/s/s99.opus").write_text("old")
        self.run_audio()
        self.assertTrue((self.root / "audio/s/s99.opus").exists())
        self.run_audio(prune=True)
        self.assertFalse((self.root / "audio/s/s99.opus").exists())
        self.assertEqual(self.run_audio(check=True)[0], 0)

    def test_only_and_limit(self):
        _, stub = self.run_audio(only=["w"])
        self.assertEqual(stub.calls, ["کتاب", "خانه", "گل"])
        self.assertNotIn("audio", self.pack("sentences.json")[0])
        _, stub = self.run_audio(limit=2)
        self.assertEqual(len(stub.calls), 2)
        _, stub = self.run_audio()
        self.assertEqual(len(stub.calls), 2)   # 7 - 3 - 2

    def test_nothing_rendered_is_a_no_op(self):
        before = snapshot(self.root)
        rc, stub = self.run_audio(limit=0)
        self.assertEqual((rc, stub.calls), (0, []))
        self.assertEqual(snapshot(self.root), before)
        self.assertFalse((self.root / "audio").exists())

    def test_missing_clip_drops_its_url(self):
        self.run_audio()
        (self.root / "audio/w/w3.opus").unlink()
        self.run_audio(limit=0)
        self.assertNotIn("audio", self.pack("words.json")[2])
        self.assertEqual(self.pack("sentences.json")[1]["audio"], TATOEBA)

    def test_no_audio_spec(self):
        rc = audio.run(self.root, SimpleNamespace(code="xx"), renderer=Stub(), out=self.log.append)
        self.assertEqual(rc, 2)

    def test_validator_clean_on_output(self):
        self.run_audio()
        r = subprocess.run([sys.executable, str(TOOLS / "validate_pack.py"), str(self.root / "pack")],
                           capture_output=True, text=True)
        # The fixture is not a complete pack (no lessons/script config); only audio rules matter here.
        bad = [ln for ln in r.stdout.splitlines() if ln.startswith(("ERROR", "WARN")) and "audio" in ln]
        self.assertEqual(bad, [], r.stdout)
        self.assertNotIn("out of sync", r.stdout)

    def test_fa_spec_has_audio_config(self):
        cfg = audio.config(get_spec("fa", str(self.root), load=False))
        self.assertEqual((cfg["voice"], cfg["version"], cfg["bitrate"]), ("fa_IR-ganji_adabi-medium", 1, "24k"))


if __name__ == "__main__":
    unittest.main()
