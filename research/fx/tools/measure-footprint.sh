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
# Output lane. Defaults to the hlh.1 lane; override with MFP_LANE to write a
# separate lane (e.g. the ATMlib2FX-hlh.4 mixer-gating spike at
# build/fx-port/mixer) without clobbering the retained baseline evidence.
LANE="${MFP_LANE:-build/fx-port}"

AVR_BIN="$HOME/Library/Arduino15/packages/arduino/tools/avr-gcc/7.3.0-atmel3.6.1-arduino7/bin"
AVR_SIZE="$AVR_BIN/avr-size"
AVR_NM="$AVR_BIN/avr-nm"
ARDUBOY_CLI="${ARDUBOY_CLI:-$(command -v arduino-cli)}"

mkdir -p "$LANE"
SUMMARY="$LANE/footprint-summary.txt"

declare -a NAMES=(shell music music_sfx fx_control)
declare -a MODES=(0 1 2 3)
declare -a LINKS_ATMLIB=(no yes yes no)
# ---------------------------------------------------------------------------
# Compile-time mixer-gating variants (spike ATMlib2FX-hlh.4). Additive: the
# four base variants above are unchanged. Each gated variant keeps the same
# sketch and only adds -DATM_HAS_OSC_CHx / -DATM_HAS_NOISE for the C compile of
# src/osc.c, so the mixer block(s) for the gated channel(s) are not assembled.
# The default (all-on) build of any variant must stay byte-identical to the
# pre-flag library.
# ---------------------------------------------------------------------------
NAMES+=(music_ch0_off music_ch1_off music_ch2_off music_ch3_off \
        music_no_noise music_1ch music_sfx_no_noise)
MODES+=(1 1 1 1 1 1 2)
LINKS_ATMLIB+=(yes yes yes yes yes yes yes)
declare -a EXTRAS=("" "" "" "" \
  "-DATM_HAS_OSC_CH0=0" \
  "-DATM_HAS_OSC_CH1=0" \
  "-DATM_HAS_OSC_CH2=0" \
  "-DATM_HAS_OSC_CH3=0" \
  "-DATM_HAS_NOISE=0" \
  "-DATM_HAS_OSC_CH1=0 -DATM_HAS_OSC_CH2=0 -DATM_HAS_OSC_CH3=0 -DATM_HAS_NOISE=0" \
  "-DATM_HAS_NOISE=0")

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
echo "variant    program  text    data  bss    sram   score sfx1  atmlib  gating"
echo "---------------------------------------------------------------------------------"

{
  echo "# ATMlib2FX footprint baseline summary"
  echo "# repo: $REPO_ROOT"
  echo "# git HEAD: $(git rev-parse HEAD)"
  echo "# fqbn: $FQBN"
  echo "# lane: $LANE"
  echo "# variant,program_bytes,text_bytes,data_bytes,bss_bytes,sram_bytes,score_bytes,sfx1_bytes,atmlib,gating"
} > "$SUMMARY"

for i in "${!NAMES[@]}"; do
  name="${NAMES[$i]}"
  mode="${MODES[$i]}"
  links="${LINKS_ATMLIB[$i]}"
  gating="${EXTRAS[$i]:-}"
  build_path="$LANE/avr-$name"
  out_dir="$LANE/out-$name"
  log="$LANE/build-$name.log"
  elf="$build_path/footprint_baseline.ino.elf"

  cpp_flags="-DFP_AUDIO=$mode -I$REPO_ROOT/$SONG_INC"
  c_flags=""
  if [ -n "$gating" ]; then
    cpp_flags="$cpp_flags $gating"
    c_flags="$gating"
  fi
  build_props=(--build-property "compiler.cpp.extra_flags=$cpp_flags")
  if [ -n "$c_flags" ]; then
    build_props+=(--build-property "compiler.c.extra_flags=$c_flags")
  fi

  "$ARDUBOY_CLI" compile \
    --fqbn "$FQBN" \
    --library . \
    --build-path "$build_path" \
    --output-dir "$out_dir" \
    "${build_props[@]}" \
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

  printf '%-11s %7d %7d %6d %5d %6d %6d %4d  %-7s %s\n' \
    "$name" "$program" "$text" "$data" "$bss" "$sram" "$score" "$sfx" "$libsel" "$gating"
  echo "  elf: $elf"
  echo "  log: $log"
  echo "$name,$program,$text,$data,$bss,$sram,$score,$sfx,$libsel,${gating// /;}" >> "$SUMMARY"
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

