#!/usr/bin/env bash
#
# run-tests.sh - permanent host checks for the maintained FX data-image packer
# (ATMlib2FX-hlh.10).
#
# Builds tools/fx_image, runs the C selftest (bitmap parsing/conversion, layout,
# single-page 24-bit extents, compose/header), then does shell end-to-end checks:
#
#   * fixture image is byte-identical to the read-only reference packer
#     tests/fx_image/reference/fx_make_fxdata.c (same layout and data page);
#   * the example PBM packs with the expected metadata;
#   * the data page is added exactly once (abs == page * 256 + relative);
#   * raw and raw-with-header bitmap inputs agree with the same pixels;
#   * packing is deterministic (same bytes across runs) and the emitted C header
#     matches the metadata.
#
# Shell + C only (no Python). Outputs land under build/fx-port/image/.
#
# Usage: tests/fx_image/run-tests.sh
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
cd "$REPO_ROOT"

OUT="build/fx-port/image"
CC="${CC:-cc}"
REF_PACKER="tests/fx_image/reference/fx_make_fxdata.c"
PBM="examples/fx/art/note_32x16.pbm"

mkdir -p "$OUT"

echo "== fx_image host checks (ATMlib2FX-hlh.10) =="
echo "repo : $REPO_ROOT"
echo "cc   : $($CC --version 2>/dev/null | head -1)"

# ---- source identity (no git) ----------------------------------------------
{
  echo "# fx_image source hashes"
  for f in \
    tools/fx_image/fx_image.c tools/fx_image/fx_image_core.c \
    tools/fx_image/fx_image_core.h tools/fx_image/Makefile \
    tests/fx_image/fx_image_test.c tests/fx_image/run-tests.sh \
    tests/fx_image/run-multi-evidence.sh \
    "$REF_PACKER" "$PBM" \
    examples/music_authoring/fx/basic/expected/stream.bin \
    examples/music_authoring/fx/stress/expected/stream.bin; do
    shasum -a 256 "$f"
  done
} > "$OUT/source-hashes.txt"

# ---- build tool + selftest -------------------------------------------------
make -C tools/fx_image CC="$CC" > "$OUT/build.log"
"$CC" -std=c11 -O1 -Wall -Wextra -Itools/fx_image \
  tests/fx_image/fx_image_test.c tools/fx_image/fx_image_core.c \
  -o "$OUT/fx_image_test"
"$OUT/fx_image_test" | tee "$OUT/selftest.log"

FX_IMAGE="$(pwd)/$OUT/fx_image"

# ---- fixture stream (no dependency on tools/fx_pack) -----------------------
STREAM="$OUT/test_stream.bin"
printf '\300\005\000\001\020\002\006\007\100\000\005\001\002\014\016\004\002\006\010\000\000' > "$STREAM"
SLEN=$(wc -c < "$STREAM" | tr -d ' ')

# ---- reference parity (fixture bitmap) -------------------------------------
"$CC" -std=c11 -O2 -Wall -Wextra "$REF_PACKER" -o "$OUT/ref_make_fxdata"
"$OUT/ref_make_fxdata" --stream "$STREAM" --out "$OUT/ref_fixture.bin" \
  > "$OUT/ref_fixture.meta"
"$FX_IMAGE" --stream "$STREAM" --fixture-bitmap --out "$OUT/fx_fixture.bin" \
  > "$OUT/fx_fixture.meta"
if ! cmp -s "$OUT/ref_fixture.bin" "$OUT/fx_fixture.bin"; then
  echo "FAIL: fixture image differs from reference packer" >&2
  exit 1
fi
REF_PAGE=$(awk -F= '/^data_page=/{print $2}' "$OUT/ref_fixture.meta")
FX_PAGE=$(awk -F= '/^data_page=/{print $2}' "$OUT/fx_fixture.meta")
if [ "$REF_PAGE" != "$FX_PAGE" ]; then
  echo "FAIL: data_page $FX_PAGE != reference $REF_PAGE" >&2
  exit 1
fi
echo "reference parity: image byte-identical, data_page=$FX_PAGE"

# ---- end-to-end with the example PBM --------------------------------------
"$FX_IMAGE" --stream "$STREAM" --bitmap "$PBM" \
  --out "$OUT/example.bin" --meta "$OUT/example.meta.json" \
  --header "$OUT/example_config.h" > "$OUT/example.meta"

meta() { awk -F= -v k="$1" '$1==k{print $2}' "$OUT/example.meta"; }
E_SLEN=$(meta stream_len)
E_BOFF=$(meta bitmap_offset)
E_IMAGELEN=$(meta image_len)
E_PAGE=$(meta data_page)
E_ABS=$(meta abs_stream_addr)
E_IMGEND=$(meta abs_bitmap_end)

