"""Shared model, constants and strict JSON loading for the v1 score format."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

TOOL_NAME = "atm-music"
TOOL_VERSION = "1.0.0"
SCHEMA_VERSION = 1
SOURCE_FORMAT = "atmlib-score"

ENGINE_NAME = "ATMlib"
TICK_BASE_HZ = 2000
CHANNEL_NAMES = ("pulse0", "pulse1", "pulse2", "noise")
CHANNEL_VOICES = ("pulse", "pulse", "pulse", "noise")
CHANNEL_VOICE = dict(zip(CHANNEL_NAMES, CHANNEL_VOICES))
PULSE_CHANNELS = frozenset(CHANNEL_NAMES[:3])

PITCH_MIN = "C2"
PITCH_MAX = "D7"
NOTE_MIN_INDEX = 1
NOTE_MAX_INDEX = 63

HOST_LIMITS = {
    "instruments": 64,
    "patterns": 256,
    "source_events": 4096,
    "source_effects": 4096,
    "source_commands": 4096,
    "expanded_pattern_uses": 4096,
    "expanded_note_events": 65536,
    "total_ticks": 1048576,
}

# Additive v1 effect-window kinds (pattern-level optional `effects`). The engine
# state each kind programs lives in src/atm_synth.h; the exact operand byte
# mapping is documented in docs/music-authoring-interface.md.
EFFECT_TYPES = (
    "arpeggio",
    "note_cut",
    "lfo",
    "slide",
    "glissando",
    "noise_retrig",
)

# Kinds that share one engine state slot. arpeggio and note_cut both program the
# note-retrigger state (`arpTiming`/`arpNotes`/`arpCount`) and their OFF command
# is the same immediate opcode (`ATM_CMD_I_ARPEGGIO_OFF`), so they cannot be
# active together.
EFFECT_SLOT = {
    "arpeggio": "retrig",
    "note_cut": "retrig",
    "lfo": "lfo",
    "slide": "slide",
    "glissando": "glissando",
    "noise_retrig": "noise_retrig",
}

# `ATM_CMD_M_NOISE_RETRIG_ON` drives the noise channel only (process_fx gates it
# on `ch_index == OSC_CH_THREE`); every other v1 effect is scoped to the pulse
# channels.
NOISE_EFFECT_TYPES = frozenset({"noise_retrig"})
PULSE_EFFECT_TYPES = frozenset(EFFECT_TYPES) - NOISE_EFFECT_TYPES

# Additive v1 instantaneous live commands (pattern-level optional `commands`).
COMMAND_TYPES = (
    "set_tempo",
    "add_tempo",
    "set_transposition",
    "add_transposition",
    "set_volume",
    "set_mod",
    "cue",
)

# Commands that write the single shared `atmlib_state` (score-global): they are
# re-executed by every channel that plays the pattern. The rest write the
# per-channel `atm_channel_state` of the channel playing the pattern.
GLOBAL_COMMAND_TYPES = frozenset({"set_tempo", "add_tempo", "cue"})
CHANNEL_COMMAND_TYPES = frozenset(COMMAND_TYPES) - GLOBAL_COMMAND_TYPES

IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
IDENTIFIER_MAX_LENGTH = 64
NOTE_RE = re.compile(r"^([A-G])(#?)([0-9])$")
SEMITONES = {
    "C": 0,
    "C#": 1,
    "D": 2,
    "D#": 3,
    "E": 4,
    "F": 5,
    "F#": 6,
    "G": 7,
    "G#": 8,
    "A": 9,
    "A#": 10,
    "B": 11,
}

FX_BACKEND_REASON = (
    "FX playback contract is pending the architecture decision in "
    "ATMlib2FX-hlh.2; FX export is owned by ATMlib2FX-3ii.3."
)
RENDER_REASON = (
    "No WAV renderer is implemented in this task; bounded WAV preview and "
    "playback evidence are owned by ATMlib2FX-3ii.2."
)
VIEWER_REASON = (
    "Offline HTML/JS track review is owned by ATMlib2FX-3ii.6; this task "
    "publishes the canonical review payload only."
)


class ScoreError(Exception):
    """Raised when validated data cannot be lowered (internal safeguard)."""


@dataclass(frozen=True)
class Diagnostic:
    code: str
    path: str
    message: str
    suggestion: str
    severity: str = "error"

    def as_dict(self) -> dict:
        return {
            "code": self.code,
            "severity": self.severity,
            "path": self.path,
            "message": self.message,
            "suggestion": self.suggestion,
        }


def pointer(*parts: object) -> str:
    """Build an RFC 6901 JSON Pointer from path segments.

    A part that already begins with ``/`` is treated as a pre-built pointer
    prefix and appended verbatim, so ``pointer(path, key)`` appends to an
    existing pointer instead of re-escaping the whole thing.
    """
    out = ""
    for part in parts:
        text = str(part)
        if text.startswith("/"):
            out += text
        else:
            out += "/" + text.replace("~", "~0").replace("/", "~1")
    return out


def identifier_problem(value: object) -> str | None:
    """Return a diagnostic code for an invalid identifier, else None."""
    if not isinstance(value, str):
        return "TYPE_MISMATCH"
    if len(value) > IDENTIFIER_MAX_LENGTH or not IDENTIFIER_RE.match(value):
        return "INVALID_IDENTIFIER"
    return None


def note_index(token: str) -> int:
    """Map a validated C2..D7 note token to the engine note table index."""
    match = NOTE_RE.match(token)
    if not match:
        raise ValueError(token)
    letter, sharp, octave_text = match.groups()
    octave = int(octave_text)
    return 1 + 12 * (octave - 2) + SEMITONES[letter + sharp]


def note_range_problem(token: str) -> tuple[str | None, int | None]:
    """Classify a note token.

    Returns ``(code, index)``.  ``code`` is ``INVALID_NOTE`` for unsupported
    syntax, ``PITCH_RANGE`` for a syntactically valid note outside C2..D7 and
    ``None`` for a valid token.
    """
    match = NOTE_RE.match(token)
    if not match:
        return "INVALID_NOTE", None
    index = note_index(token)
    if index < NOTE_MIN_INDEX or index > NOTE_MAX_INDEX:
        return "PITCH_RANGE", index
    return None, index


def tick_divisor(requested: int) -> int:
    """Integer AVR timer divider: base events per callback.

    ``osc_set_tick_rate`` programs ``div = OSC_SAMPLERATE/OSC_ISR_PRESCALER_DIV/rate - 1``
    (``src/osc.c``), so callbacks fire every ``TICK_BASE_HZ // requested`` base
    events. This integer divider is the exact timing unit; the callback rate it
    produces is the *quotient* ``TICK_BASE_HZ / tick_divisor`` (fractional when
    the requested rate is not a divisor of ``TICK_BASE_HZ``).
    """
    return TICK_BASE_HZ // requested


def effective_tick_rate(requested: int) -> int | float:
    """Actual callback rate (Hz): ``TICK_BASE_HZ / tick_divisor``.

    This is the real timer frequency, not the rounded ``TICK_BASE_HZ // divisor``
    (``255 -> 2000/7 = 285.714...``). An ``int`` is returned when the quotient is
    exact (divisor divides ``TICK_BASE_HZ``, e.g. ``50 -> 40 -> 50``) so existing
    exact metadata stays byte-identical; otherwise the true fractional quotient.
    """
    divisor = tick_divisor(requested)
    if TICK_BASE_HZ % divisor == 0:
        return TICK_BASE_HZ // divisor
    return TICK_BASE_HZ / divisor


def tick_interval_seconds(requested: int) -> float:
    """Exact seconds between callbacks: ``tick_divisor / TICK_BASE_HZ``."""
    return tick_divisor(requested) / TICK_BASE_HZ


def ticks_to_seconds(total_ticks: int, requested: int) -> float:
    """Exact musical duration derived from the divider, not the rounded Hz.

    ``total_ticks * tick_divisor / TICK_BASE_HZ`` (e.g. 2000 ticks at 255 Hz span
    exactly 7 s, whereas dividing by the rounded 285 Hz would not).
    """
    return total_ticks * tick_divisor(requested) / TICK_BASE_HZ


def effective_bpm(requested: int, ticks_per_beat: int) -> float:
    return (TICK_BASE_HZ / tick_divisor(requested)) * 60.0 / ticks_per_beat


def library_version() -> str:
    """Read ``library.properties``; fall back to the pinned release."""
    repo_root = Path(__file__).resolve().parents[2]
    properties = repo_root / "library.properties"
    try:
        for line in properties.read_text(encoding="utf-8").splitlines():
            if line.startswith("version="):
                return line.split("=", 1)[1].strip()
    except OSError:
        pass
    return "1.2.4"


@dataclass(frozen=True)
class Clock:
    tick_rate: int
    ticks_per_beat: int
    beats_per_bar: int

    @property
    def tick_divisor(self) -> int:
        return tick_divisor(self.tick_rate)

    @property
    def effective_tick_rate(self) -> int | float:
        return effective_tick_rate(self.tick_rate)

    @property
    def tick_interval_seconds(self) -> float:
        return tick_interval_seconds(self.tick_rate)

    def seconds_for_ticks(self, total_ticks: int) -> float:
        return ticks_to_seconds(total_ticks, self.tick_rate)

    @property
    def effective_bpm(self) -> float:
        return effective_bpm(self.tick_rate, self.ticks_per_beat)


@dataclass(frozen=True)
class Instrument:
    name: str
    voice: str
    volume: int
    duty: int | None

    @property
    def is_pulse(self) -> bool:
        return self.voice == "pulse"


@dataclass(frozen=True)
class NoteEvent:
    index: int
    at: int
    duration: int
    note: str
    note_index: int
    instrument: str


@dataclass(frozen=True)
class EffectWindow:
    """One validated pattern-level effect window.

    ``at`` is the inclusive first tick, ``until`` the exclusive end tick
    (defaults to the pattern length). Only the fields understood by ``kind`` are
    set; the rest stay ``None``. The byte encoding for each kind is pinned in
    docs/music-authoring-interface.md.

    Field use by ``kind``:

    * ``arpeggio`` — ``offsets`` (1–2 absolute semitone offsets from the base
      note, each 0..14; the second offset is the third arpeggio note),
      ``period`` (1..32 ticks), ``repeat``.
    * ``note_cut`` — ``period`` (1..32 ticks), ``repeat``.
    * ``lfo`` — ``mode`` (tremolo/vibrato/modulation), ``depth`` (0..255),
      ``period`` (even, 2..64 ticks).
    * ``slide`` — ``param`` (volume/frequency/modulation), ``amount``
      (-128..127), ``every`` (1..64 ticks).
    * ``glissando`` — ``period`` (1..128 ticks), ``direction`` (up/down).
    * ``noise_retrig`` — ``period`` (0..3), ``note`` and ``note_index``.
    """

    index: int
    kind: str
    at: int
    until: int
    offsets: tuple[int, ...] | None = None
    period: int | None = None
    repeat: bool | None = None
    mode: str | None = None
    depth: int | None = None
    param: str | None = None
    amount: int | None = None
    every: int | None = None
    direction: str | None = None
    note: str | None = None
    note_index: int | None = None

    @property
    def slot(self) -> str:
        return EFFECT_SLOT[self.kind]

    @property
    def duration(self) -> int:
        return self.until - self.at


@dataclass(frozen=True)
class LiveCommand:
    """One validated instantaneous live command at a pattern tick."""

    index: int
    kind: str
    at: int
    value: int

    @property
    def is_global(self) -> bool:
        return self.kind in GLOBAL_COMMAND_TYPES


@dataclass(frozen=True)
class Pattern:
    name: str
    ticks: int
    events: tuple[NoteEvent, ...]
    effects: tuple[EffectWindow, ...] = ()
    commands: tuple[LiveCommand, ...] = ()


@dataclass(frozen=True)
class TrackUse:
    index: int
    pattern: str
    repeat: int


@dataclass(frozen=True)
class Score:
    id: str
    clock: Clock
    instruments: dict[str, Instrument]
    patterns: dict[str, Pattern]
    pattern_voices: dict[str, frozenset[str]]
    tracks: dict[str, tuple[TrackUse, ...]]
    source_path: str
    source_sha256: str
    source_bytes: int
    raw_bytes: bytes = field(repr=False, default=b"")
    loop: bool = False


class InvalidJson(Exception):
    def __init__(self, message: str):
        super().__init__(message)


class _NonFinite:
    def __init__(self, text: str):
        self.text = text

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<non-finite {self.text}>"


def _escape_pointer_segment(segment: str) -> str:
    return segment.replace("~", "~0").replace("/", "~1")


def _find_paths(root: Any, predicate) -> list[str]:
    """Find JSON Pointer paths of nodes matching ``predicate``."""
    found: list[str] = []

    def walk(node: Any, path: str) -> None:
        if predicate(node):
            found.append(path)
            # Do not descend into a matched sentinel; containers still walk.
            if not isinstance(node, (dict, list)):
                return
        if isinstance(node, dict):
            for key, value in node.items():
                walk(value, path + "/" + _escape_pointer_segment(str(key)))
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, path + "/" + str(index))

    walk(root, "")
    return found


class ParsedJson:
    """Result of strict JSON parsing, including duplicate-key locations."""

    def __init__(self, document: Any, duplicates: list[tuple[dict, str]], nonfinite: list[str]):
        self.document = document
        self.duplicates = duplicates
        self.nonfinite = nonfinite


def parse_json_bytes(raw: bytes) -> ParsedJson:
    """Parse JSON bytes, rejecting duplicate keys and non-finite numbers."""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InvalidJson(f"input is not valid UTF-8: {exc}") from exc

    duplicates: list[tuple[dict, str]] = []

    def object_pairs_hook(pairs: list[tuple[str, Any]]) -> dict:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                duplicates.append((result, key))
            else:
                result[key] = value
        return result

    def parse_constant(text: str) -> _NonFinite:
        return _NonFinite(text)

    try:
        document = json.loads(
            text,
            object_pairs_hook=object_pairs_hook,
            parse_constant=parse_constant,
        )
    except json.JSONDecodeError as exc:
        raise InvalidJson(
            f"invalid JSON at line {exc.lineno} column {exc.colno}: {exc.msg}"
        ) from exc

    # Locate non-finite values (NaN / Infinity constants and overflow floats).
    def is_nonfinite(node: Any) -> bool:
        if isinstance(node, _NonFinite):
            return True
        return isinstance(node, float) and not math.isfinite(node)

    nonfinite_paths: list[str] = []
    if isinstance(document, float) and not math.isfinite(document):
        nonfinite_paths = [""]
    elif isinstance(document, _NonFinite):
        nonfinite_paths = [""]
    else:
        nonfinite_paths = _find_paths(document, is_nonfinite)

    return ParsedJson(document, duplicates, nonfinite_paths)


def duplicate_paths(parsed: ParsedJson) -> list[str]:
    """Resolve recorded duplicate-key objects to JSON Pointer paths."""
    paths: list[str] = []
    for owner, key in parsed.duplicates:
        owners = _find_paths(parsed.document, lambda node: node is owner)
        base = owners[0] if owners else ""
        paths.append(base + "/" + _escape_pointer_segment(key))
    return paths


def read_file(path: str) -> bytes:
    return Path(path).read_bytes()
