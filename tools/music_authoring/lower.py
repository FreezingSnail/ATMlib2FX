"""Lower a validated score to a canonical host timeline.

The canonical event list is the single musical interpretation shared by the
compact FX adapter, the ``review.json`` payload and the event digest.

Canonicalization id: ``atmlib-canonical-events-v1``.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

from .score import (
    CHANNEL_NAMES,
    CHANNEL_VOICE,
    COMMAND_TYPES,
    EFFECT_TYPES,
    HOST_LIMITS,
    SCHEMA_VERSION,
    TICK_BASE_HZ,
    TOOL_NAME,
    TOOL_VERSION,
    ENGINE_NAME,
    Diagnostic,
    Score,
    ScoreError,
    library_version,
    pointer,
)

CANONICALIZATION = "atmlib-canonical-events-v1"
REVIEW_PAYLOAD = "atmlib-review"
REVIEW_PAYLOAD_VERSION = 1
DIGEST_ALGORITHM = "sha256"

# Maps each effect window kind to the engine ON opcode family name and the OFF
# opcode family name. `note_cut` shares the arpeggio OFF opcode
# (`ATM_CMD_I_ARPEGGIO_OFF == ATM_CMD_I_NOTECUT_OFF`), so its window is closed
# with `arpeggio_off`. The opcode-to-byte encoding itself belongs to the
# backends (ATMlib2FX-3ii.14.3); these names are host-only.
EFFECT_ON_OPS = {
    "arpeggio": "arpeggio_on",
    "note_cut": "note_cut_on",
    "lfo": "lfo_on",
    "slide": "slide_on",
    "glissando": "glissando_on",
    "noise_retrig": "noise_retrig_on",
}
EFFECT_OFF_OPS = {
    "arpeggio": "arpeggio_off",
    "note_cut": "arpeggio_off",
    "lfo": "lfo_off",
    "slide": "slide_off",
    "glissando": "glissando_off",
    "noise_retrig": "noise_retrig_off",
}
EFFECT_OP_NAMES = frozenset(EFFECT_ON_OPS.values()) | frozenset(EFFECT_OFF_OPS.values())
COMMAND_OP_NAMES = frozenset(COMMAND_TYPES)

# Same-tick ordering (lower is earlier). Deterministic and documented in
# docs/music-authoring.md (event ordering). It only affects
# scores that carry effects or commands; an effect-free score keeps its original
# per-channel append order (the clock `set_tempo` first at tick 0, then for each
# note the volume/mod/note attack followed by the gate mute).
_ORDER_CLOCK_TEMPO = 0
_ORDER_EFFECT_OFF = 1
_ORDER_EFFECT_ON = 2
_ORDER_MUTE = 3
_ORDER_SET_VOLUME = 4
_ORDER_SET_MOD = 5
_ORDER_NOTE = 6
_ORDER_COMMAND = 7


@dataclass(frozen=True)
class NoteSpan:
    channel: int
    start_tick: int
    duration: int
    gate_end_tick: int
    note: str
    note_index: int
    instrument: str
    volume: int
    duty: int | None
    pattern: str
    repeat_index: int
    pattern_instance_index: int
    source: str

    def as_dict(self) -> dict:
        return {
            "channel": self.channel,
            "start_tick": self.start_tick,
            "duration": self.duration,
            "gate_end_tick": self.gate_end_tick,
            "note": self.note,
            "note_index": self.note_index,
            "instrument": self.instrument,
            "volume": self.volume,
            "duty": self.duty,
            "pattern": self.pattern,
            "repeat_index": self.repeat_index,
            "pattern_instance_index": self.pattern_instance_index,
            "source": self.source,
        }


@dataclass(frozen=True)
class PatternInstance:
    channel: int
    index: int
    pattern: str
    repeat_index: int
    start_tick: int
    ticks: int
    source: str

    def as_dict(self) -> dict:
        return {
            "channel": self.channel,
            "index": self.index,
            "pattern": self.pattern,
            "repeat_index": self.repeat_index,
            "start_tick": self.start_tick,
            "ticks": self.ticks,
            "source": self.source,
        }


def _json_value(value: object) -> object:
    """Convert an immutable param value to a JSON-serializable one."""
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    return value


def params_dict(params: tuple) -> dict:
    """Render an ordered ``(name, value)`` param tuple as a plain dict."""
    return {name: _json_value(value) for name, value in params}


def _effect_params(window) -> tuple:
    """Ordered typed operands for an effect window (JSON primitives only)."""
    if window.kind == "arpeggio":
        return (
            ("offsets", tuple(window.offsets or ())),
            ("period", window.period),
            ("repeat", bool(window.repeat)),
        )
    if window.kind == "note_cut":
        return (("period", window.period), ("repeat", bool(window.repeat)))
    if window.kind == "lfo":
        return (
            ("mode", window.mode),
            ("depth", window.depth),
            ("period", window.period),
        )
    if window.kind == "slide":
        return (
            ("param", window.param),
            ("amount", window.amount),
            ("every", window.every),
        )
    if window.kind == "glissando":
        return (("period", window.period), ("direction", window.direction))
    if window.kind == "noise_retrig":
        return (
            ("period", window.period),
            ("note", window.note),
            ("note_index", window.note_index),
        )
    raise ScoreError(f"unknown effect kind {window.kind!r}")


@dataclass(frozen=True)
class EffectSpan:
    """One expanded effect window in absolute song ticks."""

    channel: int
    kind: str
    start_tick: int
    end_tick: int
    params: tuple
    pattern: str
    repeat_index: int
    pattern_instance_index: int
    source: str

    def as_dict(self) -> dict:
        return {
            "channel": self.channel,
            "kind": self.kind,
            "start_tick": self.start_tick,
            "end_tick": self.end_tick,
            "params": params_dict(self.params),
            "pattern": self.pattern,
            "repeat_index": self.repeat_index,
            "pattern_instance_index": self.pattern_instance_index,
            "source": self.source,
        }


@dataclass(frozen=True)
class CommandEvent:
    """One expanded instantaneous live command in absolute song ticks.

    ``start_tick`` equals ``end_tick`` because commands take effect on a single
    tick; the pair is kept so the review payload has one span shape.
    """

    channel: int
    kind: str
    tick: int
    value: int
    is_global: bool
    pattern: str
    repeat_index: int
    pattern_instance_index: int
    source: str

    def as_dict(self) -> dict:
        return {
            "channel": self.channel,
            "kind": self.kind,
            "start_tick": self.tick,
            "end_tick": self.tick,
            "params": {"value": self.value},
            "global": self.is_global,
            "pattern": self.pattern,
            "repeat_index": self.repeat_index,
            "pattern_instance_index": self.pattern_instance_index,
            "source": self.source,
        }


@dataclass(frozen=True)
class DeviceOp:
    """One typed playback operation before backend byte encoding.

    ``params`` is an immutable, ordered tuple of ``(name, value)`` pairs giving
    the typed operand payload of effect and live-command ops.  ``value`` is a
    JSON primitive (int, str, bool, ``None``) or a tuple of primitives (nested
    tuples are flattened to arrays by :func:`params_dict`).  Existing note ops
    keep using their dedicated fields and leave ``params`` empty, so their
    ``canonical()`` output is unchanged.
    """

    op: str
    tick: int
    channel: int
    source: str
    tick_rate: int | None = None
    volume: int | None = None
    duty: int | None = None
    note: str | None = None
    note_index: int | None = None
    params: tuple = ()

    def canonical(self) -> dict:
        body = {"op": self.op, "channel": self.channel, "tick": self.tick}
        if self.op == "set_tempo":
            body["tick_rate"] = self.tick_rate
        elif self.op == "set_volume":
            # Instrument volume ops always carry an int; a live `set_volume`
            # command leaves it None and reports its operand as params.
            if self.volume is not None:
                body["volume"] = self.volume
            else:
                body["params"] = params_dict(self.params)
        elif self.op == "set_mod":
            if self.duty is not None:
                body["duty"] = self.duty
            else:
                body["params"] = params_dict(self.params)
        elif self.op == "note":
            body["note"] = self.note
            body["note_index"] = self.note_index
        elif self.op == "mute":
            pass
        elif self.op in EFFECT_OP_NAMES or self.op in COMMAND_OP_NAMES:
            body["params"] = params_dict(self.params)
        else:
            raise ScoreError(f"unknown device op {self.op!r}")
        body["source"] = self.source
        return body



@dataclass(frozen=True)
class Lowered:
    spans: tuple[NoteSpan, ...]
    pattern_instances: tuple[PatternInstance, ...]
    total_ticks: int
    track_ticks: dict[str, int]
    ops: dict[str, tuple[DeviceOp, ...]]
    canonical_events: tuple[dict, ...]
    canonical_bytes: bytes
    event_digest: dict = field(default_factory=dict)
    effect_spans: tuple[EffectSpan, ...] = ()
    command_events: tuple[CommandEvent, ...] = ()

    def ops_for_channel(self, channel: str) -> tuple[DeviceOp, ...]:
        return self.ops.get(channel, ())


def _append_op(ops: list[DeviceOp], op: DeviceOp) -> None:
    """Append an op, dropping a directly redundant volume/mod write.

    Only instrument volume/mod writes are de-duplicated; effect and command ops
    are always distinct when their tick/channel/source differ, and two effect
    ops of the same kind at one tick would still carry different operands.
    """
    if ops and op.op in ("set_volume", "set_mod"):
        previous = ops[-1]
        if (
            previous.op == op.op
            and previous.tick == op.tick
            and previous.channel == op.channel
            and previous.volume == op.volume
            and previous.duty == op.duty
        ):
            return
    ops.append(op)


def _channel_index(name: str) -> int:
    return CHANNEL_NAMES.index(name)


def _command_op(event: CommandEvent) -> DeviceOp:
    """Map a live command to its typed device op."""
    if event.kind == "set_tempo":
        return DeviceOp(
            op="set_tempo",
            tick=event.tick,
            channel=event.channel,
            source=event.source,
            tick_rate=event.value,
        )
    return DeviceOp(
        op=event.kind,
        tick=event.tick,
        channel=event.channel,
        source=event.source,
        params=(("value", event.value),),
    )


def _build_channel_ops(
    score: Score,
    channel: str,
    channel_index: int,
    spans: list[NoteSpan],
    effects: list[EffectSpan],
    commands: list[CommandEvent],
) -> tuple[DeviceOp, ...]:
    """Emit one channel's ops in the documented same-tick order.

    Ops are collected with a stable ``(tick, priority, emit_index)`` key and
    sorted, then de-duplicated. An effect-free channel reproduces the original
    append order exactly, so its canonical events (and digest) are unchanged.
    """
    raw: list[tuple[int, int, int, DeviceOp]] = []
    sequence = 0

    def emit(op: DeviceOp, priority: int) -> None:
        nonlocal sequence
        raw.append((op.tick, priority, sequence, op))
        sequence += 1

    if channel_index == 0:
        emit(
            DeviceOp(
                op="set_tempo",
                tick=0,
                channel=0,
                source="/clock/tick_rate",
                tick_rate=score.clock.tick_rate,
            ),
            _ORDER_CLOCK_TEMPO,
        )
    for span in spans:
        emit(
            DeviceOp(
                op="set_volume",
                tick=span.start_tick,
                channel=channel_index,
                source=span.source,
                volume=span.volume,
            ),
            _ORDER_SET_VOLUME,
        )
        if CHANNEL_VOICE[channel] == "pulse":
            emit(
                DeviceOp(
                    op="set_mod",
                    tick=span.start_tick,
                    channel=channel_index,
                    source=span.source,
                    duty=span.duty,
                ),
                _ORDER_SET_MOD,
            )
        emit(
            DeviceOp(
                op="note",
                tick=span.start_tick,
                channel=channel_index,
                source=span.source,
                note=span.note,
                note_index=span.note_index,
            ),
            _ORDER_NOTE,
        )
        emit(
            DeviceOp(
                op="mute",
                tick=span.gate_end_tick,
                channel=channel_index,
                source=span.source,
            ),
            _ORDER_MUTE,
        )
    for effect in effects:
        emit(
            DeviceOp(
                op=EFFECT_ON_OPS[effect.kind],
                tick=effect.start_tick,
                channel=channel_index,
                source=effect.source,
                params=effect.params,
            ),
            _ORDER_EFFECT_ON,
        )
        emit(
            DeviceOp(
                op=EFFECT_OFF_OPS[effect.kind],
                tick=effect.end_tick,
                channel=channel_index,
                source=effect.source,
                params=_off_params_for(effect),
            ),
            _ORDER_EFFECT_OFF,
        )
    for command in commands:
        emit(_command_op(command), _ORDER_COMMAND)

    raw.sort(key=lambda item: (item[0], item[1], item[2]))
    ops: list[DeviceOp] = []
    for _tick, _priority, _sequence, op in raw:
        _append_op(ops, op)
    return tuple(ops)


def _off_params_for(effect: EffectSpan) -> tuple:
    if effect.kind == "slide":
        return (("param", params_dict(effect.params)["param"]),)
    return ()


def lower(score: Score) -> Lowered:
    """Expand finite tracks and emit the canonical ordered device ops."""
    spans: list[NoteSpan] = []
    effects: list[EffectSpan] = []
    commands: list[CommandEvent] = []
    instances: list[PatternInstance] = []
    track_ticks: dict[str, int] = {}
    ops_by_channel: dict[str, tuple[DeviceOp, ...]] = {}
    all_ops: list[tuple[int, int, int, dict]] = []

    for channel in CHANNEL_NAMES:
        if channel not in score.tracks:
            continue
        channel_index = _channel_index(channel)
        channel_spans: list[NoteSpan] = []
        channel_effects: list[EffectSpan] = []
        channel_commands: list[CommandEvent] = []
        tick = 0
        instance_index = 0
        for use in score.tracks[channel]:
            pattern = score.patterns[use.pattern]
            for repeat_index in range(use.repeat):
                instance = PatternInstance(
                    channel=channel_index,
                    index=instance_index,
                    pattern=use.pattern,
                    repeat_index=repeat_index,
                    start_tick=tick,
                    ticks=pattern.ticks,
                    source=pointer("tracks", channel, use.index),
                )
                instances.append(instance)
                for event in pattern.events:
                    instrument = score.instruments[event.instrument]
                    start = tick + event.at
                    span = NoteSpan(
                        channel=channel_index,
                        start_tick=start,
                        duration=event.duration,
                        gate_end_tick=start + event.duration,
                        note=event.note,
                        note_index=event.note_index,
                        instrument=event.instrument,
                        volume=instrument.volume,
                        duty=instrument.duty,
                        pattern=use.pattern,
                        repeat_index=repeat_index,
                        pattern_instance_index=instance_index,
                        source=pointer("patterns", use.pattern, "events", event.index),
                    )
                    channel_spans.append(span)
                    spans.append(span)
                for window in pattern.effects:
                    effect = EffectSpan(
                        channel=channel_index,
                        kind=window.kind,
                        start_tick=tick + window.at,
                        end_tick=tick + window.until,
                        params=_effect_params(window),
                        pattern=use.pattern,
                        repeat_index=repeat_index,
                        pattern_instance_index=instance_index,
                        source=pointer("patterns", use.pattern, "effects", window.index),
                    )
                    channel_effects.append(effect)
                    effects.append(effect)
                for command in pattern.commands:
                    event = CommandEvent(
                        channel=channel_index,
                        kind=command.kind,
                        tick=tick + command.at,
                        value=command.value,
                        is_global=command.is_global,
                        pattern=use.pattern,
                        repeat_index=repeat_index,
                        pattern_instance_index=instance_index,
                        source=pointer("patterns", use.pattern, "commands", command.index),
                    )
                    channel_commands.append(event)
                    commands.append(event)
                tick += pattern.ticks
                instance_index += 1
                if tick > HOST_LIMITS["total_ticks"]:
                    raise ScoreError("track expansion exceeded the validated host limit")
        track_ticks[channel] = tick

        channel_ops = _build_channel_ops(
            score, channel, channel_index, channel_spans, channel_effects, channel_commands
        )
        ops_by_channel[channel] = channel_ops
        for sequence, op in enumerate(channel_ops):
            all_ops.append((op.tick, channel_index, sequence, op.canonical()))

    all_ops.sort(key=lambda item: (item[0], item[1], item[2]))
    canonical_events = tuple(item[3] for item in all_ops)
    canonical_bytes = json.dumps(
        canonical_events,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    event_digest = {
        "algorithm": DIGEST_ALGORITHM,
        "canonicalization": CANONICALIZATION,
        "hex": hashlib.sha256(canonical_bytes).hexdigest(),
    }

    total_ticks = max(track_ticks.values(), default=0)
    return Lowered(
        spans=tuple(spans),
        pattern_instances=tuple(instances),
        total_ticks=total_ticks,
        track_ticks=track_ticks,
        ops=ops_by_channel,
        canonical_events=canonical_events,
        canonical_bytes=canonical_bytes,
        event_digest=event_digest,
        effect_spans=tuple(effects),
        command_events=tuple(commands),
    )


def availability() -> dict:
    return {
        "backend": {
            "fx": {"available": True},
        },
        "capabilities": {
            "validate": {"available": True},
            "build": {"available": True},
        },
    }


def channel_descriptors(score: Score, lowered: Lowered) -> list[dict]:
    descriptors = []
    for index, name in enumerate(CHANNEL_NAMES):
        channel_spans = [span for span in lowered.spans if span.channel == index]
        channel_events = [event for event in lowered.canonical_events if event["channel"] == index]
        descriptors.append(
            {
                "index": index,
                "name": name,
                "voice": CHANNEL_VOICE[name],
                "used": bool(channel_spans),
                "note_count": len(channel_spans),
                "event_count": len(channel_events),
            }
        )
    return descriptors


def clock_report(score: Score) -> dict:
    return {
        "tick_rate": score.clock.tick_rate,
        "effective_tick_rate": score.clock.effective_tick_rate,
        "ticks_per_beat": score.clock.ticks_per_beat,
        "beats_per_bar": score.clock.beats_per_bar,
        "effective_bpm": score.clock.effective_bpm,
    }


def required_features(score: Score, lowered: Lowered) -> list[str]:
    features = ["notes", "rests", "finite_pattern_reuse", "finite_arrangement"]
    if any(span.duty is not None for span in lowered.spans):
        features.append("pulse_duty")
    if any(score.instruments[span.instrument].voice == "noise" for span in lowered.spans):
        features.append("noise_percussion")
    features.append("fixed_instrument_volume")
    features.append("explicit_gate_mute")
    # Effect/command feature names are additive: an effect-free score lists
    # exactly the features it did before this surface existed.
    present_effects = {span.kind for span in lowered.effect_spans}
    for kind in EFFECT_TYPES:
        if kind in present_effects:
            features.append(f"effect_{kind}")
    present_commands = {event.kind for event in lowered.command_events}
    for kind in COMMAND_TYPES:
        if kind in present_commands:
            features.append(f"command_{kind}")
    if score.loop:
        features.append("whole_song_loop")
    return features


def build_review_payload(
    score: Score,
    lowered: Lowered,
    diagnostics: list[Diagnostic] | None = None,
) -> dict:
    diagnostic_dicts = [item.as_dict() for item in (diagnostics or [])]
    payload = {
        "payload": REVIEW_PAYLOAD,
        "payload_version": REVIEW_PAYLOAD_VERSION,
        "tool": {"name": TOOL_NAME, "version": TOOL_VERSION},
        "engine": {
            "name": ENGINE_NAME,
            "library_version": library_version(),
            "channels": list(CHANNEL_NAMES),
            "tick_base_hz": TICK_BASE_HZ,
        },
        "source": {
            "sha256": score.source_sha256,
            "bytes": score.source_bytes,
            "path": score.source_path,
        },
        "clock": clock_report(score),
        "total_ticks": lowered.total_ticks,
        **({"loop": {"start_tick": 0, "end_tick": lowered.total_ticks}} if score.loop else {}),
        "channels": channel_descriptors(score, lowered),
        "notes": [span.as_dict() for span in lowered.spans],
    }
    # Additive keys, present only when the score actually carries them, so an
    # effect-free score serializes byte-identically to the 3ii.1 golden.
    if lowered.effect_spans:
        payload["effects"] = [span.as_dict() for span in lowered.effect_spans]
    if lowered.command_events:
        payload["commands"] = [event.as_dict() for event in lowered.command_events]
    payload["pattern_instances"] = [instance.as_dict() for instance in lowered.pattern_instances]
    payload["event_digest"] = dict(lowered.event_digest)
    payload["diagnostics"] = diagnostic_dicts
    payload["capabilities"] = availability()
    return payload


def validate_summary(score: Score, lowered: Lowered) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "id": score.id,
        "total_ticks": lowered.total_ticks,
        "clock": clock_report(score),
        "channels": channel_descriptors(score, lowered),
        "pattern_instances": len(lowered.pattern_instances),
        "expanded_note_events": len(lowered.spans),
        "required_features": required_features(score, lowered),
        "event_digest": dict(lowered.event_digest),
        "source_sha256": score.source_sha256,
    }


def serialize_review(payload: dict) -> bytes:
    return (json.dumps(payload, indent=2, ensure_ascii=True) + "\n").encode("utf-8")
