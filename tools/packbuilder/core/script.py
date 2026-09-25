"""Script primer emitter (docs/SCRIPT_PRIMER.md ss3): the spec's hand-written
units plus the generated fields -- `say` (spec.script_say), `ex` example words
and `syll` composition examples -- as pack/script.json. Pure: no files, no
Env, so tests call build_script on any word list. Deterministic: every choice
is ordered by (tier, level, spec penalty, position, file order).

`ex` (up to 3 per unit): words whose text holds the unit spelled with its own
glyph and whose every other needed symbol is taught at or before the unit's set
(earlier stages count as taught). spec.script_ex_policy(unit) gives the most
unknown units allowed (default 1) and how many levels the pool spans (default
2; ja katakana: 2 unknowns and a third level). Tiers, first non-empty wins:
levels before the last-resort (third) level first, then fewer unknown units,
then the lower level. So by default: first level readable, second level
readable, first level with one unknown, second level with one unknown. Within
a tier: the unknown unit taught soonest, then spec.script_ex_penalty, then the
unit word-initial, then file (frequency) order. Anything past tier 1 is
reported in the stats.

A token is (unitId, exact, pos[, need]). need False (default True): the token
names the unit for examples only and is not needed to read the word (ja: a
yōon unit, whose parts き + ゃ carry the readability).

`syll`: the spec's composition examples (ko blocks, ja yōon) that occur in
first-level words, given to their owner units (default: every part) whose set
is at or after every part's, ranked by how often they occur, then first
occurrence. Up to 3.
"""
from collections import Counter

from .script_opts import compose_opts

EX_MAX = 3
SYLL_MAX = 3
FIELD_ORDER = ("id", "st", "set", "group", "t", "name", "roman", "alt", "say", "sound", "note",
               "confuse", "ex", "syll", "joins", "base", "italic", "audio")


def _unit_out(u):
    """Drop empty optional fields and order keys stably."""
    out = {}
    for k in FIELD_ORDER:
        if k not in u:
            continue
        v = u[k]
        if v is None or v == [] or v == "":
            continue
        if k == "sound" and v is not False:
            continue
        out[k] = v
    extra = sorted(set(u) - set(FIELD_ORDER))
    if extra:
        raise ValueError(f"script unit {u.get('id')}: unknown fields {extra}")
    return out


def _prune_syll(units):
    """Drop every syllable a compose item could not give 4 options (3 distractor
    syllables of its stage, none sharing its roman: engine scriptItem compose, with
    every unit taught), until none is left short. Returns the dropped [unitId, t]."""
    dropped = []
    while True:
        short = [(u, s) for u in units for s in u["syll"] if len(compose_opts(u, s, units)) < 3]
        if not short:
            return dropped
        for u, s in short:
            u["syll"].remove(s)
            dropped.append([u["id"], s["t"]])


def _need(tok):
    return tok[3] if len(tok) > 3 else True


def build_script(spec, words):
    """-> (script.json dict, stats dict), or (None, None) when the spec has no primer."""
    table = spec.script_units()
    if not table or not spec.script:
        return None, None
    stage_keys = [s["key"] for s in spec.script["stages"]]
    units = [dict(u) for u in table]
    rank = {u["id"]: (stage_keys.index(u["st"]), u["set"]) for u in units}
    glyph = {u["id"]: u["t"].split()[-1] for u in units}
    levels = list(spec.level_ids[:3])

    pool = []           # (level index, file index, word, roman, toks)
    for i, w in enumerate(words):
        if w.get("lv") not in levels or not spec.script_ex_ok(w):
            continue
        text = spec.script_text(w)
        if not text:
            continue
        toks = spec.script_tokens(text)
        if not toks:
            continue
        roman = spec.script_ex_roman(w, text, toks)
        if not roman:
            continue
        pool.append((levels.index(w["lv"]), i, w, roman, toks))

    syll_count, syll_first, syll_info = Counter(), {}, {}
    for i, w in enumerate(words):
        if w.get("lv") != levels[0]:
            continue
        for sy in spec.script_syllables(spec.script_text(w) or ""):
            t = sy[0]
            syll_count[t] += 1
            syll_first.setdefault(t, len(syll_first))
            syll_info.setdefault(t, (sy[1], sy[2], sy[3] if len(sy) > 3 else sy[1]))

    flags = {"second": [], "last": [], 1: [], 2: []}
    no_ex = []
    for u in units:
        key = rank[u["id"]]
        max_unknown, n_levels = spec.script_ex_policy(u)
        tiers = {}
        for lvi, i, w, roman, toks in pool:
            if lvi >= n_levels:
                continue
            pos = [t[2] for t in toks if t[0] == u["id"] and t[1]]
            if not pos:
                continue
            unknown = {t[0] if t[0] is not None else ("?", n) for n, t in enumerate(toks)
                       if _need(t) and (t[0] is None or rank[t[0]] > key)}
            if len(unknown) > max_unknown:
                continue
            tier = (lvi >= 2, len(unknown), lvi)
            # the unknown taught soonest first (a symbol-less unknown -- a hamza
            # seat, a ko double final -- last)
            soon = sorted(rank[x] if isinstance(x, str) else (99, 0) for x in unknown)
            sk = (soon, spec.script_ex_penalty(toks), 0 if min(pos) == 0 else 1, i)
            tiers.setdefault(tier, []).append((sk, w["id"], spec.script_text(w), roman))
        ex = []
        for tier in sorted(tiers):
            seen = set()
            for _, wid, text, roman in sorted(tiers[tier]):
                if text in seen:
                    continue
                seen.add(text)
                ex.append([wid, roman])
                if len(ex) == EX_MAX:
                    break
            if tier[1]:
                flags[tier[1]].append(u["id"])
            if tier[2] == 1:
                flags["second"].append(u["id"])
            if tier[2] >= 2:
                flags["last"].append(u["id"])
            break
        if not ex:
            no_ex.append(u["id"])
        u["ex"] = ex

        cands = [t for t, (parts, _, owners) in syll_info.items()
                 if u["id"] in owners and all(rank.get(p, (99, 0)) <= key for p in parts)]
        cands.sort(key=lambda t: (-syll_count[t], syll_first[t]))
        u["syll"] = [{"t": t, "parts": [glyph[p] for p in syll_info[t][0]], "roman": syll_info[t][1]}
                     for t in cands[:SYLL_MAX]]

        say = spec.script_say(u)
        if say:
            u["say"] = say

    syll_dropped = _prune_syll(units)

    doc = {"units": [_unit_out(u) for u in units]}
    notes = spec.script_notes()
    if notes:
        doc["notes"] = notes
    stats = {
        "units": {k: sum(1 for u in units if u["st"] == k) for k in stage_keys},
        "sets": {k: max((u["set"] for u in units if u["st"] == k), default=0) for k in stage_keys},
        "ex_fallback_second_level": flags["second"],
        "ex_fallback_third_level": flags["last"],
        "ex_one_unknown_unit": flags[1],
        "ex_two_unknown_units": flags[2],
        "ex_none": no_ex,
        "syll_units": sum(1 for u in units if u["syll"]),
        "syll_dropped": syll_dropped,
    }
    return doc, stats
