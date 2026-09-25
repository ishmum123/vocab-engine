# Pack schema

A pack is one directory of JSON files that holds all the language-specific data. The engine reads nothing else.

```
<packdir>/
  pack.json        required  metadata and rules
  words.json       required  vocabulary
  sentences.json   required  example sentences (may be [])
  lessons.json     optional  "Sounds" tab lessons; required when pack.hasLessons is true
  passages.json    optional  "Read" tab graded passages with questions
  characters.json  optional  character-stage units; required when pack.characters is set
  legacy.json      optional  old-app id maps for one-time progress migration
  pack.js words.js sentences.js lessons.js characters.js legacy.js   generated, never edit by hand
```

The `.js` files are generated with `python3 tools/jsonify_pack.py <packdir>`. They hold the same data as `const PACK=`, `WORDS=`, `SENTENCES=`, `LESSONS=`, `CHARACTERS=` and `LEGACY=`, so the app can load them from `file://` and `build.sh` can inline them. `passages.json` has no file of its own: its `const PASSAGES=` is appended to `sentences.js`, so `build.sh` and the dev loader need nothing new, and a pack without passages gets exactly the `sentences.js` it had before. `characters.json` and `legacy.json` follow `lessons.json`'s pattern instead: their own optional generated file, present only when the source `.json` is. `tools/validate_pack.py` fails when they are stale.

## pack.json

| field | type | required | meaning |
|---|---|---|---|
| `key` | string `[a-z0-9_-]+` | yes | Pack identity. Progress is stored under the localStorage key `vocab_<key>`. Changing it orphans learners' progress. |
| `name` | string | yes | Display name and page title, e.g. `"Mandarin (HSK 1–4)"`. |
| `tts` | string | yes | BCP-47 locale for speech synthesis, e.g. `"zh-CN"`, `"it-IT"`. A voice with the exact locale is preferred, then any voice for the same language. |
| `ttsRate` | number 0.1–3 | no (0.9) | Speech rate. |
| `levels` | `[{id, label}]` | yes | Ordered levels. `id` is a string (`"1"`, `"A1"`), `label` is shown in the UI. The order drives set unlocking and "past this level" logic. |
| `setSize` | positive int | no (10) | Words per learn set. |
| `placement` | `[[levelId, bucketCount], …]` | yes | Placement-test buckets, in level order. Each level's sets are split into `bucketCount` contiguous buckets. Buckets alternate 2 and 3 test items, so 16 buckets give a 40-item test. Every bucket needs at least 3 words. Levels before the first listed level count as known once the first bucket passes. |
| `functionWords` | `[wordId]` | no | Word ids never blanked in cloze (gap) items: articles, pronouns, particles. They are also a word class for options: a content-word answer in recall or cloze never gets a function-word distractor, and a function-word answer gets other function words first. |
| `articleAgreement` | `{article: [article]}` | no | Cloze distractor agreement. Each key is an article that can appear right before a blank, including contractions (`la`, `l'`, `den`, `del`). Its value lists the citation articles of the words it agrees with (`"den": ["der"]`). Distractors cited with an agreeing article are offered first, so the visible article never gives the answer away. Defaults exist for fr, es, it and de (core.js `ARTICLE_AGREEMENT`), picked by `langTag` or the `tts` language. A key missing from the table agrees only with itself. |
| `typing` | object or `null` | no (`null`, validator warns when absent) | `null` turns off typed production. Recall items are used instead, so review still keeps at least 40% production. Object fields are listed below. |
| `typing.caseSensitive` | bool | no (false) | When false, both sides are lowercased before comparing. |
| `typing.accents` | `"lenient"` or `"strict"` | no (`"lenient"`) | With lenient, optional marks are folded on both sides: Latin accents (`perche` = `perché`), stress marks (`молоко́`), Arabic-script harakat and tatweel, Hebrew points, the Devanagari nukta, and ZWNJ/ZWJ (`میروم` = `می‌روم`). Marks that make a different letter are kept: Cyrillic й and ї, Devanagari vowel signs, and kana voicing marks. Strict never folds them. Arabic kaf and yeh always equal their Persian/Urdu forms (ک, ی), in both modes, because keyboards produce either. |
| `typing.strictFromLevel` | levelId or `null` | no | With lenient accents, folding stops at this level and every later one. `null` means lenient at every level. |
| `showPron` | bool | yes | Whether words and sentences carry `pron`. It sets the learner's default for the "Show pronunciation" toggle. When false, the toggle is hidden. |
| `hasLessons` | bool | yes | Shows the Sounds tab and the Today lesson hint. |
| `compounds` | `[string]` | no | Surface strings that are not drillable words but that a cloze blank must never cut into. For example, zh 这个 is listed so that 这 is never blanked out of it. Pack words' own `w`/`alt` are always protected this way; this list covers units that aren't words. |
| `spaced` | bool | no (true) | Whether the script separates words with spaces. When true, cloze matching is whole-word and case-insensitive; ZWNJ/ZWJ count as part of a word, so Persian `می` never matches inside `می‌روم`. When false, as in Chinese or Japanese, it is a plain substring match. |
| `rtl` | bool | no (false) | The target script is right-to-left (Persian, Arabic, Urdu). Target-language text gets `dir="rtl"`; see "Script display" below. |
| `langTag` | BCP-47 string | no (language part of `tts`) | `lang` attribute on target-language text, for font selection, line breaking and hyphenation, e.g. `"fa"`, `"ur"`, `"ja"`. An invalid tag falls back to the default. |
| `fontFamily` | string | no | CSS font-family list for target-language text, e.g. `"\"Noto Nastaliq Urdu\", serif"`. It is placed before the engine's default stack. A value containing `;`, `{`, `}`, `<`, `>`, `\`, `/*` or `url(` is ignored. |
| `fonts` | `[string]` | no | Google Fonts families the page loads, e.g. `["Noto Nastaliq Urdu"]`, `["Noto Naskh Arabic:wght@400;700"]`, `["Noto Sans Devanagari"]`. Each entry is a family name (letters, digits, spaces), optionally followed by a css2 axis spec. Invalid entries are skipped with a console warning. |
| `lineHeight` | number 1–4 | no | Line height for target-language text. Use it for tall scripts, e.g. `2.2` for Nastaliq. When absent, the stylesheet's own line heights apply. |
| `characters` | object | no | Turns on the character stage; see "characters" below. Absent, no character code path runs and `characters.json` must not exist. |
| `legacy` | `{key, format}` | no | Marks this pack as the successor to an old standalone app's saved progress, for a one-time migration. `key` is the old app's localStorage key (e.g. `"hsk_pinyin"`); `format` is a migration-function tag (e.g. `"hsk-v2"`). Requires `legacy.json`. |

