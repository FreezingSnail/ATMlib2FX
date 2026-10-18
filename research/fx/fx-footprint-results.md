# Original ATMlib2 footprint and playback baseline

Tracking: `ATMlib2FX-hlh.1`. Research context: `research/fx/fx-port-research.md`.
Measurement date: 2026-10-16.

This is the measured original-library baseline that the FX port must be
compared against. Everything here is reproducible from the committed harnesses
and the documented commands. No production `src/` file, song asset, or the
external `CreatureGathererFX` reference game was modified.

## 1. Source identity and tools

| Item | Value |
| --- | --- |
| Repo HEAD | `f16387358a28d43204434019236305c6c8cc5efb` (`master`) |
| Board package | `arduboy-homemade:avr` **1.4.0** |
| FQBN | `arduboy-homemade:avr:arduboy-fx` |
| Resolved board options | `core=arduboy-core` (Arduboy optimized core), `boot=cathy3k` |
| Board flash limit | 29696 bytes (upload) / `maximum_size`; SRAM 2560 bytes |
| arduino-cli | 1.2.0 (Homebrew), `/opt/homebrew/bin/arduino-cli` |
| AVR toolchain | AVR-GCC **7.3.0** (`7.3.0-atmel3.6.1-arduino7`) |
| Arduboy2 | 6.0.0 (board package) |
| EEPROM | 2.0 (board package) |
| ArduboyFX | 1.0.11 (board package) — used only by the FX control variant |
| Ardens | v0.25.9 local build, source commit `661a7dd` (`connorfranc/code/arduboy/Ardens`); absim core used for the emulator stack run |
| Local ATMlib | `library.properties` version **1.2.4** (this repo) |
| Installed ATMlib | version **1.2.6** (board package, same name) |

AVR tools actually used (they are not on `PATH`):

```
~/Library/Arduino15/packages/arduino/tools/avr-gcc/7.3.0-atmel3.6.1-arduino7/bin/avr-size
~/Library/Arduino15/packages/arduino/tools/avr-gcc/7.3.0-atmel3.6.1-arduino7/bin/avr-nm
~/Library/Arduino15/packages/arduino/tools/avr-gcc/7.3.0-atmel3.6.1-arduino7/bin/avr-gcc
```

## 2. Fixture and build lane

Single reusable lane: `build/fx-port/`. All commands below run from the repo
root. The production fixture is one sketch, `research/fx/footprint_baseline/`,
whose shell is identical across variants; only the audio backend changes,
selected with `-DFP_AUDIO=<n>`:

| `FP_AUDIO` | Variant | Links |
| --- | --- | --- |
| 0 | `shell` | no audio library |
| 1 | `music` | ATMlib, PROGMEM score only |
| 2 | `music_sfx` | ATMlib, PROGMEM score + PROGMEM SFX |
| 3 | `fx_control` | ArduboyFX linked and `FX::begin()` initialized, no music |

The song input is the existing `examples/arduino/songs/song01_sfx/song.h` used
unchanged (`score`, `sfx1`). Its include directory is supplied with
`-I…/examples/arduino/songs/song01_sfx` because arduino-cli preprocesses the `.ino` into
the build directory, where relative includes would not resolve.

Reproduce the whole matrix:

```
research/fx/tools/measure-footprint.sh
```

That script is the pin of record; it runs, per variant:

```
arduino-cli compile \
  --fqbn arduboy-homemade:avr:arduboy-fx \
  --library . \
  --build-path build/fx-port/avr-<variant> \
  --output-dir build/fx-port/out-<variant> \
  --build-property "compiler.cpp.extra_flags=-DFP_AUDIO=<n> -I<repo>/examples/arduino/songs/song01_sfx" \
  --verbose research/fx/footprint_baseline
```

Full logs, ELFs, and a CSV summary are kept in `build/fx-port/`
(`build-<variant>.log`, `avr-<variant>/…elf`, `footprint-summary.txt`).

The starting command from the bead (targeting the pre-existing example) also
passes as a sanity check:

```
arduino-cli compile --fqbn arduboy-homemade:avr:arduboy-fx --library . \
  --build-path build/fx-port/avr --output-dir build/fx-port/out --verbose \
  examples/arduino/songs/song01_sfx
```
→ `Sketch uses 8536 bytes`, `Global variables use 1406 bytes`. That example has
extra button handling; it is not the comparison fixture.

## 3. Local library selection (verified)

Both this repo and the board package ship a library named `ATMlib`, so verbose
logs were inspected rather than assumed. For the `music` and `music_sfx`
variants the log contains:

```
Multiple libraries were found for "ATMlib.h"
  Used:     /Users/connorfranc/code/arduboy/ATMlib2FX
  Not used: /Users/connorfranc/Library/Arduino15/packages/arduboy-homemade/hardware/avr/1.4.0/libraries/ATMlib
Using library ATMlib at version 1.2.4 in folder: /Users/connorfranc/code/arduboy/ATMlib2FX
```

The installed same-named library is `ATMlib` 1.2.6. The `shell` and
`fx_control` variants do not include `ATMlib.h` and therefore compile no ATMlib
object at all (corroborated by the object list in their logs). All four variants
use identical board, core, optimization, and feature flags.

## 4. Resolved feature configuration and flags

