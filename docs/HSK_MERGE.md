# HSK merge: design and plan

Design, 2026-09-25; TODO.md "Large items" 1.
hsk rollback point: `main` **3aeecc4**. Engine 510ac3e was extracted from b5b5f24-era hsk minus the characters subsystem, so every hsk change from a7e7f86 on is a delta. hsk `data/` is unchanged since, so `packs/zh` ids match a rebuild.

## 1. Delta inventory

hsk `core` = `src/pinyin_core.js`, `app` = `src/pinyin_app.html`.

| # | hsk behaviour | hsk file:line | engine counterpart | tag |
|---|---|---|---|---|
| 1 | Character records `c` `{r,w,s}` | core 408-418; app 316-329 | none | PORT |
| 2 | Tier thresholds: mastered s≥3, bare s≥6 | core 585-604 | none | PORT (pack params) |
| 3 | Mixed-script sentences (pinyin, ruby, bare by streak) | core 606-611; app 617-638 | none | PORT (needs per-token readings, §2.3) |
| 4 | "Mix known characters" toggle | app 1333, 1350 | none | PORT |
| 5 | Character stages in the path (字 after HSK3, 字4 after HSK4), sets of 10 | core 657-697; app 303-313, 823-826 | `pathStrip` app 686 (levels only) | PORT |
| 6 | Learn teaches the current stage's set: cards, 10 pickChar + 10 readChar | app 925-945, 971-984 | `todayStep` s===1, app 736 | PORT |
| 7 | Stage and unified-mode snapshotted at "Start today" | app 872-877 | app 717 | PORT-UNCONDITIONAL (no visible change without characters) |
| 8 | Items readChar, charSound, pickChar, recallChar; homophone-free `charOpts` | core 628-655, 737; app 709-758 | `meaningOpts`, `wordOpts`, `samePron` core 47-124 | PORT |
| 9 | One-time choice card (start characters / skip to HSK 4) | core 705-715; app 848-871 | none | PORT |
| 10 | Learning-order switch in Progress (reversible) | app 1334-1356 | none | PORT |
| 11 | `charsStarted` gate for every character surface | core 699-704 | none | PORT |
| 12 | Unified Review: 20 weakest across words and characters, one score | core 717-735; app 905-915 | `buildReviewPlan` core 825 | PORT-UNCONDITIONAL (inert without a character pool) |
| 13 | Unified Recall: words plus recallChar | app 951-958 | `buildRecallPlan` core 835 | PORT-UNCONDITIONAL (inert without a character pool) |
| 14 | Test → Characters N | core 614-626; app 1192, 1206-1216 | Test tab app 1071 | PORT |
| 15 | Progress rows per character stage | app 1318-1323 | `progressRender` app 1154 | PORT |
| 16 | Fields `c`, `mixChars`, `charsAfterHsk4`, `charsChoiceSeen`, additive migration | core 376-452; app 1405-1413 | `validateProgShape`/`normalizeProg` core 677-710 | PORT (as `prog.chars`, §2.5) |
| 17 | Import keeps `mixChars` when absent; Reset clears characters | app 1377-1391 | `applyImport` core 751; reset app 1215 | PORT |
| 18 | Reveal taps resolve `data-vidx` | app 596-608 | one delegated `#panel` listener, app 530 | ALREADY-IN-ENGINE (extend that listener) |
| 19 | Samsung Internet audio notice | app 363-372, 853 | `isSamsungBrowser` core 902; `samsungNoticeHTML` app 324, 707 | ALREADY-IN-ENGINE (unconditional) |
| 20 | Teach-row layout: long gloss overlapped pinyin | app 127-131 | `.rowset .info` column layout, app 120-126 | ALREADY-IN-ENGINE (other CSS) |
| 21 | Double speak on example taps | app 450-452, 596-598 | single delegated listener, app 530 (engine 59d438e) | ALREADY-IN-ENGINE |
| 22 | v2.2 separate Characters step, unlock hint, 10 new / 16 drilled per day | a7e7f86, b5b5f24 | none | DROP: hsk itself replaced it in 263768b |
| 23 | `hsk_characters.html` (radical data) | gitignored | none | DROP: pre-fork, unpublished |

