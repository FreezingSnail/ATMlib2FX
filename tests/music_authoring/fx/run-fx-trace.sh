#!/usr/bin/env bash
#
# run-fx-trace.sh - finite-v1 compact FX stream evidence lane (ATMlib2FX-3ii.3).
#
# For each authored fixture it:
#   1. builds the PROGMEM score and the pinned compact FX stream via
#      `tools/atm-music build` (original and selected backends);
#   2. compiles the *unmodified* library sources on the host twice - once for the
#      original PROGMEM engine (tools/music_authoring/preview/trace_main.c) and
#      once for the device compact decoder (this directory's
#      compact_trace_main.c, src/atm_synth.c with ATM_HAS_FX_COMPACT=1);
#   3. diffs the two tick CSV traces for the first through the terminal (stopped)
#      tick, dropping only the traversal-only `delay` column, proving
#      original-equivalent playback and terminal silence;
#   4. stresses the decoder's 32-byte ring: one service per music tick, a
#      controlled multi-tick service gap (the fixture's documented frame window)
#      swept over every alignment, and a high FX-section base address. All must
#      report zero underruns / zero format errors and max_window <= 32.
#
# Host diagnostic only: no AVR bytes, no git operations.  Identity is recorded
# as source/stream SHA-256 hashes.
#
# Usage: tests/music_authoring/fx/run-fx-trace.sh
set -euo pipefail

LANE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$LANE_DIR/../../.." && pwd)"
cd "$REPO_ROOT"

OUT="build/music-authoring/fx/lane"
SHIM="tools/music_authoring/preview/avr_shim"
CC="${CC:-cc}"
RING=32
HIGH_BASE="fff000"

mkdir -p "$OUT"
echo "compiler: $($CC --version | head -1)"

compile_trace() { # out_bin source_c
  "$CC" -std=c11 -O1 -w -I"$SHIM" -Isrc -I"$1" "$2" -o "$3"
}

norm() { # drop the traversal-only `delay` column
  awk -F, 'BEGIN{OFS=","}
           NR==1{for(i=1;i<=NF;i++) if($i!="delay") keep[i]=1}
           {out=""; for(i=1;i<=NF;i++) if(keep[i]) out=out (out==""?"":",") $i; print out}' "$1"
}

FIELD() { sed -n "s/.*$2=\([0-9]*\).*/\1/p" <<< "$1"; }

SUMMARY="$OUT/equivalence.txt"
: > "$SUMMARY"

check_fixture() { # name song.json service_ticks
  local name="$1" song="$2" service_ticks="$3"
  local dir="$OUT/$name"
  mkdir -p "$dir/progmem" "$dir/fx"

  echo "== $name =="
  tools/atm-music build "$song" --backend progmem --out "$dir/progmem" --json \
    > "$dir/progmem.json" 2> "$dir/progmem.stderr"
  tools/atm-music build "$song" --backend fx --out "$dir/fx" --json \
    > "$dir/fx.json" 2> "$dir/fx.stderr"
  echo "  $(cat "$dir/fx.stderr" | tr '\n' ' ')"

  compile_trace "$dir/progmem" tools/music_authoring/preview/trace_main.c "$dir/orig_trace"
  compile_trace src "$LANE_DIR/compact_trace_main.c" "$dir/compact_trace"

  # 1. one service per tick: original-equivalent trace + terminal silence.
  "$dir/orig_trace" 512 > "$dir/orig.csv"
  "$dir/compact_trace" "$dir/fx/stream.bin" 512 1 0 > "$dir/compact.csv" 2> "$dir/compact.stderr"
  cat "$dir/compact.stderr"
  norm "$dir/orig.csv" > "$dir/orig.norm.csv"
  norm "$dir/compact.csv" > "$dir/compact.norm.csv"
  if diff -q "$dir/orig.norm.csv" "$dir/compact.norm.csv" > /dev/null; then
    echo "  equivalence: MATCH (delay column dropped)"
  else
    echo "  equivalence: DIFF" >&2
    diff "$dir/orig.norm.csv" "$dir/compact.norm.csv" | head -30 >&2
    exit 1
  fi

  # 2. high FX-section base address: same trace through the descriptor arithmetic.
  "$dir/compact_trace" "$dir/fx/stream.bin" 512 1 0 "$HIGH_BASE" > "$dir/compact_high.csv" 2> /dev/null
  if cmp -s "$dir/compact.csv" "$dir/compact_high.csv"; then
    echo "  high base 0x$HIGH_BASE: MATCH"
  else
    echo "  high base 0x$HIGH_BASE: DIFF" >&2
    exit 1
  fi

  # 3. ring/service stress: controlled multi-tick gap swept over all alignments.
  local stress_ok=1
  for se in 1 "$service_ticks"; do
    local phases=$(( se > 1 ? se : 1 ))
    for (( ph=0; ph<phases; ph++ )); do
      local line
      line=$("$dir/compact_trace" "$dir/fx/stream.bin" 3000 "$se" "$ph" 2>&1 >/dev/null \
             | grep '^compact trace:')
      local u e w
      u=$(FIELD "$line" underruns); e=$(FIELD "$line" error); w=$(FIELD "$line" max_window)
      if [ "$u" != 0 ] || [ "$e" != 0 ] || [ "$w" -gt "$RING" ]; then
        echo "  STRESS FAIL se=$se phase=$ph: $line" >&2
        stress_ok=0
      fi
    done
  done
  if [ "$stress_ok" = 1 ]; then
    echo "  ring/service stress: OK (service=1 and service=$service_ticks, all phases; zero underruns; max_window <= $RING)"
  else
    exit 1
  fi

  {
    echo "fixture=$name"
    echo "song_sha256=$(shasum -a 256 "$song" | awk '{print $1}')"
    echo "stream_sha256=$(shasum -a 256 "$dir/fx/stream.bin" | awk '{print $1}')"
    echo "stream_bytes=$(wc -c < "$dir/fx/stream.bin" | tr -d ' ')"
    echo "orig_trace_sha256=$(shasum -a 256 "$dir/orig.csv" | awk '{print $1}')"
    echo "compact_trace_sha256=$(shasum -a 256 "$dir/compact.csv" | awk '{print $1}')"
    echo "normalized_sha256=$(shasum -a 256 "$dir/compact.norm.csv" | awk '{print $1}')"
    echo "service_ticks=$service_ticks"
    echo "result=MATCH"
  } >> "$SUMMARY"
}

check_fixture basic  examples/music_authoring/fx/basic/song.json  1
check_fixture stress examples/music_authoring/fx/stress/song.json 6

echo
echo "evidence written to $OUT (summary: $SUMMARY)"
