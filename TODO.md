# TODO / known gaps

## Verification
- Browser verification of dist/zh.html is still pending. Check the Today flow, hear items with a real TTS voice, the typed-input flow, dark mode, and the phone and desktop layouts. So far the build has only had a Node syntax check and a jsdom click-through, which found no runtime errors.

## Behaviour differences vs hsk (intentional, from the extraction)
- **zh UX is now word-first.** hsk was pinyin-first and hid characters by default. The engine shows `w` (the characters), with `pron` (pinyin) beside it when "Show pronunciation" is on. The per-syllable tone colouring and the showChars, mixChars, and Characters subsystems are gone.
- **zh has no typed production** (`typing: null`). Typing hanzi needs an IME, and pinyin is display-only by rule. zh production is recall only. Revisit this if pinyin typing should come back: it could be done with an `alt`-style "typeable" field, but that would break the "pron never drilled" rule.
- **No per-word tap-to-hear inside sentences.** hsk rendered per-token pinyin spans. Sentences are now tapped as a whole.
- **Cloze (gap) items no longer auto-play the sentence** before answering, because hearing it gave the blank away. Audio plays on reveal.
- **The pinyin reference chart and the Test "Extras"** (tone pattern and typed pinyin drills) were dropped. A pack-supplied reference chart could replace the chart.
- **Two function words resolve to their base word.** hsk's function-word list included the compounds 你们 and 他们, which now resolve to their base words 你 and 他. As a result, 你 and 他 are never blanked, including inside 你们 and 他们.
- **`SENTENCE_EXTRA` compounds resolve to their base word's id.** For example, 这个 resolves to 这, which covers 140 of 5040 tokens. They are also listed in `pack.compounds`, so a cloze never blanks 这 inside 这个. `pack_from_hsk.py` also merges adjacent hsk tokens into one longer vocab word, longest match first (8 merges, such as 为+什么 into 为什么).
- **No migration from hsk's `hsk_pinyin` localStorage progress.** It was out of scope, and the ids differ: hsk keyed progress by the hanzi, the engine keys it by word id. A one-off importer could map w→id.

