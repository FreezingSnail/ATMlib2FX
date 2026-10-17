# Packaged host tools

Start with the [music authoring guide](../docs/music-authoring-guide.md) for LLM
or human composition. Run commands from the repository root. Python tooling uses
the standard library; AVR audio rendering additionally needs the local Arduino
toolchain and an existing Ardens build (see the guide).

| Entry point | Purpose |
| --- | --- |
| `tools/atm-music capabilities --json` | Describe the score contract and backend |
| `tools/atm-music validate SONG.json --backend progmem --json` | Check a song and report JSON diagnostics |
| `tools/atm-music build SONG.json --backend progmem --out build/music-authoring/export --json` | Export PROGMEM assets |
| `tools/atm-music render SONG.json --backend progmem --seconds 12 --out build/music-authoring/preview --json` | Capture real emulated AVR audio |
| `tools/atm-music inspect SONG.json --audio-preview PREVIEW --out build/music-authoring/review.html --json` | Generate an offline track viewer |
| `python3 tools/music_authoring/library_player.py --catalog examples/music_authoring/catalog.json --out examples/music_authoring/player.html --json` | Bundle the example library into one offline player |

CLI stdout is a JSON document; progress goes to stderr. Exit codes: `0` success,
`2` invalid input or unsupported capability, `3` tool failure. Production FX
export is unavailable.

## Package contents

- `music_authoring/*.py`: validation, lowering, PROGMEM export, rendering,
  inspection, and library bundling.
- `music_authoring/preview/`: renderer runtime inputs (AVR sketch, emulator
  capture harness, engine tick trace, and host AVR shim).
- `music_authoring/viewer/`: the single-song viewer template, styles, timeline,
  and Raw/Piezo audio routing.
- `music_authoring/library_player/`: selector shell assets for the library player.

Song sources and matching preview WAV/report pairs live together in
[`examples/music_authoring/`](../examples/music_authoring/). Developer checks and
goldens live in [`tests/`](../tests/); FX experiments and their reproduction
utilities live in [`research/fx/`](../research/fx/). Write intermediate outputs
under the ignored `build/` directory.
