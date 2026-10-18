# fx_image — FX data-image packer for the finite-v1 compact stream

Maintained packer (`ATMlib2FX-hlh.10`) for the pinned finite-v1 compact FX music
stream selected by `ATMlib2FX-hlh.6`. It replaces the fixed-fixture spike packer
`research/fx/tools/fx_make_fxdata.c` (read-only reference): instead of a
hard-coded test bitmap it takes a **stream binary plus a real bitmap/image
input**, owns the layout and data-page placement, does the 24-bit extent
arithmetic and emits metadata (and optionally a C header).

Contract and framing live in
[`research/fx/fx-architecture-decision.md`](../../research/fx/fx-architecture-decision.md)
(“hlh.6 review”, item 4). This tool emits **finite (non-looping, no-SFX) music**
images only.

## Build

```sh
make -C tools/fx_image            # -> build/fx-port/image/fx_image
```

No network, no installs, no git. Outputs stay under `build/` (ignored).

## Usage

```sh
# Convert a legacy score first (tools/fx_pack), then pack stream + bitmap:
build/fx-port/image/fx_image \
  --stream build/fx-port/image/stream.bin \
  --bitmap examples/fx/art/note_32x16.pbm \
  --out build/fx-port/image/fxdata.bin \
  --meta build/fx-port/image/meta.json \
  --header build/fx-port/image/fxdata_config.h
```

| Option | Meaning |
| --- | --- |
| `--stream PATH` | Compact stream binary (required). Becomes the data-section-relative offset `0`. |
| `--bitmap PATH` | Bitmap/image input (required unless `--fixture-bitmap`). |
| `--fixture-bitmap` | Built-in deterministic 32×16 checker (reference image; for parity tests). |
| `--out PATH` | fxdata image to write (required). |
| `--meta PATH` | Optional deterministic metadata JSON. |
| `--header PATH` | Optional C header with `FX_DATA_PAGE`, `FX_BITMAP_OFFSET`, `FX_STREAM_LEN`, … |
| `--bitmap-format auto\|pbm\|raw` | Input interpretation (default `auto`: `P1`/`P4` magic → PBM, else raw). |
| `--width N` `--height N` | Dimensions for a raw page-major bitmap. |
| `--bitmap-header` | The raw bitmap already starts with the 4-byte FX header (dimensions read from it). |
| `--chip-bytes N` | FX chip size (default 16777216, W25Q128). |
| `--page-bytes N` | FX page size, power of two (default 256). |

Exit status: `0` success, `2` usage error, `1` read/validation/write failure
(diagnostic on stderr).

### Bitmap inputs

* **PBM (netpbm)** — ASCII `P1` (text, git-friendly) or binary `P4`. Pixel
  `(x, y)` of value 1 (black) becomes bit `y & 7` of byte
  `(y >> 3) * width + x` (Arduboy/FX page-major 1bpp: one byte per column, bit 0
  is the top pixel of the 8-row page).
* **Raw** — the same page-major 1bpp bytes with no header; give `--width` and
  `--height`. `--bitmap-header` accepts a file that already begins with
  `[w_hi w_lo h_hi h_lo]`.

## Emitted image

```
[ stream bytes ][ width_hi width_lo height_hi height_lo ][ page-major 1bpp bitmap ]
```

This is byte-compatible with the reference packer for the same stream and a 32×16
checker bitmap (asserted in `tests/fx_image/run-tests.sh`).

## Placement and 24-bit extents

The image is placed at the **top** of the chip, rounded up to a whole page:

```
data_bytes  = round_up(image_len, page_bytes)
data_offset = chip_bytes - data_bytes
data_page   = data_offset / page_bytes
```

The caller passes the data page to `FX::begin(page)`; the stream offset handed
to the decoder is **data-section-relative** (`0`), and the page is added exactly
once by the FX library. All absolute addresses equal `data_offset + relative`,
and the whole image stays inside the 24-bit space (`fits_24bit`). The stream's
relative extent is `[0, stream_len)`; that is the `stream_end` the device
bounds-checks against.

## stdout metadata

```
tool=fx_image
contract=finite-v1 compact directly-consumed stream
stream_offset=0
stream_len=1572
stream_end=1572
bitmap_offset=1572
bitmap_width=32
bitmap_height=16
bitmap_data_len=64
bitmap_len=68
image_len=1640
data_bytes=1792
data_offset=16775424
data_page=65529
abs_stream_addr=16775424
abs_stream_end=16776996
abs_bitmap_addr=16776996
abs_bitmap_end=16777064
chip_bytes=16777216
page_bytes=256
fits_24bit=1
```

`--meta` writes the same facts as JSON (deterministic key order). `--header`
writes the sketch constants:

```c
#define FX_DATA_PAGE 65529
#define FX_BITMAP_OFFSET 1572
#define FX_BITMAP_WIDTH 32
#define FX_BITMAP_HEIGHT 16
#define FX_STREAM_OFFSET 0
#define FX_STREAM_LEN 1572
#define FX_IMAGE_BYTES 1640
```

## Admission and bounds

* Non-empty stream and bitmap; page size a non-zero power of two; the image must
  fit the chip; the composed length must equal `layout.image_len`.
* A stream larger than a 24-bit extent is rejected.
* A stream is shippable only if its host-validated worst service window fits the
  ring (`tools/fx_pack` reports it); this tool does not re-derive that.

## Tests

```sh
tests/fx_image/run-tests.sh        # C selftest + CLI end-to-end (no AVR)
tests/fx_image/run-fresh-flow.sh   # convert -> pack -> build -> absim (needs AVR + Ardens)
```

Shell + C only. The C selftest covers bitmap parsing/conversion, layout
placement, single-page extents and compose bytes; the shell driver adds
reference-packer parity, the example PBM end-to-end, raw/raw-header parity,
determinism and admission rejections. Evidence lands under
`build/fx-port/image/`.

## Not covered

Global loops (owned by `ATMlib2FX-hlh.8`, not supported by the stream), SFX,
the general converter input matrix (`tools/fx_pack`), and game fit
(`ATMlib2FX-hlh.11`). See [`docs/fx/integration.md`](../../docs/fx/integration.md)
for the user-facing integration contract.
