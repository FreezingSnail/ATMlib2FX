# library_player tooling (ATMlib2FX-3ii.12)

Maintained tooling for the single offline example-song player with folder filters. Durable files:

| Path | Role |
| --- | --- |
| `../library_player.py` | Bundler module + CLI (`python3 tools/music_authoring/library_player.py`) |
| `template.html` | Shell skeleton with `__ATMLIB_PLAYER_CSS__`, `__ATMLIB_LIBRARY__`, `__ATMLIB_PLAYER_JS__` placeholders |
| `shell.css` | Shell styles (inlined into the output) |
| `shell.js` | Mounts exactly one review iframe on selection; no audio logic, no autoplay |

The player it produces lives at
[`examples/music_authoring/player.html`](../../../examples/music_authoring/player.html)
and the song list is
[`examples/music_authoring/catalog.json`](../../../examples/music_authoring/catalog.json).

Regenerate the player from the repository root:

```
python3 tools/music_authoring/library_player.py \
    --catalog examples/music_authoring/catalog.json \
    --out examples/music_authoring/player.html --json
```

`--report PATH` optionally writes a machine-readable bundle report. Optional catalog `folder` labels group songs in the main player; older catalogs fall back to category. Each song's
matching `preview.json` + `preview.wav` lives beside its `song.json`, under
`examples/music_authoring/**/preview/`. Regenerate one with
`tools/atm-music render SONG.json --backend progmem --seconds N --out <dir> --json`.
Use an output directory under `build/` for intermediate compilation, then retain
the matching WAV/report pair with the example. This directory contains only the
maintained player shell; it contains no song media or experimental results.
