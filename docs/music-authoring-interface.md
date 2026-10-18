# Model music authoring interface

Status: proposed authoring contract; planning only. The commands and JSON format
below are not implemented. Planning beads: `ATMlib2FX-ba0` and the HTML review
amendment `ATMlib2FX-3ii.5`. Delivery epic:
`ATMlib2FX-3ii`. This design treats “model” as an LLM composing music.

## Purpose and boundary

Give a model a small musical source language, precise errors, and something it
can listen to or have the user audition. Keep parsing, composition, pattern
expansion, validation and reporting on the desktop. Ship only compiled song
data to the device; add no JSON parser, authoring metadata or model support to
the AVR playback engine.

Use strict, versioned JSON as the first interface. A local CLI is the model's
initial transport; a local HTML/JavaScript viewer is the human review interface.
An MCP adapter can wrap the same functions later if direct model tool access is
useful; it is not a prerequisite. Do not couple authoring syntax to the
experimental FX stream framing.

The workflow is: read capabilities and a small example; write a score; validate;
open its track viewer; render and audition; revise and review the score; then
explicitly build for the selected storage backend. Generating or opening a
viewer does not export, pack or flash FX data.
Do not require a model to generate C macros, offsets, bytecode or packed flags.

## Findings from the current source

| Finding | Source | Consequence |
|---|---|---|
| Three pulse oscillators and one noise oscillator | `src/osc.c`, oscillator sections | Name channels `pulse0`, `pulse1`, `pulse2`, `noise`; do not promise triangle, saw or samples. Comments in some example scores describe different waveforms. |
| Note IDs 1–63 span C2–D7; 0 is the note-off command | `src/atm_cmd_constants.h` | Accept named pitches in that range. Reject out-of-range pitches rather than letting the engine mask indices. |
| Volume and pulse modulation are byte quantities | `src/osc.h`, `src/cmd_parse.c` | Use explicit integer 0–255 units. Start with conservative authored levels; do not silently normalize. |
| Tempo commands request a tick rate, not BPM | `src/osc.c:osc_set_tick_rate`, `src/osc.h` | Use ticks as the canonical clock; report the timer-quantized effective rate and derived BPM. Rates below 8 are unsupported by the timer divider. |
| Slides share one per-channel effect slot; LFOs share another | `src/atm_synth.h`, `src/cmd_parse.c` | Advanced effect syntax must expose conflicts and cannot promise independent simultaneous slide/LFO families. |
| The current converter includes a fixed `song.h` fixture | `research/fx/tools/fx_compile_stream.c` | It is not a general score reader or authoring compiler. Introduce a validated host intermediate representation. |
| Existing host traces stub the oscillator/timer layer | `research/fx/footprint_baseline/trace/trace_main.c` | Traces are useful correctness evidence, but do not supply an audio preview. |
| An absim runner can execute compiled AVR images with FX data | `research/fx/fx_stream_spike/trace/absim_fx_harness.cpp` | Reuse the integration approach for preview research. WAV capture has not been demonstrated by this plan. |
| The FX spike is behaviorally useful but has no demonstrated engine memory saving | `research/fx/fx-footprint-results.md`, section 10 | FX encoding and public runtime contracts remain owned by `ATMlib2FX-hlh.2`. |

One source discrepancy needs explicit coverage: in `cmd_parse.c:trigger_note`,
the note-zero branch writes zero volume and then appears to fall through to
`trigger_both`, which restores the channel volume. Do not assume raw NOTE_OFF
produces silence. Authoring gate/rest lowering should explicitly set volume to
zero and restore the authored volume for the next note. Verify actual traces
and audio before claiming this works. Any engine behavior fix belongs in its
own bead, with original-equivalence implications recorded.

## First version: a finite, conservative musical subset

Support notes, rests, pulse duty, fixed per-instrument volume, finite pattern
reuse, and finite arrangements. Each physical channel is monophonic. An
instrument is a host-side preset, not an additional hardware voice.

