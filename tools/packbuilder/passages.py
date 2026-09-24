"""Reading passages: <repo>/tools/passages_src.json -> <repo>/pack/passages.json.

The source is hand-authored: per passage an id, level, title, sentences
(Italian text + English) and questions whose `words` name the pack lemmas the
answer hinges on. This module tags each sentence with the language's tagger,
links word ids exactly as the sentence stage does for Tatoeba text
(core.sentences.sentence_links over core.lexicon.resolve_sentence), measures
in-pack coverage and level budgets, validates the questions and writes
pack/passages.json deterministically plus tools/REPORT_passages.md.

    python3 -m packbuilder passages <repo> [--check]

The link context (lexicon, word keys) is rebuilt from the cached corpus the
same way `build` builds it, verified against pack/words.json, and pickled
under <repo>/.cache/derived/ keyed by the builder source and pack files.

Source format (tools/passages_src.json):
    {"rules": {"coverage": {"A1": 0.95, ...}, "budget": {"A1": ["A2", 3], ...}},
     "passages": [{"id", "lv", "title", "sentences": [[it, en], ...],
                   "oop": {lemma: reason}, "questions": [{"q", "en", "type",
                   "options" | null, "answer", "words": [lemma, ...], "sentence"}]}]}
Coverage = in-pack tokens / counted tokens; names, numerals, punctuation and
symbols are not counted. A lemma outside the pack must be listed in "oop"
with a reason. Question words are lemmas; each must be linked in the
referenced sentence and is emitted as that sentence's word id.
"""
import hashlib
import json
import pickle
import re
import statistics
import sys
from collections import Counter
from pathlib import Path

from .core.lexicon import SKIP_UPOS
from .core.util import write_json

HERE = Path(__file__).resolve().parent
CTX_VERSION = "p1"
DEFAULT_RULES = {
    "coverage": {"A1": 0.95, "A2": 0.95, "B1": 0.93},
    # level -> [the one higher level allowed, max distinct lemmas from it];
    # anything above that level is not allowed at all
    "budget": {"A1": ["A2", 3], "A2": ["B1", 3], "B1": [None, 0]},
    "words_per_passage": {"A1": [60, 90], "A2": [90, 120], "B1": [110, 150]},
    "questions": [4, 5],
}
MANUAL_MARK = "<!-- manual section: kept across runs -->"
WORD_RE = re.compile(r"[^\W\d_]+(?:'[^\W\d_]+)?|\d+", re.UNICODE)


class Everything:
    """`allowed` for sentence_links: passages may use any lemma (coverage is checked here)."""

    def __contains__(self, x):
        return True


def _sig(repo):
    h = hashlib.sha1(CTX_VERSION.encode())
    for p in sorted(HERE.rglob("*.py")):
        if "tests" in p.parts or p.name == "passages.py":
            continue
        h.update(p.name.encode())
        h.update(p.read_bytes())
    for p in [repo / "pack" / "words.json"] + sorted((repo / "tools").glob("*.json")) + \
            sorted((repo / "tools").glob("*.txt")):
        if p.name.startswith(("passages", "REPORT")):
            continue
        if p.exists():
            h.update(p.name.encode())
            h.update(p.read_bytes())
    return h.hexdigest()[:12]


def load_context(spec):
    """Lexicon, lemma groups, truecase stats and the build's word records
    (with their internal (lemma, POS) keys), as the sentence stage sees them."""
    from .core.util import Env, log
    env = Env(spec)
    repo = env.repo
    cache = env.derived / f"passages_ctx_{_sig(repo)}.pkl"
    if cache.exists():
        with open(cache, "rb") as f:
            c = pickle.load(f)
        c["lexicon"].spec = spec
        return c
    from .core.pipeline import prepare
    from .core.words import build_words
    log("passages: rebuilding link context from the cached corpus (~1 min)")
    ctx = {}
    prepare(env, ctx)
    words, _records, _top = build_words(env, ctx)
    keep = ("id", "w", "lemma", "pos", "en", "lv", "rank", "_key", "_gender", "_epos", "_sidx", "_base")
    slim = [{k: w[k] for k in keep if k in w} for w in words]
    shipped = {w["id"]: w for w in json.loads((repo / "pack" / "words.json").read_text())}
    bad = []
    for w in slim:
        s = shipped.get(w["id"])
        lemmas = {w["lemma"]} | ({w["_base"][0]} if w.get("_base") else set())
        if s is None or s["pos"] != w["pos"] or s["lv"] != w["lv"] or s["lemma"] not in lemmas:
            bad.append(w["id"])
    if bad or len(slim) != len(shipped):
        raise SystemExit(f"passages: rebuilt words differ from pack/words.json ({len(bad)} ids, e.g. "
                         f"{bad[:5]}); rebuild the pack first")
    c = {"lexicon": ctx["lexicon"], "groups": ctx["lemma_groups"], "truecase": ctx["truecase"],
         "words": slim}
    for old in env.derived.glob("passages_ctx_*.pkl"):
        old.unlink()
    with open(cache, "wb") as f:
        pickle.dump(c, f, protocol=pickle.HIGHEST_PROTOCOL)
    return c


