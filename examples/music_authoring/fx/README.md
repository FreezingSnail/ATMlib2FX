# Finite-v1 compact FX fixtures (ATMlib2FX-3ii.3)

Authored, **finite** (non-looping) v1 scores exported through the selected
compact FX backend. The stream framing, limits and semantics are pinned by the
`hlh.6 review` section of
[`research/fx/fx-architecture-decision.md`](../../../research/fx/fx-architecture-decision.md);
the reference converter is
[`research/fx/tools/fx_compact_spike/fx_compile_compact.c`](../../../research/fx/tools/fx_compact_spike/fx_compile_compact.c)
(read-only).

This lane exports **finite v1 only**: no runtime global loop, no live effects and
no SFX. Everything the adapter cannot represent is rejected with a diagnostic
that points at the offending source JSON Pointer.

| Fixture | Purpose | Tick rate | Stream |
| --- | --- | ---: | ---: |
| [`basic/song.json`](basic/song.json) | four-channel equivalence baseline | 50 Hz | 269 B |
| [`stress/song.json`](stress/song.json) | sparse song at the 2000/7 Hz stress rate (documented 6-tick frame window) | 255 Hz | 101 B |

`basic/expected/` holds the byte-golden `stream.bin`, generated `stream.h`,
review payload and `checksums.txt`; the stream SHA-256 is also in every build's
`report.json` under `stream.sha256`.

## Build and verify

```sh
# deterministic export + packing metadata (choose the fixture you want)
tools/atm-music build examples/music_authoring/fx/basic/song.json \
    --backend fx --out build/music-authoring/fx --json

# original-engine trace vs device-decoder trace, terminal silence, ring-wrap,
# multi-tick service-gap sweep and high FX base address (host evidence)
tests/music_authoring/fx/run-fx-trace.sh

# focused unit tests
python3 -m unittest discover -s tests/music_authoring -p 'test_*.py'
```

The build report's `stream` block separates **FX asset bytes** (`stream.bytes`,
`payload_bytes`, `framing_bytes`, `max_group_bytes`, `max_record_bytes`,
`window_bytes`) from engine/build SRAM/flash/stack, which this command does not
measure (`avr_measurements.measured = false`). Never read an asset byte count as
an engine or whole-game memory result.

## Admission and diagnostics

| Condition | Code | Points at |
| --- | --- | --- |
| Global `"loop": true` | `LOOP_NOT_EXPORTED` (warning; finite arrangement exported once) | `/loop` |
| A pass record larger than the 32-byte ring or the controlled service window | `DUE_GROUP_TOO_LARGE` | first source event in the widest group |
| Channel group > 255 bytes | `LIMIT_EXCEEDED` | source event |
| Any non-finite-v1 device op / traversal | `CAPABILITY_UNSUPPORTED` | source event |

`capabilities --json` advertises the FX backend for `build` with
`loops`/`effects`/`sfx` explicitly `false`.
