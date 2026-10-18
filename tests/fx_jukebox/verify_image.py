#!/usr/bin/env python3
"""Verify the committed FX jukebox image, index header and adapter reports.

This is the host-side half of the ATMlib2FX-hlh.15 evidence. It checks the
committed artifacts only (no toolchain, no network):

* the committed header carries every catalog song, in catalog order, with the
  offset/length/loop/stream-loop facts from the packer and the per-song adapter
  build report;
* the image extents and page arithmetic stay inside the 16 MiB FX chip and add
  the data page exactly once;
* streams are densely packed (no overlap, no unaccounted gaps) and each image
  slice is byte-identical to the adapter's ``stream.bin``;
* every per-song FX build succeeded with streaming loops enabled, exported a
  ``0xC1`` loop stream, and produced no diagnostics (in particular no
  ``LOOP_NOT_EXPORTED`` warning).

It also renders a capacity table (stream bytes vs the PROGMEM jukebox asset
bytes) and the artifact hash manifest under the requested output directory.

Usage (from the repository root)::

    python3 tests/fx_jukebox/verify_image.py

Exit code 0 means every check passed; 1 means at least one failure. Defaults
read the committed header plus ``build/fx-jukebox/`` outputs written by
``tools/music_authoring/fx_jukebox.py``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_IMAGE = REPO_ROOT / "build/fx-jukebox/fxdata.bin"
DEFAULT_META = REPO_ROOT / "build/fx-jukebox/meta.json"
DEFAULT_SONGS = REPO_ROOT / "build/fx-jukebox/songs.json"
DEFAULT_HEADER = REPO_ROOT / "examples/arduino/jukebox_fx/jukebox_fx_songs.h"
DEFAULT_CATALOG = REPO_ROOT / "examples/music_authoring/catalog.json"
DEFAULT_PROGMEM_GATHERER = REPO_ROOT / "examples/arduino/jukebox/songs_gatherer.h"
DEFAULT_PROGMEM_FRONTIERS = REPO_ROOT / "examples/arduino/jukebox/songs_frontiers.h"
DEFAULT_OUT = REPO_ROOT / "build/fx-jukebox/verify"

CHIP_BYTES = 16 * 1024 * 1024
PAGE_BYTES = 256
LOOP_MAGIC = 0xC1
FINITE_MAGIC = 0xC0


class Checks:
    def __init__(self):
        self.failures = []
        self.passes = 0

    def check(self, ok, label, detail=""):
        if ok:
            self.passes += 1
            print(f"PASS {label}" + (f" ({detail})" if detail else ""))
        else:
            self.failures.append(label)
            print(f"FAIL {label}" + (f" ({detail})" if detail else ""))
        return ok

    def summary(self):
        return self.passes, len(self.failures)


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def parse_header(path):
    """Return the generated header's macros and ordered song comments."""
    text = Path(path).read_text(encoding="utf-8")
    macros = {}
    for name, value in re.findall(
        r"^#define\s+(JUKEBOX_FX_[A-Z0-9_]+)\s+(\d+)u?\s*$", text, re.MULTILINE
    ):
        macros[name] = int(value)
    comments = [
        {"index": int(index), "id": song_id, "source": source}
        for index, song_id, source in re.findall(
            r'^/\* song (\d+): "([^"]+)" \(([^)]+)\) \*/$', text, re.MULTILINE
        )
    ]
    return macros, comments


def parse_progmem_sizes(path):
    """Count the PROGMEM score bytes per song in a PROGMEM jukebox header."""
    path = Path(path)
    if not path.is_file():
        return {}
    text = Path(path).read_text(encoding="utf-8")
    sizes = {}
    for match in re.finditer(
        r"const uint8_t jukebox_song_([a-z0-9_]+)_score\[\] PROGMEM = \{(.*?)\};",
        text,
        re.DOTALL,
    ):
        sizes[match.group(1)] = len(
            re.findall(r"0x[0-9a-fA-F]{2}", match.group(2))
        )
    return sizes


