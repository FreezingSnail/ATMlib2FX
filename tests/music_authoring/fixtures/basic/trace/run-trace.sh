#!/usr/bin/env bash
#
# run-trace.sh - original-engine tick trace for the basic authoring example.
#
# Builds the GENERATED PROGMEM score (via tools/atm-music), compiles the
# *unmodified* library sources on the host (src/atm_synth.c + the
# src/cmd_parse.c it includes), substitutes only the osc.c timer layer with a
# stub that reproduces the Timer3 ISR scheduling exactly, and runs it twice to
# prove determinism.  The emitted CSV is compared against the committed golden
# fixture expected_trace.csv.
#
# Host diagnostic only: this is not an AVR image and contributes no device
# bytes.  No git operations are performed.
#
# Usage: tests/music_authoring/fixtures/basic/trace/run-trace.sh [music_ticks]
set -euo pipefail

TRACE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASIC_DIR="$(cd "$TRACE_DIR/.." && pwd)"
REPO_ROOT="$(cd "$BASIC_DIR/../../../.." && pwd)"
cd "$REPO_ROOT"

TICKS="${1:-64}"
LANE="build/music-authoring/trace"
GEN_DIR="$LANE/generated"
BIN="$LANE/trace_main"
EXPECTED="$TRACE_DIR/expected_trace.csv"

mkdir -p "$LANE"

CC="${CC:-cc}"
echo "compiler: $($CC --version | head -1)"
echo "generating score via tools/atm-music build ..."
tools/atm-music build "$REPO_ROOT/tests/music_authoring/fixtures/basic/song.json" --backend progmem --out "$GEN_DIR" --json \
  > "$LANE/build.json" 2> "$LANE/build.stderr"
echo "  $(cat "$LANE/build.stderr")"

# Copy the generated header next to the harness through the include path only.
"$CC" -std=c11 -O1 -w \
  -I"$REPO_ROOT/tools/music_authoring/preview/avr_shim" \
  -I"$REPO_ROOT/src" \
  -I"$GEN_DIR" \
  "$REPO_ROOT/tools/music_authoring/preview/trace_main.c" \
  -o "$BIN"

"$BIN" "$TICKS" > "$LANE/trace.csv"
echo "wrote $LANE/trace.csv ($(wc -l < "$LANE/trace.csv") lines)"

# Determinism: a second run must be byte-identical.
"$BIN" "$TICKS" > "$LANE/trace.2.csv"
if ! cmp -s "$LANE/trace.csv" "$LANE/trace.2.csv"; then
  echo "determinism: FAILED (two runs differ)" >&2
  exit 1
fi
echo "determinism: OK (two runs identical)"

# Fixture comparison against the committed golden trace.
if cmp -s "$LANE/trace.csv" "$EXPECTED"; then
  echo "fixture: OK (matches $EXPECTED)"
else
  echo "fixture: MISMATCH against $EXPECTED" >&2
  diff -u "$EXPECTED" "$LANE/trace.csv" | head -40 >&2 || true
  exit 1
fi

echo "trace sha256: $(shasum -a 256 "$LANE/trace.csv" | awk '{print $1}')"
rm -f "$LANE/trace.2.csv"
