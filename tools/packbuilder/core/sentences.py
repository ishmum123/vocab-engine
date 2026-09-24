"""Stage sentences: in-context word links, sentence choice per word (2 each),
and the linked-sentence -rsi gate."""
import re
from collections import Counter, defaultdict

from .lexicon import CONTENT_GROUPS, SKIP_UPOS
from .tag import iter_tagged
from .util import stat

SENT_END_RE = re.compile(r"[.!?…؟][\"'»”)]*$")     # ؟ Arabic-script question mark (fa)
PRONOMINAL_LINKED_SHARE = 0.6   # -rsi label needs this share of its linked sentences reflexive
EN_REGISTER_RE = re.compile(r"\b(ain't|gonna|wanna|gotta|y'all|dunno|lemme|gimme|innit|ya|yer)\b"
                            r"|buzzed the control tower", re.I)


def det_gender(toks, i):
    """Gender of the article/articulated preposition governing noun token i
    (skipping adjectives), or None."""
    j = i - 1
    while j >= 0 and toks[j][2] == "ADJ":
        j -= 1
    if j < 0 or toks[j][2] not in ("DET", "ADP"):
        return None
    ms = toks[j][3]
    return "m" if "Gender=Masc" in ms else "f" if "Gender=Fem" in ms else None


HOMOGRAPH_STOP = {"to", "a", "an", "the", "of", "be", "do", "for", "in", "on", "at", "with", "by", "as", "or",
                  "and", "it", "one", "not", "so", "up", "out", "off", "get", "make", "have"}
EN_WORD_RE = re.compile(r"[a-z]+")


def phrase_spans(toks, sp, key_to_id, en=None, ranges=None):
    """Token-level phrase matches (spec.phrase_token_spans). Contractions are
    split first (es: del = de + el). Returns (phrase ids in sentence order,
    fully consumed token indices, {token index: leftover words} for a
    contraction only partly inside a phrase). `ranges`, when a list, gets one
    (first token index, last token index, phrase id) per match."""
    seq = []
    for i, t in enumerate(toks):
        if t[2] == "PUNCT":
            seq.append((None, i))
            continue
        low = t[0].lower()
        if low in sp.art_prep:
            seq += [(sp.art_prep[low], i), (sp.definite_article, i)]
        else:
            seq += [(w, i) for w in low.split()]
    used, found = set(), []
    en_low = set(EN_WORD_RE.findall((en or "").lower()))
    for phrase in sorted(sp.multiword, key=lambda p: (-len(p.split()), p)):   # longest first
        if (phrase, "PHRASE") not in key_to_id:
            continue
        cues = sp.phrase_en_cues.get(phrase)
        if cues and en is not None and not en_low & set(cues):
            continue        # "No la conozco de nada": not "you're welcome"
        pw = phrase.split()
        for j in range(len(seq) - len(pw) + 1):
            if all(seq[j + k][0] == pw[k] and j + k not in used for k in range(len(pw))):
                used.update(range(j, j + len(pw)))
                found.append((j, key_to_id[(phrase, "PHRASE")]))
                if ranges is not None:
                    ranges.append((seq[j][1], seq[j + len(pw) - 1][1], key_to_id[(phrase, "PHRASE")]))
    consumed, partial = set(), {}
    for i in {seq[j][1] for j in used}:
        rest = [w for j, (w, ti) in enumerate(seq) if ti == i and j not in used]
        if rest:
            partial[i] = rest
        else:
            consumed.add(i)
    ids = []
    for _, wid in sorted(found):
        if wid not in ids:
            ids.append(wid)
    return ids, consumed, partial


def homograph_table(words, sp):
    """lemma -> [(id, English cue words)] for lemmas with several pack entries
    (spec.homograph_by_translation: solo adv "only" vs adj "alone")."""
    by = defaultdict(list)
    for w in words:
        if w["pos"] not in ("phrase", "art"):
            by[w["_key"][0]].append(w)
    out = {}
    for lem, ws in by.items():
        if len(ws) < 2:
            continue
        out[lem] = []
        for w in sorted(ws, key=lambda x: x["id"]):
            cues = set(EN_WORD_RE.findall(re.sub(r"\(.*?\)", " ", w["en"].lower()))) - HOMOGRAPH_STOP
            cues |= set(sp.homograph_cues.get((lem, w["pos"]), ()))
            out[lem].append((w["id"], cues))
        out[("adv", lem)] = {w["id"] for w in ws if w["pos"] == "adv"}
    return out