class Linker:
    def __init__(self, spec, c, shipped):
        from collections import defaultdict
        self.spec = spec
        self.lexicon = c["lexicon"]
        self.groups = c["groups"]
        self.low, self.cap = c["truecase"]
        words = c["words"]
        self.words = words
        self.by_id = {w["id"]: w for w in words}
        self.shipped = shipped
        self.key_to_id = {tuple(w["_key"]): w["id"] for w in words}
        self.gender_of = {w["id"]: w.get("_gender") for w in words}
        ep = defaultdict(list)
        for w in words:
            if w.get("_epos"):
                ep[(w["_key"][0], w["_epos"])].append((w["_sidx"], w["id"]))
        self.epos_to_id = {k: min(v)[1] for k, v in ep.items()}
        self.lemma_ids = {}
        for w in sorted(words, key=lambda x: x["rank"]):
            if w["pos"] != "art":
                self.lemma_ids.setdefault(w["_key"][0], w["id"])
        # every lemma spelling of a word (build key, shipped lemma, -rsi base)
        self.lemma_of = {}
        for w in words:
            names = {w["_key"][0], w["lemma"], shipped[w["id"]]["lemma"], shipped[w["id"]]["w"]}
            if w.get("_base"):
                names.add(w["_base"][0])
            self.lemma_of[w["id"]] = names
        self.homs = None
        if spec.homograph_by_translation:
            from .core.sentences import homograph_table
            self.homs = homograph_table([dict(w, _key=tuple(w["_key"])) for w in words], spec)
        import spacy
        self.nlp = spacy.load(spec.spacy_model, exclude=["parser", "ner"])
        spec.setup_nlp(self.nlp)

    def tag(self, text, en=""):
        from .core.tag import MORPH_KEEP, truecase
        sp = self.spec
        tc = truecase(text, self.low, self.cap, sp.word_re)
        doc = self.nlp(sp.tag_text(tc))
        keep = sp.morph_keep or MORPH_KEEP
        toks = []
        for t in doc:
            if t.is_space:
                continue
            md = t.morph.to_dict()
            ms = "|".join(f"{k}={md[k]}" for k in keep if k in md)
            toks.append(sp.fix_token([t.text, t.lemma_, t.pos_, ms]))
        return sp.fix_sentence(toks, ["passage", text, None, en, None, None], doc)

    def links(self, toks, text, en):
        from .core.sentences import sentence_links
        return sentence_links(toks, self.lexicon, self.key_to_id, Everything(), text, self.groups,
                              self.gender_of, self.epos_to_id, self.lemma_ids, en, self.homs, None)

    def classify(self, toks):
        """Per counted token: (surface, lemma, word id or None). Names,
        numerals, punctuation and symbols are skipped (not counted)."""
        sp = self.spec
        resolved = self.lexicon.resolve_sentence(toks, self.groups)
        out = []
        initial = True
        for i, (text_t, sl, upos, ms) in enumerate(toks):
            if upos in SKIP_UPOS:
                if text_t in (".", "!", "?", "…", ":"):
                    initial = True
                continue
            was_initial, initial = initial, False
            if any(ch.isdigit() for ch in text_t) or not any(ch.isalpha() for ch in text_t):
                continue
            r = resolved[i]
            low = text_t.lower()
            if r is not None and (r[1] in ("PROPN", "NUM") or upos == "PROPN" or
                                  (sp.caps_mark_names and not was_initial and text_t[:1].isupper())):
                continue
            if r is None and (upos == "PROPN" or (not was_initial and text_t[:1].isupper())):
                continue
            wid = self.key_to_id.get((low, "FORM")) or self.key_to_id.get((low, "INTJ"))
            lem = r[0] if r else low
            if not wid and r is not None:
                wid = self.key_to_id.get(tuple(r))
                if wid is None and sp.drop_keys.get(tuple(r)):
                    wid = self.key_to_id.get(sp.drop_keys[tuple(r)])
                if wid is None and r[1] in sp.group_kpos:
                    wid = self.epos_to_id.get((r[0], sp.group_kpos[r[1]][0]))
            if not wid:
                wid = self.lemma_ids.get(lem) or self.lemma_ids.get(low)
            out.append((text_t, lem, wid))
        return out


