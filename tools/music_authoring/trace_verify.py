"""Effect-aware prediction and verification of the ATMlib tick trace.

``verify_suite.py`` (research/music-authoring) checks an *effect-free* score by
building a flat expected-notes grid from the canonical ``review.json`` payload
and comparing the ``cvol``/``note``/``cmod``/``tempo`` columns of the absim
``tick_trace.csv``.  This module generalizes that to scores that use pattern
effects and live commands: it re-implements the deterministic parts of the
unmodified engine scheduler (``src/atm_synth.c`` ``process_fx``/``process_cmd``,
``src/cmd_parse.c``) over the *lowered* device ops and predicts the per-tick
observable channel state (``inc``/``vol``/``note``/``cvol``/``cmod``/``tempo``)
for every music callback.  The prediction is then compared, field by field,
against a real ``tick_trace.csv`` and every mismatch is reported with its
expectation.

Trace layout (``tools/music_authoring/preview/trace_main.c``):
    tick,channel,tempo,inc,vol,note,delay,cvol,cmod,active
one row per channel per completed music callback; song tick 0 == trace tick 1.
Columns map to engine state as:
  * ``inc``   == ``osc_params_array[c].phase_increment``
  * ``vol``   == ``osc_params_array[c].vol``
  * ``note``  == ``channels[c].note``
  * ``cvol``  == ``channels[c].vol``
  * ``cmod``  == ``channels[c].mod``
  * ``tempo`` == ``atmlib_state.tick_rate``
  * ``delay`` == ``channels[c].delay`` (scheduler bookkeeping)
  * ``active``== ``atmlib_state.channel_active_mute`` (global stop bitmask)

Modeled observables and documented exclusions
---------------------------------------------
Modeled (an effect that changes a trace column):
  * note attack / explicit gate mute (``inc``/``vol``/``note``/``cvol``/``cmod``)
  * arpeggio and note_cut retriggers (``inc``/``vol``; note_cut's silence is the
    ``trigger_note(0)`` path, which zeroes the oscillator volume but not
    ``ch->vol``, so ``cvol`` is unchanged)
  * glissando (``note`` + ``inc``)
  * LFO tremolo (``vol``) and vibrato (``inc``)
  * slide ``volume`` (``vol``) and ``frequency`` (``inc``)
  * noise_retrig (``inc`` reseed on the noise channel)
  * live commands ``set_tempo``/``add_tempo`` (``tempo``),
    ``set_volume`` (``cvol``+``vol``), ``set_mod`` (``cmod``),
    ``set_transposition``/``add_transposition`` (affects later triggers' ``inc``)

Excluded, with reasons:
  * ``delay``  -- engine command-scheduling bookkeeping, not musical state.
  * ``active`` -- the shared stop bitmask; it is a global, not per-channel
    value, and the loop/linear schedule is already implied by the row count.
  * LFO ``modulation`` and slide ``modulation`` -- they write
    ``osc_params.mod``, which the trace does not expose (``cmod`` is
    ``ch->mod``, only written by ``SET_MOD``); not observable.
  * ``cue`` -- latched into ``atmlib_state.cue``; no trace column.

The note->phase-increment table is copied verbatim from ``src/atm_synth.c``
(``noteTable[64]``).  Keeping the engine constant here lets the predictor be
used without compiling the engine.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass

from .score import CHANNEL_NAMES, Diagnostic, Score, ScoreError

# --------------------------------------------------------------------------- #
# Engine constants (src/osc.h, src/atm_synth.c).
# --------------------------------------------------------------------------- #
OSC_PHASE_INC_MAX = 0x3FFF
OSC_MOD_MAX = 255
MAX_VOLUME = 127
LAST_NOTE = 63

# Verbatim copy of `const uint16_t noteTable[64] PROGMEM` (src/atm_synth.c).
# `note_index_2_phase_inc(idx)` reads `noteTable[idx & 0x3F]`.
ENGINE_NOTE_TABLE = (
    0,
    268, 284, 301, 319, 338, 358, 379, 401, 425, 451, 477, 506,
    536, 568, 601, 637, 675, 715, 758, 803, 851, 901, 955, 1011,
    1072, 1135, 1203, 1274, 1350, 1430, 1515, 1606, 1701, 1802, 1909, 2023,
    2143, 2271, 2406, 2549, 2700, 2861, 3031, 3211, 3402, 3604, 3819, 4046,
    4286, 4541, 4811, 5098, 5401, 5722, 6062, 6422, 6804, 7209, 7638, 8092,
    8573, 9083, 9623,
)
assert len(ENGINE_NOTE_TABLE) == 64

# Host effect-window kind -> encoded effect selector byte.
LFO_SELECTORS = {"tremolo": 0, "vibrato": 1, "modulation": 2}
SLIDE_SELECTORS = {"volume": 0, "frequency": 1, "modulation": 2}

# Trace columns the predictor compares by default.
DEFAULT_FIELDS = ("inc", "vol", "note", "cvol", "cmod", "tempo")
# Trace columns deliberately ignored (documented above).
EXCLUDED_FIELDS = ("delay", "active")


def note_index_to_phase_inc(note_index: int) -> int:
    """``note_index_2_phase_inc`` with the engine's 6-bit index mask."""
    return ENGINE_NOTE_TABLE[(note_index) & 0x3F]