### Script display

Every element that shows target-language text carries `lang` (from `langTag`) and, when `rtl` is true, `dir="rtl"`. It also uses `fontFamily` and `lineHeight` when they are set. These elements are headwords, sentence text, word options in recall and cloze items, the cloze sentence with its blank, the typed-answer input, Words-list and teach-card rows, example sentences, reveal blocks, and lesson `rows` word cells and `say` buttons. English glosses, translations and `pron` never carry them, so they stay left-to-right.

- Block elements align to their start side, which is the right in RTL. The big headword stays centred.
- Inline target text inside a mixed line, such as an option button with its number and `pron`, is wrapped in `<bdi>`, so the line never reorders. Word option buttons in RTL packs also run right-to-left, with the number on the right.
- The cloze blank `____` is bidi-isolated, so it sits where the missing word was in RTL text too.
- The Words search box uses `dir="auto"`.

**External resources.** The only external resource a built page may load is Google Fonts. The page always loads IBM Plex Sans, and it loads `pack.fonts` at runtime through a `fonts.googleapis.com/css2` URL built by core.js `fontsHref`. No other URL can come from a pack. Neither font stylesheet blocks first paint: IBM Plex is a `preload` that becomes a stylesheet once loaded, and the `pack.fonts` link starts as `media="print"` and switches to `all` on load. Text shows in the fallback stack until the webfont arrives (`display=swap`).

**Pronunciation.** `pron` is display-only. With "Show pronunciation" on (the default comes from `showPron`), a word's `pron` is shown under the headword, beside it in word options, Words-list rows and teach-card rows, and under the word in every reveal. A sentence's `pron`, such as a kana line or romanised Russian with stress marks, is shown under the sentence in read items, example sentences and reveals. It is never shown before a hear or cloze item is answered, because it would give the answer away.