# ---- compile-time mixer gating: ISR cycle cost (ATMlib2FX-hlh.4) -----------
# The emulator's total cycle count is sample-rate bound (identical across
# variants), so the ISR cost is measured statically: sum the documented AVR
# instruction timings over __vector_32 (TIMER3_COMPA_vect on ATmega32U4). The
# reported base assumes data-dependent branches not taken, max assumes taken.
echo
echo "-- TIMER3 ISR cycle cost (static, __vector_32) --"
cat > "$LANE/isr-cycles.awk" <<'AWK'
BEGIN{FS="\t"}
NF>=2 {
  m=$3; if(m==""){next}
  n++
  if (m=="lds"||m=="sts"||m=="ld"||m=="ldd"||m=="st"||m=="std"||m=="push"||m=="pop") c+=2;
  else if (m=="rjmp") c+=2;
  else if (m=="call") c+=4;
  else if (m=="rcall") c+=3;
  else if (m=="jmp") c+=3;
  else if (m=="ret"||m=="reti") c+=4;
  else if (m~ /^br/) { c+=1; br++; }
  else c+=1;
}
END{printf "%d %d %d", c, br, n}
AWK
CYC_TXT="$LANE/isr-cycles.txt"
{
  echo "# TIMER3 ISR static cycle count (ATMlib2FX-hlh.4)"
  echo "# vector: __vector_32 (TIMER3_COMPA_vect, ATmega32U4)"
  echo "# base = data-dependent branches not taken; max = all taken"
  echo "# variant,base_cycles,max_cycles,instr,branches,delta_base,delta_max"
} > "$CYC_TXT"
cyc_of() { # elf -> "base branches instr"
  local elf="$1" addr next out
  addr="$("$AVR_NM" "$elf" | awk '/ T __vector_32$/{print $1}')"
  [ -n "$addr" ] || { echo "0 0 0"; return; }
  next="$("$AVR_NM" -n "$elf" | awk -v a="$addr" 'f{print $1; exit} $1==a{f=1}')"
  out="$("$AVR_BIN/avr-objdump" -d --start-address=0x$addr --stop-address=0x$next "$elf" \
        | awk -f "$LANE/isr-cycles.awk")"
  [ -n "$out" ] || out="0 0 0"
  echo "$out"
}
read -r d_base d_br d_n < <(cyc_of "$LANE/avr-music/footprint_baseline.ino.elf")
echo "default music      base=$d_base max=$((d_base+d_br)) instr=$d_n"
echo "music,$d_base,$((d_base+d_br)),$d_n,$d_br,0,0" >> "$CYC_TXT"
for name in "${NAMES[@]}"; do
  elf="$LANE/avr-$name/footprint_baseline.ino.elf"
  [ -f "$elf" ] || continue
  read -r b br n < <(cyc_of "$elf")
  printf '%-18s base=%-4s max=%-4s instr=%-4s  dbase=%-4s dmax=%-4s\n' \
    "$name" "$b" "$((b+br))" "$n" "$((b-d_base))" "$((b+br-d_base-d_br))"
  echo "$name,$b,$((b+br)),$n,$br,$((b-d_base)),$((b+br-d_base-d_br))" >> "$CYC_TXT"
done

echo
installed="$HOME/Library/Arduino15/packages/arduboy-homemade/hardware/avr/1.4.0/libraries/ATMlib"
echo "installed same-named ATMlib: $installed"
[ -d "$installed" ] && grep -E '^(name|version)=' "$installed/library.properties" | sed 's/^/  /'

exit $overall
