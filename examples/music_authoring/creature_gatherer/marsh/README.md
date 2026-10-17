# Creature Gatherer FX — Marsh: “Marsh at Dusk” (ATMlib2FX-3ii.13.3)

## Current revision — Marsh/Tideline follow-up (ATMlib2FX-cfp)

Rewritten eight-bar wetland melody in natural E minor; a clear question-and-answer phrase over Em–C–G–D / Em–Am–D–Em, held roots, quiet harmony and sparse mist noise.

**E minor · 78.95 BPM · 8 bars · 1216 ticks · 24.32 s per loop.**
[Source](song.json) · [review with Loop on](review.html) · [all-song player](../../player.html).

Fresh [WAV](preview/preview.wav) and [AVR render report](preview/preview.json)
match this source. PROGMEM asset: **563 B**. The capture contains one cycle
plus 0.5 s of the next; browser playback excludes startup and capture tail.
WAV SHA-256: `1077ab369ceec41d402985ffa52c61f7fe5af0c86f033eb0c6fbf21d04f72358`.

The new lead spans B3–E5, stays in natural E minor, and uses quarter/eighth-note
phrases. Held chord tones replace the scattered answer notes; the low noise
rumbles and chromatic detours are removed. This replaces the rejected cue.

## Earlier looping revision — 2026-10-17 (ATMlib2FX-awr)

Slow wetland theme; spacious syncopation with the sustained semitone/tritone clashes resolved.

**E Dorian/minor · 75.00 BPM · 12 bars · 1920 ticks · 38.4 s per loop.**
The source sets `"loop": true`; the original PROGMEM engine restarts all tracks
on the same callback. The [review](review.html) defaults **Loop** on and repeats
one cycle with measured startup and capture tail excluded from playback.

Current [WAV](preview/preview.wav) and [render report](preview/preview.json) were
regenerated from this source through AVR/absim; the capture includes a cycle
plus 0.5 s of the next iteration. PROGMEM asset: **1114 B**.
WAV SHA-256: `6fc5714f871627814c710bb8c88f00fa5888d0488109d4eb5b1030936296a810`.

[All-song player](../../player.html) · [source](song.json) · [canonical review](review.json).

## Historical first-version notes

The descriptions, numbers and captured paths below record the original finite
composition. Current timing, looping and media are described above. These
notes retain their original provenance; linked working assets now use the
current revision.

Candidate original cue for the Creature Gatherer FX *wetland gathering* area.
**Model-authored composition**, compiled only through `progmem`; not integrated
FX music, not a production asset. **Not** copied/transposed/imitated from any
existing song; no external code or music was cloned, fetched, downloaded,
vendored or copied.

- **Source:** [`song.json`](song.json) (`id` `cg_marsh_v1`)
- **Offline review (embedded audio):** [`review.html`](review.html)
- **Canonical viewer payload:** [`review.json`](review.json)
- **Promoted preview pair:** [`preview/preview.json`](preview/preview.json) · [`preview/preview.wav`](preview/preview.wav)
- **Suite build fragment:** `build/music-authoring/themed-suite/marsh/catalog-entry.json`

## Intended game context

Dusk wetland / marsh gathering. A slow, spacious bed with wet low rumbles and
thin high ticks, short motifs that answer each other across the bar, one Dorian
colour (raised 6th) as controlled dissonance, and a clear resolution to the
tonic. Distinct from the earlier cave cue (“Hollow Depths”), which was slower
and sparser in A natural minor: this cue uses **E minor/Dorian**, off-grid
syncopation and a two-colour noise texture.

## Musical form

- **Key / mode:** E minor with Dorian raised 6th (`C#`) as colour; D# and A#
  appear only as leading/tension tones into B or E.
- **Meter:** 4/4. **Length:** 12 bars = 1920 ticks. One bar = 160 ticks.
- **Effective BPM:** **75.0** (requested `tick_rate` 50 → integer effective
  50 Hz; `ticks_per_beat` 40, `beats_per_bar` 4). Spaciousness comes from
  long gates, rests and off-beat placement, not a fractional clock.
- **Duration:** **38.4 s** score; render **38.9 s** (song + 0.5 s tail),
  `truncated:false`, 1920/1920 ticks.