def parse_compile_report(path):
    """Pull the arduino-cli program/SRAM totals from a saved compile log."""
    path = Path(path)
    if not path.is_file():
        return None
    text = Path(path).read_text(encoding="utf-8")
    program = re.search(r"Sketch uses ([\d,]+) bytes", text)
    sram = re.search(r"Global variables use ([\d,]+) bytes", text)
    if not program or not sram:
        return None
    return {
        "program": int(program.group(1).replace(",", "")),
        "sram": int(sram.group(1).replace(",", "")),
        "source": str(path),
    }


def load_compile_report(paths):
    """First parseable arduino-cli log from ``paths`` (newest lane first)."""
    for path in paths:
        facts = parse_compile_report(Path(path))
        if facts:
            return facts
    return {}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default=str(DEFAULT_IMAGE))
    parser.add_argument("--meta", default=str(DEFAULT_META))
    parser.add_argument("--songs", default=str(DEFAULT_SONGS))
    parser.add_argument("--header", default=str(DEFAULT_HEADER))
    parser.add_argument("--catalog", default=str(DEFAULT_CATALOG))
    parser.add_argument("--progmem-gatherer", default=str(DEFAULT_PROGMEM_GATHERER))
    parser.add_argument("--progmem-frontiers", default=str(DEFAULT_PROGMEM_FRONTIERS))
    parser.add_argument("--compile-report", default=str(DEFAULT_OUT / "compile-prod.txt"),
                        help="arduino-cli log for the documented sketch build")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--ring", type=int, default=64,
                        help="ring the image was generated for (default 64)")
    parser.add_argument("--program-bytes", type=int, default=None)
    parser.add_argument("--sram-bytes", type=int, default=None)
    parser.add_argument("--cap-program", type=int, default=29696)
    parser.add_argument("--cap-sram", type=int, default=2560)
    args = parser.parse_args(argv)

    checks = Checks()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    image = Path(args.image)
    meta = load_json(args.meta)
    songs = load_json(args.songs)
    catalog = load_json(args.catalog)
    macros, header_comments = parse_header(args.header)
    image_bytes = image.stat().st_size if image.is_file() else 0
    image_data = image.read_bytes() if image.is_file() else b""

    # --- catalog order ------------------------------------------------------
    entries = catalog["entries"]
    catalog_ids = [entry["id"] for entry in entries]
    catalog_sources = [entry["source"] for entry in entries]
    catalog_names = [entry["name"] for entry in entries]
    song_records = songs["songs"]
    checks.check(
        songs["song_count"] == len(entries),
        "songs.json count matches catalog",
        f"{songs['song_count']} == {len(entries)}",
    )
    checks.check(
        [record["id"] for record in song_records] == catalog_ids,
        "songs.json order matches catalog",
    )
    checks.check(
        [record["source"] for record in song_records] == catalog_sources,
        "songs.json sources match catalog",
    )
    checks.check(
        [comment["id"] for comment in header_comments] == catalog_ids,
        "header song comments are catalog order",
    )
    checks.check(
        [comment["source"] for comment in header_comments] == catalog_sources,
        "header song comments carry catalog sources",
    )

    # --- header <-> songs.json <-> packer meta ------------------------------
    checks.check(
        macros.get("JUKEBOX_FX_SONG_COUNT") == len(entries),
        "header song count matches catalog",
        f"{macros.get('JUKEBOX_FX_SONG_COUNT')} == {len(entries)}",
    )
    checks.check(
        macros.get("JUKEBOX_FX_IMAGE_BYTES") == image_bytes == songs["image_bytes"],
        "image byte count agrees (header/songs.json/file)",
        f"{macros.get('JUKEBOX_FX_IMAGE_BYTES')} / {songs['image_bytes']} / {image_bytes}",
    )
    checks.check(
        macros.get("JUKEBOX_FX_DATA_PAGE") == songs["data_page"],
        "data page agrees (header/songs.json)",
        str(macros.get("JUKEBOX_FX_DATA_PAGE")),
    )

    layout = meta["layout"]
    meta_streams = layout["streams"]
    checks.check(
        layout["image_bytes"] == image_bytes,
        "packer meta image length matches file",
        f"{layout['image_bytes']} == {image_bytes}",
    )
    checks.check(
        layout["data_page"] == macros.get("JUKEBOX_FX_DATA_PAGE"),
        "packer meta data page matches header",
    )
    checks.check(
        len(meta_streams) == len(song_records),
        "packer stream count matches songs",
    )

    # --- per-song facts -----------------------------------------------------
    offset_total = 0
    overlap_free = True
    report_ok = True
    report_details = []
    expected_magic = LOOP_MAGIC
    for index, (entry, record, header_comment, stream) in enumerate(
        zip(entries, song_records, header_comments, meta_streams)
    ):
        song_id = entry["id"]
        prefix = f"JUKEBOX_FX_SONG_{song_id.upper()}"
        song_dir = Path(args.songs).parent / "songs" / song_id
        report_path = song_dir / "report.json"
        stream_bin = song_dir / "stream.bin"
        if not report_path.is_file() or not stream_bin.is_file():
            checks.check(False, f"song {index} {song_id}: adapter artifacts present")
            report_ok = False
            continue
        report = load_json(report_path)
        stream_bytes = stream_bin.read_bytes()

        checks.check(record["offset"] == stream["offset"],
                     f"song {index} {song_id}: songs.json offset == meta")
        checks.check(record["length"] == stream["length"],
                     f"song {index} {song_id}: songs.json length == meta")
        checks.check(macros.get(f"{prefix}_OFFSET") == stream["offset"],
                     f"song {index} {song_id}: header offset == meta")
        checks.check(macros.get(f"{prefix}_LENGTH") == stream["length"],
                     f"song {index} {song_id}: header length == meta")
        checks.check(record["offset"] == offset_total,
                     f"song {index} {song_id}: stream starts where the previous ended",
                     f"{record['offset']} == {offset_total}")
        checks.check(stream["end"] == stream["offset"] + stream["length"],
                     f"song {index} {song_id}: meta end == offset + length")
        checks.check(stream["abs_addr"] == macros["JUKEBOX_FX_DATA_PAGE"] * PAGE_BYTES + stream["offset"],
                     f"song {index} {song_id}: absolute address adds the page once")
        checks.check(stream["abs_end"] == stream["abs_addr"] + stream["length"],
                     f"song {index} {song_id}: absolute end == address + length")
        overlap_free = overlap_free and (
            stream["offset"] + stream["length"] <= layout["image_bytes"]
        )

        checks.check(len(stream_bytes) == stream["length"] == report["stream"]["bytes"],
                     f"song {index} {song_id}: stream.bin length agrees",
                     f"{len(stream_bytes)}")
        checks.check(sha256_file(stream_bin) == report["stream"]["sha256"],
                     f"song {index} {song_id}: report stream sha256 matches stream.bin")
        checks.check(
            stream_bytes == image_data[stream["offset"]: stream["offset"] + stream["length"]],
            f"song {index} {song_id}: image slice equals stream.bin",
        )
        checks.check(
            stream_bytes[:1] == bytes([expected_magic]),
            f"song {index} {song_id}: stream magic is 0x{expected_magic:02X}",
            stream_bytes[:1].hex(),
        )
        checks.check(
            macros.get(f"{prefix}_STREAM_LOOP") == 1,
            f"song {index} {song_id}: header STREAM_LOOP == 1",
        )
        checks.check(
            macros.get(f"{prefix}_LOOP") == (1 if report["loop_exported"] else 0),
            f"song {index} {song_id}: header musical LOOP matches report",
        )
        checks.check(
            report["stream"].get("loop_exported") is True
            and report["stream"].get("loop_streaming") is True,
            f"song {index} {song_id}: adapter exported a streaming loop",
        )
        checks.check(
            report["stream"].get("streaming_loops_requested") is True,
            f"song {index} {song_id}: build requested --streaming-loops",
        )
        region = report["stream"]["loop_region_bytes"]
        streaming = report["stream"].get("loop_streaming") is True
        checks.check(
            (region > args.ring) if streaming else (region <= args.ring),
            f"song {index} {song_id}: loop region matches the streaming path",
            f"region {region} B, ring {args.ring} B, streaming={streaming}",
        )
        diagnostics = report.get("diagnostics") or []
        codes = [diag.get("code") for diag in diagnostics]
        checks.check(not codes, f"song {index} {song_id}: no adapter diagnostics", str(codes))
        checks.check(
            "LOOP_NOT_EXPORTED" not in codes,
            f"song {index} {song_id}: no LOOP_NOT_EXPORTED",
        )
        report_ok = report_ok and not codes
        report_details.append(
            {
                "index": index,
                "id": song_id,
                "offset": stream["offset"],
                "length": stream["length"],
                "loop_region_bytes": report["stream"]["loop_region_bytes"],
                "loop_cycle_ticks": report["stream"].get("loop_cycle_ticks"),
                "tick_rate": report["clock"]["effective_tick_rate"],
                "max_record_bytes": report["stream"]["max_record_bytes"],
                "required_window_bytes": report["stream"]["required_window_bytes"],
                "sha256": report["stream"]["sha256"],
            }
        )
        offset_total = stream["offset"] + stream["length"]

    checks.check(overlap_free, "every stream stays inside the image")
    checks.check(offset_total == image_bytes,
                 "streams densely fill the image",
                 f"{offset_total} == {image_bytes}")
    checks.check(songs.get("warnings") == [],
                 "songs.json carries no warnings",
                 str(songs.get("warnings")))
    checks.check(report_ok, "all per-song adapter builds succeeded cleanly")

    # --- page arithmetic and chip extents -----------------------------------
    data_page = macros["JUKEBOX_FX_DATA_PAGE"]
    data_bytes = layout.get("data_bytes", image_bytes)
    base = data_page * PAGE_BYTES
    checks.check(base + data_bytes <= CHIP_BYTES,
                 "data section fits the 16 MiB chip",
                 f"{base} + {data_bytes} <= {CHIP_BYTES}")
    checks.check(meta["bounds"]["image_abs_end"] <= CHIP_BYTES,
                 "packer absolute end fits the chip",
                 f"{meta["bounds"]["image_abs_end"]} <= {CHIP_BYTES}")
    checks.check(meta["bounds"]["fits_24bit"] is True,
                 "packer reports 24-bit addressing")
    checks.check(meta["options"]["chip_bytes"] == CHIP_BYTES,
                 "packer chip size is 16 MiB")
    checks.check(base % PAGE_BYTES == 0 and data_page > 0,
                 "data page is page-aligned and non-zero",
                 f"page {data_page} @ 0x{base:06X}")
    checks.check(meta["input"]["bitmap"] is None,
                 "image has no bitmap (music-only)",
                 str(meta["input"]["bitmap"]))

    # --- capacity table -----------------------------------------------------
    progmem_sizes = parse_progmem_sizes(args.progmem_gatherer)
    progmem_sizes.update(parse_progmem_sizes(args.progmem_frontiers))
    compile_facts = load_compile_report([
        args.compile_report,
        DEFAULT_OUT / "compile-prod.txt",
        REPO_ROOT / "build/fx-jukebox/compile-prod.txt",
    ])
    program_bytes = args.program_bytes
    sram_bytes = args.sram_bytes
    if program_bytes is None:
        program_bytes = compile_facts.get("program")
    if sram_bytes is None:
        sram_bytes = compile_facts.get("sram")

    capacity_lines = [
        "# FX jukebox capacity (ATMlib2FX-hlh.15)",
        "",
        "Generated by `tests/fx_jukebox/verify_image.py`. Asset bytes are",
        "FX-stream / PROGMEM-score bytes only; sketch flash and static SRAM are",
        "whole-image `arduino-cli` totals, not audio-attributable deltas.",
        "",
        f"* image: **{image_bytes} B** ({image_bytes / 1024.0:.1f} KiB), "
        f"data page **{data_page}** (0x{base:06X}), "
        f"data section {data_bytes} B, chip fill "
        f"{100.0 * (base + data_bytes) / CHIP_BYTES:.2f}%",
        f"* image ends at 0x{meta["bounds"]["image_abs_end"]:06X}; "
        f"{CHIP_BYTES - meta["bounds"]["image_abs_end"]} B chip tail free",
        f"* songs: **{len(song_records)}**, all streaming `0xC1` loops; "
        f"ring **{args.ring} B**",
        "",
        "| # | song | stream B | PROGMEM B | delta B | loop region B | cycle ticks | FX SHA-256 |",
        "|---:|---|---:|---:|---:|---:|---:|---|",
    ]
    total_progmem = 0
    for detail in report_details:
        progmem = progmem_sizes.get(detail["id"])
        total_progmem += progmem or 0
        delta = "-" if progmem is None else str(detail["length"] - progmem)
        capacity_lines.append(
            f"| {detail['index']} | {detail['id']} | {detail['length']} | "
            f"{progmem if progmem is not None else '-'} | {delta} | "
            f"{detail['loop_region_bytes']} | {detail['loop_cycle_ticks']} | "
            f"`{detail['sha256'][:16]}…` |"
        )
    capacity_lines += [
        f"| | **total** | **{image_bytes}** | **{total_progmem}** | "
        f"**{image_bytes - total_progmem}** | | | |",
        "",
        f"* PROGMEM jukebox needs {total_progmem} B of score assets and splits "
        "into two build sets; the FX sketch holds every score on the chip.",
    ]
    if program_bytes is not None and sram_bytes is not None:
        capacity_lines += [
            f"* sketch (documented flags): program **{program_bytes} B** of "
            f"{args.cap_program} B cap ({100.0 * program_bytes / args.cap_program:.1f}%), "
            f"headroom **{args.cap_program - program_bytes} B**;",
            f"* static SRAM **{sram_bytes} B** of {args.cap_sram} B "
            f"({100.0 * sram_bytes / args.cap_sram:.1f}%), headroom "
            f"**{args.cap_sram - sram_bytes} B**.",
        ]
    capacity_lines += [
        "",
        "Ardens launch (sketch plus the matching image):",
        "",
        "```sh",
        "~/code/arduboy/Ardens/build/Ardens.app/Contents/MacOS/Ardens \\",
        '    "file=$PWD/build/fx-jukebox/out/jukebox_fx.ino.hex" \\',
        '    "file=$PWD/build/fx-jukebox/fxdata.bin"',
        "```",
        "",
    ]
    capacity_path = out_dir / "capacity.md"
    capacity_path.write_text("\n".join(capacity_lines), encoding="utf-8")

    # --- summary / manifest -------------------------------------------------
    passed, failed = checks.summary()
    summary = {
        "tool": "tests/fx_jukebox/verify_image.py",
        "image": str(Path(args.image).relative_to(REPO_ROOT)) if Path(args.image).is_absolute() else args.image,
        "image_bytes": image_bytes,
        "data_page": data_page,
        "ring": args.ring,
        "song_count": len(song_records),
        "stream_bytes": image_bytes,
        "progmem_bytes": total_progmem,
        "program_bytes": program_bytes,
        "sram_bytes": sram_bytes,
        "program_cap": args.cap_program,
        "sram_cap": args.cap_sram,
        "checks_passed": passed,
        "checks_failed": failed,
        "failures": checks.failures,
        "songs": report_details,
    }
    (out_dir / "static-report.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
    )

    manifest = [
        "# FX jukebox verification hashes (ATMlib2FX-hlh.15)",
        f"{sha256_file(image)}  {args.image}",
        f"{sha256_file(args.header)}  {args.header}",
        f"{sha256_file(args.meta)}  {args.meta}",
        f"{sha256_file(args.songs)}  {args.songs}",
        f"{sha256_file(args.catalog)}  {args.catalog}",
    ]
    (out_dir / "evidence-sha256.txt").write_text(
        "\n".join(manifest) + "\n", encoding="utf-8"
    )

    print()
    print(f"capacity: {capacity_path}")
    print(f"report  : {out_dir / 'static-report.json'}")
    print(f"RESULT: {'PASS' if failed == 0 else 'FAIL'} ({passed} passed, {failed} failed)")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
