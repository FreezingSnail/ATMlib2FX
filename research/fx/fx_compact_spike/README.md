# Compact directly-consumed FX music spike (ATMlib2FX-hlh.5)

Experimental measurement lane for **one** compact FX music candidate. It is a
spike: the record layout, ring size and limits below are **provisional** and are
not a production ABI. `ATMlib2FX-hlh.6` is the separate decision gate that may
select or reject them. This candidate replaces the *representation* measured in
the retained `ATMlib2FX-aoe` prototype (`research/fx/fx_stream_spike/`), which the
decision `research/fx/fx-architecture-decision.md` rejected for production adoption.

## What is tested

One matched 32x16 FX graphics shell (`fx_compact_spike.ino`), identical frame
work (FX bitmap read + `FX::display`, 52 fps, one foreground service per frame),
selected by `-DFC_MODE`:

| `FC_MODE` | variant | audio backend |
| --- | --- | --- |
| 0 | `noaudio` | none (FX graphics control) |
| 1 | `music` | original PROGMEM score (`examples/arduino/songs/song01_sfx`, unchanged) |
| 2 | `oldfx` | retained 64-byte-ring stream (`src/atm_fx_stream.{h,c}`) |
| 3 | `compact` | new compact 32-byte-ring stream (`src/atm_fx_compact.{h,c}`) |

`-DATM_FX_COMPACT_DIAG=1` (mode 3) / `-DATM_FX_STREAM_DIAG=1` (mode 2) build the
diagnostic variants with counters and one USB-CDC report.

Commands (all from the repo root):

```
research/fx/tools/build-fx-compact.sh                                  # converter + images + ELF sizes/hashes
research/fx/fx_compact_spike/trace/run-trace.sh 512           # equivalence + format tests + window stress
research/fx/fx_compact_spike/trace/run-absim.sh 12000         # absim device runs (serial + stack)
```

Artifacts land under `build/fx-port/compact/`. No git commands are used; identity
is source/ELF SHA-256 hashes.

## Provisional record layout

The converter is `research/fx/tools/fx_compact_spike/fx_compile_compact.c`. It resolves
pattern calls / call-repeats / returns / delays offline and copies every
note/effect/volume command **verbatim**, so the device reuses the unchanged
effect implementation.

```
byte 0       0xC0 magic/version (skipped by the decoder)
then records until END:
  <len> <body>          len = total record length in bytes (>= 5); 0x00 = END
  body := <gap> <bitmap> <groups>
    <gap>    effect-only ticks between this pass and the next
             (next_pass_tick - current_tick - 1; 0 = adjacent passes)
    <bitmap> bit0=ch0 .. bit3=ch3: exactly the channels with commands now
    <groups> per set channel, in order 0..3: <glen> then <glen> command bytes
```

* Integers are little-endian. `<glen>` and `<len>` are one byte.
* Command bytes use the original ATMlib encoding, so `cmd_size` matches the
  library (note/delay/immediate = 1, 1-parameter = 2, n-parameter = 1 + n).
* `<gap>` is a bounded varint: `<= 0x7F` -> 1 byte; `<= 0x7EFF` -> 2 bytes
  (`0x80|hi7`, `lo8`); else 3 bytes (`0xFF`, `hi8`, `lo8`). Maximum 65535.
* Limits chosen for this spike: `<len>` <= 255 in the converter (hard error),
  `<len>` <= ring size on the device (else oversize error); a pass must carry at
  least one channel (`bitmap != 0`, else nonprogressing error); a channel group
  must have `glen >= 1` and its commands must fit the record exactly.

The record's commands run at the current music tick; the gap says how many
effect-only ticks follow before the next record's commands. This removes the
per-channel delay bytecode (traversal only) and merges what the old format spent
on a per-tick APPLY plus a separate SKIP record into one bounded gap field.

## Ownership, preflight and fault policy

* Single-producer/single-consumer ring of `ATM_FX_COMPACT_RING` (32) bytes.
  `head`/`tail` are `uint8_t`; the producer writes at `tail` and publishes it
  behind a compiler barrier, the timer consumer reads only up to the published
  `tail`. The foreground writes directly into the ring (no 16-byte refill
  temporary, no 40-byte staging frame).
* Foreground `service()` runs the FX SPI read with sample interrupts enabled;
  the timer consumer touches only SRAM (never SPI).
* On a pass tick the consumer **preflights the whole record**: it checks the
  record is resident (`tail-head >= len`), rejects oversize, then structurally
  validates (lengths, bitmap, command sizes) with no effect/command mutation.
  Only then does it run effects and commands directly from the pinned record and
  advance `head`. A short record freezes the tick before any mutation and counts
  an underrun; a malformed/nonprogressing/oversize record sets a sticky error and
  stops.
* The decoder stops as soon as no voice is active (mirrors the original score
  handler), or on the END record.

## Excluded traversal fields

The equivalence trace drops two columns that are traversal only in this backend:

* `cN_ps` — per-channel pattern-stack index (removed with the pattern stacks).
* `cN_delay` — per-channel command delay. The stream itself schedules command
  timing, and no effect/oscillator path reads `ch->delay` (it is written only by
  `cmd_parse.c` and read only by the original command-fetch loop). Verified by
  source inspection of `src/`.

