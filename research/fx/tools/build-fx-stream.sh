#!/usr/bin/env bash
#
# build-fx-stream.sh - reproducible build/measurement lane for the compiled FX
# stream spike (ATMlib2FX-aoe).
#
# Same board/toolchain/options as the ATMlib2FX-hlh.1 baseline lane
# (build/fx-port/). Produces, under build/fx-port/fx-stream/:
#   - converter + generated streams (authored tempo 50 and requested tempo 255)
#   - fxdata images (stream + deterministic stress bitmap)
#   - AVR images for FS_MODE=0..3 with whole-image sizes and ELF hashes
#   - a CSV summary
#
# Usage: research/fx/tools/build-fx-stream.sh
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$REPO_ROOT"

FQBN="arduboy-homemade:avr:arduboy-fx"
SKETCH="research/fx/fx_stream_spike"
SONG_INC="examples/arduino/songs/song01_sfx"
LANE="build/fx-port"
OUT="$LANE/fx-stream"
AVR_BIN="$HOME/Library/Arduino15/packages/arduino/tools/avr-gcc/7.3.0-atmel3.6.1-arduino7/bin"
AVR_SIZE="$AVR_BIN/avr-size"
AVR_NM="$AVR_BIN/avr-nm"
ARDUINO_CLI="${ARDUINO_CLI:-$(command -v arduino-cli)}"
CC="${CC:-cc}"

mkdir -p "$OUT"
SUMMARY="$OUT/fx-stream-summary.csv"

echo "== ATMlib2FX compiled FX stream spike =="
echo "repo      : $REPO_ROOT"
echo "git HEAD  : $(git rev-parse HEAD)"
echo "fqbn      : $FQBN"
echo "sketch    : $SKETCH"
echo "lane      : $OUT"
echo "arduino-cli: $($ARDUINO_CLI version 2>/dev/null)"
echo

# ---- 1. converter + streams ------------------------------------------------
"$CC" -std=c11 -O2 -Wall -Wextra -Wno-unused-parameter \
  -Isrc -I"$SONG_INC" research/fx/tools/fx_compile_stream.c \
  -o "$OUT/fx_compile_stream" || exit 1

./"$OUT/fx_compile_stream" --out "$OUT/spike_stream.bin" \
  > "$OUT/spike_stream.meta" 2> "$OUT/spike_stream.log"
./"$OUT/fx_compile_stream" --out "$OUT/spike_stream_t255.bin" --tempo 255 \
  > "$OUT/spike_stream_t255.meta" 2> "$OUT/spike_stream_t255.log"

# ---- 2. fxdata images ------------------------------------------------------
"$CC" -std=c11 -O2 -Wall -Wextra research/fx/tools/fx_make_fxdata.c -o "$OUT/fx_make_fxdata" || exit 1

make_fxdata() { # stream out
  ./"$OUT/fx_make_fxdata" --stream "$1" --out "$2" > "$2.meta"
  # expose as shell vars
  STREAM_LEN=$(awk -F= '/^stream_len=/{print $2}' "$2.meta")
  BITMAP_OFFSET=$(awk -F= '/^bitmap_offset=/{print $2}' "$2.meta")
  DATA_PAGE=$(awk -F= '/^data_page=/{print $2}' "$2.meta")
}

make_fxdata "$OUT/spike_stream.bin" "$OUT/fxdata_spike.bin"
STREAM_LEN_A=$STREAM_LEN; BITMAP_OFFSET_A=$BITMAP_OFFSET; DATA_PAGE_A=$DATA_PAGE
make_fxdata "$OUT/spike_stream_t255.bin" "$OUT/fxdata_spike_t255.bin"
STREAM_LEN_T=$STREAM_LEN; BITMAP_OFFSET_T=$BITMAP_OFFSET; DATA_PAGE_T=$DATA_PAGE

