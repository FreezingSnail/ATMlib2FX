# Hearth and Hollow — Village (simple home / creature nursery theme)

## Current revision — 2026-10-17 (ATMlib2FX-awr)

Gentle home-village tune; chord-aligned lead and a dominant turnaround into the opening.

**C major · 93.75 BPM · 8 bars · 1024 ticks · 20.48 s per loop.**
The source sets `"loop": true`; the original PROGMEM engine restarts all tracks
on the same callback. The [review](review.html) defaults **Loop** on and repeats
one cycle with measured startup and capture tail excluded from playback.

Current [WAV](preview/preview.wav) and [render report](preview/preview.json) were
regenerated from this source through AVR/absim; the capture includes a cycle
plus 0.5 s of the next iteration. PROGMEM asset: **654 B**.
WAV SHA-256: `651d572694e3b0454c24213df8869ac12b4984a93646d15ac77f4efe8aca2e6b`.

[All-song player](../../player.html) · [source](song.json) · [canonical review](review.json).

## Historical first-version notes

The descriptions, numbers and captured paths below record the original finite
composition. Current timing, looping and media are described above. These
notes retain their original provenance; linked working assets now use the
current revision.

Original four-channel ATMlib cue for the **Creature Gatherer FX** home village /
creature nursery. This is a model-authored **candidate PROGMEM composition**
built with this repository's own `atm-music` CLI — not FX music, not a shipped
asset, and not copied, transposed or imitated from any existing song. No external
code or music was cloned, fetched, downloaded, vendored or copied. No git
operations.

- **Context:** safe home village / creature nursery, calm gathering downtime.
- **Key / mode:** C major (diatonic, no accidentals).
- **Form:** 8 bars of 4/4 — A (bars 1–4) then A′ (bars 5–8), a single singable
  antecedent–consequent period ending on the tonic.
- **Clock / tempo:** `tick_rate` 50, `ticks_per_beat` 30, `beats_per_bar` 4 →
  integer effective **50 Hz**, derived **100.0 BPM**.
- **Duration:** 960 ticks = **19.2 s** of music; render adds a 0.5 s tail
  (19.7 s, not truncated).
- **Complexity:** **simple** — 8 finite patterns, one melody voice, restrained
  two-note accompaniment, half-note bass and sparse percussion; no dense
  counterpoint or full-band sections.

## Channel roles

| Channel | Instrument | Role |
| --- | --- | --- |
| `pulse0` | `lead` (vol 82, duty 64) | Singable nursery melody; the only busy voice. |
| `pulse1` | `harm` (vol 40, duty 32) | Restrained off-beat two-note accompaniment (one note per half bar). |
| `pulse2` | `bass` (vol 66, duty 160) | Root/fifth half notes, tonic pedal to close. |
| `noise` | `perc` (vol 34) | Sparse soft ticks, roughly one per bar with a small bar-4/8 lift. |

## Motif relationships and finite reuse

Transforms the suite **Seed motif (1–3–5–6)** into the major mode **C–E–G–A**
(bars 1–2), then answers it with a gentle descent back to the tonic — the same
interval shape as the opening cue but warmer, slower and simpler. Nothing reuses
existing song phrases verbatim.

Reuse is finite and measured: the cue is only 8 patterns (two 4-bar patterns per
channel) expanded once each (`repeat` 1) — economical by construction, with no
runtime looping and no repeated-note inflation.

## Measured results (this machine)

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `song.json` source | 5955 | `00b707100967a9b41caab41e8647b6a623d45e20731c841562c7f978fe5ae558` |
| `score.bin` **PROGMEM song asset** | **623** | `245452aa142ab419f8f3dda46fb7b1ec3495dadd64481f27c47d9abee344d558` |
| `preview/preview.wav` | 1969834 | `a9b53ee96b318b1439684768ca15556299bc14c58544eefd05db3c87ed2c5817` |
| `preview/preview.json` (render report) | 44311 | `2229177fad4e0572d64fe959068fa710fb9061667608f1b5a1a0237d98da1808` |
| `review.html` (audio embedded) | 2693322 | `c01a4421e70d95a9eb666743bc8c8144724efdb2566f526aec02a748067cfb40` |
| `review.json` (canonical review payload) | 25658 | `14d471d6e5bda68e41c6c400e2b67f9d3d0a1583f195c30b81da1c50366d9c1e` |

- Canonical event digest (`atmlib-canonical-events-v1`):
  `01f2d905b33386c98f481570d6e73274ae4c8f78d214a3ce8314939d49976bb0`
- Channel note counts: `pulse0` 22, `pulse1` 16, `pulse2` 15, `noise` 10;
  expanded note events 63 over 8 pattern instances.
- `review.json` is **byte-identical** to the build's `review.json`; the viewer
  embedded the matching WAV (`wav_sha256` equals the rendered `preview.wav`,
  source/event digests matched — no stale-preview rejection).
- The `preview/preview.json` render report is copied unchanged from
  `build/music-authoring/themed-suite/village/render.json`; its embedded command
  paths are historical build paths, and the promoted WAV resolves beside it.

**`score.bin` = 623 bytes is the PROGMEM song asset only.** It is **not** engine
code, not static SRAM and not a whole-game memory measurement. The render's
instrumented fixture reports 6868 program bytes / 332 data bytes (core + ATMlib +
score + speaker enable) — a preview fixture, not a production or whole-game cost.
Engine footprint is tracked separately in `research/fx/fx-footprint-results.md`.

## Reproduce (from the repository root)

```
tools/atm-music validate examples/music_authoring/creature_gatherer/village/song.json --backend progmem --json
tools/atm-music build    examples/music_authoring/creature_gatherer/village/song.json --backend progmem \
    --out build/music-authoring/themed-suite/village/build --json
tools/atm-music render   examples/music_authoring/creature_gatherer/village/song.json --backend progmem \
    --seconds 120 --out build/music-authoring/themed-suite/village/render --json
tools/atm-music inspect  examples/music_authoring/creature_gatherer/village/song.json \
    --audio-preview examples/music_authoring/creature_gatherer/village/preview \
    --out examples/music_authoring/creature_gatherer/village/review.html --json
```

All four commands exited `0`. Full JSON payloads, stderr logs and hashes are under
`build/music-authoring/themed-suite/village/`.

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
