#!/usr/bin/env bash
#
# run-trace.sh - host equivalence check for the compact directly-consumed FX
# stream (ATMlib2FX-hlh.5).
#
# Builds the device decoder on the host (src/atm_synth.c with
# ATM_HAS_FX_COMPACT=1) and the converter, generates the compact stream, drives
# the decoder at the baseline's timer contract, and compares the first 512 music
# ticks against the original reference trace from ATMlib2FX-hlh.1
# (research/fx/footprint_baseline/trace/reference/reference_trace_music.csv).
#
# Two traversal-only columns are dropped from both sides before the diff:
#   cN_ps    - per-channel pattern-stack index (removed by the backend)
#   cN_delay - per-channel command delay; in this backend the stream itself
#              schedules command timing, and no effect/oscillator path reads
#              ch->delay (verified in src/).
# Every other column - oscillator parameters, live effect state, tempo and the
# active-channel flags - must match exactly.
#
# Usage: research/fx/fx_compact_spike/trace/run-trace.sh [ticks]
set -euo pipefail

TRACE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$TRACE_DIR/../../../.." && pwd)"
cd "$REPO_ROOT"

TICKS="${1:-512}"
OUT="build/fx-port/compact"
REF="$REPO_ROOT/research/fx/footprint_baseline/trace/reference/reference_trace_music.csv"
SHIM="$REPO_ROOT/research/fx/fx_stream_spike/trace/avr_shim"
CC="${CC:-cc}"

mkdir -p "$OUT"

echo "compiler: $($CC --version | head -1)"
echo "ticks=$TICKS"

# 1. converter + gap-codec boundary self-test + stream
"$CC" -std=c11 -O2 -Wall -Wextra -Wno-unused-parameter \
  -Isrc -Iexamples/arduino/songs/song01_sfx research/fx/tools/fx_compact_spike/fx_compile_compact.c \
  -o "$OUT/compact_conv"
"$OUT/compact_conv" --selftest
"$OUT/compact_conv" --out "$OUT/compact_stream.bin" 2> "$OUT/compact_stream.log"
cat "$OUT/compact_stream.log"

# 2. host decoder harness + format/rejection tests
"$CC" -std=c11 -O1 -w \
  -I"$SHIM" -Isrc \
  "$TRACE_DIR/trace_main.c" -o "$OUT/trace_main"
"$CC" -std=c11 -O1 -w \
  -I"$SHIM" -Isrc \
  "$TRACE_DIR/compact_format_test.c" -o "$OUT/compact_format_test"
"$OUT/compact_format_test"

# tempo-255 stream for the no-service-window stress (actual 2000/7 Hz)
"$OUT/compact_conv" --out "$OUT/compact_stream_t255.bin" --tempo 255 2> "$OUT/compact_stream_t255.log"

# 3. run + determinism
"$OUT/trace_main" "$OUT/compact_stream.bin" "$TICKS" > "$OUT/compact_trace_music.csv" \
  2> "$OUT/compact_trace_music.stderr"
cat "$OUT/compact_trace_music.stderr"
"$OUT/trace_main" "$OUT/compact_stream.bin" "$TICKS" > "$OUT/compact_trace_music.2.csv" 2> /dev/null
cmp -s "$OUT/compact_trace_music.csv" "$OUT/compact_trace_music.2.csv" \
  && echo "determinism: OK (two runs identical)" \
  || { echo "determinism: FAILED" >&2; exit 1; }
rm -f "$OUT/compact_trace_music.2.csv"

# 4. compare, dropping the removed traversal columns
norm() {
  awk -F, 'NR==1{for(i=1;i<=NF;i++) if($i !~ /_ps$/ && $i !~ /_delay$/) keep[i]=1}
           {out=""; for(i=1;i<=NF;i++) if(keep[i]) out=out (i>1?",":"") $i; print out}' "$1"
}
norm "$REF" > "$OUT/ref_norm.csv"
norm "$OUT/compact_trace_music.csv" > "$OUT/compact_norm.csv"

if diff -q "$OUT/ref_norm.csv" "$OUT/compact_norm.csv" > /dev/null; then
  {
    echo "# compact FX stream equivalence (ATMlib2FX-hlh.5)"
    echo "ticks=$TICKS"
    echo "dropped_columns=cN_ps,cN_delay"
    echo "reference_sha256=$(shasum -a 256 "$REF" | awk '{print $1}')"
    echo "stream_sha256=$(shasum -a 256 "$OUT/compact_stream.bin" | awk '{print $1}')"
    echo "compact_trace_sha256=$(shasum -a 256 "$OUT/compact_trace_music.csv" | awk '{print $1}')"
    echo "result=MATCH"
  } | tee "$OUT/compact_equivalence.txt"
else
  echo "result=DIFF" | tee "$OUT/compact_equivalence.txt" >&2
  diff "$OUT/ref_norm.csv" "$OUT/compact_norm.csv" | head -20 >&2
  exit 1
fi

# 5. finite completion + service-window stress (host decoder)
#    max_window is the largest number of stream bytes the decoder consumed
#    between two service() calls; it must stay within the 32-byte ring.
RING=32
FIELD() { sed -n "s/.*$2=\([0-9]*\).*/\1/p" <<< "$1"; }
stress() { # label stream ticks service_every require_complete [phase]
  local label="$1" stream="$2" ticks="$3" se="$4" complete="$5" phase="${6:-0}"
  local line
  line=$("$OUT/trace_main" "$stream" "$ticks" "$se" "$phase" 2>&1 >/dev/null | grep '^compact trace: ticks=')
  echo "  [$label] $line"
  local u e w st
  u=$(FIELD "$line" underruns); e=$(FIELD "$line" error)
  w=$(FIELD "$line" max_window); st=$(FIELD "$line" stopped)
  [ "$u" = 0 ] || { echo "  FAIL: $label underruns=$u" >&2; exit 1; }
  [ "$e" = 0 ] || { echo "  FAIL: $label error=$e" >&2; exit 1; }
  [ "$w" -le "$RING" ] || { echo "  FAIL: $label max_window=$w > $RING" >&2; exit 1; }
  if [ "$complete" = 1 ]; then
    [ "$st" = 2113 ] || { echo "  FAIL: $label stop_tick=$st != 2113" >&2; exit 1; }
  fi
  echo "$label|$line" >> "$OUT/compact_stress.txt"
}

echo "service-window stress (whole song, host decoder):"
: > "$OUT/compact_stress.txt"
stress "authored service=1"      "$OUT/compact_stream.bin"      3000 1 1
stress "authored service=6"      "$OUT/compact_stream.bin"      3000 6 1
stress "t255 service=7"          "$OUT/compact_stream_t255.bin" 3000 7 1
stress "t255 service=8"          "$OUT/compact_stream_t255.bin" 3000 8 1
# Controlled 7-tick no-service window at tempo255 (2000/7 Hz): sweep every
# alignment so the true worst 7-tick window is exercised. All must have zero
# underruns and stay within the 32-byte ring.
for ph in 0 1 2 3 4 5 6; do
  stress "t255 7-tick window phase=$ph" "$OUT/compact_stream_t255.bin" 3000 7 1 "$ph"
done
echo "stress OK: zero underruns/errors, max_window <= $RING (results: $OUT/compact_stress.txt)"
