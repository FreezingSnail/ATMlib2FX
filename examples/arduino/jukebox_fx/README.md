# Jukebox (FX)

The same browse-and-play jukebox as [`../jukebox`](../jukebox), but every one of
the **21** catalog songs lives in a single FX data image and is streamed from
the FX chip by the compact decoder. No score bytes are held in PROGMEM, so the
two-set `JUKEBOX_SET` build split is gone: one sketch, one image, all songs.

The compact backend and its integration contract are pinned by
[`ATMlib2FX-hlh.6`](../../../docs/fx/integration.md) /
[`ATMlib2FX-hlh.8`](../../../research/fx/fx-architecture-decision.md); the
consumer example is [`examples/fx/music_graphics`](../../fx/music_graphics).

## Controls

| Button       | Action                                        |
| ------------ | --------------------------------------------- |
| `UP`         | Previous song (wraps, plays immediately)      |
| `DOWN`       | Next song (wraps, plays immediately)          |
| `A`          | Restart the selected song                     |
| `B`          | Pause / resume playback                       |

The display shows the index (`i/N`), the song name word-wrapped over two lines,
its folder, the musical loop length (one decimal) and the FX stream byte size,
and the current status (`PLAYING` / `PAUSED` / `READY`). It redraws only when
the selection or playback status changes.

## How it works

* `setup()` calls `FX::begin(JUKEBOX_FX_DATA_PAGE)`; the page comes from the
  generated header.
* `atm_fx_compact_fetch` is implemented with `FX::readDataBytes`; the offsets
  handed to the library are **data-section-relative** and the page is added
  exactly once by the FX library.
* `loop()` finishes the OLED transaction with `FX::display()`, then calls
  `atm_fx_compact_service()` — per the pinned service placement.
* `UP`/`DOWN`/`A` re-arm the decoder with `atm_fx_compact_play(offset, length)`;
  `B` toggles `atm_fx_compact_pause()` / `atm_fx_compact_resume()`.
* A catalog score loops. When its whole loop region does not fit the FX ring the
  adapter exports the finite arrangement once, so the sketch re-arms it at the
  natural end; internally-looping `0xC1` streams never stop on their own.

`jukebox_fx_songs.h` is the generated index: per-song stream offset/length and
loop flags in catalog order, plus the display name/folder table (ASCII-folded
like the PROGMEM jukebox). It is the only committed artifact of the build.

## Regenerate the image and header

`tools/music_authoring/fx_jukebox.py` rebuilds every catalog song
(`tools/atm-music build --backend fx`), packs them with `tools/fx_image` in
multi-stream mode, and rewrites the committed header:

```sh
python3 tools/music_authoring/fx_jukebox.py \
    --out-dir build/fx-jukebox \
    --header examples/arduino/jukebox_fx/jukebox_fx_songs.h
```

Any catalog song the FX adapter rejects aborts the run with a source-pointed
report (no silent skips). The image, packer metadata and a per-song summary land
under `build/fx-jukebox/`; only `jukebox_fx_songs.h` is copied into the sketch
folder. The generator is deterministic: catalog order, no timestamps.

`--ring` (default `32`, the runtime `ATM_FX_COMPACT_RING`) must match the sketch
build. A loop region that fits the ring is exported as a resident `0xC1` loop;
larger regions fall back to the finite `0xC0` arrangement and are re-armed by
the sketch.

## Build

```sh
FLAGS="-DATM_HAS_FX_COMPACT=1 -DATM_FX_COMPACT_LOOP=1"
arduino-cli compile --fqbn arduboy-homemade:avr:arduboy-fx --library . \
    --build-path build/fx-jukebox/avr --output-dir build/fx-jukebox/out \
    --build-property "compiler.cpp.extra_flags=$FLAGS" \
    --build-property "compiler.c.extra_flags=$FLAGS" \
    examples/arduino/jukebox_fx
```

`ATM_FX_COMPACT_LOOP=1` enables the `0xC1` loop streams; omit it only if the
generator reported no loop-exported streams. Add `-DATM_FX_COMPACT_DIAG=1` to
both flag values for the one-shot `FXDIAG` underrun/error report used by the
device check. The default PROGMEM library build is untouched.

Measured with a stand-in image (the catalog adapter run is orchestrator-side;
stand-in streams from `tools/fx_image` fixtures):

* program **14,172 B** (47% of the 29,696-byte cap) — the 21 score assets are
  **not** in flash;
* static SRAM **1,482 B** (1,078 B free), diag build 15,042 B / 1,501 B.

The PROGMEM jukebox needs 25,942–28,656 B of program flash for one 14- or
7-song set; this sketch holds all 21 songs at less than half the cap because the
scores live on the FX chip.

## Run

In Ardens, load the sketch `.hex` together with the generated image:

```sh
~/code/arduboy/Ardens/build/Ardens.app/Contents/MacOS/Ardens \
    "file=$PWD/build/fx-jukebox/out/jukebox_fx.ino.hex" \
    "file=$PWD/build/fx-jukebox/fxdata.bin"
```

The `file=<hex> file=<fxdata.bin>` pair is required: the sketch addresses the
data page baked into `jukebox_fx_songs.h`, so the image must be the one the
generator packed alongside it.

## Relationship to the PROGMEM jukebox

[`../jukebox`](../jukebox) rebuilds scores as PROGMEM `ATM_SCORE_FMT_FULL`
assets and, because all 21 do not fit, is built against one of two headers at a
time (`JUKEBOX_SET`). It keeps that repo-embedded header path. This FX sketch
plays byte-for-byte the same authored scores, but reads them from the SPI flash
data section, so it drops the set split and the flash-cap constraint.

## Tests

```sh
python3 -m unittest tests.music_authoring.test_fx_jukebox
```

The unit tests cover catalog-order planning, symbol naming, header determinism,
packer-output parsing and fail-loudly reporting; they use fixture data and need
no toolchain.
