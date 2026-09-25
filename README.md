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
- **type:** see the meaning, then type the word.
- **gap:** fill a cloze sentence, by picking or typing.

## Layout

```
engine/core.js            logic with no DOM (VocabCore); shared by the app and the tests
engine/app.html           UI shell; loads a pack in dev mode, and build.sh inlines everything
build.sh                  ./build.sh <packdir> <out.html>   (awk only, no Node or Python)
packs/zh/                 Mandarin HSK 1–4 pack, ported from ../hsk (1193 words, 882 sentences, 12 lessons)
tools/jsonify_pack.py     packs/X/*.json -> *.js consts
tools/validate_pack.py    schema and referential-integrity check
tools/pack_from_hsk.py    reproducible hsk -> packs/zh converter
tools/packbuilder/        shared corpus-based pack builder for language repos (it; see its README)
tests/engine_checks.js    Node checks, no dependencies
dist/zh.html              built zh trainer (committed; the tests fail if it is stale)
docs/PACK_SCHEMA.md       pack format (authoritative)
TODO.md                   known gaps and follow-ups
```

## Commands

```sh
python3 tools/jsonify_pack.py packs/zh        # after editing any packs/zh/*.json
python3 tools/validate_pack.py packs/zh
./build.sh packs/zh dist/zh.html
/opt/homebrew/bin/node tests/engine_checks.js  # includes the stale-build guard for dist/zh.html
python3 tools/pack_from_hsk.py [../hsk]        # regenerate packs/zh from hsk (idempotent)
python3 -m unittest discover -s tools/packbuilder/tests -t tools   # packbuilder smoke tests
```

For dev mode, open `engine/app.html?pack=zh` from `file://`. It loads `../packs/zh/*.js` directly, so you don't need a rebuild while you edit the engine. Use `?packdir=<relative path>` to load a pack that lives elsewhere.

After any change to `engine/` or a pack, rebuild `dist/`. The test suite rebuilds into a scratch file and byte-compares it against the committed output.

## Using it from a language repo

Here is an example layout, using Italian:

```
italian/
  vocab-engine/          git submodule -> this repo
  pack/                  pack.json words.json sentences.json [lessons.json] + generated .js
  index.html             built output (for example, served by GitHub Pages)
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
