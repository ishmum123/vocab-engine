"""`python -m packbuilder audio --lang <x> --repo <repo>`: recorded audio for a built pack
(docs/AUDIO.md). Renders one clip per word, sentence, passage sentence and script-unit
carrier with the language's offline voice (spec.AUDIO), writes them beside the site page:

    <repo>/audio/w/<wordId>.<sha8>.opus         <repo>/audio/s/<sentenceId>.<sha8>.opus
    <repo>/audio/p/<passageId>-<n>.<sha8>.opus  <repo>/audio/x/<unitId>.<sha8>.opus
    <repo>/audio/manifest.json   voice, version, bitrate, count, generated, licence,
                                 files {item id "w/w0001": its clip file}

<sha8> is the first 8 hex digits of the clip's key, so a re-rendered clip gets a new URL and the
service worker (cache-first per URL) can never serve the superseded one.

then sets each item's `audio` to its relative URL, `pack.json` `audio` to {voice, version},
and regenerates the pack .js files. Items and rules:

- The spoken text is the item's own text (word `w`, sentence `t`, unit `say`), or its override
  from <repo>/tools/audio_say.json ({pack text: spoken text}; ezafe kasre, stress marks). An
  override changes what is spoken only, never the pack text. Keys that match no item are
  stale; `--check` fails on them.
- A clip's key is sha1 of (spoken text, voice, version, synthesis params, codec settings).
  An item whose manifest file carries the current key's sha8 is kept, so reruns are
  idempotent and a text or override edit re-renders only that item (the superseded file is
  deleted). Bump spec.AUDIO version only for voice/codec changes.
- The builder owns only what the manifest lists. An absolute URL (Tatoeba) and a relative URL
  not in the manifest (foreign) are never rendered, changed or removed; files not in the
  manifest are never deleted (--prune deletes owned clips of items no longer in the pack).
  A URL in the builder's own pattern for its item (audio/<kind>/<id>.<8 hex>.opus) whose file
  exists is adopted even when the manifest lacks it (a lost manifest), then judged by its sha8.
- pack.json audio is set only when every wanted clip is current; a partial run (--only,
  --limit: dev use) links what it rendered but leaves pack.audio unset.
- Words and script carriers render slower with silence padding (spec.AUDIO short_*);
  sentences at normal speed.
- Every clip is peak-normalised before Opus encoding: ffmpeg's `volumedetect` measures the raw
  synth's true peak, then `-af volume=<gain>dB` brings it to spec.AUDIO `peak` (default -1.0
  dBFS, never > 0). `peak` is part of the clip key, so changing it re-renders every clip.

Options: --check (report missing / stale / orphan clips, dangling URLs and stale overrides, plus notes
for foreign URLs and unowned files;
write nothing; exit 1 on any), --prune (delete orphan clips), --only w,s,p,x (render only
these kinds), --limit N (render at most N clips this run).
"""
import datetime
import hashlib
import json
import re
import shutil
import subprocess
import sys
import unicodedata
from pathlib import Path

KINDS = ("w", "s", "p", "x")
ABSOLUTE = re.compile(r"^[a-z][a-z0-9+.-]*:", re.I)
DEFAULTS = {"codec": "opus", "bitrate": "24k", "rate": 24000, "short_length_scale": 1.25,
            "short_pad_ms": [150, 250], "length_scale": 1.0, "peak": -1.0}
VOLUME_RE = re.compile(r"max_volume:\s*(-?\d+(?:\.\d+)?) dB")


def config(spec):
    """spec.AUDIO merged over DEFAULTS; None when the language has no audio voice."""
    a = getattr(spec, "AUDIO", None)
    if not a:
        return None
    cfg = dict(DEFAULTS, **a)
    for k in ("voice", "version", "licence"):
        if not cfg.get(k):
            raise SystemExit(f"audio: spec.AUDIO needs {k!r}")
    if cfg["peak"] > 0:
        raise SystemExit("audio: spec.AUDIO peak must be <= 0 dBFS (never boost above 0 dBFS)")
    return cfg


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_like(path, obj):
    """Rewrite a pack JSON in the layout it already has (pack.json indented, data compact)."""
    old = path.read_text(encoding="utf-8")
    txt = (json.dumps(obj, ensure_ascii=False, indent=2) if old.startswith("{\n")
           else json.dumps(obj, ensure_ascii=False, separators=(",", ":"))) + "\n"
    if txt != old:
        path.write_text(txt, encoding="utf-8")
        return True
    return False


