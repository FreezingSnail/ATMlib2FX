# Model music authoring — showcase piece (ATMlib2FX-3ii.7)

## Current revision — 2026-10-17 (ATMlib2FX-awr)

Four-channel demonstration; softened long seconds/sevenths against the bass.

**A minor · 125.00 BPM · 4 bars · 384 ticks · 7.68 s per loop.**
The source sets `"loop": true`; the original PROGMEM engine restarts all tracks
on the same callback. The [review](review.html) defaults **Loop** on and repeats
one cycle with measured startup and capture tail excluded from playback.

Current [WAV](preview/preview.wav) and [render report](preview/preview.json) were
regenerated from this source through AVR/absim; the capture includes a cycle
plus 0.5 s of the next iteration. PROGMEM asset: **406 B**.
WAV SHA-256: `290b9fb7f47c234c1cb15077de7d131209afbe42cb4d9a699dd542a315d2a44e`.

[All-song player](../player.html) · [source](song.json) · [canonical review](review.json).

## Historical first-version notes

The descriptions, numbers and captured paths below record the original finite
composition. Current timing, looping and media are described above. These
notes retain their original provenance; linked working assets now use the
current revision.

An original, newly composed four-channel piece that demonstrates the v1
`atmlib-score` source, the `atm-music` CLI (validate → build → real AVR WAV
render) and a small, finite musical form suitable for the offline track viewer.

- **Song source:** `examples/music_authoring/showcase/song.json`
- **This file:** `examples/music_authoring/showcase/README.md`
- **Open locally:** [standalone track viewer with embedded audio](review.html)
- **Canonical viewer payload:** [review.json](review.json)
- **Recorded browser evidence:** [piezo verification](../../../research/music-authoring/piezo/SUMMARY.md)
- **Generated outputs (git-ignored):**
  `build/music-authoring/showcase/build/` and
  `build/music-authoring/showcase/preview/`

Authoring runs on the host only. Nothing here adds AVR runtime code to `src/`,
and no FX export is produced. The source, standalone viewer, canonical review
payload and matching `preview/` media live here. Recorded browser evidence lives
under `research/music-authoring/piezo/`; intermediate exports and renders go under
`build/`.

## Provenance and originality

This piece was **composed from scratch for this example**. It is not copied from,
transposed from, or imitated after any existing song. No external code or music
was cloned, fetched, downloaded, vendored or copied from Joeri/JO3RI/TEAM a.r.g./
T-arg/ATMlib or any other source; the only inputs are this repository's existing
CLI tools and the published `docs/music-authoring-interface.md` contract. The
melody, harmony, bass line and noise rhythm below were written for this task.

## Musical form

- **Key:** A natural minor. **Meter:** 4/4. **Length:** 4 bars = 400 ticks.
- **Progression (one chord per bar):** Am | F | Dm | Am (i–VI–iv–i), ending on
  the tonic so the final bar is a clear cadence; the last ~5 ticks are silent.
- **Instrument identities** (host-side presets, not extra hardware voices):

  | Instrument | Voice  | Volume | Duty | Role                          |
  | ---------- | ------ | -----: | ---: | ----------------------------- |
  | `lead`     | pulse  |     90 |  128 | melodic motif                 |
  | `harm`     | pulse  |     58 |   64 | sparse chord/harmony tones    |
  | `bass`     | pulse  |     72 |  200 | bass roots                    |
  | `perc`     | noise  |     60 |    – | restrained noise rhythm       |

- **Channels** (`song.json` track keys): `pulse0` = lead, `pulse1` = harmony,
  `pulse2` = bass, `noise` = percussion. Every pattern is monophonic; there is no
  polyphony within a physical channel, and gates never overlap on a lane.

### Bar-by-bar / channel roles

| Bar (ticks) | Chord | `pulse0` lead                                | `pulse1` harmony       | `pulse2` bass      | `noise` perc          |
| ----------- | ----- | -------------------------------------------- | ---------------------- | ------------------ | --------------------- |
| 1 (0–99)    | Am    | E5 A4 C5 B4                                   | E4 (beat 2), C4 (beat 4) | A2 (beats 1 & 3)   | C3 (beats 2 & 4)      |
| 2 (100–199) | F     | A4 C5 D5 E5                                   | A3, C4                 | F2                 | C3                    |
| 3 (200–299) | Dm    | D5 F5 A5 G5                                   | D4, A3                 | D2                 | C3                    |
| 4 (300–399) | Am    | E5 C5 B4 → A4 (resolves to tonic)             | E4, A3                 | A2                 | C3, C5, C3 (fill)     |