def _engine_int8(value: int) -> int:
    """Interpret the low byte of ``value`` as a signed 8-bit integer."""
    value &= 0xFF
    return value - 0x100 if value >= 0x80 else value


def _clamp(value: int, bottom: int, top: int) -> int:
    if value < bottom:
        return bottom
    if value > top:
        return top
    return value


def _slide_quantity(amount: int, value: int, bottom: int, top: int, clamp: bool) -> int:
    result = value + amount
    if clamp:
        if result < bottom:
            return bottom
        if result > top:
            return top
    return result


def _param(op, name: str):
    """Fetch one typed operand from an op's ordered ``params`` payload."""
    for key, value in op.params:
        if key == name:
            return value
    raise ScoreError(f"device op {op.op!r} is missing operand {name!r}")


# --------------------------------------------------------------------------- #
# Per-channel engine state (a faithful subset of `struct atm_channel_state`
# plus the `struct osc_params` its effects write through).
# --------------------------------------------------------------------------- #
@dataclass
class _Channel:
    index: int
    note: int = 0
    vol: int = 0          # ch->vol   (trace cvol)
    mod: int = 0x7F       # ch->mod   (trace cmod; init sets 0x7F)
    trans: int = 0        # trans_config (int8)
    stopped: bool = False
    # note retrigger (arpeggio / note_cut)
    arpNotes: int = 0xFF
    arpTiming: int = 0
    arpCount: int = 0x80
    # noise retrigger
    reConfig: int = 0
    reCount: int = 0
    # LFO
    treviDepth: int = 0
    treviConfig: int = 0
    treviCount: int = 0
    # glissando
    glisConfig: int = 0
    glisCount: int = 0
    # volume/frequency slide
    slide_amount: int = 0
    slide_config: int = 0
    slide_count: int = 0
    # oscillator params (the observable trace state)
    osc_inc: int = 0
    osc_vol: int = 0
    osc_mod: int = 0x7F


def _new_channel(index: int) -> _Channel:
    # osc_setup(): all osc params zeroed except mod=0x7F; ch3 phase_increment
    # seeded to 0x0001 (LFSR); atm_synth_init_channel(): arpCount=0x80, mod=0x7F.
    return _Channel(index=index, osc_inc=0x0001 if index == 3 else 0x0000)


def _trigger_note(ch: _Channel, note: int) -> None:
    """Port of ``trigger_note()`` (src/cmd_parse.c)."""
    ch.osc_inc = note_index_to_phase_inc(note + ch.trans)
    if note == 0:
        # Note-off / note-cut: silence the oscillator only. Keep cvol and the
        # current mod so an in-flight mod slide is preserved.
        ch.osc_vol = 0
        return
    trigger_both = True
    if ch.slide_amount:
        if ch.slide_config & 0x40:
            ch.slide_count &= 0x3F
        else:
            q = ch.slide_count & 0xC0
            if q == 0:
                # Volume slide: do not re-trigger volume.
                ch.osc_mod = ch.mod
                trigger_both = False
            elif q == 0x80:
                # Modulaton slide: do not re-trigger mod.
                ch.osc_vol = ch.vol
                trigger_both = False
    if trigger_both:
        ch.osc_vol = ch.vol
        ch.osc_mod = ch.mod


