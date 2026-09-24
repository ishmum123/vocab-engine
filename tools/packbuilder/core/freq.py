"""Stage freq: corpus usage statistics + (lemma, POS) frequency blend of the
subtitle list and wordfreq, each surface split over its in-context readings."""
import math
import time
from collections import Counter, defaultdict

from .lexicon import group_of
from .tag import iter_tagged
from .util import log, stat

MIN_SHARE = 0.025   # it: "stato" the noun is ~3% of "stato" tokens
N_SUB_SURFACES = 100000
N_WORDFREQ = 30000


def corpus_usage(tagged, lexicon, groups=None):
    """One pass over the tagged corpus."""
    sp = lexicon.spec
    t0 = time.time()
    surf = defaultdict(Counter)       # surface -> Counter((lemma, group))
    raw_upos = defaultdict(Counter)   # (lemma, group) -> Counter(UPOS)
    morph = defaultdict(Counter)      # (lemma, group) -> Counter("Gender=..", "Number=..") on surface==lemma
    refl = Counter()                  # (lemma, VERB) -> tokens carrying a reflexive clitic
    initial = Counter()               # (lemma, group) -> sentence/clause-initial tokens
    stative = Counter()               # (lemma, VERB) -> essere + participle without a clitic
    for sid, toks in iter_tagged(tagged):
        for i, ((text, sl, upos, ms), r) in enumerate(zip(toks, lexicon.resolve_sentence(toks, groups))):
            if r is None:
                continue
            if i == 0 or toks[i - 1][2] == "PUNCT":
                initial[r] += 1
            if r[1] == "VERB":
                if sp.is_reflexive(toks, i):
                    refl[r] += 1
                elif "VerbForm=Part" in ms and sp.stative_aux(toks, i):
                    stative[r] += 1       # "è innamorato", "sono impegnato": neither reading
            s = text.lower()
            surf[s][r] += 1
            raw_upos[r][upos if group_of(upos) == r[1] else "VERB"] += 1
            if s == r[0] and r[1] == "NOUN":
                for kv in ms.split("|"):
                    if kv.startswith(("Gender=", "Number=")):
                        morph[r][kv] += 1
    log(f"usage pass: {len(surf)} surfaces, {len(raw_upos)} (lemma,POS) keys ({time.time()-t0:.0f}s)")
    refl["_stative"] = stative
    return surf, raw_upos, morph, refl, initial


def distribute(surface, count, surf, fallback, stats, spec):
    if spec.is_profane(surface):
        stats["profane_skipped"] += 1
        return []
    dist = surf.get(surface) or surf.get(surface + "'")
    if not dist:
        # subtitle text often drops accents (it: citta, perche, piu): use the
        # accented form when only that one occurs in the corpus
        for s2 in spec.accent_candidates(surface):
            d2 = surf.get(s2)
            if d2:
                dist = d2
                stats["accent_restored"] += 1
                break
    if dist and sum(dist.values()) >= 2:
        tot = sum(dist.values())
        keep = {k: v for k, v in dist.items() if v / tot >= MIN_SHARE}
        kt = sum(keep.values())
        stats["corpus"] += 1
        return [(k, count * v / kt) for k, v in sorted(keep.items())]
    stats["fallback"] += 1
    return [((fallback(surface), "?"), float(count))]


def accent_split(counts, surf, stats, moved, spec):
    """Unaccented spellings inflated in a frequency list (it: pero for però, da
    for dà): move the share above what the corpus predicts to the accented
    spelling. Expected share of s = corpus(s) / (corpus(s) + corpus(s'))."""
    out = dict(counts)
    for s_, n in counts.items():
        acc_forms = spec.accent_candidates(s_)
        if not acc_forms:
            continue
        cs = sum(surf.get(s_, {}).values())
        for s2 in acc_forms:
            ca = sum(surf.get(s2, {}).values())
            if not ca or s2 not in counts:
                continue
            expected = cs / (cs + ca)
            observed = n / (n + counts[s2])
            if observed > expected:
                excess = (observed - expected) * (n + counts[s2])
                out[s_] -= excess
                out[s2] += excess
                stats["accent_excess_moved"] += 1
                if excess > 1000 and len(moved) < 40:
                    moved.append(f"{s_}->{s2} {excess / n:.0%}")
    return out