**Example-sentence highlighting.** In teach cards and reveals, the taught word is bolded in each example sentence wherever it is visible. The word is found the same way as for cloze: `w` and every `alt`, whole-word when `spaced`, overlapping hits merged into the widest one. A hit inside a longer pack word or compound is not bolded, so 本 inside 日本 is left plain. When the word is not visible, as when it appears only inflected and no `alt` matches, nothing is bolded. This is core.js `highlightParts`.

**Words search** matches the query against `w`, every `alt`, `pron` and the gloss. Both sides are lowercased and accent-folded as in lenient typing. Whitespace is also ignored, so `nihao` finds `nǐ hǎo`. This is core.js `searchWords`.

## characters

Optional. A **character stage** teaches written units (hanzi, kanji-words, …) alongside the word levels, reusing the one daily new-material slot. Absent, no character code path runs, and `pack/characters.json` must not exist.

```json
"characters": {
  "label": "字",
  "stages": [ {"after":"3","levels":["1","2","3"]}, {"after":"4","levels":["4"]} ],
  "setSize": 10,
  "mastered": 3,
  "bare": 6,
  "learnKinds": ["charPick","charRead"],
  "reviewKinds": ["charRead","charSound"]
}
```

| field | type | required | meaning |
|---|---|---|---|
| `label` | string | yes | Short name for the stage strip and Progress (`字`, `漢字`). A stage after the config's last level appends that level id (`字4`). |
| `stages` | `[{after, levels}]`, non-empty | yes | Each stage sits after word level `after` (a `pack.levels[].id`) and covers `levels` (a non-empty list of `pack.levels[].id`, in the same namespace `characters.json`'s `lv` uses). `after` values must be non-decreasing in `pack.levels` order, and every `levels` id may appear in exactly one stage. |
| `setSize` | positive int | no (`pack.setSize`) | Units per learn set, chunked in level order then file order within a stage. |
| `mastered` | positive int | no (3) | Streak at which a unit's tier becomes "mastered" (bare-form drilling). |
| `bare` | positive int, `> mastered` | no (6) | Streak at which a unit's tier becomes "bare" (plain text, no ruby). |
| `learnKinds` | `[string]`, non-empty | yes | Item kinds taught for each new unit, drawn from `charRead`, `charSound`, `charPick`, `charRecall` (see "Drill items" in `docs/HSK_MERGE.md` §2.5). |
| `reviewKinds` | `[string]`, non-empty | yes | Item kinds used once a unit is in Review/Recall, from the same set. |

`tools/validate_pack.py` checks `stages` (existing level ids, `after` order, one stage per level), the thresholds (`bare > mastered`), and that `learnKinds`/`reviewKinds` are known kinds.

## pack/characters.json

Required when `pack.characters` is set (and must be absent otherwise). Holds the units, in teaching order within each level: sets are consecutive runs of `setSize` units of one level, in file order.

`[{ id, t, words, lv, reading? }]`

| field | type | meaning |
|---|---|---|
| `id` | `c0001`…, unique | Progress key. Never renumber. |
| `t` | non-empty string | Written form, shown large. |
| `words` | `[wordId]`, non-empty | Linked words, ids from this pack's `words.json`. `words[0]` supplies the gloss and the audio. |
| `lv` | levelId | Must be one of `pack.levels[].id`, and covered by one of `pack.characters.stages[].levels` — decides which stage the unit belongs to. |
| `reading` | string | Optional. Answer for `charSound` and the ruby text. Defaults to the `pron` of `words[0]`. |

`tools/validate_pack.py` checks unique ids, that every `words` id exists, and that `lv` is both a pack level and covered by a stage.

## words.json

`[{ id, w, en, lv, pos?, rank?, pron?, alt? }]`, in teaching order within each level. Sets are consecutive runs of `setSize` words of one level, in file order.

| field | type | meaning |
|---|---|---|
| `id` | string, unique | Stable id. Progress is keyed by it, so never renumber a published pack. The zh pack uses `w0001`…. |
| `w` | string | The word as written. It is shown, spoken by TTS, and is the typed or recalled answer. |
| `en` | string | English gloss. It is the answer label in meaning items. Distractors avoid the same gloss and the same first two gloss words. |
| `lv` | levelId | Must be one of `pack.levels[].id`. |
| `pos` | string | Optional part of speech. Recall and cloze distractors prefer the same `pos` and level. |
| `rank` | number | Optional frequency rank. It is validated but not yet used, and set order is file order. |
| `pron` | string | Optional pronunciation (pinyin, IPA). It is display-only and never drilled or typed. |
| `alt` | `[string]` | Optional accepted alternative typed answers, such as a feminine form or other spelling. It is also used to find the word in a sentence for cloze when `w` itself does not appear, as with inflected forms. **Convention:** when `w` carries an article or clitic (`il gioco`, `l'anno`, `le/la médecin`), put the bare lemma first (`alt[0]` = `gioco`). The engine treats `alt[0]` as the word's bare form only when it is a whole trailing token of `w`, after a space or apostrophe (core.js `bareForm`). Without such an alt, a leading article from the pack's `pos:"art"` words (their `w` and alts, including a/b pairs like `le/la`) is stripped instead. **Cloze article rule:** the blank never includes an article. When the matched form carries one (`l'église`, `la iglesia`, an alt such as `l'acqua`), the article stays visible and only the bare rest is blanked (`allons à l'____`, `Bevo l'____.`). Every multiple-choice option, answer and distractors alike, is shown by its bare form (`église / gare / fruit`), never `la gare`. Prefer alts that are the word alone. Examples for a taught word prefer sentences where `w`, then an alt, is visible. |

## sentences.json

`[{ id, t, en, lv, words, pron?, audio? }]`

| field | type | meaning |
|---|---|---|
| `id` | string, unique | Progress key. |
| `t` | string | Sentence text in the target language. It is shown, spoken, and used for cloze. |
| `en` | string | Translation, used as the answer label and in sentence distractors. |
| `lv` | levelId | Level. A sentence becomes available once all its `words` are learned, or once the learner is past this level. |
| `words` | `[wordId]` | Word ids used in the sentence, resolved at pack-build time with no runtime lookup. A cloze candidate must pass four rules. It is at the sentence's own level. It is not a function word. It is not repeated in `words`. Its forms (`w` plus every `alt`) appear exactly once in `t` overall, where overlapping hits count as one. That occurrence must also not sit inside a longer pack word or compound, such as 为 inside 为什么. |
| `pron` | string | Optional display-only pronunciation of the whole sentence. |
| `audio` | URL string | Optional recorded audio. When present it plays instead of TTS. Relative URLs resolve against the built HTML file's location, not the pack directory, so ship audio beside the built page or use absolute URLs. |
| `ruby` | `[[start, end, reading, wordId]]` | Optional, only meaningful with `pack.characters`. Per-token readings for characters tiering: each tuple is a UTF-16 offset range into `t` (`end` exclusive, same convention as `passages.json` `spans`), the reading text for that range, and the `characters.json` unit's `words[0]` id that range belongs to (so 这个 maps to its base word). Tuples are sorted, non-overlapping, and each covers non-blank text without splitting a surrogate pair. A sentence with `ruby` renders `<ruby>t<rt>reading</rt></ruby>` per token below the `bare` tier and plain `t` at or above it. |

## lessons.json

Optional. The shape is unchanged from hsk's `LESSONS`.

```
[{ id, title, blurb,
   cards: [{ h, body, rows?: [[col1, col2, col3]], say?: [string] }],
   items: [{ t: "mc", q, say?, opts: [string], a, rv? }] }]
```

- `body` is trusted HTML written by the pack author. Everything else is escaped.
- `rows` render as three columns: pronunciation, word, gloss.
- `say` entries are spoken by TTS on tap.
- An item's `say` is played when it starts. With no usable voice, an item whose `q` already contains the `say` text runs as is. An item whose `say` text contains the answer is skipped, with a notice. Any other item shows the `say` text in place of the audio. This is core.js `lessonSayMode`.
- In `items`, `t` must be `"mc"`. It is the only item type, and the engine skips any other. `a` must be one of `opts`, and the options must be distinct. `rv` is the text revealed after answering.

## passages.json

Optional. When present and non-empty, the app shows a **Read** tab. Without it nothing changes.

```
[{ id, lv, title, text, src?,
   sentences: [{ t, en, words: [wordId], spans?: [[start, end, wordId]] }],
   questions: [{ q, en?, type: "mc"|"tf", options: [4 strings] | null, answer, words: [wordId], sentence }] }]
```

| field | type | meaning |
|---|---|---|
| `id` | string, unique | Progress key (`prog.read.done`). Never renumber a published pack. Convention `p0001`…. |
| `lv` | levelId | Must be one of `pack.levels[].id` (`"A1"`, `"A2"`, `"B1"`; zh would use `"1"`…). |
| `title` | string | Target-language title, shown in the passage list. |
| `text` | string | The full passage. Each `sentences[].t` should appear in it verbatim (warning otherwise). Length in the list is whitespace tokens of `text`, or the linked word count when `pack.spaced` is false. |
| `src` | string | Optional provenance, e.g. `"gen"` for build-time generated passages. Not shown. |
| `sentences[].t` | string | One sentence of the passage, rendered in order. |
| `sentences[].en` | string | English translation, shown in question feedback and results. |
| `sentences[].words` | `[wordId]` | Linked pack words. Each is tappable for its gloss: at its `spans` when it has any, otherwise wherever its `w`, an `alt` or its bare form is visible in `t` (core.js `passageSegments`, longest match wins, so 为什么 beats 为, and a surface hit never covers a span). A linked word with neither is shown as a chip under the sentence, so every linked word stays tappable. |
| `sentences[].spans` | `[[start, end, wordId, gloss?]]` | Optional. Where each linked word sits in `t`, as written by the builder from its tagger tokens (`packbuilder passages`), so inflected forms (mele, compra, va) are tappable in place. Offsets are UTF-16 code units (JavaScript string indices; equal to character indices for text without characters above U+FFFF), `end` exclusive. Spans are sorted and do not overlap, each `wordId` is in `words`, and a word may have several spans (one per occurrence). A multi-token unit the builder links as one word (per favore) is one span. `words` stays the full list: a word without a span falls back to surface matching, and packs without `spans` render exactly as before. Invalid spans are ignored by the app. Optional 4th element `gloss`: a non-empty display-only string shown in the tap-to-gloss popover instead of the word's `en` (fallback: span gloss, then the word's gloss). zh uses it for phrase units linked to a head word (越来越 -> 越 "more and more", 开车 -> 开 "to drive") and for the pack's display glosses (`packs/zh/gloss_display.json`, a sense list per headword). It never changes `words`, drills, weak words or progress; a span without it, and a pack without it, render exactly as before. |
| `questions[].q` | string | Target-language question. |
| `questions[].en` | string | Optional English translation of `q`, shown under it. |
| `questions[].type` | `"mc"` or `"tf"` | Multiple choice or true/false. |
| `questions[].options` | 4 strings or `null` | mc: exactly 4 distinct target-language options, shown shuffled. tf: `null` or absent. |
| `questions[].answer` | int or bool | mc: index 0–3 into `options`. tf: `true` or `false`. |
| `questions[].words` | `[wordId]` | Words the answer hinges on. A wrong answer charges them. May be empty (warning). |
| `questions[].sentence` | int | Index into `sentences` of the source sentence, highlighted in feedback and results. |

