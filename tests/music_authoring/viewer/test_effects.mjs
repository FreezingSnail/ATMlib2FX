// Effect-window and live-command helpers, plus viewer integration through the
// same DOM/media adapter used by test_transport.mjs.
// Run: node tests/music_authoring/viewer/test_effects.mjs
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const assets = new URL('../../../tools/music_authoring/viewer/', import.meta.url);

// ---------------------------------------------------------------- helpers --
{
  const window = {};
  vm.runInNewContext(readFileSync(new URL('effects.js', assets), 'utf8'), { window });
  const fx = window.ATMlibEffects;
  assert.ok(fx, 'effects.js installs window.ATMlibEffects');
  assert.deepEqual(Array.from(fx.EFFECT_KINDS), [
    'arpeggio', 'note_cut', 'lfo', 'slide', 'glissando', 'noise_retrig',
  ]);
  assert.deepEqual(Array.from(fx.COMMAND_KINDS), [
    'set_tempo', 'add_tempo', 'set_transposition', 'add_transposition',
    'set_volume', 'set_mod', 'cue',
  ]);

  const effectLabel = (kind, params) => fx.describeEffect({ kind, params });
  assert.equal(effectLabel('arpeggio', { offsets: [4, 7], period: 3, repeat: true }),
    'arp +4/+7 · 3t · repeat');
  assert.equal(effectLabel('arpeggio', { offsets: [0], period: 2, repeat: false }),
    'arp 0 · 2t · no repeat');
  assert.equal(effectLabel('note_cut', { period: 3, repeat: false }), 'cut · 3t · no repeat');
  assert.equal(effectLabel('note_cut', { period: 4 }), 'cut · 4t · repeat');
  assert.equal(effectLabel('lfo', { mode: 'tremolo', depth: 90, period: 12 }),
    'lfo trem · d90 · 12t');
  assert.equal(effectLabel('lfo', { mode: 'vibrato', depth: 8, period: 2 }),
    'lfo vibr · d8 · 2t');
  assert.equal(effectLabel('lfo', { mode: 'modulation', depth: 1, period: 64 }),
    'lfo mod · d1 · 64t');
  assert.equal(effectLabel('slide', { param: 'volume', amount: -2, every: 4 }),
    'slide volume · -2/4t');
  assert.equal(effectLabel('glissando', { direction: 'up', period: 5 }),
    'gliss up · 5t');
  assert.equal(effectLabel('glissando', { direction: 'down', period: 128 }),
    'gliss down · 128t');
  assert.equal(effectLabel('noise_retrig', { period: 2, note: 'C4' }),
    'retrig 3t · C4');

  const commandLabel = (kind, value) => fx.describeCommand({ kind, params: { value } });
  assert.equal(commandLabel('set_tempo', 100), 'tempo 100');
  assert.equal(commandLabel('add_tempo', -3), 'tempo -3');
  assert.equal(commandLabel('set_transposition', -12), 'trans -12');
  assert.equal(commandLabel('add_transposition', 5), 'trans +5');
  assert.equal(commandLabel('set_volume', 90), 'vol 90');
  assert.equal(commandLabel('set_mod', 40), 'mod 40');
  assert.equal(commandLabel('cue', 7), 'cue 7');
  assert.equal(fx.isGlobalCommand('set_tempo'), true);
  assert.equal(fx.isGlobalCommand('add_tempo'), true);
  assert.equal(fx.isGlobalCommand('cue'), true);
  assert.equal(fx.isGlobalCommand('set_volume'), false);

  const colors = fx.EFFECT_KINDS.map(kind => fx.effectColor(kind));
  assert.equal(new Set(colors).size, fx.EFFECT_KINDS.length,
    'each effect kind has a distinct band color');
  assert.equal(fx.effectShortName('glissando'), 'gls');

  const bucket = fx.bucketByChannel([
    { channel: 1, start_tick: 10, end_tick: 12 },
    { channel: 0, start_tick: 5, end_tick: 6 },
    { channel: 1, start_tick: 2, end_tick: 3 },
  ]);
  assert.deepEqual(Array.from(bucket[0].map(item => item.start_tick)), [5]);
  assert.deepEqual(Array.from(bucket[1].map(item => item.start_tick)), [2, 10]);
  assert.deepEqual(Array.from(fx.visibleItems(bucket[1], 3, 10).map(item => item.start_tick)), [10]);
  assert.deepEqual(Array.from(fx.visibleItems(bucket[0], 5, 12).map(item => item.start_tick)), [5]);
  assert.deepEqual(Array.from(fx.visibleItems([{ channel: 0, start_tick: 2, end_tick: 5 }], 5, 12)
    .map(item => item.start_tick)), [], 'a span ending at the viewport start is out');
  assert.deepEqual(Array.from(fx.visibleItems([{ channel: 0, start_tick: 5, end_tick: 5 }], 5, 5)
    .map(item => item.start_tick)), [5], 'instantaneous command at the viewport start');
  console.log('Effect helper checks passed (labels, colors, globals, buckets, viewport).');
}

