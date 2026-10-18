# tools/atm-shrink — offline ATMlib2 song-shrink pass (ATMlib2FX-hlh.3)

Host-only build tooling that compresses an ATMlib2 packed score without changing
playback. It does not touch the device code or any PROGMEM traversal ABI.

## Pieces

| file | role |
| --- | --- |
| `shrink_core.[ch]` | reusable engine: packed-score parser, transforms, cost/depth model, emitters |
| `atm_shrink.c` | CLI: blob in → shrunk blob + drop-in header + text report |
| `score_dump.c` | extracts the packed PROGMEM blob from a song `.h`/`score.h` |
| `build.sh` | builds everything into `build/fx-port/shrink/bin/` |

`shrink_core` is format-only: it re-implements the traversal semantics of
`research/fx/tools/fx_compile_stream.c` (same model as the library decoder) and
never includes any spike source.

## Input format

Packed `ATM_SCORE_FMT_FULL` / `FULL_MONO` (the current library layout):

```
fmt, num_patterns, patterns_offset[2*n], num_channels, start_patterns[m], bodies
```

A body terminates with `0x61` (PATTERN_END / RETURN / STOP). The pre-2.x raw
`Song music[]` byte-array format has no pattern table (fmt byte `0x08`) and is
**rejected** with a clear message; the engine operates on the pattern-score
format only.

`score_dump.h` invocation selects the symbol/header at compile time
(`ATM_SHRINK_SCORE_HEADER`, `ATM_SHRINK_SCORE_SYMBOL`, `HAVE_SFX1`).

## Transforms

1. **Loop normalization** (`shrink_loop_normalize`). The canonical ATMlib2 loop
   is `ATM_CMD_M_SET_LOOP_PATTERN`; it is the only construct that restarts a
   finished score with no tick gap (library commit `130c9ca`). The pass detects
   and reports loop usage. Legacy `GOTO`/`REPEAT` back-edges only exist in the
   rejected raw format, so a canonical pattern score needs no rewrite and the
   transform is byte-neutral (`0`).
2. **Inline single-use patterns** (`shrink_inline_single_use`). A pattern that
   is referenced exactly once (a plain `CALL`, never an entry point or a
   `SET_LOOP_PATTERN` target) with body length `L <= 5` is spliced into its
   caller. Cost model: pattern-table entry `2 B` + `RETURN` `1 B` + `CALL`
   `2 B`. A `SET_LOOP_PATTERN` operand counts as a use: its target is never
   inlined away, and `shrink_finalize` remaps the operand together with the
   `CALL` operands when patterns are dropped (`shrink_validate` asserts every
   reference stays in range and alive).
3. **Share repeated command runs** (`shrink_share_runs`). A run of `L` bytes
   occurring `u` times becomes a new pattern + `CALL` sites when
   `u*L > L + 1 + 2 + 2u`. Runs containing `CALL`, pattern end, tempo or loop
   commands are never shared.

Every transform is value preserving. Call-nesting depth is validated from the
input score (`depth_before`) and on the final score: an input already reaching
`ATM_PATTERN_STACK_DEPTH` (3) contains `CALL`s that the library skips at
`pstack_index >= ATM_PATTERN_STACK_DEPTH-1` (`src/cmd_parse.c`), so rewriting it
cannot preserve playback and the CLI rejects it with exit 4 before transforming.
Depth roots are the channel entry patterns **and** every `SET_LOOP_PATTERN`
target: the library restarts a stopped channel — which always stopped at
`pstack_index` 0 — from the loop target (`src/atm_synth.c`), so a chain rooted
only at a loop target is counted exactly like a channel-entry chain.
The share pass additionally declines any candidate that would push the result
to the limit, and a post-finalize result at the limit is rejected the same way.

## Usage

```sh
tools/atm-shrink/build.sh
build/fx-port/shrink/bin/dump_song01_sfx score > score.bin
build/fx-port/shrink/bin/dump_song01_sfx sfx   > sfx1.bin
build/fx-port/shrink/bin/atm_shrink \
    --in score.bin --sfx sfx1.bin \
    --out-blob score.shrunk.bin --out-header song.h \
    --report report.txt --label song01_sfx
```

Options: `--label`, `--flat` (emit `const uint8_t score[] PROGMEM` instead of
the `struct score_data` drop-in header), `--no-loop`, `--no-inline`,
`--no-share`. The report lists byte totals, `patterns_before`/`patterns_after`,
`patterns_added`/`patterns_removed`, call depth before/after, loop status and
per-transform savings.

## Verification

```sh
tests/atm-shrink/run-tests.sh
```

Builds the tools, runs `tests/atm-shrink/selftest.c` (unit tests including a
traversal simulator that proves playback equivalence), shrinks the shipped
asset and the generated authoring fixture, checks the review regressions (the
`SET_LOOP_PATTERN` operand survives inlining with the emitted score byte-checked;
depth-3 `CALL` chains rooted at a channel entry point *and* at a
`SET_LOOP_PATTERN` target each exit 4 with default flags and with
`--no-inline --no-share`; a loop-rooted depth-2 control still shrinks
byte-identically), diffs the reference traces, measures flash before/after, and
writes sha256 evidence under `build/fx-port/shrink/`.
