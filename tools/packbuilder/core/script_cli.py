"""`python -m packbuilder script --lang <x> <repo>`: rewrite the script primer
of an already built pack without rebuilding it. Reads pack/words.json, writes
pack/script.json and the "script" key of pack/pack.json, and regenerates only
script.js and pack.js (tools/jsonify_pack.py render): sentences.js and the
rest are never touched. A spec with no script table removes both."""
import json
import sys
from pathlib import Path

from ..langs import get_spec
from .pipeline import write_script, script_pack_fields
from .util import Env, STATS, write_json

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))   # vocab-engine/tools
from jsonify_pack import render  # noqa: E402


def _write_js(pack_dir, stem, const):
    src = pack_dir / f"{stem}.json"
    dst = pack_dir / f"{stem}.js"
    text = render(const, json.loads(src.read_text(encoding="utf-8")))
    if not dst.exists() or dst.read_text(encoding="utf-8") != text:
        dst.write_text(text, encoding="utf-8")
        print(f"wrote {dst}")


def main(lang, repo):
    spec = get_spec(lang, repo, load=False)
    env = Env(spec)
    words = json.loads((env.pack / "words.json").read_text(encoding="utf-8"))
    doc = write_script(env, words)
    pack_path = env.pack / "pack.json"
    pack = json.loads(pack_path.read_text(encoding="utf-8"))
    pack.pop("script", None)
    pack.update(script_pack_fields(spec, doc))
    write_json(pack_path, pack, compact=False)
    _write_js(env.pack, "pack", "PACK")
    if doc is None:
        for f in ("script.json", "script.js"):
            (env.pack / f).unlink(missing_ok=True)
    else:
        _write_js(env.pack, "script", "SCRIPT")
        print(json.dumps(STATS.get("script"), ensure_ascii=False))
    return 0
