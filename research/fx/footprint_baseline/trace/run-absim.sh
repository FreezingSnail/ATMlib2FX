#!/usr/bin/env bash
#
# run-absim.sh - run fixture images against the LOCAL absim emulator core
# (built from the Ardens source tree under ../../ardens) to obtain
# device-accurate USB-CDC serial output and the emulator's stack high-water
# (`min_stack`, the lowest stack pointer reached).
#
# This is a host diagnostic. It does not modify the Ardens tree and contributes
# no AVR bytes. It complements run-trace.sh (behavioural reference trace).
#
# Usage: research/fx/footprint_baseline/trace/run-absim.sh
set -uo pipefail

TRACE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$TRACE_DIR/../../../.." && pwd)"
cd "$REPO_ROOT"

ARDENS_ROOT="${ARDENS_ROOT:-}"
if [ -z "$ARDENS_ROOT" ]; then
  for cand in "$REPO_ROOT/../../ardens" "$HOME/code/arduboy/Ardens" "$HOME/code/Ardens" "$HOME/code/ardens"; do
    [ -d "$cand/src" ] && [ -f "$cand/build/libardensdebuggerlib.a" ] && { ARDENS_ROOT="$cand"; break; }
  done
fi
if [ -z "$ARDENS_ROOT" ]; then
  echo "Ardens source/build not found; set ARDENS_ROOT" >&2
  exit 1
fi
echo "Ardens root: $ARDENS_ROOT ($(git -C "$ARDENS_ROOT" rev-parse --short HEAD 2>/dev/null))"

OUT="build/fx-port/trace"
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
  "$TRACE_DIR/absim_harness.cpp" \
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
bss_of() { "$AVR_BIN/avr-nm" "$1" | awk '/ __bss_end$/{print "0x"$1}'; }

echo
echo "== serial-capture sanity (Ardens tests/serial_cdc) =="
SC="$ARDENS_ROOT/tests/serial_cdc/serial_cdc.ino-arduboy-fx.hex"
if [ -f "$SC" ]; then
  EMIT_SERIAL=1 "$BIN" "$SC" 6000 2>&1 | tr '\n' ' '; echo
else
  echo "missing $SC"
fi

echo
echo "== production variants: emulator stack high-water (12 s) =="
for m in shell music music_sfx fx_control; do
  elf="build/fx-port/avr-$m/footprint_baseline.ino.elf"
  if [ ! -f "$elf" ]; then echo "missing $elf (run research/fx/tools/measure-footprint.sh)"; continue; fi
  bss="$(bss_of "$elf")"
  printf '%-11s ' "$m"
  "$BIN" "$elf" 12000 "$bss" 2>&1 | tr '\n' ' '; echo
done

echo
echo "== diag variant: serial report + painted stack (20 s) =="
elf="build/fx-port/diag-out/diag.ino.elf"
if [ -f "$elf" ]; then
  bss="$(bss_of "$elf")"
  EMIT_SERIAL=1 "$BIN" "$elf" 20000 "$bss" 2> "$OUT/diag-absim-stderr.txt"
  echo "--- stderr ---"; cat "$OUT/diag-absim-stderr.txt"
else
  echo "missing $elf (build the diag sketch first)"
fi
