"""Deterministic compact FX stream backend — ATMlib2FX-3ii.3 / ATMlib2FX-hlh.12.

Serializes a validated v1 authoring score into the **pinned compact stream**
selected by ``ATMlib2FX-hlh.6`` (``research/fx/fx-architecture-decision.md``,
section "hlh.6 review") and its global-loop extension ``ATMlib2FX-hlh.8``.  This
is an offline host adapter only: it emits deterministic bytes plus packing
metadata, never runtime code, and adds no parser or state to the device.

Pinned framing (little-endian, one byte per integer)::

    finite stream (0xC0)::
        byte 0    0xC0  version header (skipped by the decoder)
        records until END
        0x00           END (a single length byte)

    loop stream (0xC1, ATMlib2FX-hlh.8)::
        byte 0    0xC1  loop header
        u24 LE    loop_start_rel   byte offset of the first loop-region record
        records until END          (same record framing as finite)
        0x00           END is the loop boundary, not a stop

    record::
        <len> <gap> <bitmap> <groups>
        <gap>    finite: effect-only idle ticks (next_tick - tick - 1)
                 loop:   tick delta to the next pass (0 = same-tick extra pass)
        <bitmap> finite: bits 0..3 = channels with commands this pass (1..15)
                 loop:   bits 0..3 command channels, bits 4..7 restart mask;
                         bitmap == 0 is an effect-only pass
        <groups> per set channel in order 0..3: <glen> then <glen> command bytes

Gap varint: ``<=0x7F`` one byte; ``<=0x7EFF`` two bytes (``0x80|hi7``, ``lo8``);
otherwise three bytes (``0xFF``, ``hi8``, ``lo8``); maximum 65535.

Command bytes keep the original ATMlib encoding (``src/atm_cmd_constants.h``) and
the compact decoder applies them with the same ``apply_cmd`` the PROGMEM stream
uses.  The adapter reuses ``progmem_backend.encode_op`` as the authoritative
encoder, so an effect/command byte is never invented here.  Traversal commands
(``CALL``/repeats/``SET_LOOP_PATTERN``) are resolved offline and never appear.

Admission policy:

* **Effects and live commands are supported** (``ATMlib2FX-3ii.14.4`` revision).
  Every family lowering emits (arpeggio, note_cut, lfo, slide, glissando,
  noise_retrig and set/add tempo, set/add transposition, set_volume, set_mod,
  cue) encodes to a compact record with the correct per-channel mask.  The
  decoder parses the same command bytecode as PROGMEM, so a family is admitted
  exactly when ``progmem_backend.encode_op`` can encode it.
* **Global loops are exported** with the pinned ``0xC1`` framing when the whole
  loop region fits the admission ring.  The adapter works from lowered
  ``DeviceOp`` streams, so a loop region is the arrangement once, prefixed by
  the all-stopped restart protocol: the terminal STOP record carries the
  per-record restart mask (bits 4..7) and the re-arm pass (the arrangement's
  tick-0 commands for the looping channels) repeats the original's immediate
  same-tick second pass, including the effect-only pass when that tick has no
  note/volume ops.
* **Streaming loops (ATMlib2FX-hlh.16).**  With the target-capability switch
  ``streaming_loops=True`` (CLI ``--streaming-loops``) a loop region larger than
  the ring (but no larger than ``LOOP_REGION_MAX`` bytes) is still exported with
  the same ``0xC1`` framing: the device decoder streams the region through the
  ring, the foreground re-fetching it from FX at the wrap so the timer never
  sees END.  The switch is off by default; a firmware without the streaming
  decoder cleanly rejects such a stream (never garbles it), so the fallback is
  only produced when the capability is not requested.
* **Resident loops by default.**  Without the switch, a region larger than the
  ring falls back to the finite ``0xC0`` stream (the arrangement once) and
  reports ``LOOP_NOT_EXPORTED`` with the measured region size and ring, so
  nothing is silently truncated.  The ring is configurable (``--ring`` / the
  ``ring`` argument, default 32, power of two, max 256) for scores that exceed
  the default but still fit a larger ring.
* **Limits.**  Each record must fit the ring; the gap varint is capped at 65535;
  the controlled foreground service window is preflighted exactly as finite v1.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

from .lower import (
    COMMAND_OP_NAMES,
    EFFECT_OP_NAMES,
    Lowered,
    build_review_payload,
    clock_report,
    serialize_review,
    validate_summary,
)
from .progmem_backend import encode_op as _progmem_encode_op
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
FORMAT_MAGIC_LOOP = 0xC1
LOOP_HEADER = 4  # magic + u24 little-endian loop_start_rel
END_BYTE = 0x00
CHANNEL_COUNT = 4

# The runtime contract (src/atm_fx_compact.h): 32-byte ring, 16-byte fetch.
RING_CAPACITY = 32
FETCH_CHUNK = 16
MIN_RECORD_LEN = 5
MIN_LOOP_RECORD_LEN = 3
MIN_RING = 5
MAX_RING = 256
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

# Traversal ops resolving them offline keeps out of the emitted stream.
_TRAVERSAL_OPS = frozenset({"call", "call_repeat", "loop", "pattern_end", "return"})

# The decoder build flag that gates the loop extension (src/atm_fx_compact.h).
LOOP_BUILD_FLAG = "ATM_FX_COMPACT_LOOP=1"

# Largest loop region the streaming decoder accepts (src/atm_fx_compact.h
# ATM_FX_COMPACT_LOOP_MAX_REGION): a region above this is a clean rejection.
LOOP_REGION_MAX = 0xFFFF

# Ring-overflow diagnostics.
LOOP_NOT_EXPORTED = "LOOP_NOT_EXPORTED"
LOOP_CYCLE_INVALID = "LOOP_CYCLE_INVALID"


class FxAdmissionError(ScoreError):
    """Inadmissible content; carries a source-pointed diagnostic."""

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


def _param(op, name):
    """Fetch one typed operand from an op's ordered ``params`` payload."""
    for key, value in op.params:
        if key == name:
            return value
    raise ScoreError(f"device op {op.op!r} is missing operand {name!r}")


