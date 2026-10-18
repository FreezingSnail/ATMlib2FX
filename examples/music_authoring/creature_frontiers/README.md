# Creature Frontiers

Seven original, looping chiptune cues for a creature-gathering RPG, composed with
ATMlib2FX's local **atm-music** skill and authoring CLI.

Open the [library song player](../player.html) in a browser, pick the
**Creature Frontiers** folder, and choose a cue to play its embedded AVR audio
and inspect the synchronized score. It is self-contained and works offline.
Each cue also has a standalone review, editable JSON source, and WAV.

| Cue / game role | Key | BPM | Meter | Bars | Loop | Score asset |
| --- | --- | ---: | --- | ---: | ---: | ---: |
| [Pocket Nursery](pocket_nursery/review.html) — village / nursery | D major | 88.24 | 3/4 | 16 | 32.64 s | 1655 B |
| [Cloverbound Route](cloverbound_route/review.html) — daytime gathering | G major | 136.36 | 4/4 | 16 | 28.16 s | 3449 B |
| [Lanternfen](lanternfen/review.html) — dusk / rare-creature habitat | E minor | 75.00 | 4/4 | 12 | 38.40 s | 1000 B |
| [Bramble Skirmish](bramble_skirmish/review.html) — wild encounter | D minor | 176.47 | 4/4 | 16 | 21.76 s | 4106 B |
| [Prism Burrow](prism_burrow/review.html) — crystal cave / hidden nests | F# minor | 100.00 | 4/4 | 16 | 38.40 s | 1505 B |
| [New Wings](new_wings/review.html) — evolution / companion celebration | A major | 150.00 | 4/4 | 12 | 19.20 s | 2385 B |
| [Snapdragon Sprint](snapdragon_sprint/review.html) — speedy dash / time-trial | E major | 187.50 | 4/4 | 16 | 20.48 s | 3198 B |

Together: **199.04 seconds** per cycle and **17298 bytes** of generated PROGMEM
song assets. Asset sizes describe songs only, not engine or whole-game costs.

## Arrangement and synth techniques

- **Pocket Nursery:** a lilting question-and-answer waltz, rounded pulse melody,
  root–chord bass, plucked upper accompaniment, quiet answers and noise brushes.
- **Cloverbound Route:** a dotted ascending hook with descending answers,
  eighth-note chord arpeggios, offbeat bass, contrasting pulse duties and a
  regular noise backbeat.
- **Lanternfen:** slow, spacious minor phrases; alternating thin and wider pulse
  presets; restrained echoes during lead rests; held bass and sparse rustles.
  D# supplies the leading tone over the B-major dominant.
- **Bramble Skirmish:** short gated riffs, sixteenth-note broken chords,
  syncopated root/fifth/octave bass, pulse-duty accents and short noise fills.
  A-major dominant phrases return to D minor at the loop boundary.
- **Prism Burrow:** displaced arpeggios, separated registers, quiet delayed
  repeats, bass pedals and sparse noise sparkles. C# major returns to F# minor;
  its E# is written F because the source format uses natural/sharp spellings.
- **New Wings:** octave-lift fanfare, chord-tone support, bright arpeggios,
  contrasting accent presets, root/octave bass and a rising noise fill.
- **Snapdragon Sprint:** fast staccato E-major hook over a root/octave bass and
  noise backbeat; the middle voice runs hardware arpeggio windows (two-and
  three-step chord cycles), one block swells through a volume slide with
  tremolo shimmer, and a note-cut chatter accelerando drives the loop
  turnaround. First cue in the suite to use the engine `effects` keys.

The six note-authored cues use the three monophonic pulse voices and noise
voice with fixed instrument presets; their arpeggios are explicitly authored
notes. **Snapdragon Sprint** additionally uses the additive pattern
`effects` keys (engine `arpeggio`, `note_cut`, `slide`, `lfo`), which are
available for PROGMEM scores and rejected by the finite-v1 FX adapter. Noise
note tokens control noise behavior, rather than selecting sampled drums.

All cues use a real 100 Hz clock, with distinct ticks-per-beat values. Tempos are
actual playback rates. Every final dominant/pickup leads into the opening tonic;
there is no terminal fade or repeat-only introduction.

## Files and validation

Each cue folder contains `song.json`, `review.html`, canonical `review.json`,
and the matching `preview/preview.wav` and `preview/preview.json` pair.
[suite.json](suite.json) records form, chords, tempo and techniques.
[catalog.json](catalog.json) is the suite-local source list written by the
composer; the library-wide catalog aggregates these entries for the bundled
player.

[verification.json](verification.json) records the final source, event and WAV
hashes and checks. All seven scores pass CLI validation, have full untruncated
AVR emulator captures with measured startup offsets, and contain active audio.
For every channel at every tick across two engine trace cycles plus the next
opening tick, pitch, volume, gate state, pulse duty and tempo match the expanded
score; effect scores are checked against the effect-aware predictor
(`tools/atm-trace-verify`), which models arpeggio, note-cut, slide and LFO state
changes. All promoted previews and player entries match their final source
hashes.

The audio is the actual emulated mono speaker mix. No listening assessment,
browser walkthrough or physical-device test was performed. The player's Piezo
option is an uncalibrated approximation. This suite has no FX export or game
integration.

The suite was authored in a temporary workspace
(`/Users/connorfranc/code/memory`) by an earlier session that read the library
from this repository. It was promoted into
`examples/music_authoring/creature_frontiers/` on 2026-10-17; the library's
other compositions were left intact. Snapdragon Sprint was added on 2026-10-18,
authored directly as `song.json` against the engine `effects` contract (the
`compose.py` note-data generator does not emit effect windows). The commands
below use the relocated inputs; regenerating replaces the historical workspace
paths in the promoted preview and review reports. Re-rendering the six earlier
cues with the current library refreshes their captures; the recorded per-cue
audio metrics may move slightly from the original memory-workspace renders.

## Reproduce locally

The authoring and verification scripts, command logs, generated score assets,
AVR images and two-cycle engine traces are retained in
`../../../build/creature-frontiers/` relative to this folder.
Run the following from the repository root with the Arduino toolchain and
Ardens build installed:

```sh
python3 research/music-authoring/creature-frontiers/compose.py   # six note-authored cues
python3 research/music-authoring/creature-frontiers/render_suite.py   # renders and promotes all seven
python3 tools/music_authoring/library_player.py \
  --root . \
  --catalog examples/music_authoring/catalog.json \
  --out examples/music_authoring/player.html \
  --report build/creature-frontiers/main-player-report.json --json
python3 research/music-authoring/creature-frontiers/verify_suite.py
```

Snapdragon Sprint's source is maintained directly as
`snapdragon_sprint/song.json`; `render_suite.py`, the library player and the
suite verifier consume it from there.

The portable deliverables are the scores, preview pairs, standalone reviews and
the library player. Captured reports preserve the original local build paths as
provenance.
