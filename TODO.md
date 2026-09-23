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
- **Gap bare-form labels** rely on the pack convention "alt[0] = bare lemma when `w` carries an article". A pack that breaks it just gets `w` labels (no wrong labels), but article-bearing distractors can reappear in article contexts. `validate_pack.py` does not check the convention yet.
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
