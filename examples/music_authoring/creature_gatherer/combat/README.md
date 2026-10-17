# Creature Gatherer FX — Combat: “Clash of Gatherers” (ATMlib2FX-3ii.11)

## Current revision — 2026-10-17 (ATMlib2FX-awr)

Driving battle theme; slower than the original rush, with fewer chromatic clashes and a final upbeat.

**D minor · 176.47 BPM · 16 bars · 2176 ticks · 21.76 s per loop.**
The source sets `"loop": true`; the original PROGMEM engine restarts all tracks
on the same callback. The [review](review.html) defaults **Loop** on and repeats
one cycle with measured startup and capture tail excluded from playback.

Current [WAV](preview/preview.wav) and [render report](preview/preview.json) were
regenerated from this source through AVR/absim; the capture includes a cycle
plus 0.5 s of the next iteration. PROGMEM asset: **2041 B**.
WAV SHA-256: `04260bc21bec46815783482385bda9e55dbf8ca34a91b45a993ce78f79a5379c`.

[All-song player](../../player.html) · [source](song.json) · [canonical review](review.json).

## Historical first-version notes

The descriptions, numbers and captured paths below record the original finite
composition. Current timing, looping and media are described above. These
notes retain their original provenance; linked working assets now use the
current revision.

Candidate original cue for the Creature Gatherer FX *battle* state. **Model-authored
composition**, not integrated FX music and not a production asset: no FX export/ABI
exists, so it is compiled only through `progmem` and labelled a candidate. **Not**
copied, transposed or imitated from any existing song.

- **Source:** [`song.json`](song.json)
- **Offline review (embedded audio):** [`review.html`](review.html) — open directly in a browser
- **Canonical viewer payload:** [`review.json`](review.json)
- **Suite index:** [`../README.md`](../README.md)

## Intended game context

Driving, tense battle theme for turn-based creature combat (1–3 opponents). One
150 ms energy, fast enough to raise pulse without becoming noise under a turn menu.

## Musical form

- **Key:** D minor (harmonic-minor colour on the dominant). **Meter:** 4/4.
  **Length:** 16 bars = 1600 ticks.
- **Effective BPM:** 240.0 (requested `tick_rate` 100 → integer effective 100 Hz;
  `ticks_per_beat` 25, `beats_per_bar` 4). One bar = 100 ticks.
- **Duration:** 16.0 s score; render 16.5 s (song + 0.5 s tail).
- **Shared motif (“the Seed”):** degrees **1–3–5–6** long–short–short–long. Here the
  minor form **D–F–A–A#** (A# = B♭) drives the riff in fast eighth notes; the
  bridge pushes to `D6`/`C6` and the dominant uses `C#5`/`G#5` for tension.
- **Form (A B A′ cadence):**

  | Bars | Section | Chord per bar | Note |
  | --- | --- | --- | --- |
  | 1–4 | A | Dm Dm A# A | riff statement, chromatic descent in bar 4 |
  | 5–8 | A cont. | Dm A# F A | answers, heightens to `C6`, cadence approach |
  | 9–12 | B (contrast) | Dm C A# A | high-register bridge, chromatic `A#–A–G#–E` over V |
  | 13–16 | A′ (return) | Dm A# A Dm | riff returns; V→i cadence, final `D5` held with silence |

- **Channel roles** (fixed channels, monophonic, non-overlapping gates):

  | Channel | Instrument | Role |
  | --- | --- | --- |
  | `pulse0` | `lead` (pulse, v96, duty 96) | fast eighth-note riff |
  | `pulse1` | `harm` (pulse, v54, duty 64) | stabbing chord tones |
  | `pulse2` | `bass` (pulse, v78, duty 208) | driving eighth-note roots/fifths |
  | `noise` | `perc` (noise, v64) | kick/snare with off-beats and rolls |

- **Transitions & cadence:** drum fills at bars 8, 12, 15; the bridge raises the
  melodic register an octave and adds chromatic tension; bars 15–16 land V→i with
  the tonic `D5` held and a trailing bead of silence.
