"""Script primer emitter (docs/SCRIPT_PRIMER.md ss3): the spec's hand-written
units plus the generated fields -- `say` (spec.script_say), `ex` example words
and `syll` composition examples -- as pack/script.json. Pure: no files, no
Env, so tests call build_script on any word list. Deterministic: every choice
is ordered by (tier, level, spec penalty, position, file order).

`ex` (up to 3 per unit): words from the first two levels whose text holds the
unit spelled with its own glyph and whose every other symbol is taught at or
before the unit's set (earlier stages count as taught). Tiers, first non-empty
wins: first level readable, second level readable, first level with exactly one
unknown unit, second level with one unknown. Within a tier: the unknown unit
taught soonest, then spec.script_ex_penalty, then the unit word-initial, then
file (frequency) order. Anything past tier 1 is reported.

`syll`: the spec's composition examples (ko blocks) that occur in first-level
words, whose parts are all taught at or before the unit's set, ranked by how
often they occur, then first occurrence. Up to 3.
"""
from collections import Counter

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


def build_script(spec, words):
    """-> (script.json dict, stats dict), or (None, None) when the spec has no primer."""
    table = spec.script_units()
    if not table or not spec.script:
        return None, None
    stage_keys = [s["key"] for s in spec.script["stages"]]
    units = [dict(u) for u in table]
    rank = {u["id"]: (stage_keys.index(u["st"]), u["set"]) for u in units}
    glyph = {u["id"]: u["t"].split()[-1] for u in units}
    levels = list(spec.level_ids[:2])

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
        for t, parts, roman in spec.script_syllables(spec.script_text(w) or ""):
            syll_count[t] += 1
            syll_first.setdefault(t, len(syll_first))
            syll_info.setdefault(t, (parts, roman))

    fallback_a2, unreadable, no_ex = [], [], []
    for u in units:
        key = rank[u["id"]]
        tiers = {}
        for lvi, i, w, roman, toks in pool:
            pos = [p for uid, exact, p in toks if uid == u["id"] and exact]
            if not pos:
                continue
            unknown = {uid if uid is not None else ("?", n) for n, (uid, _, _) in enumerate(toks)
                       if uid is None or rank[uid] > key}
            if len(unknown) > 1:
                continue
            tier = (len(unknown), lvi)
            # one-unknown tier: the unknown taught soonest first (a symbol-less
            # unknown -- a hamza seat, a ko double final -- last)
            soon = [rank[x] if isinstance(x, str) else (99, 0) for x in unknown]
            sk = (min(soon, default=(0, 0)), spec.script_ex_penalty(toks), 0 if min(pos) == 0 else 1, i)
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
            if tier[0]:
                unreadable.append(u["id"])
            if tier[1]:
                fallback_a2.append(u["id"])
            break
        if not ex:
            no_ex.append(u["id"])
        u["ex"] = ex

        cands = [t for t, (parts, _) in syll_info.items()
                 if u["id"] in parts and all(rank.get(p, (99, 0)) <= key for p in parts)]
        cands.sort(key=lambda t: (-syll_count[t], syll_first[t]))
        u["syll"] = [{"t": t, "parts": [glyph[p] for p in syll_info[t][0]], "roman": syll_info[t][1]}
                     for t in cands[:SYLL_MAX]]

        say = spec.script_say(u)
        if say:
            u["say"] = say

    doc = {"units": [_unit_out(u) for u in units]}
    notes = spec.script_notes()
    if notes:
        doc["notes"] = notes
    stats = {
        "units": {k: sum(1 for u in units if u["st"] == k) for k in stage_keys},
        "sets": {k: max((u["set"] for u in units if u["st"] == k), default=0) for k in stage_keys},
        "ex_fallback_second_level": fallback_a2,
        "ex_one_unknown_unit": unreadable,
        "ex_none": no_ex,
        "syll_units": sum(1 for u in units if u["syll"]),
    }
    return doc, stats
