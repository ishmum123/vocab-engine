#!/usr/bin/env python3
"""Validate a vocab-engine pack directory against docs/PACK_SCHEMA.md.

Checks schema (required fields, types), referential integrity (sentence.words ids
exist, every lv is a pack level, functionWords exist, placement levels exist,
typing.strictFromLevel exists), placement feasibility, lesson shape, optional
passages.json (ids, levels, word ids, question shape and sentence indices), optional
script.json (script primer units and notes, with pack.script), and that
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
        return set(), None
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
    if ty is not None and ty != "pron":
        if not isinstance(ty, dict):
            rep.err('pack.typing must be an object, "pron" or null')
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
    if "legacy" in pack:
        lg = pack["legacy"]
        if not (isinstance(lg, dict) and is_str(lg.get("key")) and is_str(lg.get("format"))):
            rep.err("pack.legacy must be {key: non-empty string, format: non-empty string}")
    char_levels = check_characters_pack(pack, ids, rep)
    check_pron_aids_pack(pack, rep)
    if "pronFirst" in pack:
        if not is_bool(pack["pronFirst"]):
            rep.err("pack.pronFirst must be a boolean")
        elif pack["pronFirst"] and "characters" not in pack:
            rep.warn("pack.pronFirst is true but pack.characters is absent: it has no effect")
    return idset, char_levels


CHAR_KINDS = ("charRead", "charSound", "charPick", "charRecall")

# Pronunciation aids (docs/PACK_SCHEMA.md "Pronunciation aids"). pack.tones names the tone-
# mark system of the readings; the engine implements exactly one (Latin letters, tone marks
# on the vowel, its syllable inventory), so only that literal is accepted.
TONE_SYSTEMS = ("pinyin",)


def check_pron_aids_pack(pack, rep):
    """pack.tones, pack.soundsReference (pack.typing "pron" is checked with typing)."""
    if "tones" in pack and pack["tones"] not in TONE_SYSTEMS:
        rep.err(f"pack.tones must be one of {list(TONE_SYSTEMS)} (got {pack['tones']!r})")
    if "soundsReference" in pack:
        if pack["soundsReference"] is not True:
            rep.err("pack.soundsReference must be true when present")
        elif pack.get("hasLessons") is not True:
            rep.warn("pack.soundsReference is set but pack.hasLessons is not true: the Reference card has no lessons to build from")


def check_pron_aids_data(pack, words, lessons, rep):
    """Data the pronunciation aids need: typed readings need prons; the Reference card
    needs lesson rows with a one-character `say`."""
    if pack.get("typing") == "pron":
        nopron = [w.get("id") for w in words if isinstance(w, dict) and not (isinstance(w.get("pron"), str) and w["pron"].strip())]
        if len(nopron) == len(words):
            rep.err('pack.typing is "pron" but no word has a pron')
        elif nopron:
            rep.warn(f'pack.typing is "pron": {len(nopron)} words have no pron and get recall instead (e.g. {nopron[:3]})')
    if pack.get("soundsReference") is True and isinstance(lessons, list):
        cells = 0
        for l in lessons:
            for c in (l.get("cards") or []) if isinstance(l, dict) else []:
                rows, say = c.get("rows") or [], c.get("say") or []
                for i, r in enumerate(rows):
                    if isinstance(r, list) and r and isinstance(r[0], str) and r[0] and i < len(say) and isinstance(say[i], str) and len(say[i]) == 1:
                        cells += 1
        if cells == 0:
            rep.warn("pack.soundsReference is set but no lesson row has a one-character say: the Reference card is empty")


def check_characters_pack(pack, level_ids, rep):
    """pack.characters (optional): docs/PACK_SCHEMA.md "characters". `level_ids` is
    pack.levels[].id in order. Returns the set of character-level ids covered by some
    stage, or None if pack.characters is absent."""
    ch = pack.get("characters")
    if ch is None:
        return None
    idset = set(level_ids)
    if not isinstance(ch, dict):
        rep.err("pack.characters must be an object")
        return set()
    if not is_str(ch.get("label")):
        rep.err("pack.characters.label must be a non-empty string")
    stages = ch.get("stages")
    covered = set()
    if not isinstance(stages, list) or not stages:
        rep.err("pack.characters.stages must be a non-empty list of {after, levels}")
    else:
        last_idx = -1
        for i, st in enumerate(stages):
            where = f"pack.characters.stages[{i}]"
            if not isinstance(st, dict):
                rep.err(f"{where} must be an object")
                continue
            after = st.get("after")
            if after not in idset:
                rep.err(f"{where}.after {after!r} is not a pack level id")
            elif level_ids.index(after) < last_idx:
                rep.err(f"{where}.after {after!r} is out of pack.levels order (stages must be non-decreasing)")
            else:
                last_idx = level_ids.index(after)
            levels = st.get("levels")
            if not isinstance(levels, list) or not levels:
                rep.err(f"{where}.levels must be a non-empty list of pack level ids")
                continue
            for lv in levels:
                if lv not in idset:
                    rep.err(f"{where}.levels has {lv!r}, not a pack level id")
                elif after in idset and level_ids.index(lv) > level_ids.index(after):
                    rep.err(f"{where}.levels has {lv!r}, after the stage's own position ({after!r}) in pack.levels order: a stage covers only levels taught by then")
                elif lv in covered:
                    rep.err(f"{where}.levels: level {lv!r} is covered by more than one stage")
                else:
                    covered.add(lv)
    if not (isinstance(ch.get("mastered", 3), int) and not is_bool(ch.get("mastered", 3)) and ch.get("mastered", 3) > 0):
        rep.err("pack.characters.mastered must be a positive integer")
    if not (isinstance(ch.get("bare", 6), int) and not is_bool(ch.get("bare", 6)) and ch.get("bare", 6) > 0):
        rep.err("pack.characters.bare must be a positive integer")
    mastered, bare = ch.get("mastered", 3), ch.get("bare", 6)
    if is_num(mastered) and is_num(bare) and bare <= mastered:
        rep.err(f"pack.characters.bare ({bare}) must be greater than pack.characters.mastered ({mastered})")
    if "setSize" in ch and not (isinstance(ch["setSize"], int) and not is_bool(ch["setSize"]) and ch["setSize"] > 0):
        rep.err("pack.characters.setSize must be a positive integer")
    for f in ("learnKinds", "reviewKinds"):
        v = ch.get(f)
        if not (isinstance(v, list) and v and all(k in CHAR_KINDS for k in v)):
            rep.err(f"pack.characters.{f} must be a non-empty list drawn from {CHAR_KINDS}")
    if "testKinds" in ch:
        tk = ch["testKinds"]
        if not (isinstance(tk, dict) and tk and all(k in CHAR_KINDS and is_num(v) and 0 < v < float("inf") for k, v in tk.items())):
            rep.err(f"pack.characters.testKinds must be a non-empty object {{kind: positive weight}} with kinds from {CHAR_KINDS}")
    if "compose" in ch and not is_bool(ch["compose"]):
        rep.err("pack.characters.compose must be a boolean")
    return covered


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


def check_ruby(ruby, t, ws, char_word0, where, rep, null_ok=False):
    """sentences[].ruby (optional): [[start, end, reading, wordId], ...] in UTF-16 code
    units of t, sorted, non-overlapping, wordId in the sentence's words and some
    characters.json unit's words[0] (docs/PACK_SCHEMA.md sentences.json "ruby").
    null_ok (passages.json): wordId may be null (a token of no pack word); ws None:
    no words list to be in (titleRuby, questions[].ruby, optionsRuby)."""
    if not isinstance(ruby, list):
        rep.err(f"{where}.ruby must be a list of [start, end, reading, wordId]")
        return
    u = t.encode("utf-16-le") if isinstance(t, str) else b""
    n = len(u) // 2
    free = ws is None
    ws = set(ws) if isinstance(ws, list) else set()
    prev = 0
    for k, x in enumerate(ruby):
        rw = f"{where}.ruby[{k}]"
        if not (isinstance(x, list) and len(x) == 4 and all(isinstance(v, int) and not is_bool(v) for v in x[:2])
                and is_str(x[2]) and ((isinstance(x[3], str) and x[3]) or (null_ok and x[3] is None))):
            rep.err(f"{rw} must be [start, end, reading, wordId] with integer offsets and non-empty strings"
                    + (" (wordId may be null)" if null_ok else ""))
            continue
        a, b, reading, wid = x
        if not 0 <= a < b <= n:
            rep.err(f"{rw} [{a}, {b}] out of bounds for a {n}-unit sentence (need 0 <= start < end <= length)")
            continue
        if a < prev:
            rep.err(f"{rw} starts at {a}, before the previous ruby's end {prev} (ruby must be sorted and not overlap)")
        prev = max(prev, b)
        if wid is None:
            pass
        elif not free and wid not in ws:
            rep.err(f"{rw} word {wid!r} is not in the sentence's words")
        elif char_word0 is not None and wid not in char_word0:
            rep.err(f"{rw} word {wid!r} is not words[0] of any characters.json unit")
        try:
            piece = u[2 * a:2 * b].decode("utf-16-le")
        except UnicodeDecodeError:
            rep.err(f"{rw} [{a}, {b}] splits a surrogate pair")
            continue
        if not piece.strip():
            rep.err(f"{rw} [{a}, {b}] covers only whitespace")


def check_sentences(sents, levels, by_id, rep, char_word0=None):
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
        if "ruby" in s:
            if char_word0 is None:
                rep.warn(f"{where}.ruby present but pack.characters is absent: ruby is never rendered")
            check_ruby(s["ruby"], s.get("t"), ws, char_word0, where, rep)


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


PASSAGE_Q_TYPES = ("mc", "tf")


def check_spans(spans, t, words, where, rep):
    """sentences[].spans (optional): [[start, end, wordId], ...] in UTF-16 code
    units of t, sorted, non-overlapping, wordId in the sentence's words, and each
    slice non-blank text that does not split a surrogate pair. A span may carry a
    4th element, a non-empty display-only gloss string ([start, end, wordId, gloss])."""
    if not isinstance(spans, list):
        rep.err(f"{where}.spans must be a list of [start, end, wordId]")
        return
    u = t.encode("utf-16-le") if isinstance(t, str) else b""
    n = len(u) // 2
    ws = set(words) if isinstance(words, list) else set()
    prev = 0
    for k, x in enumerate(spans):
        sw = f"{where}.spans[{k}]"
        if not (isinstance(x, list) and len(x) in (3, 4) and all(isinstance(v, int) and not is_bool(v) for v in x[:2])
                and isinstance(x[2], str)):
            rep.err(f"{sw} must be [start, end, wordId] or [start, end, wordId, gloss] with integer offsets")
            continue
        if len(x) == 4 and not (isinstance(x[3], str) and x[3].strip()):
            rep.err(f"{sw} gloss (4th element) must be a non-empty string")
            continue
        a, b, wid = x[:3]
        if not 0 <= a < b <= n:
            rep.err(f"{sw} [{a}, {b}] out of bounds for a {n}-unit sentence (need 0 <= start < end <= length)")
            continue
        if a < prev:
            rep.err(f"{sw} starts at {a}, before the previous span's end {prev} (spans must be sorted and not overlap)")
        prev = max(prev, b)
        if wid not in ws:
            rep.err(f"{sw} word {wid!r} is not in the sentence's words")
        try:
            piece = u[2 * a:2 * b].decode("utf-16-le")
        except UnicodeDecodeError:
            rep.err(f"{sw} [{a}, {b}] splits a surrogate pair")
            continue
        if not piece.strip():
            rep.err(f"{sw} [{a}, {b}] covers only whitespace")


def check_passages(passages, levels, by_id, rep, char_word0=None):
    """passages.json (optional): docs/PACK_SCHEMA.md "passages.json"."""
    if passages is None:
        return
    if not isinstance(passages, list):
        rep.err("passages.json must be a list")
        return
    if not passages:
        rep.warn("passages.json is empty: the Read tab will be hidden")
    ids = set()
    for i, p in enumerate(passages):
        where = f"passages[{i}]"
        if not isinstance(p, dict) or not is_str(p.get("id")):
            rep.err(f"{where} must be an object with a non-empty id")
            continue
        if p["id"] in ids:
            rep.err(f"{where}.id {p['id']} duplicated")
        ids.add(p["id"])
        where = f"passage {p['id']}"
        if p.get("lv") not in levels:
            rep.err(f"{where}.lv {p.get('lv')!r} not in pack.levels")
        for f in ("title", "text"):
            if not is_str(p.get(f)):
                rep.err(f"{where}.{f} must be a non-empty string")
        if "src" in p and not is_str(p["src"]):
            rep.err(f"{where}.src must be a non-empty string when present")
        sents = p.get("sentences")
        nsent = 0
        if not isinstance(sents, list) or not sents:
            rep.err(f"{where}.sentences must be a non-empty list")
        else:
            nsent = len(sents)
            text = p.get("text") if isinstance(p.get("text"), str) else ""
            for j, s in enumerate(sents):
                sw = f"{where}.sentences[{j}]"
                if not isinstance(s, dict):
                    rep.err(f"{sw} must be an object")
                    continue
                for f in ("t", "en"):
                    if not is_str(s.get(f)):
                        rep.err(f"{sw}.{f} must be a non-empty string")
                ws = s.get("words")
                if not isinstance(ws, list):
                    rep.err(f"{sw}.words must be a list of word ids")
                else:
                    missing = [w for w in ws if w not in by_id]
                    if missing:
                        rep.err(f"{sw}.words has unknown ids {missing}")
                if "spans" in s:
                    check_spans(s["spans"], s.get("t"), ws, sw, rep)
                if "ruby" in s:
                    # Same rules as sentences.json ruby; the Read tab renders it by tier.
                    if char_word0 is None:
                        rep.warn(f"{sw}.ruby present but pack.characters is absent: ruby is never rendered")
                    check_ruby(s["ruby"], s.get("t"), ws, char_word0, sw, rep, null_ok=True)
                if is_str(s.get("t")) and text and s["t"].strip() not in text:
                    rep.warn(f"{sw}.t does not appear in the passage text")
        if "titleRuby" in p:
            passage_ruby_field(p["titleRuby"], p.get("title"), char_word0, f"{where}.title", rep)
        qs = p.get("questions")
        if not isinstance(qs, list) or not qs:
            rep.err(f"{where}.questions must be a non-empty list")
            continue
        for j, q in enumerate(qs):
            qw = f"{where}.questions[{j}]"
            if not isinstance(q, dict):
                rep.err(f"{qw} must be an object")
                continue
            if not is_str(q.get("q")):
                rep.err(f"{qw}.q must be a non-empty string")
            if "en" in q and not is_str(q["en"]):
                rep.err(f"{qw}.en must be a non-empty string when present")
            ty = q.get("type")
            if ty not in PASSAGE_Q_TYPES:
                rep.err(f"{qw}.type must be \"mc\" or \"tf\", got {ty!r}")
            elif ty == "mc":
                opts = q.get("options")
                if not (isinstance(opts, list) and len(opts) == 4 and all(is_str(o) for o in opts)
                        and len(set(o.strip() for o in opts)) == 4):
                    rep.err(f"{qw}.options must be 4 distinct non-empty strings")
                a = q.get("answer")
                if not (isinstance(a, int) and not is_bool(a) and 0 <= a < 4):
                    rep.err(f"{qw}.answer must be an option index 0..3")
            else:
                if q.get("options") is not None:
                    rep.err(f"{qw}.options must be null or absent for a tf question")
                if not is_bool(q.get("answer")):
                    rep.err(f"{qw}.answer must be true or false for a tf question")
            ws = q.get("words")
            if not isinstance(ws, list):
                rep.err(f"{qw}.words must be a list of word ids")
            else:
                missing = [w for w in ws if w not in by_id]
                if missing:
                    rep.err(f"{qw}.words has unknown ids {missing}")
                elif not ws:
                    rep.warn(f"{qw}.words is empty: a wrong answer charges no word")
            si = q.get("sentence")
            if not (isinstance(si, int) and not is_bool(si) and 0 <= si < nsent):
                rep.err(f"{qw}.sentence must be an index into {where}.sentences (0..{nsent - 1})")
            if "ruby" in q:
                passage_ruby_field(q["ruby"], q.get("q"), char_word0, f"{qw}.q", rep)
            if "optionsRuby" in q:
                opts, orb = q.get("options"), q["optionsRuby"]
                if not (isinstance(opts, list) and isinstance(orb, list) and len(orb) == len(opts)):
                    rep.err(f"{qw}.optionsRuby must be a list with one ruby list per option")
                else:
                    for k, (o, r) in enumerate(zip(opts, orb)):
                        passage_ruby_field(r, o, char_word0, f"{qw}.options[{k}]", rep)


def passage_ruby_field(ruby, t, char_word0, where, rep):
    """passages.json titleRuby, questions[].ruby, questions[].optionsRuby[k]: the
    sentences[].ruby format for that text, wordId null or a characters.json unit's
    words[0] (no words list to be in)."""
    if char_word0 is None:
        rep.warn(f"{where} ruby present but pack.characters is absent: ruby is never rendered")
    check_ruby(ruby, t, None, char_word0, where, rep, null_ok=True)


def check_characters_data(chars, char_levels, by_id, rep):
    """pack/characters.json (required exactly when pack.characters is present):
    docs/PACK_SCHEMA.md "pack/characters.json". `char_levels` is the set of level ids
    covered by pack.characters.stages, or None if pack.characters is absent.
    Returns (unit ids, {words[0] ids}) for cross-checks (legacy.json, sentences[].ruby)."""
    if chars is None:
        return set(), set()
    if not isinstance(chars, list) or not chars:
        rep.err("characters.json must be a non-empty list")
        return set(), set()
    ids, word0 = set(), set()
    for i, c in enumerate(chars):
        where = f"characters[{i}]"
        if not isinstance(c, dict) or not is_str(c.get("id")):
            rep.err(f"{where} must be an object with a non-empty id")
            continue
        if c["id"] in ids:
            rep.err(f"{where}.id {c['id']} duplicated")
        ids.add(c["id"])
        where = f"character unit {c['id']}"
        if not is_str(c.get("t")):
            rep.err(f"{where}.t must be a non-empty string")
        ws = c.get("words")
        if not isinstance(ws, list) or not ws:
            rep.err(f"{where}.words must be a non-empty list of word ids")
        else:
            missing = [w for w in ws if w not in by_id]
            if missing:
                rep.err(f"{where}.words has unknown ids {missing}")
            elif is_str(ws[0]):
                word0.add(ws[0])
                w0lv = by_id[ws[0]].get("lv") if isinstance(by_id[ws[0]], dict) else None
                if c.get("lv") != w0lv:
                    rep.err(f"{where}.lv {c.get('lv')!r} differs from the level of its words[0] {ws[0]} ({w0lv!r})")
        if char_levels is not None:
            if c.get("lv") not in char_levels:
                rep.err(f"{where}.lv {c.get('lv')!r} is not covered by any pack.characters.stages[].levels")
        if "reading" in c and not is_str(c["reading"]):
            rep.err(f"{where}.reading must be a non-empty string when present")
    return ids, word0


# Script primer (docs/PACK_SCHEMA.md "Script primer", docs/SCRIPT_PRIMER.md §3).
SCRIPT_KINDS = ("symSound", "soundSym", "symType", "compose", "formFind", "formMatch", "wordRead", "wordHear")
SCRIPT_UNIT_ID_RE = re.compile(r"^[a-z]{2,3}-[a-z0-9-]+$")
SCRIPT_JOINS = ("dual", "right")
POSITIONAL_LETTER_RE = re.compile(r"^HANGUL (?:CHOSEONG|JUNGSEONG|JONGSEONG|LETTER) (.+)$")


def is_pos_int(x):
    return isinstance(x, int) and not is_bool(x) and x >= 1


def glyph_keys(s):
    """Folds text for "does this symbol occur in that word": compatibility decomposition
    (presentation forms and composed syllables split into their letters, dakuten split
    off), lower case, and positional letter variants (a syllable-initial and a
    syllable-final form of one letter) mapped to one key. Returns a list of keys."""
    import unicodedata
    out = []
    for ch in unicodedata.normalize("NFKD", str(s).lower()):
        m = POSITIONAL_LETTER_RE.match(unicodedata.name(ch, ""))
        out.append("L:" + m.group(1) if m else ch)
    return out


def glyph_in(glyph, text):
    g, t = glyph_keys(glyph), glyph_keys(text)
    if not g:
        return False
    return any(t[i:i + len(g)] == g for i in range(len(t) - len(g) + 1))


def check_script_pack(pack, rep):
    """pack.script (optional). Returns {stage key: label} or None if absent."""
    if "script" not in pack:
        return None
    sc = pack["script"]
    if not isinstance(sc, dict):
        rep.err("pack.script must be an object")
        return {}
    keys = {}
    stages = sc.get("stages")
    if not (isinstance(stages, list) and stages):
        rep.err("pack.script.stages must be a non-empty list of {key, label}")
    else:
        for i, st in enumerate(stages):
            if not (isinstance(st, dict) and is_str(st.get("key")) and is_str(st.get("label"))):
                rep.err(f"pack.script.stages[{i}] must be {{key: non-empty string, label: non-empty string}}")
                continue
            if st["key"] in keys:
                rep.err(f"pack.script.stages key {st['key']!r} duplicated")
            keys[st["key"]] = st["label"]
    for f in ("setsPerSession", "mastered"):
        if f in sc and not is_pos_int(sc[f]):
            rep.err(f"pack.script.{f} must be a positive integer")
    if "tts" in sc and not is_bool(sc["tts"]):
        rep.err("pack.script.tts must be a boolean")
    for f in ("learnKinds", "reviewKinds"):
        if f in sc:
            v = sc[f]
            if not (isinstance(v, list) and v and all(k in SCRIPT_KINDS for k in v)):
                rep.err(f"pack.script.{f} must be a non-empty list drawn from {SCRIPT_KINDS}")
    if "testKinds" in sc:
        tk = sc["testKinds"]
        if not (isinstance(tk, dict) and tk and all(k in SCRIPT_KINDS and is_num(v) and 0 < v < float("inf") for k, v in tk.items())):
            rep.err(f"pack.script.testKinds must be a non-empty object {{kind: positive weight}} with kinds from {SCRIPT_KINDS}")
    return keys


def check_script_data(pack, script, stage_keys, words, rep):
    """pack/script.json (required exactly when pack.script is present). `stage_keys` is
    check_script_pack's result."""
    if script is None or stage_keys is None:
        return
    if not isinstance(script, dict) or not isinstance(script.get("units"), list) or not script["units"]:
        rep.err("script.json must be an object with a non-empty units list")
        return
    level_ids = [lv.get("id") for lv in pack.get("levels") or [] if isinstance(lv, dict)]
    first_lv = level_ids[0] if level_ids else None
    second_lv = level_ids[1] if len(level_ids) > 1 else None
    by_id = {w["id"]: w for w in words if isinstance(w, dict) and is_str(w.get("id"))}
    first_texts = [t for w in words if isinstance(w, dict) and w.get("lv") == first_lv
                   for t in (w.get("w"), w.get("pron")) if is_str(t)]
    units, ids = [], set()
    for i, u in enumerate(script["units"]):
        if not isinstance(u, dict) or not isinstance(u.get("id"), str):
            rep.err(f"script units[{i}] must be an object with a string id")
            continue
        if not SCRIPT_UNIT_ID_RE.match(u["id"]):
            rep.err(f"script unit id {u['id']!r} must match {SCRIPT_UNIT_ID_RE.pattern}")
        if u["id"] in ids:
            rep.err(f"script unit id {u['id']!r} duplicated")
        ids.add(u["id"])
        units.append(u)
    by_uid = {u["id"]: u for u in units}
    sets_of = {}
    for u in units:
        where = f"script unit {u['id']}"
        if u.get("st") not in stage_keys:
            rep.err(f"{where}.st {u.get('st')!r} is not a pack.script.stages key")
        if not is_pos_int(u.get("set")):
            rep.err(f"{where}.set must be an integer >= 1")
        else:
            sets_of.setdefault(u.get("st"), set()).add(u["set"])
        for f in ("t", "roman"):
            if not is_str(u.get(f)):
                rep.err(f"{where}.{f} must be a non-empty string")
        for f in ("name", "say", "audio", "note", "group", "italic"):
            if f in u and not is_str(u[f]):
                rep.err(f"{where}.{f} must be a non-empty string when present")
        if "sound" in u and not is_bool(u["sound"]):
            rep.err(f"{where}.sound must be a boolean")
        if "alt" in u and not (isinstance(u["alt"], list) and all(is_str(a) for a in u["alt"])):
            rep.err(f"{where}.alt must be a list of non-empty strings")
        cf = u.get("confuse", [])
        if not (isinstance(cf, list) and all(isinstance(c, str) for c in cf)):
            rep.err(f"{where}.confuse must be a list of unit ids")
        else:
            bad = [c for c in cf if c not in by_uid or c == u["id"]]
            if bad:
                rep.err(f"{where}.confuse has unknown or self ids {bad}")
        if "base" in u and u["base"] not in by_uid:
            rep.err(f"{where}.base {u['base']!r} is not a known unit id")
        if "joins" in u:
            if u["joins"] not in SCRIPT_JOINS:
                rep.err(f"{where}.joins must be one of {SCRIPT_JOINS}")
            elif pack.get("rtl") is not True:
                rep.err(f"{where}.joins is set but pack.rtl is not true (joining forms are right-to-left letters only)")
        glyphs = str(u.get("t") or "").split()
        ex = u.get("ex")
        if ex is None or ex == []:
            rep.warn(f"{where} has no ex example words")
        elif not (isinstance(ex, list) and 1 <= len(ex) <= 3):
            rep.err(f"{where}.ex must be a list of 1-3 [wordId, roman]")
        else:
            for j, e in enumerate(ex):
                if not (isinstance(e, list) and len(e) == 2 and isinstance(e[0], str) and is_str(e[1])):
                    rep.err(f"{where}.ex[{j}] must be [wordId, non-empty roman]")
                    continue
                w = by_id.get(e[0])
                if w is None:
                    rep.err(f"{where}.ex[{j}] word {e[0]!r} is not a word id")
                    continue
                if w.get("lv") not in (first_lv, second_lv):
                    rep.err(f"{where}.ex[{j}] word {e[0]} is level {w.get('lv')!r}, after the second level")
                elif w.get("lv") != first_lv:
                    rep.warn(f"{where}.ex[{j}] word {e[0]} is from level {w.get('lv')!r}, not the first level")
                texts = [t for t in (w.get("w"), w.get("pron")) if is_str(t)]
                if glyphs and not any(glyph_in(g, t) for g in glyphs for t in texts):
                    rep.err(f"{where}.ex[{j}]: the unit's glyph {u.get('t')!r} does not occur in word {e[0]} ({w.get('w')!r})")
        if "syll" in u:
            sy = u["syll"]
            if not isinstance(sy, list):
                rep.err(f"{where}.syll must be a list of {{t, parts, roman}}")
                sy = []
            for j, s in enumerate(sy):
                sw = f"{where}.syll[{j}]"
                if not (isinstance(s, dict) and is_str(s.get("t")) and is_str(s.get("roman"))
                        and isinstance(s.get("parts"), list) and s["parts"] and all(is_str(p) for p in s["parts"])):
                    rep.err(f"{sw} must be {{t, parts: non-empty list of glyphs, roman}}")
                    continue
                known = {g for v in units if v.get("st") == u.get("st") and is_pos_int(v.get("set")) and is_pos_int(u.get("set"))
                         and v["set"] <= u["set"] for g in str(v.get("t") or "").split()}
                late = [p for p in s["parts"] if p not in known]
                if late:
                    rep.err(f"{sw}.parts {late} are not glyphs of units at or before set {u.get('set')} of stage {u.get('st')!r}")
                if not any(glyph_in(s["t"], t) for t in first_texts):
                    rep.err(f"{sw}.t {s['t']!r} does not occur in any first-level word")
        if u.get("sound", True) is not False and "say" not in u and (pack.get("script") or {}).get("tts") is not False:
            rep.warn(f"{where} has sound but no say (TTS has nothing to speak)")
    for st, sets in sets_of.items():
        if st in stage_keys and sorted(sets) != list(range(1, len(sets) + 1)):
            rep.err(f"script stage {st!r} sets {sorted(sets)} are not contiguous from 1")
    for key in stage_keys:
        if not any(u.get("st") == key for u in units):
            rep.err(f"pack.script stage {key!r} has no units in script.json")
    groups = {}
    for u in units:
        if is_str(u.get("group")) and is_str(u.get("roman")):
            groups.setdefault((u.get("st"), u["group"], u["roman"].strip().lower()), []).append(u)
    for (st, g, r), us in groups.items():
        for a in range(len(us)):
            for b in range(a + 1, len(us)):
                x, y = us[a], us[b]
                if y["id"] not in (x.get("confuse") or []) and x["id"] not in (y.get("confuse") or []):
                    rep.warn(f"script units {x['id']} and {y['id']} share group {g!r} and roman {r!r} with no confuse link")
    notes = script.get("notes", [])
    if not isinstance(notes, list):
        rep.err("script.json notes must be a list")
        notes = []
    for i, n in enumerate(notes):
        if not (isinstance(n, dict) and is_str(n.get("h")) and is_str(n.get("body"))):
            rep.err(f"script notes[{i}] must be {{st, set, h, body}} with non-empty h and body")
            continue
        if n.get("st") not in stage_keys or n.get("set") not in sets_of.get(n.get("st"), set()):
            rep.err(f"script notes[{i}] ({n.get('st')!r}, set {n.get('set')!r}) is not a known stage set")
    extra = set(script) - {"units", "notes"}
    if extra:
        rep.err(f"script.json has unknown keys {sorted(extra)} (only units, notes are used)")


