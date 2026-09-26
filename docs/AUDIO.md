# Generated audio (Piper) — design

Status: design, phase 1 done 2026-09-26 (voice samples + this doc). Nothing below is implemented yet.
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
audio/w/<wordId>.opus        audio/s/<sentenceId>.opus
audio/p/<passageId>-<n>.opus  (n = 0-based sentence index)
audio/x/<unitId>.opus        (script primer carriers)
```

`audio/manifest.json`:

```json
{ "voice": "fa_IR-ganji_adabi-medium", "engine": "piper-tts 1.8.0", "version": 1,
  "codec": "opus", "bitrate": "24k", "rate": 24000, "count": 5610,
  "generated": "2026-10-01T12:00:00Z", "licence": "CC0 (voice dataset tts.datacula.com)",
  "files": { "w/w0001.opus": "<sha1 of key>", "...": "..." } }
```

Cost of explicit per-item URLs: ~30 bytes × 5610 items ≈ 170 KB raw in the built page (1.5 MB today),
far less gzipped. Explicit fields keep partial coverage and Tatoeba mixing trivial.

## Engine

Helpers (app.html, speech section):

```js
const wordAudio = w => (w && w.audio) || undefined;
const sayWord = (w, btn) => speak(w.w, btn, wordAudio(w));
const canHearWord = w => hasSpeech || !!wordAudio(w);      // mirrors canHearSentence
const PACK_AUDIO = !!PACK.audio;                            // pack ships generated audio
```

Word call sites to switch from `speak(w.w…)`/`say(w.w)` to `sayWord`, and from `hasSpeech` to `canHearWord`:

| site (app.html) | today | change |
|---|---|---|
| panel `data-wid` tap (Words rows, teach, char teach) | `say(w.w)` | `sayWord(w)` |
| `revealBlock` | `data-wid` + icon only if `hasSpeech` | gate on `canHearWord(entry)` |
| `hearItem` (Listen drill) | read item + notice if `!hasSpeech` | gate on `canHearWord`; `sayWord` in mount/button |
| `readItem` / `recallItem` / `typeItem` | `say(entry.w)` on mount/reveal | `sayWord(entry)` |
| `pronTypeItem` | replay button if `hasSpeech` | `canHearWord` + `sayWord` |
| `tokTap` popover | `say(head ? head.surface : w.w)` | `sayWord(w)` when no phrase head, or head.surface === w.w; else TTS as now |
| `vocabTeach` rows + hint | `hasSpeech` gate, `say(w.w)` | `canHearWord`, `sayWord` |
| `charTeach` head / `sayUnit` / `charDrillItem` | `hasSpeech` gate, `speak(w.w)` | `canHearWord(WORDS_BY_ID[id])`, `sayWord` |
| `wordListInto` (Words tab) | `hasSpeech` gate | `canHearWord`, `sayWord` |
| `placeVocabNext` (placement) | `asHear = hasSpeech && …` | `canHearWord(w) && …`, `sayWord` |
| script primer example word (`data-xw`) | `scriptVoice() && speak(w.w)` | play `wordAudio(w)` when present, else as now |
| script units (`sayUnitSound`, `unitHasSound`) | already use `u.audio` | none |

Test/drill pools: `tListen` and Today `g.listen` build `hearItem` for every word, so they work once
`hearItem` checks `canHearWord`. Sentences already use `canHearSentence`.

Notices: `speechNotice()`, the Sounds-lesson warning and the Progress-tab warning currently key on `!hasSpeech`.
With `PACK_AUDIO`, suppress the word/sentence notices (the audio covers them). Keep the Sounds-lesson warning:
lesson `say` strings are free text with no clip. `lessonSayMode` is unchanged.

Service worker (`sw.template.js`): today it ignores same-origin non-page requests, so audio goes to the
network only (Pages HTTP cache, max-age 600). Add:
- never precache audio (install stays page-only);
- `audio/*` requests: cache-first from a separate cache `<prefix>-audio-v<manifest version>`, fetched and
  stored on first play; cap at N entries (proposed 800 ≈ 6 MB), evicting oldest-inserted on write;
- the audio cache survives page-build changes (keyed by audio version, not build hash) and is deleted
  when the version changes. The `activate` handler today deletes every `PREFIX*` cache but the current
  build's, so its filter must skip the audio cache name;
- offline miss → `Response.error()`. The engine's `audio.onerror` already clears the button state; add a
  one-line hint ("Offline: this clip isn't saved yet") and fall back to TTS when a voice exists.
- Range requests: Safari fetches media with `Range`; serve full cached responses with 200 only for non-range
  requests, pass range requests to the network when uncached. Test on iOS Safari before shipping.

## Builder: `packbuilder audio --lang fa [--repo R] [--check] [--only w,s,p,x] [--limit N]`

- Config lives in `pack.json` `audio: {voice, version}` (the engine reads it for `PACK_AUDIO`) plus the lang
  spec (`langs/fa.py`: `AUDIO = {voice, length_scale_short: 1.25, pad_ms: [150, 250], bitrate: "24k"}`).
  Bitrate/rate/engine version go in the manifest only.
- Text per item: words `w`, sentences `t`, passage sentences `t`, units `say`. Optional per-language override
  file `tools/audio_say.json` (`{id: "spoken text"}`), for ezafe kasre and stress fixes found in QA. Overrides
  change the spoken text only, never the pack text.
- Key = sha1(spoken text, voice, version, synth params). A file whose manifest key matches is skipped, so
  reruns are idempotent and a text edit re-renders only that item. Orphan files (ids no longer in the pack)
  are listed and deleted with `--prune`.
- Writes `audio` URLs into the pack JSON for items with a file, skipping items that already carry an absolute
  (Tatoeba) URL, then regenerates the .js consts (`jsonify_pack.py`) and the manifest.
- `--check`: lists items with no file, files with a stale key, orphan files, and pack `audio` URLs pointing at
  missing files; exit 1 if any. Run it in the language repo's `check.sh`.
- Dependencies (`requirements-audio.txt`): piper-tts pinned, ffmpeg on PATH. Voice .onnx downloaded to the
  repo `.cache/` (never committed).
- Tests: key stability, skip-on-match, override applied, Tatoeba URL preserved, `--check` exit codes
  (stub synth; no model in CI).

## Rollout

1. **Phase 2 — engine + builder + tests.** Helpers and call-site table above, notices, SW audio cache,
   validator (`words[].audio`, `passages[].sentences[].audio`), PACK_SCHEMA update, `packbuilder audio`.
   Engine tests: `canHearWord` gating, notice suppression, SW cache cap/eviction/offline miss.
2. **Phase 3 — render, publish, live check.** Full Persian render (5610 files: 2000 words, 3025 sentences,
   552 passage sentences, 33 units). Measured estimate with ganji_adabi: ~14 min in one process
   (3025×0.11 s + 552×0.18 s + 2033×0.033 s synth + 5610×0.058 s encode); ~43.5 MB. Then a QA pass on a
   stratified sample (ear + ASR round-trip to flag outliers), `audio_say.json` fixes, publish the persian
   repo, live check on the phone (Listen drill, Words tap, passage read-aloud, offline replay of a played clip).
3. **Indonesian** (`id`): Piper lists one voice, `id_ID-news_tts-medium`; its MODEL_CARD licence is
   "See URL" (a Kaggle notebook link that looks mislabelled), so confirm the licence before use.
   Indonesian spelling is near-phonemic, so espeak-ng phonemes should need few overrides. Recorded audio
   always beats TTS under current `speak` semantics, which keeps one voice across devices.
4. **Urdu** (`ur`): Piper lists `ur_PK-fasih-medium` and `ur_PK-aegis_female-medium`, both marked MIT.
   Urdu shares Persian's unvocalised-script issues (ezafe, short vowels), so plan the same `audio_say.json` pass.
   Voice lists checked against rhasspy/piper-voices voices.json on 2026-09-26.

## Open questions (with recommendations)

1. **Voice.** Recommend ganji_adabi (best sentence intelligibility, CC0); ganji as runner-up. Exclude gyro until
   its licence is confirmed. Decide by ear on the samples page.
2. **Ezafe/stress fixes.** Recommend a hand/LLM-assisted `audio_say.json` pass on sentences in phase 3
   (mark ezafe with kasre), over shipping raw espeak output. Cost: one review pass over ~3,600 sentences.
3. **Slow words.** Recommend length_scale 1.25 + padding for words and primer carriers only; sentences at 1.0.
4. **Audio cache cap.** Recommend 800 clips (~6 MB) cached on play, no bulk "download all" button in phase 2.
