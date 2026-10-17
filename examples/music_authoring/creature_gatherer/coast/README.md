# Creature Gatherer FX — Coast: “Tideline Ramble” (ATMlib2FX-3ii.13.2)

## Current revision — Marsh/Tideline follow-up (ATMlib2FX-cfp)

Flowing shore melody; four accidental repeated-note interruptions joined into holds, smoother bass, quieter accompaniment and consistent short lead gaps.

**G major · 107.14 BPM · 12 bars · 1344 ticks · 26.88 s per loop.**
[Source](song.json) · [review with Loop on](review.html) · [all-song player](../../player.html).

Fresh [WAV](preview/preview.wav) and [AVR render report](preview/preview.json)
match this source. PROGMEM asset: **1082 B**. The capture contains one cycle
plus 0.5 s of the next; browser playback excludes startup and capture tail.
WAV SHA-256: `a257831992e610d48bf4ab3de98d5d81f831a0d97a6e877b66c9f20c69c1723d`.

The joined D5, G4, G5 and B4 repeats previously had 180, 240, 380 and 80 ms
interruptions. Lead gates now end two 50-Hz ticks before the next note (40 ms),
including phrase boundaries. This corrects authored articulation; no browser
playback-rate or engine change is involved.

## Earlier looping revision — 2026-10-17 (ATMlib2FX-awr)

Rocking shore theme; clear chord landings and a short final pickup.

**G major · 107.14 BPM · 12 bars · 1344 ticks · 26.88 s per loop.**
The source sets `"loop": true`; the original PROGMEM engine restarts all tracks
on the same callback. The [review](review.html) defaults **Loop** on and repeats
one cycle with measured startup and capture tail excluded from playback.

Current [WAV](preview/preview.wav) and [render report](preview/preview.json) were
regenerated from this source through AVR/absim; the capture includes a cycle
plus 0.5 s of the next iteration. PROGMEM asset: **1107 B**.
WAV SHA-256: `a754c8ee4dc29a998456b08adf5a9ecca826ba4864148702ffaf0bd7a6fb1c0c`.

[All-song player](../../player.html) · [source](song.json) · [canonical review](review.json).

## Historical first-version notes

The descriptions, numbers and captured paths below record the original finite
composition. Current timing, looping and media are described above. These
notes retain their original provenance; linked working assets now use the
current revision.

Candidate original cue for the Creature Gatherer FX **coast / tidal route**
area. **Model-authored composition**, compiled only through `progmem`; not
integrated FX music, not a production asset. **Not** copied/transposed/imitated
from any existing song.

- **Source:** [`song.json`](song.json)
- **Offline review (embedded audio):** [`review.html`](review.html)
- **Canonical viewer payload:** [`review.json`](review.json)
- **Matching render pair:** [`preview/preview.json`](preview/preview.json) + [`preview/preview.wav`](preview/preview.wav)
- **Suite index:** [`../README.md`](../README.md)

## Intended game context

Light, open bed for a shoreline / tidal gathering route: a simple singing melody
over half-note rocking bass with a restrained off-beat arpeggio and occasional
surf-like noise ticks. Deliberately simpler and slower-moving than the forest
cue.

## Musical form

- **Key:** G **major** (bright, diatonic). **Meter:** 4/4.
- **Length:** 12 bars = 1440 ticks.
- **Clock:** requested `tick_rate` 50 → integer effective **50 Hz**;
  `ticks_per_beat` 30, `beats_per_bar` 4 → **effective 100.0 BPM**, one bar =
  120 ticks.
- **Duration:** 28.8 s score; render 29.3 s (song + 0.5 s tail).
- **Complexity class: simple / light.** Four channels but three of them are
  economical: 20 source patterns in 42 finite instances, 115 expanded note
  events and a **1079 B** `score.bin` (at the ≈1 KiB simple soft target).
- **Harmony (one chord per bar):**

  | Bars | Chords | Note |
  | --- | --- | --- |
  | 1–4 | G Em C D | A-section: Seed statement, then a light turnaround |
  | 5–8 | G Em C D | A′: melody varied an octave-feel higher, same harmony |
  | 9–12 | C G D G | B/cadence: plagal drift, then full-bar tonic `G` |

- **Channel roles** (monophonic, non-overlapping gates):

  | Channel | Instrument | Role |
  | --- | --- | --- |
  | `pulse0` | `lead` (pulse, v78, duty 64) | open, singable 2-bar melody phrases |
  | `pulse1` | `arp` (pulse, v38, duty 96) | restrained off-beat arpeggio, two-to-three tones per bar |
  | `pulse2` | `bass` (pulse, v64, duty 192) | rocking root–fifth half notes |
  | `noise` | `wash` (noise, v28) | occasional soft surf ticks (unpitched texture, not pitched percussion) |

- **Rhythm / “rocking” feel:** the bass alternates root (beat 1) and fifth
  (beat 3) as half notes, while the arpeggio places short tones on the eighth
  off-beats (ticks 15/45/75) — a gentle back-and-forth sway rather than the
  forest’s quarter-note walking motion. Melody gates are long with real rests, so
  spacing stays open.
- **Noise is texture, not melody or pitched percussion:** the `noise` pitch token
  (C3/C5) selects noise colour only; short, quiet, sparse gates read as surf.
  (`required_features` reports `noise_percussion` because the noise channel is
  used; no pitched percussion is written.)
- **Ending:** bar 12 closes on a long tonic `G4` with trailing space; a future
  loop point is possible, but the toolchain is finite and no runtime looping is
  claimed.

## Motif relationship (suite “Seed”, degrees 1–3–5–6) and contrast with Forest

