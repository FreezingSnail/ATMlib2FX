"""Command-line interface for the v1 ATMlib music authoring contract.

stdout is always a single JSON document.  Human-readable progress and errors
go to stderr.  Exit codes: 0 success, 2 invalid score or unsupported capability,
3 tool or build failure.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from .lower import validate_summary
from .progmem_backend import (
    BackendLimit,
    build as build_backend,
    capability_summary,
    diagnostics_for,
)
from .score import Diagnostic, Score, TOOL_NAME, TOOL_VERSION
from .validate import load_and_validate


def _envelope(
    ok: bool,
    diagnostics: list[Diagnostic],
    artifacts: dict | None = None,
    **extra,
) -> dict:
    result = {
        "ok": ok,
        "diagnostics": [item.as_dict() for item in diagnostics],
        "artifacts": artifacts or {},
    }
    result.update(extra)
    return result


def _emit(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=True, sort_keys=False))


def _log(message: str) -> None:
    print(message, file=sys.stderr)


def _io_failure(message: str) -> dict:
    return _envelope(
        False,
        [Diagnostic("TOOL_ERROR", "", message, "Check the output directory and retry.")],
    )


def _backend_unavailable(backend: str) -> dict:
    return _envelope(
        False,
        [
            Diagnostic(
                "BACKEND_UNAVAILABLE",
                "",
                (
                    f"Backend {backend!r} is not implemented. The FX playback "
                    "contract is pending ATMlib2FX-hlh.2 (owned by ATMlib2FX-3ii.3)."
                ),
                "Use --backend progmem; read capabilities for availability.",
            )
        ],
    )


def _load(path: str):
    score, diagnostics = load_and_validate(path)
    if score is None:
        return None, diagnostics, 3 if any(d.code == "IO_ERROR" for d in diagnostics) else 2
    return score, diagnostics, 0


def cmd_capabilities(_args: argparse.Namespace) -> int:
    payload = capability_summary()
    payload.update(_envelope(True, []))
    # Reorder keys so the common envelope leads; values are unchanged.
    ordered = {
        "ok": payload.pop("ok"),
        "diagnostics": payload.pop("diagnostics"),
        "artifacts": payload.pop("artifacts"),
    }
    ordered.update(payload)
    _emit(ordered)
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    if args.backend != "progmem":
        _emit(_backend_unavailable(args.backend))
        return 2
    score, diagnostics, code = _load(args.song)
    if score is None:
        _emit(_envelope(False, diagnostics))
        return code
    from .lower import lower

    try:
        lowered = lower(score)
    except Exception as exc:  # pragma: no cover - defensive tool failure
        _emit(_io_failure(f"Lowering failed: {exc}"))
        return 3
    _emit(_envelope(True, [], report=validate_summary(score, lowered)))
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    if args.backend != "progmem":
        _emit(_backend_unavailable(args.backend))
        return 2
    score, diagnostics, code = _load(args.song)
    if score is None:
        _emit(_envelope(False, diagnostics))
        return code

    from .lower import lower

    try:
        lowered = lower(score)
        result, artifacts = build_backend(score, lowered, args.out)
    except BackendLimit as exc:
        _emit(_envelope(False, diagnostics_for(exc)))
        return 2
    except OSError as exc:
        _emit(_io_failure(f"Cannot write build artifacts: {exc}"))
        return 3
    except Exception as exc:  # pragma: no cover - defensive tool failure
        _emit(_io_failure(f"PROGMEM build failed: {exc}"))
        return 3

    _log(f"wrote {artifacts['score.bin']} ({result.report['score']['bytes']} bytes)")
    _emit(
        _envelope(
            True,
            [],
            artifacts=artifacts,
            report=result.report,
        )
    )
    return 0


def cmd_render(args: argparse.Namespace) -> int:
    if args.backend != "progmem":
        _emit(_backend_unavailable(args.backend))
        return 2
    from .render import render

    payload, code = render(
        args.song,
        backend=args.backend,
        seconds=args.seconds,
        out_dir=args.out,
        canonical_review=args.review,
    )
    _emit(payload)
    return code


def cmd_inspect(args: argparse.Namespace) -> int:
    from .inspect import inspect as inspect_score

    payload, code = inspect_score(
        args.song,
        args.out,
        audio_preview=args.audio_preview,
    )
    for diagnostic in payload.get("diagnostics", []):
        if diagnostic.get("severity") == "warning":
            _log(f"warning {diagnostic['code']}: {diagnostic['message']}")
    _emit(payload)
    return code


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=TOOL_NAME,
        description=(
            f"ATMlib v1 music score validator and deterministic PROGMEM exporter "
            f"({TOOL_NAME} {TOOL_VERSION})."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    capabilities = sub.add_parser("capabilities", help="report implemented features")
    capabilities.add_argument("--json", action="store_true", help="emit JSON (always on)")
    capabilities.set_defaults(func=cmd_capabilities)

    validate = sub.add_parser("validate", help="validate a score")
    validate.add_argument("song")
    validate.add_argument("--backend", default="progmem")
    validate.add_argument("--json", action="store_true", help="emit JSON (always on)")
    validate.set_defaults(func=cmd_validate)

    build = sub.add_parser("build", help="validate and export PROGMEM artifacts")
    build.add_argument("song")
    build.add_argument("--backend", default="progmem")
    build.add_argument("--out", required=True)
    build.add_argument("--json", action="store_true", help="emit JSON (always on)")
    build.set_defaults(func=cmd_build)

    render = sub.add_parser(
        "render", help="render a bounded WAV preview from real AVR playback"
    )
    render.add_argument("song")
    render.add_argument("--backend", default="progmem")
    render.add_argument(
        "--seconds", type=float, default=None,
        help=f"bounded render length in seconds (default {60}, max {300})",
    )
    render.add_argument("--out", required=True)
    render.add_argument(
        "--review", default=None,
        help="canonical review.json to align source/event digests against",
    )
    render.add_argument("--json", action="store_true", help="emit JSON (always on)")
    render.set_defaults(func=cmd_render)

    inspect = sub.add_parser(
        "inspect", help="write a standalone offline HTML/JS track review"
    )
    inspect.add_argument("song")
    inspect.add_argument("--out", required=True, help="path to the review .html file")
    inspect.add_argument(
        "--audio-preview", default=None, dest="audio_preview",
        help="render output directory (report + matching WAV) to embed and audition",
    )
    inspect.add_argument("--json", action="store_true", help="emit JSON (always on)")
    inspect.set_defaults(func=cmd_inspect)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
