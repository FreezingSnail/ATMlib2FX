#!/usr/bin/env bash
#
# measure-footprint.sh - reproducible footprint measurement for ATMlib2FX-hlh.1.
#
# Builds the research/fx/footprint_baseline fixture in each audio configuration
# through the single reusable lane build/fx-port/ and reports whole-image
# program flash, static SRAM (.data/.bss), and song/SFX asset bytes.
#
# Exit status is non-zero if any variant fails to build or if the wrong ATMlib
# was selected for a variant that links it.
#
# Usage: research/fx/tools/measure-footprint.sh
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$REPO_ROOT"

FQBN="arduboy-homemade:avr:arduboy-fx"
SKETCH="research/fx/footprint_baseline"
SONG_INC="examples/arduino/songs/song01_sfx"
LANE="build/fx-port"

AVR_BIN="$HOME/Library/Arduino15/packages/arduino/tools/avr-gcc/7.3.0-atmel3.6.1-arduino7/bin"
AVR_SIZE="$AVR_BIN/avr-size"
AVR_NM="$AVR_BIN/avr-nm"
ARDUBOY_CLI="${ARDUBOY_CLI:-$(command -v arduino-cli)}"

mkdir -p "$LANE"
SUMMARY="$LANE/footprint-summary.txt"

declare -a NAMES=(shell music music_sfx fx_control)
declare -a MODES=(0 1 2 3)
declare -a LINKS_ATMLIB=(no yes yes no)

overall=0

section_size() { # file section
  "$AVR_SIZE" -A "$1" | awk -v s=".$2" '$1==s {print $2; found=1} END{if(!found) print 0}'
}

echo "== ATMlib2FX footprint baseline =="
echo "repo       : $REPO_ROOT"
echo "git HEAD   : $(git rev-parse HEAD)"
echo "fqbn       : $FQBN"
echo "sketch     : $SKETCH"
echo "song input : $SONG_INC/song.h"
echo "lane       : $LANE"
echo "arduino-cli: $($ARDUBOY_CLI version 2>/dev/null)"
echo
echo "variant    program  text    data  bss    sram   score sfx1  atmlib"
echo "-----------------------------------------------------------------------"

{
  echo "# ATMlib2FX footprint baseline summary"
  echo "# repo: $REPO_ROOT"
  echo "# git HEAD: $(git rev-parse HEAD)"
  echo "# fqbn: $FQBN"
  echo "# variant,program_bytes,text_bytes,data_bytes,bss_bytes,sram_bytes,score_bytes,sfx1_bytes,atmlib"
} > "$SUMMARY"

for i in "${!NAMES[@]}"; do
  name="${NAMES[$i]}"
  mode="${MODES[$i]}"
  links="${LINKS_ATMLIB[$i]}"
  build_path="$LANE/avr-$name"
  out_dir="$LANE/out-$name"
  log="$LANE/build-$name.log"
  elf="$build_path/footprint_baseline.ino.elf"

  "$ARDUBOY_CLI" compile \
    --fqbn "$FQBN" \
    --library . \
    --build-path "$build_path" \
    --output-dir "$out_dir" \
    --build-property "compiler.cpp.extra_flags=-DFP_AUDIO=$mode -I$REPO_ROOT/$SONG_INC" \
    --verbose \
    "$SKETCH" > "$log" 2>&1
  rc=$?
  if [ $rc -ne 0 ] || [ ! -f "$elf" ]; then
    echo "$name: BUILD FAILED - see $log" >&2
    tail -15 "$log" >&2
    overall=1
    continue
  fi

  text=$(section_size "$elf" text)
  data=$(section_size "$elf" data)
  bss=$(section_size "$elf" bss)
  program=$((text + data))
  sram=$((data + bss))
  hex2dec() { [ -n "$1" ] && printf '%d' "$((16#$1))" || printf '0'; }
  score_hex=$(  "$AVR_NM" -S --size-sort "$elf" | awk '/_ZL5score$/{print $2}' )
  sfx_hex=$(    "$AVR_NM" -S --size-sort "$elf" | awk '/_ZL4sfx1$/{print $2}' )
  score=$(hex2dec "$score_hex")
  sfx=$(hex2dec "$sfx_hex")

  # Local-library selection evidence.
  if [ "$links" = yes ]; then
    used="$(grep -m1 '^  Used:' "$log" | sed 's/^  Used: //')"
    notused="$(grep -m1 '^  Not used:' "$log" | sed 's/^  Not used: //')"
    if [ "$used" != "$REPO_ROOT" ]; then
      echo "$name: WRONG ATMlib selected: '$used' (expected $REPO_ROOT)" >&2
      overall=1
    fi
    libsel="local"
    if [ -n "$notused" ]; then
      echo "  (installed same-named library skipped: $notused)"
    fi
    grep -m1 '^Using library ATMlib ' "$log" | sed 's/^/  /'
  else
    libsel="none"
  fi

  printf '%-11s %7d %7d %6d %5d %6d %6d %4d  %s\n' \
    "$name" "$program" "$text" "$data" "$bss" "$sram" "$score" "$sfx" "$libsel"
  echo "  elf: $elf"
  echo "  log: $log"
  echo "$name,$program,$text,$data,$bss,$sram,$score,$sfx,$libsel" >> "$SUMMARY"
done

echo
echo "summary: $SUMMARY"
echo
echo "-- SFX-state / library globals (music_sfx ELF) --"
"$AVR_NM" -S --size-sort "$LANE/avr-music_sfx/footprint_baseline.ino.elf" \
  | grep -E ' (sfx_state|atmlib_state|channels|osc_params_array|osc_pha_acc_array|osc_cb|noteTable)$' \
  | while read -r addr size type sym; do
      printf '%-24s %5d bytes  (%s)\n' "$sym" "$((16#$size))" "$type"
    done

echo
installed="$HOME/Library/Arduino15/packages/arduboy-homemade/hardware/avr/1.4.0/libraries/ATMlib"
echo "installed same-named ATMlib: $installed"
[ -d "$installed" ] && grep -E '^(name|version)=' "$installed/library.properties" | sed 's/^/  /'

exit $overall