[ "$E_SLEN" = "$SLEN" ] || { echo "FAIL: stream_len $E_SLEN != $SLEN" >&2; exit 1; }
[ "$E_BOFF" = "$E_SLEN" ] || { echo "FAIL: bitmap_offset $E_BOFF != stream_len" >&2; exit 1; }
[ "$E_ABS" = "$((E_PAGE * 256))" ] || { echo "FAIL: page added wrong: $E_ABS != $E_PAGE*256" >&2; exit 1; }
[ "$E_IMGEND" = "$((E_ABS + E_IMAGELEN))" ] || { echo "FAIL: abs end mismatch" >&2; exit 1; }

grep -q "^#define FX_STREAM_LEN $SLEN$" "$OUT/example_config.h" \
  || { echo "FAIL: header FX_STREAM_LEN mismatch" >&2; exit 1; }
grep -q "^#define FX_DATA_PAGE $E_PAGE$" "$OUT/example_config.h" \
  || { echo "FAIL: header FX_DATA_PAGE mismatch" >&2; exit 1; }
echo "end-to-end: stream_len=$SLEN bitmap_offset=$E_BOFF image_len=$E_IMAGELEN data_page=$E_PAGE abs_stream_addr=$E_ABS"

# ---- raw and raw-with-header inputs agree with the same pixels -------------
# Extract the 64 page-major pixel bytes from the example image (after the
# stream + 4-byte header) as the raw asset.
dd if="$OUT/example.bin" of="$OUT/note.raw" bs=1 skip="$((E_SLEN + 4))" \
  count=64 2>/dev/null
"$FX_IMAGE" --stream "$STREAM" --bitmap "$OUT/note.raw" --width 32 --height 16 \
  --out "$OUT/example_raw.bin" > /dev/null
cmp -s "$OUT/example.bin" "$OUT/example_raw.bin" \
  || { echo "FAIL: raw bitmap path differs from PBM path" >&2; exit 1; }
# raw-with-header: [w_hi w_lo h_hi h_lo][pixels]
printf '\000\040\000\020' > "$OUT/note_header.raw"
cat "$OUT/note.raw" >> "$OUT/note_header.raw"
"$FX_IMAGE" --stream "$STREAM" --bitmap "$OUT/note_header.raw" \
  --bitmap-format raw --bitmap-header --out "$OUT/example_hdr.bin" > /dev/null
cmp -s "$OUT/example.bin" "$OUT/example_hdr.bin" \
  || { echo "FAIL: raw-with-header path differs from PBM path" >&2; exit 1; }
echo "raw/raw-header: byte-identical to PBM path"

# ---- determinism -----------------------------------------------------------
"$FX_IMAGE" --stream "$STREAM" --bitmap "$PBM" --out "$OUT/example2.bin" > /dev/null
cmp -s "$OUT/example.bin" "$OUT/example2.bin" \
  || { echo "FAIL: packing not deterministic" >&2; exit 1; }
echo "determinism: byte-identical across runs"

# ---- multi-stream mode (ATMlib2FX-hlh.13) ----------------------------------
MOUT="build/fx-port/image-multi"
mkdir -p "$MOUT"
MBASIC="examples/music_authoring/fx/basic/expected/stream.bin"
MSTRESS="examples/music_authoring/fx/stress/expected/stream.bin"
B_BASIC=$(wc -c < "$MBASIC" | tr -d ' ')
B_STRESS=$(wc -c < "$MSTRESS" | tr -d ' ')
# A tiny loop stream (version byte 0xC1) to exercise the loop flag.
printf '\301\005\000\001\020\002\006\007\100\000\005\001\002\014\016\004\002\006\010\000\000' > "$MOUT/loop.bin"

"$FX_IMAGE" \
  --stream basic:"$MBASIC" --stream stress:"$MSTRESS" --stream loop:"$MOUT/loop.bin" \
  --bitmap "$PBM" \
  --out "$MOUT/fxdata.bin" --meta "$MOUT/meta.json" \
  --header "$MOUT/fxdata_config.h" > "$MOUT/fxdata.meta"

mmeta() { awk -F= -v k="$1" '$1==k{print $2}' "$MOUT/fxdata.meta"; }
M_COUNT=$(mmeta stream_count)
M_OFF1=$(mmeta stream1_offset)
M_OFF2=$(mmeta stream2_offset)
M_BOFF=$(mmeta bitmap_offset)
M_IMAGELEN=$(mmeta image_len)
M_PAGE=$(mmeta data_page)
M_ABS0=$(mmeta abs_stream0_addr)
[ "$M_COUNT" = "3" ] || { echo "FAIL: multi stream_count $M_COUNT != 3" >&2; exit 1; }
[ "$M_OFF1" = "$B_BASIC" ] || { echo "FAIL: stream1 offset $M_OFF1 != $B_BASIC" >&2; exit 1; }
[ "$M_OFF2" = "$((B_BASIC + B_STRESS))" ] || { echo "FAIL: stream2 offset $M_OFF2" >&2; exit 1; }
[ "$M_BOFF" = "$((B_BASIC + B_STRESS + 21))" ] || { echo "FAIL: bitmap offset $M_BOFF" >&2; exit 1; }
[ "$M_IMAGELEN" = "$((M_BOFF + 68))" ] || { echo "FAIL: image_len $M_IMAGELEN" >&2; exit 1; }
[ "$M_ABS0" = "$((M_PAGE * 256))" ] || { echo "FAIL: page added wrong: $M_ABS0" >&2; exit 1; }
grep -q "^#define FX_STREAM_COUNT 3$" "$MOUT/fxdata_config.h" \
  || { echo "FAIL: header FX_STREAM_COUNT" >&2; exit 1; }
