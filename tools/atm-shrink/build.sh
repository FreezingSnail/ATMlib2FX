#!/usr/bin/env bash
#
# build.sh - build the ATMlib2FX offline song-shrink tools (ATMlib2FX-hlh.3)
# into build/fx-port/shrink/bin/. Host tooling only; no device code.
#
# Usage: tools/atm-shrink/build.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

BIN="build/fx-port/shrink/bin"
CC="${CC:-cc}"
mkdir -p "$BIN"

CFLAGS="-std=c11 -O2 -Wall -Wextra -Wno-unused-parameter"

"$CC" $CFLAGS -Isrc \
  tools/atm-shrink/atm_shrink.c tools/atm-shrink/shrink_core.c \
  -o "$BIN/atm_shrink"

"$CC" $CFLAGS -Itools/atm-shrink \
  tests/atm-shrink/selftest.c tools/atm-shrink/shrink_core.c \
  -o "$BIN/selftest"

# CLI depth-gate fixture: a depth-3 single-use CALL chain (see
# tests/atm-shrink/depth3_fixture.c); run-tests.sh asserts atm_shrink exits 4.
"$CC" -std=c11 -O2 -Wall -Wextra \
  tests/atm-shrink/depth3_fixture.c -o "$BIN/depth3_fixture"

# Score dumpers: one per supported header layout.
"$CC" -std=c11 -w -Isrc -Iexamples/arduino/songs/song01_sfx -DHAVE_SFX1=1 \
  -DATM_SHRINK_SCORE_HEADER='"song.h"' \
  tools/atm-shrink/score_dump.c -o "$BIN/dump_song01_sfx"

"$CC" -std=c11 -w -Isrc \
  -Itests/music_authoring/fixtures/basic/expected \
  -Iresearch/fx/footprint_baseline/trace/avr_shim \
  -DATM_SHRINK_SCORE_HEADER='"score.h"' \
  tools/atm-shrink/score_dump.c -o "$BIN/dump_basic"

# Legacy raw byte-array asset (fmt byte 0x08, no pattern table): the dumper can
# still extract it so the CLI can report the unsupported format explicitly.
"$CC" -std=c11 -w -Isrc -Iexamples/arduino/songs/song01 \
  -DATM_SHRINK_SCORE_HEADER='"song.h"' -DATM_SHRINK_SCORE_SYMBOL=music \
  tools/atm-shrink/score_dump.c -o "$BIN/dump_song01_legacy"

echo "built: $BIN/{atm_shrink,selftest,depth3_fixture,dump_song01_sfx,dump_basic,dump_song01_legacy}"
