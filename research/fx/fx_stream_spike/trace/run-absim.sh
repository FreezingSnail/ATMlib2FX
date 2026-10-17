#!/usr/bin/env bash
#
# run-absim.sh - FX-aware absim runs for the compiled stream spike
# (ATMlib2FX-aoe).
#
# Builds research/fx/fx_stream_spike/trace/absim_fx_harness.cpp against the local
# Ardens absim core (read-only, no Ardens edits), loads the generated FX data
# image and runs the diag images at authored tempo and requested tempo 255.
# Reports captured USB-CDC serial (diag counters) and emulator min_stack.
#
# Host diagnostic only; contributes no AVR bytes.
#
# Usage: research/fx/fx_stream_spike/trace/run-absim.sh [ms]
set -uo pipefail

TRACE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$TRACE_DIR/../../../.." && pwd)"
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
echo "Ardens root: $ARDENS_ROOT ($(git -C "$ARDENS_ROOT" rev-parse --short HEAD 2>/dev/null))"

OUT="build/fx-port/fx-stream"
mkdir -p "$OUT"
BIN="$OUT/absim_fx_harness"

CXX="${CXX:-c++}"
LLVM="$ARDENS_ROOT/build/_deps/llvm-project-build/lib"

echo "building absim_fx_harness..."
"$CXX" -std=gnu++17 -O2 -DNDEBUG -DARDENS_LLVM -DMINIZ_STATIC_DEFINE \
  -I"$ARDENS_ROOT/src" \
  -I"$ARDENS_ROOT/deps/bitsery/include" \
  -I"$ARDENS_ROOT/deps/miniz" \
  -I"$ARDENS_ROOT/build/deps/miniz" \
  -I"$ARDENS_ROOT/deps/fmt/include" \
  -isystem "$ARDENS_ROOT/deps" \
  -isystem "$ARDENS_ROOT/build/_deps/llvm-project-build/include" \
  -isystem "$ARDENS_ROOT/build/_deps/llvm-project-src/llvm/include" \
  "$TRACE_DIR/absim_fx_harness.cpp" \
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

RESULT="$OUT/absim-results.txt"
: > "$RESULT"

run_diag() { # name elf fxdata ms
  local name="$1" elf="$2" fxdata="$3" ms="$4"
  if [ ! -f "$elf" ]; then echo "missing $elf" | tee -a "$RESULT"; return; fi
  if [ ! -f "$fxdata" ]; then echo "missing $fxdata" | tee -a "$RESULT"; return; fi
  local bss; bss="$(bss_of "$elf")"
  echo "== $name (ms=$ms, elf=$elf, fxdata=$fxdata) ==" | tee -a "$RESULT"
  EMIT_SERIAL=1 "$BIN" "$elf" "$ms" "$bss" "$fxdata" \
    2> "$OUT/$name.absim.stderr" | tee "$OUT/$name.serial.txt"
  echo "--- stderr ---"; cat "$OUT/$name.absim.stderr"
  { echo "serial: $(tr -d '\r' < "$OUT/$name.serial.txt" | tr '\n' ' ')"; \
    grep -E 'min_stack|headroom' "$OUT/$name.absim.stderr"; } | tee -a "$RESULT"
  echo
}

run_diag fx_diag      "$OUT/avr-fx_diag/fx_stream_spike.ino.elf"      "$OUT/fxdata_spike.bin"      "$MS"
run_diag fx_diag_t255 "$OUT/avr-fx_diag_t255/fx_stream_spike.ino.elf" "$OUT/fxdata_spike_t255.bin" "$MS"

# Production image: no serial report, fixed run for stack high-water.
prod="$OUT/avr-fx_stream/fx_stream_spike.ino.elf"
if [ -f "$prod" ]; then
  echo "== fx_stream production (ms=$MS) ==" | tee -a "$RESULT"
  bss="$(bss_of "$prod")"
  "$BIN" "$prod" "$MS" "$bss" "$OUT/fxdata_spike.bin" 2> "$OUT/fx_stream.absim.stderr"
  cat "$OUT/fx_stream.absim.stderr"
  grep -E 'min_stack|headroom' "$OUT/fx_stream.absim.stderr" | tee -a "$RESULT"
fi

echo
echo "results: $RESULT"
