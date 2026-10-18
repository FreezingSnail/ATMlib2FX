#!/usr/bin/env bash
#
# run-loops.sh - host loop-equivalence lane for ATMlib2FX-hlh.8.
#
# For each loop fixture under research/fx/fx_compact_spike/loops/:
#   1. convert the score to a loop-capable compact stream (fx_pack --loops);
#   2. trace the *unmodified* original engine (orig_trace.c, the library core
#      compiled against the timer shim) and the compact loop decoder
#      (compact_trace.c, ATM_HAS_FX_COMPACT + ATM_FX_COMPACT_LOOP) on the host;
#   3. drop the traversal-only columns (cN_ps, cN_delay, cN_lp) and diff.
#
# Then runs the intro/loop demo: the compact trace keeps looping (never stops),
# with zero underruns, and consecutive loop cycles are identical.
#
# Outputs land under build/fx-port/loops/. No git and no network.
#
# Usage: research/fx/fx_compact_spike/loops/run-loops.sh [ticks]
set -euo pipefail

LOOPS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$LOOPS_DIR/../../../.." && pwd)"
cd "$REPO_ROOT"

TICKS="${1:-96}"
# Power-of-two ring; 32 B matches the frozen evidence AVR build
# (build-fx-loops.sh LOOP_RING and src/atm_fx_compact.h).
RING=32
OUT="build/fx-port/loops"
SHIM="research/fx/fx_stream_spike/trace/avr_shim"
CC="${CC:-cc}"
CASES="sync target extrapass"

mkdir -p "$OUT"

echo "== compact loop equivalence (ATMlib2FX-hlh.8) =="
echo "repo  : $REPO_ROOT"
echo "cc    : $($CC --version 2>/dev/null | head -1)"
echo "ticks : $TICKS"
echo

# ---- build converter + harnesses ------------------------------------------
make -C tools/fx_pack CC="$CC" > "$OUT/build-pack.log"
"$CC" -std=c11 -O1 -w -DATM_FX_COMPACT_RING="$RING" -I"$LOOPS_DIR" -I"$SHIM" -Isrc \
  "$LOOPS_DIR/compact_trace.c" -o "$OUT/compact_trace"

norm() { # drop traversal-only columns
  awk -F, 'NR==1{for(i=1;i<=NF;i++) if($i !~ /_ps$/ && $i !~ /_delay$/ && $i !~ /_lp$/) keep[i]=1}
           {out=""; for(i=1;i<=NF;i++) if(keep[i]) out=out (i>1?",":"") $i; print out}' "$1"
}

: > "$OUT/loop-equivalence.txt"
overall=0

for c in $CASES; do
  echo "-- case $c --"
  "$CC" -std=c11 -O1 -w -I"$LOOPS_DIR/$c" -I"$LOOPS_DIR" -I"$SHIM" -Isrc \
    "$LOOPS_DIR/orig_trace.c" -o "$OUT/orig_trace_$c"
  ./build/fx-port/pack/fx_pack \
    --song "$LOOPS_DIR/$c/song.h" --symbol score --loops --ring "$RING" \
    --ticks 2048 --out "$OUT/$c.stream.bin" --meta "$OUT/$c.meta.json" \
    --workdir "$OUT/work-$c" > "$OUT/$c.window.txt" 2> "$OUT/$c.convert.log"
  cat "$OUT/$c.convert.log"
  "$OUT/orig_trace_$c" "$TICKS" > "$OUT/$c.orig.csv" 2> "$OUT/$c.orig.err"
  cat "$OUT/$c.orig.err"
  "$OUT/compact_trace" "$OUT/$c.stream.bin" "$TICKS" \
    > "$OUT/$c.compact.csv" 2> "$OUT/$c.compact.err"
  cat "$OUT/$c.compact.err"

  # determinism of both sides
  "$OUT/orig_trace_$c" "$TICKS" > "$OUT/$c.orig.2.csv" 2> /dev/null
  "$OUT/compact_trace" "$OUT/$c.stream.bin" "$TICKS" > "$OUT/$c.compact.2.csv" 2> /dev/null
  cmp -s "$OUT/$c.orig.csv" "$OUT/$c.orig.2.csv" || { echo "orig determinism FAILED" >&2; overall=1; }
  cmp -s "$OUT/$c.compact.csv" "$OUT/$c.compact.2.csv" || { echo "compact determinism FAILED" >&2; overall=1; }
  rm -f "$OUT/$c.orig.2.csv" "$OUT/$c.compact.2.csv"

  norm "$OUT/$c.orig.csv" > "$OUT/$c.orig.norm.csv"
  norm "$OUT/$c.compact.csv" > "$OUT/$c.compact.norm.csv"
  if diff -q "$OUT/$c.orig.norm.csv" "$OUT/$c.compact.norm.csv" > /dev/null; then
    {
      echo "# $c (ATMlib2FX-hlh.8)"
      echo "ticks=$TICKS"
      echo "dropped_columns=cN_ps,cN_delay,cN_lp"
      echo "score_sha256=$(shasum -a 256 "$LOOPS_DIR/$c/song.h" | awk '{print $1}')"
      echo "stream_sha256=$(shasum -a 256 "$OUT/$c.stream.bin" | awk '{print $1}')"
      echo "orig_trace_sha256=$(shasum -a 256 "$OUT/$c.orig.csv" | awk '{print $1}')"
      echo "compact_trace_sha256=$(shasum -a 256 "$OUT/$c.compact.csv" | awk '{print $1}')"
      echo "result=MATCH"
    } | tee "$OUT/$c.equivalence.txt" >> "$OUT/loop-equivalence.txt"
  else
    echo "result=DIFF" | tee "$OUT/$c.equivalence.txt" >> "$OUT/loop-equivalence.txt"
    diff "$OUT/$c.orig.norm.csv" "$OUT/$c.compact.norm.csv" | head -12 >&2
    overall=1
  fi
  echo
