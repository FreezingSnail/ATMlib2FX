#!/usr/bin/env bash
#
# run-tests.sh - permanent host checks for the compact-FX CUE command channel
# (ATMlib2FX-mpt): ATM_CMD_M_CUE(v) / atm_synth_get_cue() / atm_synth_check_cue().
#
# Builds tests/cue/cue_compact_selftest.c from the real library sources with a
# host AVR PROGMEM shim, substituting only the osc.c timer layer. The selftest
# feeds a compact record carrying CUE and checks the shared cue byte.
#
# Host diagnostic only: no AVR bytes, no git operations. Output lands under
# build/cue/.
#
# Usage: tests/cue/run-tests.sh
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
cd "$REPO_ROOT"

OUT="build/cue"
CC="${CC:-cc}"
SHIM="tests/support/avr_shim"

mkdir -p "$OUT"

echo "== compact CUE command checks (ATMlib2FX-mpt) =="
echo "repo : $REPO_ROOT"
echo "cc   : $($CC --version 2>/dev/null | head -1)"

"$CC" -std=c11 -O1 -w -I"$SHIM" -Isrc \
  tests/cue/cue_compact_selftest.c -o "$OUT/cue_compact_selftest"

"$OUT/cue_compact_selftest" | tee "$OUT/selftest.log"

echo
echo "evidence: $OUT"
