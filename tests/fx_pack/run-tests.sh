#!/usr/bin/env bash
#
# run-tests.sh - permanent host checks for the finite-v1 compact FX converter
# (ATMlib2FX-hlh.7).
#
# Builds tools/fx_pack and tests/fx_pack/fx_pack_selftest, runs the C selftest
# (gap boundaries, admission rejections, legacy translation, device decode
# round-trip), then converts the two retained example scores and verifies:
#
#   * song01_sfx reproduces the retained hlh.5 compact stream hash
#     0e8432ace6fd5d93421f07bd584ebf1ee27d00a60bc1f912a119c872f94b0990;
#   * the same input converted twice is byte-identical (determinism);
#   * the optional tempo-255 stream reproduces b7702512...;
#   * both converted streams decode to END with zero errors and zero underruns
#     on the real device decoder.
#
# Shell + C only (no Python). All outputs land under build/fx-port/pack/.
#
# Usage: tests/fx_pack/run-tests.sh
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
cd "$REPO_ROOT"

OUT="build/fx-port/pack"
CC="${CC:-cc}"
SHIM="research/fx/fx_stream_spike/trace/avr_shim"
SONG_SFX="examples/arduino/songs/song01_sfx/song.h"
SONG_01="examples/arduino/songs/song01/song.h"
WANT_AUTHORED="0e8432ace6fd5d93421f07bd584ebf1ee27d00a60bc1f912a119c872f94b0990"
WANT_T255="b7702512b218df5d614bcd1406116817720b4a5ff983dae443c5bde0f6e88249"

mkdir -p "$OUT"

echo "== fx_pack host checks (ATMlib2FX-hlh.7) =="
echo "repo : $REPO_ROOT"
echo "cc   : $($CC --version 2>/dev/null | head -1)"

# ---- source identity (no git) ----------------------------------------------
{
  echo "# fx_pack source hashes"
  for f in \
    tools/fx_pack/fx_pack.c tools/fx_pack/fx_score.c tools/fx_pack/fx_encode.c \
    tools/fx_pack/fx_score.h tools/fx_pack/fx_encode.h tools/fx_pack/Makefile \
    tests/fx_pack/fx_pack_selftest.c tests/fx_pack/run-tests.sh \
    "$SONG_SFX" "$SONG_01"; do
    shasum -a 256 "$f" | sed "s#  #  #"
  done
} > "$OUT/source-hashes.txt"

# ---- build -----------------------------------------------------------------
make -C tools/fx_pack CC="$CC" > "$OUT/build.log"
"$CC" -std=c11 -O1 -w -I"$SHIM" -Isrc -Itools/fx_pack \
  tests/fx_pack/fx_pack_selftest.c tools/fx_pack/fx_encode.c \
  tools/fx_pack/fx_score.c -o "$OUT/fx_pack_selftest"

# ---- C selftest ------------------------------------------------------------
"$OUT/fx_pack_selftest" | tee "$OUT/selftest.log"

# ---- conversion helper -----------------------------------------------------
convert() { # name song symbol extra...
  local name="$1" song="$2" symbol="$3"; shift 3
  local dir="$OUT/$name"
  mkdir -p "$dir"
  "$OUT/fx_pack" \
    --song "$song" --symbol "$symbol" \
    --out "$dir/stream.bin" --meta "$dir/meta.json" \
    --input-bin "$dir/input.bin" \
    --workdir "$OUT/work-$name" "$@" \
    > "$dir/window.txt" 2> "$dir/convert.log"
  cat "$dir/convert.log"
}

# ---- song01_sfx (retained fixture) ----------------------------------------
convert song01_sfx "$SONG_SFX" score
convert song01 "$SONG_01" music
convert song01_sfx_t255 "$SONG_SFX" score --tempo 255

# ---- determinism -----------------------------------------------------------
mkdir -p "$OUT/song01_sfx"
"$OUT/fx_pack" --song "$SONG_SFX" --symbol score \
  --out "$OUT/song01_sfx/stream.repeat.bin" \
  --workdir "$OUT/work-song01_sfx" > /dev/null 2>&1
if cmp -s "$OUT/song01_sfx/stream.bin" "$OUT/song01_sfx/stream.repeat.bin"; then
  echo "determinism: OK (two conversions identical)"
  DET=ok
else
  echo "determinism: FAILED" >&2
  exit 1
fi
rm -f "$OUT/song01_sfx/stream.repeat.bin"

# ---- hash gates ------------------------------------------------------------
HASH_SFX=$(shasum -a 256 "$OUT/song01_sfx/stream.bin" | awk '{print $1}')
HASH_T255=$(shasum -a 256 "$OUT/song01_sfx_t255/stream.bin" | awk '{print $1}')
HASH_01=$(shasum -a 256 "$OUT/song01/stream.bin" | awk '{print $1}')
HASH_SFX_IN=$(shasum -a 256 "$OUT/song01_sfx/input.bin" | awk '{print $1}')
HASH_01_IN=$(shasum -a 256 "$OUT/song01/input.bin" | awk '{print $1}')

[ "$HASH_SFX" = "$WANT_AUTHORED" ] || {
  echo "FAIL: song01_sfx stream $HASH_SFX != $WANT_AUTHORED" >&2; exit 1; }
[ "$HASH_T255" = "$WANT_T255" ] || {
  echo "FAIL: song01_sfx tempo-255 stream $HASH_T255 != $WANT_T255" >&2; exit 1; }
echo "song01_sfx authored hash: $HASH_SFX (retained match)"
echo "song01_sfx tempo255 hash: $HASH_T255 (retained match)"
echo "song01      stream hash : $HASH_01"

# ---- device decode round-trip ---------------------------------------------
decode() { # name stream
  local name="$1" stream="$2"
  "$OUT/fx_pack_selftest" --decode "$stream" | tee "$OUT/$name/decode.log"
}
decode song01_sfx "$OUT/song01_sfx/stream.bin"
decode song01 "$OUT/song01/stream.bin"
decode song01_sfx_t255 "$OUT/song01_sfx_t255/stream.bin"

# ---- summary ---------------------------------------------------------------
{
  echo "# fx_pack verification (ATMlib2FX-hlh.7)"
  echo "selftest=$(grep -c '^ok:' "$OUT/selftest.log") checks passed"
  echo "determinism=$DET"
  echo "song01_sfx_stream_sha256=$HASH_SFX"
  echo "song01_sfx_stream_matches_retained=yes"
  echo "song01_sfx_t255_stream_sha256=$HASH_T255"
  echo "song01_sfx_t255_matches_retained=yes"
  echo "song01_stream_sha256=$HASH_01"
  echo "song01_sfx_input_sha256=$HASH_SFX_IN"
  echo "song01_input_sha256=$HASH_01_IN"
  echo "song01_sfx_meta=$(tr '\n' ' ' < "$OUT/song01_sfx/meta.json")"
  echo "song01_meta=$(tr '\n' ' ' < "$OUT/song01/meta.json")"
} > "$OUT/verify.txt"

echo
echo "summary:"
grep -E '^(selftest|determinism|song01|song01_sfx)' "$OUT/verify.txt"
echo
echo "evidence: $OUT"
