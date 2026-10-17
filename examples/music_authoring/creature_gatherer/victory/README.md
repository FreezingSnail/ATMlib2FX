# Creature Gatherer FX — Victory: “Gathered!” (ATMlib2FX-3ii.11)

## Current revision — 2026-10-17 (ATMlib2FX-awr)

Bright repeating victory fanfare; resolved upper harmony and a fifth leading into the tonic.

**C major · 187.50 BPM · 4 bars · 512 ticks · 5.12 s per loop.**
The source sets `"loop": true`; the original PROGMEM engine restarts all tracks
on the same callback. The [review](review.html) defaults **Loop** on and repeats
one cycle with measured startup and capture tail excluded from playback.

Current [WAV](preview/preview.wav) and [render report](preview/preview.json) were
regenerated from this source through AVR/absim; the capture includes a cycle
plus 0.5 s of the next iteration. PROGMEM asset: **499 B**.
WAV SHA-256: `c7e373cc27dd871ff11333e4b27589d3af9416d9e82a99a075018d6728005595`.

[All-song player](../../player.html) · [source](song.json) · [canonical review](review.json).

## Historical first-version notes

The descriptions, numbers and captured paths below record the original finite
composition. Current timing, looping and media are described above. These
notes retain their original provenance; linked working assets now use the
current revision.

Candidate original outcome cue for the Creature Gatherer FX *victory* state.
**Model-authored composition**, compiled only through `progmem`; not integrated FX
music. **Not** copied/transposed/imitated from any existing song.

- **Source:** [`song.json`](song.json)
- **Offline review (embedded audio):** [`review.html`](review.html)
- **Canonical viewer payload:** [`review.json`](review.json)
- **Suite index:** [`../README.md`](../README.md)

## Intended game context

Short, bright fanfare for a successful gather/capture or battle win — a concise
reward sting, not a level theme.

## Musical form

- **Key:** C major. **Meter:** 4/4. **Length:** 4 bars = 400 ticks (concise outcome cue).
- **Effective BPM:** 240.0 (requested `tick_rate` 100 → integer effective 100 Hz;
  `ticks_per_beat` 25, `beats_per_bar` 4). One bar = 100 ticks.
- **Duration:** 4.0 s score; render 4.5 s (song + 0.5 s tail).
- **Shared motif (“the Seed”):** degrees **1–3–5–6** long–short–short–long, in the
  **major** form **C–E–G–A** (bars 1–2), answered and cadencing on a held `C6`.
- **Harmony:** C | G | F | C (I–V–IV–I) with a final tonic cadence.

- **Channel roles** (monophonic, non-overlapping gates):

  | Channel | Instrument | Role |
  | --- | --- | --- |
  | `pulse0` | `lead` (pulse, v100, duty 160) | bright fanfare motif |
  | `pulse1` | `harm` (pulse, v60, duty 64) | arpeggiated support |
  | `pulse2` | `bass` (pulse, v80, duty 208) | root/fifth per bar |
  | `noise` | `perc` (noise, v66) | sparse celebration hits + one roll |

- **Cadence:** bar 3 adds a percussion roll; bar 4 resolves to C with a held `C6`.
- **Loop-friendliness:** not a loop cue (it is a terminal sting); no runtime looping.

## Pattern reuse (finite, size-conscious)

12 pattern instances from 7 source patterns; the melody is two 2-bar phrases, the
bass is three 1-bar patterns reused, percussion is two patterns with a roll.

## Reproduction (run from the repository root)

```
tools/atm-music validate examples/music_authoring/creature_gatherer/victory/song.json --backend progmem --json
tools/atm-music build    examples/music_authoring/creature_gatherer/victory/song.json --backend progmem \
    --out build/music-authoring/creature_gatherer/victory/build --json
tools/atm-music render   examples/music_authoring/creature_gatherer/victory/song.json --backend progmem \
    --seconds 6 --out build/music-authoring/creature_gatherer/victory/preview --json
tools/atm-music inspect  examples/music_authoring/creature_gatherer/victory/song.json \
    --audio-preview build/music-authoring/creature_gatherer/victory/preview \
    --out examples/music_authoring/creature_gatherer/victory/review.html --json
```

## Measured results (this machine)

All commands exited `0` (tool 1.0.0, engine ATMlib 1.2.4, backend `progmem`).

| Quantity | Value |
| --- | --- |
| Validation | `ok:true`; 4/4 channels; 12 pattern instances; **53** expanded note events |
| Clock | requested 100 → effective **100 Hz**, 240.0 BPM, 400 ticks / 4.0 s |
| `song.json` | 5060 B, sha256 `1252eff1cdf1abef9b70d202c21d560304c4f69088b5a3f5c32284ae4d069bc7` |
| canonical event digest | `39b0c6bfd4a94de0a358473b36c9eac33253ce4dea4032a74bc1478c56098aca` |
| `score.bin` (PROGMEM asset) | **488 B**, sha256 `5e42a2421cb5a7f36234ea0c379717d208cf26cbdb7b4c35a4d6e29de2e932d8`; `program_bytes` `[163, 145, 81, 84]` |
| `review.json` | 22768 B, sha256 `2163220e6dc12351a7ebbffe0f38d3041e7b3b8a108a08ebc0b140388149f52e` (byte-identical to build) |
| `review.html` | 664641 B, sha256 `5d991ad93143f5646f75f5d9025109010b3977c7c8e49bdfc8928634346a4135` |
| `preview.wav` | 449834 B, sha256 `bcb8ba96f08cbdd16c9b4034c311bf36e027a3ce4289f49bf92e27ee5f044836`; `pcm-s16le-mono` 50000 Hz, 224895 samples = 4.4979 s |
| Render window | requested 6.0 s → effective 4.5 s, `truncated:false`, 400/400 ticks |
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
  `build/music-authoring/creature_gatherer/victory/`.