## Engine follow-ups
- Japanese live check 2026-09-25: the Words-tab example picker shows only dictionary-form sentences for 食べる (top 5 by rank all bare form) although 29 inflected examples exist; probably a shared selection preference: prefer at least one inflected example per verb (check every pack). Also ja pack.json `compounds` holds nonsense fragments (て、ア, 日、, いて話): the compound extraction for unspaced packs needs a real-word filter; harmless for cloze, fix with the ja passages round. Residual ja links: たった→ただ alt (4 sentences), どれ位/どの位→位 (2); 分 ぶん has two near-duplicate cards (w1219 A2, w0964 B1: regloss as "fraction"); drop ungrammatical Tatoeba line 来週の水曜日に会いしましょう.
- **Init-time state must be declared before the voice probe** (fixed 2026-09-25): app.html's voice probe (`pv()`) and its `onvoiceschanged` handler can run synchronously during script init, before the rest of the file has executed — e.g. Firefox on Windows returns a non-empty `getVoices()` list synchronously, with no voice for the pack's language, so `hasSpeech` flips on the very first call and `pv()` calls `render()` right then. Any top-level `let`/`const` that `render()`/`todayRender()` transitively reads (drill state, tab state, `samsungNoticeHTML`, ...) must be declared *before* the voice probe section, not merely before its own first use elsewhere — otherwise it's a temporal-dead-zone `ReferenceError` that blanks the page. New top-level state reachable from `render()` goes in the "app state" block near the top of the script, not declared inline where it's first used.
- **Tap-to-hear invariant** (fixed 2026-09-23): one delegated click listener on the persistent `#panel`, attached once at load. Never add per-render `addEventListener` on `#panel` or other persistent nodes; `el.onclick =` on freshly rendered nodes is fine. Recorded audio plays through a single shared audio object (core.js `audioSlot`). Not covered by the Node tests (DOM); verified with a jsdom probe that the old build fired 7 sounds per tap after 7 drills and the new one fires 1.
- **Script-aware accent fold** (2026-09-24): lenient typing and Words search fold only accents, stress and vowel pointing (core.js `FOLD_SCRIPTS`). Letters formed by a mark stay distinct: Cyrillic й/ї/ў, Arabic hamza letters (أ إ آ ؤ ئ ۀ), the Devanagari nukta (ज़ ≠ ज; this was folded before) and kana voicing marks. A new script with optional marks needs its range added there. The Russian repo's `index.html` was built from an older engine snapshot whose fold dropped every combining mark, so it accepts твои for твой until it is rebuilt with this engine.
- **pron hidden when it repeats the word** (`pronShown`). A pron that differs only by stress marks is still shown, because the stress is what it teaches.
- **Words search ranking**: whole-word matches on w, alt or pron come first, then a whole gloss sense, then a prefix match, then the rest.
- **Gap article rule** (2026-09-24): the cloze blank never includes an article, and every option is a bare form (core.js `gapMatch`/`bareForm`/`gapChoices`). An article found in the sentence stays visible before the blank (`à l'____`, `a la ____`). Articles come from the pack's `pos:"art"` words and their alts. Bare forms come from alt[0], else from stripping a leading pack article (so `le/la médecin` becomes `médecin`). A pack with no `art` words falls back to the alt[0] convention only. Only pack articles are cut, and only from nouns, or when the rest is the word's alt[0]. Fixed expressions like `un peu` are never cut. A span that keeps a reflexive clitic (`se lever`) is not blanked. An article visible before the blank selects distractors with an agreeing article: `la ____` offers la-nouns, and `den ____` offers der-nouns. Defaults for fr/es/it/de live in core.js `ARTICLE_AGREEMENT`, and `pack.articleAgreement` overrides them. Follow-ups: other gendered languages (pt, ro, ca...) need a table before agreement applies to them. Until then only an identical article counts as agreeing. `validate_pack.py` does not check the alt[0] convention.
- **Test tab**: the sentence test button stays hidden below 8 available sentences with no explanation. Consider a one-line "unlocks at 8 sentences" note.
- **Voice detection:** when the browser never reports a voice list, the engine optimistically assumes speech works. On browsers that report the list late, the first hear item may be spoken by a default voice.
- A missed **type** item is requeued until the learner types it correctly, as in hsk. Consider turning it into a recall item on the second miss.
- `rank` is validated but unused. Sets follow file order. Consider sorting by `rank` within each level at pack-build time.
- `pos` is used only by `wordOpts`. `meaningOpts` could also prefer the same pos.
- Cloze needs the word's surface form in `t`, found via `w` or one of `alt`. For heavily inflected languages, consider an optional per-sentence `forms` array aligned with `words`.
- Placement has a fixed 2/3 alternating item count per bucket. Consider making it pack-configurable.
- The Sounds hint text on Today is generic. Consider an optional pack field for it.
- ~~**RTL gloss popover**~~ done 2026-09-25 (PACK_SCHEMA.md reading "Script display"; needs a browser check on fa). Original note (Persian live check 2026-09-25): `#gloss` stays LTR for RTL packs, so the tapped word sits flush left with the English after it; only the inner `.gw` span is dir=rtl (PACK_SCHEMA.md ~143). For `pack.rtl` set `dir=rtl` + `text-align:start` on the popover container so the word anchors at the right edge and the pron/gloss follow in reading order; keep the English gloss span LTR. Bundle with the next engine republish.
- **Load-time follow-ups: DONE 2026-09-25** (engine 2dd8477: service worker with build-marker verification, non-blocking fonts; measured on the Italian canary vs Spanish baseline, headless Chromium, medians of 3): cold load event 1873 → 608 ms (font no longer blocks), cold FCP 676 → 504 ms, warm FCP 72 → 28 ms with 0 bytes from network (was a 304 round-trip), offline reload renders Today. Remaining ideas, low value now: lazy passages chunk (~100 KB gz), JSON.parse for the pack. Operational rule: sw.js is always committed with index.html (`engine/tools/check_site.sh` enforces it); never delete sw.js, use engine/sw.disable.js to turn it off.
- Optional per learner (toggle in Progress), off by default; enabled only when API exists and `pack.stt` locale is set (e.g. "it-IT", "fa-IR").
- Items: meaning → say the word; sentence cloze → say the missing word. Pass = normalised transcript (or any `maxAlternatives`) contains the target / an `alt`. No pronunciation score (recognisers auto-correct near-misses; a % would be fake precision).
- Never blocks: on no result / error fall back to `type`. Excluded from placement.
- Chrome 139+ has on-device mode (`processLocally`); default is server-based and needs network.

