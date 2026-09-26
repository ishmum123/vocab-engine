# Generated audio (Piper)

Status: phase 1 (samples, design) done 2026-09-26; phase 2 (engine, validator, service worker, builder,
tests) implemented on branch fa-audio-2. No pack ships clips yet: phase 3 renders and publishes Persian.
Why: Persian has no TTS voice on Apple, Windows, Google TTS or Android (verified 2026-09-26), so the
speaker is hidden and Listen items fall back to reading. Indonesian (no Apple voice) and Urdu reuse this.

## Phase 1 findings (Persian)

Tooling: `piper-tts` 1.8.0 (pip, native arm64 wheel, onnxruntime 1.30.0; no Docker needed), Python 3.12.
Phonemes come from the espeak-ng `fa` voice bundled inside piper-tts (no system espeak).
Samples, scripts and measurements: `.cache/fa-audio/` (`samples/index.html`, `samples/results.json`).

Voices on rhasspy/piper-voices (all `medium`, 22.05 kHz, ~63 MB .onnx each):

| voice | licence (MODEL_CARD) | ASR sentence CER | ASR word CER (plain / slow) | projected pack MB |
|---|---|---|---|---|
| ganji_adabi | CC0 (tts.datacula.com) | 0.14 | 0.24 / 0.31 | 43.5 |
| ganji | CC0 (tts.datacula.com) | 0.21 | 0.27 / 0.31 | 39.2 |
| gyro | unstated ("See URL", github.com/gyroing) | 0.20 | 0.42 / 0.54 | 30.3 |
| amir | CC0 (datacula) | 0.33 | 0.84 / 0.52 | 33.5 |
| reza_ibrahim | CC0 (Quran-recitation datasets) | 0.26 | 0.56 / 0.59 | 44.0 |

CER = character error rate of a faster-whisper `small` round-trip on 8 sentences and 8 words per voice.
Whisper-small is weak on Persian (it colloquialises: خانه → خونه) and single words have no context, so this
ranks voices roughly; the user's ear decides. Projection = measured bytes/char × pack text (90,828 sentence
chars, 29,474 passage chars) + measured slow-word/primer clip sizes × counts.

Pronunciation (espeak-ng `fa` + unvocalised input):
- Common words get the right vowels: کتاب ketâb, گرفتن gereftan, گل gol, مرد mard, کشتی kashti, digits 8/۸ → hašt.
- **Ezafe is never voiced**: پارک بزرگ شهر → pârk bozorg shahr (should be pârk-e bozorg-e shahr). Marking it with
  kasre fixes it: پارکِ بزرگِ شهر → pârke bozorge shahr. This is the main systematic error in sentences.
- **Stress**: espeak often stresses the first syllable (kˈetɑb, tˈasmim, dˈustam); Persian nouns stress the last.
  A kasre on the first vowel moves it (کِتاب → ketˈɑb). The VITS voice partly smooths this.
- Harakat can hurt: خانِه → xɑneh (final h voiced). Add marks only where they fix a known error.
- Feeding the pack `pron` romanisation is unusable (English letter rules: gereftan → dʒɛɹɛftən).
- Isolated syllables/words are clipped (amir تَ = 0.12 s). Words and primer carriers therefore render with
  `length_scale` 1.25 plus 150 ms lead and 250 ms tail silence ("slow" column on the samples page).

Encoding: Opus via ffmpeg libopus, 24 kbps mono, resampled 22.05 → 24 kHz, `-application voip`.
Measured ~3.1–3.4 KB per second of speech. Timing on this Mac (M-series, one process): synth 0.08–0.11 s per
sentence, 0.15–0.18 s per passage sentence, 0.02–0.03 s per word; ffmpeg encode 0.058 s per file.

## Pack schema

| where | field | status | semantics |
|---|---|---|---|
| `words[]` | `audio` | **new** | URL of a recorded clip of `w`. Same rules as `sentences[].audio`: plays instead of TTS and plays with no voice. |
| `sentences[]` | `audio` | exists | Unchanged. Tatoeba human recordings (absolute URLs) take precedence; the builder never overwrites them. |
| `passages[].sentences[]` | `audio` | **new in schema/validator** | The engine already plays it (Read tab `saySentence`), but PACK_SCHEMA and `validate_pack.py` do not list it. Add both. |
| `script.units[]` | `audio` | exists | Unchanged: beats `say`, plays with `tts: false`. |
| `pack.json` | `audio` | **new, optional** | `{voice, version}` so the engine can tell "this pack ships audio" without scanning; see Builder. |

