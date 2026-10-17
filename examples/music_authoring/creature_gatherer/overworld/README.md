# Creature Gatherer FX — Overworld: “Gatherer’s Road” (ATMlib2FX-3ii.11)

## Current revision — 2026-10-17 (ATMlib2FX-awr)

Brisk roaming theme; chord-tone bass under the minor-sixth motif and an E pickup into the opening.

**A minor · 136.36 BPM · 16 bars · 1408 ticks · 28.16 s per loop.**
The source sets `"loop": true`; the original PROGMEM engine restarts all tracks
on the same callback. The [review](review.html) defaults **Loop** on and repeats
one cycle with measured startup and capture tail excluded from playback.

Current [WAV](preview/preview.wav) and [render report](preview/preview.json) were
regenerated from this source through AVR/absim; the capture includes a cycle
plus 0.5 s of the next iteration. PROGMEM asset: **2202 B**.
WAV SHA-256: `ef7cbf797fbd498371c4052b7ba953d6d00517f2e7209aa1c9afaae801995d0a`.

[All-song player](../../player.html) · [source](song.json) · [canonical review](review.json).

## Historical first-version notes

The descriptions, numbers and captured paths below record the original finite
composition. Current timing, looping and media are described above. These
notes retain their original provenance; linked working assets now use the
current revision.

Candidate original cue for the Creature Gatherer FX *overworld / field* state. This
is a **model-authored composition**, not integrated FX music and not a production
asset: there is no FX export/ABI yet, so it is compiled only through the `progmem`
backend and labelled a candidate. It is **not** copied from, transposed from or
imitated after any existing song; inputs were this repository’s own CLI and the
published `docs/music-authoring-interface.md` contract.

- **Source:** [`song.json`](song.json)
- **Offline review (embedded audio):** [`review.html`](review.html) — open directly in a browser, no server/build needed
- **Canonical viewer payload:** [`review.json`](review.json)
- **Suite index:** [`../README.md`](../README.md)

## Intended game context

Warm, optimistic field theme for roaming the gathering overworld, moving between
gathering spots and lure zones. Bright but not frantic, with forward motion from
the bass and drums so it can sit under exploration without dominating.

## Musical form

- **Key:** A natural minor (Aeolian). **Meter:** 4/4. **Length:** 16 bars = 1600 ticks.
- **Effective BPM:** 120.0 (requested `tick_rate` 50 → integer effective 50 Hz;
  `ticks_per_beat` 25, `beats_per_bar` 4). One bar = 100 ticks.
- **Duration:** 32.0 s of score; render captures 32.5 s (song + 0.5 s tail).
- **Shared motif (“the Seed”):** the suite motif is an ascending tonic-triad
  outline with a lift to the 6th — scale degrees **1–3–5–6**, rhythm long–short–
  short–long. In this cue the minor form **A–C–E–F** states the theme, then is
  developed and answered across the form. The same contour reappears as the
  major form (C–E–G–A) on the bridge, and as its retrograde in the defeat cue.
- **Form (A A′ B A″):**

  | Bars | Section | Chord per bar | Note |
  | --- | --- | --- | --- |
  | 1–8 | A | Am F C G / Am F C G | motif stated, then answered and varied (`L1`–`L4`) |
  | 9–12 | B (contrast) | C G Am F | brighter, higher register, off-beat arpeggios (`L5`,`L6`) |
  | 13–16 | A″ (return) | Am F E Am | motif returns; V→i cadence, final A5 held, ~1 bar tail of silence (`L7`,`L8`) |

- **Channel roles** (fixed physical channels, each monophonic, gates never overlap):

  | Channel | Instrument | Role |
  | --- | --- | --- |
  | `pulse0` | `lead` (pulse, v90, duty 128) | melodic motif and development |
  | `pulse1` | `harm` (pulse, v50, duty 64) | arpeggiated harmony support |
  | `pulse2` | `bass` (pulse, v74, duty 200) | roots on beats 1 & 3; driving 8ths in the bridge |
  | `noise` | `perc` (noise, v58) | kick/backbeat pattern with fills at bars 8, 12, 16 |

- **Transitions & cadence:** percussion fills at bars 8/12/16 mark section joints;
  the bridge switches the bass from half-note roots to driving 8ths for contrast;
  bar 15 lands on E (V, with `G#5`) and bar 16 resolves to Am with a long `A5`
  and trailing silence.
- **Loop-friendliness:** the final bar is a clear tonic return and could later
  support a loop point, but the compiler/renderer are **finite**; no runtime looping
  is claimed or produced.

## Pattern reuse (finite, size-conscious)