`src/atm_synth.h` hard-defines its feature macros, so no `-D` override was used
and the measured configuration is the source default:

- `ATM_HAS_FX_NONE = 0` → noise-retrig, note-retrig, slide, LFO (tremolo/vibrato),
  glissando and loop effects all enabled.
- `ATM_PATTERN_STACK_DEPTH = 3` (three-level per-channel pattern stack).
- Score format `ATM_SCORE_FMT_FULL`; SFX format `ATM_SCORE_FMT_MINIMAL_MONO`.

Core compile flags (from the verbose log, identical for every variant except
`-DFP_AUDIO`):

```
-g -Os -w -std=gnu++11 -fpermissive -fno-exceptions -ffunction-sections
-fdata-sections -fno-threadsafe-statics -Wno-error=narrowing -flto
-mmcu=atmega32u4 -DF_CPU=16000000L -DARDUINO=10607 -DARDUINO_AVR_ARDUBOY
-DARDUINO_ARCH_AVR -DARDUBOY_10 -DCART_CS_SDA
```
Link: `-Os -flto -fuse-linker-plugin -Wl,--gc-sections -mmcu=atmega32u4`.
Timer/effect code (`src/osc.c`, `src/atm_synth.c`, `src/cmd_parse.c`) is
unmodified; the current timer divider quantization `2000 / floor(2000/rate)`
still applies.

## 5. Measured footprint

Whole image (`avr-size --format=avr --mcu=atmega32u4`), static SRAM = `.data + .bss`.
Asset bytes are the emitted ELF symbol sizes of `score` / `sfx1` (flash).

| Variant | Program | .text | .data | .bss | SRAM | score | sfx1 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `shell`       | 4928 | 4890 | 38 | 1141 | 1179 | –    | –   |
| `music`       | 8036 | 7998 | 38 | 1323 | 1361 | 123  | –   |
| `music_sfx`   | 8322 | 8284 | 38 | 1368 | 1406 | 123  | 10  |
| `fx_control`  | 4948 | 4910 | 38 | 1141 | 1179 | –    | –   |

Marginal costs (whole-image, LTO, so these are net after dead-code removal):

| Delta | Program flash | Static SRAM |
| --- | ---: | ---: |
| `music` − `shell` (PROGMEM music engine + score) | **+3108** | **+182** |
| `music_sfx` − `music` (SFX engine + state + asset) | **+286** | **+45** |
| `fx_control` − `shell` (`FX::begin()` only) | **+20** | **+0** |

Library globals (`avr-nm -S`, bytes): `channels` 140, `osc_params_array` 16,
`osc_cb` 12, `osc_pha_acc_array` 8, `atmlib_state` 4, `osc_int_count` 1,
`osc_isr_reenter` 1 → **182** bytes, exactly the `music` SRAM delta.
`sfx_state` is 44 bytes and `sfx_started` 1 byte → the 45-byte SFX SRAM delta.
`noteTable` is 128 bytes and lives in program flash (`t`), inside the 3108-byte
music delta.

These numbers confirm the research note's uncompiled estimate (≈182 core bytes,
≈44 SFX bytes) but replace it with measured values. The score (123 B) and SFX
(10 B) assets are reported separately from engine bytes; the `music`/`music_sfx`
program deltas include the assets.

## 6. Production vs diagnostic separation

| Build | Purpose | Program | SRAM |
| --- | --- | ---: | ---: |
| `music_sfx` (production fixture) | size numbers above | 8322 | 1406 |
| `diag` (`research/fx/footprint_baseline/diag`) | stack probe + serial snapshot | 9348 | 1418 |
| trace harness (`trace_main.c`, host) | reference trace | host binary, not an AVR image | – |
| absim harness (`trace/absim_harness.cpp`, host) | emulator stack run | host binary, not an AVR image | – |

The `diag` sketch adds stack painting and USB serial reporting; its sizes are
**diagnostic only** and are not used for any footprint claim. The host trace
harness is a separate host compilation and contributes no AVR bytes.

## 7. Reference playback trace (deterministic)

`research/fx/footprint_baseline/trace/` builds the **unmodified** library sources
for the host (`src/atm_synth.c` + included `src/cmd_parse.c`) with only the
`osc.c` timer layer substituted, and drives the tick callbacks exactly as the
Timer3 ISR does. The original score parser, command interpreter, effect code and
tick handlers therefore produce the values. Regenerate and verify determinism:

```
research/fx/footprint_baseline/trace/run-trace.sh          # defaults: 512 ticks, SFX at 64
```

Committed fixtures (schema and contract in `trace/README.md`):

- `trace/reference/reference_trace_music.csv` — 512 music ticks (513 lines).
- `trace/reference/reference_trace_music_sfx.csv` — 512 music ticks + SFX
  started at tick 64, run to natural stop (512 `M` + 23 `S` rows).
- `trace/reference/checksums.txt`.

Checksums (sha256; `music_sfx` regenerated for ATMlib2FX-mgd, `music` unchanged):

```
music     87e55846b3abaf214a8cb68355a8db52a431e7b75ae7b0ee0b7b7c3447e5d01d
music_sfx 10ec84de82eb11d68bd7ccd56f328f9414c2eb44e23b80b4b9e20506f184083f
```

