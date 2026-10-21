# Compact FX stream fixtures

Authored scores exported through the compact FX backend. Framing, limits and
semantics are pinned by
[`research/fx/fx-architecture-decision.md`](../../../research/fx/fx-architecture-decision.md)
and [`docs/fx/integration.md`](../../../docs/fx/integration.md).

| Fixture | Purpose | Tick rate | Stream |
| --- | --- | ---: | ---: |
| [`basic/song.json`](basic/song.json) | four-channel equivalence baseline | 50 Hz | 269 B |
| [`stress/song.json`](stress/song.json) | sparse song at the 2000/7 Hz stress rate | 255 Hz | 101 B |
| [`loop/song.json`](loop/song.json) | smallest resident loop (`0xC1`) | 50 Hz | 50 B |

`basic/expected/` and `stress/expected/` hold byte-golden streams, generated
headers and review payloads. `loop/expected/stream.bin` is the pinned `0xC1`
loop golden.

Build and verify:

```sh
tools/atm-music build examples/music_authoring/fx/basic/song.json \
    --backend fx --out build/music-authoring/fx/basic --json

python3 -m unittest discover -s tests/music_authoring -p 'test_*.py'
tests/fx_pack/run-tests.sh
```