done

# ---- intro/loop demo -------------------------------------------------------
echo "-- intro/loop demo (extrapass): continuous loop, zero underruns --"
"$OUT/compact_trace" "$OUT/extrapass.stream.bin" 200 > "$OUT/demo.compact.csv" 2> "$OUT/demo.compact.err"
cat "$OUT/demo.compact.err"
DEMO_INTRO=$(sed -n 's/.*"intro_ticks": \([0-9]*\).*/\1/p' "$OUT/extrapass.meta.json")
DEMO_CYCLE=$(sed -n 's/.*"cycle_ticks": \([0-9]*\).*/\1/p' "$OUT/extrapass.meta.json")
# Behavioral columns only for the cycle comparison (drop tick/base too).
behav() {
  awk -F, 'NR==1{for(i=1;i<=NF;i++) if($i!="tick" && $i!="base" && $i !~ /_ps$/ && $i !~ /_delay$/ && $i !~ /_lp$/) keep[i]=1; next}
           {out=""; for(i=1;i<=NF;i++) if(keep[i]) out=out (i>1?",":"") $i; print out}' "$1"
}
behav "$OUT/demo.compact.csv" > "$OUT/demo.behav.csv"
# Cycle A = rows intro+1 .. intro+cycle; cycle B = the next cycle.
sed -n "$((DEMO_INTRO + 1)),$((DEMO_INTRO + DEMO_CYCLE))p" "$OUT/demo.behav.csv" > "$OUT/demo.cycleA.csv"
sed -n "$((DEMO_INTRO + DEMO_CYCLE + 1)),$((DEMO_INTRO + 2 * DEMO_CYCLE))p" "$OUT/demo.behav.csv" > "$OUT/demo.cycleB.csv"
if cmp -s "$OUT/demo.cycleA.csv" "$OUT/demo.cycleB.csv"; then
  DEMO=ok
else
  DEMO=failed
  overall=1
fi
LAST_ACTIVE=$(awk -F, '/^M,/{a=$5} END{print a}' "$OUT/demo.compact.csv")
{
  echo "# intro/loop demo (ATMlib2FX-hlh.8, extrapass)"
  echo "intro_ticks=$DEMO_INTRO"
  echo "cycle_ticks=$DEMO_CYCLE"
  echo "demo_ticks=200"
  echo "cycles_identical=$DEMO"
  echo "last_active_mask=$LAST_ACTIVE"
  echo "compact_trace_sha256=$(shasum -a 256 "$OUT/demo.compact.csv" | awk '{print $1}')"
} | tee "$OUT/demo-summary.txt"
grep -q 'underruns=0' "$OUT/demo.compact.err" || { echo "demo underruns present" >&2; overall=1; }
grep -q 'active=1' "$OUT/demo.compact.err" || { echo "demo stopped" >&2; overall=1; }

# ---- absim (optional; AVR device proof) ------------------------------------
if [ -f "$LOOPS_DIR/run-absim-loops.sh" ]; then
  echo
  echo "-- absim loop run --"
  if [ -n "${LOOP_ABSIM_EXPECTED_ELF_SHA256:-}" ]; then
    # Lane mode: the ELF hash is pinned to the image just built, so a stale
    # image (or mismatch) must fail the equivalence result, not be ignored.
    "$LOOPS_DIR/run-absim-loops.sh" 12000 \
      || { echo "absim loop run FAILED" >&2; overall=1; }
  else
    "$LOOPS_DIR/run-absim-loops.sh" 12000 || echo "absim step skipped/failed (non-fatal here)"
  fi
fi

echo
echo "result: $( [ $overall -eq 0 ] && echo ALL-MATCH || echo FAILURES )"
echo "evidence: $OUT"
exit "$overall"