def stage_freq(env, surf, raw_upos):
    import simplemma
    from wordfreq import zipf_frequency, top_n_list
    sp = env.spec
    stats = Counter()
    sm = lambda w: sp.fallback_lemma(w, sp.fold(simplemma.lemmatize(w, lang=sp.simplemma_code)))
    moved = []
    raw = {}
    with open(env.cache / sp.subtitles_file, encoding="utf-8") as f:
        for line in f:
            parts = line.rstrip("\n").split(" ")
            if len(parts) != 2 or not sp.sub_token_re.match(parts[0]):
                continue
            w = sp.fold(parts[0])         # ru: еще + ещё are one surface
            w = sp.subtitle_surface(w)    # fa: colloquial spelling -> written form; None skips
            if not w:
                continue
            raw[w] = raw.get(w, 0) + int(parts[1])
            if len(raw) >= N_SUB_SURFACES:
                break
    sub = Counter()
    for w, c in accent_split(raw, surf, stats, moved, sp).items():
        for k, cc in distribute(w, c, surf, sm, stats, sp):
            sub[k] += cc
    sub_stats = dict(stats)
    stats = Counter()
    raw = {}
    for w in top_n_list(sp.wordfreq_code, N_WORDFREQ):
        if sp.sub_token_re.match(w):
            z = zipf_frequency(w, sp.wordfreq_code)
            if z > 0:
                raw[sp.fold(w)] = raw.get(sp.fold(w), 0) + 10 ** z
    sp.extra_wordfreq(raw)      # ru: hyphenated words wordfreq only lists split (кто-то)
    wf = Counter()
    for w, c in accent_split(raw, surf, stats, moved, sp).items():
        for k, cc in distribute(w, c, surf, sm, stats, sp):
            wf[k] += cc
    wf_stats = dict(stats)
    stat("accent_moves", moved)

    # "?"-POS keys (surface unseen in the corpus): attach to the lemma's
    # corpus-majority POS when the lemma is known from other surfaces.
    lemma_best = {}
    for (lem, g), c in sorted(raw_upos.items(), key=lambda kv: (kv[0][0], -sum(kv[1].values()), kv[0][1])):
        if g != "PROPN" and lem not in lemma_best:
            lemma_best[lem] = g
    n_q = 0
    for counter in (sub, wf):
        for (lem, g) in sorted(k for k in counter if k[1] == "?"):
            c = counter.pop((lem, g))
            if lem in lemma_best:
                counter[(lem, lemma_best[lem])] += c
            else:
                counter[(lem, "?")] += c
                n_q += 1

    def ranks(counter):
        return {k: i + 1 for i, (k, _) in enumerate(sorted(counter.items(), key=lambda kv: (-kv[1], kv[0])))}
    sr, wr = ranks(sub), ranks(wf)
    common = sorted(set(sr) & set(wr))
    cw = sp.corpus_rank_weight
    if cw:
        # id: the tagged corpus's own (lemma, POS) counts are a third ranking,
        # weighted cw against the subtitle and wordfreq ranks (1 each)
        cr = ranks(Counter({k: sum(c.values()) for k, c in raw_upos.items()}))
        miss = len(cr) + 1
        blended = sorted(((math.log(sr[k]) + math.log(wr[k]) + cw * math.log(cr.get(k, miss))) / (2.0 + cw), k)
                         for k in common)
    else:
        blended = sorted(((math.log(sr[k]) + math.log(wr[k])) / 2.0, k) for k in common)
    stat("freq", {"sub_surfaces": sub_stats, "wf_surfaces": wf_stats, "unknown_pos_keys": n_q,
                  "sub_keys": len(sr), "wf_keys": len(wr), "common_keys": len(common)})
    return [(k, sc, sr[k], wr[k], sub[k] + 0.0) for sc, k in blended]
