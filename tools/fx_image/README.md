# fx_image — FX data-image packer for the finite-v1 compact stream

Maintained packer (`ATMlib2FX-hlh.10`, multi-stream mode `ATMlib2FX-hlh.13`)
for the pinned finite-v1 compact FX music stream selected by `ATMlib2FX-hlh.6`.
It replaces the retired fixed-fixture spike packer; instead of a hard-coded
test bitmap it takes a **stream binary plus a real bitmap/image input**, owns
the layout and data-page placement, does the 24-bit extent arithmetic and emits
metadata (and optionally a C header).

Two modes share one binary:

* **single-stream** (legacy, unchanged): one stream + a required bitmap;
* **multi-stream** (`ATMlib2FX-hlh.13`): N **named** compact streams in one
  image with a generated per-song index, plus an **optional** bitmap, so a
  jukebox can address every song from one data section.

Contract and framing live in
[`research/fx/fx-architecture-decision.md`](../../research/fx/fx-architecture-decision.md)
(“hlh.6 review”, item 4). Packing is content-agnostic: per-stream loop flags are
reported for `0xC1` loop streams (`ATMlib2FX-hlh.8`), and the packer does not
interpret their contents. Independent-tempo SFX is not implemented.

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

Multi-stream mode: repeat `--stream <name>:<path>`. The name is a sketch-side
identifier (`[A-Za-z0-9_]{1,63}`); it is used in the emitted header/metadata and
**never written into the image** (the sketch keeps display names). Order follows
the command line.

```sh
build/fx-port/image/fx_image \
  --stream basic:examples/music_authoring/fx/basic/expected/stream.bin \
  --stream stress:examples/music_authoring/fx/stress/expected/stream.bin \
  --bitmap examples/fx/art/note_32x16.pbm \
  --out build/fx-port/image-multi/fxdata.bin \
  --meta build/fx-port/image-multi/meta.json \
  --header build/fx-port/image-multi/fxdata_config.h
```

| Option | Meaning |
| --- | --- |
| `--stream PATH` | Single-stream mode: compact stream binary (becomes data-section-relative offset `0`). |
| `--stream NAME:PATH` | Multi-stream mode: repeatable named stream. Every `--stream` in a multi invocation must be `NAME:PATH`; mixing named and plain forms is rejected. Duplicate names are rejected. |
| `--bitmap PATH` | Bitmap/image input. Required in single-stream mode; optional in multi-stream mode. |
| `--fixture-bitmap` | Built-in deterministic 32×16 checker (reference image; for parity tests). |
| `--out PATH` | fxdata image to write (required). |
| `--meta PATH` | Optional deterministic metadata JSON. |
| `--header PATH` | Optional C header (single: `FX_DATA_PAGE`, `FX_STREAM_OFFSET/…`; multi: `FX_DATA_PAGE`, `FX_STREAM_COUNT`, per-index offsets/lengths/loop flags). |
| `--bitmap-format auto\|pbm\|raw` | Input interpretation (default `auto`: `P1`/`P4` magic → PBM, else raw). |
| `--width N` `--height N` | Dimensions for a raw page-major bitmap. |
| `--bitmap-header` | The raw bitmap already starts with the 4-byte FX header (dimensions read from it). |
| `--chip-bytes N` | FX chip size (default 16777216, W25Q128). |
| `--page-bytes N` | FX page size, power of two (default 256). |

Exit status: `0` success, `2` usage error (bad/mixed arguments, bad stream
name), `1` read/validation/write failure (diagnostic on stderr).

### Bitmap inputs

* **PBM (netpbm)** — ASCII `P1` (text, git-friendly) or binary `P4`. Pixel
  `(x, y)` of value 1 (black) becomes bit `y & 7` of byte
  `(y >> 3) * width + x` (Arduboy/FX page-major 1bpp: one byte per column, bit 0
  is the top pixel of the 8-row page).
* **Raw** — the same page-major 1bpp bytes with no header; give `--width` and
  `--height`. `--bitmap-header` accepts a file that already begins with
  `[w_hi w_lo h_hi h_lo]`.

## Emitted image

Single-stream (legacy shape):

```
[ stream bytes ][ width_hi width_lo height_hi height_lo ][ page-major 1bpp bitmap ]
```

This is byte-compatible with the reference packer for the same stream and a 32×16
checker bitmap (asserted in `tests/fx_image/run-tests.sh`).

Multi-stream:

```
[ stream0 ][ stream1 ] ... [ streamN-1 ][ bitmap header ][ bitmap data ]
```

Streams are packed **densely** (no padding) in input order starting at
data-section-relative offset `0`; the optional bitmap follows the last stream.
A one-stream multi image is therefore byte-identical to the legacy single-stream
layout. There is no per-stream page alignment: every consumer address is
`data_offset + relative_offset`, and `FX::readDataBytes` handles offsets that
cross pages, so alignment adds nothing but padding. The whole data section is
placed at the top of the chip rounded up to a whole page (below).

## Placement and 24-bit extents

The image is placed at the **top** of the chip, rounded up to a whole page:

```
data_bytes  = round_up(image_len, page_bytes)
data_offset = chip_bytes - data_bytes
data_page   = data_offset / page_bytes
```

The caller passes the data page to `FX::begin(page)`; the stream offset handed
to the decoder is **data-section-relative** (`0` in single mode, or the per-song
offset in multi mode), and the page is added exactly once by the FX library. All
absolute addresses equal `data_offset + relative`, and the whole image stays
inside the 24-bit space (`fits_24bit`). A stream's relative extent is
`[offset, offset+len)`; that is the `stream_end` the device bounds-checks
against. Each multi-stream `abs_stream<i>_addr` may or may not be page aligned;
that is fine — the FX library owns the `+ data_offset` step.

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

### Multi-stream metadata and header

In multi mode the stdout/metadata carry the stream count, each stream's
`name`, `offset`, `len` and `loop` flag in input order, the optional bitmap
extents and the 24-bit bounds. The loop flag is `1` when a stream's version byte
is `0xC1` (loop stream, `ATMlib2FX-hlh.8`), else `0`. Names appear only in the
metadata/header, never in the image.

```c
/* Generated by fx_image (ATMlib2FX-hlh.13). Do not edit. */
#define FX_DATA_PAGE 65534
#define FX_STREAM_COUNT 2
#define FX_IMAGE_HAS_BITMAP 1
#define FX_IMAGE_BYTES 438

/* stream 0: "basic" (finite) */
#define FX_STREAM_0_OFFSET 0
#define FX_STREAM_0_LEN 269
#define FX_STREAM_0_LOOP 0
/* stream 1: "stress" (finite) */
#define FX_STREAM_1_OFFSET 269
#define FX_STREAM_1_LEN 101
#define FX_STREAM_1_LOOP 0

#define FX_BITMAP_OFFSET 370
#define FX_BITMAP_WIDTH 32
#define FX_BITMAP_HEIGHT 16
```

The sketch keeps its own display-name table indexed by the same input order and
calls `atm_fx_compact_play(FX_STREAM_<i>_OFFSET, FX_STREAM_<i>_LEN)`.

## Admission and bounds

* Non-empty streams; page size a non-zero power of two; the image must fit the
  chip; the composed length must equal `layout.image_len`.
* A stream larger than a 24-bit extent is rejected (single and multi).
* A single-stream image requires a bitmap; a multi-stream image may omit it.
* Multi-stream rejections: duplicate names, mixing `NAME:PATH` and plain
  `--stream` forms, more than 64 streams, an empty stream, a stream that pushes
  the image past the chip, or a name outside `[A-Za-z0-9_]{1,63}`.
* A stream is shippable only if its host-validated worst service window fits the
  ring (`tools/fx_pack` reports it); this tool does not re-derive that.

## Tests

```sh
tests/fx_image/run-tests.sh        # C selftest + CLI end-to-end (no AVR)
tests/fx_image/run-fresh-flow.sh   # convert -> pack -> build -> absim (needs AVR + Ardens)
```

Shell + C only. The C selftest covers bitmap parsing/conversion, layout
placement, single-page extents, compose bytes, and the multi-stream layout
(offsets, single/multi equality, per-stream byte parity, determinism, page math
and rejections); the shell driver adds reference-packer parity, the example PBM
end-to-end, raw/raw-header parity, single- and multi-stream determinism, image
read-back parity of each embedded stream, header index checks and admission
rejections. Evidence lands under `build/fx-port/image/` (single) and
`build/fx-port/image-multi/` (multi).

## Not covered

Loop record interpretation beyond the `0xC1` flag, SFX, the general converter
input matrix (`tools/fx_pack`), and game fit
(`ATMlib2FX-hlh.11`). See [`docs/fx/integration.md`](../../docs/fx/integration.md)
for the user-facing integration contract.
