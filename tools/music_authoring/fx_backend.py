"""Deterministic compact FX stream backend (finite v1) — ATMlib2FX-3ii.3.

Serializes a validated v1 authoring score into the **pinned compact stream**
selected by ``ATMlib2FX-hlh.6`` (``research/fx/fx-architecture-decision.md``,
section "hlh.6 review").  This is an offline host adapter only: it emits
deterministic bytes plus packing metadata, never runtime code, and adds no
parser or state to the device.

Pinned framing (little-endian, one byte per integer)::

    byte 0   0xC0  version header (skipped by the decoder)
    records until END:
      <len> <gap> <bitmap> <groups>
      <gap>    effect-only ticks until the next pass (next_tick - tick - 1)
      <bitmap> bit0..bit3 = channels with commands this pass (1..15)
      <groups> per set channel in order 0..3: <glen> then <glen> command bytes
    0x00        END (a single length byte)

Admission follows the selected contract: ``len <= ring`` (default 32 B), no
traversal commands (``CALL``/repeats/``SET_LOOP_PATTERN``), no effects, no live
commands and no SFX in finite v1.  Everything the adapter cannot represent is
rejected with a diagnostic that points at the offending source JSON Pointer (or
the instrument preset), never silently dropped.

Effect and live-command admission is explicit and per family (finite-v1 compact
adapter policy, ``ATMlib2FX-3ii.14.4``):

* The pinned contract (``ATMlib2FX-hlh.6``) advertises no live effects and no
  instantaneous commands.  The framing's ``<gap>`` field records *effect-only
  idle ticks between passes*, which is not a license to reshape, reschedule or
  silently drop an authored effect.
* A pattern that declares ``effects`` is rejected with ``FX_EFFECT_UNSUPPORTED``
  pointing at ``/patterns/<name>/effects/<index>``; a pattern that declares
  ``commands`` is rejected with ``FX_COMMAND_UNSUPPORTED`` pointing at
  ``/patterns/<name>/commands/<index>``.  Both are hard admission errors, one
  stable code per family.
* No family is admitted in this revision.  None is exactly representable
  within the pinned ring / service-window rules without changing the AVR
  decoder or the pinned framing (both out of scope here), so the adapter does
  not guess.

A runtime global loop is not representable by the finite stream (the decoder
stops at END or when every voice stops).  The adapter therefore exports the
finite arrangement exactly once and records ``LOOP_NOT_EXPORTED`` (a warning,
not a silent capability claim); ``capabilities`` never advertises loop support
for this backend.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

from .lower import (
    Lowered,
    build_review_payload,
    clock_report,
    serialize_review,
    validate_summary,
)
from .score import (
    CHANNEL_NAMES,
    ENGINE_NAME,
    HOST_LIMITS,
    SCHEMA_VERSION,
    TICK_BASE_HZ,
    TOOL_NAME,
    TOOL_VERSION,
    Diagnostic,
    Score,
    ScoreError,
    library_version,
    pointer,
)

BACKEND_NAME = "fx"
BACKEND_VERSION = "1"
FORMAT_NAME = "atm_fx_compact_v1"
FORMAT_MAGIC = 0xC0
END_BYTE = 0x00
CHANNEL_COUNT = 4

# The runtime contract (src/atm_fx_compact.h): 32-byte ring, 16-byte fetch.
RING_CAPACITY = 32
FETCH_CHUNK = 16
MIN_RECORD_LEN = 5
MAX_RECORD_LEN = RING_CAPACITY if RING_CAPACITY < 255 else 255

# Pinned gap varint maximum: effect-only ticks strictly between two passes
# (research/fx/fx-architecture-decision.md, hlh.6 contract item 1).
GAP_VARINT_MAX = 0xFFFF

# Refill deadline: at least one complete record per frame (52 fps ~ 19.23 ms).
FRAME_HZ = 52.0
FRAME_SECONDS = 1.0 / FRAME_HZ

# src/atm_cmd_constants.h values (explicit, never a host struct dump).
ATM_CMD_I_PATTERN_END = 0x61
ATM_CMD_I_STOP = ATM_CMD_I_PATTERN_END
ATM_CMD_1P_SET_TEMPO = 0x72
ATM_CMD_1P_SET_VOLUME = 0x74
ATM_CMD_1P_SET_MOD = 0x76

# Finite v1 advertises no live effects / commands / SFX / traversal.
_TRAVERSAL_OPS = frozenset({"call", "call_repeat", "loop", "pattern_end", "return"})

# Stable per-family admission codes for the additive v1 pattern surface.
# The pinned contract advertises no effects or live commands; a score that
# authors either family is rejected (never silently dropped) with one of these
# codes and the offending source JSON Pointer.
FX_EFFECT_UNSUPPORTED = "FX_EFFECT_UNSUPPORTED"
FX_COMMAND_UNSUPPORTED = "FX_COMMAND_UNSUPPORTED"


class FxAdmissionError(ScoreError):
    """Inadmissible finite-v1 content; carries a source-pointed diagnostic."""

    def __init__(self, code: str, path: str, message: str, suggestion: str):
        super().__init__(message)
        self.diagnostic = Diagnostic(code, path, message, suggestion)


@dataclass(frozen=True)
class BuildResult:
    stream_bytes: bytes
    header_bytes: bytes
    review_bytes: bytes
    report: dict
    report_bytes: bytes
    diagnostics: tuple[Diagnostic, ...] = ()

    @property
    def stream_sha256(self) -> str:
        return hashlib.sha256(self.stream_bytes).hexdigest()


def _op_bytes(op) -> list[int]:
    """Encode one typed device op exactly as the original ATMlib encoding."""
    if op.op == "set_tempo":
        return [ATM_CMD_1P_SET_TEMPO, op.tick_rate]
    if op.op == "set_volume":
        return [ATM_CMD_1P_SET_VOLUME, op.volume]
    if op.op == "set_mod":
        return [ATM_CMD_1P_SET_MOD, op.duty]
    if op.op == "note":
        return [op.note_index]
    if op.op == "mute":
        return [ATM_CMD_1P_SET_VOLUME, 0x00]
    raise FxAdmissionError(
        "CAPABILITY_UNSUPPORTED",
        getattr(op, "source", ""),
        f"device op {op.op!r} is not part of finite v1 (no effects/SFX).",
        "Use notes, rests, pulse duty and instrument volume only.",
    )


def channel_events(score: Score, lowered: Lowered, channel: str):
    """Ordered ``(tick, bytes, source)`` for one channel plus its STOP.

    The shared ``PATTERN_END`` byte doubles as the channel STOP.  It is emitted
    at ``track_ticks`` (the tick the original PROGMEM program's terminal
    ``PATTERN_END`` executes), which is how the decoder's all-inactive check
    stops at the same callback as the original engine.
    """
    events: list[tuple[int, bytes, str]] = []
    for op in lowered.ops_for_channel(channel):
        events.append((op.tick, bytes(_op_bytes(op)), op.source))
    track_ticks = lowered.track_ticks.get(channel, 0)
    if channel in score.tracks:
        stop_source = pointer("tracks", channel)
    else:
        stop_source = ""
    events.append((track_ticks, bytes([ATM_CMD_I_STOP]), stop_source))
    return events


def _gap_varint_len(gap: int) -> int:
    """Emitted gap varint length: 1 byte <=0x7F, 2 <=0x7EFF, else 3.

    The decoder consumes the actual varint bytes and requires the record's
    ``len`` byte to equal the full wire record length, so record sizes must
    count the real varint extent.  Gaps above the pinned 65535 maximum still
    measure as 3 bytes here; admission rejects them with a source-pointed
    diagnostic before any serialization.
    """
    if gap < 0:
        raise ValueError("gap must be nonnegative")
    if gap <= 0x7F:
        return 1
    if gap <= 0x7EFF:
        return 2
    return 3


def _gap_bytes(gap: int) -> bytes:
    """Bounded gap varint: 1 byte <=0x7F, 2 <=0x7EFF, else 3; max 65535."""
    if gap > GAP_VARINT_MAX:
        raise ValueError(f"gap must not exceed {GAP_VARINT_MAX}")
    varint_len = _gap_varint_len(gap)
    if varint_len == 1:
        return bytes([gap])
    if varint_len == 2:
        return bytes([0x80 | (gap >> 8), gap & 0xFF])
    return bytes([0xFF, (gap >> 8) & 0xFF, gap & 0xFF])


@dataclass
class _Pass:
    tick: int
    bitmap: int
    groups: list[tuple[int, bytes, str]]  # (channel index, payload, source)
    gap: int = 0  # effect-only ticks to the next pass (last pass: 0)

    @property
    def record_len(self) -> int:
        """Full wire record length, exactly what the ``len`` byte must say.

        The decoder starts after the ``len`` byte, consumes the actual gap
        varint and requires ``pos == len`` at the end, so ``len`` counts the
        len byte itself plus the gap varint's true extent (1-3 bytes), the
        bitmap and every group.
        """
        return (
            1
            + _gap_varint_len(self.gap)
            + 1
            + sum(1 + len(payload) for _, payload, _ in self.groups)
        )

    @property
    def payload_bytes(self) -> int:
        return sum(len(payload) for _, payload, _ in self.groups)


def _collect_passes(score: Score, lowered: Lowered) -> list[_Pass]:
    per_channel = [
        channel_events(score, lowered, name) for name in CHANNEL_NAMES
    ]
    ticks = sorted({tick for events in per_channel for (tick, _, _) in events})
    passes: list[_Pass] = []
    for tick in ticks:
        bitmap = 0
        groups: list[tuple[int, bytes, str]] = []
        for index, events in enumerate(per_channel):
            payload = b"".join(body for (t, body, _s) in events if t == tick)
            if not payload:
                continue
            source = next(s for (t, _b, s) in events if t == tick)
            bitmap |= 1 << index
            groups.append((index, payload, source))
        passes.append(_Pass(tick=tick, bitmap=bitmap, groups=groups))
    for index in range(len(passes) - 1):
        passes[index].gap = passes[index + 1].tick - passes[index].tick - 1
    return passes


def _window_table(passes: list[_Pass], total_ticks: int) -> dict[int, int]:
    """Worst bytes consumed over k consecutive music callbacks (k = 1..8).

    One music callback is one decoder tick; a pass at authoring tick ``T`` runs
    on callback ``T + 1`` (the original engine executes a tick-0 command on its
    first callback).  The decoder stops as soon as no voice is active, and the
    terminal pass stops the last track, so the END byte is never consumed on
    this stop path and is not charged; the terminal record itself is counted.
    """
    consumed = [0] * (total_ticks + 2)
    for p in passes:
        consumed[p.tick + 1] = p.record_len
    table: dict[int, int] = {}
    for k in range(1, 9):
        best = 0
        for i in range(len(consumed)):
            lo = max(0, i - k + 1)
            best = max(best, sum(consumed[lo : i + 1]))
        table[k] = best
    return table


def _service_ticks(score: Score) -> int:
    """Music ticks that can elapse between two foreground refills.

    At the authored timer interval the foreground services once per frame
    (~19.23 ms); one extra tick is added as the spike's controlled margin.
    """
    interval = score.clock.tick_interval_seconds
    if interval <= 0:
        return 1
    return int(FRAME_SECONDS / interval) + 1


def _admission(
    score: Score, lowered: Lowered, passes: list[_Pass], total_ticks: int
) -> tuple[list[Diagnostic], dict]:
    diagnostics: list[Diagnostic] = []

    if score.loop:
        diagnostics.append(
            Diagnostic(
                "LOOP_NOT_EXPORTED",
                "/loop",
                (
                    "finite v1 cannot represent a runtime global loop; the "
                    "arrangement is exported exactly once and stops at its end."
                ),
                "Set \"loop\": false for a finite FX export.",
                severity="warning",
            )
        )
    # Reject any unsupported op / SFX / traversal that may reach this adapter.
    for _channel, ops in lowered.ops.items():
        for op in ops:
            if op.op in _TRAVERSAL_OPS:  # pragma: no cover - defensive
                raise FxAdmissionError(
                    "CAPABILITY_UNSUPPORTED",
                    op.source,
                    f"traversal op {op.op!r} must be resolved offline.",
                    "Use finite pattern repeats; loops are not part of finite v1.",
                )

    max_record = 0
    max_group = 0
    for p in passes:
        if p.bitmap == 0:  # pragma: no cover - construction guarantees nonzero
            raise FxAdmissionError(
                "LIMIT_EXCEEDED",
                "",
                "a pass carries no channel commands (nonprogressing record).",
                "Report this as a tool failure.",
            )
        if p.record_len > MAX_RECORD_LEN:
            offender = max(p.groups, key=lambda g: len(g[1]))
            raise FxAdmissionError(
                "DUE_GROUP_TOO_LARGE",
                offender[2],
                (
                    f"pass at tick {p.tick} is {p.record_len} bytes, larger than "
                    f"the {RING_CAPACITY}-byte ring."
                ),
                "Split the event, lower the tick rate, or build with a larger ring.",
            )
        for _index, payload, source in p.groups:
            if len(payload) > 255:
                raise FxAdmissionError(
                    "LIMIT_EXCEEDED",
                    source,
                    f"channel group is {len(payload)} bytes (> 255).",
                    "Split the event across ticks.",
                )
        max_record = max(max_record, p.record_len)
        max_group = max(max_group, p.payload_bytes)

    # Pinned gap varint extent: effect-only ticks strictly between two passes
    # must fit 65535.  Longer intervals are inadmissible, not a host crash:
    # point at the next pass the gap would have to reach.
    for index, p in enumerate(passes):
        if index + 1 >= len(passes):
            break
        nxt = passes[index + 1]
        gap = nxt.tick - p.tick - 1
        if gap > GAP_VARINT_MAX:
            raise FxAdmissionError(
                "LIMIT_EXCEEDED",
                nxt.groups[0][2] if nxt.groups else "",
                (
                    f"gap of {gap} ticks between the pass at tick {p.tick} and "
                    f"the pass at tick {nxt.tick} exceeds the {GAP_VARINT_MAX}-tick "
                    "gap varint maximum."
                ),
                "Add an event or rest before the next pass, shorten the gate, or "
                "lower the tick rate so the interval fits the gap varint.",
            )

    window = _window_table(passes, total_ticks)
    service_ticks = _service_ticks(score)
    required_window = window[min(service_ticks, max(window))] if window else 0
    if window.get(1, 0) > RING_CAPACITY:
        raise FxAdmissionError(
            "DUE_GROUP_TOO_LARGE",
            _widest_source(passes),
            (
                f"largest pass record is {window[1]} bytes, larger than the "
                f"{RING_CAPACITY}-byte ring."
            ),
            "Split the event or build with a larger ring.",
        )
    if required_window > RING_CAPACITY:
        raise FxAdmissionError(
            "DUE_GROUP_TOO_LARGE",
            "/clock/tick_rate",
            (
                f"at tick_rate {score.clock.tick_rate} the worst "
                f"{service_ticks}-tick service window is {required_window} bytes, "
                f"larger than the {RING_CAPACITY}-byte ring."
            ),
            "Raise the tick rate interval (lower tick_rate), split events, or "
            "build with a larger ring.",
        )

    metrics = {
        "max_record": max_record,
        "max_group": max_group,
        "window_bytes": {str(k): v for k, v in sorted(window.items())},
        "service_ticks": service_ticks,
        "required_window_bytes": required_window,
    }
    return diagnostics, metrics


def _widest_source(passes: list[_Pass]) -> str:
    if not passes:
        return ""
    widest = max(passes, key=lambda p: p.record_len)
    offender = max(widest.groups, key=lambda g: len(g[1]))
    return offender[2]


def reject_effect_families(score: Score) -> None:
    """Reject pattern ``effects`` / ``commands`` before any byte is emitted.

    The finite-v1 compact stream advertises neither live effects nor
    instantaneous commands, and the framing's effect-only gap ticks are idle
    ticks, not a license to reshape an authored effect.  Every family is
    rejected with a stable, source-pointed diagnostic (one code per family), so
    an effect- or command-bearing score fails loudly instead of silently
    exporting as if the surface were absent.

    Raises:
        FxAdmissionError: ``FX_EFFECT_UNSUPPORTED`` at
            ``/patterns/<name>/effects/<index>`` or ``FX_COMMAND_UNSUPPORTED``
            at ``/patterns/<name>/commands/<index>``.
    """
    for name, pattern in score.patterns.items():
        if pattern.effects:
            window = pattern.effects[0]
            raise FxAdmissionError(
                FX_EFFECT_UNSUPPORTED,
                pointer("patterns", name, "effects", window.index),
                (
                    f"pattern {name!r} declares a {window.kind!r} effect window; "
                    "finite v1 cannot represent live effects."
                ),
                (
                    "Remove the effect window. Finite v1 encodes notes, rests, "
                    "pulse duty, fixed instrument volume and the clock only; "
                    "author the sound with note events or build with the PROGMEM "
                    "backend."
                ),
            )
        if pattern.commands:
            command = pattern.commands[0]
            raise FxAdmissionError(
                FX_COMMAND_UNSUPPORTED,
                pointer("patterns", name, "commands", command.index),
                (
                    f"pattern {name!r} declares a {command.kind!r} live command; "
                    "finite v1 cannot represent instantaneous commands."
                ),
                (
                    "Remove the live command. Finite v1 carries the score clock "
                    "only; express the change with note or instrument events or "
                    "build with the PROGMEM backend."
                ),
            )


def serialize_compact(score: Score, lowered: Lowered) -> tuple[bytes, dict, list[Diagnostic]]:
    """Build the pinned byte stream plus packing metadata."""
    reject_effect_families(score)
    passes = _collect_passes(score, lowered)
    diagnostics, metrics = _admission(score, lowered, passes, lowered.total_ticks)

    out = bytearray()
    out.append(FORMAT_MAGIC)
    payload_total = 0
    framing_total = 0
    for p in passes:
        out.append(p.record_len)
        out.extend(_gap_bytes(p.gap))
        out.append(p.bitmap)
        for _ch, body, _src in p.groups:
            out.append(len(body))
            out.extend(body)
        payload_total += p.payload_bytes
        framing_total += p.record_len
    out.append(END_BYTE)

    stream = bytes(out)
    metadata = {
        "stream_bytes": len(stream),
        "ticks": lowered.total_ticks,
        "passes": len(passes),
        "payload_bytes": payload_total,
        "framing_bytes": framing_total,
        "max_group_bytes": metrics["max_group"],
        "max_record_bytes": metrics["max_record"],
        "window_bytes": metrics["window_bytes"],
        "service_ticks": metrics["service_ticks"],
        "required_window_bytes": metrics["required_window_bytes"],
        "ring_capacity": RING_CAPACITY,
        "fetch_chunk": FETCH_CHUNK,
        "sha256": hashlib.sha256(stream).hexdigest(),
    }
    return stream, metadata, diagnostics


def render_header(score: Score, stream_bytes: bytes) -> bytes:
    digest = hashlib.sha256(stream_bytes).hexdigest()
    lines = [
        "/* Generated by tools/atm-music (atm-music 1.0.0). Do not edit. */",
        "/* Backend: fx / atm_fx_compact_v1 (finite v1; not the PROGMEM default). */",
        "#ifndef ATMLIB_FX_STREAM_H",
        "#define ATMLIB_FX_STREAM_H",
        "",
        "#include <stdint.h>",
        "",
        f'#define FX_STREAM_ID "{score.id}"',
        f"#define FX_STREAM_BYTES {len(stream_bytes)}u",
        f"#define FX_STREAM_MAGIC 0x{FORMAT_MAGIC:02x}u",
        f'#define FX_STREAM_SHA256 "{digest}"',
        "",
        "const uint8_t fx_stream[] = {",
    ]
    per_line = 12
    for start in range(0, len(stream_bytes), per_line):
        chunk = stream_bytes[start : start + per_line]
        rendered = ", ".join(f"0x{byte:02x}" for byte in chunk)
        suffix = "," if start + per_line < len(stream_bytes) else ""
        lines.append(f"    {rendered}{suffix}")
    lines.extend(["};", "", "#endif /* ATMLIB_FX_STREAM_H */", ""])
    return "\n".join(lines).encode("utf-8")


def build_report(
    score: Score,
    lowered: Lowered,
    stream_bytes: bytes,
    metadata: dict,
    out_dir: str,
    diagnostics: list[Diagnostic],
) -> dict:
    digest = hashlib.sha256(stream_bytes).hexdigest()
    summary = validate_summary(score, lowered)
    return {
        "tool": {"name": TOOL_NAME, "version": TOOL_VERSION},
        "schema_version": SCHEMA_VERSION,
        "backend": {
            "name": BACKEND_NAME,
            "version": BACKEND_VERSION,
            "format": FORMAT_NAME,
            "magic": FORMAT_MAGIC,
            "ring_capacity": RING_CAPACITY,
            "fetch_chunk": FETCH_CHUNK,
            "selected_by": "ATMlib2FX-hlh.6",
        },
        "engine": {
            "name": ENGINE_NAME,
            "library_version": library_version(),
            "channels": list(CHANNEL_NAMES),
            "tick_base_hz": TICK_BASE_HZ,
        },
        "source": {
            "path": score.source_path,
            "sha256": score.source_sha256,
            "bytes": score.source_bytes,
        },
        "clock": clock_report(score),
        "total_ticks": lowered.total_ticks,
        "event_digest": dict(lowered.event_digest),
        "pattern_instances": len(lowered.pattern_instances),
        "expanded_note_events": len(lowered.spans),
        "required_features": summary["required_features"],
        "loop_exported": False,
        "capabilities": {
            "finite_v1": True,
            "loops": False,
            "effects": False,
            "commands": False,
            "sfx": False,
            "deterministic_bytes": True,
            "packing_metadata": True,
        },
        "stream": {
            "file": "stream.bin",
            "bytes": len(stream_bytes),
            "sha256": digest,
            **{k: v for k, v in metadata.items() if k != "sha256"},
        },
        "artifacts": {
            "stream_bin": os.path.join(out_dir, "stream.bin"),
            "stream_h": os.path.join(out_dir, "stream.h"),
            "review_json": os.path.join(out_dir, "review.json"),
            "report_json": os.path.join(out_dir, "report.json"),
        },
        "diagnostics": [d.as_dict() for d in diagnostics],
        "host_limits": dict(HOST_LIMITS),
        "resource_note": (
            "stream.bin is the FX-section music asset only. It is not engine "
            "code, not static SRAM and not a whole-game memory measurement; the "
            "packing metadata (max group/record, service window) is asset-shaped, "
            "not a device stack/flash measurement."
        ),
        "avr_measurements": {
            "measured": False,
            "reason": (
                "This build command does not invoke arduino-cli or the absim "
                "runner. Device FX-address, ring-wrap and service-gap stress is "
                "recorded separately under build/music-authoring/fx/."
            ),
        },
    }


def serialize(score: Score, lowered: Lowered, out_dir: str) -> BuildResult:
    stream_bytes, metadata, diagnostics = serialize_compact(score, lowered)
    header_bytes = render_header(score, stream_bytes)
    payload = build_review_payload(score, lowered, diagnostics=diagnostics)
    review_bytes = serialize_review(payload)
    report = build_report(score, lowered, stream_bytes, metadata, out_dir, diagnostics)
    report_bytes = (json.dumps(report, indent=2, ensure_ascii=True) + "\n").encode("utf-8")
    return BuildResult(
        stream_bytes=stream_bytes,
        header_bytes=header_bytes,
        review_bytes=review_bytes,
        report=report,
        report_bytes=report_bytes,
        diagnostics=tuple(diagnostics),
    )


def write_outputs(out_dir: str, result: BuildResult) -> dict:
    directory = Path(out_dir)
    directory.mkdir(parents=True, exist_ok=True)
    files = {
        "stream.bin": result.stream_bytes,
        "stream.h": result.header_bytes,
        "review.json": result.review_bytes,
        "report.json": result.report_bytes,
    }
    for name, body in files.items():
        (directory / name).write_bytes(body)
    return {name: str(directory / name) for name in files}


def build(score: Score, lowered: Lowered, out_dir: str) -> tuple[BuildResult, dict]:
    result = serialize(score, lowered, out_dir)
    artifacts = write_outputs(out_dir, result)
    return result, artifacts


def diagnostics_for(exc: Exception) -> list[Diagnostic]:
    if isinstance(exc, FxAdmissionError):
        return [exc.diagnostic]
    return []
