"""Stratified samples for hand QA (the ship criteria in README.md).

    python3 -m packbuilder sample --lang it --repo . --seed 303

Words: an equal share per level, each printed with gloss and one example so
the reviewer judges "is the primary sense right?". Sentences: printed with
every linked word so the reviewer judges each link. Use a new seed for every
QA round and record seed + verdict counts in the language repo's REPORT.md
manual section.
"""
import random

from . import load_pack


def sample(spec, seed, n_words=60, n_sentences=60):
    pack, W, S = load_pack(spec)
    rng = random.Random(seed)
    byid = {w["id"]: w for w in W}
    first_sentence = {}
    for s in S:
        for wid in s["words"]:
            first_sentence.setdefault(wid, s)
    levels = spec.level_ids
    per = max(n_words // len(levels), 1)
    print(f"== {per * len(levels)} words, {per} per level (seed {seed}). Verdict per line: ok / wrong sense / wrong POS")
    i = 0
    for lv in levels:
        pool = sorted((w for w in W if w["lv"] == lv), key=lambda w: w["id"])
        for w in rng.sample(pool, min(per, len(pool))):
            i += 1
            ex = first_sentence.get(w["id"])
            print(f"{i:>3} {w['id']} {lv} [{w['pos']}] {w['w']} = {w['en']}")
            if ex:
                print(f"      e.g. {ex['t']}  |  {ex['en']}")
    pool = sorted(S, key=lambda s: s["id"])
    picks = sorted(rng.sample(pool, min(n_sentences, len(pool))), key=lambda s: s["id"])
    n_links = sum(len(s["words"]) for s in picks)
    print(f"\n== {len(picks)} sentences, {n_links} links (seed {seed}). Count wrong links; a sentence is "
          "fully correct when all its links are right")
    for j, s in enumerate(picks, 1):
        print(f"{j:>3} {s['id']} {s['lv']} {s['t']}  |  {s['en']}")
        print("      " + "; ".join(f"{byid[w]['w']} [{byid[w]['pos']}] {byid[w]['en']}" for w in s["words"]))
    return 0
