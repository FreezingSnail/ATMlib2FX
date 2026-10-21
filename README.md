# ATMlib2FX

Compact four-channel chiptune synthesis for ArduboyFX. Songs are authored as
JSON on the host, exported as a directly-consumed `atm_fx_compact_v1` stream,
packed into an FX data image, and decoded by the AVR library while the game keeps
running. Minimum SRAM and AVR program flash are the design priorities.

## Start here

- **Create music:** [authoring guide](docs/music-authoring.md) and
  [tool entry points](tools/README.md).
- **Integrate playback:** [FX integration contract](docs/fx/integration.md).
- **Run the examples:** [21-song FX jukebox](examples/arduino/jukebox_fx/) and
  [music + graphics](examples/fx/music_graphics/).
- **Browse song sources:** [authoring catalog](examples/music_authoring/catalog.json).
- **Read the archive:** [FX research and measurements](research/fx/README.md).

## Repository map

| Directory | Contents |
| --- | --- |
| [`src/`](src/) | Compact FX decoder and shared synthesis/effect engine |
| [`tools/`](tools/README.md) | `atm-music` CLI, `fx_pack`, `fx_image`, and FX jukebox generator |
| [`examples/`](examples/README.md) | FX sketches and JSON song sources |
| [`schemas/`](schemas/) | JSON score schema |
| [`docs/`](docs/README.md) | Authoring, integration and layout guides |
| [`tests/`](tests/README.md) | Host checks, fixtures and goldens |
| [`research/`](research/README.md) | Archived FX decisions, measurements and evidence |
| `build/` | Ignored generated outputs and retained measurement evidence |

Development work is tracked in Beads (`bd ready`).

## Quick CLI example

Run from the repository root:

```sh
tools/atm-music validate examples/music_authoring/basic/song.json --json
tools/atm-music build examples/music_authoring/basic/song.json \
    --backend fx --ring 64 --streaming-loops \
    --out build/music-authoring/fx --json
```

`build` emits the compact stream, C header, canonical review and packing report.
Pack streams into an FX data image with [`tools/fx_image`](tools/fx_image/README.md),
then build the sketch with a matching `-DATM_FX_COMPACT_RING`, and `-DATM_FX_COMPACT_LOOP=1` for loops. `stream.bin`
counts are music-asset bytes, not whole-game memory cost.

## Attribution

ATMlib2FX builds on ATMlib and Squawk, with contributions from Davey Taylor,
Delio Brignoli, Jay Garcia, and Joeri Gantois. See [LICENSE](LICENSE).
