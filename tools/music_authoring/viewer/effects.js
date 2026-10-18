/* Effect-window and live-command helpers for the offline review viewer.
 *
 * The canonical review payload already carries expanded `effects` and
 * `commands` spans (see `tools/music_authoring/lower.py`). This module only
 * turns those typed spans into short, stable labels and per-channel buckets;
 * it never parses the source score, expands a pattern or lowers a device op.
 *
 * Loaded before viewer.js. It has no DOM or browser dependency so the same
 * helpers are exercised directly by tests/music_authoring/viewer.
 */
(function () {
  "use strict";

  var EFFECT_KINDS = [
    "arpeggio",
    "note_cut",
    "lfo",
    "slide",
    "glissando",
    "noise_retrig"
  ];
  var COMMAND_KINDS = [
    "set_tempo",
    "add_tempo",
    "set_transposition",
    "add_transposition",
    "set_volume",
    "set_mod",
    "cue"
  ];

  // Deliberately distinct from the four lane/note colors and from the
  // playhead red: effects read as translucent bands, commands as amber ticks.
  var EFFECT_COLORS = {
    arpeggio: "#0f6f6a",
    note_cut: "#a3410f",
    lfo: "#6a3d9a",
    slide: "#1f5f8b",
    glissando: "#a05d00",
    noise_retrig: "#9c2f74"
  };
  var EFFECT_NAMES = {
    arpeggio: "Arpeggio",
    note_cut: "Note cut",
    lfo: "LFO",
    slide: "Slide",
    glissando: "Glissando",
    noise_retrig: "Noise retrigger"
  };
  var EFFECT_SHORT = {
    arpeggio: "arp",
    note_cut: "cut",
    lfo: "lfo",
    slide: "sld",
    glissando: "gls",
    noise_retrig: "nrt"
  };
  var COMMAND_COLOR = "#b5651d";
  var GLOBAL_COMMANDS = { set_tempo: true, add_tempo: true, cue: true };

  function fmt(value) {
    if (value === null || value === undefined || value === "") return "?";
    return String(value);
  }
  function signed(value) {
    var number = typeof value === "number" ? value : Number(value);
    if (isNaN(number)) return fmt(value);
    return number > 0 ? "+" + number : String(number);
  }
  function params(span) { return (span && span.params) || {}; }
  function repeatSuffix(params) {
    return params.repeat === false ? "no repeat" : "repeat";
  }

  function describeEffect(span) {
    var p = params(span);
    switch (span && span.kind) {
      case "arpeggio": {
        var offsets = Array.isArray(p.offsets) ? p.offsets : [];
        var steps = offsets.length
          ? offsets.map(function (offset) { return signed(offset); }).join("/")
          : "?";
        return "arp " + steps + " · " + fmt(p.period) + "t · " + repeatSuffix(p);
      }
      case "note_cut":
        return "cut · " + fmt(p.period) + "t · " + repeatSuffix(p);
      case "lfo": {
        var mode = p.mode === "tremolo" ? "trem"
          : p.mode === "vibrato" ? "vibr"
          : p.mode === "modulation" ? "mod"
          : fmt(p.mode);
        return "lfo " + mode + " · d" + fmt(p.depth) + " · " + fmt(p.period) + "t";
      }
      case "slide":
        return "slide " + fmt(p.param) + " · " + signed(p.amount) + "/" + fmt(p.every) + "t";
      case "glissando":
        return "gliss " + fmt(p.direction) + " · " + fmt(p.period) + "t";
      case "noise_retrig":
        return "retrig " + (Number(p.period) + 1) + "t · " + fmt(p.note);
      default:
        return fmt(span && span.kind);
    }
  }

  function describeCommand(event) {
    var p = params(event);
    var value = p.value !== undefined ? p.value : event && event.value;
    switch (event && event.kind) {
      case "set_tempo": return "tempo " + fmt(value);
      case "add_tempo": return "tempo " + signed(value);
      case "set_transposition": return "trans " + signed(value);
      case "add_transposition": return "trans " + signed(value);
      case "set_volume": return "vol " + fmt(value);
      case "set_mod": return "mod " + fmt(value);
      case "cue": return "cue " + fmt(value);
      default: return fmt(event && event.kind) + " " + fmt(value);
    }
  }

  function effectColor(kind) { return EFFECT_COLORS[kind] || "#5b564e"; }
  function effectName(kind) { return EFFECT_NAMES[kind] || fmt(kind); }
  function effectShortName(kind) { return EFFECT_SHORT[kind] || fmt(kind).slice(0, 4); }
  function commandColor() { return COMMAND_COLOR; }
  function isGlobalCommand(kind) { return !!GLOBAL_COMMANDS[kind]; }

  function startTick(item) { return Number(item && item.start_tick) || 0; }
  function endTick(item) {
    var end = Number(item && item.end_tick);
    return isNaN(end) ? startTick(item) : end;
  }

  /* Stable per-channel buckets sorted by absolute start tick. The viewer uses
   * these for windowed drawing; tests pin ordering and channel isolation. */
  function bucketByChannel(items) {
    var buckets = [];
    var ordered = (items || []).map(function (item, index) {
      return { item: item, index: index };
    });
    ordered.sort(function (a, b) {
      return startTick(a.item) - startTick(b.item) || a.index - b.index;
    });
    ordered.forEach(function (entry) {
      var channel = Number(entry.item.channel);
      if (isNaN(channel) || channel < 0) return;
      if (!buckets[channel]) buckets[channel] = [];
      buckets[channel].push(entry.item);
    });
    return buckets;
  }

  /* Half-open viewport selection: spans that overlap [from, to) plus
   * instantaneous commands at `start_tick` inside it. */
  function visibleItems(bucket, from, to) {
    var out = [];
    (bucket || []).forEach(function (item) {
      var start = startTick(item);
      var end = endTick(item);
      if (start > to) return;
      // Half-open span [start, end) is out once it ends at the viewport start,
      // but an instantaneous command at that tick still belongs to the view.
      if (end < from || (end === from && start < from)) return;
      out.push(item);
    });
    return out;
  }

  window.ATMlibEffects = {
    EFFECT_KINDS: EFFECT_KINDS.slice(),
    COMMAND_KINDS: COMMAND_KINDS.slice(),
    GLOBAL_COMMANDS: Object.keys(GLOBAL_COMMANDS),
    describeEffect: describeEffect,
    describeCommand: describeCommand,
    effectColor: effectColor,
    effectName: effectName,
    effectShortName: effectShortName,
    commandColor: commandColor,
    isGlobalCommand: isGlobalCommand,
    bucketByChannel: bucketByChannel,
    visibleItems: visibleItems
  };
})();
