# FX playback architecture decision

> Historical record. The spike code was removed; commands and paths below refer
> to the retired research lane. Current contract: [FX music integration](../../docs/fx/integration.md).

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

Refreshed 2026-10-18 for the ATMlib2FX-mgd evidence update:
`avr-music/footprint_baseline.ino.elf` is now
`dd14545861c96924dabc17c26cbd3496a06ba697302715ee874fca8598b46403` (the
hlh.1-era artifact above is preserved at `build/fx-port/avr-music-hlh1-retained/`;
cumulative `.text` `+28 B`, `.bss` `+1 B`; see `output-ATMlib2FX-mgd.md`).

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

## hlh.6 review: compact stream selected for finite v1 music (2026-10-17)

Decision bead: `ATMlib2FX-hlh.6`. The compact directly-consumed stream measured
by `ATMlib2FX-hlh.5` is selected as the production direction **for finite
(non-looping, no-SFX) music only**, with the pinned contract below. Every
behavior marked *not yet demonstrated* is owned by a listed production bead; no
such behavior may be advertised or shipped before that bead passes. This
selection does not adopt any other measured prototype and does not change the
legacy PROGMEM default build.

Measured same-shell deltas versus the original PROGMEM interpreter
(`fx-footprint-results.md` §12, `build/fx-port/compact/`): engine SRAM −10 B,
engine flash +29 B (disclosed tradeoff; −140 B flash / −30 B SRAM versus the
rejected 64-byte prototype), FX asset 1572 B vs 1903 B (−17.4 %), 512-tick
trace MATCH with only the traversal-only columns `cN_ps`/`cN_delay` dropped,
worst observed 7-tick service window 31 B inside a 32 B ring with zero underruns
at 2000/7 Hz (absim, ~49 ring laps, FX address above `0x010000`), production
stack free 1130 B. Record maxima on the fixture: complete record 24 B, due group
17 B, 188 passes, 809 payload bytes; these are measurements, not limits.

Source identity for this selection is the working-tree set committed with this
decision: `src/atm_fx_compact.{h,c}` plus the guarded integration in
`src/atm_synth.{h,c}` and `src/cmd_parse.c`. The hlh.5-era binary hash set is the
HASH CORRECTION set recorded in `ATMlib2FX-hlh.5` (`compact 177dec70…`,
`oldfx 9148a34a…`, `music d558e071…`, `noaudio 13b5dc0b…`,
`compact_diag/t255 a95945ab…`, stream `0e8432ac…`, t255 `b7702512…`). Documents
listed above still cite pre-reorganization paths; the live trees are under
`research/fx/`.

### Pinned contract (finite v1)

1. **Framing.** Stream = version byte `0xC0` (skipped by the decoder), then
   records until an `0x00` length byte (END). Record = `<len>` + `<gap>` +
   `<bitmap>` + for each set channel in order 0–3 `<glen>` then `<glen>` command
   bytes. All integers little-endian, one byte each. Gap varint: `<=0x7F` one
   byte; `<=0x7EFF` two bytes (`0x80|hi7`, `lo8`); otherwise three bytes
   (`0xFF`, `hi8`, `lo8`); maximum 65535. `bitmap` must be 1–15; `len >= 5`;
   `glen >= 1`; command bytes keep the original ATMlib command encoding.
   Traversal commands (`CALL`, repeats, `SET_LOOP_PATTERN`) must never appear in
   finite-v1 streams; the converter resolves them offline. A `PATTERN_END` byte
   surviving in a group stops that channel (shared `apply_cmd` semantics), never
   loops.
2. **Limits.** `len <= ring capacity`; default ring 32 B (`ATM_FX_COMPACT_RING`,
   power of two, `<=256`). The host converter must enforce the same admission
   limit and report the offending source event on rejection. Larger rings are a
   build-time configuration, never a silent host behavior.
3. **Refill and publication.** Single-producer (foreground service only) /
   single-consumer (timer ISR only) ring. Producer fills directly with bounded
   fetches, then publishes `tail` behind a compiler barrier; consumer preflights
   the complete record (resident, length in range, structural walk, no mutation)
   and pins `head` until the pass is applied, then advances `head`. 8-bit
   indices are atomic on AVR; the timer never touches SPI. Refill deadline: at
   least one complete record per frame (52 fps ≈ 19.23 ms); a stream is shippable
   only if the host-validated worst service window fits the ring.
