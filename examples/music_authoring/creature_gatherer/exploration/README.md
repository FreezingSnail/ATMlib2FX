# Creature Gatherer FX — Cave / Exploration: “Hollow Depths” (ATMlib2FX-3ii.11)

## Current revision — 2026-10-17 (ATMlib2FX-awr)

Spacious cave theme; slower phrases and open harmony, with a quiet pickup instead of a terminal hold.

**A minor · 83.33 BPM · 12 bars · 1728 ticks · 34.56 s per loop.**
The source sets `"loop": true`; the original PROGMEM engine restarts all tracks
on the same callback. The [review](review.html) defaults **Loop** on and repeats
one cycle with measured startup and capture tail excluded from playback.

Current [WAV](preview/preview.wav) and [render report](preview/preview.json) were
regenerated from this source through AVR/absim; the capture includes a cycle
plus 0.5 s of the next iteration. PROGMEM asset: **756 B**.
WAV SHA-256: `92e9b70cca050bb97d21f3d7a248f385663940d1dfd347cc3e0491501301f90b`.

[All-song player](../../player.html) · [source](song.json) · [canonical review](review.json).

## Historical first-version notes

The descriptions, numbers and captured paths below record the original finite
composition. Current timing, looping and media are described above. These
notes retain their original provenance; linked working assets now use the
current revision.

Candidate original cue for the Creature Gatherer FX *cave / gathering-exploration*
state. **Model-authored composition**, compiled only through `progmem`; not
integrated FX music, not a production asset. **Not** copied/transposed/imitated.

- **Source:** [`song.json`](song.json)
- **Offline review (embedded audio):** [`review.html`](review.html)
- **Canonical viewer payload:** [`review.json`](review.json)
- **Suite index:** [`../README.md`](../README.md)

## Intended game context

Sparse, low, atmospheric bed for cave and quiet gathering stretches — long tones,
slow harmonic movement and occasional noise “drips”, leaving room for ambience.

## Musical form

- **Key:** A natural minor. **Meter:** 4/4. **Length:** 12 bars = 1200 ticks.
- **Effective BPM:** 120.0 (requested `tick_rate` 50 → integer effective 50 Hz;
  `ticks_per_beat` 25, `beats_per_bar` 4). One bar = 100 ticks. Slowness comes
  from long gates and silence, not from a fractional clock.
- **Duration:** 24.0 s score; render 24.5 s (song + 0.5 s tail).
- **Shared motif (“the Seed”):** degrees **1–3–5–6**, minor form **A–C–E–F**, stated
  in a low register at half speed (`E1`), fragmented and answered across the form.
- **Form (A A′ with an E-major cadence approach):**

  | Bars | Chord per bar | Note |
  | --- | --- | --- |
  | 1–4 | Am Am F Dm | low motif statement (A–C–E–F) and answer |
  | 5–8 | Am C F Dm | motif fragment rises, first open cadence |
  | 9–12 | Am E F Am | dominant `E` tension, then full-bar tonic `A3` with trailing silence |

- **Channel roles** (monophonic, non-overlapping gates):

  | Channel | Instrument | Role |
  | --- | --- | --- |
  | `pulse0` | `lead` (pulse, v72, duty 32) | low, long-note motif |
  | `pulse1` | `harm` (pulse, v44, duty 32) | very sparse arpeggio tones |
  | `pulse2` | `bass` (pulse, v66, duty 176) | whole/half-note roots |
  | `noise` | `perc` (noise, v42) | occasional one/two-hit “drips” |

- **Transitions & cadence:** the harmony shifts to `E` (V) at bar 10 before a
  whole-bar `A` tonic; the sparse noise drips place one or two per bar rather than
  a groove.
- **Loop-friendliness:** ends on the tonic (bar 12) so a future loop point is
  possible; the toolchain is finite, so no runtime looping is claimed.

## Pattern reuse (finite, size-conscious)

36 pattern instances from 17 source patterns. Bass is five 1-bar whole-note
patterns; percussion is three short drip patterns cycled; harmony reuses `EB` for
two different 2-bar slots. Only the lead carries six phrases.

## Reproduction (run from the repository root)

```
tools/atm-music validate examples/music_authoring/creature_gatherer/exploration/song.json --backend progmem --json
tools/atm-music build    examples/music_authoring/creature_gatherer/exploration/song.json --backend progmem \
    --out build/music-authoring/creature_gatherer/exploration/build --json
tools/atm-music render   examples/music_authoring/creature_gatherer/exploration/song.json --backend progmem \
    --seconds 28 --out build/music-authoring/creature_gatherer/exploration/preview --json
tools/atm-music inspect  examples/music_authoring/creature_gatherer/exploration/song.json \
    --audio-preview build/music-authoring/creature_gatherer/exploration/preview \
    --out examples/music_authoring/creature_gatherer/exploration/review.html --json
```

## Measured results (this machine)

All commands exited `0` (tool 1.0.0, engine ATMlib 1.2.4, backend `progmem`).

| Quantity | Value |
| --- | --- |
| Validation | `ok:true`; 4/4 channels; 36 pattern instances; **75** expanded note events |
| Clock | requested 50 → effective **50 Hz**, 120.0 BPM, 1200 ticks / 24.0 s |
| `song.json` | 6988 B, sha256 `146b2f0883eddaefff77b05136ae387e60180091a842ea4327a0632ffaff40a9` |
| canonical event digest | `2c62ee88eecc506421f31acdd065855d75d9db6c77e73394f24800a8ab45dd1a` |
| `score.bin` (PROGMEM asset) | **702 B**, sha256 `d1751fec06ab0f6e08f9a074bf3e27c3dfca625a5fd6bc10a45a5848359150d5`; `program_bytes` `[213, 217, 121, 136]` |
| `review.json` | 34596 B, sha256 `31611f8136b9e7dbc861a1c50edc93e1d87e864e898af88a8412522d333f6162` (byte-identical to build) |
| `review.html` | 3339052 B, sha256 `8155ae8e1a8c4a9a3bb6aee946694b982eae7c135e0e965d71f7e448770a8beb` |
| `preview.wav` | 2449834 B, sha256 `71274672fa87de5d4314d91682056bd879d5fc9977839aec992987014284c321`; `pcm-s16le-mono` 50000 Hz, 1224895 samples = 24.4979 s |
| Render window | requested 28.0 s → effective 24.5 s, `truncated:false`, 1200/1200 ticks |
| First music callback | sample 1045 (0.0209 s), measured |
| Embedded audio match | `review.html` embeds this WAV (`wav_sha256` matches); source + event digests matched |

`score.bin` is PROGMEM song asset data only, not engine/SRAM/whole-game cost.

## Audio limitations (read honestly)

Mono emulated speaker mix; lane toggles change visibility only. Viewer
**Piezo (approx.)** is uncalibrated and not a measured device response; Raw
emulator is default. BPM is derived from the quantized timer rate; post-end DC
rail (~−2000, zero AC) is acoustically silent. Numeric evidence proves
correctness, not taste.

## Limitations / status

- **No FX export, no FX integration** (`--backend fx` → `BACKEND_UNAVAILABLE`).
- No external code or music was cloned, fetched, downloaded, vendored or copied.
- Intermediates live only under the excluded
  `build/music-authoring/creature_gatherer/exploration/`.
