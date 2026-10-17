// Verification-only driver for the optional Piezo (approx.) sound profile
// (ATMlib2FX-3ii.9). Launches a real installed Chrome, offline, against the
// generated file:// review and records evidence under build/music-authoring/piezo-tests/.
//
// It does not modify product code. All diagnostic hooks are page-local and
// installed only through Page.addScriptToEvaluateOnNewDocument.
//
// Usage: node research/music-authoring/piezo/piezo-verify.mjs <review.html> <out-dir>

import { spawn } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";

const CHROME = process.env.CHROME ||
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const [, , htmlArg, outArg] = process.argv;
if (!htmlArg || !outArg) {
  console.error("usage: piezo-verify.mjs <review.html> <out-dir>");
  process.exit(2);
}
const htmlPath = resolve(htmlArg);
const outDir = resolve(outArg);
mkdirSync(outDir, { recursive: true });
const fileURL = "file://" + htmlPath.split("/").map(encodeURIComponent).join("/");

const profile = join(outDir, `chrome-profile-${process.pid}`);
const port = 9100 + Math.floor(Math.random() * 700);
const chrome = spawn(CHROME, [
  "--headless=new",
  "--disable-gpu",
  "--no-first-run",
  "--no-default-browser-check",
  "--mute-audio",
  "--allow-file-access-from-files",
  "--autoplay-policy=no-user-gesture-required",
  `--remote-debugging-port=${port}`,
  `--user-data-dir=${profile}`,
  "about:blank",
], { stdio: "ignore" });

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function versionInfo() {
  for (let i = 0; i < 150; i++) {
    try {
      const res = await fetch(`http://127.0.0.1:${port}/json/version`);
      if (res.ok) return res.json();
    } catch { /* not up yet */ }
    await sleep(100);
  }
  throw new Error("Chrome DevTools endpoint did not come up");
}

class CDP {
  constructor(ws) {
    this.ws = ws; this.id = 0; this.pending = new Map(); this.listeners = [];
    ws.addEventListener("message", (event) => {
      const msg = JSON.parse(event.data);
      if (msg.id && this.pending.has(msg.id)) {
        const { resolve, reject } = this.pending.get(msg.id);
        this.pending.delete(msg.id);
        msg.error ? reject(new Error(JSON.stringify(msg.error))) : resolve(msg.result);
      } else if (msg.method) { this.listeners.forEach((fn) => fn(msg)); }
    });
  }
  send(method, params = {}, sessionId) {
    const id = ++this.id;
    const payload = { id, method, params };
    if (sessionId) payload.sessionId = sessionId;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.ws.send(JSON.stringify(payload));
    });
  }
  on(fn) { this.listeners.push(fn); }
}

// Diagnostic hooks. mode: "normal" | "no-audio-context" | "resume-reject".
function hookScript(mode) {
  return `(() => {
    window.__piezoProbe = { contexts: 0, sources: 0, gains: [], filters: [],
      resumes: 0, ctx: null, mediaEl: null, mode: ${JSON.stringify(mode)} };
    const OrigAC = window.AudioContext, OrigWAC = window.webkitAudioContext;
    function wrap(Orig) {
      if (!Orig) return Orig;
      const Wrapped = function () {
        const ctx = new Orig();
        const probe = window.__piezoProbe;
        probe.contexts++; probe.ctx = ctx;
        if (probe.mode === "resume-reject") {
          // Force a suspended context even though headless autoplay is allowed,
          // so the diagnostic resume() rejection is actually reached.
          let forcedState = "suspended";
          try { Object.defineProperty(ctx, "state", { configurable: true, get: () => forcedState }); } catch (e) {}
        }
        const g = ctx.createGain.bind(ctx);
        ctx.createGain = function () { const n = g(); probe.gains.push(n); return n; };
        const b = ctx.createBiquadFilter.bind(ctx);
        ctx.createBiquadFilter = function () { const n = b(); probe.filters.push(n); return n; };
        const m = ctx.createMediaElementSource.bind(ctx);
        ctx.createMediaElementSource = function (el) { probe.sources++; probe.mediaEl = el; const n = m(el); probe.sourceNode = n; return n; };
        const r = ctx.resume.bind(ctx);
        ctx.resume = function () {
          probe.resumes++;
          if (probe.mode === "resume-reject") return Promise.reject(new Error("synthetic autoplay rejection"));
          return r();
        };
        return ctx;
      };
      Wrapped.prototype = Orig.prototype;
      return Wrapped;
    }
    if (${JSON.stringify(mode)} === "no-audio-context") {
      try { Object.defineProperty(window, "AudioContext", { configurable: true, get: () => undefined }); } catch (e) {}
      try { Object.defineProperty(window, "webkitAudioContext", { configurable: true, get: () => undefined }); } catch (e) {}
    } else {
      try { Object.defineProperty(window, "AudioContext", { configurable: true, writable: true, value: wrap(OrigAC) }); } catch (e) {}
      try { if (OrigWAC) Object.defineProperty(window, "webkitAudioContext", { configurable: true, writable: true, value: wrap(OrigWAC) }); } catch (e) {}
    }
  })();`;
}

