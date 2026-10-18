The finite baseline source is now frozen in [`song.json`](song.json). Historical
source paths below and in goldens record its original example location. The
listening example has since been revised into a musical loop.

# Model music authoring — basic example (ATMlib2FX-3ii.1)

Historical implementation and measurement record for the basic authoring fixture.
Commands below use the relocated paths; versions, measurements and hashes record
the original runs. This document's early implementation status describes those
runs. For current usage, see the
[authoring guide](../../../../docs/music-authoring-guide.md) and
[basic example](../../../../examples/music_authoring/basic/README.md).
The goldens and expected trace live here; required renderer inputs live in
`tools/music_authoring/preview/`.

Strict v1 source contract, canonical host timeline/review payload, and the
deterministic original PROGMEM export for model-authored music. Authoring runs
on the host only; **no AVR runtime is added to `src/`**.

## What is implemented

| Command | Result |
| --- | --- |
| `tools/atm-music capabilities --json` | features, 4 channels, pitch range `C2..D7`, host limits, tool/engine identity, backend availability |
| `tools/atm-music validate <song.json> [--backend progmem] --json` | strict validation + expanded duration/tempo/channel-use report |
| `tools/atm-music build <song.json> --backend progmem --out <dir> --json` | validates, lowers, serializes original PROGMEM bytes + header + review payload + report |

stdout is always one JSON document; logs go to stderr. Exit codes: `0` success,
`2` invalid score / unsupported capability, `3` tool/build failure.

