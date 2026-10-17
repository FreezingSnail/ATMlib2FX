# Developer checks and fixtures

| Directory | Contents |
| --- | --- |
| `music_authoring/test_*.py` | Python checks for validation, encoding, rendering, and inspection |
| `music_authoring/fixtures/basic/` | PROGMEM golden outputs, expected engine trace, isolated-channel source, and AVR compile fixture |
| `music_authoring/viewer/` | Piezo routing checks and browser walkthrough driver |
| `arduino/test_sketch/` | Existing on-device manual listening checks |

The renderer uses its own shipped harness inputs under
`tools/music_authoring/preview/`. Tests exercise those inputs; the CLI does not
load its runtime assets from this directory.

When checking changes, run these from the repository root:

```sh
python3 -m unittest discover -s tests/music_authoring -p 'test_*.py'
node tests/music_authoring/viewer/test_piezo.mjs
tests/music_authoring/fixtures/basic/trace/run-trace.sh
```

The real AVR render check is opt-in through `ATMLIB_AVR_PREVIEW=1` and needs the
Arduino toolchain and an existing Ardens build. Browser driver usage is documented
in the [viewer README](../tools/music_authoring/viewer/README.md).
Generated outputs go under `build/`. Historical browser results are preserved in
[`research/music-authoring/piezo/`](../research/music-authoring/piezo/SUMMARY.md).

These commands are documentation; no test suite or browser run was performed as
part of the repository layout cleanup.
