# Compile-time mixer gating — spike results (ATMlib2FX-hlh.4)

**Recommendation: GO.** Compile-gated per-channel and noise/LFSR mixer blocks
remove real flash and real ISR cycles, the all-on default is provably
byte-identical to the pre-flag library, SRAM is unchanged, and every gated
build boots and runs cleanly under the emulator. Adopt the macros and keep the
default all-on.

## Question

How many flash bytes and ISR cycles can be dropped by (a) omitting the
noise/LFSR mixer path when the build uses no noise channel, and (b) allowing a
channel mixer to be compiled out (the `WAVE_OFF` equivalent that T-arg/ATMlib
2.x implements as `ATM_WAVE_CH0..3 = PULSE/SQUARE/SAW/NOISE/OFF`, LFSR omitted
when no channel is noise)?

## Method

`src/osc.c` is the whole oscillator/mixer ISR (`ISR(TIMER3_COMPA_vect)`), and
its four per-channel mixing blocks plus the channel-3 LFSR noise generator are
inline asm. Each block is now wrapped in a preprocessor conditional
(additions only; default paths untouched):

| Macro | Default | Effect when 0 |
| --- | --- | --- |
| `ATM_HAS_OSC_CH0` | `1` | channel 0 phase-advance + square mixer not assembled |
| `ATM_HAS_OSC_CH1` | `1` | channel 1 phase-advance + square mixer not assembled |
| `ATM_HAS_OSC_CH2` | `1` | channel 2 phase-advance + square mixer not assembled |
| `ATM_HAS_OSC_CH3` | `1` | channel 3 LFSR noise generator + noise mixer not assembled |
| `ATM_HAS_NOISE` | `1` | master switch for the channel-3 LFSR noise path (0 removes it even if `ATM_HAS_OSC_CH3` stays 1) |

A gated channel's phase accumulator no longer advances and it adds nothing to
the mixer sum, so its output is silenced. Its command/effect processing in
`atm_synth.c`/`cmd_parse.c` is unchanged, so it still consumes score/SFX
commands — the `WAVE_OFF` contract. State arrays and `atm_synth.c` are not
modified.

All flags are all-on by default. Definitions live in `src/osc.h` behind
`#ifndef` guards, so they can be set from the C compile of `src/osc.c`
(`compiler.c.extra_flags`).

### Reproduction

```
MFP_LANE=build/fx-port/mixer research/fx/tools/measure-footprint.sh
```

The script was extended additively: a `MFP_LANE` override (default unchanged at
`build/fx-port`) writes the new lane without touching the retained hlh.1 lane,
and the gated variants are appended to the existing variant arrays. It now also
writes `isr-cycles.txt` (static ISR cycles, see below). Supporting evidence is
also collected by hand (trace harness, absim smoke) into the same lane; see
`build/fx-port/mixer/`.

## Identity and toolchain

| Item | Value |
| --- | --- |
| Repo HEAD | `c5994831d330f4a88aa6d959b870ea31524a3614` |
| FQBN | `arduboy-homemade:avr:arduboy-fx` (board package 1.4.0) |
| arduino-cli | 1.2.0 (Homebrew) |
| AVR-GCC | 7.3.0 (`7.3.0-atmel3.6.1-arduino7`) |
| Local ATMlib | 1.2.4 (this repo); board-package ATMlib 1.2.6 skipped |
| Fixture | `research/fx/footprint_baseline` (`-DFP_AUDIO=<n>`) |
| Song input | `examples/arduino/songs/song01_sfx/song.h` (unchanged) |
| Emulator | local Ardens absim core (`connorfranc/code/arduboy/Ardens`) |

## Flash / SRAM matrix

Lane `build/fx-port/mixer`, HEAD `c599483`. `program = text + data`; `sram =
data + bss`. All numbers are whole-image bytes from `avr-size`.

| Variant | Flags | program | text | data | bss | sram | Δtext vs default |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `shell` | (no ATMlib) | 4928 | 4890 | 38 | 1141 | 1179 | — |
| `music` (default) | — | 8064 | 8026 | 38 | 1324 | 1362 | 0 |
| `music_sfx` (default) | — | 8350 | 8312 | 38 | 1370 | 1408 | 0 |
| `music_ch0_off` | `-DATM_HAS_OSC_CH0=0` | 8012 | 7974 | 38 | 1324 | 1362 | **−52** |
| `music_ch1_off` | `-DATM_HAS_OSC_CH1=0` | 8012 | 7974 | 38 | 1324 | 1362 | **−52** |
| `music_ch2_off` | `-DATM_HAS_OSC_CH2=0` | 8012 | 7974 | 38 | 1324 | 1362 | **−52** |
| `music_ch3_off` | `-DATM_HAS_OSC_CH3=0` | 8014 | 7976 | 38 | 1324 | 1362 | **−50** |
| `music_no_noise` | `-DATM_HAS_NOISE=0` | 8014 | 7976 | 38 | 1324 | 1362 | **−50** |
| `music_1ch` | `CH1/CH2/CH3=0 NOISE=0` | 7910 | 7872 | 38 | 1324 | 1362 | **−154** |
| `music_sfx_no_noise` | `FP_AUDIO=2` `-DATM_HAS_NOISE=0` | 8300 | 8262 | 38 | 1370 | 1408 | **−50** |

Notes:

- **SRAM is unchanged** in every variant (`data`/`bss` identical): gating removes
  code only. This is expected — the state arrays are shared and untouched.
- A single square-channel mixer costs **52 flash bytes**; the channel-3
  noise/LFSR block costs **50**. Removing all three square channels + noise
  (`music_1ch`, one channel left) costs **154 bytes** — 8 bytes more than the
  sum of the individual deltas, i.e. a small extra from picker/relocation
  interaction. Report the measured total, not the sum.
