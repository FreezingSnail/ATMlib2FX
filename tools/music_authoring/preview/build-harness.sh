#!/usr/bin/env bash
#
# build-harness.sh - build the absim audio-capture harness
# (tools/music_authoring/preview/absim_audio_harness.cpp) against the LOCAL
# absim emulator core from the Ardens source tree.
#
# ATMlib2FX-3ii.2. Read-only use of Ardens; modifies nothing outside build/.
# Link line mirrors research/fx/footprint_baseline/trace/run-absim.sh.
#
# Usage: tools/music_authoring/preview/build-harness.sh [output_binary]
set -euo pipefail

PREVIEW_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$PREVIEW_DIR/../../.." && pwd)"
cd "$REPO_ROOT"

OUT="${1:-build/music-authoring/preview/absim_audio_harness}"

ARDENS_ROOT="${ARDENS_ROOT:-}"
if [ -z "$ARDENS_ROOT" ]; then
  for cand in "$REPO_ROOT/../ardens" "$REPO_ROOT/../../ardens" "$HOME/code/arduboy/ardens" "$HOME/code/Ardens" "$HOME/code/ardens"; do
    [ -d "$cand/src" ] && [ -f "$cand/build/libardensdebuggerlib.a" ] && { ARDENS_ROOT="$cand"; break; }
  done
fi
if [ -z "$ARDENS_ROOT" ]; then
  echo "Ardens source/build not found; set ARDENS_ROOT" >&2
  exit 1
fi
export ARDENS_ROOT

mkdir -p "$(dirname "$OUT")"

LLVM="$ARDENS_ROOT/build/_deps/llvm-project-build/lib"
CXX="${CXX:-c++}"

"$CXX" -std=gnu++17 -O2 -DNDEBUG -DARDENS_LLVM -DMINIZ_STATIC_DEFINE \
  -I"$ARDENS_ROOT/src" \
  -I"$ARDENS_ROOT/deps/bitsery/include" \
  -I"$ARDENS_ROOT/deps/miniz" \
  -I"$ARDENS_ROOT/build/deps/miniz" \
  -I"$ARDENS_ROOT/deps/fmt/include" \
  -isystem "$ARDENS_ROOT/deps" \
  -isystem "$ARDENS_ROOT/build/_deps/llvm-project-build/include" \
  -isystem "$ARDENS_ROOT/build/_deps/llvm-project-src/llvm/include" \
  "$PREVIEW_DIR/absim_audio_harness.cpp" \
  "$ARDENS_ROOT/build/libardensdebuggerlib.a" \
  "$ARDENS_ROOT/build/deps/miniz/libminiz.a" \
  "$ARDENS_ROOT/build/deps/fmt/libfmt.a" \
  "$LLVM/libLLVMDebugInfoDWARF.a" \
  "$LLVM/libLLVMObject.a" \
  "$LLVM/libLLVMIRReader.a" \
  "$LLVM/libLLVMBitReader.a" \
  "$LLVM/libLLVMAsmParser.a" \
  "$LLVM/libLLVMCore.a" \
  "$LLVM/libLLVMRemarks.a" \
  "$LLVM/libLLVMBitstreamReader.a" \
  "$LLVM/libLLVMMCParser.a" \
  "$LLVM/libLLVMMC.a" \
  "$LLVM/libLLVMDebugInfoCodeView.a" \
  "$LLVM/libLLVMTextAPI.a" \
  "$LLVM/libLLVMBinaryFormat.a" \
  "$LLVM/libLLVMTargetParser.a" \
  "$LLVM/libLLVMSupport.a" \
  -lm "$LLVM/libLLVMDemangle.a" \
  -o "$OUT"

echo "built $OUT" >&2
