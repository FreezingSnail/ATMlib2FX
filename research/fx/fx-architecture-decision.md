# FX playback architecture decision

Date: 2026-10-17. Decision bead: `ATMlib2FX-hlh.2`.

**Decision: do not adopt the current 64-byte compiled-stream prototype as the
production backend.** It demonstrates useful music playback and FX concurrency,
but does not demonstrate the owner's minimum-SRAM/program-flash goal. Retain
offline expansion and foreground-only FX reads as hypotheses to test in one
smaller experiment. No production stream ABI or library API is selected here.

The next experiment is `ATMlib2FX-hlh.5`; its architecture review is
`ATMlib2FX-hlh.6`. Production authoring export `ATMlib2FX-3ii.3` depends on the
new review and remains blocked when this decision closes. A closed decision
bead must never be interpreted as evidence that a runtime was selected.

## Evidence and resource comparison

Sources: [original and prototype measurements](fx-footprint-results.md),
[source research](fx-port-research.md), retained artifacts under
`build/fx-port/`, and the current local decoder/converter source. This decision
rechecked the saved ELF sizes and hashes. It did not rebuild firmware or run a
new playback experiment.

All numbers below use the existing board/toolchain: FQBN
`arduboy-homemade:avr:arduboy-fx`, homemade AVR package 1.4.0, optimized
`arduboy-core`, `cathy3k`, AVR-GCC 7.3.0, Arduino CLI 1.2.0, `-Os -flto`,
`CART_CS_SDA`, local ATMlib 1.2.4 and installed ArduboyFX 1.0.11. Existing
logs establish local library selection over the installed same-named ATMlib.
Ardens source identity recorded by the measurement is `661a7dd`, v0.25.9.

### Whole images and song assets

Program is `.text + .data`; static SRAM is `.data + .bss`. These are music-only
comparisons except the explicitly separate music/SFX row.

| Image | Program B | .data B | .bss B | SRAM B | Song storage |
|---|---:|---:|---:|---:|---|
| Original shell | 4928 | 38 | 1141 | 1179 | None |
| Original music | 8036 | 38 | 1323 | 1361 | 123 B PROGMEM |
| Original music + SFX | 8322 | 38 | 1368 | 1406 | 123 B score + 10 B SFX, PROGMEM |
| FX initialization control | 4948 | 38 | 1141 | 1179 | None; `FX::begin()` only |
| FX graphics control | 4780 | 38 | 1142 | 1180 | FX bitmap; no music |
| FX music production prototype | 7890 | 38 | 1344 | 1382 | 1903 B FX stream |
| FX music diagnostic prototype | 8582 | 42 | 1355 | 1397 | Same FX stream |

The original music contribution is 3108 B program including the 123 B score,
or a 2985 B engine estimate after subtracting that score, and 182 B SRAM.
The FX prototype contribution over its graphics control is 3110 B program and
202 B SRAM. The reported difference is therefore **+125 B program** after
excluding the original song, and **+20 B SRAM**. The asset expands 123 to
1903 bytes, approximately 15.5 times; the bitmap is separate.

The flash difference is a **comparison of two different paired-shell deltas**,
not an isolated engine measurement. The original shell draws a PROGMEM sprite
and calls `arduboy.display()`; the FX shell draws an FX bitmap and calls
`FX::display()`. LTO can change attribution at those boundaries. Likewise,
the raw 7890-versus-8036 difference does not establish a 146-byte engine
saving. The next experiment must put original and FX music in the **same FX
graphics shell**, with identical frame work and a shared no-audio control.

The SRAM regression has direct symbol support: music channels shrink 140 to
84 B (56 B saved), while stream state adds 76 B, yielding 20 B net growth.
That state comprises a 64 B ring, two 32-bit offsets and four byte fields.
The 128 B note table remains in program flash in both builds. Neither a loop
implementation nor SFX playback is supplied by the current FX build, so these
costs cannot stand in for a complete equivalent-feature production library.

Original SFX adds 45 B fixture SRAM: a 44 B SFX state plus a one-byte fixture
flag. Its 286 B program delta includes the ten-byte SFX asset. FX SFX costs
have not been measured. The 20 B `FX::begin()` control does not measure the
cost of an audio-only FX reader or complete standalone FX playback.

