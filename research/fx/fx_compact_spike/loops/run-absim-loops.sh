#!/usr/bin/env bash
#
# run-absim-loops.sh - FX-aware absim run for the loop-capable compact stream
# (ATMlib2FX-hlh.8).
#
# Builds research/fx/fx_compact_spike/trace/absim_compact_harness.cpp against
# the local Ardens absim core (read-only; no Ardens edits, no git), loads the
# loop fixture FX data image and runs the loop diagnostic image. Reports the
# captured USB-CDC serial (diag counters) and the emulator stack high-water.
#
# Usage: research/fx/fx_compact_spike/loops/run-absim-loops.sh [ms]
set -uo pipefail

LOOPS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$LOOPS_DIR/../../../.." && pwd)"
cd "$REPO_ROOT"

MS="${1:-12000}"
ARDENS_ROOT="${ARDENS_ROOT:-}"
if [ -z "$ARDENS_ROOT" ]; then
  for cand in "$HOME/code/arduboy/Ardens" "$HOME/code/Ardens" "$REPO_ROOT/../Ardens"; do
    if [ -d "$cand/src" ] && [ -f "$cand/build/libardensdebuggerlib.a" ]; then
      ARDENS_ROOT="$cand"; break
    fi
  done
fi
if [ -z "$ARDENS_ROOT" ]; then
  echo "Ardens source/build not found; set ARDENS_ROOT" >&2
  exit 1
fi
echo "Ardens root: $ARDENS_ROOT"

OUT="build/fx-port/loops"
mkdir -p "$OUT"
BIN="$OUT/absim_loops_harness"

CXX="${CXX:-c++}"
LLVM="$ARDENS_ROOT/build/_deps/llvm-project-build/lib"
HARNESS="$REPO_ROOT/research/fx/fx_compact_spike/trace/absim_compact_harness.cpp"

echo "building absim_loops_harness..."
"$CXX" -std=gnu++17 -O2 -DNDEBUG -DARDENS_LLVM -DMINIZ_STATIC_DEFINE \
  -I"$ARDENS_ROOT/src" -I"$ARDENS_ROOT/deps/bitsery/include" \
  -I"$ARDENS_ROOT/deps/miniz" -I"$ARDENS_ROOT/build/deps/miniz" \
  -I"$ARDENS_ROOT/deps/fmt/include" \
  -isystem "$ARDENS_ROOT/deps" \
  -isystem "$ARDENS_ROOT/build/_deps/llvm-project-build/include" \
  -isystem "$ARDENS_ROOT/build/_deps/llvm-project-src/llvm/include" \
  "$HARNESS" \
  "$ARDENS_ROOT/build/libardensdebuggerlib.a" \
  "$ARDENS_ROOT/build/deps/miniz/libminiz.a" \
  "$ARDENS_ROOT/build/deps/fmt/libfmt.a" \
  "$LLVM/libLLVMDebugInfoDWARF.a" "$LLVM/libLLVMObject.a" \
  "$LLVM/libLLVMIRReader.a" "$LLVM/libLLVMBitReader.a" \
  "$LLVM/libLLVMAsmParser.a" "$LLVM/libLLVMCore.a" "$LLVM/libLLVMRemarks.a" \
  "$LLVM/libLLVMBitstreamReader.a" "$LLVM/libLLVMMCParser.a" "$LLVM/libLLVMMC.a" \
  "$LLVM/libLLVMDebugInfoCodeView.a" "$LLVM/libLLVMTextAPI.a" \
  "$LLVM/libLLVMBinaryFormat.a" "$LLVM/libLLVMTargetParser.a" \
  "$LLVM/libLLVMSupport.a" -lm "$LLVM/libLLVMDemangle.a" \
  -o "$BIN" || { echo "harness build failed" >&2; exit 1; }

AVR_BIN="$HOME/Library/Arduino15/packages/arduino/tools/avr-gcc/7.3.0-atmel3.6.1-arduino7/bin"
bss_of() { "$AVR_BIN/avr-nm" "$1" | awk '/ __bss_end$/{print "0x"$1}'; }

ELF="$OUT/avr-loop_dg/fx_compact_spike.ino.elf"
FXDATA="$OUT/fxdata_loops.bin"
RESULT="$OUT/absim-loops.txt"
if [ ! -f "$ELF" ] || [ ! -f "$FXDATA" ]; then
  echo "missing $ELF or $FXDATA (run research/fx/tools/build-fx-loops.sh first)" | tee "$RESULT"
  exit 1
fi
# When the lane supplies the hash of the image it just built, refuse to run a
# stale/mismatched ELF: the device bullet must describe the fresh loop build.
EXPECTED_SHA="${LOOP_ABSIM_EXPECTED_ELF_SHA256:-}"
if [ -n "$EXPECTED_SHA" ]; then
  ACTUAL_SHA=$(shasum -a 256 "$ELF" | awk '{print $1}')
  if [ "$ACTUAL_SHA" != "$EXPECTED_SHA" ]; then
    {
      echo "stale ELF: $ELF"
      echo "expected_sha256=$EXPECTED_SHA"
      echo "actual_sha256=$ACTUAL_SHA"
    } | tee "$RESULT"
    exit 1
  fi
  echo "elf_sha256=$ACTUAL_SHA (matches fresh lane build)"
fi
bss="$(bss_of "$ELF")"
echo "== loop_dg (ms=$MS, elf=$ELF, fxdata=$FXDATA) ==" | tee "$RESULT"
EMIT_SERIAL=1 "$BIN" "$ELF" "$MS" "$bss" "$FXDATA" \
  2> "$OUT/loop_dg.absim.stderr" | tee "$OUT/loop_dg.serial.txt"
echo "--- stderr ---"; cat "$OUT/loop_dg.absim.stderr"
{ echo "serial: $(tr -d '\r' < "$OUT/loop_dg.serial.txt" | tr '\n' ' ')"; \
  grep -E 'min_stack|headroom' "$OUT/loop_dg.absim.stderr"; } | tee -a "$RESULT"
echo
echo "results: $RESULT"
