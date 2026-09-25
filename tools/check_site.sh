#!/bin/sh
# Stale-build guard for a language repo's published site (index.html + sw.js).
# Run from the language repo root; one line in its check.sh:
#   sh engine/tools/check_site.sh pack            # [page], default index.html
# Fails when:
#   - a fresh build (into a private mktemp -d, as <page>) differs from the committed
#     <page> or sw.js (forgot ./build.sh, or rebuilt one file without the other);
#   - <page> or sw.js is not tracked by git (never published);
#   - <page> or sw.js has uncommitted changes (built but not committed).
# A stale sw.js is the dangerous case: the installed worker keeps serving its cached
# page until a publish changes sw.js. A site running the kill switch (engine/sw.disable.js
# copied over sw.js) fails the sw.js comparison by design; see the engine README.
set -e
if [ $# -lt 1 ] || [ $# -gt 2 ]; then echo "usage: $0 <packdir> [page]" >&2; exit 2; fi
PACKDIR="$1"
PAGE="${2:-index.html}"
ENGINE_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMPD="$(mktemp -d "${TMPDIR:-/tmp}/ve_check_site.XXXXXX")"
trap 'rm -rf "$TMPD"' EXIT
sh "$ENGINE_ROOT/build.sh" "$PACKDIR" "$TMPD/$PAGE" > /dev/null
fail=0
for f in "$PAGE" sw.js; do
  if [ ! -f "$f" ]; then
    echo "FAIL $f is missing: run ./build.sh and commit $PAGE and sw.js." >&2; fail=1; continue
  fi
  if ! cmp -s "$TMPD/$f" "$f"; then
    echo "FAIL $f is stale: a fresh build differs. Run ./build.sh and commit $PAGE and sw.js together." >&2; fail=1
  fi
  if ! git ls-files --error-unmatch -- "$f" > /dev/null 2>&1; then
    echo "FAIL $f is not tracked by git: add and commit it (it must be published)." >&2; fail=1
  fi
done
if ! git diff --quiet HEAD -- "$PAGE" sw.js 2> /dev/null; then
  echo "FAIL $PAGE / sw.js have uncommitted changes: commit them together." >&2; fail=1
fi
[ "$fail" -eq 0 ] || exit 1
echo "OK $PAGE and sw.js match a fresh build and are committed ($(wc -c < "$PAGE" | tr -d ' ') bytes)"
