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
- There is no service worker or offline manifest, as in hsk.

## Follow-up: `speak` question type (decided 2026-09-23)
Production drill using Web Speech API `SpeechRecognition` (Chrome/Edge/Safari; Firefox flag-only; needs HTTPS + mic, not file://).
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
- Gloss-level sensitive scan (vulgar/sexual/slur regex over glosses, A1/A2 must be clean) was introduced after German and Italian shipped. Re-run it on **german** and **italian** (rebuild with the flag on, republish) once the shared rule lands in packbuilder core.
- Sentence filter scope (A1/A2): sexual content + threats/violence. Italian shipped before this rule; rebuild + republish Italian with `sensitive` enabled.
- Gap blank on reduplicated inflections (Indonesian anak-anak, alat-alatnya, berjam-jam): the blank covers only one half. gapMatch should extend the span across a hyphen-joined repeat of the matched form (and a trailing clitic -nya) before rendering. 7/4110 Indonesian gap candidates.