Validator: `audio` must be a non-empty string wherever present; `packbuilder audio --check` (below) checks the
files exist. Relative URLs resolve against the built page, as today.

File layout in the language repo (beside `index.html`, so relative URLs work on Pages and locally):

```
audio/manifest.json
audio/w/<wordId>.<sha8>.opus        audio/s/<sentenceId>.<sha8>.opus
audio/p/<passageId>-<n>.<sha8>.opus  (n = 0-based sentence index)
audio/x/<unitId>.<sha8>.opus        (script primer carriers)
```

File names are content-addressed: `<sha8>` is the first 8 hex digits of the clip's key (below). The
service worker caches per URL, so a re-rendered clip (an override fix, a text edit) must get a new URL,
or listeners who played the old one keep hearing it from their cache. The builder deletes the superseded
file. Bumping `version` is only for voice or codec changes.

`audio/manifest.json`:

```json
{ "voice": "fa_IR-ganji_adabi-medium", "engine": "piper-tts 1.8.0", "version": 1,
  "codec": "opus", "bitrate": "24k", "rate": 24000, "count": 5610,
  "generated": "2026-10-01T12:00:00Z", "licence": "CC0 (voice dataset tts.datacula.com)",
  "files": { "w/w0001": "w/w0001.1a2b3c4d.opus", "...": "..." } }
```

`files` maps item id (`<kind>/<id>`) to its clip file, and is the list of files the builder owns.

Cost of explicit per-item URLs: ~30 bytes × 5610 items ≈ 170 KB raw in the built page (1.5 MB today),
far less gzipped. Explicit fields keep partial coverage and Tatoeba mixing trivial.

## Engine

Helpers (app.html, speech section):

```js
const wordAudio = VC.wordAudio;                    // core.js: a word's non-empty audio string, else undefined
const sayWord = (w, btn) => speak(w.w, btn, wordAudio(w));
const canHearWord = w => hasSpeech || !!wordAudio(w);   // mirrors canHearSentence
const PACK_AUDIO = VC.packAudio(PACK);             // pack.json audio {voice: non-empty, ...}
```

Fallback order in `speak(text, btn, url)`: the clip; if it fails to load (a 404, or offline and not
cached), TTS of the same text when a voice is usable (script units: their `say` carrier when the script is
voiced); else a short toast. Offline, a same-site clip says "Offline: this recording isn't saved on this
device yet."; a cross-origin clip (Tatoeba, never cached by sw.js) says "Recording needs a connection.";
online, "This recording couldn't be played.". An interrupted clip (AbortError, a later `speak` replaced
it) and a blocked autoplay (NotAllowedError) are not failures; a generation counter drops failures and
late ends of replaced clips, so a reused button keeps its "speaking" state. Packs with Tatoeba clips gain
this fallback too (before, a failed clip was silent).

Call-site audit: every place that speaks a pack word, with its verdict (all migrated; tests/audio_checks.js).

| site | before | after |
|---|---|---|
| panel `data-wid` tap (reveal blocks, char teach heads) | `say(w.w)` | `sayWord(w)` |
| `revealBlock` | tappable if `hasSpeech` | `canHearWord(entry)` |
| `hearItem` (Listen: Today, Test, drills) | read + notice if `!hasSpeech` | `canHearWord` gate, `sayWord` |
| `readItem` mount, `recallItem` / `typeItem` reveal | `say(entry.w)` | `sayWord(entry)` |
| `pronTypeItem` replay + reveal | `hasSpeech` gate, `speak(entry.w)` | `canHearWord`, `sayWord` |
| `tokTap` popover | `say(head ? surface : w.w)` | `sayWord(w)`; a phrase head whose surface differs from `w.w` stays TTS |
| `vocabTeach` rows + hint | `hasSpeech` gate, `say(w.w)` | per-row `canHearWord`, `sayWord`; hint if any row hears |
| `charTeach` heads + hint, `charRevealBlock`, `sayUnit`, charPick `hear` | `hasSpeech` | `canHearWord` / `canHearUnit`, `sayWord` |
| `wordListInto` (Words tab) | `hasSpeech` gate, `say(w.w)` | `canHearWord`, `sayWord` |
| `placeVocabNext` (placement) | `asHear = hasSpeech && rand` | `canHearWord(w) && rand` (same rng use), `sayWord` |
| primer example-word tap `data-xw`, teach rows, reveal | `scriptVoice()` gate | `scriptVoice() \|\| wordAudio(w)`, `sayWord` |
| primer `wordRead` / `wordHear` items (core.js `scriptItem`) | TTS only; no voice turns wordHear into wordRead | example-word clip as `audioUrl`; wordHear kept without a voice when every example word of the unit has a clip (`exRecorded`, also in `scriptKindFor`) |
| script units (`sayUnitSound`, `unitHasSound`) | already `u.audio` | unchanged; teach hint also shows when a unit has `audio` |

