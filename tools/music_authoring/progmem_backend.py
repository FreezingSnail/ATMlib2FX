"""Deterministic original PROGMEM (``ATM_SCORE_FMT_FULL``) backend."""

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
)

BACKEND_NAME = "progmem"
BACKEND_VERSION = "1"
SCORE_FORMAT_NAME = "ATM_SCORE_FMT_FULL"
SCORE_FORMAT_BYTE = 0x03
CHANNEL_COUNT = 4

# src/atm_cmd_constants.h values (explicit, never a host struct dump).
ATM_CMD_I_PATTERN_END = 0x61
ATM_CMD_P_SET_LOOP_PATTERN = 0x80
ATM_CMD_1P_SET_TEMPO = 0x72
ATM_CMD_1P_SET_VOLUME = 0x74
ATM_CMD_1P_SET_MOD = 0x76
ATM_CMD_P_U8_DELAY = 0x85
ATM_CMD_P_U16_DELAY = 0x95
DELAY_1_TICK = 64

MAX_U16_OFFSET = 0xFFFF
MAX_PATTERN_COUNT = 0xFF


class BackendLimit(ScoreError):
    """A backend-specific encoding limit was exceeded."""


def encode_delay(ticks: int) -> list[int]:
    """Encode one music delay exactly as ``ATM_CMD_M_DELAY_TICKS*`` does."""
    if ticks < 1:
        raise ValueError("delay must be positive")
    if ticks <= 32:
        return [DELAY_1_TICK + (ticks - 1)]
    if ticks <= 256:
        return [ATM_CMD_P_U8_DELAY, (ticks - 1) & 0xFF]
    if ticks <= 65535:
        value = ticks - 1
        return [ATM_CMD_P_U16_DELAY, (value >> 8) & 0xFF, value & 0xFF]
    raise ValueError("single delay must not exceed 65535 ticks")


def encode_delay_chunks(ticks: int) -> list[int]:
    """Split a long delay into the largest legal PROGMEM delay commands."""
    if ticks < 0:
        raise ValueError("delay must be nonnegative")
    out: list[int] = []
    remaining = ticks
    while remaining > 65535:
        out.extend(encode_delay(65535))
        remaining -= 65535
    if remaining:
        out.extend(encode_delay(remaining))
    return out


def encode_op(op) -> list[int]:
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
    raise ScoreError(f"unknown device op {op.op!r}")


def encode_program(channel: str, ops, track_ticks: int | None, tick_rate: int) -> bytes:
    """Encode one channel program, including padding and explicit STOP."""
    out: list[int] = []
    cursor = 0
    for op in ops:
        gap = op.tick - cursor
        if gap < 0:
            raise ScoreError("device ops are not ordered by tick")
        if gap:
            out.extend(encode_delay_chunks(gap))
            cursor = op.tick
        out.extend(encode_op(op))
    if track_ticks is not None:
        gap = track_ticks - cursor
        if gap < 0:
            raise ScoreError("program has ops past the track length")
        if gap:
            out.extend(encode_delay_chunks(gap))
    out.append(ATM_CMD_I_PATTERN_END)
    return bytes(out)


@dataclass(frozen=True)
class BuildResult:
    score_bytes: bytes
    header_bytes: bytes
    review_bytes: bytes
    report: dict
    report_bytes: bytes
    programs: tuple[bytes, ...]
    entries: tuple[int, ...]

    @property
    def score_sha256(self) -> str:
        return hashlib.sha256(self.score_bytes).hexdigest()


