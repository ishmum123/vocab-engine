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
  script.json      optional  script-primer units; required when pack.script is set
  legacy.json      optional  old-app id maps for one-time progress migration
  pack.js words.js sentences.js lessons.js characters.js script.js legacy.js   generated, never edit by hand
```

The `.js` files are generated with `python3 tools/jsonify_pack.py <packdir>`. They hold the same data as `const PACK=`, `WORDS=`, `SENTENCES=`, `LESSONS=`, `CHARACTERS=`, `SCRIPT=` and `LEGACY=`, so the app can load them from `file://` and `build.sh` can inline them. `passages.json` has no file of its own: its `const PASSAGES=` is appended to `sentences.js`, so `build.sh` and the dev loader need nothing new, and a pack without passages gets exactly the `sentences.js` it had before. `characters.json`, `script.json` and `legacy.json` follow `lessons.json`'s pattern instead: their own optional generated file, present only when the source `.json` is. `tools/validate_pack.py` fails when they are stale.

## pack.json

| field | type | required | meaning |
|---|---|---|---|
| `key` | string `[a-z0-9_-]+` | yes | Pack identity. Progress is stored under the localStorage key `vocab_<key>`. Changing it orphans learners' progress. |
| `name` | string | yes | Display name and page title, e.g. `"Mandarin (HSK 1–4)"`. |
| `tts` | string | yes | BCP-47 locale for speech synthesis, e.g. `"zh-CN"`, `"it-IT"`. A voice with the exact locale is preferred, then any voice for the same language. |
| `ttsRate` | number 0.1–3 | no (0.9) | Speech rate. |
| `audio` | `{voice, version}` | no | The pack ships recorded clips (docs/AUDIO.md, written by `packbuilder audio`). `voice` is a non-empty string, `version` an integer ≥ 1 that names the service worker's audio cache, so a new version never plays a stale cached clip. With it, the no-voice notices are not shown. Clips play with or without it. |
| `levels` | `[{id, label}]` | yes | Ordered levels. `id` is a string (`"1"`, `"A1"`), `label` is shown in the UI. The order drives set unlocking and "past this level" logic. |
| `setSize` | positive int | no (10) | Words per learn set. |
| `placement` | `[[levelId, bucketCount], …]` | yes | Placement-test buckets, in level order. Each level's sets are split into `bucketCount` contiguous buckets. Buckets alternate 2 and 3 test items, so 16 buckets give a 40-item test. Every bucket needs at least 3 words. Levels before the first listed level count as known once the first bucket passes. |
| `functionWords` | `[wordId]` | no | Word ids never blanked in cloze (gap) items: articles, pronouns, particles. They are also a word class for options: a content-word answer in recall or cloze never gets a function-word distractor, and a function-word answer gets other function words first. |
| `articleAgreement` | `{article: [article]}` | no | Cloze distractor agreement. Each key is an article that can appear right before a blank, including contractions (`la`, `l'`, `den`, `del`). Its value lists the citation articles of the words it agrees with (`"den": ["der"]`). Distractors cited with an agreeing article are offered first, so the visible article never gives the answer away. Defaults exist for fr, es, it and de (core.js `ARTICLE_AGREEMENT`), picked by `langTag` or the `tts` language. A key missing from the table agrees only with itself. |
| `typing` | object, `"pron"` or `null` | no (`null`, validator warns when absent) | `null` turns off typed production. Recall items are used instead, so review still keeps at least 40% production. Object fields are listed below. `"pron"` alternates a typed-reading item (tones optional, no audio) with a typed-characters item (audio played); see "Pronunciation aids" below. |
| `typing.caseSensitive` | bool | no (false) | When false, both sides are lowercased before comparing. |
| `typing.accents` | `"lenient"` or `"strict"` | no (`"lenient"`) | With lenient, optional marks are folded on both sides: Latin accents (`perche` = `perché`), stress marks (`молоко́`), Arabic-script harakat and tatweel, Hebrew points, and ZWNJ/ZWJ (`میروم` = `می‌روم`). Lenient also folds optional spelling variants in Arabic script and Devanagari (hamza carriers, ء, ة, ى, ھ, nukta, chandrabindu; see "Lenient typing letter folds" below). Every lenient fold is guarded: an answer that matches only after folding is wrong when it is exactly another pack word (`si` for `sí`). Marks that make a different letter are kept: Cyrillic й and ї, Devanagari vowel signs, and kana voicing marks. Strict never folds them. Arabic kaf and yeh always equal their Persian/Urdu forms (ک, ی), in both modes, because keyboards produce either. |
| `typing.strictFromLevel` | levelId or `null` | no | With lenient accents, folding stops at this level and every later one. `null` means lenient at every level. |
| `showPron` | bool | yes | Whether words and sentences carry `pron`. It sets the learner's default for the "Show pronunciation" toggle. When false, the toggle is hidden. |
| `hasLessons` | bool | yes | Shows the Sounds tab and the Today lesson hint. |
| `compounds` | `[string]` | no | Surface strings that are not drillable words but that a cloze blank must never cut into. For example, zh 这个 is listed so that 这 is never blanked out of it. Pack words' own `w`/`alt` are always protected this way; this list covers units that aren't words. A blank that would leave no letter or digit outside it (a one-word sentence such as 不客气。) is never a cloze item, in any pack. |
| `spaced` | bool | no (true) | Whether the script separates words with spaces. When true, cloze matching is whole-word and case-insensitive; ZWNJ/ZWJ count as part of a word, so Persian `می` never matches inside `می‌روم`. When false, as in Chinese or Japanese, it is a plain substring match. |
| `rtl` | bool | no (false) | The target script is right-to-left (Persian, Arabic, Urdu). Target-language text gets `dir="rtl"`; see "Script display" below. |
| `langTag` | BCP-47 string | no (language part of `tts`) | `lang` attribute on target-language text, for font selection, line breaking and hyphenation, e.g. `"fa"`, `"ur"`, `"ja"`. An invalid tag falls back to the default. |
| `fontFamily` | string | no | CSS font-family list for target-language text, e.g. `"\"Noto Nastaliq Urdu\", serif"`. It is placed before the engine's default stack. For `rtl` packs only its named families are used: generic keywords such as `serif` are dropped (core.js `fontStackOf`, quote-aware), so Latin text inside target text falls to the UI font. LTR packs use the value as given. A value containing `;`, `{`, `}`, `<`, `>`, `\`, `/*` or `url(` is ignored. |
| `fonts` | `[string]` | no | Google Fonts families the page loads, e.g. `["Noto Nastaliq Urdu"]`, `["Noto Naskh Arabic:wght@400;700"]`, `["Noto Sans Devanagari"]`. Each entry is a family name (letters, digits, spaces), optionally followed by a css2 axis spec. Invalid entries are skipped with a console warning. |
| `lineHeight` | number 1–4 | no | Line height for target-language text. Use it for tall scripts, e.g. `2.2` for Nastaliq. When absent, the stylesheet's own line heights apply. |
| `characters` | object | no | Turns on the character stage; see "characters" below. Absent, no character code path runs and `characters.json` must not exist. |
| `script` | object | no | Turns on the script primer: stages before the first word level that teach the writing system; see "Script primer" below. Absent, no script code path runs and `script.json` must not exist. |
| `pronFirst` | bool | no (false) | Pronunciation first, for a pack with `characters`: a word is shown by its `pron` until its character unit is mastered; see "pronFirst" below. Without `characters` it has no effect (validator warning). |
| `tones` | `"pinyin"` | no | Readings carry tone marks: every displayed reading is coloured per syllable by tone; see "Pronunciation aids" below. The only accepted value is `"pinyin"`. |
| `soundsReference` | `true` | no | The Sounds tab gets a Reference card built from the lesson rows; see "Pronunciation aids" below. Needs `hasLessons` (validator warning). |
| `legacy` | `{key, format}` | no | Marks this pack as the successor to an old standalone app's saved progress, for a one-time migration. `key` is the old app's localStorage key (e.g. `"hsk_pinyin"`); `format` is a migration-function tag (e.g. `"hsk-v2"`). Requires `legacy.json`. |