Lesson `say` strings (Sounds tab, lesson items and reference card) are free text with no clip: unchanged.
Notices: `speechNotice()` and the Progress-tab warning are hidden when `PACK_AUDIO`; the Sounds-lesson
warning stays. A pack with clips but no `pack.audio` plays them and still shows the notices (validator warns).
Flag-off: with no `audio` fields every gate reduces to `hasSpeech`, so packs without audio behave as before
(flagoff goldens unchanged; `tests/flagoff_snapshot.js` strips `pack.audio`, `words[].audio` and relative
sentence `audio` so the phase 3 render is not drift; absolute Tatoeba URLs stay hashed).

Service worker (`sw.template.js`):
- install precaches the page only; `audio/*` requests in scope go to `audioResponse`: cached copy, else
  fetch the whole clip (no Range), store a 200 in `AUDIO_CACHE`, trim to `AUDIO_CAP` = 800 (oldest stored
  first; ~6 MB at Persian clip sizes). 404s pass through uncached. Offline with no copy the request fails
  and the page falls back as above.
- Range: media elements send Range (Chrome `bytes=0-`), so a Range request gets a 206 slice of the full
  cached clip (suffix ranges, 416 when unsatisfiable).
- `AUDIO_CACHE` = `ve:<scope>:audio:v<pack.audio.version>`; build.sh fills the version (0 without audio).
  `activate` keeps it across page builds and deletes other audio versions.
- **Untested until the phase 3 live check:** iOS Safari's media Range behaviour through the worker, and the
  MIME type GitHub Pages sends for `.opus`. Codec risk: caniuse lists Opus as supported on iOS Safari
  from 18.4 and "partial" on 11–18.3; which containers the partial covers is unverified. On a device
  that cannot play Ogg Opus the clip fails, and Persian (no voice) shows the hint. Phase 3 checks a real
  iPhone; if older iOS matters, add a second encoding (AAC `.m4a`) and pick per `canPlayType`.

## Builder: `python3 -m packbuilder audio --lang fa --repo <repo> [--check] [--prune] [--only w,s,p,x] [--limit N]`

Implemented in `tools/packbuilder/audio.py` (tests: `packbuilder/tests/test_audio.py`, stub synthesiser).

