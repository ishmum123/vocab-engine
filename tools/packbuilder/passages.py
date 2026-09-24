"""Reading passages: <repo>/tools/passages_src.json -> <repo>/pack/passages.json.

The source is hand-authored: per passage an id, level, title, sentences
(Italian text + English) and questions whose `words` name the pack lemmas the
answer hinges on. This module tags each sentence with the language's tagger
(core.tag.tag_docs/doc_tokens: spaCy, or the spec's Stanza tag_texts),
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
with a reason; one whose reason starts with "name" is a name and not counted. Question words are lemmas; each must be linked in the
referenced sentence and is emitted as that sentence's word id.

Each emitted sentence also carries `spans`: [[start, end, wordId], ...], the
text of `t` each linked word was read from (token_offsets + make_spans), so
the app can make inflected forms (mele, compra, va) tappable in place. Offsets
are UTF-16 code units (JavaScript string indices), equal to Python indices for
BMP-only text. A word in `words` with no span (its token could not be located
in `t`, or a longer span covers it) falls back to surface matching in the app.
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
CTX_VERSION = "p3"      # p3: the pickle carries the spec state and the English vocabulary
DEFAULT_RULES = {
    "coverage": {"A1": 0.95, "A2": 0.95, "B1": 0.93},
    # level -> [the one higher level allowed, max distinct lemmas from it];
    # anything above that level is not allowed at all
    "budget": {"A1": ["A2", 3], "A2": ["B1", 3], "B1": [None, 0]},
    "words_per_passage": {"A1": [60, 90], "A2": [90, 120], "B1": [110, 150]},
    "questions": [4, 5],
}
PHRASE_HEADS = {"rispetto": {"a"}, "fine": {"settimana"}}   # lemma -> next word that makes it part of a compound (rispetto a, fine settimana): no link
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
        # the fresh path's spec went through bind_lexicon (and the build); an
        # unpickled lexicon does not rebind, and re-running bind_lexicon would
        # repeat its in-place lexicon edits (de/fa/fr/id/ru). Restore the spec
        # state instead (es _lex/_voseo, fr/id _lx, de pluralia_tantum, id
        # voice_alt), and the English vocabulary prepare() filled (en_stem:
        # id post_resolve, cross-POS links), so a cached run equals a fresh one
        spec.__dict__.update(c.pop("spec_state"))
        _set_english(*c.pop("english"))
        return c
    from .core.pipeline import finish_words, prepare
    from .core.words import build_words
    log("passages: rebuilding link context from the cached corpus (~1 min)")
    ctx = {}
    prepare(env, ctx)
    words, records, top = build_words(env, ctx)
    # the build's full word pass: refill_unexampled (de/id/ru) and finalize_words
    # (fa display lemmas, id adjective POS) change ids, lemmas and POS
    words = finish_words(env, ctx, words, records, top)[0]
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
    # the whole spec state after the build (bind_lexicon handles, derived sets,
    # attributes edited in place), pickled with the lexicon it points to; the
    # repo path is the caller's
    from .core.english import _STEM, EN_VOCAB
    state = {k: v for k, v in spec.__dict__.items() if k != "repo"}
    english = (set(EN_VOCAB), dict(_STEM))
    for old in env.derived.glob("passages_ctx_*.pkl"):
        old.unlink()
    with open(cache, "wb") as f:
        pickle.dump(dict(c, spec_state=state, english=english), f, protocol=pickle.HIGHEST_PROTOCOL)
    return c


def _set_english(vocab, stems):
    """Restore core.english's corpus vocabulary and en_stem memo in place."""
    from .core.english import _STEM, EN_VOCAB
    EN_VOCAB.clear()
    EN_VOCAB.update(vocab)
    _STEM.clear()
    _STEM.update(stems)


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
        self.num_ids = {w["_key"][0]: w["id"] for w in words if w["_key"][1] == "NUM"}
        self.homs = None
        if spec.homograph_by_translation:
            from .core.sentences import homograph_table
            self.homs = homograph_table([dict(w, _key=tuple(w["_key"])) for w in words], spec)
        # spec.passage_post_resolve: passage-only resolve rules, after post_resolve,
        # for classify and sentence_links alike (the build's resolve is untouched)
        lex = self.lexicon
        if lex is not None and not getattr(lex, "_passage_wrapped", False):
            orig = lex.resolve_sentence

            def resolve_sentence(toks, groups=None):
                return spec.passage_post_resolve(toks, orig(toks, groups))
            lex.resolve_sentence = resolve_sentence
            lex._passage_wrapped = True
        self.tagged = {}     # (text, en) -> tokens
        self.lowered = {}    # (text, en) -> indices of tokens truecase_after lowered

    def pretag(self, items):
        """Tag (text, en) pairs in one tagger run (one model load; Stanza
        batches) through core.tag's shared entry point, exactly as stage_tag
        tags the corpus: truecase (passages only: spec.truecase_after, the
        first word of quoted/exclaimed speech, and spec.truecase_after_end,
        after a mid-text ! ?), spec.tag_text, the spec's tagger (spaCy or
        spec.tag_texts), fix_token, fix_sentence. A batch-dependent
        tag_texts sees only this batch: id's PROPN rescue counts lowercase
        uses across the texts it is given, so passage tagging has less
        evidence than the corpus build (measure when id passages are built)."""
        from .core.tag import doc_tokens, tag_docs, truecase, truecase_after
        sp = self.spec
        todo = list(dict.fromkeys(k for k in items if k not in self.tagged))
        if not todo:
            return
        known = (lambda w: bool(self.lexicon.readings(w))) if sp.truecase_after_end else None
        base = [truecase(t, self.low, self.cap, sp.word_re) for t, _en in todo]
        after = [truecase_after(b, self.low, self.cap, sp.word_re, sp.truecase_after, sp.truecase_after_end, known)
                 for b in base]
        texts = [sp.tag_text(a) for a in after]
        docs, fields = tag_docs(sp, texts, n_process=1)
        for (t, en), doc, b, a in zip(todo, docs, base, after):
            self.tagged[(t, en)] = toks = doc_tokens(sp, doc, fields, ["passage", t, None, en, None, None])
            # tokens truecase_after lowered: to classify they are like a
            # sentence start (a lowered name is not a pack verb: «¡Leo, ven!»)
            moved = {j for j, (x, y) in enumerate(zip(b, a)) if x != y}
            lowered = set()
            if moved:
                offs = token_offsets(a, toks, sp.span_fold, sp.span_joiners)
                lowered = {i for i, o in enumerate(offs) if o and o[0] in moved}
            self.lowered[(t, en)] = lowered

    def tag(self, text, en=""):
        if (text, en) not in self.tagged:
            self.pretag([(text, en)])
        return self.tagged[(text, en)]

    def links(self, toks, text, en, where=None):
        from .core.sentences import sentence_links
        return sentence_links(toks, self.lexicon, self.key_to_id, Everything(), text, self.groups,
                              self.gender_of, self.epos_to_id, self.lemma_ids, en, self.homs, None, where)

    def classify(self, toks, en=None, lowered=()):
        """Per counted token: (surface, lemma, word id or None, may link, token index).
        Names (capitalised), numerals, punctuation and symbols are skipped
        (not counted). A lowercase token the tagger calls PROPN is counted.
        A token with no pack id by its reading falls back to:
        - the pack phrase it sits in ("favor" of "por favor", "embargo" of
          "sin embargo"): that phrase's id;
        - spec.surface_reading_fallback: the most frequent other dictionary
          reading of the same surface that is a pack word (lowercase "leo"/
          "vuelve" tagged PROPN, "escucha" as a noun, "contenta" as
          contentar: leer, volver, escuchar, contento). Not for a
          sentence-initial PROPN: a name the truecaser lowered ("Lucía" is
          not lucir), nor a PROPN truecase_after lowered (`lowered`); such a
        name is declared in oop. `en` gates cue phrases as sentence_links
        does ("de nada" is a phrase only when the English says welcome)."""
        from .core.sentences import phrase_spans
        sp = self.spec
        resolved = self.lexicon.resolve_sentence(toks, self.groups)
        ranges = []
        _, ph_tok, _ = phrase_spans(toks, sp, self.key_to_id, en, ranges)
        tok_phrase = {i: pid for a, b, pid in ranges for i in range(a, b + 1) if i in ph_tok}
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
            cap = text_t[:1].isupper()
            name = (upos == "PROPN" or (r is not None and r[1] == "PROPN")) and cap
            if name or (sp.caps_mark_names and not was_initial and cap):
                continue
            if r is not None and r[1] == "NUM":
                continue
            if low in self.num_ids and r is not None and r[1] != "VERB" and r[0] != low:
                continue        # "venti minuti" read as the plural of vento: a numeral
            wid = self.key_to_id.get((low, "FORM")) or self.key_to_id.get((low, "INTJ"))
            lem = r[0] if r else low
            if not wid and r is not None and r[1] != "PROPN":
                wid = self.key_to_id.get(tuple(r))
                if wid is None and sp.drop_keys.get(tuple(r)):
                    wid = self.key_to_id.get(sp.drop_keys[tuple(r)])
                if wid is None and r[1] in sp.group_kpos:
                    wid = self.epos_to_id.get((r[0], sp.group_kpos[r[1]][0]))
            if not wid:
                wid = self.lemma_ids.get(lem) or self.lemma_ids.get(low)
            if not wid:
                wid = tok_phrase.get(i)
            if not wid and sp.surface_reading_fallback and not \
                    ((was_initial or i in lowered) and r is not None and r[1] == "PROPN"):
                alts = [(self.lexicon.zipf(l), l, g) for l, g in self.lexicon.readings(low)
                        if self.key_to_id.get((l, g)) or self.lemma_ids.get(l)]
                if alts:
                    _, l, g = max(alts)
                    wid = self.key_to_id.get((l, g)) or self.lemma_ids.get(l)
                    lem = l
            nxt = toks[i + 1][0].lower() if i + 1 < len(toks) else ""
            # compounds: "rispetto a/al..." is not the noun rispetto, "fine settimana" not la fine
            may_link = not (lem in PHRASE_HEADS and (nxt in PHRASE_HEADS[lem] or
                                                     sp.art_prep.get(nxt) in PHRASE_HEADS[lem]))
            out.append((text_t, lem, wid, may_link, i))
        return out

    def links_all(self, toks, text, en):
        """sentence_links, then a lemma fallback, with one word id per token:
        - a substring phrase (a "chars" record) owns its tokens: a
          single-token link inside it is dropped, and its id too unless it is
          linked elsewhere in the sentence (per favore is the phrase, not
          per + il favore). A token-level phrase keeps sentence_links'
          records (the leftover article of "a pesar del" stays);
        - the fallback: a counted token whose lemma is a pack word under
          another POS (molto/tutto as determiners, lontano as an adjective,
          po', mezza) links that word, but only a token no earlier link
          claimed (come already read as "how" is not also "as");
        - compound-preposition heads (rispetto a) never link.
        Returns (word ids, classify(toks), spans as make_spans, the indices
        of tokens that carry a link)."""
        where = []
        ws = list(self.links(toks, text, en, where))
        cl = self.classify(toks, en, self.lowered.get((text, en), ()))
        offsets = token_offsets(text, toks, self.spec.span_fold, self.spec.span_joiners)
        # a substring phrase (Italian multiword, "chars") owns the tokens it
        # covers: their single-token links go. A token-level phrase
        # (phrase_token_spans: es, de, id) already consumed its tokens in
        # sentence_links; a single-token record left there is the leftover
        # article of a contraction ("a pesar del": el) and stays. Both kinds
        # keep the fallback off their tokens.
        owned, spanned = set(), set()
        for kind, a, b, _wid in where:
            if kind == "chars":
                owned |= {i for i, o in enumerate(offsets) if o and a <= o[0] and o[1] <= b}
            elif b > a:
                spanned |= set(range(a, b + 1))
        recs = [r for r in where if not (r[0] == "tok" and r[1] == r[2] and r[1] in owned)]
        gone = {r[3] for r in where} - {r[3] for r in recs}
        ws = [w for w in ws if w not in gone]
        drop = {wid for _, _, wid, ok, _ in cl if wid and not ok}
        keep = {wid for _, _, wid, ok, _ in cl if wid and ok}
        ws = [w for w in ws if w not in drop or w in keep]
        # a compound head (fine in "fine settimana") links nothing at that token
        not_ok = {i for _, _, wid, ok, i in cl if not ok}
        recs = [r for r in recs if not (r[0] == "tok" and not_ok & set(range(r[1], r[2] + 1)))]
        claimed = owned | spanned | {i for r in recs if r[0] == "tok" for i in range(r[1], r[2] + 1)}
        extra = []
        for _, _, wid, ok, i in cl:
            if wid and ok and i not in claimed:
                claimed.add(i)
                recs.append(("tok", i, i, wid))
                if wid not in ws and wid not in extra:
                    extra.append(wid)
        ids = ws + extra
        return ids, cl, make_spans(text, offsets, recs, ids), claimed


