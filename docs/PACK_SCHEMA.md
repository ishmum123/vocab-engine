# Pack schema

A pack is one directory of JSON files that holds all the language-specific data. The engine reads nothing else.

```
<packdir>/
  pack.json        required  metadata and rules
  words.json       required  vocabulary
  sentences.json   required  example sentences (may be [])
  lessons.json     optional  "Sounds" tab lessons; required when pack.hasLessons is true
  pack.js words.js sentences.js lessons.js   generated, never edit by hand
```

The `.js` files are generated with `python3 tools/jsonify_pack.py <packdir>`. They hold the same data as `const PACK=`, `WORDS=`, `SENTENCES=` and `LESSONS=`, so the app can load them from `file://` and `build.sh` can inline them. `tools/validate_pack.py` fails when they are stale.

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

### Script display

Every element that shows target-language text carries `lang` (from `langTag`) and, when `rtl` is true, `dir="rtl"`. It also uses `fontFamily` and `lineHeight` when they are set. These elements are headwords, sentence text, word options in recall and cloze items, the cloze sentence with its blank, the typed-answer input, Words-list and teach-card rows, example sentences, reveal blocks, and lesson `rows` word cells and `say` buttons. English glosses, translations and `pron` never carry them, so they stay left-to-right.

- Block elements align to their start side, which is the right in RTL. The big headword stays centred.
- Inline target text inside a mixed line, such as an option button with its number and `pron`, is wrapped in `<bdi>`, so the line never reorders. Word option buttons in RTL packs also run right-to-left, with the number on the right.
- The cloze blank `____` is bidi-isolated, so it sits where the missing word was in RTL text too.
- The Words search box uses `dir="auto"`.

**External resources.** The only external resource a built page may load is Google Fonts. The page always loads IBM Plex Sans, and it loads `pack.fonts` at runtime through a `fonts.googleapis.com/css2` URL built by core.js `fontsHref`. No other URL can come from a pack.

**Pronunciation.** `pron` is display-only. With "Show pronunciation" on (the default comes from `showPron`), a word's `pron` is shown under the headword, beside it in word options, Words-list rows and teach-card rows, and under the word in every reveal. A sentence's `pron`, such as a kana line or romanised Russian with stress marks, is shown under the sentence in read items, example sentences and reveals. It is never shown before a hear or cloze item is answered, because it would give the answer away.

**Example-sentence highlighting.** In teach cards and reveals, the taught word is bolded in each example sentence wherever it is visible. The word is found the same way as for cloze: `w` and every `alt`, whole-word when `spaced`, overlapping hits merged into the widest one. A hit inside a longer pack word or compound is not bolded, so 本 inside 日本 is left plain. When the word is not visible, as when it appears only inflected and no `alt` matches, nothing is bolded. This is core.js `highlightParts`.

**Words search** matches the query against `w`, every `alt`, `pron` and the gloss. Both sides are lowercased and accent-folded as in lenient typing. Whitespace is also ignored, so `nihao` finds `nǐ hǎo`. This is core.js `searchWords`.

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
| `alt` | `[string]` | Optional accepted alternative typed answers, such as a feminine form or other spelling. It is also used to find the word in a sentence for cloze when `w` itself does not appear, as with inflected forms. The blank covers exactly the matched alt. So an elided alt such as `l'acqua` for `acqua` blanks the article too (`Bevo ____.`), while the multiple-choice options still show bare `w` (`acqua`). Prefer alts that are the word alone. **Convention:** when `w` carries an article or clitic (`il gioco`, `l'anno`), put the bare lemma first (`alt[0]` = `gioco`). The engine treats `alt[0]` as the word's bare form only when it is a whole trailing token of `w`, after a space or apostrophe (core.js `bareForm`). When a gap blank matched an alt instead of `w`, every multiple-choice option is shown by its bare form, so `È un ____ di parole.` offers `gioco / padre`, never `il padre`. When the blank matched `w`, options show `w`. Examples for a taught word prefer sentences where `w`, then an alt, is visible. |

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
- The generated `.js` files are in sync.

A word that shares its surface form with another word at the same level produces a warning.