**Run order: `audio` runs last, after any rebuild.** `build`/`passages`/`script` (and their tests
comparing a freshly regenerated pack file to the shipped one) know nothing about recorded audio and
rewrite `words.json`/`sentences.json`/`passages.json`/`script.json` from scratch, so any of them
dropping a previously-shipped `audio` field is expected. It is not a defect in those emitters and they
should not be changed to carry a field they do not own; `packbuilder audio` re-links every wanted item
from `<repo>/audio/manifest.json` (which the other commands never touch), and since the manifest and the
`audio/*.opus` files on disk are unaffected by a words/sentences/passages/script rebuild, this recovery
is a no-op render: 0 clips synthesised, every field just relinked (proven by
`packbuilder/tests/test_audio.py::AudioBuild::test_rebuild_strip_then_audio_restores_links_with_nothing_rerendered`,
which strips every relative `audio` field the way a rebuild would and reruns `audio` alone). A
staleness comparison between a regenerated doc and its shipped file (e.g. `tools/packbuilder/tests/test_script.py`'s
`ShippedPacks.test_validator_clean_on_shipped`) must therefore strip `audio` fields from both sides before
comparing (`core/util.strip_audio`; mirrored on the JS side, for `pack.json`/`words.json`/`sentences.json`,
by `tests/flagoff_snapshot.js`'s `stripFlagOnFields`), rather than requiring the emitter to reproduce
fields only `packbuilder audio` writes.
- Config: `spec.AUDIO` in the language spec (`langs/fa.py`: voice, version, engine, licence), merged over
  defaults (Opus 24 kbps, 24 kHz, words/carriers `length_scale` 1.25 + 150/250 ms padding, sentences 1.0).
  The builder writes `pack.json` `audio: {voice, version}` **only when every wanted clip is current**
  (nothing missing or stale) and removes it otherwise, so the no-voice notices never hide over a partial
  render. `--only`/`--limit` runs are for development: they link what they render but leave `pack.audio`
  unset until a full run completes. Codec details go in the manifest only. Bump `version` for voice or
  codec changes (it re-renders everything under new names).
- Items: words `w` → `audio/w/<id>.<sha8>.opus`, sentences `t` → `audio/s/`, passage sentences `t` →
  `audio/p/<passageId>-<n>.<sha8>.opus`, script units `say` (skipping `sound: false`) → `audio/x/`. Items
  that already carry an absolute URL (Tatoeba) are never rendered and never changed.
- Ownership: the builder owns exactly the files the manifest lists. A relative URL that is not one of them
  is foreign (a hand recording): never rendered over, relinked or removed, and logged as a note. Files on
  disk that the manifest does not list are never deleted. Exception, for a lost or hand-edited manifest:
  an item's URL in the builder's own pattern for that item (`audio/<kind>/<id>.<8 hex>.opus`) whose file
  exists is adopted as owned. Its sha8 is checked against the current key: a match is current (no
  re-render), a mismatch is stale (re-rendered, old file deleted). `--check` reports such clips as
  "unrecorded" and exits 1; the next normal run rewrites the manifest.
- Overrides: `<repo>/tools/audio_say.json` = `{pack text: spoken text}`, keyed by the item's exact pack text
  (so one fix covers every item with that text). Spoken text only; pack text never changes. `--check` fails
  on stale keys (no item has that text) and notes overrides that change letters rather than only marks.
- Key = sha1(spoken text, voice, version, codec, bitrate, rate, speed, padding); its first 8 hex digits
  name the file. An item whose manifest file has the current name is skipped: reruns are idempotent
  (byte-identical repo, `generated` unchanged) and a text or override edit re-renders only that item,
  under a new name, deleting the old file.
- URLs: each wanted item links its owned clip (a stale one stays linked until re-rendered); an item with
  no clip has its builder URL removed.
  Pack JSON keeps its layout; the .js consts are regenerated (`jsonify_pack.py`).
- `--check` (writes nothing): missing, stale, orphan clips, dangling relative URLs, stale override keys; exit 1
  on any. Notes (not failures): foreign URLs, unowned files, overrides that change letters. `--prune`
  deletes owned clips of items no longer in the pack (never unowned files). `--only` limits rendering to
  kinds; `--limit N` renders at most N.
- Dependencies (`tools/packbuilder/requirements-audio.txt`): piper-tts 1.8.0, ffmpeg with libopus on PATH.
  Voice model at `<repo>/.cache/voices/<voice>.onnx` (+ `.onnx.json`), never committed.
- Smoke-tested 2026-09-26 on a copy of the Persian pack (`--limit 3`, real Piper): 3 Opus clips, URLs,
  pack.audio, manifest; validator 0 errors. `--check` on the real pack: 5610 wanted, 5610 missing.

## Ezafe override pass (Persian, phase 3)

Generator: `persian/tools/ezafe_say.py` (committed in the persian repo; needs stanza 1.14 + the fa models in
`.cache/stanza`, and piper-tts for espeak). It writes `tools/audio_say.json` for the sentences and passage
sentences; run it again after editing either file, then `packbuilder audio` re-renders only changed items.
- **Parse:** Stanza fa (UD Persian-Seraji) tokenize/mwt/pos/lemma/depparse. For each arc head→dep with deprel
  `amod`, `nmod` or `nmod:poss` where dep follows head, the word just before dep's subtree gets the ezafe.
- **Skipped:** that word not NOUN/PROPN/ADJ/DET, or a clitic split (دوستم); dep's subtree starting with
  ADP/CCONJ/SCONJ/PUNCT; indefinite -ی (word ends in ی, lemma does not: روزی, نیرویی); dep a written-apart
  suffix (اش, شان, ها, ریزی ...); the idiom به نظر + ADJ; an ezafe already written (ِ, ٔ, final ای/وی).
- **Spelling** (checked on espeak phonemes): consonant + kasre (پارکِ → pârke); silent ه + hamza above
  (خانهٔ → xâneye); spoken ه or و + kasre, decided by espeak's own reading of the bare word (ماهِ → mâhe,
  not mâhye; عضوِ → ozve, not ozvi); ی + ZWNJ + ی (کشتی‌ی → kashtiye; کشتیِ gives koshtie); vowel ا/و + ی
  (دانشجوی, هوای). The ی additions change letters, so `--check` lists them as notes.