echo "authored stream: $(cat "$OUT/spike_stream.meta" | tr '\n' ' ')"
echo "tempo255 stream: $(cat "$OUT/spike_stream_t255.meta" | tr '\n' ' ')"
echo "fxdata page    : authored=$DATA_PAGE_A t255=$DATA_PAGE_T"
echo

# ---- 3. AVR images ---------------------------------------------------------
section_size() { # file section
  "$AVR_SIZE" -A "$1" | awk -v s=".$2" '$1==s {print $2; found=1} END{if(!found) print 0}'
}

{
  echo "# ATMlib2FX compiled FX stream spike summary"
  echo "# git HEAD: $(git rev-parse HEAD)"
  echo "# fqbn: $FQBN"
  echo "# variant,mode,program,text,data,bss,sram,stream_bytes,elf_sha256,elf"
} > "$SUMMARY"

build_variant() { # name mode extra_flags stream_len bitmap_off data_page
  local name="$1" mode="$2" extra="$3" slen="$4" boff="$5" page="$6"
  local build_path="$OUT/avr-$name"
  local out_dir="$OUT/out-$name"
  local log="$OUT/build-$name.log"
  local elf="$build_path/fx_stream_spike.ino.elf"
  local flags="-DFS_MODE=$mode -I$REPO_ROOT/$SONG_INC $extra"

  if [ "$mode" -ge 1 ]; then
    flags="$flags -DFS_FX_DATA_PAGE=$page -DFS_BITMAP_OFFSET=$boff"
  fi
  if [ "$mode" -ge 2 ]; then
    flags="$flags -DATM_HAS_FX_STREAM=1 -DFS_STREAM_OFFSET=0 -DFS_STREAM_LEN=$slen"
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

  local text data bss program sram hash
  text=$(section_size "$elf" text)
  data=$(section_size "$elf" data)
  bss=$(section_size "$elf" bss)
  program=$((text + data))
  sram=$((data + bss))
  hash=$(shasum -a 256 "$elf" | awk '{print $1}')

  printf '%-18s %2d %7d %7d %6d %5d %6d %7s  %s\n' \
    "$name" "$mode" "$program" "$text" "$data" "$bss" "$sram" \
    "$([ "$mode" -ge 2 ] && echo "$slen" || echo '-')" "${hash:0:16}"
  echo "  elf: $elf"
  echo "  sha256: $hash"
  echo "$name,$mode,$program,$text,$data,$bss,$sram,$([ "$mode" -ge 2 ] && echo "$slen" || echo 0),$hash,$elf" >> "$SUMMARY"
}

echo "variant             md program    text   data   bss   sram  stream  elf(sha16)"
echo "----------------------------------------------------------------------------------"
build_variant shell_fx         0 "" 0 0 0 || overall=1
build_variant fx_gfx           1 "" 0 "$BITMAP_OFFSET_A" "$DATA_PAGE_A" || overall=1
build_variant fx_stream        2 "" "$STREAM_LEN_A" "$BITMAP_OFFSET_A" "$DATA_PAGE_A" || overall=1
build_variant fx_diag          3 "-DATM_FX_STREAM_DIAG=1" "$STREAM_LEN_A" "$BITMAP_OFFSET_A" "$DATA_PAGE_A" || overall=1
# stress variant uses the requested-tempo-255 stream (same size/page here)
build_variant fx_diag_t255     3 "-DATM_FX_STREAM_DIAG=1" "$STREAM_LEN_T" "$BITMAP_OFFSET_T" "$DATA_PAGE_T" || overall=1

echo
echo "-- library globals (fx_stream ELF) --"
"$AVR_NM" -S --size-sort "$OUT/avr-fx_stream/fx_stream_spike.ino.elf" \
  | grep -E ' (atm_fx_stream_state|atmlib_state|channels|osc_params_array|osc_pha_acc_array|osc_cb|noteTable)$' \
  | while read -r addr size type sym; do
      printf '%-24s %5d bytes  (%s)\n' "$sym" "$((16#$size))" "$type"
    done

echo
echo "summary: $SUMMARY"
exit "${overall:-0}"
