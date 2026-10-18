#!/usr/bin/env bash
#
# run-tests.sh - test + verification driver for the ATMlib2FX offline
# song-shrink pass (ATMlib2FX-hlh.3).
#
#  1. builds the host tools and runs the C selftest
#  2. shrinks the shipped song01_sfx header and the generated authoring fixture
#  3. regression checks: the SET_LOOP_PATTERN operand survives inlining; a
#     depth-3 single-use CALL chain input exits 4 under both flag modes
#     (channel-entry root and loop-rooted root); a loop-rooted depth-2 input
#     still shrinks byte-identically
#  4. proves playback is unchanged with the reference trace harness
#     (research/fx/footprint_baseline/trace) and the authoring preview harness
#  5. measures flash size before/after the swap
#  6. writes sha256 evidence under build/fx-port/shrink/
#
# The only git command run is a read-only `git rev-parse HEAD` recorded in the
# evidence file for provenance; nothing is added, committed or pushed. All new
# outputs stay under build/fx-port/shrink/.
#
# Usage: tests/atm-shrink/run-tests.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

OUT="build/fx-port/shrink"
BIN="$OUT/bin"
SHIM="research/fx/footprint_baseline/trace/avr_shim"
PSHIM="tools/music_authoring/preview/avr_shim"
SOCKET_INC="examples/arduino/songs/song01_sfx"
BASIC_INC="tests/music_authoring/fixtures/basic/expected"

CC="${CC:-cc}"
mkdir -p "$BIN" "$OUT/song01_sfx" "$OUT/basic"

echo "== build tools =="
tools/atm-shrink/build.sh

echo
echo "== C selftest =="
"$BIN/selftest"

echo
echo "== shrink shipped asset: song01_sfx =="
"$BIN/dump_song01_sfx" score > "$OUT/song01_sfx/score.bin"
"$BIN/dump_song01_sfx" sfx   > "$OUT/song01_sfx/sfx1.bin"
cp -f "$SOCKET_INC/bitmaps.h" "$OUT/song01_sfx/bitmaps.h"
"$BIN/atm_shrink" \
  --in "$OUT/song01_sfx/score.bin" --sfx "$OUT/song01_sfx/sfx1.bin" \
  --out-blob "$OUT/song01_sfx/score.shrunk.bin" \
  --out-header "$OUT/song01_sfx/song.h" \
  --report "$OUT/song01_sfx/report.txt" \
  --label song01_sfx
cat "$OUT/song01_sfx/report.txt"

echo
echo "== shrink generated authoring fixture: basic =="
"$BIN/dump_basic" score > "$OUT/basic/score.bin"
"$BIN/atm_shrink" \
  --in "$OUT/basic/score.bin" --flat \
  --out-blob "$OUT/basic/score.shrunk.bin" \
  --out-header "$OUT/basic/score.h" \
  --report "$OUT/basic/report.txt" \
  --label basic_authoring_v1
cat "$OUT/basic/report.txt"

echo
echo "== shipped asset: song01 (legacy raw byte array, unsupported format) =="
mkdir -p "$OUT/song01_legacy"
"$BIN/dump_song01_legacy" > "$OUT/song01_legacy/music.bin"
if "$BIN/atm_shrink" --in "$OUT/song01_legacy/music.bin" \
     --report "$OUT/song01_legacy/report.txt" --label song01 \
     > "$OUT/song01_legacy/stdout.txt" 2> "$OUT/song01_legacy/stderr.txt"; then
  echo "  ERROR: legacy asset unexpectedly accepted" >&2
  exit 1
else
  echo "  rejected as expected: $(cat "$OUT/song01_legacy/stderr.txt")"
fi

echo
echo "== regression: SET_LOOP_PATTERN operand survives inlining (review repro) =="
mkdir -p "$OUT/drift_repro"
printf '\x03\x03\x0a\x00\x0f\x00\x12\x00\x01\x00\x82\x01\x80\x02\x61\x74\x10\x61\x74\x20\x61' \
  > "$OUT/drift_repro/loop_operand.bin"