## Script support (added 2026-09-23)
- RTL verified in a real browser on the Persian pack (2026-09-24): Vazirmatn loads, dir/lang on all target nodes, cloze blank at the correct RTL position, ZWNJ forms joined, no overflow at 360/390. Still unverified: Nastaliq (Urdu) line height. Minor: speaker icons and the "Tap a word to hear it" hint still show when no TTS voice exists for the pack language (engine already converts Listen items to read items) — hide them in that case; Words-list pron column ragged for long headwords.
- validate_pack.py checks the script fields (`rtl`, `langTag`, `fontFamily`, `fonts`, `lineHeight`) with the same patterns as core.js, and warns when `rtl` is set without a font.
- Word-option distractors (recall and cloze) keep the answer's word class: a content-word answer never gets a `functionWords` distractor (fixed 2026-09-23).
- There is no per-word reading (furigana) alignment. A Japanese pack gives `sentence.pron` as one kana line, shown under the sentence.

## Follow-up: reading passages layer (proposed 2026-09-24, do after all packs ship)
**Engine side done 2026-09-24** (Read tab, `passages.json` schema + validator, weak-word inference, progress, tests; see docs/PACK_SCHEMA.md "passages.json"). Remaining: passage generation pipeline in packbuilder (LLM, lemma-coverage check, Opus QA), Italian pilot data, then fan-out. Not built: reading speed in Progress. Known, accepted: "Add to review" flags unlearned passage words `d`, so they count as learned for Today and for the 70% unlock (same as Words-tab drill-ahead).
"Read a passage, answer questions, infer weak words." Separate pass; pilot on Italian, then fan out.
- Data: no open graded-reader corpus for most packs. Generate passages at build time (LLM), hard-constrained to the pack's lemmas; validate with the tagger (reject <95% in-pack lemma coverage); link sentences to word ids as now. ~20 passages/level, 80–150 words, 4–5 questions. New pack file `passages.json`: {id, lv, title, text, sentences[{t,en,words}], questions[{q, options, answer, words[ids], sentence}]}. Opus QA pass per language.
- Inference: word-based only, no grammar inference (no grammar tagging exists). Signals → existing weakScore/misses: tapped word for gloss while reading (strong), wrong answer (medium, charged to the question's `words`), reopened passage during questions (weak).
- UI: "Read" tab, unlocked per level at ~70% of level learned; Today suggests 1 passage. Reading screen with tap-to-gloss (logged), optional TTS, "Done reading" → questions one at a time (MCQ/true-false), passage hidden with recorded "Show passage" → results: score, source sentence per question, "Weak words from this passage" auto-queued into next Today review (untickable). Progress: passages per level, reading speed.
- Effort: engine 1–2 days Opus worker + review, once. Data ~half day per language after pipeline exists; more for ur/fa/ar/hi.

## Minor (from live Italian regression check, 2026-09-24)
- Gap article agreement: after "un ____" feminine l'-nouns (l'informazione) can appear as distractors because the table maps un→l' and packs carry no gender field. Fix: builders emit a `g` (m/f) field on nouns and the engine prefers same-gender distractors when present.
- favicon 404 on every load on GitHub Pages; add an inline data-URI `<link rel="icon">` in app.html.