Totals: 14 PORT, 3 PORT-UNCONDITIONAL, 4 ALREADY-IN-ENGINE, 2 DROP.

## 2. Characters stage (zh and ja)

### 2.1 Unit and UI placement
A **character unit** is the written form of a known word. hsk teaches whole words (我们, not 们) and has no decomposition data. zh units are all 1193 words. ja units are words whose `w` contains kanji, read by their kana `pron`. Single glyphs (食 linked to 食べる, 食事) fit later through a multi-id `words` list.

Characters stay a **stage in the path**, as in hsk. A stage reuses the one daily new-material slot (Learn), so the load stays at 10 new items. A tab would add a second stream, crowd the tab bar at 390px, and collide with item 1c's Script tab.

### 2.2 pack.json
`characters` is an optional object. When it is absent, no character code path runs.

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
- Each stage sits after word level `after` and covers `levels`. Later stages append their last level id to `label` (字4).
- Deferred order (`prog.chars.defer`) merges all stages into one after the last level.
- ja: `stages:[{after:"A2",levels:["A1","A2"]},{after:"B1",levels:["B1"]}]`, label 漢字, `learnKinds:["charSound","charRead"]` (reading plus meaning).
- `validate_pack.py` checks stages, level ids and thresholds.

### 2.3 Data files
`pack/characters.json` holds the units, in teaching order within each level:

| field | type | meaning |
|---|---|---|
| `id` | `c0001`… | Progress key. Never renumber. |
| `t` | string | Written form, shown large. |
| `words` | `[wordId]`, ≥1 | Linked words. `words[0]` supplies the gloss and the audio. |
| `lv` | levelId | Decides which stage the unit belongs to. |
| `reading` | string | Answer for charSound and the ruby text. Defaults to the pron of `words[0]`. |

Optional `sentences[].ruby` is `[[start, end, reading, wordId]]` in UTF-16 offsets, sorted, non-overlapping. A token's tier follows the unit whose `words[0]` is `wordId`. zh builds it from hsk's space-aligned pinyin tokens, with compounds like 这个 mapped to their base word. ja builds it from the per-token readings `langs/ja.py` `kana_line` (~2085, 2336) already computes but flattens into `pron`; nothing per-token is emitted today.

`jsonify_pack.py` writes `characters.js` only when `characters.json` exists. `build.sh` inlines it when present and emits nothing otherwise.

### 2.4 Rules, all in core.js and DOM-free
- `stagePath(pack, words, chars, prog)` inserts character stages among word stages. `nextStage` is the first incomplete one.
- `nextCharSet` chunks a stage's units in level order, then file order. A set is taught once all its units have records.
- `charsStarted`, `showCharChoice`, `charTier` and `charReviewScore` port hsk's rules. The choice needs a later word level still incomplete.
- Without `pack.characters`, `stagePath` returns today's level stages exactly.

### 2.5 Drill items
| kind | stimulus | answer options |
|---|---|---|
| charRead | `t` only, no reading, no audio | 4 meanings (`meaningOpts`) |
| charSound | `t` | 4 readings, never a homophone, same length first |
| charPick | audio plus reading | 4 written forms (`charOpts`) |
| charRecall | meaning | 4 written forms |

Scoring writes `prog.chars.c` only. charSound drills `pron`, breaking the engine's pron-is-display-only rule, but only in character items.

### 2.6 Progress
`prog.chars = {v:1, c:{[unitId]:{r,w,s}}, defer:false, choiceSeen:false, mix:true}`, added by `normalizeProg` only when `pack.characters` exists and validated whenever present. Top-level `v` stays 1: the current engine treats an unknown `v` as invalid, so a bump would reset learners on any rollback, while an unknown `chars` key survives untouched.

