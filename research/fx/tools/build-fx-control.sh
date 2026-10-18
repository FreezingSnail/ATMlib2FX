#!/usr/bin/env bash
#
# build-fx-control.sh - reproducible lane for the compact-backend control and
# SFX semantics (ATMlib2FX-hlh.9).
#
# Produces, under build/fx-port/control/ (a NEW lane; the retained
# build/fx-port/compact/ lane and the hlh.5 ELFs are never touched):
#   - the compact music + SFX converters, generated assets and the PROGMEM SFX
#     header
#   - the host control test (pause/resume, replacement atomicity, prefill,
#     stop-mute, SFX borrow/restore) and the music+SFX trace equivalence vs the
#     original reference trace
#   - AVR images for the compact music-only configuration (before) and the SFX
#     configuration (after), with avr-size, symbol sizes and ELF hashes
#   - a default-configuration regression: rebuild the hlh.1 music fixture and
#     compare .text against the retained hlh.1 ELF
#   - a CSV summary and a SHA-256 evidence manifest
#
# No git commands: identity is recorded as source/ELF SHA-256 hashes.
#
# Usage: research/fx/tools/build-fx-control.sh
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$REPO_ROOT"

FQBN="arduboy-homemade:avr:arduboy-fx"
SKETCH="research/fx/fx_compact_spike"
BASELINE_SKETCH="research/fx/footprint_baseline"
SONG_INC="examples/arduino/songs/song01_sfx"
LANE="build/fx-port"
OUT="$LANE/control"
REF="$REPO_ROOT/research/fx/footprint_baseline/trace/reference/reference_trace_music_sfx.csv"
SHIM="$REPO_ROOT/research/fx/footprint_baseline/trace/avr_shim"
AVR_BIN="$HOME/Library/Arduino15/packages/arduino/tools/avr-gcc/7.3.0-atmel3.6.1-arduino7/bin"
AVR_SIZE="$AVR_BIN/avr-size"
AVR_NM="$AVR_BIN/avr-nm"
AVR_OBJCOPY="$AVR_BIN/avr-objcopy"
ARDUINO_CLI="${ARDUINO_CLI:-$(command -v arduino-cli)}"
CC="${CC:-cc}"
overall=0

mkdir -p "$OUT"
SUMMARY="$OUT/control-summary.csv"

echo "== ATMlib2FX compact control + SFX lane (ATMlib2FX-hlh.9) =="
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
           src/cmd_parse.c src/osc.c \
           research/fx/fx_compact_spike/fx_compact_spike.ino \
           research/fx/fx_compact_spike/control/fx_compile_sfx.c \
           research/fx/fx_compact_spike/control/control_test.c \
           research/fx/fx_compact_spike/control/sfx_trace_main.c \
           research/fx/tools/build-fx-control.sh \
           examples/arduino/songs/song01_sfx/song.h; do
    echo "$(shasum -a 256 "$f" | awk '{print $1}')  $f"
  done
} | tee "$OUT/source-hashes.txt"

# ---- 1. converters + assets -------------------------------------------------
"$CC" -std=c11 -O2 -Wall -Wextra -Wno-unused-parameter \
  -Isrc -I"$SONG_INC" research/fx/tools/fx_compact_spike/fx_compile_compact.c \
  -o "$OUT/compact_conv" || exit 1
"$OUT/compact_conv" --out "$OUT/compact_stream.bin" \
  > "$OUT/compact_stream.meta" 2> "$OUT/compact_stream.log" || exit 1
cat "$OUT/compact_stream.log"

"$CC" -std=c11 -O2 -Wall -Wextra -Wno-unused-parameter \
  -Isrc -I"$SONG_INC" research/fx/fx_compact_spike/control/fx_compile_sfx.c \
  -o "$OUT/fx_compile_sfx" || exit 1
"$OUT/fx_compile_sfx" 2 "$OUT/sfx_compact.bin" "$OUT/sfx_compact.h" \
  "sfx_compact_stream" 2> "$OUT/sfx_compact.log" || exit 1
cat "$OUT/sfx_compact.log"

"$CC" -std=c11 -O2 -Wall -Wextra research/fx/tools/fx_make_fxdata.c \
  -o "$OUT/fx_make_fxdata" || exit 1
"$OUT/fx_make_fxdata" --stream "$OUT/compact_stream.bin" \
  --out "$OUT/fxdata_control.bin" > "$OUT/fxdata_control.meta" || exit 1
cat "$OUT/fxdata_control.meta"

SLEN=$(awk -F= '/^stream_len=/{print $2}' "$OUT/fxdata_control.meta")
BITMAP=$(awk -F= '/^bitmap_offset=/{print $2}' "$OUT/fxdata_control.meta")
PAGE=$(awk -F= '/^data_page=/{print $2}' "$OUT/fxdata_control.meta")
SFX_BYTES=$(wc -c < "$OUT/sfx_compact.bin" | tr -d ' ')
echo "stream_bytes=$SLEN  sfx_bytes=$SFX_BYTES  data_page=$PAGE"
echo

