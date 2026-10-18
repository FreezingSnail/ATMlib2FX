# Local port and preview workflow

Run from the ATMlib2FX repository root. Use existing tools rather than inventing
another score interpreter. Check only the code and documents relevant to the
requested change.

## Source and capability facts

- `tools/music_authoring/validate.py`: authoritative accepted source shape and
  semantic checks. Ordered, non-overlapping events must fit their pattern.
- `tools/music_authoring/lower.py`: canonical timeline, source pointers, gates
  and event digest; reviews describe one cycle even for a looping score.
- `tools/music_authoring/progmem_backend.py`: original-format score encoding.
- `src/atm_cmd_constants.h`, `src/cmd_parse.c`, `src/atm_synth.c`, `src/osc.c`:
  local command meanings, effects, playback and timer behavior.

`tools/atm-music capabilities --json` reports the available backend and limits.
Its pinned static report misleadingly lists render/inspect as unavailable;
those commands work and report their own capabilities. FX export remains
unavailable. Check actual command diagnostics before concluding a tool is absent.

One known discrepancy needs care until its fix lands:

- The public JSON schema currently omits the optional root `loop` boolean that
  the CLI validator supports. Use CLI validation and inspect the actual code;
  do not remove requested looping just to satisfy the stale schema. Tracked in
  Bead ATMlib2FX-9jo.

`score.py:effective_tick_rate` now reports the timer's true rate
`2000 / floor(2000 / requested_tick_rate)` (an integer when the requested rate
is a divisor of 2000, e.g. 50 Hz; the real quotient otherwise). Host durations
derive from the integer divider `floor(2000 / tick_rate)`, not the rounded
quotient (Bead ATMlib2FX-3ii.8). The device timer divider is unchanged, so
prefer exact supported clocks such as 50 or 100 Hz for ordinary compositions;
other clocks now report accurately.

Recheck these discrepancies against current code when the skill is used.

## Real tempo changes

At an exact 50 Hz clock, 25 ticks/beat means 120 BPM; 30 means 100 BPM.
`seconds = total_ticks * floor(2000 / tick_rate) / 2000`. To preserve musical
shape while changing speed, scale pattern lengths, event onsets and **gate end
times** with the beat grid, then derive durations from the rounded ends.
Revalidate rounding for collisions, zero-length notes and pattern overflow.
Changing only `ticks_per_beat` relabels the grid without changing playback
timing.

## Render and review

Example shell variables below are illustrative; select the affected source and
an output lane under `build/`. The render bound must cover the cycle plus its
capture allowance. Default is 60 s, maximum 300 s; a bounded prefix cannot prove
or audition a complete loop. Report that limitation if the requested song is
longer than the renderer permits.

```sh
atm_song=examples/music_authoring/creature_gatherer/coast/song.json
atm_out=build/music-authoring/coast-revision
tools/atm-music validate "$atm_song" --backend progmem --json
tools/atm-music inspect "$atm_song" --out "$atm_out/visual/review.html" --json
tools/atm-music render "$atm_song" --backend progmem --seconds 60 --out "$atm_out/preview" --json
tools/atm-music inspect "$atm_song" --audio-preview "$atm_out/preview" --out "$atm_out/review.html" --json
```

Inspect diagnostics, source/event digests, `render.truncated`, WAV identity,
measured callback offset, musical activity and generated asset bytes. Never
retag stale media to make it appear current. Render uses the installed AVR tools
and local Ardens build; missing prerequisites are a tool limitation, not evidence
that the composition is silent or valid on device.

A successful real render also produces `tick_trace` and a `tick_trace` binary
under the chosen render directory. `tick_trace N` emits N callbacks, up to score
stop. For a loop, the renderer requests `2 * total_ticks + 1` callbacks. Compare
pitch, duty, gates, delays, tempo and active/mute state between cycles. Ignore
retained pitch/duty registers while muted. A gate/pattern-boundary change merits
checking the relevant callbacks; avoid rerunning unrelated firmware experiments.

## Loop semantics

Root `"loop": true` uses the existing per-channel `SET_LOOP_PATTERN` command.
The compiler pads participating channels to the longest track and the engine
restarts them together in the same callback. Missing channels stay silent.
Omission or false gives finite playback. No partial-song loop target is exposed
by JSON v1.

The capture retains startup and a tail; looping captures continue into the next
iteration. The browser prepares one complete PCM cycle using the measured first
callback, then uses native media looping. Loop defaults on for looping scores;
unmeasured or truncated previews cannot enable it. A cropped media clock must
still map correctly to source ticks for ruler/slider seek, restart and playhead.

## Promote only the affected artifacts

When updating a catalogued demo, retain its matching `preview.wav` and
`preview.json` in the score's `preview/` directory. Preserve the report's captured
paths and provenance; the loader supports the promoted pair. Use non-interactive
file operations, for example `cp -f`, or structured file-copy APIs.

Regenerate `review.html` and adjacent canonical `review.json` with the promoted
pair. Update the affected catalog context and current README measurements when
BPM, bars, duration or score bytes change; preserve historical evidence.

```sh
tools/atm-music inspect "$atm_song" --audio-preview examples/music_authoring/creature_gatherer/coast/preview --out examples/music_authoring/creature_gatherer/coast/review.html --json
python3 tools/music_authoring/library_player.py --catalog examples/music_authoring/catalog.json --out examples/music_authoring/player.html --json
```

The library embeds matching standalone documents, so it must be rebuilt after a
catalogued source, preview, or viewer change. Its shell does not provide separate
audio logic. Verify changed entries reference the new source/event/WAV identities.

Build a requested PROGMEM export with `tools/atm-music build "$atm_song"
--backend progmem --out "$atm_out/export" --json` (one shell command). Rendering
already compiles an instrumented image for capture; its total flash/SRAM figures
are not production engine or whole-game costs.

For authoring/transport code changes, choose relevant existing checks:

```sh
python3 -m unittest discover -s tests/music_authoring -p 'test_*.py'
node tests/music_authoring/viewer/test_loop.mjs
node tests/music_authoring/viewer/test_transport.mjs
node tests/music_authoring/viewer/test_piezo.mjs
```

Composition-only edits usually need source validation, matching renders and
relevant boundary evidence rather than new tests of taste. Keep the frozen finite
basic source/goldens under `tests/music_authoring/fixtures/basic/` unchanged when
editing the musical basic demo. Browser walkthroughs require a working installed
Chrome; report an unavailable browser separately from passing Node adapter checks.