def _pattern_entries(score: Score, lowered: Lowered) -> tuple[list[bytes], list[int]]:
    if score.loop:
        # Keep pattern zero as a silent STOP. Each participating channel loops
        # to its own entry; the engine restarts them together in the same tick
        # once all reach STOP. Pad shorter tracks to the whole cycle length.
        programs = [bytes([ATM_CMD_I_PATTERN_END])]
        if "pulse0" not in score.tracks:
            programs[0] = bytes([ATM_CMD_1P_SET_TEMPO, score.clock.tick_rate, ATM_CMD_I_PATTERN_END])
        entries = []
        for channel in CHANNEL_NAMES:
            if channel not in score.tracks:
                entries.append(0)
                continue
            entry = len(programs)
            program = bytes([ATM_CMD_P_SET_LOOP_PATTERN, entry]) + encode_program(
                channel, lowered.ops_for_channel(channel), lowered.total_ticks, score.clock.tick_rate
            )
            programs.append(program)
            entries.append(entry)
        return programs, entries
    programs: list[bytes] = []
    entries: list[int] = []
    index_by_bytes: dict[bytes, int] = {}
    for index, channel in enumerate(CHANNEL_NAMES):
        if channel in score.tracks:
            target = lowered.track_ticks[channel]
            program = encode_program(
                channel,
                lowered.ops_for_channel(channel),
                target,
                score.clock.tick_rate,
            )
        else:
            program = encode_program(channel, (), None, score.clock.tick_rate)
            if index == 0:
                program = bytes([ATM_CMD_1P_SET_TEMPO, score.clock.tick_rate, ATM_CMD_I_PATTERN_END])
        if program not in index_by_bytes:
            index_by_bytes[program] = len(programs)
            programs.append(program)
        entries.append(index_by_bytes[program])
    return programs, entries


def serialize_score(score: Score, lowered: Lowered) -> tuple[bytes, tuple[bytes, ...], tuple[int, ...]]:
    """Build the explicit ``ATM_SCORE_FMT_FULL`` byte layout."""
    programs, entries = _pattern_entries(score, lowered)
    if len(programs) > MAX_PATTERN_COUNT:
        raise BackendLimit("pattern table exceeds the uint8 pattern count")
    header_size = 1 + 1 + 2 * len(programs) + 1 + CHANNEL_COUNT
    offsets: list[int] = []
    cursor = header_size
    for program in programs:
        offsets.append(cursor)
        cursor += len(program)
    if cursor > MAX_U16_OFFSET:
        raise BackendLimit(
            f"PROGMEM score would be {cursor} bytes; the full-format offset table is uint16"
        )
    data = bytearray()
    data.append(SCORE_FORMAT_BYTE)
    data.append(len(programs))
    for offset in offsets:
        # get_track_start_ptr reads these with pgm_read_word (little-endian).
        data.append(offset & 0xFF)
        data.append((offset >> 8) & 0xFF)
    data.append(CHANNEL_COUNT)
    data.extend(entries)
    for program in programs:
        data.extend(program)
    return bytes(data), tuple(programs), tuple(entries)


def render_header(score: Score, score_bytes: bytes, pattern_count: int) -> bytes:
    digest = hashlib.sha256(score_bytes).hexdigest()
    lines = [
        "/* Generated by tools/atm-music (atm-music 1.0.0). Do not edit. */",
        "/* Backend: progmem / ATM_SCORE_FMT_FULL. */",
        "#ifndef ATMLIB_SCORE_H",
        "#define ATMLIB_SCORE_H",
        "",
        "#include <stdint.h>",
        "#include <avr/pgmspace.h>",
        "",
        f'#define SCORE_ID "{score.id}"',
        f"#define SCORE_BYTES {len(score_bytes)}u",
        f"#define SCORE_PATTERNS {pattern_count}u",
        f'#define SCORE_SHA256 "{digest}"',
        "",
        "const uint8_t score[] PROGMEM = {",
    ]
    per_line = 12
    for start in range(0, len(score_bytes), per_line):
        chunk = score_bytes[start : start + per_line]
        rendered = ", ".join(f"0x{byte:02x}" for byte in chunk)
        suffix = "," if start + per_line < len(score_bytes) else ""
        lines.append(f"    {rendered}{suffix}")
    lines.extend(["};", "", "#endif /* ATMLIB_SCORE_H */", ""])
    return "\n".join(lines).encode("utf-8")


