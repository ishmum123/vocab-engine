"""Shared helpers: logging, the STATS dict REPORT.md reads, JSON writers,
and the per-build environment (language spec + language-repo paths)."""
import json
import sys

STATS = {}  # everything REPORT.md prints; filled by the stages


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