"$BIN/atm_shrink" --in "$OUT/drift_repro/loop_operand.bin" \
  --out-blob "$OUT/drift_repro/loop_operand.shrunk.bin" \
  --report "$OUT/drift_repro/loop_operand.report.txt" \
  --label loop_operand
if cmp -s <(printf '\x03\x02\x08\x00\x0d\x00\x01\x00\x74\x10\x80\x01\x61\x74\x20\x61') \
     "$OUT/drift_repro/loop_operand.shrunk.bin"; then
  echo "  OK: npat=2, loop operand remapped 2 -> 1"
else
  echo "  ERROR: loop operand not remapped; emitted:" >&2
  od -An -tx1 "$OUT/drift_repro/loop_operand.shrunk.bin" >&2
  exit 1
fi

echo
echo "== regression: depth-3 input rejected (CLI exit 4) =="
mkdir -p "$OUT/depth_gate"
"$BIN/depth3_fixture" > "$OUT/depth_gate/score.bin"
rc=0
"$BIN/atm_shrink" --in "$OUT/depth_gate/score.bin" --label depth3_chain \
  > "$OUT/depth_gate/stdout.txt" 2> "$OUT/depth_gate/stderr.txt" || rc=$?
if [ "$rc" -ne 4 ]; then
  echo "  ERROR: expected exit 4, got $rc" >&2
  cat "$OUT/depth_gate/stderr.txt" >&2
  exit 1
fi
echo "  default flags: exit 4 ($(cat "$OUT/depth_gate/stderr.txt"))"
rc=0
"$BIN/atm_shrink" --in "$OUT/depth_gate/score.bin" --no-inline --no-share \
  --label depth3_chain \
  > "$OUT/depth_gate/stdout_noinline.txt" 2> "$OUT/depth_gate/stderr_noinline.txt" || rc=$?
if [ "$rc" -ne 4 ]; then
  echo "  ERROR: control --no-inline --no-share expected exit 4, got $rc" >&2
  exit 1
fi
echo "  --no-inline --no-share: exit 4 (control)"

echo
echo "== regression: loop-rooted depth-3 input rejected (CLI exit 4) =="
"$BIN/depth3_fixture" looproot > "$OUT/depth_gate/looproot.bin"
rc=0
"$BIN/atm_shrink" --in "$OUT/depth_gate/looproot.bin" --label looproot_depth3 \
  > "$OUT/depth_gate/looproot_stdout.txt" 2> "$OUT/depth_gate/looproot_stderr.txt" || rc=$?
if [ "$rc" -ne 4 ]; then
  echo "  ERROR: default flags expected exit 4, got $rc" >&2
  cat "$OUT/depth_gate/looproot_stderr.txt" >&2
  exit 1
fi
if ! grep -q "call depth 4 reaches limit 3" "$OUT/depth_gate/looproot_stderr.txt"; then
  echo "  ERROR: loop-rooted chain was not counted at the limit" >&2
  cat "$OUT/depth_gate/looproot_stderr.txt" >&2
  exit 1
fi
echo "  default flags: exit 4 ($(cat "$OUT/depth_gate/looproot_stderr.txt"))"
rc=0
"$BIN/atm_shrink" --in "$OUT/depth_gate/looproot.bin" --no-inline --no-share \
  --label looproot_depth3 \
  > "$OUT/depth_gate/looproot_stdout_noinline.txt" 2> "$OUT/depth_gate/looproot_stderr_noinline.txt" || rc=$?
if [ "$rc" -ne 4 ]; then
  echo "  ERROR: --no-inline --no-share expected exit 4, got $rc" >&2
  cat "$OUT/depth_gate/looproot_stderr_noinline.txt" >&2
  exit 1
fi
echo "  --no-inline --no-share: exit 4 (control)"

echo
echo "== control: loop-rooted depth-2 input still accepted =="
"$BIN/depth3_fixture" looproot2 > "$OUT/depth_gate/looproot2.bin"
"$BIN/atm_shrink" --in "$OUT/depth_gate/looproot2.bin" \
  --out-blob "$OUT/depth_gate/looproot2.shrunk.bin" \
  --report "$OUT/depth_gate/looproot2.report.txt" \
  --label looproot_depth2
