# Examples

## Compose, view, and listen

Open the [offline song player](music_authoring/player.html) to review all twenty
JSON compositions, or read the [song library index](music_authoring/README.md).
Each composition has its source, standalone review, and matching preview media.
The [authoring guide](../docs/music-authoring-guide.md) explains the CLI workflow.

## Arduino playback demos

The [Arduino demos](arduino/) contain the existing effect directories
(`arpeggio`, `drums`, `frequencySlides`,
`Glissando`, `gotoAdvanced`, `noteCut`, `tempo`, `transposition`, `tremolo`,
`vibrato`, `volumeSlides`) demonstrating the macro score API. `arduino/songs/`
contains complete music/SFX examples; `arduino/midi_synth/` contains the MIDI
synthesizer demo; `arduino/jukebox/` is a two-set jukebox that plays all twenty
authored songs on hardware.
Open an individual sketch directory in Arduino with the library installed.
Existing music and attribution are preserved.

FX measurement sketches and trace harnesses are in
[`research/fx/`](../research/fx/). Developer fixtures and the manual listening
check sketch are in [`tests/`](../tests/).
