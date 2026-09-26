"""`python -m packbuilder audio --lang <x> --repo <repo>`: recorded audio for a built pack
(docs/AUDIO.md). Renders one clip per word, sentence, passage sentence and script-unit
carrier with the language's offline voice (spec.AUDIO), writes them beside the site page:

    <repo>/audio/w/<wordId>.opus         <repo>/audio/s/<sentenceId>.opus
    <repo>/audio/p/<passageId>-<n>.opus  <repo>/audio/x/<unitId>.opus
    <repo>/audio/manifest.json           voice, version, bitrate, count, generated, licence, files

then sets each item's `audio` to its relative URL, `pack.json` `audio` to {voice, version},
and regenerates the pack .js files. Items and rules:

- The spoken text is the item's own text (word `w`, sentence `t`, unit `say`), or its override
  from <repo>/tools/audio_say.json ({pack text: spoken text}; ezafe kasre, stress marks). An
  override changes what is spoken only, never the pack text. Keys that match no item are
  stale; `--check` fails on them.
- A clip's key is sha1 of (spoken text, voice, version, synthesis params, codec settings).
  A file whose manifest key matches is kept, so reruns are idempotent and a text or
  override edit re-renders only that item.
- An item that already has an absolute audio URL (Tatoeba recordings) is never rendered and
  its URL is never changed. A relative URL is the builder's own: set when the clip exists,
  removed when it does not.
- Words and script carriers render slower with silence padding (spec.AUDIO short_*);
  sentences at normal speed.

Options: --check (report missing / stale / orphan clips, dangling URLs and stale overrides;
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
            "short_pad_ms": [150, 250], "length_scale": 1.0}


def config(spec):
    """spec.AUDIO merged over DEFAULTS; None when the language has no audio voice."""
    a = getattr(spec, "AUDIO", None)
    if not a:
        return None
    cfg = dict(DEFAULTS, **a)
    for k in ("voice", "version", "licence"):
        if not cfg.get(k):
            raise SystemExit(f"audio: spec.AUDIO needs {k!r}")
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
              cfg["short_pad_ms"] if short else [0, 0]]
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
        pad = cfg["short_pad_ms"] if short else [0, 0]
        af = ["-af", f"adelay={pad[0]},apad=pad_dur={pad[1] / 1000}"] if short else []
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "wav", "-i", "pipe:0", *af, "-ac", "1",
                        "-ar", str(cfg["rate"]), "-c:a", "libopus", "-b:a", cfg["bitrate"],
                        "-application", "voip", str(out)], input=buf.getvalue(), check=True)


def run(repo, spec, check=False, prune=False, only=None, limit=None, renderer=None, now=None, out=print):
    repo = Path(repo)
    cfg = config(spec)
    if cfg is None:
        out(f"audio: language {getattr(spec, 'code', '?')!r} has no spec.AUDIO voice")
        return 2
    pack_dir, adir = repo / "pack", repo / "audio"
    mpath = adir / "manifest.json"
    manifest = load_json(mpath) if mpath.exists() else {}
    files = dict(manifest.get("files") or {}) if manifest.get("voice") == cfg["voice"] else {}
    overrides, problems = load_overrides(repo)
    its = items(pack_dir)
    stale_ov, letter_ov = override_notes(overrides, {t for _, _, t, _, _ in its})

    want = {}     # rel path -> (key, spoken, short, holder); items whose URL the builder owns
    for kind, name, text, short, holder in its:
        if isinstance(holder.get("audio"), str) and ABSOLUTE.match(holder["audio"]):
            continue
        spoken = overrides.get(text, text)
        want[f"{kind}/{name}.opus"] = (clip_key(spoken, short, cfg), spoken, short, holder)

    def exists_ok(rel):
        return (adir / rel).exists() and files.get(rel) == want[rel][0]

    on_disk = {p.relative_to(adir).as_posix() for k in KINDS if (adir / k).is_dir()
               for p in (adir / k).glob("*.opus")}
    orphans = sorted(on_disk - set(want))
    missing = sorted(r for r in want if not (adir / r).exists())
    stale = sorted(r for r in want if (adir / r).exists() and files.get(r) != want[r][0])
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
        for k in letter_ov:
            out(f"note: override changes letters, not just marks: {k!r}")
        bad = sum(map(len, (missing, stale, orphans, dangling, stale_ov, problems)))
        out(f"audio --check: {len(want)} clips wanted, {len(missing)} missing, {len(stale)} stale, "
            f"{len(orphans)} orphan, {len(dangling)} dangling URLs, {len(stale_ov)} stale override keys")
        return 1 if bad else 0

    if problems:
        for p in problems:
            out(p)
        return 1
    for k in stale_ov:
        out(f"warning: stale override key (no item has this text): {k!r}")

    kinds = set(only) if only else set(KINDS)
    todo = [r for r in want if r.split("/")[0] in kinds and not exists_ok(r)]
    if limit is not None:
        todo = todo[:limit]
    if todo and renderer is None:
        renderer = PiperRenderer(repo, cfg)
    for rel in todo:
        key, spoken, short, _ = want[rel]
        dst = adir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_suffix(".tmp.opus")
        renderer.render(spoken, short, tmp)
        tmp.replace(dst)
        files[rel] = key
    pruned = 0
    if prune:
        for rel in orphans:
            (adir / rel).unlink()
            files.pop(rel, None)
            pruned += 1
    files = {r: k for r, k in files.items() if (adir / r).exists()}

    # URLs: the builder's own (relative) URL on every wanted item whose clip is current.
    for rel, (key, _, _, holder) in want.items():
        if files.get(rel) == key and (adir / rel).exists():
            holder["audio"] = f"audio/{rel}"
        else:
            holder.pop("audio", None)

    changed = False
    if (files or mpath.exists()) and (todo or pruned or not mpath.exists() or manifest.get("files") != dict(sorted(files.items()))):
        adir.mkdir(parents=True, exist_ok=True)
        ts = (now or datetime.datetime.now(datetime.timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
        doc = {"voice": cfg["voice"], "engine": cfg.get("engine", "piper-tts"), "version": cfg["version"],
               "codec": cfg["codec"], "bitrate": cfg["bitrate"], "rate": cfg["rate"], "count": len(files),
               "generated": ts, "licence": cfg["licence"], "files": dict(sorted(files.items()))}
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
    pack = load_json(pack_dir / "pack.json")
    if files:
        pack["audio"] = {"voice": cfg["voice"], "version": cfg["version"]}
    else:
        pack.pop("audio", None)
    if write_like(pack_dir / "pack.json", pack):
        wrote.append("pack.json")
    if wrote:
        jsonify = Path(__file__).resolve().parents[1] / "jsonify_pack.py"
        subprocess.run([sys.executable, str(jsonify), str(pack_dir)], check=True, capture_output=True)
    out(f"audio: {len(todo)} rendered, {len(files)} clips, {pruned} pruned, {len(orphans) - pruned} orphan, "
        f"{len(missing) - len([r for r in todo if r in missing])} still missing; "
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
