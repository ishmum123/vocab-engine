"""Stage driver: prepare shared context, build words and sentences, write
pack/*.json, attribution.json, build_stats.json and REPORT.md."""
import json
import time
from collections import Counter, defaultdict

from .english import EN_VOCAB, EN_WORD_RE, en_stems
from .freq import corpus_usage, stage_freq
from .lex import stage_lex
from .lexicon import Lexicon, FUNCTION_UPOS
from .report import write_report
from .sentences import build_sentences
from .sources import ensure_downloaded, stage_corpus, audio_recorders
from .tag import stage_tag, truecase_stats, iter_tagged, tag_rows
from .util import STATS, log, stat, dump_json, write_json
from .words import build_words, apply_gloss_display

STAGES = ["all", "corpus", "tag", "lex", "freq", "words", "sentences", "final"]
WORD_FIELDS = ("id", "w", "lemma", "pos", "en", "lv", "rank", "pron", "alt")


def build_pack_json(env, words, raw_upos):
    sp = env.spec
    fids = []
    for w in words:
        k = w["_key"]
        if k[1] == "FORM":
            fids.append(w["id"])
            continue
        c = raw_upos.get(k)
        if k[1] == "VERB" and k[0] not in sp.function_verbs:
            continue       # modal/aux verbs (potere, stare...) are drilled as words
        if k in sp.fixed_word or k[0] in sp.function_lemmas or (c and c.most_common(1)[0][0] in FUNCTION_UPOS):
            fids.append(w["id"])
    return {
        "key": sp.code,
        "name": sp.pack_name,
        "tts": sp.tts,
        "stt": sp.stt,
        "ttsRate": sp.tts_rate,
        "levels": [{"id": lv, "label": lv} for lv in sp.level_ids],
        "setSize": sp.set_size,
        "placement": sp.placement,
        "functionWords": sorted(fids),
        "typing": sp.typing,
        "showPron": sp.show_pron,
        "hasLessons": sp.has_lessons,
        **sp.pack_json_extra(),     # script display fields (fa: rtl, langTag, fontFamily, fonts, lineHeight)
    }


def write_characters(env, out_words, sentences):
    """Characters stage (docs/HSK_MERGE.md ss2.3): pack/characters.json from
    spec.character_units, and each sentence's spec.sentence_ruby tuples cut to
    the words that are some unit's words[0] (a ruby with no unit is never
    rendered). No units: no file and no ruby. Returns the units."""
    units = env.spec.character_units(out_words) or []
    word0 = {u["words"][0] for u in units}
    for s in sentences:
        if "ruby" in s:
            keep = [r for r in s["ruby"] if r[3] in word0]
            if keep:
                s["ruby"] = keep
            else:
                del s["ruby"]
    if units:
        stat("characters", {"units": len(units),
                            "sentences_with_ruby": sum(1 for s in sentences if "ruby" in s),
                            "ruby_tokens": sum(len(s.get("ruby", ())) for s in sentences)})
        write_json(env.pack / "characters.json", units)
    return units


def characters_pack_fields(sp, units):
    """pack.json keys the characters stage adds, only when units were written:
    "characters" (spec.characters) and, for a pron_first spec, "pronFirst": true."""
    if not units:
        return {}
    out = {"characters": sp.characters}
    if sp.pron_first:
        out["pronFirst"] = True
    return out


def attribution(env, ctx, users, sentences):
    sp = env.spec
    return {
        "spoken_freq": {"source": "hermitdave/FrequencyWords", "licence": "CC-BY-SA-4.0",
                        "url": sp.sources[sp.subtitles_file]},
        "written_freq": {"source": "wordfreq (Python package)", "licence": "CC-BY-SA-4.0"},
        "dictionary": {"source": f"kaikki.org {sp.name_en} Wiktionary extract", "licence": "CC-BY-SA-3.0/GFDL",
                       "url": sp.sources[sp.kaikki_file]},
        "tagger": dict(sp.tagger_attribution),
        "sentences": {"source": f"Tatoeba {sp.tatoeba_code}_sentences_detailed.tsv", "licence": "CC-BY 2.0 FR",
                      "url": sp.sources[sp.sentences_file], "contributor_usernames": users},
        "audio": {"source": "Tatoeba sentences_with_audio.tsv",
                  "licences": "per clip; recorders listed per licence",
                  "recorders": audio_recorders(env, sentences)},
        **({"written_examples": {
            "source": "written for this pack (tools/generated_examples.tsv) and reviewed; marked \"src\": \"gen\"",
            "licence": "CC-BY-SA-4.0", "count": ctx["example_rows_shipped"],
            "note": "Example sentences only, for words whose corpus sentences are missing or dropped by policy; no audio."}}
           if ctx.get("example_rows_shipped") else {}),
        **sp.extra_attribution(env, sentences),
    }


