# Script primer: design and plan (TODO item 1c)

A pack-gated stage that teaches a non-Latin script before A1: symbol → sound, recognition, then syllable and word reading on the pack's own A1 words. Consumers: ko Hangul, ru Cyrillic, fa Persian, ja kana; ar, hi, ur are built with it from the start. zh keeps pinyin in the Sounds tab. Kanji stay in the characters stage (`docs/HSK_MERGE.md` §2).

Decisions in force: pronunciation-first for logographic packs (built, BP). The primer is unlocked before A1, with a "skip, I can read" choice that is reversible from Progress (user 2026-09-25). Placement is untouched. "Never start a learner with pictograph letters; ease of learning over coding ease."

## 0. Live state that shapes the design

Probed 2026-09-26 against `../{korean,russian,persian,japanese}/pack`:

| pack | `pron` on words | what it is | TTS voice |
|---|---|---|---|
| ko | 0 of 2000 | none | ko-KR on Apple, Google, Samsung (not probed for bare jamo) |
| ru | 2000 | Cyrillic with stress marks (`тако́й`), not Latin | ru-RU common |
| fa | 1980 | Latin, packbuilder scheme (`â`, `kh`, `sh`, `q`, `gh`, `'`) | none on Apple, Windows or Google TTS (TODO "Generated audio") |
| ja | 2000 | kana, not romaji | ja-JP common |

Consequences:
- The pack's words carry no Latin romanisation except in fa. The primer's romanisation comes from `script.json` itself: per symbol, and per example word as emitted by packbuilder.
- fa must work with no audio at all. Every audio kind has a text fallback, and there is a per-unit `audio` hook for the Piper plan.
- ja A1 has 10 katakana words, and the first one is A1 word 229 (set 23). Katakana is needed inside A1 (question 2).
- ko A1 has 342 of 600 words with no final consonant before the last block (나, 우리, 가다). Early example words come from these, so no sound-change rule is needed to read them.

## 1. Learner flow

**Path.** `stagePath` prepends one `{kind:"script"}` stage per `pack.script.stages` entry before the first word level, unless `prog.script.skipped`. ja has two stages (ひらがな, カタカナ); every other pack has one. The strip shows them like character stages.

**Choice card.** It shows on Today when `pack.script` exists, `choiceSeen` is false, and no script record exists. It sits above the placement hint and replaces Start today until answered, like the characters card.
- "Learn the script" sets `choiceSeen` and leaves `skipped` false.
- "I can read it, skip" sets `choiceSeen` and `skipped`. The next stage is A1 set 1, or wherever placement put the learner.
- Placement is unchanged. A learner who places into A2 still meets the choice card, because placement tests words, not the script.

**Reversibility.** Progress gets a chip pair, "Script primer on" and "Script primer off", that calls `setScriptSkipped`. It flips the flag only. The path is re-derived, so turning it on re-inserts the script stage at the front, and `nextStage` becomes that stage. Word records, set counters and script records are never touched. A running session keeps its snapshot, as with the characters order chips. While skipped, script units are left out of Review, Recall and Test.

**Today while a script stage is next:**

| step | behaviour |
|---|---|
| Review | 12 script items, weakest first, once one set is taught. Gated on recorded script units (`todayGates` gets a unit count), since no words are learned yet. |
| Learn | Up to `setsPerSession` script sets (default 2). Each set gets teach cards, then its drill. After set 1 a "One more set" button offers set 2 and the finish screen follows either way. |
| Listen, Recall, Sentences | Skipped by their own gates until words exist. |

After the last script set the path moves to A1. Recorded script units then join the unified Review pool like character units. Mastered units rank low under the existing `charReviewScore` logic, so they fade out without a rule of their own.

**Done.** The stage is done when every unit in it has a record, which is the same rule as `charSetTaught`. **Mastered** is per unit and matches the characters tier: streak ≥ `mastered` (default 3). Learn asks one recognition kind and one sound kind per unit, so a unit's first streak spans both. Progress shows taught, mastered and a "Script mastered" line once every unit is mastered. Nothing derived is stored (see §4).

## 2. Item kinds

Each item scores one unit's record, `prog.script.u[id]`. Options are 4, shuffled. The stimulus never shows the answer.