Two consecutive runs are byte-identical (the script asserts this). Contract:
2000 Hz base; each callback's period = `2000/floor(2000/rate)` base events; the
SFX starts at the zero-based music-tick-64 boundary and runs at ~22.22 Hz
(period 90). Observed fixture behavior worth pinning:

- Music tick 64 completes at base event 2520; the first SFX tick is at base
  2521 (`S,1,…,22,…`). Music continues, and the borrowed channel `OSC_CH_TWO`
  is muted for music (`active` drops `0x70 → 0x30` while the SFX plays).
- The SFX runs 23 ticks and stops naturally at base 4501 (`active 0x00`,
  `delay 0xFFFF`) — it does not require an explicit stop.
- `tempo` column shows the per-player rate; music sets 50 via pattern 1, SFX
  sets 22 via its own pattern.
- Music channel 3 (noise) has no note until its entry pattern is reached, and
  the oscillator seed `phase_increment = 0x0001` is visible before then.

The trace covers the fixture's nested calls/repeats (patterns 1–7 with three
`CALL_REPEAT` levels) and the independent SFX interval, as required.

## 8. Stack evidence (emulator-measured)

**Measured with the local absim emulator core; no longer a blocker.**

The Ardens **command-line** modes could not emit the image's serial report (see
below), so stack high-water was measured by running each production image
against the absim core built in the local Ardens tree. absim tracks `min_stack`
(the lowest stack pointer reached on any push) and sets `stack_check` to the
image's `.bss` end, raising an overflow autobreak if SP crosses it. The harness
is `research/fx/footprint_baseline/trace/absim_harness.cpp`; run it with
`research/fx/footprint_baseline/trace/run-absim.sh` (Ardens tree commit `661a7dd`).
Buttons are driven released (otherwise `Arduboy2Base::begin()` →
`waitNoButtons()` spins forever) and USB is connected.

12 s emulator runs (`EMIT_SERIAL` off); static SRAM is from section 5:

| variant | `min_stack` | `.bss` end | free SRAM at peak |
| --- | ---: | ---: | ---: |
| shell | 0x0AAF | 0x059B | 1300 |
| music | 0x0AAF | 0x0651 | 1118 |
| music_sfx | 0x0AB2 | 0x067E | **1076** |
| fx_control | 0x0AAF | 0x059B | 1300 |

`free SRAM at peak = min_stack − .bss_end`. No stack-overflow autobreak fired
in any run (`autobreaks=0`). The exercised music+SFX shell leaves **1076 bytes**
free with all four effects enabled.

Independent cross-check: the `diag` image paints free SRAM and reports its own
high-water over USB-CDC (captured by absim too): painted `deepest_sp=0x0ABC`,
headroom 1074; absim `min_stack=0x0AB2`, headroom 1064 — two methods agree
within ~10 bytes. That same log shows playback running (`tempo=50`,
`active_mute=0x30` after the SFX stop, `osc0 phase_increment=0x1FA`, matching
the reference trace's `c0_inc=0x01FA`).

Limits: the figures cover the exercised 12 s (music + SFX overlay + display);
unexercised paths (save, other game code) are not covered, and this is the
fixture, not the reference game.

The Ardens **CLI** itself could not produce this: `--headless` runs the image
(`cycles_with_sleep` = full duration, hotspots include the Timer3 ISR) but
emits 0 serial bytes because it never raises USB CDC line state, and
`--captureserial` does not terminate here:

```
Ardens --headless=16000 --profiledump=build/fx-port/diag-profiledump.txt \
  build/fx-port/diag-out/diag.ino.elf        # exit 0; serial bytes: 0
Ardens --captureserial=5000 build/fx-port/diag-out/diag.ino.hex
  # hangs; watchdog-killed after 60 s; serial bytes: 0
```

The absim harness above is the working path; these CLI results are retained
because the CLI limitation is real.

**Static lower bound** (diagnostic, non-LTO, `avr-g++ -fstack-usage`, kept in
`build/fx-port/stack/`). Per-function static frame sizes for the music chain:

```
atm_synth_score_tick_handler 11
  process_channel            13
    process_fx                5     (max)
    process_cmd               9
      trigger_note            4
```

Worst library call chain ≈ 11 + 13 + 9 + 4 = **37 bytes** of C stack, plus the
naked Timer3 ISR's explicit pushes (`osc.c` pushes r2/r0/r1/r18/r26/r27 and, on
the playroutine path, r19–r25/r30/r31 ≈ 15 bytes) plus the hardware return
address. This is a **static lower bound only**; it excludes the ISR nesting the
design relies on (`sei` inside the ISR), register spills under LTO, and the
`Arduboy2` render path. The measured 1076-byte headroom is consistent with it
and is the number to use; the static figure only bounds the library's own
contribution.

## 9. What is and is not covered

Covered: deterministic production-size flash and static SRAM for shell/music/
music+SFX, marginal `FX::begin()` control cost, verified local-library
selection, equivalent flags/features, separately reported score/SFX bytes, and
a deterministic tick-level reference trace with a matching music-only trace.

Not covered (out of this bead's scope): stack on unexercised paths (save, other
game code), SPI/FX bus behavior, and any FX decoder. All required baseline
items, including measured stack headroom, are evidenced.

---