def _op_bytes(op) -> list[int]:
    """Encode one typed device op exactly as the original ATMlib encoding.

    Note, rest, mute, tempo, volume and modulation keep the adapter's explicit
    bytes; every effect/command op defers to ``progmem_backend.encode_op`` (the
    authoritative per-op encoder), so the compact decoder sees exactly the
    bytecode the PROGMEM backend emits for the same op.
    """
    if op.op == "set_tempo":
        return [ATM_CMD_1P_SET_TEMPO, op.tick_rate]
    if op.op == "set_volume":
        if getattr(op, "volume", None) is not None:
            return [ATM_CMD_1P_SET_VOLUME, op.volume]
        return [ATM_CMD_1P_SET_VOLUME, _param(op, "value")]
    if op.op == "set_mod":
        if getattr(op, "duty", None) is not None:
            return [ATM_CMD_1P_SET_MOD, op.duty]
        return [ATM_CMD_1P_SET_MOD, _param(op, "value")]
    if op.op == "note":
        return [op.note_index]
    if op.op == "mute":
        return [ATM_CMD_1P_SET_VOLUME, 0x00]
    if op.op in EFFECT_OP_NAMES or op.op in COMMAND_OP_NAMES:
        try:
            return list(_progmem_encode_op(op))
        except ScoreError as exc:
            raise FxAdmissionError(
                "CAPABILITY_UNSUPPORTED",
                getattr(op, "source", ""),
                f"device op {op.op!r} is not encodable in the compact stream: {exc}",
                "Check the effect/command operands or the PROGMEM backend.",
            )
    raise FxAdmissionError(
        "CAPABILITY_UNSUPPORTED",
        getattr(op, "source", ""),
        f"device op {op.op!r} is not part of the compact music stream.",
        "Use notes, rests, pulse duty, instruments, effects or live commands.",
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
    gap: int = 0  # to the next pass (finite: idle-1; loop: tick delta)
    restart: int = 0  # loop mode: bits 4..7 of the record bitmap

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


def _arrangement_passes(score: Score, lowered: Lowered) -> list[_Pass]:
    """One pass per tick that carries channel commands (gaps unset)."""
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
    return passes


def _collect_passes(score: Score, lowered: Lowered) -> list[_Pass]:
    """Finite-v1 passes with ``gap = next_tick - tick - 1``."""
    passes = _arrangement_passes(score, lowered)
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


def _validate_ring(ring: int) -> None:
    if ring < MIN_RING or ring > MAX_RING:
        raise FxAdmissionError(
            "LIMIT_EXCEEDED",
            "",
            f"ring must be in [{MIN_RING}, {MAX_RING}] bytes, got {ring}.",
            "Use a power-of-two ring between 5 and 256 (the decoder build cap).",
        )


def _admission(
    score: Score,
    lowered: Lowered,
    passes: list[_Pass],
    total_ticks: int,
    ring: int,
) -> tuple[list[Diagnostic], dict]:
    diagnostics: list[Diagnostic] = []

    # Reject any unsupported op / SFX / traversal that may reach this adapter.
    for _channel, ops in lowered.ops.items():
        for op in ops:
            if op.op in _TRAVERSAL_OPS:  # pragma: no cover - defensive
                raise FxAdmissionError(
                    "CAPABILITY_UNSUPPORTED",
                    op.source,
                    f"traversal op {op.op!r} must be resolved offline.",
                    "Use finite pattern repeats; loops are the 0xC1 extension.",
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
        if p.record_len > ring:
            offender = max(p.groups, key=lambda g: len(g[1]))
            raise FxAdmissionError(
                "DUE_GROUP_TOO_LARGE",
                offender[2],
                (
                    f"pass at tick {p.tick} is {p.record_len} bytes, larger than "
                    f"the {ring}-byte ring."
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
    if window.get(1, 0) > ring:
        raise FxAdmissionError(
            "DUE_GROUP_TOO_LARGE",
            _widest_source(passes),
            (
                f"largest pass record is {window[1]} bytes, larger than the "
                f"{ring}-byte ring."
            ),
            "Split the event or build with a larger ring.",
        )
    if required_window > ring:
        raise FxAdmissionError(
            "DUE_GROUP_TOO_LARGE",
            "/clock/tick_rate",
            (
                f"at tick_rate {score.clock.tick_rate} the worst "
                f"{service_ticks}-tick service window is {required_window} bytes, "
                f"larger than the {ring}-byte ring."
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


def _build_loop(score: Score, lowered: Lowered):
    """Build the pinned 0xC1 loop extent from the lowered ops, or None.

    Returns ``(intro, loop_passes, loop_start_rel, region_bytes, cycle_ticks)``.
    ``intro`` is the arrangement played once (ticks ``< cycle``); ``loop_passes``
    is the pinned, replayed region: the terminal STOP record (restart mask) and
    the re-arm pass, then the arrangement's later passes.  Returns ``None`` when
    the score has no representable cycle (no tracks or a zero-time cycle).
    """
    if not score.tracks:
        return None
    total = lowered.total_ticks
    if total <= 0:
        return None
    tracked = [index for index, name in enumerate(CHANNEL_NAMES) if name in score.tracks]
    if not tracked:
        return None
    tracked_set = set(tracked)
    restart_mask = 0
    for index in tracked:
        restart_mask |= 1 << index

    arrangement = _arrangement_passes(score, lowered)
    intro = [p for p in arrangement if p.tick < total]
    terminal = [p for p in arrangement if p.tick == total]
    if len(terminal) != 1:
        return None
    terminal = terminal[0]
    terminal.restart = restart_mask

    tick0 = next((p for p in intro if p.tick == 0), None)
    rearm_groups = (
        [(idx, body, src) for (idx, body, src) in tick0.groups if idx in tracked_set]
        if tick0 is not None
        else []
    )
    rearm_bitmap = 0
    for idx, _body, _src in rearm_groups:
        rearm_bitmap |= 1 << idx
    rearm = _Pass(tick=total, bitmap=rearm_bitmap, groups=rearm_groups)

    copies = [
        _Pass(tick=total + p.tick, bitmap=p.bitmap, groups=list(p.groups))
        for p in intro
        if p.tick > 0
    ]
    loop_passes = [terminal, rearm] + copies

    # Cyclic gaps: a loop-mode gap is the tick delta to the next pass; the last
    # record wraps to the terminal STOP of the next cycle.
    for index, p in enumerate(loop_passes):
        nxt = loop_passes[index + 1].tick if index + 1 < len(loop_passes) else loop_passes[0].tick + total
        delta = nxt - p.tick
        if delta < 0:
            return None
        p.gap = delta
    for index, p in enumerate(intro):
        nxt = intro[index + 1].tick if index + 1 < len(intro) else loop_passes[0].tick
        p.gap = nxt - p.tick

    region_bytes = sum(p.record_len for p in loop_passes)
    intro_bytes = sum(p.record_len for p in intro)
    loop_start_rel = LOOP_HEADER + intro_bytes
    return intro, loop_passes, loop_start_rel, region_bytes, total


def _same_tick_chain_max(passes: list[_Pass]) -> int:
    """Worst sum of consecutive same-tick records (loop gap 0 chains).

    A loop record with gap 0 is applied on the same callback as the previous
    one, so the whole chain must be resident at once: when the region streams,
    a chain longer than the ring would underrun mid-tick.
    """
    best = 0
    run = 0
    for p in passes:
        run += p.record_len
        if run > best:
            best = run
        if p.gap != 0:
            run = 0
    return best


def _cyclic_same_tick_chain_max(passes: list[_Pass]) -> int:
    """``_same_tick_chain_max`` over the loop region's cyclic pass sequence."""
    n = len(passes)
    if n == 0:
        return 0
    best = 0
    run = 0
    for k in range(2 * n):  # doubled scan resolves a chain across the wrap
        p = passes[k % n]
        run += p.record_len
        if run > best:
            best = run
        if p.gap != 0:
            run = 0
    return best


def _loop_admission(
    score: Score,
    lowered: Lowered,
    intro: list[_Pass],
    loop_passes: list[_Pass],
    region_bytes: int,
    ring: int,
) -> tuple[list[Diagnostic], dict]:
    """Preflight the loop stream before serialization (record + region bounds)."""
    all_passes = intro + loop_passes
    max_record = 0
    max_group = 0
    for p in all_passes:
        if p.record_len > ring:
            raise FxAdmissionError(
                "DUE_GROUP_TOO_LARGE",
                (p.groups[0][2] if p.groups else "/loop"),
                (
                    f"loop record at tick {p.tick} is {p.record_len} bytes, larger "
                    f"than the {ring}-byte ring."
                ),
                "Split the event or build with a larger ring.",
            )
        max_record = max(max_record, p.record_len)
        max_group = max(max_group, p.payload_bytes)
        if p.gap > GAP_VARINT_MAX:
            raise FxAdmissionError(
                "LIMIT_EXCEEDED",
                (p.groups[0][2] if p.groups else "/loop"),
                f"loop gap of {p.gap} ticks exceeds the {GAP_VARINT_MAX}-tick varint maximum.",
                "Add an event before the next pass or lower the tick rate.",
            )

    # A same-tick chain (gap 0) is consumed on one callback and must be resident
    # at once in both the pinned and the streaming path.
    chain = max(_same_tick_chain_max(intro), _cyclic_same_tick_chain_max(loop_passes))
    if chain > ring:
        raise FxAdmissionError(
            "DUE_GROUP_TOO_LARGE",
            "/loop",
            (
                f"the loop's worst same-tick pass chain is {chain} bytes, larger "
                f"than the {ring}-byte ring."
            ),
            "Split the same-tick events or build with a larger ring.",
        )

    # The intro is streamed; the same foreground service-window preflight the
    # finite path applies must hold while it is consumed.
    window = _window_table(intro, lowered.total_ticks)
    service_ticks = _service_ticks(score)
    required_window = window[min(service_ticks, max(window))] if window else 0
    if required_window > ring:
        raise FxAdmissionError(
            "DUE_GROUP_TOO_LARGE",
            "/clock/tick_rate",
            (
                f"at tick_rate {score.clock.tick_rate} the worst "
                f"{service_ticks}-tick service window is {required_window} bytes, "
                f"larger than the {ring}-byte ring."
            ),
            "Lower tick_rate, split events, or build with a larger ring.",
        )

    metrics = {
        "max_record": max_record,
        "max_group": max_group,
        "window_bytes": {str(k): v for k, v in sorted(window.items())},
        "service_ticks": service_ticks,
        "required_window_bytes": required_window,
        "loop_region_bytes": region_bytes,
        "loop_ring": ring,
    }
    return [], metrics


def _write_record(out: bytearray, p: _Pass, loop_mode: bool) -> None:
    out.append(p.record_len)
    out.extend(_gap_bytes(p.gap))
    bitmap = p.bitmap & 0x0F
    if loop_mode:
        bitmap |= (p.restart & 0x0F) << 4
    out.append(bitmap)
    for _ch, body, _src in p.groups:
        out.append(len(body))
        out.extend(body)


def _serialize_finite(passes: list[_Pass]) -> bytes:
    out = bytearray()
    out.append(FORMAT_MAGIC)
    for p in passes:
        _write_record(out, p, loop_mode=False)
    out.append(END_BYTE)
    return bytes(out)


def _serialize_loop(intro: list[_Pass], loop_passes: list[_Pass], loop_start_rel: int) -> bytes:
    out = bytearray()
    out.append(FORMAT_MAGIC_LOOP)
    out.extend(
        [
            loop_start_rel & 0xFF,
            (loop_start_rel >> 8) & 0xFF,
            (loop_start_rel >> 16) & 0xFF,
        ]
    )
    for p in intro:
        _write_record(out, p, loop_mode=True)
    for p in loop_passes:
        _write_record(out, p, loop_mode=True)
    out.append(END_BYTE)
    return bytes(out)


def _loop_fallback_diagnostic(
    region_bytes: int, ring: int, total: int, streaming_available: bool = False
) -> Diagnostic:
    suggestion = (
        "Build with a larger --ring (power of two, max 256) if the cycle fits, "
        "or shorten the loop / export the finite arrangement."
    )
    if streaming_available:
        suggestion = (
            "Build with --streaming-loops for a decoder that streams the region "
            "through the ring (firmware gated by ATM_FX_COMPACT_LOOP), build with "
            "a larger --ring if the cycle fits, or export the finite arrangement."
        )
    return Diagnostic(
        LOOP_NOT_EXPORTED,
        "/loop",
        (
            f"the loop region is {region_bytes} bytes, larger than the {ring}-byte "
            f"ring; the device pins and replays the whole region, so a resident "
            f"loop is not representable. The finite 0xC0 arrangement is exported "
            f"once and stops at its end."
        ),
        suggestion,
        severity="warning",
    )


def serialize_compact(
    score: Score,
    lowered: Lowered,
    ring: int = RING_CAPACITY,
    streaming_loops: bool = False,
) -> tuple[bytes, dict, list[Diagnostic]]:
    """Build the pinned byte stream plus packing metadata.

    ``streaming_loops`` is the target-capability switch (ATMlib2FX-hlh.16): when
    true, a loop region up to ``LOOP_REGION_MAX`` bytes is exported for a
    decoder that streams it through the ring (the device re-fetches the region
    at the wrap). It is off by default so the finite fallback and its byte
    stability are unchanged.
    """
    _validate_ring(ring)
    diagnostics: list[Diagnostic] = []

    loop_exported = False
    loop_streaming = False
    loop_meta: dict = {}
    if score.loop:
        built = _build_loop(score, lowered)
        if built is None:
            raise FxAdmissionError(
                LOOP_CYCLE_INVALID,
                "/loop",
                "the loop has no representable cycle (no tracks or a zero-time cycle).",
                "Add at least one track/event, or set \"loop\": false.",
            )
        intro, loop_passes, loop_start_rel, region_bytes, cycle_ticks = built
        if region_bytes <= ring:
            _diag, metrics = _loop_admission(
                score, lowered, intro, loop_passes, region_bytes, ring
            )
            stream = _serialize_loop(intro, loop_passes, loop_start_rel)
            loop_exported = True
            passes_count = len(loop_passes)
            payload_total = sum(p.payload_bytes for p in loop_passes)
            framing_total = sum(p.record_len for p in loop_passes)
        elif streaming_loops:
            if region_bytes > LOOP_REGION_MAX:
                raise FxAdmissionError(
                    "LIMIT_EXCEEDED",
                    "/loop",
                    (
                        f"the loop region is {region_bytes} bytes, larger than the "
                        f"{LOOP_REGION_MAX}-byte streaming bound; the decoder cannot "
                        f"track a larger streamed region."
                    ),
                    "Shorten the arrangement or export the finite 0xC0 stream.",
                )
            _diag, metrics = _loop_admission(
                score, lowered, intro, loop_passes, region_bytes, ring
            )
            stream = _serialize_loop(intro, loop_passes, loop_start_rel)
            loop_exported = True
            loop_streaming = True
            passes_count = len(loop_passes)
            payload_total = sum(p.payload_bytes for p in loop_passes)
            framing_total = sum(p.record_len for p in loop_passes)
        else:
            diagnostics.append(
                _loop_fallback_diagnostic(
                    region_bytes, ring, lowered.total_ticks, streaming_available=True
                )
            )

        if loop_exported:
            loop_meta = {
                "loop_start_rel": loop_start_rel,
                "loop_region_bytes": region_bytes,
                "loop_cycle_ticks": cycle_ticks,
                "intro_bytes": loop_start_rel - LOOP_HEADER,
                "loop_passes": len(loop_passes),
                "intro_passes": len(intro),
                "restart_mask": loop_passes[0].restart if loop_passes else 0,
                "loop_streaming": loop_streaming,
            }

    if not loop_exported:
        passes = _collect_passes(score, lowered)
        _diag, metrics = _admission(score, lowered, passes, lowered.total_ticks, ring)
        stream = _serialize_finite(passes)
        passes_count = len(passes)
        payload_total = sum(p.payload_bytes for p in passes)
        framing_total = sum(p.record_len for p in passes)

    metadata = {
        "stream_bytes": len(stream),
        "ticks": lowered.total_ticks,
        "passes": passes_count,
        "payload_bytes": payload_total,
        "framing_bytes": framing_total,
        "max_group_bytes": metrics["max_group"],
        "max_record_bytes": metrics["max_record"],
        "window_bytes": metrics["window_bytes"],
        "service_ticks": metrics["service_ticks"],
        "required_window_bytes": metrics["required_window_bytes"],
        "ring_capacity": ring,
        "fetch_chunk": FETCH_CHUNK,
        "loop_exported": loop_exported,
        "loop_streaming": loop_streaming,
        "streaming_loops_requested": bool(streaming_loops),
        "magic": stream[0],
        "sha256": hashlib.sha256(stream).hexdigest(),
    }
    metadata.update(loop_meta)
    return stream, metadata, diagnostics


def render_header(score: Score, stream_bytes: bytes) -> bytes:
    digest = hashlib.sha256(stream_bytes).hexdigest()
    magic = stream_bytes[0] if stream_bytes else FORMAT_MAGIC
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
        f"#define FX_STREAM_MAGIC 0x{magic:02x}u",
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
            "magic": stream_bytes[0] if stream_bytes else FORMAT_MAGIC,
            "ring_capacity": metadata.get("ring_capacity", RING_CAPACITY),
            "fetch_chunk": FETCH_CHUNK,
            "selected_by": "ATMlib2FX-hlh.6",
            "loop_extension": "ATMlib2FX-hlh.8",
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
        "loop_exported": bool(metadata.get("loop_exported", False)),
        "capabilities": {
            "finite_v1": True,
            "loops": True,
            "loops_require_build_flag": LOOP_BUILD_FLAG,
            "streaming_loops": bool(metadata.get("streaming_loops_requested", False)),
            "streaming_loops_region_max": LOOP_REGION_MAX,
            "effects": True,
            "commands": True,
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
            "packing metadata (max group/record, service window, loop region) is "
            "asset-shaped, not a device stack/flash measurement."
        ),
        "avr_measurements": {
            "measured": False,
            "reason": (
                "This build command does not invoke arduino-cli or the absim "
                "runner. Device FX-address, ring-wrap and service-gap stress is "
                "recorded separately under build/."
            ),
        },
    }


def serialize(
    score: Score,
    lowered: Lowered,
    out_dir: str,
    ring: int = RING_CAPACITY,
    streaming_loops: bool = False,
) -> BuildResult:
    stream_bytes, metadata, diagnostics = serialize_compact(
        score, lowered, ring=ring, streaming_loops=streaming_loops
    )
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


def build(
    score: Score,
    lowered: Lowered,
    out_dir: str,
    ring: int = RING_CAPACITY,
    streaming_loops: bool = False,
) -> tuple[BuildResult, dict]:
    result = serialize(
        score, lowered, out_dir, ring=ring, streaming_loops=streaming_loops
    )
    artifacts = write_outputs(out_dir, result)
    return result, artifacts


def diagnostics_for(exc: Exception) -> list[Diagnostic]:
    if isinstance(exc, FxAdmissionError):
        return [exc.diagnostic]
    return []
