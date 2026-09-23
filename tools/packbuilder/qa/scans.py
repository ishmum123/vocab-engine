"""QA scans over a built pack (ported from the Italian QA rounds' scan1-3).

    python3 -m packbuilder scan --lang it --repo . [--only 1|2|3]

They print review lists; they do not fail. Ship criteria (see README.md):
each "should be empty" list below is empty or every entry is justified.

  scan 1  gloss junk: form-of / obsolete / vulgar / over-long / empty glosses, POS lists
  scan 2  articles, verb lemma shape, duplicates, loanwords, top 100, function words
  scan 3  closed sets at the first level, fixed items, non-lemma leftovers, gloss shape
"""
import re
from collections import Counter

from . import load_pack

GLOSS_PATTERNS = {
    "form of": r"form of",
    "of X": r"\bof [A-Za-zàèéìòù]+$|^(plural|feminine|masculine|diminutive|augmentative|superlative|"
            r"alternative|apocopic|elided|synonym)",
    "regional": r"Tuscan|dialect",
    "obs": r"obsolete|archaic|dated|\brare\b|literary|poetic|regional",
    "vulg": r"vulgar|slang|offensive|derogatory|pejorative|colloquial",
}
ENGLISH_LOOKING = set("the of and you me he she it is are to a on in at my we off out up down go no yes ok okay "
                      "baby sexy team show film sport bar computer weekend cool boss manager online email mail "
                      "internet club fan star killer party hotel shopping stop test drink jeans look".split())
CLOSED_POS = {"pron", "det", "prep", "conj", "article"}


def _show(title, rows, n=40):
    print(f"\n== {title}: {len(rows)}   (should be empty or justified)")
    for r in rows[:n]:
        print("  ", r["id"], r["w"], "|", r["pos"], "|", r["en"], "|", r["lv"])


def scan1(spec, pack, W, S):
    for k, p in GLOSS_PATTERNS.items():
        _show(k, [w for w in W if re.search(p, w["en"], re.I)])
    _show("long>60", [w for w in W if len(w["en"]) > 60], 15)
    _show("empty/single-cap", [w for w in W if not w["en"].strip() or re.fullmatch(r"[A-Z][a-z]+", w["en"].strip())])
    print("\nPOS counts", dict(Counter(w["pos"] for w in W).most_common()))
    for p in ["pron", "det", "art", "prep", "conj", "num", "adv", "intj", "other", "name"]:
        rows = [w for w in W if w["pos"] == p]
        if rows:
            print(p, len(rows), [(w["w"], w["en"][:40]) for w in rows][:60])


def scan2(spec, pack, W, S):
    fw = set(pack["functionWords"])
    byid = {w["id"]: w for w in W}
    nouns = [w for w in W if w["pos"] == "noun"]
    noart = [w for w in nouns if w["w"] == w["lemma"]]
    print("nouns without article (expected: no_article set only)", len(noart),
          [(w["w"], w["en"][:30]) for w in noart])
    if spec.qa_article_rules:
        bad = [(w["w"], msg) for w in nouns for rx, msg in spec.qa_article_rules if re.search(rx, w["w"])]
        print("article sanity (should be empty or justified)", len(bad), bad)
    verbs = [w for w in W if w["pos"] == "verb"]
    if spec.qa_verb_re:
        print("verbs with a non-infinitive lemma (should be empty except forced forms)",
              [(w["w"], w["en"][:30]) for w in verbs if not re.search(spec.qa_verb_re, w["w"])])
    print("pronominal verbs", [w["w"] for w in verbs if spec.pronominal_base(w["w"])])
    if spec.qa_adj_inflected_re:
        print("adjectives that look inflected", [(w["w"], w["en"][:25]) for w in W
                                                 if w["pos"] == "adj" and re.search(spec.qa_adj_inflected_re, w["w"])])
    c = Counter(w["lemma"] for w in W)
    print("dup lemma (expected: intended second-POS entries only)",
          [(k, [(x["id"], x["w"], x["pos"], x["en"][:25]) for x in W if x["lemma"] == k]) for k, v in c.items() if v > 1])
    c2 = Counter(w["w"] for w in W)
    print("dup w", [k for k, v in c2.items() if v > 1])
    print("noun gloss looks like adj/participle",
          [(w["w"], w["en"][:40]) for w in nouns if re.search(r"equivalent|one who|person who|someone who", w["en"])])
    foreign = spec.qa_foreign_letters_re
    print("english-looking", [(w["w"], w["pos"], w["en"][:30], w["lv"]) for w in W
                              if w["lemma"] in ENGLISH_LOOKING or (foreign and re.search(foreign, w["lemma"]))])
    if spec.qa_proper_re:
        print("proper-noun glosses", [(w["w"], w["en"]) for w in W if re.search(spec.qa_proper_re, w["en"])])
    print("\nTOP100:")
    print(" ".join(f"{w['rank']}:{w['w']}[{w['pos']}]" for w in sorted(W, key=lambda x: x["rank"])[:100]))
    print("\nranks unique/contiguous", len(set(w["rank"] for w in W)), min(w["rank"] for w in W),
          max(w["rank"] for w in W))
    print("level rank ranges", [(lv, min(w["rank"] for w in W if w["lv"] == lv), max(w["rank"] for w in W if w["lv"] == lv))
                                for lv in spec.level_ids if any(w["lv"] == lv for w in W)])
    print("\nFUNCTION WORDS", len(fw))
    print(" ".join(f"{byid[i]['w']}[{byid[i]['pos']}]" for i in pack["functionWords"]))
    print("\nclosed-class NOT in functionWords (should be empty or justified):",
          [(w["id"], w["w"], w["pos"]) for w in W if w["pos"] in CLOSED_POS and w["id"] not in fw])
    print("\nfunctionWords that are content POS:",
          [(byid[i]["w"], byid[i]["pos"], byid[i]["en"][:30]) for i in fw if byid[i]["pos"] in ("noun", "verb", "adj")])
    print("pack.json", {k: (v if not isinstance(v, list) or len(v) < 10 else len(v)) for k, v in pack.items()})