48 pattern instances expand from 23 source patterns. Melody uses eight 2-bar
phrases (the theme needs variety); harmony reuses `HA`/`HB` across the A section
and `HB` in the bridge; bass reuses 1-bar chord patterns (`BAm`,`BF`,`BC`,`BG`)
and changes only in the bridge (8th-note `BA8/BC8/BG8/BF8`); percussion reuses a
single `beat` bar seven times and `fill` as a section marker. Repetition is finite
(`repeat` 1–7); no brute-force unique expanded patterns.

## Reproduction (run from the repository root)

```
tools/atm-music validate examples/music_authoring/creature_gatherer/overworld/song.json --backend progmem --json
tools/atm-music build    examples/music_authoring/creature_gatherer/overworld/song.json --backend progmem \
    --out build/music-authoring/creature_gatherer/overworld/build --json
tools/atm-music render   examples/music_authoring/creature_gatherer/overworld/song.json --backend progmem \
    --seconds 40 --out build/music-authoring/creature_gatherer/overworld/preview --json
tools/atm-music inspect  examples/music_authoring/creature_gatherer/overworld/song.json \
    --audio-preview build/music-authoring/creature_gatherer/overworld/preview \
    --out examples/music_authoring/creature_gatherer/overworld/review.html --json
```

## Measured results (this machine)

Tool `atm-music` 1.0.0, engine ATMlib 1.2.4, backend `progmem`
(`ATM_SCORE_FMT_FULL`). All commands exited `0`.

| Quantity | Value |
| --- | --- |
| Validation | `ok:true`; 4/4 channels; 48 pattern instances; **253** expanded note events; features `notes, rests, finite_pattern_reuse, finite_arrangement, pulse_duty, noise_percussion, fixed_instrument_volume, explicit_gate_mute` |
| Clock | requested 50 → effective **50 Hz**, 120.0 BPM, 1600 ticks / 32.0 s |
| `song.json` | 15618 B, sha256 `43aea1283e8eda2e68e7ff2ca59412bbb537762213d11c046f25511fb1f2d3d9` |
| canonical event digest | `7ed41805e93b7e0ff769055ab5959afd22d8e893c2fbe3d0b832e25b2e78c582` |
| `score.bin` (PROGMEM asset) | **2175 B**, sha256 `f70552ed256c8a0e9cd86e7193d3c2b3b44a1be190de991869ee5d4f0b4c0f4d`; per-channel `program_bytes` `[679, 577, 385, 519]` |
| `review.json` | 98074 B, sha256 `299a4181ec1304b2153134c58f4a49794ae5b2bf23789b59e4fb4b16de9d9025` (byte-identical to the build’s `review.json`) |
| `review.html` | 4448109 B, sha256 `0e3fdd57d8de043338b912099ec1d60f1e5850bb4407b292730d742db37c3dc9` |
| `preview.wav` | 3249834 B, sha256 `3b8e4e9400f43a7a9afa39c02a7612a533d32e0ab5e6720106ee12184a242422`; `pcm-s16le-mono` 50000 Hz, 1624895 samples = 32.4979 s |
| Render window | requested 40.0 s → effective 32.5 s (32.0 song + 0.5 tail), `truncated:false`, 1600/1600 ticks |
| First music callback | sample 1045 (0.0209 s), measured by absim PC breakpoint |
| Embedded audio match | `review.html` embeds the WAV above (`wav_sha256` matches); source + event digests matched at inspect time |

`score.bin` is PROGMEM **song asset data only** — not engine code, not static SRAM,
not a whole-game footprint. The build command does not invoke `arduino-cli`, so no
AVR image measurement is reported.

## Audio limitations (read honestly)

- The WAV is the emulated **mono speaker mix**; a single file cannot isolate one
  channel. Lane checkboxes in the viewer are visibility only and never change audio.
- The offline viewer exposes **Raw emulator** (default) and **Piezo (approx.)**.
  Piezo is an **uncalibrated** browser-only coloration and is **not** a measured
  Arduboy piezo/enclosure response or a loudness prediction. Check final sound on
  device.
- `tick_rate` is a timer request; BPM is the derived quantized value. After the
  score ends the stopped PWM leaves a constant DC rail (≈ −2000, zero AC),
  acoustically silent rather than neutral 0.
- Sound-quality judgement is the listener’s job; the numeric evidence here proves
  gates, timing, silence, digests and determinism, not taste.

## Limitations / status

- **No FX export, no FX integration.** `--backend fx` is unavailable
  (`BACKEND_UNAVAILABLE`, pending ATMlib2FX-hlh.2 / 3ii.3). This is a candidate
  progmem composition only.
- No external code or music was cloned, fetched, downloaded, vendored or copied.
- Intermediate build caches for this cue live only under the excluded
  `build/music-authoring/creature_gatherer/overworld/`.