### Stack and timing evidence

| Image/run | Lowest SP | End of globals | Free SRAM at peak |
|---|---|---|---:|
| Original music, production | `0x0AAF` | `0x0651` | 1118 B |
| Original music/SFX, production | `0x0AB2` | `0x067E` | 1076 B |
| FX music, production | `0x0A90` | `0x0666` | 1066 B |
| FX music diagnostic, authored tempo | `0x0A8E` | `0x0675` | 1049 B |
| FX music diagnostic, requested 255 | `0x0A87` | `0x0675` | 1042 B |

These are the saved 12-second absim runs, not current full-game measurements.
The old report's `0x0A8C` for the last row was a transcription error; the saved
log says `0x0A87`, consistent with its 1042-byte result. The two production
music fixtures differ by 52 B of measured free headroom, but their foreground
graphics paths differ, so that difference cannot all be attributed to the
decoder. The FX code stages a 40 B frame on the timer stack and a 16 B fetch
temporary on the foreground stack; local array sizes alone do not determine
the final nested-stack cost.

The original-reference comparison matched all 512 compared music ticks after
excluding removed pattern-stack indices: oscillator parameters, live effects,
channel values, delays, tempo and active/mute flags. The reference digest is
`87e55846b3abaf214a8cb68355a8db52a431e7b75ae7b0ee0b7b7c3447e5d01d`.
This is finite music-fixture evidence, not evidence for global loops, complete
score formats, independent SFX, pause/replacement or save integration.

The FX image was loaded above `0x010000` (absolute base `0xFFF800`). At 52 fps
with bitmap reads/display and one refill per frame, diagnostics reported zero
underruns: authored tempo 50 reached 493 music ticks; requested 255 reached
END at 2114 callbacks. Requested 255 means **2000/7 Hz**, one tick per 3.5 ms,
and the largest observed service gap was six ticks. This is an observation
under that fixture, not a universal six-tick or 19.23 ms service guarantee.

Saved byte-window maxima for the current stream are:

| Window, music ticks | 1 | 2 | 5 | 6 | 7 | 8 | 16 |
|---|---:|---:|---:|---:|---:|---:|---:|
| Bytes consumed | 25 | 27 | 29 | 31 | 33 | 33 | 35 |

Shrinking this implementation directly to a 32-byte ring cannot cover a
seven-tick window. The maximum current due frame is 25 B. The saved stream
has 1035 payload bytes within 1903 total bytes; removing traversal on the
desktop did not by itself produce a small device decoder or small FX asset.

## Why this is a no-go

The footprint priority is to minimize SRAM and engine program flash, while
retaining musical behavior. There is no measured saving in either engine
resource from the present evidence, and the direct SRAM accounting shows a
regression before production loop/SFX costs. Passing one finite song with no
underruns is valuable feasibility evidence, but does not justify freezing the
prototype ABI or adding the remaining features on top of it.

This conclusion rejects the measured implementation for production adoption;
it does not claim all pre-expanded streams are larger, or that the current
FXport branch is preferable. ISR SPI, whole-song SRAM loading and an unbounded
runtime lookahead queue remain unsuitable shortcuts for the stated integration.

## Next bounded experiment

`ATMlib2FX-hlh.5` will measure **one compact stream candidate**:

- Eliminate replay of traversal/delay bytecode where a shared tick-gap record
  can schedule the same note/effect command groups. Retain live synth/effect
  state and original ordering. Removing a traversal-only counter does not
  permit changing audible state or effect timing.
- Preflight a complete due-pass record, then consume it directly from the ring.
  Keep its head pinned until consumption finishes. Avoid the current 40 B
  staged frame and foreground copy temporary if the compiler and ownership
  proof allow it. Count all replacement metadata and measured stack.
- Try a 32 B ring with explicit complete-record lengths and a bounded wait
  representation. This is an experimental target, not a production contract.
  Measure byte windows and a controlled seven-tick service gap at tempo 255
  (24.5 ms between service opportunities, with refill execution/phase accounted
  for). If it cannot fit without changing behavior, report the failure.
- Use the same FX graphics shell for original music, no music, old FX music
  and the compact candidate. Preserve all existing effect algorithms/features;
  do not improve the comparison by silently disabling effects or adding fixes
  to the behavioral reference.

