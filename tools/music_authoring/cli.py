"""Command-line interface for the compact FX music authoring contract.

stdout is always a single JSON document. Human-readable progress and errors go
to stderr. Exit codes: 0 success, 2 invalid score or unsupported capability,
3 tool or build failure.
"""

from __future__ import annotations

import argparse
import json
import sys

from .fx_backend import FxAdmissionError, capability_summary
from .fx_backend import diagnostics_for as fx_diagnostics_for
from .lower import validate_summary
from .score import Diagnostic, TOOL_NAME, TOOL_VERSION
from .validate import load_and_validate

BACKEND = "fx"


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


def _backend_unavailable(backend: str, capability: str) -> dict:
    return _envelope(
        False,
        [
            Diagnostic(
                "BACKEND_UNAVAILABLE",
                "",
                f"Only the compact FX backend is supported; got {backend!r} for {capability}.",
                "Use --backend fx (the default).",
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
    ordered = {
        "ok": payload.pop("ok"),
        "diagnostics": payload.pop("diagnostics"),
        "artifacts": payload.pop("artifacts"),
    }
    ordered.update(payload)
    _emit(ordered)
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    if args.backend != BACKEND:
        _emit(_backend_unavailable(args.backend, "validate"))
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
    if args.backend != BACKEND:
        _emit(_backend_unavailable(args.backend, "build"))
        return 2
    score, diagnostics, code = _load(args.song)
    if score is None:
        _emit(_envelope(False, diagnostics))
        return code

    from . import fx_backend
    from .lower import lower

    try:
        lowered = lower(score)
        if args.ring is None:
            result, artifacts = fx_backend.build(
                score, lowered, args.out, streaming_loops=args.streaming_loops
            )
        else:
            result, artifacts = fx_backend.build(
                score, lowered, args.out, ring=args.ring,
                streaming_loops=args.streaming_loops,
            )
        warnings = list(result.diagnostics)
    except FxAdmissionError as exc:
        _emit(_envelope(False, fx_diagnostics_for(exc)))
        return 2
    except OSError as exc:
        _emit(_io_failure(f"Cannot write build artifacts: {exc}"))
        return 3
    except Exception as exc:  # pragma: no cover - defensive tool failure
        _emit(_io_failure(f"FX build failed: {exc}"))
        return 3

    for diagnostic in warnings:
        _log(f"warning {diagnostic.code}: {diagnostic.message}")
    _log(f"wrote {artifacts['stream.bin']} ({result.report['stream']['bytes']} bytes)")
    _emit(
        _envelope(
            True,
            warnings,
            artifacts=artifacts,
            report=result.report,
        )
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=TOOL_NAME,
        description=(
            f"ATMlib compact FX score validator and deterministic stream exporter "
            f"({TOOL_NAME} {TOOL_VERSION})."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    capabilities = sub.add_parser("capabilities", help="report implemented features")
    capabilities.add_argument("--json", action="store_true", help="emit JSON (always on)")
    capabilities.set_defaults(func=cmd_capabilities)

    validate = sub.add_parser("validate", help="validate a score")
    validate.add_argument("song")
    validate.add_argument("--backend", default=BACKEND)
    validate.add_argument("--json", action="store_true", help="emit JSON (always on)")
    validate.set_defaults(func=cmd_validate)

    build = sub.add_parser("build", help="validate and export a compact FX stream")
    build.add_argument("song")
    build.add_argument("--backend", default=BACKEND)
    build.add_argument("--out", required=True)
    build.add_argument(
        "--ring",
        type=int,
        default=None,
        help="FX admission ring in bytes (power of two, 5..256; default 32).",
    )
    build.add_argument(
        "--streaming-loops",
        action="store_true",
        dest="streaming_loops",
        help=(
            "Advertise a decoder that streams loop regions larger than the ring "
            "(ATMlib2FX-hlh.16). Off by default: a larger region falls back to "
            "the finite 0xC0 stream with LOOP_NOT_EXPORTED."
        ),
    )
    build.add_argument("--json", action="store_true", help="emit JSON (always on)")
    build.set_defaults(func=cmd_build)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