| kind | stimulus | answer | options | audio |
|---|---|---|---|---|
| `symSound` | glyph, large | `roman` | romans of distractor units | plays `say` after answering |
| `soundSym` | `say` via TTS, or `roman` text with no voice | glyph | distractor glyphs | before answering |
| `symType` | glyph | typed `roman` or any `alt` | none | after answering |
| `compose` | `parts` joined with " + " (ㄱ + ㅏ, き + ゃ, क + ा) | the syllable `t` | other syllables sharing a part | after answering |
| `formFind` | the isolated letter plus its name | the example word containing it, in any joined form | 3 example words without that letter | after answering |
| `formMatch` | one joined form, init, medi or fina, rendered with ZWJ | the isolated letter | distractor glyphs from the same shape family | none |
| `wordRead` | example word, no audio | its roman | romans of other taught example words | word audio after answering |
| `wordHear` | example word audio | the word | other taught example words, nearest by edit distance | before answering |

**Silent units.** A unit with `sound:false` (ru ь ъ, ja っ ー) never gets `symSound`, `soundSym` or `symType`. It gets `wordRead` and `wordHear` on its examples, and its teach card carries the rule.

**No voice.** Where there is no voice, as for fa today, `soundSym` shows `roman` and `wordHear` becomes `wordRead`. A unit or example with a recorded `audio` URL plays it instead of TTS, through the existing `speak(text, btn, audioUrl)`.

**Distractors** for symbol options come from `scriptOpts`. The pool is units of the same stage and `group`, either already recorded or in the current set. The preference order is:
1. The unit's `confuse` list (ㅏ/ㅑ/ㅓ, б/в/ь, ш/щ, ب/پ/ت/ث, さ/き, シ/ツ, ソ/ン).
2. Same `group`.
3. Same set.
4. Any recorded unit.

If fewer than 3 remain, the pool is padded from the `confuse` list even when those units are untaught. A set-1 item therefore never has fewer than 4 options.

**Four options or the kind does not fit.** Every option kind (all but `symType`) needs at least 4 distinct options when distractors may come from every unit. Otherwise `scriptKindFits(kind, unit, ctx)` is false, so no Learn, Review or practice plan picks it, and `pickScriptKind` moves to the next kind. ctx is `{units, byId | words, tts}`. The app always passes it, and the Review and practice plans default `units` to their own. Compose distractors widen in this order: the same set, the same stage, then any stage written in the same Unicode script. Hiragana and katakana are two scripts and never mix.

**Never a second right answer:**
- `soundSym` and `formMatch` never offer a unit with the same `roman` or `say`. That covers fa ت/ط, س/ص/ث, ز/ذ/ض/ظ, ه/ح, ja じ/ぢ and ず/づ.
- `symSound` never offers a duplicate roman.
- `alt` is typed acceptance only (`symType`). An option item (`symSound`, `soundSym`, `formMatch`) excludes by glyph, `roman` and `say`, and by `alt` only when two units accept each other's roman (homophones: fa غ gh/q, ق q/gh). A one-way alt is a contrast to drill: ko ㄱ (alt `k`) is offered against ㅋ, ㄷ against ㅌ, ㅂ against ㅍ, ru Е (alt `e`) against Э (decision 2026-09-26, core.js `scriptSecondRight`).
- `formFind` distractors never contain the letter, compared by the validator's fold (core.js `scriptGlyphIn` = validate_pack.py `glyph_in`): آب contains ا, a batchim contains its jamo (책 has ㄱ), case folds. The teach card's example tint uses the same fold.
- `wordRead` and `wordHear` never offer two words with the same roman.
- Hira and kata units never mix within one item.

**Word distractors** use taught example words only. The order is: differs from the answer in the target unit only, then same length, then any. There is no gloss in these items, because the primer is about reading. The gloss is shown in the reveal.

**Kinds per family:**

| family | learnKinds | reviewKinds | why |
|---|---|---|---|
| ko Hangul | symSound, compose | symSound, soundSym, compose, wordRead | Blocks are the reading unit. compose is used from set 2, once both vowels and consonants exist. |
| ru Cyrillic | symSound, soundSym | symSound, soundSym, wordRead, wordHear | Letters are sequential, so words carry the practice. The false friends В Н Р С У Х need both directions. |
| fa, ar, ur | symSound, formFind | symSound, formMatch, formFind, wordRead | Joining forms are the real difficulty. soundSym degrades to text with no voice. wordRead uses the pack `pron`. |
| ja kana | symSound, soundSym | symSound, soundSym, compose (yōon), wordRead | Dakuten sets are learned by rule, and yōon by compose. |
| hi Devanagari | symSound, compose | symSound, soundSym, compose, wordRead | Matras and conjuncts are compose: क + ि = कि. |

