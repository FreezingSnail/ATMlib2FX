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
# Immediate (no operand) effect-off opcodes.  NB: ATM_CMD_I_STOP/RETURN alias
# ATM_CMD_I_PATTERN_END (=0x61) so they do not consume an enum slot; the OFF
# opcodes are therefore 0x62/0x63/0x64, not 0x63/0x64/0x65.
ATM_CMD_I_GLISSANDO_OFF = 0x62
ATM_CMD_I_ARPEGGIO_OFF = 0x63
ATM_CMD_I_NOTECUT_OFF = ATM_CMD_I_ARPEGGIO_OFF  # shared arpeggio/note-cut slot
ATM_CMD_I_NOISE_RETRIG_OFF = 0x64
# Single-byte (1P) commands: opcode + one operand.
ATM_CMD_1P_SET_TRANSPOSITION = 0x70
ATM_CMD_1P_ADD_TRANSPOSITION = 0x71
ATM_CMD_1P_SET_TEMPO = 0x72
ATM_CMD_1P_ADD_TEMPO = 0x73
ATM_CMD_1P_SET_VOLUME = 0x74
ATM_CMD_1P_NOISE_RETRIG_ON = 0x75
ATM_CMD_1P_SET_MOD = 0x76
ATM_CMD_1P_SET_CUE = 0x77
# Parametrised (NP) commands: opcode + N operands (N in bits 6:4).
ATM_CMD_P_SET_LOOP_PATTERN = 0x80
ATM_CMD_P_SLIDE_OFF = 0x81
ATM_CMD_P_GLISSANDO_ON = 0x83
ATM_CMD_P_NOTECUT_ON = 0x84
ATM_CMD_P_U8_DELAY = 0x85
ATM_CMD_P_LFO_OFF = 0x86
ATM_CMD_P_SLIDE_ON = 0x91
ATM_CMD_P_ARPEGGIO_ON = 0x94
ATM_CMD_P_U16_DELAY = 0x95
ATM_CMD_P_SLIDE_ADV_ON = 0xA1
ATM_CMD_P_LFO_ON = 0xA6
DELAY_1_TICK = 64

# Effect selector bytes (`ATM_CMD_M_SLIDE_*` / `ATM_CMD_M_*_LFO_ON` macros).
SLIDE_SELECTORS = {"volume": 0, "frequency": 1, "modulation": 2}
LFO_SELECTORS = {"tremolo": 0, "vibrato": 1, "modulation": 2}

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


def _param(op, name):
    """Fetch one typed operand from an op's ordered ``params`` payload."""
    for key, value in op.params:
        if key == name:
            return value
    raise ScoreError(f"device op {op.op!r} is missing operand {name!r}")


def _encode_arpeggio_on(op) -> list[int]:
    offsets = tuple(_param(op, "offsets"))
    period = _param(op, "period")
    repeat = bool(_param(op, "repeat"))
    if not offsets:
        raise ScoreError("arpeggio_on requires at least one offset")
    two_step = len(offsets) == 1
    # Absolute base-relative semitone intervals; each nibble is added to the
    # base note (never chained). Low nibble is unused for a two-step cycle.
    notes = (offsets[0] << 4) | (offsets[1] if not two_step else 0)
    timing = (period - 1) & 0x1F  # bits 4:0 = ticks per step minus one
    if two_step:
        timing |= 0x40  # bit 6: two-step (skip the third note)
    if not repeat:
        timing |= 0x20  # bit 5: disable automatic base re-trigger
    # Engine read order is params[0]=arpTiming then params[1]=arpNotes; the
    # public ATM_CMD_M_ARPEGGIO_ON(notes, timing) macro reverses its arguments.
    return [ATM_CMD_P_ARPEGGIO_ON, timing, notes]


def _encode_note_cut_on(op) -> list[int]:
    period = _param(op, "period")
    repeat = bool(_param(op, "repeat"))
    # arpTiming with bit 6 set (two-step); arpNotes defaults to 0xFF (nibble 15
    # = no note), so the "step" silences the channel.
    byte = ((period - 1) & 0x1F) | 0x40
    if not repeat:
        byte |= 0x20
    return [ATM_CMD_P_NOTECUT_ON, byte]


