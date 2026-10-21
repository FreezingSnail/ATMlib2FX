# Developer checks and fixtures

| Directory | Contents |
| --- | --- |
| `music_authoring/test_*.py` | Score validation, lowering, effects, FX streams and jukebox generation |
| `music_authoring/fixtures/basic/` | Minimal score and canonical review payload |
| `music_authoring/fx/` | Compact-decoder trace harness |
| `fx_pack/` | Compact stream converter checks and legacy score fixtures |
| `fx_image/` | FX data-image packer checks, reference packer and absim harness |
| `fx_jukebox/` | Image/header verification and absim jukebox evidence |
| `cue/`, `cmd_parse/` | Compact decoder command and note-retrigger checks |
| `support/avr_shim/` | Host `<avr/pgmspace.h>` shim used by the C harnesses |

Run these from the repository root:

```sh
python3 -m unittest discover -s tests/music_authoring -p 'test_*.py'
tests/cue/run-tests.sh
tests/cmd_parse/run-tests.sh
tests/fx_pack/run-tests.sh
tests/fx_image/run-tests.sh
python3 tests/fx_jukebox/verify_image.py
tests/fx_jukebox/run-absim-verify.sh
```

Generated outputs go under `build/`. The absim and AVR checks need the local
Arduino toolchain and an Ardens build.
