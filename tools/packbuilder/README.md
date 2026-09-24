# packbuilder

A shared, language-configurable builder for vocab-engine packs. It builds `pack/{pack,words,sentences,attribution}.json` and `tools/REPORT.md` in a language repo from public sources:

- a subtitle frequency list,
- `wordfreq`,
- a kaikki.org Wiktionary extract,
- Tatoeba sentences with English translations and audio.

A new language needs a language module (`langs/<code>.py`) and a few data files in its own repo. It does not need a fork of the pipeline.

The Italian pack (`key: "it"`) was the first language. The shared builder reproduces it byte for byte.

## Layout

```
packbuilder/
  cli.py              python3 -m packbuilder {build,check,scan,sample} --lang <code> --repo <path>; passages <repo>
  core/               language-agnostic stages
    sources.py        downloads into <repo>/.cache, the Tatoeba corpus stage, audio recorders
    tag.py            truecasing and tagging (cached): tag_docs/doc_tokens run spaCy or spec.tag_texts (fa, id: Stanza)
    lex.py            kaikki -> compact lexicon + form map (cached)
    lexicon.py        token -> (lemma, POS) resolution with context rules
    freq.py           corpus usage pass, frequency blend
    english.py        English stemming for gloss <-> translation overlap
    gloss.py          gloss cleaning, sense ranking
    words.py          pool, entry/sense choice, second-POS entries, levels (assign_levels), ids (assign_ids)
    sentences.py      in-context links, sentence choice, -rsi gate
    report.py         REPORT.md (keeps the manual section)
    pipeline.py       stage driver (finish_words: sentences, refill, finalize_words), pack.json, attribution.json
  passages.py         reading passages: tools/passages_src.json -> pack/passages.json
  langs/base.py       LanguageSpec: the interface and its defaults
  langs/it.py         Italian
  langs/ru.py         Russian (ё/е folding, pron = stressed form, aspect/gender gloss suffixes)
  qa/check.py         hard gate: schema, ids, levels, coverage, spec.check_word
  qa/scans.py         review scans 1-3 (gloss junk, articles/closed sets, non-lemmas)
  qa/sample.py        stratified word/sentence samples for hand QA
  tests/test_spec.py  stdlib unittest smoke tests
  requirements.txt
```

## Language repo contract

A language repo includes vocab-engine as a submodule at `engine/`, and it holds these files:

```
pack/                      generated pack (commit it)
tools/build_pack.py        shim: PYTHONPATH=engine/tools python3 -m packbuilder build --lang <code> --repo .
tools/gloss_overrides.json hand gloss fixes, "lemma|pos": "gloss" (keys starting with _ are comments)
tools/forced_a1.txt        A1 core list: [NOUN] / [VERB] / [ADJ] / [ADV] headers, then lemmas
tools/id_map_v1.json       frozen "lemma|pos" -> word id (keeps learner progress across rebuilds)
tools/REPORT.md            generated; text between <!-- manual:begin/end --> is kept
build.sh check.sh README.md TODO.md
.cache/                    gitignored: downloads + derived/ (corpus, tagged corpus, lexicon)
```

Caches are keyed by `LanguageSpec.versions` and the source file names and sizes. Bump a version when that stage's code, or the language's rules for that stage, change. Otherwise the cached tagged corpus is reused. Tagging is the slow stage, about 7 minutes for 650k sentences.

## Commands

```sh
pip install -r engine/tools/packbuilder/requirements.txt   # plus the language's spaCy model, see below
export PYTHONPATH=engine/tools                             # from the language repo
python3 -m packbuilder build  --lang it --repo .           # [--stage corpus|tag|lex|freq|words|all] [--check-remote]
python3 -m packbuilder check  --lang it --repo .           # exit 1 on failure
python3 -m packbuilder scan   --lang it --repo . [--only 1|2|3]
python3 -m packbuilder sample --lang it --repo . --seed 303
python3 -m packbuilder passages . [--lang it] [--check]    # reading passages, see below
python3 -m unittest discover -s engine/tools/packbuilder/tests -t engine/tools
```

### Reading passages