`symType` goes into `testKinds` only. Typing on a phone is slow, and recognition is the primer's goal. Question 5 covers this.

## 3. Data: `pack/script.json`

```json
{ "units": [
  { "id":"ko-a", "st":"hangul", "set":1, "group":"vowel", "t":"ㅏ", "name":"아", "roman":"a", "alt":[],
    "say":"아", "sound":true, "note":"a as in 'father'", "confuse":["ko-ya","ko-eo"],
    "ex":[["w0003","na"],["w0005","gada"]],
    "syll":[{"t":"나","parts":["ㄴ","ㅏ"],"roman":"na"}] },
  { "id":"fa-be", "st":"abjad", "set":1, "group":"be", "t":"ب", "name":"be", "roman":"b",
    "joins":"dual", "ex":[["w0003","be"]] },
  { "id":"ja-ga", "st":"hira", "set":7, "group":"dakuten", "t":"が", "roman":"ga", "base":"ja-ka" },
  { "id":"ru-d", "st":"cyr", "set":3, "group":"new", "t":"Д д", "roman":"d", "italic":"д" } ],
  "notes": [ {"st":"abjad","set":5,"h":"Ezafe","body":"…"} ] }
```

| field | type | meaning |
|---|---|---|
| `id` | `<lang>-<slug>`, unique | Progress key. It is stable and never renumbered. It is not the glyph, because ko ㄱ initial and ㄱ final are separate units. |
| `st` | stage key | One of `pack.script.stages[].key`. |
| `set` | int ≥ 1 | Teaching set within the stage. File order is the order within a set. |
| `group` | string | Distractor family: vowel/consonant/tense, the fa dot family, the kana row, dakuten. |
| `t` | string | The glyph shown. ru shows "Д д" on teach cards; items use the lower case. |
| `name`, `roman`, `alt` | strings | The letter's name, its canonical romanisation (Revised Romanization for ko, a BGN-like scheme for ru, the pack scheme for fa, Hepburn for ja), and accepted typed alternatives (ㄱ `g`/`k`). |
| `say` | string | The TTS carrier, chosen per the §5 probe: a bare glyph, a carrier syllable (가, 아), or the letter name. It is absent when unspeakable. |
| `audio` | URL | Optional recorded clip (Piper for fa). It beats `say`. |
| `sound` | bool, default true | false for silent or modifier units. |
| `note` | string | A one-line sound note, plain text. |
| `confuse` | `[unitId]` | Hand-listed visual confusables. |
| `ex` | `[[wordId, roman]]`, 1–3 | Example words from this pack, with a letter-level romanisation. fa uses the word's `pron`. |
| `syll` | `[{t, parts, roman}]` | Composition examples: Hangul blocks, yōon, matras and conjuncts. `parts` are glyphs of units at or before this set. |
| `joins` | `"dual"` / `"right"` | Arabic-script letters only. Forms render as `L+ZWJ`, `ZWJ+L+ZWJ` and `ZWJ+L`. No per-form strings are stored, since Unicode shaping draws them. |
| `base` | unitId | Kana dakuten, handakuten and katakana variants: the teach card shows base → variant. |
| `italic` | string | ru: the glyph whose italic or cursive shape differs (д, т, и, п, г). The card shows it in italic. |

`notes` are rule cards shown with the teach cards of `(st, set)`. Examples: fa short vowels unwritten, ezafe; ru hard and soft sign, stress reduction; ko batchim sounds and liaison; ja long vowels.

**Teaching order and size:**