All output format bytes, limits and direct-ring ownership choices are local
spike outputs. The task must record a provisional layout and test it, not turn
this sketch into a production ABI. Additional architecture implementations,
full converter work and game changes stay outside that experiment.

The experimental commands are to be implemented/documented by that bead:
`research/fx/tools/build-fx-compact.sh`,
`research/fx/fx_compact_spike/trace/run-trace.sh 512`, and
`research/fx/fx_compact_spike/trace/run-absim.sh 12000`.
Use `build/fx-port/compact/`, retaining old evidence. Historical build scripts
contain git identity commands; future scripts must use explicit source/ELF
hashes and obey the current no-git/no-cloning instruction.

If the candidate reduces measured costs and preserves behavior, the separate
review `ATMlib2FX-hlh.6` may select it and decompose production work. If it fails,
that review must retain a blocker and scope the next evidence needed. Reducing
SRAM while growing engine flash is a disclosed tradeoff, not an automatic
pass, and a combined score must not conceal either cost.

## Contracts retained, and decisions still open

The no-go branch of this task does not require inventing byte layouts or a
stable API for an unsuccessful candidate. The following constraints remain
binding; the next review must resolve the open implementations explicitly.

| Area | Binding requirement | Unselected implementation |
|---|---|---|
| Record format | Explicit byte order, lengths, extents, maximum due group and padding; never dump host structs | New magic/opcodes/operands, gap width, terminator and admission limits |
| Musical ordering | Each pass advances effects then commands in channel order 0–3; preserve original rate transitions and independent player timing | Compact representation and evidence for any coalesced rate writes |
| Global loops | All-stopped synchronization, changed loop targets and immediate same-tick extra passes must match original; live effect state carries across | Intro/loop extents, traversal-cycle detection, extra-pass encoding and zero-time-cycle rejection |
| FX addressing | Data-section-relative 24-bit offsets; widened extent/base arithmetic, no double-added page, no wrapping beyond chip | Descriptor fields/widths and bounds/error policy |
| Refill and publication | Foreground SPI with sample interrupts enabled, timer uses only SRAM; full-record validation before effects/commands; no partial tick | Capacity, complete-group bound, byte-index visibility/barriers and refill deadline |
| Underrun | Freeze the affected player's tick before mutation, retain oscillator state and expose a diagnostic; supported loads must have zero underruns | Fault recovery and diagnostic feature cost |
| Start and replacement | Establish available initial data before advancing, replace atomically, invalidate old unread data; no partially mixed track state | Prefill/arming API and descriptor lifetime |
| Pause/stop | Pause preserves position/live state with defined mute/restore; stop mutes owned voices and unregisters the player | Immediate control API, pending-group handling and concurrent SFX effects |
| SFX | Independent tempo; music advances behind borrowed channel; stop/replacement restores the current music voice | Small PROGMEM SFX versus FX SFX, added state/reader costs; no mandatory second queue |
| Build/backend | Optional features pay only when linked; do not force both legacy traversal and FX decoding into shipping builds | C/C++ public API, build flags and bridge granularity |
| FX initialization | Caller owns its data page and existing FX lifecycle; library service runs between complete transactions | Exact public init/service surface and ownership documentation |
| Host conversion | Validate formats, operands, bounds, call-stack behavior, loops and finite conversion work before emitting assets | Complete legacy adapter, selected binary encoder and supported input matrix |

Source details that must survive later conversion include little-endian legacy
pattern offsets versus high-byte-first long-delay operands, skipped calls at
the three-level stack limit or to the current pattern, and the shared
PATTERN_END/RETURN/STOP opcode whose meaning depends on traversal state. Do not
silently adopt unrelated synth bug fixes while claiming original equivalence.

The model's v1 JSON authoring format, WAV renderer and HTML viewer can continue
to use their existing PROGMEM path. Their canonical host timeline is not an FX
wire format. A source-read finding also exposed integer rounding in host
effective-rate reporting: `ATMlib2FX-3ii.8` tracks preserving the actual
fractional rate before production FX authoring export. This decision changes
neither the device timer nor the host implementation.

## Full-game integration remains unmeasured