Defer live effects, tempo changes and FX SFX to explicit
capability extensions. Reject an unsupported request with a diagnostic. Finite
arrangement repetition is permitted because the compiler can expand it within
declared host limits. The optional root `"loop": true` repeats the entire
arrangement through the original PROGMEM engine's `SET_LOOP_PATTERN` command.
Omitting it (or setting false) retains finite playback and existing byte goldens.
This is a PROGMEM capability; no FX loop contract is selected here.

### Proposed JSON

```json
{
  "format": "atmlib-score",
  "version": 1,
  "id": "small_victory",
  "clock": {"tick_rate": 50, "ticks_per_beat": 25, "beats_per_bar": 4},
  "instruments": {
    "lead": {"voice": "pulse", "volume": 80, "duty": 127}
  },
  "patterns": {
    "phrase": {
      "ticks": 100,
      "events": [
        {"at": 0, "note": "C4", "duration": 20, "instrument": "lead"},
        {"at": 25, "note": "E4", "duration": 20, "instrument": "lead"},
        {"at": 50, "note": "G4", "duration": 20, "instrument": "lead"},
        {"at": 75, "note": "C5", "duration": 20, "instrument": "lead"}
      ]
    }
  },
  "tracks": {
    "pulse0": [{"pattern": "phrase", "repeat": 2}]
  }
}
```

The result is 200 ticks, eight beats, approximately four seconds at the
effective 50 Hz tick rate. Unspecified channels stay silent. Empty regions of a
pattern and the five ticks after each gate close are silent. This example is a
contract illustration, not a claimed playable artifact.

### Exact source rules

- `format` and `version` are required. Reject unknown fields, duplicate JSON
  keys, nonfinite values, floats where integers are required, and unsupported
  versions. IDs and references are case sensitive; restrict identifiers to
  `[A-Za-z_][A-Za-z0-9_]*` with maximum length 64.
- Require `clock.tick_rate` in 8–255, `ticks_per_beat` in 1–256, and
  `beats_per_bar` in 1–16. Do not default a missing clock. `tick_rate` requests
  the library rate; the *actual* rate is the quotient
  `2000 / floor(2000 / tick_rate)` for the current timer configuration.
  Requested 255 yields exactly `2000/7 ≈ 285.714 Hz`, not a rounded 285.
  Reported durations derive from the integer divider, not the quotient:
  `seconds = total_ticks * floor(2000 / tick_rate) / 2000`.
- Musical metadata does not change playback: report
  `effective_bpm = effective_tick_rate * 60 / ticks_per_beat`.
  The device divider (`src/osc.c:osc_set_tick_rate`) is untouched; only host
  time reporting is corrected.
  A future BPM convenience input must show its chosen integer mapping and
  error; never reinterpret BPM as the engine tempo byte.
- Require pattern `ticks` to be a positive integer. `events` are ordered by
  ascending `at`, in the pattern's half-open interval `[0, ticks)`. Each event
  has nonnegative integer `at`, positive integer `duration`, and
  `at + duration <= ticks`. V1 permits only one note event at any timestamp in
  a pattern and rejects overlapping durations. Adjacent notes are allowed.
- Accept natural notes and sharps such as `C4`, `F#3`, `D7`; range C2–D7.
  Flats, MIDI numbers, chords, microtones and arbitrary frequencies are not
  v1 syntax. Noise events use the same note token as a library frequency/seed
  control, not a promise of pitched percussion.
- Each event references an instrument. Pulse instruments require `voice`,
  `volume` and `duty`; noise instruments require `voice` and `volume` and
  reject `duty`. Values are integers in 0–255. Patterns containing noise
  instruments may only be used on `noise`; pulse patterns only on pulse tracks.
- Track keys are the four fixed channel names. Require at least one track;
  missing tracks are silent. Each track is a nonempty array of pattern uses,
  each with a required `repeat` integer in 1–256. Uses concatenate at exact
  pattern lengths; all v1 repetition is finite and contains no nested calls.