| pack | order (sets) | units | sets |
|---|---|---|---|
| ko | silent ㅇ + ㅏㅓㅗㅜㅡㅣ, then ㄱㄴㄷㄹㅁㅂㅅ, then ㅈㅊㅋㅌㅍㅎ, then ㅑㅕㅛㅠ + ㅐㅔ, then ㄲㄸㅃㅆㅉ, then ㅒㅖㅘㅙㅚㅝㅞㅟㅢ, then batchim ㄱㄴㄷㄹㅁㅂㅇ as finals | 47 | 7 |
| ru | true friends А К М О Т Е, then false friends В Н Р С У Х, then new Б Г Д З И Й Л П Ф, then Ж Ц Ч Ш Щ, then Ы Э Ю Я Ё, then Ь Ъ | 33 | 6 |
| fa | ا ب پ ت د ر ز م ن, then ث ج چ ح خ, then و ی ه آ ذ ژ, then س ش ص ض ط ظ, then ع غ ف ق, then ک گ ل | 33 | 6 |
| ja | ひらがな: vowels + か, さ + た, な + は, ま + や + ら, わ を ん, dakuten ×2, handakuten, small ゃ ゅ ょ っ, yōon ×3. カタカナ: the same (ー with ワ ヲ ン), plus 12 extended (ティ ファ ウィ…) | 108 + 121 | 12 + 13 |
| ar, ur, hi (future) | Arabic 28 + ة ى ء + 3 harakat + sukun, shadda. Urdu 38 + ھ digraphs. Devanagari 11 vowels, 33 consonants by varga, matras as compose, 10 common conjuncts, ं ः ँ ़ | ~38 / ~42 / ~60 | 5–8 |

**Rationale for the order:**
- **Readable words early.** The first set that combines with an earlier one must spell real A1 words: ko 나 너 이 우리, fa بابا نان در, ru мама кот там. ko teaches the silent ㅇ with the vowels, so set 1 already reads 아이 and 오 (decision 2026-09-26).
- **Small kana are units** (decision 2026-09-26): ゃ ゅ ょ っ and ャ ュ ョ ッ are taught in the set before the first yōon set, with their own roman (ya, yu, yo; っ is `sound:false`), confuse-linked to their full-size forms. A yōon unit keeps `base` (the i-row kana) and has `syll` parts [i-row kana, small kana], so `compose` works. A yōon in a word is read from its parts: the word is readable once き and ゃ are taught. A hiragana yōon in an A1 word also gives the katakana twin (キャ from きゃく) as a katakana `syll`, since A1 has one katakana yōon (ニュ) and a compose item needs 3 distractor syllables of its own stage. The validator accepts a later stage's `syll.t` attested after kana folding. Packbuilder drops any syllable that could not get 4 compose options and reports it (`syll_dropped`).
- **Confusables grouped.** Dot families and ㅏ/ㅓ are taught in the same set, so the difference is taught once, on purpose.
- **Rule-based variants last.** Dakuten and tense consonants are one rule applied to known shapes.

**Packbuilder.**
- Each `langs/<x>.py` gets a `SCRIPT` table: the hand-written units, minus `ex` and `syll`. Adding `script = {...}` turns on the pack.json block, the same way `characters` does.
- A generic `core/pipeline.py write_script(env, out_words)` emitter fills in the generated fields.
- **`ex`:** up to 3 words from the shipped A1 set, falling back to A2. The unit must appear in the word, initial position is preferred, and so is file order, which is the frequency order. The word must be readable, meaning every unit it contains sits at or before this set. One unknown unit is allowed only when no fully readable word exists, and ko prefers words with no final consonant before the last block.
- **ja katakana `ex`** (decision 2026-09-26): ja A1 and A2 hold only 62 katakana words, so a katakana unit's example may hold up to 2 unknown katakana, and B1 is the last fallback after A1 and A2. A unit with no such word ships without `ex`. The spec hook is `script_ex_policy`.
- **`ex` roman:** ja via the existing `langs/ja.py romaji()`; ko via block-wise Revised Romanization with no sound change, which the ex rule keeps equal to the spoken form; ru via the table's `roman`; fa via the word's `pron`.
- **`syll`:** syllables that occur in the shipped A1 words, ranked by frequency. For ko, blocks are decomposed by Unicode arithmetic.
- Output is deterministic. `stat("script", …)` reports every unit whose `ex` needed the fallback.

