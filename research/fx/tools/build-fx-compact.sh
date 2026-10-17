#!/usr/bin/env bash
#
# build-fx-compact.sh - reproducible build/measurement lane for the compact
# directly-consumed FX music spike (ATMlib2FX-hlh.5).
#
# Same board/toolchain/options as the ATMlib2FX-hlh.1 baseline lane and the
# retained ATMlib2FX-aoe lane (build/fx-port/). Produces, under
# build/fx-port/compact/:
#   - the compact converter + gap-codec self-test + generated streams (authored
#     tempo and requested tempo 255)
#   - fxdata images (stream + deterministic stress bitmap)
#   - the matched 4-mode FX graphics shell (noaudio/music/oldfx/compact) plus two
#     diagnostic images, with whole-image sizes and ELF hashes
#   - a CSV summary and library-selection proof
#
# No git commands: identity is recorded as source/ELF SHA-256 hashes.
#
# Usage: research/fx/tools/build-fx-compact.sh
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$REPO_ROOT"

FQBN="arduboy-homemade:avr:arduboy-fx"
SKETCH="research/fx/fx_compact_spike"
SONG_INC="examples/arduino/songs/song01_sfx"
LANE="build/fx-port"
OUT="$LANE/compact"
AVR_BIN="$HOME/Library/Arduino15/packages/arduino/tools/avr-gcc/7.3.0-atmel3.6.1-arduino7/bin"
AVR_SIZE="$AVR_BIN/avr-size"
AVR_NM="$AVR_BIN/avr-nm"
ARDUINO_CLI="${ARDUINO_CLI:-$(command -v arduino-cli)}"
CC="${CC:-cc}"

mkdir -p "$OUT"
SUMMARY="$OUT/compact-summary.csv"

echo "== ATMlib2FX compact FX stream spike (ATMlib2FX-hlh.5) =="
echo "repo        : $REPO_ROOT"
echo "fqbn        : $FQBN"
echo "sketch      : $SKETCH"
echo "lane        : $OUT"
echo "arduino-cli : $($ARDUINO_CLI version 2>/dev/null)"
echo

# ---- 0. source identity (no git) -------------------------------------------
{
  echo "# source hashes"
  for f in src/atm_fx_compact.c src/atm_fx_compact.h src/atm_synth.c src/atm_synth.h \
           src/cmd_parse.c src/osc.c src/atm_fx_stream.c src/atm_fx_stream.h \
           research/fx/tools/fx_compact_spike/fx_compile_compact.c research/fx/tools/fx_make_fxdata.c \
           research/fx/fx_compact_spike/fx_compact_spike.ino \
           research/fx/fx_compact_spike/README.md \
           research/fx/fx_compact_spike/trace/trace_main.c \
           research/fx/fx_compact_spike/trace/compact_format_test.c \
           research/fx/fx_compact_spike/trace/absim_compact_harness.cpp \
           research/fx/fx_compact_spike/trace/run-trace.sh \
           research/fx/fx_compact_spike/trace/run-absim.sh \
           examples/arduino/songs/song01_sfx/song.h; do
    echo "$(shasum -a 256 "$f" | awk '{print $1}')  $f"
  done
} | tee "$OUT/source-hashes.txt"

# ---- 1. converter + self-test + streams ------------------------------------
"$CC" -std=c11 -O2 -Wall -Wextra -Wno-unused-parameter \
  -Isrc -I"$SONG_INC" research/fx/tools/fx_compact_spike/fx_compile_compact.c \
  -o "$OUT/fx_compile_compact" || exit 1

"$OUT/fx_compile_compact" --selftest || exit 1
"$OUT/fx_compile_compact" --out "$OUT/compact_stream.bin" \
  > "$OUT/compact_stream.meta" 2> "$OUT/compact_stream.log"
"$OUT/fx_compile_compact" --out "$OUT/compact_stream_t255.bin" --tempo 255 \
  > "$OUT/compact_stream_t255.meta" 2> "$OUT/compact_stream_t255.log"
cat "$OUT/compact_stream.log" "$OUT/compact_stream.meta"

# ---- 2. fxdata images ------------------------------------------------------
"$CC" -std=c11 -O2 -Wall -Wextra research/fx/tools/fx_make_fxdata.c -o "$OUT/fx_make_fxdata" || exit 1
"$OUT/fx_make_fxdata" --stream "$OUT/compact_stream.bin" --out "$OUT/fxdata_compact.bin" \
  > "$OUT/fxdata_compact.meta"
"$OUT/fx_make_fxdata" --stream "$OUT/compact_stream_t255.bin" --out "$OUT/fxdata_compact_t255.bin" \
  > "$OUT/fxdata_compact_t255.meta"

SLEN_A=$(awk -F= '/^stream_len=/{print $2}' "$OUT/fxdata_compact.meta")
BITMAP_A=$(awk -F= '/^bitmap_offset=/{print $2}' "$OUT/fxdata_compact.meta")
PAGE_A=$(awk -F= '/^data_page=/{print $2}' "$OUT/fxdata_compact.meta")
ABS_A=$(awk -F= '/^abs_stream_addr=/{print $2}' "$OUT/fxdata_compact.meta")
SLEN_T=$(awk -F= '/^stream_len=/{print $2}' "$OUT/fxdata_compact_t255.meta")
BITMAP_T=$(awk -F= '/^bitmap_offset=/{print $2}' "$OUT/fxdata_compact_t255.meta")
PAGE_T=$(awk -F= '/^data_page=/{print $2}' "$OUT/fxdata_compact_t255.meta")

