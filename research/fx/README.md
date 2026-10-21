# FX playback research archive

The compact directly-consumed FX music stream (`atm_fx_compact_v1`) is the
selected production backend. This directory preserves the architecture
decisions, measurements and provenance from the FX port; it is not an active
build lane.

The spike sketches, converters, packers and emulator harnesses were removed
after the maintained implementations landed. Historical commands in the
documents below refer to those removed paths and cannot be rerun. Permanent
fixtures used by the current test suite live under `tests/`:

| Fixture | Current location |
| --- | --- |
| Host AVR PROGMEM shim | `tests/support/avr_shim/` |
| Original-engine reference trace | removed with the PROGMEM runtime; see the git history |
| Footprint measurement sketch | removed with the PROGMEM runtime; see the git history |
| Compact loop-decoder trace | `tests/fx_jukebox/trace/` |
| Reference FX image packer | `tests/fx_image/reference/fx_make_fxdata.c` |

Current implementation and contracts:

- [`src/atm_fx_compact.h`](../../src/atm_fx_compact.h) and
  [`src/atm_fx_compact.c`](../../src/atm_fx_compact.c): device decoder.
- [`docs/fx/integration.md`](../../docs/fx/integration.md): integration contract.
- [`tools/fx_pack/`](../../tools/fx_pack/) and
  [`tools/fx_image/`](../../tools/fx_image/): maintained stream converter and
  data-image packer.
- [`tools/music_authoring/fx_backend.py`](../../tools/music_authoring/fx_backend.py)
  and [`fx_jukebox.py`](../../tools/music_authoring/fx_jukebox.py): authoring
  adapter and multi-song image generator.
- [`examples/arduino/jukebox_fx/`](../../examples/arduino/jukebox_fx/) and
  [`examples/fx/music_graphics/`](../../examples/fx/music_graphics/): consumers.

## Documents

| Document | Contents |
| --- | --- |
| [`fx-architecture-decision.md`](fx-architecture-decision.md) | Pinned framing, ownership, loops, pause/replacement and admission decisions |
| [`fx-footprint-results.md`](fx-footprint-results.md) | Original engine and candidate decoder flash/SRAM/stack measurements |
| [`fx-port-research.md`](fx-port-research.md) | Storage and playback research notes |
| [`fx-mixer-gating-results.md`](fx-mixer-gating-results.md) | Compile-time mixer gating spike and go recommendation |

These files are historical records. Their captured paths, hashes and build
commands describe the state at measurement time and have not been rewritten.
