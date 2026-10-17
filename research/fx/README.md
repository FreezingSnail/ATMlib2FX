# FX playback research

The production FX storage ABI has not been selected. The owner priority is
minimum SRAM and AVR program flash. Read the
[architecture decision](fx-architecture-decision.md),
[footprint results](fx-footprint-results.md), and
[source research](fx-port-research.md) before continuing this work.

| Directory | Purpose |
| --- | --- |
| `footprint_baseline/` | Original engine measurement sketch, diagnostic sketch, trace harnesses and reference traces |
| `fx_stream_spike/` | Retained 64-byte ring prototype and emulation/trace harnesses |
| `fx_compact_spike/` | Compact 32-byte ring candidate and equivalence/format harnesses |
| `tools/` | Experiment-specific converters, FX data builder and measurement scripts |

Reproduction entry points, from the repository root:

```sh
research/fx/tools/measure-footprint.sh
research/fx/tools/build-fx-stream.sh
research/fx/tools/build-fx-compact.sh
```

These scripts require the existing local Arduino/AVR toolchain; emulator scripts
also require an existing local Ardens build. They write to `build/fx-port/`.
The compile-gated candidate backends remain in `src/atm_fx_{stream,compact}.{c,h}`
because they are integrated with the engine for reproduction. Their presence
does not mean a production format has been accepted.

## Relocated paths

| Former location | Current location |
| --- | --- |
| `tools/build-fx-*.sh`, `tools/measure-footprint.sh`, `tools/fx_*.c`, `tools/fx_compact_spike/` | `research/fx/tools/` |
| `examples/footprint_baseline/` | `research/fx/footprint_baseline/` |
| `examples/fx_stream_spike/` | `research/fx/fx_stream_spike/` |
| `examples/fx_compact_spike/` | `research/fx/fx_compact_spike/` |
| `docs/fx-*.md` | `research/fx/fx-*.md` |

Current reproduction commands use the new paths. Captured files in `build/`,
published hash tables, and unchanged engine comments may refer to former paths.
The cleanup changed paths/comments in research utilities; historical source
hashes still identify the original measurement inputs. No measurements were rerun.
