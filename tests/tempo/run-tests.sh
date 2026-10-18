#!/usr/bin/env bash
#
# run-tests.sh - permanent host checks for the runtime tempo API
# (ATMlib2FX-y1w): atm_synth_set_tempo(uint8_t tick_rate).
#
# Builds tests/tempo/tempo_selftest from the real library C sources
# (src/atm_synth.c, which includes src/cmd_parse.c) with an AVR PROGMEM shim,
# substituting only the osc.c timer layer with a stub that reproduces the
# Timer3 ISR callback scheduling (2000 Hz base). The selftest drives the tick
# callbacks exactly like the real ISR and asserts the trace "tempo" column.
#
# Host diagnostic only: no AVR bytes, no git operations. Output lands under
# build/tempo/.
#
# Usage: tests/tempo/run-tests.sh
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
cd "$REPO_ROOT"

OUT="build/tempo"
CC="${CC:-cc}"
SHIM="research/fx/footprint_baseline/trace/avr_shim"

mkdir -p "$OUT"

echo "== Runtime tempo API checks (ATMlib2FX-y1w) =="
echo "repo : $REPO_ROOT"
echo "cc   : $($CC --version 2>/dev/null | head -1)"

"$CC" -std=c11 -O1 -w -I"$SHIM" -Isrc \
  tests/tempo/tempo_selftest.c -o "$OUT/tempo_selftest"

"$OUT/tempo_selftest" | tee "$OUT/selftest.log"

{
  echo "# runtime tempo API verification (ATMlib2FX-y1w)"
  echo "checks_passed=$(grep -c '^ok:' "$OUT/selftest.log")"
  echo "failures=$(grep -c '^FAIL:' "$OUT/selftest.log" || true)"
} > "$OUT/verify.txt"

echo
echo "summary:"
cat "$OUT/verify.txt"
echo
echo "evidence: $OUT"