### 2.7 Today and the rest of the UI
- **Review:** up to 5 provisional words, then the weakest words and units under one score: 20 items once started, 15 before. Words keep the ≥40% production mix.
- **Learn:** the snapshotted stage's next set, word or unit. A unit set gets teach cards, then two `learnKinds` items per unit.
- **Recall:** 8 weakest-first from words plus charRecall units (hsk picks at random; question 5).
- **Listen, Sentences:** unchanged apart from tiers.
- The choice card replaces Start today until answered, and the strip shows every stage. Test gains Characters N. Progress gains stage rows, order chips and the mix chip.
- **Tiers**, with mix on and characters started: sentences with `ruby` render `<ruby>t<rt>reading</rt></ruby>` below `bare` and plain `t` at or above it, replacing the pron line. `showPron` off hides all ruby. Gap items are unchanged.

## 3. Learning order, unified Review and Recall, Samsung
- **Learning order:** pack-gated, since it only exists with characters. `prog.chars.defer` replaces `charsAfterHsk4`. Flipping it re-derives the path only, and a running session keeps its snapshot.
- **Unified Review and Recall:** engine default. The plan builders take an optional unit pool, and with none their output is unchanged. One ranking is simpler than per-kind steps, and hsk's clamp prevents starvation.
- **Samsung notice:** already in the engine, unconditional (row 19).

## 4. Progress migration `hsk_pinyin` → `vocab_zh`
`pack_from_hsk.py` emits `packs/zh/legacy.json` (`const LEGACY`): `w` hanzi→word id (1193, unique), `s` sentence text→id (882, unique), `c` hanzi→unit id. `pack.legacy = {"key":"hsk_pinyin","format":"hsk-v2"}`. Pure core `migrateLegacy(raw, LEGACY, pack)` returns `{prog, unmapped}`.

| hsk field | vocab_zh |
|---|---|
| `v` (1 or 2) | `v:1` |
| `w[hanzi]` `{r,w,s,prov,d}` | `w[wordId]`, fields verbatim |
| `s[zh]` `{r,w,s}` | `s[sentId]` |
| `sets{1..4}` | `sets{"1".."4"}` |
| `lessons`, `sessions`, `theme`, `placedOnce`, `soundsOpened` | same |
| `c[hanzi]` | `chars.c[unitId]` |
| `mixChars`, `charsAfterHsk4`, `charsChoiceSeen` | `chars.mix`, `chars.defer`, `chars.choiceSeen` |
| `showChars`, `dismissedSoundsHint` | dropped. `showPron` gets the pack default (see question 1). |

