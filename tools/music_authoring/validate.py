"""Strict v1 score validation with stable codes and JSON Pointer diagnostics."""

from __future__ import annotations

import hashlib
from typing import Any

from .score import (
    CHANNEL_NAMES,
    CHANNEL_VOICE,
    HOST_LIMITS,
    IDENTIFIER_MAX_LENGTH,
    IDENTIFIER_RE,
    NOTE_MAX_INDEX,
    NOTE_MIN_INDEX,
    PITCH_MAX,
    PITCH_MIN,
    SOURCE_FORMAT,
    SCHEMA_VERSION,
    Clock,
    Diagnostic,
    Instrument,
    InvalidJson,
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
EVENT_FIELDS = ("at", "note", "duration", "instrument")
TRACK_USE_FIELDS = ("pattern", "repeat")


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
            allowed=PATTERN_FIELDS,
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

        if valid_events:
            patterns[pattern_name] = Pattern(
                name=pattern_name,
                ticks=body["ticks"],
                events=tuple(events),
            )
            pattern_voices[pattern_name] = frozenset(voices)

    return patterns, pattern_voices


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
