# Example song library

Open [player.html](player.html) to browse all twenty-one demo songs offline. Use the Folder selector to filter Creature Gatherer, Creature Frontiers, or Authoring Examples. Every song loops in both its exported PROGMEM score and the web preview. The
**Loop** checkbox defaults on; turn it off to hear one cycle. Pause, Restart,
seek and Raw/Piezo sound selection remain available.

The 2026-10-17 revision reduces sustained dissonant overlaps, gives each game
state a distinct pace, brings the highest voices down, and replaces terminal
endings with turnarounds. Rhythm timestamps and gates were scaled with the beat
grid, so the tempo changes affect playback. All clocks use exact 50 or 100 Hz.

The Marsh/Tideline follow-up (ATMlib2FX-cfp) replaces Marsh with an eight-bar
natural-minor tune and joins the accidental repeated-note interruptions in
Tideline. Both have freshly rendered matching previews.

| Song | Key | BPM | Bars | Loop | PROGMEM asset |
| --- | --- | ---: | ---: | ---: | ---: |
| [Gatherer's Road — Overworld](creature_gatherer/overworld/review.html) | A minor | 136.36 | 16 | 28.16 s | 2202 B |
| [Clash of Gatherers — Combat](creature_gatherer/combat/review.html) | D minor | 176.47 | 16 | 21.76 s | 2041 B |
| [Hollow Depths — Cave Exploration](creature_gatherer/exploration/review.html) | A minor | 83.33 | 12 | 34.56 s | 756 B |
| [Gathered! — Victory](creature_gatherer/victory/review.html) | C major | 187.50 | 4 | 5.12 s | 499 B |
| [Lost — Defeat](creature_gatherer/defeat/review.html) | A minor | 68.18 | 4 | 14.08 s | 292 B |
| [Showcase — Twilight (A minor)](showcase/review.html) | A minor | 125.00 | 4 | 7.68 s | 406 B |
| [Basic authoring example](basic/review.html) | C major | 125.00 | 2 | 3.84 s | 222 B |
| [Guide sketch — one-bar example](guide/review.html) | C major | 100.00 | 1 | 2.4 s | 140 B |
| [First Light — Opening](creature_gatherer/opening/review.html) | E minor | 115.38 | 24 | 49.92 s | 2511 B |
| [Hearth and Hollow — Village](creature_gatherer/village/review.html) | C major | 93.75 | 8 | 20.48 s | 654 B |
| [Greenwake Thicket — Forest](creature_gatherer/forest/review.html) | A Dorian | 130.43 | 16 | 29.44 s | 2244 B |
| [Tideline Ramble — Coast](creature_gatherer/coast/review.html) | G major | 107.14 | 12 | 26.88 s | 1082 B |
| [Marsh at Dusk — wetland gathering](creature_gatherer/marsh/review.html) | E minor | 78.95 | 8 | 24.32 s | 563 B |
| [Ancient Observatory — ruins boss gate](creature_gatherer/ruins/review.html) | B minor | 125.00 | 24 | 46.08 s | 2684 B |

Each song directory contains the authored source, a matching WAV/report pair,
and a standalone review. Capture reports retain toolchain, source/event/WAV
identities and measured first-callback offsets. WAVs contain a cycle plus 0.5 s
of the next iteration; the browser uses a separate one-cycle playback buffer
without changing the embedded capture.

Validation compares two full original-engine cycles for every song, including
gates, pitch, duty, tempo, delays and active/mute state. All twenty-one restart
without an added callback or channel drift. The finite basic-source goldens are
preserved under `tests/music_authoring/fixtures/basic/`. Browser PCM/transport
and piezo-routing checks run with Node. A live Chrome walkthrough could not run
in this sandbox (Chrome exited before its DevTools endpoint started).

These are original candidate compositions using the local engine; they remain
PROGMEM assets pending FX backend selection. Musical improvement was assessed
from score harmony, voice placement and phrasing; automated checks establish
playback correctness, not listener preference or physical speaker sound.

Effects and automation: the additive per-pattern `effects` and `commands` keys
(engine arpeggio, note cut, LFO, slide, glissando and noise retrigger; tempo,
transposition, volume/duty and cue commands) are available for PROGMEM scores
and are drawn in the review viewer. The finite-v1 FX adapter rejects any score
that declares them, so an effect passage stays PROGMEM. See the
[authoring guide](../../docs/music-authoring-guide.md) and the
[composition guidance](../../docs/skills/atm-music/references/composition.md).

Regenerate a cue using the commands in the [authoring guide](../../docs/music-authoring-guide.md),
then rebuild the library with:

```sh
python3 tools/music_authoring/library_player.py --catalog examples/music_authoring/catalog.json --out examples/music_authoring/player.html --json
```
