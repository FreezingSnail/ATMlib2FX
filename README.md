# ATMlib2FX

Compact four-channel chiptune synthesis for ArduboyFX. Songs are authored as
JSON on the host, exported as a directly-consumed `atm_fx_compact_v1` stream,
packed into an FX data image, and decoded by the AVR library while the game keeps
running. Minimum SRAM and AVR program flash are the design priorities.

This project would not be possible without the original ATM/ATMlib work by
TEAM a.r.g., Davey Taylor (STG), Joeri Gantois (JO3RI), Delio Brignoli, and all
other original ATMlib committers.

## Start here

- **Create music:** [authoring guide](docs/music-authoring.md) and
  [tool entry points](tools/README.md).
- **Integrate playback:** [FX integration contract](docs/fx/integration.md).
- **Run the examples:** [21-song FX jukebox](examples/arduino/jukebox_fx/) and
  [music + graphics](examples/fx/music_graphics/).
- **Browse song sources:** [authoring catalog](examples/music_authoring/catalog.json).
- **Read the archive:** [FX research and measurements](research/fx/README.md).

## Requirements

- **Firmware:** Arduino AVR toolchain, the `arduboy-homemade:avr:arduboy-fx`
  board package, and the Arduboy2 + ArduboyFX libraries.
- **Host tools:** Python 3.10+ for `tools/atm-music` and the jukebox generator
  (standard library only); a C compiler and `make` for `tools/fx_image` and
  `tools/fx_pack`.
- **Optional:** an Ardens build for the absim checks and example run scripts.

## Repository map

| Directory | Contents |
| --- | --- |
| [`src/`](src/) | Compact FX decoder and shared synthesis/effect engine |
| [`tools/`](tools/README.md) | `atm-music` CLI, `fx_pack`, `fx_image`, and FX jukebox generator |
| [`examples/`](examples/README.md) | FX sketches and JSON song sources |
| [`schemas/`](schemas/) | JSON score schema |
| [`docs/`](docs/README.md) | Authoring, integration and layout guides |
| [`tests/`](tests/README.md) | Host checks, fixtures and goldens |
| [`research/`](research/README.md) | Archived FX decisions, measurements and evidence |
| `build/` | Ignored generated outputs and retained measurement evidence |

Development work is tracked in Beads (`bd ready`).

## How the FX music library works

Songs are expanded on the host into a compact stream of **due passes**. Each
record carries every command that runs on one music tick for a bitmap of
channels, plus a gap to the next pass:

```
0xC0 (finite) or 0xC1 (loop)
<len> <gap> <bitmap> <per-channel command groups> ...
0x00 END
```

Pattern traversal, calls and per-channel delays are resolved during export, so
the device keeps no pattern stacks. At runtime the work is split between the
main loop and the audio timer:

* **Foreground** — `atm_fx_compact_service()` runs after `FX::display()` and
  fetches stream bytes from FX flash into a small SRAM ring, at most
  `ATM_FX_COMPACT_CHUNK` bytes per SPI transaction. It never touches audio.
* **Timer3 ISR** — mixes the four square-wave channels plus channel-3 LFSR
  noise from SRAM only, driving Timer4 PWM. No SPI and no blocking work.
* **Music tick** — consumes one complete record from the ring, preflights its
  structure before mutating any state, then applies effects and commands in
  the original channel order. A partial record freezes the tick instead of
  advancing with corrupt state.

`play()` is atomic with respect to the timer and prefills the first record, so
the first tick cannot underrun. `pause()` silences the owned voices while
preserving the ring position and live effect state; `resume()` re-arms.

Loop streams (`0xC1`) either pin a region that fits the ring and replay it in
place, or stream a larger region by re-pointing the producer at the loop start
during the wrap. Build knobs (`ATM_FX_COMPACT_RING`,
`ATM_FX_COMPACT_LOOP`, `ATM_FX_COMPACT_CHUNK`, diagnostics) are documented in
the [FX integration contract](docs/fx/integration.md).

## From JSON score to FX data image

Conversion is two offline stages:

```
song.json ── atm-music build ──► stream.bin ── fx_image ──► fxdata.bin
             (compact music asset)            (FX data image)
```

**1. Validate and lower the score.** `tools/atm-music` checks the
`atmlib-score` v1 schema (`clock`, `instruments`, `patterns`, `tracks`,
optional `loop`), expands every pattern use and repeat into absolute ticks, and
turns notes, effect windows and live commands into ordered device operations.
The device never sees pattern traversal, calls or loop stacks.

**2. Serialize the compact stream.** Operations are encoded with the original
ATMlib command bytecode and grouped by tick into due-pass records:

```
<len> <gap> <bitmap> <per-channel: glen + command bytes>
```

