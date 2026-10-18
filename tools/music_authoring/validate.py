"""Strict v1 score validation with stable codes and JSON Pointer diagnostics."""

from __future__ import annotations

import hashlib
from typing import Any

from .score import (
    CHANNEL_NAMES,
    CHANNEL_VOICE,
    COMMAND_TYPES,
    EFFECT_SLOT,
    EFFECT_TYPES,
    HOST_LIMITS,
    IDENTIFIER_MAX_LENGTH,
    IDENTIFIER_RE,
    NOISE_EFFECT_TYPES,
    NOTE_MAX_INDEX,
    NOTE_MIN_INDEX,
    PITCH_MAX,
    PITCH_MIN,
    SOURCE_FORMAT,
    SCHEMA_VERSION,
    Clock,
    Diagnostic,
    EffectWindow,
    Instrument,
    InvalidJson,
    LiveCommand,
    NoteEvent,
    ParsedJson,
    Pattern,
    Score,
    TrackUse,
    duplicate_paths,
    identifier_problem,
    note_range_problem,
    parse_json_bytes,
    pointer,
    read_file,
)

TOP_LEVEL_FIELDS = ("format", "version", "id", "clock", "instruments", "patterns", "tracks")
CLOCK_FIELDS = ("tick_rate", "ticks_per_beat", "beats_per_bar")
INSTRUMENT_FIELDS = ("voice", "volume", "duty")
PATTERN_FIELDS = ("ticks", "events")
PATTERN_OPTIONAL_FIELDS = ("effects", "commands")
EVENT_FIELDS = ("at", "note", "duration", "instrument")
TRACK_USE_FIELDS = ("pattern", "repeat")

# Effect windows: common keys plus per-kind keys. `until` and `repeat` are
# optional everywhere; every other per-kind key is required.
EFFECT_COMMON_FIELDS = ("at", "type", "until")
EFFECT_KIND_FIELDS = {
    "arpeggio": ("offsets", "period", "repeat"),
    "note_cut": ("period", "repeat"),
    "lfo": ("mode", "depth", "period"),
    "slide": ("param", "amount", "every"),
    "glissando": ("period", "direction"),
    "noise_retrig": ("period", "note"),
}
EFFECT_KIND_REQUIRED = {
    "arpeggio": ("offsets", "period"),
    "note_cut": ("period",),
    "lfo": ("mode", "depth", "period"),
    "slide": ("param", "amount", "every"),
    "glissando": ("period", "direction"),
    "noise_retrig": ("period", "note"),
}
LFO_MODES = ("tremolo", "vibrato", "modulation")
SLIDE_PARAMS = ("volume", "frequency", "modulation")
GLISSANDO_DIRECTIONS = ("up", "down")

COMMAND_FIELDS = ("at", "type", "value")
# Accumulator ranges from src/cmd_parse.c / src/cmd_synth.h; see the interface
# doc for the engine operand widths behind each bound.
COMMAND_VALUE_RANGES = {
    "set_tempo": (8, 255),
    "add_tempo": (-128, 127),
    "set_transposition": (-128, 127),
    "add_transposition": (-128, 127),
    "set_volume": (0, 255),
    "set_mod": (0, 255),
    "cue": (0, 255),
}


class _Sink:
    def __init__(self) -> None:
        self.items: list[Diagnostic] = []

    def error(self, code: str, path: str, message: str, suggestion: str) -> None:
        self.items.append(Diagnostic(code, path, message, suggestion))

    @property
    def failed(self) -> bool:
        return bool(self.items)


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _check_keys(
    value: dict,
    *,
    path: str,
    allowed: tuple[str, ...],
    required: tuple[str, ...],
    sink: _Sink,
) -> None:
    for key in value:
        if key not in allowed:
            sink.error(
                "UNKNOWN_FIELD",
                pointer(*_segments(path), key),
                f"Unknown field {key!r}.",
                f"Remove {key!r}; the v1 {path or 'root'} object allows {', '.join(allowed)}.",
            )
    for key in required:
        if key not in value:
            sink.error(
                "MISSING_FIELD",
                pointer(*_segments(path), key),
                f"Required field {key!r} is missing.",
                f"Add {key!r}; v1 has no implicit defaults.",
            )


def _segments(path: str) -> tuple[str, ...]:
    if not path:
        return ()
    return tuple(part.replace("~1", "/").replace("~0", "~") for part in path.lstrip("/").split("/"))


def _check_identifier(value: Any, *, path: str, label: str, sink: _Sink) -> bool:
    problem = identifier_problem(value)
    if problem == "TYPE_MISMATCH":
        sink.error(
            "TYPE_MISMATCH",
            path,
            f"{label} must be a string.",
            "Use a JSON string.",
        )
        return False
    if problem == "INVALID_IDENTIFIER":
        sink.error(
            "INVALID_IDENTIFIER",
            path,
            f"{value!r} is not a valid {label}.",
            "Use [A-Za-z_][A-Za-z0-9_]* with at most 64 characters.",
        )
        return False
    return True


def _check_int_range(
    value: Any,
    *,
    path: str,
    minimum: int,
    maximum: int,
    label: str,
    sink: _Sink,
) -> bool:
    if not _is_int(value):
        sink.error(
            "TYPE_MISMATCH",
            path,
            f"{label} must be an integer (booleans and floats are not accepted).",
            "Use a JSON integer.",
        )
        return False
    if value < minimum or value > maximum:
        sink.error(
            "VALUE_RANGE",
            path,
            f"{label} is {value}, outside {minimum}..{maximum}.",
            f"Choose an integer in {minimum}..{maximum}.",
        )
        return False
    return True