def check_legacy(pack, legacy, by_id, sent_ids, char_ids, rep):
    """legacy.json (optional, requires pack.legacy and vice versa): docs/PACK_SCHEMA.md
    "legacy.json". `by_id`/`sent_ids`/`char_ids` are this pack's known ids."""
    has_pack, has_file = "legacy" in pack, legacy is not None
    if has_pack and not has_file:
        rep.err("pack.legacy is set but legacy.json is missing")
    if has_file and not has_pack:
        rep.err("legacy.json is present but pack.legacy is not set")
    if legacy is None:
        return
    if not isinstance(legacy, dict):
        rep.err("legacy.json must be an object with optional keys w, s, c")
        return
    targets = {"w": by_id, "s": sent_ids, "c": char_ids}
    for key, target in targets.items():
        if key not in legacy:
            continue
        m = legacy[key]
        if not isinstance(m, dict) or not all(is_str(k) for k in m):
            rep.err(f"legacy.json.{key} must be an object of string -> id")
            continue
        missing = [v for v in m.values() if v not in target]
        if missing:
            rep.err(f"legacy.json.{key} has values with no matching id: {missing[:10]}")
        vals = list(m.values())
        if len(set(vals)) != len(vals):
            rep.warn(f"legacy.json.{key} maps more than one key to the same id")
    extra = set(legacy) - {"w", "s", "c"}
    if extra:
        rep.err(f"legacy.json has unknown keys {sorted(extra)} (only w, s, c are used)")


