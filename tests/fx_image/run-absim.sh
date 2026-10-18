#!/usr/bin/env bash
#
# run-absim.sh - FX-aware absim run for a finite-v1 compact FX example image
# (ATMlib2FX-hlh.10).
#
# Adapted from the hlh.5 spike runner
# research/fx/fx_compact_spike/trace/run-absim.sh (read-only; not edited). It
# builds tests/fx_image/absim_harness.cpp against the local Ardens absim core
# (read-only; no Ardens edits, no git commands), loads the generated FX data
# image, and runs one ELF. It reports the captured USB-CDC diagnostic line and
# the emulator stack high-water, and fails if the build reports any underrun.
#
# Identity is recorded as file SHA-256 hashes, not git revisions.
#
# Usage: run-absim.sh <elf> <fxdata.bin> [ms]
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
cd "$REPO_ROOT"

if [ "$#" -lt 2 ]; then
  echo "usage: $0 <elf> <fxdata.bin> [ms]" >&2
  exit 2
fi
ELF="$1"
FXDATA="$2"
MS="${3:-12000}"

if [ ! -f "$ELF" ]; then echo "missing elf $ELF" >&2; exit 1; fi
if [ ! -f "$FXDATA" ]; then echo "missing fxdata $FXDATA" >&2; exit 1; fi

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
echo "Ardens root: $ARDENS_ROOT (libardensdebuggerlib.a sha256 $(shasum -a 256 "$ARDENS_ROOT/build/libardensdebuggerlib.a" | awk '{print $1}'))"

OUT="build/fx-port/image"
mkdir -p "$OUT"
BIN="$OUT/absim_harness"

CXX="${CXX:-c++}"
LLVM="$ARDENS_ROOT/build/_deps/llvm-project-build/lib"

echo "building absim_harness..."
"$CXX" -std=gnu++17 -O2 -DNDEBUG -DARDENS_LLVM -DMINIZ_STATIC_DEFINE \
  -I"$ARDENS_ROOT/src" \
  -I"$ARDENS_ROOT/deps/bitsery/include" \
  -I"$ARDENS_ROOT/deps/miniz" \
  -I"$ARDENS_ROOT/build/deps/miniz" \
  -I"$ARDENS_ROOT/deps/fmt/include" \
  -isystem "$ARDENS_ROOT/deps" \
  -isystem "$ARDENS_ROOT/build/_deps/llvm-project-build/include" \
  -isystem "$ARDENS_ROOT/build/_deps/llvm-project-src/llvm/include" \
  "$HERE/absim_harness.cpp" \
  "$ARDENS_ROOT/build/libardensdebuggerlib.a" \
  "$ARDENS_ROOT/build/deps/miniz/libminiz.a" \
  "$ARDENS_ROOT/build/deps/fmt/libfmt.a" \
  "$LLVM/libLLVMDebugInfoDWARF.a" \
  "$LLVM/libLLVMObject.a" \
  "$LLVM/libLLVMIRReader.a" \
  "$LLVM/libLLVMBitReader.a" \
  "$LLVM/libLLVMAsmParser.a" \
  "$LLVM/libLLVMCore.a" \
  "$LLVM/libLLVMRemarks.a" \
  "$LLVM/libLLVMBitstreamReader.a" \
  "$LLVM/libLLVMMCParser.a" \
  "$LLVM/libLLVMMC.a" \
  "$LLVM/libLLVMDebugInfoCodeView.a" \
  "$LLVM/libLLVMTextAPI.a" \
  "$LLVM/libLLVMBinaryFormat.a" \
  "$LLVM/libLLVMTargetParser.a" \
  "$LLVM/libLLVMSupport.a" \
  -lm "$LLVM/libLLVMDemangle.a" \
  -o "$BIN" || { echo "harness build failed" >&2; exit 1; }

AVR_BIN="$HOME/Library/Arduino15/packages/arduino/tools/avr-gcc/7.3.0-atmel3.6.1-arduino7/bin"
bss="$(  "$AVR_BIN/avr-nm" "$ELF" | awk '/ __bss_end$/{print "0x"$1}' )"

echo "== music_graphics (ms=$MS, elf=$ELF, fxdata=$FXDATA) =="
EMIT_SERIAL=1 "$BIN" "$ELF" "$MS" "$bss" "$FXDATA" \
  2> "$OUT/music_graphics.absim.stderr" | tee "$OUT/music_graphics.serial.txt"
echo "--- stderr ---"
cat "$OUT/music_graphics.absim.stderr"

SERIAL="$(tr -d '\r' < "$OUT/music_graphics.serial.txt" | tr '\n' ' ')"
echo "$SERIAL"
if ! printf '%s' "$SERIAL" | grep -q 'FXDIAG'; then
  echo "no FXDIAG line captured - build with -DATM_FX_COMPACT_DIAG=1" >&2
  exit 1
fi
if ! printf '%s' "$SERIAL" | grep -q 'underruns=0'; then
  echo "UNDERRUNS detected in $SERIAL" >&2
  exit 1
fi
if ! printf '%s' "$SERIAL" | grep -q 'error=0'; then
  echo "decoder error detected in $SERIAL" >&2
  exit 1
fi
echo "absim: zero underruns, zero error"
