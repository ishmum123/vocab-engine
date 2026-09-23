#!/usr/bin/env python3
"""Validate a vocab-engine pack directory against docs/PACK_SCHEMA.md.

Checks schema (required fields, types), referential integrity (sentence.words ids
exist, every lv is a pack level, functionWords exist, placement levels exist,
typing.strictFromLevel exists), placement feasibility, lesson shape, and that
the generated .js consts are in sync with the .json sources.

Usage: python3 tools/validate_pack.py packs/zh [--dump-strata]
  --dump-strata  print the placement buckets as JSON (parity test with core.js)
Exit 0 = valid (warnings allowed), 1 = errors.
"""
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


class Report:
    def __init__(self):
        self.errors, self.warnings = [], []

    def err(self, msg):
        self.errors.append(msg)

    def warn(self, msg):
        self.warnings.append(msg)


def is_str(x):
    return isinstance(x, str) and x.strip() != ""


def is_bool(x):
    return isinstance(x, bool)


def is_num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def load(packdir, stem, rep, required=True):
    path = os.path.join(packdir, stem + ".json")
    if not os.path.exists(path):
        if required:
            rep.err(f"{stem}.json missing")
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except ValueError as e:
        rep.err(f"{stem}.json is not valid JSON: {e}")
        return None


def check_pack(pack, rep):
    if not isinstance(pack, dict):
        rep.err("pack.json must be an object")
        return set()
    if not (is_str(pack.get("key")) and re.fullmatch(r"[a-z0-9_-]+", pack["key"])):
        rep.err("pack.key must be a lowercase slug [a-z0-9_-]+")
    for f in ("name", "tts"):
        if not is_str(pack.get(f)):
            rep.err(f"pack.{f} must be a non-empty string")
    if "ttsRate" in pack and not (is_num(pack["ttsRate"]) and 0.1 <= pack["ttsRate"] <= 3):
        rep.err("pack.ttsRate must be a number in 0.1..3")
    levels = pack.get("levels")
    ids = []
    if not isinstance(levels, list) or not levels:
        rep.err("pack.levels must be a non-empty list")
    else:
        for i, lv in enumerate(levels):
            if not isinstance(lv, dict) or not isinstance(lv.get("id"), str) or not lv["id"] or not is_str(lv.get("label")):
                rep.err(f"pack.levels[{i}] must be {{id: non-empty string, label: string}}")
                continue
            ids.append(lv["id"])
        if len(set(ids)) != len(ids):
            rep.err("pack.levels ids must be unique")
    idset = set(ids)
    if "setSize" in pack and not (isinstance(pack["setSize"], int) and not is_bool(pack["setSize"]) and pack["setSize"] > 0):
        rep.err("pack.setSize must be a positive integer (default 10)")
    pl = pack.get("placement")
    if not isinstance(pl, list) or not pl:
        rep.err("pack.placement must be a non-empty list of [levelId, bucketCount]")
    else:
        seen = []
        for i, b in enumerate(pl):
            if not (isinstance(b, list) and len(b) == 2 and b[0] in idset and isinstance(b[1], int) and b[1] > 0):
                rep.err(f"pack.placement[{i}] must be [existing level id, positive int], got {b!r}")
            else:
                seen.append(ids.index(b[0]))
        if seen != sorted(seen) or len(set(seen)) != len(seen):
            rep.err("pack.placement levels must be distinct and in pack.levels order")
    if not isinstance(pack.get("functionWords", []), list):
        rep.err("pack.functionWords must be a list of word ids")
    if "typing" not in pack:
        rep.warn("pack.typing absent: typed items are off (same as typing: null)")
    ty = pack.get("typing", None)
    if ty is not None:
        if not isinstance(ty, dict):
            rep.err("pack.typing must be an object or null")
        else:
            if not is_bool(ty.get("caseSensitive", False)):
                rep.err("pack.typing.caseSensitive must be a boolean")
            if ty.get("accents", "lenient") not in ("lenient", "strict"):
                rep.err('pack.typing.accents must be "lenient" or "strict"')
            sfl = ty.get("strictFromLevel", None)
            if sfl is not None and sfl not in idset:
                rep.err(f"pack.typing.strictFromLevel {sfl!r} is not a pack level id")
    for f in ("showPron", "hasLessons"):
        if not is_bool(pack.get(f)):
            rep.err(f"pack.{f} must be a boolean")
    if "spaced" in pack and not is_bool(pack["spaced"]):
        rep.err("pack.spaced must be a boolean")
    if "compounds" in pack and not (isinstance(pack["compounds"], list) and all(is_str(c) for c in pack["compounds"])):
        rep.err("pack.compounds must be a list of non-empty strings")
    check_script_display(pack, rep)
    return idset