def items(pack_dir):
    """Every item that can carry a clip: (kind, name, text, short, holder) where holder is the
    dict whose `audio` the builder owns. Order is file order."""
    out = []
    for w in load_json(pack_dir / "words.json"):
        out.append(("w", w["id"], w["w"], True, w))
    for s in load_json(pack_dir / "sentences.json"):
        out.append(("s", s["id"], s["t"], False, s))
    if (pack_dir / "passages.json").exists():
        for p in load_json(pack_dir / "passages.json"):
            for n, s in enumerate(p.get("sentences") or []):
                out.append(("p", f"{p['id']}-{n}", s["t"], False, s))
    if (pack_dir / "script.json").exists():
        for u in load_json(pack_dir / "script.json").get("units") or []:
            if u.get("say") and u.get("sound", True) is not False:
                out.append(("x", u["id"], u["say"], True, u))
    return out


def bare(s):
    """Text with combining marks (harakat) and joiners removed: an override may add marks only."""
    s = unicodedata.normalize("NFD", s)
    return "".join(ch for ch in s if unicodedata.category(ch) != "Mn" and ch not in "‌‍")


def load_overrides(repo):
    """(overrides, problems): tools/audio_say.json, {} when absent."""
    path = repo / "tools" / "audio_say.json"
    if not path.exists():
        return {}, []
    data = load_json(path)
    probs = []
    if not isinstance(data, dict):
        return {}, ["tools/audio_say.json must be an object {pack text: spoken text}"]
    good = {}
    for k, v in data.items():
        if not (isinstance(v, str) and v.strip()):
            probs.append(f"audio_say.json[{k!r}] must be a non-empty string")
        else:
            good[k] = v
    return good, probs


def override_notes(overrides, texts):
    """Stale keys (no item has that text) and overrides that change letters, not just marks."""
    stale = sorted(k for k in overrides if k not in texts)
    letters = sorted(k for k, v in overrides.items() if bare(k) != bare(v))
    return stale, letters


def clip_key(spoken, short, cfg):
    params = [spoken, cfg["voice"], cfg["version"], cfg["codec"], cfg["bitrate"], cfg["rate"],
              cfg["short_length_scale"] if short else cfg["length_scale"],
              cfg["short_pad_ms"] if short else [0, 0], cfg["peak"]]
    return hashlib.sha1(json.dumps(params, ensure_ascii=False).encode("utf-8")).hexdigest()


class PiperRenderer:
    """Piper (piper-tts) + ffmpeg libopus. Needs `pip install piper-tts` and ffmpeg on PATH;
    the voice .onnx (+ .onnx.json) is read from <repo>/.cache/voices/<voice>.onnx."""

    def __init__(self, repo, cfg):
        try:
            from piper import PiperVoice, SynthesisConfig
        except ImportError:
            raise SystemExit("audio: piper-tts is not installed (pip install -r tools/packbuilder/requirements-audio.txt)")
        if not shutil.which("ffmpeg"):
            raise SystemExit("audio: ffmpeg is not on PATH")
        model = repo / ".cache" / "voices" / f"{cfg['voice']}.onnx"
        if not model.exists():
            raise SystemExit(f"audio: voice model missing: {model} (download it from huggingface.co/rhasspy/piper-voices)")
        self.voice, self.cfg, self.SC = PiperVoice.load(str(model)), cfg, SynthesisConfig

    def render(self, text, short, out):
        import io
        import wave
        cfg = self.cfg
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            self.voice.synthesize_wav(text, wf, syn_config=self.SC(
                length_scale=cfg["short_length_scale"] if short else cfg["length_scale"]))
        wav_bytes = buf.getvalue()
        gain = self.peak_gain(wav_bytes, cfg["peak"])
        pad = cfg["short_pad_ms"] if short else [0, 0]
        filters = []
        if short:
            filters.append(f"adelay={pad[0]},apad=pad_dur={pad[1] / 1000}")
        filters.append(f"volume={gain:.2f}dB")
        af = ["-af", ",".join(filters)]
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "wav", "-i", "pipe:0", *af, "-ac", "1",
                        "-ar", str(cfg["rate"]), "-c:a", "libopus", "-b:a", cfg["bitrate"],
                        "-application", "voip", str(out)], input=wav_bytes, check=True)

    @staticmethod
    def peak_gain(wav_bytes, target_dbfs):
        """Gain (dB) to apply so the clip's true peak lands at `target_dbfs` (<= 0). Measures the
        raw synth's peak with ffmpeg's volumedetect filter; never returns a gain that would push
        the peak above 0 dBFS, since `target_dbfs` itself is validated <= 0 (config())."""
        p = subprocess.run(["ffmpeg", "-v", "info", "-f", "wav", "-i", "pipe:0",
                            "-af", "volumedetect", "-f", "null", "-"],
                           input=wav_bytes, capture_output=True)
        m = VOLUME_RE.search(p.stderr.decode("utf-8", "replace"))
        measured = float(m.group(1)) if m else 0.0
        return target_dbfs - measured


