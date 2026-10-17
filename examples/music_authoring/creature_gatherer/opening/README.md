# First Light — Opening (rich main/title theme)

## Current revision — 2026-10-17 (ATMlib2FX-awr)

Title theme; a full opening melody, a lower reprise and cleaner chord transitions.

**E minor · 115.38 BPM · 24 bars · 2496 ticks · 49.92 s per loop.**
The source sets `"loop": true`; the original PROGMEM engine restarts all tracks
on the same callback. The [review](review.html) defaults **Loop** on and repeats
one cycle with measured startup and capture tail excluded from playback.

Current [WAV](preview/preview.wav) and [render report](preview/preview.json) were
regenerated from this source through AVR/absim; the capture includes a cycle
plus 0.5 s of the next iteration. PROGMEM asset: **2511 B**.
WAV SHA-256: `1204307a7e5a2fbd02094f14308dc81141b4cbace2b11054dd2d3553cc8b2f8a`.

[All-song player](../../player.html) · [source](song.json) · [canonical review](review.json).

## Historical first-version notes

The descriptions, numbers and captured paths below record the original finite
composition. Current timing, looping and media are described above. These
notes retain their original provenance; linked working assets now use the
current revision.

Original four-channel ATMlib cue for the **Creature Gatherer FX** title screen /
opening. This is a model-authored **candidate PROGMEM composition** built with
this repository's own `atm-music` CLI — not FX music, not a shipped asset, and
not copied, transposed or imitated from any existing song. No external code or
music was cloned, fetched, downloaded, vendored or copied. No git operations.