## Cross-pack policy follow-ups (2026-09-24)
- Gloss-level sensitive scan (vulgar/sexual/slur regex over glosses, A1/A2 must be clean) was introduced after German and Italian shipped. Re-run it on **german** and **italian** (rebuild with the flag on, republish) once the shared rule lands in packbuilder core. **Italian done 2026-09-24** (it.py `sensitive_gloss_re`; 0 glosses matched at any level, words.json byte-identical).
- Sentence filter scope (A1/A2): sexual content + threats/violence. Italian shipped before this rule; rebuild + republish Italian with `sensitive` enabled. **Italian done 2026-09-24** (it.py `sensitive_re` + `drop_all_levels`; A1/A2: 15 sentences replaced, 23 moved to B1, 1 dropped everywhere; ids frozen).
- ~~Drop-everywhere tier: sexual assault, suicide / self-harm in every language.~~ **Code done 2026-09-25** (`langs/base.py` `DROP_ALL_EN` + `drop_all_re(own)`; every spec merges its own-language terms: it violenza/aggressione sessuale, suicid*, uccidersi, farla finita; es agresión sexual, suicid*, matarse, quitarse la vida; fr agression sexuelle, suicid*, se tuer, mettre fin à ses jours; de sexueller Übergriff, Missbrauch, Selbstmord, Suizid, sich umbringen; ru сексуальное насилие, самоубийство, покончить с собой, убить себя; fa خودکشی; id kekerasan seksual, bunuh diri; ja 性的暴行, 自殺, 自傷; ko already had them). `check` already failed on a shipped match; tests in `tests/test_drop_all.py`. **Rebuild wave pending**: shipped sentences now matching (all B1): it 3 (s0553, s1849, s3131), fr 3 (s2071, s2568, s3161), de 1 (s1015), fa 2 (s2319, s2320 after the fix_links rebuild), id 2 (s0144, s2498), ja 3 (s2106, s2463, s2803); es, ru, ko 0. Words that lose every example on rebuild: it w1873 il suicidio, fr w1843 le suicide, fa w1599 خودکشی, ja w1409 自殺 (refill or drop them per spec). **Refill policy done 2026-09-25**: the word stays with one neutral written example in the language repo's `tools/generated_examples.tsv` (`spec.example_rows`, now a base default; tagged apart from the corpus, so ranks never move). Hand-reviewed example rows are exempt from `drop_all_levels` in the build and in `check`; `extra_corpus_rows` are not (`tests/test_policy_rows.py`). it, fr, fa rebuilt and refilled; **ja w1409 自殺 pending** (with the ja rebuild). Latent: the shared English stems also run on target text; it `rape[ds]?` (pre-existing) would drop an Italian sentence about turnips (rape); none shipped.
- ~~Word-level ceiling: Italian uccidere at A1 and il sesso at A2 while French has both at B1.~~ **Code done 2026-09-25; Italian resolved** (rebuilt): `langs/base.py` `WORD_CEILING_EN` + `make_word_ceiling_re(own)`, default `spec.word_ceiling_re` for every spec; `core/words.apply_word_ceiling` gives a matching word the top level as its `level_floor` after the gloss passes (ranks, ids, glosses unchanged; band-edge words shift one level each); `check` fails on a match below the top level. Rebuilt with it: it 8 (uccidere, arma, sangue, sesso, omicidio, droga, pistola, sessuale), fr 2 (sang, drogue), fa 6 (کشتن, خون, قتل, اسلحه, قاتل, سلاح). **Rebuild pending; their `check` fails on the engine bump until then**: es 9 (matar, arma, sangre, sexo, asesinato, droga, asesinar, sexual, asesino), de 8 (töten, Waffe, Sex, Blut, umbringen, Mord, Droge, Leiche), ru 8 (убить, убийство, кровь, оружие, погибнуть, убивать, секс, убийца), id 2 (senjata, narkoba); ko, ja 0.
- ~~fa کم‌کم vs کمکم "help me".~~ **Done 2026-09-25** (not a policy item): `spec.fix_links` core hook (sentence links + example choice only) and `spec.example_rows` (written examples tagged apart from the corpus, never frequency evidence). Persian rebuilt: words.json unchanged, passages.json unchanged; see persian/TODO.md.
- Gap blank on reduplicated inflections (Indonesian anak-anak, alat-alatnya, berjam-jam): the blank covers only one half. gapMatch should extend the span across a hyphen-joined repeat of the matched form (and a trailing clitic -nya) before rendering. 7/4110 Indonesian gap candidates.
- ~~Read tab: inflected forms in passage text not tappable inline (chips under the sentence).~~ **Done 2026-09-24**: `packbuilder passages` emits per-sentence `spans` [[start,end,wordId]] (UTF-16 offsets, from the tagger tokens); core.js `passageSegments` prefers spans and falls back to surface matching for ids without one. Italian: 543 sentences, 6338 spans, 11 ids left without a span (all one token claimed by two ids: `links_all` adds a classify id for a token sentence_links already linked, e.g. come w2012+w2017, scusa w0469+w2137; plus per/il favore inside the `per favore` phrase span). Follow-up **done 2026-09-24** (not yet rebuilt into italian/pack): `links_all` gives one id per token. A phrase owns its tokens, and the fallback never re-links a token the primary pass linked. The scratch relink removes exactly those 11 ids from `words`. No id is left without a span, spans go 6338 -> 6339 («La gains il), and REPORT_passages is unchanged.
- **id passages: batch-dependent tagging.** `id.tag_texts` rescues a capitalised common word from PROPN using lowercase counts across its batch (`lowc`/`capc`, `lowpos`). `packbuilder passages` tags only the passage texts, so it has less evidence than the corpus build. When id passages are authored, compare their PROPN tags with the corpus tagging, for example by tagging the passage texts appended to a corpus sample. If they differ, seed the rescue counts from the tagged corpus.
- **Main pipeline: `per favore` also links per + il favore in sentences.json** (it has neither `phrase_token_spans` nor `phrase_absorbs_parts`). 21 Italian example sentences carry w2135 together with w0009 and w0241. Making the phrase own its parts keeps words.json identical but re-picks 1084 of 3152 sentences (a 2026-09-24 experiment), so it was not changed. Do it as a deliberate Italian rebuild if wanted: set the policy per spec, and extend `phrase_absorbs_parts` beyond CONTENT_GROUPS so that `per` goes too.
- Open: the same span idea would highlight inflected headwords in ordinary example sentences (sentences.json has no spans yet).

