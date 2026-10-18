#!/usr/bin/env bash
#
# measure-footprint-swap.sh - before/after size check for ATMlib2FX-hlh.3.
#
# Uses the same measurement method as research/fx/tools/measure-footprint.sh
# (same FQBN, same arduino-cli invocation, same avr-size/avr-nm section math)
# but with a redirected lane under build/fx-port/shrink/ so the committed
# build/fx-port/ evidence is preserved. Measures the score asset bytes and the
# whole-image program size before and after swapping in the shrunk song header.
#
# Usage: tests/atm-shrink/measure-footprint-swap.sh
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

FQBN="arduboy-homemade:avr:arduboy-fx"
LANE="build/fx-port/shrink/footprint"
SHRUNK_SONG="build/fx-port/shrink/song01_sfx"
SHRUNK_BASIC="build/fx-port/shrink/basic"

AVR_BIN="$HOME/Library/Arduino15/packages/arduino/tools/avr-gcc/7.3.0-atmel3.6.1-arduino7/bin"
AVR_SIZE="$AVR_BIN/avr-size"
AVR_NM="$AVR_BIN/avr-nm"
ARDUBOY_CLI="${ARDUBOY_CLI:-$(command -v arduino-cli)}"

mkdir -p "$LANE"
SUMMARY="$LANE/size-swap-summary.csv"

section_size() { "$AVR_SIZE" -A "$1" | awk -v s=".$2" '$1==s {print $2; found=1} END{if(!found) print 0}'; }
hex2dec() { [ -n "$1" ] && printf '%d' "$((16#$1))" || printf '0'; }

echo "== ATMlib2FX shrink size swap =="
echo "repo      : $REPO_ROOT"
echo "git HEAD  : $(git rev-parse HEAD)"
echo "fqbn      : $FQBN"
echo "arduino-cli: $($ARDUBOY_CLI version 2>/dev/null)"
echo
echo "variant          program    text   data   bss   sram   score"
echo "----------------------------------------------------------------"

{
  echo "# ATMlib2FX-hlh.3 shrink size before/after (method of research/fx/tools/measure-footprint.sh)"
  echo "# git HEAD: $(git rev-parse HEAD)"
  echo "# fqbn: $FQBN"
  echo "# variant,program_bytes,text_bytes,data_bytes,bss_bytes,sram_bytes,score_bytes"
} > "$SUMMARY"

measure() { # name sketch extra_flags
  local name="$1" sketch="$2" flags="$3"
  local bp="$LANE/avr-$name" od="$LANE/out-$name" log="$LANE/build-$name.log"
  local base; base="$(basename "$sketch")"
  local elf="$bp/$base.ino.elf"

  "$ARDUBOY_CLI" compile --fqbn "$FQBN" --library . \
    --build-path "$bp" --output-dir "$od" \
    --build-property "compiler.cpp.extra_flags=$flags" "$sketch" > "$log" 2>&1
  if [ $? -ne 0 ] || [ ! -f "$elf" ]; then
    echo "$name: BUILD FAILED - see $log" >&2
    tail -15 "$log" >&2
    return 1
  fi
  local text data bss program sram sh
  text=$(section_size "$elf" text)
  data=$(section_size "$elf" data)
  bss=$(section_size "$elf" bss)
  program=$((text + data))
  sram=$((data + bss))
  sh=$("$AVR_NM" -S --size-sort "$elf" | awk '/score$/{print $2; exit}')
  local score; score=$(hex2dec "$sh")
  printf '%-16s %7d %7d %6d %5d %6d %7d\n' \
    "$name" "$program" "$text" "$data" "$bss" "$sram" "$score"
  echo "$name,$program,$text,$data,$bss,$sram,$score" >> "$SUMMARY"
}

# 1. footprint_baseline, music-only (FP_AUDIO=1), original vs shrunk song01_sfx.
measure fp_music_before research/fx/footprint_baseline \
  "-DFP_AUDIO=1 -I$REPO_ROOT/examples/arduino/songs/song01_sfx"
measure fp_music_after  research/fx/footprint_baseline \
  "-DFP_AUDIO=1 -I$REPO_ROOT/$SHRUNK_SONG -I$REPO_ROOT/examples/arduino/songs/song01_sfx"

# 2. basic authoring AVR fixture, original vs shrunk generated score.
measure basic_before tests/music_authoring/fixtures/basic/avr \
  "-I$REPO_ROOT/tests/music_authoring/fixtures/basic/expected"
measure basic_after  tests/music_authoring/fixtures/basic/avr \
  "-I$REPO_ROOT/$SHRUNK_BASIC"

echo
echo "summary: $SUMMARY"
