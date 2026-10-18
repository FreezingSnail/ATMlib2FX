# Reference playback trace (ATMlib2FX-hlh.1)

Deterministic, tick-level record of the **original** ATMlib2 implementation for
the `research/fx/footprint_baseline` fixture. Future FX-decoder candidates compare
against these values instead of against hand-invented timings.

## What is traced

The harness `trace_main.c` compiles the **unmodified** library sources for the
host:

- `src/atm_synth.c` (which `#include`s `src/cmd_parse.c`), and
- a `src/osc.c` substitution (`osc_setup` / `osc_set_tick_rate` /
  `osc_set_tick_callback` / `osc_get_tick_callback`) that reproduces the Timer3
  ISR callback scheduling exactly.

Because the score parser, command interpreter, effect code and tick handlers are
the real library code, the emitted values are the original implementation's
values. The host shim (`avr_shim/avr/pgmspace.h`) only maps `PROGMEM` /
`pgm_read_*` / `memcpy_P` onto ordinary memory.

## Scheduling contract

- Base timer: `OSC_SAMPLERATE / OSC_ISR_PRESCALER_DIV` = 2000 Hz.
- Each callback has the ISR's down-counter; it fires when the counter wraps
  `0 -> 0xFF` and reloads with `preset = 2000 / rate - 1`. This is the original
  `osc_set_tick_rate` math, **including its floor quantization** (`2000/rate`,
  not `rate` exactly). Example: rate 22 → `2000/22 = 90`, period 90 base events
  ≈ 22.22 Hz.
- Callback 0 = music, callback 1 = SFX, in the ISR's loop order.
- Zero-based music tick index counts completed music callbacks internally; the
  printed `M` `tick` column is that count after increment, i.e. 1..N (row
  `M,64` is the 64th music tick).
- In `sfx` mode the SFX track is started immediately after music tick `64`
  (row `M,64`) completes, i.e. at the tick-64 boundary; it then runs on its own
  tempo. Music keeps advancing; the borrowed channel is muted for music.

## Files

- `reference_trace_music.csv` — 512 music ticks, no SFX (`trace_main music 512`).
- `reference_trace_music_sfx.csv` — 512 music ticks + SFX started at tick 64
  (`trace_main sfx 512 64`). Contains 512 `M` rows and 23 `S` rows; the SFX runs
  to its natural stop.
- `checksums.txt` — sha256 of both traces (regenerated on equal runs).

Regenerate with `./run-trace.sh` (writes these files in place; it verifies two
runs are byte-identical). The host binary is written to `build/fx-port/trace/`.

## Regeneration note (ATMlib2FX-mgd)

music_sfx reference regenerated after ATMlib2FX-mgd: trigger_note() note-off returns after osc.vol=0 instead of falling through to trigger_both; sfx1 NOTE_OFF at S,12 -> 36 vol cells only (S,12-22 and M,89-113 c2_vol); music/basic traces byte-identical.

Only the `music_sfx` reference moved (`7d3ba7e1…27a1` → `10ec84de…083f`); the
`music` reference and the `basic` authoring golden are unchanged.

## CSV schema

One row per event. `event` is `M` (music tick) or `S` (SFX tick).

```
event,tick,base,tempo,active,
c0_inc,c0_mod,c0_vol,c0_note,c0_cvol,c0_cmod,c0_delay,c0_ps,
c0_sla,c0_slc,c0_slk,c0_arp,c0_art,c0_arc,c0_rec,c0_recn,c0_trd,c0_trt,c0_trc,c0_glc,c0_glk,c0_lp,
... c1..c3 ...
```

- `tick`: music tick number (`M`, 1-based) or SFX tick number (`S`).
- `base`: base-timer event at which the record happened (shows music/SFX
  coincidence: equal `base` values).
- `tempo`: `atmlib_state.tick_rate` (`M`) or `sfx_state.track_info.tick_rate` (`S`).
- `active`: `channel_active_mute` (bit0-3 mute, bit4-7 active).
- Per channel `cN_*`:
  - `inc` (`osc_params.phase_increment`, hex), `mod`, `vol` (oscillator params)
  - `note`, `cvol`, `cmod`, `delay` (hex), `ps` (`pstack_index`)
  - `sla/slc/slk` = `vf_slide.slide_amount`/`_config`/`_count`
  - `arp/art/arc` = `arpNotes`/`arpTiming`/`arpCount`
  - `rec/recn` = `reConfig`/`reCount`
  - `trd/trt/trc` = `treviDepth`/`treviConfig`/`treviCount`
  - `glc/glk` = `glisConfig`/`glisCount`
  - `lp` = `loop_pattern_index`

For `S` rows only the SFX channel (OSC_CH_TWO) is meaningful; the other
`cN_*` columns mirror the current music oscillator/channel arrays. All effects
are compiled in (`ATM_HAS_FX_NONE == 0`), so every effect column is populated.

Raw byte values are printed unsigned; `slide_amount` and `glisConfig` are
`int8_t`, so `0xFF` means −1.