- **Loop-friendliness:** the final bar is a tonic return suitable for a future loop
  point, but the toolchain is finite; no runtime looping is claimed.

## Pattern reuse (finite, size-conscious)

48 pattern instances expand from 22 source patterns. Bass is eight 1-bar patterns
reused across the form; harmony reuses `H1`/`H2`; percussion reuses `beatD`/
`beatD2` and `fillC` as the section marker. Melody uses eight 2-bar riff phrases
because the identity is carried by the lead. All repetition is finite.

## Reproduction (run from the repository root)

```
tools/atm-music validate examples/music_authoring/creature_gatherer/combat/song.json --backend progmem --json
tools/atm-music build    examples/music_authoring/creature_gatherer/combat/song.json --backend progmem \
    --out build/music-authoring/creature_gatherer/combat/build --json
tools/atm-music render   examples/music_authoring/creature_gatherer/combat/song.json --backend progmem \
    --seconds 20 --out build/music-authoring/creature_gatherer/combat/preview --json
tools/atm-music inspect  examples/music_authoring/creature_gatherer/combat/song.json \
    --audio-preview build/music-authoring/creature_gatherer/combat/preview \
    --out examples/music_authoring/creature_gatherer/combat/review.html --json
```

## Measured results (this machine)

All commands exited `0` (tool 1.0.0, engine ATMlib 1.2.4, backend `progmem`).

| Quantity | Value |
| --- | --- |
| Validation | `ok:true`; 4/4 channels; 48 pattern instances; **235** expanded note events |
| Clock | requested 100 → effective **100 Hz**, 240.0 BPM, 1600 ticks / 16.0 s |
| `song.json` | 12611 B, sha256 `d34dca2c2c9d0bcadd5c1bd9eb321a659150fe40a52ed2ffdbd7a6f852a4c1f1` |
| canonical event digest | `c1ec59d706fbe51a2aceb0380b29a56e2e3a35ae56d1c23e331a6aa41bcc3c0e` |
| `score.bin` (PROGMEM asset) | **2011 B**, sha256 `0b5b74bdc7263308dd7a2619897b2bdbe349f017a0c1f4edbaa28929aebbf633`; `program_bytes` `[553, 321, 561, 561]` |
| `review.json` | 92035 B, sha256 `b5742a4d4e8af900f9a72c11d13ac5c6e48b429ba4f20e8cbc127740a64a5b23` (byte-identical to build) |
| `review.html` | 2310787 B, sha256 `3acd1442cc01b980381354ed62708693b51d1627c3f4cb2afadeb22aa575eacb` |
| `preview.wav` | 1649834 B, sha256 `c8f7f4e9a124874fe7d49718fa1be99d6103130d4b591b319fb62162be4d4ddc`; `pcm-s16le-mono` 50000 Hz, 824895 samples = 16.4979 s |
| Render window | requested 20.0 s → effective 16.5 s, `truncated:false`, 1600/1600 ticks |
| First music callback | sample 1045 (0.0209 s), measured |
| Embedded audio match | `review.html` embeds this WAV (`wav_sha256` matches); source + event digests matched |

`score.bin` is PROGMEM song asset data only, not engine/SRAM/whole-game cost.

## Audio limitations (read honestly)

- Mono emulated speaker mix only; lane toggles change visibility, never audio.
- Viewer **Piezo (approx.)** is an **uncalibrated** browser coloration, not a
  measured device response. Raw emulator is the default. Verify on device.
- BPM is derived from the quantized timer rate. Post-end constant DC rail
  (~−2000, zero AC) is acoustically silent, not neutral 0.
- Numeric evidence proves correctness (gates/timing/silence/digests), not taste.

## Limitations / status

- **No FX export, no FX integration** (`--backend fx` → `BACKEND_UNAVAILABLE`).
- No external code or music was cloned, fetched, downloaded, vendored or copied.
- Intermediates live only under the excluded
  `build/music-authoring/creature_gatherer/combat/`.
