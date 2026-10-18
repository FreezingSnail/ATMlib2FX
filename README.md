# ATMlib2FX

Arduboy Tracker Music: a small four-channel chiptune synthesizer and player,
with host tools for authoring music as JSON. FX storage/playback is under
investigation; production FX export is unavailable. Minimum SRAM and AVR program
flash remain the design priorities.

## Start here

- **Listen and view tracks:** open [the offline song player](examples/music_authoring/player.html).
  All fourteen compositions (eleven Creature Gatherer FX cues plus three
  authoring examples) are embedded; no server or build step is needed.
- **Create music with an LLM or the CLI:** [authoring guide](docs/music-authoring-guide.md)
  and [tool entry points](tools/README.md).
- **Use the Arduino library:** [C/C++ playback and score reference](docs/library-reference.md),
  [example sketches](examples/README.md).
- **Continue the FX port:** [research index and architecture decisions](research/fx/README.md).

## Repository map

| Directory | Contents |
| --- | --- |
| [`src/`](src/) | Arduino playback library |
| [`tools/`](tools/README.md) | Packaged host CLI, viewer, bundler, and renderer assets |
| [`examples/`](examples/README.md) | `arduino/` playback demos; `music_authoring/` songs with offline reviews/audio |
| [`schemas/`](schemas/) | JSON score schema |
| [`docs/`](docs/README.md) | Authoring guide, contracts, and library reference |
| [`tests/`](tests/README.md) | Developer checks, fixtures, and goldens |
| [`research/`](research/README.md) | FX spikes, measurements, decisions, and reproduction scripts |
| [`extras/`](extras/) | Inherited design and music theory notes |
| `build/` | Ignored generated outputs and retained local measurement evidence |

See [repository layout](docs/repository-layout.md) for directory boundaries and
paths moved during cleanup. Development work is tracked in Beads (`bd ready`).

## Quick CLI example

Run from the repository root:

```sh
tools/atm-music validate examples/music_authoring/basic/song.json --backend progmem --json
tools/atm-music build examples/music_authoring/basic/song.json --backend progmem --out build/music-authoring/export --json
```

Tooling runs on the host and adds no AVR runtime footprint. The single offline
player supports piano-roll/tracker views and Raw emulator / approximate Piezo
sound; [song library instructions](examples/music_authoring/README.md) explain
regeneration and adding compositions.

The bundled player and the per-cue reviews are **not browser-validated** and were
**not hardware-listened to**: their pages are self-contained and network-free by
construction, and correctness is evidenced by validated sources, canonical event
digests and rendered AVR (absim) WAVs — not by taste or an automated UI run. No
FX export exists (`--backend fx` → `BACKEND_UNAVAILABLE`); the music is candidate
PROGMEM, and `score.bin` bytes are song-asset bytes, not whole-game cost.

## Score command reference

The public `ATM_CMD_M_*` macros, their bit-level encoding, and stream costs are
documented in the [library reference](docs/library-reference.md#public-command-macros);
the macros themselves live in [`src/atm_cmd_constants.h`](src/atm_cmd_constants.h).

## Attribution

ATMlib2 builds on ATMlib and Squawk, with contributions from Davey Taylor,
Delio Brignoli, Jay Garcia, and Joeri Gantois. The inherited background,
acknowledgements, and technical reference are preserved in the
[library reference](docs/library-reference.md). See [LICENSE](LICENSE).