**Unlocking.** A level's passages unlock once 70% of that level's words are learned (core.js `READ_UNLOCK`, `readingLevels`). The unlock is stored in `prog.read.unlocked` and stays even if the count later drops. A locked level shows the threshold and the learned count. Today suggests "Read 1 passage" with the first not-done passage at an unlocked level (`suggestPassage`).

**Flow.** Reading screen: sentence by sentence, tap-to-gloss on linked words (each tapped id is logged), optional per-sentence read-aloud when speech works or the sentence has `audio`. "Done reading" starts the questions, one at a time, with the passage hidden behind a "Show passage" toggle. Opening it before answering is logged for that question. Feedback highlights the source sentence.

**Weak words.** The results screen lists the union of tapped words, the `words` of wrongly answered questions, and the `words` of questions answered after reopening the passage (`passageWeakWords`). Each has a checkbox, ticked by default. "Add to review" adds misses to `prog.w[id].w`: 2 for tapped or wrong, 1 for reopened only, the largest reason winning (`READ_WEIGHT`, `applyWeakWords`). The streak resets as for any miss, so `weakScore` ranks them first in the next review. A word not yet learned is flagged `d` (drilled ahead), which puts it in the review pool. As with a Words-tab drill-ahead, a `d` word then counts as learned everywhere, including the 70% unlock threshold. This is intended. The passage is recorded as done in `prog.read.done[id] = {sc, n, d, x}`: latest score, question count, date and attempt count.