# 10. Compiled FX stream prototype: measured costs

Tracking: `ATMlib2FX-aoe`. Measurement date: 2026-10-17. Repo HEAD
`f16387358a28d43204434019236305c6c8cc5efb` (same as the baseline). This is a
bounded prototype measurement for the architecture decision in
`ATMlib2FX-hlh.2`, **not** an architecture selection. No production `src/`
behavior, song asset, or `CreatureGathererFX` file is changed: the default
library build is byte-identical to section 5 (re-verified) and the reference
trace checksum is unchanged.

## 10.1 What was built

- Converter: `research/fx/tools/fx_compile_stream.c` reads one `ATM_SCORE_FMT_FULL` score
  and resolves pattern calls, call-repeats, returns and delays offline into a
  single sequential, channel-interleaved byte stream. Effects are not
  interpreted; every note/effect/volume/delay command is copied verbatim, so
  the device reuses the original effect implementation. `CALL` and
  `PATTERN_END`/`RETURN` are consumed for traversal and never emitted; a genuine
  channel stop is emitted as the original `ATM_CMD_I_STOP`.
- Device decoder: `src/atm_fx_stream.{h,c}` (`ATM_HAS_FX_STREAM`), included by
  `src/atm_synth.c` like `cmd_parse.c`. It keeps a small SRAM ring, stages one
  complete music tick (or a run of silent ticks) before applying it, and calls
  the shared `process_fx()`/`apply_cmd()`. The PROGMEM score/SFX paths and the
  per-channel pattern/return stacks are compiled out of this build.
- Fixture: `research/fx/fx_stream_spike/fx_stream_spike.ino` (`-DFS_MODE`), with a
  host equivalence harness and an absim stress harness under
  `research/fx/fx_stream_spike/trace/`.
- FX image: `research/fx/tools/fx_make_fxdata.c` concatenates the stream and a deterministic
  32x16 stress bitmap; `research/fx/tools/build-fx-stream.sh` drives the whole lane.

Framing (provisional, `0xF5` magic header skipped by the decoder):

| Byte | Meaning |
| --- | --- |
| `0x00 <n>` | SKIP: advance `1+n` music ticks, no commands |
| `0x10` | END |
| `0x01..0x0F <groups>` | APPLY one tick; low nibble = channel bitmap; per present channel, in order: `<len>` then `<len>` command bytes |

The timer still fires once per tick, so a SKIP record sets a pending-silent-tick
counter; each callback advances exactly one tick.

## 10.2 Fixture equivalence (first 512 music ticks)

Method: the **device decoder** is compiled on the host (`src/atm_synth.c` with
`ATM_HAS_FX_STREAM=1`) under the baseline's osc.c timer contract (2000 Hz base,
ISR down-counter, `2000/floor(2000/rate)` divider) and emits the same CSV schema
as `ATMlib2FX-hlh.1`. The generated stream is the only input; the effect core is
the unmodified library code.

```
research/fx/fx_stream_spike/trace/run-trace.sh 512
```

- Result: **MATCH** for all 512 ticks on every behavioural column - oscillator
  parameters (`inc`/`mod`/`vol`), per-channel note/vol/mod/delay, live effect
  state (slide, arpeggio, noise-retrig, LFO, glissando), tempo-update order and
  the `active`/`active_mute` flags - covering the fixture's independent delays
  and three `CALL_REPEAT` nesting levels (patterns 1-7).
- The only dropped column is `cN_ps` (`pstack_index`), the removed traversal
  state; it is not a musical/behavioural value.
- `reference_sha256=87e55846…d01d`, `fx_trace_sha256=5e57dbec…7c50`
  (`build/fx-port/fx-stream/equivalence.txt`). Two host runs are byte-identical.
- Host trace: `underruns=0 max_gap=1` with `service()` before each base event.

Converter output for the authored fixture (`build/fx-port/fx-stream/spike_stream.log`):
`ticks=2113`, `stream_bytes=1903`, `payload_bytes=1035`, `max_group=20`,
`max_frame=25`, `apply_records=218`, `skip_records=209`.

## 10.3 Whole-image footprint

Same board, toolchain, options and lane as section 2 (`arduboy-homemade:avr`
1.4.0, FQBN `arduboy-homemade:avr:arduboy-fx`, AVR-GCC 7.3.0, `-Os -flto`,
`-DCART_CS_SDA`). Build:

```
research/fx/tools/build-fx-stream.sh
```

Whole image (`avr-size --format=avr`), static SRAM = `.data + .bss`. The stream
lives on FX, so no song bytes are in flash.

| Variant | `FS_MODE` | Program | .text | .data | .bss | SRAM | stream | ELF sha256 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `shell_fx` | 0 | 4928 | 4890 | 38 | 1141 | 1179 | – | `879c9487…9115` |
| `fx_gfx` | 1 | 4780 | 4742 | 38 | 1142 | 1180 | – | `d3c8e417…c86d` |
| `fx_stream` | 2 | 7890 | 7852 | 38 | 1344 | 1382 | 1903 | `422e683f…bac6` |
| `fx_diag` | 3 | 8582 | 8540 | 42 | 1355 | 1397 | 1903 | `d98eb354…45bb` |

`fx_diag` adds the counters and the USB-CDC report; its sizes are diagnostic
only. Production size is `fx_stream`.