## Licensing (user decision)
- vocab-engine has no LICENSE file (GitHub shows none). Pack READMEs list data/model licences but make no claim about the engine. Pick a licence (MIT suggested; note it_core_news_sm CC BY-NC-SA constrains the Italian *build*, not the engine) and add LICENSE here and a one-line pointer in each pack README.

## Generated audio for languages without browser voices (user 2026-09-24: keep in TODO, revisit later)
- Persian has no TTS on Apple/Windows/Google TTS and no Tatoeba clips, so the speaker is hidden for most users; Indonesian has no voice on Apple devices; Urdu will be the same. Option: render words + sentences offline with Piper (fa_IR voices, permissive licence) to Opus (~50–80 MB per pack) and serve from each repo's Pages site. Pack already carries per-sentence `audio`; word audio needs a small engine addition. Also: show a one-line "no voice for this language" note instead of silently hiding the speaker.

## Large items (user 2026-09-25; order revised 09:10 the same day)
Update 2026-09-25 14:35 (user): items 1 (hsk merge, design first in docs/HSK_MERGE.md) and 1b (Chinese passages: hooks + authoring) START NOW, in parallel with the Japanese publish/passages. Final hsk switch still last.
Order: (a) live-language follow-ups + Japanese/Korean live with passages,
(b) merge hsk's post-fork features INTO the engine (section 1 below, minus the
final switch), (c) Arabic, Hindi, Urdu, (d) switch hsk onto the engine
submodule as the LAST task (user 2026-09-25: go ahead without asking IF
nothing breaks — meaning: hsk branch first, full browser walk incl.
characters stage + learning-order switch, progress migration proven on a
real `hsk_pinyin` snapshot by diff, parity list ticked, rollback hash
recorded; otherwise stop and ask),
(e) B2 expansion. Progress is kept across the switch: hsk stores it under
localStorage `hsk_pinyin`, the engine under `vocab_<key>`; the switch ships
a one-time migration that reads `hsk_pinyin` on first load, remaps word ids
where the rebuilt pack differs (id map recorded at pack build), copies the
characters-stage fields, and writes `vocab_zh`.

