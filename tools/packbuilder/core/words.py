"""Stage words: candidate pool, entry/sense selection, second-POS entries,
-rsi (pronominal) display, feminine folding, level banding and id mapping."""
import json
import re
import time
from collections import Counter, defaultdict

from .english import en_stems
from .gloss import sense_candidates, compose_gloss, MAX_GLOSS, GLOSS_IGNORE
from .lexicon import CONTENT_GROUPS, GROUP_LABEL, demote_tags
from .tag import iter_tagged
from .util import log, stat

SECOND_ENTRY_SHARE = 0.20     # a second (lemma, POS) entry needs this share of the lemma's tokens
IMPERATIVE_INITIAL_SHARE = 0.5
FOLD_IGNORE = {"a", "an", "the", "of", "to", "one", "thing", "person", "female", "male", "woman", "man",
               "f", "m", "or", "and"}
COLLISION_SUPPORT = 0.75      # a replacement lead sense/alternative needs this share of the top score
SECOND_SENSE_OVERLAP = 0.25   # max share of a second POS's translations using the first entry's words
PRONOMINAL_SHARE = 0.5        # verbs used mostly with a reflexive clitic are shown as -rsi
EN_BAG_CAP = 400
POOL_KEYS = 6500   # distinct lemmas considered (all their POS keys)


def english_bags(tagged, lexicon, keys, en_by_sid, groups=None):
    """(lemma, group) -> (#sentences, Counter(English stem -> #sentences))."""
    keys = set(keys)
    bags = {k: [0, Counter()] for k in keys}
    for sid, toks in iter_tagged(tagged):
        seen = set()
        for r in lexicon.resolve_sentence(toks, groups):
            if r in keys and r not in seen:
                seen.add(r)
        if not seen or (lexicon.spec.untranslated_rows and not en_by_sid[sid]):
            continue
        stems = set(en_stems(en_by_sid[sid], keep_stop=True))
        for r in seen:
            b = bags[r]
            if b[0] < EN_BAG_CAP:
                b[0] += 1
                b[1].update(stems)
    return bags


