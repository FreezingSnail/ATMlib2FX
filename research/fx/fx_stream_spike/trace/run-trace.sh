#!/usr/bin/env bash
#
# run-trace.sh - host equivalence check for the compiled FX stream
# (ATMlib2FX-aoe).
#
# Builds the device decoder on the host (src/atm_synth.c with
# ATM_HAS_FX_STREAM=1) and the converter, generates the stream, drives the
# decoder at the baseline's timer contract, and compares the first 512 music
# ticks against the original reference trace from ATMlib2FX-hlh.1
# (research/fx/footprint_baseline/trace/reference/reference_trace_music.csv).
#
# The removed traversal column (cN_ps) is dropped from both sides before the
# diff; every other column - oscillator parameters, live effect state, tempo and
# active-channel flags - must match exactly.
#
# Usage: research/fx/fx_stream_spike/trace/run-trace.sh [ticks]
set -euo pipefail

TRACE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$TRACE_DIR/../../../.." && pwd)"
cd "$REPO_ROOT"

TICKS="${1:-512}"
OUT="build/fx-port/fx-stream"
REF="$REPO_ROOT/research/fx/footprint_baseline/trace/reference/reference_trace_music.csv"
CC="${CC:-cc}"

mkdir -p "$OUT"

echo "compiler: $($CC --version | head -1)"
echo "ticks=$TICKS"

# 1. converter + stream
"$CC" -std=c11 -O2 -Wall -Wextra -Wno-unused-parameter \
  -Isrc -Iexamples/arduino/songs/song01_sfx research/fx/tools/fx_compile_stream.c \
  -o "$OUT/fx_compile_stream"
./"$OUT/fx_compile_stream" --out "$OUT/spike_stream.bin" 2> "$OUT/spike_stream.log"

# 2. host decoder harness
"$CC" -std=c11 -O1 -w \
  -I"$TRACE_DIR/avr_shim" -Isrc \
  "$TRACE_DIR/trace_main.c" -o "$OUT/trace_main"

# 3. run + determinism
"$OUT/trace_main" "$OUT/spike_stream.bin" "$TICKS" > "$OUT/fx_trace_music.csv" 2> "$OUT/fx_trace_music.stderr"
cat "$OUT/fx_trace_music.stderr"
"$OUT/trace_main" "$OUT/spike_stream.bin" "$TICKS" > "$OUT/fx_trace_music.2.csv" 2> /dev/null
cmp -s "$OUT/fx_trace_music.csv" "$OUT/fx_trace_music.2.csv" \
  && echo "determinism: OK (two runs identical)" \
  || { echo "determinism: FAILED" >&2; exit 1; }
rm -f "$OUT/fx_trace_music.2.csv"

# 4. compare, dropping the removed cN_ps traversal column
norm() {
  awk -F, 'NR==1{for(i=1;i<=NF;i++) if($i !~ /_ps$/) keep[i]=1}
           {out=""; for(i=1;i<=NF;i++) if(keep[i]) out=out (i>1?",":"") $i; print out}' "$1"
}
norm "$REF" > "$OUT/ref_norm.csv"
norm "$OUT/fx_trace_music.csv" > "$OUT/fx_norm.csv"

if diff -q "$OUT/ref_norm.csv" "$OUT/fx_norm.csv" > /dev/null; then
  {
    echo "# compiled FX stream equivalence (ATMlib2FX-aoe)"
    echo "ticks=$TICKS"
    echo "dropped_columns=cN_ps"
    echo "reference_sha256=$(shasum -a 256 "$REF" | awk '{print $1}')"
    echo "fx_trace_sha256=$(shasum -a 256 "$OUT/fx_trace_music.csv" | awk '{print $1}')"
    echo "result=MATCH"
  } | tee "$OUT/equivalence.txt"
else
  echo "result=DIFF" | tee "$OUT/equivalence.txt" >&2
  diff "$OUT/ref_norm.csv" "$OUT/fx_norm.csv" | head -20 >&2
  exit 1
fi