def token_offsets(text, toks, fold=None, joiners=""):
    """Per token, its (start, end) in `text` (Python str offsets), or None.
    Tokens are found in order, case-insensitively (the tagger saw truecased
    text). Between two located tokens only non-alphanumeric text may be
    skipped; a token not found that way is None, and the next token may then
    skip at most the unlocated tokens' text (a tokenizer or fix_token rewrite
    of a surface resynchronises instead of drifting). A word token found after
    skipped text never starts inside a word, and while resynchronising an
    alphanumeric token must also end at a word end.

    fold (spec.span_fold): string normaliser applied to text and surfaces
    before matching, to the text one alphanumeric run (a word) or one other
    character at a time, so multi-character rules inside a word apply (fa:
    پائین = پایین, ابتداء = ابتدا). Offsets map back to `text`; a match
    ending where a folded word ends ends where the original word ends.
    joiners (spec.span_joiners): characters of the text that may sit between
    two characters of a surface (the tagger input rewrite removed them: fa
    "می روم" -> token میروم); at most one per token."""
    if fold is None:
        ftext, fmap, fend = text, None, None
    else:
        ftext, fmap, fend = _fold_map(text, fold)
    out, at, pending = [], 0, 0
    for tok in toks:
        surf = tok[0] or ""
        if fold is not None:
            surf = fold(surf)
        m = None
        if surf:
            if joiners:
                j = "[" + re.escape(joiners) + "]?"
                pat = j.join(re.escape(ch) for ch in surf)
            else:
                pat = re.escape(surf)
            for c in re.compile(pat, re.IGNORECASE).finditer(ftext, at):
                if sum(ch.isalnum() for ch in ftext[at:c.start()]) > pending:
                    break
                if joiners and sum(ch in joiners for ch in c.group(0)) > 1:
                    continue
                if c.start() != at and surf[:1].isalnum() and ftext[c.start() - 1:c.start()].isalnum():
                    continue    # not after a skip: never start inside a word ("e" in mercato)
                if pending and surf[-1:].isalnum() and ftext[c.end():c.end() + 1].isalnum():
                    continue    # resyncing: the token must end where a word ends
                m = c
                break
        if m is None:
            out.append(None)
            pending += len(surf)
            continue
        at, pending = m.end(), 0
        if fmap is None:
            out.append((m.start(), m.end()))
        else:
            out.append((fmap[m.start()], fend.get(m.end(), fmap[m.end() - 1] + 1)))
    return out


