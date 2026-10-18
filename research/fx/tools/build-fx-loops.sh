#!/usr/bin/env bash
#
# build-fx-loops.sh - reproducible lane for global-loop FX streams
# (ATMlib2FX-hlh.8).
#
# Produces, under build/fx-port/loops/ (a NEW lane; the compact/control/pack
# lanes are never overwritten):
#   - source identity hashes, snapshotted at lane start and re-checked with
#     `shasum -c` at lane end (frozen-source discipline)
#   - the loop selftests and the host loop-equivalence + demo runs
#   - a loop fixture FX data image (stream + deterministic stress bitmap)
#   - AVR images for the finite compact control and the loop-capable decoder,
#     with avr-size and ELF hashes
#   - a default-configuration regression: rebuild the hlh.1 music fixture (no
#     FX macros) and compare .text against the retained hlh.1 music ELF
#   - an absim device run of the loop image (if the Ardens core is available)
#   - a CSV summary and a SHA-256 evidence manifest
#
# No git commands and no network: identity is recorded as hashes.
#
# Usage: research/fx/tools/build-fx-loops.sh
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$REPO_ROOT"

FQBN="arduboy-homemade:avr:arduboy-fx"
SKETCH="research/fx/fx_compact_spike"
BASELINE_SKETCH="research/fx/footprint_baseline"
SONG_INC="examples/arduino/songs/song01_sfx"
LOOPS_DIR="research/fx/fx_compact_spike/loops"
LANE="build/fx-port"
OUT="$LANE/loops"
AVR_BIN="$HOME/Library/Arduino15/packages/arduino/tools/avr-gcc/7.3.0-atmel3.6.1-arduino7/bin"
AVR_SIZE="$AVR_BIN/avr-size"
AVR_NM="$AVR_BIN/avr-nm"
AVR_OBJCOPY="$AVR_BIN/avr-objcopy"
ARDUINO_CLI="${ARDUINO_CLI:-$(command -v arduino-cli)}"
CC="${CC:-cc}"
# Power of two (src/atm_fx_compact.h enforces it); 32 B is the pinned ring
# used by the loop evidence and the seed for run-loops.sh RING.
LOOP_RING=32
overall=0

mkdir -p "$OUT"
SUMMARY="$OUT/loops-summary.csv"

echo "== ATMlib2FX global-loop FX lane (ATMlib2FX-hlh.8) =="
echo "repo        : $REPO_ROOT"
echo "fqbn        : $FQBN"
echo "sketch      : $SKETCH"
echo "lane        : $OUT"
echo "arduino-cli : $($ARDUINO_CLI version 2>/dev/null)"
echo

# ---- 0. source identity + frozen-source snapshot ----------------------------
# Every lane input is hashed before any work; the snapshot is re-checked with
# `shasum -c` at the end, so evidence cannot come from mixed sources.
{
  echo "# source hashes (frozen-source identity; re-checked at lane end)"
  for f in src/atm_fx_compact.c src/atm_fx_compact.h src/atm_synth.c src/atm_synth.h \
           src/cmd_parse.c src/osc.c \
           tools/fx_pack/fx_encode.c tools/fx_pack/fx_encode.h tools/fx_pack/fx_pack.c \
           tools/fx_pack/fx_score.c tools/fx_pack/fx_score.h tools/fx_pack/Makefile \
           tests/fx_pack/fx_pack_selftest.c \
           tests/fx_pack/fx_loop_selftest.c tests/fx_pack/run-tests.sh \
           research/fx/fx_compact_spike/loops/orig_trace.c \
           research/fx/fx_compact_spike/loops/compact_trace.c \
           research/fx/fx_compact_spike/loops/loops_trace_common.h \
           research/fx/fx_compact_spike/loops/run-loops.sh \
           research/fx/fx_compact_spike/loops/run-absim-loops.sh \
           research/fx/fx_compact_spike/loops/sync/song.h \
           research/fx/fx_compact_spike/loops/target/song.h \
           research/fx/fx_compact_spike/loops/extrapass/song.h \
           research/fx/fx_compact_spike/trace/absim_compact_harness.cpp \
           research/fx/tools/fx_make_fxdata.c \
           research/fx/tools/build-fx-loops.sh \
           research/fx/fx_compact_spike/fx_compact_spike.ino; do
    shasum -a 256 "$f"
  done
} | tee "$OUT/source-hashes.start.txt"
cp -f "$OUT/source-hashes.start.txt" "$OUT/source-hashes.txt"