`passages` tags `tools/passages_src.json` with the language's own tagger through the same entry point as the tag stage (`core/tag.py` `tag_docs` / `doc_tokens`: spaCy, or the spec's `tag_texts` for Stanza languages), in one batch. spaCy is not imported for a Stanza language, so run fa/id with the repo's own `.venv` (it has Stanza). The link context is rebuilt from the cached corpus with the build's full word pass (`pipeline.finish_words`: refill_unexampled and `finalize_words`) and must match `pack/words.json`. Span alignment (`token_offsets`) matches tagger surfaces in the text. `span_fold` (a per-character fold of text and surfaces, fa: Arabic yeh/kaf, ZWNJ, harakat) and `span_joiners` (text characters a `tag_text` rewrite removed inside a token, fa: the space of "می روم") let it align folded surfaces. Both default to exact matching. Indonesian `tag_texts` is batch-dependent: its PROPN rescue counts lowercase uses across the texts it is given. Passage tagging gives it only the passage texts, so a capitalised common word may stay a name where the corpus build would rescue it. Check this when id passages are built. Run `tools/jsonify_pack.py` after writing so the generated `.js` stays in sync.

To work on packbuilder itself against a language repo, point the shim at your checkout with `PACKBUILDER_PATH=../vocab-engine/tools python3 tools/build_pack.py`.

## spaCy models and licences

The model runs at build time only, and packs ship no model files. The model licence still limits how the project can be used.

| lang | model | licence | trained on | note |
|---|---|---|---|---|
| it | `it_core_news_sm` 3.8.0 | CC BY-NC-SA 3.0 | UD Italian ISDT, WikiNER | non-commercial only |
| es | `es_core_news_sm` 3.8.0 | GNU GPL 3.0 | UD Spanish AnCora, WikiNER | copyleft |
| fr | `fr_core_news_sm` 3.8.0 | LGPL-LR | UD French Sequoia, WikiNER | |
| ru | `ru_core_news_sm` 3.8.0 | MIT | Nerus | |
| fa | none | | | spaCy 3.8 has no Persian pipeline. Another tagger is needed. |

These licences were checked against `explosion/spacy-models` `meta/<model>-3.8.0.json` on 2026-09-23. Install a model with its wheel, for example:

```sh
pip install https://github.com/explosion/spacy-models/releases/download/es_core_news_sm-3.8.0/es_core_news_sm-3.8.0-py3-none-any.whl
```

## Adding a language

1. **Verify sources and their licences.** Record each one in the language README's sources table.
   - Subtitle frequency: hermitdave/FrequencyWords `content/2018/<code>/<code>_full.txt`, CC-BY-SA 4.0.
   - `wordfreq`: check that the language is supported.
   - kaikki.org extract: `https://kaikki.org/dictionary/<Name>/kaikki.org-dictionary-<Name>.jsonl.gz`, CC-BY-SA 3.0/GFDL. Check that its `lang_code` is what you expect.
   - Tatoeba `<iso3>_sentences_detailed.tsv.bz2`, CC-BY 2.0 FR. Count the sentences that have an English link. The Italian pack had 650k.
   - Optionally, a CEFR list for the Kelly-style cross-check. It is never shipped.
2. **Choose the spaCy model and record its licence.** Use the table above. The licence goes into `tagger_attribution` and the README. When no model exists (fa), stop and decide on a tagger first. The tagging stage expects spaCy.
3. **Copy `langs/it.py` to `langs/<code>.py`** and fill in these fields:
   - Identity: `code`, `name_en`, `pack_name`, `tts`, `stt`, `tatoeba_code`.
   - Sources: `sources` and the role file names (`subtitles_file`, `kaikki_file`, `sentences_file`, `kelly_file`).
   - Model: `spacy_model`.
   - Cache versions: set `versions` to `c1`/`t1`/`l1`.
   - Orthography: `word_re`, `lex_word_re`, `sub_token_re`, `form_target_re` and `fem_of_re` for the alphabet. Set `accent_variants` only if the subtitles drop accents.
   - Wiktionary: `noun_head_template` (for example `es-noun`, `fr-noun`), `regional_tags`, and `group_kpos` if the UD and Wiktionary POS conventions differ.
   - Report wording: `report_title`, `forced_description`, `numeral_exclusion`, `marked_past_name`.