def validate_document(
    document: Any,
    *,
    source_path: str,
    raw_bytes: bytes,
    parsed: ParsedJson | None = None,
) -> tuple[Score | None, list[Diagnostic]]:
    """Validate a parsed JSON document and return a Score when error-free."""
    sink = _Sink()
    source_sha256 = hashlib.sha256(raw_bytes).hexdigest()

    if parsed is not None:
        for path in duplicate_paths(parsed):
            sink.error(
                "DUPLICATE_KEY",
                path,
                "Duplicate JSON object key.",
                "Keep exactly one occurrence of this key.",
            )
        for path in parsed.nonfinite:
            sink.error(
                "TYPE_MISMATCH",
                path,
                "Non-finite numbers (NaN, Infinity) are not allowed.",
                "Use a finite JSON integer.",
            )

    if not isinstance(document, dict):
        sink.error(
            "TYPE_MISMATCH",
            "",
            "The score document must be a JSON object.",
            "Start the file with '{' and use the v1 object fields.",
        )
        return None, sink.items

    _check_keys(document, path="", allowed=TOP_LEVEL_FIELDS + ("loop",), required=TOP_LEVEL_FIELDS, sink=sink)
    if "loop" in document and not isinstance(document["loop"], bool):
        sink.error("TYPE_MISMATCH", "/loop", "loop must be a boolean.", "Use true or false; omit for a finite score.")

    if "format" in document:
        if not isinstance(document["format"], str):
            sink.error(
                "TYPE_MISMATCH",
                "/format",
                "format must be a string.",
                f'Use "{SOURCE_FORMAT}".',
            )
        elif document["format"] != SOURCE_FORMAT:
            sink.error(
                "INVALID_FORMAT",
                "/format",
                f"Unsupported document format {document['format']!r}.",
                f'Use "{SOURCE_FORMAT}".',
            )

    if "version" in document:
        version = document["version"]
        if not _is_int(version):
            sink.error(
                "TYPE_MISMATCH",
                "/version",
                "version must be an integer.",
                f"Use {SCHEMA_VERSION}.",
            )
        elif version != SCHEMA_VERSION:
            sink.error(
                "UNSUPPORTED_VERSION",
                "/version",
                f"Score version {version} is not supported.",
                f"Use version {SCHEMA_VERSION}; no other versions are implemented.",
            )

    score_id = document.get("id")
    if "id" in document:
        _check_identifier(score_id, path="/id", label="score id", sink=sink)

    clock = _validate_clock(document.get("clock"), sink)
    instruments = _validate_instruments(document.get("instruments"), sink)
    patterns, pattern_voices = _validate_patterns(document.get("patterns"), instruments, sink)
    tracks = _validate_tracks(document.get("tracks"), patterns, pattern_voices, sink)

    if sink.failed:
        return None, sink.items

    assert clock is not None
    assert score_id is not None
    return (
        Score(
            id=score_id,
            clock=clock,
            instruments=instruments,
            patterns=patterns,
            pattern_voices=pattern_voices,
            tracks=tracks,
            source_path=source_path,
            source_sha256=source_sha256,
            source_bytes=len(raw_bytes),
            raw_bytes=raw_bytes,
            loop=document.get("loop", False),
        ),
        [],
    )


def _validate_clock(value: Any, sink: _Sink) -> Clock | None:
    if not isinstance(value, dict):
        sink.error(
            "TYPE_MISMATCH",
            "/clock",
            "clock must be an object.",
            "Provide tick_rate, ticks_per_beat and beats_per_bar.",
        )
        return None

    _check_keys(
        value,
        path="/clock",
        allowed=CLOCK_FIELDS,
        required=CLOCK_FIELDS,
        sink=sink,
    )
    ok = True
    ok &= _check_int_range(
        value.get("tick_rate"),
        path="/clock/tick_rate",
        minimum=8,
        maximum=255,
        label="clock.tick_rate",
        sink=sink,
    )
    ok &= _check_int_range(
        value.get("ticks_per_beat"),
        path="/clock/ticks_per_beat",
        minimum=1,
        maximum=256,
        label="clock.ticks_per_beat",
        sink=sink,
    )
    ok &= _check_int_range(
        value.get("beats_per_bar"),
        path="/clock/beats_per_bar",
        minimum=1,
        maximum=16,
        label="clock.beats_per_bar",
        sink=sink,
    )
    if not ok or sink.failed:
        return None
    return Clock(
        tick_rate=value["tick_rate"],
        ticks_per_beat=value["ticks_per_beat"],
        beats_per_bar=value["beats_per_bar"],
    )


