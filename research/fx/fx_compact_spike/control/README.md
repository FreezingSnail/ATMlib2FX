# Compact control + SFX lane (ATMlib2FX-hlh.9)

Second measurement lane for the compact directly-consumed FX backend. It adds
the pause/replacement/arming control contract and an independent-tempo SFX
overlay, without touching the retained `ATMlib2FX-hlh.5` compact lane
(`build/fx-port/compact/`) or its ELFs.

Everything here is **build-time gated**:

* `ATM_HAS_FX_COMPACT=1` selects the compact backend (default `0`; the legacy
  PROGMEM library build is byte-identical — the lane rebuilds the hlh.1 music
  fixture and compares `.text` against the retained ELF).
* `ATM_FX_COMPACT_SFX=1` adds the SFX overlay. Default `0` pays nothing.
* `ATM_FX_COMPACT_DIAG=1` adds counters and the USB-CDC report.

## Files

| file | role |
| --- | --- |
| `fx_compile_sfx.c` | encodes the `song01_sfx` `sfx1` fixture into a compact SFX stream (`.bin` + PROGMEM `.h`) |
| `control_test.c` | host tests: prefill-before-arm, pause/resume position + mute/restore, atomic replacement, stop-mute, SFX borrow/restore/replacement |
| `sfx_trace_main.c` | host music+SFX trace harness; diffs against the original reference trace |
| `run-absim.sh` | absim device run of the diagnostic SFX image |

Driver: `research/fx/tools/build-fx-control.sh` (builds assets, runs both host
tests, builds the AVR images, prints `avr-size`, hashes evidence). Outputs land
under `build/fx-port/control/`.

```
research/fx/tools/build-fx-control.sh                       # assets + host tests + AVR sizes
research/fx/fx_compact_spike/control/run-absim.sh 12000     # absim device semantics run
```

## What the control contract is

* **Prefill before arm.** `atm_fx_compact_play` resets the descriptor, fills the
  ring from the fetch callback (SPI, interrupts enabled, callback still
  unregistered), and only then arms the timer. The first due tick cannot
  underrun.
* **Pause/resume.** `atm_fx_compact_pause` keeps the ring position, gap, channel
  and effect state, saves each owned voice's oscillator volume, mutes it, and
  unregisters the timer. `atm_fx_compact_resume` restores the saved volumes and
  re-arms at the same position. `atm_synth_set_score_paused` /
  `atm_synth_get_score_paused` delegate to these for the compact backend.
* **Stop.** `atm_fx_compact_stop` unregisters, stops any SFX overlay, and mutes
  the owned voices.
* **Atomic replacement.** `play` runs under an interrupt-restoring atomic block
  on AVR: it stops/mutes the previous track, resets the descriptor, re-initializes
  the channels, discards unread bytes, prefills, then arms. No partially mixed
  track state is observable.
* **SFX overlay.** `atm_fx_compact_play_sfx(ch, stream, len)` plays a compact
  record stream stored in **PROGMEM** on tick callback 1 at its own tempo. It
  saves + zeroes the borrowed music voice and redirects the music channel's
  effects into the saved shadow, so music keeps advancing behind the borrowed
  channel. Natural stop, explicit stop and replacement all restore the borrowed
  voice from that shadow.

The full ownership/API contract is documented at the top of
`src/atm_fx_compact.h`.

## Storage decision

The SFX is stored as a **PROGMEM compact stream** (same record framing as
music), read directly by the timer with `pgm_read_byte`. This needs no FX SPI,
no second ring and no second queue. Measured costs and the rejected alternatives
are recorded in `research/fx/fx-architecture-decision.md` ("hlh.9" section).

## Evidence

`build/fx-port/control/` retains: `control_test.out`, `sfx_equivalence.txt`
(512-tick music+SFX MATCH), `control-summary.csv`, `absim-control.txt`, and
`evidence-sha256.txt`. Source identity is `source-hashes.txt`; no git commands
are used.
