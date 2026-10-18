# Jukebox

A single Arduboy sketch that browses and plays the authored example songs. It
uses the canonical PROGMEM (`ATM_SCORE_FMT_FULL`) assets rebuilt from the
`examples/music_authoring/catalog.json` sources, so what you hear on hardware is
byte-identical to what the authoring tools validate and preview.

## Controls

| Button       | Action                                        |
| ------------ | --------------------------------------------- |
| `UP`         | Previous song (wraps, plays immediately)      |
| `DOWN`       | Next song (wraps, plays immediately)          |
| `A`          | Restart the selected song                     |
| `B`          | Pause / resume playback                       |

The display shows the index (`i/N`), the song name word-wrapped over two lines,
its folder, the loop length (one decimal) and score byte size, and the current
status (`PLAYING` / `PAUSED` / `READY`).

## Why two sets

The `arduboy-homemade:avr:arduboy-fx` image caps flash at **29,696 bytes**. The
twenty-one catalog scores total **33,594 bytes** of PROGMEM asset data alone, before
the engine, menu and Arduboy2 overhead (a measured shell + engine is about
8,196 bytes). One image therefore cannot hold every song, so the sketch is built
against one header at a time:

| `JUKEBOX_SET` | Header                | Songs                                             | Score bytes |
| ------------- | --------------------- | ------------------------------------------------- | ----------- |
| `1` (default) | `songs_gatherer.h`    | Creature Gatherer + Authoring Examples (14 songs) | 16,296      |
| `2`           | `songs_frontiers.h`   | Creature Frontiers (7 songs)                      | 17,298      |

Together the two sets cover all **21** catalog songs. `songs_gatherer.h` and
`songs_frontiers.h` are generated and committed beside the sketch; the model
also supports an `all` set (21 songs, 33,594 bytes) for reporting only — it does
not fit.

## Regenerate the headers

```sh
python3 tools/music_authoring/jukebox.py --set gatherer \
    --out examples/arduino/jukebox/songs_gatherer.h
python3 tools/music_authoring/jukebox.py --set frontiers \
    --out examples/arduino/jukebox/songs_frontiers.h
```

The generator is deterministic (catalog order, no timestamps) and writes nothing
else. Add `--json` for a machine-readable report of `song_bytes` and `fits`.

## Build

```sh
# Set 1 (gatherer, default)
arduino-cli compile --library . --fqbn arduboy-homemade:avr:arduboy-fx \
    --build-path build/jukebox/avr-gatherer examples/arduino/jukebox

# Set 2 (frontiers)
arduino-cli compile --library . --fqbn arduboy-homemade:avr:arduboy-fx \
    --build-property compiler.cpp.extra_flags=-DJUKEBOX_SET=2 \
    --build-path build/jukebox/avr-frontiers examples/arduino/jukebox
```

Measured program sizes (both under the 29,696-byte cap):

* gatherer: `Sketch uses 28,656 bytes (96%) of program storage space.`
* frontiers: `Sketch uses 25,942 bytes (87%) of program storage space.`

## Run

```sh
# Interactive
~/code/arduboy/Ardens/build/Ardens.app/Contents/MacOS/Ardens \
    "file=$PWD/build/jukebox/avr-gatherer/jukebox.ino.hex"

# Headless smoke test (exit 0 on success)
~/code/arduboy/Ardens/build/Ardens.app/Contents/MacOS/Ardens headless=3000 \
    "file=$PWD/build/jukebox/avr-gatherer/jukebox.ino.hex"
```

You can also drag the built `.hex` onto the Ardens window.