# Script-display fields (docs/PACK_SCHEMA.md "Script display"). Patterns mirror
# engine/core.js targetLang / fontFamilyOf / FONT_NAME_RE / lineHeightOf, which ignore
# invalid values at runtime; here they are errors so a pack author sees them.
LANG_TAG_RE = re.compile(r"^[A-Za-z]{2,8}(-[A-Za-z0-9]{1,8})*$")
FONT_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ]{0,60}(:[a-z,]+@[0-9.,;]+)?$")
UNSAFE_FONT_FAMILY_RE = re.compile(r"[;{}<>\\]|url\s*\(|/\*", re.I)


def check_script_display(pack, rep):
    if "rtl" in pack and not is_bool(pack["rtl"]):
        rep.err("pack.rtl must be a boolean")
    if "langTag" in pack and not (isinstance(pack["langTag"], str) and LANG_TAG_RE.match(pack["langTag"])):
        rep.err(f"pack.langTag must be a BCP-47 tag like \"fa\" or \"ur-Arab\", got {pack['langTag']!r}")
    if "fontFamily" in pack:
        ff = pack["fontFamily"]
        if not is_str(ff):
            rep.err("pack.fontFamily must be a non-empty string")
        elif UNSAFE_FONT_FAMILY_RE.search(ff):
            rep.err("pack.fontFamily must not contain ; { } < > \\ /* or url(")
    if "fonts" in pack:
        fonts = pack["fonts"]
        if not isinstance(fonts, list):
            rep.err("pack.fonts must be a list of Google Fonts family names")
        else:
            for i, f in enumerate(fonts):
                if not (isinstance(f, str) and FONT_NAME_RE.match(f.strip())):
                    rep.err(f"pack.fonts[{i}] {f!r} is not a Google Fonts family name (letters, digits, spaces, optional ':wght@400;700')")
    if "lineHeight" in pack:
        lh = pack["lineHeight"]
        if not (is_num(lh) and 1 <= lh <= 4):
            rep.err("pack.lineHeight must be a number in 1..4")
    if pack.get("rtl") is True and not pack.get("fontFamily") and not pack.get("fonts"):
        rep.warn("pack.rtl is true but neither fontFamily nor fonts is set: RTL text falls back to system fonts")


def check_words(words, levels, rep):
    if not isinstance(words, list) or not words:
        rep.err("words.json must be a non-empty list")
        return {}
    by_id = {}
    for i, w in enumerate(words):
        where = f"words[{i}]"
        if not isinstance(w, dict):
            rep.err(f"{where} must be an object")
            continue
        if not is_str(w.get("id")):
            rep.err(f"{where}.id must be a non-empty string")
            continue
        if w["id"] in by_id:
            rep.err(f"{where}.id {w['id']} duplicated")
        by_id[w["id"]] = w
        where = f"word {w['id']}"
        for f in ("w", "en"):
            if not is_str(w.get(f)):
                rep.err(f"{where}.{f} must be a non-empty string")
        if w.get("lv") not in levels:
            rep.err(f"{where}.lv {w.get('lv')!r} not in pack.levels")
        for f in ("pos", "pron"):
            if f in w and not is_str(w[f]):
                rep.err(f"{where}.{f} must be a non-empty string when present")
        if "rank" in w and not is_num(w["rank"]):
            rep.err(f"{where}.rank must be a number")
        if "alt" in w and not (isinstance(w["alt"], list) and all(is_str(a) for a in w["alt"])):
            rep.err(f"{where}.alt must be a list of non-empty strings")
    # same surface form twice in one level makes recall options ambiguous
    seen = {}
    for w in words:
        if isinstance(w, dict) and is_str(w.get("w")):
            k = (w.get("lv"), w["w"].strip().lower())
            if k in seen:
                rep.warn(f"words {seen[k]} and {w.get('id')} share surface form {w['w']!r} at level {w.get('lv')}")
            seen[k] = w.get("id")
    return by_id