def build_words(env, ctx):
    sp = env.spec
    lexicon, raw_upos, morph, blended = ctx["lexicon"], ctx["raw_upos"], ctx["morph"], ctx["blended"]
    low, cap = ctx["truecase"]
    from wordfreq import top_n_list, zipf_frequency
    en_top = set(top_n_list("en", 2000))
    demote = demote_tags(sp)

    gloss_dropped = []

    def compose(rows, lem=None):
        # spec.sensitive_gloss_re: a vulgar/sexual sense never leads or joins
        # the gloss while a clean sense exists (es mamar, perra)
        if sp.sensitive_gloss_re is not None and rows:
            clean = [r for r in rows if not sp.sensitive_gloss_re.search(r["g"])]
            if clean and len(clean) < len(rows):
                gloss_dropped.append(lem)
                rows = clean
        return compose_gloss(rows)

    def senses(e, g, df, nsent, closed):
        return sense_candidates(e, g, df, nsent, closed, ctx["en_bg"], ctx["en_bgn"], demote)

    lemma_groups = ctx["lemma_groups"]

    def share(lem, g):
        lg = lemma_groups.get(lem, Counter())
        tot = sum(c for gg, c in lg.items() if gg != "PROPN")
        return lg[g] / tot if tot else 0.0

    def gloss_words(gl):
        # exact English words: amica "friend" folds into amico "friend";
        # volta "time" stays apart from volto "face"
        return {x for x in re.findall(r"[a-z]+", re.sub(r"\(.*?\)", " ", gl.lower()))
                if x not in FOLD_IGNORE}

    def same_words(a, b):
        # "this, these" (PRON) vs "this, these" (DET): stopword-only glosses
        f = lambda x: set(en_stems(re.sub(r"\(.*?\)", " ", x), keep_stop=True)) - {"to", "a", "an", "the", "of"}
        return bool(f(a) & f(b))

    def gloss_stems(gl):
        return set(en_stems(re.sub(r"\(.*?\)", " ", gl))) - GLOSS_IGNORE

    def is_proper(lem):
        lg = lemma_groups.get(lem)
        tot = sum(lg.values()) if lg else 0
        if sp.propn_lowercase_rescue and low[lem] >= sp.propn_lowercase_rescue:
            return False        # es: tierra, dios, reino are common nouns too
        if tot and lg["PROPN"] / tot > 0.5:
            return True
        return sp.caps_mark_names and sp.caps_proper_pool and cap[lem] >= 3 and cap[lem] > low[lem]

    excluded = Counter()
    ex_examples = defaultdict(list)

    def exclude(reason, lem):
        excluded[reason] += 1
        if len(ex_examples[reason]) < 25:
            ex_examples[reason].append(lem)

    # words that occur mostly inside a fixed phrase the pack teaches as a whole
    # (es: embargo in "sin embargo", través in "a través de")
    bound = {}
    if sp.phrase_bound_share:
        texts = [r[1].lower() for r in ctx["rows_by_sid"].values()]
        if sp.phrase_token_spans and sp.art_prep:
            # "a pesar del" counts for "a pesar de"
            rx_c = re.compile(r"\b(" + "|".join(map(re.escape, sorted(sp.art_prep))) + r")\b")
            texts = [rx_c.sub(lambda m: f"{sp.art_prep[m.group(1)]} {sp.definite_article}", t) for t in texts]
        for phrase, parts in sp.multiword.items():
            rx = re.compile(r"\b" + re.escape(phrase) + r"\b")
            n = sum(1 for t in texts if rx.search(t))
            for p in parts:
                tot = sum(c for gg, c in lemma_groups.get(p, Counter()).items() if gg != "PROPN")
                if tot and n / tot >= sp.phrase_bound_share:
                    bound.setdefault(p, phrase)
        stat("phrase_bound_words", {k: bound[k] for k in sorted(bound)})

    # --- candidate pool: one key per lemma (its best-ranked POS), plus articles
    forced_keys = []
    for w, g in sp.forced:
        if g is None:
            lg = lemma_groups.get(w, Counter())
            opts = [(c, gg) for gg, c in lg.items() if gg != "PROPN"]
            g = max(opts)[1] if opts else "INTJ"
        forced_keys.append((w, g))
    forced_set = set(forced_keys)
    forced_lemmas = {k[0] for k in forced_keys}
    order = {}
    pool = []
    lemmas_in_pool = set()
    for i, (k, sc, sr, wr, subc) in enumerate(blended):
        order[k] = i
        lem, g = k
        if g == "PROPN" or k in sp.drop_keys or (g == "?" and not sp.keep_unseen_keys):
            continue
        is_article = g == "DET" and lem in sp.article_forms
        if lem in forced_lemmas and k not in forced_set and not is_article and \
                share(lem, g) < SECOND_ENTRY_SHARE:
            continue       # the forced POS wins for forced lemmas (e.g. rosa ADJ, sei NUM)
        if len(lemmas_in_pool) < POOL_KEYS or lem in lemmas_in_pool:
            pool.append(k)
            lemmas_in_pool.add(lem)
    for k in forced_keys:
        if k not in pool:
            pool.append(k)
    stat("pool_keys", len(pool))

    t0 = time.time()
    bags = english_bags(ctx["tagged"], lexicon, pool, ctx["en_by_sid"], lemma_groups)
    log(f"english bags for {len(pool)} keys ({time.time()-t0:.0f}s)")

    multi_pos = 0
    fem_glossed = []
    records = {}
    done_lemma = {}
    second_entries, pronominal, overridden, second_diag = [], [], [], []
    for k in pool:
        lem, g = k
        forced = k in forced_set
        is_article = g == "DET" and lem in sp.article_forms
        second = lem in done_lemma and not is_article
        displaced = None
        if second and not forced:
            if share(lem, g) < SECOND_ENTRY_SHARE:
                continue
            if len(done_lemma[lem]) >= 2:
                # the second slot goes to the POS with the larger corpus share
                # (come: ADV "how" 27% over CONJ 25%)
                prev = done_lemma[lem][1]
                if records[prev]["forced"] or share(lem, g) <= share(lem, prev[1]):
                    continue
                displaced = prev       # one entry per lemma (its best-ranked POS with a usable entry), plus
            #                a second POS holding >=20% of the lemma's tokens with a different sense
        if g == "PHRASE" or g == "FORM":
            records[k] = {"lemma": lem, "group": g, "pos": "phrase" if g == "PHRASE" else "verb",
                          "en": sp.fixed_gloss[k], "w": lem, "alt": None, "forced": True,
                          "entry_pos": None, "sense_idx": None, "gender": None}
            continue
        if k in sp.fixed_gloss and not lexicon.usable_entries(lem, sp.group_kpos.get(g)):
            # closed-class word whose Wiktionary entry is only form-of lines
            # (es: me "accusative of yo: me"): the fixed gloss is its entry
            done_lemma.setdefault(lem, []).append(k)
            records[k] = {"lemma": lem, "group": g, "en": sp.fixed_gloss[k], "forced": forced,
                          "pos_from_dict": False, "entry_pos": None, "sense_idx": None, "sense_score": 0.0,
                          "gender": None, "nsent": 0, "rows": [], "display": None, "base_en": None,
                          "fem_of": [], "fixed": True}
            continue
        if not forced:
            if lem in bound:
                exclude(f"bound in a fixed phrase the pack teaches ({bound[lem]})", lem); continue
            if is_proper(lem):
                exclude("proper noun (corpus PROPN/capitalised majority)", lem); continue
            if sp.is_profane(lem):
                exclude("profanity (hand list)", lem); continue
            if g == "INTJ":
                exclude("interjection (not in forced greetings)", lem); continue
            if g == "NUM" and lem not in sp.allowed_num:
                exclude(sp.numeral_exclusion, lem); continue
        if len([gg for gg in lemma_groups.get(lem, {}) if gg != "PROPN" and lemma_groups[lem][gg] >= 5]) > 1:
            multi_pos += 1
        kpos = sp.group_kpos.get(g) if g != "?" else None
        ents = lexicon.usable_entries(lem, kpos)
        if not ents and forced:
            ents = lexicon.usable_entries(lem, None)
        if not ents:
            exclude("no usable Wiktionary entry for corpus POS", lem); continue
        nsent, df = bags.get(k, [0, Counter()])
        closed = g not in CONTENT_GROUPS
        best = None
        for ei, e in enumerate(ents):
            rows = senses(e, g, df, nsent, closed)
            if not rows:
                continue
            top = rows[0]
            q = (top["demote"], 0 if top["score"] > 0 and not top["defn"] else 1 if top["score"] > 0 else 2,
                 top["defn"], -round(top["score"], 3), ei)
            if best is None or q < best[0]:
                best = (q, e, rows)
        if best is not None and best[0][1] > 0 and g != "ADJ":
            # only definitional senses ("used to call someone's attention"):
            # a translation-like sense under another POS header wins (ecco)
            for ei, e in enumerate(lexicon.usable_entries(lem, None)):
                if e in ents:
                    continue
                rows = senses(e, g, df, nsent, closed)
                if rows and not rows[0]["defn"]:
                    top = rows[0]
                    q = (top["demote"], 0 if top["score"] > 0 else 2, False, -round(top["score"], 3), 100 + ei)
                    if q < best[0]:
                        best = (q, e, rows)
        if best is None:
            exclude("no usable sense after cleaning", lem); continue
        _, ent, rows = best
        if (not forced and ent.get("b") and lem in en_top and
                sum(raw_upos.get(k, Counter()).values()) < 10):
            exclude(f"English loanword unattested in {sp.name_en} corpus", lem); continue
        if sp.strict_selection and not forced:
            if k[1] == "?":
                exclude("surface unseen in the tagged corpus (POS from dictionary only)", lem); continue
            if len(lem) < 2:
                exclude("single letter", lem); continue
            if lem in en_top and sum(raw_upos.get(k, Counter()).values()) < 10 and \
                    zipf_frequency(lem, sp.wordfreq_code) < zipf_frequency(lem, "en") - 1.0:
                exclude("English homograph rare in the tagged corpus (subtitle contamination)", lem); continue
        if sp.min_corpus_tokens and not forced and \
                sum(raw_upos.get(k, Counter()).values()) < sp.min_corpus_tokens:
            # fa: subtitle fragments, names, web-only words unattested in the tagged sentences
            exclude(f"fewer than {sp.min_corpus_tokens} tokens in the tagged corpus", lem); continue
        if sp.strict_selection and not forced and g == "NOUN" and ent["p"] not in ("noun", "name"):
            exclude("noun reading glossed only from another POS (not a noun)", lem); continue
        gloss, top = compose(rows, lem)
        tokens = sum(raw_upos.get(k, Counter()).values())
        if g == "NOUN" and not forced and tokens:
            # an imperative + clitic homograph ("Fallo subito." = do it, not the
            # noun "foul/phallus"): the tokens open the sentence with no
            # determiner (measured: fallo 94%, real nouns <=5%), or the noun's
            # only senses are vulgar
            if sp.imperative_homograph(lexicon, lem):
                noun_tags = [set(sn[2]) for e in lexicon.E.get(lem, []) if e["p"] == "noun"
                             for sn in e["s"] if not sn[3]]
                vulgar = bool(noun_tags) and all(t & {"vulgar", "offensive"} for t in noun_tags)
                if ctx["initial"][k] / tokens >= IMPERATIVE_INITIAL_SHARE or vulgar:
                    exclude("noun homograph of an imperative+clitic (sentence-initial or vulgar)", lem)
                    continue
        disp = None
        base_gloss = None
        active = tokens - ctx["refl"]["_stative"][k]
        if g == "VERB" and active >= 10 and ctx["refl"][k] / active >= PRONOMINAL_SHARE and \
                sp.pronominal_form(lem):
            # used mostly pronominally ("mi lamento", "si fida"): show the -rsi
            # verb with its own sense
            rsi = sp.pronominal_form(lem)
            prow = None
            for e in lexicon.usable_entries(rsi, ["verb"]):
                r2 = [r for r in senses(e, g, df, nsent, closed)
                      if not r["defn"]]
                if r2 and (prow is None or r2[0]["score"] > prow[0]["score"]):
                    prow = r2
            if prow is None:
                prow = [r for r in rows if r["tags"] & {"pronominal", "reflexive"}] or None
            if prow:
                base_gloss = gloss
                gloss, top = compose(prow, lem)
                disp = rsi
                pronominal.append(rsi)
        fem_of = []
        if g == "NOUN":
            # (target, via_noun): "female equivalent of amico" in the noun
            # entry, or only an adjective inflection line ("feminine singular
            # of santo"), which folds only into a same-meaning masculine noun
            fem_of = sorted({(m.group(1), e["p"] == "noun") for e in lexicon.E.get(lem, [])
                             if e["p"] in ("noun", "adj")
                             for sn in e["s"] if sn[3] == "form"
                             for m in [sp.fem_of_re.match(sn[0].lower())] if m})
        if g == "NOUN" and not forced:
            # Feminine forms with an extra sense of their own (la piccola "small
            # beer", l'amica "girlfriend", la fisica "physics"): compare the
            # corpus support for the masculine lemma's reading with the
            # entry's own senses.
            fem = sorted({m.group(1) for e in lexicon.E.get(lem, []) if e["p"] in ("noun", "adj")
                          for sn in e["s"] if sn[3] == "form"
                          for m in [sp.fem_of_re.match(sn[0].lower())] if m})
            drop = False
            for t in fem:
                t_adj = lemma_groups.get(t) and lemma_groups[t].most_common(1)[0][0] == "ADJ"
                tents = lexicon.usable_entries(t, ["adj"] if t_adj else ["noun"])
                tbest = None
                for te in tents:
                    trows = senses(te, g, df, nsent, closed)
                    if trows and (tbest is None or trows[0]["score"] > tbest[0]["score"]):
                        tbest = trows
                if not tbest or tbest[0]["demote"]:
                    continue
                if t_adj and top["defn"] and tbest[0]["score"] >= top["score"]:
                    drop = True          # nominalised adjective: la piccola = the little one
                elif not t_adj and tbest[0]["score"] >= 1.0 and tbest[0]["score"] > top["score"] * 1.5:
                    gloss, top = compose(tbest, lem)
                    fem_glossed.append(lem)
            if drop:
                exclude("feminine of an adjective used as a noun", lem); continue
        if k in sp.fixed_gloss:
            gloss = sp.fixed_gloss[k]
        okey = f"{lem}|{GROUP_LABEL.get(g, g.lower())}"
        if okey in sp.gloss_overrides:
            gloss = sp.gloss_overrides[okey]
            overridden.append(okey)
        if second:
            fk = done_lemma[lem][0]
            first = records[fk]
            # the second POS is a distinct sense only if its sentences' English
            # does not keep using the first entry's words (il malato = "the sick")
            fw = gloss_stems(first["en"].split(";")[0].split(",")[0])
            overlap = max((df.get(t, 0) / nsent for t in fw), default=0.0) if nsent else 1.0
            second_diag.append(f"{lem} {g} '{gloss}' vs {first['group']} '{first['en']}' overlap={overlap:.2f}")
            nominalised = {g, first["group"]} == {"NOUN", "ADJ"} and \
                re.search(r"\b(person|people|man|woman|one|soul)\b", gloss)
            if gloss_stems(gloss) & gloss_stems(first["en"]) or first["group"] == g or \
                    same_words(gloss, first["en"]) or nominalised or \
                    top["score"] <= 0 or top["defn"] or top["demote"] or \
                    overlap > SECOND_SENSE_OVERLAP:
                if not forced or first["forced"]:
                    exclude("second POS entry without a distinct sense", lem); continue
                del records[fk]              # the forced POS replaces a same-sense entry
                done_lemma[lem].remove(fk)
            else:
                second_entries.append(f"{lem} {g}")
                if displaced:
                    del records[displaced]
                    done_lemma[lem].remove(displaced)
                    second_entries.append(f"(replaces {lem} {displaced[1]})")
        if g == "?":
            inv = {"noun": "NOUN", "verb": "VERB", "adj": "ADJ", "adv": "ADV", "pron": "PRON",
                   "prep": "ADP", "conj": "CONJ", "num": "NUM", "intj": "INTJ", "det": "DET",
                   "article": "DET"}
            g = inv.get(ent["p"], "NOUN")
        if not is_article:
            done_lemma.setdefault(lem, []).append(k)
        records[k] = {"lemma": lem, "group": g, "en": gloss, "forced": forced, "pos_from_dict": k[1] == "?",
                      "entry_pos": ent["p"], "sense_idx": top["idx"], "sense_score": top["score"],
                      "gender": ent.get("g"), "nsent": nsent, "rows": rows, "display": disp, "base_en": base_gloss,
                      "fem_of": fem_of, "fixed": okey in sp.gloss_overrides or k in sp.fixed_gloss}
    stat("excluded", dict(excluded))
    stat("excluded_examples", {k: v for k, v in ex_examples.items()})
    stat("multi_pos_lemmas_in_pool", multi_pos)
    stat("feminine_glossed_from_masculine", sorted(set(fem_glossed)))
    stat("second_pos_entries_in_pool", second_entries)
    stat("second_pos_diagnostics", second_diag)
    stat("pronominal_verbs_shown_as_rsi", sorted(pronominal))
    if sp.sensitive_gloss_re is not None:
        stat("sensitive_gloss_senses_skipped", sorted(set(x for x in gloss_dropped if x)))
    stat("gloss_overrides", {"applied": sorted(set(overridden)),
                             "unused": sorted(set(sp.gloss_overrides) - set(overridden))})

    # --- selection + levels
    ranked = [k for k in pool if k in records and not records[k]["forced"]]
    ranked.sort(key=lambda k: order.get(k, 10**9))
    forced_ok = [k for k in forced_keys if k in records]
    stat("forced", {"requested": len(forced_keys), "included": len(forced_ok),
                    "missing": [k[0] for k in forced_keys if k not in records]})
    need = sp.n_words - len(forced_ok)
    # a feminine noun whose masculine lemma is in the pack (l'amica, la santa,
    # l'unica) is folded into the masculine entry as an alt; refill to 2000
    fem_folded = {}
    while True:
        chosen = [k for k in ranked if k not in fem_folded][:need]
        in_pack = defaultdict(list)
        for kk in forced_ok + chosen:
            in_pack[records[kk]["lemma"]].append(kk)
        new = {}
        for k in chosen:
            for m, via_noun in records[k]["fem_of"]:
                if m == records[k]["lemma"] or k in new:
                    continue
                for mk in in_pack.get(m, []):
                    if not via_noun and mk[1] != "NOUN":
                        continue
                    if gloss_words(records[k]["en"]) & gloss_words(records[mk]["en"]):
                        new[k] = mk
                        break
        if not new:
            break
        fem_folded.update(new)
    fem_alt = defaultdict(list)
    for k, mk in sorted(fem_folded.items()):
        fem_alt[mk].append(records[k]["lemma"])
    stat("feminine_folded_into_masculine", sorted(f"{records[k]['lemma']}->{records[m]['lemma']}"
                                                  for k, m in fem_folded.items()))
    if sp.level_floor or sp.level_ceiling:
        chosen = apply_level_floor(chosen, forced_ok, sp)    # id: colloquial words no lower than A2
    level_of = assign_levels(forced_ok, chosen, sp.bands)
    final = forced_ok + chosen
    stat("words_pos_from_dictionary", sorted(records[k]["lemma"] for k in final if records[k].get("pos_from_dict")))
    rank_order = sorted(final, key=lambda k: (order.get(k, 10**9), k))
    rank_of = {k: i + 1 for i, k in enumerate(rank_order)}

    # a content word whose main English word is already the main gloss of a
    # higher-ranked word of the same POS leads with its next-best supported
    # sense instead (stare "to stay" after essere "to be")
    def main_word(gl):
        head = re.split(r"[;,]", re.sub(r"\(.*?\)", "", gl))[0].strip().lower()
        return re.sub(r"^(to|a|an|the) ", "", head)
    taken = defaultdict(dict)
    collisions = []
    for k in rank_order:
        rec = records[k]
        g = rec["group"]
        if g not in CONTENT_GROUPS:
            continue
        mw = main_word(rec["en"])
        if mw in taken[g] and not rec["fixed"] and not sp.shares_gloss(rec["lemma"], taken[g][mw]):
            segs = [x.strip() for x in rec["en"].split(";")]
            parts = [x.strip() for x in segs[0].split(",")]
            top = rec["rows"][0] if rec["rows"] else None
            ps = top["pscore"] if top else {}
            lead = ps.get(parts[0], 0.0)
            # the next-best alternative must have its own corpus support
            alt_part = next((i for i, x in enumerate(parts) if i and main_word(x) not in taken[g]
                             and lead > 0 and ps.get(x, 0.0) >= COLLISION_SUPPORT * lead), None)
            new = None
            if alt_part:
                parts.insert(0, parts.pop(alt_part))
                new = "; ".join([", ".join(parts)] + segs[1:])
            elif top:
                for r in rec["rows"][1:]:
                    if r["demote"] or r["defn"] or r["score"] < COLLISION_SUPPORT * top["score"] or \
                            top["score"] <= 0:
                        continue
                    if main_word(r["g"]) in taken[g] or mw in r["g"].lower():
                        continue          # vetro "object made of glass" still scores on "glass"
                    new = r["g"] if len(r["g"]) + 2 + len(segs[0]) > MAX_GLOSS else f"{r['g']}; {segs[0]}"
                    break
            if new:
                collisions.append(f"{rec['lemma']}: {rec['en']} -> {new} (after {taken[g][mw]})")
                rec["en"] = new
                mw = main_word(new)
        taken[g].setdefault(mw, rec["lemma"])
    stat("gloss_collisions_resolved", collisions)

    if sp.lower_level_gloss_re is not None:
        # cross-pack policy: no sexual/violent gloss below the top level. A gloss
        # with clean ";"-segments keeps only those ("to pull; to shoot" -> "to
        # pull"); a chosen word with none moves to the end of the level order,
        # i.e. the top level (forced words stay and are reported)
        top = sp.level_ids[-1]
        cleaned, moved, forced_hits = [], [], []
        for k in final:
            if level_of[k] == top or not sp.lower_level_gloss_re.search(records[k]["en"]):
                continue
            segs = [x for x in re.split(r"\s*;\s*", records[k]["en"]) if not sp.lower_level_gloss_re.search(x)]
            if segs:
                cleaned.append(f"{records[k]['lemma']}: {records[k]['en']} -> {'; '.join(segs)}")
                records[k]["en"] = "; ".join(segs)
            elif k in forced_ok:
                forced_hits.append(records[k]["lemma"])
            else:
                moved.append(k)
        if moved:
            chosen = [k for k in chosen if k not in moved] + moved
            if sp.level_floor or sp.level_ceiling:
                chosen = apply_level_floor(chosen, forced_ok, sp)    # keep the floor after the move
            level_of = assign_levels(forced_ok, chosen, sp.bands)
        stat("sensitive_glosses", {"cleaned": cleaned, "moved_to_top_level": sorted(records[k]["lemma"] for k in moved),
                                   "forced_unresolved": forced_hits})

    words = []
    for k in final:
        rec = records[k]
        lem, g = rec["lemma"], rec["group"]
        w, alt, en = lem, None, rec["en"]
        gender = None
        pos = GROUP_LABEL.get(g, rec.get("pos", "other"))
        if g == "PHRASE":
            pos = "phrase"
        elif g == "FORM":
            pos = "verb"
        if k in sp.fixed_word:
            w, alt = sp.fixed_word[k][0], list(sp.fixed_word[k][1])
            pos = "art"
        elif g == "NOUN" and lem not in sp.no_article:
            gender, plural = sp.parse_gender(rec["gender"])
            mc = morph.get(k, Counter())
            if gender is None:
                gm, gf = mc["Gender=Masc"], mc["Gender=Fem"]
                gender = "m" if gm > gf else "f" if gf > gm else sp.default_gender(lem)
            # plural articles only for dictionary plural-only heads and the
            # pluralia tantum list; corpus plural majorities are not evidence
            plural = plural or lem in sp.pluralia_tantum
            w, en = sp.noun_display(lem, gender, plural, en)
            if w != lem:
                alt = [lem]
        if rec.get("display"):
            lem, w, alt = rec["display"], rec["display"], [rec["lemma"]]
        if fem_alt.get(k):
            alt = (alt or []) + [x for x in fem_alt[k] if x not in (alt or [])]
        word = {"lemma": lem, "w": w, "pos": pos, "en": en, "lv": level_of[k], "rank": rank_of[k]}
        if alt:
            word["alt"] = alt
        word["_key"] = k
        if rec.get("display"):
            word["_base"] = (rec["lemma"], rec["base_en"])
        word["_gender"] = gender if g == "NOUN" else None
        word["_epos"] = rec.get("entry_pos")
        word["_sidx"] = rec.get("sense_idx") if rec.get("sense_idx") is not None else 99
        words.append(word)
    lvl = {b: i for i, b in enumerate(sp.level_ids)}
    words.sort(key=lambda x: (lvl[x["lv"]], x["rank"]))

    id_map = env.repo / sp.id_map_file
    idmap = json.loads(id_map.read_text()) if id_map.exists() else {}
    stat("ids_reused_from_v1", assign_ids(words, idmap))

    top3000 = set()
    for k, *_ in blended:
        if k[1] != "PROPN":
            top3000.add(k[0])
        if len(top3000) >= 3000:
            break
    return words, records, top3000


