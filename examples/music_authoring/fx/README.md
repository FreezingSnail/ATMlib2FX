# Compact FX fixtures (ATMlib2FX-3ii.3 / ATMlib2FX-hlh.12)

Authored v1 scores exported through the selected compact FX backend. The stream
framing, limits and semantics are pinned by the `hlh.6 review` section of
[`research/fx/fx-architecture-decision.md`](../../../research/fx/fx-architecture-decision.md)
and its global-loop extension (`hlh.8`); the reference converter is
[`tools/fx_pack/fx_encode.c`](../../../tools/fx_pack/fx_encode.c).

The adapter exports **finite effect/command scores** (the same command bytecode
the compact decoder parses, via `progmem_backend.encode_op`), **resident global
loops** with the pinned `0xC1` framing when the whole loop region fits the
admission ring, and — with `--streaming-loops` — **streaming loops** when the
region is larger than the ring (up to 65535 B, the `hlh.16` extension). Without
`--streaming-loops` a region larger than the ring falls back to the finite
`0xC0` arrangement once with a `LOOP_NOT_EXPORTED` warning — never silently.
SFX is not offered.

| Fixture | Purpose | Tick rate | Stream |
| --- | --- | ---: | ---: |
| [`basic/song.json`](basic/song.json) | four-channel equivalence baseline | 50 Hz | 269 B |
| [`stress/song.json`](stress/song.json) | sparse song at the 2000/7 Hz stress rate (documented 6-tick frame window) | 255 Hz | 101 B |
| [`loop/song.json`](loop/song.json) | smallest resident loop: 2-tick cycle, `0xC1` framing, 22-byte loop region | 50 Hz | 50 B |

`basic/expected/` holds the byte-golden `stream.bin`, generated `stream.h`,
review payload and `checksums.txt`; the stream SHA-256 is also in every build's
`report.json` under `stream.sha256`. `loop/expected/stream.bin` is the pinned
`0xC1` loop golden (hand-verified byte-for-byte against the device decoder).

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
| Loop region larger than the ring and no `--streaming-loops` | `LOOP_NOT_EXPORTED` (warning; finite arrangement exported once) | `/loop` |
| Loop region larger than the 65535 B streaming bound | `LIMIT_EXCEEDED` | `/loop` |
| A loop with no representable cycle (no tracks / zero-time) | `LOOP_CYCLE_INVALID` | `/loop` |
| A pass record larger than the ring or the controlled service window | `DUE_GROUP_TOO_LARGE` | first source event in the widest group |
| Channel group > 255 bytes, or a gap beyond the 65535-tick varint | `LIMIT_EXCEEDED` | source event |
| An op with no compact command encoding / a traversal op | `CAPABILITY_UNSUPPORTED` | source event |

The admission ring is configurable: `--ring N` (power of two, `5..256`, default
32) or the `ring` argument to `fx_backend.build`/`serialize`. A larger ring can
keep a loop region that the default 32 B ring would stream, and
`--streaming-loops` admits a region larger than any ring up to 65535 B; the host
enforces the same record/region bounds the device build (`ATM_FX_COMPACT_RING` /
`ATM_FX_COMPACT_LOOP_STREAMING`) requires.

`capabilities --json` advertises the FX backend for `build` with `effects` and
`commands` supported, `loops` supported when the decoder is built with
`ATM_FX_COMPACT_LOOP=1` (stated explicitly), `streaming_loops` supported with
`--streaming-loops` (region max 65535 B), and `sfx` false. Effect and
live-command families are encoded, never silently dropped; a family is admitted
exactly when `progmem_backend.encode_op` can encode it.
