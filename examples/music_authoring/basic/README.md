# Basic authoring example

## Current revision — 2026-10-17 (ATMlib2FX-awr)

Two-bar teaching loop; stable thirds/fifths, a full-length bass and gentler percussion.

**C major · 125.00 BPM · 2 bars · 192 ticks · 3.84 s per loop.**
The source sets `"loop": true`; the original PROGMEM engine restarts all tracks
on the same callback. The [review](review.html) defaults **Loop** on and repeats
one cycle with measured startup and capture tail excluded from playback.

Current [WAV](preview/preview.wav) and [render report](preview/preview.json) were
regenerated from this source through AVR/absim; the capture includes a cycle
plus 0.5 s of the next iteration. PROGMEM asset: **222 B**.
WAV SHA-256: `2f5b3626527a2b3912a990799e37259b75afc17f1cbd87dc1031e6b634a82ec1`.

[All-song player](../player.html) · [source](song.json) · [canonical review](review.json).

This small four-channel score demonstrates repeated patterns, adjacent notes
and rests on a musical beat grid. The original finite source, one-tick gates,
short-channel case and unchanged goldens live in the
[basic test fixture](../../../tests/music_authoring/fixtures/basic/README.md).

Validate, build and render with `tools/atm-music`; write intermediate outputs
under `build/`. See the [authoring guide](../../../docs/music-authoring-guide.md).
