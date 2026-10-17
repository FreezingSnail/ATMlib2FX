// Offline browser walkthrough driver for the ATMlib track review (ATMlib2FX-3ii.6).
//
// Drives a real local Chrome over the DevTools Protocol against a
// `file://` review.html with no network access. It records DOM assertions, the
// observed resource requests (proving the page is self-contained), keyboard
// navigation and a full-page screenshot.
//
// Usage:
//   node tests/music_authoring/viewer/walkthrough.mjs <review.html> <out.json> [out.png]
//
// Requires a local Chrome. Override the binary with CHROME=/path/to/chrome.
// Nothing is downloaded; this only launches the installed browser.

import { spawn } from "node:child_process";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import assert from "node:assert/strict";

const CHROME = process.env.CHROME ||
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const [, , htmlArg, jsonArg, pngArg] = process.argv;
if (!htmlArg || !jsonArg) {
  console.error("usage: walkthrough.mjs <review.html> <out.json> [out.png]");
  process.exit(2);
}
const htmlPath = resolve(htmlArg);
const fileURL = "file://" + htmlPath.split("/").map(encodeURIComponent).join("/");

const profile = mkdtempSync(join(tmpdir(), "atmlib-walkthrough-"));
const port = 9000 + Math.floor(Math.random() * 900);
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
  for (let i = 0; i < 100; i++) {
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
    this.ws = ws;
    this.id = 0;
    this.pending = new Map();
    this.listeners = [];
    ws.addEventListener("message", (event) => {
      const msg = JSON.parse(event.data);
      if (msg.id && this.pending.has(msg.id)) {
        const { resolve, reject } = this.pending.get(msg.id);
        this.pending.delete(msg.id);
        msg.error ? reject(new Error(JSON.stringify(msg.error))) : resolve(msg.result);
      } else if (msg.method) {
        this.listeners.forEach((fn) => fn(msg));
      }
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

async function main() {
  const info = await versionInfo();
  const ws = new WebSocket(info.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    ws.addEventListener("open", resolve, { once: true });
    ws.addEventListener("error", reject, { once: true });
  });
  const cdp = new CDP(ws);
  const requests = [];
  cdp.on((msg) => {
    if (msg.method === "Network.requestWillBeSent") requests.push(msg.params.request.url);
  });

  const { targetId } = await cdp.send("Target.createTarget", { url: "about:blank" });
  const { sessionId } = await cdp.send("Target.attachToTarget", { targetId, flatten: true });
  const S = (m, p) => cdp.send(m, p, sessionId);

  await S("Page.enable");
  await S("Runtime.enable");
  await S("Network.enable");
  await S("Page.navigate", { url: fileURL });
  for (let i = 0; i < 100; i++) {
    const ready = await S("Runtime.evaluate", { expression: "document.readyState", returnByValue: true });
    if (ready.result.value === "complete") break;
    await sleep(50);
  }
  await sleep(400); // let requestAnimationFrame and audio metadata settle

  const evaluate = async (expression) => {
    const res = await S("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
    if (res.exceptionDetails) throw new Error(res.exceptionDetails.text);
    return res.result.value;
  };

  const base = await evaluate(`(() => {
    const q = (s) => document.querySelector(s);
    const totals = {};
    document.querySelectorAll('#totals dt').forEach((dt, i) => {
      totals[dt.textContent] = document.querySelectorAll('#totals dd')[i].textContent;
    });
    return {
      title: document.title,
      url: location.href,
      lanes: Array.from(document.querySelectorAll('#gutter .lane-label .name')).map((n) => n.textContent),
      voiceLabels: Array.from(document.querySelectorAll('#gutter .lane-label .voice')).map((n) => n.textContent),
      totals,
      canvas: { w: q('#roll-canvas').width, h: q('#roll-canvas').height },
      audioStatus: q('#audio-status').textContent,
      audioRange: q('#audio-range').textContent,
      audioControlsHidden: q('#audio-controls').hidden,
      visibilityNote: q('#visibility-note').textContent,
      toggles: Array.from(document.querySelectorAll('#lane-toggles input')).map((b) => b.getAttribute('aria-label')),
      diagnostics: q('#diagnostics').textContent.trim(),
    };
  })()`);

  // Piano-roll selection: click the first pulse0 note region, then read details.
  const clickNote = await evaluate(`(() => {
    const roll = document.querySelector('#roll');
    const canvas = document.querySelector('#roll-canvas');
    const rect = canvas.getBoundingClientRect();
    const ev = new MouseEvent('click', { clientX: rect.left + 6, clientY: rect.top + 28 + 18, bubbles: true });
    roll.dispatchEvent(ev);
    return document.querySelector('#detail').textContent;
  })()`);

  // Switch to the tracker table and confirm expanded rows are drawn.
  const tracker = await evaluate(`(() => {
    document.getElementById('btn-tracker').click();
    const rows = document.querySelectorAll('#tracker-body tr');
    return { hidden: document.getElementById('tracker').hidden, rows: rows.length,
             firstRow: rows.length ? rows[0].textContent : null };
  })()`);

  // Keyboard navigation: focus the first tracker row and press ArrowDown.
  const keyboard = { before: null, after: null };
  await evaluate(`(() => { const r = document.querySelector('#tracker-body tr'); if (r) r.focus(); })()`);
  keyboard.before = await evaluate(`document.activeElement && document.activeElement.dataset ? document.activeElement.dataset.noteIndex : null`);
  await S("Input.dispatchKeyEvent", { type: "rawKeyDown", key: "ArrowDown", code: "ArrowDown", windowsVirtualKeyCode: 40, nativeVirtualKeyCode: 40 });
  await S("Input.dispatchKeyEvent", { type: "keyUp", key: "ArrowDown", code: "ArrowDown", windowsVirtualKeyCode: 40, nativeVirtualKeyCode: 40 });
  await sleep(50);
  keyboard.after = await evaluate(`document.activeElement && document.activeElement.dataset ? document.activeElement.dataset.noteIndex : null`);
  keyboard.selectedNote = await evaluate(`document.querySelector('#detail').textContent`);

  // Toggle a lane's visibility (must not change audio; labelled visibility only).
  const laneToggle = await evaluate(`(() => {
    const box = document.querySelector('#lane-toggles input');
    box.click();
    return { checked: box.checked, status: document.querySelector('#audio-status').textContent };
  })()`);

  // Audio: read back state after metadata load.
  const audio = await evaluate(`(() => {
    const el = document.getElementsByTagName('audio')[0];
    const btn = document.getElementById('btn-play');
    return {
      present: !!el, readyState: el ? el.readyState : null,
      duration: el ? el.duration : null,
      playText: btn ? btn.textContent : null,
      status: document.getElementById('audio-status').textContent,
      range: document.getElementById('audio-range').textContent,
    };
  })()`);

  // Space toggles play/pause when audio is ready.
  const playback = { before: audio.playText, after: null };
  await evaluate(`document.body.focus()`);
  await S("Input.dispatchKeyEvent", { type: "rawKeyDown", key: " ", code: "Space", windowsVirtualKeyCode: 32, nativeVirtualKeyCode: 32 });
  await S("Input.dispatchKeyEvent", { type: "keyUp", key: " ", code: "Space", windowsVirtualKeyCode: 32, nativeVirtualKeyCode: 32 });
  await sleep(200);
  playback.after = await evaluate(`document.getElementById('btn-play').textContent`);
  await S("Runtime.evaluate", { expression: "(() => { const el = document.getElementsByTagName('audio')[0]; if (el) el.pause(); })()" });

  // Seek alignment: restart -> first music callback; mid; bounded end.
  const alignment = {};
  alignment.restart = await evaluate(`(() => {
    document.getElementById('btn-restart').click();
    const el = document.getElementsByTagName('audio')[0];
    return { time: el ? el.currentTime : null, duration: el ? el.duration : null,
             readout: document.getElementById('time-readout').textContent };
  })()`);
  alignment.mid = await evaluate(`(() => {
    const s = document.getElementById('seek');
    s.value = '500'; s.dispatchEvent(new Event('input', { bubbles: true }));
    const el = document.getElementsByTagName('audio')[0];
    return { time: el ? el.currentTime : null, readout: document.getElementById('time-readout').textContent };
  })()`);
  alignment.end = await evaluate(`(() => {
    const s = document.getElementById('seek');
    s.value = '1000'; s.dispatchEvent(new Event('input', { bubbles: true }));
    const el = document.getElementsByTagName('audio')[0];
    return { time: el ? el.currentTime : null, readout: document.getElementById('time-readout').textContent };
  })()`);

  // Exercise native looping across a real end boundary, in both sound modes.
  const looping = await evaluate(`(async () => {
    const box = document.getElementById('loop-preview');
    const media = document.querySelector('audio');
    if (!media || box.disabled) return { available: false };
    const data = JSON.parse(document.getElementById('atmlib-data').textContent);
    const expected = data.audio.total_ticks / data.audio.effective_tick_rate;
    const initial = box.checked;
    const wraps = [];
    const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
    for (const mode of ['raw', 'piezo']) {
      const profile = document.getElementById('sound-profile');
      profile.value = mode; profile.dispatchEvent(new Event('change'));
      await sleep(150);
      box.checked = true; box.dispatchEvent(new Event('change'));
      media.currentTime = media.duration - 0.12;
      await media.play(); await sleep(450);
      wraps.push({ mode, time: media.currentTime, paused: media.paused, loop: media.loop });
      media.pause();
    }
    box.checked = false; box.dispatchEvent(new Event('change'));
    media.currentTime = media.duration - 0.1;
    await media.play(); await sleep(400);
    const once = { ended: media.ended, paused: media.paused, text: document.getElementById('btn-play').textContent };
    document.getElementById('btn-restart').click();
    const restarted = media.currentTime;
    box.checked = initial; box.dispatchEvent(new Event('change'));
    return { available: true, initial, scoreLoops: !!data.review.loop, duration: media.duration, expected, wraps, once, restarted };
  })()`);
  if (looping.available) {
    assert.equal(looping.initial, looping.scoreLoops);
    assert.ok(Math.abs(looping.duration - looping.expected) < 0.00003, 'exact musical cycle duration');
    for (const wrap of looping.wraps) {
      assert.equal(wrap.paused, false, wrap.mode);
      assert.equal(wrap.loop, true, wrap.mode);
      assert.ok(wrap.time < 1, 'wrapped to beginning: ' + wrap.mode);
    }
    assert.equal(looping.once.ended, true);
    assert.equal(looping.once.paused, true);
    assert.equal(looping.once.text, 'Play');
    assert.equal(looping.restarted, 0);
  }

  if (pngArg) {
    const shot = await S("Page.captureScreenshot", { format: "png", captureBeyondViewport: true });
    writeFileSync(resolve(pngArg), Buffer.from(shot.data, "base64"));
  }

  const external = requests.filter((u) => !/^(file:|blob:|data:)/.test(u));
  const result = {
    driver: "tests/music_authoring/viewer/walkthrough.mjs",
    chrome: info.Browser,
    reviewed_file: fileURL,
    loaded_offline: true,
    network_requests: requests,
    external_requests: external,
    base,
    click_note_detail: clickNote,
    tracker,
    keyboard,
    lane_toggle: laneToggle,
    audio,
    playback,
    seek_alignment: alignment,
    looping,
  };
  writeFileSync(resolve(jsonArg), JSON.stringify(result, null, 2) + "\n");
  console.log(JSON.stringify({ ok: external.length === 0, external_requests: external, lanes: base.lanes, audio_status: base.audioStatus, tracker_rows: tracker.rows, keyboard, playback }, null, 2));
  ws.close();
  chrome.kill("SIGTERM");
}

main().catch((err) => {
  console.error(err);
  chrome.kill("SIGTERM");
  process.exit(1);
});