def _addto_osc_param(ch: _Channel, amount: int, param: int, flags: int) -> None:
    """Port of ``addto_osc_param()`` (src/atm_synth.c)."""
    selector = param & 0xC0
    clamp = not (flags & 0x80)
    if selector == 0x00:
        result = _slide_quantity(amount, ch.osc_vol, 0, MAX_VOLUME, clamp)
        ch.osc_vol = result & 0xFF
    elif selector == 0x40:
        result = _slide_quantity(amount, ch.osc_inc, 0, OSC_PHASE_INC_MAX, clamp)
        ch.osc_inc = result & 0xFFFF
    elif selector == 0x80:
        result = _slide_quantity(amount, ch.osc_mod, 0, OSC_MOD_MAX, clamp)
        ch.osc_mod = result & 0xFF


def _process_fx(ch: _Channel) -> None:
    """Port of ``process_fx()`` (src/atm_synth.c), same FX ordering."""
    # Noise retriggering (noise channel only).
    if ch.index == 3 and ch.reConfig:
        if ch.reCount >= (ch.reConfig & 0x03):
            ch.osc_inc = note_index_to_phase_inc((ch.reConfig >> 2) & 0x3F)
            ch.reCount = 0
        else:
            ch.reCount += 1

    # Glissando.
    if ch.glisConfig:
        if ch.glisCount >= (ch.glisConfig & 0x7F):
            amount = -1 if (ch.glisConfig & 0x80) else 1
            ch.note = _clamp(ch.note + amount, 1, LAST_NOTE)
            ch.osc_inc = note_index_to_phase_inc(ch.note)
            ch.glisCount = 0
        else:
            ch.glisCount += 1

    # Volume / frequency / modulation slides.
    if ch.slide_amount:
        if (ch.slide_count & 0x3F) >= (ch.slide_config & 0x3F):
            _addto_osc_param(ch, ch.slide_amount, ch.slide_count & 0xC0, ch.slide_config & 0x80)
            ch.slide_count &= 0xC0
        else:
            ch.slide_count += 1

    # Arpeggio / note cut.
    arp_flags = ch.arpCount & 0xE0
    if arp_flags != 0x80 and ch.note:
        if (ch.arpCount & 0x1F) < (ch.arpTiming & 0x1F):
            ch.arpCount += 1
        else:
            num_notes = 0x20 if (ch.arpTiming & 0x40) else 0x40
            if arp_flags == num_notes:
                # Re-trigger disabled? (bit 5 set means no automatic base note)
                disable_auto_trigger = ch.arpTiming & 0x20
                arp_flags = 0x80 if disable_auto_trigger else 0
                arp_note = 0 if disable_auto_trigger else ch.note
            else:
                note_inc = (ch.arpNotes & 0x0F) if arp_flags else (ch.arpNotes >> 4)
                arp_note = 0 if note_inc == 0x0F else ch.note + note_inc
                arp_flags += 0x20
            _trigger_note(ch, arp_note)
            ch.arpCount = arp_flags

    # Tremolo (vol) / vibrato (inc) / modulation LFO.
    if ch.treviDepth:
        amount = ch.treviDepth if (ch.treviCount & 0x80) else -ch.treviDepth
        _addto_osc_param(ch, amount, ch.treviConfig & 0xC0, 0)
        if (ch.treviCount & 0x1F) < (ch.treviConfig & 0x1F):
            ch.treviCount += 1
        else:
            ch.treviCount = 0 if (ch.treviCount & 0x80) else 0x80