def _validate_instruments(value: Any, sink: _Sink) -> dict[str, Instrument]:
    instruments: dict[str, Instrument] = {}
    if not isinstance(value, dict):
        sink.error(
            "TYPE_MISMATCH",
            "/instruments",
            "instruments must be an object.",
            "Define at least one instrument preset.",
        )
        return instruments

    if len(value) > HOST_LIMITS["instruments"]:
        sink.error(
            "LIMIT_EXCEEDED",
            "/instruments",
            f"{len(value)} instruments exceed the host limit of {HOST_LIMITS['instruments']}.",
            "Remove instruments or split the score.",
        )
        return instruments

    for name, body in value.items():
        name_path = pointer("instruments", name)
        if not _check_identifier(name, path=name_path, label="instrument name", sink=sink):
            continue
        if not isinstance(body, dict):
            sink.error(
                "TYPE_MISMATCH",
                name_path,
                "Instrument must be an object.",
                "Provide voice and volume (and duty for pulse).",
            )
            continue

        voice = body.get("voice")
        if "voice" in body:
            if not isinstance(voice, str):
                sink.error(
                    "TYPE_MISMATCH",
                    pointer(name_path, "voice"),
                    "instrument voice must be a string.",
                    'Use "pulse" or "noise".',
                )
                voice = None
            elif voice not in ("pulse", "noise"):
                sink.error(
                    "VALUE_RANGE",
                    pointer(name_path, "voice"),
                    f"Unsupported instrument voice {voice!r}.",
                    'Use "pulse" or "noise"; the engine has no other oscillator types.',
                )
                voice = None

        required = ("voice", "volume", "duty") if voice == "pulse" else ("voice", "volume")
        allowed = required
        _check_keys(body, path=name_path, allowed=allowed, required=required, sink=sink)

        volume_ok = _check_int_range(
            body.get("volume"),
            path=pointer(name_path, "volume"),
            minimum=0,
            maximum=255,
            label="instrument volume",
            sink=sink,
        )
        duty = None
        duty_ok = True
        if voice == "pulse":
            duty_ok = _check_int_range(
                body.get("duty"),
                path=pointer(name_path, "duty"),
                minimum=0,
                maximum=255,
                label="instrument duty",
                sink=sink,
            )
            if duty_ok:
                duty = body["duty"]

        if voice is not None and volume_ok and duty_ok:
            instruments[name] = Instrument(name=name, voice=voice, volume=body["volume"], duty=duty)

    return instruments