def sentence_links(toks, lexicon, key_to_id, allowed, text, groups=None, gender_of=None, epos_to_id=None,
                   lemma_ids=None, en=None, homs=None, st=None, where=None):
    """Word ids linked by (lemma, POS) in context, or None if the sentence
    has a content lemma outside the pack/top-3000.

    `where`, when a list, records where each link comes from, one entry per
    linking occurrence (a word linked twice is recorded twice):
    ("tok", first token index, last token index, id) for token links and
    token-level phrases, ("chars", start, end, id) for a spec.multiword
    phrase matched in `text` (Python str offsets). Links are unchanged."""
    sp = lexicon.spec
    links = []

    def note(kind, a, b, wid):
        if where is not None and wid:
            where.append((kind, a, b, wid))
    initial = True
    resolved = lexicon.resolve_sentence(toks, groups)
    consumed, partial, phrase_ids = set(), {}, []
    if sp.phrase_token_spans:
        ranges = [] if where is not None else None
        phrase_ids, consumed, partial = phrase_spans(toks, sp, key_to_id, en, ranges)
        for a, b, wid in ranges or ():
            note("tok", a, b, wid)
    en_words = None
    if homs and en:
        en_words = set(EN_WORD_RE.findall(en.lower()))
        # facts -> fact, boxes -> box: cues are base forms
        en_words |= {w[:-1] for w in en_words if w.endswith("s")} | {w[:-2] for w in en_words if w.endswith("es")}
    for i, (text_t, sl, upos, ms) in enumerate(toks):
        if upos == "PUNCT":
            if text_t in (".", "!", "?", "…"):
                initial = True
            continue
        was_initial, initial = initial, False
        if i in consumed:
            continue            # inside a matched phrase: the phrase is the link
        if i in partial:
            for w in partial[i]:                # "a pesar del": the article part of del
                wid = key_to_id.get((w, "DET"))
                note("tok", i, i, wid)
                if wid and wid not in links:
                    links.append(wid)
            continue
        r = resolved[i]
        low = text_t.lower()
        if lemma_ids:
            later = toks[i + 1][0] if i + 1 < len(toks) else ""
            direct = None
            if low in sp.apocope and (was_initial or not text_t[:1].isupper()) and not later[:1].isupper():
                direct = lemma_ids.get(sp.apocope[low])     # nessun -> nessuno, quel -> quello
            elif (r is None or key_to_id.get(r) is None) and sp.surface_link_ok(toks[i]) and (
                    (low, "INTJ") in key_to_id or (was_initial and low in lemma_ids)):
                # "Grazie per..." read as the noun grazie; a sentence-initial
                # capitalised pack word the tagger took for a name
                direct = key_to_id.get((low, "INTJ")) or lemma_ids[low]
            if direct:
                note("tok", i, i, direct)
                if direct not in links:
                    links.append(direct)
                continue
        if r is None:
            continue
        lem, g = r
        if g == "PROPN" or (sp.caps_mark_names and not was_initial and text_t[:1].isupper()):
            continue
        if g in CONTENT_GROUPS and lem not in allowed:
            return None
        nxt = toks[i + 1][2] if i + 1 < len(toks) else "PUNCT"
        if (text_t.lower(), "FORM") in key_to_id:
            wid = key_to_id[(text_t.lower(), "FORM")]    # it: "è" -> the forced form entry
        elif (text_t.lower(), "INTJ") in key_to_id and nxt == "PUNCT" and g != "INTJ":
            # "Prego." / "Scusa, ..." / "Grazie!": standalone greeting use
            wid = key_to_id[(text_t.lower(), "INTJ")]
        else:
            wid = key_to_id.get((lem, g))
            if wid is None and sp.drop_keys.get((lem, g)):
                wid = key_to_id.get(sp.drop_keys[(lem, g)])   # "dire di no", "o no" -> no (intj)
            if wid is None and epos_to_id and g in sp.group_kpos:
                # no entry for this POS: the lemma's entry built from the same
                # Wiktionary headword (come ADV "Come stai?" -> come "how",
                # whose gloss comes from the adverb headword)
                wid = epos_to_id.get((lem, sp.group_kpos[g][0]))
            if wid is None:
                wid = sp.cross_pos_link(lexicon, lem, g, key_to_id)    # default None (id: same sense)
            if wid and en_words is not None and lem in homs:
                # several entries for this lemma: the English translation decides
                # when it names the other entry's sense and not this one's
                cues = dict(homs[lem])
                advs = homs[("adv", lem)]
                inflected = "Gender=Fem" in ms or "Number=Plur" in ms
                if inflected and wid in advs:
                    # an adverb does not inflect: "una sola pierna" is the adjective
                    other = [x for x, _ in homs[lem] if x not in advs]
                    if len(other) == 1:
                        wid = other[0]
                elif wid in cues and not cues[wid] & en_words:
                    hit = [x for x, c in homs[lem] if x != wid and c & en_words and not (inflected and x in advs)]
                    if len(hit) == 1:
                        wid = hit[0]
                        if st is not None:
                            st["homograph_routed_by_translation"] += 1
                            st[("routed", lem)] += 1
            if wid and g == "NOUN" and gender_of and gender_of.get(wid) in ("m", "f"):
                dg = det_gender(toks, i)
                if dg is None and sp.needs_gender_evidence(lexicon, lem):
                    # el frente / la frente: no article, so the noun's own
                    # gender must agree; no evidence means no link
                    dg = "m" if "Gender=Masc" in ms else "f" if "Gender=Fem" in ms else "?"
                if dg and dg != gender_of[wid]:
                    wid = None       # la moto is not il moto, il fine is not la fine
        note("tok", i, i, wid)
        if wid and wid not in links:
            links.append(wid)
    if sp.phrase_token_spans:
        for wid in phrase_ids:
            if wid not in links:
                links.append(wid)
        return links
    low = text.lower()
    for phrase in sp.multiword:
        if re.search(r"\b" + re.escape(phrase) + r"\b", low) and (phrase, "PHRASE") in key_to_id:
            wid = key_to_id[(phrase, "PHRASE")]
            if where is not None:
                for m in re.finditer(r"\b" + re.escape(phrase) + r"\b", text, re.IGNORECASE):
                    note("chars", m.start(), m.end(), wid)
            if wid not in links:
                links.append(wid)
            if sp.phrase_absorbs_parts:
                # "De hecho": the phrase is the word, not el hecho; a part keeps its
                # link only when it also occurs outside the phrase
                n_phrase = len(re.findall(r"\b" + re.escape(phrase) + r"\b", low))
                for part in sp.multiword[phrase]:
                    if len(re.findall(r"\b" + re.escape(part) + r"\b", low)) > n_phrase:
                        continue
                    for g in CONTENT_GROUPS:
                        pid = key_to_id.get((part, g))
                        if pid in links:
                            links.remove(pid)
    return links