# ---- 1. loop fixture fxdata -------------------------------------------------
echo
echo "-- loop fixture FX data image --"
"$CC" -std=c11 -O2 -Wall -Wextra research/fx/tools/fx_make_fxdata.c -o "$OUT/fx_make_fxdata" || overall=1
"$OUT/fx_make_fxdata" --stream "$OUT/sync.stream.bin" --out "$OUT/fxdata_loops.bin" \
  > "$OUT/fxdata_loops.meta" || overall=1
cat "$OUT/fxdata_loops.meta"
SLEN=$(awk -F= '/^stream_len=/{print $2}' "$OUT/fxdata_loops.meta")
BITMAP=$(awk -F= '/^bitmap_offset=/{print $2}' "$OUT/fxdata_loops.meta")
PAGE=$(awk -F= '/^data_page=/{print $2}' "$OUT/fxdata_loops.meta")

# ---- 2. AVR images ----------------------------------------------------------
section_size() { "$AVR_SIZE" -A "$1" | awk -v s=".$2" '$1==s {print $2; found=1} END{if(!found) print 0}'; }

{
  echo "# ATMlib2FX global-loop FX summary (ATMlib2FX-hlh.8)"
  echo "# fqbn: $FQBN"
  echo "# no git: identity is the source hashes in source-hashes.txt"
  echo "# variant,mode,program,text,data,bss,sram,stream_bytes,elf_sha256,elf"
} > "$SUMMARY"

build_variant() { # name mode extra slen
  local name="$1" mode="$2" extra="$3" slen="$4"
  local build_path="$OUT/avr-$name"
  local out_dir="$OUT/out-$name"
  local log="$OUT/build-$name.log"
  local elf="$build_path/fx_compact_spike.ino.elf"
  local flags="-DFC_MODE=$mode -I$REPO_ROOT/$SONG_INC -DFC_FX_DATA_PAGE=$PAGE -DFC_BITMAP_OFFSET=$BITMAP -DFC_STREAM_OFFSET=0 -DFC_STREAM_LEN=$slen -DATM_HAS_FX_COMPACT=1 $extra"

  "$ARDUINO_CLI" compile \
    --fqbn "$FQBN" --library . \
    --build-path "$build_path" --output-dir "$out_dir" \
    --build-property "compiler.cpp.extra_flags=$flags" \
    --build-property "compiler.c.extra_flags=$flags" \
    --verbose "$SKETCH" > "$log" 2>&1
  local rc=$?
  if [ $rc -ne 0 ] || [ ! -f "$elf" ]; then
    echo "$name: BUILD FAILED - see $log" >&2
    tail -20 "$log" >&2
    overall=1
    return 1
  fi
  local text data bss program sram hash
  text=$(section_size "$elf" text)
  data=$(section_size "$elf" data)
  bss=$(section_size "$elf" bss)
  program=$((text + data))
  sram=$((data + bss))
  hash=$(shasum -a 256 "$elf" | awk '{print $1}')
  printf '%-12s %2d %7d %7d %6d %5d %6d %6s  %s\n' \
    "$name" "$mode" "$program" "$text" "$data" "$bss" "$sram" "$slen" "${hash:0:16}"
  echo "  elf: $elf"
  echo "$name,$mode,$program,$text,$data,$bss,$sram,$slen,$hash,$elf" >> "$SUMMARY"
}

echo
echo "-- AVR images (finite compact control vs loop-capable decoder) --"
echo "variant       md program    text   data   bss   sram stream  elf(sha16)"
echo "-----------------------------------------------------------------------"
build_variant finite   3 "" "$(wc -c < "$LANE/pack/song01_sfx/stream.bin" 2>/dev/null | tr -d ' ')" || true
build_variant loop     3 "-DATM_FX_COMPACT_LOOP=1 -DATM_FX_COMPACT_RING=$LOOP_RING" "$SLEN"
build_variant loop_dg  3 "-DATM_FX_COMPACT_LOOP=1 -DATM_FX_COMPACT_RING=$LOOP_RING -DATM_FX_COMPACT_DIAG=1" "$SLEN"

# The nested absim run in step 3 must use the loop_dg ELF built here, not a
# previous lane's image: pin its SHA-256 and let the device step verify it.
LOOP_DG_ELF="$OUT/avr-loop_dg/fx_compact_spike.ino.elf"
if [ -f "$LOOP_DG_ELF" ]; then
  LOOP_DG_ELF_SHA=$(shasum -a 256 "$LOOP_DG_ELF" | awk '{print $1}')
else
  LOOP_DG_ELF_SHA=""
  overall=1
fi