Not implemented here (owned elsewhere, advertised unavailable):
`--backend fx` (ATMlib2FX-3ii.3 / `ATMlib2FX-hlh.2`), HTML/JS viewer
(ATMlib2FX-3ii.6). The canonical review payload these consume is produced here.
Bounded WAV preview is now implemented by ATMlib2FX-3ii.2 (see
[WAV preview](#wav-preview-atmlib2fx-3ii2) below).

Files: `schemas/atmlib-score-v1.schema.json`, `tools/atm-music`,
`tools/music_authoring/{__init__,cli,score,validate,lower,progmem_backend,render}.py`,
`tools/music_authoring/preview/{absim_audio_harness.cpp,build-harness.sh}`,
`tests/music_authoring/{test_score,test_progmem,test_render}.py`.

## Engine behavior: note-off silences; gates still set volume explicitly

`src/cmd_parse.c:trigger_note()` silences on note 0 (`osc.vol = 0`, then
`return`; fixed by ATMlib2FX-mgd, change pending commit) and leaves `osc.mod`
and the channel volume untouched. The compiler still lowers each gate with an
**explicit `SET_VOLUME(0)`**, and each new note is preceded by
`SET_VOLUME(instrument.volume)` (+ `SET_MOD(duty)` on pulse), so generated
programs do not depend on the note-off path.

Timing: `NOTE; DELAY(D); SET_VOLUME(0)` mutes exactly at tick `start+D` (the
engine's `process_channel` loop decrements one tick per callback). Channel 0's
program begins with `SET_TEMPO(tick_rate)` so the requested rate is in effect
from tick 1 (the engine default of 25 Hz governs the very first callback).

## Example: `song.json`

`basic_authoring_v1`: clock `tick_rate=50, ticks_per_beat=25, beats_per_bar=4`
→ effective 50 Hz, 120.0 BPM. Instruments `lead`(pulse,80,127), `bass`(pulse,64,200),
`perc`(noise,90). Patterns `lead_line` (16 ticks, silent span 4..8),
`short` (8 ticks: one-tick gates + adjacent notes), `bassline` (16 ticks),
`percs` (noise). Tracks: pulse0 `lead_line`×2, pulse1 `short`×4, pulse2
`bassline`×1, noise `percs`×2 → **total_ticks = 32**; pulse2 is short (silent
16..32); pulse0 has an adjacent pattern boundary at tick 16.

## Reproduce (repo root; no git operations)

```
python3 -m unittest discover -s tests/music_authoring -p 'test_*.py'

tools/atm-music capabilities --json
tools/atm-music validate examples/music_authoring/basic/song.json --backend progmem --json
tools/atm-music build    examples/music_authoring/basic/song.json --backend progmem \
    --out build/music-authoring/generated --json

tests/music_authoring/fixtures/basic/trace/run-trace.sh          # original-engine host trace

# AVR fixture: generate the header, then compile with the baseline board/toolchain
tools/atm-music build examples/music_authoring/basic/song.json --backend progmem \
    --out build/music-authoring/generated --json
arduino-cli compile --fqbn arduboy-homemade:avr:arduboy-fx --library . \
    --build-path build/music-authoring/avr-build \
    --output-dir build/music-authoring/avr-out \
    --build-property "compiler.cpp.extra_flags=-I$PWD/build/music-authoring/generated" \
    tests/music_authoring/fixtures/basic/avr
```

## Provenance and results (measured on this machine)

| Item | Value |
| --- | --- |
| Repo HEAD | `f16387358a28d43204434019236305c6c8cc5efb` |
| Python | 3.14.7 (stdlib only) |
| arduino-cli | 1.2.0 (Homebrew) |
| AVR toolchain | avr-gcc 7.3.0 (`7.3.0-atmel3.6.1-arduino7`) |
| FQBN | `arduboy-homemade:avr:arduboy-fx` |
| Local ATMlib selected | `/Users/…/ATMlib2FX` version 1.2.4 (not the installed board-package 1.2.6) |

Source identity / determinism:

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `song.json` (input) | 1685 | `a4c43fbf82788b838a3e33d90d747c0372ed05c8bc34d665b27be24afa941c4a` |
| canonical event digest (`atmlib-canonical-events-v1`) | – | `54e5eb30a39f735558dc3fb2850c78a2b3de0fa4418c9a415ee8c7a170a18113` |
| `score.bin` (PROGMEM asset) | 215 | `8ba7c409364dd8f96f572a0b4fc0bb6284448c3ca61076f721e38018afd6c1a1` |
| expected original-engine trace | – | `17c4a78c39a07c30606075de7964cf7119e287d48a520ae771e9da1cf42d0574` |

- `python3 -m unittest discover -s tests/music_authoring -p 'test_*.py'`
  → **38 tests, OK** (validation codes/pointers, encoding boundaries, golden
  bytes/hashes, review payload, capabilities).
- Two `build` runs produce byte-identical `score.bin`, `score.h`, `review.json`.
- `capabilities`/`validate`/`build` exit `0`; invalid pitch exits `2` with
  `PITCH_RANGE` at `/patterns/p/events/0/note`; `--backend fx` exits `2` with
  `BACKEND_UNAVAILABLE`; missing file exits `3` with `IO_ERROR`.

### Original-engine trace (`trace/expected_trace.csv`)

`trace/run-trace.sh` compiles the **unmodified** `src/atm_synth.c` (+ its
included `src/cmd_parse.c`) for the host, substituting only the `osc.c` timer
layer (2000 Hz base, `preset = 2000/rate − 1`), and plays the generated
`score.h`. One row per channel per completed music callback. Observed:

- **All channels start at tick 1 with no extra delay** (pulse0 note 25/C4,
  pulse1 note 37/C5, pulse2 note 13/C3, noise note 10/A2; tempo 50).
- **One-tick gates**: pulse1 C5 audible at tick 1 only, D5 at tick 2 only.
- **Adjacency**: pulse1 C5→D5 adjacent; pattern boundary at tick 17 (pulse0 rep0
  G4 → rep1 C4) with no extra tick.
- **Silent spans**: pulse0 silent 4..8 each repetition.
- **Short channel**: pulse2 stops after tick 16 (`delay 0xffff`, active bit 2
  clears `0xf0→0xb0`).
- **End muting**: at tick 33 every channel shows `vol 0`, `delay 0xffff`,
  `active 0x00`.
- **Determinism**: two runs byte-identical; matches the committed fixture.

### AVR fixture (`avr/avr.ino`)

`arduino-cli` build succeeds against `arduboy-homemade:avr:arduboy-fx`; the
local repo ATMlib is selected (`Using library ATMlib at version 1.2.4`,
installed 1.2.6 skipped).

- `avr-size`: **Program 6454 bytes**, **Data 332 bytes** (`.data+.bss`).
- `avr-nm`: `score` = **215 bytes** (flash), matching `score.bin`.

These are the **minimal fixture sketch** numbers (core + ATMlib + score), not a
whole-game measurement and **not** engine-memory deltas; `score.bin` is a song
asset byte count only. The footprint baseline
(`research/fx/fx-footprint-results.md`) remains the engine-cost reference and was not
overwritten.

## WAV preview (ATMlib2FX-3ii.2)

`tools/atm-music render` produces a **bounded, faithful WAV** by executing an
*actual* AVR image (the unmodified PROGMEM library + the generated score) under
the local absim emulator core and capturing the emulator's real PCM sample
stream. No sine/MIDI/hand-written oscillator substitute is used. Authoring still
adds nothing to `src/`.

```
tools/atm-music render examples/music_authoring/basic/song.json \
    --backend progmem --seconds 8 --out build/music-authoring/preview --json

tools/atm-music render tests/music_authoring/fixtures/basic/isolated.json \
    --backend progmem --seconds 8 --out build/music-authoring/preview-isolated --json
```

stdout is one JSON report; logs go to stderr. Exit codes match the other
commands (`0` ok, `2` invalid/unsupported, `3` tool/render failure). The render
window is `min(--seconds, song + 0.5 s tail)`, default cap 60 s, hard cap 300 s;
`--seconds > 300` is rejected with `DURATION_CAP`, and a window shorter than the
song sets `render.truncated` with a reason.

### capture facts (from the local Ardens sources, read-only)

| Item | Value | Source |
| --- | --- | --- |
| audio API | `core_state.cpu.sound_buffer` (int16 PCM mono) | `ardens/src/absim_sound.hpp` |
| sample rate | `16'000'000 / SOUND_CYCLES(320)` = **50'000 Hz** | `absim.hpp`, `common.hpp` |
| neutral DC | **0** (silence), gain 2000 | `absim_sound.hpp` |
| output enable | speaker pins DDRC6/DDRC7 + Timer4 PWM | `Arduboy2Audio::on()`, `osc.c` |
| noise seed | `osc_params_array[3].phase_increment = 1` at setup | `src/osc.c:osc_reset` |

The first music callback is **measured** (absim non-step PC breakpoint on the
engine's `osc_tick_handler`, located with `avr-nm`), never inferred.

### measured results (this machine)

| Artifact | Value |
| --- | --- |
| `basic` WAV | `build/music-authoring/preview/preview.wav` |
| `basic` WAV sha256 | `3dda695e0e70644d861325839b4628c067e9da20f0a4c509325bee130c7bb2c4` |
| `basic` sample count / rate | 56 895 / 50 000 Hz (32 ticks + 0.5 s tail) |
| `basic` first music callback | sample **1045** (0.0209 s) — measured |
| `basic` peak / min | +1232 / −2000 |
| `basic` in-song silence level | **2** (gap ticks 21..24, steady zero-AC) |
| `basic` end state | constant DC rail −2000 (zero AC), PWM stopped |
| `basic` tick trace sha | `17c4a78c39a07c30606075de7964cf7119e287d48a520ae771e9da1cf42d0574` (matches the committed golden) |
| `isolated` WAV sha / samples | `beeaeccfc3cdbed136aef9fe3c4f7f8238aee752bd55219d998c3f34c1141f54` / 64 895 |
| `isolated` noise repeatability | noise A2 at ticks 24 and 32 → identical sample sha `5b064ed5ffe0ae6f` |
| cost (production) | `score.bin` = 215 bytes (asset only) |
| cost (instrumented) | preview ELF program 6460 / data 332 bytes — **not** a production cost |

Evidence captured from real audio: all four channels (basic, mixed); pulse duty
(steady AC 782 on pulse gates); one-tick gates (`isolated` C5/D5 at ticks 8/9);
noise hits (`isolated` channel 3); **neutral-level silence** in gaps
(`basic` 21..24, `isolated` 4..8/13..24/26..32 → steady AC 0); end-muted state;
and deterministic **repeatability** (two renders → identical WAV sha; the two
isolated noise hits are sample-identical).

Viewer-synchronisation fields (for ATMlib2FX-3ii.6) are in the report:
`audio.first_music_callback_sample`/`_seconds`, `audio.sample_rate`, `format`,
`sample_count`, `render.rendered_ticks`, `render.total_ticks`, matching
`source.sha256` / `event_digest`, and per-note/gate `analysis.note_windows` /
`analysis.gate_regions`.

Honest limitations: the emulated speaker mix is mono, so per-channel isolation
is not possible from one WAV (channel ordering is covered by the tick trace and
the time-isolated fixture). While PWM runs the emulated neutral is 0 plus a small
DC-quantization offset (measured silence = 2); after the score ends the engine
stops PWM and the capture is a constant DC rail (~−2000, zero AC). Both are
acoustically silent but not equal to 0. `capabilities` still reports render
unavailable because ATMlib2FX-3ii.1 pinned that payload in the `review.json`
golden; the render command reports its own availability.

## Gaps / honest limitations

- FX backend and the HTML/JS viewer are **not** available here (bounded WAV
  preview is now provided by ATMlib2FX-3ii.2, above).
- ATMlib2FX-3ii.1 captured no audio; its timing/gate evidence is the
  deterministic host trace of the original engine. ATMlib2FX-3ii.2 adds real
  absim audio capture and this README's preview section records it.
- The example exercises small delays; U16 delay/offset paths are covered by unit
  tests, not by an AVR run.
- Two latent bugs in the initial generator were found by this evidence and
  fixed: pattern offsets were serialized big-endian (engine `pgm_read_word`
  reads little-endian), and JSON-Pointer construction double-escaped appended
  path segments.