The exporter rejects a record larger than the ring, a gap above 65535 ticks, or
a foreground service window larger than the ring. A `"loop": true` score emits
`0xC1` when the loop region fits the ring (or with `--streaming-loops`), with a
finite `0xC0` fallback and `LOOP_NOT_EXPORTED` warning otherwise. Outputs are
`stream.bin`, `stream.h`, `report.json` and `review.json`.

**3. Pack the FX data image.** [`tools/fx_image`](tools/fx_image/README.md)
packs one stream or many named streams plus a bitmap (required for a
single-stream image, optional for a multi-stream image):

```
[stream0][stream1]...[streamN][bitmap header][page-major 1bpp bitmap]
```

Streams are packed densely at data-section-relative offsets. The image is
placed at the top of the FX chip, rounded up to a page:

```
data_bytes  = round_up(image_len, page_bytes)
data_offset = chip_bytes - data_bytes
data_page   = data_offset / page_bytes
```

The packer emits `fxdata.bin`, metadata and a header with `FX_DATA_PAGE`,
per-stream offsets/lengths and bitmap constants. The sketch loads the image with
`FX::begin(FX_DATA_PAGE)` and calls
`atm_fx_compact_play(FX_STREAM_OFFSET, FX_STREAM_LEN)`; all stream offsets are
data-section-relative, and the FX library adds the page once. The image lives on
the FX chip, not in AVR program memory, and is loaded alongside the sketch
`.hex`. Legacy tracker C scores can use `tools/fx_pack` to produce the same
`stream.bin` without a JSON source.

## Minimal integration

Include the generated `fxdata_config.h` (build with `-I<lane>` and
`-DFX_IMAGE_USE_HEADER`), then:

```cpp
#include <Arduino.h>
#include <Arduboy2.h>
#include <ArduboyFX.h>
extern "C" {
#include <atm_synth.h>
#include <atm_fx_compact.h>
}
#include "fxdata_config.h"

Arduboy2Base arduboy;

extern "C" void atm_fx_compact_fetch(uint32_t offset, uint8_t *dst, uint8_t n)
{
    FX::readDataBytes(offset, dst, n);   // data-section-relative offset
}

void setup()
{
    arduboy.begin();
    arduboy.setFrameRate(52);
    arduboy.audio.on();                  // sample interrupts stay enabled
    FX::begin(FX_DATA_PAGE);
    atm_synth_setup();
    atm_fx_compact_play(FX_STREAM_OFFSET, FX_STREAM_LEN);
}

void loop()
{
    if (!arduboy.nextFrame()) return;
    FX::display(CLEAR_BUFFER);           // finish the OLED/SPI transaction
    atm_fx_compact_service();            // refill the music ring
}
```

Call `atm_fx_compact_pause()` / `atm_fx_compact_resume()` for pause,
`atm_fx_compact_stop()` to stop, and `atm_fx_compact_is_active()` to query
playback. The service must not run inside the timer or during an FX/OLED SPI
transaction.

## Scope and checks

The engine is four monophonic channels: three pulse voices and one noise
channel. Effects and live commands are supported; independent SFX playback is
not.

Host checks:

```sh
python3 -m unittest discover -s tests/music_authoring -p 'test_*.py'
tests/cue/run-tests.sh
tests/cmd_parse/run-tests.sh
tests/fx_pack/run-tests.sh
tests/fx_image/run-tests.sh
python3 tests/fx_jukebox/verify_image.py
```

The AVR absim checks additionally need the local Arduino toolchain and Ardens;
see [`tests/README.md`](tests/README.md).

## Quick CLI example

Run from the repository root:

```sh
tools/atm-music validate examples/music_authoring/basic/song.json --json
tools/atm-music build examples/music_authoring/basic/song.json \
    --backend fx --ring 64 --streaming-loops \
    --out build/music-authoring/fx --json

make -C tools/fx_image
build/fx-port/image/fx_image \
    --stream basic:build/music-authoring/fx/stream.bin \
    --bitmap examples/fx/art/note_32x16.pbm \
    --out build/music-authoring/fx/fxdata.bin \
    --meta build/music-authoring/fx/meta.json \
    --header build/music-authoring/fx/fxdata_config.h
```

Build the sketch with a matching `-DATM_FX_COMPACT_RING`, and
`-DATM_FX_COMPACT_LOOP=1` for loops. `stream.bin` counts are music-asset bytes,
not whole-game memory cost. For a multi-song image, see the
[jukebox generator](examples/arduino/jukebox_fx/README.md).

## Attribution

ATMlib2FX builds on ATMlib and Squawk, with contributions from Davey Taylor,
Delio Brignoli, Jay Garcia, and Joeri Gantois. See [LICENSE](LICENSE).
