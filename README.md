# vocab-engine

A language-agnostic vocabulary trainer that builds to one self-contained HTML file. It was extracted from the `hsk` pinyin trainer. The engine holds the logic and UI, and each language is a **pack** of JSON data. Language repos (Italian, Spanish, and others) include this repo as a git submodule and hold only their pack.

The app has these tabs:

- **Today** runs one session: review 15 items with at least 40% production, learn the next set, listen 12, recall 8, then 8 sentences.
- **Words** is a browser with search and per-set drills.
- **Sounds** shows pack lessons. It appears only when the pack has lessons.
- **Test** has placement plus free tests.
- **Progress** shows stats and handles export, import, and reset.

The question types are:

- **hear:** hear the word, then pick its meaning.
- **read:** see the word, then pick its meaning.
- **recall:** see the meaning, then pick the word.
- **type:** see the meaning, then type the word. A pack with `typing: "pron"` (zh) alternates two tagged kinds here instead. "Type the pinyin" is silent and tones are optional. "Type the characters" plays the word first. See docs/PACK_SCHEMA.md "Pronunciation aids".
- **gap:** fill a cloze sentence, by picking or typing.

An item that plays audio by itself shows a Replay button. A gap item plays its sentence only after the answer, with Replay in the reveal. See docs/AUDIO.md "Playback reliability".

## Layout

```
engine/core.js            logic with no DOM (VocabCore); shared by the app and the tests
engine/app.html           UI shell; loads a pack in dev mode, and build.sh inlines everything
engine/sw.template.js     service worker; build.sh fills in the build id and writes sw.js
engine/sw.disable.js      kill switch: copy over sw.js to turn the offline cache off
build.sh                  ./build.sh <packdir> <out.html>   (awk only, no Node or Python; also writes sw.js next to out.html)
packs/zh/                 Mandarin HSK 1–4 pack, ported from the hsk app, now ../chinese (1193 words, 882 sentences, 12 lessons)
tools/jsonify_pack.py     packs/X/*.json -> *.js consts
tools/validate_pack.py    schema and referential-integrity check
tools/check_site.sh       stale-build guard for a language repo's index.html + sw.js
tools/pack_from_hsk.py    reproducible hsk -> packs/zh converter
tools/packbuilder/        shared corpus-based pack builder for language repos (it; see its README)
tests/engine_checks.js    Node checks, no dependencies
tests/pron_aids_checks.js Node checks for the pronunciation aids (docs/PACK_SCHEMA.md "Pronunciation aids"), incl. a byte-identical control against main's engine
tests/audio_checks.js     Node checks for recorded audio (docs/AUDIO.md): word call sites, fallback, sw.js audio cache
tests/validate_pack_audio_checks.js  validator rules for pack.audio / words[].audio / passage sentence audio
tests/flagoff_snapshot.js Golden harness proving hsk-merge work is a no-op for every pack without `characters` (see docs/HSK_MERGE.md); tests/golden/ holds the goldens
dist/zh.html dist/sw.js   built zh trainer + its service worker (committed; the tests fail if either is stale)
docs/PACK_SCHEMA.md       pack format (authoritative)
docs/AUDIO.md             recorded audio (Piper clips): findings, engine/SW/builder design, rollout, peak normalisation
TODO.md                   known gaps and follow-ups
```

## Commands

```sh
python3 tools/jsonify_pack.py packs/zh        # after editing any packs/zh/*.json
python3 tools/validate_pack.py packs/zh
./build.sh packs/zh dist/zh.html
/opt/homebrew/bin/node tests/engine_checks.js  # includes the stale-build guard for dist/zh.html
/opt/homebrew/bin/node tests/flagoff_snapshot.js --check  # flag-off golden check (--capture to update goldens)
/opt/homebrew/bin/node tests/audio_checks.js   # recorded audio (needs ../persian for the app section)
python3 -m packbuilder audio --lang fa --repo ../persian --check   # from tools/: recorded-audio status of a repo
python3 tools/pack_from_hsk.py [../chinese]    # regenerate packs/zh from the hsk app (repo now ../chinese) (idempotent)
python3 -m unittest discover -s tools/packbuilder/tests -t tools   # packbuilder smoke tests
```

## Tests

`node tests/engine_checks.js` covers `engine/core.js`/`engine/app.html` against the real
zh pack plus synthetic packs. `node tests/flagoff_snapshot.js --check` guards the
in-progress hsk/characters merge (docs/HSK_MERGE.md): goldens in `tests/golden/` cover
`defaultProg`, `normalizeProg`, the plan builders, and a fake-DOM boot of every tab, for
zh, italian, korean and japanese, proving no behaviour change for a pack without
`characters`. `--capture` regenerates goldens after an intentional flag-off-safe change.

For dev mode, open `engine/app.html?pack=zh` from `file://`. It loads `../packs/zh/*.js` directly, so you don't need a rebuild while you edit the engine. Use `?packdir=<relative path>` to load a pack that lives elsewhere.

