# Packaged host tools

Start with the [music authoring guide](../docs/music-authoring.md). Run commands
from the repository root. Python tooling uses the standard library; device checks
need the local Arduino toolchain and an existing Ardens build.

| Entry point | Purpose |
| --- | --- |
| `tools/atm-music capabilities --json` | Describe the score contract and FX backend |
| `tools/atm-music validate SONG.json --json` | Check a song and report diagnostics |
| `tools/atm-music build SONG.json --backend fx --out build/music-authoring/export --json` | Export a compact FX stream |
| `tools/atm-music build SONG.json --backend fx --ring 64 --streaming-loops --out build/music-authoring/fx --json` | Export a configurable-ring streaming-loop stream |
| `python3 tools/music_authoring/fx_jukebox.py --out-dir build/fx-jukebox --header examples/arduino/jukebox_fx/jukebox_fx_songs.h --ring 64 --streaming-loops` | Rebuild the 21-song jukebox image and index header |

`tools/fx_pack` converts legacy tracker score headers to compact streams;
`tools/fx_image` packs streams and bitmaps into an FX data image.

CLI stdout is a JSON document; progress goes to stderr. Exit codes: `0` success,
`2` invalid input or unsupported capability, `3` tool failure. The FX backend
exports finite streams, effects/commands and resident or streaming loops. SFX is
not offered.

## Package contents

- `music_authoring/*.py`: validation, lowering, command encoding, compact FX
  export and jukebox generation.
- `fx_pack/`: legacy score to compact stream converter.
- `fx_image/`: FX data-image packer.

Song sources live in [`examples/music_authoring/`](../examples/music_authoring/).
Developer checks and goldens live in [`tests/`](../tests/); archived FX
measurements live in [`research/fx/`](../research/fx/). Write intermediate outputs
under the ignored `build/` directory.