**`tools/validate_pack.py` rules:**
- `script.json` exists exactly when `pack.script` does.
- Ids are unique and match `^[a-z]{2,3}-[a-z0-9-]+$`.
- `st` is a known stage key, `set` is an int ≥ 1, and each stage's sets are contiguous from 1.
- `t` and `roman` are non-empty, and `sound` is a bool.
- `confuse` and `base` reference known ids.
- `ex` word ids exist, their level is the first level (the second level, packbuilder's fallback, is a warning; the third level is a warning for a unit of a later stage, such as ja katakana, and an error for the first stage; later is an error), the roman is non-empty, and the unit's glyph occurs in the word's `w` or `pron`. The comparison uses compatibility decomposition and lower case, and folds positional letter variants, so a jamo matches inside a composed block and a dakuten kana inside its word.
- `syll.parts` are glyphs of units at or before this set, and `syll.t` occurs in some A1 word (for a later stage, after folding katakana to hiragana).
- `joins` is present only when `pack.rtl`.
- `notes` reference a known `(st, set)`.
- **Warnings:** a unit with no `ex`; two units in one group with the same `roman` and no `confuse` link; a `say` missing on a `sound:true` unit.
- `script.js` is in sync. jsonify and `build.sh` handle it like `characters.js`.

`pack.json`:
```json
"script": { "stages":[{"key":"hira","label":"ひらがな"},{"key":"kata","label":"カタカナ"}],
  "setsPerSession":2, "mastered":3, "tts":true,
  "learnKinds":["symSound","soundSym"], "reviewKinds":["symSound","soundSym","compose","wordRead"],
  "testKinds":{"symSound":35,"soundSym":25,"wordRead":25,"symType":15} }
```
`tts` false means every `say` is treated as absent. It is set from the §5 probe per language, and it is false for fa.

## 4. Progress model

`prog.script = {v:1, u:{[unitId]:{r,w,s}}, skipped:false, skip:{}, choiceSeen:false, notice:false}`. `skipped` switches the whole primer off; `skip[stageKey]` switches one stage off (decision 2: each ja stage is skippable on its own). Records reuse the chars shape and `markRec`. `notice` is true while the existing-learner notice below is pending; `dismissScriptNotice` clears it.

- `defaultProg` and `normalizeProg` add the field only when `pack.script` exists. `validateProgShape` validates it whenever it is present: `v` is a positive integer, `u` goes through `validateRecMap`, and both flags are booleans. Top-level `v` stays 1.
- **No migration.** The field is new, and normalize fills it. **Existing learners are the exception**: a stored progress with at least one `w` record and no `script` key normalizes to `skipped:true, choiceSeen:true, notice:true`. They then get a one-time dismissible Today line: "A script primer is available. Turn it on in Progress." Without this rule, every current ru, ko, fa and ja learner would be sent back before A1 (question 1).
- **Deviations from the brief's sketch.** The record map is `u`, not `s`, because `s` is already the streak field inside every record and top-level sentences. There is no stored `done`, because done, taught and mastered are all derived from records. Stage completion counts recorded units, so a missed review can never pull the stage back into the path.
- **Flag-off guarantee:**
  - A pack without `pack.script` gets byte-identical `defaultProg`, `normalizeProg`, `stagePath`, plans and boot renders.
  - `tests/flagoff_snapshot.js stripFlagOnFields` also deletes `pack.script`, and the harness ignores `script.json` and `script.js` in the sibling-repo source check.
  - The zh and ja character goldens are recaptured only if ja gains `script`. That happens in the data brief, as a separate golden commit.

## 5. Engine surface

**core.js** gets a new section, DOM-free. As built in S1: the script units (`SCRIPT.units`) are an optional last argument `sunits` of `stagePath`, `nextStage`, `charsStarted`, `showCharChoice` and `todaySnapshot`; every call without it, and every pack without `pack.script`, returns exactly what it did before.

| export | contract |
|---|---|
| `scriptConfig(pack)` | Normalized `pack.script` (defaults, known kinds only), or null. |
| `scriptStageUnits(key, units)` | The stage's units in `set` order, then file order. |
| `scriptSets(key, units)` | `[[unit]]` grouped by `set`. |
| `nextScriptSets(key, units, pack, prog, n)` | Up to n first untaught sets: `{index, units, total}[]`. |
| `stagePath` (changed) | Prepends `{kind:"script", key, label, recorded, nunits, nsets, frac, done}` per stage unless skipped. Output is unchanged without `pack.script`. |
| `scriptSkipped(prog, key?)` / `setScriptSkipped(prog, bool, key?)` | Read or flip the flag: the whole primer, or with `key` one stage. Nothing else is touched. An off stage leaves the path, Review and Test. |
| `showScriptChoice(pack, units, prog)` / `answerScriptChoice(prog, learn)` | The choice card rule (§1). |
| `scriptItem(kind, unit, ctx)` | `{kind, key:"x:"+id, unitId, show, audio, say, audioUrl, options, answer, reveal}`. ctx is `{units, words, byId, tts, rng}`. It throws on an unknown kind. |
| `scriptOpts`, `scriptRomanOpts`, `scriptWordOpts` | The distractor rules in §2, exported for tests. |
| `learnScriptPlan(set, pack)` | One item per learnKind per unit. A unit with `sound:false` swaps in wordRead. compose is used only when the unit has `syll`. |
| `markScript(prog, id, ok)` | Writes `prog.script.u` only. |
| `scriptMastered(rec, pack)` | `s >= mastered`. |
| `scriptTestPlan(units, prog, pack, n, rng)` | The n weakest recorded units, kinds drawn from `testKinds`. |
| `todaySnapshot` (changed) | With `pack.script` only: adds `ssets` (script sets for Learn, `[]` off the script stage), and `choice` becomes `"script"` while the script card shows (otherwise the characters boolean, unchanged). `reviewSize` is 12 while a script stage is next. |
| `todayGates` (changed) | An optional recorded-script-unit count opens Review. |
| `buildReviewPlan` (changed) | An optional `script` pool. Script units join `rankUnified` as kind `"x"` with `charReviewScore` semantics and draw a random reviewKind. |

**app.html:**
- **Script tab.** It takes the Sounds slot, labelled from `pack.script.stages[0].label`, when `pack.script` is set and `hasLessons` is false. That is true for all four consumers, so the tab bar is unchanged at 390px. A pack with both gets a Script section at the top of Sounds. The tab holds a chart of every unit in teaching order, coloured by tier, each tappable to hear `say` or open its teach card. It also has "Practise weakest 20", which runs `scriptTestPlan`.
- **Teach card, 390px.**
  - Glyph at 64px, left for LTR and right for RTL.
  - Beside it: `name`, `roman` in bold and `note`.
  - A play button, hidden with no voice and no `audio`.
  - Row 2 by script: fa, ar and ur show the forms strip, four cells for dual joiners or two for right joiners, in visual RTL order (isolated, initial, medial, final from the right), each labelled underneath in English. ko shows `syll[0]` as a "ㄴ + ㅏ = 나" strip. ja shows `base` → variant.
  - Row 3: `ex` words as teach rows (word, roman, gloss). The unit is highlighted with a background tint on a wrapping span, not with bold or a font change, so joined words keep their shaping.
  - A set's `notes` card goes first.
- **Items** reuse the drill shell. Glyph stimuli use `.cform` at 64px. Option buttons are 2×2 for glyphs and a list for romans and words. RTL follows "Script display" in PACK_SCHEMA.
- **Progress.** Per-stage rows ("n / N taught · m mastered"), the on/off chip pair with the line "Changes what Today's Learn step teaches next. Nothing you've learned is lost.", and the Script mastered line.
- **Today.** The script choice card, the Learn line "ひらがな, sets 3–4 of 11", and the "One more set" button.

**As built in S3 (app.html):**
- `script.js` declares the global `const SCRIPT` (the `{units, notes}` data). The app's display settings, formerly also `SCRIPT`, are now `DISP`; two top-level `const SCRIPT` in one page are a redeclaration error that stops the app script (`tests/script_app_checks.js` [11] runs a built page's scripts in one scope).
- **Example words are shown in the script.** A word whose `w` has letters outside the primer's inventory (every unit glyph and `syll.t`, compared after compatibility decomposition and lower-casing) while its `pron` is fully inside it is shown, spoken and answered by its `pron`. A Latin `pron` (fa) never replaces the word. On the shipped data this switches 163 of 267 ja example words from kanji to kana, and no ko, ru or fa word; afterwards no example word in any pack shows an untaught letter. The rule is app-side (`SCRIPT_BYID`), so `scriptItem` receives it through `ctx.byId`.
- No voice means `pack.script.tts` false or no browser voice for the pack's language (`ctx.tts = tts && hasSpeech`). A unit's recorded `audio` still plays.
- The existing-learner notice shows while the primer is off and until dismissed (persisted through `dismissScriptNotice`). The Progress chips only call `setScriptSkipped`; turning the primer or a stage on there also clears the notice, so turning it off again does not bring it back.
- The Script tab button is labelled with the first stage's label and uses that stage's first symbol as its icon. The practice button reads "Practise weakest N", where N is the size of the plan (at most 20).
- The drill runner's `drill(items, onDone, summary, onShown)` gained an optional hook that wires "One more set" on the end screen.