def run(repo, spec, check=False, prune=False, only=None, limit=None, renderer=None, now=None, out=print):
    repo = Path(repo)
    cfg = config(spec)
    if cfg is None:
        out(f"audio: language {getattr(spec, 'code', '?')!r} has no spec.AUDIO voice")
        return 2
    pack_dir, adir = repo / "pack", repo / "audio"
    mpath = adir / "manifest.json"
    manifest = load_json(mpath) if mpath.exists() else {}
    # owned: item id ("w/w0001") -> its current clip file ("w/w0001.1a2b3c4d.opus"). Only files
    # listed here are the builder's: it never deletes or relinks anything else.
    owned = dict(manifest.get("files") or {})
    owned_files = set(owned.values())
    overrides, problems = load_overrides(repo)
    its = items(pack_dir)
    stale_ov, letter_ov = override_notes(overrides, {t for _, _, t, _, _ in its})

    want, foreign, adopted = {}, [], []   # want: id -> (file, spoken, short, holder)
    for kind, name, text, short, holder in its:
        url = holder.get("audio")
        if isinstance(url, str) and ABSOLUTE.match(url):
            continue                                   # Tatoeba or other remote clip: never touched
        # A URL in the builder's own pattern for this very item whose file exists, but that the
        # manifest does not list (manifest lost or hand-edited): adopt it as owned. Its sha8 is
        # then checked against the current key like any owned clip (match: current; else stale,
        # re-rendered under a new name).
        own = f"{kind}/{name}"
        if (isinstance(url, str) and url[len("audio/"):] not in owned_files
                and re.fullmatch(r"audio/" + re.escape(own) + r"\.[0-9a-f]{8}\.opus", url)
                and (repo / url).is_file() and own not in owned):
            owned[own] = url[len("audio/"):]
            owned_files.add(owned[own])
            adopted.append(own)
        if isinstance(url, str) and not (url.startswith("audio/") and url[len("audio/"):] in owned_files):
            foreign.append(f"{kind}/{name}: {url}")    # a relative URL the builder did not write
            continue
        spoken = overrides.get(text, text)
        key = clip_key(spoken, short, cfg)
        want[f"{kind}/{name}"] = (f"{kind}/{name}.{key[:8]}.opus", spoken, short, holder)

    def current(i):
        return owned.get(i) == want[i][0] and (adir / want[i][0]).exists()

    def status():
        stale = sorted(i for i in want if not current(i) and i in owned and (adir / owned[i]).exists())
        missing = sorted(i for i in want if not current(i) and i not in stale)
        return missing, stale

    missing, stale = status()
    orphans = sorted(i for i in owned if i not in want)
    on_disk = {p.relative_to(adir).as_posix() for k in KINDS if (adir / k).is_dir()
               for p in (adir / k).glob("*.opus")}
    unowned = sorted(on_disk - owned_files)
    dangling = sorted(f"{name}: {h['audio']}" for _, name, _, _, h in its
                      if isinstance(h.get("audio"), str) and not ABSOLUTE.match(h["audio"])
                      and not (repo / h["audio"]).exists())

    if check:
        for label, xs in (("missing", missing), ("stale", stale), ("orphan", orphans),
                          ("dangling URL", dangling), ("stale override key", stale_ov),
                          ("override problem", problems)):
            for x in xs[:20]:
                out(f"{label}: {x}")
            if len(xs) > 20:
                out(f"{label}: ... {len(xs) - 20} more")
        for label, xs in (("note: foreign URL (not in the manifest; left alone)", foreign),
                          ("note: unowned file (not in the manifest; never deleted)", unowned),
                          ("note: override changes letters, not just marks", [repr(k) for k in letter_ov])):
            for x in xs[:20]:
                out(f"{label}: {x}")
        for x in adopted[:20]:
            out(f"unrecorded: {x} (clip in the builder's pattern but not in the manifest; the next run adopts it)")
        bad = sum(map(len, (missing, stale, orphans, dangling, stale_ov, problems, adopted)))
        out(f"audio --check: {len(want)} clips wanted, {len(missing)} missing, {len(stale)} stale, "
            f"{len(orphans)} orphan, {len(dangling)} dangling URLs, {len(stale_ov)} stale override keys, "
            f"{len(foreign)} foreign URLs, {len(unowned)} unowned files, {len(adopted)} unrecorded")
        return 1 if bad else 0

    if problems:
        for p in problems:
            out(p)
        return 1
    for k in stale_ov:
        out(f"warning: stale override key (no item has this text): {k!r}")
    for f in foreign[:20]:
        out(f"note: foreign URL left alone (not in the manifest): {f}")
    if adopted:
        out(f"note: adopted {len(adopted)} clips missing from the manifest (builder's own URL pattern, file present)")

    kinds = set(only) if only else set(KINDS)
    todo = [i for i in want if i.split("/")[0] in kinds and not current(i)]
    if limit is not None:
        todo = todo[:limit]
    if todo and renderer is None:
        renderer = PiperRenderer(repo, cfg)
    for i in todo:
        file, spoken, short, _ = want[i]
        dst = adir / file
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.parent / (".tmp-" + dst.name)
        renderer.render(spoken, short, tmp)
        tmp.replace(dst)
        old = owned.get(i)
        if old and old != file and (adir / old).exists():
            (adir / old).unlink()                      # superseded clip: a new name, so no stale cache
        owned[i] = file
    pruned = 0
    if prune:
        for i in orphans:
            if (adir / owned[i]).exists():
                (adir / owned[i]).unlink()
            del owned[i]
            pruned += 1
    owned = {i: f for i, f in owned.items() if (adir / f).exists()}

    # URLs: each wanted item links its owned clip (current, or stale until re-rendered).
    for i, (_, _, _, holder) in want.items():
        if i in owned:
            holder["audio"] = f"audio/{owned[i]}"
        else:
            holder.pop("audio", None)
    missing_after, stale_after = status()
    complete = bool(owned) and not missing_after and not stale_after

    changed = False
    files_sorted = dict(sorted(owned.items()))
    if (owned or mpath.exists()) and (todo or pruned or adopted or not mpath.exists() or manifest.get("files") != files_sorted
                                      or manifest.get("version") != cfg["version"] or manifest.get("voice") != cfg["voice"]):
        adir.mkdir(parents=True, exist_ok=True)
        ts = (now or datetime.datetime.now(datetime.timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
        doc = {"voice": cfg["voice"], "engine": cfg.get("engine", "piper-tts"), "version": cfg["version"],
               "codec": cfg["codec"], "bitrate": cfg["bitrate"], "rate": cfg["rate"], "peak": cfg["peak"],
               "count": len(owned), "generated": ts, "licence": cfg["licence"], "files": files_sorted}
        mpath.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        changed = True

    # Pack files: items were edited in place through `holder`; rewrite each file.
    words = [h for k, _, _, _, h in its if k == "w"]
    sents = [h for k, _, _, _, h in its if k == "s"]
    wrote = []
    if write_like(pack_dir / "words.json", words):
        wrote.append("words.json")
    if write_like(pack_dir / "sentences.json", sents):
        wrote.append("sentences.json")
    if (pack_dir / "passages.json").exists():
        ps = load_json(pack_dir / "passages.json")
        pmap = {name: h for k, name, _, _, h in its if k == "p"}
        for p in ps:
            p["sentences"] = [pmap[f"{p['id']}-{n}"] for n in range(len(p.get("sentences") or []))]
        if write_like(pack_dir / "passages.json", ps):
            wrote.append("passages.json")
    if (pack_dir / "script.json").exists():
        sc = load_json(pack_dir / "script.json")
        umap = {name: h for k, name, _, _, h in its if k == "x"}
        sc["units"] = [umap.get(u["id"], u) for u in sc.get("units") or []]
        if write_like(pack_dir / "script.json", sc):
            wrote.append("script.json")
    # pack.audio (hides the app's no-voice notices) only when every wanted clip is current: a
    # partial --only/--limit run (dev use) links its clips but leaves the notices on.
    pack = load_json(pack_dir / "pack.json")
    if complete:
        pack["audio"] = {"voice": cfg["voice"], "version": cfg["version"]}
    else:
        pack.pop("audio", None)
    if write_like(pack_dir / "pack.json", pack):
        wrote.append("pack.json")
    if wrote:
        jsonify = Path(__file__).resolve().parents[1] / "jsonify_pack.py"
        subprocess.run([sys.executable, str(jsonify), str(pack_dir)], check=True, capture_output=True)
    out(f"audio: {len(todo)} rendered, {len(owned)} clips, {pruned} pruned, {len(orphans) - pruned} orphan, "
        f"{len(missing_after)} missing, {len(stale_after)} stale, {len(foreign)} foreign; "
        f"pack.audio {'set' if complete else 'not set (incomplete)'}; "
        f"wrote {', '.join(wrote) or 'no pack files'}{' + manifest' if changed else ''}")
    return 0


def main(lang, repo, check=False, prune=False, only=None, limit=None):
    from .langs import get_spec
    spec = get_spec(lang, repo, load=False)
    kinds = None
    if only:
        kinds = [k.strip() for k in only.split(",") if k.strip()]
        bad = [k for k in kinds if k not in KINDS]
        if bad:
            raise SystemExit(f"audio: --only takes {','.join(KINDS)}, got {bad}")
    return run(repo, spec, check=check, prune=prune, only=kinds, limit=limit)