# --------------------------------------------------------------------------- #
# Device-op application (the engine's `process_cmd` successors).
# --------------------------------------------------------------------------- #
def _apply_arpeggio_on(ch: _Channel, op) -> None:
    offsets = tuple(int(item) for item in _param(op, "offsets"))
    period = int(_param(op, "period"))
    repeat = bool(_param(op, "repeat"))
    two_step = len(offsets) == 1
    notes = (offsets[0] << 4) | (offsets[1] if not two_step else 0)
    timing = (period - 1) & 0x1F
    if two_step:
        timing |= 0x40
    if not repeat:
        timing |= 0x20
    ch.arpTiming = timing
    ch.arpNotes = notes & 0xFF
    ch.arpCount = 0x00


def _apply_note_cut_on(ch: _Channel, op) -> None:
    period = int(_param(op, "period"))
    repeat = bool(_param(op, "repeat"))
    timing = ((period - 1) & 0x1F) | 0x40
    if not repeat:
        timing |= 0x20
    ch.arpTiming = timing
    ch.arpNotes = 0xFF
    ch.arpCount = 0x00


def _apply_lfo_on(ch: _Channel, op) -> None:
    mode = _param(op, "mode")
    depth = int(_param(op, "depth"))
    period = int(_param(op, "period"))
    selector = LFO_SELECTORS[mode]
    half = period // 2 - 1
    ch.treviDepth = depth & 0xFF
    ch.treviConfig = ((half & 0x1F) | ((selector & 0x03) << 6)) & 0xFF
    ch.treviCount = ((half & 0x1F) >> 1) & 0xFF


def _apply_slide_on(ch: _Channel, op) -> None:
    param = _param(op, "param")
    amount = int(_param(op, "amount"))
    every = int(_param(op, "every"))
    selector = SLIDE_SELECTORS[param]
    ch.slide_count = (selector & 0x03) << 6
    ch.slide_amount = _engine_int8(amount)
    ch.slide_config = (every - 1) & 0xFF


def _apply_glissando_on(ch: _Channel, op) -> None:
    period = int(_param(op, "period"))
    direction = _param(op, "direction")
    byte = (period - 1) & 0x7F
    if direction == "down":
        byte |= 0x80
    ch.glisConfig = byte & 0xFF
    ch.glisCount = 0


def _apply_noise_retrig_on(ch: _Channel, op) -> None:
    period = int(_param(op, "period"))
    note_index = int(_param(op, "note_index"))
    ch.reConfig = ((note_index << 2) | period) & 0xFF
    ch.reCount = 0


def _apply_op(ch: _Channel, op, tempo: int) -> int:
    """Apply one lowered device op; return the updated global tempo."""
    name = op.op
    if name == "set_tempo":
        return int(op.tick_rate) & 0xFF
    if name == "set_volume":
        value = op.volume if op.volume is not None else _param(op, "value")
        value &= 0xFF
        ch.vol = value
        ch.osc_vol = value
    elif name == "set_mod":
        value = op.duty if op.duty is not None else _param(op, "value")
        value &= 0xFF
        ch.mod = value
        ch.osc_mod = value
    elif name == "note":
        ch.note = op.note_index & 0xFF
        _trigger_note(ch, ch.note)
        if ch.arpTiming & 0x20:
            ch.arpCount = 0
    elif name == "mute":
        # Encoded as SET_VOLUME 0x00: both the channel and oscillator volume.
        ch.vol = 0
        ch.osc_vol = 0
    elif name == "arpeggio_on":
        _apply_arpeggio_on(ch, op)
    elif name == "arpeggio_off":
        # Shared by arpeggio and note_cut.
        ch.arpCount = 0x80
    elif name == "note_cut_on":
        _apply_note_cut_on(ch, op)
    elif name == "lfo_on":
        _apply_lfo_on(ch, op)
    elif name == "lfo_off":
        ch.treviDepth = 0
    elif name == "slide_on":
        _apply_slide_on(ch, op)
    elif name == "slide_off":
        ch.slide_amount = 0
    elif name == "glissando_on":
        _apply_glissando_on(ch, op)
    elif name == "glissando_off":
        ch.glisConfig = 0
    elif name == "noise_retrig_on":
        _apply_noise_retrig_on(ch, op)
    elif name == "noise_retrig_off":
        ch.reConfig = 0
    # --- live commands --- #
    elif name == "add_tempo":
        return (tempo + _engine_int8(_param(op, "value"))) & 0xFF
    elif name == "set_transposition":
        ch.trans = _engine_int8(_param(op, "value"))
    elif name == "add_transposition":
        ch.trans = _engine_int8(ch.trans + _engine_int8(_param(op, "value")))
    elif name == "cue":
        pass  # latched into atmlib_state.cue; not observable in the trace.
    else:
        raise ScoreError(f"trace_verify cannot predict device op {name!r}")
    return tempo


