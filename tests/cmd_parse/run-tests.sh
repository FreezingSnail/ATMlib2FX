#!/usr/bin/env bash
#
# run-tests.sh - permanent host checks for trigger_note() in src/cmd_parse.c:
# slide re-trigger behaviour (ATMlib2FX-74q) and note-off/note-cut semantics
# (ATMlib2FX-mgd).
#
# Compiles the real library C sources (src/atm_synth.c + the src/cmd_parse.c it
# includes) for the host with an AVR PROGMEM shim, substituting only the osc.c
# timer layer, and calls the static trigger_note() directly to pin the three
# slide targets (vol/freq/mod), the re-trigger config branch, and the note-off
# (index 0) volume-zero / mod-preserved contract.
#
# Host diagnostic only: no AVR bytes, no git operations. Output lands under
# build/cmd_parse/.
#
# Usage: tests/cmd_parse/run-tests.sh
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
cd "$REPO_ROOT"

OUT="build/cmd_parse"
CC="${CC:-cc}"
SHIM="research/fx/footprint_baseline/trace/avr_shim"

mkdir -p "$OUT"

echo "== cmd_parse trigger_note checks (ATMlib2FX-74q, ATMlib2FX-mgd) =="
echo "repo : $REPO_ROOT"
echo "cc   : $($CC --version 2>/dev/null | head -1)"

"$CC" -std=c11 -O1 -w -I"$SHIM" -Isrc \
  tests/cmd_parse/trigger_note_slide_selftest.c \
  -o "$OUT/trigger_note_slide_selftest"

"$CC" -std=c11 -O1 -w -I"$SHIM" -Isrc \
  tests/cmd_parse/trigger_note_note_off_selftest.c \
  -o "$OUT/trigger_note_note_off_selftest"

"$OUT/trigger_note_slide_selftest" | tee "$OUT/selftest.log"
"$OUT/trigger_note_note_off_selftest" | tee "$OUT/note_off_selftest.log"

echo
echo "evidence: $OUT"