echo "authored stream : $(tr '\n' ' ' < "$OUT/compact_stream.meta")"
echo "tempo255 stream : $(tr '\n' ' ' < "$OUT/compact_stream_t255.meta")"
echo "fxdata authored : $(tr '\n' ' ' < "$OUT/fxdata_compact.meta")"
echo "abs stream addr : authored=$ABS_A"
echo

# ---- 3. AVR images ---------------------------------------------------------
section_size() { # file section
  "$AVR_SIZE" -A "$1" | awk -v s=".$2" '$1==s {print $2; found=1} END{if(!found) print 0}'
}
symbol_size() { # elf symbol -> bytes (bash arithmetic; BSD awk has no strtonum)
  local hex
  hex=$("$AVR_NM" -S "$1" 2>/dev/null | awk -v sym="$2" '$NF==sym {print $2; found=1} END{if(!found) print "0"}')
  echo $((16#$hex))
}

{
  echo "# ATMlib2FX compact FX stream spike summary (ATMlib2FX-hlh.5)"
  echo "# fqbn: $FQBN"
  echo "# no git: identity is the source hashes in source-hashes.txt"
  echo "# variant,mode,program,text,data,bss,sram,score_bytes,stream_bytes,elf_sha256,elf"
} > "$SUMMARY"

build_variant() { # name mode extra slen bitmap page
  local name="$1" mode="$2" extra="$3" slen="$4" boff="$5" page="$6"
  local build_path="$OUT/avr-$name"
  local out_dir="$OUT/out-$name"
  local log="$OUT/build-$name.log"
  local elf="$build_path/fx_compact_spike.ino.elf"
  local flags="-DFC_MODE=$mode -I$REPO_ROOT/$SONG_INC -DFC_FX_DATA_PAGE=$page -DFC_BITMAP_OFFSET=$boff $extra"

  if [ "$mode" -ge 2 ]; then
    flags="$flags -DFC_STREAM_OFFSET=0 -DFC_STREAM_LEN=$slen"
  fi
  if [ "$mode" = 2 ]; then
    flags="$flags -DATM_HAS_FX_STREAM=1"
  fi
  if [ "$mode" = 3 ]; then
    flags="$flags -DATM_HAS_FX_COMPACT=1"
  fi

  "$ARDUINO_CLI" compile \
    --fqbn "$FQBN" \
    --library . \
    --build-path "$build_path" \
    --output-dir "$out_dir" \
    --build-property "compiler.cpp.extra_flags=$flags" \
    --build-property "compiler.c.extra_flags=$flags" \
    --verbose \
    "$SKETCH" > "$log" 2>&1
  local rc=$?
  if [ $rc -ne 0 ] || [ ! -f "$elf" ]; then
    echo "$name: BUILD FAILED - see $log" >&2
    tail -20 "$log" >&2
    return 1
  fi

  local text data bss program sram hash score stream
  text=$(section_size "$elf" text)
  data=$(section_size "$elf" data)
  bss=$(section_size "$elf" bss)
  program=$((text + data))
  sram=$((data + bss))
  hash=$(shasum -a 256 "$elf" | awk '{print $1}')
  score=$(symbol_size "$elf" _ZL5score)
  if [ "$mode" -ge 2 ]; then stream="$slen"; else stream=0; fi

  printf '%-18s %2d %7d %7d %6d %5d %6d %6s %7s  %s\n' \
    "$name" "$mode" "$program" "$text" "$data" "$bss" "$sram" \
    "$score" "$([ "$stream" != 0 ] && echo "$stream" || echo '-')" "${hash:0:16}"
  echo "  elf: $elf"
  echo "  sha256: $hash"
  echo "$name,$mode,$program,$text,$data,$bss,$sram,$score,$stream,$hash,$elf" >> "$SUMMARY"
}

echo "variant             md program    text   data   bss   sram  score  stream  elf(sha16)"
echo "--------------------------------------------------------------------------------------"
build_variant noaudio          0 "" 0 "$BITMAP_A" "$PAGE_A" || overall=1
build_variant music            1 "" 0 "$BITMAP_A" "$PAGE_A" || overall=1
build_variant oldfx            2 "" "$SLEN_A" "$BITMAP_A" "$PAGE_A" || overall=1
build_variant compact          3 "" "$SLEN_A" "$BITMAP_A" "$PAGE_A" || overall=1
build_variant compact_diag     3 "-DATM_FX_COMPACT_DIAG=1" "$SLEN_A" "$BITMAP_A" "$PAGE_A" || overall=1
build_variant compact_diag_t255 3 "-DATM_FX_COMPACT_DIAG=1" "$SLEN_T" "$BITMAP_T" "$PAGE_T" || overall=1

echo
echo "-- library-selection proof (compact build log) --"
grep -A2 'Multiple libraries were found for "ATMlib.h"' "$OUT/build-compact.log" | head -4
grep -m1 'Using library ATMlib' "$OUT/build-compact.log"
echo
echo "-- library globals (compact ELF, bytes) --"
for elf in "$OUT/avr-music/fx_compact_spike.ino.elf" "$OUT/avr-oldfx/fx_compact_spike.ino.elf" \
           "$OUT/avr-compact/fx_compact_spike.ino.elf"; do
  echo "  [$elf]"
  "$AVR_NM" -S --size-sort "$elf" \
    | grep -E ' (atm_fx_compact_state|atm_fx_stream_state|atmlib_state|channels|osc_params_array|osc_pha_acc_array|osc_cb|noteTable|score)$' \
    | while read -r addr size type sym; do
        printf '    %-24s %5d bytes  (%s)\n' "$sym" "$((16#$size))" "$type"
      done
done

echo
echo "summary: $SUMMARY"
exit "${overall:-0}"