# ---- 2. host control test ---------------------------------------------------
echo "-- host control test (pause/resume, replacement, prefill, stop, SFX) --"
"$CC" -std=c11 -O1 -w -I"$SHIM" -Isrc \
  research/fx/fx_compact_spike/control/control_test.c -o "$OUT/control_test" || exit 1
"$OUT/control_test" > "$OUT/control_test.out" 2> "$OUT/control_test.err"
rc=$?
cat "$OUT/control_test.out" "$OUT/control_test.err"
[ $rc -eq 0 ] || { echo "control_test FAILED" >&2; overall=1; }

# ---- 3. music + SFX trace equivalence --------------------------------------
echo
echo "-- host music+SFX trace equivalence vs original reference --"
"$CC" -std=c11 -O1 -w -I"$SHIM" -Isrc \
  research/fx/fx_compact_spike/control/sfx_trace_main.c -o "$OUT/sfx_trace_main" || exit 1
"$OUT/sfx_trace_main" "$OUT/compact_stream.bin" 512 64 "$OUT/sfx_compact.bin" \
  > "$OUT/sfx_trace.csv" 2> "$OUT/sfx_trace.stderr" || exit 1
cat "$OUT/sfx_trace.stderr"
# determinism
"$OUT/sfx_trace_main" "$OUT/compact_stream.bin" 512 64 "$OUT/sfx_compact.bin" \
  > "$OUT/sfx_trace.2.csv" 2> /dev/null
cmp -s "$OUT/sfx_trace.csv" "$OUT/sfx_trace.2.csv" \
  && echo "determinism: OK" || { echo "determinism: FAILED" >&2; overall=1; }
rm -f "$OUT/sfx_trace.2.csv"

norm() {
  awk -F, 'NR==1{for(i=1;i<=NF;i++) if($i !~ /_ps$/ && $i !~ /_delay$/) keep[i]=1}
           {out=""; for(i=1;i<=NF;i++) if(keep[i]) out=out (i>1?",":"") $i; print out}' "$1"
}
norm "$REF" > "$OUT/ref_sfx_norm.csv"
norm "$OUT/sfx_trace.csv" > "$OUT/sfx_norm.csv"
if diff -q "$OUT/ref_sfx_norm.csv" "$OUT/sfx_norm.csv" > /dev/null; then
  {
    echo "# compact music+SFX equivalence (ATMlib2FX-hlh.9)"
    echo "music_ticks=512"
    echo "sfx_start_music_tick=64"
    echo "dropped_columns=cN_ps,cN_delay"
    echo "reference_sha256=$(shasum -a 256 "$REF" | awk '{print $1}')"
    echo "music_stream_sha256=$(shasum -a 256 "$OUT/compact_stream.bin" | awk '{print $1}')"
    echo "sfx_stream_sha256=$(shasum -a 256 "$OUT/sfx_compact.bin" | awk '{print $1}')"
    echo "trace_sha256=$(shasum -a 256 "$OUT/sfx_trace.csv" | awk '{print $1}')"
    echo "result=MATCH"
  } | tee "$OUT/sfx_equivalence.txt"
else
  echo "result=DIFF" | tee "$OUT/sfx_equivalence.txt" >&2
  diff "$OUT/ref_sfx_norm.csv" "$OUT/sfx_norm.csv" | head -20 >&2
  overall=1
fi