### Marginal comparison (asset separated from engine)

| Delta | Program flash | Static SRAM | Note |
| --- | ---: | ---: | --- |
| baseline `music` − `shell` | +3108 | +182 | includes the 123 B PROGMEM score |
| baseline engine only (minus 123 B score) | +2985 | +182 | |
| candidate `fx_stream` − `fx_gfx` | **+3110** | **+202** | no stream in flash (stream is on FX) |

These paired-shell audio deltas differ by **+2 B** including the original
score, or **+125 B** after subtracting the removable 123 B score. This is an
engine-cost estimate: the original and FX controls use different graphics and
display paths, and LTO can change attribution. It is not an isolated engine
flash comparison. Static engine SRAM is **+20 B**, supported by the symbol
accounting below, with the 64 B ring. The FX asset grows from
**123 B to 1903 B (~15.5x)**, separate from any engine bytes.

Per-symbol attribution (`avr-nm -S`): `channels` 140 → **84** bytes (the
per-channel `pstack[3]` + index + loop index are gone, −56 B), `noteTable`
128 B stays in flash, and the decoder adds `atm_fx_stream_state` **76 B**
(64 B ring + head/tail/silent/active/flags + two 32-bit offsets). The decoder
tick handler `atm_fx_stream_tick_handler` is ~1150 B and
`atm_fx_run_silent_tick` ~72 B; the baseline `atm_synth_score_tick_handler`
(inlined traversal) was ~1582 B and the score 123 B.

Conclusion: for this fixture the compiled-stream candidate is **roughly
footprint-neutral** (a hair more flash, +20 B SRAM) and substantially larger on
FX. It does **not** demonstrate the hoped-for flash/SRAM reduction, and it is
not a smaller whole-game by itself.

## 10.4 FX asset, refill metadata and stress runs

FX data image: `stream_offset=0`, `stream_len=1903`, `bitmap_offset=1903`,
`image_len=1971`. absim places the image at the top of the 16 MB chip, so the
asset base is `abs_stream_addr=0xFFF800` (`16775168`) - above `0x010000`, i.e.
the 24-bit FX address path is exercised. The fixture calls
`FX::begin(0xFFF8)`; the board FX CS is `CART_CS_SDA` (`PORTD1`), which is also
absim's default `fxport` mask.

Refill/buffer metadata (`fx_stream` build):

| Item | Value |
| --- | --- |
| ring buffer | 64 B (`ATM_FX_REFILL_BYTES`), power-of-two mask |
| foreground fetch | ≤16 B per SPI transaction (`ATM_FX_REFILL_CHUNK`), looped to fill the ring |
| staging | `ATM_FX_MAX_FRAME` = 40 B ceiling; converter asserts `max_frame=25` |
| decoder state | 76 B static (`atm_fx_stream_state`) |
| publication | SPSC ring; `tail` published after a compiler barrier; consumer never holds SPI |
| underrun policy | freeze before applying a partial tick, count it |

Measured max decoder-consumed bytes over any K consecutive ticks
(`--out`, converter stdout): 1:25, 2:27, 5:29, 6:31, 8:33, 16:35. At the game's
52 fps with one `service()` per frame, tempo 255 needs ≤6 ticks/frame, so the
64 B ring has ~2x margin over the measured 31 B worst case. A 32 B ring would be
too tight for a 7-tick frame.

Stress runs (52 fps, `FX::drawBitmap` + `FX::display(CLEAR_BUFFER)` every frame,
`atm_fx_stream_service()` once per frame after display; absim 12000 ms;
harness `research/fx/fx_stream_spike/trace/absim_fx_harness.cpp`):

```
research/fx/fx_stream_spike/trace/run-absim.sh 12000
```

| Run | Tempo (effective) | Ticks | Underruns | Max service gap | Overflow |
| --- | --- | ---: | ---: | ---: | ---: |
| `fx_diag` (authored) | 50 req → 50.0 Hz | 493 (of 2113, 10 s) | **0** | **1** tick | 0 |
| `fx_diag_t255` | 255 req → `2000/7` ≈ 285.7 Hz | 2114 (to END) | **0** | **6** ticks | 0 |

The tempo-255 run decodes the entire 1903-byte stream to its END marker, so
buffer wrap (~30 laps of the 64 B ring) and the high FX addresses are exercised
end to end. The existing effective-divider behaviour is retained
(`osc_set_tick_rate` unchanged: `2000/rate`). Both runs report
`serviced=520`, i.e. one foreground service per frame, with zero underruns.

## 10.5 Stack

absim `min_stack` (lowest SP) with `.bss` end from `avr-nm`:

| Image | min_stack | .bss end | headroom |
| --- | ---: | ---: | ---: |
| `fx_stream` (production) | `0x0A90` | `0x0666` | **1066 B** |
| `fx_diag` | `0x0A8E` | `0x0675` | 1049 B |
| `fx_diag_t255` | `0x0A87` | `0x0675` | 1042 B |

Diag headroom is lower because of the diagnostic SRAM (`+15 B` total `.data`/`.bss`)
and the serial report path; production is 1066 B free at peak over the exercised
12 s. This is the spike fixture, not the game; no whole-game stack reserve is
claimed.

