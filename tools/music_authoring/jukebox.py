"""Build-time Arduboy jukebox header generator (ATMlib2FX-dch).

``python3 tools/music_authoring/jukebox.py --set gatherer \
    --out examples/arduino/jukebox/songs_gatherer.h --json``

The Arduboy FX image cannot hold every example song at once.  All twenty
catalog scores total 30,396 bytes of PROGMEM asset data alone, while the
``arduboy-homemade:avr:arduboy-fx`` flash cap is 29,696 bytes (a measured
example shell + engine adds another ~8.2 kB).  This generator therefore emits
one **deterministic** C header per build-time set:

* ``gatherer``  - Creature Gatherer + Authoring Examples (14 songs).
* ``frontiers`` - Creature Frontiers (6 songs).
* ``all``       - every catalog song (does not fit; useful for reporting).

Each song record is rebuilt with the canonical host pipeline
(``load_and_validate`` -> ``lower`` -> ``progmem_backend.serialize``); the
serializer is pure, so nothing is written except the requested header.  Songs
appear in catalog order and no timestamps are emitted, so re-running the tool
produces byte-identical output.

Host-only / stdlib-only: nothing here changes AVR runtime, SRAM or flash.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

# This module lives inside the ``music_authoring`` package directory, so running
# it as a script would put that directory on ``sys.path[0]`` and shadow the
# standard-library ``inspect`` module that ``dataclasses`` imports (the package
# also ships an ``inspect.py``).  Drop the script's own directory and expose the
# package parent instead, exactly as ``library_player.py`` does.
_HERE = Path(__file__).resolve().parent
_TOOLS_DIR = _HERE.parent
sys.path = [p for p in sys.path if not p or Path(p).resolve() != _HERE]
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from music_authoring.lower import lower  # noqa: E402
from music_authoring.progmem_backend import serialize  # noqa: E402
from music_authoring.validate import load_and_validate  # noqa: E402

TOOL_NAME = "atm-music-jukebox"
TOOL_VERSION = "1.0.0"
CATALOG_FORMAT = "atmlib-song-library-catalog"

DEFAULT_BUDGET_BYTES = 29696
# Measured ``examples/arduino/songs/song01`` shell + engine is 8,196 bytes; the
# menu/UI allowance brings the documented shell estimate to 10,500 bytes.
SHELL_ESTIMATE = 10500
BYTES_PER_LINE = 12

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CATALOG = REPO_ROOT / "examples/music_authoring/catalog.json"
DEFAULT_OUT_DIR = REPO_ROOT / "examples/arduino/jukebox"

# Set definition: id is the numeric build tag, folders selects catalog entries
# (``None`` means every entry).  ``label`` is the on-board set banner.
SET_ORDER = ("gatherer", "frontiers", "all")
SETS = {
    "gatherer": {
        "id": 1,
        "label": "Creature Gatherer + Examples",
        "folders": ("Creature Gatherer", "Authoring Examples"),
    },
    "frontiers": {
        "id": 2,
        "label": "Creature Frontiers",
        "folders": ("Creature Frontiers",),
    },
    "all": {
        "id": 0,
        "label": "All songs",
        "folders": None,
    },
}


class JukeboxError(Exception):
    """Structured generator failure carrying an exit code."""

    def __init__(self, code: str, message: str, exit_code: int = 2):
        super().__init__(message)
        self.code = code
        self.message = message
        self.exit_code = exit_code


# --- display-text folding ---------------------------------------------------

# Smart punctuation -> ASCII, so the on-board 6x8 font renders clean glyphs.
_FOLD = {
    0x2014: "-",   # em dash
    0x2013: "-",   # en dash
    0x2018: "'",   # left single quote
    0x2019: "'",   # right single quote
    0x201C: '"',   # left double quote
    0x201D: '"',   # right double quote
    0x2026: "...",  # horizontal ellipsis
}


def fold_text(text: str) -> str:
    """ASCII-fold a display string (keep 0x20..0x7E, else '?')."""
    out: list[str] = []
    for ch in text:
        code_point = ord(ch)
        if code_point in _FOLD:
            out.append(_FOLD[code_point])
        elif 0x20 <= code_point <= 0x7E:
            out.append(ch)
        else:
            out.append("?")
    return "".join(out)


def c_escape(text: str) -> str:
    """Escape backslash and double quote for a C string literal body."""
    return text.replace("\\", "\\\\").replace('"', '\\"')


def ascii_c_string(text: str) -> str:
    """Fold to ASCII, then escape for inclusion inside a C string literal."""
    return c_escape(fold_text(text))


def _is_identifier(name: str) -> bool:
    if not name or not (name[0].isalpha() or name[0] == "_"):
        return False
    return all(ch.isalnum() or ch == "_" for ch in name)


# --- catalog + records ------------------------------------------------------


def load_catalog(catalog_path: str) -> tuple[dict, str, bytes]:
    """Read a catalog; return (document, sha256_hex, raw_bytes)."""
    path = Path(catalog_path)
    if not path.is_file():
        raise JukeboxError("CATALOG_MISSING", f"catalog {path} not found")
    raw = path.read_bytes()
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise JukeboxError("CATALOG_INVALID", f"cannot read catalog {path}: {exc}")
    if data.get("format") != CATALOG_FORMAT:
        raise JukeboxError(
            "CATALOG_INVALID",
            f"catalog format is {data.get('format')!r}, expected {CATALOG_FORMAT!r}",
        )
    entries = data.get("entries")
    if not isinstance(entries, list) or not entries:
        raise JukeboxError("CATALOG_INVALID", "catalog has no entries")
    return data, hashlib.sha256(raw).hexdigest(), raw


def validate_set_name(set_name: str) -> None:
    """Raise ``INVALID_SET`` unless ``set_name`` is a known set."""
    if set_name not in SETS:
        raise JukeboxError(
            "INVALID_SET",
            f"unknown set {set_name!r}; expected one of {', '.join(SET_ORDER)}",
        )


def select_entries(entries: list[dict], set_name: str) -> list[dict]:
    """Select catalog entries for a named set, preserving catalog order."""
    validate_set_name(set_name)
    folders = SETS[set_name]["folders"]
    if folders is None:
        selected = list(entries)
    else:
        selected = [
            entry
            for entry in entries
            if (entry.get("folder") or entry.get("category")) in folders
        ]
    if not selected:
        raise JukeboxError("EMPTY_SET", f"set {set_name!r} matched no catalog entries")
    return selected


def build_song_record(entry: dict, repo_root: Path, index: int) -> dict:
    """Rebuild one PROGMEM score and capture its display metadata."""
    for key in ("id", "name", "source"):
        if not isinstance(entry.get(key), str) or not entry[key]:
            raise JukeboxError(
                "CATALOG_INVALID", f"entry {index} is missing a string {key!r}"
            )
    if not _is_identifier(entry["id"]):
        raise JukeboxError(
            "CATALOG_INVALID", f"entry id {entry['id']!r} is not a C identifier"
        )

    source = entry["source"]
    source_abs = source if os.path.isabs(source) else os.path.join(str(repo_root), source)
    score, diagnostics = load_and_validate(source_abs)
    if score is None:
        first = diagnostics[0] if diagnostics else None
        exit_code = 3 if any(d.code == "IO_ERROR" for d in diagnostics) else 2
        raise JukeboxError(
            "SOURCE_INVALID",
            f"cannot validate {entry['id']!r}: {first.message if first else 'invalid score'}",
            exit_code=exit_code,
        )

    lowered = lower(score)
    result = serialize(score, lowered, "")
    loop_tenths = int(round(10 * lowered.total_ticks / score.clock.effective_tick_rate))
    return {
        "id": entry["id"],
        "name": entry["name"],
        "folder": entry.get("folder") or entry.get("category") or "Other",
        "bytes": len(result.score_bytes),
        "loop_tenths": loop_tenths,
        "source": source,
        "score_bytes": result.score_bytes,
    }


def build_songs(entries: list[dict], repo_root: Path) -> list[dict]:
    """Build every selected song, rejecting duplicate ids."""
    records: list[dict] = []
    seen: set[str] = set()
    for index, entry in enumerate(entries):
        record = build_song_record(entry, repo_root, index)
        if record["id"] in seen:
            raise JukeboxError("DUPLICATE_ID", f"duplicate song id {record['id']!r}")
        seen.add(record["id"])
        records.append(record)
    return records


# --- header rendering -------------------------------------------------------


def _include_guard(set_name: str) -> str:
    return "ATMLIB_JUKEBOX_SONGS_" + set_name.upper().replace("-", "_") + "_H"


def render_header(
    set_name: str,
    label: str,
    records: list[dict],
    catalog_sha256: str,
    set_id: int | None = None,
) -> str:
    """Render one deterministic C header for the given song records."""
    if set_id is None:
        set_id = SETS.get(set_name, {}).get("id", 0)
    total_bytes = sum(record["bytes"] for record in records)
    guard = _include_guard(set_name)

    lines: list[str] = [
        f"/* Generated by tools/music_authoring/jukebox.py ({TOOL_NAME} {TOOL_VERSION}). Do not edit. */",
        f"/* Set: {set_name} - {fold_text(label)}; {len(records)} songs, {total_bytes} score bytes. */",
        f"/* Catalog sha256: {catalog_sha256}. */",
        "",
        f"#ifndef {guard}",
        f"#define {guard}",
        "",
        "#include <stdint.h>",
        "#include <avr/pgmspace.h>",
        "",
        f"#define JUKEBOX_SET_ID {set_id}",
        f'#define JUKEBOX_SET_LABEL "{ascii_c_string(label)}"',
        f"#define JUKEBOX_SONG_COUNT {len(records)}u",
        "",
    ]

    for record in records:
        sym = f"jukebox_song_{record['id']}"
        lines.append(f'const char {sym}_name[] PROGMEM = "{ascii_c_string(record["name"])}";')
        lines.append(
            f'const char {sym}_folder[] PROGMEM = "{ascii_c_string(record["folder"])}";'
        )
        data = record["score_bytes"]
        lines.append(f"const uint8_t {sym}_score[] PROGMEM = {{")
        for start in range(0, len(data), BYTES_PER_LINE):
            chunk = data[start : start + BYTES_PER_LINE]
            rendered = ", ".join(f"0x{byte:02x}" for byte in chunk)
            suffix = "," if start + BYTES_PER_LINE < len(data) else ""
            lines.append(f"    {rendered}{suffix}")
        lines.append("};")
        lines.append("")

    lines.extend(
        [
            "struct jukebox_song {",
            "  const char *name;",
            "  const char *folder;",
            "  const uint8_t *score;",
            "  uint16_t bytes;",
            "  uint16_t loop_tenths;",
            "};",
            "",
            "const struct jukebox_song jukebox_songs[JUKEBOX_SONG_COUNT] PROGMEM = {",
        ]
    )
    for record in records:
        sym = f"jukebox_song_{record['id']}"
        lines.append(
            f"    {{ {sym}_name, {sym}_folder, {sym}_score, "
            f"{record['bytes']}u, {record['loop_tenths']}u }},"
        )
    lines.extend(["};", "", f"#endif /* {guard} */", ""])
    return "\n".join(lines)


def _json_song(record: dict) -> dict:
    """Project a record onto the documented ``--json`` song fields."""
    return {
        "id": record["id"],
        "name": record["name"],
        "folder": record["folder"],
        "bytes": record["bytes"],
        "loop_tenths": record["loop_tenths"],
        "source": record["source"],
    }


# --- top-level driver -------------------------------------------------------


def generate(
    set_name: str,
    entries: list[dict],
    catalog_sha256: str,
    repo_root: Path,
) -> tuple[list[dict], str, str]:
    """Select, build and render; return (records, header_text, label)."""
    selected = select_entries(entries, set_name)
    records = build_songs(selected, repo_root)
    label = SETS.get(set_name, {}).get("label", "Songs")
    text = render_header(set_name, label, records, catalog_sha256)
    return records, text, label


def run(
    *,
    set_name: str,
    out_path: str,
    catalog_path: str,
    repo_root: Path,
    budget_bytes: int = DEFAULT_BUDGET_BYTES,
) -> tuple[dict, int]:
    """Generate one header from one catalog; return (payload, exit_code)."""
    try:
        catalog, catalog_sha256, _ = load_catalog(catalog_path)
    except JukeboxError as exc:
        return (
            {"ok": False, "set": set_name, "code": exc.code, "message": exc.message},
            exc.exit_code,
        )
    return _render_to(
        set_name=set_name,
        out_path=out_path,
        entries=catalog["entries"],
        catalog_sha256=catalog_sha256,
        repo_root=repo_root,
        budget_bytes=budget_bytes,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog=TOOL_NAME,
        description="Generate a deterministic Arduboy jukebox song header for one build set.",
    )
    parser.add_argument("--set", required=True, help="Song set: gatherer, frontiers or all.")
    parser.add_argument("--out", required=True, help="Header path to write (e.g. songs_gatherer.h).")
    parser.add_argument(
        "--catalog",
        action="append",
        default=None,
        help="Catalog JSON (repeatable; defaults to examples/music_authoring/catalog.json).",
    )
    parser.add_argument("--repo-root", default=None, help="Base directory for relative source paths.")
    parser.add_argument("--budget-bytes", type=int, default=DEFAULT_BUDGET_BYTES)
    parser.add_argument("--json", action="store_true", help="Ignored; stdout is always one JSON document.")
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve() if args.repo_root else REPO_ROOT

    # Unknown set / catalog problems must fail before any file is written.
    try:
        validate_set_name(args.set)
    except JukeboxError as exc:
        print(json.dumps({"ok": False, "set": args.set, "code": exc.code, "message": exc.message}))
        return exc.exit_code

    entries: list[dict] = []
    digest = hashlib.sha256()
    try:
        for catalog_path in (args.catalog or [str(DEFAULT_CATALOG)]):
            catalog, _, raw = load_catalog(catalog_path)
            entries.extend(catalog["entries"])
            digest.update(raw)
    except JukeboxError as exc:
        print(json.dumps({"ok": False, "set": args.set, "code": exc.code, "message": exc.message}))
        return exc.exit_code

    payload, code = _render_to(
        set_name=args.set,
        out_path=args.out,
        entries=entries,
        catalog_sha256=digest.hexdigest(),
        repo_root=repo_root,
        budget_bytes=args.budget_bytes,
    )
    print(json.dumps(payload, ensure_ascii=True, sort_keys=False))
    return code


def _render_to(
    *,
    set_name: str,
    out_path: str,
    entries: list[dict],
    catalog_sha256: str,
    repo_root: Path,
    budget_bytes: int,
) -> tuple[dict, int]:
    try:
        records, text, _ = generate(set_name, entries, catalog_sha256, repo_root)
    except JukeboxError as exc:
        return (
            {"ok": False, "set": set_name, "code": exc.code, "message": exc.message},
            exc.exit_code,
        )

    song_bytes = sum(record["bytes"] for record in records)
    out = Path(out_path)
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
    except OSError as exc:
        return (
            {"ok": False, "set": set_name, "code": "WRITE_ERROR", "message": f"cannot write {out}: {exc}"},
            3,
        )

    return (
        {
            "ok": True,
            "set": set_name,
            "out": str(out),
            "song_count": len(records),
            "song_bytes": song_bytes,
            "budget_bytes": budget_bytes,
            "fits": song_bytes + SHELL_ESTIMATE <= budget_bytes,
            "songs": [_json_song(record) for record in records],
        },
        0,
    )


if __name__ == "__main__":
    raise SystemExit(main())
