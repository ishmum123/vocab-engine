"""Token resolution: (surface, spaCy lemma, UPOS) -> (lemma, POS group),
validated against the Wiktionary lexicon, with context rules on top of the
tagger. Language tables (clitics, articles, copulas...) come from the spec;
an empty table switches its rule off."""
import re
from collections import Counter

GROUP_OF = {"AUX": "VERB", "CCONJ": "CONJ", "SCONJ": "CONJ"}
SKIP_UPOS = {"PUNCT", "SYM", "X", "SPACE"}
GROUP_LABEL = {"NOUN": "noun", "VERB": "verb", "ADJ": "adj", "ADV": "adv", "DET": "det",
               "ADP": "prep", "PRON": "pron", "CONJ": "conj", "NUM": "num", "INTJ": "intj",
               "PART": "part"}
CONTENT_GROUPS = {"NOUN", "VERB", "ADJ", "ADV"}
FUNCTION_UPOS = {"DET", "ADP", "PRON", "CCONJ", "SCONJ", "AUX", "PART"}
INFORMAL_TAGS = {"informal", "slang", "vulgar", "derogatory", "offensive", "colloquial",
                 "humorous", "euphemistic"}
KPOS_GROUP = {"noun": "NOUN", "verb": "VERB", "adj": "ADJ", "adv": "ADV", "pron": "PRON",
              "det": "DET", "article": "DET", "prep": "ADP", "conj": "CONJ", "num": "NUM",
              "intj": "INTJ"}
# senses carrying one of these rank last; the spec adds its regional tags
BASE_DEMOTE_TAGS = {"archaic", "obsolete", "rare", "dated", "historical", "regional", "dialectal"}
# an entry whose every sense carries one of these is not a learner lemma
# (giuro "oath" [Tuscany, literary], bisogna "matter" [literary])
BASE_MARKED_TAGS = {"archaic", "obsolete", "dated", "historical", "regional", "dialectal", "literary",
                    "poetic"}
RARE_ZIPF = 2.5
RARE_MARGIN = 1.5


def group_of(upos):
    return GROUP_OF.get(upos, upos)


def header_tags(ent):
    """Tags kaikki copies onto every sense from headword-level qualifiers
    (stazione 'f,m<l:archaic>', gente [archaic, poetic] on all 6 senses).
    They qualify an alternative form or gender, not the senses."""
    ht = set(re.findall(r"[A-Za-z-]+", " ".join(re.findall(r"<[^>]*>", ent.get("g", "")))))
    if ht & {"outdated", "old-fashioned", "obsolescent"}:
        ht |= {"archaic", "dated", "obsolete"}       # kaikki's normalised names for these
    defs = [set(sn[2]) for sn in ent["s"] if sn[3] == ""]
    if len(defs) >= 3:
        ht |= set.intersection(*defs)
    return ht


def sense_tags(ent, sn):
    return set(sn[2]) - ent["ht"]


def demote_tags(spec):
    return BASE_DEMOTE_TAGS | spec.regional_tags