## 10.6 Selected ELF hashes and capture settings

- Capture: Ardens absim core (`Ardens` tree commit `661a7dd`), 12000 ms per run,
  USB connected, buttons released, `EMIT_SERIAL=1`; serial report at frame 520.
- FX CS: `CART_CS_SDA` (FQBN `arduboy-homemade:avr:arduboy-fx`), absim
  `fxport` = `PORTD1`.
- Candidate ELFs (sha256): `shell_fx` `879c9487…9115`, `fx_gfx` `d3c8e417…c86d`,
  `fx_stream` `422e683f…bac6`, `fx_diag` `d98eb354…45bb`.
- Baseline ELFs (sha256, re-measured): `shell` `365161da…0f93`, `music`
  `9ed998e7…e1fb` (refreshed 2026-10-18 to `dd145458…b403`; see
  `output-ATMlib2FX-mgd.md`), `music_sfx` `ebfa4c0e…d56d`.
- Streams: authored `62cba4f0…0e75`, tempo-255 `072d0f1d…3090`; fxdata
  `fa109a02…d593`.
- Exact commands: `research/fx/tools/measure-footprint.sh` (baseline, re-verified),
  `research/fx/tools/build-fx-stream.sh` (candidate),
  `research/fx/fx_stream_spike/trace/run-trace.sh 512`,
  `research/fx/fx_stream_spike/trace/run-absim.sh 12000`.

## 10.7 Explicit unsupported cases / not covered

This prototype supports only the shapes the `song01_sfx` music fixture uses and
does **not** establish any of the following:

- **Global loops**: `SET_LOOP_PATTERN` is rejected by the converter
  (`exit 2`); the all-channels-stopped loop restart is not converted.
- **FX SFX**: no SFX conversion or SFX timeline; the fixture is music only.
- **Complete converter**: only `ATM_SCORE_FMT_FULL`, 4 channels and the
  fixture's command set are handled; no general format validation.
- **Stream framing**: provisional; the SKIP/pending-tick split and the 8-bit
  group lengths are prototype choices, not pinned contracts.
- **Game integration**: no `CreatureGathererFX` save/read accounting, no save
  pause/resume, no bus arbitration beyond "service between transactions".
- **Whole-game fit**: the fixture is not the game; no total SRAM/stack/product
  claim is made.
- **Architecture selection**: this is one measured candidate. Its neutral
  footprint and ~15x asset expansion are inputs to `ATMlib2FX-hlh.2`, not a
  decision.
- **Device stack on unexercised paths**: save, other game phases and SFX
  interaction are not covered; the measured headroom is for the exercised 12 s.

## 10.8 Reproduce

```
research/fx/tools/measure-footprint.sh                                  # baseline pin
research/fx/tools/build-fx-stream.sh                                    # converter + candidate images
research/fx/fx_stream_spike/trace/run-trace.sh 512             # 512-tick equivalence
research/fx/fx_stream_spike/trace/run-absim.sh 12000           # stress + stack
```

Artifacts: `build/fx-port/fx-stream/` (`fx-stream-summary.csv`,
`equivalence.txt`, `absim-results.txt`, `spike_stream*.bin`, `fxdata_spike*.bin`,
per-variant `build-*.log`, ELFs). `build/` is not committed.

## 11. Architecture assessment (2026-10-17)

`ATMlib2FX-hlh.2` records a **no-go for production adoption of this
implementation**. It does not show the requested SRAM/program-flash reduction,
and loop/SFX/control/full-game behavior and costs remain unmeasured. The new
[architecture decision](fx-architecture-decision.md) preserves the resource
table and full retained ELF identities, qualifies the different-shell flash
estimate, and corrects the diagnostic tempo-255 lowest-SP transcription above
from `0x0A8C` to the saved log's `0x0A87` (1042 B headroom).

`ATMlib2FX-hlh.5` will measure one compact directly consumed stream, aiming at
a 32 B ring without the current 40 B staged frame. Merely shrinking the present
ring is insufficient: the saved converter metadata requires 33 B over seven
ticks. The experiment must establish actual feasibility and compare against
original music in the same FX graphics shell. `ATMlib2FX-hlh.6` is the next
selection gate; production authoring FX export stays blocked behind it.

---

# 12. Compact directly-consumed FX stream: measured costs

Tracking: `ATMlib2FX-hlh.5`. Measurement date: 2026-10-17. Repo HEAD
`f16387358a28d43204434019236305c6c8cc5efb`. This is one bounded candidate for
the architecture review `ATMlib2FX-hlh.6`, **not** an architecture selection.
No production `src/` behavior is changed: the default library build and the
retained `ATMlib2FX-aoe` build are byte-identical at the `.text` level
(re-verified, section 12.8). No external code was cloned, downloaded or copied;
`CreatureGathererFX` and `Ardens` were read only.

## 12.1 Outcome in one line

The compact candidate **meets the 32-byte ring / 7-tick service window** (worst
7-tick window 31 B) and **reduces engine SRAM** (−10 B vs the original same-shell
engine, −30 B vs the retained old-FX prototype) and the **FX asset** (1572 B vs
1903 B, −17.4%), but its **engine flash is +29 B** over the original same-shell
engine (while −140 B versus the retained prototype). It is a measured
SRAM/asset win with a small flash tradeoff against the original interpreter,
reported for `ATMlib2FX-hlh.6`; no production format is selected.