**TTS: live state, probed before any build (brief S0).** For each of ko-KR, ru-RU, fa-IR and ja-JP:
1. Wait for `speechSynthesis.getVoices()` to settle through `voiceschanged` or 2 s. List every voice with lang, name and localService on Chrome/mac and Safari/mac. The user reports the same on their Samsung (Android Chrome).
2. For each unit, speak three candidates: the bare glyph, the carrier syllable, and the name. Record `onstart` to `onend` duration and any `onerror`. A duration under 120 ms, an error, or no `onend` within 3 s means unspeakable. Candidates:
   - ko: bare ㄱ, carrier 가 or 아, name 기역.
   - ru: bare б, carrier ба, name бэ.
   - ja: bare は, っ, ー, ゃ, plus きゃ.
   - fa: bare ب, carrier بَ, name "be".
3. The probe cannot tell which reading was spoken. `tools/tts_probe.html` (dev only) lists every candidate with a play button. The user listens on the phone and marks right or wrong. That sheet decides `say`, and `pack.script.tts`. Expected results, unverified: ko voices read bare jamo as names or not at all, so ko uses carriers. ru bare letters read as names, so ru uses carriers. ja bare kana are fine except は/へ as particles and small kana. fa has no voice.

## 6. Tests, browser walk, briefs