def _validate_patterns(
    value: Any,
    instruments: dict[str, Instrument],
    sink: _Sink,
) -> tuple[dict[str, Pattern], dict[str, frozenset[str]]]:
    patterns: dict[str, Pattern] = {}
    pattern_voices: dict[str, frozenset[str]] = {}
    if not isinstance(value, dict):
        sink.error(
            "TYPE_MISMATCH",
            "/patterns",
            "patterns must be an object.",
            "Define at least one pattern.",
        )
        return patterns, pattern_voices

    if len(value) > HOST_LIMITS["patterns"]:
        sink.error(
            "LIMIT_EXCEEDED",
            "/patterns",
            f"{len(value)} patterns exceed the host limit of {HOST_LIMITS['patterns']}.",
            "Remove patterns or split the score.",
        )
        return patterns, pattern_voices

    source_events = 0
    source_effects = 0
    source_commands = 0
    for pattern_name, body in value.items():
        pattern_path = pointer("patterns", pattern_name)
        if not _check_identifier(pattern_name, path=pattern_path, label="pattern name", sink=sink):
            continue
        if not isinstance(body, dict):
            sink.error(
                "TYPE_MISMATCH",
                pattern_path,
                "Pattern must be an object.",
                "Provide ticks and events.",
            )
            continue

        _check_keys(
            body,
            path=pattern_path,
            allowed=PATTERN_FIELDS + PATTERN_OPTIONAL_FIELDS,
            required=PATTERN_FIELDS,
            sink=sink,
        )

        ticks_ok = _check_int_range(
            body.get("ticks"),
            path=pointer(pattern_path, "ticks"),
            minimum=1,
            maximum=HOST_LIMITS["total_ticks"],
            label="pattern ticks",
            sink=sink,
        )
        events_value = body.get("events")
        if not isinstance(events_value, list):
            sink.error(
                "TYPE_MISMATCH",
                pointer(pattern_path, "events"),
                "events must be an array.",
                "Use an array of note events (an empty array is a silent pattern).",
            )
            continue

        source_events += len(events_value)
        if source_events > HOST_LIMITS["source_events"]:
            sink.error(
                "LIMIT_EXCEEDED",
                pointer(pattern_path, "events"),
                f"More than {HOST_LIMITS['source_events']} source note events.",
                "Remove patterns or events; v1 expands nothing unboundedly.",
            )
            continue

        events: list[NoteEvent] = []
        voices: set[str] = set()
        previous_at: int | None = None
        previous_end: int | None = None
        valid_events = True

        for index, event in enumerate(events_value):
            event_path = pointer(pattern_path, "events", index)
            if not isinstance(event, dict):
                sink.error(
                    "TYPE_MISMATCH",
                    event_path,
                    "Note event must be an object.",
                    "Provide at, note, duration and instrument.",
                )
                valid_events = False
                continue

            _check_keys(
                event,
                path=event_path,
                allowed=EVENT_FIELDS,
                required=EVENT_FIELDS,
                sink=sink,
            )

            at_ok = _check_int_range(
                event.get("at"),
                path=pointer(event_path, "at"),
                minimum=0,
                maximum=HOST_LIMITS["total_ticks"],
                label="event at",
                sink=sink,
            )
            duration_ok = _check_int_range(
                event.get("duration"),
                path=pointer(event_path, "duration"),
                minimum=1,
                maximum=HOST_LIMITS["total_ticks"],
                label="event duration",
                sink=sink,
            )

            instrument_name = event.get("instrument")
            instrument_ok = True
            if "instrument" in event:
                if not isinstance(instrument_name, str):
                    sink.error(
                        "TYPE_MISMATCH",
                        pointer(event_path, "instrument"),
                        "instrument must be a string.",
                        "Reference an instrument name.",
                    )
                    instrument_ok = False
                elif instrument_name not in instruments:
                    sink.error(
                        "UNKNOWN_INSTRUMENT",
                        pointer(event_path, "instrument"),
                        f"Unknown instrument {instrument_name!r}.",
                        "Add the instrument to /instruments or fix the reference.",
                    )
                    instrument_ok = False

            note = event.get("note")
            note_ok = True
            note_value: int | None = None
            if "note" in event:
                if not isinstance(note, str):
                    sink.error(
                        "TYPE_MISMATCH",
                        pointer(event_path, "note"),
                        "note must be a string.",
                        f"Use a pitch token such as {PITCH_MIN}..{PITCH_MAX}.",
                    )
                    note_ok = False
                else:
                    problem, note_value = note_range_problem(note)
                    if problem == "INVALID_NOTE":
                        sink.error(
                            "INVALID_NOTE",
                            pointer(event_path, "note"),
                            f"{note!r} is not a v1 note token.",
                            f"Use a natural or sharp pitch from {PITCH_MIN} to {PITCH_MAX} "
                            "(flats, MIDI numbers and chords are not v1 syntax).",
                        )
                        note_ok = False
                    elif problem == "PITCH_RANGE":
                        sink.error(
                            "PITCH_RANGE",
                            pointer(event_path, "note"),
                            f"{note} is outside the engine pitch range {PITCH_MIN}..{PITCH_MAX}.",
                            f"Choose a pitch between {PITCH_MIN} and {PITCH_MAX}.",
                        )
                        note_ok = False

            if not (at_ok and duration_ok and instrument_ok and note_ok):
                valid_events = False
                if at_ok:
                    previous_at = event["at"]
                continue

            assert isinstance(note, str)
            assert isinstance(note_value, int)
            at = event["at"]
            duration = event["duration"]

            if ticks_ok and at + duration > body["ticks"]:
                sink.error(
                    "EVENT_OUTSIDE_PATTERN",
                    pointer(event_path, "duration"),
                    f"Event ends at {at + duration}, past pattern ticks={body['ticks']}.",
                    "Reduce at or duration, or increase pattern ticks.",
                )
                valid_events = False

            if previous_at is not None and at <= previous_at:
                sink.error(
                    "EVENT_ORDER",
                    pointer(event_path, "at"),
                    f"Event at {at} is not after the previous event at {previous_at}.",
                    "Sort events by ascending at; v1 allows only one event per timestamp.",
                )
                valid_events = False
            elif previous_end is not None and at < previous_end:
                sink.error(
                    "EVENT_OVERLAP",
                    event_path,
                    f"Event at {at} starts before the previous gate ends at {previous_end}.",
                    "Shorten the previous duration or move this event; adjacent gates are allowed.",
                )
                valid_events = False

            voices.add(instruments[instrument_name].voice)
            events.append(
                NoteEvent(
                    index=index,
                    at=at,
                    duration=duration,
                    note=note,
                    note_index=note_value,
                    instrument=instrument_name,
                )
            )
            previous_at = at
            previous_end = at + duration

        if len(voices) > 1:
            valid_events = False
            # Point at the first event whose voice differs from the first one.
            first_voice = next(iter(voices))
            for event in events:
                if instruments[event.instrument].voice != first_voice:
                    sink.error(
                        "VOICE_CHANNEL_MISMATCH",
                        pointer(pattern_path, "events", event.index, "instrument"),
                        "A v1 pattern mixes pulse and noise instruments.",
                        "Split the pattern into per-channel patterns; each physical channel is monophonic.",
                    )
                    break

        # A pattern is monophonic, so its events define the single channel voice
        # that plays any effect window it declares.
        pattern_voice = next(iter(voices)) if len(voices) == 1 else None
        effects: tuple[EffectWindow, ...] = ()
        commands: tuple[LiveCommand, ...] = ()
        effects_ok = True
        commands_ok = True

        if "effects" in body:
            effects_value = body["effects"]
            source_effects += len(effects_value) if isinstance(effects_value, list) else 1
            if source_effects > HOST_LIMITS["source_effects"]:
                sink.error(
                    "LIMIT_EXCEEDED",
                    pointer(pattern_path, "effects"),
                    f"More than {HOST_LIMITS['source_effects']} source effect windows.",
                    "Remove effect windows or split the score.",
                )
                effects_ok = False
            else:
                effects, effects_ok = _validate_effects(
                    effects_value,
                    pattern_path=pattern_path,
                    ticks=body.get("ticks"),
                    ticks_ok=ticks_ok,
                    voice=pattern_voice,
                    sink=sink,
                )

        if "commands" in body:
            commands_value = body["commands"]
            source_commands += len(commands_value) if isinstance(commands_value, list) else 1
            if source_commands > HOST_LIMITS["source_commands"]:
                sink.error(
                    "LIMIT_EXCEEDED",
                    pointer(pattern_path, "commands"),
                    f"More than {HOST_LIMITS['source_commands']} source live commands.",
                    "Remove commands or split the score.",
                )
                commands_ok = False
            else:
                commands, commands_ok = _validate_commands(
                    commands_value,
                    pattern_path=pattern_path,
                    ticks=body.get("ticks"),
                    ticks_ok=ticks_ok,
                    sink=sink,
                )

        if valid_events and effects_ok and commands_ok:
            patterns[pattern_name] = Pattern(
                name=pattern_name,
                ticks=body["ticks"],
                events=tuple(events),
                effects=effects,
                commands=commands,
            )
            pattern_voices[pattern_name] = frozenset(voices)

    return patterns, pattern_voices


def _check_bool(value: Any, *, path: str, label: str, sink: _Sink) -> bool:
    if not isinstance(value, bool):
        sink.error(
            "TYPE_MISMATCH",
            path,
            f"{label} must be a boolean.",
            "Use true or false.",
        )
        return False
    return True