4. **Addressing.** The caller supplies a data-section-relative 24-bit offset and
   length; decoder offsets are `uint32_t` relative to the descriptor base; the
   fetch callback receives relative offsets; the page is added exactly once; all
   reads are bounds-checked against `stream_end`.
5. **Underrun and errors.** A due pass without a resident record freezes the
   tick before mutation, retains oscillator state and increments the underrun
   counter. A malformed record (walk mismatch) or `len > ring` sets a sticky
   error and stops playback. An END record or an all-inactive voice mask stops
   cleanly, mirroring the original.
6. **Start and stop.** `play` stops previous playback, re-initializes channels
   and arms the descriptor; production must prefill the first record before the
   first due tick (correction to the spike's register-then-fill order). `stop`
   mutes owned voices and unregisters.
7. **Pause and replacement** (semantics pinned; implementation owned by
   `ATMlib2FX-hlh.9`): pause preserves position and live state with a defined
   mute/restore; replacement is atomic and invalidates unread data; no partially
   mixed track state is observable.
8. **SFX** (owned by `ATMlib2FX-hlh.9`): independent tempo, music advances
   behind the borrowed channel, stop/replacement restores the current music
   voice. Storage choice (small PROGMEM SFX versus FX SFX) must be selected with
   separate estimated/unmeasured/measured costs; no mandatory second queue.
9. **Build/backend.** `ATM_HAS_FX_COMPACT=1` selects this backend (default 0);
   shipping builds never link both the legacy traversal path and an FX decoder;
   diagnostics (`ATM_FX_COMPACT_DIAG`) and SFX pay only when enabled; the legacy
   PROGMEM path remains the default library build.
10. **FX initialization and service ownership.** The caller owns
    `FX::begin(page)` and the data-page lifecycle; the library only consumes the
    fetch callback. Service runs in the main loop after display with sample
    interrupts enabled, between complete SPI transactions.
11. **Host admission** (owned by `ATMlib2FX-hlh.7`): validate formats, operands,
    bounds, call-stack behavior and finite conversion work; reject anything
    outside the input matrix with source-event diagnostics; emit deterministic
    bytes plus metadata (ticks, passes, payload, max group/record, window table).

### Explicitly not claimed

Global loop synchronization, loop-target changes and same-tick extra effect
passes remain **unresolved** — no concrete original trace exists yet and the
spike converter rejects `SET_LOOP_PATTERN`; they are owned by
`ATMlib2FX-hlh.8`, whose acceptance requires new original-engine loop traces,
compact equivalence with no dropped behavioral columns, and an intro/loop demo.
Pause/replacement/SFX behavior, the general converter input matrix, packing
tooling, and game fit are owned by `ATMlib2FX-hlh.9` … `ATMlib2FX-hlh.11`. Game
gates (flash ≤ 29696 B, static SRAM ≤ 2160 B, ≈150 B reserve with painted
headroom) are **unmeasured**; the authoring adapter `ATMlib2FX-3ii.3` exports
finite v1 only and must not advertise loops, effects or SFX.

### Production beads created by this review

| Bead | Scope | Depends on |
|---|---|---|
| `ATMlib2FX-hlh.7` | General converter for legacy tracker scores into the pinned format; admission diagnostics; deterministic metadata | hlh.6 |
| `ATMlib2FX-hlh.8` | Runtime loop completion: all-stopped sync, loop targets, same-tick extra passes, intro/loop demo with original traces | hlh.6 |
| `ATMlib2FX-hlh.9` | Pause/replacement/arming semantics + independent-tempo SFX overlay, storage choice with cost classes | hlh.6 |
| `ATMlib2FX-hlh.10` | FX packing tooling, example sketches and integration documentation | hlh.7 |
| `ATMlib2FX-hlh.11` | CreatureGathererFX integration and game-gate verification (cross-repo, owner-scoped) | hlh.8, hlh.9, hlh.10 |

Residual disclosures: engine flash is +29 B versus the original interpreter;
SPI transfer time for refills is assumed, not measured; all `build/fx-port/`
evidence and the selected decoding sources were workspace-only and are preserved
by the commit accompanying this decision.

## hlh.9: pause/replacement/arming + independent-tempo SFX (2026-10-17)

Decision bead: `ATMlib2FX-hlh.9`. This section implements and measures contract
items 6–8 of the hlh.6 pinned contract: start/prefill, pause/stop/replacement,
and the SFX overlay. It does **not** touch loop support (hlh.8). All evidence is
in the new lane `build/fx-port/control/`; the retained `build/fx-port/compact/`
lane and its hlh.5 ELFs were not rebuilt (retained `avr-compact` ELF is still
`177dec70b66c1bac…`) and the original reference trace was re-read, never
regenerated.

Source identity (SHA-256 in `build/fx-port/control/source-hashes.txt`): the
implementation is `src/atm_fx_compact.{h,c}` (pause/prefill/atomic-replacement
and the PROGMEM SFX overlay) plus the guarded `ATM_HAS_FX_COMPACT` block in
`src/atm_synth.c`; `src/cmd_parse.c` is unchanged. Everything is gated by
`ATM_HAS_FX_COMPACT` (default 0) and the overlay by `ATM_FX_COMPACT_SFX`
(default 0).

### What was implemented and proven

* **Prefill before arm.** `play` resets the descriptor, runs the foreground
  refill with sample interrupts enabled and the timer still unregistered, then
  arms. `control_test` asserts a resident record immediately after `play` and
  `underruns == 0` on the first due tick.
* **Pause/resume.** Position, gap, channel and effect state are preserved; owned
  voice volumes are saved and muted on pause and restored on resume; the timer
  is unregistered on pause and re-armed on resume. The host test shows a
  paused/resumed run reaches the next note at the **same music-tick count** as a
  control run (no drift) and that 4000 base events while paused advance nothing.
  `atm_synth_set_score_paused`/`_get_score_paused` delegate to it for the
  compact backend.
* **Stop and atomic replacement.** `stop` unregisters and mutes the owned
  voices. `play` runs inside `ATOMIC_BLOCK(ATOMIC_RESTORESTATE)` on AVR:
  stop/mute, reset, channel re-init, discard unread bytes, prefill, arm. The host
  test shows the ring after replacement holds only the new track and the first
  due tick applies the new track's record with the channel re-initialized (no
  mixed state).
