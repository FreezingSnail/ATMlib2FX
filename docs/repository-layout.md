# Repository layout

| Path | Responsibility |
| --- | --- |
| `src/` | Compact FX decoder and shared synthesis/effect engine |
| `tools/` | Maintained host CLI and FX stream/image packers |
| `schemas/` | Public JSON score schema |
| `examples/` | FX playback sketches and authored song sources |
| `tests/` | Host checks, fixtures and goldens |
| `research/` | Archived architecture decisions, measurements and captured evidence |
| `docs/` | User guides, contracts and composition guidance |
| `build/` | Ignored local outputs and retained measurement evidence |

Open [`examples/music_authoring/catalog.json`](../examples/music_authoring/catalog.json)
for the song list. Start authoring with [`tools/atm-music`](../tools/atm-music)
and the [music authoring guide](music-authoring.md).

## Rules for new files

Keep maintained tool implementation in `tools/`. Put a song's source JSON under
`examples/music_authoring/` and register it in the catalog. Keep intermediate
renders and generated images under `build/`. Put checks and expected outputs in
`tests/`. Put archived experiment results and captured evidence in `research/`;
do not leave retired spike code or test fixtures there. Track work and follow-ups
in Beads.

## Relocated files

| Former location | Current location |
| --- | --- |
| `examples/arduino/songs/song01{,_sfx}/` | `tests/fx_pack/fixtures/song01{,_sfx}/` |
| `research/fx/footprint_baseline/trace/trace_main.c` | removed with the PROGMEM runtime |
| `research/fx/fx_compact_spike/loops/{compact_trace.c,loops_trace_common.h}` | `tests/fx_jukebox/trace/` |
| `research/fx/tools/fx_make_fxdata.c` | `tests/fx_image/reference/fx_make_fxdata.c` |