def _check_choice(value: Any, *, path: str, label: str, choices: tuple[str, ...], sink: _Sink) -> bool:
    if not isinstance(value, str):
        sink.error(
            "TYPE_MISMATCH",
            path,
            f"{label} must be a string.",
            f"Use one of {', '.join(choices)}.",
        )
        return False
    if value not in choices:
        sink.error(
            "VALUE_RANGE",
            path,
            f"Unsupported {label} {value!r}.",
            f"Use one of {', '.join(choices)}.",
        )
        return False
    return True


def _check_note_token(value: Any, *, path: str, label: str, sink: _Sink) -> tuple[bool, str | None, int | None]:
    if not isinstance(value, str):
        sink.error(
            "TYPE_MISMATCH",
            path,
            f"{label} must be a string.",
            f"Use a pitch token such as {PITCH_MIN}..{PITCH_MAX}.",
        )
        return False, None, None
    problem, note_value = note_range_problem(value)
    if problem == "INVALID_NOTE":
        sink.error(
            "INVALID_NOTE",
            path,
            f"{value!r} is not a v1 note token.",
            f"Use a natural or sharp pitch from {PITCH_MIN} to {PITCH_MAX}.",
        )
        return False, None, None
    if problem == "PITCH_RANGE":
        sink.error(
            "PITCH_RANGE",
            path,
            f"{value} is outside the engine pitch range {PITCH_MIN}..{PITCH_MAX}.",
            f"Choose a pitch between {PITCH_MIN} and {PITCH_MAX}.",
        )
        return False, None, None
    return True, value, note_value


def _validate_effect_params(kind: str, item: dict, *, path: str, sink: _Sink) -> tuple[bool, dict]:
    """Validate the kind-specific operands and return ``(ok, params)``."""
    ok = True
    params: dict[str, Any] = {}

    if kind == "arpeggio":
        offsets = item.get("offsets")
        offsets_ok = True
        values: list[int] = []
        if not isinstance(offsets, list):
            sink.error(
                "TYPE_MISMATCH",
                pointer(path, "offsets"),
                "arpeggio offsets must be an array.",
                "Use [a] for a two-step cycle or [a, b] for a three-step cycle.",
            )
            offsets_ok = False
        elif len(offsets) not in (1, 2):
            sink.error(
                "VALUE_RANGE",
                pointer(path, "offsets"),
                f"arpeggio offsets has {len(offsets)} entries; expected 1 or 2.",
                "Use [a] (two-step) or [a, b] (three-step).",
            )
            offsets_ok = False
        else:
            for i, entry in enumerate(offsets):
                if not _is_int(entry):
                    sink.error(
                        "TYPE_MISMATCH",
                        pointer(path, "offsets", i),
                        "arpeggio offset must be an integer.",
                        "Use an integer in 0..14.",
                    )
                    offsets_ok = False
                elif entry < 0 or entry > 14:
                    sink.error(
                        "VALUE_RANGE",
                        pointer(path, "offsets", i),
                        f"arpeggio offset {entry} is outside 0..14.",
                        "Use 0..14; 15 is the engine's note-off nibble (use note_cut instead).",
                    )
                    offsets_ok = False
                else:
                    values.append(entry)
            period_ok = _check_int_range(
            item.get("period"),
            path=pointer(path, "period"),
            minimum=1,
            maximum=32,
            label="arpeggio period",
            sink=sink,
        )
        repeat = True
        repeat_ok = True
        if "repeat" in item:
            repeat_ok = _check_bool(item.get("repeat"), path=pointer(path, "repeat"), label="arpeggio repeat", sink=sink)
        if repeat_ok and "repeat" in item:
            repeat = item["repeat"]
        ok = offsets_ok and period_ok and repeat_ok
        if ok:
            params.update(offsets=tuple(values), period=item["period"], repeat=repeat)

    elif kind == "note_cut":
        period_ok = _check_int_range(
            item.get("period"),
            path=pointer(path, "period"),
            minimum=1,
            maximum=32,
            label="note_cut period",
            sink=sink,
        )
        repeat = True
        repeat_ok = True
        if "repeat" in item:
            repeat_ok = _check_bool(item.get("repeat"), path=pointer(path, "repeat"), label="note_cut repeat", sink=sink)
        if repeat_ok and "repeat" in item:
            repeat = item["repeat"]
        ok = period_ok and repeat_ok
        if ok:
            params.update(period=item["period"], repeat=repeat)

    elif kind == "lfo":
        mode_ok = _check_choice(
            item.get("mode"),
            path=pointer(path, "mode"),
            label="lfo mode",
            choices=LFO_MODES,
            sink=sink,
        )
        depth_ok = _check_int_range(
            item.get("depth"),
            path=pointer(path, "depth"),
            minimum=0,
            maximum=255,
            label="lfo depth",
            sink=sink,
        )
        period_ok = _check_int_range(
            item.get("period"),
            path=pointer(path, "period"),
            minimum=2,
            maximum=64,
            label="lfo period",
            sink=sink,
        )
        if period_ok and item["period"] % 2 != 0:
            sink.error(
                "VALUE_RANGE",
                pointer(path, "period"),
                f"lfo period {item['period']} is not even; the engine stores a half period of 1..32 ticks.",
                "Use an even full period from 2 to 64.",
            )
            period_ok = False
        ok = mode_ok and depth_ok and period_ok
        if ok:
            params.update(mode=item["mode"], depth=item["depth"], period=item["period"])

    elif kind == "slide":
        param_ok = _check_choice(
            item.get("param"),
            path=pointer(path, "param"),
            label="slide param",
            choices=SLIDE_PARAMS,
            sink=sink,
        )
        amount_ok = _check_int_range(
            item.get("amount"),
            path=pointer(path, "amount"),
            minimum=-128,
            maximum=127,
            label="slide amount",
            sink=sink,
        )
        every_ok = _check_int_range(
            item.get("every"),
            path=pointer(path, "every"),
            minimum=1,
            maximum=64,
            label="slide every",
            sink=sink,
        )
        ok = param_ok and amount_ok and every_ok
        if ok:
            params.update(param=item["param"], amount=item["amount"], every=item["every"])

    elif kind == "glissando":
        period_ok = _check_int_range(
            item.get("period"),
            path=pointer(path, "period"),
            minimum=1,
            maximum=128,
            label="glissando period",
            sink=sink,
        )
        direction_ok = _check_choice(
            item.get("direction"),
            path=pointer(path, "direction"),
            label="glissando direction",
            choices=GLISSANDO_DIRECTIONS,
            sink=sink,
        )
        ok = period_ok and direction_ok
        if ok:
            params.update(period=item["period"], direction=item["direction"])

    elif kind == "noise_retrig":
        period_ok = _check_int_range(
            item.get("period"),
            path=pointer(path, "period"),
            minimum=0,
            maximum=3,
            label="noise_retrig period",
            sink=sink,
        )
        note_ok, note, note_index = _check_note_token(
            item.get("note"),
            path=pointer(path, "note"),
            label="noise_retrig note",
            sink=sink,
        )
        ok = period_ok and note_ok
        if ok:
            params.update(period=item["period"], note=note, note_index=note_index)

    return ok, params