if ! grep -q '^depth_before: 2$' "$OUT/depth_gate/looproot2.report.txt" ||
   ! grep -q '^depth_after: 0$' "$OUT/depth_gate/looproot2.report.txt"; then
  echo "  ERROR: loop-rooted depth-2 control reported wrong depths" >&2
  cat "$OUT/depth_gate/looproot2.report.txt" >&2
  exit 1
fi
if cmp -s <(printf '\x03\x02\x0b\x00\x10\x00\x04\x00\x00\x00\x00\x80\x01\x74\x10\x61\x74\x20\x40\x40\x61') \
     "$OUT/depth_gate/looproot2.shrunk.bin"; then
  echo "  OK: accepted (depth_before 2 -> depth_after 0), output byte-checked"
else
  echo "  ERROR: loop-rooted depth-2 control output drifted; emitted:" >&2
  od -An -tx1 "$OUT/depth_gate/looproot2.shrunk.bin" >&2
  exit 1
fi

echo
echo "== playback trace: song01_sfx (reference harness) =="
"$CC" -std=c11 -O1 -w -I"$SHIM" -Isrc -I"$SOCKET_INC" \
  research/fx/footprint_baseline/trace/trace_main.c -o "$BIN/trace_song_orig"
"$CC" -std=c11 -O1 -w -I"$OUT/song01_sfx" -I"$SHIM" -Isrc \
  research/fx/footprint_baseline/trace/trace_main.c -o "$BIN/trace_song_shrunk"
for mode in "music 512" "sfx 512 64"; do
  set -- $mode
  name="$1"
  "$BIN/trace_song_orig"   "$@" > "$OUT/song01_sfx/trace_${name}_orig.csv"
  "$BIN/trace_song_shrunk" "$@" > "$OUT/song01_sfx/trace_${name}_shrunk.csv"
  if cmp -s "$OUT/song01_sfx/trace_${name}_orig.csv" "$OUT/song01_sfx/trace_${name}_shrunk.csv"; then
    echo "  $name: OK (byte-identical trace)"
  else
    echo "  $name: MISMATCH" >&2
    diff "$OUT/song01_sfx/trace_${name}_orig.csv" "$OUT/song01_sfx/trace_${name}_shrunk.csv" | head -20 >&2
    exit 1
  fi
done

echo
echo "== playback trace: basic fixture (authoring preview harness) =="
"$CC" -std=c11 -O1 -w -I"$PSHIM" -Isrc -I"$BASIC_INC" \
  tools/music_authoring/preview/trace_main.c -o "$BIN/trace_basic_orig"
"$CC" -std=c11 -O1 -w -I"$OUT/basic" -I"$PSHIM" -Isrc \
  tools/music_authoring/preview/trace_main.c -o "$BIN/trace_basic_shrunk"
"$BIN/trace_basic_orig"   2048 > "$OUT/basic/trace_orig.csv"
"$BIN/trace_basic_shrunk" 2048 > "$OUT/basic/trace_shrunk.csv"
if cmp -s "$OUT/basic/trace_orig.csv" "$OUT/basic/trace_shrunk.csv"; then
  echo "  basic: OK (byte-identical trace, $(wc -l < "$OUT/basic/trace_orig.csv") rows)"
else
  echo "  basic: MISMATCH" >&2
  diff "$OUT/basic/trace_orig.csv" "$OUT/basic/trace_shrunk.csv" | head -20 >&2
  exit 1
fi

echo
echo "== flash size before/after swap =="
tests/atm-shrink/measure-footprint-swap.sh

echo
echo "== evidence hashes =="
EVID="$OUT/evidence.sha256"
{
  echo "# ATMlib2FX-hlh.3 shrink evidence (sha256)"
  echo "# git HEAD: $(git rev-parse HEAD)"
  find "$OUT/song01_sfx" "$OUT/basic" "$OUT/song01_legacy" \
    "$OUT/drift_repro" "$OUT/depth_gate" -type f \
    \( -name '*.bin' -o -name '*.h' -o -name '*.csv' -o -name '*.txt' \) \
    -print0 | sort -z | xargs -0 shasum -a 256
} > "$EVID"
cat "$EVID"

echo
echo "ALL CHECKS PASSED"
