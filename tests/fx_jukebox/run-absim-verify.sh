#!/usr/bin/env bash
#
# run-absim-verify.sh - end-to-end device evidence for the committed FX jukebox
# image (ATMlib2FX-hlh.15).
#
# Two independent checks over the *packed* image and its per-song streams:
#
#   1. Host device-decoder trace (research/fx/fx_compact_spike/loops/compact_trace.c,
#      the same streaming decoder the device runs) for intro + two full loop
#      cycles of one Creature Gatherer loop (overworld) and Snapdragon Sprint:
#      zero underruns / zero error, and consecutive loop cycles byte-identical
#      (the wrap repeats on the pinned period).
#   2. absim device run of the real examples/arduino/jukebox_fx sketch (built
#      with the documented FX flags + ring 64) against build/fx-jukebox/fxdata.bin,
#      started on each song, past intro + two full cycles. The one-shot FXDIAG
#      report must show zero underruns, zero error, stop_tick=0 and a tick count
#      beyond two cycles.
#
# Everything lands under build/fx-jukebox/verify/. No git, no network, no
# downloads; identity is recorded as SHA-256 hashes.
#
# Usage: tests/fx_jukebox/run-absim-verify.sh
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
cd "$REPO_ROOT"

OUT="build/fx-jukebox/verify"
IMAGE="build/fx-jukebox/fxdata.bin"
HOST_OUT="$OUT/host-trace"
APP_OUT="$OUT/absim"
mkdir -p "$OUT" "$HOST_OUT" "$APP_OUT"
LOG="$OUT/run.log"
: > "$LOG"
overall=0

CC="${CC:-cc}"
CXX="${CXX:-c++}"
ARDUINO_CLI="${ARDUINO_CLI:-$(command -v arduino-cli)}"
FQBN="arduboy-homemade:avr:arduboy-fx"
AVR_BIN="$HOME/Library/Arduino15/packages/arduino/tools/avr-gcc/7.3.0-atmel3.6.1-arduino7/bin"
AVR_NM="$AVR_BIN/avr-nm"
LOOPS="research/fx/fx_compact_spike/loops"
SHIM="research/fx/fx_stream_spike/trace/avr_shim"
HARNESS_SRC="tests/fx_image/absim_harness.cpp"
RING=64

# song id: catalog index: <name>
SONGS=("overworld:0" "snapdragon_sprint:20")

log() { echo "$@" | tee -a "$LOG"; }
fail() { echo "FAIL: $*" | tee -a "$LOG" >&2; overall=1; }

log "== FX jukebox device verification (ATMlib2FX-hlh.15) =="
log "repo : $REPO_ROOT"
log "image: $IMAGE ($(wc -c < "$IMAGE" | tr -d ' ') B)"
log "ring : $RING"
log "cli  : $("$ARDUINO_CLI" version 2>/dev/null)"

# ---- source/artifact identity ----------------------------------------------
{
  shasum -a 256 "$IMAGE" \
    examples/arduino/jukebox_fx/jukebox_fx_songs.h \
    examples/arduino/jukebox_fx/jukebox_fx.ino \
    build/fx-jukebox/meta.json build/fx-jukebox/songs.json \
    build/fx-jukebox/songs/overworld/stream.bin \
    build/fx-jukebox/songs/overworld/report.json \
    build/fx-jukebox/songs/snapdragon_sprint/stream.bin \
    build/fx-jukebox/songs/snapdragon_sprint/report.json \
    "$LOOPS/compact_trace.c" "$LOOPS/loops_trace_common.h"
} > "$OUT/source-hashes.txt"

# ---- 1. host device-decoder trace ------------------------------------------
log
log "-- 1. host decoder trace (streaming, ring $RING) --"
"$CC" -std=c11 -O1 -w -DATM_FX_COMPACT_RING=$RING -I"$LOOPS" -I"$SHIM" -Isrc \
  "$LOOPS/compact_trace.c" -o "$OUT/compact_trace_ring$RING" \
  || { fail "compact_trace build"; }

norm_behav() { # drop tick/base and the traversal-only columns
  awk -F, 'NR==1{for(i=1;i<=NF;i++) if($i!="tick" && $i!="base" && $i !~ /_ps$/ && $i !~ /_delay$/ && $i !~ /_lp$/) keep[i]=1}
           {out=""; for(i=1;i<=NF;i++) if(keep[i]) out=out (i>1?",":"") $i; print out}' "$1"
}

