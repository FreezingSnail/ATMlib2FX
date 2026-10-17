#!/usr/bin/env bash
#
# run-ardens.sh - launch the compiled FX stream demo in the Ardens GUI.
#
# Uses the production FS_MODE=2 image (stream playback + FX bitmap read +
# FX::display at 52 fps) and the generated FX data image. The same absim core
# that the headless harness uses drives the GUI, so the emulated build/stream
# placement is identical to the verified absim runs.
#
# No `save=` file is passed on purpose: absim/Ardens then place the data image
# at the top of the 16 MB chip (0xFFF800, page 0xFFF8), which matches the
# fixture's -DFS_FX_DATA_PAGE=65528. Adding a save image shifts the data page and
# requires a rebuild with the new page.
#
# Prerequisite: research/fx/tools/build-fx-stream.sh (builds the hex + fxdata image).
# Usage: research/fx/fx_stream_spike/run-ardens.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$REPO_ROOT"

HEX="$REPO_ROOT/build/fx-port/fx-stream/avr-fx_stream/fx_stream_spike.ino.hex"
FXDATA="$REPO_ROOT/build/fx-port/fx-stream/fxdata_spike.bin"

if [ ! -f "$HEX" ] || [ ! -f "$FXDATA" ]; then
  echo "missing demo images; run research/fx/tools/build-fx-stream.sh first" >&2
  exit 1
fi

ARDENS="${ARDENS:-}"
if [ -z "$ARDENS" ]; then
  for cand in "$(command -v Ardens 2>/dev/null || true)" \
              "$HOME/code/arduboy/Ardens/build/Ardens.app/Contents/MacOS/Ardens" \
              "/Applications/Ardens.app/Contents/MacOS/Ardens"; do
    if [ -n "$cand" ] && [ -x "$cand" ]; then ARDENS="$cand"; break; fi
  done
fi
if [ -z "$ARDENS" ]; then
  echo "Ardens executable not found; set ARDENS=/path/to/Ardens" >&2
  exit 1
fi

echo "Ardens : $ARDENS"
echo "sketch : $HEX"
echo "fxdata : $FXDATA (base 0xFFF800, page 0xFFF8)"
echo "fx CS  : d1 (CART_CS_SDA)"

# key=value arguments, same shape as CreatureGathererFX `make run`.
exec "$ARDENS" fxport=d1 display=ssd1306 "file=$HEX" "file=$FXDATA"