4. **Fill the forced sets.** `forced_closed` holds days, months, numbers, colours, greetings and any other closed sets. `no_article` holds nouns shown bare, and `allowed_num` holds the numerals allowed as words. Write the repo's `tools/forced_a1.txt`, an A1 core list of about 150-200 everyday words.
5. **Set up articles and gender.**
   - Fill `article_forms`, `definite_article`, `fixed_word` and `fixed_gloss` for the articles.
   - Fill `pluralia_tantum`.
   - Override `default_gender`, `noun_display` (how a noun is shown with its article) and `check_word` (the hard article assertion). Russian and Persian have no articles, so keep the base versions: nouns are shown bare.
6. **Set up clitics and reflexives.**
   - Fill `clitic_re` (verb + enclitic) and `mono_imperative`, and `art_prep` for articulated prepositions.
   - Fill `clitic_of`, `refl_clitics` and `copulas`, and set `verb_endings`.
   - Override `pronominal_base`/`pronominal_form` (it: -rsi; es: -rse; fr: se + verb, usually `None`), and override `is_reflexive`/`carries_refl_clitic`/`stative_aux` to match the language.
   - Override `is_marked_past` only for a literary tense that should be kept to the top level (it: passato remoto). Spanish preterite is everyday and must not be marked.
   - Tables left empty switch their rule off.
7. **Add hand tables only after a QA round shows a need.** These are `gloss_overrides.json`, `drop_keys`, `apocope`, `multiword`, `profanity` and `bad_text_re`. Fix categories with a rule first; a hand table is for residuals.
8. **Run and check.** Run `build`, then `check`, then `python3 engine/tools/validate_pack.py pack`, then `./build.sh`. Run the unit tests. The every-language test checks the new module's required fields.
9. **Do three QA rounds.** Each round runs `scan` and reads every "should be empty" list. It then runs `sample` with a new seed and hand-checks the samples. Rounds so far used seeds 7, 303 and 404. Fix the rule behind each finding, rebuild, and record the rules, counts and seeds in the manual section of `tools/REPORT.md`. The pack ships when all of these hold:
   - at least 95% correct primary sense on the 60-word stratified sample,
   - 0 wrong POS in the top 300 by rank,
   - at least 95% link accuracy on the 60-sentence sample, counted over its links,
   - every closed set complete at the first level (scan 3),
   - `check` passes and the validator reports 0 errors.
10. **Browser verification.** Build `index.html` and check the pack in a real browser: every tab, TTS voice for the locale, typing with accents at each level, gap items, and audio playback. Check at phone width, 390px.
11. **Publish.**
    - Create a public repo `<language>` with `engine/` as a submodule, and commit `pack/`, `index.html` and `tools/` data.
    - Enable GitHub Pages from the repo root.
    - When the language module is new or changed in vocab-engine, commit that there first. Then bump the submodule in the language repo with `git submodule update --remote engine`, rebuild, and check that `./check.sh` passes.

## Normalisation and finishing hooks

Added for Russian; each defaults to a no-op, so other languages are unchanged.

- `fold(s)`: spelling folded on every matching side (Wiktionary headwords and form targets, frequency-list and wordfreq surfaces, summed). ru: ё -> е, stress marks stripped.
- `tag_text(text)` / `fix_token(tok)`: the sentence text fed to spaCy and a per-token fix of the stored `[text, lemma, upos, morph]`. Bump `versions["tag"]` when they change.
- `morph_keep`: UD features kept in the tagged corpus (ru adds Case and Aspect).
- `fallback_lemma(surface, lemma)`: rejects a simplemma fallback lemma (ru: abbreviation expansions such as мм -> миллиметр).
- `sentence_rank(toks, lv)`: sort penalty when choosing example sentences (ru: A1 prefers Nom/Acc nouns).
- `shares_gloss(lemma, other)`: exempts a pair from the gloss-collision rule (ru: aspect partners).
- `finalize_words(env, ctx, words)`: last pass over the word list after sentences; may set `pron` (ru: display spelling, stressed form, aspect suffix).
- Flags: `numeral_verb_rule` (off in ru: "три" is not тереть), `rare_zipf` (rare-reading threshold), `finite_verb_lemma` (a finite token keeps the tagger lemma over a same-spelling infinitive: ru "есть" = is).
- `extra_wordfreq(raw)`: extra wordfreq surfaces after the main loop (ru: hyphenated words such as кто-то, which wordfreq splits at the hyphen).
- `drop_all_levels`: regex (text or English); matching sentences are removed at every level (rape, sexual/child abuse). `check` fails if a pack sentence matches. ru sets it; `sensitive_re` stays the A1/A2 tier.
- `audio_rank_bonus`: a sentence with native audio has its `sentence_rank` penalty lowered by this (ru: 5, audio first after the level key).
- `bare_prefer_shared`: with `example_shows_word`, the bare-form sentence is picked with audio first, then one already chosen for another word.
- `derived_form_tags` also takes gloss phrases (ru: "female equivalent"), and `clean_sentence_text` strips stress marks (ru).
- `surface_link_ok(tok)`: may an unresolved token fall back to linking by surface (ru: not "О нет!" -> о "about").
- `refill_unexampled`: words left with no example sentence (and not forced) are dropped and the next words by rank take their place (one extra words+sentences pass).
- `caps_proper_pool`: gates the capitalisation-based proper-noun test in word selection, separately from `caps_mark_names` (ru: off, so Земля and Бог stay).
- `core/gloss.strip_gloss_style(gloss)`: shared strip list for Wiktionary style leaks ("mutually reflexive", "diminutive:", quoted words, thy/hither/whither, "to dun", "one wants", "as ... as"); not called by core, a spec calls it (ru from `finalize_words`).