def _validate_effects(
    value: Any,
    *,
    pattern_path: str,
    ticks: Any,
    ticks_ok: bool,
    voice: str | None,
    sink: _Sink,
) -> tuple[tuple[EffectWindow, ...], bool]:
    effects_path = pointer(pattern_path, "effects")
    if not isinstance(value, list):
        sink.error(
            "TYPE_MISMATCH",
            effects_path,
            "effects must be an array.",
            "Use an ordered array of effect windows (an empty array is allowed).",
        )
        return (), False

    ticks_valid = _is_int(ticks) and ticks_ok
    windows: list[EffectWindow] = []
    valid = True
    previous_at: int | None = None
    slot_ends: dict[str, int] = {}

    for index, item in enumerate(value):
        item_path = pointer(effects_path, index)
        if not isinstance(item, dict):
            sink.error(
                "TYPE_MISMATCH",
                item_path,
                "Effect window must be an object.",
                "Provide at, type and the type's parameters.",
            )
            valid = False
            continue

        kind = item.get("type")
        if "type" not in item:
            sink.error(
                "MISSING_FIELD",
                pointer(item_path, "type"),
                "Required field 'type' is missing.",
                f"Add 'type' naming one of {', '.join(EFFECT_TYPES)}.",
            )
            valid = False
            continue
        if not isinstance(kind, str):
            sink.error(
                "TYPE_MISMATCH",
                pointer(item_path, "type"),
                "Effect type must be a string.",
                f"Use one of {', '.join(EFFECT_TYPES)}.",
            )
            valid = False
            continue
        if kind not in EFFECT_TYPES:
            sink.error(
                "UNKNOWN_EFFECT_TYPE",
                pointer(item_path, "type"),
                f"Unsupported effect type {kind!r}.",
                f"Use one of {', '.join(EFFECT_TYPES)}.",
            )
            valid = False
            continue

        _check_keys(
            item,
            path=item_path,
            allowed=EFFECT_COMMON_FIELDS + EFFECT_KIND_FIELDS[kind],
            required=("at", "type") + EFFECT_KIND_REQUIRED[kind],
            sink=sink,
        )

        at_ok = _check_int_range(
            item.get("at"),
            path=pointer(item_path, "at"),
            minimum=0,
            maximum=HOST_LIMITS["total_ticks"],
            label=f"{kind} effect at",
            sink=sink,
        )
        at_value = item["at"] if at_ok else None

        until_value: int | None = ticks if ticks_valid else None
        until_ok = True
        if "until" in item:
            until_ok = _check_int_range(
                item.get("until"),
                path=pointer(item_path, "until"),
                minimum=1,
                maximum=HOST_LIMITS["total_ticks"],
                label=f"{kind} effect until",
                sink=sink,
            )
            until_value = item["until"] if until_ok else None

        if at_ok and ticks_valid and at_value is not None and at_value >= ticks:
            sink.error(
                "EFFECT_BOUNDS",
                pointer(item_path, "at"),
                f"{kind} effect starts at {at_value}, outside pattern ticks={ticks}.",
                "Start the effect inside [0, ticks) or increase pattern ticks.",
            )
            at_ok = False

        if until_ok:
            if until_value is not None and at_value is not None and until_value <= at_value:
                sink.error(
                    "EFFECT_BOUNDS",
                    pointer(item_path, "until"),
                    f"{kind} effect ends at {until_value}, not after at={at_value}.",
                    "Set until greater than at (until is the exclusive end tick).",
                )
                until_ok = False
            elif until_value is not None and ticks_valid and until_value > ticks:
                sink.error(
                    "EFFECT_BOUNDS",
                    pointer(item_path, "until"),
                    f"{kind} effect ends at {until_value}, past pattern ticks={ticks}.",
                    "End the effect at or before the pattern boundary.",
                )
                until_ok = False

        params_ok, params = _validate_effect_params(kind, item, path=item_path, sink=sink)

        channel_ok = True
        if voice is not None:
            expected = "noise" if kind in NOISE_EFFECT_TYPES else "pulse"
            if voice != expected:
                sink.error(
                    "EFFECT_CHANNEL_MISMATCH",
                    pointer(item_path, "type"),
                    f"{kind} is a {expected}-channel effect but the pattern's instruments are {voice}.",
                    (
                        "Use noise_retrig only in a pattern whose events are noise instruments."
                        if expected == "noise"
                        else f"Use {kind} only in a pattern whose events are pulse instruments."
                    ),
                )
                channel_ok = False

        if at_value is not None:
            if previous_at is not None and at_value < previous_at:
                sink.error(
                    "EFFECT_ORDER",
                    pointer(item_path, "at"),
                    f"Effect at {at_value} is not after the previous effect at {previous_at}.",
                    "Sort effects by ascending at; equal at is allowed for different slots.",
                )
                valid = False
            else:
                slot = EFFECT_SLOT[kind]
                last_end = slot_ends.get(slot)
                if last_end is not None and at_value < last_end:
                    sink.error(
                        "EFFECT_OVERLAP",
                        item_path,
                        f"{kind} starts at {at_value}, before the previous {slot} window ends at {last_end}.",
                        "Shorten the previous window or move this one; a slot is monophonic.",
                    )
                    valid = False
                elif until_value is not None and until_ok:
                    slot_ends[slot] = until_value
            previous_at = at_value

        if at_ok and until_ok and params_ok and channel_ok:
            windows.append(
                EffectWindow(
                    index=index,
                    kind=kind,
                    at=item["at"],
                    until=until_value if until_value is not None else item["at"] + 1,
                    **params,
                )
            )
        else:
            valid = False

    return tuple(windows), valid