**Checks that fail before and pass after** (`tests/script_checks.js` unless noted):
1. `stagePath` on a synthetic ko-like pack starts with a script stage. After `setScriptSkipped(true)` it equals the flag-off path. After `false` it has the stage again, with `w`, `sets` and `u` deep-equal throughout.
2. `showScriptChoice` is true for fresh progress, false after either answer, and false once any script record exists.
3. `normalizeProg` on stored progress with `w` records and no `script` gives `skipped:true`. Fresh progress gives `skipped:false`.
4. `scriptOpts` never returns a same-roman or same-`say` unit for soundSym. Covered on a fa-like fixture (ت/ط, س/ص/ث) and ja (じ/ぢ).
5. The set-1 pool has 4 options, padded from `confuse`. Hira and kata never mix.
6. `learnScriptPlan` covers every unit in the set. A `sound:false` unit gets no symSound or soundSym.
7. No voice (`tts:false`): soundSym shows roman, and wordHear is replaced by wordRead.
8. The Review plan with a script pool and 0 learned words gives 12 script items. With skipped, it gives none.
9. The flag-off harness passes, with `script` stripped, on every sibling pack and on zh.
10. `validate_pack_script_checks.js`: a dangling `confuse`, an `ex` glyph not in the word, a `syll.parts` from a later set, a non-contiguous `set`, `joins` in a non-RTL pack, and `script.json` without `pack.script` each fail. The shipped packs pass.
11. App boot (fake DOM): a fresh ko seed shows the choice card, Learn runs 2 sets, and Progress chip off moves Learn to A1 set 1.
12. Packbuilder: `write_script` run twice is byte-identical. Every `ex` word is readable by its set or is flagged in stat, and ja `ex` roman equals `romaji(pron)`.

**Browser walk** of `dist/{ko,ru,fa,ja}.html` at 390, 360 and desktop, light and dark:
- [ ] Fresh load shows the choice card. Learn gives set 1 teach cards, the drill, "One more set", and finish.
- [ ] Skip, then the Progress chip on: the script stage returns first, and word progress is unchanged.
- [ ] ko: the compose item and the 나 strip.
- [ ] fa: the forms strip in RTL with 4 or 2 cells, shaping intact under the highlight span, and no overflow at 360.
- [ ] ja: the dakuten base → variant card, the っ note, and the katakana stage after the hiragana stage.
- [ ] ru: italic д and т on the card.
- [ ] An existing-learner seed boots skipped and shows the notice once.
- [ ] Script tab: the chart, a tap plays exactly one utterance, and "Practise weakest 20".
- [ ] No-voice path: fa, and ko with voices stubbed out.

**Measured basis for the estimate.** The characters-stage briefs were 7–27 lines each. Times run from brief-file creation to the implementation commit on 2026-09-25:

| brief | time |
|---|---|
| B1 schema | 11 min |
| B2 core, 993 lines | 15 min |
| B3 zh data | 5 min |
| B7 ja data | 14 min |
| B6 migration | 11 min |
| B4 app part 1 | 10 min |
| B5 app part 2 | 8 min |
| B8 polish | 16 min |

Design commit to final merge took 87 min. Review and browser walks sat inside that window. The user's phone ear-check is not measured.

