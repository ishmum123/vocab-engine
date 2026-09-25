"""A mirror of engine/core.js's script option builders (scriptOpts, the compose
branch of scriptItem, formFind, scriptWordOpts), used to check that every unit
x kind it can carry gets 4 options when every unit of its stage is taught (the
app's full sweep in tests/script_app_checks.js). The engine shuffles, then
fills greedily under distinctness rules; option_counts replays that over many
shuffles and returns the fewest options seen, so a count holds for any order.

Keep in step with core.js: scriptKindFits, scriptSecondRight, scriptOpts,
scriptItem (compose, formFind), scriptWordOpts, scriptExamples.
"""
import random

KINDS = ("symSound", "soundSym", "symType", "compose", "formFind", "formMatch", "wordRead", "wordHear")
SOUND_KINDS = ("symSound", "soundSym", "symType")


def norm(s):
    return str("" if s is None else s).strip().lower()


def glyph(u):
    p = str(u.get("t") or "").strip().split()
    return p[-1] if p else ""


def romans(u):
    return [r for r in (norm(x) for x in [u.get("roman"), *(u.get("alt") or [])]) if r]


def has_ex(u):
    return any(isinstance(e, list) and e and e[0] is not None for e in (u.get("ex") or []))


def kind_fits(kind, u):
    if kind in SOUND_KINDS:
        return u.get("sound") is not False and bool(u.get("roman"))
    if kind == "compose":
        return any(isinstance(s, dict) and s.get("t") and s.get("parts") for s in (u.get("syll") or []))
    if kind == "formMatch":
        return u.get("joins") in ("dual", "right")
    if kind in ("formFind", "wordRead", "wordHear"):
        return has_ex(u)
    return False


def second_right(u, c, kind):
    if c["id"] == u["id"] or norm(glyph(c)) == norm(glyph(u)):
        return True
    if u.get("say") and c.get("say") and norm(u["say"]) == norm(c["say"]):
        return True
    ur, cr = norm(u.get("roman")), norm(c.get("roman"))
    if ur and ur == cr:
        return True
    return cr in romans(u) if kind == "symSound" else ur in romans(c)


def sym_opts(u, units, kind, rng):
    sound = kind in SOUND_KINDS
    ok = [v for v in units if v.get("st") == u.get("st") and v.get("roman")
          and not (sound and v.get("sound") is False) and not second_right(u, v, kind)]
    confuse = set(u.get("confuse") or [])
    tiers = [[v for v in ok if v["id"] in confuse], [v for v in ok if u.get("group") is not None and v.get("group") == u.get("group")],
             [v for v in ok if v.get("set") == u.get("set")], ok]
    out, ids, used_g, used_r = [], {u["id"]}, {norm(glyph(u))}, {norm(u.get("roman"))}
    for tier in tiers:
        tier = tier[:]
        rng.shuffle(tier)
        for v in tier:
            if len(out) >= 3:
                return out
            g, r = norm(glyph(v)), norm(v.get("roman"))
            if v["id"] in ids or g in used_g or r in used_r:
                continue
            out.append(v)
            ids.add(v["id"])
            used_g.add(g)
            used_r.add(r)
    return out


def examples(u, by_id):
    return [{"id": e[0], "w": str(by_id[e[0]]["w"]), "roman": str(e[1] if e[1] is not None else "")}
            for e in (u.get("ex") or []) if isinstance(e, list) and e and e[0] in by_id and by_id[e[0]].get("w")]


def compose_opts(u, s, units):
    """Distractor syllables for compose on syllable s (pool = every unit taught)."""
    parts = set(map(str, s["parts"]))
    cand = [x for v in units if v.get("st") == u.get("st") for x in (v.get("syll") or [])
            if isinstance(x, dict) and x.get("t") and str(x["t"]) != str(s["t"])
            and not (s.get("roman") and x.get("roman") and norm(x["roman"]) == norm(s["roman"]))]
    shares = [x for x in cand if any(str(p) in parts for p in x.get("parts") or [])]
    out, used = [], {str(s["t"])}
    for x in shares + cand:
        if len(out) >= 3:
            break
        if str(x["t"]) not in used:
            used.add(str(x["t"]))
            out.append(str(x["t"]))
    return out


def form_find_opts(u, e, units, by_id, rng):
    g = glyph(u)
    has = lambda w: all(ch in w for ch in g)
    cands = [x for v in units if v.get("st") == u.get("st") for x in examples(v, by_id) if not has(x["w"])]
    rng.shuffle(cands)
    out, used = [], {norm(e["w"])}
    for x in cands:
        if len(out) >= 3:
            break
        if norm(x["w"]) not in used:
            used.add(norm(x["w"]))
            out.append(x["w"])
    return out


def word_opts(u, ans, units, by_id, rng):
    cands = [e for v in units if v.get("st") == u.get("st") for e in examples(v, by_id)
             if e["id"] != ans["id"] and norm(e["w"]) != norm(ans["w"]) and e["roman"] and norm(e["roman"]) != norm(ans["roman"])]
    rng.shuffle(cands)
    out, used_w, used_r = [], {norm(ans["w"])}, {norm(ans["roman"])}
    for e in cands:          # the engine sorts by edit distance; greedy distinctness is order-sensitive, so shuffles cover it
        if len(out) >= 3:
            break
        if norm(e["w"]) in used_w or norm(e["roman"]) in used_r:
            continue
        out.append(e)
        used_w.add(norm(e["w"]))
        used_r.add(norm(e["roman"]))
    return out


def option_counts(units, words, tts=True, tries=24):
    """{(unitId, kind): fewest options (answer included) over `tries` shuffles and
    over every syllable / example the item may pick}, for every kind the unit
    carries except symType (typed, no options)."""
    by_id = {w["id"]: w for w in words}
    out = {}
    for u in units:
        for kind in KINDS:
            k = "wordRead" if kind == "wordHear" and not tts else kind
            if k == "symType" or not kind_fits(k, u):
                continue
            best = None
            for t in range(tries):
                rng = random.Random(t)
                if k in ("symSound", "soundSym", "formMatch"):
                    ns = [1 + len(sym_opts(u, units, k, rng))]
                elif k == "compose":
                    ns = [1 + len(compose_opts(u, s, units)) for s in u["syll"]]
                elif k == "formFind":
                    ns = [1 + len(form_find_opts(u, e, units, by_id, rng)) for e in examples(u, by_id)]
                else:
                    ns = [1 + len(word_opts(u, e, units, by_id, rng)) for e in examples(u, by_id)]
                n = min(ns) if ns else 0
                best = n if best is None else min(best, n)
            out[(u["id"], k)] = best
    return out
