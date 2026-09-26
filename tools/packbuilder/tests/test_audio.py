"""`packbuilder audio` (packbuilder/audio.py, docs/AUDIO.md) against a synthetic repo with a
stub renderer (no Piper, no ffmpeg): URLs and manifest, idempotent reruns, hash keys,
Tatoeba URLs untouched, spoken-text overrides and their stale keys, --check / --prune /
--only / --limit, and the validator clean on the result."""
import datetime
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
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

    def url(self, name, i):
        """The audio URL of item i in a pack file (words/sentences: index; passages: (p, n); script: id)."""
        if name == "passages.json":
            return self.pack(name)[i[0]]["sentences"][i[1]].get("audio")
        if name == "script.json":
            return {u["id"]: u for u in self.pack(name)["units"]}[i].get("audio")
        return self.pack(name)[i].get("audio")

    def manifest(self):
        return json.loads((self.root / "audio" / "manifest.json").read_text())

    def test_first_run_renders_and_links(self):
        rc, stub = self.run_audio()
        self.assertEqual(rc, 0)
        # 3 words + 1 sentence (s2 is Tatoeba) + 2 passage sentences + 1 unit (mute and no-say skipped)
        self.assertEqual(len(stub.calls), 7)
        m = self.manifest()
        self.assertEqual(set(m["files"]), {"w/w1", "w/w2", "w/w3", "s/s1", "p/p1-0", "p/p1-1", "x/xx-te"})
        for i, f in m["files"].items():   # content-addressed: <id>.<sha8>.opus
            self.assertRegex(f, "^" + re.escape(i) + r"\.[0-9a-f]{8}\.opus$")
            self.assertTrue((self.root / "audio" / f).exists())
        self.assertEqual([self.url("words.json", k) for k in range(3)],
                         ["audio/" + m["files"][f"w/w{k}"] for k in (1, 2, 3)])
        self.assertEqual(self.url("sentences.json", 0), "audio/" + m["files"]["s/s1"])
        self.assertEqual(self.url("sentences.json", 1), TATOEBA)
        self.assertEqual([self.url("passages.json", (0, n)) for n in (0, 1)],
                         ["audio/" + m["files"]["p/p1-0"], "audio/" + m["files"]["p/p1-1"]])
        self.assertEqual(self.url("script.json", "xx-te"), "audio/" + m["files"]["x/xx-te"])
        self.assertIsNone(self.url("script.json", "xx-mute"))
        self.assertIsNone(self.url("script.json", "xx-nosay"))
        self.assertEqual(self.pack("pack.json")["audio"], {"voice": "xx-test-medium", "version": 1})
        self.assertEqual((m["voice"], m["version"], m["count"], m["generated"], m["licence"]),
                         ("xx-test-medium", 1, 7, "2026-09-26T12:00:00Z", "CC0"))
        # short items (words, carriers) vs sentences
        self.assertEqual((self.root / "audio" / m["files"]["w/w1"]).read_text(), "1|کتاب")
        self.assertEqual((self.root / "audio" / m["files"]["s/s1"]).read_text(), "0|کتاب من")
        # generated .js regenerated: words.js carries the URL, pack.js the audio key
        self.assertIn(f'"audio":"audio/{m["files"]["w/w1"]}"', (self.root / "pack/words.js").read_text())
        self.assertIn('"audio":{"voice":"xx-test-medium","version":1}', (self.root / "pack/pack.js").read_text())
        self.assertIn(f'"audio":"audio/{m["files"]["p/p1-0"]}"', (self.root / "pack/sentences.js").read_text())

    def test_rerun_is_idempotent(self):
        self.run_audio()
        before = snapshot(self.root)
        rc, stub = self.run_audio()
        self.assertEqual((rc, stub.calls), (0, []))
        self.assertEqual(snapshot(self.root), before)

    def test_rebuild_strip_then_audio_restores_links_with_nothing_rerendered(self):
        """A stale-emitter rebuild (packbuilder build/passages/script) overwrites words.json,
        passages.json and script.json from scratch and knows nothing about recorded audio, so
        it drops every relative `audio` field the builder had written (docs/AUDIO.md: audio
        runs last and re-links from the manifest). Simulate that here by stripping those
        fields directly, leaving the manifest and audio/*.opus files untouched, and check that
        a plain rerun relinks everything with 0 renders -- the manifest's own recovery path."""
        self.run_audio()
        before = self.manifest()

        def strip(name, holders):
            doc = self.pack(name)
            for h in holders(doc):
                if isinstance(h.get("audio"), str) and not audio.ABSOLUTE.match(h["audio"]):
                    del h["audio"]
            (self.root / "pack" / name).write_text(
                json.dumps(doc, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")

        strip("words.json", lambda d: d)
        strip("sentences.json", lambda d: d)   # s2's Tatoeba absolute URL survives (ABSOLUTE guard)
        strip("passages.json", lambda d: [s for p in d for s in (p.get("sentences") or [])])
        doc = self.pack("script.json")
        for u in doc.get("units") or []:
            u.pop("audio", None)
        (self.root / "pack" / "script.json").write_text(
            json.dumps(doc, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
        subprocess.run([sys.executable, str(TOOLS / "jsonify_pack.py"), str(self.root / "pack")],
                       check=True, capture_output=True)

        self.assertIsNone(self.url("words.json", 0))
        self.assertIsNone(self.url("script.json", "xx-te"))

        rc, stub = self.run_audio()
        self.assertEqual((rc, stub.calls), (0, []))              # 0 rendered: nothing was actually lost
        self.assertEqual(self.manifest()["files"], before["files"])
        self.assertEqual([self.url("words.json", k) for k in range(3)],
                         ["audio/" + before["files"][f"w/w{k}"] for k in (1, 2, 3)])
        self.assertEqual(self.url("sentences.json", 0), "audio/" + before["files"]["s/s1"])
        self.assertEqual(self.url("sentences.json", 1), TATOEBA)
        self.assertEqual([self.url("passages.json", (0, n)) for n in (0, 1)],
                         ["audio/" + before["files"]["p/p1-0"], "audio/" + before["files"]["p/p1-1"]])
        self.assertEqual(self.url("script.json", "xx-te"), "audio/" + before["files"]["x/xx-te"])
        self.assertEqual(self.pack("pack.json")["audio"], {"voice": "xx-test-medium", "version": 1})

    def test_version_bump_rerenders_everything(self):
        self.run_audio()
        old = set(self.manifest()["files"].values())
        _, stub = self.run_audio(sp=spec(version=2))
        self.assertEqual(len(stub.calls), 7)
        self.assertEqual(self.pack("pack.json")["audio"]["version"], 2)
        new = set(self.manifest()["files"].values())
        self.assertFalse(old & new)                                   # every clip has a new URL
        self.assertFalse(any((self.root / "audio" / f).exists() for f in old))

    def test_peak_change_rerenders_everything_and_is_recorded(self):
        self.run_audio()
        old = set(self.manifest()["files"].values())
        _, stub = self.run_audio(sp=spec(peak=-3.0))
        self.assertEqual(len(stub.calls), 7)                              # every clip re-keyed
        new = set(self.manifest()["files"].values())
        self.assertFalse(old & new)
        self.assertFalse(any((self.root / "audio" / f).exists() for f in old))
        self.assertEqual(self.manifest()["peak"], -3.0)

    def test_peak_must_not_exceed_0_dbfs(self):
        with self.assertRaises(SystemExit):
            self.run_audio(sp=spec(peak=0.5))

    def test_text_edit_rerenders_only_that_item(self):
        self.run_audio()
        words = self.pack("words.json")
        words[2]["w"] = "گلها"
        (self.root / "pack/words.json").write_text(json.dumps(words, ensure_ascii=False, separators=(",", ":")) + "\n")
        _, stub = self.run_audio()
        self.assertEqual(stub.calls, ["گلها"])

    def test_rerender_gets_a_new_url_and_removes_the_superseded_clip(self):
        # The phase 3 override pass re-renders single items: the service worker caches per URL,
        # so the new clip must live at a new URL or listeners keep hearing the old one.
        self.run_audio()
        old = self.manifest()["files"]["p/p1-0"]
        (self.root / "tools/audio_say.json").write_text(json.dumps(
            {"پارک بزرگ شهر.": "پارکِ بزرگِ شهر."}, ensure_ascii=False))
        _, stub = self.run_audio()
        new = self.manifest()["files"]["p/p1-0"]
        self.assertEqual(stub.calls, ["پارکِ بزرگِ شهر."])
        self.assertNotEqual(old, new)
        self.assertFalse((self.root / "audio" / old).exists())
        self.assertEqual((self.root / "audio" / new).read_text(), "0|پارکِ بزرگِ شهر.")
        self.assertEqual(self.url("passages.json", (0, 0)), "audio/" + new)
        self.assertIn(f'"audio":"audio/{new}"', (self.root / "pack/sentences.js").read_text())

    def test_override_changes_spoken_text_only(self):
        self.run_audio()
        words_text = [w["w"] for w in self.pack("words.json")]
        (self.root / "tools/audio_say.json").write_text(json.dumps(
            {"پارک بزرگ شهر.": "پارکِ بزرگِ شهر.", "کتاب": "کِتاب"}, ensure_ascii=False))
        _, stub = self.run_audio()
        self.assertEqual(sorted(stub.calls), sorted(["پارکِ بزرگِ شهر.", "کِتاب"]))
        self.assertEqual([w["w"] for w in self.pack("words.json")], words_text)   # pack text unchanged
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
        m = self.manifest()
        (self.root / "audio" / m["files"]["w/w2"]).unlink()    # missing + its URL now dangles
        words = self.pack("words.json")[:2]                    # w3 leaves the pack: its clip is an orphan
        (self.root / "pack/words.json").write_text(json.dumps(words, ensure_ascii=False, separators=(",", ":")) + "\n")
        self.log.clear()
        self.assertEqual(self.run_audio(check=True)[0], 1)
        text = "\n".join(self.log)
        self.assertIn("missing: w/w2", text)
        self.assertIn("orphan: w/w3", text)
        self.assertIn(f"dangling URL: w2: audio/{m['files']['w/w2']}", text)

    def test_stale_clip_detected_and_rerendered(self):
        self.run_audio()
        words = self.pack("words.json")
        words[0]["w"] = "کتابها"
        (self.root / "pack/words.json").write_text(json.dumps(words, ensure_ascii=False, separators=(",", ":")) + "\n")
        self.log.clear()
        self.assertEqual(self.run_audio(check=True)[0], 1)
        self.assertIn("stale: w/w1", "\n".join(self.log))
        _, stub = self.run_audio()
        self.assertEqual(stub.calls, ["کتابها"])
        self.assertEqual(self.run_audio(check=True)[0], 0)

    def test_prune_deletes_owned_orphans_only(self):
        self.run_audio()
        m = self.manifest()
        (self.root / "audio/s/hand-made.opus").write_text("mine")   # not in the manifest: never deleted
        words = self.pack("words.json")[:2]
        (self.root / "pack/words.json").write_text(json.dumps(words, ensure_ascii=False, separators=(",", ":")) + "\n")
        self.run_audio()
        self.assertTrue((self.root / "audio" / m["files"]["w/w3"]).exists())   # kept without --prune
        self.log.clear()
        self.run_audio(check=True)
        self.assertIn("note: unowned file (not in the manifest; never deleted): s/hand-made.opus", "\n".join(self.log))
        self.run_audio(prune=True)
        self.assertFalse((self.root / "audio" / m["files"]["w/w3"]).exists())
        self.assertNotIn("w/w3", self.manifest()["files"])
        self.assertTrue((self.root / "audio/s/hand-made.opus").exists())
        self.assertEqual(self.run_audio(check=True)[0], 0)

    def test_foreign_relative_url_is_left_alone(self):
        words = self.pack("words.json")
        words[1]["audio"] = "audio/w/recorded-by-hand.mp3"      # a relative URL the builder did not write
        (self.root / "audio/w").mkdir(parents=True)
        (self.root / "audio/w/recorded-by-hand.mp3").write_text("human")
        (self.root / "pack/words.json").write_text(json.dumps(words, ensure_ascii=False, separators=(",", ":")) + "\n")
        _, stub = self.run_audio()
        self.assertNotIn("خانه", stub.calls)
        self.assertEqual(self.url("words.json", 1), "audio/w/recorded-by-hand.mp3")
        self.assertNotIn("w/w2", self.manifest()["files"])
        self.assertIn("note: foreign URL left alone (not in the manifest): w/w2: audio/w/recorded-by-hand.mp3", "\n".join(self.log))
        self.run_audio(prune=True)
        self.assertTrue((self.root / "audio/w/recorded-by-hand.mp3").exists())
        self.assertEqual(self.url("words.json", 1), "audio/w/recorded-by-hand.mp3")

    def test_lost_manifest_readopts_builder_clips(self):
        self.run_audio()
        files_before = self.manifest()["files"]
        (self.root / "audio/manifest.json").unlink()
        self.log.clear()
        self.assertEqual(self.run_audio(check=True)[0], 1)          # the loss is reported, not hidden
        self.assertIn("unrecorded: w/w1", "\n".join(self.log))
        rc, stub = self.run_audio()
        self.assertEqual((rc, stub.calls), (0, []))                 # sha8 matches: adopted as current
        self.assertEqual(self.manifest()["files"], files_before)
        self.assertEqual(self.pack("pack.json")["audio"], {"voice": "xx-test-medium", "version": 1})
        self.assertEqual(self.url("words.json", 0), "audio/" + files_before["w/w1"])
        self.assertEqual(self.run_audio(check=True)[0], 0)

    def test_lost_manifest_with_changed_text_rerenders(self):
        self.run_audio()
        old = self.manifest()["files"]["w/w1"]
        (self.root / "audio/manifest.json").unlink()
        words = self.pack("words.json")
        words[0]["w"] = "کتابها"
        (self.root / "pack/words.json").write_text(json.dumps(words, ensure_ascii=False, separators=(",", ":")) + "\n")
        _, stub = self.run_audio()
        self.assertEqual(stub.calls, ["کتابها"])                     # adopted, sha8 mismatch: stale
        self.assertFalse((self.root / "audio" / old).exists())
        self.assertNotEqual(self.manifest()["files"]["w/w1"], old)
        self.assertIn("audio", self.pack("pack.json"))
        self.assertEqual(self.run_audio(check=True)[0], 0)

    def test_pack_audio_only_when_complete(self):
        self.run_audio(only=["w"])
        self.assertEqual(self.url("words.json", 0), "audio/" + self.manifest()["files"]["w/w1"])
        self.assertIsNone(self.url("sentences.json", 0))
        self.assertNotIn("audio", self.pack("pack.json"))              # partial: notices stay on
        self.run_audio(limit=2)
        self.assertNotIn("audio", self.pack("pack.json"))
        self.run_audio()
        self.assertIn("audio", self.pack("pack.json"))                 # complete
        words = self.pack("words.json")
        words[0]["w"] = "کتابها"
        (self.root / "pack/words.json").write_text(json.dumps(words, ensure_ascii=False, separators=(",", ":")) + "\n")
        self.run_audio(only=["s"])                                     # w1 stale, not re-rendered
        self.assertNotIn("audio", self.pack("pack.json"))
        self.assertTrue(self.url("words.json", 0).startswith("audio/w/w1."))   # old clip still linked
        self.run_audio()
        self.assertIn("audio", self.pack("pack.json"))

    def test_only_and_limit(self):
        _, stub = self.run_audio(only=["w"])
        self.assertEqual(stub.calls, ["کتاب", "خانه", "گل"])
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

    def test_lost_clip_drops_its_url(self):
        self.run_audio()
        (self.root / "audio" / self.manifest()["files"]["w/w3"]).unlink()
        self.run_audio(limit=0)
        self.assertIsNone(self.url("words.json", 2))
        self.assertEqual(self.url("sentences.json", 1), TATOEBA)
        self.assertNotIn("audio", self.pack("pack.json"))

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


class PiperRendererFfmpegCommand(unittest.TestCase):
    """PiperRenderer.render's ffmpeg invocations, without Piper or a real ffmpeg: a stub voice
    writes silence to the wav, and subprocess.run is stubbed to report peaks so the correction
    loop (docs/AUDIO.md "Encoding": libopus overshoots the PCM peak by a roughly fixed amount
    after decode, so the *encoded* file is re-measured and re-encoded until compliant) and the
    final -af filter can be checked without needing real audio."""

    def render_with_stub_ffmpeg(self, raw_dbfs, overshoot_db=0.0, peak_cfg=-1.0, short=True):
        """Simulates: measuring the raw synth's peak returns `raw_dbfs`; each encode's decoded
        peak comes back as (raw_dbfs + gain applied + overshoot_db), mimicking a codec that adds
        a roughly constant overshoot regardless of level. Returns (encode_cmds, final_gain_str)."""
        renderer = audio.PiperRenderer.__new__(audio.PiperRenderer)
        renderer.cfg = dict(audio.DEFAULTS, voice="xx", version=1, licence="CC0", peak=peak_cfg)
        renderer.SC = lambda **kw: kw

        class FakeVoice:
            def synthesize_wav(self, text, wf, syn_config=None):
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(22050)
                wf.writeframes(b"\x00\x00" * 100)
        renderer.voice = FakeVoice()

        encode_cmds = []
        last_gain = [None]

        def fake_run(cmd, **kw):
            if "volumedetect" in cmd:
                if "pipe:0" in cmd:                      # raw synth measurement
                    dbfs = raw_dbfs
                else:                                     # re-measuring the just-encoded file
                    dbfs = raw_dbfs + last_gain[0] + overshoot_db
                return SimpleNamespace(stderr=f"[Parsed_volumedetect_0] max_volume: {dbfs} dB\n".encode())
            # an encode call: pull its gain out of -af, and actually create the output file so
            # render()'s final tmp.replace(out) has something to rename
            af = cmd[cmd.index("-af") + 1]
            last_gain[0] = float(re.search(r"volume=(-?[\d.]+)dB", af).group(1))
            encode_cmds.append(cmd)
            Path(cmd[-1]).write_bytes(b"")
            return SimpleNamespace(returncode=0)

        with tempfile.TemporaryDirectory() as d, \
             unittest.mock.patch("packbuilder.audio.subprocess.run", side_effect=fake_run):
            out = Path(d) / "clip.opus"
            renderer.render("hello", short, out)
            self.assertTrue(out.exists())
        return encode_cmds

    def test_converges_in_one_pass_with_no_codec_overshoot(self):
        cmds = self.render_with_stub_ffmpeg(raw_dbfs=-6.0, overshoot_db=0.0)
        self.assertEqual(len(cmds), 1)
        af = cmds[-1][cmds[-1].index("-af") + 1]
        self.assertIn("volume=5.00dB", af)                # target -1.0 - raw -6.0 = +5.0 dB
        self.assertIn("adelay=150,apad=pad_dur=0.25", af)  # short-item padding still applied

    def test_corrects_for_codec_overshoot_across_two_passes(self):
        # Reproduces the category this fix addresses: a single pass targeting the raw peak
        # shipped clips up to 0 dBFS because libopus overshoots the PCM peak by ~1 dB on decode
        # (measured on shipped Persian audio 2026-09-26: 25/30 sampled clips above -1.0 dBFS).
        cmds = self.render_with_stub_ffmpeg(raw_dbfs=-6.0, overshoot_db=1.0)
        self.assertEqual(len(cmds), 2)
        first_af = cmds[0][cmds[0].index("-af") + 1]
        second_af = cmds[1][cmds[1].index("-af") + 1]
        self.assertIn("volume=5.00dB", first_af)           # naive gain: overshoots to 0.0 dBFS
        self.assertIn("volume=4.00dB", second_af)          # corrected: lands exactly at -1.0 dBFS

    def test_never_ships_a_clip_above_0_dbfs(self):
        # Already louder than target (the +0.9 dBFS finding this class covers), plus codec
        # overshoot: the correction loop still lands at or under 0 dBFS.
        cmds = self.render_with_stub_ffmpeg(raw_dbfs=0.9, overshoot_db=1.0)
        final_measured = 0.9 + last_gain_of(cmds) + 1.0
        self.assertLessEqual(final_measured, -1.0)
        self.assertLessEqual(final_measured, 0.0)

    def test_sentence_gets_no_padding_filter_but_still_normalises(self):
        cmds = self.render_with_stub_ffmpeg(raw_dbfs=-3.0, overshoot_db=0.0, short=False)
        af = cmds[-1][cmds[-1].index("-af") + 1]
        self.assertNotIn("adelay", af)
        self.assertIn("volume=2.00dB", af)


def last_gain_of(cmds):
    af = cmds[-1][cmds[-1].index("-af") + 1]
    return float(re.search(r"volume=(-?[\d.]+)dB", af).group(1))


if __name__ == "__main__":
    unittest.main()