Every other behavioural column — oscillator `inc`/`mod`/`vol`, note/vol/mod,
live effect state (slide, arpeggio, note-retrig, noise-retrig, LFO, glissando),
tempo, and the active/mute flags — is compared exactly.

## Measured results (this workspace)

Board `arduboy-homemade:avr:arduboy-fx`, package 1.4.0, AVR-GCC 7.3.0, `-Os
-flto`, `CART_CS_SDA`; local ATMlib 1.2.4 (selected over the installed 1.2.6).

Asset: the compact stream is **1572 B** (old prototype **1903 B**; −17.4%), on
FX, not in flash. Original score `_ZL5score` = 123 B in the `music` build.

| variant | program | .text | .data | .bss | SRAM | ELF sha256 (head) |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| noaudio | 4780 | 4742 | 38 | 1142 | 1180 | `13b5dc0b54fc3377` |
| music | 7844 | 7806 | 38 | 1324 | 1362 | `d558e071014250dc` |
| oldfx | 7890 | 7852 | 38 | 1344 | 1382 | `9148a34a6601c87c` |
| compact | 7750 | 7712 | 38 | 1314 | 1352 | `177dec70b66c1bac` |
| compact_diag | 8640 | 8598 | 42 | 1329 | 1371 | `a95945ab78a625df` |

Matched engine deltas (over `noaudio`, same shell):

| delta | program flash | static SRAM |
| --- | ---: | ---: |
| original music engine (−123 B score) | +2941 | +182 |
| old FX prototype engine | +3110 | +202 |
| **compact engine** | **+2970** | **+172** |

So the compact candidate is **−10 B engine SRAM** and **+29 B engine flash**
versus the original same-shell engine, and **−140 B flash / −30 B SRAM** versus
the retained old-FX prototype. Engine SRAM meets the target; flash does not meet
the original-engine target (a `+29 B`, ~1% tradeoff). Decoder symbols: channels
140 -> 84 B, `atm_fx_compact_state` 46 B (vs `atm_fx_stream_state` 76 B); the
production decoder tick handler is `atm_fx_compact_tick_handler` 248 B +
`atm_fx_compact_walk` 858 B, versus `atm_fx_stream_tick_handler` 1150 B.

Stream/dispatch bounds: max due group **17 B**, max record **24 B**, decoder
byte-window maxima 1:24, 2:24, 3:24, 4:28, 5:28, 6:31, 7:31, 8:31 (worst at tick
590). The 32-byte ring holds the worst 7-tick window (31 B).

Device runs (absim, 12 s, USB connected, buttons released):

| run | ticks | underruns | max service gap | max window | error | stop tick |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| compact_diag (authored ~50 Hz) | 493 | 0 | 1 tick (20 ms) | 24 | 0 | – |
| compact_diag_t255 (2000/7 Hz) | 2113 | 0 | 6 ticks (21 ms) | 28 | 0 | 2113 |
| compact production | – | – | – | – | – | – |

The tempo-255 run decodes the whole stream to END, exercising the FX address
`abs_stream_addr=16775424` (`0xFFF000`, above `0x010000`) and ring wrap (~49
laps of the 32 B ring). Production `min_stack=0x0AB2`, `.bss` end `0x0648`,
**1130 B free** at peak — better than the old prototype's `0x0A90`/1066 B because
the 40-byte staging frame is gone.

### Service window and refill assumptions

At 52 fps a frame is ~19.23 ms. The requested tempo 255 is `2000/7` Hz
(3.5 ms/tick), so a frame spans 5-6 ticks. The **controlled 7-tick no-service
window** is a one-tick margin over that: the host harness services only every 7
music ticks and sweeps all seven phases, exercising the true worst 7-tick window
(31 B) with **zero underruns** and `max_window <= 32`. Assumptions recorded here
(not separately instrumented): the foreground refill is one `FX::readDataBytes`
of at most 16 B per chunk, looped until the ring is full, and runs after
`FX::display()` has finished; the SPI transaction is assumed to complete within
the frame's remaining time. The absim runs demonstrate zero underruns with one
service per frame, but do not time the SPI transfer itself.

## Format and fault tests

`research/fx/fx_compact_spike/trace/compact_format_test.c` (host, permanent):
gap-codec boundaries 0/1/31/32/33/127/128/254/255/256/257/0x7EFE/0x7EFF/0x7F00/
65534/65535 advance exactly `gap+1` ticks; oversize, zero-channel
(nonprogressing) and malformed records are rejected with the sticky error set and
no channel mutation; an injected underflow increments the counter and freezes the
tick without mutating channel state.

## Not covered (out of scope)

Global loops (`SET_LOOP_PATTERN` is rejected by the converter), SFX, pause/stop
API, replacement/arming, game save integration, full conversion validation, a
production converter or ABI, and any architecture selection. Only the shapes the
`song01_sfx` music fixture uses are converted. A `32 B`/`7-tick` failure or a
flash/SRAM tradeoff is experiment data for `ATMlib2FX-hlh.6`, not production
approval.

## Provenance

No git/network/clone/fetch/download/vendor/copy of external code. External
references (`Ardens`, `CreatureGathererFX`) were read only. Regression proof:
rebuilding the default footprint `music` build and the retained `oldfx` build
produces `.text` byte-identical to the retained `ATMlib2FX-hlh.1`/`aoe` ELFs
(`avr-objcopy -O binary --only-section=.text`).
