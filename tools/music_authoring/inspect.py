"""Offline HTML/JavaScript track review with synchronized audition (ATMlib2FX-3ii.6).

``atm-music inspect song.json --out review.html --json`` validates the source
through the existing frontend, then writes two artifacts:

* a standalone ``review.html`` that embeds the canonical review payload, the
  viewer CSS/JS and (optionally) the matching WAV bytes.  It opens from
  ``file://`` with no server, network, CDN, module or external file.
* a deterministic adjacent ``review.json`` containing the canonical review
  payload (the same bytes ``build --backend progmem`` writes).

The browser viewer *draws* the canonical payload.  It never parses the score,
expands repetition, lowers effects or quantizes ticks, and it never compiles,
packs, writes or flashes FX data.  The JSON source stays authoritative.

Audition is optional: ``--audio-preview <dir>`` loads the renderer's report and
WAV, requires the current source/event digests to match, validates the WAV
metadata/identity, and embeds the audio.  Stale or mismatched audio is rejected
instead of letting a previous revision play under a new score.  Paths inside the
report are resolved and bounded to the requested preview directory.
"""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from .lower import (
    build_review_payload,
    channel_descriptors,
    clock_report,
    lower,
    serialize_review,
)
from .render import (
    CAPTURE_FORMAT,
    NEUTRAL_LEVEL,
    REPORT_PAYLOAD,
    SAMPLE_RATE,
    SOUND_GAIN,
    parse_wav_bytes,
)
from .score import (
    Diagnostic,
    ScoreError,
    TOOL_NAME,
    TOOL_VERSION,
    library_version,
    tick_divisor,
)

VIEWER_DIR = Path(__file__).resolve().parent / "viewer"
VIEWER_PAYLOAD = "atmlib-inspect"
VIEWER_PAYLOAD_VERSION = 1

# Bound the embedded audio so a pathological render cannot balloon the HTML.
MAX_EMBED_BYTES = 48 * 1024 * 1024

SIDE_EFFECT_NOTE = (
    "Review artifact only: generating or opening this file never compiles, "
    "packs, writes or flashes FX data. The JSON source stays authoritative."
)