# ---- 4. AVR images ----------------------------------------------------------
section_size() { "$AVR_SIZE" -A "$1" | awk -v s=".$2" '$1==s{print $2;found=1} END{if(!found)print 0}'; }
symbol_size() {
  local hex
  hex=$("$AVR_NM" -S "$1" 2>/dev/null | awk -v sym="$2" '$NF==sym{print $2;found=1} END{if(!found)print "0"}')
  echo $((16#$hex))
}

{
  echo "# ATMlib2FX compact control + SFX summary (ATMlib2FX-hlh.9)"
  echo "# fqbn: $FQBN"
  echo "# no git: identity is the source hashes in source-hashes.txt"
  echo "# variant,mode,program,text,data,bss,sram,sfx,elf_sha256,elf"
} > "$SUMMARY"

build_variant() { # name mode extra
  local name="$1" mode="$2" extra="$3"
  local build_path="$OUT/avr-$name"
  local out_dir="$OUT/out-$name"
  local log="$OUT/build-$name.log"
  local elf="$build_path/fx_compact_spike.ino.elf"
  local flags="-DFC_MODE=$mode -I$REPO_ROOT/$SONG_INC -DFC_FX_DATA_PAGE=$PAGE -DFC_BITMAP_OFFSET=$BITMAP $extra"

  if [ "$mode" -ge 3 ]; then
    flags="$flags -DFC_STREAM_OFFSET=0 -DFC_STREAM_LEN=$SLEN -DATM_HAS_FX_COMPACT=1"
  fi
  if [ "$mode" -eq 4 ]; then
    flags="$flags -DATM_FX_COMPACT_SFX=1 -I$REPO_ROOT/$OUT"
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
    overall=1
    return 1
  fi

  local text data bss program sram hash
  text=$(section_size "$elf" text)
  data=$(section_size "$elf" data)
  bss=$(section_size "$elf" bss)
  program=$((text + data))
  sram=$((data + bss))
  hash=$(shasum -a 256 "$elf" | awk '{print $1}')
  local sfx=0
  [ "$mode" -eq 4 ] && sfx="$SFX_BYTES"

  printf '%-14s %2d %7d %7d %6d %5d %6d %6s  %s\n' \
    "$name" "$mode" "$program" "$text" "$data" "$bss" "$sram" \
    "$sfx" "${hash:0:16}"
  echo "  elf: $elf"
  echo "  sha256: $hash"
  echo "$name,$mode,$program,$text,$data,$bss,$sram,$sfx,$hash,$elf" >> "$SUMMARY"
}

echo
echo "-- AVR images (before = music-only compact, after = + SFX) --"
echo "variant        md program    text   data   bss   sram    sfx  elf(sha16)"
echo "----------------------------------------------------------------------------"
build_variant compact    3 ""
build_variant control    4 ""
build_variant control_dg 4 "-DATM_FX_COMPACT_DIAG=1"

# ---- 5. default-configuration regression (hlh.1 fixture, FP_AUDIO=1) -------
echo
echo "-- default-configuration regression (no FX macros) --"
DEF_BUILD="$OUT/avr-default"
"$ARDUINO_CLI" compile \
  --fqbn "$FQBN" --library . \
  --build-path "$DEF_BUILD" --output-dir "$OUT/out-default" \
  --build-property "compiler.cpp.extra_flags=-DFP_AUDIO=1 -I$REPO_ROOT/$SONG_INC" \
  --verbose "$BASELINE_SKETCH" > "$OUT/build-default.log" 2>&1
DEF_ELF="$DEF_BUILD/footprint_baseline.ino.elf"
RET_ELF="$LANE/avr-music/footprint_baseline.ino.elf"
if [ -f "$DEF_ELF" ] && [ -f "$RET_ELF" ]; then
  "$AVR_OBJCOPY" -O binary --only-section=.text "$DEF_ELF" "$OUT/default.text.bin"
  "$AVR_OBJCOPY" -O binary --only-section=.text "$RET_ELF" "$OUT/retained-music.text.bin"
  if cmp -s "$OUT/default.text.bin" "$OUT/retained-music.text.bin"; then
    echo "default .text byte-identical to retained hlh.1 music ELF: OK"
    echo "default_text_identical=1" > "$OUT/default_regression.txt"
  else
    echo "default .text DIFFERS from retained hlh.1 music ELF" >&2
    echo "default_text_identical=0" > "$OUT/default_regression.txt"
    overall=1
  fi
  echo "default_text_sha256=$(shasum -a 256 "$OUT/default.text.bin" | awk '{print $1}')" >> "$OUT/default_regression.txt"
else
  echo "default regression: missing elf (def=$DEF_ELF ret=$RET_ELF)" >&2
  overall=1
fi

# ---- 6. symbol sizes --------------------------------------------------------
echo
echo "-- library globals (bytes) --"
for elf in "$OUT/avr-compact/fx_compact_spike.ino.elf" "$OUT/avr-control/fx_compact_spike.ino.elf"; do
  echo "  [$elf]"
  "$AVR_NM" -S --size-sort "$elf" \
    | grep -E ' (atm_fx_compact_state|atmlib_state|channels|osc_params_array)$' \
    | while read -r addr size type sym; do
        printf '    %-24s %5d bytes  (%s)\n' "$sym" "$((16#$size))" "$type"
      done
done

# ---- 7. evidence manifest ---------------------------------------------------
echo
echo "-- evidence manifest --"
{
  for f in "$OUT/compact_stream.bin" "$OUT/sfx_compact.bin" "$OUT/sfx_trace.csv" \
           "$OUT/sfx_equivalence.txt" "$OUT/avr-compact/fx_compact_spike.ino.elf" \
           "$OUT/avr-control/fx_compact_spike.ino.elf" \
           "$OUT/avr-control_dg/fx_compact_spike.ino.elf" "$OUT/fxdata_control.bin"; do
    [ -f "$f" ] && shasum -a 256 "$f"
  done
} | tee "$OUT/evidence-sha256.txt"

echo
echo "summary: $SUMMARY"
exit "${overall:-0}"
