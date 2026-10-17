# Creature Gatherer FX — Ruins: “Ancient Observatory” (ATMlib2FX-3ii.13.3)

## Current revision — 2026-10-17 (ATMlib2FX-awr)

Ruins theme; retained leading-tone tension, softer diminished passages and a lower upper register.

**B minor · 125.00 BPM · 24 bars · 4608 ticks · 46.08 s per loop.**
The source sets `"loop": true`; the original PROGMEM engine restarts all tracks
on the same callback. The [review](review.html) defaults **Loop** on and repeats
one cycle with measured startup and capture tail excluded from playback.

Current [WAV](preview/preview.wav) and [render report](preview/preview.json) were
regenerated from this source through AVR/absim; the capture includes a cycle
plus 0.5 s of the next iteration. PROGMEM asset: **2684 B**.
WAV SHA-256: `2697ebcc3903002269d7950ff0053d8ecdd3918cba0b2a1742c8a762da448968`.

[All-song player](../../player.html) · [source](song.json) · [canonical review](review.json).

## Historical first-version notes

The descriptions, numbers and captured paths below record the original finite
composition. Current timing, looping and media are described above. These
notes retain their original provenance; linked working assets now use the
current revision.

Candidate original cue for the Creature Gatherer FX *ancient ruins / observatory
boss-gate* exploration state. **Model-authored composition**, compiled only
through `progmem`; not integrated FX music, not a production asset. **Not**
copied/transposed/imitated from any existing song; no external code or music was
cloned, fetched, downloaded, vendored or copied.

- **Source:** [`song.json`](song.json) (`id` `cg_ruins_v1`)
- **Offline review (embedded audio):** [`review.html`](review.html)
- **Canonical viewer payload:** [`review.json`](review.json)
- **Promoted preview pair:** [`preview/preview.json`](preview/preview.json) · [`preview/preview.wav`](preview/preview.wav)
- **Suite build fragment:** `build/music-authoring/themed-suite/ruins/catalog-entry.json`

## Intended game context

Approach to an ancient observatory / boss gate inside the ruins: driving,
ritualistic pulse, interlocking counter-lines, harmonic tension from diminished
chords and the A# leading tone, a bridge that opens outward, and a developed
reprise that returns to the gate. Distinct from the cave cue (“Hollow Depths”,
A natural minor, slow drips): this is **B harmonic minor**, fast 3+3+2 accent
grouping, four active mono voices in counterpoint.

## Musical form

