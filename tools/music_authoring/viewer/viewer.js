/* ATMlib offline track review viewer.
 *
 * Draws ONLY the canonical frontend review payload embedded by
 * `tools/atm-music inspect`. It never parses the source score, expands
 * patterns, lowers effects or quantizes ticks; those are host responsibilities.
 *
 * It is a passive review artifact: nothing here writes, compiles, flashes or
 * fetches. All data, styles and scripts are embedded in the HTML file.
 */
(function () {
  "use strict";

  var dataEl = document.getElementById("atmlib-data");
  var DATA = JSON.parse(dataEl.textContent);
  var REVIEW = DATA.review || {};
  var AUDIO = DATA.audio || null;
  var CAPS = DATA.capabilities || {};

  var CHANNELS = REVIEW.channels || [];
  var NOTES = REVIEW.notes || [];
  var INSTANCES = REVIEW.pattern_instances || [];
  var EFFECT_SPANS = REVIEW.effects || [];
  var COMMANDS = REVIEW.commands || [];
  var CLOCK = REVIEW.clock || {};
  var TOTAL = REVIEW.total_ticks || 0;
  var FX = window.ATMlibEffects || null;

  var RULER_H = 28;
  var LANE_H = 36;
  var NOTE_PAD = 4;
  var EFFECT_BAND_H = 10;
  var TRACKER_MAX_ROWS = 400;
  var LANE_COLORS = ["#1f5f8b", "#2f7d4f", "#8a5a1f", "#7a2f6f"];
  var TICK_BASE_HZ = 2000;

  var el = function (tag, cls, txt) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (txt !== undefined && txt !== null) node.textContent = String(txt);
    return node;
  };
  var clear = function (node) { while (node.firstChild) node.removeChild(node.firstChild); };
  var fmt = function (value, digits) {
    if (value === null || value === undefined || value === "") return "—";
    if (typeof value === "number") {
      return digits === undefined || Number.isInteger(value)
        ? String(value)
        : value.toFixed(digits);
    }
    return String(value);
  };

  // ---------------------------------------------------------------- state --
  var state = {
    viewStart: 0,
    viewTicks: Math.max(1, TOTAL),
    view: "piano",
    laneVisible: [true, true, true, true],
    selection: null,
    renderedRegionHighlighted: false
  };

  // ------------------------------------------------------------- geometry --
  var rollWrap = document.getElementById("roll");
  var rollCanvas = document.getElementById("roll-canvas");
  var overlayCanvas = document.getElementById("overlay-canvas");
  var gutter = document.getElementById("gutter");
  var rollCtx = rollCanvas.getContext("2d");
  var overlayCtx = overlayCanvas.getContext("2d");

  function trackWidth() {
    var w = rollWrap.clientWidth;
    return w > 0 ? w : 640;
  }
  function laneTop(ch) { return RULER_H + ch * LANE_H; }
  function totalHeight() { return RULER_H + CHANNELS.length * LANE_H; }
  function tickToX(tick) {
    return (tick - state.viewStart) / state.viewTicks * trackWidth();
  }
  function xToTick(x) {
    return state.viewStart + (x / trackWidth()) * state.viewTicks;
  }

  // Per-lane note indexes sorted by start tick for windowed drawing.
  var notesByChannel = CHANNELS.map(function () { return []; });
  NOTES.forEach(function (n, i) {
    if (!notesByChannel[n.channel]) notesByChannel[n.channel] = [];
    notesByChannel[n.channel].push(i);
  });
  notesByChannel.forEach(function (arr) {
    arr.sort(function (a, b) {
      return NOTES[a].start_tick - NOTES[b].start_tick || a - b;
    });
  });
  var pitchRange = CHANNELS.map(function (_, ch) {
    var lo = null, hi = null;
    (notesByChannel[ch] || []).forEach(function (i) {
      var v = NOTES[i].note_index;
      if (lo === null || v < lo) lo = v;
      if (hi === null || v > hi) hi = v;
    });
    return { lo: lo === null ? 0 : lo, hi: hi === null ? 0 : hi };
  });

  // Effect spans and commands are already expanded and absolute in the
  // canonical payload; bucket them once so a lane only scans its own entries.
  function bucketByChannel(items) {
    var buckets = [];
    (items || []).map(function (item, index) { return { item: item, index: index }; })
      .sort(function (a, b) {
        return (a.item.start_tick || 0) - (b.item.start_tick || 0) || a.index - b.index;
      })
      .forEach(function (entry) {
        var channel = Number(entry.item.channel);
        if (isNaN(channel) || channel < 0) return;
        if (!buckets[channel]) buckets[channel] = [];
        buckets[channel].push(entry.item);
      });
    return buckets;
  }
  var effectsByChannel = bucketByChannel(EFFECT_SPANS);
  var commandsByChannel = bucketByChannel(COMMANDS);

  function lowerBound(arr, tick) {
    var lo = 0, hi = arr.length;
    while (lo < hi) {
      var mid = (lo + hi) >> 1;
      if (NOTES[arr[mid]].start_tick < tick) lo = mid + 1; else hi = mid;
    }
    return lo;
  }
  function visibleNotes(ch) {
    var arr = notesByChannel[ch] || [];
    if (!arr.length) return [];
    var a = state.viewStart;
    var b = state.viewStart + state.viewTicks;
    var i = lowerBound(arr, a);
    while (i > 0 && NOTES[arr[i - 1]].start_tick + NOTES[arr[i - 1]].duration > a) i--;
    var out = [];
    for (; i < arr.length; i++) {
      var n = NOTES[arr[i]];
      if (n.start_tick > b) break;
      out.push(arr[i]);
    }
    return out;
  }

  function itemStart(item) { return Number(item.start_tick) || 0; }
  function itemEnd(item) {
    var end = Number(item.end_tick);
    return isNaN(end) ? itemStart(item) : end;
  }
  function visibleSpans(buckets, ch) {
    var arr = buckets[ch] || [];
    var a = state.viewStart;
    var b = state.viewStart + state.viewTicks;
    var out = [];
    arr.forEach(function (item) {
      if (itemStart(item) > b) return;
      var end = itemEnd(item);
      if (end < a || (end === a && itemStart(item) < a)) return;
      out.push(item);
    });
    return out;
  }

  function noteY(ch, noteIndex) {
    var range = pitchRange[ch];
    var top = laneTop(ch) + EFFECT_BAND_H + NOTE_PAD;
    var height = LANE_H - EFFECT_BAND_H - 2 * NOTE_PAD;
    if (range.hi === range.lo) return top + height / 2 - 5;
    var ratio = (noteIndex - range.lo) / (range.hi - range.lo);
    return top + (1 - ratio) * (height - 10);
  }

  // -------------------------------------------------------------- drawing --
  function drawRuler(ctx) {
    var w = trackWidth();
    ctx.save();
    ctx.fillStyle = "#f4f1ea";
    ctx.fillRect(0, 0, w, RULER_H);
    ctx.strokeStyle = "#d8d2c6";
    ctx.beginPath();
    ctx.moveTo(0, RULER_H - 0.5);
    ctx.lineTo(w, RULER_H - 0.5);
    ctx.stroke();

    var beat = CLOCK.ticks_per_beat || 25;
    var bar = beat * (CLOCK.beats_per_bar || 4);
    var rate = clockTicksPerSecond();
    var pxPerTick = w / state.viewTicks;
    var first = Math.floor(state.viewStart / beat) * beat;
    var last = state.viewStart + state.viewTicks;

    ctx.font = "10px -apple-system, sans-serif";
    ctx.textBaseline = "top";
    for (var t = first; t <= last; t += beat) {
      if (t < 0) continue;
      var x = tickToX(t);
      var isBar = bar > 0 && t % bar === 0;
      ctx.strokeStyle = isBar ? "#9c958a" : "#ded8cc";
      ctx.beginPath();
      ctx.moveTo(x + 0.5, isBar ? 4 : 12);
      ctx.lineTo(x + 0.5, RULER_H - 0.5);
      ctx.stroke();
      if (beat * pxPerTick >= 46 || isBar) {
        ctx.fillStyle = isBar ? "#1c1b19" : "#5b564e";
        var barNo = bar > 0 ? Math.floor(t / bar) + 1 : 0;
        var beatNo = beat > 0 ? Math.floor((t % bar) / beat) + 1 : 0;
        ctx.fillText(barNo + "." + beatNo, x + 3, 2);
      }
    }
    if (rate > 0) {
      ctx.fillStyle = "#5b564e";
      var secStep = 1;
      while (secStep * rate * pxPerTick < 60) secStep *= 2;
      var firstSec = Math.ceil(state.viewStart / (rate * secStep)) * secStep;
      for (var s = firstSec; s * rate <= last; s += secStep) {
        if (s <= 0) continue;
        var sx = tickToX(s * rate);
        ctx.fillText(s + "s", sx + 3, RULER_H - 12);
      }
    }
    ctx.restore();
  }

  function drawLanes(ctx) {
    var w = trackWidth();
    CHANNELS.forEach(function (channel, ch) {
      var top = laneTop(ch);
      ctx.fillStyle = ch % 2 ? "#ffffff" : "#fbfaf7";
      ctx.fillRect(0, top, w, LANE_H);
      ctx.strokeStyle = "#e6e0d5";
      ctx.beginPath();
      ctx.moveTo(0, top + LANE_H - 0.5);
      ctx.lineTo(w, top + LANE_H - 0.5);
      ctx.stroke();
      if (!state.laneVisible[ch]) {
        ctx.fillStyle = "rgba(120,120,120,0.10)";
        ctx.fillRect(0, top, w, LANE_H);
        return;
      }
      drawInstances(ctx, ch);
      drawNotes(ctx, ch);
      drawEffects(ctx, ch);
      drawCommands(ctx, ch);
    });
  }

  function drawInstances(ctx, ch) {
    var top = laneTop(ch);
    var pxPerTick = trackWidth() / state.viewTicks;
    INSTANCES.forEach(function (inst) {
      if (inst.channel !== ch) return;
      var end = inst.start_tick + inst.ticks;
      if (end < state.viewStart || inst.start_tick > state.viewStart + state.viewTicks) return;
      var x = tickToX(inst.start_tick);
      ctx.strokeStyle = "#c9b8d8";
      ctx.setLineDash([3, 3]);
      ctx.beginPath();
      ctx.moveTo(x + 0.5, top);
      ctx.lineTo(x + 0.5, top + LANE_H);
      ctx.stroke();
      ctx.setLineDash([]);
      if (pxPerTick * inst.ticks >= 60) {
        ctx.fillStyle = "#8a7f9a";
        ctx.font = "9px -apple-system, sans-serif";
        ctx.textBaseline = "bottom";
        ctx.fillText(inst.pattern + " #" + inst.repeat_index, x + 3, top + EFFECT_BAND_H + 9);
      }
    });
  }

  function drawNotes(ctx, ch) {
    var color = LANE_COLORS[ch] || "#333";
    var isNoise = ch === CHANNELS.length - 1 && (CHANNELS[ch] || {}).voice === "noise";
    visibleNotes(ch).forEach(function (index) {
      var note = NOTES[index];
      var x0 = tickToX(note.start_tick);
      var x1 = tickToX(note.gate_end_tick);
      var width = Math.max(2, x1 - x0);
      var y = noteY(ch, note.note_index);
      if (state.selection === index) {
        ctx.strokeStyle = "#111";
        ctx.lineWidth = 2;
      } else {
        ctx.strokeStyle = color;
        ctx.lineWidth = 1;
      }
      ctx.fillStyle = color;
      if (isNoise) {
        ctx.fillStyle = "rgba(122,47,111,0.35)";
      }
      ctx.fillRect(x0, y, width, 10);
      ctx.strokeRect(x0 + 0.5, y + 0.5, Math.max(1, width - 1), 9);
      ctx.lineWidth = 1;
      var pxPerTick = trackWidth() / state.viewTicks;
      if (pxPerTick * note.duration >= 26) {
        ctx.fillStyle = "#ffffff";
        ctx.font = "9px -apple-system, sans-serif";
        ctx.textBaseline = "middle";
        ctx.fillText(note.note, x0 + 3, y + 5);
      }
    });
  }

  function effectColor(kind) { return FX ? FX.effectColor(kind) : "#5b564e"; }
  function effectShort(kind) { return FX ? FX.effectShortName(kind) : String(kind).slice(0, 4); }
  function effectText(span) { return FX ? FX.describeEffect(span) : String(span.kind); }
  function commandText(event) { return FX ? FX.describeCommand(event) : String(event.kind); }
  function commandColor() { return FX ? FX.commandColor() : "#b5651d"; }

  function fitLabel(ctx, width, full, short) {
    if (ctx.measureText(full).width + 6 <= width) return full;
    if (ctx.measureText(short).width + 6 <= width) return short;
    return "";
  }

  /* Effect windows occupy a reserved band at the top of their lane, so they
   * stay visually separate from the pitch-positioned note blocks. */
  function drawEffects(ctx, ch) {
    var spans = visibleSpans(effectsByChannel, ch);
    if (!spans.length) return;
    var top = laneTop(ch) + 1;
    var height = EFFECT_BAND_H - 2;
    var w = trackWidth();
    ctx.save();
    ctx.font = "9px -apple-system, sans-serif";
    ctx.textBaseline = "middle";
    spans.forEach(function (span) {
      var x0 = tickToX(itemStart(span));
      var x1 = tickToX(itemEnd(span));
      if (x1 < 0 || x0 > w) return;
      x0 = Math.max(-2, Math.min(w + 2, x0));
      x1 = Math.max(-2, Math.min(w + 2, x1));
      var width = Math.max(2, x1 - x0);
      var color = effectColor(span.kind);
      ctx.globalAlpha = 0.18;
      ctx.fillStyle = color;
      ctx.fillRect(x0, top, width, height);
      ctx.globalAlpha = 1;
      ctx.fillStyle = color;
      ctx.fillRect(x0, top, width, 2);
      if (width > 3) ctx.fillRect(x0, top, 1.5, height);
      var label = fitLabel(ctx, width,
        effectText(span), effectShort(span.kind));
      if (label) {
        ctx.fillStyle = color;
        ctx.fillText(label, x0 + 3, top + height / 2 + 0.5);
      }
    });
    ctx.restore();
  }

  /* Instantaneous commands are amber dashed ticks with a diamond and a short
   * text label. Labels are skipped when neighbours would collide. */
  function drawCommands(ctx, ch) {
    var commands = visibleSpans(commandsByChannel, ch);
    if (!commands.length) return;
    var top = laneTop(ch) + 2;
    var bottom = laneTop(ch) + LANE_H - 1;
    var w = trackWidth();
    var color = commandColor();
    var lastLabelEnd = -Infinity;
    ctx.save();
    ctx.font = "9px -apple-system, sans-serif";
    ctx.textBaseline = "bottom";
    commands.forEach(function (event) {
      var x = tickToX(itemStart(event));
      if (x < -4 || x > w + 4) return;
      ctx.strokeStyle = color;
      ctx.globalAlpha = 0.7;
      ctx.setLineDash([2, 3]);
      ctx.beginPath();
      ctx.moveTo(x + 0.5, top);
      ctx.lineTo(x + 0.5, bottom);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.globalAlpha = 1;
      ctx.fillStyle = color;
      ctx.beginPath();
      ctx.moveTo(x, bottom - 4);
      ctx.lineTo(x - 3.5, bottom);
      ctx.lineTo(x + 3.5, bottom);
      ctx.closePath();
      ctx.fill();
      var label = commandText(event);
      var width = ctx.measureText(label).width;
      if (x + 5 < lastLabelEnd || x + width + 7 > w) return;
      var labelX = x + 4;
      var labelY = bottom - 5;
      ctx.fillStyle = "rgba(255,255,255,0.86)";
      ctx.fillRect(labelX - 2, labelY - 10, width + 4, 11);
      ctx.fillStyle = color;
      ctx.fillText(label, labelX, labelY);
      lastLabelEnd = labelX + width + 3;
    });
    ctx.restore();
  }

  function drawRenderedRegion(ctx) {
    if (!AUDIO || !AUDIO.available || !AUDIO.truncated) return;
    var x = tickToX(AUDIO.rendered_ticks);
    var w = trackWidth();
    if (x >= w) return;
    ctx.save();
    ctx.fillStyle = "rgba(120,120,120,0.18)";
    ctx.fillRect(x, 0, w - x, totalHeight());
    ctx.fillStyle = "#5b564e";
    ctx.font = "10px -apple-system, sans-serif";
    ctx.textBaseline = "top";
    ctx.fillText("outside rendered audio", x + 4, 2);
    ctx.restore();
  }

  function redrawCanvas() {
    var w = trackWidth();
    var h = totalHeight();
    var dpr = window.devicePixelRatio || 1;
    [rollCanvas, overlayCanvas].forEach(function (canvas) {
      canvas.width = Math.max(1, Math.floor(w * dpr));
      canvas.height = Math.max(1, Math.floor(h * dpr));
      canvas.style.width = w + "px";
      canvas.style.height = h + "px";
    });
    rollCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
    overlayCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
    rollCtx.clearRect(0, 0, w, h);
    drawLanes(rollCtx);
    drawRuler(rollCtx);
    drawRenderedRegion(rollCtx);
    drawOverlay();
  }

  function redraw() {
    redrawCanvas();
    layoutGutter();
    renderTracker();
  }

  function layoutGutter() {
    clear(gutter);
    gutter.appendChild(el("div", "ruler-spacer"));
    CHANNELS.forEach(function (channel, ch) {
      var label = el("div", "lane-label" + (state.laneVisible[ch] ? "" : " lane-hidden"));
      label.style.height = LANE_H + "px";
      label.appendChild(el("span", "name", channel.name || ("lane " + ch)));
      var voice = channel.voice === "noise" ? "noise (freq/seed)" : "pulse";
      label.appendChild(el("span", "voice", voice + " · " + (channel.note_count || 0) + " notes"));
      gutter.appendChild(label);
    });
  }

  // ------------------------------------------------------------- playhead --
  function drawOverlay() {
    var w = trackWidth();
    var h = totalHeight();
    overlayCtx.clearRect(0, 0, w, h);
    if (!audioState.ready) return;
    var tick = currentTick();
    var x = tickToX(tick);
    if (x < 0 || x > w) return;
    overlayCtx.strokeStyle = "#c0392b";
    overlayCtx.lineWidth = 2;
    overlayCtx.beginPath();
    overlayCtx.moveTo(x, 0);
    overlayCtx.lineTo(x, h);
    overlayCtx.stroke();
    overlayCtx.lineWidth = 1;
  }

  // ---------------------------------------------------------------- audio --
  var audioEl = null;
  var audition = null;
  var audioState = { ready: false, objectUrl: null, reason: "", startSample: 0, endSample: 0 };

  function updateSoundProfile() {
    var select = document.getElementById("sound-profile");
    var note = document.getElementById("sound-profile-note");
    note.hidden = false;
    select.value = audition.mode;
    if (audition.failed) {
      select.querySelector('option[value="piezo"]').disabled = true;
      note.textContent = "Piezo preview is unavailable in this browser. Raw emulator audio remains available.";
    } else if (audition.mode === "piezo") {
      note.textContent = "Approximate piezo coloration: reduced bass and a resonant tone. This profile is not calibrated to a physical Arduboy.";
    } else {
      note.textContent = "Raw emulator audio. Choose Piezo (approx.) for an uncalibrated speaker approximation.";
    }
  }

  async function selectSoundProfile() {
    var select = document.getElementById("sound-profile");
    var note = document.getElementById("sound-profile-note");
    var mode = select.value;
    note.textContent = mode === "piezo" ? "Preparing approximate piezo preview…" : "Selecting raw audio…";
    try {
      await audition.select(mode);
    } catch (error) {
      // No processing graph is attached if setup/resume was blocked. Native
      // raw playback remains usable; graph failures retain a direct raw route.
    }
    updateSoundProfile();
  }

  /* Exact tick<->sample timing uses the integer timer divider (2000 base events
   * per second). Prefer the audio descriptor's `tick_divisor`; fall back to the
   * requested clock rate, then to the reported (rounded) effective rate. */
  function audioTickDivisor() {
    if (AUDIO && Number.isInteger(AUDIO.tick_divisor) && AUDIO.tick_divisor > 0) {
      return AUDIO.tick_divisor;
    }
    if (Number.isInteger(CLOCK.tick_rate) && CLOCK.tick_rate > 0) {
      return Math.floor(TICK_BASE_HZ / CLOCK.tick_rate);
    }
    return 0;
  }
  function clockTicksPerSecond() {
    var d = audioTickDivisor();
    if (d > 0) return TICK_BASE_HZ / d;
    return CLOCK.effective_tick_rate || 0;
  }

  function tickToSample(tick) {
    if (!AUDIO) return 0;
    var d = audioTickDivisor();
    if (d > 0) {
      return Math.round(AUDIO.first_music_callback_sample +
        tick * d / TICK_BASE_HZ * AUDIO.sample_rate);
    }
    if (!AUDIO.effective_tick_rate) return 0;
    return Math.round(AUDIO.first_music_callback_sample +
      tick / AUDIO.effective_tick_rate * AUDIO.sample_rate);
  }
  function sampleToTick(sample) {
    if (!AUDIO) return 0;
    var d = audioTickDivisor();
    if (d > 0) {
      return (sample - AUDIO.first_music_callback_sample) / AUDIO.sample_rate * TICK_BASE_HZ / d;
    }
    if (!AUDIO.effective_tick_rate) return 0;
    return (sample - AUDIO.first_music_callback_sample) / AUDIO.sample_rate * AUDIO.effective_tick_rate;
  }
  function currentSample() {
    if (!audioEl) return 0;
    return audioState.startSample + audioEl.currentTime * AUDIO.sample_rate;
  }
  function currentTick() {
    var t = sampleToTick(currentSample());
    if (t < 0) t = 0;
    if (t > TOTAL) t = TOTAL;
    return t;
  }
  function audibleMaxSample() {
    var max = audioState.endSample || AUDIO.sample_count;
    if (AUDIO.truncated) max = Math.min(max, tickToSample(AUDIO.rendered_ticks));
    return max;
  }

  function b64ToBytes(b64) {
    var bin = window.atob(b64);
    var bytes = new Uint8Array(bin.length);
    for (var i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    return bytes;
  }

  function setupAudio() {
    var statusEl = document.getElementById("audio-status");
    var controls = document.getElementById("audio-controls");
    var rangeEl = document.getElementById("audio-range");
    if (!AUDIO || !AUDIO.available) {
      statusEl.className = "audio-status bad";
      statusEl.textContent = AUDIO && AUDIO.reason
        ? "Audio unavailable: " + AUDIO.reason
        : "Audio unavailable: visual review only. Re-run with --audio-preview to audition.";
      return;
    }
    try {
      var bytes = b64ToBytes(AUDIO.wav_base64 || "");
      var cycle = window.ATMlibLoop.prepare(bytes, AUDIO);
      bytes = cycle.bytes;
      audioState.startSample = cycle.startSample;
      audioState.endSample = cycle.endSample;
      var blob = new Blob([bytes], { type: "audio/wav" });
      audioState.objectUrl = URL.createObjectURL(blob);
    } catch (err) {
      statusEl.className = "audio-status bad";
      statusEl.textContent = "Audio unavailable: could not decode the embedded WAV (" + err + ").";
      return;
    }
    audioEl = document.createElement("audio");
    audioEl.preload = "auto";
    audioEl.hidden = true;
    audioEl.setAttribute("aria-hidden", "true");
    audioEl.src = audioState.objectUrl;
    var loopBox = document.getElementById("loop-preview");
    loopBox.disabled = !cycle.available;
    loopBox.checked = cycle.available && !!REVIEW.loop;
    loopBox.title = cycle.available ? "Repeat the complete song" : "Looping requires a complete capture with measured timing";
    audioEl.loop = loopBox.checked;
    loopBox.addEventListener("change", function () { audioEl.loop = loopBox.checked; });
    audioEl.addEventListener("ended", function () { document.getElementById("btn-play").textContent = "Play"; });
    document.body.appendChild(audioEl);
    audition = window.ATMlibAudition.createRouter(audioEl);
    audioEl.addEventListener("error", function () {
      statusEl.className = "audio-status bad";
      statusEl.textContent = "Audio unavailable: the embedded WAV failed to load.";
      controls.hidden = true;
    });
    audioEl.addEventListener("loadedmetadata", function () {
      audioState.ready = true;
      controls.hidden = false;
      statusEl.className = "audio-status ok";
      statusEl.textContent = "Matching preview loaded (WAV sha256 " +
        String(AUDIO.wav_sha256 || "").slice(0, 12) + "…).";
      updateSoundProfile();
      updateRangeText();
      drawOverlay();
    });
    var playBtn = document.getElementById("btn-play");
    document.getElementById("sound-profile").addEventListener("change", selectSoundProfile);
    playBtn.addEventListener("click", togglePlay);
    document.getElementById("btn-restart").addEventListener("click", function () {
      restart();
    });
    document.getElementById("seek").addEventListener("input", function (ev) {
      seekToSlider(Number(ev.target.value));
    });
    rangeEl.textContent = "";
    requestAnimationFrame(frame);
  }

  function updateRangeText() {
    var rangeEl = document.getElementById("audio-range");
    if (!AUDIO || !AUDIO.available) { rangeEl.textContent = ""; return; }
    var text = "Rendered " + fmt(AUDIO.rendered_ticks) + " of " + fmt(AUDIO.total_ticks) +
      " ticks · startup offset " + fmt(AUDIO.first_music_callback_sample) + " samples (" +
      fmt(AUDIO.first_music_callback_seconds, 4) + " s) · effective tick rate " +
      fmt(AUDIO.effective_tick_rate) + " Hz.";
    if (AUDIO.truncated) {
      text += " The capture is a bounded prefix: audition is disabled beyond the rendered range.";
    }
    if (!document.getElementById("loop-preview").disabled) {
      text += " Playback uses one complete cycle, with startup and capture tail removed. Loop repeats that cycle.";
    }
    rangeEl.textContent = text;
  }

  async function togglePlay() {
    if (!audioState.ready) return;
    var playBtn = document.getElementById("btn-play");
    if (audioEl.paused) {
      if (audioEl.ended || currentSample() >= audibleMaxSample() - 1) restart();
      try {
        await audition.resume();
        await audioEl.play();
        playBtn.textContent = "Pause";
      } catch (error) {
        document.getElementById("audio-status").textContent = "Playback was blocked by the browser. Press Play to retry.";
      }
    } else {
      audioEl.pause();
      playBtn.textContent = "Play";
    }
  }
  function restart() {
    if (!audioState.ready) return;
    audioEl.currentTime = Math.max(0, (AUDIO.first_music_callback_sample || 0) - audioState.startSample) / AUDIO.sample_rate;
    drawOverlay();
    updateReadout();
  }
  function seekToSlider(value) {
    if (!audioState.ready) return;
    var lo = AUDIO.first_music_callback_sample || 0;
    var hi = audibleMaxSample();
    var sample = lo + (hi - lo) * (value / 1000);
    audioEl.currentTime = (sample - audioState.startSample) / AUDIO.sample_rate;
    drawOverlay();
    updateReadout();
  }
  function updateReadout() {
    var readout = document.getElementById("time-readout");
    var slider = document.getElementById("seek");
    if (!audioState.ready) return;
    var sample = Math.max(AUDIO.first_music_callback_sample || 0, Math.min(currentSample(), audibleMaxSample()));
    readout.textContent = (sample / AUDIO.sample_rate).toFixed(3) + " s · tick " +
      fmt(Math.round(currentTick()));
    var lo = AUDIO.first_music_callback_sample || 0;
    var hi = audibleMaxSample();
    var value = hi > lo ? ((sample - lo) / (hi - lo)) * 1000 : 0;
    slider.value = String(Math.max(0, Math.min(1000, value)));
  }
  function frame() {
    if (audioState.ready) {
      drawOverlay();
      updateReadout();
    }
    requestAnimationFrame(frame);
  }

  // -------------------------------------------------------------- tracker --
  function renderTracker() {
    if (state.view !== "tracker") return;
    var body = document.getElementById("tracker-body");
    var active = document.activeElement;
    var focusedIndex =
      active && active.parentNode === body && active.dataset ? active.dataset.noteIndex : null;
    clear(body);
    var a = state.viewStart;
    var b = state.viewStart + state.viewTicks;
    var rows = [];
    for (var i = 0; i < NOTES.length && rows.length < TRACKER_MAX_ROWS; i++) {
      var n = NOTES[i];
      if (n.start_tick > b) break;
      if (n.gate_end_tick < a) continue;
      rows.push(i);
    }
    rows.forEach(function (index) {
      var n = NOTES[index];
      var tr = el("tr");
      tr.tabIndex = -1;
      tr.dataset.noteIndex = String(index);
      if (state.selection === index) tr.className = "selected";
      var cells = [
        String(index),
        (CHANNELS[n.channel] || {}).name || n.channel,
        String(n.start_tick),
        String(n.duration),
        String(n.gate_end_tick),
        n.note,
        n.instrument,
        String(n.volume),
        n.duty === null || n.duty === undefined ? "—" : String(n.duty),
        n.pattern,
        String(n.repeat_index),
        String(n.pattern_instance_index),
        n.source
      ];
      cells.forEach(function (value, column) {
        var cell = el("td", column === 12 ? "ptr" : "", value);
        tr.appendChild(cell);
      });
      tr.addEventListener("focus", function () { selectNote(index, false); });
      tr.addEventListener("click", function () { selectNote(index, true); });
      body.appendChild(tr);
    });
    var visible = document.getElementById("tracker");
    visible.hidden = false;
    if (focusedIndex !== null) {
      var restored = body.querySelector('tr[data-note-index="' + focusedIndex + '"]');
      if (restored) restored.focus();
    }
  }

  function updateTrackerSelection() {
    var rows = document.querySelectorAll("#tracker-body tr");
    rows.forEach(function (row) {
      row.className = Number(row.dataset.noteIndex) === state.selection ? "selected" : "";
    });
  }

  function selectNote(index, focusRow) {
    state.selection = index;
    renderDetail(index);
    updateTrackerSelection();
    redrawCanvas();
    if (focusRow) {
      var row = document.querySelector('#tracker-body tr[data-note-index="' + index + '"]');
      if (row) row.focus();
    }
  }

  function renderDetail(index) {
    var detail = document.getElementById("detail");
    var empty = document.getElementById("detail-empty");
    clear(detail);
    if (index === null || index === undefined || !NOTES[index]) {
      detail.hidden = true;
      empty.hidden = false;
      return;
    }
    var n = NOTES[index];
    var channel = CHANNELS[n.channel] || {};
    var entries = [
      ["Lane", (channel.name || n.channel) + " (" + (channel.voice || "pulse") + ")"],
      ["Note semantics", channel.voice === "noise"
        ? "noise frequency/seed control (note index " + n.note_index + "), not a pitched tone"
        : "pulse pitch " + n.note + " (note index " + n.note_index + ")"],
      ["Start tick", n.start_tick],
      ["Gate length", n.duration + " ticks"],
      ["Gate end tick", n.gate_end_tick],
      ["Instrument", n.instrument],
      ["Volume (0–255)", n.volume],
      ["Duty (0–255)", n.duty === null || n.duty === undefined ? "n/a (noise)" : n.duty],
      ["Pattern", n.pattern],
      ["Repeat index", n.repeat_index],
      ["Pattern instance", n.pattern_instance_index],
      ["Source JSON Pointer", n.source]
    ];
    entries.forEach(function (pair) {
      detail.appendChild(el("dt", "", pair[0]));
      detail.appendChild(el("dd", pair[0] === "Source JSON Pointer" ? "ptr" : "", pair[1]));
    });
    detail.hidden = false;
    empty.hidden = true;
  }

  // ------------------------------------------------------------ selection --
  function renderTotals() {
    var totals = document.getElementById("totals");
    clear(totals);
    var source = REVIEW.source || {};
    var digest = REVIEW.event_digest || {};
    var engine = REVIEW.engine || {};
    var divisor = audioTickDivisor();
    var songSeconds = divisor > 0
      ? TOTAL * divisor / TICK_BASE_HZ
      : (CLOCK.effective_tick_rate ? TOTAL / CLOCK.effective_tick_rate : 0);
    var rows = [
      ["Score id", DATA.score_id || "—"],
      ["Channels", CHANNELS.map(function (c) { return c.name; }).join(", ")],
      ["Total ticks", TOTAL],
      ["Playback", REVIEW.loop ? "Loop whole song" : "Play once"],
      ["Requested tick rate", CLOCK.tick_rate],
      ["Timer divider (base events/tick)", divisor || "—"],
      ["Effective tick rate", CLOCK.effective_tick_rate],
      ["Ticks per beat", CLOCK.ticks_per_beat],
      ["Beats per bar", CLOCK.beats_per_bar],
      ["Effective BPM", fmt(CLOCK.effective_bpm, 3)],
      ["Song length", songSeconds.toFixed(4) + " s"],
      ["Expanded notes", NOTES.length],
      ["Pattern instances", INSTANCES.length]
    ];
    // Additive rows keep effect-free reviews byte-similar in meaning while
    // surfacing the expanded automation actually present in the timeline.
    if (EFFECT_SPANS.length) rows.push(["Expanded effect windows", EFFECT_SPANS.length]);
    if (COMMANDS.length) rows.push(["Expanded live commands", COMMANDS.length]);
    rows.push(
      ["Source sha256", source.sha256],
      ["Source bytes", source.bytes],
      ["Canonical event digest", digest.hex],
      ["Canonicalization", digest.canonicalization],
      ["Engine", (engine.name || "ATMlib") + " " + (engine.library_version || "")]
    );
    rows.forEach(function (pair) {
      totals.appendChild(el("dt", "", pair[0]));
      totals.appendChild(el("dd", pair[0].indexOf("sha256") >= 0 ? "ptr" : "", fmt(pair[1])));
    });
  }

  function renderDiagnostics() {
    var list = document.getElementById("diagnostics");
    clear(list);
    var diags = (REVIEW.diagnostics || []).slice();
    (DATA.audio_diagnostics || []).forEach(function (d) { diags.push(d); });
    if (!diags.length) {
      list.appendChild(el("li", "empty", "No diagnostics from the frontend validator."));
      return;
    }
    diags.forEach(function (d) {
      var li = el("li", "sev-" + (d.severity || "error"));
      li.appendChild(el("strong", "", d.code + " "));
      li.appendChild(document.createTextNode((d.path ? d.path + ": " : "") + d.message));
      if (d.suggestion) li.appendChild(document.createTextNode(" — " + d.suggestion));
      list.appendChild(li);
    });
  }

  // ----------------------------------------------------------------- init --
  function buildLaneToggles() {
    var host = document.getElementById("lane-toggles");
    clear(host);
    CHANNELS.forEach(function (channel, ch) {
      var label = el("label");
      var box = document.createElement("input");
      box.type = "checkbox";
      box.checked = true;
      box.setAttribute("aria-label", "Show lane " + (channel.name || ch));
      box.addEventListener("change", function () {
        state.laneVisible[ch] = box.checked;
        redraw();
      });
      label.appendChild(box);
      label.appendChild(document.createTextNode("Show " + (channel.name || ch)));
      host.appendChild(label);
    });
  }

  function buildAutomation() {
    if (!EFFECT_SPANS.length && !COMMANDS.length) return;
    var legend = document.getElementById("effect-legend");
    var panel = document.getElementById("automation-panel");
    var list = document.getElementById("automation-list");
    clear(legend);
    clear(list);

    var present = [];
    if (FX) {
      FX.EFFECT_KINDS.forEach(function (kind) {
        if (EFFECT_SPANS.some(function (span) { return span.kind === kind; })) present.push(kind);
      });
    } else {
      EFFECT_SPANS.forEach(function (span) {
        if (present.indexOf(span.kind) < 0) present.push(span.kind);
      });
    }
    present.forEach(function (kind) {
      var item = el("span");
      var swatch = el("span", "swatch");
      swatch.style.background = effectColor(kind);
      item.appendChild(swatch);
      item.appendChild(document.createTextNode(
        FX ? FX.effectName(kind) : String(kind)));
      legend.appendChild(item);
    });
    if (COMMANDS.length) {
      var commandKey = el("span");
      commandKey.appendChild(el("span", "command-key", "┤"));
      commandKey.appendChild(document.createTextNode(" live command (amber tick)"));
      legend.appendChild(commandKey);
    }
    legend.hidden = false;

    var entries = EFFECT_SPANS.map(function (span) {
      return { tick: itemStart(span), order: 0, effect: true, item: span };
    }).concat(COMMANDS.map(function (event) {
      return { tick: itemStart(event), order: 1, effect: false, item: event };
    }));
    entries.sort(function (a, b) { return a.tick - b.tick || a.order - b.order; });
    entries.forEach(function (entry) {
      var item = entry.item;
      var channel = CHANNELS[item.channel] || {};
      var li = el("li", entry.effect ? "auto-effect" : "auto-command");
      li.style.borderLeft = "3px solid " +
        (entry.effect ? effectColor(item.kind) : commandColor());
      li.style.paddingLeft = "8px";
      li.appendChild(el("span", "auto-kind",
        entry.effect ? (FX ? FX.effectName(item.kind) : item.kind) : "Live command"));
      li.appendChild(el("span", "auto-channel", channel.name || ("lane " + item.channel)));
      li.appendChild(el("span", "auto-ticks",
        itemStart(item) + "–" + itemEnd(item) + "t"));
      var description = entry.effect ? effectText(item) : commandText(item);
      if (!entry.effect && item.global) description += " · score-wide";
      li.appendChild(el("span", "auto-desc", description));
      if (item.source) li.appendChild(el("span", "ptr", item.source));
      list.appendChild(li);
    });
    panel.hidden = false;
  }

  function setView(view) {
    state.view = view;
    document.getElementById("btn-piano").setAttribute("aria-pressed", String(view === "piano"));
    document.getElementById("btn-tracker").setAttribute("aria-pressed", String(view === "tracker"));
    document.querySelector(".roll-wrap").style.display = view === "piano" ? "" : "none";
    document.getElementById("tracker").hidden = view !== "tracker";
    if (view === "tracker") renderTracker();
  }

  function fit() { state.viewStart = 0; state.viewTicks = Math.max(1, TOTAL); redraw(); }
  function zoomBy(factor) {
    var center = state.viewStart + state.viewTicks / 2;
    var next = state.viewTicks * factor;
    next = Math.max(1, Math.min(Math.max(1, TOTAL), next));
    state.viewTicks = next;
    state.viewStart = Math.max(0, Math.min(TOTAL - next, center - next / 2));
    redraw();
  }
  function panBy(ticks) {
    state.viewStart = Math.max(0, Math.min(Math.max(0, TOTAL - state.viewTicks), state.viewStart + ticks));
    redraw();
  }

  function wireToolbar() {
    document.getElementById("btn-piano").addEventListener("click", function () { setView("piano"); });
    document.getElementById("btn-tracker").addEventListener("click", function () { setView("tracker"); });
    document.getElementById("btn-fit").addEventListener("click", fit);
    document.getElementById("btn-zoom-in").addEventListener("click", function () { zoomBy(0.6); });
    document.getElementById("btn-zoom-out").addEventListener("click", function () { zoomBy(1 / 0.6); });
    document.getElementById("btn-pan-left").addEventListener("click", function () { panBy(-state.viewTicks / 8); });
    document.getElementById("btn-pan-right").addEventListener("click", function () { panBy(state.viewTicks / 8); });
  }

  function wireRollInteractions() {
    var seekRuler = function (ev) {
      if (!audioState.ready) return;
      var rect = rollWrap.getBoundingClientRect();
      var x = ev.clientX - rect.left;
      if (x < 0 || x > rect.width) return;
      var tick = xToTick(x);
      var sample = tickToSample(tick);
      var lo = AUDIO.first_music_callback_sample || 0;
      var hi = audibleMaxSample();
      sample = Math.max(lo, Math.min(hi, sample));
      audioEl.currentTime = (sample - audioState.startSample) / AUDIO.sample_rate;
      drawOverlay();
      updateReadout();
    };
    rollWrap.addEventListener("click", function (ev) {
      var rect = rollWrap.getBoundingClientRect();
      if (ev.clientY - rect.top <= RULER_H) { seekRuler(ev); return; }
      // Clicking a lane selects the nearest visible note in that lane.
      var ch = Math.floor((ev.clientY - rect.top - RULER_H) / LANE_H);
      if (ch < 0 || ch >= CHANNELS.length || !state.laneVisible[ch]) return;
      var candidate = null;
      visibleNotes(ch).forEach(function (index) {
        var n = NOTES[index];
        if (n.start_tick <= xToTick(ev.clientX - rect.left) &&
            n.gate_end_tick >= xToTick(ev.clientX - rect.left)) candidate = index;
      });
      if (candidate !== null) selectNote(candidate, false);
    });
  }

  function wireKeyboard() {
    document.addEventListener("keydown", function (ev) {
      var tag = (ev.target && ev.target.tagName) || "";
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
      if (ev.key === "ArrowLeft") { panBy(-state.viewTicks / 10); ev.preventDefault(); }
      else if (ev.key === "ArrowRight") { panBy(state.viewTicks / 10); ev.preventDefault(); }
      else if (ev.key === "+" || ev.key === "=") { zoomBy(0.7); ev.preventDefault(); }
      else if (ev.key === "-" || ev.key === "_") { zoomBy(1 / 0.7); ev.preventDefault(); }
      else if (ev.key === "Home") { state.viewStart = 0; redraw(); ev.preventDefault(); }
      else if (ev.key === "End") { state.viewStart = Math.max(0, TOTAL - state.viewTicks); redraw(); ev.preventDefault(); }
      else if (ev.key === " ") { togglePlay(); ev.preventDefault(); }
      else if (ev.key === "r" || ev.key === "R") { restart(); ev.preventDefault(); }
    });
    var body = document.getElementById("tracker-body");
    body.addEventListener("keydown", function (ev) {
      var rows = Array.prototype.slice.call(body.querySelectorAll("tr"));
      var current = rows.indexOf(document.activeElement);
      if (current < 0) current = 0;
      var next = null;
      if (ev.key === "ArrowDown") next = Math.min(rows.length - 1, current + 1);
      else if (ev.key === "ArrowUp") next = Math.max(0, current - 1);
      else if (ev.key === "Home") next = 0;
      else if (ev.key === "End") next = rows.length - 1;
      if (next !== null && rows[next]) {
        rows[next].focus();
        ev.preventDefault();
      }
    });
  }

  function annotateHeader() {
    document.title = "ATMlib track review — " + (DATA.score_id || REVIEW.source && REVIEW.source.path || "score");
    document.getElementById("doc-title").textContent = "ATMlib track review — " + (DATA.score_id || "");
    var note = document.getElementById("banner-note");
    note.textContent = "Offline review artifact. Opening or regenerating it never compiles, writes or flashes FX data. " +
      "The source JSON remains authoritative; edit it and re-run `atm-music inspect` to revise this review.";
    document.getElementById("side-effect-note").textContent =
      "Capabilities: inspect " + ((CAPS.inspect || {}).available ? "available" : "unavailable") +
      ", bounded WAV preview " + ((CAPS.render || {}).available ? "available" : "unavailable") +
      ". The canonical review payload keeps its pinned 3ii.1 capabilities block for golden stability.";
    document.getElementById("visibility-note").textContent =
      "These checkboxes only hide a lane for readability; they never mute or solo audio. " +
      "Audio mute/solo is unavailable because the preview WAV is a single mono speaker mix.";
  }

  function init() {
    annotateHeader();
    renderTotals();
    renderDiagnostics();
    buildLaneToggles();
    buildAutomation();
    wireToolbar();
    wireRollInteractions();
    wireKeyboard();
    setView("piano");
    redraw();
    setupAudio();
    window.addEventListener("resize", redraw);
    if (window.ResizeObserver) {
      new ResizeObserver(redraw).observe(rollWrap);
    }
  }

  init();
})();
