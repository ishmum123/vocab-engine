"""Stage sentences: in-context word links, sentence choice per word (2 each),
and the linked-sentence -rsi gate."""
import re
from collections import Counter, defaultdict

from .lexicon import CONTENT_GROUPS, SKIP_UPOS
from .tag import iter_tagged
from .util import stat

SENT_END_RE = re.compile(r"[.!?…][\"'»”)]*$")
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


def sentence_links(toks, lexicon, key_to_id, allowed, text, groups=None, gender_of=None, epos_to_id=None,
                   lemma_ids=None):
    sp = lexicon.spec
    """Word ids linked by (lemma, POS) in context, or None if the sentence
    has a content lemma outside the pack/top-3000."""
    links = []
    initial = True
    resolved = lexicon.resolve_sentence(toks, groups)
    for i, (text_t, sl, upos, ms) in enumerate(toks):
        if upos == "PUNCT":
            if text_t in (".", "!", "?", "…"):
                initial = True
            continue
        was_initial, initial = initial, False
        r = resolved[i]
        low = text_t.lower()
        if lemma_ids:
            later = toks[i + 1][0] if i + 1 < len(toks) else ""
            direct = None
            if low in sp.apocope and (was_initial or not text_t[:1].isupper()) and not later[:1].isupper():
                direct = lemma_ids.get(sp.apocope[low])     # nessun -> nessuno, quel -> quello
            elif (r is None or key_to_id.get(r) is None) and (
                    (low, "INTJ") in key_to_id or (was_initial and low in lemma_ids)):
                # "Grazie per..." read as the noun grazie; a sentence-initial
                # capitalised pack word the tagger took for a name
                direct = key_to_id.get((low, "INTJ")) or lemma_ids[low]
            if direct:
                if direct not in links:
                    links.append(direct)
                continue
        if r is None:
            continue
        lem, g = r
        if g == "PROPN" or (not was_initial and text_t[:1].isupper()):
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
            if wid and g == "NOUN" and gender_of and gender_of.get(wid) in ("m", "f"):
                dg = det_gender(toks, i)
                if dg and dg != gender_of[wid]:
                    wid = None       # la moto is not il moto, il fine is not la fine
        if wid and wid not in links:
            links.append(wid)
    low = text.lower()
    for phrase in sp.multiword:
        if re.search(r"\b" + re.escape(phrase) + r"\b", low) and (phrase, "PHRASE") in key_to_id:
            wid = key_to_id[(phrase, "PHRASE")]
            if wid not in links:
                links.append(wid)
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
    st = Counter()
    info = {}
    cands = defaultdict(list)
    for sid, toks in iter_tagged(ctx["tagged"]):
        text = rows[sid][1]
        if not SENT_END_RE.search(text.strip()):
            st["no_terminal_punct"] += 1
            continue
        if sp.bad_text_re is not None and sp.bad_text_re.search(text):
            st["ungrammatical_italian"] += 1
            continue
        if EN_REGISTER_RE.search(rows[sid][3]):
            st["non_standard_english_register"] += 1
            continue
        n = sum(1 for t in toks if t[2] not in SKIP_UPOS)
        if n < 3 or n > sp.max_len:
            st["length_out_of_range"] += 1
            continue
        links = sentence_links(toks, lexicon, key_to_id, allowed, text, groups, gender_of, epos_to_id,
                               lemma_ids)
        if links and rsi_ids & set(links):
            refl_by_sid[sid] = {key_to_id.get(r) for j, r in enumerate(lexicon.resolve_sentence(toks, groups))
                                if r and r[1] == "VERB" and sp.carries_refl_clitic(toks, j)}
        if links is None:
            st["content_lemma_outside_pack_top3000"] += 1
            continue
        if not links:
            continue
        remoto = any(sp.is_marked_past(t[3]) or (r is not None and r[1] == "VERB" and lexicon.historic_past(t[0].lower()))
                     for t, r in zip(toks, lexicon.resolve_sentence(toks, groups)))
        maxlv = max((lv_of[w] for w in links), key=lambda l: lv_ord[l])
        if remoto:
            st["candidates_with_passato_remoto"] += 1
        info[sid] = (n, remoto, rows[sid][4] is not None, maxlv, links)
        for w in links:
            cands[w].append(sid)
    st["candidates"] = len(info)

    use = Counter()
    chosen = defaultdict(list)
    primary = {}
    remoto_blocked = Counter()
    first_lv, top_lv = sp.level_ids[0], sp.level_ids[-1]    # marked past tense: top level only
    order = sorted(cands, key=lambda w: (len(cands[w]), w))
    for wid in order:
        lv = lv_of[wid]
        ok = []
        for sid in cands[wid]:
            n, remoto, aud, maxlv, links = info[sid]
            if remoto and lv != top_lv:
                remoto_blocked[sid] += 1
                continue
            ok.append(sid)
        good = [s for s in ok if sp.min_len[lv] <= info[s][0]]
        if lv == first_lv and len(good) < 2:
            good += [s for s in ok if info[s][0] == 3]
        good.sort(key=lambda s: (lv_ord[info[s][3]] > lv_ord[lv], not info[s][2],
                                 abs(info[s][0] - sp.target_len[lv]), use[s] == 0, s))
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
            w["en"] = f"{head(base_en)}; {rsi}: {head(rsi_en)}" if base_en else w["en"]
            reverted.append(f"{rsi} ({rs}/{len(linked)})")
    st_rev = sorted(reverted)
    cov = Counter(min(len(chosen.get(w["id"], [])), 2) for w in words)
    lens = Counter(info[s][0] for s in sel)
    st = dict(st)
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