- **Context:** opening title / main theme while the player begins a new run.
- **Key / mode:** E minor (natural minor with raised 7th, D#, as harmonic colour).
- **Form:** 24 bars of 4/4 — Intro (bars 1–4) · Development A (5–12) ·
  Contrasting bridge in C major (13–16) · Reprise (17–24, hook returns and lifts
  an octave before the tonic cadence).
- **Clock / tempo:** `tick_rate` 50, `ticks_per_beat` 25, `beats_per_bar` 4 →
  integer effective **50 Hz**, derived **120.0 BPM**.
- **Duration:** 2400 ticks = **48.0 s** of music; render adds a 0.5 s tail
  (48.5 s, not truncated).
- **Complexity:** **rich** — 20 finite patterns, four active voices, a
  coordinated countervoice, dense noise in full sections and deliberately sparse
  intro/bridge bars.

## Channel roles

| Channel | Instrument | Role |
| --- | --- | --- |
| `pulse0` | `lead` (vol 92, duty 96) | Hook melody: intro pickup, A/B development, bridge long tones, octave-lifted reprise. |
| `pulse1` | `counter` (vol 46, duty 32) | Coordinated countervoice: seed-contour arpeggios in the intro, off-beat answer figures under the lead, sparse echo in the bridge, sixth/third harmony in the reprise. |
| `pulse2` | `bass` (vol 78, duty 200) | Root/fifth bass: walking eighths under development, sustained half-bar pedal tones in the bridge. |
| `noise` | `kick`/`hat` (vol 62/28) | Intentional percussion: near-silent intro, steady kick/hat in full sections, one kick and one hat only through the bridge. |

## Motif relationships and finite reuse

The suite **Seed motif (scale degrees 1–3–5–6)** is transformed here, not copied:
the hook states **E–G–B–C** (1–3–5–6) as a long–short–short pickup, then
develops it with a raised 7th (D#) and an inverted descent; the countervoice
re-states the contour a sixth below and the reprise lifts it an octave
(E6–G6–B6–C7). Nothing reuses existing song phrases verbatim.

Reuse is finite and measured: `leadA`, `cntA`, `bassA` and `percA` are each
reused exactly once for the reprise (bars 17–20), so the 24-bar arrangement
expands from 20 distinct patterns with no runtime looping. `repeat` is always 1;
repetition is structural, not brute-force.

## Measured results (this machine)

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `song.json` source | 19439 | `87c03326855842a0bd4c3cdae01fe5245a043f9fdfd3397dcc4c72b262030c4f` |
| `score.bin` **PROGMEM song asset** | **2444** | `df83479c9b15f6e4d043900e36f1a2b1baa0586d0a6e2739823d5b8dc73c7db9` |
| `preview/preview.wav` | 4849834 | `c79a41a155612be9ad41fda1f3020348c448df0cd5f8e6810c150d2b5fb6c445` |
| `preview/preview.json` (render report) | 162258 | `01b02cab9235bb454bc1dedfe2a8d154f59f69ae4ea44159fa2fcb17b3669cc8` |
| `review.html` (audio embedded) | 6586723 | `667281477ae1b0d97e7abba5f574cd7e6b1aa56974fd95c3ec33b60f12427967` |
| `review.json` (canonical review payload) | 104736 | `46a7ebbb6c73f34bc876d6a53f5878d3e583ecb8275a0d3f6dde01eceba95b95` |

- Canonical event digest (`atmlib-canonical-events-v1`):
  `73a344fbdc270bbc690248bafb5520776815cd810be382b1079161cb5f69724a`
- Channel note counts: `pulse0` 72, `pulse1` 83, `pulse2` 44, `noise` 80;
  expanded note events 279 over 24 pattern instances.
- `review.json` is **byte-identical** to the build's `review.json`; the viewer
  embedded the matching WAV (`wav_sha256` equals the rendered `preview.wav`,
  source/event digests matched — no stale-preview rejection).
- The `preview/preview.json` render report is copied unchanged from
  `build/music-authoring/themed-suite/opening/render.json`; its embedded command
  paths are historical build paths, and the promoted WAV resolves beside it.

**`score.bin` = 2444 bytes is the PROGMEM song asset only.** It is **not** engine
code, not static SRAM and not a whole-game memory measurement. The render's
instrumented fixture reports 8688 program bytes / 332 data bytes (core + ATMlib +
score + speaker enable) — a preview fixture, not a production or whole-game cost.
Engine footprint is tracked separately in `research/fx/fx-footprint-results.md`.

## Reproduce (from the repository root)

```
tools/atm-music validate examples/music_authoring/creature_gatherer/opening/song.json --backend progmem --json
tools/atm-music build    examples/music_authoring/creature_gatherer/opening/song.json --backend progmem \
    --out build/music-authoring/themed-suite/opening/build --json
tools/atm-music render   examples/music_authoring/creature_gatherer/opening/song.json --backend progmem \
    --seconds 120 --out build/music-authoring/themed-suite/opening/render --json
tools/atm-music inspect  examples/music_authoring/creature_gatherer/opening/song.json \
    --audio-preview examples/music_authoring/creature_gatherer/opening/preview \
    --out examples/music_authoring/creature_gatherer/opening/review.html --json
```

All four commands exited `0`. Full JSON payloads, stderr logs and hashes are under
`build/music-authoring/themed-suite/opening/`.

## Honest limitations

- The WAV is the emulated **mono speaker mix**; a single file cannot isolate one
  channel. Viewer lane checkboxes are **visibility only** and never change audio.
- The offline viewer offers **Raw emulator** (default) and **Piezo (approx.)**;
  Piezo is an uncalibrated browser-only coloration, not a measured device
  response. Check on device.
- Tempo is timer-quantized; reported BPM is derived, not stored. After the score
  ends the stopped PWM leaves a constant DC rail (≈ −2000, zero AC) —
  acoustically silent, not neutral 0.
- **Sound quality was not judged here.** The recorded numbers prove gates,
  timing, silence, digests and determinism — not taste. No browser or hardware
  listening test was performed for this cue.
- `--backend fx` is unavailable (`BACKEND_UNAVAILABLE`, pending ATMlib2FX-hlh.2 /
  ATMlib2FX-3ii.3). This is a candidate PROGMEM composition, not FX music.
