"""Glosses: cleaning Wiktionary sense text into short learner glosses and
ranking senses by association with the corpus translations."""
import math
import re

from .english import en_stems, EN_STOP

MAX_GLOSS = 45
GLOSS_LABEL_RE = re.compile(
    r"^(transitive|intransitive|ambitransitive|reflexive|pronominal|figuratively|figurative|broadly|"
    r"colloquial|informal|formal|euphemistic|rare|dated|archaic|literary|by extension|chiefly|"
    r"especially|usually|often|sometimes|in the plural|plural|singular|uncountable|countable),?:?\s+",
    re.IGNORECASE)
DEFINITIONAL_RE = re.compile(
    r"^(used|denotes|denoting|indicates|indicating|expresses|expressing|introduces|forms|"
    r"a |an |the |one who|someone who|something that|any |of or |relating|pertaining|"
    r"in the sense|with the meaning|translated|equivalent|see )", re.IGNORECASE)


def cap_parts(parts):
    """At most 3 comma alternatives and MAX_GLOSS chars."""
    parts = parts[:3]
    g = ", ".join(parts)
    if len(g) > MAX_GLOSS:
        out = []
        for p in parts:
            if len(", ".join(out + [p])) > MAX_GLOSS:
                break
            out.append(p)
        g = ", ".join(out) if out else g[:MAX_GLOSS].rsplit(" ", 1)[0]
    return g


EN_PROFANE_RE = re.compile(r"\b(fuck\w*|motherfuck\w*|shit\w*|cunt\w*)\b", re.I)


def clean_gloss(g, cap=True, all_groups=False):
    g = g.strip()
    for _ in range(4):
        g2 = GLOSS_LABEL_RE.sub("", g.strip())
        g2 = re.sub(r"^\([^)]*\)\s*", "", g2)
        if g2 == g:
            break
        g = g2
    g = re.sub(r"\[[^\[\]]*\]", "", g)
    stripped = g
    for _ in range(4):
        stripped = re.sub(r"\s*\([^()]*\)", "", stripped)
    if "(" in stripped:
        stripped = stripped.split("(")[0]
    stripped = stripped.replace(")", "")
    if len(stripped.strip()) >= 1:
        g = stripped
    if ". " in g:
        segs = [x.strip() for x in g.split(". ") if x.strip()]
        g = segs[-1] if len(segs[-1].split()) <= 4 else segs[0]
    if ": " in g:
        head, tail = g.rsplit(": ", 1)
        if tail and DEFINITIONAL_RE.match(head + " "):
            g = tail
    g = re.sub(r"^(with the same meaning|in the same sense|same as)\s*:?\s*", "", g, flags=re.I)
    g = re.sub(r"^the (need|desire)(?: or (?:need|desire))? (for|to)\s+", "", g, flags=re.I)
    g = re.sub(r"([!?]) (?=\S)", r"\1, ", g)       # "here it is! there you have it!"
    if len(g.split()) <= 4:
        g = re.sub(r"^(a|an|the) (?!(lot|little|bit|few|while|long)\b)", "", g)   # "a full moon" -> "full moon"
    g = re.sub(r",?\s*\betc\.?$", "", g.strip())
    g = re.sub(r"\s{2,}", " ", g)
    g = re.sub(r"\s+([,.;:])", r"\1", g).strip().rstrip(".").strip()
    g = re.sub(r"[,;:]\s*$", "", g).strip()
    if ";" in g:
        # relational adjectives ("home; national, domestic", "sex; sexual")
        # keep every group so the adjectival one can lead
        g = g.replace(";", ",") if all_groups else g.split(";")[0].strip()
    parts = [p.strip() for p in g.split(",") if re.search(r"[A-Za-z]", p) and p.strip() and not re.match(r"^(pl\.?|see|cf\.?) ", p.strip())]
    # strong English profanity never leads a learner gloss (fregare "to fuck, to screw")
    parts = [p for p in parts if not EN_PROFANE_RE.search(p)] or parts
    # "shop, a store" -> "shop, store": a bare article on a short alternative
    parts = [re.sub(r"^(a|an|the) (?!(lot|little|bit|few|while|long)\b)", "", p) if len(p.split()) <= 3 else p
             for p in parts]
    return cap_parts(parts) if cap else parts


def is_definitional(g, group):
    if DEFINITIONAL_RE.match(g):
        return True
    if group == "VERB" and not g.startswith("to "):
        return True
    return len(g.split(",")[0].split()) > 5