- **Pattern layout (finite reuse):** melody, harmony and bass each use two
  2-bar patterns (`lead_a`/`lead_b`, `harm_a`/`harm_b`, `bass_a`/`bass_b`,
  each `repeat: 1`). Percussion uses a 1-bar `beat` pattern with `repeat: 3`
  followed by a 1-bar `fill`, so the same pattern is reused and a visible
  pattern boundary falls at bar 3 → bar 4.
- **Rests / gaps:** each bass bar is a 45-tick gate followed by 5 silent ticks,
  so the render shows regular silent gaps on every 50-tick cycle; the entire
  final 5 ticks (395–400) are silent on all lanes and the engine mutes every
  channel at end of song.
- **Noise note tokens** (`C3`, `C5`) are the engine's noise frequency/seed
  control, not pitched percussion — they are documented as such and are not a
  promise of melody.
- **Range:** every pitch token lies inside the engine range `C2..D7` (this song
  uses `D2`–`A5`).

## Commands (run from the repository root)

```
# 1. validate the source against the progmem backend
tools/atm-music validate examples/music_authoring/showcase/song.json --backend progmem --json

# 2. deterministic PROGMEM export (score.bin / score.h / review.json / report.json)
tools/atm-music build examples/music_authoring/showcase/song.json --backend progmem \
    --out build/music-authoring/showcase/build --json

# 3. bounded, faithful WAV preview from a real AVR image (absim capture)
tools/atm-music render examples/music_authoring/showcase/song.json --backend progmem \
    --seconds 12 --out build/music-authoring/showcase/preview --json

# 4. tool test suite (unchanged by this example)
python3 -m unittest discover -s tests/music_authoring -p 'test_*.py'
```

stdout is a single JSON document; human logs go to stderr. Exit codes: `0`
success, `2` invalid score / unsupported capability, `3` tool/build/render
failure.

## Recorded results (measured on this machine)

Environment: Python 3.14.7 (stdlib only), `arduino-cli` 1.2.0, AVR toolchain
`avr-gcc 7.3.0`, FQBN `arduboy-homemade:avr:arduboy-fx`, local Ardens emulator
tree, local ATMlib `1.2.4`.

### Clock

| Field | Value |
| --- | --- |
| requested `tick_rate` | 50 |
| effective tick rate | 50 Hz (timer-quantized: `2000 / floor(2000 / 50)`) |
| `ticks_per_beat` / `beats_per_bar` | 25 / 4 |
| **effective BPM** | **120.0** |
| total ticks / duration | 400 ticks / **8.0 s** |

### Source / event identity

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `song.json` (input) | 4170 | `636cd3b0f0e458e2a4357144b58b7a09056c96d3bbe0dd190b9c2772c5ba7936` |
| canonical event digest (`atmlib-canonical-events-v1`) | – | `e4b1a95aee458c78f80118400754e9eca1b9ba6832368c16a2e61ce03d53c90e` |

Validation summary: 4/4 channels used; 10 pattern instances; 41 expanded note
events; required features `notes, rests, finite_pattern_reuse,
finite_arrangement, pulse_duty, noise_percussion, fixed_instrument_volume,
explicit_gate_mute`; `ok: true`, exit `0`.

### Build assets (`--out build/music-authoring/showcase/build`)

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `score.bin` (PROGMEM asset) | 395 | `5a89dbde291ab9f1182a3d8cb0737737b1680edc654d36704b5f63b9e9935981` |
| `score.h` | – | `46f0897eb4cf9a9e47b81bb56aa5071ef030233f0b3558592caad1ec25958709` |
| `review.json` (viewer payload) | – | `db74d2fe8811d97c529da30da475dab54a81bdd6ad9fa7f756217b79f64be41a` |
| `report.json` | – | `0f25ef913496d2f2499d2adc41bc21d71c116f4f9400723c061c98c11fc1e3c2` |

`score.bin` is PROGMEM **song asset data only** (per-channel program bytes
`[147, 81, 81, 71]`), not engine code, not SRAM and not a whole-game footprint.
`channel_pattern_entries` are `[0, 1, 2, 3]`. The build command does not invoke
`arduino-cli`, so it reports no AVR image measurement.

### WAV preview (`--out build/music-authoring/showcase/preview`)