After any change to `engine/` or a pack, rebuild `dist/`. The test suite rebuilds into a scratch file and byte-compares it against the committed output.

## Using it from a language repo

Here is an example layout, using Italian:

```
italian/
  vocab-engine/          git submodule -> this repo
  pack/                  pack.json words.json sentences.json [lessons.json] + generated .js
  index.html             built output (for example, served by GitHub Pages)
  sw.js                  service worker written by build.sh next to index.html; publish it too
```

Set it up and build with these commands:

```sh
git submodule add <vocab-engine remote> vocab-engine
# write pack/*.json following vocab-engine/docs/PACK_SCHEMA.md, then:
python3 vocab-engine/tools/jsonify_pack.py pack
python3 vocab-engine/tools/validate_pack.py pack
vocab-engine/build.sh pack index.html
# for dev mode, open vocab-engine/engine/app.html?packdir=../../pack
```

### Offline and repeat loads (sw.js)

`build.sh` writes `sw.js` next to the page. The page registers it after `window` load, over http(s) only, so `file://` and dev mode are unaffected. The worker:

- serves the page cache-first, so repeat visits load instantly and work offline. Other offline navigations inside the site fall back to the cached page. Packs are inlined, so nothing else is cached;
- names its cache `ve:<site path>:<build id>`. The build id is the POSIX `cksum` of the built page before its last line, `<!--ve-build:<id>-->`. Every rebuild that changes the page changes `sw.js`, and the browser installs the new worker on the next visit. Activation deletes only this site's older caches. All language sites share the `github.io` origin, so the site path in the name keeps them apart;
- caches a page only when it carries this build's marker. Right after a publish a CDN edge can still serve the old `index.html`. Install then fails and the browser retries it on a later navigation, instead of pinning the old page under the new id;
- falls back to the plain network whenever the Cache API fails, and never touches cross-origin requests (Google Fonts, tatoeba.org audio).

A new build takes over in the background. The open page keeps running and shows "Updated, reload for the new version". The load after that gets the new build.

**Publishing.** Commit `sw.js` together with `index.html` every time. A stale `sw.js` keeps serving the old cached page until a publish changes `sw.js`. Add this line to the language repo's `check.sh`. It rebuilds into a private temp dir, compares `index.html` and `sw.js`, and checks that both are tracked and committed:

```sh
sh engine/tools/check_site.sh pack        # [page], default index.html
```

**Kill switch and rollback.** Never delete a published `sw.js`. When the update check gets a 404, the installed worker stays and keeps serving its cached page. To turn the cache off, copy `engine/sw.disable.js` over `sw.js` after `build.sh`, then publish. On the next visit it deletes this site's `ve:` caches, unregisters itself and handles no requests. `check_site.sh` reports `sw.js` as stale while the kill switch is in place. To roll back a bad build, publish the previous `index.html` and `sw.js` together. Its build id differs from the live one, so browsers install it and replace the cache in the usual way. To re-enable after the kill switch, rebuild and publish.

To take an engine update, run this and then rebuild:

```sh
git submodule update --remote vocab-engine
```

Progress lives in the browser under `vocab_<pack.key>`, so each language keeps separate progress.

## Progress backups and recovery

The app never discards stored progress silently. It writes a backup to the same storage backend as the progress, under these keys:

| key | written when |
|---|---|
| `vocab_<key>_invalid_backup` | At startup, stored progress can't be parsed or fails validation. The raw string is kept and the app starts fresh. |
| `vocab_<key>_pre_import_backup` | Just before a valid import replaces the current progress. The import is not applied if this backup can't be written. |
| `vocab_<key>_reset_backup` | Just before "Reset all progress". The reset is cancelled if this backup can't be written. |

Each key holds only the most recent backup of its kind.

If the stored progress can't be read at all (a storage read error), the session runs read-only with a visible warning. Nothing is saved, so the stored progress is left untouched. A storage write error also shows a warning; it never falls through to a different storage backend.

To recover, copy the backup's value and paste it into Progress → Import progress:

1. In the browser devtools console, run `copy(localStorage.getItem("vocab_zh_reset_backup"))`, using your pack key and the backup you want.
2. On the Progress tab, choose Import progress, paste, and choose Load.

Import is strict, so a backup taken from an older pack whose levels were since renamed is rejected with a reason.

## Pack essentials

The full reference is in docs/PACK_SCHEMA.md. The key rules are:

- Everything language-specific comes from the pack: levels, set size, placement buckets, function words, typing rules, and the TTS locale.
- `pron` is display-only and never drilled.
- Sentence `words` are word ids resolved when the pack is built. There is no runtime lookup.

## Licence

Code (engine/, tools/, tests/, docs/) is MIT. Pack data under `packs/*/` is
CC BY-SA 4.0. See LICENSE for details and attribution.
