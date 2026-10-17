# Repository layout

| Path | Responsibility |
| --- | --- |
| `src/` | Arduino synthesizer/player library and compile-gated experimental backends |
| `tools/` | Maintained host CLI, viewer/bundler implementation, and required runtime assets |
| `schemas/` | Public JSON score schema |
| `examples/` | Arduino playback demonstrations and authored songs with their ready-to-open reviews/media |
| `tests/` | Developer checks, goldens, isolated sources, and manual test sketches |
| `research/` | Experiments, measurement/verification reports, and reproduction utilities |
| `docs/` | User guides, public contracts, and library reference |
| `extras/` | Inherited design and music theory notes |
| `build/` | Ignored local outputs, caches, and retained measurement evidence |

Open [`examples/music_authoring/player.html`](../examples/music_authoring/player.html)
to hear every authored song. Start LLM composition with
[`tools/atm-music`](../tools/atm-music) and the
[authoring guide](music-authoring-guide.md). The full code reference is in
[library-reference.md](library-reference.md).

## Rules for new files

Keep maintained tool implementation and its required runtime templates in
`tools/`. Put a song's `song.json`, `review.html`, `review.json`, and matching
`preview/{preview.json,preview.wav}` together in its example directory. Add the
source and preview paths to `examples/music_authoring/catalog.json` and use the
bundler to refresh the single player. Keep temporary render/build directories
under `build/`; promote just the media/report pair needed to reproduce the player.

Put experimental scripts with their experiment in `research/`. Put checks and
expected outputs in `tests/`. Track work and follow-ups in Beads.

## Other relocated files

The [FX index](../research/fx/README.md#relocated-paths) maps all FX moves.

| Former location | Current location |
| --- | --- |
| `examples/{arpeggio,drums,songs,...}/` | `examples/arduino/{arpeggio,drums,songs,...}/` (all 13 existing Arduino demo groups) |
| `tools/music_authoring/library_player/music/<id>/` | The corresponding song's `examples/music_authoring/**/preview/` |
| `tools/music_authoring/tests/` | `tests/music_authoring/` |
| `tools/music_authoring/viewer/{test_piezo,walkthrough}.mjs` | `tests/music_authoring/viewer/` |
| `examples/tests/test_sketch/` | `tests/arduino/test_sketch/` |
| `examples/music_authoring/basic/{expected,avr,trace}/` | `tests/music_authoring/fixtures/basic/` (except the runtime trace inputs below) |
| `examples/music_authoring/basic/preview/isolated.json` | `tests/music_authoring/fixtures/basic/isolated.json` |
| `examples/music_authoring/basic/preview/preview.ino` | `tools/music_authoring/preview/preview/preview.ino` |
| `examples/music_authoring/basic/trace/{trace_main.c,avr_shim}/` | `tools/music_authoring/preview/` |
| `examples/music_authoring/showcase/evidence/piezo/` | `research/music-authoring/piezo/` |
| Root README playback/score/macro reference | `docs/library-reference.md` |

Original captured reports and generated reviews retain historical paths. The
existing standalone player and per-song reviews remain usable offline. Their
bytes, song sources, preview WAV/report pairs, test goldens, engine sources and
retained `build/` evidence are preserved by the layout cleanup. Current catalog
and reproduction commands use the relocated inputs. Rebuilding a viewer can
change its recorded path metadata without changing its song or audio.
