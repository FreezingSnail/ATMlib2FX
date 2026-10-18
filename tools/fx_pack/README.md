# fx_pack — finite-v1 compact FX music converter

Supported host converter (`ATMlib2FX-hlh.7`) for the pinned compact,
directly-consumed FX music stream selected by `ATMlib2FX-hlh.6`. It replaces
the fixed-fixture spike converter
(`research/fx/tools/fx_compact_spike/fx_compile_compact.c`): the score is an
argument, the encoder is a reusable library, and every rejection names the
source event.

Contract and framing live in
[`research/fx/fx-architecture-decision.md`](../../research/fx/fx-architecture-decision.md)
(“hlh.6 review”, “hlh.8: global loops”). This tool emits finite (non-looping,
no-SFX) music by default, and loop-capable streams with `--loops`.

## Build

```sh
make -C tools/fx_pack            # -> build/fx-port/pack/fx_pack
```

No network, no installs, no git. Outputs stay under `build/` (ignored).

## Usage

```sh
# From a song header (modern full-format example):
build/fx-port/pack/fx_pack \
  --song examples/arduino/songs/song01_sfx/song.h --symbol score \
  --out build/fx-port/pack/song01_sfx/stream.bin \
  --meta build/fx-port/pack/song01_sfx/meta.json \
  --input-bin build/fx-port/pack/song01_sfx/input.bin

# Legacy pre-2.0 raw tracker score:
build/fx-port/pack/fx_pack \
  --song examples/arduino/songs/song01/song.h --symbol music \
  --out build/fx-port/pack/song01/stream.bin

# Flat score blob (no runtime extraction):
build/fx-port/pack/fx_pack --score-bin score.bin --out stream.bin
```

| Option | Meaning |
| --- | --- |
| `--song PATH` | C header defining the score object. Extracted at runtime by compiling a tiny probe TU that `#include`s the header; this is how the CLI accepts an arbitrary score instead of a built-in fixture. |
| `--symbol NAME` | Top-level object in the header. Default: try `score`, then `music`. |
| `--score-bin PATH` | Already-flat score bytes (auto-detected format). |
| `--format auto\|modern\|legacy` | Force the input interpretation (default `auto`). |
| `--out PATH` | Compact stream (required). |
| `--meta PATH` | Deterministic metadata JSON. |
| `--input-bin PATH` | Write the extracted flat score (evidence). |
| `--tempo N` | Replace `SET_TEMPO` operands (`0` = authored, default). |
| `--loops` | Allow `SET_LOOP_PATTERN` and emit a loop-capable stream (magic `0xC1`, ATMlib2FX-hlh.8). Without it, global loops are rejected in finite v1. |
| `--ticks N` | Conversion tick cap (default 8192). |
| `--ring N` | Admission ring size (default 32, allowed 5..256). |
| `--workdir DIR` | Probe scratch directory (default `build/fx-port/pack/work`). |
| `--cc PATH` | C compiler used for header extraction (default `$CC`, then `cc`). |

Exit status: `0` success, `2` usage or admission failure (diagnostic on
stderr). The emitted bytes are re-validated with the same structural rules the
device preflight applies before anything is written.

## Input matrix

1. **`ATM_SCORE_FMT_FULL` (0x03)** — the current library/authoring layout:

   ```
   <fmt=0x03> <pattern-count> <u16 LE offsets>[count]
   <channel-count=4> <entry>[4] <patterns...>
   ```

   Offsets are absolute, little-endian. Command bytes use the modern
   `src/atm_cmd_constants.h` encoding. Calls, repeats, returns and delays are
   resolved offline; `SET_LOOP_PATTERN` is rejected in finite v1.

2. **Legacy ATMlib v1 raw tracker layout** — the pre-2.0 `Song music[]` form
   (`<track-count> <u16 LE offsets relative to pattern-data start> <4 entry
   tracks> <tracks>`), which is what `examples/arduino/songs/song01/song.h`
   uses. The loader translates the pre-2.0 command encoding to modern bytes
   (including the CALL/REPEAT operand order and shared
   `PATTERN_END`/RETURN/STOP semantics), so the shared encoder and device
   decoder are unchanged.

   Legacy caveats (documented, not claimed equivalent):
   * volume/slide magnitudes are copied numerically (the pre-2.0 volume range
     was 0..63; the modern engine scales 0..127);
   * LFO/slide sub-opcode config bits are passed through, but the modern
     effect implementations differ slightly in phase/period setup;
   * `GOTO ADVANCED`, `EMBEDDED DATA`, reserved opcodes and unknown setup-FX
     opcodes are rejected with the pattern index and byte offset.

Anything else (minimal/mono/SFX formats, non-4-channel scores, global loops)
is rejected with a source diagnostic.

## Emitted stream

```
byte 0  0xC0
then records until END:
  <len> <body>            len >= 5; len <= ring; 0x00 = END
  body := <gap> <bitmap> <groups>
    <gap>    effect-only ticks until the next pass (varint, max 65535)
    <bitmap> bit0=ch0 .. bit3=ch3, 1..15
    <groups> per set channel in order: <glen> then <glen> command bytes
```

