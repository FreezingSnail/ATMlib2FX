#!/usr/bin/env bash
#
# run-absim.sh - FX-aware absim runs for the compact stream spike
# (ATMlib2FX-hlh.5).
#
# Builds research/fx/fx_compact_spike/trace/absim_compact_harness.cpp against the
# local Ardens absim core (read-only; no Ardens edits, no git commands), loads
# the generated compact FX data image and runs the diagnostic images at authored
# tempo and requested tempo 255, plus the production image for stack high-water.
# Reports captured USB-CDC serial (diag counters) and emulator min_stack.
#
# Identity is recorded as file SHA-256 hashes, not git revisions.
#
# Usage: research/fx/fx_compact_spike/trace/run-absim.sh [ms]
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
echo "Ardens root: $ARDENS_ROOT (libardensdebuggerlib.a sha256 $(shasum -a 256 "$ARDENS_ROOT/build/libardensdebuggerlib.a" | awk '{print $1}'))"

OUT="build/fx-port/compact"
mkdir -p "$OUT"
BIN="$OUT/absim_compact_harness"

CXX="${CXX:-c++}"
LLVM="$ARDENS_ROOT/build/_deps/llvm-project-build/lib"

echo "building absim_compact_harness..."
"$CXX" -std=gnu++17 -O2 -DNDEBUG -DARDENS_LLVM -DMINIZ_STATIC_DEFINE \
  -I"$ARDENS_ROOT/src" \
  -I"$ARDENS_ROOT/deps/bitsery/include" \
  -I"$ARDENS_ROOT/deps/miniz" \
  -I"$ARDENS_ROOT/build/deps/miniz" \
  -I"$ARDENS_ROOT/deps/fmt/include" \
  -isystem "$ARDENS_ROOT/deps" \
  -isystem "$ARDENS_ROOT/build/_deps/llvm-project-build/include" \
  -isystem "$ARDENS_ROOT/build/_deps/llvm-project-src/llvm/include" \
  "$TRACE_DIR/absim_compact_harness.cpp" \
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

run_diag compact_diag      "$OUT/avr-compact_diag/fx_compact_spike.ino.elf"      "$OUT/fxdata_compact.bin"      "$MS"
run_diag compact_diag_t255 "$OUT/avr-compact_diag_t255/fx_compact_spike.ino.elf" "$OUT/fxdata_compact_t255.bin" "$MS"

# Production image: no serial report, fixed run for stack high-water.
prod="$OUT/avr-compact/fx_compact_spike.ino.elf"
if [ -f "$prod" ]; then
  echo "== compact production (ms=$MS) ==" | tee -a "$RESULT"
  bss="$(bss_of "$prod")"
  "$BIN" "$prod" "$MS" "$bss" "$OUT/fxdata_compact.bin" 2> "$OUT/compact.absim.stderr"
  cat "$OUT/compact.absim.stderr"
  grep -E 'min_stack|headroom' "$OUT/compact.absim.stderr" | tee -a "$RESULT"
fi

echo
echo "results: $RESULT"