## Lemma, gloss and selection hooks

Added for Spanish; each defaults to off or a no-op, so Italian stays byte-identical.

- `accent_candidates(s)`: accent-split readings of a surface (es: si/sí, el/él, solo/sólo).
- `clitic_stem_tries(stem)`: stems tried when stripping enclitics (it: stem, stem+e, stem+'; es: host check for dímelo, dándole).
- `surface_lemma(surface, upos)`: fixed lemma, or (lemma, group), for a surface (es: mis -> mi DET, eso own lemma, cómo PRON -> ADV).
- `sentence_openers`: characters stripped before truecasing (es: ¿¡). Bump `versions["tag"]`.
- `lemma_tiebreak_corpus`: ties between lemmas sharing a form break on corpus lemma votes (creo: creer over crear).
- `copula_inflected`, `numeral_may_be_verb`, `after_article_is_noun`, `object_clitics`, `post_resolve`: in-context POS fixes (es: "son animales" is a noun, "un poco" not a noun, "la amo" a verb, fue a -> ir).
- `form_colon_translation`: form-of glosses "X of Y: translation" also yield the translation (es: tía).
- `strict_selection`: drops "?" POS keys, single letters, English homographs rare in the corpus, and noun keys whose entry is not a noun.
- `phrase_bound_share` / `phrase_absorbs_parts`: words mostly bound in a taught phrase are dropped, and a phrase match removes its literal part links (embargo in sin embargo).
- `imperative_homograph(lexicon, lemma)`: noun homographs of an imperative+clitic.
- `revert_dedupe_gloss`: a reverted -se verb whose base and reflexive glosses lead the same shows one gloss (on for es; would change 4 Italian glosses).
- `marks_sentence(toks)`: extra top-level marker (es: voseo and regional slang kept out of A1/A2).
- `phrase_token_spans`: phrases match by token after splitting `art_prep` contractions ("a pesar del"); every token inside a match links only the phrase, and a contraction's leftover article still links.
- `closed_surfaces` / `function_lemmas`: surfaces resolved to a fixed (lemma, group) whatever the tag, even PROPN, and always counted as function words (es: vosotros, contigo).
- `numeral_group(lexicon, surface, lemma)`: group for a NUM token (es: only cardinals stay NUM; ambos, medio take their dictionary POS).
- `sense_tags(tags)`: lex-time sense tag normalisation (es: a sense tagged for Spain, Latin America or 3+ countries is standard). Bump `versions["lex"]`.
- `propn_lowercase_rescue`: a lemma seen lowercase mid-sentence this often is not a proper noun (es: tierra, dios).
- `homograph_by_translation` / `homograph_cues`: when a lemma has two entries, the English translation picks the one whose gloss (or cue) words it contains (solo "only" vs "alone").
- `needs_gender_evidence(lexicon, lemma)`: a noun with separate m and f entries links only with gender evidence (el frente / la frente).
- `initial_noun_verb_homograph`: a bare clause-initial noun with a verb reading, not followed by a finite verb, is the verb ("Estudio inglés").
- `translation_mismatch(toks, en)`: drop a sentence whose English contradicts it (es: pronoun gender).
- `prefer_headword_sentence`: sentence choice puts first a sentence showing the headword or an alt, then (verbs) one with a 3sg present form, so the engine's first example shows the word as taught.
- `derived_form_tags`: lex: form-of senses with these tags (es: diminutive, augmentative) are words of their own, not inflections of the base (señorita is not señora). Bump `versions["lex"]`.
- `fallback_rarity_margin`: when no reading fits the tagged POS, keep the tagger's lemma rather than a surface reading this many zipf rarer (es "linda" is not lindar); the token then links nothing.
- `sensitive_gloss_re`: a sense matching it never leads or joins a gloss while a clean sense exists; `check` fails on any below-top-level gloss that still matches. `SENSITIVE_GLOSS_EN` in `langs/base.py` is the shared English list (vulgar and sexual senses: es mamar, perra).
- `verb_homograph_ratio`: a surface that is a form of several verbs goes to the one the tagger's person, then Sub/Imp mood, uniquely fits (only when every reading is a listed form), else to a lemma used this many times more in the corpus (crees: creer, pare: parar). A lemma used 6x the ratio more always wins (vete: ir, not vetar).
- `fallback_same_class`: a NOUN/ADJ-tagged token with no reading of its class falls back to nominal readings first ("video juego": juego, not jugar).
- `phrase_en_cues`: a phrase links only when the translation contains one of its cue words (es "de nada": welcome).
- `sensitive_re`: sentences matching it (text or English) are kept to the top level, except as examples of a word that itself matches (and then levelled at the top). Cross-pack policy: sexual content and threats/violence stay out of A1/A2. `langs/base.py` `SENSITIVE_EN` is the shared English half; each spec adds its own-language terms (es: matar, asesinar, disparar, "estás muerto").

## Passage hooks

Used only by `passages` (never by `build`); each defaults to off, so other languages' passages stay byte-identical.

- `passage_post_resolve(toks, out)`: resolve rules after `post_resolve`, applied only in passages (the Linker wraps the lexicon's `resolve_sentence`, so classify and `sentence_links` both see them); the corpus build never runs them. es: fue/fui are ser in a cleft "lo que aprendí fue a confiar", "fui una de", "fue muy agradable"; "fuera de", "por fuera", clause-final fuera are the adverb. Moving such a rule into `post_resolve` changes sentence links and needs that language's rebuild and QA.
- `truecase_after`: characters after which a capitalised word opens quoted or exclaimed speech and is truecased like a sentence start (`core/tag.truecase_after`). es: `«¡¿` ("dice: «Me gusta»", "gritaron: «¡Feliz...!»"); names stay capitalised by the corpus counts.
- `truecase_after_end`: characters after which (plus whitespace, mid-text) a capitalised word is truecased the same way, but only when the lexicon has a lowercase reading of it. es: `!?` ("—¡Perfecto! Compro las entradas").
- `surface_reading_fallback`: a counted token whose reading is out of the pack links the most frequent other dictionary reading of the same surface that is a pack word (es: lowercase "leo"/"vuelve" tagged PROPN -> leer/volver, "escucha" as a noun -> escuchar, "contenta" as contentar -> contento). A sentence-initial PROPN is skipped: a name the truecaser lowered ("Lucía" is not lucir) is declared in the passage's `oop`. Candidate for other languages after their own passage QA.

Always on (all languages): a counted token with no pack id inside a matched pack phrase links that phrase ("favor" in "por favor", "embargo" in "sin embargo").

The link context is pickled with the spec attributes the fresh build set (`bind_lexicon` handles such as es `_lex`, fr/id `_lx`, derived sets such as de `pluralia_tantum`); a cached run restores them instead of re-running `bind_lexicon`, whose lexicon edits are already in the pickle. A cached run gives the same output as a fresh one.

## Determinism

The build has no randomness. Every iteration over sets and dicts that affects output is sorted, and gzip caches are written with `mtime=0`. Two runs with different `PYTHONHASHSEED` values give byte-identical `pack/*.json` and `REPORT.md`. Recheck this after adding a language.