Gap varint: `<= 0x7F` one byte; `<= 0x7EFF` two bytes (`0x80|hi7`, `lo8`);
otherwise `0xFF`, `hi8`, `lo8`.

Long delays are scheduled as `operand + 1` (the original library semantics);
the retained `song01_sfx` fixture uses only short delays, so this correction
does not change its bytes. A gap larger than 65535 is rejected, not truncated.

### Loop streams (`--loops`, ATMlib2FX-hlh.8)

When `--loops` is set and the score issues `SET_LOOP_PATTERN`, the encoder
simulates the original all-stopped restart and emits a loop-capable stream:

```
byte 0  0xC1
u24 LE loop_start_rel     byte offset of the first loop-region record
then records until END (0x00); END is the loop boundary, not a stop
```

Records use the finite framing with two loop-mode changes:

* **gap field.** `0` means the next record runs in the **same** tick (the
  original's immediate second pass); otherwise the value is
  `effect-only ticks + 1`.
* **bitmap.** bits 0..3 are the command channels; bits 4..7 are the restart
  mask. A non-zero restart mask marks the original's all-stopped pass: after
  applying it the device re-arms those channels in the same tick. A bitmap of
  `0` (no channels, no restart) is an effect-only pass.

The loop region `[loop_start_rel, stream_len-1)` is found by traversal-cycle
detection on the post-restart state; it must fit the admission ring so the
device can pin and replay it with no further fetch (no underrun at the wrap).
A cycle that advances no ticks (a restart that stops again immediately) is
rejected as a zero-time cycle, and a traversal that never becomes periodic
within the tick cap is rejected. A loop region whose records all carry gap 0
is rejected too: replaying it would stay in the same-tick chain and never
yield a tick. The device additionally bounds that chain at one region wrap per
tick, so crafted bytes stop with a format error instead of hanging.
`SET_LOOP_PATTERN` operand 0 is a legal target (the engine reserves 255 as the
no-loop marker); operand 255 and out-of-range targets are rejected.

Finite (`0xC0`) output is byte-identical to hlh.7; loops are opt-in.

## Metadata JSON

Deterministic key order, integers only:

```json
{
  "input":   { "path": "...", "symbol": "...", "format": "...", "bytes": 124 },
  "options": { "tempo": "authored", "tick_cap": 8192, "ring": 32 },
  "result":  { "stream_bytes": 1572, "ticks": 2113, "stopped_at": 2113,
               "passes": 188, "payload_bytes": 809, "max_group": 17,
               "max_record": 24, "framing_bytes": 1570,
               "window_bytes": { "1": 24, ... },
               "window_at":    { "1": 0, ... } }
}
```

`window_bytes` is the maximum number of stream bytes consumed over K
consecutive music ticks (K = 1..8), matching the spike's service-window
analysis.

## Reusable encoder

`fx_encode.c` / `fx_encode.h` take a modern-encoded pattern model plus options
and return the stream, metadata, and source diagnostics. The CLI and the future
JSON authoring adapter (`ATMlib2FX-3ii.3`) can share it directly — the JSON
adapter already emits the modern full layout.

`fx_score.c` / `fx_score.h` provide the header-format loaders and the legacy
translation.

## Tests

```sh
tests/fx_pack/run-tests.sh
```

Shell + C only. The C selftest compiles the real device decoder
(`src/atm_synth.c` with `ATM_HAS_FX_COMPACT=1`), ports the retained
`compact_format_test.c` checks, and covers:

* gap boundaries `0/1/31/32/33/127/128/254/255/256/257/0x7EFE/0x7EFF/0x7F00/
  65534/65535` in both the codec and the device scheduler;
* `len > ring`, `len < 5`, `glen < 1`, `bitmap 0`, `bitmap > 15`, malformed
  command groups, `SET_LOOP_PATTERN`, out-of-range `CALL`, gap > 65535, and
  non-full/non-4-channel scores;
* legacy v1 translation to modern command bytes;
* a host decode round-trip with zero errors/underruns.

The shell driver also converts both example scores, asserts the retained
`song01_sfx` hashes
(`0e8432ac…` authored, `b7702512…` tempo 255), checks determinism, and decodes
both streams to END. Evidence lands under `build/fx-port/pack/`.

`tests/fx_pack/fx_loop_selftest.c` (compiled with `ATM_FX_COMPACT_LOOP=1`)
covers the loop extension: zero-time-cycle and non-periodic-traversal
rejection, `SET_LOOP_PATTERN` operand bounds, loop-region ring limits, loop
stream validation (header extent, record-boundary `loop_start_rel`,
truncation, all-gap-0 rejection), a device-decoder intro/loop restart
round-trip, and the same-tick wrap bound (a crafted all-gap-0 stream errors and
stops instead of hanging).

## Not covered

Pause/replacement/SFX (`ATMlib2FX-hlh.9`, implemented in the device backend),
the general authoring input matrix, packing tooling and game fit
(`ATMlib2FX-hlh.10`/`.11`). A stream is shippable only if its measured worst
service window fits the ring; the converter reports the window but does not
reject a stream whose per-record lengths fit while a multi-tick window does not
(that is a deployment decision). Loop streams additionally require the whole
loop region to fit the ring; larger loops (streaming wraps) are out of scope.