async function main() {
  const info = await versionInfo();
  const ws = new WebSocket(info.webSocketDebuggerUrl);
  await new Promise((res, rej) => {
    ws.addEventListener("open", res, { once: true });
    ws.addEventListener("error", rej, { once: true });
  });
  const cdp = new CDP(ws);
  const requests = [];
  cdp.on((m) => { if (m.method === "Network.requestWillBeSent") requests.push(m.params.request.url); });

  const evidence = { chrome: info.Browser, reviewed_file: fileURL, scenarios: {} };

  async function newPage(mode) {
    const { targetId } = await cdp.send("Target.createTarget", { url: "about:blank" });
    const { sessionId } = await cdp.send("Target.attachToTarget", { targetId, flatten: true });
    const S = (m, p) => cdp.send(m, p, sessionId);
    const exceptions = [];
    const off = (m) => {
      if (m.method === "Runtime.exceptionThrown") {
        exceptions.push((m.params.exceptionDetails && m.params.exceptionDetails.text) || "exception");
      }
    };
    cdp.on(off);
    await S("Page.enable");
    await S("Runtime.enable");
    await S("Network.enable");
    const { identifier } = await S("Page.addScriptToEvaluateOnNewDocument", { source: hookScript(mode) });
    await S("Page.navigate", { url: fileURL });
    for (let i = 0; i < 200; i++) {
      const r = await S("Runtime.evaluate", { expression: "document.readyState", returnByValue: true });
      if (r.result.value === "complete") break;
      await sleep(25);
    }
    await sleep(500);
    const evaluate = async (expression, userGesture = false) => {
      const res = await S("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true, userGesture });
      if (res.exceptionDetails) throw new Error(res.exceptionDetails.text + " :: " + expression.slice(0, 80));
      return res.result.value;
    };
    const waitFor = async (expression, ms = 3000) => {
      const end = Date.now() + ms;
      while (Date.now() < end) {
        try { if (await evaluate(expression)) return true; } catch { /* keep polling */ }
        await sleep(50);
      }
      return false;
    };
    return { S, evaluate, waitFor, exceptions, removeHook: () => S("Page.removeScriptToEvaluateOnNewDocument", { identifier }), cdp };
  }

  // ---------------------------------------------------------------- S1: UI --
  const ui = await newPage("normal");
  const uiBefore = await ui.evaluate(`(() => {
    const sel = document.getElementById('sound-profile');
    return {
      options: sel ? Array.from(sel.options).map(o => ({ value: o.value, label: o.textContent, disabled: o.disabled, selected: o.selected })) : null,
      value: sel ? sel.value : null,
      noteHidden: document.getElementById('sound-profile-note').hidden,
      audioStatus: document.getElementById('audio-status').textContent,
      controlsHidden: document.getElementById('audio-controls').hidden,
      lanes: Array.from(document.querySelectorAll('#gutter .lane-label .name')).map(n => n.textContent),
      probe: { contexts: window.__piezoProbe.contexts, sources: window.__piezoProbe.sources },
      audio: (() => { const el = document.getElementsByTagName('audio')[0];
        return el ? { src: el.src.slice(0, 24), duration: el.duration, currentTime: el.currentTime, playbackRate: el.playbackRate } : null; })(),
    };
  })()`);
  const embedded = await ui.evaluate(`(() => {
    const d = JSON.parse(document.getElementById('atmlib-data').textContent);
    return { wav_sha256: d.audio && d.audio.wav_sha256, available: !!(d.audio && d.audio.available),
             first_music_callback_sample: d.audio && d.audio.first_music_callback_sample,
             total_ticks: d.review.total_ticks };
  })()`);
  evidence.scenarios.ui = { before: uiBefore, embedded, exceptions: ui.exceptions };

  // --------------------------------------------------- S3: offline response --
  const offline = await ui.evaluate(`(async () => {
    const results = { chain: null, filters: [], frequency_response: {}, sine_rms: {}, dc: null, error: null };
    try {
      const ctx0 = new OfflineAudioContext(1, 48000, 48000);
      const chain = window.ATMlibAudition.createPiezoChain(ctx0);
      results.chain = { outputGain: chain.output.gain.value, filterCount: chain.filters.length };
      results.filters = chain.filters.map(f => ({ type: f.type, frequency: f.frequency.value, Q: f.Q.value, gain: f.gain.value }));
      const freqs = new Float32Array([0, 100, 3300, 12000, 20000]);
      let combined = Float32Array.from([1, 1, 1, 1, 1]);
      for (const f of chain.filters) {
        const mag = new Float32Array(freqs.length), ph = new Float32Array(freqs.length);
        f.getFrequencyResponse(freqs, mag, ph);
        for (let i = 0; i < freqs.length; i++) combined[i] *= mag[i];
      }
      for (let i = 0; i < freqs.length; i++) combined[i] *= chain.output.gain.value;
      results.frequency_response = { frequencies: Array.from(freqs), magnitudes: Array.from(combined) };

      async function renderRms(freq, useChain) {
        const ctx = new OfflineAudioContext(1, 48000, 48000);
        const osc = ctx.createOscillator();
        osc.type = "sine"; osc.frequency.value = freq;
        let out;
        if (useChain) { const c = window.ATMlibAudition.createPiezoChain(ctx); out = c.output; osc.connect(c.input); }
        else { out = ctx.createGain(); out.gain.value = 1; osc.connect(out); }
        out.connect(ctx.destination);
        osc.start(0);
        const buf = await ctx.startRendering();
        const data = buf.getChannelData(0);
        let sum = 0; for (let i = 0; i < data.length; i++) sum += data[i] * data[i];
        return Math.sqrt(sum / data.length);
      }
      for (const f of [100, 3300, 12000]) {
        const raw = await renderRms(f, false);
        const piezo = await renderRms(f, true);
        results.sine_rms[f] = { raw: raw, piezo: piezo, ratio: raw ? piezo / raw : null };
      }
      // DC through the chain must settle near 0 (highpass rejects it).
      const ctxDc = new OfflineAudioContext(1, 24000, 48000);
      const dc = ctxDc.createConstantSource(); dc.offset.value = 1;
      const cdc = window.ATMlibAudition.createPiezoChain(ctxDc);
      dc.connect(cdc.input); cdc.output.connect(ctxDc.destination); dc.start(0);
      const bufDc = await ctxDc.startRendering();
      const d = bufDc.getChannelData(0);
      let tail = 0; for (let i = d.length - 2400; i < d.length; i++) tail += Math.abs(d[i]);
      results.dc = { input: 1, tailMeanAbs: tail / 2400 };
    } catch (err) { results.error = String(err); }
    return results;
  })()`);
  evidence.scenarios.offline = offline;

  // ------------------------------------------------------- S2: profile swap --
  const swap = await ui.evaluate(`(async () => {
    const el = document.getElementsByTagName('audio')[0];
    const identity = (t) => ({ src: el.src, currentTime: el.currentTime, duration: el.duration, playbackRate: el.playbackRate });
    const out = { prefix: {}, toggles: [], counts: {}, probeFilters: null, exceptions: [] };
    // start playing (raw)
    document.getElementById('btn-play').click();
    out.playingRaw = { playText: document.getElementById('btn-play').textContent };
    await new Promise(r => setTimeout(r, 400));
    out.advancedRaw = el.currentTime;
    const identBefore = identity();
    out.prefix.before = identBefore;

    async function liveMeasure() {
      const probe = window.__piezoProbe;
      if (!probe.sourceNode || !probe.ctx) return { available: false, reason: "no source node captured" };
      const ctx = probe.ctx;
      const analyser = ctx.createAnalyser(); analyser.fftSize = 2048;
      const sink = ctx.createGain(); sink.gain.value = 0;
      probe.sourceNode.connect(analyser); analyser.connect(sink); sink.connect(ctx.destination);
      const rate = 50000, firstCb = 1045;
      el.currentTime = (firstCb + 0.30 * rate) / rate;
      if (el.paused) el.play();
      const buf = new Float32Array(analyser.fftSize);
      const frames = [];
      for (let i = 0; i < 40; i++) {
        await new Promise(r => setTimeout(r, 25));
        analyser.getFloatTimeDomainData(buf);
        let s = 0; for (let k = 0; k < buf.length; k++) s += buf[k] * buf[k];
        frames.push(Math.sqrt(s / buf.length));
      }
      const maxRms = Math.max.apply(null, frames);
      const meanRms = frames.reduce((a, b) => a + b, 0) / frames.length;
      probe.sourceNode.disconnect(analyser); analyser.disconnect(); sink.disconnect();

      const doc = JSON.parse(document.getElementById('atmlib-data').textContent);
      const bin = atob(doc.audio.wav_base64);
      const bytes = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
      const full = new DataView(bytes.buffer);
      let off = 12, dataOff = -1;
      while (off + 8 <= bytes.length) {
        const id = String.fromCharCode(bytes[off], bytes[off + 1], bytes[off + 2], bytes[off + 3]);
        const size = full.getUint32(off + 4, true);
        if (id === "data") { dataOff = off + 8; break; }
        off += 8 + size + (size & 1);
      }
      const t0 = firstCb + Math.round(0.30 * rate);
      const t1 = t0 + Math.round(1.0 * rate);
      let sum = 0, n = 0;
      for (let i = t0; i < t1; i++) {
        const v = full.getInt16(dataOff + i * 2, true) / 32768;
        sum += v * v; n++;
      }
      const pcmRms = Math.sqrt(sum / n);
      return {
        available: true, contextState: ctx.state, maxRms: maxRms, meanRms: meanRms,
        pcmRms: pcmRms, ratioToPcm: pcmRms ? meanRms / pcmRms : null,
        windowSeconds: [ (t0) / rate, (t1) / rate ], dataOffset: dataOff,
      };
    }

    async function choose(mode) {
      const sel = document.getElementById('sound-profile');
      sel.value = mode;
      sel.dispatchEvent(new Event('change', { bubbles: true }));
      for (let i = 0; i < 60; i++) {
        await new Promise(r => setTimeout(r, 50));
        const note = document.getElementById('sound-profile-note').textContent;
        if (!/Preparing|Selecting/.test(note)) break;
      }
      const probe = window.__piezoProbe;
      await new Promise(r => setTimeout(r, 120));
      return {
        requested: mode,
        selectValue: sel.value,
        piezoDisabled: sel.querySelector('option[value="piezo"]').disabled,
        note: document.getElementById('sound-profile-note').textContent,
        contexts: probe.contexts, sources: probe.sources, resumes: probe.resumes,
        ctxState: probe.ctx ? probe.ctx.state : null,
        rawGain: probe.gains[0] ? probe.gains[0].gain.value : null,
        piezoGain: probe.gains[1] ? probe.gains[1].gain.value : null,
        filters: probe.filters.map(f => ({ type: f.type, frequency: f.frequency.value, Q: f.Q.value, gain: f.gain.value })),
        currentTime: el.currentTime,
        identity: identity(),
      };
    }
    out.piezo = await choose('piezo');
    await new Promise(r => setTimeout(r, 350));
    out.advancedPiezo = el.currentTime;
    out.livePiezo = await liveMeasure();
    out.raw = await choose('raw');
    out.liveRaw = await liveMeasure();
    out.prefix.after = identity();
    out.identitySurvived = (out.prefix.before.src === out.prefix.after.src) &&
      (out.prefix.before.duration === out.prefix.after.duration) &&
      (out.prefix.before.playbackRate === out.prefix.after.playbackRate);

    // repeat toggles: no doubled playback / duplicate source
    for (let i = 0; i < 8; i++) {
      await choose(i % 2 === 0 ? 'piezo' : 'raw');
    }
    out.toggles = { contexts: window.__piezoProbe.contexts, sources: window.__piezoProbe.sources,
      sourceIsSameElement: window.__piezoProbe.mediaEl === el,
      filtersCreated: window.__piezoProbe.filters.length, resumes: window.__piezoProbe.resumes,
      finalSelectValue: document.getElementById('sound-profile').value };

    // seek/restart mapping under piezo
    await choose('piezo'); // leave piezo selected for the screenshot
    document.getElementById('btn-restart').click();
    out.restart = { time: el.currentTime, readout: document.getElementById('time-readout').textContent };
    const seek = document.getElementById('seek');
    seek.value = '500'; seek.dispatchEvent(new Event('input', { bubbles: true }));
    out.seekMid = { time: el.currentTime, readout: document.getElementById('time-readout').textContent };
    seek.value = '1000'; seek.dispatchEvent(new Event('input', { bubbles: true }));
    out.seekEnd = { time: el.currentTime, readout: document.getElementById('time-readout').textContent };
    el.pause();
    return out;
  })()`);
  evidence.scenarios.profile = { swap, exceptions: ui.exceptions };

  const shot = await ui.S("Page.captureScreenshot", { format: "png", captureBeyondViewport: true });
  writeFileSync(join(outDir, "piezo-selected.png"), Buffer.from(shot.data, "base64"));
  await ui.removeHook();

  // ------------------------------------------------ S4: no AudioContext API --
  const noApi = await newPage("no-audio-context");
  const noApiResult = await noApi.evaluate(`(async () => {
    const el = document.getElementsByTagName('audio')[0];
    const before = { contexts: window.__piezoProbe.contexts };
    document.getElementById('btn-play').click();
    await new Promise(r => setTimeout(r, 250));
    const playing = { currentTime: el.currentTime, paused: el.paused, playText: document.getElementById('btn-play').textContent };
    const sel = document.getElementById('sound-profile');
    sel.value = 'piezo';
    sel.dispatchEvent(new Event('change', { bubbles: true }));
    await new Promise(r => setTimeout(r, 500));
    const after = {
      selectValue: sel.value,
      piezoDisabled: sel.querySelector('option[value="piezo"]').disabled,
      note: document.getElementById('sound-profile-note').textContent,
      contexts: window.__piezoProbe.contexts, sources: window.__piezoProbe.sources,
      rawStillPlays: !el.paused, currentTime: el.currentTime,
      audioStatus: document.getElementById('audio-status').textContent,
    };
    el.pause();
    return { before, playing, after };
  })()`);
  evidence.scenarios.no_audio_context = { result: noApiResult, exceptions: noApi.exceptions };
  await noApi.removeHook();

  // ------------------------------------------------ S5: resume rejection --
  const rej = await newPage("resume-reject");
  const rejResult = await rej.evaluate(`(async () => {
    const el = document.getElementsByTagName('audio')[0];
    document.getElementById('btn-play').click();
    await new Promise(r => setTimeout(r, 250));
    const playing = { currentTime: el.currentTime, paused: el.paused };
    const sel = document.getElementById('sound-profile');
    sel.value = 'piezo';
    sel.dispatchEvent(new Event('change', { bubbles: true }));
    await new Promise(r => setTimeout(r, 600));
    const after = {
      selectValue: sel.value,
      piezoDisabled: sel.querySelector('option[value="piezo"]').disabled,
      note: document.getElementById('sound-profile-note').textContent,
      contexts: window.__piezoProbe.contexts, sources: window.__piezoProbe.sources,
      resumes: window.__piezoProbe.resumes,
      ctxState: window.__piezoProbe.ctx ? window.__piezoProbe.ctx.state : null,
      rawStillPlays: !el.paused, currentTime: el.currentTime,
    };
    el.pause();
    return { playing, after };
  })()`);
  evidence.scenarios.resume_reject = { result: rejResult, exceptions: rej.exceptions };
  await rej.removeHook();

  const external = requests.filter((u) => !/^(file:|blob:|data:)/.test(u));
  evidence.network_requests = requests;
  evidence.external_requests = external;
  evidence.unhandled_exceptions = {
    ui: ui.exceptions, no_api: noApi.exceptions, resume_reject: rej.exceptions,
  };
  writeFileSync(join(outDir, "piezo-verify.json"), JSON.stringify(evidence, null, 2) + "\n");
  console.log(JSON.stringify({
    chrome: evidence.chrome,
    external_requests: external,
    default_profile: uiBefore.value,
    options: uiBefore.options,
    audio_status: uiBefore.audioStatus,
    wav_sha256: embedded.wav_sha256,
    lanes: uiBefore.lanes,
    offline_error: offline.error,
    freq_response: offline.frequency_response,
    sine_rms: offline.sine_rms,
    dc_tail: offline.dc,
    piezo_swap: swap.piezo && { contexts: swap.piezo.contexts, sources: swap.piezo.sources, ctxState: swap.piezo.ctxState, rawGain: swap.piezo.rawGain, piezoGain: swap.piezo.piezoGain, filters: swap.piezo.filters },
    toggles: swap.toggles,
    identity_survived: swap.identitySurvived,
    live_raw: swap.liveRaw, live_piezo: swap.livePiezo,
    advanced_raw: swap.advancedRaw, advanced_piezo: swap.advancedPiezo,
    restart: swap.restart, seekMid: swap.seekMid, seekEnd: swap.seekEnd,
    no_audio_context: noApiResult.after,
    resume_reject: rejResult.after,
    exceptions: evidence.unhandled_exceptions,
  }, null, 2));

  ws.close();
  chrome.kill("SIGTERM");
}

main().catch((err) => {
  console.error("VERIFY_FAILED:", err && err.message ? err.message : err);
  chrome.kill("SIGTERM");
  process.exit(1);
});