- **Coverage (2026-09-26):** 3575 distinct texts, 1508 overridden (42%), 1929 ezafe marks. Precision: 20 random
  overrides phoneme-checked, 19 right; the one wrong class (به نظر کافی می‌رسد) got the idiom guard. Recall is
  unmeasured: parser misses and flat:name chains (حضرت محمد, ایالات متحده) stay unmarked.
- **Stress is not addressed.** espeak-ng's fa stress is kept as is, except where an ezafe mark shifts it
  (the kasre also moves the stress off the linked word, as in phase 1). Fix individual items by hand-editing `audio_say.json` (the generator overwrites
  the file, so hand edits belong in the generator as rules or must be re-applied).

## Rollout

1. **Phase 2 — engine + builder + tests (done, branch fa-audio-2).** Tests: `tests/audio_checks.js` (core,
   app call sites on the Persian pack with 3 clips, fallback, build.sh version, SW cache),
   `tests/validate_pack_audio_checks.js`, `packbuilder/tests/test_audio.py`.
2. **Phase 3 — render, publish, live check.** Full Persian render (5610 files: 2000 words, 3025 sentences,
   552 passage sentences, 33 units). Measured estimate with ganji_adabi: ~14 min in one process
   (3025×0.11 s + 552×0.18 s + 2033×0.033 s synth + 5610×0.058 s encode); ~43.5 MB. Measured 2026-09-26 (persian beefd3b):
   5610 clips, 43.5 MB, 1652 s wall (27.5 min, about twice the estimate); `--check` exit 0, validate_pack
   0 errors; GitHub Pages serves `.opus` as `audio/ogg` with 200, and 206 for a Range request. Then a QA pass on a
   stratified sample (ear + ASR round-trip to flag outliers), `audio_say.json` fixes, publish the persian
   repo, live check on the phone (Listen drill, Words tap, passage read-aloud, offline replay of a played clip)
   and an iPhone (Opus playback, Range through the worker), and the `.opus` MIME type Pages serves.
3. **Indonesian** (`id`): Piper lists one voice, `id_ID-news_tts-medium`; its MODEL_CARD licence is
   "See URL" (a Kaggle notebook link that looks mislabelled), so confirm the licence before use.
   Indonesian spelling is near-phonemic, so espeak-ng phonemes should need few overrides. Recorded audio
   always beats TTS under current `speak` semantics, which keeps one voice across devices.
4. **Urdu** (`ur`): Piper lists `ur_PK-fasih-medium` and `ur_PK-aegis_female-medium`, both marked MIT.
   Urdu shares Persian's unvocalised-script issues (ezafe, short vowels), so plan the same `audio_say.json` pass.
   Voice lists checked against rhasspy/piper-voices voices.json on 2026-09-26.

## Decisions (2026-09-26)

1. **Voice:** the user decides by ear on the phase 1 samples; default ganji_adabi (`langs/fa.py` AUDIO).
   gyro excluded until its licence is confirmed.
2. **Ezafe/stress fixes:** yes, in phase 3, as `tools/audio_say.json` overrides (mechanism built in phase 2).
3. **Slow render:** words and primer carriers only (length_scale 1.25 + padding); sentences at 1.0.
4. **Audio cache:** cap 800 clips, cached on play; no "download all" in phase 2.