**Progress.** `prog.read` (`{unlocked: {levelId: 1}, done: {passageId: {sc, n, d, x}}}`) is created on first use, exported and imported with the rest, and checked by `validateProgShape`. Stored progress without it loads unchanged. The Progress tab shows passages done and the average latest score per level.

**Script display.** Titles, passage sentences, questions, mc options and gloss words carry `lang`, `dir="rtl"` and the pack fonts, as everywhere else. English translations and True/False labels do not. In RTL packs the tap-to-gloss popover itself is `dir="rtl"` with `text-align:start`, so the tapped word sits at the right edge and its `pron` and English gloss follow in reading order. Those two stay isolated left-to-right runs (`dir="ltr"`).

## legacy.json

Optional, required when `pack.legacy` is set (and must be absent otherwise). Maps an old standalone app's own ids to this pack's ids, for a one-time progress migration (`docs/HSK_MERGE.md` §4) that this schema and its tooling only carry the data for; the migration function itself lives in `engine/core.js`.

```json
{ "w": {"你好": "w0028"}, "s": {"你好，我是学生。": "s0001"}, "c": {"你": "c0001"} }
```

An object with up to three optional keys, each a map from an old-app string key to an id in this pack:

| key | maps to | meaning |
|---|---|---|
| `w` | `wordId` | Old word key (e.g. the hanzi surface) to this pack's `words.json` id. |
| `s` | `sentId` | Old sentence key (e.g. the sentence text) to this pack's `sentences.json` id. |
| `c` | `unitId` | Old character key to this pack's `characters.json` id. Only meaningful with `pack.characters`. |