| id | brief | files | acceptance | depends | model | estimate (from the B analogue) |
|---|---|---|---|---|---|---|
| S0 | TTS probe (§5): `tools/tts_probe.html` plus the automated durations | the probe page only | a per-language table of voices and candidate durations, and the page ready for the user's ear-check | none | browser worker (Opus) plus the user | ~15 min worker, user time unmeasured |
| S1 | Schema, validator, jsonify, build, and core logic | `docs/PACK_SCHEMA.md`, `tools/validate_pack.py`, `tools/jsonify_pack.py`, `build.sh`, `engine/core.js`, `tests/script_checks.js`, `tests/validate_pack_script_checks.js`, flagoff strip | checks 1–10 pass, and engine, characters and flag-off checks stay green | none | Opus | ~25 min (B1 + B2) |
| S2 | Packbuilder `write_script`, plus the ko, ru, fa, ja `SCRIPT` tables, then rebuild the 4 packs and recapture the ja goldens | `tools/packbuilder/core/pipeline.py`, `langs/{ko,ru,fa,ja}.py`, packbuilder tests, sibling `pack/` | check 12, validator clean on 4 packs, unit counts per §3, and a stat list of fallback `ex` | S1 (schema), S0 (`say`) | Opus, since the tables need script expertise. Split per language if it runs long. | ~30 min (B3 + B7, ×2 for 4 hand tables) |
| S3 | App: choice card, Today stage and one more set, 8 item renderers, teach card with forms, compose and variant rows, Script tab, Progress chips, existing-learner notice | `engine/app.html`, `tests/script_app_checks.js` | check 11, the [23] boot goldens unchanged flag-off, and 390px layout by fake-DOM width proxy | S1, S2 (real data for dev) | Opus | ~25 min (B4 + B5) |
| S4 | Opus review of S1–S3, then the browser walk above | none (read-only) | every walk row ticked or filed | S3 | Opus reviewer plus browser worker | ~20 min (B8) |

**Parallelism.** S0 and S1 run together. S2 starts once S1's schema lands. S3 runs after S1, alongside S2 on synthetic fixtures, and switches to real packs once S2 is done. Every brief carries the test gate: `node tests/engine_checks.js`, `characters_checks.js`, `script_checks.js`, `flagoff_snapshot.js`, and `validate_pack.py` on every pack it touches. Expected wall time is about 1.5–2 h plus the user's ear-check. That is extrapolated from the B timings above, not measured for this work.

## 7. Decisions

All five were decided 2026-09-26, each as recommended below, and S1 builds on them:
1. Existing learners default to the primer skipped, with a one-time notice.
2. ja: hiragana then katakana, both before A1, each skippable (option a).
3. fa ships text-only now, with the per-unit `audio` hook for Piper later.
4. Up to 2 script sets per session, the second behind "One more set".
5. A1 starts once every symbol is taught; mastery continues in Review.

The questions as they were put:

1. **Existing learners.** Should a stored progress with word records default to primer skipped, with a one-time notice? Otherwise every current ru, ko, fa and ja learner is sent to the primer before their next word set. **Recommend:** skipped, with the notice.
2. **ja katakana placement.** A1 needs katakana from word 229 (10 A1 words, 52 in A2). Stages can only sit between levels, so the options are:
   - (a) Hiragana then katakana, both before A1. That is about 12 sessions at 2 sets per session.
   - (b) Hiragana before A1 and katakana after A1. The 10 A1 loanwords are then shown in unread katakana.
   - (c) Build mid-level stage insertion ("after A1 set 20"), which costs an extra core change.

   **Recommend (a).** pronFirst already makes kana the only thing a ja learner reads, and each kana stage can be skipped separately through the chips.
3. **Persian with no voice.** Ship fa's primer text-only now, with the `audio` hook, and render symbols and example words with Piper later under the existing TODO item? The alternative is to hold fa's primer until the audio exists. **Recommend:** ship text-only. symSound, formMatch, formFind and wordRead need no audio.
4. **Sets per session.** Should Today teach up to 2 script sets per session while the primer runs, through the "One more set" button? That gives ko 7 sets in about 4 days and ja about 12 days. The alternative is 1 set, as with words. **Recommend:** 2. No words compete for the slot, and the primer stays about 15 minutes a day.
5. **When does A1 start?** The design moves on once every symbol is taught, and mastery continues in Review, mixed with A1 words. The alternative waits until every symbol is mastered, at streak ≥ 3. **Recommend:** taught. Waiting on mastery can stall a learner for days on ㅐ/ㅔ or ذ/ز/ض/ظ, while real words are the best practice. The typed `symType` stays test-only in either case.
