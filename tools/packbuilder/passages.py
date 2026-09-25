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

<repo> may also be a flat pack directory (pack.json, words.json and
passages_src.json together; zh: packs/zh), see layout(); a spec with
passage_linker (zh) supplies its own linker and no link context is built.

The link context (lexicon, word keys) is rebuilt from the cached corpus the
same way `build` builds it, verified against pack/words.json, and pickled
under <repo>/.cache/derived/ keyed by the builder source and pack files.

Source format (tools/passages_src.json):
    {"rules": {"coverage": {"A1": 0.95, ...}, "budget": {"A1": ["A2", 3], ...}},
     "passages": [{"id", "lv", "title", "sentences": [[it, en], ...],
                   "oop": {lemma: reason}, "names": [declared name, ...] (optional),
                   "questions": [{"q", "en", "type",
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
import unicodedata
from collections import Counter
from pathlib import Path

from .core.lexicon import SKIP_UPOS
from .core.util import write_json
from .langs.base import LanguageSpec

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
# form_base: kaikki POS -> resolve group; inflection tags; derivation lines
KPOS_GROUP = {"noun": "NOUN", "verb": "VERB", "adj": "ADJ", "adv": "ADV", "pron": "PRON", "det": "DET",
              "article": "DET", "prep": "ADP", "conj": "CONJ", "num": "NUM", "intj": "INTJ", "particle": "PART",
              "name": "PROPN"}
INFLECTION_TAGS = {"plural", "singular", "feminine", "masculine", "participle"}
DERIVATION_RE = re.compile(r"\b(?:diminutive|augmentative|pejorative|verbal noun|agent noun|nominali[sz]ation|"
                           r"alternative|abbreviation|ellipsis|synonym|clipping)\b", re.I)
FEMALE_EQ_RE = re.compile(r"\bfemale equivalent of\b", re.I)
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
    state = {k: v for k, v in spec.__getstate__().items() if k != "repo"}   # __getstate__: ja drops its Sudachi tokenizer
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
        # passage rules that read a word's gloss (fr passage_fallback_ok) see
        # the build's gloss, never a display-only one (tools/gloss_display.json,
        # merged into words.json after linking): no display file, no change
        from .core.words import load_gloss_display
        disp = load_gloss_display(getattr(spec, "repo", None), getattr(spec, "gloss_display_file", "tools/gloss_display.json"))
        if disp:
            shipped = {wid: ({**w, "en": self.by_id[wid]["en"]}
                             if f"{w['lemma']}|{w['pos']}" in disp and "en" in self.by_id.get(wid, {}) else w)
                       for wid, w in shipped.items()}
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
        # a token whose lemma is an article (de relative/demonstrative der, the
        # numeral "ein oder zwei") and no other pack word links the article entry
        self.art_ids = {w["_key"][0]: w["id"] for w in words if w["pos"] == "art"}
        # spec.passage_adverb_from: a pack adverb by its folded spelling -> its build lemma
        self.adverbs = {spec.fold(k[0]): k[0] for k in self.key_to_id if k[1] == "ADV"} \
            if getattr(spec, "passage_adverb_from", ()) else {}
        self.homs = None
        if spec.homograph_by_translation:
            from .core.sentences import homograph_table
            self.homs = homograph_table([dict(w, _key=tuple(w["_key"])) for w in words], spec)
        # spec.passage_post_resolve: passage-only resolve rules, after post_resolve,
        # for classify and sentence_links alike (the build's resolve is untouched).
        # passage_mode is True for the whole call, so post_resolve may gate
        # passage-only rules inside it (de); the corpus build never sets it.
        # The spec is the lexicon's current one (load_context rebinds it), and
        # the flag's prior value comes back even when resolving raises
        lex = self.lexicon
        if lex is not None and not getattr(lex, "_passage_wrapped", False):
            orig = lex.resolve_sentence

            def resolve_sentence(toks, groups=None):
                sp = getattr(lex, "spec", None) or spec
                prior = getattr(sp, "passage_mode", False)
                sp.passage_mode = True
                try:
                    return sp.passage_post_resolve(toks, orig(toks, groups))
                finally:
                    sp.passage_mode = prior
            lex.resolve_sentence = resolve_sentence
            lex._passage_wrapped = True
        self.tagged = {}     # (text, en, names) -> tokens
        self.lowered = {}    # (text, en, names) -> indices of tokens truecase_after lowered

    def pretag(self, items):
        """Tag (text, en) pairs, or (text, en, names) triples, in one tagger run (one model load; Stanza
        batches) through core.tag's shared entry point, exactly as stage_tag
        tags the corpus: truecase (passages only: spec.truecase_after, the
        first word of quoted/exclaimed speech, and spec.truecase_after_end,
        after a mid-text ! ?), spec.tag_text, the spec's tagger (spaCy or
        spec.tag_texts), fix_token, fix_sentence. A batch-dependent
        tag_texts sees only this batch: id's PROPN rescue counts lowercase
        uses across the texts it is given, so passage tagging has less
        evidence than the corpus build (measure when id passages are built).
        `names`: the passage's declared name words (source "names"). A
        sentence whose first word is one is not truecased ("Pierre" never
        becomes the noun pierre), a capitalised token spelled like one is
        PROPN, and spec.passage_text sees them. The tag cache is keyed by
        (text, en, names)."""
        from .core.tag import doc_tokens, tag_docs, truecase, truecase_after
        sp = self.spec
        keys = [(k[0], k[1], frozenset(k[2]) if len(k) > 2 else frozenset()) for k in items]
        todo = list(dict.fromkeys(k for k in keys if k not in self.tagged))
        if not todo:
            return
        # passage tagging (spec.passage_tagging, core.util.derived_write_ok):
        # no derived cache may change while passage texts go through the
        # tagger (a cache built from tagger input, keyed by the corpus, would
        # hold passage text: ja word groups). Writers check the flag; the
        # tripwire below fails the run if any derived file changed anyway
        derived = sp.repo / ".cache" / "derived" if getattr(sp, "repo", None) else None
        before = _derived_state(derived)
        prior = getattr(sp, "passage_tagging", False)
        sp.passage_tagging = True
        try:
            self._pretag(todo)
        finally:
            sp.passage_tagging = prior
        after = _derived_state(derived)
        changed = sorted(p for p in set(before) | set(after) if before.get(p) != after.get(p))
        if changed:
            raise SystemExit(f"passages: tagging passage texts changed derived cache files {changed}; "
                             "guard their writer with core.util.derived_write_ok(spec)")

    def _pretag(self, todo):
        from .core.tag import doc_tokens, tag_docs, truecase, truecase_after
        sp = self.spec
        known = (lambda w: bool(self.lexicon.readings(w))) if sp.truecase_after_end else None
        base = []
        for t, _en, names in todo:
            first = sp.word_re.search(t)
            base.append(t if names and first and first.group(0) in names else
                        truecase(t, self.low, self.cap, sp.word_re))
        after = [truecase_after(b, self.low, self.cap, sp.word_re, sp.truecase_after, sp.truecase_after_end, known)
                 for b in base]
        texts = [sp.tag_text(sp.passage_text(a, names, self.lexicon) if hasattr(sp, "passage_text") else a)
                 for a, (_t, _en, names) in zip(after, todo)]
        docs, fields = tag_docs(sp, texts, n_process=1)
        for (t, en, names), doc, b, a in zip(todo, docs, base, after):
            key = (t, en, names)
            self.tagged[key] = toks = self.retag(doc_tokens(sp, doc, fields, ["passage", t, None, en, None, None]),
                                                 names)
            # tokens truecase_after lowered: to classify they are like a
            # sentence start (a lowered name is not a pack verb: «¡Leo, ven!»)
            moved = {j for j, (x, y) in enumerate(zip(b, a)) if x != y}
            lowered = set()
            if moved:
                offs = token_offsets(a, toks, sp.span_fold, sp.span_joiners)
                lowered = {i for i, o in enumerate(offs) if o and o[0] in moved}
            self.lowered[key] = lowered

    def retag(self, toks, names=frozenset()):
        """Passage-only token rules after the shared tagging (the corpus build
        never sees them): spec.passage_retag (ru: correlative Тому, кто;
        стоит/стоять; capitalised Новый год; меньше), then the adverb rule: a
        token read with a POS in spec.passage_adverb_from (ru: ADJ, NUM) whose
        surface is spelled like a pack adverb (after spec.fold) is that adverb
        (хорошо, лучше, тихо, странно, больше: not хороший, тихий, the numeral).
        First, a capitalised token spelled like a declared name is PROPN."""
        sp = self.spec
        own = getattr(type(sp), "passage_retag", LanguageSpec.passage_retag)
        if own is LanguageSpec.passage_retag and not self.adverbs and not names:
            return toks         # nothing to rewrite: the tagged tokens as they are
        toks = [list(t) for t in toks]
        for t in toks:
            if t[0] in names and t[0][:1].isupper():
                t[2] = "PROPN"      # a declared name (Pierre, not la pierre)
        if hasattr(sp, "passage_retag"):
            # spec.passage_retag_names (ko, opt-in): the hook also gets the
            # declared names (Hangul has no capitals to mark them)
            toks = sp.passage_retag(toks, names) if getattr(sp, "passage_retag_names", False) else sp.passage_retag(toks)
        for t in toks if self.adverbs else ():
            lem = self.adverbs.get(sp.fold(t[0].lower()))
            if lem and t[2] in sp.passage_adverb_from:
                t[1], t[2] = lem, "ADV"
        return toks

    def tag(self, text, en="", names=frozenset()):
        key = (text, en, frozenset(names))
        if key not in self.tagged:
            self.pretag([key])
        return self.tagged[key]

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
        # spec.passage_uncounted (ja): grammar tokens outside the pack (ん,
        # れる, たり, ている's aux verbs) are not counted when they link nothing
        uncounted = sp.passage_uncounted(toks, resolved) if hasattr(sp, "passage_uncounted") else set()
        ranges = []
        _, ph_tok, _ = phrase_spans(toks, sp, self.key_to_id, en, ranges)
        tok_phrase = {i: pid for a, b, pid in ranges for i in range(a, b + 1) if i in ph_tok}
        no_link = sp.passage_no_link(toks) if hasattr(sp, "passage_no_link") else set()
        # spec.passage_phrase_ranges (fr MWES): a part of an expression
        # resolved on its anchor ("-ce", "qu'" of est-ce qu') reads as it
        ranges_mwe = sp.passage_phrase_ranges(toks) if hasattr(sp, "passage_phrase_ranges") else []
        tails = {j: anc for a, b, anc in ranges_mwe for j in range(a, b + 1) if j != anc}
        alias = getattr(sp, "passage_lemma_alias", {})
        out = []
        initial = True
        for i, (text_t, sl, upos, ms) in enumerate(toks):
            if upos in SKIP_UPOS:
                # an ellipsis ends a sentence too ("Так... Вижу"): the next
                # capital is not a name
                if text_t in ("!", "?", ":") or (text_t and set(text_t) <= {".", "…"}):
                    initial = True
                continue
            was_initial, initial = initial, False
            if any(ch.isdigit() for ch in text_t) or not any(ch.isalpha() for ch in text_t):
                continue
            r = resolved[i]
            if i in tails and resolved[tails[i]] is not None and tuple(resolved[tails[i]]) in self.key_to_id:
                r = resolved[tails[i]]
            low = text_t.lower()
            if r is None and i and getattr(sp, "passage_particle_links", False):
                # a separable particle post_resolve rejoined to its verb ("steht
                # ... auf" -> aufstehen, particle set to None) is that verb
                for j in range(i - 1, -1, -1):
                    rj = resolved[j]
                    if toks[j][0] in (".", "!", "?", ";"):
                        break
                    if rj and rj[1] == "VERB" and rj[0].startswith(low) and len(rj[0]) > len(low) \
                            and not toks[j][0].lower().startswith(low):
                        r = rj
                        break
            cap = text_t[:1].isupper()
            name = (upos == "PROPN" or (r is not None and r[1] == "PROPN")) and cap
            if name or (sp.caps_mark_names and not was_initial and cap):
                continue
            if r is not None and r[1] == "NUM":
                continue
            if low in self.num_ids and r is not None and r[1] != "VERB" and r[0] != low:
                continue        # "venti minuti" read as the plural of vento: a numeral
            # a token read as a verb is not the interjection spelled like it
            # ("Ich bitte Sie": bitten, not bitte)
            wid = self.key_to_id.get((low, "FORM")) or \
                (self.key_to_id.get((low, "INTJ")) if not (r and r[1] == "VERB") else None)
            lem = r[0] if r else low
            if not wid and r is not None and r[1] != "PROPN":
                wid = self.key_to_id.get(tuple(r))
                if wid is None and sp.drop_keys.get(tuple(r)):
                    wid = self.key_to_id.get(sp.drop_keys[tuple(r)])
                if wid is None and r[1] in sp.group_kpos:
                    wid = self.epos_to_id.get((r[0], sp.group_kpos[r[1]][0]))
            vetoed = False
            if not wid:
                wid = self.lemma_ids.get(lem) or self.lemma_ids.get(low) or \
                    self.lemma_ids.get(alias.get(lem)) or self.art_ids.get(lem)
                if wid and getattr(sp, "nouns_capitalised", False) and self.by_id[wid]["pos"] == "noun" and text_t[:1].islower():
                    wid = None      # de: a lowercase token never falls back to a noun (meisten is not Meister)
                if wid and r is not None and hasattr(sp, "passage_fallback_ok") and \
                        not sp.passage_fallback_ok(self.lexicon, tuple(r), self.shipped[wid], en or ""):
                    wid, vetoed = None, True   # fr: la ferme (farm) is not the adjective ferme (firm)
            if not wid and not vetoed and getattr(sp, "passage_form_base", False):
                # the vetoed word never comes back through the surface's
                # form-of line (sons "plural of son" is not the determiner son),
                # and a form_base hit passes the same guard with its own reading
                hit = self.form_base(lem, low)
                if hit and (not hasattr(sp, "passage_fallback_ok") or
                            sp.passage_fallback_ok(self.lexicon, hit[1:], self.shipped[hit[0]], en or "")):
                    wid, lem = hit[0], hit[1]
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
                                                     sp.art_prep.get(nxt) in PHRASE_HEADS[lem])) \
                and i not in no_link        # spec.passage_no_link: ru "друг другу" is not friend
            if wid is None and i in uncounted:
                continue
            out.append((text_t, lem, wid, may_link, i))
        return out

    def form_base(self, *keys):
        """(word id, base lemma, group) of the pack word an unresolved
        lemma/surface is an inflected form of (spec.passage_form_base), or
        None. Inflection lines only: a form-of sense tagged plural, singular,
        feminine, masculine or participle ("plural of son", "past participle
        of danser", "inflection (feminine singular) allemand"); a "female
        equivalent of X" line or a feminine entry's g "m=X" only when the
        form is a regular feminine of X (spec.passage_feminine_suffixes: amie
        of ami, chanteuse of chanteur, not drôlesse of drôle). Derivations
        (diminutive, verbal noun, ...) never. The pack key with the entry's
        own POS wins (morte adj -> mort adj, not la mort); lemma_ids only
        when there is none. The first key with a hit decides."""
        sp = self.spec
        for k in keys:
            fallback = None
            for e in self.lexicon.E.get(k, []):
                group = KPOS_GROUP.get(e["p"], e["p"].upper())
                bases = []
                m = re.search(r"(?:^|\|)m=([^|]+)", e.get("g") or "")
                if m and _regular_feminine(k, m.group(1), sp):
                    bases.append(m.group(1))
                for sn in e["s"]:
                    if sn[3] != "form" or DERIVATION_RE.search(sn[0]):
                        continue
                    m = re.search(r"\b(?:of|\))\s+([^\s,;()]+)\s*$", sn[0])
                    if not m:
                        continue
                    if FEMALE_EQ_RE.search(sn[0]):
                        if _regular_feminine(k, m.group(1), sp):
                            bases.append(m.group(1))
                    elif INFLECTION_TAGS & set(sn[2]) or sn[0].startswith("inflection"):
                        bases.append(m.group(1))
                for b in bases:
                    if (b, group) in self.key_to_id:
                        return self.key_to_id[(b, group)], b, group
                    if fallback is None and b in self.lemma_ids:
                        fallback = (self.lemma_ids[b], b, group)
            if fallback:
                return fallback
        return None

    def links_all(self, toks, text, en, names=frozenset()):
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
        cl = self.classify(toks, en, self.lowered.get((text, en, frozenset(names)), ()))
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
        # spec.passage_names_never_link (id): a capitalised token of a declared
        # name never links, whatever sentence_links read it as ("Jawa Tengah"
        # is not tengah "middle", "Museum Nasional" not the noun museum);
        # opt-in, other languages keep their links
        # The test reads the sentence text: the tagger may lowercase the token
        # (id's PROPN rescue: "Tengah" -> tengah). Such tokens are not counted.
        nt = set()
        if getattr(self.spec, "passage_names_never_link", False) and names:
            nt = {i for i, o in enumerate(offsets) if o and text[o[0]:o[1]] in names and text[o[0]:o[0] + 1].isupper()}
            nspan = [offsets[i] for i in nt]

            def on_name(r):
                if r[0] == "tok":
                    return bool(nt & set(range(r[1], r[2] + 1)))
                return any(a < r[2] and r[1] < b for a, b in nspan)
            kept = [r for r in recs if not on_name(r)]
            gone_n = {r[3] for r in recs} - {r[3] for r in kept}
            recs = kept
            ws = [w for w in ws if w not in gone_n]
            cl = [c for c in cl if c[4] not in nt]
        # a multiword expression resolved on its anchor token (fr parce qu',
        # est-ce qu', au lieu du; spec.passage_phrase_ranges): one span over it
        for a, b, anc in (self.spec.passage_phrase_ranges(toks) if hasattr(self.spec, "passage_phrase_ranges") else []):
            hit = [r for r in recs if r[0] == "tok" and r[1] == r[2] == anc]
            if hit:
                recs = [r for r in recs if not (r[0] == "tok" and a <= r[1] and r[2] <= b)]
                recs.append(("tok", a, b, hit[0][3]))
                spanned |= set(range(a, b + 1))
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


def _derived_state(d):
    """{file name: (size, mtime_ns)} of a derived cache directory ({} if absent)."""
    if d is None or not d.is_dir():
        return {}
    return {p.name: (p.stat().st_size, p.stat().st_mtime_ns) for p in sorted(d.iterdir()) if p.is_file()}


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


def _regular_feminine(fem, masc, sp):
    """fem is masc with one of spec.passage_feminine_suffixes swapped in
    (("", "e"): ami -> amie; ("eur", "euse"): chanteur -> chanteuse)."""
    return any(masc.endswith(a) and fem == masc[:len(masc) - len(a)] + b
               for a, b in getattr(sp, "passage_feminine_suffixes", (("", "e"),)))


def utf16_index(text, i):
    """Python str index -> UTF-16 code-unit index (a JavaScript string index)."""
    return i + sum(1 for ch in text[:i] if ord(ch) > 0xFFFF)


def _is_mark(ch):
    return unicodedata.category(ch) in ("Mn", "Mc")


def _mark_bounds(text, a, b):
    """A span owns the combining marks (Unicode Mn/Mc) that follow its last
    character (fa لطفاً: the tanwin the folded surface lacks) and never starts
    on one. Text without combining marks (NFC Latin, Cyrillic) is unchanged."""
    while b < len(text) and _is_mark(text[b]):
        b += 1
    while a < b and _is_mark(text[a]):
        a += 1
    return a, b


def make_spans(text, offsets, recs, ids):
    """Link records (sentence_links `where` entries) -> sorted, non-overlapping
    [[start, end, wordId], ...] in UTF-16 code units. Only ids in `ids` get
    spans; a record whose token has no offset is skipped. Overlaps keep the
    longer span (per start, earliest first), so "per favore" beats favore.
    Each span's bounds pass _mark_bounds first (trailing combining marks join
    the span; none starts on one)."""
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
        se = _mark_bounds(text, *se)
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


def _q_words_in_sentence(lk, shipped, wids, sent):
    """Is any of a question's resolved word ids visible in its sentence: a span
    of it, or its headword or a lemma spelling in the text (case-folded)."""
    spanned = {x[2] for x in sent.get("spans", [])}
    t = sent["t"].casefold()
    for wid in wids:
        if wid in spanned:
            return True
        forms = {shipped[wid]["w"]} | set(lk.lemma_of.get(wid, ()))
        if any(f and f.casefold() in t for f in forms):
            return True
    return False


def resolve_q_words(lk, lemmas, sent_ids):
    out, errs = [], []
    for lem in lemmas:
        hit = [wid for wid in sent_ids if lem in lk.lemma_of[wid]]
        if not hit:
            errs.append(f"question word {lem!r} is not linked in its sentence")
        elif hit[0] not in out:
            out.append(hit[0])
    return out, errs


def layout(repo):
    """(source/report dir, pack dir) of a passages repo. A language repo keeps
    tools/passages_src.json and pack/words.json; a pack directory built outside
    the packbuilder (packs/zh) holds pack.json, words.json and the source and
    report beside them."""
    repo = Path(repo)
    if not (repo / "pack" / "words.json").exists() and (repo / "words.json").exists() \
            and (repo / "pack.json").exists():
        return repo, repo
    return repo / "tools", repo / "pack"


def run(spec, check_only=False, out=sys.stdout):
    repo = spec.repo
    tools_dir, pack_dir = layout(repo)
    src = json.loads((tools_dir / "passages_src.json").read_text())
    rules = {**DEFAULT_RULES, **src.get("rules", {})}
    shipped = {w["id"]: w for w in json.loads((pack_dir / "words.json").read_text())}
    for w in shipped.values():
        w.setdefault("lemma", w["w"])      # a pack without lemmas (zh): the headword
    # spec.passage_linker (zh): a language whose pack has no build context
    # supplies its own linker with the Linker interface
    lk = spec.passage_linker(shipped, pack_dir) if hasattr(spec, "passage_linker") else \
        Linker(spec, load_context(spec), shipped)
    lv_rank = {lv: i for i, lv in enumerate(spec.level_ids)}
    lv_of = {wid: w["lv"] for wid, w in shipped.items()}
    passages, rows, errors = [], [], []
    verbatim = {}       # level -> [mc questions, [(passage id, q index, key) found verbatim in the text]]
    q_absent = []       # (passage id, q index, words, sentence index): none of the words in the sentence
    n_spans = n_ids = 0
    unplaced = []       # (passage id, sentence index, headword, id) linked but with no span
    ids = set()
    # a linker's declared(p) (zh) widens the per-passage names into its own
    # segmentation units (names plus declared oop words)
    names_of = {id(p): lk.declared(p) if hasattr(lk, "declared") else
                frozenset(w for n in p.get("names", []) for w in n.split()) for p in src["passages"]}
    lk.pretag([(t, en, names_of[id(p)]) for p in src["passages"] for t, en in p["sentences"]] +
              [(qt, "", names_of[id(p)]) for p in src["passages"] for q in p["questions"]
               for qt in [q["q"]] + (q["options"] or [])])
    # titles: tagged in a batch of their own (the passage batch stays as it
    # was), for the report-only note below
    lk.pretag([(p["title"], "", names_of[id(p)]) for p in src["passages"]])
    for p in src["passages"]:
        pid, lv = p["id"], p["lv"]
        perr = []
        if pid in ids:
            perr.append("duplicate id")
        ids.add(pid)
        if lv not in lv_rank:
            perr.append(f"unknown level {lv}")
        # declared oop lemmas match the tagger lemma after spec.span_fold (ru:
        # ёлка = елка); the report shows the declared spelling
        ofold = getattr(spec, "span_fold", None) or (lambda x: x)
        oop_ok = {ofold(k): v for k, v in p.get("oop", {}).items()}
        oop_name = {ofold(k): k for k in p.get("oop", {})}
        names = names_of[id(p)]
        sents, counted, oop, above = [], [], Counter(), {}
        sent_toks = []
        linked = 0
        used_oop = set()     # declared oop lemmas met as names or in questions/options
        for t, en in p["sentences"]:
            toks = lk.tag(t, en, names)
            sent_toks.append(toks)
            ws, cl, spans, linked_toks = lk.links_all(toks, t, en, names)
            sents.append({"t": t, "en": en, "words": ws, "spans": spans})
            placed = {sp_[2] for sp_ in spans}
            n_spans += len(spans)
            n_ids += len(ws)
            unplaced += [(pid, len(sents) - 1, shipped[w]["w"], w) for w in ws if w not in placed]
            for surf, lem, wid, _ok, i in cl:
                lem = ofold(lem)
                if wid is None and str(oop_ok.get(lem, "")).startswith("name"):
                    used_oop.add(lem)
                    continue    # a declared name the truecaser lowered ("Bruno" -> bruno)
                counted.append(wid is not None)
                linked += wid is not None and i in linked_toks
                if wid is None:
                    oop[lem] += 1
                elif lv_rank[lv_of[wid]] > lv_rank[lv]:
                    above.setdefault(lv_of[wid], set()).add(shipped[wid]["lemma"])
        text = getattr(spec, "passage_join", " ").join(s["t"] for s in sents)
        cov = sum(counted) / len(counted) if counted else 0.0
        if cov < rules["coverage"][lv]:
            perr.append(f"coverage {cov:.3f} < {rules['coverage'][lv]}")
        unlisted = sorted(set(oop) - set(oop_ok))
        if unlisted:
            perr.append(f"out-of-pack lemmas without a reason: {[oop_name.get(k, k) for k in unlisted]}")
        # a linker's n_words (zh, unspaced): the sentences' tokens after segmentation
        nw = sum(lk.n_words(tk) for tk in sent_toks) if hasattr(lk, "n_words") else n_words(text)
        if getattr(spec, "passage_words_counted", False):
            nw = len(counted)       # ja (unspaced): the counted tokens after segmentation
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
                for surf, lem, wid, _ok, _i in lk.classify(lk.tag(qt, "", names), None, lk.lowered.get((qt, "", names), ())):
                    lem = ofold(lem)
                    if wid is None and lem in oop_ok:
                        used_oop.add(lem)
                    if wid is None and lem not in oop_ok:
                        qe.append(f"out-of-pack {lem!r} in {qt!r}")
                    elif wid is not None and lv_rank[lv_of[wid]] > lv_rank[lv]:
                        above.setdefault(lv_of[wid], set()).add(shipped[wid]["lemma"])
            perr += [f"q{j}: {x}" for x in qe]
            qs.append({"q": q["q"], "en": q["en"], "type": q["type"], "options": q["options"] if q["type"] == "mc" else None,
                       "answer": q["answer"], "words": wids, "sentence": si})
            # self-checks (report only, never errors)
            if wids and not _q_words_in_sentence(lk, shipped, wids, sents[si]):
                q_absent.append((pid, j, q["words"], si))
            if q["type"] == "mc" and isinstance(q["options"], list) and isinstance(q["answer"], int) \
                    and 0 <= q["answer"] < len(q["options"]):
                vb = verbatim.setdefault(lv, [0, []])
                vb[0] += 1
                key = str(q["options"][q["answer"]]).strip()
                if len(key) >= 4 and not any(ch.isdigit() for ch in key) and \
                        not any(t[2] == "NUM" for t in lk.tag(key, "", names)) and \
                        key.casefold() in getattr(spec, "passage_join", " ").join(t for t, _en in p["sentences"]).casefold():
                    vb[1].append((pid, j, key))
        # report only (the budget rule and the stale-oop check are unchanged):
        # title words, and question or option words classify does not count (a
        # numeral-like pack word: "Setengah jam"), that are out of the pack or
        # above the passage's level
        note = []
        title = p["title"]
        tnames = names_of[id(p)]
        ttoks = lk.tag(title, "", tnames)
        for surf, lem, wid, _ok, ti in lk.classify(ttoks, None, lk.lowered.get((title, "", tnames), ())):
            lem = ofold(lem)
            # numerals and names are not vocabulary: a numeral read, a declared
            # name, a capitalised word after the first
            if ttoks[ti][2] in ("NUM", "PROPN") or lem in lk.num_ids or surf in tnames or \
                    (ti and surf[:1].isupper()):
                continue
            if wid is None:
                if lem not in oop_ok:    # a declared oop word must still be used in the text (stale check)
                    note.append(f"title {surf!r}: out of pack")
            else:
                # a pack word spelled like the surface that is not the one read
                # (surprise / surpris, nouvelle "news" / nouveau): shown only when
                # both are above the level, as the word spelled like it
                w2 = lk.lemma_ids.get(surf.lower())
                if w2 and w2 != wid:
                    if lv_rank[lv_of[wid]] <= lv_rank[lv] or lv_rank[lv_of[w2]] <= lv_rank[lv]:
                        continue
                    wid = w2
                if lv_rank[lv_of[wid]] > lv_rank[lv]:
                    note.append(f"title {surf!r}: {shipped[wid]['lemma']} {lv_of[wid]}")
        if hasattr(lk, "passage_notes"):
            note += lk.passage_notes([t for t, _en in p["sentences"]], names)
        counted_q = {x for ls in above.values() for x in ls}
        for q in p["questions"]:
            for qt in [q["q"]] + (q["options"] or []):
                seen = {i for *_x, i in lk.classify(lk.tag(qt, "", names), None, lk.lowered.get((qt, "", names), ()))}
                for i, tk in enumerate(lk.tag(qt, "", names)):
                    if i in seen or not any(ch.isalpha() for ch in tk[0] or "") or tk[2] in ("PROPN", "PUNCT") or \
                            (tk[0] or "").lower() in lk.num_ids:     # a pack numeral (neuf "nine", not neuf "new")
                        continue
                    wid = lk.lemma_ids.get(tk[1]) or lk.lemma_ids.get((tk[0] or "").lower())
                    if wid and lv_rank[lv_of[wid]] > lv_rank[lv] and shipped[wid]["lemma"] not in counted_q:
                        note.append(f"{qt!r}: {shipped[wid]['lemma']} {lv_of[wid]} (not counted)")
        stale = sorted(oop_name[k] for k in set(oop_ok) - set(oop) - used_oop)
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
        # unspaced script (zh): the app's length is the linked word count
        ws_n = sum(len(s["words"]) for s in sents) if getattr(spec, "passage_unspaced", False) else len(text.split())
        rows.append({"id": pid, "lv": lv, "title": p["title"], "words": nw, "ws_words": ws_n, "cov": cov,
                     "counted": len(counted), "link": linked / len(counted) if counted else 0.0, "oop": dict(sorted((oop_name.get(k, k), n) for k, n in oop.items())),
                     "oop_reason": p.get("oop", {}),
                     "above": {k: sorted(v) for k, v in sorted(above.items())},
                     "q": Counter(q["type"] for q in qs), "err": perr, "note": list(dict.fromkeys(note))})
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
    # self-checks (report only): mc answer keys lifted verbatim from the text
    # (>= 4 characters, numerals exempt), questions whose words are not visible
    # in their sentence (no span and no surface spelling)
    for lv in sorted(verbatim, key=lambda x: lv_rank.get(x, 99)):
        n, hits = verbatim[lv]
        print(f"self-check: level {lv}: {len(hits)}/{n} mc keys verbatim in the passage text (>=4 chars, numerals exempt)"
              + (": " + ", ".join(f"{a} q{b} {c!r}" for a, b, c in hits) if hits else ""), file=out)
    for pid, j, ws, si in q_absent:
        print(f"self-check: {pid} q{j}: none of its words {ws} appears in sentence {si}", file=out)
    if errors:
        print(f"passages: {len(errors)} errors", file=out)
    # a linker's passage_ruby (zh), else the spec's passage_ruby(lk, ...) (ja):
    # per-token readings on sentences, titles, questions and options, returning
    # its report lines
    pnames = [names_of[id(p)] for p in src["passages"]]
    extra = lk.passage_ruby(passages, pnames) if hasattr(lk, "passage_ruby") else \
        spec.passage_ruby(lk, passages, pnames) if hasattr(spec, "passage_ruby") else []
    if not check_only:
        if errors:
            print("passages: not writing pack/passages.json (fix the errors first)", file=out)
            return 1
        write_json(pack_dir / "passages.json", passages)
        write_report(repo, rows, rules, tools_dir, getattr(spec, "passage_unspaced", False), extra)
        print(f"passages: wrote {len(passages)} passages", file=out)
    return 1 if errors else 0


def write_report(repo, rows, rules, tools_dir=None, unspaced=False, extra=()):
    tools_dir = tools_dir or repo / "tools"
    if rules["budget"] == DEFAULT_RULES["budget"]:
        budget = ["punctuation not counted). Level budget (passage + questions + options): A1 may use",
                  "<=3 A2 lemmas and no B1; A2 may use <=3 B1 lemmas; B1 may use anything in the pack."]
    else:
        parts = [f"{lv} may use <={n} {nxt} lemmas and nothing above" if nxt else f"{lv} may use anything in the pack"
                 for lv, (nxt, n) in rules["budget"].items()]
        budget = ["punctuation not counted). Level budget (passage + questions + options): " + "; ".join(parts) + "."]
    src_rel = "tools/passages_src.json" if layout(repo)[0] == Path(repo) / "tools" else "passages_src.json"
    lines = ["# Reading passages report", "",
             f"Generated by `python3 -m packbuilder passages <repo>` from `{src_rel}`.",
             "Coverage = tokens whose lemma is a pack word / counted tokens (names, numerals,"] + budget + [
             "Linked = tokens whose word id is also in the sentence's `words` (the stricter share:",
             "a pack lemma can go unlinked when the tagger reads it with another POS)."]
    if unspaced:
        lines += ["words = the builder's word count (the band rule: tokens after segmentation); ws_words =",
                  "linked words, the count the app shows for an unspaced pack (report only).", ""]
    else:
        lines += ["words = the builder's word count (the band rule); ws_words = whitespace-separated",
                  "tokens of the passage text, the count the app shows (report only).", ""]
    for lv in sorted({r["lv"] for r in rows}):
        rs = [r for r in rows if r["lv"] == lv]
        covs = [r["cov"] for r in rs]
        lks = [r["link"] for r in rs]
        nws = [r["words"] for r in rs]
        wss = [r["ws_words"] for r in rs]
        qt = Counter()
        for r in rs:
            qt.update(r["q"])
        lines.append(f"- **{lv}**: {len(rs)} passages; words/passage {min(nws)}-{max(nws)} "
                     f"(median {statistics.median(nws)}); ws_words {min(wss)}-{max(wss)}; coverage min {min(covs):.3f}, median "
                     f"{statistics.median(covs):.3f} (rule >= {rules['coverage'][lv]}); linked min {min(lks):.3f}; questions "
                     f"mc {qt['mc']}, tf {qt['tf']}")
    lines += ["", "| id | lv | title | words | ws_words | coverage | linked | out-of-pack lemmas (reason) | higher-level lemmas |",
              "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        oop = ", ".join(f"{k} x{v} ({r['oop_reason'].get(k, '?')})" for k, v in r["oop"].items()) or "-"
        above = "; ".join(f"{k}: {', '.join(v)}" for k, v in r["above"].items()) or "-"
        lines.append(f"| {r['id']} | {r['lv']} | {r['title']} | {r['words']} | {r['ws_words']} | {r['cov']:.3f} | {r['link']:.3f} | {oop} | {above} |")
    notes = [f"- {r['id']}: " + "; ".join(r["note"]) for r in rows if r.get("note")]
    if notes:
        lines += ["", "Title words, and question/option words the budget does not count (a numeral-like",
                  "pack word), that are out of the pack or above the passage's level (report only;",
                  "the budget rule above is unchanged):", ""] + notes
    if extra:
        lines += [""] + list(extra)
    path = tools_dir / "REPORT_passages.md"
    manual = ""
    if path.exists() and MANUAL_MARK in path.read_text():
        manual = path.read_text().split(MANUAL_MARK, 1)[1]
    path.write_text("\n".join(lines) + "\n\n" + MANUAL_MARK + (manual or "\n"))


def main(repo, lang=None, check_only=False):
    from .langs import get_spec
    repo = Path(repo).resolve()
    if lang is None:
        lang = json.loads((layout(repo)[1] / "pack.json").read_text())["key"]
    return run(get_spec(lang, str(repo)), check_only)