for entry in "${SONGS[@]}"; do
  song="${entry%%:*}"; index="${entry##*:}"
  report="build/fx-jukebox/songs/$song/report.json"
  stream="build/fx-jukebox/songs/$song/stream.bin"
  cycle=$(grep -m1 '"loop_cycle_ticks"' "$report" | tr -dc '0-9')
  ticks=$((3 * cycle)) # intro + two full loop cycles
  log "   $song (index $index): cycle=$cycle ticks, running $ticks ticks"
  "$OUT/compact_trace_ring$RING" "$stream" "$ticks" 1 \
    > "$HOST_OUT/$song.compact.csv" 2> "$HOST_OUT/$song.compact.err"
  cat "$HOST_OUT/$song.compact.err" | tee -a "$LOG"
  grep -q 'underruns=0' "$HOST_OUT/$song.compact.err" \
    && grep -q 'error=0' "$HOST_OUT/$song.compact.err" \
    && grep -q 'active=1' "$HOST_OUT/$song.compact.err" \
    || fail "$song host trace: underruns/error/active"

  norm_behav "$HOST_OUT/$song.compact.csv" > "$HOST_OUT/$song.behav.csv"
  sed -n "$((2 + cycle)),$((1 + 2 * cycle))p" "$HOST_OUT/$song.behav.csv" \
    > "$HOST_OUT/$song.cycle1.csv"
  sed -n "$((2 + 2 * cycle)),$((1 + 3 * cycle))p" "$HOST_OUT/$song.behav.csv" \
    > "$HOST_OUT/$song.cycle2.csv"
  if cmp -s "$HOST_OUT/$song.cycle1.csv" "$HOST_OUT/$song.cycle2.csv"; then
    echo "$song: two loop cycles byte-identical (wrap period = $cycle ticks)" \
      | tee "$HOST_OUT/$song.wrap-check.txt"
  else
    fail "$song host trace: consecutive loop cycles differ"
    echo "$song: loop cycles DIFFER" > "$HOST_OUT/$song.wrap-check.txt"
  fi
done

# ---- 2. absim device run ----------------------------------------------------
log
log "-- 2. absim device run (real sketch, packed image) --"

HARNESS_BIN=""
for cand in "$OUT/absim_harness" build/fx-port/image/absim_harness \
            build/fx-port/streaming-loop/absim_harness; do
  [ -x "$cand" ] && { HARNESS_BIN="$cand"; break; }
done

if [ -z "$HARNESS_BIN" ]; then
  ARDENS_ROOT="${ARDENS_ROOT:-$HOME/code/arduboy/Ardens}"
  LLVM="$ARDENS_ROOT/build/_deps/llvm-project-build/lib"
  log "   building absim_harness from $HARNESS_SRC"
  "$CXX" -std=gnu++17 -O2 -DNDEBUG -DARDENS_LLVM -DMINIZ_STATIC_DEFINE \
    -I"$ARDENS_ROOT/src" -I"$ARDENS_ROOT/deps/bitsery/include" \
    -I"$ARDENS_ROOT/deps/miniz" -I"$ARDENS_ROOT/build/deps/miniz" \
    -I"$ARDENS_ROOT/deps/fmt/include" -isystem "$ARDENS_ROOT/deps" \
    -isystem "$ARDENS_ROOT/build/_deps/llvm-project-build/include" \
    -isystem "$ARDENS_ROOT/build/_deps/llvm-project-src/llvm/include" \
    "$HARNESS_SRC" "$ARDENS_ROOT/build/libardensdebuggerlib.a" \
    "$ARDENS_ROOT/build/deps/miniz/libminiz.a" "$ARDENS_ROOT/build/deps/fmt/libfmt.a" \
    "$LLVM/libLLVMDebugInfoDWARF.a" "$LLVM/libLLVMObject.a" \
    "$LLVM/libLLVMIRReader.a" "$LLVM/libLLVMBitReader.a" "$LLVM/libLLVMAsmParser.a" \
    "$LLVM/libLLVMCore.a" "$LLVM/libLLVMRemarks.a" "$LLVM/libLLVMBitstreamReader.a" \
    "$LLVM/libLLVMMCParser.a" "$LLVM/libLLVMMC.a" \
    "$LLVM/libLLVMDebugInfoCodeView.a" "$LLVM/libLLVMTextAPI.a" \
    "$LLVM/libLLVMBinaryFormat.a" "$LLVM/libLLVMTargetParser.a" \
    "$LLVM/libLLVMSupport.a" -lm "$LLVM/libLLVMDemangle.a" \
    -o "$OUT/absim_harness" 2> "$APP_OUT/harness-build.err" \
    || { fail "absim harness build"; HARNESS_BIN=""; }
  [ -x "$OUT/absim_harness" ] && HARNESS_BIN="$OUT/absim_harness"
fi
log "   harness: ${HARNESS_BIN:-unavailable}"

: > "$APP_OUT/absim-summary.txt"

