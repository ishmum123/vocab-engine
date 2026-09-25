#!/bin/sh
# Builds a self-contained single-file trainer from engine/app.html + engine/core.js
# + one pack's generated .js consts. No Node/Python needed (awk only).
#
# Usage: ./build.sh <packdir> <out.html>
#   e.g. ./build.sh packs/zh dist/zh.html
#        ./build.sh ../pack ../index.html      (from a language repo's submodule checkout)
#
# The pack's .js files are generated from its .json by tools/jsonify_pack.py;
# tools/validate_pack.py fails if they are stale.
#
# Also writes sw.js next to <out.html>: engine/sw.template.js with the build id (POSIX
# cksum of the built page) and the page's file name filled in. The page then gets a last
# line <!--ve-build:<id>--> that sw.js checks before caching it. Publish sw.js with the
# page; app.html registers it (offline use and instant repeat loads, see README).
# tools/check_site.sh is the stale-build guard for a language repo.
set -e
if [ $# -ne 2 ]; then echo "usage: $0 <packdir> <out.html>" >&2; exit 2; fi
PACKDIR="${1%/}"
OUT="$2"
PAGE="$(basename "$OUT")"
case "$PAGE" in *[!A-Za-z0-9._-]*) echo "build.sh: output file name '$PAGE' must be [A-Za-z0-9._-] (it goes into sw.js)" >&2; exit 1;; esac
ENGINE="$(cd "$(dirname "$0")" && pwd)/engine"
SRC="$ENGINE/app.html"
CORE="$ENGINE/core.js"
SWT="$ENGINE/sw.template.js"

for f in "$SRC" "$CORE" "$SWT" "$PACKDIR/pack.js" "$PACKDIR/words.js" "$PACKDIR/sentences.js"; do
  if [ ! -f "$f" ]; then echo "build.sh: missing $f" >&2; exit 1; fi
done
LESSONS="$PACKDIR/lessons.js"
if [ ! -f "$LESSONS" ]; then
  LESSONS=""
  if grep -q '"hasLessons":true' "$PACKDIR/pack.js"; then
    echo "build.sh: warning: $PACKDIR/pack.js has hasLessons=true but $PACKDIR/lessons.js is missing (Sounds tab will be hidden)" >&2
  fi
fi
CHARS="$PACKDIR/characters.js"
if [ ! -f "$CHARS" ]; then
  CHARS=""
  if grep -q '"characters":' "$PACKDIR/pack.js"; then
    echo "build.sh: warning: $PACKDIR/pack.js has a characters block but $PACKDIR/characters.js is missing (character stage will be off)" >&2
  fi
fi
SCRIPTF="$PACKDIR/script.js"
if [ ! -f "$SCRIPTF" ]; then
  SCRIPTF=""
  if grep -q '"script":' "$PACKDIR/pack.js"; then
    echo "build.sh: warning: $PACKDIR/pack.js has a script block but $PACKDIR/script.js is missing (script primer will be off)" >&2
  fi
fi
LEGACY="$PACKDIR/legacy.js"
if [ ! -f "$LEGACY" ]; then LEGACY=""; fi

mkdir -p "$(dirname "$OUT")"
TMP="$OUT.tmp.$$"
# Paths go to awk via ENVIRON, not -v: -v expands backslash escapes in values.
VE_PACK="$PACKDIR/pack.js" VE_WORDS="$PACKDIR/words.js" VE_SENTS="$PACKDIR/sentences.js" \
VE_LESSONS="$LESSONS" VE_CHARS="$CHARS" VE_SCRIPT="$SCRIPTF" VE_LEGACY="$LEGACY" VE_CORE="$CORE" awk '
  BEGIN { pack = ENVIRON["VE_PACK"]; words = ENVIRON["VE_WORDS"]; sents = ENVIRON["VE_SENTS"]
          lessons = ENVIRON["VE_LESSONS"]; chars = ENVIRON["VE_CHARS"]; script = ENVIRON["VE_SCRIPT"]; legacy = ENVIRON["VE_LEGACY"]
          core = ENVIRON["VE_CORE"] }
  function inline(f,   line){ print "<script>"; while ((getline line < f) > 0) print line; close(f); print "</script>" }
  /<!-- PACK-BEGIN/ { skipping = 1; seen_begin = 1
                      inline(pack); inline(words); inline(sents)
                      if (lessons != "") inline(lessons); else print "<script>const LESSONS=[];</script>"
                      if (chars != "") inline(chars)
                      if (script != "") inline(script)
                      if (legacy != "") inline(legacy)
                      next }
  skipping && /<!-- PACK-END -->/ { skipping = 0; seen_end = 1; next }
  skipping { next }
  /<script src="core\.js"><\/script>/ { inline(core); seen_core = 1; next }
  { print }
  END { if (!seen_begin || !seen_end || !seen_core) { print "build.sh: PACK-BEGIN/PACK-END markers or core.js tag not found in app.html" > "/dev/stderr"; exit 1 } }
' "$SRC" > "$TMP" || { rm -f "$TMP"; exit 1; }

# Build id: cksum of the page before the marker line. sw.js cache name = build id, so any
# change to the page changes sw.js and busts the cache.
BUILD_ID="$(cksum < "$TMP" | awk '{ printf "%s-%s", $1, $2 }')"
echo "<!--ve-build:$BUILD_ID-->" >> "$TMP"
mv "$TMP" "$OUT"

SW="$(dirname "$OUT")/sw.js"
SWTMP="$SW.tmp.$$"
VE_BUILD="$BUILD_ID" VE_PAGE="$PAGE" awk '
  BEGIN { b = ENVIRON["VE_BUILD"]; p = ENVIRON["VE_PAGE"] }
  { gsub(/__VE_BUILD__/, b); gsub(/__VE_PAGE__/, p); print }
' "$SWT" > "$SWTMP" || { rm -f "$SWTMP"; exit 1; }
mv "$SWTMP" "$SW"
echo "Built $OUT ($(wc -c < "$OUT" | tr -d ' ') bytes) from $PACKDIR, and $SW"
