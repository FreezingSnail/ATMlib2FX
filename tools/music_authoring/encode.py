"""Command-byte encoder shared by the compact FX adapter.

The compact stream carries the engine's original command bytecode, so this is
the single authoritative mapping from lowered score ops to device bytes.
"""

from __future__ import annotations

from .score import ScoreError

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

# Effect selector bytes (`ATM_CMD_M_SLIDE_*` / `ATM_CMD_M_*_LFO_ON` macros).
SLIDE_SELECTORS = {"volume": 0, "frequency": 1, "modulation": 2}
LFO_SELECTORS = {"tremolo": 0, "vibrato": 1, "modulation": 2}


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