# --------------------------------------------------------------------------- #
# Schedule extraction and simulation.
# --------------------------------------------------------------------------- #
def _ops_by_channel_tick(lowered) -> dict[int, dict[int, list]]:
    table: dict[int, dict[int, list]] = {index: {} for index in range(4)}
    for channel in CHANNEL_NAMES:
        index = CHANNEL_NAMES.index(channel)
        for op in lowered.ops.get(channel, ()):
            table[index].setdefault(op.tick, []).append(op)
    return table


def _stop_ticks(score: Score, lowered) -> dict[int, int]:
    """Per-channel STOP tick for linear playback (unused channels stop at 0)."""
    stops: dict[int, int] = {}
    for index, channel in enumerate(CHANNEL_NAMES):
        stops[index] = int(lowered.track_ticks.get(channel, 0)) if channel in score.tracks else 0
    return stops


def _snapshot(channels, tempo) -> tuple:
    return tuple(
        {
            "inc": ch.osc_inc,
            "vol": ch.osc_vol,
            "note": ch.note,
            "cvol": ch.vol,
            "cmod": ch.mod,
            "tempo": tempo,
        }
        for ch in channels
    )


def _simulate_linear(score: Score, lowered, ticks: int, stop_ticks) -> list:
    """Predict a non-looping trace; channels freeze at their STOP tick."""
    channels = [_new_channel(index) for index in range(4)]
    ops_table = _ops_by_channel_tick(lowered)
    stops = dict(stop_ticks or {})
    tempo = int(score.clock.tick_rate)
    snapshots = []
    for tick in range(ticks):
        for ch in channels:
            if ch.stopped:
                continue
            _process_fx(ch)
            for op in ops_table[ch.index].get(tick, ()):
                tempo = _apply_op(ch, op, tempo)
            if stops.get(ch.index) == tick:
                # encode_program appends PATTERN_END after the padded track.
                ch.stopped = True
                ch.osc_vol = 0
        snapshots.append(_snapshot(channels, tempo))
    return snapshots


def _simulate_loop(score: Score, lowered, cycles: int) -> list:
    """Predict a looping trace for ``cycles`` cycles plus the opening tick.

    The engine keeps channel state across the loop boundary (it is not
    re-initialised), so state left by the previous cycle persists for any
    channel that does not re-attack on its tick-0 phase.  At each boundary the
    engine: applies FX for the just-finished tick, runs the cycle-end ops
    (effect off / gate mute), executes ``PATTERN_END`` (which zeroes the
    oscillator volume), then re-runs FX and processes the tick-0 ops again in
    the same callback.  The boundary callback is the one that prints the next
    cycle's tick 0, so no "stopped" row ever appears in a looping trace.
    """
    total = int(lowered.total_ticks)
    channels = [_new_channel(index) for index in range(4)]
    ops_table = _ops_by_channel_tick(lowered)
    tempo = int(score.clock.tick_rate)
    if total <= 0:
        return [_snapshot(channels, tempo)]
    snapshots = []
    for position in range(cycles * total + 1):
        phase = position % total
        boundary = position != 0 and phase == 0
        for ch in channels:
            if boundary:
                _process_fx(ch)
                for op in ops_table[ch.index].get(total, ()):
                    tempo = _apply_op(ch, op, tempo)
                ch.osc_vol = 0  # PATTERN_END / stop_channel
            _process_fx(ch)
            for op in ops_table[ch.index].get(phase, ()):
                tempo = _apply_op(ch, op, tempo)
        snapshots.append(_snapshot(channels, tempo))
    return snapshots