def n_words(text):
    return len([m for m in WORD_RE.findall(text) if not m.isdigit()])


def resolve_q_words(lk, lemmas, sent_ids):
    out, errs = [], []
    for lem in lemmas:
        hit = [wid for wid in sent_ids if lem in lk.lemma_of[wid]]
        if not hit:
            errs.append(f"question word {lem!r} is not linked in its sentence")
        elif hit[0] not in out:
            out.append(hit[0])
    return out, errs


def run(spec, check_only=False, out=sys.stdout):
    repo = spec.repo
    src = json.loads((repo / "tools" / "passages_src.json").read_text())
    rules = {**DEFAULT_RULES, **src.get("rules", {})}
    shipped = {w["id"]: w for w in json.loads((repo / "pack" / "words.json").read_text())}
    lk = Linker(spec, load_context(spec), shipped)
    lv_rank = {lv: i for i, lv in enumerate(spec.level_ids)}
    lv_of = {wid: w["lv"] for wid, w in shipped.items()}
    passages, rows, errors = [], [], []
    ids = set()
    for p in src["passages"]:
        pid, lv = p["id"], p["lv"]
        perr = []
        if pid in ids:
            perr.append("duplicate id")
        ids.add(pid)
        if lv not in lv_rank:
            perr.append(f"unknown level {lv}")
        oop_ok = p.get("oop", {})
        sents, counted, oop, above = [], [], Counter(), {}
        linked = 0
        for t, en in p["sentences"]:
            toks = lk.tag(t, en)
            ws = lk.links(toks, t, en)
            sents.append({"t": t, "en": en, "words": ws})
            for surf, lem, wid in lk.classify(toks):
                counted.append(wid is not None)
                linked += wid is not None and wid in ws
                if wid is None:
                    oop[lem] += 1
                elif lv_rank[lv_of[wid]] > lv_rank[lv]:
                    above.setdefault(lv_of[wid], set()).add(shipped[wid]["lemma"])
        text = " ".join(s["t"] for s in sents)
        cov = sum(counted) / len(counted) if counted else 0.0
        if cov < rules["coverage"][lv]:
            perr.append(f"coverage {cov:.3f} < {rules['coverage'][lv]}")
        unlisted = sorted(set(oop) - set(oop_ok))
        if unlisted:
            perr.append(f"out-of-pack lemmas without a reason: {unlisted}")
        stale = sorted(set(oop_ok) - set(oop))
        if stale:
            perr.append(f"oop lists lemmas not in the text: {stale}")
        nw = n_words(text)
        lo, hi = rules["words_per_passage"][lv]
        if not lo <= nw <= hi:
            perr.append(f"{nw} words outside {lo}-{hi}")
        qs = []
        qlo, qhi = rules["questions"]
        if not qlo <= len(p["questions"]) <= qhi:
            perr.append(f"{len(p['questions'])} questions outside {qlo}-{qhi}")
        for j, q in enumerate(p["questions"]):
            qe = []
            si = q["sentence"]
            if not (isinstance(si, int) and 0 <= si < len(sents)):
                perr.append(f"q{j}: sentence index {si} out of range")
                continue
            wids, e = resolve_q_words(lk, q["words"], sents[si]["words"])
            qe += e
            if not 1 <= len(wids) <= 3:
                qe.append(f"{len(wids)} question words (need 1-3)")
            if q["type"] == "mc":
                o = q["options"]
                if not (isinstance(o, list) and len(o) == 4 and len(set(o)) == 4):
                    qe.append("mc needs 4 distinct options")
                if not (isinstance(q["answer"], int) and not isinstance(q["answer"], bool)
                        and 0 <= q["answer"] < 4):
                    qe.append("mc answer must be 0..3")
            elif q["type"] == "tf":
                if q.get("options") is not None or not isinstance(q["answer"], bool):
                    qe.append("tf needs options null and a boolean answer")
            else:
                qe.append(f"type {q['type']!r}")
            # question and options stay inside the pack (plus this passage's listed oop)
            qtexts = [q["q"]] + (q["options"] or [])
            for qt in qtexts:
                for surf, lem, wid in lk.classify(lk.tag(qt)):
                    if wid is None and lem not in oop_ok:
                        qe.append(f"out-of-pack {lem!r} in {qt!r}")
                    elif wid is not None and lv_rank[lv_of[wid]] > lv_rank[lv]:
                        above.setdefault(lv_of[wid], set()).add(shipped[wid]["lemma"])
            perr += [f"q{j}: {x}" for x in qe]
            qs.append({"q": q["q"], "en": q["en"], "type": q["type"], "options": q["options"] if q["type"] == "mc" else None,
                       "answer": q["answer"], "words": wids, "sentence": si})
        # level budget over the passage, its questions and options
        nxt, cap = rules["budget"][lv]
        for alv, lems in sorted(above.items()):
            if alv != nxt:
                perr.append(f"{alv} words not allowed at {lv}: {sorted(lems)}")
            elif len(lems) > cap:
                perr.append(f"{len(lems)} {alv} words > {cap}: {sorted(lems)}")
        passages.append({"id": pid, "lv": lv, "title": p["title"], "text": text, "sentences": sents,
                         "questions": qs, "src": "gen"})
        rows.append({"id": pid, "lv": lv, "title": p["title"], "words": nw, "cov": cov,
                     "counted": len(counted), "link": linked / len(counted) if counted else 0.0, "oop": dict(sorted(oop.items())), "oop_reason": oop_ok,
                     "above": {k: sorted(v) for k, v in sorted(above.items())},
                     "q": Counter(q["type"] for q in qs), "err": perr})
        errors += [f"{pid}: {e}" for e in perr]
    for r in rows:
        flag = "  <-- " + "; ".join(r["err"]) if r["err"] else ""
        print(f"{r['id']} {r['lv']} w={r['words']:3d} cov={r['cov']:.3f} link={r['link']:.3f} oop={r['oop']} above={r['above']}{flag}",
              file=out)
    if errors:
        print(f"passages: {len(errors)} errors", file=out)
    if not check_only:
        if errors:
            print("passages: not writing pack/passages.json (fix the errors first)", file=out)
            return 1
        write_json(repo / "pack" / "passages.json", passages)
        write_report(repo, rows, rules)
        print(f"passages: wrote {len(passages)} passages", file=out)
    return 1 if errors else 0