if [ -n "$HARNESS_BIN" ]; then
  for entry in "${SONGS[@]}"; do
    song="${entry%%:*}"; index="${entry##*:}"
    report="build/fx-jukebox/songs/$song/report.json"
    cycle=$(grep -m1 '"loop_cycle_ticks"' "$report" | tr -dc '0-9')
    rate=$(grep -m1 '"effective_tick_rate"' "$report" | tr -dc '0-9')
    needed=$((3 * cycle))
    # frames at 60 fps to clear intro + two cycles, ~5% margin; ms budget +15%.
    frame=$(awk -v c="$cycle" -v r="$rate" 'BEGIN{printf "%d", int(3*c/r*60*1.05)+2}')
    ms=$(awk -v c="$cycle" -v r="$rate" 'BEGIN{printf "%d", int(3*c/r*1000*1.15)+1000}')
    flags="-DATM_HAS_FX_COMPACT=1 -DATM_FX_COMPACT_LOOP=1 -DATM_FX_COMPACT_RING=$RING -DATM_FX_COMPACT_DIAG=1 -DJUKEBOX_FX_START_SONG=$index -DFX_REPORT_FRAME=$frame"
    build_path="$OUT/avr-$song"; out_dir="$OUT/out-$song"
    log "   $song: start=$index report_frame=$frame absim_ms=$ms (need >= $needed ticks)"
    "$ARDUINO_CLI" compile --fqbn "$FQBN" --library . \
      --build-path "$build_path" --output-dir "$out_dir" \
      --build-property "compiler.cpp.extra_flags=$flags" \
      --build-property "compiler.c.extra_flags=$flags" \
      examples/arduino/jukebox_fx > "$OUT/build-$song.log" 2>&1
    elf="$build_path/jukebox_fx.ino.elf"
    if [ ! -f "$elf" ]; then
      fail "$song sketch build (see $OUT/build-$song.log)"
      continue
    fi
    bss=$("$AVR_NM" "$elf" | awk '/ __bss_end$/{print "0x"$1}')
    # Emit the full serial stream: USB-CDC bytes arrive asynchronously, so
    # STOP_ON_SERIAL would truncate the one-shot FXDIAG line mid-print.
    EMIT_SERIAL=1 "$HARNESS_BIN" "$elf" "$ms" "$bss" "$IMAGE" \
      > "$APP_OUT/$song.serial.txt" 2> "$APP_OUT/$song.absim.stderr"
    serial="$(tr -d '\r' < "$APP_OUT/$song.serial.txt" | tr '\n' ' ')"
    log "   $song serial: $serial"
    cat "$APP_OUT/$song.absim.stderr" | tee -a "$LOG"
    echo "$song: $serial" >> "$APP_OUT/absim-summary.txt"
    ! printf '%s' "$serial" | grep -q 'FXDIAG' && fail "$song absim: no FXDIAG"
    ! printf '%s' "$serial" | grep -q 'underruns=0' && fail "$song absim: underruns"
    ! printf '%s' "$serial" | grep -q 'error=0' && fail "$song absim: decoder error"
    ! printf '%s' "$serial" | grep -q 'stop_tick=0' && fail "$song absim: stopped"
    ticks_seen="$(printf '%s' "$serial" | sed -n 's/.*ticks=\([0-9]*\).*/\1/p')"
    if [ -n "$ticks_seen" ] && [ "$ticks_seen" -ge "$needed" ]; then
      echo "$song: ticks=$ticks_seen >= $needed (intro + two cycles) OK" | tee -a "$LOG"
    else
      fail "$song absim: ticks=${ticks_seen:-?} < $needed"
    fi
  done
else
  log "   absim harness unavailable; host trace only (documented)"
fi

# ---- 3. documented sketch sizes --------------------------------------------
log
log "-- 3. documented sketch sizes (ring $RING) --"
for variant in prod diag; do
  flags="-DATM_HAS_FX_COMPACT=1 -DATM_FX_COMPACT_LOOP=1 -DATM_FX_COMPACT_RING=$RING"
  [ "$variant" = diag ] && flags="$flags -DATM_FX_COMPACT_DIAG=1"
  "$ARDUINO_CLI" compile --fqbn "$FQBN" --library . \
    --build-path "$OUT/avr-$variant" --output-dir "$OUT/out-$variant" \
    --build-property "compiler.cpp.extra_flags=$flags" \
    --build-property "compiler.c.extra_flags=$flags" \
    examples/arduino/jukebox_fx > "$OUT/compile-$variant.txt" 2>&1
  tail -2 "$OUT/compile-$variant.txt" | tee -a "$LOG"
done

# ---- evidence manifest ------------------------------------------------------
log
log "-- evidence manifest --"
{
  echo "# FX jukebox verification artifacts (ATMlib2FX-hlh.15)"
  shasum -a 256 "$IMAGE" \
    examples/arduino/jukebox_fx/jukebox_fx_songs.h \
    "$OUT/source-hashes.txt" 2>/dev/null
  for f in "$HOST_OUT"/*.csv "$HOST_OUT"/*.err "$HOST_OUT"/*.wrap-check.txt \
           "$APP_OUT"/*.txt "$APP_OUT"/*.stderr "$APP_OUT/absim-summary.txt"; do
    [ -f "$f" ] && shasum -a 256 "$f"
  done
} > "$OUT/evidence-sha256.txt"
cat "$OUT/evidence-sha256.txt" | tee -a "$LOG"

log
log "evidence: $OUT"
exit "${overall:-0}"
