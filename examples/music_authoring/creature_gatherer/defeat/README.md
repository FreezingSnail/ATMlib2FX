# Creature Gatherer FX — Defeat: “Lost” (ATMlib2FX-3ii.11)

## Current revision — 2026-10-17 (ATMlib2FX-awr)

Slow descending loss cue; consonant sustained notes and a quiet fifth leading back into the opening.

**A minor · 68.18 BPM · 4 bars · 704 ticks · 14.08 s per loop.**
The source sets `"loop": true`; the original PROGMEM engine restarts all tracks
on the same callback. The [review](review.html) defaults **Loop** on and repeats
one cycle with measured startup and capture tail excluded from playback.

Current [WAV](preview/preview.wav) and [render report](preview/preview.json) were
regenerated from this source through AVR/absim; the capture includes a cycle
plus 0.5 s of the next iteration. PROGMEM asset: **292 B**.
WAV SHA-256: `3a6f3b0a3fd9b631e1734e018402fc6fcb4f9229524a3e0fa556dfbf0b0e3418`.

[All-song player](../../player.html) · [source](song.json) · [canonical review](review.json).

## Historical first-version notes

The descriptions, numbers and captured paths below record the original finite
composition. Current timing, looping and media are described above. These
notes retain their original provenance; linked working assets now use the
current revision.

Candidate original outcome cue for the Creature Gatherer FX *defeat / failure*
state. **Model-authored composition**, compiled only through `progmem`; not
integrated FX music. **Not** copied/transposed/imitated from any existing song.

- **Source:** [`song.json`](song.json)
- **Offline review (embedded audio):** [`review.html`](review.html)
- **Canonical viewer payload:** [`review.json`](review.json)
- **Suite index:** [`../README.md`](../README.md)

## Intended game context

Sombre, descending sting for a failed battle or a lost creature — a concise “down”
counterpart to the victory cue.

## Musical form

- **Key:** A natural minor. **Meter:** 4/4. **Length:** 4 bars = 400 ticks (concise outcome cue).
- **Effective BPM:** 120.0 (requested `tick_rate` 50 → integer effective 50 Hz;
  `ticks_per_beat` 25, `beats_per_bar` 4). One bar = 100 ticks; long half-note gates
  give the slow, sinking feel.
- **Duration:** 8.0 s score; render 8.5 s (song + 0.5 s tail).
- **Shared motif (“the Seed”):** the **retrograde/inversion** of the suite motif —
  descending degrees **♭6–5–♭3–1**, i.e. **A–G–F–E–C–A** across the form’s long notes,
  a direct minor-mood mirror of the overworld’s rising 1–3–5–6.
- **Harmony:** Am | F | E | Am (i–VI–V–i), a full minor cadence.

- **Channel roles** (monophonic, non-overlapping gates):

  | Channel | Instrument | Role |
  | --- | --- | --- |
  | `pulse0` | `lead` (pulse, v64, duty 64) | slow descending line |
  | `pulse1` | `harm` (pulse, v40, duty 32) | sparse chord tones |
  | `pulse2` | `bass` (pulse, v60, duty 176) | whole-bar roots |
  | `noise` | `perc` (noise, v36) | low heartbeat hits |

- **Cadence:** the `E` dominant (bar 3) resolves to a long tonic `A3` (bar 4); the
  low sparse percussion reads as a heartbeat.
- **Loop-friendliness:** terminal sting; no runtime looping claimed.

## Pattern reuse (finite, size-conscious)

12 pattern instances from 7 source patterns; melody is two 2-bar phrases, bass
three 1-bar whole-note roots reused, percussion two patterns alternating.

## Reproduction (run from the repository root)

```
tools/atm-music validate examples/music_authoring/creature_gatherer/defeat/song.json --backend progmem --json
tools/atm-music build    examples/music_authoring/creature_gatherer/defeat/song.json --backend progmem \
    --out build/music-authoring/creature_gatherer/defeat/build --json
tools/atm-music render   examples/music_authoring/creature_gatherer/defeat/song.json --backend progmem \
    --seconds 10 --out build/music-authoring/creature_gatherer/defeat/preview --json
tools/atm-music inspect  examples/music_authoring/creature_gatherer/defeat/song.json \
    --audio-preview build/music-authoring/creature_gatherer/defeat/preview \
    --out examples/music_authoring/creature_gatherer/defeat/review.html --json
```

## Measured results (this machine)

All commands exited `0` (tool 1.0.0, engine ATMlib 1.2.4, backend `progmem`).

| Quantity | Value |
| --- | --- |
| Validation | `ok:true`; 4/4 channels; 12 pattern instances; **26** expanded note events |
| Clock | requested 50 → effective **50 Hz**, 120.0 BPM, 400 ticks / 8.0 s |
| `song.json` | 3255 B, sha256 `3c4a40c31fa0a592dc2f7b77775661d96b0cbe5125c7d6cdcc841032bc79192e` |
| canonical event digest | `f0ec20961a487f56f1a2b5848c08f0ba0e8095b34669110fe539a6cbf0a0ac0e` |
| `score.bin` (PROGMEM asset) | **257 B**, sha256 `5a4cb4c7b7b0531097e5d0bc9d71b16f78561dbec9a09f946180cf469ba122c1`; `program_bytes` `[79, 73, 41, 49]` |
| `review.json` | 13486 B, sha256 `7e7e45dadd64e759994e376e02bc82a5303cbb5fe183d324b5f4ee3ff3b20666` (byte-identical to build) |
| `review.html` | 1191767 B, sha256 `3c61c4fbc4c0999835125f61b0252cfa478a58c585f44b1ab8f03ef468c379c9` |
| `preview.wav` | 849834 B, sha256 `9f9048cf0ae9dde33c42c33328bf734bb61aafec4a333dfa7866fbd01cfec7a0`; `pcm-s16le-mono` 50000 Hz, 424895 samples = 8.4979 s |
| Render window | requested 10.0 s → effective 8.5 s, `truncated:false`, 400/400 ticks |
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
  `build/music-authoring/creature_gatherer/defeat/`.