- Derive song length from the longest expanded track. Pad shorter tracks with
  silence. An explicit rest is an empty time span, not a special pitched note.
  No sustain or effect state crosses a pattern boundary in v1.
- Optional `loop` must be a boolean. For true, pad every participating channel
  to the longest track, set a per-channel loop target, and stop together. The
  original engine restarts all targets within that same callback, with no extra
  silent tick. Missing channels stay silent. Reviews describe one cycle with
  `loop.start_tick: 0` and `loop.end_tick: total_ticks`; bounded renders include
  one cycle and capture tail (which contains the start of the next cycle).
- Define tick zero as the first music callback after playback starts. At a
  boundary: finish the previous gate by muting, then initialize and trigger any
  new event. Simultaneous channels execute in physical order 0, 1, 2, 3.
  End-of-song explicitly mutes all owned channels before terminating.
- Each new note restores its instrument's volume and pulse duty. The v1
  compiler establishes a known effect-free initial state. Do not emit resets
  every tick; host lowering may remove redundant writes only after equivalence
  evidence shows that the removal preserves state and audible output.

Host admission limits for v1 are proposed as: 64 instruments, 256 patterns,
4096 source events, 4096 expanded pattern uses, 65536 expanded note events,
and 1048576 total song ticks. All arithmetic is checked before allocation or
expansion. Cap rendered output separately at 60 seconds by default and 300
seconds maximum; render truncation must be reported. These are host safeguards,
not decoder guarantees. Each backend must apply its own stricter limits on
offset widths, asset extents, due groups and supported features. Do not expose
raw bytes or arbitrary embedded code as a way around validation.

## Compiler boundary

Lower the score into ordered host events with absolute song tick, physical
channel, stable ordering, typed command operands, and source JSON Pointer.
Retain a separate terminal boundary. This representation is host-only.

The frontend owns musical timing, gate/rest semantics, instruments, validation
and finite arrangement expansion. Backends own byte encoding, packing,
endianness, permitted feature set and playback constraints. Never serialize a
host C struct directly as AVR score data. Never execute generated C from an
untrusted authoring file.

Initially export a deterministic original PROGMEM score and generated header,
with a fixed-width explicit serializer and original-engine playback oracle.
Record how initial tempo and terminal channel handling are encoded; test
one-tick gates and adjacent pattern boundaries for extra-tick errors. Legacy
pattern/offset and call-stack limits must be checked; a flattened bounded
representation is acceptable and must report its asset cost.

FX export is a separate adapter after `ATMlib2FX-hlh.2` settles the playback
contract. The fixture compiler is reference material, not a stable backend API.
The authoring format is not blocked by that decision; promising production FX
output is blocked. Check the chosen due-group and service-gap admission rules
before emitting an FX artifact.

## Proposed CLI and feedback contract

```sh
atm-music capabilities --json
atm-music validate song.json --backend progmem --json
atm-music inspect song.json --out review.html --json
atm-music render song.json --backend progmem --seconds 8 --out preview/ --json
atm-music inspect song.json --audio-preview preview/ --out review.html --json
atm-music build song.json --backend progmem --out generated/ --json
```

These commands are proposed. `--backend fx` is advertised only when its adapter
is supported. A capability response lists schema version, implemented features,
channel/pitch ranges, host limits, backend availability, tool version, engine
identity and render provenance. The model reads it at the start of a session;
backend capability absence must be explicit.

All command JSON goes to stdout and human logs to stderr. Exit codes: 0 success,
2 invalid score or unsupported capability, 3 tool/build/render failure.
Every result includes `ok`, `diagnostics` and available artifact paths. Errors
carry a stable code, severity, JSON Pointer and suggested correction. For example:

```json
{
  "ok": false,
  "diagnostics": [{
    "code": "PITCH_RANGE",
    "severity": "error",
    "path": "/patterns/phrase/events/0/note",
    "message": "E7 is above D7.",
    "suggestion": "Choose a pitch between C2 and D7."
  }],
  "artifacts": {}
}
```

Also distinguish `EVENT_OVERLAP`, `EVENT_OUTSIDE_PATTERN`, `UNKNOWN_INSTRUMENT`,
`VOICE_CHANNEL_MISMATCH`, `LIMIT_EXCEEDED`, `BACKEND_UNAVAILABLE`, and
`DUE_GROUP_TOO_LARGE`. Do not silently quantize time, drop voices, transpose
out-of-range notes, truncate arrangements or disable requested effects.

Successful validation reports expanded duration, requested/effective tick rate,
effective BPM, channel use and required features. Build reports source and
artifact hashes, backend version and asset bytes. Report measured AVR image,
static SRAM, buffer and stack costs only when an actual identified build/run
produced them. Mark unavailable measurements as unknown; distinguish a song
asset byte count from engine cost and whole-game fit.

## Local HTML/JavaScript track viewer

The owner requires viewing the tracks before committing the song to FX. Make
this a normal part of the review workflow. `inspect` validates the source and
generates a standalone `review.html`, with embedded compiler data and local
JavaScript/CSS, that can be opened directly in a browser. It requires no hosted
site, account, network access, installation of a browser app, or selected FX
backend. It adds no AVR runtime code or state.

The first viewer is a review tool. The model edits the source JSON and
regenerates the review; a graphical song editor can be scoped later.

### Track views and inspection

- Show all four named physical channels on one shared horizontal timeline,
  including silent channels. Offer a piano-roll view and a tracker-style event
  table. Label noise frequency/seed control separately from melodic pitch.
- Draw notes with their gate lengths, silent gaps, instrument identity,
  concatenated pattern boundaries and repetition indices. Provide fit-to-song,
  horizontal zoom/pan and rulers in ticks, bars/beats and effective seconds.
- Selecting a note shows channel, pitch, start tick, duration, instrument,
  volume/duty where applicable, pattern instance and original JSON Pointer.
  Preserve source maps through repetitions so revisions can target the source.
- Show requested/effective tick rate, effective BPM, full song duration,
  diagnostics, backend availability and any measured or unknown asset/resource
  costs. Diagnostics remain readable without relying on color alone.
- A visual track visibility toggle must be labeled as visibility. Audio solo
  and mute are deferred until separately rendered or otherwise verified audio
  supports them; hiding a lane does not change the WAV.

### One timeline interpretation

Extend the frontend's canonical host representation with a versioned review
payload: exact validated source digest, canonical event digest, clock,
total_ticks, four channel descriptors, expanded note spans, pattern-instance
boundaries, source pointers, diagnostics and tool/engine identity. Hash the
original input bytes for source identity; use a separately specified canonical
serialization for event identity.

`inspect` uses this same data for the HTML. JavaScript draws and selects it;
it does not independently parse patterns, expand repetition, lower effects,
or choose timer rounding. Preserve this payload as an inspectable JSON report
alongside HTML, using a documented deterministic output name. This avoids
maintaining a second musical compiler in the browser.

Embed JSON as inert data with correct escaping, including script terminators;
render authored strings as text, never as executable HTML/JavaScript. Bound
viewer work by the admitted host limits and draw only the visible window for
large timelines. Use accessible labels and keyboard selection for note details.

### Audition and source identity

Without a WAV, the viewer can inspect and navigate the whole timeline, but
must clearly say that audio is unavailable. With `--audio-preview preview/`,
load the renderer's report and WAV, check source/event digest and render
provenance, and embed the matching audio in the HTML. Reject mismatched audio
rather than letting a previous revision play under a new score.

