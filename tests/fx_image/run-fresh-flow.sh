#!/usr/bin/env bash
#
# run-fresh-flow.sh - fresh-flow reproduction for the finite-v1 FX music +
# graphics example (ATMlib2FX-hlh.10).
#
# Reproduces the documented example flow from a built repo, using only the
# supported host tools and the local Arduino toolchain:
#
#   1. convert a legacy score with tools/fx_pack (read-only invocation);
#   2. pack stream + a real bitmap with tools/fx_image;
#   3. build examples/fx/music_graphics with arduino-cli
#      (FQBN arduboy-homemade:avr:arduboy-fx);
#   4. run the absim harness and require zero underruns and zero decoder error;
#   5. report image/ELF sizes, hashes, and confirm the default PROGMEM library
#      build is untouched (no src/ changes).
#
# No network, no installs, no git writes. Everything lands under
# build/fx-port/image/. Usage: tests/fx_image/run-fresh-flow.sh [ms]
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
cd "$REPO_ROOT"

MS="${1:-12000}"
OUT="build/fx-port/image"
FQBN="arduboy-homemade:avr:arduboy-fx"
ARDENS_ROOT="${ARDENS_ROOT:-$HOME/code/arduboy/Ardens}"
ARDUINO_CLI="${ARDUINO_CLI:-/opt/homebrew/bin/arduino-cli}"
SONG="examples/arduino/songs/song01_sfx/song.h"
PBM="examples/fx/art/note_32x16.pbm"
SKETCH="examples/fx/music_graphics"
AVR_BIN="$HOME/Library/Arduino15/packages/arduino/tools/avr-gcc/7.3.0-atmel3.6.1-arduino7/bin"

mkdir -p "$OUT"
RESULT="$OUT/fresh-flow.txt"
: > "$RESULT"

log() { echo "$@" | tee -a "$RESULT"; }

log "== fx_image fresh-flow (ATMlib2FX-hlh.10) =="
log "repo : $REPO_ROOT"
log "fqbn : $FQBN"
log "cli  : $($ARDUINO_CLI version 2>/dev/null)"

# ---- 1. convert the legacy score (tools/fx_pack, read-only) ----------------
FX_PACK="$OUT/fx_pack/fx_pack"
if ! make -C tools/fx_pack CC="${CC:-cc}" BUILD_DIR="$REPO_ROOT/$OUT/fx_pack" \
      > "$OUT/fx_pack-build.log" 2>&1 || [ ! -x "$FX_PACK" ]; then
  # Fall back to an existing build of the tool if a concurrent edit broke it.
  if [ -x "build/fx-port/pack/fx_pack" ]; then
    FX_PACK="build/fx-port/pack/fx_pack"
    log "note : using prebuilt $FX_PACK"
  else
    log "convert: fx_pack build failed - see $OUT/fx_pack-build.log"
    exit 1
  fi
fi
"$FX_PACK" --song "$SONG" --symbol score \
  --out "$OUT/stream.bin" --meta "$OUT/stream_meta.json" \
  --workdir "$OUT/fx_pack/work" > "$OUT/convert.log" 2>&1
log "convert: $(cat "$OUT/convert.log")"

# ---- 2. pack the FX data image --------------------------------------------
"$OUT/fx_image" --stream "$OUT/stream.bin" --bitmap "$PBM" \
  --out "$OUT/fxdata.bin" --meta "$OUT/meta.json" \
  --header "$OUT/fxdata_config.h" > "$OUT/fxdata.meta"
log "pack   : $(tr '\n' ' ' < "$OUT/fxdata.meta")"

# ---- 3. build the example --------------------------------------------------
FLAGS="-DATM_HAS_FX_COMPACT=1 -DATM_FX_COMPACT_DIAG=1 -DFX_IMAGE_USE_HEADER -I$REPO_ROOT/$OUT"
"$ARDUINO_CLI" compile --fqbn "$FQBN" --library . \
  --build-path "$OUT/avr-music_graphics" --output-dir "$OUT/out-music_graphics" \
  --build-property "compiler.cpp.extra_flags=$FLAGS" \
  --build-property "compiler.c.extra_flags=$FLAGS" \
  --verbose "$SKETCH" > "$OUT/build-music_graphics.log" 2>&1 \
  || { log "build: FAILED - see $OUT/build-music_graphics.log"; tail -20 "$OUT/build-music_graphics.log" | tee -a "$RESULT"; exit 1; }

ELF="$OUT/avr-music_graphics/music_graphics.ino.elf"
section_size() { "$AVR_BIN/avr-size" -A "$1" | awk -v s=".$2" '$1==s{print $2; found=1} END{if(!found)print 0}'; }
PROGRAM=$(( $(section_size "$ELF" text) + $(section_size "$ELF" data) ))
SRAM=$(( $(section_size "$ELF" data) + $(section_size "$ELF" bss) ))
log "build  : program=${PROGRAM}B sram=${SRAM}B elf=$(shasum -a 256 "$ELF" | awk '{print substr($1,1,16)}')"

# ---- 4. absim device run (zero underruns) ---------------------------------
ARDENS_ROOT="$ARDENS_ROOT" "$HERE/run-absim.sh" "$ELF" "$OUT/fxdata.bin" "$MS" \
  2>&1 | tee -a "$RESULT"

# ---- 5. sizes, hashes, default-build check --------------------------------
log ""
log "sizes:"
log "  stream.bin    $(wc -c < "$OUT/stream.bin" | tr -d ' ') B  sha256 $(shasum -a 256 "$OUT/stream.bin" | awk '{print $1}')"
log "  fxdata.bin    $(wc -c < "$OUT/fxdata.bin" | tr -d ' ') B  sha256 $(shasum -a 256 "$OUT/fxdata.bin" | awk '{print $1}')"
log "  sketch ELF    ${PROGRAM} B program / ${SRAM} B SRAM  sha256 $(shasum -a 256 "$ELF" | awk '{print $1}')"

DEFAULT_DIFF="$(git status --porcelain -- src/ library.properties library.json || true)"
if [ -n "$DEFAULT_DIFF" ]; then
  log "default build: CHANGED (unexpected)"
  log "$DEFAULT_DIFF"
  exit 1
fi
log "default build: untouched (no src/ or default-path changes)"

log ""
log "results: $RESULT"