def validate(packdir):
    rep = Report()
    pack = load(packdir, "pack", rep)
    words = load(packdir, "words", rep)
    sents = load(packdir, "sentences", rep)
    lessons = load(packdir, "lessons", rep, required=False)
    passages = load(packdir, "passages", rep, required=False)
    chars = load(packdir, "characters", rep, required=False)
    legacy = load(packdir, "legacy", rep, required=False)
    script = load(packdir, "script", rep, required=False)
    if pack is None or words is None or sents is None:
        return rep, {}
    levels, char_levels = check_pack(pack, rep)
    by_id = check_words(words, levels, rep)
    for fw in pack.get("functionWords") or []:
        if fw not in by_id:
            rep.err(f"pack.functionWords id {fw!r} is not a word id")
    check_levels_populated(pack, words, rep)
    check_placement(pack, words, rep)
    has_pack_chars, has_chars_file = "characters" in pack, chars is not None
    if has_pack_chars and not has_chars_file:
        rep.err("pack.characters is set but characters.json is missing")
    if has_chars_file and not has_pack_chars:
        rep.err("characters.json is present but pack.characters is not set")
    char_ids, char_word0 = check_characters_data(chars, char_levels, by_id, rep)
    check_sentences(sents, levels, by_id, rep, char_word0=char_word0 if has_pack_chars else None)
    check_lessons(pack, lessons, rep)
    check_pron_aids_data(pack, words, lessons, rep)
    check_passages(passages, levels, by_id, rep, char_word0=char_word0 if has_pack_chars else None)
    has_pack_script, has_script_file = isinstance(pack, dict) and "script" in pack, script is not None
    if has_pack_script and not has_script_file:
        rep.err("pack.script is set but script.json is missing")
    if has_script_file and not has_pack_script:
        rep.err("script.json is present but pack.script is not set")
    check_script_data(pack, script, check_script_pack(pack, rep) if isinstance(pack, dict) else None, words, rep)
    check_legacy(pack, legacy, by_id, {s.get("id") for s in sents if isinstance(s, dict)}, char_ids, rep)
    r = subprocess.run([sys.executable, os.path.join(HERE, "jsonify_pack.py"), packdir, "--check"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        rep.err("generated .js out of sync with .json: " + r.stdout.strip().replace("\n", "; "))
    counts = {"words": len(words), "sentences": len(sents) if isinstance(sents, list) else 0,
              "lessons": len(lessons) if isinstance(lessons, list) else 0,
              "passages": len(passages) if isinstance(passages, list) else 0,
              "characters": len(chars) if isinstance(chars, list) else 0,
              "script": len(script["units"]) if isinstance(script, dict) and isinstance(script.get("units"), list) else 0}
    return rep, counts


def passages_note(counts):
    # Only packs with passages mention them, so existing packs' output is unchanged.
    n = counts.get("passages", 0)
    return f", {n} passages" if n else ""


def characters_note(counts):
    # Only packs with a characters stage mention it, so existing packs' output is unchanged.
    n = counts.get("characters", 0)
    return f", {n} character units" if n else ""


def script_note(counts):
    # Only packs with a script primer mention it, so existing packs' output is unchanged.
    n = counts.get("script", 0)
    return f", {n} script units" if n else ""


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
          f"{counts.get('lessons', 0)} lessons{passages_note(counts)}{characters_note(counts)}{script_note(counts)}; "
          f"{len(rep.errors)} errors, {len(rep.warnings)} warnings")
    return 1 if rep.errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