def apply_level_floor(chosen, forced_ok, sp):
    """spec.level_floor {(lemma, group): level}: a chosen key ranked into an
    earlier band moves to the start of its floor band (the keys it passes
    move up one place each)."""
    start, acc = {}, -len(forced_ok)
    for lv, n in sp.bands:
        start[lv] = max(acc, 0)
        acc += n
    out = [k for k in chosen if k not in sp.level_floor]
    for i, k in enumerate(chosen):
        if k in sp.level_floor:
            out.insert(min(max(i, start[sp.level_floor[k]]), len(out)), k)
    # spec.level_ceiling {(lemma, group): level} (ko: a NIKL beginner word is
    # never B1): a key ranked past the end of its ceiling band moves into that
    # band, and the band's last keys without a ceiling move down one band each
    ceil = sp.level_ceiling or {}
    if ceil:
        order = [lv for lv, _ in sp.bands]
        for ci, (lv, _) in enumerate(sp.bands[:-1]):
            lim = start[order[ci + 1]]
            over = [k for k in out[lim:] if k in ceil and order.index(ceil[k]) <= ci]
            if not over:
                continue
            free = [k for k in out[start[lv]:lim] if k not in ceil][::-1][:len(over)]
            head = [k for k in out[:lim] if k not in free]
            out = head + over + free[::-1] + [k for k in out[lim:] if k not in over]
    return out


