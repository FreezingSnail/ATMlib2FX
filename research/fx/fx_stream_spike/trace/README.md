# Compiled FX stream trace harness (ATMlib2FX-aoe)

Host tooling for the compiled FX stream prototype. Nothing here is part of a
production image; no AVR bytes are contributed.

- `trace_main.c` compiles the device decoder on the host
  (`src/atm_synth.c` with `ATM_HAS_FX_STREAM=1`, which `#include`s
  `src/atm_fx_stream.c`) and drives it under the baseline osc.c timer contract
  (2000 Hz base, ISR down-counter, `2000/floor(2000/rate)` divider). It emits the
  same CSV schema as `ATMlib2FX-hlh.1`, except `cN_ps` (the removed traversal
  state) is printed as `0`.
- `avr_shim/avr/pgmspace.h` maps `PROGMEM`/`pgm_read_*`/`memcpy_P` for the host.
- `run-trace.sh` builds the converter + harness, runs twice for determinism and
  diffs the first 512 music ticks against
  `research/fx/footprint_baseline/trace/reference/reference_trace_music.csv`,
  dropping the `cN_ps` column from both sides.
- `absim_fx_harness.cpp` / `run-absim.sh` run a built image against the local
  Ardens absim core with the generated FX data image loaded, reporting USB-CDC
  serial (diag counters) and `min_stack`.

Usage:

```
research/fx/fx_stream_spike/trace/run-trace.sh 512
research/fx/fx_stream_spike/trace/run-absim.sh 12000
```

See `research/fx/fx-footprint-results.md` section 10.
