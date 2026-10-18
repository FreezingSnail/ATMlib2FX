# FX jukebox verification (ATMlib2FX-hlh.15)

Host tooling that verifies the committed FX jukebox image
(`build/fx-jukebox/fxdata.bin`), its index header
(`examples/arduino/jukebox_fx/jukebox_fx_songs.h`) and the per-song adapter
reports. Two pieces, run from the repository root:

```sh
# 1. static image / header / report consistency + capacity table (stdlib Python)
python3 tests/fx_jukebox/verify_image.py

# 2. host streaming-decoder trace + absim device run of the packed image
tests/fx_jukebox/run-absim-verify.sh
```

Everything lands under `build/fx-jukebox/verify/`. Neither script commits,
downloads, or edits the image/header; the tree stays dirty.

## `verify_image.py`

Reads only committed/generated artifacts (no toolchain) and checks:

* every catalog song is present in catalog order in `songs.json` and in the
  generated header comments, with sources matching `catalog.json`;
* the header macros, `songs.json` and packer `meta.json` agree on the data page,
  image length and each song's offset/length/loop/stream-loop facts;
* streams are densely packed (each starts where the previous ended, no overlap,
  no unaccounted gap, total equals the image length);
* page arithmetic adds the data page exactly once and stays inside the 16 MiB
  FX chip (24-bit addressing);
* each image slice is byte-identical to the adapter's `stream.bin`, its SHA-256
  matches `report.json`, and the leading magic byte is `0xC1`;
* every per-song FX build requested `--streaming-loops`, exported a streaming
  loop (`loop_streaming`), and produced no diagnostics — in particular no
  `LOOP_NOT_EXPORTED`.

It writes `static-report.json`, `evidence-sha256.txt` and a `capacity.md` table
(stream bytes vs the PROGMEM jukebox asset bytes, sketch flash/SRAM, Ardens
launch line). Exit status is non-zero if any check fails.

## `run-absim-verify.sh`

Uses the real `examples/arduino/jukebox_fx` sketch (its `JUKEBOX_FX_START_SONG`
and `FX_REPORT_FRAME` hooks) so the evidence is on the shipped consumer:

1. **Host decoder trace** — `research/fx/fx_compact_spike/loops/compact_trace.c`
   (the device streaming decoder on the host, ring 64) runs each stream for
   intro + two full loop cycles. It must show zero underruns, zero error, an
   active player, and consecutive loop cycles byte-identical after dropping the
   traversal-only columns (the wrap repeats on the pinned period).
2. **absim device run** — the sketch is compiled with the documented FX flags
   (`ATM_HAS_FX_COMPACT=1`, `ATM_FX_COMPACT_LOOP=1`, `ATM_FX_COMPACT_RING=64`,
   `ATM_FX_COMPACT_DIAG=1`) and started on each song, then run on the packed
   image past intro + two full cycles. The one-shot `FXDIAG` line must show
   `underruns=0`, `error=0`, `stop_tick=0`, and a tick count beyond two cycles.

Songs covered: `overworld` (index 0, a Creature Gatherer loop, 1408-tick cycle)
and `snapdragon_sprint` (index 20, 2048-tick cycle, the widest record at 34 B).

Binaries reused if present under `build/`, otherwise built from
`tests/fx_image/absim_harness.cpp` against the local Ardens absim core. No git,
no network.