// ----------------------------------------------------- viewer integration --
{
  const counts = {};
  function context() {
    const target = { measureText: () => ({ width: 40 }) };
    return new Proxy(target, {
      get(object, key) {
        if (key in object) return object[key];
        return (...args) => {
          counts[key] = (counts[key] || 0) + 1;
          return undefined;
        };
      },
      set(object, key, value) { object[key] = value; return true; },
    });
  }
  class Element {
    constructor(tag = 'div') {
      this.tagName = tag.toUpperCase();
      this.style = {};
      this.children = [];
      this.events = {};
      this.dataset = {};
      this.textContent = '';
      this.clientWidth = 640;
      this.hidden = false;
    }
    get firstChild() { return this.children[0]; }
    appendChild(node) { this.children.push(node); node.parentNode = this; return node; }
    removeChild(node) { this.children.splice(this.children.indexOf(node), 1); }
    setAttribute(key, value) { this[key] = value; }
    addEventListener(name, fn) { (this.events[name] ||= []).push(fn); }
    querySelector() { return new Element(); }
    querySelectorAll() { return []; }
    getBoundingClientRect() { return { left: 0, top: 0, width: 640 }; }
    getContext() { return context(); }
  }

  const channels = [
    { name: 'pulse0', voice: 'pulse', note_count: 1 },
    { name: 'pulse1', voice: 'pulse', note_count: 0 },
    { name: 'pulse2', voice: 'pulse', note_count: 0 },
    { name: 'noise', voice: 'noise', note_count: 0 },
  ];
  const effects = [
    { channel: 0, kind: 'arpeggio', start_tick: 0, end_tick: 8, params: { offsets: [4, 7], period: 3, repeat: true }, source: '/patterns/run/effects/0' },
    { channel: 0, kind: 'note_cut', start_tick: 8, end_tick: 16, params: { period: 3, repeat: false }, source: '/patterns/run/effects/1' },
    { channel: 0, kind: 'lfo', start_tick: 16, end_tick: 32, params: { mode: 'tremolo', depth: 90, period: 12 }, source: '/patterns/run/effects/2' },
    { channel: 1, kind: 'slide', start_tick: 0, end_tick: 24, params: { param: 'volume', amount: -2, every: 4 }, source: '/patterns/run/effects/3' },
    { channel: 2, kind: 'glissando', start_tick: 8, end_tick: 24, params: { direction: 'up', period: 5 }, source: '/patterns/run/effects/4' },
    { channel: 3, kind: 'noise_retrig', start_tick: 0, end_tick: 16, params: { period: 2, note: 'C4' }, source: '/patterns/run/effects/5' },
  ];
  const commands = [
    { channel: 0, kind: 'set_tempo', start_tick: 2, end_tick: 2, params: { value: 100 }, global: true, source: '/patterns/run/commands/0' },
    { channel: 0, kind: 'add_tempo', start_tick: 12, end_tick: 12, params: { value: -3 }, global: true, source: '/patterns/run/commands/1' },
    { channel: 0, kind: 'set_transposition', start_tick: 18, end_tick: 18, params: { value: -12 }, global: false, source: '/patterns/run/commands/2' },
    { channel: 0, kind: 'add_transposition', start_tick: 24, end_tick: 24, params: { value: 5 }, global: false, source: '/patterns/run/commands/3' },
    { channel: 1, kind: 'set_volume', start_tick: 8, end_tick: 8, params: { value: 90 }, global: false, source: '/patterns/run/commands/4' },
    { channel: 1, kind: 'set_mod', start_tick: 16, end_tick: 16, params: { value: 40 }, global: false, source: '/patterns/run/commands/5' },
    { channel: 3, kind: 'cue', start_tick: 4, end_tick: 4, params: { value: 7 }, global: true, source: '/patterns/run/commands/6' },
  ];
  const data = {
    payload: 'atmlib-inspect',
    score_id: 'effect_viewer_probe',
    audio: null,
    review: {
      total_ticks: 64,
      clock: { tick_rate: 100, effective_tick_rate: 100, ticks_per_beat: 16, beats_per_bar: 4 },
      channels,
      notes: [{
        channel: 0, start_tick: 0, duration: 8, gate_end_tick: 8, note: 'C4',
        note_index: 24, instrument: 'lead', volume: 90, duty: 64,
        pattern: 'run', repeat_index: 0, pattern_instance_index: 0,
        source: '/patterns/run/events/0',
      }],
      pattern_instances: [],
      effects,
      commands,
      event_digest: { hex: 'test', canonicalization: 'test' },
      diagnostics: [],
      capabilities: {},
    },
    capabilities: {},
  };

  const nodes = new Map();
  const get = id => {
    if (!nodes.has(id)) nodes.set(id, new Element());
    return nodes.get(id);
  };
  get('atmlib-data').textContent = JSON.stringify(data);
  const document = {
    getElementById: get,
    createElement: tag => new Element(tag),
    createTextNode: text => ({ textContent: text }),
    body: new Element('body'),
    querySelector: get,
    addEventListener() {},
  };
  const window = { addEventListener() {} };
  const sandbox = { window, document, requestAnimationFrame() {}, Uint8Array, DataView };
  for (const file of ['effects.js', 'loop.js', 'viewer.js']) {
    vm.runInNewContext(readFileSync(new URL(file, assets), 'utf8'), sandbox);
  }

  assert.equal(get('automation-panel').hidden, false);
  assert.equal(get('effect-legend').hidden, false);
  assert.equal(get('automation-list').children.length, effects.length + commands.length);
  assert.equal(get('effect-legend').children.length, effects.length + 1,
    'one swatch per effect kind plus the command key');
  const totals = get('totals').children.map(node => node.textContent);
  assert.ok(totals.includes('Expanded effect windows'));
  assert.ok(totals.includes('Expanded live commands'));
  assert.ok((counts.fillRect || 0) > 0, 'effect bands draw on the roll canvas');
  assert.ok((counts.fillText || 0) >= effects.length + commands.length,
    'effect and command labels draw on the roll canvas');
  assert.ok((counts.setLineDash || 0) > 0, 'command ticks use a dashed marker');
  console.log('Viewer effect checks passed (legend, automation list, totals, lane drawing).');
}