def build_sentences(env, ctx, words, top3000):
    sp = env.spec
    lv_ord = {b: i for i, b in enumerate(sp.level_ids)}
    lexicon = ctx["lexicon"]
    groups = ctx["lemma_groups"]
    gender_of = {w["id"]: w.get("_gender") for w in words}
    ep = defaultdict(list)
    for w in words:
        if w.get("_epos"):
            ep[(w["_key"][0], w["_epos"])].append((w["_sidx"], w["id"]))
    # several entries from one headword: the one carrying its primary sense
    epos_to_id = {k: min(v)[1] for k, v in ep.items()}
    lemma_ids = {}
    for w in sorted(words, key=lambda x: x["rank"]):
        if w["pos"] != "art":
            lemma_ids.setdefault(w["_key"][0], w["id"])
    rsi_ids = {w["id"] for w in words if w.get("_base")}
    refl_by_sid = {}
    rows = ctx["rows_by_sid"]
    key_to_id = {w["_key"]: w["id"] for w in words}
    lv_of = {w["id"]: w["lv"] for w in words}
    allowed = {w["lemma"] for w in words} | top3000
    homs = homograph_table(words, sp) if sp.homograph_by_translation else None
    sensitive_sids = set()
    hw_tier = {}       # (sid, wid) -> 0 headword/alt visible, 1 verb in 3sg present, 2 other
    if sp.prefer_headword_sentence:
        forms_of = {}
        for w in words:
            fs = {w["w"].lower(), w["_key"][0].lower(), w["lemma"].lower()} | {a.lower() for a in (w.get("alt") or [])}
            forms_of[w["id"]] = [(f, " " in f) for f in sorted(fs) if f]
        verb_key = {w["id"]: w["_key"] for w in words if w["_key"][1] == "VERB"}
    # a word that is itself on the sensitive list (el sexo) may use those sentences
    sensitive_words = {w["id"] for w in words if sp.sensitive_re is not None and sp.sensitive_re.search(w["lemma"])}
    st = Counter()
    info = {}
    rank_pen = {}      # (sid, word level) -> spec.sentence_rank penalty
    cands = defaultdict(list)
    tok_forms = {}     # sid -> folded token surfaces (example_shows_word only)
    for sid, toks in iter_tagged(ctx["tagged"]):
        text = rows[sid][1]
        if sp.untranslated_rows and not rows[sid][3]:
            continue            # tagged for evidence only: no English translation
        if not SENT_END_RE.search(text.strip()):
            st["no_terminal_punct"] += 1
            continue
        if sp.bad_text_re is not None and sp.bad_text_re.search(text):
            st["ungrammatical_italian"] += 1
            continue
        if EN_REGISTER_RE.search(rows[sid][3]):
            st["non_standard_english_register"] += 1
            continue
        if sp.translation_mismatch(toks, rows[sid][3]):
            st["translation_contradicts_sentence"] += 1
            continue
        n = sum(1 for t in toks if t[2] not in SKIP_UPOS)
        if n < 3 or n > sp.max_len:
            st["length_out_of_range"] += 1
            continue
        links = sentence_links(toks, lexicon, key_to_id, allowed, text, groups, gender_of, epos_to_id,
                               lemma_ids, rows[sid][3], homs, st)
        if links and rsi_ids & set(links):
            refl_by_sid[sid] = {key_to_id.get(r) for j, r in enumerate(lexicon.resolve_sentence(toks, groups))
                                if r and r[1] == "VERB" and sp.carries_refl_clitic(toks, j)}
        if links is None:
            st["content_lemma_outside_pack_top3000"] += 1
            continue
        if not links:
            continue
        if sp.drop_all_levels is not None and (sp.drop_all_levels.search(text) or
                                               sp.drop_all_levels.search(rows[sid][3])):
            st["dropped_all_levels"] += 1
            continue
        sensitive = sp.sensitive_re is not None and bool(
            sp.sensitive_re.search(text) or sp.sensitive_re.search(rows[sid][3]))
        if sensitive:
            st["sensitive_kept_to_top_level"] += 1
            sensitive_sids.add(sid)
        marked = sp.marks_sentence(toks) or any(sp.is_marked_past(t[3]) or (r is not None and r[1] == "VERB" and lexicon.historic_past(t[0].lower()))
                     for t, r in zip(toks, lexicon.resolve_sentence(toks, groups)))
        if marked:
            sensitive_sids.discard(sid)    # kept to the top level anyway: no word exemption
        remoto = sensitive or marked
        maxlv = max((lv_of[w] for w in links), key=lambda l: lv_ord[l])
        if sensitive and maxlv != sp.level_ids[-1]:
            st["sensitive_kept_from_lower_levels"] += 1     # would otherwise serve A1/A2 words
        if remoto:
            st["candidates_with_passato_remoto"] += 1
        info[sid] = (n, remoto, rows[sid][4] is not None, maxlv, links)
        if sp.example_shows_word:
            tok_forms[sid] = {sp.fold(t[0]) for t in toks}
        for lvx in sp.level_ids:
            rank_pen[(sid, lvx)] = sp.sentence_rank(toks, lvx)
        if sp.prefer_headword_sentence:
            low_t = text.lower()
            tokset = {t[0].lower() for t in toks}
            res = None
            for w in links:
                tier = 2
                if any((re.search(r"(?<!\w)" + re.escape(f) + r"(?!\w)", low_t) if multi else f in tokset)
                       for f, multi in forms_of[w]):
                    tier = 0
                elif w in verb_key:
                    res = res or lexicon.resolve_sentence(toks, groups)
                    if any(r == verb_key[w] and "Person=3" in t[3] and "Number=Sing" in t[3] and
                           "Tense=Pres" in t[3] and "Mood=Ind" in t[3] for t, r in zip(toks, res)):
                        tier = 1
                hw_tier[(sid, w)] = tier
        for w in links:
            cands[w].append(sid)
    st["candidates"] = len(info)

    use = Counter()
    chosen = defaultdict(list)
    primary = {}
    remoto_blocked = Counter()
    first_lv, top_lv = sp.level_ids[0], sp.level_ids[-1]    # marked past tense: top level only
    order = sorted(cands, key=lambda w: (len(cands[w]), w))
    surface_of = {w["id"]: sp.fold(w["_key"][0]) for w in words} if sp.example_shows_word else {}
    for wid in order:
        lv = lv_of[wid]
        ok = []
        for sid in cands[wid]:
            n, remoto, aud, maxlv, links = info[sid]
            if remoto and lv != top_lv and not (sid in sensitive_sids and wid in sensitive_words):
                remoto_blocked[sid] += 1
                continue
            ok.append(sid)
        good = [s for s in ok if sp.min_len[lv] <= info[s][0]]
        if lv == first_lv and len(good) < 2:
            good += [s for s in ok if info[s][0] == 3]
        good.sort(key=lambda s: (lv_ord[info[s][3]] > lv_ord[lv],
                                 rank_pen[(s, lv)] - (sp.audio_rank_bonus if info[s][2] else 0),
                                 hw_tier.get((s, wid), 0),
                                 not info[s][2],
                                 abs(info[s][0] - sp.target_len[lv]), use[s] == 0, s))
        if sp.example_shows_word and good:
            # one example shows the word itself (Haus, not only Häuser) when any can
            form = surface_of[wid]
            bare = [s for s in good if form in tok_forms.get(s, ())]
            if sp.bare_prefer_shared:
                # among the bare-form sentences: one with audio, then one already
                # chosen for another word (fewer extra sentences, audio kept)
                bare.sort(key=lambda s: (not info[s][2], use[s] == 0))
            if bare and not any(s in bare for s in good[:2]):
                good.remove(bare[0])
                good.insert(0, bare[0])
            if not bare:
                st["words_without_bare_form_example"] += 1
        for s in good[:2]:
            chosen[wid].append(s)
            use[s] += 1
            primary.setdefault(s, wid)

    sel = sorted(primary)
    sentences = []
    users = set()
    for i, sid in enumerate(sel):
        n, remoto, aud, maxlv, links = info[sid]
        lv = top_lv if remoto else maxlv
        row = rows[sid]
        rec = {"id": f"s{i+1:04d}", "t": sp.clean_sentence_text(row[1]), "en": row[3], "lv": lv,
               "words": links}
        if row[4] is not None:
            rec["audio"] = f"https://tatoeba.org/audio/download/{row[4]}"
        rec.update(sp.sentence_fields(row))     # fa: "src": "gen" on sentences written for the pack
        sentences.append(rec)
        if row[2]:
            users.add(row[2])
    # -rsi label only when the pack's own sentences show it: >=60% of the
    # sentences linking the word carry a reflexive clitic on it; otherwise the
    # base infinitive with a combined gloss
    reverted = []
    for w in words:
        if not w.get("_base"):
            continue
        linked = [sid for sid in sel if w["id"] in info[sid][4]]
        if not linked:
            continue
        rs = sum(1 for sid in linked if w["id"] in refl_by_sid.get(sid, ()))
        if rs / len(linked) < PRONOMINAL_LINKED_SHARE:
            base, base_en = w["_base"]
            rsi, rsi_en = w["lemma"], w["en"]
            w["lemma"], w["w"] = base, base
            w.pop("alt", None)
            head = lambda x: re.split(r"[,;]", x)[0].strip()
            if sp.revert_dedupe_gloss and base_en and head(base_en) == head(rsi_en):
                w["en"] = head(base_en)       # enterar / enterarse both "to find out"
            else:
                w["en"] = f"{head(base_en)}; {rsi}: {head(rsi_en)}" if base_en else w["en"]
            reverted.append(f"{rsi} ({rs}/{len(linked)})")
    if sp.strict_pronominal_links:
        # a verb shown with its reflexive pronoun links only sentences where
        # the pronoun is there ("Je rappellerai" is not se rappeler)
        kept = {w["id"] for w in words if w.get("_base") and w["lemma"] != w["_base"][0]}
        for rec, sid in zip(sentences, sel):
            drop = [x for x in rec["words"] if x in kept and x not in refl_by_sid.get(sid, ())]
            if drop and len(drop) < len(rec["words"]):
                rec["words"] = [x for x in rec["words"] if x not in drop]
                st["pronominal_links_dropped"] += len(drop)
    st_rev = sorted(reverted)
    cov = Counter(min(len(chosen.get(w["id"], [])), 2) for w in words)
    lens = Counter(info[s][0] for s in sel)
    routed = {k[1]: v for k, v in st.items() if isinstance(k, tuple)}
    st = {k: v for k, v in st.items() if not isinstance(k, tuple)}
    if routed:
        st["homograph_routed_by_lemma"] = dict(sorted(routed.items(), key=lambda kv: (-kv[1], kv[0])))
    st.update({
        "final_sentences": len(sentences),
        "with_audio": sum(1 for s in sentences if "audio" in s),
        "coverage_0": cov[0], "coverage_1": cov[1], "coverage_2": cov[2],
        "remoto_candidates_blocked_for_A1_A2": len(remoto_blocked),
        "remoto_in_final": sum(1 for s in sel if info[s][1]),
        "length_hist": {str(k): lens[k] for k in sorted(lens)},
        "primary_by_level": dict(Counter(lv_of[primary[s]] for s in sel)),
        "zero_sentence_words": [w["w"] for w in words if not chosen.get(w["id"])],
        "rsi_reverted_to_base": st_rev,
    })
    stat("sentences", dict(st))
    return sentences, sorted(users), primary