def _encode_lfo_on(op) -> list[int]:
    mode = _param(op, "mode")
    depth = _param(op, "depth")
    period = _param(op, "period")
    if mode not in LFO_SELECTORS:
        raise ScoreError(f"unknown lfo mode {mode!r}")
    # Selector lands in treviConfig bits 7:6; low 5 bits carry half period - 1.
    return [ATM_CMD_P_LFO_ON, LFO_SELECTORS[mode], depth, period // 2 - 1]


def _encode_slide_on(op) -> list[int]:
    param = _param(op, "param")
    amount = _param(op, "amount")
    every = _param(op, "every")
    if param not in SLIDE_SELECTORS:
        raise ScoreError(f"unknown slide param {param!r}")
    sel = SLIDE_SELECTORS[param]
    signed = amount & 0xFF  # engine int8, two's complement in the stream
    if every == 1:
        # Plain two-operand form: config defaults to 0 => apply every tick.
        return [ATM_CMD_P_SLIDE_ON, sel, signed]
    # Advanced three-operand form: config low 6 bits = every - 1.
    return [ATM_CMD_P_SLIDE_ADV_ON, sel, signed, every - 1]


def _encode_glissando_on(op) -> list[int]:
    period = _param(op, "period")
    direction = _param(op, "direction")
    byte = (period - 1) & 0x7F  # low 7 bits = ticks per semitone minus one
    if direction == "down":
        byte |= 0x80  # bit 7: descending
    return [ATM_CMD_P_GLISSANDO_ON, byte]


def _encode_noise_retrig_on(op) -> list[int]:
    period = _param(op, "period")
    note_index = _param(op, "note_index")
    # reConfig bits 7:2 = note index, bits 1:0 = speed; retrigger every period+1.
    return [ATM_CMD_1P_NOISE_RETRIG_ON, ((note_index << 2) | period) & 0xFF]


def encode_op(op) -> list[int]:
    name = op.op
    if name == "set_tempo":
        return [ATM_CMD_1P_SET_TEMPO, op.tick_rate]
    if name == "set_volume":
        # Instrument volume ops carry the operand in the dedicated field; a live
        # `set_volume` command carries it in `params`.
        if op.volume is not None:
            return [ATM_CMD_1P_SET_VOLUME, op.volume]
        return [ATM_CMD_1P_SET_VOLUME, _param(op, "value")]
    if name == "set_mod":
        if op.duty is not None:
            return [ATM_CMD_1P_SET_MOD, op.duty]
        return [ATM_CMD_1P_SET_MOD, _param(op, "value")]
    if name == "note":
        return [op.note_index]
    if name == "mute":
        return [ATM_CMD_1P_SET_VOLUME, 0x00]
    # --- effect window ON/OFF -------------------------------------------- #
    if name == "arpeggio_on":
        return _encode_arpeggio_on(op)
    if name == "arpeggio_off":
        return [ATM_CMD_I_ARPEGGIO_OFF]
    if name == "note_cut_on":
        return _encode_note_cut_on(op)
    if name == "lfo_on":
        return _encode_lfo_on(op)
    if name == "lfo_off":
        # P_LFO_OFF is a one-parameter opcode; the engine ignores the selector
        # (it always zeroes treviDepth), so emit 0 and keep the stream aligned.
        return [ATM_CMD_P_LFO_OFF, 0x00]
    if name == "slide_on":
        return _encode_slide_on(op)
    if name == "slide_off":
        param = _param(op, "param")
        if param not in SLIDE_SELECTORS:
            raise ScoreError(f"unknown slide param {param!r}")
        return [ATM_CMD_P_SLIDE_OFF, SLIDE_SELECTORS[param]]
    if name == "glissando_on":
        return _encode_glissando_on(op)
    if name == "glissando_off":
        return [ATM_CMD_I_GLISSANDO_OFF]
    if name == "noise_retrig_on":
        return _encode_noise_retrig_on(op)
    if name == "noise_retrig_off":
        return [ATM_CMD_I_NOISE_RETRIG_OFF]
    # --- live commands --------------------------------------------------- #
    if name == "add_tempo":
        return [ATM_CMD_1P_ADD_TEMPO, _param(op, "value") & 0xFF]
    if name == "set_transposition":
        return [ATM_CMD_1P_SET_TRANSPOSITION, _param(op, "value") & 0xFF]
    if name == "add_transposition":
        return [ATM_CMD_1P_ADD_TRANSPOSITION, _param(op, "value") & 0xFF]
    if name == "cue":
        return [ATM_CMD_1P_SET_CUE, _param(op, "value")]
    raise ScoreError(f"unknown device op {name!r}")


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
    backends = dict(available["backend"])
    # The compact FX adapter is supported for `build --backend fx` (stream
    # framing selected by ATMlib2FX-hlh.6, loop extension by ATMlib2FX-hlh.8).
    # Effects and live commands encode to the same command bytecode the compact
    # decoder parses (progmem_backend.encode_op is authoritative). Global loops
    # are exported with the pinned 0xC1 framing when the whole loop region fits
    # the ring; the decoder consumes restart masks / effect-only passes only
    # when built with ATM_FX_COMPACT_LOOP=1 (default 0), so that gating is
    # reported explicitly instead of overclaimed. SFX is never offered.
    backends["fx"] = {
        "available": True,
        "command": "build",
        "format": "atm_fx_compact_v1",
        "ring_capacity": 32,
        "ring_configurable": {"default": 32, "max": 256, "option": "--ring"},
        "finite_v1": True,
        "advertises": {
            "loops": True,
            "loops_require_build_flag": "ATM_FX_COMPACT_LOOP=1",
            "effects": True,
            "commands": True,
            "sfx": False,
        },
    }
    features = [
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
        "fx_stream_export",
        "finite_v1_fx",
        "fx_loops",
        "fx_effects",
        "fx_commands",
        "packing_metadata",
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "tool": {"name": TOOL_NAME, "version": TOOL_VERSION},
        "engine": {
            "name": ENGINE_NAME,
            "library_version": library_version(),
            "channels": list(CHANNEL_NAMES),
            "tick_base_hz": TICK_BASE_HZ,
        },
        "features": features,
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
        "backends": backends,
        "capabilities": {
            # These commands are implemented and reachable from the CLI
            # (cli.py: cmd_inspect / cmd_render). Report the real availability
            # instead of the 3ii.1-pinned "owned by" placeholders.
            "inspect": {"available": True},
            "render": {"available": True},
            "wav_preview": {"available": True},
        },
        "canonicalization": "atmlib-canonical-events-v1",
        "review_payload_version": 1,
    }
