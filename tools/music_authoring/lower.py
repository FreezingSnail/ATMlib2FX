"""Lower a validated score to a canonical host timeline.

The canonical event list is the single musical interpretation shared by the
PROGMEM backend, the ``review.json`` viewer payload and the event digest.  The
browser viewer task (ATMlib2FX-3ii.6) must draw this data rather than parse the
source again.

Canonicalization id: ``atmlib-canonical-events-v1``.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

from .score import (
    CHANNEL_NAMES,
    CHANNEL_VOICE,
    FX_BACKEND_REASON,
    HOST_LIMITS,
    RENDER_REASON,
    SCHEMA_VERSION,
    TICK_BASE_HZ,
    TOOL_NAME,
    TOOL_VERSION,
    VIEWER_REASON,
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


@dataclass(frozen=True)
class DeviceOp:
    """One typed playback operation before backend byte encoding."""

    op: str
    tick: int
    channel: int
    source: str
    tick_rate: int | None = None
    volume: int | None = None
    duty: int | None = None
    note: str | None = None
    note_index: int | None = None

    def canonical(self) -> dict:
        body = {"op": self.op, "channel": self.channel, "tick": self.tick}
        if self.op == "set_tempo":
            body["tick_rate"] = self.tick_rate
        elif self.op == "set_volume":
            body["volume"] = self.volume
        elif self.op == "set_mod":
            body["duty"] = self.duty
        elif self.op == "note":
            body["note"] = self.note
            body["note_index"] = self.note_index
        elif self.op != "mute":
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

    def ops_for_channel(self, channel: str) -> tuple[DeviceOp, ...]:
        return self.ops.get(channel, ())


def _append_op(ops: list[DeviceOp], op: DeviceOp) -> None:
    """Append an op, dropping a directly redundant volume/mod write."""
    if ops:
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


def lower(score: Score) -> Lowered:
    """Expand finite tracks and emit the canonical ordered device ops."""
    spans: list[NoteSpan] = []
    instances: list[PatternInstance] = []
    track_ticks: dict[str, int] = {}
    ops_by_channel: dict[str, tuple[DeviceOp, ...]] = {}
    all_ops: list[tuple[int, int, int, dict]] = []

    for channel in CHANNEL_NAMES:
        if channel not in score.tracks:
            continue
        channel_index = _channel_index(channel)
        channel_spans: list[NoteSpan] = []
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
                tick += pattern.ticks
                instance_index += 1
                if tick > HOST_LIMITS["total_ticks"]:
                    raise ScoreError("track expansion exceeded the validated host limit")
        track_ticks[channel] = tick

        channel_ops: list[DeviceOp] = []
        if channel_index == 0:
            _append_op(
                channel_ops,
                DeviceOp(
                    op="set_tempo",
                    tick=0,
                    channel=0,
                    source="/clock/tick_rate",
                    tick_rate=score.clock.tick_rate,
                ),
            )
        for span in channel_spans:
            _append_op(
                channel_ops,
                DeviceOp(
                    op="set_volume",
                    tick=span.start_tick,
                    channel=channel_index,
                    source=span.source,
                    volume=span.volume,
                ),
            )
            if CHANNEL_VOICE[channel] == "pulse":
                _append_op(
                    channel_ops,
                    DeviceOp(
                        op="set_mod",
                        tick=span.start_tick,
                        channel=channel_index,
                        source=span.source,
                        duty=span.duty,
                    ),
                )
            _append_op(
                channel_ops,
                DeviceOp(
                    op="note",
                    tick=span.start_tick,
                    channel=channel_index,
                    source=span.source,
                    note=span.note,
                    note_index=span.note_index,
                ),
            )
            _append_op(
                channel_ops,
                DeviceOp(
                    op="mute",
                    tick=span.gate_end_tick,
                    channel=channel_index,
                    source=span.source,
                ),
            )
        ops_by_channel[channel] = tuple(channel_ops)
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
    )


def availability() -> dict:
    return {
        "backend": {
            "progmem": {"available": True},
            "fx": {"available": False, "reason": FX_BACKEND_REASON},
        },
        "capabilities": {
            "inspect": {"available": False, "reason": VIEWER_REASON},
            "render": {"available": False, "reason": RENDER_REASON},
            "wav_preview": {"available": False, "reason": RENDER_REASON},
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
    if score.loop:
        features.append("whole_song_loop")
    return features


def build_review_payload(
    score: Score,
    lowered: Lowered,
    diagnostics: list[Diagnostic] | None = None,
) -> dict:
    diagnostic_dicts = [item.as_dict() for item in (diagnostics or [])]
    return {
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
        "pattern_instances": [instance.as_dict() for instance in lowered.pattern_instances],
        "event_digest": dict(lowered.event_digest),
        "diagnostics": diagnostic_dicts,
        "capabilities": availability(),
    }


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