In G major the Seed is **G–B–D–E** (1–3–5–6). Coast states it **plainly and
briefly**: `M1` opens `G4–B4–D5–E5`, then the figure is developed rather than
repeated (`M3` reaches `G5`, `M5`/`M6` turn it back to the tonic). This is the
literal, singable presentation.

The contrast with the [forest cue](../forest/README.md) is intentional:

| | Forest “Greenwake Thicket” | Coast “Tideline Ramble” |
| --- | --- | --- |
| Mode | A **Dorian** (modal colour) | G **major** |
| Tempo | 125.0 BPM | 100.0 BPM |
| Form | 16 bars, call-and-response across two voices | 12 bars, single lead + arpeggio |
| Phrasing | 2-bar call answered in the same gaps | 2-bar open melodic phrases, no answer voice |
| Harmony | i–III–IV with modal `Em`/`G` shift | I–vi–IV–V, plagal cadence |
| Bass | moving quarters + eighth passing tones | rocking root–fifth half notes |
| Seed | implied (1–3–5 outline, 6th at cadences) | stated outright 1–3–5–6 |

## Pattern reuse (finite, size-conscious)

20 source patterns → 42 bounded instances (`repeat` = 1): 6 two-bar melody
phrases, 8 one-bar arpeggio patterns (4 reused between A and A′), 8 one-bar bass
patterns (4 reused) and 3 one-bar surf patterns cycled. Reuse is the reason the
asset stays near 1 KiB; the B/cadence section introduces new melody material
rather than looping the A-section.

## Reproduction (run from the repository root)

```
tools/atm-music capabilities --json
tools/atm-music validate examples/music_authoring/creature_gatherer/coast/song.json --backend progmem --json
tools/atm-music build    examples/music_authoring/creature_gatherer/coast/song.json --backend progmem \
    --out build/music-authoring/themed-suite/coast/build --json
tools/atm-music render   examples/music_authoring/creature_gatherer/coast/song.json --backend progmem \
    --seconds 120 --out build/music-authoring/themed-suite/coast/render --json
tools/atm-music inspect  examples/music_authoring/creature_gatherer/coast/song.json \
    --audio-preview build/music-authoring/themed-suite/coast/render \
    --out examples/music_authoring/creature_gatherer/coast/review.html --json
```

`--seconds 120` is bounded automatically to song + 0.5 s tail (29.3 s); it is
not a truncation. Command stdout/stderr logs and build/render intermediates are
under the git-ignored `build/music-authoring/themed-suite/coast/`.

## Measured results (this machine)

All commands exited `0` (tool `atm-music` 1.0.0, engine ATMlib 1.2.4, backend
`progmem`).

| Quantity | Value |
| --- | --- |
| Validation | `ok:true`; 4/4 channels; 42 pattern instances; **115** expanded note events |
| Clock | requested 50 → effective **50 Hz**, **100.0 BPM**, 1440 ticks / 28.8 s |
| `song.json` | 9568 B, sha256 `4ee5d8722beef208476068d6acfd9f77c1f2d15cb77ae6c15d3a731de19bae51` |
| canonical event digest | `1617153ab312224aa347b0b1311ee570a25726326732f3edf92d063dd28a6098` |
| `score.bin` (PROGMEM asset) | **1079 B**, sha256 `a97e3cabefa996a463eadba43b636c76dfb0a761571e943edb635d4cf9a00525`; `program_bytes` `[367, 286, 249, 162]` |
| `score.h` | 7277 B, sha256 `c8601517d0fb99e4e0a32e6f7de6a024d5e4e976f396dac13a6ec1187edb1b20` |
| `review.json` | 49272 B, sha256 `b69b2c65cbb7bbd4cb9308351abae400e548d785b7dd3c00e7ac9d4f251df516` (byte-identical to build `review.json`) |
| `review.html` | 3988765 B, sha256 `540441b5aaf6de009549ddebc093dda513868c81e75fa813b6c9d40448431731` |
| `preview.json` | 129862 B, sha256 `43353e818c6c29b8c130246374700f242f975d79a8b471fc77f55ac686392a67` (promoted unchanged) |
| `preview.wav` | 2929834 B, sha256 `67815c144e687f01349dffb9430371cd21beb5fc0a6c5baf5d22a11cf301ff9f`; `pcm-s16le-mono` 50000 Hz, 1464895 samples = 29.2979 s |
| Render window | requested 120.0 s → effective **29.3 s**, `truncated:false`, 1440/1440 ticks |
| First music callback | sample 1045 (0.0209 s), measured |
| Embedded audio match | `review.html` embeds this WAV (`wav_sha256` `67815c14…`); source + event digests matched at inspect |

`score.bin` is PROGMEM **song asset** data only — not engine code, not SRAM and
not whole-game cost. The preview pair is promoted byte-unchanged from the render
output (its internal `audio.wav` path still names the build tree; that path is
historical and the promoted `preview/preview.wav` beside it resolves for
loaders).

## Musical tradeoffs (honest)

- Keeping the coast “simple” meant accepting a repeating two-bar harmonic loop
  for bars 1–8; contrast comes from melody register/rhythm and the B/cadence
  bars, not from more chords.
- The arpeggio is deliberately quiet (v38) and off-beat; louder or denser it
  would fight the melody in the mono mix and inflate the asset.
- Choosing 100 BPM at `ticks_per_beat` 30 keeps every eighth-note on an integer
  tick (15) — no fractional clock — which rules out some 16th-note embellishments
  used in the forest cue.

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
  `build/music-authoring/themed-suite/coast/`.
