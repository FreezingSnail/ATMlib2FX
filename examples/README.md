# Examples

## FX playback

- [`arduino/jukebox_fx/`](arduino/jukebox_fx/): all 21 catalog songs in one FX
  data image, with browse, restart and pause controls.
- [`fx/music_graphics/`](fx/music_graphics/): compact FX stream plus bitmap
  service in one sketch.

Both sketches require the library and an ArduboyFX data image. See each
directory for build flags and image generation.

## Song sources

[`music_authoring/`](music_authoring/README.md) holds the JSON sources and FX
fixtures. The catalog drives the jukebox image. There is no PROGMEM score
example in this repository.
