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
set -e
if [ $# -ne 2 ]; then echo "usage: $0 <packdir> <out.html>" >&2; exit 2; fi
PACKDIR="${1%/}"
OUT="$2"
ENGINE="$(cd "$(dirname "$0")" && pwd)/engine"
SRC="$ENGINE/app.html"
CORE="$ENGINE/core.js"

for f in "$SRC" "$CORE" "$PACKDIR/pack.js" "$PACKDIR/words.js" "$PACKDIR/sentences.js"; do
  if [ ! -f "$f" ]; then echo "build.sh: missing $f" >&2; exit 1; fi
done
LESSONS="$PACKDIR/lessons.js"
if [ ! -f "$LESSONS" ]; then
  LESSONS=""
  if grep -q '"hasLessons":true' "$PACKDIR/pack.js"; then
    echo "build.sh: warning: $PACKDIR/pack.js has hasLessons=true but $PACKDIR/lessons.js is missing (Sounds tab will be hidden)" >&2
  fi
fi

mkdir -p "$(dirname "$OUT")"
TMP="$OUT.tmp.$$"
# Paths go to awk via ENVIRON, not -v: -v expands backslash escapes in values.
VE_PACK="$PACKDIR/pack.js" VE_WORDS="$PACKDIR/words.js" VE_SENTS="$PACKDIR/sentences.js" \
VE_LESSONS="$LESSONS" VE_CORE="$CORE" awk '
  BEGIN { pack = ENVIRON["VE_PACK"]; words = ENVIRON["VE_WORDS"]; sents = ENVIRON["VE_SENTS"]
          lessons = ENVIRON["VE_LESSONS"]; core = ENVIRON["VE_CORE"] }
  function inline(f,   line){ print "<script>"; while ((getline line < f) > 0) print line; close(f); print "</script>" }
  /<!-- PACK-BEGIN/ { skipping = 1; seen_begin = 1
                      inline(pack); inline(words); inline(sents)
                      if (lessons != "") inline(lessons); else print "<script>const LESSONS=[];</script>"
                      next }
  skipping && /<!-- PACK-END -->/ { skipping = 0; seen_end = 1; next }
  skipping { next }
  /<script src="core\.js"><\/script>/ { inline(core); seen_core = 1; next }
  { print }
  END { if (!seen_begin || !seen_end || !seen_core) { print "build.sh: PACK-BEGIN/PACK-END markers or core.js tag not found in app.html" > "/dev/stderr"; exit 1 } }
' "$SRC" > "$TMP" || { rm -f "$TMP"; exit 1; }
mv "$TMP" "$OUT"
echo "Built $OUT ($(wc -c < "$OUT" | tr -d ' ') bytes) from $PACKDIR"