def _validate_commands(
    value: Any,
    *,
    pattern_path: str,
    ticks: Any,
    ticks_ok: bool,
    sink: _Sink,
) -> tuple[tuple[LiveCommand, ...], bool]:
    commands_path = pointer(pattern_path, "commands")
    if not isinstance(value, list):
        sink.error(
            "TYPE_MISMATCH",
            commands_path,
            "commands must be an array.",
            "Use an ordered array of live commands (an empty array is allowed).",
        )
        return (), False

    ticks_valid = _is_int(ticks) and ticks_ok
    commands: list[LiveCommand] = []
    valid = True
    previous_at: int | None = None
    seen: set[tuple[str, int]] = set()

    for index, item in enumerate(value):
        item_path = pointer(commands_path, index)
        if not isinstance(item, dict):
            sink.error(
                "TYPE_MISMATCH",
                item_path,
                "Live command must be an object.",
                "Provide at, type and value.",
            )
            valid = False
            continue

        kind = item.get("type")
        if "type" not in item:
            sink.error(
                "MISSING_FIELD",
                pointer(item_path, "type"),
                "Required field 'type' is missing.",
                f"Add 'type' naming one of {', '.join(COMMAND_TYPES)}.",
            )
            valid = False
            continue
        if not isinstance(kind, str):
            sink.error(
                "TYPE_MISMATCH",
                pointer(item_path, "type"),
                "Command type must be a string.",
                f"Use one of {', '.join(COMMAND_TYPES)}.",
            )
            valid = False
            continue
        if kind not in COMMAND_TYPES:
            sink.error(
                "UNKNOWN_COMMAND_TYPE",
                pointer(item_path, "type"),
                f"Unsupported command type {kind!r}.",
                f"Use one of {', '.join(COMMAND_TYPES)}.",
            )
            valid = False
            continue

        _check_keys(
            item,
            path=item_path,
            allowed=COMMAND_FIELDS,
            required=COMMAND_FIELDS,
            sink=sink,
        )

        at_ok = _check_int_range(
            item.get("at"),
            path=pointer(item_path, "at"),
            minimum=0,
            maximum=HOST_LIMITS["total_ticks"],
            label=f"{kind} at",
            sink=sink,
        )
        minimum, maximum = COMMAND_VALUE_RANGES[kind]
        value_ok = _check_int_range(
            item.get("value"),
            path=pointer(item_path, "value"),
            minimum=minimum,
            maximum=maximum,
            label=f"{kind} value",
            sink=sink,
        )

        if at_ok and ticks_valid and item["at"] >= ticks:
            sink.error(
                "COMMAND_BOUNDS",
                pointer(item_path, "at"),
                f"{kind} at {item['at']} is outside pattern ticks={ticks}.",
                "Place the command inside [0, ticks).",
            )
            at_ok = False

        if at_ok:
            at = item["at"]
            key = (kind, at)
            if key in seen:
                sink.error(
                    "COMMAND_DUPLICATE",
                    pointer(item_path, "at"),
                    f"Duplicate {kind} command at {at}.",
                    "One command per (type, at); remove the duplicate.",
                )
                valid = False
            if previous_at is not None and at < previous_at:
                sink.error(
                    "COMMAND_ORDER",
                    pointer(item_path, "at"),
                    f"Command at {at} is not after the previous command at {previous_at}.",
                    "Sort commands by ascending at; equal at is allowed for different types.",
                )
                valid = False
            seen.add(key)
            previous_at = at

        if at_ok and value_ok:
            commands.append(
                LiveCommand(
                    index=index,
                    kind=kind,
                    at=item["at"],
                    value=item["value"],
                )
            )
        else:
            valid = False

    return tuple(commands), valid