MIN_BUCKET_WORDS = 3  # placement draws up to 3 items per bucket (core.js placementItemCount)


def strata(words, spec, set_size):
    """Exact port of core.js strata(): buckets cut on set boundaries.
    tests/engine_checks.js asserts parity via --dump-strata."""
    out = []
    for lv, nb in spec:
        lst = [w for w in words if isinstance(w, dict) and w.get("lv") == lv]
        nsets = -(-len(lst) // set_size)
        per = nsets / nb
        for b in range(nb):
            s0 = int(b * per // 1)
            s1 = max(s0 + 1, int((b + 1) * per // 1))
            out.append({"lv": lv, "s0": s0, "s1": s1, "n": len(lst[s0 * set_size:s1 * set_size])})
    return out


def check_levels_populated(pack, words, rep):
    size = pack.get("setSize") or 10
    for lv in pack.get("levels") or []:
        if not isinstance(lv, dict):
            continue
        n = sum(1 for w in words if isinstance(w, dict) and w.get("lv") == lv.get("id"))
        if n == 0:
            rep.err(f"level {lv.get('id')!r} has no words")
        elif n < size:
            rep.warn(f"level {lv.get('id')!r} has {n} words, fewer than one set ({size})")


def check_placement(pack, words, rep):
    size = pack.get("setSize") or 10
    spec = [b for b in (pack.get("placement") or []) if isinstance(b, list) and len(b) == 2 and isinstance(b[1], int) and b[1] > 0]
    for lv, nb in spec:
        n = sum(1 for w in words if isinstance(w, dict) and w.get("lv") == lv)
        nsets = -(-n // size)
        if nb > nsets:
            rep.err(f"placement level {lv}: {nb} buckets but only {nsets} sets")
    for i, b in enumerate(strata(words, spec, size)):
        if b["n"] < MIN_BUCKET_WORDS:
            rep.err(f"placement bucket {i} (level {b['lv']}, sets {b['s0'] + 1}-{b['s1']}) has {b['n']} words; needs >= {MIN_BUCKET_WORDS}")


def check_sentences(sents, levels, by_id, rep):
    if not isinstance(sents, list):
        rep.err("sentences.json must be a list")
        return
    if not sents:
        rep.warn("sentences.json is empty: the Sentences step will always be skipped")
    ids = set()
    for i, s in enumerate(sents):
        where = f"sentences[{i}]"
        if not isinstance(s, dict) or not is_str(s.get("id")):
            rep.err(f"{where} must be an object with a non-empty id")
            continue
        if s["id"] in ids:
            rep.err(f"{where}.id {s['id']} duplicated")
        ids.add(s["id"])
        where = f"sentence {s['id']}"
        for f in ("t", "en"):
            if not is_str(s.get(f)):
                rep.err(f"{where}.{f} must be a non-empty string")
        if s.get("lv") not in levels:
            rep.err(f"{where}.lv {s.get('lv')!r} not in pack.levels")
        ws = s.get("words")
        if not isinstance(ws, list) or not ws:
            rep.err(f"{where}.words must be a non-empty list of word ids")
        else:
            missing = [w for w in ws if w not in by_id]
            if missing:
                rep.err(f"{where}.words has unknown ids {missing}")
        for f in ("pron", "audio"):
            if f in s and not is_str(s[f]):
                rep.err(f"{where}.{f} must be a non-empty string when present")


def check_lessons(pack, lessons, rep):
    if lessons is None:
        if pack.get("hasLessons"):
            rep.err("pack.hasLessons is true but lessons.json is missing")
        return
    if not pack.get("hasLessons"):
        rep.warn("lessons.json present but pack.hasLessons is false: lessons will not be shown")
    if not isinstance(lessons, list) or (pack.get("hasLessons") and not lessons):
        rep.err("lessons.json must be a non-empty list when hasLessons")
        return
    ids = set()
    for i, l in enumerate(lessons):
        where = f"lessons[{i}]"
        if not isinstance(l, dict):
            rep.err(f"{where} must be an object")
            continue
        for f in ("id", "title", "blurb"):
            if not is_str(l.get(f)):
                rep.err(f"{where}.{f} must be a non-empty string")
        if l.get("id") in ids:
            rep.err(f"{where}.id duplicated")
        ids.add(l.get("id"))
        for j, c in enumerate(l.get("cards") or []):
            if not (isinstance(c, dict) and is_str(c.get("h")) and isinstance(c.get("body"), str)):
                rep.err(f"{where}.cards[{j}] needs h and body")
        items = l.get("items")
        if not isinstance(items, list) or not items:
            rep.err(f"{where}.items must be a non-empty list")
            continue
        for j, it in enumerate(items):
            ok = (isinstance(it, dict) and it.get("t") == "mc" and is_str(it.get("q"))
                  and isinstance(it.get("opts"), list) and len(it["opts"]) >= 2
                  and it.get("a") in it["opts"] and len(set(it["opts"])) == len(it["opts"]))
            if not ok:
                rep.err(f"{where}.items[{j}] must be {{t:'mc', q, opts (distinct, >=2), a in opts}}")


def validate(packdir):
    rep = Report()
    pack = load(packdir, "pack", rep)
    words = load(packdir, "words", rep)
    sents = load(packdir, "sentences", rep)
    lessons = load(packdir, "lessons", rep, required=False)
    if pack is None or words is None or sents is None:
        return rep, {}
    levels = check_pack(pack, rep)
    by_id = check_words(words, levels, rep)
    for fw in pack.get("functionWords") or []:
        if fw not in by_id:
            rep.err(f"pack.functionWords id {fw!r} is not a word id")
    check_levels_populated(pack, words, rep)
    check_placement(pack, words, rep)
    check_sentences(sents, levels, by_id, rep)
    check_lessons(pack, lessons, rep)
    r = subprocess.run([sys.executable, os.path.join(HERE, "jsonify_pack.py"), packdir, "--check"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        rep.err("generated .js out of sync with .json: " + r.stdout.strip().replace("\n", "; "))
    counts = {"words": len(words), "sentences": len(sents) if isinstance(sents, list) else 0,
              "lessons": len(lessons) if isinstance(lessons, list) else 0}
    return rep, counts


def main(argv):
    if len(argv) == 2 and argv[1] == "--dump-strata":
        pack = json.load(open(os.path.join(argv[0], "pack.json"), encoding="utf-8"))
        words = json.load(open(os.path.join(argv[0], "words.json"), encoding="utf-8"))
        print(json.dumps(strata(words, pack.get("placement") or [], pack.get("setSize") or 10)))
        return 0
    if len(argv) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    packdir = argv[0].rstrip("/")
    rep, counts = validate(packdir)
    for w in rep.warnings:
        print(f"WARN  {w}")
    for e in rep.errors[:50]:
        print(f"ERROR {e}")
    if len(rep.errors) > 50:
        print(f"ERROR ... and {len(rep.errors) - 50} more")
    status = "FAIL" if rep.errors else "OK"
    print(f"{status} {packdir}: {counts.get('words', 0)} words, {counts.get('sentences', 0)} sentences, "
          f"{counts.get('lessons', 0)} lessons; {len(rep.errors)} errors, {len(rep.warnings)} warnings")
    return 1 if rep.errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
