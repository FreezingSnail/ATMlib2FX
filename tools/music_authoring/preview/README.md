# Renderer runtime assets

These inputs are required by `atm-music render`:

| Asset | Purpose |
| --- | --- |
| `preview/preview.ino` | Play the generated score in the real AVR engine with speaker output enabled |
| `absim_audio_harness.cpp` | Capture mono PCM from a locally built Ardens emulator |
| `build-harness.sh` | Build that capture executable into the requested output directory |
| `trace_main.c` | Run the engine's tick processing on the host for trace metadata |
| `avr_shim/` | Host PROGMEM substitution for the tick trace |

The Arduino sketch directory must share its basename with `preview.ino`.
The renderer locates these files within this package; it does not require example
or test directories for compilation. The existing basic golden trace runner in
`tests/music_authoring/fixtures/basic/trace/` also uses these maintained inputs.
Generated executables, AVR images, WAVs, and reports go into the render output
directory, normally under `build/music-authoring/`.