| Field | Value |
| --- | --- |
| `preview.wav` | 849834 bytes, SHA-256 `68768532bd638a8537c8e513f126f471f46a6da7636d8b3b2032e2594cbc78f6` |
| format | `pcm-s16le-mono`, 50000 Hz, 16-bit |
| samples / duration | 424895 / **8.4979 s** |
| render window | requested 12.0 s → effective 8.5 s (song 8.0 s + 0.5 s tail), `truncated: false`, rendered 400/400 ticks |
| first music callback | sample **1045** (0.0209 s) — measured via absim PC breakpoint |
| min / max sample | −2000 / 1098 (peak abs 2000) |
| gate regions / note windows | 16 / 41 (one window per expanded note) |
| in-song measured silence level | 2 (steady, zero AC) |
| end state | constant DC rail −2000 (zero AC); PWM stopped after the score |
| report | `build/music-authoring/showcase/preview/preview.json` |
| tick trace | `build/music-authoring/showcase/preview/tick_trace.csv` |

The capture is the emulated **mono speaker mix** (DDRC6/7 differential); a single
WAV cannot isolate one channel. Channel assignment is evidenced by the
`note_windows` (per-note channel/pitch/instrument) and the tick trace, and the
final silent tick range 395–400 confirms the end-with-silence cadence.

**Determinism:** two independent `build` runs produced a byte-identical
`score.bin` (same SHA-256), and two independent `render` runs produced a
byte-identical `preview.wav` (same SHA-256).

The instrumented preview fixture built for capture measured program 6640 / data
332 bytes. This is an instrumented fixture (core + ATMlib + score + speaker
enable), **not** a production or whole-game cost.

### Test suite

`python3 -m unittest discover -s tests/music_authoring -p 'test_*.py'`
→ **61 tests, OK (skipped=1)**. This example changes no `tools/` code.

## `capabilities` matches the working render command

`tools/atm-music capabilities --json` reports

```
"render": { "available": true }
```

matching the `render` subcommand, which reports
`"capabilities": {"render": {"available": true}}`. The ATMlib2FX-3ii.1 golden
fixtures keep their byte-stable embedded capabilities block, so the fix lives in
the tool and changes no frozen payload. **This example changes no `tools/` code**;
the discrepancy is recorded here for continuity.

## Scope and limitations

- **No FX export exists.** Only `--backend progmem` (build) and the real WAV
  preview are produced; `--backend fx` correctly reports `BACKEND_UNAVAILABLE`.
- **Offline viewer included.** [review.html](review.html) embeds the matching
  WAV and needs no build directory or server. Its source/event digests and
  embedded WAV match this README's artifacts. A Chrome 155 walkthrough verified
  playback, profile switching, seek/restart, raw fallback and offline loading;
  see [recorded evidence](../../../research/music-authoring/piezo/SUMMARY.md). This was a headless check,
  not a listening test on hardware.
- Audio is the mono emulated speaker mix; per-channel isolation is not possible
  from one WAV. After the score ends, the stopped PWM leaves a constant DC rail
  (~−2000, zero AC) rather than neutral 0; both are acoustically silent.
- `tick_rate` is a timer request; the reported BPM is the quantized effective
  value (`effective_tick_rate * 60 / ticks_per_beat`), not a stored tempo.
- `review.html` and `review.json` are generated snapshots kept beside the song.
  Regenerate them after source or viewer changes. Compiler caches and duplicate
  experiment outputs have been removed; compact WAV/report/trace and ELF
  evidence remains under the git-ignored `build/music-authoring/showcase/`.

## Open in the offline HTML track viewer

Open [review.html](review.html) directly in a browser. The adjacent JSON is for
inspection by tools; the HTML does not load it or any other external file.

To regenerate both durable snapshots from the repository root, render the
matching WAV (this also works after deleting the build directory), then inspect:

```
tools/atm-music render examples/music_authoring/showcase/song.json --backend progmem \
  --seconds 12 --out build/music-authoring/showcase/preview --json
tools/atm-music inspect examples/music_authoring/showcase/song.json \
  --audio-preview build/music-authoring/showcase/preview \
  --out examples/music_authoring/showcase/review.html --json
```

This completed successfully for the current artifacts. It reports four used
channels, 41 note events across 10 pattern instances, matching source and event
digests, and the 400-tick 120 BPM clock. The output HTML embeds the matching
849,834-byte WAV; its size varies with the viewer assets. The Sound selector
offers Raw emulator and Piezo (approx.) for an uncalibrated speaker preview. Open
`examples/music_authoring/showcase/review.html` locally to inspect it; the
review command does not write or flash FX data.
