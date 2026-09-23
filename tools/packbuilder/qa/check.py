"""Schema + referential integrity + language assertions for a built pack.

    python3 -m packbuilder check --lang it --repo .

Exits non-zero on any failure. Language-specific assertions (it: noun article
forms) come from LanguageSpec.check_word.
"""
from collections import Counter

from . import load_pack

PACK_KEYS = ("key", "name", "tts", "ttsRate", "levels", "setSize", "placement",
             "functionWords", "typing", "showPron", "hasLessons")
MIN_COVERAGE_1 = 90    # % of words with >=1 sentence (fail below)
MIN_COVERAGE_2 = 70    # % of words with >=2 sentences (warn below)


def check(spec):
    pack, words, sentences = load_pack(spec)
    valid_levels = set(spec.level_ids)
    fails, warns = [], []
    fail, warn = fails.append, warns.append

    for key in PACK_KEYS:
        if key not in pack:
            fail(f"pack.json missing key: {key}")
    if pack.get("key") != spec.code:
        fail(f"pack.json key {pack.get('key')!r} != language code {spec.code!r}")

    if len(words) != spec.n_words:
        fail(f"words.json has {len(words)} entries, expected {spec.n_words}")
    ids_seen = set()
    lv_counts = Counter()
    for w in words:
        for key in ("id", "w", "lemma", "pos", "en", "lv", "rank"):
            if key not in w:
                fail(f"word {w.get('id','?')} missing key {key}")
        if w["id"] in ids_seen:
            fail(f"duplicate word id: {w['id']}")
        ids_seen.add(w["id"])
        err = spec.check_word(w)
        if err:
            fail(err)
        # engine convention (PACK_SCHEMA.md): when w carries an article or
        # clitic, alt[0] is the bare form, a whole trailing token of w
        alt = w.get("alt") or []
        if alt and (" " in w["w"] or "'" in w["w"]) and w["pos"] != "phrase":
            a0 = alt[0]
            if not (w["w"].endswith(" " + a0) or w["w"].endswith("'" + a0)):
                fail(f"word {w['id']} {w['w']!r}: alt[0] {a0!r} is not its trailing bare form")
        if w.get("lv") not in valid_levels:
            fail(f"word {w['id']} has invalid lv: {w.get('lv')}")
        else:
            lv_counts[w["lv"]] += 1
    for lv, n in spec.bands:
        if lv_counts[lv] != n:
            fail(f"level {lv} has {lv_counts[lv]} words, expected {n}")

    function_word_ids = set(pack.get("functionWords", []))
    unknown_fw = function_word_ids - ids_seen
    if unknown_fw:
        fail(f"functionWords references unknown word ids: {sorted(unknown_fw)[:10]}")

    sent_ids_seen = set()
    for s in sentences:
        for key in ("id", "t", "en", "lv", "words"):
            if key not in s:
                fail(f"sentence {s.get('id','?')} missing key {key}")
        if s["id"] in sent_ids_seen:
            fail(f"duplicate sentence id: {s['id']}")
        sent_ids_seen.add(s["id"])
        if s.get("lv") not in valid_levels:
            fail(f"sentence {s['id']} has invalid lv: {s.get('lv')}")
        for wid in s.get("words", []):
            if wid not in ids_seen:
                fail(f"sentence {s['id']} references unknown word id {wid}")

    word_sentence_count = Counter()
    for s in sentences:
        for wid in s.get("words", []):
            word_sentence_count[wid] += 1
    zero = [w["id"] for w in words if word_sentence_count[w["id"]] == 0]
    one = [w["id"] for w in words if word_sentence_count[w["id"]] == 1]
    two_plus = [w["id"] for w in words if word_sentence_count[w["id"]] >= 2]
    n = max(len(words), 1)
    pct_ge1 = 100.0 * (len(words) - len(zero)) / n
    pct_ge2 = 100.0 * len(two_plus) / n
    if pct_ge1 < MIN_COVERAGE_1:
        fail(f"only {pct_ge1:.1f}% of words have >=1 sentence (need >={MIN_COVERAGE_1}%)")
    if pct_ge2 < MIN_COVERAGE_2:
        warn(f"only {pct_ge2:.1f}% of words have >=2 sentences (target >={MIN_COVERAGE_2}%)")

    print("=== check_pack summary ===")
    print(f"words: {len(words)} total; levels: {dict(lv_counts)}")
    print(f"sentences: {len(sentences)} total")
    print(f"word sentence coverage: 0={len(zero)} 1={len(one)} 2+={len(two_plus)} "
          f"(>=1: {pct_ge1:.1f}%, >=2: {pct_ge2:.1f}%)")
    print(f"function words: {len(function_word_ids)}")
    if warns:
        print("\nWARNINGS:")
        for w in warns:
            print(f"  - {w}")
    if fails:
        print("\nFAILURES:")
        for f in fails:
            print(f"  - {f}")
        print(f"\ncheck_pack: FAILED ({len(fails)} failures)")
        return 1
    print("\ncheck_pack: PASSED")
    return 0