Provide play/pause, seek, restart and a synchronized playhead driven by the
audio element's playback time. The render report must specify the offset from
the first music callback to WAV sample zero; account for startup latency and
the effective tick rate when mapping time to notes. If the WAV covers only a
bounded prefix, mark the rendered range and disable audition beyond it. Do not
present visual navigation outside the rendered range as audible playback.

After revising JSON, regenerate HTML and WAV. Export remains a deliberate CLI
build of that JSON. The review shows source identity and build reports retain
it so the user can compare the reviewed revision with exported artifacts. Do
not require a persistent approval state, and do not put FX write/upload controls
inside the first viewer.

## Audio preview and model iteration

Provide a bounded WAV preview plus event/state trace. Prefer executing an AVR
image through absim and extracting audio if its audio API supports it. The
existing runner proves program execution, not audio capture. Preview delivery
must first establish the capture API, sample format/rate, deterministic startup,
noise seed and audio-enabled state. Record emulator/core/engine/tool versions.

If a host synthesis path is needed, it must reproduce the actual oscillator,
noise, timer quantization and effect behavior, with comparison against emulator
output. A generic MIDI soundfont or synthesized sine-wave demo cannot serve as
the library preview oracle. A trace-only fallback must identify that no audio
was rendered and cannot satisfy preview acceptance.

Keep rendering instrumentation and its cost out of production footprint claims.
Verify audible silence in gaps and after end, pulse duty, noise repeatability,
tempo/duration, one-tick notes, and multiple simultaneous channels. Silence must
be measured from captured output relative to the renderer's documented neutral
level, rather than inferred solely from event names.

Give the model paths to the WAV, trace and reports. If the model supports audio
input, it can inspect the WAV; otherwise the user auditions it. Do not claim
automatic musical judgment from numeric traces. The model revises the JSON
source and repeats validation/rendering, rather than hand-editing generated
headers or binary assets.

Provide a short authoring guide with this example, the exact pitch/clock/channel
rules, and instructions to read capabilities, validate, generate/open the HTML
track review, render and audition, revise, then explicitly export. Report HTML,
WAV and source paths together. A composing brief can specify mood, length,
density, register and channel
roles in natural language; those are composition goals, not required engine
fields. Keep an optional agent skill or MCP transport as follow-up packaging.

## Deferred extensions and unresolved evidence

- Partial-song loops, FX loops and tempo changes require selected playback
  contracts and original-equivalent boundary tests. Whole-song PROGMEM loops
  are supported for the effect-free v1 subset above.
- Advanced effects require named typed operands, documented parameter units and
  shared-slot collision rules. README descriptions contain discrepancies (for
  example slide target numbering); source and measured traces decide behavior.
- A host envelope/preset feature must show its generated event density and asset
  cost. It cannot introduce new device-side instrument state implicitly.
- SFX authoring needs a separate mono profile and explicit target channel,
  independent tempo and restoration behavior. Do not advertise FX SFX based on
  the music-only spike.
- The actual game resource reserve, save behavior and audio/graphics SPI budget
  remain FX integration requirements; this authoring plan does not establish them.

## Delivery evidence

Implementation task status and dependencies live in Beads under
`ATMlib2FX-3ii`:

| Bead | Owned result | Prerequisites |
|---|---|---|
| `ATMlib2FX-3ii.1` | Schema, validator, canonical host events and original PROGMEM export | Ready independently of FX design |
| `ATMlib2FX-3ii.2` | Faithful bounded WAV preview and playback evidence | `.1` |
| `ATMlib2FX-3ii.3` | Selected FX backend and resource admission checks | `.1`, `.2`, and `ATMlib2FX-hlh.2` with a selected runtime |
| `ATMlib2FX-3ii.6` | Offline HTML/JS track review and synchronized matching-WAV audition | `.1`, `.2`; visual review has no FX backend dependency |
| `ATMlib2FX-3ii.4` | Model authoring guide and demonstrated compose/review/revise workflow | `.1`, `.2`, `.6` |

