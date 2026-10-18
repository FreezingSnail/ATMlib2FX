#!/usr/bin/env bash
#
# run-multi-evidence.sh - multi-stream packing evidence for fx_image
# (ATMlib2FX-hlh.13).
#
# Packs several real compact streams plus the example bitmap into one FX data
# image, writes the generated index header and metadata, then proves the
# per-song offsets by reading every embedded stream back out of the image and
# byte-comparing it against its source. Re-runs once to show determinism.
#
# Committed fixtures are always used; streams under build/fx-port/ are folded
# in when present (they are generated artifacts). No network, no installs, no
# git. Everything lands under build/fx-port/image-multi/.
#
# Usage: tests/fx_image/run-multi-evidence.sh
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
cd "$REPO_ROOT"

OUT="build/fx-port/image-multi"
PBM="examples/fx/art/note_32x16.pbm"
LOG="$OUT/commands.txt"
EVIDENCE="$OUT/evidence-sha256.txt"
mkdir -p "$OUT"
: > "$LOG"
: > "$EVIDENCE"

log() { echo "$@" | tee -a "$LOG"; }

FX_IMAGE="$REPO_ROOT/build/fx-port/image/fx_image"
make -C tools/fx_image > "$OUT/build.log" 2>&1
log "make -C tools/fx_image"

# --- assemble the real streams (input order is the catalog order) -----------
STREAM_ARGS=(
  --stream "basic:examples/music_authoring/fx/basic/expected/stream.bin"
  --stream "stress:examples/music_authoring/fx/stress/expected/stream.bin"
)
SOURCES=(
  "examples/music_authoring/fx/basic/expected/stream.bin"
  "examples/music_authoring/fx/stress/expected/stream.bin"
)
for f in build/fx-port/image/stream.bin build/fx-port/loops/sync.stream.bin \
         build/fx-port/loops/target.stream.bin build/fx-port/loops/extrapass.stream.bin; do
  [ -f "$f" ] || continue
  base="$(basename "$f")"
  name="${base%.stream.bin}"
  name="$(printf '%s' "$name" | tr -c 'A-Za-z0-9_' '_')"
  STREAM_ARGS+=(--stream "$name:$f")
  SOURCES+=("$f")
done

CMD=("$FX_IMAGE" "${STREAM_ARGS[@]}" --bitmap "$PBM"
     --out "$OUT/fxdata.bin" --meta "$OUT/meta.json"
     --header "$OUT/fxdata_config.h")
log "+ ${CMD[*]}"
"${CMD[@]}" > "$OUT/fxdata.meta"

echo "--- generated header ($OUT/fxdata_config.h) ---" | tee -a "$LOG"
cat "$OUT/fxdata_config.h" | tee -a "$LOG"

# --- prove offsets: read each stream back from the image --------------------
count="$(awk -F= '/^stream_count=/{print $2}' "$OUT/fxdata.meta")"
log ""
log "read-back parity ($count streams):"
for ((i = 0; i < count; i++)); do
  name="$(awk -F= -v k="stream${i}_name" '$1==k{print $2}' "$OUT/fxdata.meta")"
  off="$(awk -F= -v k="stream${i}_offset" '$1==k{print $2}' "$OUT/fxdata.meta")"
  len="$(awk -F= -v k="stream${i}_len" '$1==k{print $2}' "$OUT/fxdata.meta")"
  loop="$(awk -F= -v k="stream${i}_loop" '$1==k{print $2}' "$OUT/fxdata.meta")"
  src="${SOURCES[$i]}"
  dd if="$OUT/fxdata.bin" of="$OUT/rb_$i.bin" bs=1 skip="$off" \
     count="$len" 2>/dev/null
  cmp -s "$OUT/rb_$i.bin" "$src" \
    || { echo "FAIL: stream $i ($name) parity at offset $off" >&2; exit 1; }
  log "  stream $i name=$name offset=$off len=$len loop=$loop  == $src  OK"
done

# --- determinism ------------------------------------------------------------
"${CMD[@]}" --out "$OUT/fxdata_det.bin" > /dev/null
cmp -s "$OUT/fxdata.bin" "$OUT/fxdata_det.bin" \
  || { echo "FAIL: not deterministic" >&2; exit 1; }
log ""
log "determinism: byte-identical across runs"

# --- image/bitmap extents ---------------------------------------------------
boff="$(awk -F= '/^bitmap_offset=/{print $2}' "$OUT/fxdata.meta")"
bw="$(awk -F= '/^bitmap_width=/{print $2}' "$OUT/fxdata.meta")"
bh="$(awk -F= '/^bitmap_height=/{print $2}' "$OUT/fxdata.meta")"
dd if="$OUT/fxdata.bin" of="$OUT/rb_bitmap_hdr.bin" bs=1 skip="$boff" \
   count=4 2>/dev/null
log "bitmap header at offset $boff: $(xxd -p "$OUT/rb_bitmap_hdr.bin") (w=$bw h=$bh)"

# --- hashes -----------------------------------------------------------------
{
  echo "# fx_image multi-stream evidence hashes"
  for f in "$OUT/fxdata.bin" "$OUT/fxdata_config.h" "$OUT/meta.json" \
           "$PBM" "${SOURCES[@]}"; do
    shasum -a 256 "$f"
  done
} > "$EVIDENCE"
cat "$EVIDENCE" | tee -a "$LOG"

log ""
log "results: $OUT"