def assign_levels(forced_ok, chosen, bands):
    """Level per key: every forced key goes to the first band, which the
    rank-ordered chosen keys then fill up; later bands take the next
    band-size keys each, and the last band takes the rest."""
    level_of = {k: bands[0][0] for k in forced_ok}
    limits, acc = [], bands[0][1] - len(forced_ok)
    for lv, n in bands[:-1]:
        limits.append((acc, lv))
        acc += bands[len(limits)][1]
    for i, k in enumerate(chosen):
        level_of[k] = next((lv for lim, lv in limits if i < lim), bands[-1][0])
    return level_of


def assign_ids(words, idmap):
    """Stable ids: a word whose "lemma|pos" is in the frozen id map keeps its
    id (first claimant wins); the rest get fresh ids above the map's maximum,
    in list order. Returns the number of reused ids."""
    used = set()
    reused = 0
    for wd in words:
        old = idmap.get(f"{wd['lemma']}|{wd['pos']}")
        if old and old not in used:
            wd["id"] = old
            used.add(old)
            reused += 1
    nxt = max([int(v[1:]) for v in idmap.values()] + [0]) + 1
    for wd in words:
        if "id" not in wd:
            wd["id"] = f"w{nxt:04d}"
            nxt += 1
    return reused


def load_gloss_display(repo, path="tools/gloss_display.json"):
    """The repo's display-only gloss table {"lemma|pos": en} ({} without the
    file; keys starting with _ are comments)."""
    from pathlib import Path
    p = Path(repo) / path if repo else None
    if p is None or not p.exists():
        return {}
    return {k: v for k, v in json.loads(p.read_text()).items() if not k.startswith("_")}


def apply_gloss_display(repo, out_words, path="tools/gloss_display.json"):
    """Display-only glosses: the optional repo file `path` maps "lemma|pos"
    (the shipped words.json lemma and pos, as in gloss_overrides.json; keys
    starting with _ are comments) to the `en` text shipped for that word.
    Applied to the written word list only, after ranking, example selection
    and linking, so a display sense never changes rank, order, examples or
    links (gloss_overrides.json feeds those). No file: no change. Returns
    (applied keys, unused keys)."""
    table = load_gloss_display(repo, path)
    if not table:
        return [], []
    applied = set()
    for w in out_words:
        k = f"{w.get('lemma')}|{w.get('pos')}"
        if k in table:
            w["en"] = table[k]
            applied.add(k)
    unused = sorted(set(table) - applied)
    stat("gloss_display", {"applied": sorted(applied), "unused": unused})
    if unused:
        log(f"gloss_display: {len(unused)} keys match no shipped word: {unused[:10]}")
    return sorted(applied), unused