## 12.2 What was built

- Converter: `research/fx/tools/fx_compact_spike/fx_compile_compact.c`. It resolves pattern
  calls / call-repeats / returns / delays offline and copies every
  note/effect/volume command verbatim, so the device reuses the unchanged effect
  implementation. Unlike `research/fx/tools/fx_compile_stream.c` it does **not** emit the
  per-channel delay bytecode: it records each channel's next command tick and
  emits one shared gap per due pass.
- Device decoder: `src/atm_fx_compact.{h,c}` (`ATM_HAS_FX_COMPACT`), included by
  `src/atm_synth.c` like `cmd_parse.c`. 32-byte SPSC ring, direct in-ring
  consumption, whole-record preflight, no 40 B staged frame and no 16 B refill
  temporary. The PROGMEM score/SFX paths and per-channel pattern/return stacks
  are compiled out (`ATM_HAS_FX_STREAM_BACKEND`).
- Matched fixture: `research/fx/fx_compact_spike/fx_compact_spike.ino` (`-DFC_MODE`):
  identical 32x16 FX graphics / display / 52 fps shell for no-audio, original
  PROGMEM music, retained old FX stream and the compact stream.
- Host/absim harnesses and a format/fault test under
  `research/fx/fx_compact_spike/trace/`. Build lane `research/fx/tools/build-fx-compact.sh`.

Provisional framing (not a frozen ABI; full detail in the example README):

| Byte | Meaning |
| --- | --- |
| `0xC0` | magic/version header (skipped) |
| `<len> <gap> <bitmap> <per-channel glen+cmds>` | one due pass; `len` = total record bytes (>=5), `0x00` = END |
| `<gap>` | effect-only ticks to the next pass (`next-current-1`); bounded varint 1-3 bytes, max 65535 |
| `<bitmap>` | bit0..bit3 = channels with commands now |
| `<glen> <cmds>` | per set channel, in order, verbatim original command bytes |

The record's commands run at the current tick; effects advance on gap ticks. The
device preflights the whole record (residency + structure) before any mutation,
holds the consumer head until the record is applied, then publishes the head
advance behind a compiler barrier. Underflow freezes the tick (no partial
apply); malformed / zero-channel (nonprogressing) / oversize records set a
sticky error and stop. The foreground SPI read runs with sample interrupts
enabled; the timer consumer touches only SRAM.

## 12.3 Behavioural equivalence (first 512 music ticks)

```
research/fx/fx_compact_spike/trace/run-trace.sh 512
```

The **device decoder** is compiled on the host under the baseline osc.c timer
contract and emits the same CSV schema as section 7. Result: **MATCH** for all
512 ticks on oscillator `inc`/`mod`/`vol`, note/vol/mod, live effect state
(slide, arpeggio, note-retrig, noise-retrig, LFO, glissando), tempo-update order
and the active/mute flags, covering independent delays and three `CALL_REPEAT`
levels. Two host runs are byte-identical.
`reference_sha256=87e55846…d01d`, `compact_trace_sha256=001fa503…3947`.

Two columns are dropped as traversal-only: `cN_ps` (pattern stack index) and
`cN_delay`. `ch->delay` is written only by `cmd_parse.c` and read only by the
original command-fetch loop; no effect/oscillator path reads it, and the stream
now schedules command timing directly (source inspection of `src/`). The finite
run stops at tick 2113 (all voices muted, END reached); `stop_tick=2113`.

## 12.4 Whole-image footprint

Same lane/board/toolchain as section 2, matched FX graphics shell; `avr-size`,
static SRAM = `.data + .bss`. `score` is the 123 B `_ZL5score` symbol in `music`;
the compact stream lives on FX.

| variant | `FC_MODE` | Program | .text | .data | .bss | SRAM | score | stream | ELF sha256 (head) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `noaudio` | 0 | 4780 | 4742 | 38 | 1142 | 1180 | – | – | `13b5dc0b54fc3377` |
| `music` | 1 | 7844 | 7806 | 38 | 1324 | 1362 | 123 | – | `d558e071014250dc` |
| `oldfx` | 2 | 7890 | 7852 | 38 | 1344 | 1382 | – | 1572 | `9148a34a6601c87c` |
| `compact` | 3 | 7750 | 7712 | 38 | 1314 | 1352 | – | 1572 | `177dec70b66c1bac` |
| `compact_diag` | 3 | 8640 | 8598 | 42 | 1329 | 1371 | – | 1572 | `a95945ab78a625df` |

Matched engine deltas (over `noaudio`, same shell):

| Delta | Program flash | Static SRAM |
| --- | ---: | ---: |
| original music engine (−123 B score) | +2941 | +182 |
| retained old-FX engine | +3110 | +202 |
| **compact engine** | **+2970** | **+172** |

Engine SRAM meets the target; engine flash is a **+29 B** (~1%) regression versus
the original same-shell engine and **−140 B** versus the retained prototype.
Diagnostic overhead: `compact_diag − compact` = +890 B program, +19 B SRAM.

