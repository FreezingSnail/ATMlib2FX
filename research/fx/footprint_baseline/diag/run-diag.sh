#!/usr/bin/env bash
#
# run-diag.sh - diagnostic emulator run for ATMlib2FX-hlh.1 (stack probe).
#
# Builds research/fx/footprint_baseline/diag (music+SFX shell that paints free
# SRAM, runs a fixed number of frames, then reports stack high-water and a live
# oscillator/tempo snapshot over USB CDC serial) into the build/fx-port lane and
# attempts to capture that serial with the installed Ardens emulator.
#
# This is a DIAGNOSTIC build. It is not used for flash/SRAM size numbers.
#
# Findings on this machine (2026-10-16, Ardens v0.25.9):
#   * headless execution works and proves the fixture runs (profiledump shows
#     the audio Timer3 ISR and display code consuming cycles);
#   * neither `--headless=<ms> <hex>` nor `--captureserial=<ms> <hex>` emits the
#     sketch's USB CDC bytes: headless produces 0 bytes, captureserial does not
#     terminate (watchdog-killed).
#   * RESOLVED: the same image is read correctly through the local absim core
#     via trace/run-absim.sh (USB CDC + stack high-water). This script is kept
#     only to document the Ardens CLI limitation.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
cd "$REPO_ROOT"

FQBN="arduboy-homemade:avr:arduboy-fx"
LANE="build/fx-port"
ARDENS="${ARDENS:-$HOME/Applications/CreatureGathererTools/bin/Ardens}"
ARDUBOY_CLI="${ARDUBOY_CLI:-$(command -v arduino-cli)}"
WATCHDOG_SECS="${WATCHDOG_SECS:-60}"

mkdir -p "$LANE"

echo "== build diag sketch =="
"$ARDUBOY_CLI" compile \
  --fqbn "$FQBN" --library . \
  --build-path "$LANE/diag" --output-dir "$LANE/diag-out" \
  --build-property "compiler.cpp.extra_flags=-I$REPO_ROOT/examples/arduino/songs/song01_sfx" \
  --verbose research/fx/footprint_baseline/diag > "$LANE/build-diag.log" 2>&1
echo "build exit=$? (log: $LANE/build-diag.log)"
grep -m1 '^  Used:' "$LANE/build-diag.log" | sed 's/^/  /'

ELF="$LANE/diag-out/diag.ino.elf"
HEX="$LANE/diag-out/diag.ino.hex"

echo
echo "== headless execution (16 s simulated) + profiler dump =="
"$ARDENS" --headless=16000 --profiledump="$LANE/diag-profiledump.txt" "$ELF" \
  > "$LANE/diag-headless-serial.txt" 2> "$LANE/diag-headless.err"
echo "exit=$?  serial_bytes_captured=$(wc -c < "$LANE/diag-headless-serial.txt")"
head -8 "$LANE/diag-profiledump.txt" | sed 's/^/  /'

echo
echo "== captureserial attempt (watchdog ${WATCHDOG_SECS}s) =="
( "$ARDENS" --captureserial=5000 "$HEX" > "$LANE/diag-captureserial.txt" 2> "$LANE/diag-captureserial.err" & \
  pid=$!; ( sleep "$WATCHDOG_SECS"; kill -9 "$pid" 2>/dev/null ) & wd=$!; \
  wait "$pid"; rc=$?; kill "$wd" 2>/dev/null; exit $rc )
echo "captureserial exit=$?  serial_bytes_captured=$(wc -c < "$LANE/diag-captureserial.txt")"
echo "(nonzero/hang means emulator serial capture is unusable here; see docs)"