def build_report(
    score: Score,
    lowered: Lowered,
    score_bytes: bytes,
    programs: tuple[bytes, ...],
    entries: tuple[int, ...],
    out_dir: str,
) -> dict:
    digest = hashlib.sha256(score_bytes).hexdigest()
    summary = validate_summary(score, lowered)
    return {
        "tool": {"name": TOOL_NAME, "version": TOOL_VERSION},
        "schema_version": SCHEMA_VERSION,
        "backend": {
            "name": BACKEND_NAME,
            "version": BACKEND_VERSION,
            "format": SCORE_FORMAT_NAME,
            "format_byte": SCORE_FORMAT_BYTE,
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
        "score": {
            "file": "score.bin",
            "bytes": len(score_bytes),
            "sha256": digest,
            "patterns": len(programs),
            "program_bytes": [len(program) for program in programs],
            "channel_pattern_entries": list(entries),
        },
        "artifacts": {
            "score_bin": os.path.join(out_dir, "score.bin"),
            "score_h": os.path.join(out_dir, "score.h"),
            "review_json": os.path.join(out_dir, "review.json"),
            "report_json": os.path.join(out_dir, "report.json"),
        },
        "host_limits": dict(HOST_LIMITS),
        "resource_note": (
            "score.bin is PROGMEM song asset data only. It is not engine code, "
            "not static SRAM and not a whole-game memory measurement."
        ),
        "avr_measurements": {
            "measured": False,
            "reason": (
                "This build command does not invoke arduino-cli. The example "
                "README records separately measured AVR image and score sizes."
            ),
        },
    }


def serialize(score: Score, lowered: Lowered, out_dir: str) -> BuildResult:
    score_bytes, programs, entries = serialize_score(score, lowered)
    header_bytes = render_header(score, score_bytes, len(programs))
    payload = build_review_payload(score, lowered)
    review_bytes = serialize_review(payload)
    report = build_report(score, lowered, score_bytes, programs, entries, out_dir)
    report_bytes = (json.dumps(report, indent=2, ensure_ascii=True) + "\n").encode("utf-8")
    return BuildResult(
        score_bytes=score_bytes,
        header_bytes=header_bytes,
        review_bytes=review_bytes,
        report=report,
        report_bytes=report_bytes,
        programs=programs,
        entries=entries,
    )


def write_outputs(out_dir: str, result: BuildResult) -> dict:
    directory = Path(out_dir)
    directory.mkdir(parents=True, exist_ok=True)
    files = {
        "score.bin": result.score_bytes,
        "score.h": result.header_bytes,
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
    if isinstance(exc, BackendLimit):
        return [
            Diagnostic(
                "LIMIT_EXCEEDED",
                "",
                str(exc),
                "Shorten the song or reduce pattern/event counts for this backend.",
            )
        ]
    return []


def capability_summary() -> dict:
    from .lower import availability

    available = availability()
    return {
        "schema_version": SCHEMA_VERSION,
        "tool": {"name": TOOL_NAME, "version": TOOL_VERSION},
        "engine": {
            "name": ENGINE_NAME,
            "library_version": library_version(),
            "channels": list(CHANNEL_NAMES),
            "tick_base_hz": TICK_BASE_HZ,
        },
        "features": [
            "notes",
            "rests",
            "pulse_duty",
            "fixed_instrument_volume",
            "finite_pattern_reuse",
            "finite_arrangement",
            "whole_song_loop",
            "explicit_gate_mute",
            "canonical_review_payload",
            "progmem_export",
            "validate",
        ],
        "channels": list(CHANNEL_NAMES),
        "channel_voices": {
            "pulse0": "pulse",
            "pulse1": "pulse",
            "pulse2": "pulse",
            "noise": "noise",
        },
        "pitch_range": {
            "min": "C2",
            "max": "D7",
            "note_indices": [1, 63],
        },
        "host_limits": dict(HOST_LIMITS),
        "backends": available["backend"],
        "capabilities": available["capabilities"],
        "canonicalization": "atmlib-canonical-events-v1",
        "review_payload_version": 1,
    }