- Relative to the default music image (8064 program bytes) the gated extremes
  are −50 bytes (0.6 %) to −154 bytes (1.9 %).

## ISR cycle cost

The emulator's **total** cycle count is timer/sample-rate bound and is identical
across variants (127 983 762 cycles for 8 s ≈ 16 MHz), so the mixer ISR cost is
measured **statically**: sum the documented AVR instruction timings over
`__vector_32` (`TIMER3_COMPA_vect` on ATmega32U4). `base` assumes
data-dependent branches not taken, `max` assumes taken; deltas are vs the
default music ISR.

| Variant | base | max | instr | Δbase | Δmax |
| --- | ---: | ---: | ---: | ---: | ---: |
| `music` (default) | 146 | 152 | 102 | 0 | 0 |
| `music_ch0_off` | 120 | 125 | 84 | −26 | −27 |
| `music_ch1_off` | 120 | 125 | 84 | −26 | −27 |
| `music_ch2_off` | 120 | 125 | 84 | −26 | −27 |
| `music_ch3_off` | 121 | 126 | 82 | −25 | −26 |
| `music_no_noise` | 121 | 126 | 82 | −25 | −26 |
| `music_1ch` | 69 | 72 | 46 | −77 | −80 |

Converted to CPU load at the 16 kHz sample rate (16 MHz core):

- one square channel off ≈ 26 × 16 000 = **416 k cycles/s ≈ 2.6 %**;
- noise/LFSR off ≈ 25 × 16 000 = **400 k cycles/s ≈ 2.5 %**;
- all three square channels + noise off ≈ 77 × 16 000 = **1.232 M cycles/s ≈ 7.7 %**.

The mixer ISR itself is 146 cycles base ≈ 14.6 % of the core; the gated-1ch
extreme leaves the unavoidable tick-handler tail at 69 cycles ≈ 6.9 %.

## Default byte-identity (all-on)

- `music` default `.text` sha256 `129dc2e755023557bf58fad8b72a7f688f1a63a6ebac3155791a0128640bdcff`
  is **byte-identical** to the retained pre-change hlh.1 ELF and to a build
  against a reconstructed pre-change library (gating directives stripped).
- `music_sfx` default `.text` sha256 `1acc536ef6d613b47fcdce50646bc84fd49deaa6913feab74560f94e4c5f9ed8`
  is **byte-identical** to the same source built without the gating directives
  (the retained hlh.1 `music_sfx` ELF predates HEAD `c599483` and is not a valid
  comparison point).
- Reference trace harness output is byte-identical to the committed references:
  `music` `87e55846b3abaf214a8cb68355a8db52a431e7b75ae7b0ee0b7b7c3447e5d01d`,
  `music_sfx` `10ec84de82eb11d68bd7ccd56f328f9414c2eb44e23b80b4b9e20506f184083f`.

## Audio-path verification

- **Trace equivalence.** The host trace harness (music and music_sfx, 512 ticks,
  SFX at tick 64) reproduces the committed reference CSVs byte-for-byte, so the
  score/SFX command interpretation and channel state are unchanged by the
  gating work (the gating only removes mixer asm, which the host harness
  substitutes).
- **Emulator smoke.** Every variant (default music, default music_sfx, and all
  gated variants) boots and runs 8 s in the Ardens absim core with
  `autobreaks=0x0`, `pushed=1` (the ISR ran), `serial_bytes=0`, and positive
  stack headroom (1117 bytes music / 1074 bytes music_sfx). Full table in
  `build/fx-port/mixer/absim-smoke.txt`.
- **Static mixer evidence.** Disassembly of the gated `music_1ch` ISR
  (`build/fx-port/mixer/isr-{default,1ch}.dis`, `isr-diff.txt`) shows the removed
  instructions are only channel/LFSR blocks: 59 instructions removed, 0 added
  (the three differing lines are branch targets relocated by the shorter
  vector). The surviving code still advances the channel-0 phase accumulator
  (`sts 0x064A`) and still writes the PWM compare/high registers
  (`sts 0x00CF` = `OCR4A`, `sts 0x00BF` = `TC4H`), so the mixer output path is
  intact and only the gated channels are silent.

## Reproduction artifacts (lane `build/fx-port/mixer/`)

| File | Contents |
| --- | --- |
| `measure-run.txt` | full `measure-footprint.sh` console output |
| `footprint-summary.txt` | variant matrix CSV (flash + SRAM) |
| `isr-cycles.txt` / `isr-cycles.awk` | static ISR cycle table + cost model |
| `absim-smoke.txt` | emulator smoke results per variant |
| `isr-default.dis`, `isr-1ch.dis`, `isr-diff.txt` | ISR disassembly + removed-instruction diff |
| `trace_music.csv`, `trace_music_sfx.csv` | host trace, compared byte-for-byte to the reference |
| `avr-<variant>/…elf`, `build-<variant>.log` | per-variant ELF and full build log |
| `prechange-lib/`, `prechange-avr-*` | reconstructed pre-change library + control builds for byte-identity |

## Recommendation

**GO.** Adopt the `ATM_HAS_OSC_CHx` / `ATM_HAS_NOISE` macros with all-on
defaults. The default build is provably unchanged (byte-identical `.text`, no
SRAM change), and gating is a safe, per-song opt-in that removes 50–154 flash
bytes and up to ~7.7 % of the ISR's CPU load. The highest-value, lowest-risk use
is the noise/LFSR omission (−50 bytes, −2.5 % cycles) for the common case of a
build whose music uses no noise channel; per-channel `OFF` is available for
space-constrained single/dual-channel ports. No production `src/` change beyond
the compile-gated blocks is needed, and no runtime or format change is involved.
