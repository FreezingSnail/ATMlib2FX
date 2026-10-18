"""Deterministic FX-jukebox image + index-header generator (ATMlib2FX-hlh.14).

Builds **one** FX data image holding every song in
``examples/music_authoring/catalog.json`` and emits the committed sketch index
header plus packing metadata::

    python3 tools/music_authoring/fx_jukebox.py \
        --out-dir build/fx-jukebox \
        --header examples/arduino/jukebox_fx/jukebox_fx_songs.h

Pipeline per song, in catalog order:

1. ``tools/atm-music build <song> --backend fx --out <lane>/songs/<id>`` writes
   the compact ``stream.bin`` (the pinned finite-v1/loop FX stream). Any
   rejected song aborts the run with a source-pointed report; there are no
   silent skips.
2. every ``stream.bin`` is handed to ``tools/fx_image`` in multi-stream mode
   (``--stream <name>:<path>``), which lays them out densely at
   data-section-relative offsets and emits ``fxdata.bin`` + ``meta.json`` +
   its own generated header.

The committed sketch header (``jukebox_fx_songs.h``) is the packer index
(offset/length/stream-loop flag per song) merged with the catalog display names
and folders (sketch PROGMEM) and the per-song loop length. Display text is
ASCII-folded exactly as ``jukebox.py`` folds the PROGMEM jukebox table.

Host-only / stdlib-only: nothing here changes AVR runtime, SRAM or flash.
Generated artifacts land under ``--out-dir`` except the header, which is copied
into the sketch folder so it can be committed.

The generator is split into pure planning/rendering helpers (``plan_songs``,
``assemble_records``, ``render_header``) and the subprocess orchestration
(``build_song_reports``, ``run_pack``); the helpers are exercised without a
toolchain by ``tests/music_authoring/test_fx_jukebox.py``.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

# This module lives inside the ``music_authoring`` package directory, so running
# it as a script would put that directory on ``sys.path[0]`` and shadow the
# standard-library ``inspect`` module that ``dataclasses`` imports (the package
# also ships an ``inspect.py``).  Drop the script's own directory and expose the
# package parent instead, exactly as ``jukebox.py`` does.  This must happen
# before ``dataclasses`` is imported.
_HERE = Path(__file__).resolve().parent
_TOOLS_DIR = _HERE.parent
sys.path = [p for p in sys.path if not p or Path(p).resolve() != _HERE]
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from dataclasses import dataclass  # noqa: E402

from music_authoring.jukebox import ascii_c_string, load_catalog  # noqa: E402

TOOL_NAME = "atm-music-fx-jukebox"
TOOL_VERSION = "1.0.0"

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CATALOG = REPO_ROOT / "examples/music_authoring/catalog.json"
DEFAULT_OUT_DIR = REPO_ROOT / "build/fx-jukebox"
DEFAULT_HEADER = REPO_ROOT / "examples/arduino/jukebox_fx/jukebox_fx_songs.h"
DEFAULT_ATM_MUSIC = REPO_ROOT / "tools/atm-music"
DEFAULT_FX_IMAGE = REPO_ROOT / "build/fx-port/image/fx_image"

# The runtime ring (src/atm_fx_compact.h ATM_FX_COMPACT_RING).  A song's loop
# region is exported resident only when it fits this many bytes; larger loops
# fall back to the finite 0xC0 arrangement.  The sketch must be built with the
# same ring, so the generator defaults to the runtime default.
DEFAULT_RING = 32

# Minimum catalog display facts the generator needs.
_REQUIRED_ENTRY_KEYS = ("id", "name", "source")


class FxJukeboxError(Exception):
    """Structured generator failure carrying an exit code."""

    def __init__(self, code, message, exit_code=2, song_id=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.exit_code = exit_code
        self.song_id = song_id


@dataclass(frozen=True)
class Plan:
    """One catalog song scheduled for export."""

    index: int
    id: str
    name: str
    folder: str
    source: str
    stream_name: str


@dataclass(frozen=True)
class SongRecord:
    """Packer index facts plus display facts for one song (catalog order)."""

    index: int
    id: str
    name: str
    folder: str
    source: str
    stream_name: str
    offset: int
    length: int
    stream_loop: bool
    loop: bool
    loop_tenths: int


# --- pure planning ----------------------------------------------------------


def is_identifier(name):
    """True when ``name`` is a C identifier (same check as ``jukebox.py``)."""
    if not name or not (name[0].isalpha() or name[0] == "_"):
        return False
    return all(ch.isalnum() or ch == "_" for ch in name)


def stream_name(song_id):
    """Sanitize a catalog id to the fx_image ``[A-Za-z0-9_]{1,63}`` name form."""
    cleaned = "".join(ch if (ch.isalnum() or ch == "_") else "_" for ch in song_id)
    cleaned = cleaned[:63]
    if not cleaned or cleaned[0].isdigit():
        cleaned = "_" + cleaned
    return cleaned


def plan_songs(entries, repo_root):
    """Validate catalog entries and return one ``Plan`` per song in order.

    Fails on a missing/invalid id, name or source and on duplicate ids, before
    any tool runs.
    """
    plans = []
    seen = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise FxJukeboxError(
                "CATALOG_INVALID", f"entry {index} is not an object"
            )
        for key in _REQUIRED_ENTRY_KEYS:
            if not isinstance(entry.get(key), str) or not entry[key]:
                raise FxJukeboxError(
                    "CATALOG_INVALID", f"entry {index} is missing a string {key!r}"
                )
        song_id = entry["id"]
        if not is_identifier(song_id):
            raise FxJukeboxError(
                "CATALOG_INVALID", f"entry id {song_id!r} is not a C identifier"
            )
        if song_id in seen:
            raise FxJukeboxError("DUPLICATE_ID", f"duplicate song id {song_id!r}")
        seen.add(song_id)
        folder = entry.get("folder") or entry.get("category") or "Other"
        plans.append(
            Plan(
                index=index,
                id=song_id,
                name=entry["name"],
                folder=folder,
                source=entry["source"],
                stream_name=stream_name(song_id),
            )
        )
    if not plans:
        raise FxJukeboxError("EMPTY_CATALOG", "catalog has no entries")
    return plans


def song_loop_tenths(report):
    """Loop length in tenths of a second from an ``atm-music`` build report."""
    clock = report.get("clock") or {}
    rate = clock.get("effective_tick_rate")
    ticks = report.get("total_ticks")
    if not rate or not ticks:
        raise FxJukeboxError(
            "BUILD_REPORT_INVALID",
            "build report is missing clock.effective_tick_rate or total_ticks",
        )
    return int(round(10 * ticks / rate))


def musical_loop(report):
    """True when the source score loops (``whole_song_loop`` feature present)."""
    return "whole_song_loop" in (report.get("required_features") or [])


def parse_fx_image_stdout(text):
    """Parse ``tools/fx_image`` ``key=value`` stdout into a dict (str values)."""
    facts = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or "=" not in line:
            continue
        key, value = line.split("=", 1)
        facts[key.strip()] = value.strip()
    return facts


def fx_image_layout(facts):
    """Extract (data_page, image_bytes, streams) from parsed packer facts."""
    try:
        count = int(facts["stream_count"])
        data_page = int(facts["data_page"])
        image_bytes = int(facts["image_len"])
    except (KeyError, ValueError) as exc:
        raise FxJukeboxError(
            "PACK_OUTPUT_INVALID", f"fx_image metadata is incomplete: {exc}"
        )
    streams = []
    for i in range(count):
        try:
            streams.append(
                {
                    "index": i,
                    "name": facts[f"stream{i}_name"],
                    "offset": int(facts[f"stream{i}_offset"]),
                    "length": int(facts[f"stream{i}_len"]),
                    "stream_loop": bool(int(facts[f"stream{i}_loop"])),
                }
            )
        except (KeyError, ValueError) as exc:
            raise FxJukeboxError(
                "PACK_OUTPUT_INVALID", f"fx_image stream {i} is incomplete: {exc}"
            )
    return data_page, image_bytes, streams


def assemble_records(plans, reports, layout):
    """Merge plans, per-song build reports and the packer layout (catalog order)."""
    data_page, image_bytes, streams = layout
    if len(streams) != len(plans):
        raise FxJukeboxError(
            "PACK_MISMATCH",
            f"packer emitted {len(streams)} streams for {len(plans)} songs",
        )
    records = []
    for plan, report, stream in zip(plans, reports, streams):
        if stream["name"] != plan.stream_name:
            raise FxJukeboxError(
                "PACK_MISMATCH",
                f"packer stream {stream['index']} is {stream['name']!r}, "
                f"expected {plan.stream_name!r}",
            )
        records.append(
            SongRecord(
                index=plan.index,
                id=plan.id,
                name=plan.name,
                folder=plan.folder,
                source=plan.source,
                stream_name=plan.stream_name,
                offset=stream["offset"],
                length=stream["length"],
                stream_loop=stream["stream_loop"],
                loop=musical_loop(report),
                loop_tenths=song_loop_tenths(report),
            )
        )
    return data_page, image_bytes, records


# --- header rendering -------------------------------------------------------


def _macro(record, suffix):
    return f"JUKEBOX_FX_SONG_{record.id.upper()}_{suffix}"


def render_header(records, catalog_sha256, data_page, image_bytes):
    """Render the deterministic committed sketch header."""
    guard = "ATMLIB_JUKEBOX_FX_SONGS_H"
    total_stream_bytes = sum(record.length for record in records)
    lines = [
        f"/* Generated by tools/music_authoring/fx_jukebox.py ({TOOL_NAME} {TOOL_VERSION}). Do not edit. */",
        f"/* One FX data image: {len(records)} catalog songs streamed from the FX data section. */",
        f"/* Stream bytes: {total_stream_bytes}; image bytes: {image_bytes}; data page: {data_page}. */",
        f"/* Catalog sha256: {catalog_sha256}. */",
        "/* Regenerate with:",
        " *   python3 tools/music_authoring/fx_jukebox.py",
        " */",
        "",
        f"#ifndef {guard}",
        f"#define {guard}",
        "",
        "#include <stdint.h>",
        "#include <avr/pgmspace.h>",
        "",
        f"#define JUKEBOX_FX_DATA_PAGE {data_page}u",
        f"#define JUKEBOX_FX_IMAGE_BYTES {image_bytes}u",
        f"#define JUKEBOX_FX_SONG_COUNT {len(records)}u",
        "",
    ]
    for record in records:
        lines.append(f'/* song {record.index}: "{record.id}" ({record.source}) */')
        lines.append(f"#define {_macro(record, 'OFFSET')} {record.offset}u")
        lines.append(f"#define {_macro(record, 'LENGTH')} {record.length}u")
        lines.append(f"#define {_macro(record, 'LOOP')} {1 if record.loop else 0}u")
        lines.append(
            f"#define {_macro(record, 'STREAM_LOOP')} {1 if record.stream_loop else 0}u"
        )
        lines.append(f"#define {_macro(record, 'LOOP_TENTHS')} {record.loop_tenths}u")
        lines.append("")

    for record in records:
        symbol = f"jukebox_fx_song_{record.id}"
        lines.append(
            f'const char {symbol}_name[] PROGMEM = "{ascii_c_string(record.name)}";'
        )
        lines.append(
            f'const char {symbol}_folder[] PROGMEM = "{ascii_c_string(record.folder)}";'
        )

    lines.extend(
        [
            "",
            "struct jukebox_fx_song {",
            "  const char *name;",
            "  const char *folder;",
            "  uint32_t offset;",
            "  uint32_t length;",
            "  uint16_t loop_tenths;",
            "  uint8_t loop;",
            "  uint8_t stream_loop;",
            "};",
            "",
            "const struct jukebox_fx_song jukebox_fx_songs[JUKEBOX_FX_SONG_COUNT] PROGMEM = {",
        ]
    )
    for record in records:
        symbol = f"jukebox_fx_song_{record.id}"
        lines.append(
            "    { "
            f"{symbol}_name, {symbol}_folder, "
            f"{_macro(record, 'OFFSET')}, {_macro(record, 'LENGTH')}, "
            f"{_macro(record, 'LOOP_TENTHS')}, {_macro(record, 'LOOP')}, "
            f"{_macro(record, 'STREAM_LOOP')} }},"
        )
    lines.extend(["};", "", f"#endif /* {guard} */", ""])
    return "\n".join(lines)


# --- subprocess orchestration ----------------------------------------------


def default_run(cmd, cwd):
    """Run ``cmd`` capturing text output (the default injectable runner)."""
    return subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True)


def _diagnostics_detail(envelope, stderr):
    """Human-readable detail from a failed ``atm-music`` envelope or stderr."""
    messages = []
    for diagnostic in envelope.get("diagnostics") or []:
        code = diagnostic.get("code", "?")
        message = diagnostic.get("message", "")
        messages.append(f"{code}: {message}")
    if not messages and stderr:
        messages.append(stderr.strip().splitlines()[-1] if stderr.strip() else "")
    return "; ".join(item for item in messages if item)


def _load_json_stdout(text, code, context):
    try:
        return json.loads(text)
    except (TypeError, ValueError) as exc:
        raise FxJukeboxError(code, f"{context}: cannot parse JSON output: {exc}")


def song_output_dir(out_dir, plan):
    return Path(out_dir) / "songs" / plan.id


def run_song_build(plan, out_dir, run, atm_music, repo_root, ring=None, streaming_loops=False):
    """Export one song with ``tools/atm-music build --backend fx``.

    Returns ``(report, warnings)``. A nonzero exit or a non-OK envelope raises
    ``FxJukeboxError`` naming the song — the adapter never fails silently.
    """
    lane = song_output_dir(out_dir, plan)
    cmd = [
        str(atm_music),
        "build",
        plan.source,
        "--backend",
        "fx",
        "--out",
        str(lane),
        "--json",
    ]
    if ring is not None:
        cmd += ["--ring", str(ring)]
    if streaming_loops:
        cmd += ["--streaming-loops"]
    proc = run(cmd, repo_root)
    if proc.returncode != 0:
        envelope = {}
        try:
            envelope = json.loads(proc.stdout or "{}")
        except ValueError:
            envelope = {}
        detail = _diagnostics_detail(envelope, proc.stderr)
        raise FxJukeboxError(
            "SONG_BUILD_FAILED",
            f"song {plan.id!r} rejected by the fx adapter: "
            f"{detail or 'no diagnostic'} (exit {proc.returncode})",
            exit_code=2,
            song_id=plan.id,
        )
    envelope = _load_json_stdout(
        proc.stdout, "SONG_BUILD_FAILED", f"song {plan.id!r}"
    )
    if not envelope.get("ok"):
        detail = _diagnostics_detail(envelope, proc.stderr)
        raise FxJukeboxError(
            "SONG_BUILD_FAILED",
            f"song {plan.id!r} rejected by the fx adapter: {detail or 'no diagnostic'}",
            exit_code=2,
            song_id=plan.id,
        )
    report = envelope.get("report") or {}
    warnings = [
        diagnostic
        for diagnostic in envelope.get("diagnostics") or []
        if diagnostic.get("severity") != "error"
    ]
    return report, warnings


def build_song_reports(plans, out_dir, run, atm_music, repo_root, ring=None, streaming_loops=False):
    """Export every song in order; return ``[(plan, report, warnings)]``.

    Aborts on the first rejected song (no silent skips); successfully exported
    songs are still on disk for inspection.
    """
    built = []
    for plan in plans:
        report, warnings = run_song_build(
            plan, out_dir, run, atm_music, repo_root, ring=ring,
            streaming_loops=streaming_loops,
        )
        built.append((plan, report, warnings))
    return built


def ensure_fx_image(run, repo_root, fx_image):
    """Return the fx_image binary path, building it if needed."""
    path = Path(fx_image)
    if path.is_file():
        return path
    proc = run(["make", "-C", "tools/fx_image"], repo_root)
    if proc.returncode != 0 or not path.is_file():
        raise FxJukeboxError(
            "FX_IMAGE_MISSING",
            f"fx_image not built ({path}); make -C tools/fx_image failed",
            exit_code=3,
        )
    return path


def run_pack(plans, out_dir, run, fx_image, repo_root):
    """Pack every stream into one image; return parsed packer facts."""
    out_dir = Path(out_dir)
    cmd = [str(fx_image)]
    for plan in plans:
        cmd += ["--stream", f"{plan.stream_name}:{song_output_dir(out_dir, plan) / 'stream.bin'}"]
    cmd += [
        "--out",
        str(out_dir / "fxdata.bin"),
        "--meta",
        str(out_dir / "meta.json"),
        "--header",
        str(out_dir / "fx_image_config.h"),
    ]
    proc = run(cmd, repo_root)
    if proc.returncode != 0:
        raise FxJukeboxError(
            "PACK_FAILED",
            f"fx_image failed (exit {proc.returncode}): {(proc.stderr or '').strip()}",
            exit_code=3,
        )
    return parse_fx_image_stdout(proc.stdout)


def write_json(path, payload):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(
        json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
    )


def records_payload(records, data_page, image_bytes, catalog_sha256, warnings):
    """Deterministic per-song summary written beside the image."""
    return {
        "tool": {"name": TOOL_NAME, "version": TOOL_VERSION},
        "catalog_sha256": catalog_sha256,
        "data_page": data_page,
        "image_bytes": image_bytes,
        "song_count": len(records),
        "stream_bytes": sum(record.length for record in records),
        "loop_exported_count": sum(1 for record in records if record.stream_loop),
        "songs": [
            {
                "index": record.index,
                "id": record.id,
                "name": record.name,
                "folder": record.folder,
                "source": record.source,
                "stream_name": record.stream_name,
                "offset": record.offset,
                "length": record.length,
                "loop": record.loop,
                "stream_loop": record.stream_loop,
                "loop_tenths": record.loop_tenths,
            }
            for record in records
        ],
        "warnings": warnings,
    }


def generate(
    *,
    catalog_path,
    out_dir,
    header_path,
    run,
    atm_music,
    fx_image,
    repo_root,
    ring=None,
    streaming_loops=False,
    write=True,
):
    """Full pipeline: plan -> export -> pack -> records -> header.

    With ``write=False`` nothing is written (useful for a dry run/verify).
    Returns the summary payload.
    """
    document, catalog_sha256, _raw = load_catalog(str(catalog_path))
    plans = plan_songs(document["entries"], Path(repo_root))
    fx_image = ensure_fx_image(run, Path(repo_root), fx_image)

    built = build_song_reports(
        plans, out_dir, run, atm_music, Path(repo_root), ring=ring,
        streaming_loops=streaming_loops,
    )
    warnings = []
    for plan, _report, song_warnings in built:
        for diagnostic in song_warnings:
            warnings.append(
                {"song": plan.id, "code": diagnostic.get("code"), "message": diagnostic.get("message")}
            )

    facts = run_pack(plans, out_dir, run, fx_image, Path(repo_root))
    data_page, image_bytes, records = assemble_records(
        plans, [report for (_plan, report, _w) in built], fx_image_layout(facts)
    )
    header = render_header(records, catalog_sha256, data_page, image_bytes)

    payload = records_payload(
        records, data_page, image_bytes, catalog_sha256, warnings
    )
    if write:
        Path(header_path).parent.mkdir(parents=True, exist_ok=True)
        Path(header_path).write_text(header, encoding="utf-8")
        write_json(Path(out_dir) / "songs.json", payload)
    return payload


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog=TOOL_NAME,
        description=(
            "Build one FX data image with every catalog song and regenerate the "
            "jukebox_fx sketch index header."
        ),
    )
    parser.add_argument("--catalog", default=str(DEFAULT_CATALOG))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--header", default=str(DEFAULT_HEADER))
    parser.add_argument(
        "--ring",
        type=int,
        default=DEFAULT_RING,
        help=(
            "FX admission ring in bytes (power of two, 5..256). Must match the "
            "sketch ATM_FX_COMPACT_RING; loops that do not fit fall back finite."
        ),
    )
    parser.add_argument("--atm-music", default=str(DEFAULT_ATM_MUSIC))
    parser.add_argument(
        "--streaming-loops",
        action="store_true",
        help=(
            "ask the adapter for streaming loops (region larger than the ring "
            "re-fetches from FX flash); requires ATM_FX_COMPACT_LOOP_STREAMING "
            "in the sketch build and a decoder with the hlh.16 extension."
        ),
    )
    parser.add_argument("--fx-image", default=str(DEFAULT_FX_IMAGE))
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    parser.add_argument(
        "--json", action="store_true", help="ignored; stdout is always JSON."
    )
    args = parser.parse_args(argv)

    try:
        payload = generate(
            catalog_path=args.catalog,
            out_dir=args.out_dir,
            header_path=args.header,
            run=default_run,
            atm_music=args.atm_music,
            fx_image=args.fx_image,
            repo_root=args.repo_root,
            ring=args.ring,
            streaming_loops=args.streaming_loops,
            write=True,
        )
    except FxJukeboxError as exc:
        print(
            json.dumps(
                {"ok": False, "code": exc.code, "song": exc.song_id, "message": exc.message}
            )
        )
        return exc.exit_code

    print(json.dumps({"ok": True, **payload}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
