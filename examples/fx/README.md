# FX music + graphics example

`music_graphics/` is a maintained example of the finite-v1 **compact
directly-consumed FX music stream** (`ATMlib2FX-hlh.10`): it draws an FX bitmap,
displays it, then refills the music ring in the main loop, per the pinned
integration contract (`docs/fx/integration.md`). It is a finite (non-looping,
no-SFX) demo only.

## Files

* `music_graphics/music_graphics.ino` — the sketch.
* `art/note_32x16.pbm` — the example 32×16 bitmap in netpbm `P1` form.
* generated (not committed): `stream.bin`, `fxdata.bin`, `meta.json`,
  `fxdata_config.h` under `build/fx-port/image/`.

## Commands (from the repo root)

```sh
# 1. convert the legacy score to the finite-v1 compact stream (tools/fx_pack)
make -C tools/fx_pack
build/fx-port/pack/fx_pack \
  --song examples/arduino/songs/song01_sfx/song.h --symbol score \
  --out build/fx-port/image/stream.bin \
  --meta build/fx-port/image/stream_meta.json

# 2. pack the stream + bitmap into the FX data image (tools/fx_image)
make -C tools/fx_image
build/fx-port/image/fx_image \
  --stream build/fx-port/image/stream.bin \
  --bitmap examples/fx/art/note_32x16.pbm \
  --out build/fx-port/image/fxdata.bin \
  --meta build/fx-port/image/meta.json \
  --header build/fx-port/image/fxdata_config.h

# 3. build the sketch (FQBN arduboy-homemade:avr:arduboy-fx)
LANE="$PWD/build/fx-port/image"
arduino-cli compile --fqbn arduboy-homemade:avr:arduboy-fx --library . \
  --build-path "$LANE/avr-music_graphics" --output-dir "$LANE/out-music_graphics" \
  --build-property "compiler.cpp.extra_flags=-DATM_HAS_FX_COMPACT=1 -DFX_IMAGE_USE_HEADER -I$LANE" \
  --build-property "compiler.c.extra_flags=-DATM_HAS_FX_COMPACT=1" \
  examples/fx/music_graphics
```

Add `-DATM_FX_COMPACT_DIAG=1` to **both** extra-flag values to get the one-shot
`FXDIAG` serial report used by the device check. The generated
`fxdata_config.h` supplies `FX_DATA_PAGE`, `FX_BITMAP_OFFSET`, `FX_STREAM_LEN`
and the bitmap dimensions.

## Run and verify

```sh
# device run: emulate the image and require zero underruns / zero error
ARDENS_ROOT=~/code/arduboy/Ardens \
  tests/fx_image/run-absim.sh \
  build/fx-port/image/avr-music_graphics/music_graphics.ino.elf \
  build/fx-port/image/fxdata.bin 12000
```

The whole fresh flow (convert → pack → build → absim, plus the default
PROGMEM-build check) is automated:

```sh
tests/fx_image/run-fresh-flow.sh
```

Expected on the reference fixture at authored tempo:
`FXDIAG ticks=493 underruns=0 max_gap=1 max_record=24 max_window=24 error=0`,
program 8736 B, static SRAM 1376 B.

## Runtime contract

* Caller owns `FX::begin(FX_DATA_PAGE)` and the data page; the library consumes
  the relative-offset fetch callback.
* Service after `FX::display()`, with sample interrupts enabled, between complete
  SPI transactions.
* Refill deadline: at least one complete record per frame (52 fps ≈ 19.23 ms).
* Default 32 B ring; every record must satisfy `len <= ring`.
* Finite songs only. Global loops are **not** available yet; this sketch never
  loops the stream.

See [`docs/fx/integration.md`](../../docs/fx/integration.md) for the full
contract and toolchain flags.