The current local reference is
`/Users/connorfranc/code/creaturegather/CreatureGathererFX`, inspected read-only.
Its declared physical application limit is 29696 B program flash; the project
static-SRAM ceiling is 2160 B out of 2560 B, and about 150 B effective stack
reserve must remain after real worst-case nested work. The older 23488 B
program/1747 B globals/509 B painted headroom checkpoint is dated 2026-10-10.
It is not a fresh budget for adding audio.

A separately owned cross-repository integration task must measure actual game
flash, static state, waveform/refill/nested interrupt stack and save-path stack.
It must give audio reads their own accounting without weakening metadata-read
assertions, keep prohibited render-to-display intervals free of reads, and
measure real maximum service gaps. Before any save program/erase begins, pause
and mute FX players; do not refill while the chip is busy; resume only after
final busy completion. Seamless save-time playback is not selected.

No existing standalone trace or stack measurement proves those constraints.
A selected music decoder must still budget SFX, loop/control metadata and final
bridge code. Production converter, runtime/loop, SFX/API, packing/examples and
game-verification tasks should be filed with concrete contracts only after
the new architecture review selects a runtime.

## Retained identity and verification

The historical source reference is
`f16387358a28d43204434019236305c6c8cc5efb`; the FX prototype was a workspace
change over it, so that reference alone is not a source snapshot. The following
retained ELF hashes were re-read for this decision, without git commands:

| Saved artifact under `build/fx-port/` | SHA-256 |
|---|---|
| `avr-shell/footprint_baseline.ino.elf` | `365161da452517b60e1a0eef4bce8050719a58a111a6a5b62ae8b28286430f93` |
| `avr-music/footprint_baseline.ino.elf` | `9ed998e756c3776ea5a72f8ce8124f08661613b8fb221e3521078557b1cae1fb` |
| `avr-music_sfx/footprint_baseline.ino.elf` | `ebfa4c0ed3a5a58c58b646d485816bd591f67b796332b1c961266899cf2dd56d` |
| `fx-stream/avr-fx_gfx/fx_stream_spike.ino.elf` | `d3c8e41705f455f4a3534fc07f9ba731f3e1a0f392c4e9762f34ab155aa0c86d` |
| `fx-stream/avr-fx_stream/fx_stream_spike.ino.elf` | `422e683f07af342559a883757daeded47f9c6c2bdfeaddb185235d8e97d9bac6` |
| `fx-stream/avr-fx_diag/fx_stream_spike.ino.elf` | `d98eb3545fce63300df067ba03ec62860309ce4f3ad98a76ac45de119b6145bb` |
| `fx-stream/spike_stream.bin` | `62cba4f0faefcff8f605690c278b7bff466fa73d3a79f3aa3dfc52b4c91a0e75` |
| `fx-stream/spike_stream_t255.bin` | `072d0f1da9c4d4db2560588c52812a251fa318f88150c0c6ac9ee269b30d3090` |

Current decoder source hashes, recorded at decision time, are not a claim that
all historical binaries were rebuilt from today's files:

| File | SHA-256 |
|---|---|
| `src/atm_fx_stream.c` | `c521f47cc6764f74186d6c25049650224154944b4f02cfba4a12d4b91580d52d` |
| `src/atm_fx_stream.h` | `788544c87fb45ae27fc3ae2ab97113c2400922ff35f2657c437a42bd331d1116` |
| `research/fx/tools/fx_compile_stream.c` | `0a38bdc0b64e18e57c6718646a26c2a5abdd4c04b8e88db13e54b4fe31911893` |
| `src/atm_synth.c` | `e8820ad445ce0608f87cb612d5c6ff7078f6a10e83f30e39c05eb120e311772f` |
| `src/cmd_parse.c` | `90ab99fe961294b6ac091bfe1ff89102e4fb2da475ff114b3da62f8eda4e6c89` |
| `src/osc.c` | `bd2156625ce41a2c34ce8609726fa7694537d8129faf5c6922d7a061c06a3e80` |

Verification here was limited to reading saved CSV/trace/absim results,
hashing retained files, and running the installed `avr-size --format=avr
--mcu=atmega32u4` on original and FX production ELFs. Those reproduced
8036/1361 and 7890/1382 B. No production source, external repository, or binary
was changed. No external source was cloned, downloaded or copied.