### 1. Merge hsk's post-fork state into the engine, then (last task) move hsk onto the engine
DECISION 2026-09-25 16:10 (user): pronunciation-first for zh (pinyin) and ja (kana); never start a logographic pack with the written form; UX and ease of learning over coding ease. Briefs BP (pronFirst) and BP2 (restore per-word taps, tone colouring, typed pinyin, pinyin chart) follow the B8 polish; see docs/HSK_MERGE.md §8.
BP2 addition (browser recheck 2026-09-25 16:20, cosmetic): phrase-span popovers show the linked word headword+pinyin (越 yuè for 越来越, 下 xià for 一下); use the tapped span surface (with its reading when available) as the popover headword.
STATUS 2026-09-25 16:00: design docs/HSK_MERGE.md; briefs B0–B7 merged on main (characters stage core + app, zh characters.json/ruby/legacy map, ja ruby + kanji units, migration core + boot hook + tools/diff_hsk_migration.js, flag-off golden harness); B8 review + browser walk done (no blockers), polish round in progress. Remaining: polish merge, republish wave of live languages, Japanese rebuild with kanji stage, then the final switch (needs the user's real hsk_pinyin export and the pinyin-first decision).
EVIDENCE 2026-09-25 16:30: user supplied the real hsk_pinyin export (saved at .cache/hsk-switch/hsk_pinyin.real.json, untracked): v2 with zero word/sentence/character records, showChars=false, mixChars=true, charsAfterHsk4=false. tools/diff_hsk_migration.js on it: unmapped 0, roundtrip differences 0, derived views all same, RESULT PASS. Because the export carries no progress, the populated-record proof rests on the migration_checks fixtures; the real-export condition for the final switch is met. Browser walk (B8 + popover recheck) is 10/10. Still needed before the switch: BP/BP2 merged, republish wave, hsk branch first, rollback hash 3aeecc4, parity list §5.
hsk (`../hsk`, read-only until the user says go) kept evolving after the
2026-09-23 extraction: characters stage (v2.2/v2.3, 10 new / 16 drilled per
day, unlocks after HSK 3), learning-order switch (characters before/after
HSK 4), unified Review/Recall, Samsung Internet audio notice, plus two fixes
the engine already has in another form (teach-row overlap, double speak).
Plan: diff `hsk/src/pinyin_core.js` + `pinyin_app.html` against
`engine/core.js` + `engine/app.html`; port the hsk deltas as pack-gated
features (`hasCharacters` + character data in the pack; unified
Review/Recall as default if it is simply better; Samsung notice
unconditional); rebuild the Chinese pack from hsk's current data with
`tools/pack_from_hsk.py`; migrate the progress localStorage key to `vocab_zh`;
switch hsk to the engine submodule; browser-check the full HSK path incl.
the characters stage. The characters stage needs its own tests. Second consumer: Japanese (kanji stage: unlock after A1/A2, drill kanji reading + meaning, mixed kana/kanji sentences from the Tatoeba furigana data the ja builder already uses), so design the flag and data shape for both scripts from the start; Korean and the others do not need it. Reference
list of what hsk would gain: `hsk/TODO.md`. Do this BEFORE the B2 expansion
so every pack is rebuilt once, on the merged engine.

### 1b. Chinese reading passages (user 2026-09-25, right after item 1)
DONE 2026-09-25 16:00 (a5de0e0): 60 passages, 15 per HSK level, two QA rounds; zh passage hooks (dictionary segmenter, phrase units, 没有 rule) + span display glosses (packs/zh/gloss_display.json, 4-element spans) + report self-checks for all languages. Ships to learners with the hsk switch. Residual: 走路 as a phrase unit; Italian numeral keys (Ventisette) not exempt in the self-check.
Author 60 passages for the engine's zh pack the same way as the other
languages (unspaced linking as in `langs/ja.py`; rules in any repo's
`tools/passages_src.json`; one Opus authoring pass + two QA rounds). They
reach learners only when hsk switches onto the engine (last task), so they
ship with that switch.

### 1c. Script primer stage (user 2026-09-25, after 1b, before ar/hi/ur)
A pack-gated "Script" tab for non-Latin packs, distinct from hsk's
characters stage: letter/jamo → sound, recognition, syllable and word
reading, using the pack's own words as examples, TTS for the sound; unlocked
before A1 with a "skip, I can read" option; placement untouched. Data: a
small per-pack table (`pack/script.json`: symbol, name, romanisation, sound
note, example word id, joining forms where the script has them). Consumers:
ko (Hangul, 40 jamo), ru (Cyrillic, 33), fa (32, joining forms), ja (kana,
92; kanji come from item 1's characters stage), ar/hi/ur (built with it from
the start). zh keeps pinyin via the Sounds tab. Reverses the 2026-09-23
"script is not drilled" decision on purpose: an A1 learner cannot use a
Hangul or Devanagari pack without it.

### 2. Expand every pack from B1 to B2 (user is considering it)
Roughly 2000 → 4000 words per language (B2 ≈ ranks 2001–4000), a fourth
level in `placement`, `levels` and the Read tab (20 more passages at
110–150+ words), id maps extended (never renumbered), README scope lines
updated. Expect the low-resource corpora to strain: Korean (15.9k Tatoeba,
already 1,513 generated sentences), Persian (1,211 generated), Indonesian
(421) will need far more generated + reviewed sentences at B2; kaikki gloss
quality drops in the 2–4k rank band, so the gloss-scan and sensitive-gloss
filters matter more. Decide per language whether B2 is viable before
starting (measure candidate words with ≥2 corpus sentences in ranks
2001–4000). Order after the hsk merge (item 1) so the rebuild happens on the
final engine.

## Backlog (not scheduled)
- **Video stage** (user 2026-09-25: backlog only): level-graded YouTube
  videos per language with a timed transcript and passage-style questions,
  modelled as a passage with a video id; player hidden and item degraded to a
  plain passage when the embed reports unavailable; link check at build time
  only, no periodic recheck. Parked because curating videos that respect
  Islamic principles (no music, modest imagery, no objectionable content) is
  a manual per-video judgement the project cannot staff, and video is a
  one-time curation the user will not maintain. Revisit only with a curated
  source list.
