"""Shared helpers: logging, the STATS dict REPORT.md reads, JSON writers,
and the per-build environment (language spec + language-repo paths)."""
import json
import re
import sys

STATS = {}  # everything REPORT.md prints; filled by the stages

# A relative audio URL (packbuilder/audio.py's own item pattern, or any relative clip):
# recorded audio (docs/AUDIO.md), as opposed to an absolute one (Tatoeba), which predates
# it and is untouched by `packbuilder audio`. Mirrors audio.py's ABSOLUTE regex.
_ABSOLUTE_URL = re.compile(r"^[a-z][a-z0-9+.-]*:", re.I)


def strip_audio(obj):
    """Deep copy of obj with every dict's relative `audio` field removed (an absolute one,
    e.g. Tatoeba, is left alone). `packbuilder audio` (docs/AUDIO.md) is the only writer of
    recorded-audio fields (words[].audio, sentences[].audio when relative,
    passages[].sentences[].audio, script.json units[].audio, pack.json audio); every other
    emitter (script/words/sentences/passages builders) knows nothing about them and
    regenerates its file without them -- so a regenerated doc must have this same stripping
    applied to whatever it is compared against (the shipped file) instead of the emitter
    being made to carry audio fields it does not own."""
    if isinstance(obj, dict):
        return {k: strip_audio(v) for k, v in obj.items()
                if not (k == "audio" and isinstance(v, str) and not _ABSOLUTE_URL.match(v))}
    if isinstance(obj, list):
        return [strip_audio(v) for v in obj]
    return obj


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def stat(key, value):
    STATS[key] = value


def dump_json(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def write_json(path, obj, compact=True):
    if compact:
        txt = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    else:
        txt = json.dumps(obj, ensure_ascii=False, indent=2)
    path.write_text(txt + "\n")


def derived_write_ok(spec):
    """May spec code write a derived cache (.cache/derived) now? False while
    passages.Linker.pretag tags passage texts (spec.passage_tagging): a cache
    built from the texts handed to the tagger (ja word groups, fa's Stanza memo)
    would then hold passage texts, and one keyed by the corpus alone would be
    clobbered. Every writer reachable from tagging checks this; pretag also
    fails when any derived file changes while it runs (passages._derived_state)."""
    return not getattr(spec, "passage_tagging", False)


def file_sig(path):
    st = path.stat()
    return f"{path.name}:{st.st_size}"


class Env:
    """One build: the language spec and the language repo's directories.
    Caches live in <repo>/.cache (sources) and <repo>/.cache/derived."""

    def __init__(self, spec):
        self.spec = spec
        self.repo = spec.repo
        self.cache = self.repo / ".cache"
        self.derived = self.cache / "derived"
        self.pack = self.repo / "pack"
        self.tools = self.repo / "tools"