class InspectError(Exception):
    """A structured inspect/tool failure carrying a diagnostic code."""

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
# Escaping / assets (unit-testable)
# --------------------------------------------------------------------------- #
def escape_json_for_script(text: str) -> str:
    """Escape a JSON document for safe embedding in a ``<script>`` block.

    ``json.dumps(..., ensure_ascii=True)`` already escapes non-ASCII, but ``<``,
    ``>`` and ``&`` survive it; escaping them prevents a ``</script>`` sequence
    (or an HTML comment) inside authored data from terminating the block.
    """
    return (
        text.replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def serialize_embedded_json(document: dict) -> str:
    """Deterministic, inert JSON text for the data block."""
    text = json.dumps(document, ensure_ascii=True, sort_keys=False, separators=(",", ":"))
    return escape_json_for_script(text)


def _read_asset(name: str) -> str:
    return (VIEWER_DIR / name).read_text(encoding="utf-8")


def render_html(document: dict) -> str:
    """Substitute the viewer template with embedded data, CSS and JS."""
    template = _read_asset("template.html")
    data = serialize_embedded_json(document)
    html = (
        template.replace("__ATMLIB_CSS__", _read_asset("viewer.css"), 1)
        .replace("__ATMLIB_DATA__", data, 1)
        .replace("__ATMLIB_JS__", _read_asset("piezo.js") + "\n" + _read_asset("loop.js") + "\n" + _read_asset("viewer.js"), 1)
    )
    return html


# --------------------------------------------------------------------------- #
# Audio preview loading
# --------------------------------------------------------------------------- #
def _resolve_within(base: Path, ref: str) -> Path | None:
    """Resolve ``ref`` under ``base``; return None if it escapes or is missing."""
    candidate = Path(ref)
    if not candidate.is_absolute():
        candidate = base / candidate
    try:
        resolved = candidate.resolve()
        root = base.resolve()
        resolved.relative_to(root)
    except (OSError, ValueError):
        return None
    return resolved


def _warning(code: str, path: str, message: str, suggestion: str) -> Diagnostic:
    return Diagnostic(code, path, message, suggestion, severity="warning")


def identity_diagnostics(current_review: dict, report: dict) -> list[Diagnostic]:
    """Compare the current review digests against a render report (warning severity)."""
    diagnostics: list[Diagnostic] = []
    cur_src = (current_review.get("source") or {}).get("sha256")
    rep_src = (report.get("source") or {}).get("sha256")
    if cur_src and rep_src and cur_src != rep_src:
        diagnostics.append(
            _warning(
                "SOURCE_DIGEST_MISMATCH",
                "/source/sha256",
                f"preview source sha256 {rep_src} does not match the current score {cur_src}",
                "Re-render the WAV for this revised source; the old capture was not embedded.",
            )
        )
    cur_ev = (current_review.get("event_digest") or {}).get("hex")
    rep_ev = (report.get("event_digest") or {}).get("hex")
    if cur_ev and rep_ev and cur_ev != rep_ev:
        diagnostics.append(
            _warning(
                "EVENT_DIGEST_MISMATCH",
                "/event_digest/hex",
                f"preview canonical event digest {rep_ev} does not match the current score {cur_ev}",
                "Re-render the WAV for the revised score; stale audio was rejected.",
            )
        )
    return diagnostics


def _load_report(preview_dir: Path) -> dict:
    report_path = preview_dir / "preview.json"
    if not report_path.is_file():
        raise InspectError(
            "AUDIO_PREVIEW_INVALID",
            f"no preview.json in {preview_dir}",
            "Point --audio-preview at a directory produced by `atm-music render`.",
            path="/audio_preview",
        )
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InspectError(
            "AUDIO_PREVIEW_INVALID",
            f"cannot read render report {report_path}: {exc}",
            "Re-run `atm-music render` to regenerate the report.",
            path="/audio_preview",
        ) from exc
    if report.get("payload") != REPORT_PAYLOAD:
        raise InspectError(
            "AUDIO_PREVIEW_INVALID",
            f"{report_path} is not an {REPORT_PAYLOAD} report",
            "Point --audio-preview at a directory produced by `atm-music render`.",
            path="/audio_preview",
        )
    return report


def _load_wav(preview_dir: Path, report: dict) -> tuple[bytes, Path, dict, list[Diagnostic]]:
    diagnostics: list[Diagnostic] = []
    audio = report.get("audio") or {}
    wav_ref = audio.get("wav")
    wav_path = None
    if isinstance(wav_ref, str):
        wav_path = _resolve_within(preview_dir, wav_ref)
        if wav_path is None or not wav_path.is_file():
            wav_path = _resolve_within(preview_dir, Path(wav_ref).name)
    if wav_path is None or not wav_path.is_file():
        diagnostics.append(
            _warning(
                "AUDIO_WAV_MISSING",
                "/audio/wav",
                "the report names a WAV that is missing or outside the requested preview directory",
                "Re-run `atm-music render` and keep the WAV beside its report.",
            )
        )
        return b"", Path(), {}, diagnostics

    data = wav_path.read_bytes()
    actual_sha = hashlib.sha256(data).hexdigest()
    declared_sha = audio.get("sha256")
    if declared_sha and declared_sha != actual_sha:
        diagnostics.append(
            _warning(
                "AUDIO_WAV_DIGEST_MISMATCH",
                "/audio/sha256",
                f"WAV sha256 {actual_sha} does not match the render report {declared_sha}",
                "Re-render; the WAV does not match its report.",
            )
        )
    try:
        info = parse_wav_bytes(data)
    except Exception as exc:  # RenderError and friends
        diagnostics.append(
            _warning(
                "AUDIO_WAV_INVALID",
                "/audio/wav",
                f"embeddable WAV is not valid RIFF/PCM: {exc}",
                "Re-render the preview WAV.",
            )
        )
        return b"", wav_path, {}, diagnostics

    fmt = info["format"]
    checks = {
        "sample_rate": (fmt["sample_rate"], audio.get("sample_rate")),
        "channels": (fmt["channels"], audio.get("channels")),
        "bit_depth": (fmt["bits_per_sample"], audio.get("bit_depth")),
        "sample_count": (info["frames"], audio.get("sample_count")),
    }
    for label, (measured, declared) in checks.items():
        if declared is not None and measured != declared:
            diagnostics.append(
                _warning(
                    "AUDIO_WAV_METADATA_MISMATCH",
                    "/audio/" + label,
                    f"WAV {label} is {measured}, but the render report records {declared}",
                    "Re-render the preview WAV.",
                )
            )
    return data, wav_path, info, diagnostics


def load_audio_preview(preview_dir: str, current_review: dict) -> tuple[dict | None, list[Diagnostic]]:
    """Load, verify and describe the optional audio preview.

    Returns ``(descriptor_or_None, diagnostics)``.  Structural problems raise
    :class:`InspectError`; identity/metadata problems reject the audio with
    warnings so the visual review is still produced.
    """
    base = Path(preview_dir)
    if not base.is_dir():
        raise InspectError(
            "AUDIO_PREVIEW_INVALID",
            f"--audio-preview {preview_dir!r} is not a directory",
            "Point --audio-preview at a directory produced by `atm-music render`.",
            path="/audio_preview",
        )

    report = _load_report(base)

    diagnostics = identity_diagnostics(current_review, report)
    if diagnostics:
        return None, diagnostics

    data, wav_path, info, wav_diagnostics = _load_wav(base, report)
    diagnostics.extend(wav_diagnostics)
    if diagnostics or not data:
        return None, diagnostics

    if len(data) > MAX_EMBED_BYTES:
        return None, [
            _warning(
                "AUDIO_EMBED_TOO_LARGE",
                "/audio/bytes",
                f"WAV is {len(data)} bytes, above the {MAX_EMBED_BYTES} byte embed bound",
                "Render a shorter window with --seconds.",
            )
        ]

    report_digest = hashlib.sha256((base / "preview.json").read_bytes()).hexdigest()
    audio_meta = report.get("audio") or {}
    render_meta = report.get("render") or {}
    analysis = audio_meta.get("analysis") or {}
    first_cb = audio_meta.get("first_music_callback_sample")
    report_clock = report.get("clock") or {}
    requested_rate = report_clock.get("tick_rate")
    divisor = (
        tick_divisor(requested_rate)
        if isinstance(requested_rate, int) and not isinstance(requested_rate, bool) and requested_rate > 0
        else None
    )
    descriptor = {
        "available": True,
        "format": audio_meta.get("format") or CAPTURE_FORMAT,
        "sample_rate": info["format"]["sample_rate"],
        "channels": info["format"]["channels"],
        "bit_depth": info["format"]["bits_per_sample"],
        "sample_count": info["frames"],
        "neutral_level": audio_meta.get("neutral_level", NEUTRAL_LEVEL),
        "sound_gain": audio_meta.get("sound_gain", SOUND_GAIN),
        "first_music_callback_sample": first_cb,
        "first_music_callback_seconds": (
            round(first_cb / SAMPLE_RATE, 9) if first_cb is not None else None
        ),
        "first_music_callback_measured": bool(audio_meta.get("first_music_callback_measured")),
        "effective_tick_rate": report_clock.get("effective_tick_rate"),
        "tick_divisor": divisor,
        "ticks_per_beat": report_clock.get("ticks_per_beat"),
        "beats_per_bar": (report.get("clock") or {}).get("beats_per_bar"),
        "total_ticks": report.get("total_ticks"),
        "rendered_ticks": render_meta.get("rendered_ticks"),
        "truncated": bool(render_meta.get("truncated")),
        "truncation_reason": render_meta.get("truncation_reason"),
        "song_seconds": (render_meta.get("seconds") or {}).get("song"),
        "post_end_dc_level": (
            analysis.get("post_end_dc_level") if analysis.get("post_end_is_ac_silent") else None
        ),
        "post_end_is_ac_silent": bool(analysis.get("post_end_is_ac_silent")),
        "measured_in_song_silence_levels": analysis.get("measured_in_song_silence_levels") or [],
        "wav_name": wav_path.name,
        "wav_sha256": hashlib.sha256(data).hexdigest(),
        "wav_bytes": len(data),
        "report_name": "preview.json",
        "report_sha256": report_digest,
        "matched_source_sha256": (report.get("source") or {}).get("sha256"),
        "matched_event_digest_hex": (report.get("event_digest") or {}).get("hex"),
        "limitations": list(report.get("limitations") or []),
        "wav_base64": base64.b64encode(data).decode("ascii"),
    }
    return descriptor, diagnostics


# --------------------------------------------------------------------------- #
# Document assembly
# --------------------------------------------------------------------------- #
def build_inspect_document(
    *,
    review_payload: dict,
    score_id: str,
    audio: dict | None,
    audio_diagnostics: list[Diagnostic],
) -> dict:
    """Assemble the inert document embedded in the HTML and written adjacent."""
    return {
        "payload": VIEWER_PAYLOAD,
        "payload_version": VIEWER_PAYLOAD_VERSION,
        "tool": {"name": TOOL_NAME, "version": TOOL_VERSION},
        "score_id": score_id,
        "source_sha256": (review_payload.get("source") or {}).get("sha256"),
        "event_digest_hex": (review_payload.get("event_digest") or {}).get("hex"),
        "review": review_payload,
        "audio": audio,
        "audio_diagnostics": [d.as_dict() for d in audio_diagnostics],
        "capabilities": {
            "inspect": {"available": True},
            "render": {"available": True},
            "canonical_payload_capabilities_pinned": True,
            "note": (
                "The embedded canonical review payload keeps its 3ii.1-pinned "
                "capabilities block (inspect/render reported unavailable) for golden "
                "stability; this command reports its own truthful availability."
            ),
        },
        "side_effects": SIDE_EFFECT_NOTE,
    }


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def inspect(
    song_path: str,
    out_path: str,
    *,
    audio_preview: str | None = None,
) -> tuple[dict, int]:
    """Validate ``song_path`` and write the offline review. Returns (payload, code)."""
    from .validate import load_and_validate

    score, diagnostics = load_and_validate(song_path)
    if score is None:
        code = 3 if any(d.code == "IO_ERROR" for d in diagnostics) else 2
        return (
            {"ok": False, "diagnostics": [d.as_dict() for d in diagnostics], "artifacts": {}},
            code,
        )

    try:
        lowered = lower(score)
    except ScoreError as exc:
        return (
            {
                "ok": False,
                "diagnostics": [Diagnostic("TOOL_ERROR", "", str(exc), "Check the score.").as_dict()],
                "artifacts": {},
            },
            3,
        )

    review_payload = build_review_payload(score, lowered)

    audio = None
    audio_diagnostics: list[Diagnostic] = []
    if audio_preview:
        try:
            audio, audio_diagnostics = load_audio_preview(audio_preview, review_payload)
        except InspectError as exc:
            return (
                {
                    "ok": False,
                    "diagnostics": [exc.diagnostic().as_dict()],
                    "artifacts": {},
                },
                exc.exit_code,
            )

    document = build_inspect_document(
        review_payload=review_payload,
        score_id=score.id,
        audio=audio,
        audio_diagnostics=audio_diagnostics,
    )

    out = Path(out_path)
    if out.exists() and out.is_dir():
        return (
            {
                "ok": False,
                "diagnostics": [
                    Diagnostic(
                        "IO_ERROR",
                        "",
                        f"--out {out_path!r} is a directory",
                        "Pass a file path such as review.html.",
                    ).as_dict()
                ],
                "artifacts": {},
            },
            3,
        )
    review_json_path = out.with_suffix(".json")

    try:
        html = render_html(document)
        review_bytes = serialize_review(review_payload)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(html, encoding="utf-8")
        review_json_path.write_bytes(review_bytes)
    except OSError as exc:
        return (
            {
                "ok": False,
                "diagnostics": [
                    Diagnostic("IO_ERROR", "", f"cannot write review artifacts: {exc}", "Check paths and permissions.").as_dict()
                ],
                "artifacts": {},
            },
            3,
        )

    artifacts = {
        "html": str(out),
        "review_json": str(review_json_path),
    }
    audio_report = None
    if audio:
        artifacts["audio_wav"] = str(Path(audio_preview) / audio["wav_name"])
        artifacts["audio_report"] = str(Path(audio_preview) / "preview.json")
        audio_report = {
            "available": True,
            "wav_sha256": audio["wav_sha256"],
            "wav_bytes": audio["wav_bytes"],
            "report_sha256": audio["report_sha256"],
            "sample_rate": audio["sample_rate"],
            "sample_count": audio["sample_count"],
            "first_music_callback_sample": audio["first_music_callback_sample"],
            "effective_tick_rate": audio["effective_tick_rate"],
            "tick_divisor": audio.get("tick_divisor"),
            "rendered_ticks": audio["rendered_ticks"],
            "total_ticks": audio["total_ticks"],
            "truncated": audio["truncated"],
        }
    else:
        audio_report = {"available": False}
        if not audio_preview:
            audio_report["reason"] = "no --audio-preview was provided; visual review only"
        for item in audio_diagnostics:
            audio_report.setdefault("diagnostics", []).append(item.as_dict())

    html_bytes = len(html.encode("utf-8"))
    report = {
        "schema_version": 1,
        "score_id": score.id,
        "total_ticks": lowered.total_ticks,
        "clock": clock_report(score),
        "channels": channel_descriptors(score, lowered),
        "expanded_note_events": len(lowered.spans),
        "pattern_instances": len(lowered.pattern_instances),
        "source": dict(review_payload["source"]),
        "event_digest": dict(review_payload["event_digest"]),
        "artifacts": dict(artifacts),
        "digests": {
            "html_sha256": _sha256_text(html),
            "review_json_sha256": hashlib.sha256(review_bytes).hexdigest(),
            "html_bytes": html_bytes,
            "review_json_bytes": len(review_bytes),
        },
        "audio": audio_report,
        "capabilities": {
            "inspect": {"available": True},
            "canonical_payload_capabilities_pinned": True,
            "note": (
                "The embedded canonical review payload keeps its byte-stable "
                "3ii.1-pinned capabilities block; `capabilities --json` and this "
                "command report their own truthful availability."
            ),
        },
        "side_effects": SIDE_EFFECT_NOTE,
        "engine": review_payload["engine"],
    }

    return (
        {
            "ok": True,
            "diagnostics": [d.as_dict() for d in audio_diagnostics],
            "artifacts": artifacts,
            "report": report,
        },
        0,
    )