### Lenient typing letter folds

With `typing.accents: "lenient"` (at levels before `strictFromLevel`), typed answers also fold these optional spelling variants, on both sides (core.js `LENIENT_LETTERS`, `foldLenientLetters`). Strict typing folds none of them.

| script | folds |
|---|---|
| Arabic script (ar, fa, ur) | Hamza/madda on a carrier dropped: أ إ آ → ا, ؤ → و, ئ → ی, ۓ → ے, ۂ → ہ, ۀ → ه, and a loose hamza mark (خانهٔ → خانه). ٱ ٲ ٳ ٵ → ا, ٶ ٷ → و, ٸ → ی. Standalone ء dropped. ة → ه, ۃ → ہ. ى → ی. ھ → ہ (بھائی = بہائی). |
| Devanagari (hi) | Nukta dropped (ज़ = ज, including precomposed क़–य़ U+0958–095F). Chandrabindu ँ → anusvara ं (माँ = मां). |

Not folded: a leading ال (it changes the word; `كتاب` ≠ `الكتاب` when typing), and ه vs ہ (each pack spells with one).

**Collision guard (every lenient fold).** Folding can make distinct words one typed key: Spanish `si`/`sí`, Arabic ما "what"/ماء "water". core.js `acceptTyped` first compares strict forms (no accent or letter folding; case, whitespace, apostrophes and kaf/yeh unified as always). An exact match to the target always passes. Otherwise, in lenient mode, an answer that matches only after folding (Latin/Greek/Cyrillic accents and stress, Arabic marks, joiners, the letter folds above) is rejected when it spells another pack entry's `w` or `alt`: its strict form is that entry's, or its form without non-distinguishing marks (Arabic harakat and tatweel, Hebrew niqqud, ZWJ/ZWNJ, Cyrillic stress; core.js `pointingKey`) is that entry's and not the target's. So `مَا` or `مـا` typed for `ماء` is wrong, and so is `si` with a joiner typed for `sí`. Stress-less `замок` stays right for `за́мок` even when `замо́к` is also a pack word, because the target shares that form; typed `замо́к` is wrong. The guard needs the pack word list (`acceptTyped`'s `words` argument; the app passes `WORDS`); without it the fold alone decides. So `si` is wrong for `sí` and `ماء` for `ما`, while `perche` for `perché`, `еж` for `ёж` and `امس` for `أمس` are right. Strict mode is unchanged.

Colliding pairs in the typing packs at the time of writing, counting pairs where at least one word is at a lenient level (italian 8, spanish 15, french 8, german 2, russian 0, indonesian 0, korean 0, arabic 25, persian 1, urdu 2, hindi 0). Each is rejected both ways by the guard. Indonesian types strictly; Russian, Korean and Hindi have no pair.

| pack | typed | word (id, level) | also folds to | word (id, level) |
|---|---|---|---|---|
| italian | la | il (w0001, A1) | là | là (w0559, A1) |
| italian | la | la (w2021, A1) | là | là (w0559, A1) |
| italian | si | si (w0011, A1) | sì | sì (w2029, A1) |
| italian | e | e (w2005, A1) | è | è (w2138, A1) |
| italian | se | se (w0022, A1) | sé | sé (w1237, A1) |
| italian | ne | ne (w0050, A1) | né | né (w0621, A2) |
| italian | te | te (w0056, A1) | tè | il tè (w2050, A1) |
| italian | li | li (w2028, A1) | lì | lì (w0291, A1) |
| spanish | el | el (w0001, A1) | él | él (w0024, A1) |
| spanish | que | que (w0009, A1) | qué | qué (w0023, A1) |
| spanish | te | te (w0027, A1) | té | el té (w0444, A1) |
| spanish | mi | mi (w0028, A1) | mí | mí (w0144, A1) |
| spanish | si | si (w0029, A1) | sí | sí (w0078, A1) |
| spanish | si | si (w0029, A1) | sí | sí (w0133, A1) |
| spanish | como | como (w0033, A1) | cómo | cómo (w0048, A1) |
| spanish | tu | tu (w0040, A1) | tú | tú (w0088, A1) |
| spanish | cuando | cuando (w0053, A1) | cuándo | cuándo (w0171, A1) |
| spanish | porque | porque (w0063, A1) | porqué | el porqué (w1324, B1) |
| spanish | dónde | dónde (w0077, A1) | donde | donde (w0229, A1) |
| spanish | quién | quién (w0092, A1) | quien | quien (w0220, A1) |
| spanish | aún | aún (w0170, A1) | aun | aun (w1775, B1) |
| spanish | cuánto | cuánto (w0612, A2) | cuanto | cuanto (w1276, A2) |
| spanish | sonar | sonar (w0709, A2) | soñar | soñar (w1462, B1) |
| french | la | le (w0002, A1) | là | là (w0067, A1) |
| french | la | le (w0024, A1) | là | là (w0067, A1) |
| french | sur | sur (w0035, A1) | sûr | sûr (w0212, A1) |
| french | où | où (w0050, A1) | ou | ou (w0068, A1) |
| french | côté | le côté (w0224, A1) | côte | la côte (w1288, A2) |
| french | marché | le marché (w0477, A1) | marche | la marche (w0824, A2) |
| french | élève | l'élève (w0517, A1) | élevé | élevé (w1082, A2) |
| french | âge | l'âge (w0639, A2) | âgé | âgé (w1807, B1) |
| german | schon | schon (w0054, A1) | schön | schön (w0109, A1) |
| german | zahlen | zahlen (w0671, A2) | zählen | zählen (w0706, A2) |
| arabic | أن | أن (w0001, A1) | إن | إن (w0010, A1) |
| arabic | كان | كان (w0005, A1) | كأن | كأن (w0362, A1) |
| arabic | إلى | إلى (w0008, A1) | آلي | آلي (w1707, B1) |
| arabic | ما | ما (w0009, A1) | ماء | ماء (w0206, A1) |
| arabic | رأى | رأى (w0053, A1) | رأي | رأي (w0381, A1) |
| arabic | يرى | رأى (w0053, A1) | يري | أرى (w1858, B1) |
| arabic | بدأ | بدأ (w0112, A1) | بدا | بدا (w0128, A1) |
| arabic | إلا | إلا (w0135, A1) | ألا | ألا (w0170, A1) |
| arabic | أمن | أمن (w0411, A1) | آمن | آمن (w0802, A2) |
| arabic | أمن | أمن (w0411, A1) | آمن | آمن (w1073, A2) |
| arabic | رجا | رجا (w0420, A1) | رجاء | رجاء (w0813, A2) |
| arabic | إله | إله (w0425, A1) | آلة | آلة (w0856, A2) |
| arabic | آسف | آسف (w0448, A1) | أسف | أسف (w0992, A2) |
| arabic | غدا | غدا (w0453, A1) | غداء | غداء (w0550, A1) |
| arabic | موسيقى | موسيقى (w0466, A1) | موسيقي | موسيقي (w1743, B1) |
| arabic | بني | بني (w0543, A1) | بنى | بنى (w0779, A2) |
| arabic | أذن | أذن (w0589, A1) | إذن | إذن (w0659, A2) |
| arabic | أذن | أذن (w0589, A1) | إذن | إذن (w0828, A2) |
| arabic | أخطاء | خطأ (w0644, A2) | أخطأ | أخطأ (w1985, B1) |
| arabic | كرة | كرة (w0650, A2) | كره | كره (w0861, A2) |
| arabic | آثار | أثر (w0717, A2) | أثار | أثار (w1100, A2) |
| arabic | أما | أما (w0724, A2) | إما | إما (w0786, A2) |
| arabic | سوى | سوى (w0775, A2) | سوي | سوي (w1546, B1) |
| arabic | غني | غني (w1454, B1) | غنى | غنى (w1548, B1) |
| arabic | بري | بري (w1551, B1) | بريء | بريء (w1823, B1) |
| persian | جز | جز (w0686, A2) | جزء | جزء (w1496, B1) |
| urdu | پھر | پھر (w0067, A1) | پہر | پہر (w1964, B1) |
| urdu | کھلانا | کھلانا (w2016, A2) | کہلانا | کہلانا (w1743, B1) |

### Script display

Every element that shows target-language text carries `lang` (from `langTag`) and, when `rtl` is true, `dir="rtl"`. It also uses `fontFamily` and `lineHeight` when they are set. These elements are headwords, sentence text, word options in recall and cloze items, the cloze sentence with its blank, the typed-answer input, Words-list and teach-card rows, example sentences, reveal blocks, and lesson `rows` word cells and `say` buttons. English glosses, translations and `pron` never carry them, so they stay left-to-right; see "RTL rendering" below.

- Block elements align to their start side, which is the right in RTL. The big headword stays centred.
- Inline target text inside a mixed line, such as an option button with its number and `pron`, is wrapped in `<bdi>`, so the line never reorders. Word option buttons in RTL packs also run right-to-left, with the number on the right.
- The cloze blank `____` is bidi-isolated, so it sits where the missing word was in RTL text too.
- The Words search box uses `dir="auto"`.

#### RTL rendering

For `rtl` packs, target-language text and UI/English text never share a bidi context. Mixing them lets the bidi algorithm reorder the Latin run: `79 words` shows as `words 79`, and a gloss such as `near; (someone) has (میرے پاس: I have)` scrambles. The rules, all in engine/app.html, change nothing for LTR packs:

- **Target text** is an element with `data-tl lang dir="rtl"`: `TA`, or `tw()` for an inline `<bdi>`.
- **UI/English lines inside a target-language block** carry `dir="ltr" data-ui` (`UIA`). This includes digit-only lines. Examples are the Read-list meta line and the done tick `✓ 3 / 4` inside the RTL title button, option numbers, the `pron` beside a word option, and the weak-word reason labels. They get their own isolated LTR context and the UI font.
- **The gloss popover** (`#gloss` and the sentence token popover) is an LTR line, right-aligned in RTL packs. The word is an isolated `dir="rtl"` span, and `pron` and gloss follow as LTR runs, so a wrapping gloss never interleaves with the word. The results' weak-word rows are RTL flex rows with the checkbox on the right, where each piece is its own flex item.
- **Any UI/English string that can embed target-language text** goes through one renderer, `ui()`. That covers glosses, sentence translations, notes, lesson text, labels and the Today plan lines. It escapes the string and wraps each run of RTL script (core.js `rtlRuns`) in `<bdi data-tl lang dir="rtl" class="tlf">`, so `(bound: لـ)` keeps its order and the fragment gets the pack font. A run extends across neutrals (`...`, `…`, `/`, commas, digits, spaces) up to the last RTL letter before a Latin letter, as the Unicode bidi algorithm resolves them. So `از ... متنفرم` and `کا/کی/کے` stay one run in their own order, while `: I have)` after `میرے پاس` stays outside.
- **A pack label inside a UI line**, such as a stage label or a symbol's name, uses `tf()`. That is `ui()` for RTL packs, so a Latin name such as `choṭī he` stays UI text.
- **Inline fragments** (`.tlf`) have their line-height capped at 1, so a tall script such as Nastaliq at `lineHeight` 2.6 does not grow the UI row it sits in.

Tests check these rules on rendered markup with tests/fixtures/rtl_audit.js `rtlAudit`, from script_app_checks.js [14], engine_checks.js "RTL rendering rules on the Read screens" and characters_app_checks.js [rtl]. No UI text node, meaning Latin letters or digits without RTL letters, may have `dir="rtl"` as its nearest `dir`. RTL-script text must be inside `data-tl`, and Latin text inside `data-tl` needs a `data-ui` element in between.

**External resources.** The only external resource a built page may load is Google Fonts. The page always loads IBM Plex Sans, and it loads `pack.fonts` at runtime through a `fonts.googleapis.com/css2` URL built by core.js `fontsHref`. No other URL can come from a pack. Neither font stylesheet blocks first paint: IBM Plex is a `preload` that becomes a stylesheet once loaded, and the `pack.fonts` link starts as `media="print"` and switches to `all` on load. Text shows in the fallback stack until the webfont arrives (`display=swap`).

**Pronunciation.** `pron` is display-only. With "Show pronunciation" on (the default comes from `showPron`), a word's `pron` is shown under the headword, beside it in word options, Words-list rows and teach-card rows, and under the word in every reveal. A sentence's `pron`, such as a kana line or romanised Russian with stress marks, is shown under the sentence in read items, example sentences and reveals. It is never shown before a hear or cloze item is answered, because it would give the answer away.

**Example-sentence highlighting.** In teach cards and reveals, the taught word is bolded in each example sentence wherever it is visible. The word is found the same way as for cloze: `w` and every `alt`, whole-word when `spaced`, overlapping hits merged into the widest one. A hit inside a longer pack word or compound is not bolded, so 本 inside 日本 is left plain. When the word is not visible, as when it appears only inflected and no `alt` matches, nothing is bolded. This is core.js `highlightParts`.

**Words search** matches the query against `w`, every `alt`, `pron` and the gloss. Both sides are lowercased and accent-folded as in lenient typing. Whitespace is also ignored, so `nihao` finds `nǐ hǎo`. A hyphen folds to a space, so a reduplicated or hyphenated lemma (`धीरे-धीरे`) matches its unhyphenated spelling (`धीरे धीरे`) too. A romanised nasal tilde (`kahā̃`) folds to a literal `n`, so plain ASCII typing (`kahan`) finds it, alongside the existing macron/dot-below folding (`ā`, `ṛ`). This is core.js `searchWords` (`searchFold`); typed-answer checking (`normalizeTyped`/`acceptTyped`) is unaffected by any of the folds below.

Arabic-script text (ar/fa/ur) has its own search folds, separate from the lenient typing letter folds above (search keeps ھ and ء, and makes ال optional): hamza and madda on a carrier drop (`انا` finds `أنا`, `سوال` finds `سؤال`), ٱ is ا, ة/ه/ۃ/ۀ all fold to ہ, ى is ی/ي (`فى` finds `في`), and a leading ال is optional on both sides (`كتاب` finds `الكتاب`). Urdu spelling variants of the same letter are unified to Urdu heh goal ہ — Arabic heh ه, teh marbuta goal ۃ, and the Arabic-preset ۀ all fold to ہ (`مدرسۃ` finds `مدرسہ`) — while do-chashmi heh ھ (a distinct aspirated phoneme) is never folded into ہ. Bari ye ے folds to ی at a word boundary only (`بڑے` and `بڑی` search as the same word); this is a deliberate tradeoff, since ے is otherwise indistinguishable from ی for search — a reveal still shows the pack's own spelling.

Devanagari text (hi) is also folded for search, the same two folds as lenient typing: nukta folds away (`जरूर` finds `ज़रूर`, `लडका` finds `लड़का`), including from a precomposed nukta letter (क़ ख़ ग़ ज़ ड़ ढ़ फ़ य़, U+0958–095F, decomposed first); chandrabindu ँ folds to anusvara ं (`हैँ` finds `हैं`), a common informal spelling swap. ZWJ/ZWNJ are dropped for every script.

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
  "reviewKinds": ["charRead","charSound"],
  "testKinds": {"charRead":40,"charSound":30,"charPick":30}
}
```

| field | type | required | meaning |
|---|---|---|---|
| `label` | string | yes | Short name for the stage strip and Progress (`字`, `漢字`). A stage after the config's last level appends that level id (`字4`). |
| `stages` | `[{after, levels}]`, non-empty | yes | Each stage sits after word level `after` (a `pack.levels[].id`) and covers `levels` (a non-empty list of `pack.levels[].id`, in the same namespace `characters.json`'s `lv` uses). `after` values must be non-decreasing in `pack.levels` order, and every `levels` id may appear in exactly one stage. |
| `setSize` | positive int | no (`pack.setSize`) | Units per learn set, chunked in level order then file order within a stage. |
| `mastered` | positive int | no (3) | Streak at which a unit's tier becomes "mastered" (bare-form drilling). |
| `bare` | positive int, `> mastered` | no (6) | Streak at which a unit's tier becomes "bare" (written form without its reading; the reading stays in the markup, hidden, so the token keeps its width). |
| `learnKinds` | `[string]`, non-empty | yes | Item kinds taught for each new unit, drawn from `charRead`, `charSound`, `charPick`, `charRecall` (see "Drill items" in `docs/HSK_MERGE.md` §2.5). |
| `reviewKinds` | `[string]`, non-empty | yes | Item kinds used once a unit is in Review/Recall, from the same set. |
| `testKinds` | `{kind: weight}`, non-empty | no (`{"charRead":40,"charSound":30,"charPick":30}`) | Kind mix for the Test tab's Characters N: each item's kind is drawn with these relative weights (kinds from the same set, weights positive numbers). The test's pool is the 20 weakest recorded units, topped up with learned words' unrecorded units (level order, then file order); the button shows once characters have started. |
| `compose` | bool | no (false) | Per-character span readings: a passage tap span longer than its word reads each character outside the word by its single-character unit's reading (core.js `composeSpanReading`). Set only when a character reads the same in every word (zh: `pack_from_hsk.py` sets `true`). Off, those characters stay written (ja: 6時, 一週間 would read 6とき, いちしゅうあいだ). |

`tools/validate_pack.py` checks `stages` (existing level ids, `after` order, one stage per level, every `levels` id at or before the stage's own `after` in `pack.levels` order), the thresholds (`bare > mastered`), that `learnKinds`/`reviewKinds` are known kinds, that `testKinds`, when present, maps known kinds to positive weights, and that `compose`, when present, is a boolean.

### pronFirst

`"pronFirst": true` (zh and ja) makes a logographic pack pronunciation-first: the learner never starts from the written form. A word whose character unit is below the `mastered` tier is shown by its `pron` (pinyin, kana) wherever its written form would otherwise appear. That covers teach rows, every word drill (stimulus, options, reveal), the Words list and search, Test, Progress and result screens, and the Read tab's tap spans and popover. The unit is the one whose `words[0]` is the word. A word with no unit (a kana word) or no `pron` is shown as written. Once the unit is mastered the word is shown written, with its `pron` beside it as usual. The written form is taught only in the characters stage (teach cards and the four unit item kinds), which is unchanged.

Sentences follow the same rule token by token (`ruby`): before characters start, or with the mix preference off, every token shows its reading. Once they have started with mix on, a token below mastered shows its reading, and the ruby and bare tiers apply from mastered. With Latin readings, tokens are spaced and full-width punctuation is shown in ASCII form. These spacing rules are display cosmetics keyed on Unicode script (Latin readings get spaces, Han text outside tokens triggers the reading-line fallback). They never affect scoring or which tier a token gets. A sentence whose written characters are not all inside `ruby` tokens (a name, a word with no unit) is shown by its sentence `pron` instead, and is never used as a cloze item. "Show pronunciation" off hides only the ruby over written tokens. The reading itself is always shown.

A small **show written** tap sits beside every word or sentence shown by its reading (never inside answer buttons or passage tap spans, which are tap targets themselves). It swaps itself for the written form, for that item only, with no progress effect, so a learner who wants the characters is never blocked. Keys pressed on it never reach the drill shortcuts. When it had keyboard focus, the revealed text takes the focus. Its label is left out of the live-region announcement.

In the characters stage, a unit's teach card shows its example sentence with that unit's own tokens written, with ruby. The other tokens follow the rule above. The example is picked by core.js `unitExampleSentences`: first a sentence with a `ruby` token of the unit's word whose tokens cover every Han character (core.js `rubyCovers`, the same test that decides the reading-line fallback), then one with the unit's token, then any other. So the card shows the unit written whenever some sentence of its word allows it.

Recall and cloze options are unambiguous when shown by their readings: no two options sound alike, and no two share a written form. Recall options are keyed by word id. A distractor with the same `pron` as the answer or another option, or written as another option's reading, is dropped. This is core.js `pronClash` in `wordOpts`.

The rules live in core.js: `displayForm(word, units, prog, pack)` returns `{text, isPron, written}`, plus `sentenceDisplay`, `sentencePieces`, `rubyTiers` and `pronFirstOn`. Validation: `pronFirst` must be a boolean.

A passage span can be longer than its linked word: 这个 links 这, 越来越 links 越, 一下 links 下. Without `ruby`, such a span reads as core.js `composeSpanReading`. Each place the word's written form occurs gets the word's `pron`. With `characters.compose`, every other character gets the reading of the single-character unit with that `t` (the first in file order). Without it, every other character stays written: a character's reading can depend on its word (ja 時 is じ in 6時, とき alone), so no reading is guessed. A character with no reading stays written, so a span never loses a character. The popover of such a span shows the tapped surface with that reading as its headword, and show written gives the surface. A span equal to its word keeps the word's own headword. A reading that starts a sentence is capitalised, including one after a sentence-internal `.`, `!` or `?` and the first inside a quote opened after a colon. An ellipsis stays as written and starts nothing.

### Pronunciation aids

Three pack fields and the sentence `ruby` turn on learning aids for the reading. Each is off unless the pack sets it, so every other pack renders exactly as before (tests/pron_aids_checks.js [7], tests/flagoff_snapshot.js).

- **Word taps in sentences** (a sentence drawn with its `ruby` tokens: always under `pronFirst`, and on a word-first characters pack once characters have started with mix on; also passage question reveals and results under `pronFirst`): each token with a known word is a tap target (Enter or Space from the keyboard). A tap shows the word's popover, the same one the Read tab uses (reading, gloss, show written), inside that sentence, and speaks the word only. A token whose surface contains its word and more (这个 for 这, 他们 for 他) is a phrase token: its popover heads with the surface's reading, show written gives the surface, and the tap speaks the surface. A token covering only part of its word (ja ruby over the written stem) keeps the word's headword. Escape closes any open popover or Read-tab gloss box and clears the tapped highlight, staying on the same view (inside a drill it does not quit); with nothing open it works as usual. The sentence itself is heard from its own speaker button, not by tapping the text. Question stimuli and answer options never carry taps. A tap has no progress effect. Sentence rows, reveal blocks, teach examples and passage reveals get taps; a sentence shown by its sentence `pron` line has no tokens and keeps the old whole-row tap.
- **`tones: "pinyin"`**: every displayed reading is coloured per syllable, as `<span class="t1">` to `t5` (tone 1 to 4, 5 for neutral), with light and dark colours. This covers word displays, sentence tokens and ruby, options, reveals, the Words list, popovers, teach rows, character items and lesson rows. A reading is split into syllables by the tone marks on its vowels and the pinyin syllable inventory (core.js `splitReading`, `splitSyllable`, `markSyllable`, `toneHTML`). A letter run that does not split into syllables (a Latin name, "OK") stays uncoloured.
- **`typing: "pron"`**: the production slot that alternates with recall (the same rule as other typing packs) is one of two typed items. The plan is unchanged. The item is picked by the slot's order among the plan's "type" slots: the first, third and later odd slots type the reading, the rest type the characters (core.js `typeSlotKind`, no randomness, so plans stay reproducible). Each card has a kind tag, its own heading and its own placeholder.
  - **Type the pinyin** (the reading; "Type the reading" when `tones` is unset): the card shows the meaning and plays no audio before the answer, since audio would give the reading away. The input is a Latin one (`lang="en"`). Tones are optional. Tone marks or tone numbers are accepted; a neutral syllable may be written 5, 0 or with no digit, and an r-suffixed syllable with its digit after the r, or before it with the r bare, r5 or r0 (hsk's `yi1hui4r5`). Case, spaces and apostrophes are ignored, and v or u: stand for ü. The right letters with no tones, or with other tones, also count as right, and a "tones:" note gives the tone-coloured marked form. Other letters are wrong. This is core.js `checkPronTyped` ("ok", "tones", "tonesDiff", "wrong").
  - **Without `tones`** (ja: kana readings): "Type the reading", tag "reading", placeholder "reading…", and no tone note. The input takes the target-language attributes when the reading is not Latin script, so the kana keyboard comes up. The typed reading must equal the `pron` after `plainPronKey`: NFKC (half-width kana count as full width), katakana folded to hiragana on both sides (テレビ may be typed てれび and the reverse), then `normalizeTyped` and every non-letter removed (spaces, the affix mark 〜, the middle dot ・). The long-vowel mark ー, small kana and voicing marks must match exactly: こうひい is not コーヒー, きやく is not きゃく. The verdict is "ok" or "wrong" only; pinyin syllable splitting and tone digits never apply (たべる1 is wrong).
  - **Type the characters**: the card shows the meaning, plays the word's audio once and has a replay button (as hear items). The input carries the target-language attributes, so a phone keyboard switches to the pack's language. The written form or any `alt` is accepted (core.js `acceptTyped` with default options), and so is the written form without a leading or trailing affix mark 〜/～ (年 for 〜年, core.js `affixBare`). Katakana and hiragana are not interchangeable here: the written form is the spelling (テレビ).
  - The characters item needs the word's written form on display. Under `pronFirst`, a word below its character tier is shown by its reading only, so the learner has not seen its characters; that word gets the pinyin item in both slots, and the alternation resumes once the word reaches its tier. A word with no `pron` always gets the characters item. Both items record progress under the same `w:<id>` key as every other word item. The reading is never drilled on its own, typed cloze items never appear (the blank is written), and placement is unchanged.
- **`soundsReference: true`**: a collapsed Reference card below the Sounds lesson list. It lists every lesson row whose `say` is one character (its reading coloured, each reading once), grouped by lesson. Tapping a cell speaks that character. The zh lessons already cover every initial, final and tone, so the card is built from them, not from a separate chart file.

## pack/characters.json

Required when `pack.characters` is set (and must be absent otherwise). Holds the units, in teaching order within each level: sets are consecutive runs of `setSize` units of one level, in file order.

`[{ id, t, words, lv, reading? }]`

| field | type | meaning |
|---|---|---|
| `id` | `c0001`…, unique | Progress key. Builders derive it from the unit's `words[0]` id (`w0416` → `c0416`), so ids follow word ids and are never renumbered when units are added or left out; a pack with gaps in unit ids is normal. |
| `t` | non-empty string | Written form, shown large. |
| `words` | `[wordId]`, non-empty | Linked words, ids from this pack's `words.json`. `words[0]` supplies the gloss and the audio. |
| `lv` | levelId | Must be one of `pack.levels[].id`, equal to the `lv` of `words[0]`, and covered by one of `pack.characters.stages[].levels` — decides which stage the unit belongs to. |
| `reading` | string | Optional. Answer for `charSound` and the ruby text. Defaults to the `pron` of `words[0]`. |

`tools/validate_pack.py` checks unique ids, that every `words` id exists, and that `lv` is a pack level, equals the level of `words[0]`, and is covered by a stage.

## Script primer

Optional. `pack.script` plus `pack/script.json` turn on a **script primer**: one stage per `pack.script.stages` entry, placed before the first word level, that teaches a non-Latin writing system symbol by symbol (symbol to sound, recognition, then reading the pack's own first-level words). Absent, no script code path runs and `script.json` must not exist. Design of record: `docs/SCRIPT_PRIMER.md`.

```json
"script": { "stages":[{"key":"hira","label":"ひらがな"},{"key":"kata","label":"カタカナ"}],
  "setsPerSession":2, "mastered":3, "tts":true,
  "learnKinds":["symSound","soundSym"], "reviewKinds":["symSound","soundSym","compose","wordRead"],
  "testKinds":{"symSound":35,"soundSym":25,"wordRead":25,"symType":15} }