def scan3(spec, pack, W, S):
    first = spec.level_ids[0]
    print("levels", dict(Counter(w["lv"] for w in W)), "sentence levels", dict(Counter(s["lv"] for s in S)))

    def lv(lemma):
        x = [w for w in W if w["lemma"] == lemma]
        return ",".join(f"{w['w']}:{w['lv']}:{w['pos']}" for w in x) if x else "MISSING"
    for k, v in spec.qa_closed_sets.items():
        print(f"closed set {k} not at {first} (should be empty):",
              [(x, lv(x)) for x in v.split() if lv(x) == "MISSING" or f":{first}:" not in lv(x) + ":"],
              "n=", len(v.split()))
    fixed = {k[0] for k in list(spec.fixed_gloss) + list(spec.fixed_word)}
    print("fixed items", [(w["id"], w["w"], w["lemma"], w["en"], w["lv"]) for w in W if w["lemma"] in fixed or w["w"] in fixed])
    if spec.qa_clitic_verb_re:
        print("verbs with an attached clitic (should be empty)",
              [w["w"] for w in W if w["pos"] == "verb" and re.search(spec.qa_clitic_verb_re, w["w"])
               and not spec.pronominal_base(w["w"])])
    if spec.qa_clitic_cluster_re:
        print("clitic clusters as words (should be empty)", [w["w"] for w in W if re.search(spec.qa_clitic_cluster_re, w["w"])])
    print("fem-of/plural/form glosses (should be empty)",
          [(w["w"], w["en"]) for w in W if re.search(r"female|feminine|plural|masculine|equivalent|form of|from [a-z]+\)", w["en"], re.I)])
    if spec.qa_plural_article_re:
        print("plural-article nouns (expected: pluralia tantum only)",
              [(w["w"], w["en"]) for w in W if w["pos"] == "noun" and re.match(spec.qa_plural_article_re, w["w"])])
    print("common-gender nouns", [w["w"] for w in W if "(m/f)" in w["en"] or "/" in w["w"].split(" ")[0]][:40])
    print("gloss with ?/!", [(w["w"], w["en"]) for w in W if "?" in w["en"] or "!" in w["en"]])
    print("gloss starts 'to' but not a verb", [(w["w"], w["pos"], w["en"]) for w in W if w["en"].lower().startswith("to ") and w["pos"] != "verb"])
    print("verb gloss without 'to'", [(w["w"], w["en"]) for w in W if w["pos"] == "verb" and not w["en"].startswith("to ")])
    print("alt present", sum("alt" in w for w in W), [(w["w"], w["alt"]) for w in W if "alt" in w][:15])
    print("capitalised w", [w["w"] for w in W if re.search(r"[A-Z]", w["w"])])
    print("empty gloss", [w["id"] for w in W if not w["en"].strip()])
    print("glosses with >2 senses", sum(w["en"].count(";") >= 2 for w in W))
    print("glosses with brackets/definitional words",
          [(w["w"], w["en"]) for w in W if re.search(r"\(|Used|used|indicat|denot|etc", w["en"])][:30])


def run_scans(spec, only=None):
    pack, W, S = load_pack(spec)
    for n, fn in (("1", scan1), ("2", scan2), ("3", scan3)):
        if only in (None, n):
            print(f"\n######## scan {n} ########")
            fn(spec, pack, W, S)
    return 0