# ---- 3. host regression + loop selftest + equivalence + demo ---------------
# Runs after the AVR images so run-loops.sh's nested absim device bullet uses
# the freshly built loop_dg ELF; the expected hash makes a stale image fatal.
echo
echo "-- host regression, loop selftest and equivalence --"
tests/fx_pack/run-tests.sh > "$OUT/run-tests.log" 2>&1
rc=$?
tail -14 "$OUT/run-tests.log"
[ $rc -eq 0 ] || { echo "tests/fx_pack/run-tests.sh FAILED" >&2; overall=1; }

LOOP_ABSIM_EXPECTED_ELF_SHA256="$LOOP_DG_ELF_SHA" \
  research/fx/fx_compact_spike/loops/run-loops.sh 96 2>&1 | tee "$OUT/run-loops.log"
grep -q 'result: ALL-MATCH' "$OUT/run-loops.log" || { echo "loop equivalence FAILED" >&2; overall=1; }

# ---- 4. default-configuration regression ------------------------------------
echo
echo "-- default-configuration regression (no FX macros) --"
DEF_BUILD="$OUT/avr-default"
"$ARDUINO_CLI" compile \
  --fqbn "$FQBN" --library . \
  --build-path "$DEF_BUILD" --output-dir "$OUT/out-default" \
  --build-property "compiler.cpp.extra_flags=-DFP_AUDIO=1 -I$REPO_ROOT/$SONG_INC" \
  --verbose "$BASELINE_SKETCH" > "$OUT/build-default.log" 2>&1
DEF_ELF="$DEF_BUILD/footprint_baseline.ino.elf"
RET_ELF="$LANE/avr-music/footprint_baseline.ino.elf"
if [ -f "$DEF_ELF" ] && [ -f "$RET_ELF" ]; then
  "$AVR_OBJCOPY" -O binary --only-section=.text "$DEF_ELF" "$OUT/default.text.bin"
  "$AVR_OBJCOPY" -O binary --only-section=.text "$RET_ELF" "$OUT/retained-music.text.bin"
  if cmp -s "$OUT/default.text.bin" "$OUT/retained-music.text.bin"; then
    echo "default .text byte-identical to retained hlh.1 music ELF: OK"
    echo "default_text_identical=1" > "$OUT/default_regression.txt"
  else
    echo "default .text DIFFERS from retained hlh.1 music ELF" >&2
    echo "default_text_identical=0" > "$OUT/default_regression.txt"
    overall=1
  fi
  echo "default_text_sha256=$(shasum -a 256 "$OUT/default.text.bin" | awk '{print $1}')" >> "$OUT/default_regression.txt"
else
  echo "default regression: missing elf (def=$DEF_ELF ret=$RET_ELF)" >&2
  overall=1
fi

# ---- 5. absim device run (optional) -----------------------------------------
echo
echo "-- absim loop device run --"
if [ -f "$LOOPS_DIR/run-absim-loops.sh" ]; then
  LOOP_ABSIM_EXPECTED_ELF_SHA256="$LOOP_DG_ELF_SHA" \
    "$LOOPS_DIR/run-absim-loops.sh" 12000 \
    || { echo "absim step FAILED (stale or mismatched loop_dg ELF?)" >&2; overall=1; }
else
  echo "run-absim-loops.sh not present"
fi

# ---- 6. frozen-source re-check ----------------------------------------------
echo
echo "-- frozen-source check (start vs end) --"
if shasum -a 256 -c "$OUT/source-hashes.start.txt" > "$OUT/source-hashes.end.txt" 2>&1; then
  echo "sources unchanged during the lane: OK"
  echo "sources_frozen=1" > "$OUT/source-freeze.txt"
else
  echo "SOURCES CHANGED DURING THE LANE:" >&2
  grep -v ': OK$' "$OUT/source-hashes.end.txt" >&2
  echo "sources_frozen=0" > "$OUT/source-freeze.txt"
  overall=1
fi

# ---- 7. evidence manifest ---------------------------------------------------
echo
echo "-- evidence manifest --"
{
  for f in "$OUT/sync.stream.bin" "$OUT/target.stream.bin" "$OUT/extrapass.stream.bin" \
           "$OUT/sync.equivalence.txt" "$OUT/target.equivalence.txt" "$OUT/extrapass.equivalence.txt" \
           "$OUT/demo-summary.txt" "$OUT/fxdata_loops.bin" \
           "$OUT/run-loops.log" \
           "$OUT/source-hashes.start.txt" "$OUT/source-freeze.txt" \
           "$OUT/avr-loop/fx_compact_spike.ino.elf" \
           "$OUT/avr-loop_dg/fx_compact_spike.ino.elf"; do
    [ -f "$f" ] && shasum -a 256 "$f"
  done
} | tee "$OUT/evidence-sha256.txt"

echo
echo "summary: $SUMMARY"
exit "${overall:-0}"