def write_report(repo, rows, rules):
    lines = ["# Reading passages report", "",
             "Generated by `python3 -m packbuilder passages <repo>` from `tools/passages_src.json`.",
             "Coverage = tokens whose lemma is a pack word / counted tokens (names, numerals,",
             "punctuation not counted). Level budget (passage + questions + options): A1 may use",
             "<=3 A2 lemmas and no B1; A2 may use <=3 B1 lemmas; B1 may use anything in the pack.",
             "Linked = tokens whose word id is also in the sentence's `words` (the stricter share:",
             "a pack lemma can go unlinked when the tagger reads it with another POS).", ""]
    for lv in sorted({r["lv"] for r in rows}):
        rs = [r for r in rows if r["lv"] == lv]
        covs = [r["cov"] for r in rs]
        lks = [r["link"] for r in rs]
        nws = [r["words"] for r in rs]
        qt = Counter()
        for r in rs:
            qt.update(r["q"])
        lines.append(f"- **{lv}**: {len(rs)} passages; words/passage {min(nws)}-{max(nws)} "
                     f"(median {statistics.median(nws)}); coverage min {min(covs):.3f}, median "
                     f"{statistics.median(covs):.3f} (rule >= {rules['coverage'][lv]}); linked min {min(lks):.3f}; questions "
                     f"mc {qt['mc']}, tf {qt['tf']}")
    lines += ["", "| id | lv | title | words | coverage | linked | out-of-pack lemmas (reason) | higher-level lemmas |",
              "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        oop = ", ".join(f"{k} x{v} ({r['oop_reason'].get(k, '?')})" for k, v in r["oop"].items()) or "-"
        above = "; ".join(f"{k}: {', '.join(v)}" for k, v in r["above"].items()) or "-"
        lines.append(f"| {r['id']} | {r['lv']} | {r['title']} | {r['words']} | {r['cov']:.3f} | {r['link']:.3f} | {oop} | {above} |")
    path = repo / "tools" / "REPORT_passages.md"
    manual = ""
    if path.exists() and MANUAL_MARK in path.read_text():
        manual = path.read_text().split(MANUAL_MARK, 1)[1]
    path.write_text("\n".join(lines) + "\n\n" + MANUAL_MARK + (manual or "\n"))


def main(repo, lang=None, check_only=False):
    from .langs import get_spec
    repo = Path(repo).resolve()
    if lang is None:
        lang = json.loads((repo / "pack" / "pack.json").read_text())["key"]
    return run(get_spec(lang, str(repo)), check_only)
