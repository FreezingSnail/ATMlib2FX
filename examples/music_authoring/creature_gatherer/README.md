# Creature Gatherer FX — candidate chiptune suite (ATMlib2FX-3ii.11)

## Current looping revision — 2026-10-17

All eleven cues have revised harmony, pacing and turnarounds, with refreshed
AVR/absim captures. Open the [offline library player](../player.html); Loop is on
by default. See the [current song library](../README.md) for the complete table
and validation details. Each cue README leads with its current measurements.

| Cue | BPM | Bars | Cycle | PROGMEM asset |
| --- | ---: | ---: | ---: | ---: |
| [Gatherer's Road — Overworld](overworld/review.html) | 136.36 | 16 | 28.16 s | 2202 B |
| [Clash of Gatherers — Combat](combat/review.html) | 176.47 | 16 | 21.76 s | 2041 B |
| [Hollow Depths — Cave Exploration](exploration/review.html) | 83.33 | 12 | 34.56 s | 756 B |
| [Gathered! — Victory](victory/review.html) | 187.50 | 4 | 5.12 s | 499 B |
| [Lost — Defeat](defeat/review.html) | 68.18 | 4 | 14.08 s | 292 B |
| [First Light — Opening](opening/review.html) | 115.38 | 24 | 49.92 s | 2511 B |
| [Hearth and Hollow — Village](village/review.html) | 93.75 | 8 | 20.48 s | 654 B |
| [Greenwake Thicket — Forest](forest/review.html) | 130.43 | 16 | 29.44 s | 2244 B |
| [Tideline Ramble — Coast](coast/review.html) | 107.14 | 12 | 26.88 s | 1082 B |
| [Marsh at Dusk — wetland gathering](marsh/review.html) | 78.95 | 8 | 24.32 s | 563 B |
| [Ancient Observatory — ruins boss gate](ruins/review.html) | 125.00 | 24 | 46.08 s | 2684 B |



## Historical first-version composition and measurements

The material below preserves the original finite-suite design and captured
measurements. Current sources and media use the looping revision above.

Eleven **original** four-channel ATMlib cues composed for the Creature Gatherer FX
game context (title opening, home village, gathering overworld, turn-based
creature combat, cave/forest/coast/marsh/ruins exploration, and win/lose
outcomes). They are **model-authored candidate compositions built
with this repository’s own `atm-music` CLI** — not FX music, not a shipped asset,
and not copied, transposed or imitated from any existing song. No external code
or music was cloned, fetched, downloaded, vendored or copied.

Every cue is a valid `atmlib-score` v1 source, compiles to a deterministic PROGMEM
asset, renders to a real AVR (absim) WAV of the full song plus tail, and has a
standalone offline review page with the matching WAV embedded.

All eleven cues are also collected, with the repository's other example songs, in
the single offline [example song library player](../player.html); open it directly
to select and review any song in one page.

## Cues

| Cue | State | Complexity | Key | BPM | Bars | Ticks | Score | PROGMEM `score.bin` | WAV | Review |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- |
| [Opening “First Light”](opening/README.md) | title / main theme | rich | E minor | 120.0 | 24 | 2400 | 48.0 s | **2444 B** | [wav](opening/README.md#measured-results-this-machine) | [review.html](opening/review.html) · [source](opening/song.json) |
| [Village “Hearth and Hollow”](village/README.md) | home / nursery | simple | C major | 100.0 | 8 | 960 | 19.2 s | **623 B** | [wav](village/README.md#measured-results-this-machine) | [review.html](village/review.html) · [source](village/song.json) |
| [Overworld “Gatherer’s Road”](overworld/README.md) | field/overworld | moderate | A minor | 120.0 | 16 | 1600 | 32.0 s | **2175 B** | [wav](overworld/README.md#measured-results-this-machine) | [review.html](overworld/review.html) · [source](overworld/song.json) |
| [Combat “Clash of Gatherers”](combat/README.md) | battle | moderate | D minor | 240.0 | 16 | 1600 | 16.0 s | **2011 B** | [wav](combat/README.md#measured-results-this-machine) | [review.html](combat/review.html) · [source](combat/song.json) |
| [Forest “Greenwake Thicket”](forest/README.md) | living woodland | moderate | A dorian | 125.0 | 16 | 1536 | 30.72 s | **2225 B** | [wav](forest/README.md#measured-results-this-machine) | [review.html](forest/review.html) · [source](forest/song.json) |
| [Coast “Tideline Ramble”](coast/README.md) | shoreline route | simple | G major | 100.0 | 12 | 1440 | 28.8 s | **1079 B** | [wav](coast/README.md#measured-results-this-machine) | [review.html](coast/review.html) · [source](coast/song.json) |
| [Marsh “Marsh at Dusk”](marsh/README.md) | wetland | moderate | E dorian | 75.0 | 12 | 1920 | 38.4 s | **1104 B** | [wav](marsh/README.md#measured-results-this-machine) | [review.html](marsh/review.html) · [source](marsh/song.json) |
| [Ruins “Ancient Observatory”](ruins/README.md) | boss-gate ruins | rich | B harmonic minor | 120.0 | 24 | 4800 | 48.0 s | **2673 B** | [wav](ruins/README.md#measured-results-this-machine) | [review.html](ruins/review.html) · [source](ruins/song.json) |
| [Exploration “Hollow Depths”](exploration/README.md) | cave | simple | A minor | 120.0 | 12 | 1200 | 24.0 s | **702 B** | [wav](exploration/README.md#measured-results-this-machine) | [review.html](exploration/review.html) · [source](exploration/song.json) |
| [Victory “Gathered!”](victory/README.md) | outcome | simple | C major | 240.0 | 4 | 400 | 4.0 s | **488 B** | [wav](victory/README.md#measured-results-this-machine) | [review.html](victory/review.html) · [source](victory/song.json) |
| [Defeat “Lost”](defeat/README.md) | outcome | simple | A minor | 120.0 | 4 | 400 | 8.0 s | **257 B** | [wav](defeat/README.md#measured-results-this-machine) | [review.html](defeat/review.html) · [source](defeat/song.json) |

Complexity labels follow the suite's asset-size soft targets (simple ≈ ≤1 KiB,
moderate ≈ ≤3 KiB, rich ≈ ≤6 KiB) together with arrangement density; they are
musical/asset descriptors, not whole-game measurements. The six newest cues
(opening, village, forest, coast, marsh, ruins) were added by ATMlib2FX-3ii.13;
the original five remain as previously measured.

Each tracked channel is monophonic with non-overlapping gates; all four channels
(`pulse0` lead, `pulse1` harmony/countervoice, `pulse2` bass, `noise`
percussion) are used in every cue. Total suite audio across the eleven cues:
**297.12 s**. Total PROGMEM asset: **15781 B** (original five 5633 B + six new
10148 B).

## Shared musical identity — “the Seed” motif

One short motif unifies the suite: an **ascending tonic-triad outline that lifts to
the 6th — scale degrees 1–3–5–6**, phrased long–short–short–long. It is adapted per
mood:

| Cue | Motif realisation |
| --- | --- |
| Overworld | minor **A–C–E–F**, stated and developed over an AABA′ form |
| Combat | minor **D–F–A–A#**, driven as fast eighth-note riffs in D minor |
| Exploration | the same interval shape low and slow, stated at half speed |
| Victory | **major** form **C–E–G–A** as a bright fanfare |
| Defeat | the **retrograde** (♭6–5–♭3–1) as a slow descending mirror |
| Opening | minor **E–G–B–C** stated long–short–short, developed with the raised 7th (D#) and lifted an octave in the reprise |
| Village | **major** form **C–E–G–A** answered by a gentle diatonic descent to the tonic |
| Forest | A dorian **A–C–E–F#** as a curious call with a lower answer phrase |
| Coast | G major **G–B–D–E** over a rocking root-fifth bass |
| Marsh | E dorian **E–G–B–C#** (raised 6th) as controlled colour resolving to E |
| Ruins | B harmonic minor **B–D–F#–G** with the A# leading tone, phrased in 3+3+2 |

All patterns are finite and reused (`repeat` 1–7); nothing expands into brute-force
unique bars. Integer timer clocks only (`tick_rate` 50 or 100 → integer effective
50/100 Hz) to avoid the open fractional-clock issue ATMlib2FX-3ii.8; BPM is derived
from the quantized rate.

## Intended game context (read-only reference)

Context was read from `/Users/connorfranc/code/creaturegather/CreatureGathererFX`
(`README.md`, `Notes/Gameplay Loop.md`, `Notes/Design Notes.md`) for mood only —
gathering in the field, random-encounter turn-based combat versus 1–3 creatures,
lure zones and boss gates. **No game file was modified, and no existing song was
copied.** The game repo is not touched by this work.

## Reproduce everything

Run from the repository root. stdout is one JSON document; human logs go to stderr.
Exit codes: `0` success, `2` invalid score / unsupported capability, `3` tool/build/render failure.

```
for s in opening village overworld combat forest coast marsh ruins exploration victory defeat; do
  tools/atm-music validate examples/music_authoring/creature_gatherer/$s/song.json --backend progmem --json
  tools/atm-music build    examples/music_authoring/creature_gatherer/$s/song.json --backend progmem \
      --out build/music-authoring/creature_gatherer/$s/build --json
  tools/atm-music render   examples/music_authoring/creature_gatherer/$s/song.json --backend progmem \
      --seconds <song+tail> --out build/music-authoring/creature_gatherer/$s/preview --json
  tools/atm-music inspect  examples/music_authoring/creature_gatherer/$s/song.json \
      --audio-preview build/music-authoring/creature_gatherer/$s/preview \
      --out examples/music_authoring/creature_gatherer/$s/review.html --json
done
```

`--seconds` used per cue (all far below the 300 s cap; each render is bounded to
song + 0.5 s tail and reported `truncated:false`): original five — overworld 40,
combat 20, exploration 28, victory 6, defeat 10; six new cues (ATMlib2FX-3ii.13)
— opening 120, village 120, forest 32, coast 30, marsh 40, ruins 120. The six new
cues' full command JSON, logs and hashes are recorded under
`build/music-authoring/themed-suite/<cue>/`; the original five remain summarised
under `build/music-authoring/creature_gatherer/` and its `EVIDENCE.md`.

## Source / event identity (all cues)

| Cue | `song.json` sha256 | canonical event digest |
| --- | --- | --- |
| Opening | `87c03326855842a0bd4c3cdae01fe5245a043f9fdfd3397dcc4c72b262030c4f` | `73a344fbdc270bbc690248bafb5520776815cd810be382b1079161cb5f69724a` |
| Village | `00b707100967a9b41caab41e8647b6a623d45e20731c841562c7f978fe5ae558` | `01f2d905b33386c98f481570d6e73274ae4c8f78d214a3ce8314939d49976bb0` |
| Overworld | `43aea1283e8eda2e68e7ff2ca59412bbb537762213d11c046f25511fb1f2d3d9` | `7ed41805e93b7e0ff769055ab5959afd22d8e893c2fbe3d0b832e25b2e78c582` |
| Combat | `d34dca2c2c9d0bcadd5c1bd9eb321a659150fe40a52ed2ffdbd7a6f852a4c1f1` | `c1ec59d706fbe51a2aceb0380b29a56e2e3a35ae56d1c23e331a6aa41bcc3c0e` |
| Forest | `b0b3748c8470d9d9415059e2c52ccfea467aafa83daa7317c1ad3e5b55994d99` | `f7aeb53aa57307d805d34c15bb71817fd86df29fdf2a20ce8f8c29a73248d2d4` |
| Coast | `4ee5d8722beef208476068d6acfd9f77c1f2d15cb77ae6c15d3a731de19bae51` | `1617153ab312224aa347b0b1311ee570a25726326732f3edf92d063dd28a6098` |
| Marsh | `f4c2e4fa3314412863ad5dcf81e3ad12785bfcc6a3c9dafada7e9bf76923c850` | `235997c9d96566b9c99d9829dac8eb9ee63d2c8ed27051f4c855d2cf25ed39a1` |
| Ruins | `551c1123c17bdb8e6aac70170950b4fa31f1aa2fab128b4d45b1bb34222665c9` | `7f663c859c5de410a8ba3ab4813c5a1de4bbd12e5f9351f97df3a73dd265890a` |
| Exploration | `146b2f0883eddaefff77b05136ae387e60180091a842ea4327a0632ffaff40a9` | `2c62ee88eecc506421f31acdd065855d75d9db6c77e73394f24800a8ab45dd1a` |
| Victory | `1252eff1cdf1abef9b70d202c21d560304c4f69088b5a3f5c32284ae4d069bc7` | `39b0c6bfd4a94de0a358473b36c9eac33253ce4dea4032a74bc1478c56098aca` |
| Defeat | `3c4a40c31fa0a592dc2f7b77775661d96b0cbe5125c7d6cdcc841032bc79192e` | `f0ec20961a487f56f1a2b5848c08f0ba0e8095b34669110fe539a6cbf0a0ac0e` |

For every cue the durable `review.json` is **byte-identical** to the build’s
`review.json` (canonical `atmlib-review` payload), and the `review.html` embeds the
matching WAV (its `wav_sha256` equals the rendered `preview.wav`). Source and event
digests matched at inspect time (no stale-preview rejection).

## Audio limitations

- The WAV is the emulated **mono speaker mix**; a single file cannot isolate one
  channel. Viewer lane checkboxes are **visibility only** and never change audio.
- The offline viewer offers **Raw emulator** (default) and **Piezo (approx.)**.
  Piezo is an **uncalibrated** browser-only coloration, not a measured Arduboy
  piezo/enclosure response and not a loudness prediction. Check on device.
- Tempo is timer-quantized; reported BPM is derived. After the score ends, the
  stopped PWM leaves a constant DC rail (≈ −2000, zero AC) — acoustically silent,
  not neutral 0.
- Sound-quality judgement is the listener’s job. The recorded numbers prove gates,
  timing, silence, digests and determinism — not taste.

## Scope, status and blockers

- **No FX export / no FX integration.** `--backend fx` is unavailable
  (`BACKEND_UNAVAILABLE`, pending the architecture decision in ATMlib2FX-hlh.2 and
  the adapter in ATMlib2FX-3ii.3). These are **candidate PROGMEM compositions**,
  not FX music; do not read `score.bin` bytes as FX or whole-game cost.
- **Integer clocks only** by design; no fractional effective rate is requested.
- Reusable finite patterns and `repeat` arrangements limit asset size (largest cue
  2673 B, ruins); no runtime looping is produced or claimed.
- Authoring adds nothing to `src/`; only this directory and the git-ignored
  `build/music-authoring/creature_gatherer/` (original five) and
  `build/music-authoring/themed-suite/` (six new cues) were written.
- **Blockers:** production FX export/ABI (external, not in scope here). No tool
  failures were encountered; all `validate`/`build`/`render`/`inspect` runs exited `0`.
- Intermediate compiler caches and the native absim harness were removed after the
  final artifacts were produced; retained evidence is the WAV/report/trace and logs.