class Lexicon:
    def __init__(self, lex, spec):
        self.spec = spec
        self.demote = demote_tags(spec)
        self.marked = BASE_MARKED_TAGS | spec.regional_tags
        self.E = lex["entries"]
        for ents in self.E.values():
            for e in ents:
                e["ht"] = header_tags(e)
        self.F = lex["formmap"]
        self.names = set(lex["names"])
        self._cache = {}
        self._hp = {}
        self._zipf = {}
        self.n_unresolved = Counter()
        self.n_clitic = 0
        self.n_num_as_verb = 0
        self.n_rare_override = 0
        self.n_after_article = 0
        self.n_copula_adj = 0
        self.n_pron_as_article = 0
        self.n_imperative = 0

    # ---- word frequency -------------------------------------------------
    def zipf(self, w):
        if w not in self._zipf:
            from wordfreq import zipf_frequency
            self._zipf[w] = zipf_frequency(w, self.spec.wordfreq_code)
        return self._zipf[w]

    def best_by_freq(self, cands):
        """Deterministic tie-break between dictionary-valid lemmas: the more
        frequent word (wordfreq), then alphabetical."""
        from wordfreq import zipf_frequency
        lang = self.spec.wordfreq_code
        return sorted(cands, key=lambda c: (-zipf_frequency(c, lang), c))[0]

    def verbs_only(self, cands):
        return {c for c in cands if self.spec.is_verb_lemma(c)}

    # ---- entries ----------------------------------------------------------
    def entry_usable(self, ent):
        # a translation recovered from a form-of line ("...of molto; more")
        # glosses the word but does not make the entry a lemma of its own
        defs = [s for s in ent["s"] if s[3] == "" and "from-form-sense" not in s[2]]
        if not defs or all(sense_tags(ent, s) & self.marked for s in defs):
            return False            # no senses, or archaic/literary/regional-only
        has_form = any(s[3] in ("form", "alt") for s in ent["s"])
        if not has_form:
            return True
        # "female equivalent of X" + only an informal/archaic extra sense
        # (bambina -> "babe") is a feminine-of, not a lemma in its own right
        return any(not (sense_tags(ent, s) & (self.demote | INFORMAL_TAGS)) for s in defs)

    def usable_entries(self, word, kpos):
        return [e for e in self.E.get(word, []) if (kpos is None or e["p"] in kpos) and self.entry_usable(e)]

    def chase(self, word, kpos, depth=0):
        """Follow form/alt/compound pointers until a usable lemma entry."""
        if self.usable_entries(word, kpos):
            return word
        if depth >= 3:
            return None
        for tgt, pos, kind in self.F.get(word, []):
            if kpos is None or pos in kpos:
                r = self.chase(tgt, kpos, depth + 1)
                if r:
                    return r
        return None

    def candidates(self, s, kpos):
        c = set()
        if self.usable_entries(s, kpos):
            c.add(s)
        for tgt, pos, kind in self.F.get(s, []):
            if kpos is None or pos in kpos:
                r = self.chase(tgt, kpos)
                if r:
                    c.add(r)
        return c

    def readings(self, s):
        """All dictionary-valid (lemma, group) readings of a surface."""
        out = set()
        for pos, grp in KPOS_GROUP.items():
            for lem in self.candidates(s, [pos]):
                if grp != "VERB" or self.spec.is_verb_lemma(lem):
                    out.add((lem, grp))
        return sorted(out)

    def historic_past(self, s):
        """Wiktionary lists the surface as a literary past form (it: passato
        remoto "cadde", "vendette"): catches tokens the tagger gave no Tense
        morph. Off unless the spec sets uses_historic_past_forms."""
        if not self.spec.uses_historic_past_forms:
            return False
        if s not in self._hp:
            self._hp[s] = any(sn[3] == "form" and {"historic", "past"} <= set(sn[2])
                              for e in self.E.get(s, []) if e["p"] == "verb" for sn in e["s"])
        return self._hp[s]

    def plural_pointer(self, s):
        return any(sn[3] == "form" and "plural" in sn[2]
                   for e in self.E.get(s, []) if e["p"] == "noun" for sn in e["s"])

    # ---- clitics / imperatives (off when spec.clitic_re is None) -------------
    def clitic_verb(self, s):
        """farlo -> fare, dimmi -> dire, portami -> portare, dirglielo -> dire."""
        clitic_re, mono = self.spec.clitic_re, self.spec.mono_imperative
        if clitic_re is None:
            return None
        stems = []
        cur = s
        for _ in range(2):
            m = clitic_re.match(cur)
            if not m:
                break
            cur, cl = m.group(1), m.group(2)
            stems.append((cur, cl))
        for stem, cl in stems:
            tries = [stem, stem + "e", stem + "'"]
            if len(stem) > 2 and stem[-1] == cl[0] and stem[:-1] in mono:
                # monosyllabic imperatives double the clitic consonant:
                # dimmi -> di', fallo -> fa', dacci -> da', stammi -> sta'
                self.n_clitic += 1
                return mono[stem[:-1]]
            if stem in mono and cl.startswith("gli"):
                self.n_clitic += 1
                return mono[stem]
            for t in tries:
                if len(t) < 2:
                    continue
                c = self.candidates(t, ["verb"])
                if c:
                    self.n_clitic += 1
                    return self.best_by_freq(c)
        return None

    def imperative_form(self, s):
        """Verb lemma if Wiktionary lists s as a second-person imperative."""
        for e in self.E.get(s, []):
            if e["p"] != "verb":
                continue
            for sn in e["s"]:
                if sn[3] == "form" and "imperative" in sn[2] and "second-person" in sn[2]:
                    c = self.verbs_only(self.candidates(s, ["verb"]))
                    if c:
                        return self.best_by_freq(c)
        return None

    def imperative_clitic(self, s):
        """s splits into an imperative verb form + enclitic ("fallo" = fa' + lo,
        "dimmi" = di' + mi, "portalo" = porta + lo)."""
        clitic_re, mono = self.spec.clitic_re, self.spec.mono_imperative
        if clitic_re is None:
            return False
        cur = s
        for _ in range(2):
            m = clitic_re.match(cur)
            if not m:
                return False
            cur, cl = m.group(1), m.group(2)
            stems = [cur, cur + "'"]
            if len(cur) > 2 and cur[-1] == cl[0]:
                stems += [cur[:-1], cur[:-1] + "'"]
            for st in stems:
                if st in mono or any(
                        sn[3] == "form" and "imperative" in sn[2]
                        for e in self.E.get(st, []) if e["p"] == "verb" for sn in e["s"]):
                    return True
        return False

    # ---- resolution ---------------------------------------------------------
    def resolve_sentence(self, toks, groups=None):
        """Resolve every token of a tagged sentence, with context rules on top
        of the tagger: a numeral that is also a verb form and is not followed
        by a noun is the verb ("Sei sicuro?", "Tu sei...": you are, not six)."""
        sp = self.spec
        def_forms = sp.article_forms.get(sp.definite_article, set())
        out = []
        for i, (text, sl, upos, ms) in enumerate(toks):
            if upos == "NUM" and text.isalpha():
                after = [t[2] for t in toks[i + 1:i + 4] if t[2] != "PUNCT"][:2]
                if after[:1] == ["ADJ"]:
                    after = after[1:]           # "sei belle ragazze"
                prev_tok = toks[i - 1][0] if i else "."
                prev = next((t[2] for t in reversed(toks[:i]) if t[2] != "PUNCT"), None)
                nominal = bool(after) and after[0] in ("NOUN", "NUM", "PROPN")
                clause_q = next((t[0] for t in toks[i + 1:] if t[0] in (".", "!", "?")), "") == "?"
                initial_question = prev_tok in (".", "!", "?", "…") and clause_q   # "Sei Elijah?"
                if prev in ("ADP", "DET"):
                    pass                        # "alle sei", "ogni sei mesi": the numeral
                elif prev == "PRON" or not nominal or initial_question:
                    c = self.verbs_only(self.candidates(text.lower(), ["verb"]))
                    if c:
                        self.n_num_as_verb += 1
                        out.append((self.best_by_freq(c), "VERB"))
                        continue
            if upos == "NOUN" and i:
                # predicate after a copula with no determiner is an adjective
                # ("sono fiera", "diventare matto"), not the noun homograph
                j = i - 1
                while j >= 0 and toks[j][2] == "ADV":
                    j -= 1
                if j >= 0 and toks[j][2] in ("AUX", "VERB"):
                    vr = self.resolve(*toks[j])
                    adj = self.candidates(text.lower(), ["adj"])
                    if vr and vr[0] in sp.copulas and adj:
                        a = self.best_by_freq(adj)
                        inflected = a != text.lower()
                        adj_major = groups is not None and groups.get(a) and \
                            groups[a]["ADJ"] > groups[a]["NOUN"]
                        if inflected or adj_major:
                            self.n_copula_adj += 1
                            out.append((a, "ADJ"))
                            continue
            low = text.lower()
            nxt = next((t for t in toks[i + 1:i + 3] if t[2] != "ADJ"), None)
            if upos == "PRON" and low in def_forms and nxt is not None and \
                    nxt[2] != "PUNCT" and self.candidates(nxt[0].lower(), ["noun"]) and \
                    not self.candidates(nxt[0].lower(), ["verb"]):
                # the dictionary decides, not the tag of the next word: the small
                # tagger calls "schiavo" a verb after "Lo" and "vidi" a noun after
                # "lo"; only a word with a noun and no verb reading counts
                # "Lo schiavo scappò": an article form before a noun is the article
                self.n_pron_as_article += 1
                out.append((sp.definite_article, "DET"))
                continue
            if upos == "NOUN" and (i == 0 or toks[i - 1][0] in (".", "!", "?", "…", ":", ";")) and \
                    i + 1 < len(toks) and \
                    toks[i + 1][2] == "DET" and self.imperative_form(low):
                # clause-initial noun homograph + determiner is an imperative
                # ("Traccia una linea", "Porta un ombrello")
                self.n_imperative += 1
                out.append((self.imperative_form(low), "VERB"))
                continue
            if upos in ("ADV", "VERB") and i and toks[i - 1][2] == "DET" and \
                    toks[i - 1][0].lower() in sp.all_article_forms:
                # right after an article the word is a noun ("gettò l'ancora")
                nouns = self.candidates(text.lower(), ["noun"])
                if nouns:
                    self.n_after_article += 1
                    out.append((self.best_by_freq(nouns), "NOUN"))
                    continue
            out.append(self.resolve(text, sl, upos, ms))
        return out

    def resolve(self, text, slemma, upos, morph=""):
        """Return (lemma, group) or None for punctuation/symbols/digits."""
        plur = upos == "NOUN" and "Number=Plur" in morph
        key = (text, slemma, upos, plur)
        if key in self._cache:
            return self._cache[key]
        r = self._resolve(text.lower(), slemma.lower(), upos, plur)
        if r and r[1] not in ("PROPN",) and self.zipf(r[0]) < RARE_ZIPF:
            # implausibly rare reading picked by the tagger ("carino" as a
            # form of cariare): take a far more common reading of the surface
            best = max((x for x in self.readings(text.lower()) if x[1] != r[1]),
                       key=lambda x: (self.zipf(x[0]), x), default=None)
            if best and self.zipf(best[0]) >= self.zipf(r[0]) + RARE_MARGIN:
                self.n_rare_override += 1
                r = best
        if r and r[1] == "VERB":
            base = self.spec.pronominal_base(r[0])      # farsi -> fare, muoversi -> muovere
            if base and any(not (sense_tags(e, sn) & self.demote) for e in self.usable_entries(base, ["verb"])
                            for sn in e["s"] if sn[3] == ""):
                r = (base, "VERB")
        self._cache[key] = r
        return r

    def _resolve(self, s, sl, upos, plur=False):
        sp = self.spec
        if upos in SKIP_UPOS or not sp.word_re.search(s):
            return None
        if any(ch.isdigit() for ch in s):
            return None
        g = group_of(upos)
        if " " in sl:
            sl = sl.split()[0]          # 'su il' (sulla), 'fare lo' (farlo)
        if g == "PROPN":
            return (s, "PROPN")
        kp = sp.group_kpos.get(g)
        if s in sp.art_prep:
            return (sp.art_prep[s], "ADP")  # sulla -> su, nell' -> in (also when tagged DET: "del pane")
        if g == "DET" and sl in sp.article_forms and s in sp.article_forms[sl]:
            return (sl, g)              # la/le/gli/l' -> il, una/un' -> uno
        cands = self.candidates(s, kp)
        if g == "VERB":
            cands = self.verbs_only(cands)
        if g == "NOUN" and s not in sp.pluralia_tantum and sl != s and (plur or self.plural_pointer(s)):
            if self.usable_entries(sl, kp):
                return (sl, g)          # giorni -> giorno (plural never its own lemma)
            cands.discard(s)
        if g == "NOUN" and s in cands:
            return (s, g)               # signora, soldi: the surface is its own noun lemma
        if g == "VERB" and s in cands:
            return (s, g)
        if g == "PRON" and s in sp.clitic_of:
            return (sp.clitic_of[s], g)    # mi -> io, ti -> tu (spaCy gives 'si' for ti)
        if sl in cands:
            return (sl, g)
        if len(cands) == 1:
            return (next(iter(cands)), g)
        if cands:
            return (self.best_by_freq(cands), g)
        if sp.clitic_re is not None and sp.clitic_re.match(s):
            v = self.clitic_verb(s)
            if v:
                return (v, "VERB")
        # nothing with the tagged POS: trust spaCy's lemma when it is a real headword
        if sl and self.usable_entries(sl, kp):
            return (sl, g)
        # ...else the surface's reading under another POS (tagger error:
        # "Lo giuro" tagged NOUN -> giurare)
        alt = self.readings(s)
        if alt:
            return max(alt, key=lambda r: (self.zipf(r[0]), r))
        self.n_unresolved[g] += 1
        return (sl or s, g)