GLOSS_IGNORE = {"to", "a", "an", "the", "of", "or", "and", "in", "on", "at", "for", "with", "by",
                "from", "as", "one", "someon", "someth", "somebody", "oneself", "etc", "thing",
                "used", "us", "denot", "indicat", "express", "especially", "particularly"}


ADJISH_RE = re.compile(r"(al|ic|ous|ive|ary|ful|less|able|ible|ed|ing|ish|an|ese|ent|ant|ile|ar|ory|y|ern|en|ior|ite|ate|ual|ular|ior)$")


def sense_candidates(entry, group, df, nsent, closed, bg, bgn, demote_tags):
    """Scored, cleaned senses of an entry, best first. A sense scores by its
    best English word's association with the translations of the corpus
    sentences that use this (lemma, POS): p * log2(p / q), where p is the
    share of those translations containing the word and q its share over all
    translations (so generic words like 'be', 'thing' do not win). Senses
    tagged with demote_tags (archaic, regional...) rank last."""
    rows = []
    for idx, (gl, hdr, tags, kind) in enumerate(entry["s"]):
        if kind:
            continue
        parts = clean_gloss(gl, cap=False, all_groups=group == "ADJ" and "relational" in tags)
        if not parts:
            continue

        def tok_scores(text):
            st = set(en_stems(text, keep_stop=True))
            if not closed:
                st -= GLOSS_IGNORE
            st.discard("to")
            out = {}
            for t in st:
                pp = df.get(t, 0) / nsent if nsent else 0.0
                q = (bg.get(t, 0) + 1) / bgn
                out[t] = pp * math.log2(pp / q) if pp > q else 0.0
            return out
        # score each comma alternative; the best-supported one leads the
        # displayed gloss ("to marry, to cause to get married")
        if group == "ADJ" and "relational" in tags and any(ADJISH_RE.search(p) for p in parts):
            # relational senses list the noun first ("law; legal"): an
            # adjective gloss must be adjectival
            parts = [p for p in parts if ADJISH_RE.search(p)]
        if group == "VERB" and any(p.startswith("to ") for p in parts):
            parts = [p if p.startswith("to ") or p.split()[0].lower() in EN_STOP else "to " + p
                     for p in parts]
        sc = [tok_scores(p) for p in parts]
        best = [max(d.values(), default=0.0) for d in sc]
        order = sorted(range(len(parts)), key=lambda i: (-round(best[i], 3),
                                                         sum(1 for v in sc[i].values() if v < 0.01), i))
        parts = [parts[i] for i in order]
        lead = sc[order[0]]
        g = cap_parts(parts)
        stems = set().union(*[set(sc[i]) for i in order[:3]])
        score = best[order[0]]
        unmatched = sum(1 for v in lead.values() if v < 0.01)
        demote = bool((set(tags) - entry.get("ht", set())) & demote_tags)
        if group == "ADJ" and "relational" in tags and not ADJISH_RE.search(parts[0]):
            demote = True
        rows.append({"idx": idx, "g": g, "score": round(score, 4), "demote": demote,
                     "defn": is_definitional(g, group), "stems": stems, "unmatched": unmatched,
                     "tags": set(tags), "pscore": {parts[j]: best[i] for j, i in enumerate(order)}})
    # translation-like senses with corpus support first, then definitional
    # ones ("Used as ...") only when nothing translation-like matched; ties go
    # to the sense whose leading alternative has fewer unsupported words,
    # then Wiktionary order.
    rows.sort(key=lambda r: (r["demote"], 0 if r["score"] > 0 and not r["defn"] else 1 if r["score"] > 0 else 2,
                             r["defn"], -round(r["score"], 3), r["unmatched"] if r["score"] > 0 else 0, r["idx"]))
    return rows


def compose_gloss(rows):
    if not rows:
        return None, None
    top = rows[0]
    gloss = top["g"]
    second = None
    for r in rows[1:]:
        if r["demote"] or r["defn"] or top["score"] <= 0 or r["score"] < 0.5 * top["score"]:
            continue
        if r["stems"] & top["stems"] or r["g"].lower() == gloss.lower():
            continue
        if len(gloss) + 2 + len(r["g"]) <= MAX_GLOSS:
            second = r
        break
    if second:
        gloss = f"{gloss}; {second['g']}"
    return gloss, top