def build_expected(score: Score, lowered, *, mode: str | None = None, cycles: int = 2) -> dict:
    """Predict the full expected timeline for a lowered score.

    Returns ``{"mode", "total_ticks", "rows", "wrap"}`` where
    ``rows[t][channel]`` is a field dict.

    * ``"loop"``: ``rows`` are the continuous simulation of ``cycles`` cycles
      plus the next opening tick (``cycles*total_ticks+1`` rows) with state
      carried across the loop boundary; compare trace ticks directly
      (``wrap`` is ``False``).
    * ``"linear"``: ``rows`` cover song ticks 0..last STOP inclusive; compare
      trace ticks directly.
    """
    if mode is None:
        mode = "loop" if score.loop else "linear"
    if mode == "loop":
        total = int(lowered.total_ticks)
        rows = _simulate_loop(score, lowered, cycles)
        return {"mode": "loop", "total_ticks": total, "rows": rows, "wrap": False}
    if mode == "linear":
        stops = _stop_ticks(score, lowered)
        ticks = (max(stops.values()) if stops else 0) + 1
        rows = _simulate_linear(score, lowered, ticks, stops)
        return {"mode": "linear", "total_ticks": int(lowered.total_ticks), "rows": rows, "wrap": False}
    raise ScoreError(f"unknown trace mode {mode!r}")


def expected_from_notes(notes, total_ticks: int, tempo: int) -> dict:
    """Effect-free expectation grid built from review-payload note spans.

    This is the shared comparator input for ``verify_suite.py``.  ``cvol`` is 0
    for every tick; inside each note gate it is the instrument volume and
    ``note``/``cmod`` carry the attack values (``cmod`` only for pulse
    channels).  ``tempo`` is constant.  The comparator skips any field absent
    from a cell, which reproduces the effect-free check exactly.
    """
    rows = [
        [{"cvol": 0, "tempo": int(tempo)} for _ in range(4)]
        for _ in range(int(total_ticks))
    ]
    for note in notes:
        channel = int(note["channel"])
        volume = int(note["volume"])
        note_index = int(note["note_index"])
        duty = note.get("duty")
        start = int(note["start_tick"])
        end = int(note["gate_end_tick"])
        for tick in range(start, end):
            cell = rows[tick % int(total_ticks)][channel]
            cell["cvol"] = volume
            cell["note"] = note_index
            if channel < 3 and duty is not None:
                cell["cmod"] = int(duty)
    return {"mode": "loop", "total_ticks": int(total_ticks), "rows": rows, "wrap": True}


def _parse_int(text) -> int:
    text = str(text).strip()
    lowered = text.lower()
    if lowered.startswith("0x") or lowered.startswith("-0x"):
        return int(text, 16)
    return int(text, 10)


def compare_rows(rows, expected: dict, *, fields=DEFAULT_FIELDS, wrap: int | None = None):
    """Compare trace rows against an expected grid; return per-tick mismatches.

    ``expected`` is as returned by :func:`build_expected` (or
    :func:`expected_from_notes`).  ``wrap`` defaults to ``total_ticks`` when the
    expectation is a single wrapped cycle (``expected["wrap"]`` true), else
    trace ticks index the expected rows directly.  Each mismatch is a dict with
    ``tick``, ``song_tick``, ``channel``, ``field``, ``expected`` and
    ``actual``.
    """
    grid = expected["rows"]
    total = int(expected["total_ticks"])
    if wrap is None:
        wrap = total if expected.get("wrap") else None
    if wrap is not None:
        wrap = int(wrap) or None
    mismatches = []
    for row in rows:
        try:
            tick = int(str(row["tick"]))
            channel = int(str(row["channel"]))
        except (KeyError, TypeError, ValueError):
            mismatches.append(
                {
                    "tick": row.get("tick"),
                    "channel": row.get("channel"),
                    "field": "row",
                    "expected": "integer tick/channel",
                    "actual": dict(row),
                }
            )
            continue
        song_tick = tick - 1
        if wrap:
            song_tick %= wrap
        if not (0 <= song_tick < len(grid)) or not (0 <= channel < 4):
            mismatches.append(
                {
                    "tick": tick,
                    "song_tick": song_tick,
                    "channel": channel,
                    "field": "schedule",
                    "expected": f"0 <= song_tick < {len(grid)}",
                    "actual": song_tick,
                }
            )
            continue
        cell = grid[song_tick][channel]
        for field_name in fields:
            if field_name not in cell:
                continue
            expected_value = cell[field_name]
            try:
                actual_value = _parse_int(row.get(field_name))
            except (TypeError, ValueError):
                mismatches.append(
                    {
                        "tick": tick,
                        "song_tick": song_tick,
                        "channel": channel,
                        "field": field_name,
                        "expected": expected_value,
                        "actual": row.get(field_name),
                    }
                )
                continue
            if actual_value != expected_value:
                mismatches.append(
                    {
                        "tick": tick,
                        "song_tick": song_tick,
                        "channel": channel,
                        "field": field_name,
                        "expected": expected_value,
                        "actual": actual_value,
                    }
                )
    return mismatches