`tools/validate_pack.py` checks that every mapped id exists (in `words.json`, `sentences.json`, or `characters.json` respectively) and warns if a map's values are not unique.

## Validation

`python3 tools/validate_pack.py <packdir>` checks the following. Exit status 1 means at least one error.

- Required fields and types for every file.
- Unique ids.
- Every `lv` is a pack level.
- Every level has at least one word. A level with fewer words than `setSize` produces a warning.
- Every `sentence.words` and `functionWords` id exists.
- `placement` levels exist, are in order, and fit the level's set count.
- Every placement bucket has at least 3 words. This is computed with the same set-boundary math as core.js `strata()`, and a test asserts parity via `--dump-strata`.
- `typing.strictFromLevel` exists.
- Script fields: `rtl` is a bool, `langTag` is a BCP-47 tag, `fontFamily` has no `;`, `{`, `}`, `<`, `>`, `\`, `/*` or `url(`, every `fonts` entry is a Google Fonts family name, and `lineHeight` is 1–4. A pack with `rtl` true and neither `fontFamily` nor `fonts` gets a warning.
- Lesson answers are among their options.
- `passages.json`, when present: unique ids, `lv` is a pack level, `title`/`text` non-empty, non-empty `sentences` with `t`, `en` and known `words` ids, optional `spans` (a list of `[start, end, wordId]`, or `[start, end, wordId, gloss]` with a non-empty gloss string, with integer UTF-16 offsets, `0 <= start < end <= len(t)`, sorted, non-overlapping, not splitting a surrogate pair, `wordId` in that sentence's `words`, covering non-blank text), non-empty `questions` with `q`, `type` mc or tf, mc `options` of 4 distinct strings with `answer` 0–3, tf `answer` a bool and no options, known `words` ids, and `sentence` a valid index. A sentence `t` missing from `text` and a question with empty `words` are warnings.
- `pack.characters`, when present: `stages` is a non-empty list of `{after, levels}` with existing level ids, `after` non-decreasing in `pack.levels` order, and every level id covered by exactly one stage; `mastered`/`setSize` positive ints and `bare > mastered`; `learnKinds`/`reviewKinds` non-empty lists of known kinds. `characters.json` must exist exactly when `pack.characters` does, each error naming which side is missing.
- `characters.json`, when present: unique ids, non-empty `t`, non-empty `words` with known word ids, and `lv` both a pack level and covered by a `pack.characters.stages[].levels`.
- `sentences[].ruby`, when present: same offset rules as `passages.json` `spans` (sorted, non-overlapping, in-bounds, no split surrogate pairs, non-blank), plus a non-empty `reading` and a `wordId` that is both in the sentence's `words` and some `characters.json` unit's `words[0]`.
- `pack.legacy` and `legacy.json` must exist together, and every value in `legacy.json`'s `w`/`s`/`c` maps is a real `words.json`/`sentences.json`/`characters.json` id (duplicate values across one map are a warning).
- The generated `.js` files are in sync.

A word that shares its surface form with another word at the same level produces a warning.
