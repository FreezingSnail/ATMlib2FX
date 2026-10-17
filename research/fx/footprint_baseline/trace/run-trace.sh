#!/usr/bin/env bash
#
# run-trace.sh - build and run the reference-trace harness for ATMlib2FX-hlh.1.
#
# The harness compiles the unmodified library C sources on the host with an
# AVR PROGMEM shim and drives the osc tick callbacks exactly as the timer ISR
# does. Output is deterministic; the script verifies that by running twice and
# comparing checksums.
#
# Outputs (single lane build/fx-port/):
#   build/fx-port/trace/reference_trace_music.csv
#   build/fx-port/trace/reference_trace_music_sfx.csv
#   build/fx-port/trace/checksums.txt
#
# Usage: tools/... no: research/fx/footprint_baseline/trace/run-trace.sh [ticks] [sfx_start_tick]
set -euo pipefail

TRACE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$TRACE_DIR/../../../.." && pwd)"
cd "$REPO_ROOT"

TICKS="${1:-512}"
SFX_AT="${2:-64}"
REF_DIR="$TRACE_DIR/reference"
BIN_DIR="build/fx-port/trace"
BIN="$BIN_DIR/trace_main"

mkdir -p "$REF_DIR" "$BIN_DIR"

CC="${CC:-cc}"
echo "compiler: $($CC --version | head -1)"
echo "library sources:"
echo "  src/atm_synth.c (+ src/cmd_parse.c included by it), unmodified"
echo "  shim: research/fx/footprint_baseline/trace/avr_shim/avr/pgmspace.h"
echo "ticks=$TICKS sfx_start_tick=$SFX_AT"
echo

"$CC" -std=c11 -O1 -w \
  -I"$TRACE_DIR/avr_shim" \
  -I"$REPO_ROOT/src" \
  -I"$REPO_ROOT/examples/arduino/songs/song01_sfx" \
  "$TRACE_DIR/trace_main.c" \
  -o "$BIN"

run() { # mode outfile
  local mode="$1" out="$2"
  "$BIN" "$mode" "$TICKS" "$SFX_AT" > "$out"
  echo "wrote $out ($(wc -l < "$out") lines, $(wc -c < "$out") bytes)"
}

run music "$REF_DIR/reference_trace_music.csv"
run sfx   "$REF_DIR/reference_trace_music_sfx.csv"

# Determinism check: regenerate and compare.
"$BIN" music "$TICKS" "$SFX_AT" > "$BIN_DIR/.music.2"
"$BIN" sfx   "$TICKS" "$SFX_AT" > "$BIN_DIR/.sfx.2"

{
  echo "# reference trace checksums (sha256), ATMlib2FX-hlh.1"
  echo "music     $(shasum -a 256 "$REF_DIR/reference_trace_music.csv" | awk '{print $1}')"
  echo "music_sfx $(shasum -a 256 "$REF_DIR/reference_trace_music_sfx.csv" | awk '{print $1}')"
} | tee "$REF_DIR/checksums.txt"

if cmp -s "$REF_DIR/reference_trace_music.csv" "$BIN_DIR/.music.2" && \
   cmp -s "$REF_DIR/reference_trace_music_sfx.csv" "$BIN_DIR/.sfx.2"; then
  echo "determinism: OK (two runs identical)"
else
  echo "determinism: FAILED" >&2
  exit 1
fi
rm -f "$BIN_DIR/.music.2" "$BIN_DIR/.sfx.2"