```

| field | type | required | meaning |
|---|---|---|---|
| `stages` | `[{key, label}]`, non-empty | yes | Path order. `key` is the `st` of its units, unique; `label` is shown on the stage strip, Progress and the Script tab. |
| `setsPerSession` | positive int | no (2) | Script sets Today's Learn step offers per session: the first is taught, the rest behind "One more set". |
| `mastered` | positive int | no (3) | Streak at which a unit counts as mastered. |
| `tts` | bool | no (true) | `false` treats every `say` as absent: `soundSym` shows the `roman` as text and `wordHear` becomes `wordRead`. A unit's recorded `audio` still plays. |
| `learnKinds` | kinds, non-empty | no (`symSound`, `soundSym`) | One Learn item per kind per unit, among the kinds the unit can carry (below). |
| `reviewKinds` | kinds, non-empty | no (`symSound`, `soundSym`, `wordRead`) | Review draws one at random per unit. |
| `testKinds` | `{kind: weight}` | no (`symSound` 35, `soundSym` 25, `wordRead` 25, `symType` 15) | The Script tab's practice mix. |

Kinds are `symSound`, `soundSym`, `symType`, `compose`, `formFind`, `formMatch`, `wordRead`, `wordHear` (`docs/SCRIPT_PRIMER.md` §2). A unit carries a kind only when it has what the kind needs: the three sound kinds need `sound` not false; `compose` needs `syll`; `formMatch` needs `joins`; `formFind`, `wordRead` and `wordHear` need `ex`. A `sound:false` unit gets `wordRead` in place of the sound kinds in Learn. An option kind also needs at least 4 distinct options drawn from all the pack's units, or it is never asked of that unit.

### pack/script.json

Required when `pack.script` is set, absent otherwise. `{units, notes?}`.

| unit field | type | meaning |
|---|---|---|
| `id` | `^[a-z]{2,3}-[a-z0-9-]+$`, unique | Progress key (`prog.script.u`), stable, never renumbered. Not the glyph: one glyph in two roles is two units. |
| `st` | stage key | One of `pack.script.stages[].key`. |
| `set` | int ≥ 1 | Teaching set within the stage; each stage's sets are contiguous from 1. File order is the order within a set. |
| `group` | string | Distractor family (vowels, a dot family, a kana row). |
| `t` | non-empty string | The glyph. A teach card may show two forms separated by a space ("Д д"); items use the last. |
| `name` | string | The letter's name. Dropped from the teach card head and reveal when it only repeats `roman` ("ka" \| "ka"), compared trimmed and case-insensitively; core.js `scriptUnitHeadName`. |
| `roman` | non-empty string | Canonical romanisation, the answer to `symSound`. |
| `alt` | `[string]` | Other accepted romanisations (typed `symType`). Options ignore a one-way alt (ko ㄱ alt `k` is drilled against ㅋ); two units that accept each other's roman (fa غ gh/q, ق q/gh) are never each other's distractor. |
| `say` | string | TTS carrier: the bare glyph, a carrier syllable or the name. Absent when unspeakable. |
| `audio` | URL | Recorded clip; beats `say`, and plays even with `tts` false. |
| `sound` | bool, default true | `false` for silent or modifier units. |
| `note` | string | One-line sound note. Dropped the same way when it only repeats `roman`; core.js `scriptUnitNote`. |
| `confuse` | `[unitId]` | Hand-listed confusables: preferred distractors, and the padding for early sets. |
| `ex` | `[[wordId, roman]]`, 1–3 | Example words from this pack with their romanisation. The glyph occurs in the word's `w` or `pron`. |
| `syll` | `[{t, parts, roman}]` | Composition examples for `compose`; `parts` are glyphs of units at or before this set, `t` occurs in a first-level word. |
| `joins` | `"dual"` / `"right"` | Joining letters of a right-to-left pack. Forms are drawn by Unicode shaping from the letter plus a zero-width joiner. |
| `base` | unitId | The unit this one is a variant of (a mark added, the other syllabary); the teach card shows base → variant. |
| `italic` | string | The glyph's italic form when it differs; the teach card shows it. |

`notes`: `[{st, set, h, body}]`, rule cards shown with the teach cards of that stage's set. `h` and `body` are plain text (escaped).

**Example words** are shown in the script being taught: a word whose `w` uses letters outside the primer's units while its `pron` is written entirely with them (ja kanji words) is shown, spoken and answered by its `pron`; otherwise by its `w`.

**Progress.** `prog.script = {v:1, u:{[unitId]:{r,w,s}}, skipped, skip:{[stageKey]:bool}, choiceSeen, notice}`, present only with `pack.script`. `skipped` turns the whole primer off and `skip` one stage; an off stage leaves the path, Review and Test, and its records are kept. Taught, done and mastered are derived: a set is taught and a stage done once every unit has a record; mastered is streak ≥ `mastered`. Stored progress with word records and no `script` field (a learner from before the primer) normalizes to `skipped:true, choiceSeen:true, notice:true`: the primer starts off, with a one-time notice that it can be turned on in Progress. Fresh progress starts with the primer on and the choice card unanswered. Turning the primer or a stage on in Progress clears `notice`. `prog.script` is created whenever `pack.script` is set, even when `script.js` has no units and the primer is off; it is then inert.

**Validation** (`tools/validate_pack.py`): `script.json` exists exactly when `pack.script` does; `pack.script` field types and known kinds; unit ids unique and well-formed; `st` a stage key, `set` an int ≥ 1, each stage's sets contiguous from 1, every stage non-empty; `t` and `roman` non-empty, `sound` a bool, `alt` strings; `confuse` and `base` known ids; `ex` word ids exist, from the first or second level (the second is a warning; a unit of a later stage may also use the third level, with a warning, because a later stage such as ja katakana teaches a script the first levels barely use), the roman non-empty and the glyph in the word (compared after compatibility decomposition and lower-casing, with positional letter variants folded); `syll.parts` glyphs of units at or before the set and `syll.t` in a first-level word (for a later stage, after folding katakana to hiragana); `joins` only in an `rtl` pack; `notes` on a known stage set. Warnings: a unit with no `ex`; two units of one group with the same `roman` and no `confuse` link; a sounded unit with no `say` while `tts` is on; an `alt` equal to another same-stage unit's `roman` (typed answers would accept the unit as that letter's sound), except between units of the same glyph or units that accept each other's roman.

## words.json

`[{ id, w, en, lv, pos?, rank?, pron?, alt?, audio? }]`, in teaching order within each level. Sets are consecutive runs of `setSize` words of one level, in file order.

| field | type | meaning |
|---|---|---|
| `id` | string, unique | Stable id. Progress is keyed by it, so never renumber a published pack. The zh pack uses `w0001`…. |
| `w` | string | The word as written. It is shown, spoken by TTS, and is the typed or recalled answer. |
| `en` | string | English gloss. It is the answer label in meaning items. Distractors avoid the same gloss and the same first two gloss words. |
| `lv` | levelId | Must be one of `pack.levels[].id`. |
| `pos` | string | Optional part of speech. Recall and cloze distractors prefer the same `pos` and level. |
| `rank` | number | Optional frequency rank. It is validated but not yet used, and set order is file order. |
| `pron` | string | Optional pronunciation (pinyin, IPA). It is display-only, except that `typing: "pron"` makes it a typed answer. |
| `audio` | URL string | Optional recorded clip of `w`, with the same rules as `sentences.json` `audio`. Every place the app speaks the word plays it instead of TTS, and a word with a clip can be heard with no voice (Listen items, taps, placement, the script primer's example words; app.html `sayWord`/`canHearWord`). |
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
| `audio` | URL string | Optional recorded audio. When present it plays instead of TTS. Relative URLs resolve against the built HTML file's location, not the pack directory, so ship audio beside the built page or use absolute URLs. A clip that fails to play (offline and not cached, a 404) falls back to TTS when a voice exists, else a short hint is shown. `packbuilder audio` writes relative content-addressed `audio/…/<id>.<sha8>.opus` URLs and never changes an absolute (Tatoeba) one or a relative one it did not write. |
| `ruby` | `[[start, end, reading, wordId]]` | Optional, only meaningful with `pack.characters`. Per-token readings for characters tiering: each tuple is a UTF-16 offset range into `t` (`end` exclusive, same convention as `passages.json` `spans`), the reading text for that range, and the `characters.json` unit's `words[0]` id that range belongs to (so 这个 maps to its base word), or `null` for a token of no unit word (a name, a word the sentence does not link or that has no unit): it follows streak 0, so it shows its reading under `pronFirst` and the ruby tier otherwise. ja writes a token for every kanji (langs/ja.py `sentence_ruby`), so every sentence can show every kanji with a reading. Tuples are sorted, non-overlapping, and each covers non-blank text without splitting a surrogate pair. A sentence with `ruby` renders `<ruby>t<rt>reading</rt></ruby>` per token below the `bare` tier and `<ruby class="bare">t<rt>reading</rt></ruby>` at or above it, with that `<rt>` hidden (`visibility:hidden`), so a token's width and the line's wrapping never change across tiers. With pron hidden or the mix preference off the sentence renders as plain text, as without characters. |

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
[{ id, lv, title, titleRuby?, text, src?,
   sentences: [{ t, en, words: [wordId], spans?: [[start, end, wordId]], ruby?: [[start, end, reading, wordId|null]], audio? }],
   questions: [{ q, en?, type: "mc"|"tf", options: [4 strings] | null, answer, words: [wordId], sentence,
                 ruby?, optionsRuby?: [ruby per option] }] }]
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
| `sentences[].ruby` | `[[start, end, reading, wordId]]` | Optional, only meaningful with `pack.characters`. Same format, rules and rendering as `sentences.json` `ruby`, per passage sentence; a token crossing a tap-span edge renders plain. As in `sentences.json`, `wordId` may be `null`: a token of no pack word (a name, an out-of-pack word, zh aspect 过) with no unit, so it follows streak 0 (its reading under `pronFirst`, the ruby tier otherwise). zh writes a token for every hanzi (`packbuilder passages`, langs/zh.py `passage_ruby`) and ja one for every kanji (langs/ja.py `passage_ruby`, readings in hiragana over the kanji only, okurigana outside: 悪かった is 悪 わる), so a pronFirst passage never shows a hanzi or kanji below mastered. |
| `titleRuby` | ruby list | Optional, same tuple format for `title` (wordId `null` or a characters.json unit's `words[0]`; no words list applies). Rendered under `pronFirst` (app.html `pfRubyText`): the passage list button, the Today read hint, the passage heading and the results heading show the title by the sentence tier rules, readings tone-coloured with `tones`, a `null` token by its reading. The heading and hint get a show-written tap; list buttons do not. Without `pronFirst` (or without `titleRuby`) the title shows as written. |
| `questions[].ruby` | ruby list | Optional, same format for `q`. Rendered under `pronFirst` like `titleRuby`, on the question screen and the results screen, with a show-written tap. No word taps. |
| `questions[].optionsRuby` | `[ruby list]` | Optional, mc only: one ruby list per `options` entry, same index (a list may be empty). Rendered under `pronFirst` like `titleRuby` inside each option button, with no show-written tap and no word taps (the button is the tap target). An empty list shows the option as written. |
| `sentences[].audio` | URL string | Optional recorded clip of the sentence, with the same rules as `sentences.json` `audio`. The Read tab's per-sentence read-aloud plays it, also with no voice. |
| `sentences[].spans` | `[[start, end, wordId, gloss?]]` | Optional. Where each linked word sits in `t`, as written by the builder from its tagger tokens (`packbuilder passages`), so inflected forms (mele, compra, va) are tappable in place. Offsets are UTF-16 code units (JavaScript string indices; equal to character indices for text without characters above U+FFFF), `end` exclusive. Spans are sorted and do not overlap, each `wordId` is in `words`, and a word may have several spans (one per occurrence). A multi-token unit the builder links as one word (per favore) is one span. `words` stays the full list: a word without a span falls back to surface matching, and packs without `spans` render exactly as before. Invalid spans are ignored by the app. Optional 4th element `gloss`: a non-empty display-only string shown in the tap-to-gloss popover instead of the word's `en` (fallback: span gloss, then the word's gloss). zh uses it for phrase units linked to a head word (越来越 -> 越 "more and more", 开车 -> 开 "to drive") and, in zh and ja, for display glosses from `gloss_display.json` (`packs/zh/gloss_display.json`, `japanese/tools/gloss_display.json`: a sense list per headword). It never changes `words`, drills, weak words or progress; a span without it, and a pack without it, render exactly as before. |
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
- `typing.strictFromLevel` exists. `typing` is an object, `"pron"` or `null`; with `"pron"`, no word having a `pron` is an error and some words lacking one is a warning.
- `tones`, when present, is `"pinyin"`. `soundsReference`, when present, is `true`; a warning when `hasLessons` is not true or no lesson row has a one-character `say`.
- Script fields: `rtl` is a bool, `langTag` is a BCP-47 tag, `fontFamily` has no `;`, `{`, `}`, `<`, `>`, `\`, `/*` or `url(`, every `fonts` entry is a Google Fonts family name, and `lineHeight` is 1–4. A pack with `rtl` true and neither `fontFamily` nor `fonts` gets a warning.
- Lesson answers are among their options.
- `passages.json`, when present: unique ids, `lv` is a pack level, `title`/`text` non-empty, non-empty `sentences` with `t`, `en` and known `words` ids, optional `spans` (a list of `[start, end, wordId]`, or `[start, end, wordId, gloss]` with a non-empty gloss string, with integer UTF-16 offsets, `0 <= start < end <= len(t)`, sorted, non-overlapping, not splitting a surrogate pair, `wordId` in that sentence's `words`, covering non-blank text), non-empty `questions` with `q`, `type` mc or tf, mc `options` of 4 distinct strings with `answer` 0–3, tf `answer` a bool and no options, known `words` ids, and `sentence` a valid index. A sentence `t` missing from `text` and a question with empty `words` are warnings.
- `pack.characters`, when present: `stages` is a non-empty list of `{after, levels}` with existing level ids, `after` non-decreasing in `pack.levels` order, and every level id covered by exactly one stage; `mastered`/`setSize` positive ints and `bare > mastered`; `learnKinds`/`reviewKinds` non-empty lists of known kinds; `testKinds`, when present, a non-empty object of known kinds to positive weights; every `stages[].levels` id at or before that stage's `after` in `pack.levels` order. `characters.json` must exist exactly when `pack.characters` does, each error naming which side is missing.
- `characters.json`, when present: unique ids, non-empty `t`, non-empty `words` with known word ids, and `lv` a pack level, equal to the level of `words[0]`, and covered by a `pack.characters.stages[].levels`.
- `sentences[].ruby` (and `passages.json` `sentences[].ruby`), when present: same offset rules as `passages.json` `spans` (sorted, non-overlapping, in-bounds, no split surrogate pairs, non-blank), plus a non-empty `reading` and a `wordId` that is either `null` or both in the sentence's `words` and some `characters.json` unit's `words[0]`.
- `passages.json` `titleRuby`, `questions[].ruby` and `questions[].optionsRuby` (one ruby list per option, same length as `options`), when present: the same offset and reading rules against `title`, `q` and each option, with `wordId` `null` or some `characters.json` unit's `words[0]`. Without `pack.characters` they are a warning.
- `pack.script` and `script.json`, when present: see "Script primer" above.
- Recorded audio: `pack.audio`, when present, is `{voice, version}` with a non-empty `voice` and an integer `version` ≥ 1 (other keys are a warning). `audio` on words, sentences and passage sentences is a non-empty string when present. `pack.audio` with no clip anywhere (words, sentences, passage sentences or script units), relative clips without `pack.audio`, and relative clips with no file beside the site page (resolved against the pack directory's parent, where a language repo's `index.html` sits) are warnings. `packbuilder audio --check` checks that the files exist (docs/AUDIO.md).
- `pack.legacy` and `legacy.json` must exist together, and every value in `legacy.json`'s `w`/`s`/`c` maps is a real `words.json`/`sentences.json`/`characters.json` id (duplicate values across one map are a warning).
- The generated `.js` files are in sync.

A word that shares its surface form with another word at the same level produces a warning.
