"""Bounded faithful WAV preview for authored music (ATMlib2FX-3ii.2).

Renders a validated ``atmlib-score`` to an audible WAV by executing an
*actual* AVR image (the unmodified PROGMEM library + generated score) under the
local absim emulator core, and captures the emulator's real PCM sample stream.
No sine/MIDI/oscillator substitute is ever used.

Pipeline::

    validate -> lower -> PROGMEM header -> arduino-cli AVR image
             -> absim audio capture (real AVR execution) -> WAV + report

Design facts established from the local Ardens sources (read-only):

* ``core_state.cpu.sound_buffer`` is the emulator's audio output
  (``ardens/src/absim_sound.hpp``), int16 PCM mono.
* Sample rate is ``F_CPU / SOUND_CYCLES = 16'000'000 / 320 = 50'000 Hz``.
* The neutral DC level is 0; audio is only produced once the Arduboy speaker
  pins (DDRC bits 6/7) are outputs and Timer4 PWM is running.
* The first music callback is *measured* with an absim PC breakpoint on the
  engine's ``osc_tick_handler`` (never inferred).

stdout JSON only; diagnostics to stderr.  Authoring never touches ``src/``.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import struct
import subprocess
from collections import Counter
from pathlib import Path

from .lower import availability, build_review_payload, clock_report, lower
from .progmem_backend import BACKEND_NAME, build as build_progmem
from .score import (
    CHANNEL_NAMES,
    ENGINE_NAME,
    TICK_BASE_HZ,
    Diagnostic,
    ScoreError,
    library_version,
)

# --- audio facts (from the local Ardens sources; see module docstring) ------
SAMPLE_RATE = 50000
SAMPLE_BIT_DEPTH = 16
SAMPLE_CHANNELS = 1
NEUTRAL_LEVEL = 0
SOUND_GAIN = 2000
SOUND_CYCLES = 320
CAPTURE_FORMAT = "pcm-s16le-mono"

DEFAULT_SECONDS = 60.0
MAX_SECONDS = 300.0
TAIL_SECONDS = 0.5

FQBN = "arduboy-homemade:avr:arduboy-fx"
AVR_TOOLCHAIN_VERSION = "7.3.0-atmel3.6.1-arduino7"

REPORT_PAYLOAD = "atmlib-render-preview"
REPORT_PAYLOAD_VERSION = 1

# Packaged runtime inputs for AVR capture and original-engine tick tracing.
TRACE_MAIN_REL = "tools/music_authoring/preview/trace_main.c"
TRACE_SHIM_REL = "tools/music_authoring/preview/avr_shim"
PREVIEW_INO_REL = "tools/music_authoring/preview/preview/preview.ino"


class RenderError(Exception):
    """A structured render/tool failure carrying a diagnostic code."""

    def __init__(self, code: str, message: str, suggestion: str, exit_code: int = 3, path: str = ""):
        super().__init__(message)
        self.code = code
        self.message = message
        self.suggestion = suggestion
        self.exit_code = exit_code
        self.path = path

    def diagnostic(self) -> Diagnostic:
        return Diagnostic(self.code, self.path, self.message, self.suggestion)


# --------------------------------------------------------------------------- #
# Tool discovery
# --------------------------------------------------------------------------- #
def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _preview_dir() -> Path:
    return Path(__file__).resolve().parent / "preview"


def _ardens_root() -> Path | None:
    env = os.environ.get("ARDENS_ROOT")
    candidates = []
    if env:
        candidates.append(Path(env))
    root = _repo_root()
    candidates += [
        root.parent / "ardens",
        root.parent.parent / "ardens",
        Path.home() / "code/arduboy/ardens",
        Path.home() / "code/Ardens",
        Path.home() / "code/ardens",
    ]
    for cand in candidates:
        if (cand / "src/absim.hpp").is_file() and (cand / "build/libardensdebuggerlib.a").is_file():
            return cand
    return None


def _arduino_cli() -> str | None:
    return shutil.which("arduino-cli")


def _avr_tool_bin() -> Path | None:
    base = Path.home() / "Library/Arduino15/packages/arduino/tools/avr-gcc" / AVR_TOOLCHAIN_VERSION / "bin"
    if (base / "avr-nm").is_file():
        return base
    return None


def _core_version() -> str | None:
    base = Path.home() / "Library/Arduino15/packages/arduboy-homemade/hardware/avr"
    if not base.is_dir():
        return None
    versions = sorted((p.name for p in base.iterdir() if p.is_dir()), reverse=True)
    return versions[0] if versions else None


def _ardens_version(ardens: Path) -> str:
    """Best-effort Ardens version without git operations."""
    for name in ("VERSION", "version.txt"):
        candidate = ardens / name
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8").strip()
    return "unknown (no git operations permitted; read from source tree)"


def _tool_version(argv: list[str]) -> str:
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    text = (proc.stdout or proc.stderr or "").strip().splitlines()
    return text[0].strip() if text else "unknown"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run(argv: list[str], *, cwd: Path | None = None, env: dict | None = None, timeout: int = 600):
    proc = subprocess.run(
        argv,
        cwd=str(cwd) if cwd else None,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return proc.returncode, proc.stdout, proc.stderr


# --------------------------------------------------------------------------- #
# Pure helpers (unit-testable without AVR/absim)
# --------------------------------------------------------------------------- #
def duration_plan(total_ticks: int, tick_divisor: int, seconds: float | None) -> dict:
    """Decide the bounded render window and whether the song is truncated.

    ``tick_divisor`` is the integer AVR divider (``Clock.tick_divisor``); all
    durations derive from ``tick_divisor / TICK_BASE_HZ`` so nondivisor tempos
    keep exact timing (255 Hz -> 7/2000 s per tick) instead of a rounded Hz.
    """
    requested = DEFAULT_SECONDS if seconds is None else float(seconds)
    if not (requested > 0.0) or requested > MAX_SECONDS:
        raise RenderError(
            "DURATION_CAP",
            f"requested render length {requested!r}s is outside (0, {MAX_SECONDS:g}]",
            f"Choose --seconds between 0 and {MAX_SECONDS:g}.",
            exit_code=2,
        )
    if tick_divisor:
        song_seconds = total_ticks * tick_divisor / TICK_BASE_HZ
        ticks_per_second = TICK_BASE_HZ / tick_divisor
    else:
        song_seconds = 0.0
        ticks_per_second = 0.0
    needed = song_seconds + TAIL_SECONDS
    render_seconds = min(requested, needed)
    truncated = needed > requested + 1e-9
    rendered_ticks = min(total_ticks, int(render_seconds * ticks_per_second + 1e-9))
    return {
        "requested_seconds": requested,
        "max_seconds": MAX_SECONDS,
        "song_seconds": song_seconds,
        "tail_seconds": TAIL_SECONDS,
        "effective_render_seconds": render_seconds,
        "render_ms": int(round(render_seconds * 1000.0)),
        "truncated": truncated,
        "rendered_ticks": rendered_ticks,
        "total_ticks": total_ticks,
        "truncation_reason": (
            f"requested {requested:g}s < song+tail {needed:.6f}s" if truncated else None
        ),
    }


def parse_wav_bytes(data: bytes) -> dict:
    """Parse and validate a canonical WAV header; raise RenderError if invalid."""
    if len(data) < 44 or data[0:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise RenderError("WAV_INVALID", "not a RIFF/WAVE file", "Re-run the capture.", exit_code=3)
    riff_size = struct.unpack_from("<I", data, 4)[0]
    pos = 12
    fmt = None
    data_bytes = None
    data_offset = None
    while pos + 8 <= len(data):
        chunk_id = data[pos : pos + 4]
        chunk_size = struct.unpack_from("<I", data, pos + 4)[0]
        body = pos + 8
        if chunk_id == b"fmt ":
            audio_format, channels, rate, byte_rate, block_align, bits = struct.unpack_from(
                "<HHIIHH", data, body
            )
            fmt = {
                "audio_format": audio_format,
                "channels": channels,
                "sample_rate": rate,
                "byte_rate": byte_rate,
                "block_align": block_align,
                "bits_per_sample": bits,
            }
        elif chunk_id == b"data":
            data_bytes = chunk_size
            data_offset = body
        pos = body + chunk_size + (chunk_size & 1)
    if fmt is None or data_bytes is None:
        raise RenderError("WAV_INVALID", "missing fmt or data chunk", "Re-run the capture.", exit_code=3)
    if fmt["audio_format"] != 1:
        raise RenderError("WAV_FORMAT", "expected PCM (format 1)", "Re-run the capture.", exit_code=3)
    frame_bytes = fmt["block_align"]
    frames = data_bytes // frame_bytes if frame_bytes else 0
    if data_offset is not None and data_offset + data_bytes > len(data):
        raise RenderError("WAV_TRUNCATED", "data chunk shorter than declared", "Re-run the capture.", exit_code=3)
    return {
        "riff_bytes": riff_size + 8,
        "format": fmt,
        "data_bytes": data_bytes,
        "data_offset": data_offset,
        "frames": frames,
    }


def decode_samples(data: bytes) -> list[int]:
    info = parse_wav_bytes(data)
    fmt = info["format"]
    if fmt["bits_per_sample"] != 16:
        raise RenderError("WAV_FORMAT", "expected 16-bit samples", "Re-run the capture.", exit_code=3)
    count = info["frames"] * fmt["channels"]
    return list(struct.unpack_from(f"<{count}h", data, info["data_offset"]))


def compare_source_identity(payload: dict, expect: dict) -> list[Diagnostic]:
    """Reject stale/mismatched source & event digests against a canonical review."""
    diagnostics: list[Diagnostic] = []
    exp_src = (expect.get("source") or {}).get("sha256")
    got_src = (payload.get("source") or {}).get("sha256")
    if exp_src and got_src and exp_src != got_src:
        diagnostics.append(
            Diagnostic(
                "SOURCE_DIGEST_MISMATCH",
                "/source/sha256",
                f"score source sha256 {got_src} does not match canonical review {exp_src}",
                "Re-run validate/build on the current song.json or refresh the review payload.",
            )
        )
    exp_ev = (expect.get("event_digest") or {}).get("hex")
    got_ev = (payload.get("event_digest") or {}).get("hex")
    if exp_ev and got_ev and exp_ev != got_ev:
        diagnostics.append(
            Diagnostic(
                "EVENT_DIGEST_MISMATCH",
                "/event_digest/hex",
                f"canonical event digest {got_ev} does not match review {exp_ev}",
                "Regenerate the canonical review payload for this source.",
            )
        )
    return diagnostics


def _tick_to_sample(tick: int, first_callback_sample: int, tick_divisor: int) -> int:
    if not tick_divisor:
        return first_callback_sample
    return first_callback_sample + int(round(tick * tick_divisor / TICK_BASE_HZ * SAMPLE_RATE))


def gate_timeline(spans, total_ticks: int) -> list[bool]:
    """Per-tick active mask: is any channel gated at this tick?"""
    active = [False] * max(0, total_ticks)
    for span in spans:
        for tick in range(span.start_tick, min(span.gate_end_tick, total_ticks)):
            if tick >= 0:
                active[tick] = True
    return active


def _window_measure(samples: list[int], lo: int, hi: int, settle_guard: int = 128) -> dict:
    lo = max(0, min(lo, len(samples)))
    hi = max(lo, min(hi, len(samples)))
    seg = samples[lo:hi]
    if not seg:
        return {"start_sample": lo, "end_sample": hi, "samples": 0, "known": False}
    digest = hashlib.sha256(struct.pack(f"<{len(seg)}h", *seg)).hexdigest()[:16]
    steady = seg[settle_guard:] if len(seg) > settle_guard else seg
    modal_value, modal_count = Counter(seg).most_common(1)[0]
    return {
        "start_sample": lo,
        "end_sample": hi,
        "samples": len(seg),
        "min": min(seg),
        "max": max(seg),
        "mean": round(sum(seg) / len(seg), 4),
        "ac_amplitude": max(seg) - min(seg),
        "constant": (max(seg) == min(seg)),
        "modal_value": modal_value,
        "modal_fraction": round(modal_count / len(seg), 6),
        "steady_min": min(steady),
        "steady_max": max(steady),
        "steady_mean": round(sum(steady) / len(steady), 4),
        "steady_ac_amplitude": max(steady) - min(steady),
        "steady_constant": max(steady) == min(steady),
        "samples_sha256_16": digest,
        "known": True,
    }


def _measure_gate_regions(samples, spans, total_ticks, first_cb, tick_divisor, cap: int = 256) -> dict:
    active = gate_timeline(spans, total_ticks)
    regions = []
    i = 0
    while i < len(active) and len(regions) < cap:
        j = i
        while j < len(active) and active[j] == active[i]:
            j += 1
        lo = _tick_to_sample(i, first_cb, tick_divisor)
        hi = _tick_to_sample(j, first_cb, tick_divisor)
        measure = _window_measure(samples, lo, hi)
        measure.update({"start_tick": i, "end_tick": j, "active": active[i]})
        regions.append(measure)
        i = j
    return {"count": len(regions), "truncated": len(regions) >= cap, "regions": regions}


def _measure_note_windows(samples, spans, first_cb, tick_divisor, cap: int = 512) -> dict:
    windows = []
    for span in spans[:cap]:
        lo = _tick_to_sample(span.start_tick, first_cb, tick_divisor)
        hi = _tick_to_sample(span.gate_end_tick, first_cb, tick_divisor)
        measure = _window_measure(samples, lo, hi)
        measure.update(
            {
                "channel": span.channel,
                "note": span.note,
                "instrument": span.instrument,
                "start_tick": span.start_tick,
                "duration": span.duration,
                "duty": span.duty,
            }
        )
        windows.append(measure)
    return {"count": len(windows), "truncated": len(spans) > cap, "notes": windows}


def analyze_capture(samples: list[int], first_callback_sample: int, total_ticks: int, tick_divisor: int, spans=None) -> dict:
    """Measure silence/level facts from the captured PCM relative to neutral."""
    n = len(samples)
    peak = max((abs(s) for s in samples), default=0)
    if tick_divisor:
        musical_len = int(round(total_ticks * tick_divisor / TICK_BASE_HZ * SAMPLE_RATE))
    else:
        musical_len = 0
    music_start = max(0, min(first_callback_sample, n))
    music_end = min(n, music_start + musical_len)
    guard = int(round(0.05 * SAMPLE_RATE))  # skip the PWM-stop transition

    def window(lo: int, hi: int) -> dict:
        return _window_measure(samples, lo, hi)

    pre = window(0, first_callback_sample)
    musical = window(music_start, music_end)
    post = window(music_end + guard, n)
    # A steady (zero-AC) region is "acoustically silent" even when the speaker
    # holds a non-neutral DC level (e.g. after the engine stops PWM).
    post_silent = post.get("steady_constant", post.get("constant", False))
    musical_active = musical.get("steady_ac_amplitude", 0) > 8 * SOUND_GAIN // 100
    pre_silent = pre.get("known", False) and pre.get("steady_ac_amplitude", 999) <= 8

    gate_regions = None
    note_windows = None
    if spans is not None:
        gate_regions = _measure_gate_regions(samples, spans, total_ticks, music_start, tick_divisor)
        note_windows = _measure_note_windows(samples, spans, music_start, tick_divisor)

    # Steady in-song silence level (PWM running at the DC offset) vs the
    # post-end PWM-off rail; both are zero-AC but differ from neutral 0.
    in_song_silence_levels = []
    if gate_regions:
        for region in gate_regions["regions"]:
            if not region.get("active") and region.get("steady_constant"):
                in_song_silence_levels.append(region["steady_min"])

    return {
        "neutral_level": NEUTRAL_LEVEL,
        "peak_abs": peak,
        "first_music_callback_sample": first_callback_sample,
        "musical_window": {
            "start_sample": music_start,
            "end_sample": music_end,
            "samples": max(0, music_end - music_start),
            "tick_extent": total_ticks,
        },
        "pre_music": pre,
        "post_end": post,
        "post_end_guard_samples": guard,
        "post_end_is_ac_silent": post_silent,
        "post_end_dc_level": post.get("steady_min") if post_silent else None,
        "measured_in_song_silence_levels": sorted(set(in_song_silence_levels)),
        "musical_active": musical_active,
        "gate_regions": gate_regions,
        "note_windows": note_windows,
        "checks": {
            "neutral_level_is_zero": NEUTRAL_LEVEL == 0,
            "pre_music_steady_near_neutral": pre_silent,
            "musical_window_active": musical_active,
            "post_end_is_ac_silent": post_silent,
            "post_end_level_relative_to_neutral": (
                (post.get("steady_min") == NEUTRAL_LEVEL == post.get("steady_max")) if post_silent else None
            ),
        },
    }


def build_render_report(
    *,
    score,
    lowered,
    review_payload: dict,
    source_identity_diagnostics: list[Diagnostic],
    canonical_review_path: str | None,
    plan: dict,
    capture: dict,
    wav_path: str,
    wav_sha256: str,
    wav_bytes: int,
    wav_info: dict,
    trace_path: str | None,
    provenance: dict,
    cost: dict,
    commands: list[dict],
    artifacts: dict,
) -> dict:
    """Assemble the deterministic render report consumed by the viewer."""
    samples = capture.get("samples_data", [])
    analysis = analyze_capture(
        samples,
        int(capture.get("first_callback_sample") or 0),
        lowered.total_ticks,
        score.clock.tick_divisor,
        spans=lowered.spans,
    )
    analysis.pop("samples_data", None)
    if score.loop:
        analysis["after_first_cycle"] = analysis.pop("post_end")
        analysis["post_end_is_ac_silent"] = None
        analysis["post_end_dc_level"] = None
        analysis["checks"]["post_end_is_ac_silent"] = None
        analysis["checks"]["post_end_level_relative_to_neutral"] = None
    return {
        "payload": REPORT_PAYLOAD,
        "payload_version": REPORT_PAYLOAD_VERSION,
        "ok": not source_identity_diagnostics,
        "tool": {"name": "atm-music", "version": _tool_version_str()},
        "engine": {
            "name": ENGINE_NAME,
            "library_version": library_version(),
            "channels": list(CHANNEL_NAMES),
            "tick_base_hz": TICK_BASE_HZ,
        },
        "backend": {"name": BACKEND_NAME, "available": True},
        "source": {
            "path": score.source_path,
            "sha256": score.source_sha256,
            "bytes": score.source_bytes,
        },
        "event_digest": dict(lowered.event_digest),
        "clock": clock_report(score),
        "total_ticks": lowered.total_ticks,
        **({"loop": {"start_tick": 0, "end_tick": lowered.total_ticks}} if score.loop else {}),
        "canonical_review": {
            "path": canonical_review_path,
            "matched": not source_identity_diagnostics,
            "identity_diagnostics": [d.as_dict() for d in source_identity_diagnostics],
        },
        "render": {
            "seconds": {
                "requested": plan["requested_seconds"],
                "effective": plan["effective_render_seconds"],
                "song": plan["song_seconds"],
                "tail": plan["tail_seconds"],
                "max": plan["max_seconds"],
            },
            "truncated": plan["truncated"],
            "truncation_reason": plan["truncation_reason"],
            "rendered_ticks": plan["rendered_ticks"],
            "total_ticks": plan["total_ticks"],
        },
        "audio": {
            "wav": wav_path,
            "sha256": wav_sha256,
            "bytes": wav_bytes,
            "format": CAPTURE_FORMAT,
            "channels": wav_info["format"]["channels"],
            "sample_rate": wav_info["format"]["sample_rate"],
            "bit_depth": wav_info["format"]["bits_per_sample"],
            "sample_count": wav_info["frames"],
            "neutral_level": NEUTRAL_LEVEL,
            "sound_gain": SOUND_GAIN,
            "sound_cycles": SOUND_CYCLES,
            "first_music_callback_sample": capture.get("first_callback_sample"),
            "first_music_callback_seconds": (
                round(capture["first_callback_sample"] / SAMPLE_RATE, 9)
                if capture.get("first_callback_sample") is not None
                else None
            ),
            "first_music_callback_measured": bool(capture.get("first_callback_found")),
            "first_nonzero_sample": capture.get("first_nonzero_sample"),
            "min_sample": capture.get("min_sample"),
            "max_sample": capture.get("max_sample"),
            "nonzero_samples": capture.get("nonzero_samples"),
            "analysis": analysis,
        },
        "trace": {"csv": trace_path},
        "provenance": provenance,
        "cost": cost,
        "commands": commands,
        "limitations": [
            "The WAV is the emulated mono speaker mix (DDRC6/7 differential); per-channel isolation is not possible from a single capture. Channel ordering is evidenced by the original-engine tick trace and the time-isolated preview fixture (tests/music_authoring/fixtures/basic/isolated.json).",
            "While Timer4 PWM runs, emulated neutral is 0 plus a small DC quantization offset (measured steady silence = 2 counts). After the score ends the engine stops PWM and the captured level is a constant DC rail (~-2000, zero AC), not 0; both are acoustically silent but not equal to neutral 0.",
            "Sound is only produced when the Arduboy speaker pins are outputs (DDRC6/7) and Timer4 PWM is active; a fixture that does not enable them captures silence.",
        ],
        "capabilities": {
            "render": {"available": True},
            "wav_preview": {"available": True},
            "note": (
                "This render command owns bounded WAV preview. The frontend "
                "capabilities payload stays pinned by its 3ii.1 golden fixtures."
            ),
        },
        "diagnostics": source_identity_diagnostics,
        "artifacts": artifacts,
    }


def _tool_version_str() -> str:
    from .score import TOOL_VERSION

    return TOOL_VERSION


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def _tick_instr_index(elf: Path, avr_nm: Path) -> int | None:
    rc, out, _ = _run([str(avr_nm), str(elf)])
    if rc != 0:
        return None
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[-1] == "osc_tick_handler" and parts[1] in ("t", "T"):
            try:
                return int(parts[0], 16) // 2
            except ValueError:
                return None
    return None


def render(
    song_path: str,
    *,
    backend: str = "progmem",
    seconds: float | None = None,
    out_dir: str,
    canonical_review: str | None = None,
    keep_artifacts: bool = True,
) -> tuple[dict, int]:
    """Render ``song_path`` to a bounded WAV preview. Returns ``(payload, exit_code)``."""
    from .validate import load_and_validate

    if backend != "progmem":
        return (
            {
                "ok": False,
                "diagnostics": [
                    Diagnostic(
                        "BACKEND_UNAVAILABLE",
                        "/backend",
                        f"Backend {backend!r} cannot render audio; only 'progmem' is supported.",
                        "Use --backend progmem.",
                    ).as_dict()
                ],
                "artifacts": {},
            },
            2,
        )

    score, diagnostics = load_and_validate(song_path)
    if score is None:
        code = 3 if any(d.code == "IO_ERROR" for d in diagnostics) else 2
        return ({"ok": False, "diagnostics": [d.as_dict() for d in diagnostics], "artifacts": {}}, code)

    try:
        lowered = lower(score)
    except ScoreError as exc:
        return ({"ok": False, "diagnostics": [Diagnostic("TOOL_ERROR", "", str(exc), "Check the score.").as_dict()], "artifacts": {}}, 3)

    try:
        plan = duration_plan(lowered.total_ticks, score.clock.tick_divisor, seconds)
    except RenderError as exc:
        return ({"ok": False, "diagnostics": [exc.diagnostic().as_dict()], "artifacts": {}}, exc.exit_code)

    review_payload = build_review_payload(score, lowered)

    # --- canonical review identity check ------------------------------------ #
    canonical_path = canonical_review
    if canonical_path is None:
        default_review = Path(song_path).resolve().parent / "expected/review.json"
        if default_review.is_file():
            canonical_path = str(default_review)
    identity_diagnostics: list[Diagnostic] = []
    if canonical_path:
        try:
            with open(canonical_path, "r", encoding="utf-8") as handle:
                expect = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            identity_diagnostics.append(
                Diagnostic("REVIEW_UNREADABLE", "", f"cannot read canonical review {canonical_path}: {exc}", "Fix or drop --review.")
            )
        else:
            identity_diagnostics = compare_source_identity(review_payload, expect)
    if identity_diagnostics:
        return (
            {
                "ok": False,
                "diagnostics": [d.as_dict() for d in identity_diagnostics],
                "artifacts": {},
            },
            2,
        )

    # --- tool discovery ----------------------------------------------------- #
    out = Path(out_dir)
    if out.exists() and not out.is_dir():
        return ({"ok": False, "diagnostics": [Diagnostic("IO_ERROR", "", f"--out {out_dir!r} is not a directory", "Choose a directory path.").as_dict()], "artifacts": {}}, 3)

    ardens = _ardens_root()
    cli = _arduino_cli()
    avr_bin = _avr_tool_bin()
    if ardens is None:
        return (
            {"ok": False, "diagnostics": [Diagnostic("RENDER_TOOL_MISSING", "", "local Ardens absim source/build not found", "Set ARDENS_ROOT to a built Ardens tree.").as_dict()], "artifacts": {}},
            3,
        )
    if cli is None:
        return ({"ok": False, "diagnostics": [Diagnostic("RENDER_TOOL_MISSING", "", "arduino-cli not found on PATH", "Install arduino-cli.").as_dict()], "artifacts": {}}, 3)
    if avr_bin is None:
        return ({"ok": False, "diagnostics": [Diagnostic("RENDER_TOOL_MISSING", "", f"avr-gcc toolchain {AVR_TOOLCHAIN_VERSION} not found", "Install the Arduino AVR toolchain.").as_dict()], "artifacts": {}}, 3)

    repo = _repo_root()
    preview_ino = repo / PREVIEW_INO_REL
    if not preview_ino.is_file():
        return ({"ok": False, "diagnostics": [Diagnostic("RENDER_TOOL_MISSING", "", f"preview fixture {PREVIEW_INO_REL} missing", "Restore the preview fixture.").as_dict()], "artifacts": {}}, 3)

    commands: list[dict] = []

    def record(step: str, argv: list[str]) -> None:
        commands.append({"step": step, "argv": argv})

    try:
        out.mkdir(parents=True, exist_ok=True)
        gen_dir = out / "generated"
        avr_build = out / "avr-build"
        avr_out = out / "avr-out"

        # 1. PROGMEM header (frontend backend; deterministic).
        build_result, gen_artifacts = build_progmem(score, lowered, str(gen_dir))
        record("build-progmem", ["tools/atm-music", "build", str(song_path), "--backend", "progmem", "--out", str(gen_dir)])

        # 2. AVR image (real library + generated score).
        argv = [
            cli, "compile", "--fqbn", FQBN, "--library", str(repo),
            "--build-path", str(avr_build),
            "--output-dir", str(avr_out),
            "--build-property", f"compiler.cpp.extra_flags=-I{gen_dir.resolve()}",
            str(preview_ino.parent),
        ]
        record("arduino-cli-compile", argv)
        rc, so, se = _run(argv, cwd=repo, timeout=900)
        if rc != 0:
            return (
                {"ok": False, "diagnostics": [Diagnostic("COMPILE_FAILED", "", f"arduino-cli compile failed: {se.strip()[-800:]}", "Inspect the AVR toolchain.").as_dict()], "artifacts": {}, "commands": commands},
                3,
            )
        elf = avr_out / "preview.ino.elf"
        if not elf.is_file():
            candidates = list(avr_out.glob("*.elf"))
            if not candidates:
                return ({"ok": False, "diagnostics": [Diagnostic("COMPILE_FAILED", "", "no .elf produced by arduino-cli", "Check the sketch build.").as_dict()], "artifacts": {}}, 3)
            elf = candidates[0]

        # 3. absim audio-capture harness (build once; cached).
        harness = out / "absim_audio_harness"
        if not harness.is_file():
            build_script = _preview_dir() / "build-harness.sh"
            env = dict(os.environ, ARDENS_ROOT=str(ardens))
            record("build-harness", [str(build_script), str(harness)])
            rc, so, se = _run([str(build_script), str(harness)], cwd=repo, env=env, timeout=900)
            if rc != 0 or not harness.is_file():
                return ({"ok": False, "diagnostics": [Diagnostic("RENDER_TOOL_MISSING", "", f"absim harness build failed: {se.strip()[-400:]}", "Check the Ardens build.").as_dict()], "artifacts": {}}, 3)

        # 4. measure the first-music-callback instruction index.
        tick_instr = _tick_instr_index(elf, avr_bin / "avr-nm")

        # 5. capture real AVR audio.
        wav_path = out / "preview.wav"
        argv = [str(harness), str(elf), str(plan["render_ms"]), str(wav_path)]
        if tick_instr is not None:
            argv.append(hex(tick_instr))
        record("absim-capture", argv)
        rc, so, se = _run(argv, cwd=repo, timeout=900)
        if rc != 0 or not wav_path.is_file():
            return ({"ok": False, "diagnostics": [Diagnostic("CAPTURE_FAILED", "", f"absim audio capture failed: {se.strip()[-400:]}", "Check the AVR image and harness.").as_dict()], "artifacts": {}}, 3)
        capture = json.loads(so.strip().splitlines()[-1])

        wav_data = wav_path.read_bytes()
        wav_info = parse_wav_bytes(wav_data)
        samples = decode_samples(wav_data)
        capture["samples_data"] = samples

        # 6. original-engine tick trace (reuse the frontend host harness).
        trace_path = None
        trace_main = repo / TRACE_MAIN_REL
        shim = repo / TRACE_SHIM_REL
        trace_bin = out / "tick_trace"
        if trace_main.is_file() and shim.is_dir():
            cc = os.environ.get("CC", "cc")
            argv = [
                cc, "-std=c11", "-O1", "-w",
                f"-I{shim}", f"-I{repo / 'src'}", f"-I{gen_dir}",
                str(trace_main), "-o", str(trace_bin),
            ]
            record("build-trace", argv)
            rc, so, se = _run(argv, cwd=repo, timeout=300)
            if rc == 0:
                trace_csv = out / "tick_trace.csv"
                trace_ticks = lowered.total_ticks * (2 if score.loop else 1) + 1
                rc2, so2, _ = _run([str(trace_bin), str(trace_ticks)], cwd=repo, timeout=300)
                if rc2 == 0:
                    trace_csv.write_text(so2, encoding="utf-8")
                    trace_path = str(trace_csv)
                    record("run-trace", [str(trace_bin), str(trace_ticks)])

        # 7. provenance + cost.
        provenance = _provenance(ardens, cli, avr_bin)
        provenance["absim"]["first_music_callback_measured"] = bool(capture.get("first_callback_found"))
        provenance["absim"]["tick_breakpoint_instr"] = tick_instr
        cost = _cost(avr_bin / "avr-size", elf, build_result)

        artifacts = {
            "wav": str(wav_path),
            "report": str(out / "preview.json"),
            "tick_trace": trace_path,
            "score_h": gen_artifacts.get("score.h"),
            "review_json": gen_artifacts.get("review.json"),
            "avr_elf": str(elf),
        }

        report = build_render_report(
            score=score,
            lowered=lowered,
            review_payload=review_payload,
            source_identity_diagnostics=identity_diagnostics,
            canonical_review_path=canonical_path,
            plan=plan,
            capture=capture,
            wav_path=str(wav_path),
            wav_sha256=_sha256_file(wav_path),
            wav_bytes=len(wav_data),
            wav_info=wav_info,
            trace_path=trace_path,
            provenance=provenance,
            cost=cost,
            commands=commands,
            artifacts=artifacts,
        )
        (out / "preview.json").write_text(json.dumps(report, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    except RenderError as exc:
        return ({"ok": False, "diagnostics": [exc.diagnostic().as_dict()], "artifacts": {}, "commands": commands}, exc.exit_code)
    except OSError as exc:
        return ({"ok": False, "diagnostics": [Diagnostic("IO_ERROR", "", f"render I/O failure: {exc}", "Check paths and permissions.").as_dict()], "artifacts": {}}, 3)
    except Exception as exc:  # pragma: no cover - defensive tool failure
        return ({"ok": False, "diagnostics": [Diagnostic("TOOL_ERROR", "", f"render failed: {exc}", "Inspect stderr diagnostics.").as_dict()], "artifacts": {}, "commands": commands}, 3)

    return (report, 0)


def _provenance(ardens: Path, cli: str, avr_bin: Path) -> dict:
    return {
        "python": platform.python_version(),
        "avr_gcc": _tool_version([str(avr_bin / "avr-gcc"), "--version"]),
        "arduino_cli": _tool_version([cli, "version"]),
        "fqbn": FQBN,
        "core": {
            "package": "arduboy-homemade",
            "version": _core_version(),
        },
        "ardens": {
            "root": str(ardens),
            "version": _ardens_version(ardens),
            "lib": str(ardens / "build/libardensdebuggerlib.a"),
        },
        "absim": {
            "sample_rate": SAMPLE_RATE,
            "sound_cycles": SOUND_CYCLES,
            "sound_gain": SOUND_GAIN,
            "neutral_level": NEUTRAL_LEVEL,
            "cpu_hz": 16000000,
        },
        "engine": {"name": ENGINE_NAME, "library_version": library_version()},
    }


def _cost(avr_size: Path, elf: Path, build_result) -> dict:
    instrumented = {"measured": False}
    if avr_size.is_file():
        rc, out, _ = _run([str(avr_size), "-C", "--mcu=atmega32u4", str(elf)])
        if rc == 0:
            program = data = None
            for line in out.splitlines():
                parts = line.split()
                if line.startswith("Program:"):
                    program = int(parts[1])
                elif line.startswith("Data:"):
                    data = int(parts[1])
            instrumented = {
                "measured": program is not None,
                "program_bytes": program,
                "data_bytes": data,
                "note": (
                    "Instrumented preview fixture (core + ATMlib + score + speaker "
                    "enable). Not a production or whole-game measurement."
                ),
            }
    return {
        "production": {
            "score_bytes": build_result.report["score"]["bytes"],
            "score_sha256": build_result.report["score"]["sha256"],
            "note": "PROGMEM song asset only; engine cost is tracked separately.",
        },
        "instrumented": instrumented,
        "status": "partially_measured",
    }


def capability_report() -> dict:
    """Render availability reported by this command (frontend payload is pinned)."""
    return {
        "backend": {"progmem": {"available": True, "render": True}},
        "capabilities": {
            "render": {"available": True},
            "wav_preview": {"available": True},
            "inspect": availability()["capabilities"]["inspect"],
        },
    }
