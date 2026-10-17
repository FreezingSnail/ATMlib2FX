# Piezo (approx.) verification — ATMlib2FX-3ii.9 (verification only)

This records the original ATMlib2FX-3ii.9 verification run. Its compact evidence
was promoted from the ignored build directory by ATMlib2FX-3ii.10. The tested
HTML was copied byte-for-byte to [showcase/review.html](../../../examples/music_authoring/showcase/review.html), SHA-256
`4247bad8ce038690a05d910a671cc4337ea341582f9bdcc1ee2d50087bcf538d`.
Paths inside the captured JSON/stdout describe the original run.

## Command

```
node research/music-authoring/piezo/piezo-verify.mjs \
  examples/music_authoring/showcase/review.html \
  build/music-authoring/piezo-tests
```

Real installed `Google Chrome 155.0.8059.40`, headless, offline `file://`, no
network (CDP on localhost only). Root's direct Chrome launch abort (code -6) was
not reproduced here; launch via node `spawn` (as in the .6 walkthrough) worked.

## 1. Generated UI (verified)

- `#sound-profile` has exactly two options: `raw` "Raw emulator" (selected,
  enabled) and `piezo` "Piezo (approx.)". Default = raw. Audio controls visible.
- Audio status "Matching preview loaded (WAV sha256 68768532bd63…)".
- Embedded audio `available:true`, `wav_sha256 =
  68768532bd638a8537c8e513f126f471f46a6da7636d8b3b2032e2594cbc78f6` (unchanged),
  `first_music_callback_sample = 1045`, `total_ticks = 400`.
- Four lanes: pulse0, pulse1, pulse2, noise.
- Before any profile change: probe `contexts:0, sources:0` (no Web Audio created).

## 2. Profile switching / lifecycle (verified)

- piezo selected via `change` with `userGesture` → `selectValue:"piezo"`, option
  enabled, `ctxState:"running"`, live node graph captured: highpass 700 Hz,
  peaking 3300 Hz Q1.4 gain+6, lowpass 7000 Hz, output gain 0.5 (all
  `Q ≈ -3.010299921` in the two edge filters).
- `rawGain 0 / piezoGain 1` in piezo; `rawGain 1 / piezoGain 0` back in raw.
- Audio element advanced while playing: raw 0.343 s, piezo 0.860 s.
- Identity survived profile changes: same `src`, `duration`, `playbackRate`.
- Repeat toggles (8×): `contexts:1, sources:1`, `sourceIsSameElement:true`,
  3 filters total → no duplicate source/context, no doubled playback.
- Seek/restart under piezo: restart `0.0209 s · tick 0` (measured 1045 offset),
  mid `4.259 s · tick 212`, end `8.498 s · tick 400`.

## 3. Native OfflineAudioContext response (verified, uncalibrated)

`window.ATMlibAudition.createPiezoChain` measured with `getFrequencyResponse`
and offline sine RMS (48 kHz):

| Point | Filter response (incl. 0.5 out) | Sine ratio piezo/raw |
| --- | --- | --- |
| 0 Hz (DC) | 0.0 | – |
| 100 Hz | 0.0102 | 0.0102 |
| 3300 Hz | 0.9777 | 0.9776 |
| 12000 Hz | 0.1205 | 0.1205 |
| 20 kHz | 0.0087 | – |

- Bass and treble are lower than the 3300 Hz mid band, as intended.
- Raw branch is unity/bypass: raw sine RMS = 0.7071067 at every frequency
  (ratio 1.0); graph raw gain = 1.
- DC settles to 0: ConstantSource(1.0) through the chain → tail mean abs = 0.0.
- This is an explicitly uncalibrated approximation; no hardware claim.

## 3b. Live MediaElementAudioSource emits nonzero AC (verified)

Diagnostic `AnalyserNode` (2048-pt) tapped the live source on an audible segment
(window 0.321–1.321 s; embedded PCM decoded in-page for reference):

| Profile | mean RMS | max RMS | PCM RMS (ref) | ratio |
| --- | --- | --- | --- | --- |
| raw | 0.010574 | 0.016279 | 0.011527 | 0.917 |
| piezo | 0.010617 | 0.016237 | 0.011527 | 0.921 |

Nonzero AC (not silence), same order as the embedded blob WAV sample data
(`data` chunk at offset 44), so the `file://` blob does not route to silence via
an origin/CORS taint. The analyser taps the source before the router gains, so
raw and piezo match; band coloration is covered by the offline measurements.

## 4. Failure fallbacks (verified)

- **No AudioContext/webkitAudioContext** (deleted before page scripts): choosing
  piezo reverts to `selectValue:"raw"`, piezo option disabled, note = "Piezo
  preview is unavailable in this browser. Raw emulator audio remains available.",
  `contexts:0 sources:0`, raw native playback advanced (0.714 s).
- **Resume rejection** (context forced `state:"suspended"` via an own getter, and
  `resume()` rejects before `createMediaElementSource`): `resumes:1`,
  `ctxState:"suspended"`, `sources:0`, reverted to raw, piezo disabled, raw
  native playback advanced (0.216 → 0.811 s).
- Unhandled JS exceptions: none in any scenario
  (`ui:[]`, `no_api:[]`, `resume_reject:[]`).

## 5. Network (verified)

`external_requests: []`. Only `file:` and `blob:` requests observed.

## Retained artifacts (beside this summary)

- `piezo-verify.mjs` — bounded verification driver
- `piezo-verify.json` — full evidence
- `run-stdout.txt` — console summary
- `piezo-selected.png` — screenshot (piezo selected)

Temporary `chrome-profile-*/` browser profiles were removed during cleanup;
they are recreated in the output directory when rerunning the driver.

## Unverified / limitations

- No audible listening (headless `--mute-audio`); no physical-piezo acoustics.
- Live-source ratio ≈0.92 is not 1.0 (analyser taps pre-router gain; sampling
  window alignment); the claim is "nonzero AC comparable to embedded PCM".
- No real truncated preview in this run; not part of this assignment.
- Root's standalone Chrome `-6` abort not reproduced to diagnose; a working
  launch path (node spawn + CDP) was used instead.