def _fold_map(text, fold):
    """fold applied per alphanumeric run and per other character. Returns
    (folded text, folded index -> text index, {folded end of a run: text end
    of the run})."""
    ftext, fmap, fend = [], [], {}
    i = 0
    while i < len(text):
        j = i + 1
        if text[i].isalnum():
            while j < len(text) and text[j].isalnum():
                j += 1
        run = text[i:j]
        fr = fold(run)
        if j - i == 1:
            fmap += [i] * len(fr)
        else:
            done = 0            # folded chars of the run mapped so far
            for k in range(1, len(run) + 1):
                n = min(len(fold(run[:k])), len(fr)) if k < len(run) else len(fr)
                fmap += [i + k - 1] * max(0, n - done)
                done = max(done, n)
        ftext.append(fr)
        if fr and j - i > 1:
            fend[len(fmap)] = j
        i = j
    return "".join(ftext), fmap, fend


def utf16_index(text, i):
    """Python str index -> UTF-16 code-unit index (a JavaScript string index)."""
    return i + sum(1 for ch in text[:i] if ord(ch) > 0xFFFF)


def make_spans(text, offsets, recs, ids):
    """Link records (sentence_links `where` entries) -> sorted, non-overlapping
    [[start, end, wordId], ...] in UTF-16 code units. Only ids in `ids` get
    spans; a record whose token has no offset is skipped. Overlaps keep the
    longer span (per start, earliest first), so "per favore" beats favore."""
    idset = set(ids)
    cand = []
    for kind, a, b, wid in recs:
        if wid not in idset:
            continue
        if kind == "chars":
            se = (a, b)
        elif offsets[a] is not None and offsets[b] is not None:
            se = (offsets[a][0], offsets[b][1])
        else:
            continue
        if se[1] > se[0] and text[se[0]:se[1]].strip():
            cand.append((se[0], se[1], wid))
    cand.sort(key=lambda c: (-(c[1] - c[0]), c[0]))
    keep = []
    for c in cand:
        if not any(c[0] < k[1] and k[0] < c[1] for k in keep):
            keep.append(c)
    keep.sort()
    return [[utf16_index(text, a), utf16_index(text, b), wid] for a, b, wid in keep]


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
    n_spans = n_ids = 0
    unplaced = []       # (passage id, sentence index, headword, id) linked but with no span
    ids = set()
    lk.pretag([(t, en) for p in src["passages"] for t, en in p["sentences"]] +
              [(qt, "") for p in src["passages"] for q in p["questions"] for qt in [q["q"]] + (q["options"] or [])])
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
        used_oop = set()     # declared oop lemmas met as names or in questions/options
        for t, en in p["sentences"]:
            toks = lk.tag(t, en)
            ws, cl, spans, linked_toks = lk.links_all(toks, t, en)
            sents.append({"t": t, "en": en, "words": ws, "spans": spans})
            placed = {sp_[2] for sp_ in spans}
            n_spans += len(spans)
            n_ids += len(ws)
            unplaced += [(pid, len(sents) - 1, shipped[w]["w"], w) for w in ws if w not in placed]
            for surf, lem, wid, _ok, i in cl:
                if wid is None and str(oop_ok.get(lem, "")).startswith("name"):
                    used_oop.add(lem)
                    continue    # a declared name the truecaser lowered ("Bruno" -> bruno)
                counted.append(wid is not None)
                linked += wid is not None and i in linked_toks
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
                for surf, lem, wid, _ok, _i in lk.classify(lk.tag(qt), None, lk.lowered.get((qt, ""), ())):
                    if wid is None and lem in oop_ok:
                        used_oop.add(lem)
                    if wid is None and lem not in oop_ok:
                        qe.append(f"out-of-pack {lem!r} in {qt!r}")
                    elif wid is not None and lv_rank[lv_of[wid]] > lv_rank[lv]:
                        above.setdefault(lv_of[wid], set()).add(shipped[wid]["lemma"])
            perr += [f"q{j}: {x}" for x in qe]
            qs.append({"q": q["q"], "en": q["en"], "type": q["type"], "options": q["options"] if q["type"] == "mc" else None,
                       "answer": q["answer"], "words": wids, "sentence": si})
        stale = sorted(set(oop_ok) - set(oop) - used_oop)
        if stale:
            perr.append(f"oop lists lemmas used nowhere: {stale}")
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
    n_sent = sum(len(p["sentences"]) for p in passages)
    print(f"passages: {n_sent} sentences, {n_spans} spans; {n_ids - len(unplaced)} linked words with a span, "
          f"{len(unplaced)} without", file=out)
    for pid, si, w, wid in unplaced:
        print(f"  no span: {pid} s{si} {w} ({wid})", file=out)
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
