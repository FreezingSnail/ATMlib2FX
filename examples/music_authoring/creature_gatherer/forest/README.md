# Creature Gatherer FX — Forest: “Greenwake Thicket” (ATMlib2FX-3ii.13.2)

## Current revision — 2026-10-17 (ATMlib2FX-awr)

Lively woodland call and response; smoother countervoice, reduced clashes and a lighter pulse tone.

**A Dorian · 130.43 BPM · 16 bars · 1472 ticks · 29.44 s per loop.**
The source sets `"loop": true`; the original PROGMEM engine restarts all tracks
on the same callback. The [review](review.html) defaults **Loop** on and repeats
one cycle with measured startup and capture tail excluded from playback.

Current [WAV](preview/preview.wav) and [render report](preview/preview.json) were
regenerated from this source through AVR/absim; the capture includes a cycle
plus 0.5 s of the next iteration. PROGMEM asset: **2244 B**.
WAV SHA-256: `a90ec963b7ffd08fd444313f625e91c901e69d32c38bd4c4cf8b1a43d62b8e92`.

[All-song player](../../player.html) · [source](song.json) · [canonical review](review.json).

## Historical first-version notes

The descriptions, numbers and captured paths below record the original finite
composition. Current timing, looping and media are described above. These
notes retain their original provenance; linked working assets now use the
current revision.

Candidate original cue for the Creature Gatherer FX **forest / living woodland
gathering** area. **Model-authored composition**, compiled only through
`progmem`; not integrated FX music, not a production asset. **Not**
copied/transposed/imitated from any existing song.

- **Source:** [`song.json`](song.json)
- **Offline review (embedded audio):** [`review.html`](review.html)
- **Canonical viewer payload:** [`review.json`](review.json)
- **Matching render pair:** [`preview/preview.json`](preview/preview.json) + [`preview/preview.wav`](preview/preview.wav)
- **Suite index:** [`../README.md`](../README.md)

## Intended game context

Moderate, curious woodland bed for gathering in a living forest: a call phrase
from the lead, a lower answering phrase, a walking bass and a light leaf-rustle
noise texture. Busier than the cave bed, calmer than combat.

## Musical form

- **Key / mode:** A **Dorian** (A B C D E F# G — natural minor with a raised
  6th), giving the “modal colour” without flats. **Meter:** 4/4.
- **Length:** 16 bars = 1536 ticks.
- **Clock:** requested `tick_rate` 50 → integer effective **50 Hz**;
  `ticks_per_beat` 24, `beats_per_bar` 4 → **effective 125.0 BPM**, one bar =
  96 ticks.
- **Duration:** 30.72 s score; render 31.22 s (song + 0.5 s tail).
- **Complexity class: moderate.** Four active channels, 34 source patterns in 48
  finite instances, 250 expanded note events and a **2225 B** `score.bin`
  (inside the ≤3 KiB moderate soft target). Complexity is carried by form,
  phrase interaction and a moving bass line — not by length or repeated notes.
- **Harmony (one chord per bar):**

  | Bars | Chords | Note |
  | --- | --- | --- |
  | 1–4 | Am C D Am | A-section: call (bars 1–2), answer (bars 3–4) |
  | 5–8 | Am C D Em | A′: chromatic-ish lift into `Em`, first open cadence |
  | 9–12 | Em D C G | B-section: modal shift, higher register, sequence |
  | 13–16 | Am C D Am | A″: return, variation, full-bar tonic cadence |

- **Channel roles** (monophonic, non-overlapping gates):

  | Channel | Instrument | Role |
  | --- | --- | --- |
  | `pulse0` | `lead` (pulse, v80, duty 32) | curious 2-bar call phrases |
  | `pulse1` | `answer` (pulse, v48, duty 64) | lower answering counter-phrases in the call’s gaps |
  | `pulse2` | `bass` (pulse, v70, duty 176) | moving bass: quarter-note roots with eighth-note passing motion |
  | `noise` | `rustle` (noise, v36) | sparse leaf-rustle ticks (unpitched texture, not pitched percussion) |

- **Rhythm & interaction:** the lead and answer trade 2-bar units — the lead
  states a phrase, the answer fills the tail of the phrase; the walking bass
  supplies forward motion the coast cue deliberately lacks.
- **Noise is texture, not melody or pitched percussion:** on `noise` the pitch
  token (C3/C5) only selects noise colour; short low-volume gates read as
  rustle. (The tool’s `required_features` reports `noise_percussion` because the
  noise channel is used; no pitched percussion is written.)
- **Ending:** bar 16 closes on the tonic `A4` held to the pattern end, so a
  future loop point is possible; the toolchain is finite and no runtime looping
  is claimed.

## Motif relationship (suite “Seed”, degrees 1–3–5–6)

The Seed is stated **implicitly** here to distinguish forest from the more literal
coast cue. In A dorian the Seed is A–C–E–F#:

- `L1` opens with the **1–3–5** outline `A4–C5–E5` (with a B4 passing tone).
- `L3` completes the rising shape `A4–C5–D5–E5`.
- `L7` reaches the **6th** (`F#5`) as the phrase apex; `L2`/`L8` colour cadences
  with F# and E4→A4 resolutions.
- The answer voice mirrors the same cell a register lower (`A3–C4–E4`), so call
  and response share one motivic source.

## Pattern reuse (finite, size-conscious)

34 source patterns → 48 bounded instances (`repeat` ≤ 2): 8 two-bar lead
phrases, 8 two-bar answer phrases, 9 one-bar bass patterns (reused across the
16-bar arrangement) and 5 one-bar rustle patterns cycled. The B-section
sequence is genuine variation (transposed/reshaped phrases), not a copy.

## Reproduction (run from the repository root)

```
tools/atm-music capabilities --json
tools/atm-music validate examples/music_authoring/creature_gatherer/forest/song.json --backend progmem --json
tools/atm-music build    examples/music_authoring/creature_gatherer/forest/song.json --backend progmem \
    --out build/music-authoring/themed-suite/forest/build --json
tools/atm-music render   examples/music_authoring/creature_gatherer/forest/song.json --backend progmem \
    --seconds 120 --out build/music-authoring/themed-suite/forest/render --json
tools/atm-music inspect  examples/music_authoring/creature_gatherer/forest/song.json \
    --audio-preview build/music-authoring/themed-suite/forest/render \
    --out examples/music_authoring/creature_gatherer/forest/review.html --json
```

`--seconds 120` is bounded automatically to song + 0.5 s tail (31.22 s); it is
not a truncation. Command stdout/stderr logs and build/render intermediates are
under the git-ignored `build/music-authoring/themed-suite/forest/`.

## Measured results (this machine)

All commands exited `0` (tool `atm-music` 1.0.0, engine ATMlib 1.2.4, backend
`progmem`).

| Quantity | Value |
| --- | --- |
| Validation | `ok:true`; 4/4 channels; 48 pattern instances; **250** expanded note events |
| Clock | requested 50 → effective **50 Hz**, **125.0 BPM**, 1536 ticks / 30.72 s |
| `song.json` | 17732 B, sha256 `b0b3748c8470d9d9415059e2c52ccfea467aafa83daa7317c1ad3e5b55994d99` |
| canonical event digest | `f7aeb53aa57307d805d34c15bb71817fd86df29fdf2a20ce8f8c29a73248d2d4` |
| `score.bin` (PROGMEM asset) | **2225 B**, sha256 `425914c4c67ae2c8f0eb51e0ec952ad7d4314b83caab0742722022dc9b5931fa`; `program_bytes` `[546, 550, 848, 266]` |
| `score.h` | 14538 B, sha256 `8652e8e81378b667456bd9940099ffc6a4ff29ddb3c209d6b66827e5a2a8e0b7` |
| `review.json` | 96762 B, sha256 `3db2d595d4c40f68cb3485f1188d17be0e762f030f93f7bfccc4b1475f1027e9` (byte-identical to build `review.json`) |
| `review.html` | 4276471 B, sha256 `7c447db0a1fc4364c8f5de198a5b537307974a757d25220e71861d42c2e47b5b` |
| `preview.json` | 243289 B, sha256 `a3e4a142b45466e406900f11e325dbcb738ecc0736bf799c387667a373fded67` (promoted unchanged) |
| `preview.wav` | 3121834 B, sha256 `1c90cb444fbba9a629a68b07e9a35b3f5cf2db30780857da02f19bf46569ac60`; `pcm-s16le-mono` 50000 Hz, 1560895 samples = 31.2179 s |
| Render window | requested 120.0 s → effective **31.22 s**, `truncated:false`, 1536/1536 ticks |
| First music callback | sample 1045 (0.0209 s), measured |
| Embedded audio match | `review.html` embeds this WAV (`wav_sha256` `1c90cb44…`); source + event digests matched at inspect |

`score.bin` is PROGMEM **song asset** data only — not engine code, not SRAM and
not whole-game cost. The preview pair is promoted byte-unchanged from the render
output (its internal `audio.wav` path still names the build tree; that path is
historical and the promoted `preview/preview.wav` beside it resolves for
loaders).

## Audio limitations (read honestly)

Mono emulated speaker mix; lane toggles change visibility only. Viewer
**Piezo (approx.)** is uncalibrated and not a measured device response; **Raw
emulator** is the default. BPM is derived from the quantized timer rate; the
post-end DC rail (≈ −2000, zero AC) is acoustically silent. Numeric evidence
proves gates, timing, silence and determinism — not taste.

## Limitations / status

- **No FX export, no FX integration** (`--backend fx` → `BACKEND_UNAVAILABLE`,
  pending ATMlib2FX-hlh.2 / ATMlib2FX-3ii.3).
- No external code or music was cloned, fetched, downloaded, vendored or copied.
- No unit/integration/browser/hardware listening tests were run and none are
  claimed.
- Intermediates live only under the git-ignored
  `build/music-authoring/themed-suite/forest/`.
