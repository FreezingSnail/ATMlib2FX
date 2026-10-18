#!/usr/bin/env bash
#
# run-absim.sh - absim device run for the compact control + SFX lane
# (ATMlib2FX-hlh.9).
#
# Builds the generic compact absim harness against the local Ardens absim core
# (read-only; no Ardens edits, no git commands), loads the control-lane FX data
# image and runs the diagnostic control image. The image plays the compact music
# stream and starts the independent-tempo PROGMEM SFX overlay once at
# FC_SFX_FRAME; the firmware reports the borrowed channel, the SFX tick count,
# the restore status and the music tick window over USB-CDC.
#
# Asserts the reference-trace semantics on-device: the SFX borrows OSC_CH_TWO,
# runs exactly 23 ticks at its own tempo, restores the borrowed voice, and the
# music keeps advancing with no underruns/errors.
#
# Usage: research/fx/fx_compact_spike/control/run-absim.sh [ms]
set -uo pipefail

CTRL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$CTRL_DIR/../../../.." && pwd)"
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
echo "Ardens root: $ARDENS_ROOT (lib sha256 $(shasum -a 256 "$ARDENS_ROOT/build/libardensdebuggerlib.a" | awk '{print $1}'))"

OUT="build/fx-port/control"
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
  "$REPO_ROOT/research/fx/fx_compact_spike/trace/absim_compact_harness.cpp" \
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
ELF="$OUT/avr-control_dg/fx_compact_spike.ino.elf"
FXDATA="$OUT/fxdata_control.bin"
[ -f "$ELF" ]   || { echo "missing $ELF (run build-fx-control.sh)" >&2; exit 1; }
[ -f "$FXDATA" ]|| { echo "missing $FXDATA (run build-fx-control.sh)" >&2; exit 1; }

BSS="$("$AVR_BIN/avr-nm" "$ELF" | awk '/ __bss_end$/{print "0x"$1}')"
RESULT="$OUT/absim-control.txt"
: > "$RESULT"
echo "== control_dg (ms=$MS, elf=$ELF) ==" | tee -a "$RESULT"
EMIT_SERIAL=1 "$BIN" "$ELF" "$MS" "$BSS" "$FXDATA" \
  2> "$OUT/control.absim.stderr" | tee "$OUT/control.serial.txt"
echo "--- stderr ---"; cat "$OUT/control.absim.stderr"
{ echo "serial: $(tr -d '\r' < "$OUT/control.serial.txt" | tr '\n' ' ')"; \
  grep -E 'min_stack|headroom' "$OUT/control.absim.stderr"; } | tee -a "$RESULT"

LINE="$(tr -d '\r' < "$OUT/control.serial.txt" | grep 'FCSFXDIAG' | tail -1)"
if [ -z "$LINE" ]; then
  echo "FAIL: no FCSFXDIAG report captured" >&2
  exit 1
fi
FIELD() { sed -n "s/.*$1=\([^ ]*\).*/\1/p" <<< "$LINE"; }
BORROW=$(FIELD borrow); SFXT=$(FIELD sfx_ticks); ROK=$(FIELD restore_ok)
START=$(FIELD start); STOP=$(FIELD stop); UE=$(FIELD error); UR=$(FIELD underruns)
echo "parsed: borrow=$BORROW sfx_ticks=$SFXT restore_ok=$ROK start=$START stop=$STOP underruns=$UR error=$UE"

fail=0
[ "$BORROW" = 2 ] || { echo "FAIL: borrowed channel $BORROW != 2 (OSC_CH_TWO)" >&2; fail=1; }
[ "$SFXT" = 23 ] || { echo "FAIL: sfx_ticks $SFXT != 23 (reference)" >&2; fail=1; }
[ "$ROK" = 1 ] || { echo "FAIL: restore_ok $ROK != 1" >&2; fail=1; }
[ "$UE" = 0 ] || { echo "FAIL: error $UE != 0" >&2; fail=1; }
[ "$UR" = 0 ] || { echo "FAIL: underruns $UR != 0" >&2; fail=1; }
[ "${START:-0}" -gt 0 ] || { echo "FAIL: sfx start tick $START not > 0" >&2; fail=1; }
[ "${STOP:-0}" -gt "${START:-0}" ] || { echo "FAIL: music did not advance during SFX (stop=$STOP start=$START)" >&2; fail=1; }
[ $fail -eq 0 ] && echo "absim control semantics: OK" | tee -a "$RESULT"
echo "results: $RESULT"
exit $fail
