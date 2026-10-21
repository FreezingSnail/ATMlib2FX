# FX music integration

User-facing guide for integrating the **compact directly-consumed FX music
stream** (`ATMlib2FX-hlh.6`) into an ArduboyFX program. It covers ownership,
service placement, the refill deadline, ring/admission limits, global loops
(resident and streaming), underrun/error behaviour and the toolchain flags. The
pinned contract is
[`research/fx/fx-architecture-decision.md`](../../research/fx/fx-architecture-decision.md)
(“hlh.6 review” plus the `hlh.8` and `hlh.16` addenda); the packer is
[`tools/fx_image`](../../tools/fx_image/README.md), the reference converter is
[`tools/fx_pack`](../../tools/fx_pack/README.md), and the authoring adapter is
[`tools/music_authoring/fx_backend.py`](../../tools/music_authoring/fx_backend.py).

## Capability matrix

| Feature | Status | Build gate |
| --- | --- | --- |
| Finite `0xC0` music stream | supported | built in |
| Global loops, region ≤ ring (`0xC1`, resident replay, no further fetch) | supported | `+ ATM_FX_COMPACT_LOOP=1` |
| Global loops, region > ring (`0xC1`, streamed through the ring) | supported; region ≤ `ATM_FX_COMPACT_LOOP_MAX_REGION` (65535 B) | `+ ATM_FX_COMPACT_LOOP_STREAMING` (defaults to `ATM_FX_COMPACT_LOOP`) |
| Pattern effects and live commands (arpeggio, note_cut, lfo, slide, glissando, noise_retrig; set/add tempo, set/add transposition, set_volume, set_mod, cue) | supported (original engine command bytecode) | built in |
| Pause / resume / atomic replacement | supported | built in |

Authoring (`tools/atm-music build --backend fx`): `--ring N` (power of two,
5..256, default 32) sets the admission ring; `--streaming-loops` exports a loop
region larger than the ring (up to 65535 B) with the same `0xC1` framing. The
sketch must be built with the matching `ATM_FX_COMPACT_RING`.

## End-to-end flow

```sh
# 1. convert a legacy tracker score to the compact stream (tools/fx_pack)
make -C tools/fx_pack
build/fx-port/pack/fx_pack \
  --song tests/fx_pack/fixtures/song01_sfx/song.h --symbol score \
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

The full jukebox consumer (all 21 catalog songs in one image) is
[`examples/arduino/jukebox_fx`](../../examples/arduino/jukebox_fx); its generator
is [`tools/music_authoring/fx_jukebox.py`](../../tools/music_authoring/fx_jukebox.py).

For authored scores, the adapter (`tools/atm-music build SONG.json --backend fx
--ring 64 --streaming-loops`) emits the compact stream directly. The generator
used for the committed jukebox image is `fx_jukebox.py --ring 64
--streaming-loops`; the sketch is built with `ATM_FX_COMPACT_LOOP=1
-DATM_FX_COMPACT_RING=64`. Verification for that image (static checks, a
two-cycle host decoder trace, and an absim run of the packed image) lives under
[`build/fx-jukebox/verify/`](../../build/fx-jukebox/verify/README.md) with the
committed scripts in [`tests/fx_jukebox/`](../../tests/fx_jukebox/README.md).

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
  a build-time configuration, never a silent host behaviour). Author scores
  whose widest record exceeds 32 B with `--ring N` and build the sketch with the
  matching `ATM_FX_COMPACT_RING` (the committed jukebox image uses 64).
* **Every record must satisfy `len <= ring`**; the converter/adapter enforce the
  same admission limit and name the offending source event on rejection
  (`DUE_GROUP_TOO_LARGE`).
* Foreground fetches are at most `ATM_FX_COMPACT_CHUNK = 16` bytes per SPI
  transaction, looped until the ring is full.
* A ring smaller than the worst service window will underrun even if every
  single record fits; check `window_bytes` before shrinking.

### Global loops

* A `0xC1` loop stream carries the loop region `[loop_start_rel, len-1)`; the
  record framing is the finite framing with the loop-mode `gap` (tick delta to
  the next pass, `0` = same-tick extra pass) and `bitmap` (bits 0..3 command
  channels, bits 4..7 restart mask).
* **Region ≤ ring** — the device pins the region and replays it in place; the
  wrap needs no foreground fetch and cannot underrun (the `hlh.8` path).
* **Region > ring** — with `ATM_FX_COMPACT_LOOP_STREAMING` the foreground
  producer re-points to `loop_start` when it reaches the trailing END, so the
  timer never sees END and the same-tick restart semantics are unchanged. The
  region is bounded by `ATM_FX_COMPACT_LOOP_MAX_REGION` (65535 B). The adapter
  emits this only with `--streaming-loops`; otherwise it falls back to the
  finite `0xC0` stream with a `LOOP_NOT_EXPORTED` warning.
* A pre-`hlh.16` (or `LOOP_STREAMING=0`) decoder cleanly rejects a large-region
  stream (format error, stop) before consuming any byte — never garbling.

## Underrun and error behaviour

* **Underrun** — a due pass without a resident complete record freezes the tick
  *before* mutating any state, retains oscillator state and increments the
  underrun counter. A streaming-wrap record that the foreground could not
  pre-fill is an underrun (never a skipped tick). Supported loads must run with
  **zero** underruns.
* **Malformed record / `len > ring`** — sets a sticky error and stops playback.
* **END record or all-inactive voice mask** — stops cleanly, mirroring the
  original score handler (in streaming mode END is consumed by the producer and
  becomes the loop wrap, so the timer only sees loop records).
* With `-DATM_FX_COMPACT_DIAG=1` the state exposes `ticks`, `underruns`,
  `max_service_gap`, `max_record`, `max_window`, `error` and `stop_tick` for a
  one-shot serial report. Diagnostics are off in production builds and pay
  nothing.

## Toolchain flags

The compact decoder is the library's playback path. Build knobs:

| Flag | Default | Meaning |
| --- | --- | --- |
| `ATM_FX_COMPACT_LOOP` | `0` | Enables `0xC1` loop streams (resident region ≤ ring). |
| `ATM_FX_COMPACT_LOOP_STREAMING` | `= ATM_FX_COMPACT_LOOP` | Streams a loop region larger than the ring through the ring (`hlh.16`); set `0` to keep the pinned-only build. |
| `ATM_FX_COMPACT_LOOP_MAX_REGION` | `65535` | Largest streamed loop region the decoder accepts. |
| `ATM_FX_COMPACT_RING` | `32` | Music ring size in bytes (power of two, ≤ 256). |
| `ATM_FX_COMPACT_CHUNK` | `16` | Largest foreground FX fetch per transaction. |
| `ATM_FX_COMPACT_DIAG` | `0` | Adds counters and the serial report (diagnostic builds only). |

Example `arduino-cli` invocation:

```sh
arduino-cli compile --fqbn arduboy-homemade:avr:arduboy-fx --library . \
  --build-path build/fx-port/image/avr-music_graphics \
  --output-dir build/fx-port/image/out-music_graphics \
  --build-property "compiler.cpp.extra_flags=-DFX_IMAGE_USE_HEADER -I$PWD/build/fx-port/image" \
  examples/fx/music_graphics
```

Measured example image (authored tempo, 52 fps, `song01_sfx`):
program 8796 B, static SRAM 1375 B, decoded with zero underruns and zero error.
