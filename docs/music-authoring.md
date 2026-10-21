# Music authoring (compact FX)

`tools/atm-music` validates an `atmlib-score` version 1 JSON file and exports one
compact directly-consumed FX stream (`atm_fx_compact_v1`). Run commands from the
repository root.

```sh
tools/atm-music capabilities --json
tools/atm-music validate SONG.json --json
tools/atm-music build SONG.json --backend fx --out build/music-authoring/export --json
```

`build` writes `stream.bin`, `stream.h`, `review.json` and `report.json`. The
stream is a music asset only; its byte count is not engine, sketch or whole-game
memory. Pack one or more streams into an FX data image with
[`tools/fx_image`](../tools/fx_image/README.md), then build the sketch with:

```sh
-DATM_FX_COMPACT_RING=32          # match the adapter ring
-DATM_FX_COMPACT_LOOP=1           # only for 0xC1 loop streams
```

See [FX music integration](fx/integration.md) for ownership, service placement,
the refill deadline and loop behavior.

## Score surface

- Four monophonic channels: `pulse0`, `pulse1`, `pulse2`, `noise`.
- Note names use natural/sharp spellings from C2 through D7. Noise tokens select
  noise behavior, not pitched samples.
- Instruments are fixed voice/volume/duty presets.
- Patterns support notes, rests, gates, finite repeats and whole-song loops.
- Optional per-pattern `effects`: `arpeggio`, `note_cut`, `lfo`, `slide`,
  `glissando`, `noise_retrig`.
- Optional per-pattern `commands`: `set_tempo`, `add_tempo`,
  `set_transposition`, `add_transposition`, `set_volume`, `set_mod`, `cue`.
- Effect slots are shared: `arpeggio`/`note_cut` share the retrigger slot;
  `slide`, `lfo`, `glissando` and `noise_retrig` are one slot each. Windows in a
  slot must be ordered and non-overlapping.

The structural schema is [`schemas/atmlib-score-v1.schema.json`](../schemas/atmlib-score-v1.schema.json).
Semantic ranges, ordering, shared-slot conflicts and duplicate rules are enforced
by `tools/music_authoring/validate.py` with stable diagnostic codes and JSON
Pointers.

## Loops and ring size

Root `"loop": true` exports a `0xC1` loop stream when the loop region fits the
admission ring. A larger region:

- falls back to a finite `0xC0` arrangement with a `LOOP_NOT_EXPORTED` warning by
  default;
- exports a streaming loop (region up to 65,535 B) with `--streaming-loops`;
- is rejected above the streaming bound.

The default ring is 32 B. Use `--ring N` (power of two, 5..256) for wider records
and build the sketch with the same `ATM_FX_COMPACT_RING`. The committed jukebox
uses 64 B because Snapdragon Sprint has a 34 B record.

## FX layout and playback

`atm_fx_compact_fetch(offset, dst, n)` is supplied by the sketch and must read
from the FX data section using data-section-relative offsets. Call
`atm_fx_compact_service()` in the main loop after `FX::display()`, with sample
interrupts enabled and between complete SPI transactions. At 52 fps, service at
least once per frame (about 19.23 ms). The timer consumer touches only SRAM.

## Tests

```sh
python3 -m unittest discover -s tests/music_authoring -p 'test_*.py'
tests/fx_pack/run-tests.sh
tests/fx_image/run-tests.sh
tests/fx_jukebox/run-absim-verify.sh
```