* **SFX overlay.** A second compact record stream stored in **PROGMEM** is read
  by the timer directly (no FX SPI, no second ring, no second queue) on tick
  callback 1 at its own tempo. It borrows one music voice (save + zero +
  redirect the music channel's effects into the saved shadow), keeps music
  advancing behind it, and restores the borrowed voice on natural stop, explicit
  stop and replacement. The borrow/restore and single-overlay replacement are
  asserted in `control_test`.

Ownership/API surface is documented at the top of `src/atm_fx_compact.h`
(caller owns the FX page and stream lifetimes; library owns the ring, channels
and the borrowed SFX voice; service runs in the foreground between complete SPI
transactions).

### Trace equivalence

`build/fx-port/control/sfx_trace_main` drives the device decoder (music + SFX)
on the host and compares against `reference_trace_music_sfx.csv`
(SHA-256 `10ec84de82eb11d68bd7ccd56f328f9414c2eb44e23b80b4b9e20506f184083f`;
regenerated for ATMlib2FX-mgd, see
`research/fx/footprint_baseline/trace/README.md`), dropping only the
traversal-only columns `cN_ps`/`cN_delay`:

* 512 `M` rows + 23 `S` rows, **MATCH** (trace SHA-256 `0a9aa641d348254a…`,
  `build/fx-port/control/sfx_equivalence.txt`).

So the borrowed-channel overlay, the `0x70→0x30` mute flip, the independent
22.22 Hz SFX tempo and the music-advances-behind behaviour all reproduce the
original reference exactly.

### Storage decision (SFX)

**Selected: PROGMEM compact SFX.** The SFX fixture (`sfx1`) encodes to a 21-byte
compact stream in flash, read directly with `pgm_read_byte`; it needs no FX
read, no ring and no second queue. Per-class costs:

| SFX storage class | Asset | Runtime need | Status |
| --- | ---: | --- | --- |
| **PROGMEM compact (selected)** | **21 B flash** | shared compact reader + `pgm_read_byte`; no ring, no SPI, no queue | **measured** |
| small PROGMEM SFX via legacy MINIMAL_MONO traversal | 10 B flash | retains the traversal interpreter the FX backend removes | estimated (hlh.1: original SFX adds 286 B program incl. 10 B asset, 45 B SRAM) — not built here |
| FX SFX (compact records in the FX data section) | 21 B on FX | second ring (≥32 B SRAM) + foreground SPI service + duplicate ownership | estimated/unmeasured — rejected (mandatory second queue) |

The measured cost of the whole SFX feature (not the storage-class difference) is
the `mode 4` build over the music-only `mode 3` build in the same shell:

| variant | program | .text | .data | .bss | SRAM | SFX asset | ELF sha (head) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| compact (music only, hlh.9) | 7848 | 7810 | 38 | 1319 | 1357 | 0 | `f7ef2855e869da98` |
| control (+ SFX) | 9152 | 9114 | 38 | 1363 | 1401 | 21 | `956b41dcd4ae4857` |
| control_dg (+ SFX, DIAG) | 10292 | 10250 | 42 | 1390 | 1432 | 21 | `e5521783e776cafb` |

Whole-image deltas for SFX: **+1304 B program** (includes the 21 B asset) and
**+44 B SRAM** (`atm_fx_compact_state` 51 → 94 B; SFX symbols
`atm_fx_compact_sfx_walk` 386 B, `atm_fx_compact_sfx_tick_handler` 276 B,
`atm_fx_compact_stop_sfx` 100 B). LTO re-attributed some shared code
(`apply_cmd` appears standalone at 460 B, `main` grows 296 B), so the whole-image
number is the honest one; the SFX-only symbol sum is ~762 B plus the reader.
Because it is gated by `ATM_FX_COMPACT_SFX` (default 0), music-only builds pay
none of it. The pause/prefill/atomic/stop-mute work costs the compact build
**+98 B program / +5 B SRAM** over the retained hlh.5 `compact` build
(7750/1352 → 7848/1357).

### Device verification (absim)

`build/fx-port/control/avr-control_dg` (12 s run, 52 fps, FX address above
`0x010000`, one foreground service per frame):

```
FCSFXDIAG borrow=2 sfx_ticks=23 restore_ok=1 start=56 stop=105 underruns=0 error=0 ticks=493 frames=520
min_stack=0x0aaf bss_end=0x0698 headroom_bytes=1047
```

The SFX borrows `OSC_CH_TWO`, runs exactly 23 ticks (the reference count) at its
own tempo, restores the borrowed voice, and the music advances 49 ticks behind
it with zero underruns — the reference-trace semantics reproduced on device.

### Default build unchanged

The lane rebuilds the hlh.1 music fixture (`FP_AUDIO=1`, no FX macros) and
compares `.text` against the retained `avr-music` baseline ELF (refreshed
2026-10-18 for ATMlib2FX-mgd: cumulative `.text` `+28 B`, `.bss` `+1 B` over the
hlh.1-era artifact; see `output-ATMlib2FX-mgd.md`): **byte-identical**
(`build/fx-port/control/default_regression.txt`). Default library builds are
unaffected by the FX layers; every change lives behind `ATM_HAS_FX_COMPACT` /
`ATM_FX_COMPACT_SFX`.

### Not claimed

Loop support (hlh.8) is untouched. The SFX converter covers the `song01_sfx`
`sfx1` MINIMAL_MONO fixture shape only; a general host converter/admission is
hlh.7/hlh.10. The SFX asset is device-read directly, so the SFX must fit the
PROGMEM record framing; large or streaming SFX is out of scope. Game fit, save
integration and general packing remain hlh.10/hlh.11.


## hlh.8: global loops - all-stopped sync, loop targets, same-tick extra passes (2026-10-17)

Decision bead: `ATMlib2FX-hlh.8`. This section resolves the global-loop behavior
`ATMlib2FX-hlh.6` explicitly deferred: the original engine's all-stopped loop
restart, changed loop targets (including the pattern-0 quirk path), and the
immediate same-tick extra effect pass with live effect state carried across. It
extends the pinned compact contract; it does not change finite-v1 output.

Source identity is frozen: `research/fx/tools/build-fx-loops.sh` snapshots the
SHA-256 of every lane input at lane start (`build/fx-port/loops/source-hashes.txt`,
`source-hashes.start.txt`) and re-checks the snapshot with `shasum -c` at lane end
(`source-freeze.txt`), so evidence cannot come from mixed sources. The lane also
orders its steps so the AVR images are rebuilt before the nested absim device
run, and pins the fresh loop_dg ELF SHA-256 across both absim invocations
(`run-absim-loops.sh` fails on a stale/mismatched image), so the recorded
device bullet cannot describe a previous lane's ELF. The encoder is
`tools/fx_pack/fx_encode.{c,h}`/`fx_pack.c`; the device decoder is the
guarded loop block in `src/atm_fx_compact.{c,h}` (`ATM_FX_COMPACT_LOOP`, default
0). `src/atm_synth.c`, `src/cmd_parse.c` and the finite `ATM_HAS_FX_COMPACT`
behavior are unchanged. All evidence is in the NEW lane `build/fx-port/loops/`;
the compact/control/pack lanes were not overwritten.

### Contract extension (loop streams, magic 0xC1)

```
0xC1
u24 LE loop_start_rel   byte offset of the first loop-region record
<records...>            same record framing as finite, with:
0x00 END                END is the loop boundary, not a stop
```

Loop-mode record changes:

* `gap` field: `0` = next record in the **same** tick (the original's immediate
  second pass); otherwise `effect-only ticks + 1`.
* `bitmap`: bits 0..3 command channels, bits 4..7 the restart mask. A non-zero
  restart mask marks the original's all-stopped pass; after applying it the
  device re-arms those channels in the same tick. `bitmap == 0` is an
  effect-only pass (no commands, no restart).

The loop region `[loop_start_rel, stream_len-1)` is the traversal cycle found by
detecting the first repeat of the post-restart channel state. It must fit the
admission ring; the device pins it (stops fetching) and replays it in place, so
the wrap needs no foreground read and cannot underrun. Rejections: a cycle that
advances no ticks (a restart that stops again immediately) is a **zero-time
cycle**; a traversal that does not become periodic within the tick cap is a
**traversal-cycle** failure; the loop region must fit the ring; an **all-gap-0
loop region** is rejected by `fx_stream_validate` (replay would stay in the
same-tick chain and never yield a tick); `SET_LOOP_PATTERN` operand 0 is a legal
target, 255 and out-of-range targets are rejected.

The encoder reproduces the original restart exactly: the same stack frame, delay
0, re-armed, with the frame pattern index left stale (the documented quirk). The
decoder corresponds record-for-record, so a same-tick extra pass advances live
effect state exactly as the original's second `process_channel` pass. The
same-tick chain is bounded at one loop-region wrap per tick (a validated region
always contains a non-zero gap, so its replay returns before a second wrap): a
second wrap sets the sticky format error and stops, so crafted bytes cannot hang
the device. `tests/fx_pack/fx_loop_selftest.c` regresses the validator rejection
(hand-built all-gap-0 stream) and the device bound (same bytes fed straight to
the decoder: error, stop, no hang).

### New original-engine traces and compact equivalence

Three fixtures under `research/fx/fx_compact_spike/loops/` are traced with the
*unmodified* library core (`orig_trace.c`, the same timer-shim contract as the
hlh.1 reference trace) and with the compact loop decoder (`compact_trace.c`,
`ATM_HAS_FX_COMPACT=1`, `ATM_FX_COMPACT_LOOP=1`):

* `sync` - two channels looping on periods 4 and 6; the original only restarts
  when *every* channel has stopped, so they re-synchronize.
* `target` - the loop target changes 1 -> 0 -> 1, exercising the pattern-0
  quirk path.
* `extrapass` - a volume slide left running across the loop boundary, so the
  all-stopped tick's extra pass advances live effect state.

`research/fx/fx_compact_spike/loops/run-loops.sh` converts each score with
`fx_pack --loops` and diffs 96 music ticks, dropping only the traversal-only
columns `cN_ps`, `cN_delay`, `cN_lp` (the compact backend resolves traversal and
loop targets offline; no effect, oscillator, tempo or active-channel column is
dropped). All three: **MATCH**, zero underruns, deterministic. Hashes are in
`build/fx-port/loops/{sync,target,extrapass}.{equivalence.txt,orig.csv,compact.csv}`.

### Intro/loop demo

`build/fx-port/loops/demo-summary.txt`: the `extrapass` compact trace runs 200
ticks with `underruns=0`, `error=0`, `active=1` (never stops); `intro_ticks=8`,
`cycle_ticks=4`, and the first and second loop cycles are byte-identical
(behavioral columns). The demo makes no claim about resetting live synth state:
the loop carries the running slide exactly as the original does.

### Device verification (absim)

`build/fx-port/loops/avr-loop_dg` (12 s run, 52 fps, FX address above
`0x010000`, one foreground service per frame), loop fixture stream pinned in the
32-byte ring:

```
FCDIAG ticks=247 underruns=0 max_gap=1 max_record=13 max_window=13 error=0 stop_tick=0 serviced=520 frames=520
min_stack=0x0aa8 headroom_bytes=1077
```

`stop_tick=0` (a loop never stops), zero underruns, 1077 B stack headroom. The
run is pinned to the freshly built image (`elf_sha256=28b77e86…`, asserted
before the emulator starts), and two consecutive frozen lane reruns reproduce
`run-loops.log` byte-for-byte.

### AVR sizes

Same shell, `avr-size`:

| variant | program | .text | .data | .bss | SRAM | stream | ELF sha (head) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| finite compact (control) | 7880 | 7842 | 38 | 1319 | 1357 | 1572 B | `4e97d8477a1dfef1` |
| loop-capable (`ATM_FX_COMPACT_LOOP=1`, ring 32) | 8554 | 8516 | 38 | 1338 | 1376 | 40 B | `0378c846065268a5` |
| loop-capable + DIAG | 9430 | 9388 | 42 | 1353 | 1395 | 40 B | `28b77e863fa598df` |

Loop support costs **+674 B program / +19 B static SRAM** over the finite
compact control. It is gated by `ATM_FX_COMPACT_LOOP` (default 0): the default
library build is unchanged, and the hlh.1 music fixture rebuilt with no FX
macros is **byte-identical** in `.text` to the retained ELF
(`build/fx-port/loops/default_regression.txt`).

### Not claimed

Streaming loop wraps (a loop region that does not fit the ring) are rejected by
the hlh.8 decoder. The authoring adapter `ATMlib2FX-3ii.3` still exports finite
v1 only; the loop extension is documented here for a later adapter. Game fit
remains hlh.11.

> **Superseded by hlh.16** for the streaming-wrap sentence; see the next section.


## hlh.16: streaming loops for regions larger than the ring (2026-10-18)

Decision bead: `ATMlib2FX-hlh.16`. It removes the hlh.8 restriction that a
`0xC1` loop region must fit the ring. The pinned record framing is unchanged; the
only change is where the wrap is performed.

* **Acceptance.** `atm_fx_compact_play` accepts a loop region up to
  `ATM_FX_COMPACT_LOOP_MAX_REGION` (default `0xFFFF`, the uint16 region counter).
  A region `<= ATM_FX_COMPACT_RING` keeps the hlh.8 pinned path (resident replay,
  no further fetch, bit-for-bit identical). A larger region sets the
  `loop_streaming` state and is streamed.
* **Streaming wrap.** The wrap belongs to the **foreground producer**
  (`atm_fx_compact_fill`): when the fetch position reaches the trailing END byte
  it re-points to `loop_start` and keeps pre-filling. The END byte is never
  written to the ring, so the timer consumer only ever sees loop records and the
  same-tick restart semantics are exactly the pinned ones (all-stopped sync,
  per-record restart mask bits 4..7, effect-only extra passes with gap 0). The
  first loop record is therefore applied on the same tick as the all-stopped
  pass, as in the original engine.
* **Failure accounting.** An unprefillable wrap (foreground starved while the
  consumer catches up) is an **underrun**: the consumer freezes, effect/tick
  state does not advance, and `underruns` increments — never a skipped tick. An
  END byte reaching the timer in streaming mode, a region above the bound, or an
  oversize record is a sticky format/oversize error that stops the player.
* **Gating.** All new code/SRAM is inside `ATM_FX_COMPACT_LOOP`; the streaming
  block additionally has `ATM_FX_COMPACT_LOOP_STREAMING` (default =
  `ATM_FX_COMPACT_LOOP`, used to measure the footprint delta). The default build
  is unchanged.
* **Adapter.** `tools/music_authoring/fx_backend.py` gains a capability switch
  (`build --streaming-loops`, `serialize_compact(streaming_loops=True)`). Off by
  default: a large region still falls back to the finite `0xC0` stream with
  `LOOP_NOT_EXPORTED`, byte-stable. On, the same `0xC1` framing is exported for a
  region up to the bound; above the bound it is a source-pointed `LIMIT_EXCEEDED`
  on `/loop`. The exporter also preflights that each record and each same-tick
  pass chain fits the ring.
* **Compatibility.** A large-region stream fed to a pre-hlh.16 (or
  `LOOP_STREAMING=0`) decoder is a clean header rejection (format error, stop),
  never garbling. Finite `0xC0` output and the pinned small-region path are
  byte-identical.
* **Evidence.** `build/fx-port/streaming-loop/` — Snapdragon Sprint (region
  4647 B, ring 64) over two loop cycles: host decoder trace byte-identical to the
  unmodified original engine over 6300 ticks; absim `ticks=4179 underruns=0
  error=0 stop_tick=0`, 1042 B stack headroom; streaming delta +138 B program /
  +1 B SRAM over the pinned-only loop build. Same-stream ring 16 (streaming) and
  ring 32 (pinned) traces are byte-identical.
* **Docs owned by hlh.15.** Advertise the new capability/bound and this section
  in the user-facing docs.