Delivery requires a valid example and structured failures, stable
canonical lowering/artifact hashes, original-engine evidence for gate/rest/end
behavior, a local HTML/JS track review with matching audible preview and pinned
provenance, and an export through each advertised backend. Authoring must not add device runtime bytes. FX export stays
dependent on the architecture decision; the frontend and original preview can
proceed independently.

## Measured audio-preview findings (ATMlib2FX-3ii.2)

`tools/atm-music render` establishes the facts this plan left open:

- The local absim emulator does expose a real audio API:
  `core_state.cpu.sound_buffer` (`ardens/src/absim_sound.hpp`), int16 PCM mono,
  at `F_CPU / SOUND_CYCLES = 16'000'000 / 320 = 50'000 Hz`, neutral DC 0, gain
  2000. Sound is only produced when the Arduboy speaker pins (DDRC6/DDRC7) are
  outputs and Timer4 PWM is running; a fixture that omits the enable captures
  all-zero samples (proven with the 3ii.1 `avr.ino`, `sound_enabled=0`).
- The first music callback is measurable, not inferred: an absim non-step PC
  breakpoint on the engine's `osc_tick_handler` (located with `avr-nm`) yields a
  fixed startup offset (measured 1045 samples = 20.9 ms from reset).
- Real captured audio satisfies the gate/silence/timing checks: neutral-level
  silence (steady zero-AC ≈ 2 counts) in gaps, pulse/noise activity, one-tick
  gates, end-muting, and deterministic repeatability (identical WAV hashes; two
  identical noise hits are sample-identical). The reproduced engine tick trace
  hash matches the committed golden.
- Two caveats are recorded: the capture is the mono speaker mix (no per-channel
  isolation from one WAV), and after the score ends the stopped PWM leaves a
  constant DC rail (~−2000, zero AC) rather than neutral 0.

See `tests/music_authoring/fixtures/basic/README.md` (WAV preview section) for the
exact commands, versions and hashes.

## Measured viewer findings (ATMlib2FX-3ii.6)

`tools/atm-music inspect song.json --out review.html [--audio-preview preview/] --json`
implements the local HTML/JavaScript track review this plan proposed:

- The viewer draws the canonical `atmlib-review` payload and embeds it, the
  viewer CSS/JS and (optionally) the matching WAV as base64 in one standalone
  file. It loads from `file://` with an embedded `default-src 'none'`
  Content-Security-Policy; a real Chrome 155 run recorded only `file:`/`blob:`
  resource requests (zero external). The adjacent JSON is exactly the canonical
  payload — byte-identical to `build --backend progmem`'s `review.json`.
- Authored strings are escaped for the inert data block (`<`, `>`, `&`,
  U+2028/2029) and rendered with `textContent`, so a `</script>` or comment in a
  path/string stays inert.
- With `--audio-preview` the report's source **and** canonical event digests must
  match the current score, and the WAV metadata/identity must validate; a stale
  preview is rejected and only a warning is emitted. Playhead sync uses the
  measured startup offset and the exact effective tick rate (the integer timer
  divider, `2000 / floor(2000 / tick_rate)`); the
  finite capture (and truncation) bounds audition, and the post-end DC rail
  (≈ −2000, zero AC) is described as acoustically silent rather than neutral.
- Lane checkboxes are visibility only and never mute/solo; the WAV is a mono
  speaker mix.
- **Capability report mismatch, deliberately not changed.** `capabilities --json`
  still reports `inspect`/`render` unavailable because the 3ii.1
  `expected/review.json` golden embeds that capabilities block and
  `test_progmem.CapabilityTests` pins it. Regenerating that frozen golden is out
  of scope, so `inspect` and `render` instead report their own truthful
  availability in their payloads, and the viewer shows the same. The divergence
  is pinned by `test_inspect.CapabilityDivergenceTests`.

See `tools/music_authoring/viewer/README.md` for the embedded document shape and
the offline walkthrough driver.