grep -q "^#define FX_STREAM_1_OFFSET $B_BASIC$" "$MOUT/fxdata_config.h" \
  || { echo "FAIL: header FX_STREAM_1_OFFSET" >&2; exit 1; }
grep -q "^#define FX_STREAM_2_LOOP 1$" "$MOUT/fxdata_config.h" \
  || { echo "FAIL: header loop flag for the 0xC1 stream" >&2; exit 1; }
grep -q "FX_STREAM_0_LOOP 0" "$MOUT/fxdata_config.h" \
  || { echo "FAIL: header finite flag" >&2; exit 1; }
echo "multi: count=3 offsets=$M_OFF1,$M_OFF2 bitmap_offset=$M_BOFF data_page=$M_PAGE image_len=$M_IMAGELEN"

# Read each embedded stream back from the image and require byte parity.
dd if="$MOUT/fxdata.bin" of="$MOUT/rb_basic.bin" bs=1 skip=0 \
  count="$B_BASIC" 2>/dev/null
cmp -s "$MOUT/rb_basic.bin" "$MBASIC" \
  || { echo "FAIL: embedded basic stream parity" >&2; exit 1; }
dd if="$MOUT/fxdata.bin" of="$MOUT/rb_stress.bin" bs=1 skip="$M_OFF1" \
  count="$B_STRESS" 2>/dev/null
cmp -s "$MOUT/rb_stress.bin" "$MSTRESS" \
  || { echo "FAIL: embedded stress stream parity" >&2; exit 1; }
echo "multi: embedded stream byte parity ok"

# Determinism (no timestamps).
"$FX_IMAGE" \
  --stream basic:"$MBASIC" --stream stress:"$MSTRESS" --stream loop:"$MOUT/loop.bin" \
  --bitmap "$PBM" --out "$MOUT/fxdata2.bin" > /dev/null
cmp -s "$MOUT/fxdata.bin" "$MOUT/fxdata2.bin" \
  || { echo "FAIL: multi-stream packing not deterministic" >&2; exit 1; }
# The optional bitmap may be omitted.
"$FX_IMAGE" --stream basic:"$MBASIC" --stream stress:"$MSTRESS" \
  --out "$MOUT/fxdata_nobm.bin" > "$MOUT/fxdata_nobm.meta"
[ "$(awk -F= '/^bitmap=/{print $2}' "$MOUT/fxdata_nobm.meta")" = "0" ] \
  || { echo "FAIL: streams-only image should report bitmap=0" >&2; exit 1; }
echo "multi: deterministic; streams-only image packs without a bitmap"

# Multi-stream admission rejections.
if "$FX_IMAGE" --stream a:"$MBASIC" --stream a:"$MSTRESS" \
    --out "$MOUT/bad.bin" > /dev/null 2>&1; then
  echo "FAIL: duplicate stream name accepted" >&2
  exit 1
fi
if "$FX_IMAGE" --stream a:"$MOUT/empty_never.bin" \
    --out "$MOUT/bad.bin" > /dev/null 2>&1; then
  echo "FAIL: missing stream file accepted" >&2
  exit 1
fi
: > "$MOUT/empty.bin"
if "$FX_IMAGE" --stream a:"$MOUT/empty.bin" \
    --out "$MOUT/bad.bin" > /dev/null 2>&1; then
  echo "FAIL: empty stream accepted" >&2
  exit 1
fi
if "$FX_IMAGE" --stream a:"$MBASIC" --stream plain_path \
    --out "$MOUT/bad.bin" > /dev/null 2>&1; then
  echo "FAIL: mixed named/plain streams accepted" >&2
  exit 1
fi
echo "multi: duplicate name, empty stream and mixed forms rejected"

# ---- admission rejections through the CLI ---------------------------------
if "$FX_IMAGE" --stream "$STREAM" --bitmap "$PBM" --page-bytes 200 \
    --out "$OUT/bad.bin" > /dev/null 2>&1; then
  echo "FAIL: non-power-of-two page accepted" >&2
  exit 1
fi
if "$FX_IMAGE" --stream "$STREAM" --out "$OUT/bad.bin" > /dev/null 2>&1; then
  echo "FAIL: missing bitmap accepted" >&2
  exit 1
fi
echo "rejections: non-power-of-two page and missing bitmap rejected"

echo
echo "artifacts and hashes:"
shasum -a 256 "$OUT/example.bin" "$OUT/fx_fixture.bin" "$OUT/note.raw" \
  "$MOUT/fxdata.bin" | sed 's/^/  /'
echo "results: $OUT (single) and $MOUT (multi)"