Per-symbol (`avr-nm -S`): `channels` 140 → **84** B (−56, pattern stacks gone);
`atm_fx_compact_state` **46** B (32 B ring, head/tail, two 32-bit offsets, active,
16-bit gap, error) versus `atm_fx_stream_state` **76** B; `noteTable` 128 B stays
in flash; note table/effect code shared. Production decoder:
`atm_fx_compact_tick_handler` 248 B + `atm_fx_compact_walk` 858 B, versus
`atm_fx_stream_tick_handler` 1150 B.

## 12.5 Asset and service-window feasibility

Converter output (`build/fx-port/compact/compact_stream.log`): `ticks=2113`,
`stream_bytes=1572`, `passes=188`, `payload_bytes=809`, `max_group=17`,
`max_record=24`. The old stream is 1903 B; the compact asset is **17.4%**
smaller. Decoder byte-window maxima (converter exhaustive, ticks): 1:24, 2:24,
3:24, 4:28, 5:28, **6:31, 7:31, 8:31** (worst at tick 590/591). The old stream's
7-tick maximum was 33 B, which a 32-byte ring cannot hold; the compact worst is
31 B, which a 32-byte ring holds.

Controlled seven-tick no-service window at requested tempo 255 (actual
`2000/7` Hz, 3.5 ms/tick): the host decoder services only every 7 music ticks and
sweeps all seven phases, exercising the true worst 7-tick window. Across the
whole song: **zero underruns**, `max_window=31 <= 32`, on every phase. Assumptions
recorded: refill is one `FX::readDataBytes` of ≤16 B per chunk looped to fill the
ring, executed once per foreground frame after `FX::display()`, assumed to
complete within the frame; the SPI transfer itself is not timed here.

## 12.6 Device runs (absim) and stack

12 s absim runs, USB connected, buttons released (`run-absim.sh 12000`), FX image
at `abs_stream_addr=16775424` (`0xFFF000`, above `0x010000`):

| run | ticks | underruns | max service gap | max window | error | stop tick |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `compact_diag` (authored ~50 Hz) | 493 | 0 | 1 tick (20 ms) | 24 | 0 | – |
| `compact_diag_t255` (`2000/7` Hz) | 2113 | 0 | 6 ticks (21 ms) | 28 | 0 | 2113 |

The tempo-255 run decodes the entire 1572-byte stream to END, exercising the high
FX address and ~49 laps of the 32-byte ring. Stack (`min_stack`, `.bss` end):
`compact` production `0x0AB2` / `0x0648` → **1130 B free**, versus the retained
prototype's `0x0A90` / `0x0666` → 1066 B; removing the 40 B staging frame lowers
the nested stack. `compact_diag` records `underruns=0`, `error=0`.

## 12.7 Format and fault tests

`research/fx/fx_compact_spike/trace/compact_format_test.c` (permanent host test,
run by `run-trace.sh`): gap-codec boundaries
0/1/31/32/33/127/128/254/255/256/257/0x7EFE/0x7EFF/0x7F00/65534/65535 advance
exactly `gap+1` ticks; oversize (`len > ring`), zero-channel (nonprogressing) and
malformed (group length mismatch) records are rejected with a sticky error and no
channel mutation; an injected underflow increments the counter and freezes the
tick with channel state unchanged.

## 12.8 Regression and identity

Rebuilding the default footprint `music` build and the retained `oldfx` build in
the new lane yields `.text` sections byte-identical to the retained
`ATMlib2FX-hlh.1` and `ATMlib2FX-aoe` ELFs (`avr-objcopy -O binary
--only-section=.text`): `a3543dc2…0d61` (FX stream) and `16f946a3…abc9` (music).
So the default and old-FX code paths are unchanged; whole-ELF hashes differ only
by build-path/debug metadata.

Selected artifacts (SHA-256): compact stream `0e8432ac…b0990`, tempo-255 stream
`b7702512…8249`, fxdata `45598c1c…4436`; ELFs `noaudio` `13b5dc0b…2d88`, `music`
`d558e071…d733`, `oldfx` `9148a34a…e201`, `compact` `177dec70…240a`, `compact_diag`
`a95945ab…2404`. Exact per-source hashes are in
`build/fx-port/compact/source-hashes.txt`. Toolchain: `arduboy-homemade:avr`
1.4.0, FQBN `arduboy-homemade:avr:arduboy-fx`, AVR-GCC 7.3.0, `-Os -flto`,
`CART_CS_SDA`, arduino-cli 1.2.0; local ATMlib 1.2.4 selected over installed
1.2.6 (build-log `Using library ATMlib at version 1.2.4 … ATMlib2FX`). Ardens
absim `libardensdebuggerlib.a` sha256 `0683bf46…dcd1`.

## 12.9 For `ATMlib2FX-hlh.6` and not covered

The compact candidate is one measured data point: ring/service feasibility is
established for this fixture, engine SRAM is nonincreasing, the FX asset is
smaller, and engine flash is a small disclosed regression versus the original
interpreter (and a saving versus the retained prototype). It is **not** approved
for production. Global loops (`SET_LOOP_PATTERN` rejected), SFX, pause/stop,
replacement/arming, save integration, full converter validation and any ABI
selection remain out of scope, exactly as the decision requires. Conversion
covers only the shapes `song01_sfx` uses; 32 B / seven ticks is demonstrated for
that fixture with zero underruns, not asserted universally.

