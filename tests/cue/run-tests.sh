#!/usr/bin/env bash
#
# run-tests.sh - permanent host checks for the CUE command channel
# (ATMlib2FX-mpt): ATM_CMD_M_CUE(v) / atm_synth_get_cue() / atm_synth_check_cue().
#
# Builds two host binaries from the real library C sources (src/atm_synth.c and
# the src/cmd_parse.c it includes) with an AVR PROGMEM shim, substituting only
# the osc.c timer layer:
#
#   cue_selftest     - PROGMEM score + SFX path (get = value+clear; check = no
#                      clear; score and SFX share the last-cue byte).
#   cue_fx_selftest  - compiled FX-stream backend (-DATM_HAS_FX_STREAM=1):
#                      confirms 1P commands (incl. CUE) route through the same
#                      process_1p_cmd() handler.
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
SHIM="research/fx/footprint_baseline/trace/avr_shim"

mkdir -p "$OUT"

echo "== CUE command checks (ATMlib2FX-mpt) =="
echo "repo : $REPO_ROOT"
echo "cc   : $($CC --version 2>/dev/null | head -1)"

"$CC" -std=c11 -O1 -w -I"$SHIM" -Isrc \
  tests/cue/cue_selftest.c -o "$OUT/cue_selftest"

"$CC" -std=c11 -O1 -w -DATM_HAS_FX_STREAM=1 -I"$SHIM" -Isrc \
  tests/cue/cue_fx_selftest.c -o "$OUT/cue_fx_selftest"

"$OUT/cue_selftest" | tee "$OUT/selftest.log"
"$OUT/cue_fx_selftest" | tee "$OUT/fx_selftest.log"

echo
echo "evidence: $OUT"