- **Key / mode:** B harmonic minor (B C# D E F# G A#); A# is the leading tone
  and C#/A# diminished sonorities carry the tension.
- **Meter:** 4/4. **Length:** 24 bars = 4800 ticks. One bar = 200 ticks.
- **Effective BPM:** **120.0** (requested `tick_rate` 100 → integer effective
  100 Hz; `ticks_per_beat` 50, `beats_per_bar` 4). An eighth = 25 ticks, so the
  **3+3+2** accents fall on ticks 0, 75 and 150 of each bar.
- **Duration:** **48.0 s** score; render **48.5 s** (song + 0.5 s tail),
  `truncated:false`, 4800/4800 ticks.
- **Form:** A (statement) – bridge (tension) – A′ (developed reprise):

  | Bars | Section | Harmony (per bar) | Note |
  | --- | --- | --- | --- |
  | 1–8 | A | Bm · G · Em · F#7 · Bm · D · G · F#7 | Seed statement on 3+3+2; counter-line answers in the gaps |
  | 9–16 | Bridge | Em · C#dim · D · F#7 · Bm · G · A#dim · F#7 | diminished tension, rising sequence, climax on V |
  | 17–20 | A′ reprise | Bm · G · Em · F#7 | original A material returns, re-voiced by accompaniment |
  | 21–24 | cadence | F#7 · Bm · G · Bm | developed ending: G6–F#6–D6–B5 over a tonic arrival |

- **Channel roles** (monophonic, non-overlapping gates):

  | Channel | Instrument | Role |
  | --- | --- | --- |
  | `pulse0` | `lead` (pulse, v86, duty 64) | main theme, accented on 0/75/150 |
  | `pulse1` | `counter` (pulse, v52, duty 32) | interlocking counter-line on the off-accents 25/100/175 |
  | `pulse2` | `bass` (pulse, v76, duty 192) | driving 3+3+2 root/fifth bass |
  | `noise` | `metal` (noise, v38) / `rumble` (noise, v26) | high metallic tick and low rumble, offset from the grid |

### Seed motif (1–3–5–6) and finite reuse

The suite Seed (1–3–5–6) appears in the original **B harmonic-minor** form:
bar 1 states **B–D–F#** (1–3–5) and lifts to **G** (♭6) at bar 2 (1–3–5–♭6),
then the line sequences upward in L_B/L_C, darkens through the A# diminished
bridge (**A#–C#–E**), and the developed reprise ends the Seed as
**G6–F#6–D6–B5** over the tonic cadence. Reuse is finite: **24 pattern instances
from 20 source patterns** (L_A/H_A/B_A/N_A each recur once in the reprise).
Bass and noise patterns are 3+3+2 variants rather than brute-force unique bars.

### Complexity rationale (rich)

Complexity is **arrangement and development**, not note count: a 24-bar
three-part form with a genuine bridge and a developed reprise; **interlocking
pulse counterpoint** (lead accents on 0/75/150 answered by the counter-line on
25/100/175, gates never overlapping); 3+3+2 rhythmic grouping in every voice;
harmonic tension through C#dim and A#dim plus the A# leading tone; and two
contrasting noise colours. 277 expanded note events over 48 s — rich because of
form, harmony and four-voice interaction, not repeated notes.

## Measured results (this machine)

All commands exited `0` (tool `atm-music` 1.0.0, engine ATMlib 1.2.4, backend
`progmem`).

| Quantity | Value |
| --- | --- |
| Validation | `ok:true`; 4/4 channels; 24 pattern instances; **277** expanded note events |
| Clock | requested 100 → effective **100 Hz**, **120.0 BPM**, 4800 ticks / 48.0 s |
| `song.json` | 20098 B, sha256 `551c1123c17bdb8e6aac70170950b4fa31f1aa2fab128b4d45b1bb34222665c9` |
| canonical event digest | `7f663c859c5de410a8ba3ab4813c5a1de4bbd12e5f9351f97df3a73dd265890a` |
| `score.bin` (PROGMEM song asset) | **2673 B**, sha256 `ed4a71a8760dc8dfc261f5b61cf4806aa76a02f977ab235659377e69b9c70652`; `program_bytes` `[747, 721, 716, 474]` |
| `review.json` | 102698 B, sha256 `cff99ca21128b31963b5627f1e193fefcaaeaac2128f3024b5f014082f92eb31` (**byte-identical** to the build’s `review.json`) |
| `review.html` | 6584912 B, sha256 `ccab0b09655752ea70a6d2b3102cf9a0011314ce917f912df470078718014c51` |
| `preview/preview.json` | 335122 B, sha256 `1eadb9e57470be0d56094d07a4a81fe82abe1eab0299724d53756b0f17aa9961` (promoted unchanged from render) |
| `preview/preview.wav` | **4849834 B**, sha256 `35b24ebbd165cfaa65b5c9191ac596d7145f061a9f2bbdc1617524c83c8e8920`; `pcm-s16le-mono` 50000 Hz, 2424895 samples = **48.4979 s** |
| Render window | requested 49.0 s → effective 48.5 s, `truncated:false`, 4800/4800 ticks |
| First music callback | sample 1045 (0.0209 s), measured |
| Embedded audio match | `review.html` embeds this WAV (`wav_sha256` `35b24ebb…`); source + event digests matched (no stale-preview rejection, no warnings) |

**Bytes are asset bytes, not engine or game cost.** `score.bin` = 2673 bytes is
the PROGMEM *song asset only*, comfortably under the rich soft target of 6 KiB.
It is **not** engine code, not static SRAM and not a whole-game measurement
(`build` does not invoke `arduino-cli`; `avr_measurements.measured = false`).

## Reproduce (run from the repository root)

```
tools/atm-music capabilities --json
tools/atm-music validate examples/music_authoring/creature_gatherer/ruins/song.json --backend progmem --json
tools/atm-music build    examples/music_authoring/creature_gatherer/ruins/song.json --backend progmem \
    --out build/music-authoring/themed-suite/ruins/build --json
tools/atm-music render   examples/music_authoring/creature_gatherer/ruins/song.json --backend progmem \
    --seconds 49 --out build/music-authoring/themed-suite/ruins/render --json
cp build/music-authoring/themed-suite/ruins/render/preview.json \
   examples/music_authoring/creature_gatherer/ruins/preview/preview.json
cp build/music-authoring/themed-suite/ruins/render/preview.wav \
   examples/music_authoring/creature_gatherer/ruins/preview/preview.wav
tools/atm-music inspect  examples/music_authoring/creature_gatherer/ruins/song.json \
    --audio-preview examples/music_authoring/creature_gatherer/ruins/preview \
    --out examples/music_authoring/creature_gatherer/ruins/review.html --json
```

Intermediates, command logs and the catalog fragment live only under
`build/music-authoring/themed-suite/ruins/`.

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
- Reusable finite patterns and `repeat` keep the asset compact; no runtime loop,
  tempo change or effect is produced or claimed.
- No changes to `src/`, `tools/`, `schemas/`, `tests/`, `research/`, existing
  songs or shared catalog/player/docs. No git operations.