- **Form:** three 4-bar phrases — statement, development, cadence:

  | Bars | Harmony (per bar) | Note |
  | --- | --- | --- |
  | 1–4 | Em · Em · C · Am | motif statement (E–G–B–C#) then a descending answer; first Dorian colour |
  | 5–8 | Em · F#m7b5 · C · B7 | development: half-diminished tension (F#–A–C–E) over the dominant, rising line |
  | 9–12 | Am · Em · B7(A#) · Em | cadence: A# leading tone over V, whole-bar tonic E with trailing silence |

- **Channel roles** (monophonic, non-overlapping gates):

  | Channel | Instrument | Role |
  | --- | --- | --- |
  | `pulse0` | `lead` (pulse, v78, duty 96) | main motif and answering phrases |
  | `pulse1` | `harm` (pulse, v42, duty 32) | sparse off-beat answering arpeggio |
  | `pulse2` | `bass` (pulse, v70, duty 176) | sustained roots; short walk-ups in bars 8 and 11 |
  | `noise` | `perc` (noise, v44) / `rumble` (noise, v28) | contrasting high ticks and low rumbles |

### Seed motif (1–3–5–6) and finite reuse

The suite Seed (scale degrees 1–3–5–6) appears in **original E minor/Dorian
variants**: the bar-1 statement **E–G–B–C#** (1–3–5–♯6), the bar-2 answer
**B–A–G–F#** (descending 5–4–♭3–2), a mid-phrase **E–G–C–B** variant (bars 3/7),
and a tension-reversal **A#–B–D#–F#** (bar 11) into the final **E–B–E** tonic
cadence. Reuse is finite: **30 pattern instances from 16 source patterns**
(`pulse2` reuses `bE` five times and `bC`/`bA` twice; `noise` reuses `n1` four
times, `n2`/`n3` three times, `n4` twice). No runtime loop, no repeated-note
inflation.

### Complexity rationale (moderate)

Complexity lives in **form and voice interaction**, not note count: three
contrasting 4-bar phrases, a half-diminished development bar, suspension-tones
(A# over B, C# over E) that resolve at the cadence, antiphonal lead/harmony
placement on off-beats, and two distinct noise colours placed off the beat.
116 expanded note events across 12 bars — economical for a moderate cue.

## Measured results (this machine)

All commands exited `0` (tool `atm-music` 1.0.0, engine ATMlib 1.2.4, backend
`progmem`).

| Quantity | Value |
| --- | --- |
| Validation | `ok:true`; 4/4 channels; 30 pattern instances; **116** expanded note events |
| Clock | requested 50 → effective **50 Hz**, **75.0 BPM**, 1920 ticks / 38.4 s |
| `song.json` | 9508 B, sha256 `f4c2e4fa3314412863ad5dcf81e3ad12785bfcc6a3c9dafada7e9bf76923c850` |
| canonical event digest | `235997c9d96566b9c99d9829dac8eb9ee63d2c8ed27051f4c855d2cf25ed39a1` |
| `score.bin` (PROGMEM song asset) | **1104 B**, sha256 `0500442d360d37c1d482e2d0f5268546ee472a134fb86ef5b94faf60d5ee5a48`; `program_bytes` `[446, 253, 159, 231]` |
| `review.json` | 47876 B, sha256 `4550d777c021acf8e085a02a42d115ca3b5f2ddce63ca1fa91c835206e38acce` (**byte-identical** to the build’s `review.json`) |
| `review.html` | 5268047 B, sha256 `58c35c96de9cca4b50cffb007cb464c0c7c9d7b115e5e0753cab6d64054db7e7` |
| `preview/preview.json` | 117278 B, sha256 `f113fb84d212853ef933313ad51a45ab1dee03c7204045b139fa82ded7d8072f` (promoted unchanged from render) |
| `preview/preview.wav` | **3889834 B**, sha256 `07a4a939968ce378f1caeb5955d4639f7529c2d3a8eb6e69a45a624c05715be8`; `pcm-s16le-mono` 50000 Hz, 1944895 samples = **38.8979 s** |
| Render window | requested 39.0 s → effective 38.9 s, `truncated:false`, 1920/1920 ticks |
| First music callback | sample 1045 (0.0209 s), measured |
| Embedded audio match | `review.html` embeds this WAV (`wav_sha256` `07a4a939…`); source + event digests matched (no stale-preview rejection, no warnings) |

**Bytes are asset bytes, not engine or game cost.** `score.bin` = 1104 bytes is
the PROGMEM *song asset only*. It is **not** engine code, not static SRAM and not
a whole-game measurement (`build` does not invoke `arduino-cli`; `avr_measurements.measured = false`).

## Reproduce (run from the repository root)

```
tools/atm-music capabilities --json
tools/atm-music validate examples/music_authoring/creature_gatherer/marsh/song.json --backend progmem --json
tools/atm-music build    examples/music_authoring/creature_gatherer/marsh/song.json --backend progmem \
    --out build/music-authoring/themed-suite/marsh/build --json
tools/atm-music render   examples/music_authoring/creature_gatherer/marsh/song.json --backend progmem \
    --seconds 39 --out build/music-authoring/themed-suite/marsh/render --json
cp build/music-authoring/themed-suite/marsh/render/preview.json \
   examples/music_authoring/creature_gatherer/marsh/preview/preview.json
cp build/music-authoring/themed-suite/marsh/render/preview.wav \
   examples/music_authoring/creature_gatherer/marsh/preview/preview.wav
tools/atm-music inspect  examples/music_authoring/creature_gatherer/marsh/song.json \
    --audio-preview examples/music_authoring/creature_gatherer/marsh/preview \
    --out examples/music_authoring/creature_gatherer/marsh/review.html --json
```

Intermediates, command logs and the catalog fragment live only under
`build/music-authoring/themed-suite/marsh/`.

## Audio limitations (read honestly)

- Mono emulated speaker mix; a single WAV cannot isolate one channel. Viewer
  lane checkboxes are **visibility only**.
- Viewer **Piezo (approx.)** is uncalibrated browser coloration, not a measured
  device response; Raw emulator is default. Check on device.
- Tempo is timer-quantized; reported BPM is derived. After the score ends the
  stopped PWM leaves a constant DC rail (≈ −2000, zero AC) — acoustically
  silent, not neutral 0.
- **No browser/hardware listening verification is claimed.** Numeric evidence
  proves gates, timing, silence, digests and determinism — not taste.

## Limitations / status

- **No FX export, no FX integration** (`--backend fx` → `BACKEND_UNAVAILABLE`).
- Reusable finite patterns and `repeat` keep the asset small; no runtime looping.
- No changes to `src/`, `tools/`, `schemas/`, `tests/`, `research/`, existing
  songs or shared catalog/player/docs. No git operations.