def prepare(env, ctx):
    corpus = stage_corpus(env)
    ctx["rows_by_sid"] = {r[0]: r for r in corpus["rows"]}
    ctx["en_by_sid"] = {r[0]: r[3] for r in corpus["rows"]}
    ctx["truecase"] = truecase_stats(corpus["rows"], env.spec.word_re, env.spec.sentence_openers)
    # untranslated rows (spec.untranslated_rows, english "") are tagged but never
    # ship and carry no English evidence
    en_rows = [r for r in corpus["rows"] if r[3]] if env.spec.untranslated_rows else corpus["rows"]
    for r in en_rows:
        EN_VOCAB.update(EN_WORD_RE.findall(r[3].lower()))
    bg = Counter()
    for r in en_rows:
        bg.update(set(en_stems(r[3], keep_stop=True)))
    ctx["en_bg"], ctx["en_bgn"] = bg, len(en_rows)
    stat("corpus", {k: v for k, v in corpus.items() if k != "rows"})
    ctx["tagged"] = stage_tag(env, corpus)
    # sentences written as examples only (spec.example_rows): tagged apart from
    # the corpus, so no frequency, gloss or lemma evidence ever sees them
    ex = env.spec.example_rows(env)
    ctx["example_rows"] = {r[0]: r for r in ex}
    ctx["example_tagged"] = tag_rows(env.spec, ex, ctx["truecase"]) if ex else []
    ctx["lexicon"] = Lexicon(stage_lex(env), env.spec)
    if env.spec.lemma_tiebreak_corpus:
        ctx["lexicon"].count_lemma_votes(iter_tagged(ctx["tagged"]))
    # two passes: the first gives each lemma's POS mix, which the copula rule
    # of the second uses ("è ridicolo" = the adjective)
    lx = ctx["lexicon"]
    for _ in range(2):
        surf, raw_upos, morph, refl, initial = corpus_usage(ctx["tagged"], lx, ctx.get("lemma_groups"))
        lg = defaultdict(Counter)
        for (lem, g), c in raw_upos.items():
            lg[lem][g] += sum(c.values())
        ctx["lemma_groups"] = lg
    ctx.update(surf=surf, raw_upos=raw_upos, morph=morph, refl=refl, initial=initial)
    ctx["blended"] = stage_freq(env, surf, raw_upos)


def finish_words(env, ctx, words, records, top3000):
    """build_words output -> the shipped word list: sentences, the
    refill_unexampled second pass (de/id/ru), then spec.finalize_words (fa
    display lemmas, id adjective POS). Shared by run and passages.load_context
    so both see the same words. Returns (words, records, top3000, sentences,
    users, primary)."""
    sp = env.spec
    sentences, users, primary = build_sentences(env, ctx, words, top3000)
    if sp.refill_unexampled:
        # words no sentence could illustrate give their slot to the next-ranked word (once)
        used = {wid for s in sentences for wid in s["words"]}
        drop = sorted(w["_key"] for w in words if w["id"] not in used and not records[w["_key"]]["forced"])
        if drop:
            stat("refilled_unexampled", [k[0] for k in drop])
            sp.drop_keys = {**sp.drop_keys, **{k: None for k in drop}}
            words, records, top3000 = build_words(env, ctx)
            sentences, users, primary = build_sentences(env, ctx, words, top3000)
    sp.finalize_words(env, ctx, words)
    return words, records, top3000, sentences, users, primary


def run(env, stage="all", check_remote=False):
    sp = env.spec
    t0 = time.time()
    ensure_downloaded(env, check_remote)
    if stage == "corpus":
        stage_corpus(env); return
    if stage == "tag":
        stage_tag(env, stage_corpus(env)); log(STATS.get("tag_meta")); return
    if stage == "lex":
        stage_lex(env); return
    ctx = {}
    prepare(env, ctx)
    lx = ctx["lexicon"]
    stat("resolution", {"unresolved_tokens_by_pos": dict(lx.n_unresolved),
                        "clitic_compounds_resolved": lx.n_clitic,
                        "numeral_tokens_read_as_verb": lx.n_num_as_verb,
                        "rare_reading_overrides": lx.n_rare_override,
                        "adv_verb_after_article_read_as_noun": lx.n_after_article,
                        "noun_after_copula_read_as_adjective": lx.n_copula_adj,
                        "pronoun_before_noun_read_as_article": lx.n_pron_as_article,
                        "initial_noun_before_determiner_read_as_imperative": lx.n_imperative})
    if sp.verb_homograph_ratio:
        stat("verb_homographs_by_person_mood_or_use", lx.n_verb_homograph)
    if stage == "freq":
        log(json.dumps(STATS.get("freq"))); return
    words, records, top3000 = build_words(env, ctx)
    env.pack.mkdir(exist_ok=True)
    out_words = [{k: w[k] for k in WORD_FIELDS if k in w} for w in words]
    if stage == "words":
        apply_gloss_display(sp.repo, out_words, sp.gloss_display_file)
    write_json(env.pack / "words.json", out_words)
    if stage == "words":
        return
    words, records, top3000, sentences, users, primary = finish_words(env, ctx, words, records, top3000)
    out_words = [{k: w[k] for k in WORD_FIELDS if k in w} for w in words]
    apply_gloss_display(sp.repo, out_words, sp.gloss_display_file)    # display-only senses, after everything else
    write_json(env.pack / "words.json", out_words)     # -rsi gate may revert entries
    units = write_characters(env, out_words, sentences)
    write_json(env.pack / "sentences.json", sentences)
    pack_json = build_pack_json(env, words, ctx["raw_upos"])
    pack_json.update(characters_pack_fields(sp, units))
    write_json(env.pack / "pack.json", pack_json, compact=False)
    write_json(env.pack / "attribution.json", attribution(env, ctx, users, sentences), compact=False)
    ctx.update(words=words, records=records, sentences=sentences, primary=primary)
    stat("wall_seconds_this_run", round(time.time() - t0, 1))
    dump_json(env.derived / "build_stats.json", STATS)
    write_report(env, ctx)
    log(f"done in {time.time()-t0:.1f}s")