def expected_row_count(expected: dict) -> int:
    """Total CSV rows the trace must contain for this expectation."""
    if expected.get("wrap"):
        return (2 * int(expected["total_ticks"]) + 1) * 4
    return len(expected["rows"]) * 4


def verify_trace(score: Score, lowered, trace_path, *, fields=DEFAULT_FIELDS) -> dict:
    """Compare a score's prediction against ``trace_path``; return a summary."""
    expected = build_expected(score, lowered)
    with open(trace_path, newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    wants = expected_row_count(expected)
    mismatches = compare_rows(rows, expected, fields=fields)
    if len(rows) != wants:
        mismatches.insert(
            0,
            {
                "tick": None,
                "channel": None,
                "field": "row_count",
                "expected": wants,
                "actual": len(rows),
            },
        )
    return {
        "ok": not mismatches,
        "song": score.id,
        "trace": str(trace_path),
        "mode": expected["mode"],
        "total_ticks": int(expected["total_ticks"]),
        "expected_rows": wants,
        "actual_rows": len(rows),
        "checked_fields": list(fields),
        "excluded_fields": list(EXCLUDED_FIELDS),
        "effect_families": sorted({span.kind for span in lowered.effect_spans}),
        "command_kinds": sorted({event.kind for event in lowered.command_events}),
        "mismatch_count": len(mismatches),
        "mismatches": mismatches[:50],
        "mismatches_truncated": len(mismatches) > 50,
    }


# --------------------------------------------------------------------------- #
# CLI.
# --------------------------------------------------------------------------- #
def main(argv=None) -> int:
    import argparse
    import json

    from .lower import lower
    from .validate import load_and_validate

    parser = argparse.ArgumentParser(
        prog="atm-trace-verify",
        description=(
            "Predict the effect-aware ATMlib tick trace for a score and compare "
            "it against an absim tick_trace.csv."
        ),
    )
    parser.add_argument("song", help="path to the score JSON")
    parser.add_argument("trace", help="path to the absim tick_trace.csv")
    parser.add_argument("--json", action="store_true", help="emit JSON (always on)")
    args = parser.parse_args(argv)

    score, diagnostics = load_and_validate(args.song)
    if score is None:
        print(
            json.dumps(
                {
                    "ok": False,
                    "song": args.song,
                    "trace": args.trace,
                    "diagnostics": [item.as_dict() for item in diagnostics],
                },
                indent=2,
            )
        )
        return 3 if any(item.code == "IO_ERROR" for item in diagnostics) else 2
    try:
        lowered = lower(score)
        summary = verify_trace(score, lowered, args.trace)
    except (ScoreError, OSError) as exc:
        diagnostics = diagnostics + [
            Diagnostic("TRACE_VERIFY_ERROR", "", str(exc), "Check the score and trace inputs.")
        ]
        print(
            json.dumps(
                {
                    "ok": False,
                    "song": args.song,
                    "trace": args.trace,
                    "diagnostics": [item.as_dict() for item in diagnostics],
                },
                indent=2,
            )
        )
        return 3
    print(json.dumps(summary, indent=2, sort_keys=False))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