- **Once:** at boot, only if `vocab_zh` is absent and `hsk_pinyin` validates. It writes `vocab_zh` plus `vocab_zh_legacy_backup` (raw copy) and never touches `hsk_pinyin`. A second boot sees `vocab_zh` and skips. Progress import accepts hsk exports through the same function.
- **Unmapped keys** are listed and kept in the backup. Acceptance requires none.
- **Proof:** `tools/diff_hsk_migration.js <snapshot.json>` migrates a real Progress → Export file, reverse-maps it and diffs every record and flag. It also compares derived views, hsk `pinyin_core.js` on the old record against `core.js` on the new: per-level learned and mastered, current stage, stage fractions, choice-card state, sentence availability (hsk's rule re-stated over `data/hsk_sentences.js`, differing ids listed). The diff must be empty apart from the accepted deviations in §8 (s0823).

## 5. Parity checklist and rollback
Walk `dist/zh.html`, then the hsk branch build, at 390, 360 and desktop, light and dark. Walked 2026-09-26: every row passed except the two switch-time rows; deviations it found are in §8 ("hsk parity walk").

- [ ] Fresh load and offline reload: PASS on dist/zh.html (walk 2026-09-26). The old `hsk_pinyin.html` URL (question 4): switch-time, verified on the hsk branch build.
- [x] The migration diff is empty on the real snapshot (user export of 2026-09-25, .cache/hsk-switch/hsk_pinyin.real.json: diff PASS; walk 2026-09-26: boot migrates, Today shows Session 1, 0 learned, HSK 1 set 1, identical to hsk). After boot, Today shows the same session number, learned count, strip fractions and current stage as hsk (seeds A–E all identical).
- [x] Seeds A–E from hsk `PINYIN_SPEC.md` "Browser-verify seeds", migrated:
  - A shows no character surface.
  - B shows the choice card. Start teaches 10 cards and a 20-item drill and records 10 units. Skip teaches HSK 4 set 1, and 字 moves after HSK 4.
  - C gives a 20-item Review with both kinds and charRecall in Recall, and Characters N runs. The mix chip changes the sentence tiers.
  - D is a v1 record that migrates.
  - E puts the deferred stage after HSK 4.
- [x] The learning-order chips flip the path, and a running session is unaffected.
- [x] Today runs all 5 steps before characters: Review 15, Learn, Listen 12, Recall 8 and Sentences 8.
- [x] Placement works from the hint and on retake, and a placement past HSK 3 lands on the choice card.
- [x] Sounds: lessons open, and lesson progress is kept.
- [x] Words: search, the set pager and "Drill this set".
- [x] Test: Placement, Listen, Recall, Sentences and Characters.
- [x] Progress: export, import of an old hsk export, and reset.
- [x] Each tap plays exactly one utterance.
- [x] The Samsung notice shows with a spoofed user agent, and the no-voice notice shows with voices stubbed out.
- [x] No overflow at 360px.
- [x] The user has signed off the known losses: questions 1 and 2.

**Rollback:** reset hsk `main` to 3aeecc4 and republish. `hsk_pinyin` is never modified, so the old build resumes at the pre-switch state; post-switch progress stays in `vocab_zh`.

## 6. Implementation briefs
Every brief carries the test gate: `node tests/engine_checks.js`, `node tests/characters_checks.js` and `python3 tools/validate_pack.py packs/zh` all pass, and the flag-off snapshot check passes.

**Flag-off proof.** Literal `dist` bytes must change, since engine code is inlined and `sw.js` carries the build id. The proof is instead:
1. Flag-off pack sources and generated `.js` are unchanged (`git diff` empty).
2. `defaultProg`, `normalizeProg`, `stagePath` and the plan builders deep-equal B0 goldens under a seeded random generator.
3. The [23] fake-DOM boot, seeded, renders Today, Words, Test, Progress, Read and the first item of every Today step for 3 progress seeds, plus the saved progress string. All must be byte-identical to goldens captured on the pre-merge engine.

Flag-off packs: zh with `characters` stripped, the synthetic packs, and each sibling repo's `pack/` when present.

| id | brief | files | tests added | depends | model |
|---|---|---|---|---|---|
| B0 | Flag-off golden harness, captured on the unmodified engine | `tests/flagoff_snapshot.js`, `tests/golden/` | the proof above | none | Sonnet |
| B1 | Schema and tooling: `characters` block, `characters.json`, `sentences[].ruby`, legacy file; validator, jsonify and build.sh; dev loader | `docs/PACK_SCHEMA.md`, `tools/validate_pack.py`, `tools/jsonify_pack.py`, `build.sh`, app.html loader lines | validator cases for bad stages, dangling ids and overlapping ruby; build with and without `characters.js` | B0 | Sonnet |
| B2 | Core logic (§2.4–2.6, 3): stages, sets, gate, choice, tiers, options, unified plans, `prog.chars` | `engine/core.js` | new `tests/characters_checks.js`: hsk checks 20–31 ported onto a synthetic zh-like and ja-like pack, plus the unified plans equal the current output when there is no pool | B0 | Opus |
| B3 | zh data: `pack_from_hsk.py` emits `characters.json`, `ruby`, `pack.characters`, `legacy.json`; rebuild `packs/zh` | `tools/pack_from_hsk.py`, `packs/zh/*` | determinism by running twice; 1193 units; ruby covers every sentence token | B1 | Sonnet |
| B4 | App part 1: strip, Learn per stage, teach cards, 4 item renderers, choice card, snapshot, unified Review and Recall wiring | `engine/app.html` | [23]-style boot: seed B shows the choice card, seed C builds a 20-item Review with units | B2, B3 | Opus |
| B5 | App part 2: Test Characters, Progress rows, order and mix chips, import and reset, ruby tier rendering | `engine/app.html` | boot checks for the order flip, mix off and deferred path | B4 | Opus |
| B6 | Migration: `migrateLegacy`, boot hook, import path, `tools/diff_hsk_migration.js` | `engine/core.js` (a separate section), `engine/app.html` boot, a new tool | seeds A–E and v1, v2 and v2.2 records; idempotence; unmapped list | B2, B3. The app hook goes after B5. | Opus |
| B7 | ja consumer: emit per-token `ruby` and kanji-word `characters.json`; ja `pack.characters` | `tools/packbuilder/langs/ja.py`, packbuilder writer, packbuilder tests | ruby offsets match `t`, readings are kana, units contain kanji | B1 | Opus |
| B8 | Opus review of B2–B6, then a browser walk of `dist/zh.html` and the ja build | none (read-only) | the parity list excluding hsk-only rows | B5, B6 | Opus, plus a browser worker |

**Parallel:** B0 first. Then B1 and B2 together; B3 and B7 once B1 lands. B4 then B5 serially (same file). B6 core alongside B4, its app hook after B5. Each brief touches 1–3 files.

**Question 1 gates B4.** For hsk parity, add brief BP (`pack.pronFirst`: the reading replaces `w` until a unit reaches `bare`, about half a day of Opus) between B4 and B5. The hsk switch (TODO item d) runs last, on an hsk branch, against §5.

## 7. Open questions
1. **Pinyin-first vs word-first.** hsk shows pinyin only and hides characters by default, and its characters stage assumes that. The engine is word-first, so zh learners see hanzi from day one, and the stage becomes "read without pinyin". The switch would change hsk's core pedagogy, and the parity list cannot pass without a decision. The options are to accept word-first, or to build BP.
2. **Other pre-fork losses** recorded in TODO "Behaviour differences": tone colouring, typed pinyin and Extras, the pinyin chart, per-word tap in sentences, and `showChars`. Are these accepted for the switch?
3. **ja unlock point.** The TODO says "after A1/A2". The design assumes the first stage comes after A2. Kanji-word units are used because single-glyph units would need KANJIDIC-type data and its licence.
4. **The `hsk_pinyin.html` URL** after the switch. `build.sh` writes one `sw.js` per page name, so the options are a redirect stub or a single page.
5. **Recall order.** The design uses the engine's weakest-first, where hsk picks at random in unified mode. The random choice was a brief artefact, not a finding.
6. **Real snapshot source.** The user needs to export `hsk_pinyin` from the device they actually use.
7. **The brief's "10 new / 16 drilled".** That is v2.2 (b5b5f24). hsk HEAD replaced it with sets of 10 and a 20-item drill, and this design follows HEAD.


## 8. Decisions taken at implementation (2026-09-25)
- B6: the migration section in core.js is `migrateLegacy(pack, legacyMap, oldRecord)` (not `migrateLegacy(raw, LEGACY, pack)`), the backup key is `hsk_pinyin.bak` (not `vocab_zh_legacy_backup`); §4 is superseded on those two points. The hsk record's own field names (e.g. `charsAfterHsk4`) must appear in that section, so engine_checks [10] exempts only the lines between core.js's "legacy migration" header and its "export" header, capped at 150 lines and asserted by a check. Alternative considered and deferred: a `fields` rename map in `pack.legacy` keeping the engine fully generic; revisit only if a second legacy consumer appears.
- B4 proceeds word-first (open question 1); `pack.pronFirst` remains a hook for BP.
- B7: ruby ranges cover only the kanji part of a token; counter units keep 〜 in `t` but not in `reading`; one unit per word, so duplicate headwords give duplicate `t` (方, 〜分, 大変, 結構) — B8 review to decide whether to merge them.

- **Open question 1 answered (user 2026-09-25 16:10): PRONUNCIATION-FIRST for every logographic pack.** "Never start with pictograph letters; user experience and ease of learning is the priority, coding easiness is not." zh: a new word is shown as pinyin (hanzi hidden) until its unit reaches the mastered tier in the characters stage; ja: the same with the kana reading; kana itself is taught by the script primer (TODO 1c). Implement as brief BP (`pack.pronFirst`, B2 left the hook in sentenceTokenTier/charTier), on by default for zh and ja packs, off for every other pack (flag-off goldens byte-identical).
- **Open question 2 answered in the same spirit:** restore the extraction losses that aid learning, pack-gated, after BP (brief BP2): per-word tap-to-hear/gloss inside sentences, tone colouring of pinyin, typed-pinyin production for zh (hsk's numbered-pinyin normaliser), and the pinyin chart if the Sounds lessons do not already cover it. Drop only `showChars` (replaced by the tiers).
- B8 Characters test (hsk parity): pool = the 20 weakest recorded units, topped up with learned words' unrecorded units via core `newCharUnits` (level order, then file order); kinds drawn from `pack.characters.testKinds`, default charRead 40 / charSound 30 / charPick 30 as hsk; core `charTestPlan`. The button shows once characters have started (`charsStarted`), not only once a unit has a record. Deviation kept: hsk gates on "unlocked", which also covers a deferred learner who has not started.
- B8 unit ids follow word ids: both builders (`pack_from_hsk.py`, `langs/ja.py`) emit `"c" + wordId[1:]` (w0416 → c0416), and a unit id is never renumbered. zh ids were already identical (one unit per word, in word order), so `characters.json` and `legacy.json` did not change; ja ids now have gaps where kana-only words have no unit.
- B8 Today Review line: the Review plan is built at Today render with the snapshot, and Start today runs exactly that plan. The line says "words and <label>" only when that plan holds a unit, and "words" when characters have started but it holds none (first character day, or every recorded unit ranked out).
- B8 ruby at the bare tier keeps the `<rt>` with its reading, `visibility:hidden` (`<ruby class="bare">`), so a token's width never changes across tiers and a line wraps the same with or without visible readings (browser walk at 390px: 生活里总是会遇到一些困难，这很正常。 was 2 lines with ruby, 1 line bare). The fixed tall line box stays. Pron hidden or mix off still renders the plain path. Checked by a width proxy over all 882 zh sentences; a real-browser recheck at 390px is still owed.
- B8 boot migration failure: when a legacy record exists (or cannot be read) but is not imported (legacy read error, not convertible, backup unreadable or unwritable), Today shows why and the session is read-only, so this pack's key stays empty and a later boot tries again. "Start without it" lifts the hold and saves from then on; the old record is never touched.
- B8 data: `pack_from_hsk.py` `EN_OVERRIDES` (sentence text → English) fixes upstream placeholders; s0554 was the only `PLACEHOLDER_*` in packs/zh. The build fails if a placeholder survives or an override matches no sentence.
- **BP done (2026-09-25):** `pack.pronFirst` (docs/PACK_SCHEMA.md "pronFirst"), true for zh (`pack_from_hsk.py`) and for ja whenever the packbuilder writes `characters` (`LanguageSpec.pron_first`, `pipeline.characters_pack_fields`). The threshold is the mastered tier, per the 16:10 decision (the §6 note's "until bare" is superseded). Mix off under pronFirst means reading-only sentences, as hsk's mix off did. The written form still appears in these places: the characters stage (by design); mastered words; the stage label (字); and zh passage titles, questions, options and unlinked names (王明, 上海: 223 of 8656 passage characters), which have no reading data. The Sounds lessons show pack-authored text as is. A later zh passage-hooks round could add `ruby` to passages and readings to titles and questions; passages with `ruby` already render by tier.
- **BP2 done (2026-09-26, branch hsk-bp2):** the extraction losses that aid learning are restored, pack-gated (docs/PACK_SCHEMA.md "Pronunciation aids"; checks in tests/pron_aids_checks.js). (1) Word taps inside sentences: every ruby token is a tap that shows the Read-tab popover and speaks the word; the sentence is heard from its own speaker button; never in stimuli or answer options; no progress effect. (2) `pack.tones: "pinyin"`: every displayed reading is coloured per syllable (hsk's colours, light and dark); the syllable split is ported from hsk (`markSyllable`, `splitSyllable`) and checked against every zh pron, ruby reading and unit reading. (3) `pack.typing: "pron"`: the production slot alternating with recall types the pinyin, with hsk's numbered rules and a "tones missing" partial; no typed cloze; placement untouched. (4) The Sounds lessons already cover every initial, final and tone, so the chart is a collapsed Reference card built from the lesson rows (`pack.soundsReference`), not a new file. (5) `showChars` is gone except the migration's intentional drop list and historical docs. (6) Phrase-span popovers head with the tapped surface and its reading. (7) Pinyin-first passage spans longer than their word (146 of 6017) no longer drop syllables: they compose the word's pron with single-character unit readings, keeping any unread character written; a reading after a sentence-internal . ! ? is capitalised. Engine guard [10] now allows the generic word "tone" (it still bans pinyin/cjk/hsk/hanzi/kanji), since `pack.tones` is a pack-gated feature. Follow-on after merging main cc4dca0 (zh passage ruby): passage titles (list, Today read hint, heading, results), questions and mc options render their `titleRuby`/`questions[].ruby`/`optionsRuby` reading-first under pronFirst (no taps, no show-written inside buttons), so the Read tab shows no hanzi below mastered (checked over all 60 passages); every passage sentence now has ruby, so 越来越/一下 read from it as the builder wrote it (一下 yīxià, no sandhi) and composeSpanReading is only the fallback for a sentence without ruby. Residuals: readings follow the builder, which writes 一下 as yīxià (citation), not the spoken yíxià; typed pinyin accepts a sandhi-written pron (一点儿 yìdiǎnr) only as written; glosses that quote pinyin ("also pr. [shuí]") and lesson item text stay uncoloured; on a word-first characters pack, taps appear only once ruby renders (characters started, mix on); the Reference card lists one example syllable per lesson row (66 cells), not a full initial x final grid; browser verification at 390px is owed.
- Unchanged deviations from hsk, confirmed at B8: Recall is weakest-first (hsk picks at random; question 5). Sentence tokens below mastered show ruby, not pron-only, on a word-first pack (`pronFirst` would give the pron tier). The mix chip shows once characters have started (hsk shows it once unlocked); before that it changes nothing.
- **hsk parity walk (2026-09-26), accepted deviations:**
  - Placement retake never moves the learner back. "Retaking can only move you forward" is an engine-wide rule across languages; hsk reset to HSK 1 set 1 after an all-wrong retake.
  - Seed E sentence availability is 617 vs hsk's 618. `pack_from_hsk.py` merges 分+之 into the HSK 4 word 分之, so s0823 needs 分之 learned here and only 分 and 之 in hsk. `tools/diff_hsk_migration.js` did not compare sentence availability although §4 said so; it now does (hsk's rule over `data/hsk_sentences.js`, differing ids listed) and accepts only s0823 (migration_checks "walk seed E").
  - Words search folds tones and matches hanzi, which hsk did not. Kept: strictly more useful.
  - Progress showed the 字 stage rows ("字 0/595 taught", "字4") while characters were still locked; hsk hides them until characters start. Fixed: the rows show once `charsStarted` (hsk's own gate), checked in characters_app_checks [8]. The learning-order chips are unchanged.