def _validate_tracks(
    value: Any,
    patterns: dict[str, Pattern],
    pattern_voices: dict[str, frozenset[str]],
    sink: _Sink,
) -> dict[str, tuple[TrackUse, ...]]:
    tracks: dict[str, tuple[TrackUse, ...]] = {}
    if not isinstance(value, dict):
        sink.error(
            "TYPE_MISMATCH",
            "/tracks",
            "tracks must be an object.",
            "Name at least one of pulse0, pulse1, pulse2, noise.",
        )
        return tracks

    for key in value:
        if key not in CHANNEL_NAMES:
            sink.error(
                "UNKNOWN_TRACK",
                pointer("tracks", key),
                f"Unknown physical track {key!r}.",
                f"Use one of {', '.join(CHANNEL_NAMES)} as track keys.",
            )

    known = [name for name in CHANNEL_NAMES if name in value]
    if not known:
        sink.error(
            "EMPTY_TRACK",
            "/tracks",
            "At least one physical track is required.",
            "Add a non-empty array under a channel name such as pulse0.",
        )
        return tracks

    total_uses = 0
    total_expanded_notes = 0
    total_tick_guard = 0
    for channel in known:
        track_path = pointer("tracks", channel)
        uses_value = value[channel]
        if not isinstance(uses_value, list):
            sink.error(
                "TYPE_MISMATCH",
                track_path,
                "Track must be an array of pattern uses.",
                "Use [{\"pattern\": \"name\", \"repeat\": 1}].",
            )
            continue
        if not uses_value:
            sink.error(
                "EMPTY_TRACK",
                track_path,
                "Track array is empty.",
                "Remove the channel key to leave it silent, or add a pattern use.",
            )
            continue

        uses: list[TrackUse] = []
        channel_ok = True
        channel_ticks = 0
        for index, use in enumerate(uses_value):
            use_path = pointer(track_path, index)
            if not isinstance(use, dict):
                sink.error(
                    "TYPE_MISMATCH",
                    use_path,
                    "Pattern use must be an object.",
                    "Provide pattern and repeat.",
                )
                channel_ok = False
                continue

            _check_keys(
                use,
                path=use_path,
                allowed=TRACK_USE_FIELDS,
                required=TRACK_USE_FIELDS,
                sink=sink,
            )

            pattern_name = use.get("pattern")
            pattern_ok = True
            if "pattern" in use:
                if not isinstance(pattern_name, str):
                    sink.error(
                        "TYPE_MISMATCH",
                        pointer(use_path, "pattern"),
                        "pattern must be a string.",
                        "Reference a pattern name.",
                    )
                    pattern_ok = False
                elif pattern_name not in patterns:
                    sink.error(
                        "UNKNOWN_PATTERN",
                        pointer(use_path, "pattern"),
                        f"Unknown pattern {pattern_name!r}.",
                        "Add the pattern to /patterns or fix the reference.",
                    )
                    pattern_ok = False

            repeat_ok = _check_int_range(
                use.get("repeat"),
                path=pointer(use_path, "repeat"),
                minimum=1,
                maximum=256,
                label="pattern repeat",
                sink=sink,
            )
            if not (pattern_ok and repeat_ok):
                channel_ok = False
                continue

            assert isinstance(pattern_name, str)
            repeat = use["repeat"]

            total_uses += repeat
            if total_uses > HOST_LIMITS["expanded_pattern_uses"]:
                sink.error(
                    "LIMIT_EXCEEDED",
                    use_path,
                    f"More than {HOST_LIMITS['expanded_pattern_uses']} expanded pattern uses.",
                    "Reduce repeats or split the arrangement.",
                )
                channel_ok = False
                continue

            pattern = patterns[pattern_name]
            total_expanded_notes += repeat * len(pattern.events)
            if total_expanded_notes > HOST_LIMITS["expanded_note_events"]:
                sink.error(
                    "LIMIT_EXCEEDED",
                    use_path,
                    f"More than {HOST_LIMITS['expanded_note_events']} expanded note events.",
                    "Reduce repeats, events or split the song.",
                )
                channel_ok = False
                continue

            expected_voice = CHANNEL_VOICE[channel]
            voices = pattern_voices.get(pattern_name, frozenset())
            if voices and expected_voice not in voices:
                sink.error(
                    "VOICE_CHANNEL_MISMATCH",
                    pointer(use_path, "pattern"),
                    f"Pattern {pattern_name!r} uses {sorted(voices)[0]} instruments on {channel}.",
                    f"{channel} accepts only {expected_voice} instruments.",
                )
                channel_ok = False
                continue

            channel_ticks += pattern.ticks * repeat
            total_tick_guard = max(total_tick_guard, channel_ticks)
            if channel_ticks > HOST_LIMITS["total_ticks"]:
                sink.error(
                    "LIMIT_EXCEEDED",
                    track_path,
                    f"Expanded track length exceeds {HOST_LIMITS['total_ticks']} ticks.",
                    "Reduce pattern ticks or repeats.",
                )
                channel_ok = False
                break

            uses.append(TrackUse(index=index, pattern=pattern_name, repeat=repeat))

        if channel_ok and uses:
            tracks[channel] = tuple(uses)

    if total_tick_guard > HOST_LIMITS["total_ticks"]:
        return {}
    return tracks


def load_and_validate(path: str) -> tuple[Score | None, list[Diagnostic]]:
    """Read, parse and validate a score file.  I/O errors are exit-code 3."""
    try:
        raw = read_file(path)
    except OSError as exc:
        return None, [
            Diagnostic(
                "IO_ERROR",
                "",
                f"Cannot read {path!r}: {exc}",
                "Pass a readable JSON score path.",
            )
        ]

    try:
        parsed = parse_json_bytes(raw)
    except InvalidJson as exc:
        return None, [
            Diagnostic(
                "INVALID_JSON",
                "",
                str(exc),
                "Fix the JSON syntax; use UTF-8 and no comments or trailing commas.",
            )
        ]

    return validate_document(parsed.document, source_path=path, raw_bytes=raw, parsed=parsed)
