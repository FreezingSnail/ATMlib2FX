# FX music integration

User-facing guide for integrating the finite-v1 **compact directly-consumed FX
music stream** (`ATMlib2FX-hlh.6`) into an ArduboyFX program. It covers
ownership, service placement, the refill deadline, ring/admission limits,
underrun/error behaviour and the toolchain flags.

**Scope: finite (non-looping, no-SFX) music only.** Global loop
synchronization, pause/replacement arming, and independent-tempo SFX are
separate, tracked work (`ATMlib2FX-hlh.8`/`hlh.9`); do not advertise loops or
SFX for this path. The pinned contract is
[`research/fx/fx-architecture-decision.md`](../../research/fx/fx-architecture-decision.md)
(“hlh.6 review”); the packer is [`tools/fx_image`](../../tools/fx_image/README.md)
and the converter is [`tools/fx_pack`](../../tools/fx_pack/README.md).

## End-to-end flow

```sh
# 1. convert a legacy tracker score to the finite-v1 stream (tools/fx_pack)
make -C tools/fx_pack
build/fx-port/pack/fx_pack \
  --song examples/arduino/songs/song01_sfx/song.h --symbol score \
  --out build/fx-port/image/stream.bin --meta build/fx-port/image/stream_meta.json

# 2. pack the stream plus a bitmap into the FX data image (tools/fx_image)
make -C tools/fx_image
build/fx-port/image/fx_image \
  --stream build/fx-port/image/stream.bin \
  --bitmap examples/fx/art/note_32x16.pbm \
  --out build/fx-port/image/fxdata.bin \
  --meta build/fx-port/image/meta.json \
  --header build/fx-port/image/fxdata_config.h

# 3. build the example (see examples/fx/README.md for the full command)
```

The workable example is [`examples/fx/music_graphics`](../../examples/fx/music_graphics/music_graphics.ino).

## Ownership

* **The caller owns `FX::begin(page)` and the data page.** The packer computes
  the page (`data_page`) and the data-section-relative stream offset/length.
  Call `FX::begin(FX_DATA_PAGE)` once in `setup()`.
* **The caller owns the bitmap.** Layout is
  `[stream][bitmap header][page-major 1bpp bitmap]`; the packer records the
  bitmap offset and extents.
* **The library owns the ring, the four music channels and the decoder state.**
  It consumes a byte source the caller provides:

  ```cpp
  extern "C" void atm_fx_compact_fetch(uint32_t offset, uint8_t *dst, uint8_t n)
  {
      FX::readDataBytes(offset, dst, n);   // offset is data-section-relative
  }
  ```

  Offsets are data-section-relative; **the page is added exactly once** by the FX
  library. All decoder reads are bounds-checked against `stream_end`
  (the relative stream length).

## Service placement

* Call `atm_fx_compact_service()` in the **main loop, after `FX::display()`**,
  between complete SPI transactions. It must not run inside the timer or during
  an OLED/SPI transaction.
* Run it with **sample interrupts enabled** (the Arduboy audio timer). The
  service performs foreground FX SPI reads into SRAM; the Timer3 consumer
  touches only SRAM and never SPI.
* `atm_fx_compact_play(offset, length)` already prefills the first record before
  arming, so the first due tick cannot underrun.

```cpp
void loop()
{
    if (!arduboy.nextFrame()) return;
    FX::drawBitmap(x, y, FX_BITMAP_OFFSET, 0, dbmNormal);
    FX::display(CLEAR_BUFFER);      // finish the bus transaction first
    atm_fx_compact_service();       // refill; sample interrupts stay enabled
}
```

## Refill deadline

Provide **at least one complete record per frame**. At 52 fps a frame is
`1000 / 52 ≈ 19.23 ms`. The converter reports the worst number of stream bytes
consumed over K consecutive music ticks (`window_bytes` in its metadata); a
stream is shippable only if that worst service window fits the ring.

Observed on the reference fixture at authored tempo: 493 music ticks in 12 s,
`max_gap=1` tick, `max_record=24` bytes, `max_window=24` bytes, zero underruns
(`build/fx-port/image/fresh-flow.txt`). At the stress tempo `2000/7 Hz` the
hlh.5 lane measured a worst 7-tick window of 31 B with zero underruns in a 32 B
ring.

## Ring and admission limits

* Default music ring: **`ATM_FX_COMPACT_RING = 32` bytes** (power of two, ≤ 256;
  a build-time configuration, never a silent host behaviour).
* **Every record must satisfy `len <= ring`**; the converter enforces the same
  admission limit and names the offending source event on rejection.
* Foreground fetches are at most `ATM_FX_COMPACT_CHUNK = 16` bytes per SPI
  transaction, looped until the ring is full.
* A ring smaller than the worst service window will underrun even if every
  single record fits; check `window_bytes` before shrinking.

## Underrun and error behaviour

* **Underrun** — a due pass without a resident complete record freezes the tick
  *before* mutating any state, retains oscillator state and increments the
  underrun counter. Supported loads must run with **zero** underruns.
* **Malformed record / `len > ring`** — sets a sticky error and stops playback.
* **END record or all-inactive voice mask** — stops cleanly, mirroring the
  original score handler.
* With `-DATM_FX_COMPACT_DIAG=1` the state exposes `ticks`, `underruns`,
  `max_service_gap`, `max_record`, `max_window`, `error` and `stop_tick` for a
  one-shot serial report. Diagnostics are off in production builds and pay
  nothing.

## Toolchain flags

The default PROGMEM library build is **unchanged**; FX audio is opt-in per
build:

| Flag | Default | Meaning |
| --- | --- | --- |
| `ATM_HAS_FX_COMPACT` | `0` | Selects the compact FX music backend (removes the PROGMEM traversal path for that build). |
| `ATM_FX_COMPACT_RING` | `32` | Music ring size in bytes (power of two, ≤ 256). |
| `ATM_FX_COMPACT_CHUNK` | `16` | Largest foreground FX fetch per transaction. |
| `ATM_FX_COMPACT_DIAG` | `0` | Adds counters and the serial report (diagnostic builds only). |
| `ATM_FX_COMPACT_SFX` | `0` | Independent-tempo SFX overlay (separate work; not advertised here). |

Set them on both C and C++ compilations. Example `arduino-cli` invocation:

```sh
arduino-cli compile --fqbn arduboy-homemade:avr:arduboy-fx --library . \
  --build-path build/fx-port/image/avr-music_graphics \
  --output-dir build/fx-port/image/out-music_graphics \
  --build-property "compiler.cpp.extra_flags=-DATM_HAS_FX_COMPACT=1 -DFX_IMAGE_USE_HEADER -I$PWD/build/fx-port/image" \
  --build-property "compiler.c.extra_flags=-DATM_HAS_FX_COMPACT=1" \
  examples/fx/music_graphics
```

Shipping builds must never link both the legacy traversal path and an FX
decoder. Measured example image (authored tempo, 52 fps, `song01_sfx`):
program 8736 B, static SRAM 1376 B, decoded with zero underruns and zero error.
