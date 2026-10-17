// Routing/lifecycle checks using the browser-independent native-Web-Audio adapter.
// Run: node tests/music_authoring/viewer/test_piezo.mjs
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const code = readFileSync(new URL('../../../tools/music_authoring/viewer/piezo.js', import.meta.url), 'utf8');

function parameter(value = 0) {
  return {
    value, target: value,
    cancelScheduledValues() {},
    setValueAtTime(value) { this.value = value; },
    linearRampToValueAtTime(value) { this.value = this.target = value; }
  };
}

function makeWindow(options = {}) {
  const contexts = [];
  class Context {
    constructor() {
      if (options.constructorFails) throw new Error('device unavailable');
      this.state = 'suspended';
      this.currentTime = 5;
      this.destination = { name: 'destination' };
      this.sources = [];
      contexts.push(this);
    }
    async resume() {
      if (options.denyResume) throw new Error('blocked');
      if (options.resumeGate) await options.resumeGate;
      this.state = 'running';
    }
    async close() { this.state = 'closed'; }
    node() {
      return {
        connections: [],
        connect(node) { this.connections.push(node); },
        disconnect() { this.connections = []; }
      };
    }
    createGain() { return Object.assign(this.node(), { gain: parameter(1) }); }
    createBiquadFilter() {
      return Object.assign(this.node(), {
        frequency: parameter(), Q: parameter(), gain: parameter()
      });
    }
    createMediaElementSource(mediaElement) {
      const source = Object.assign(this.node(), { mediaElement });
      if (options.connectionFails) {
        let count = 0;
        source.connect = function (node) {
          if (++count === 2) throw new Error('connection failed');
          this.connections.push(node);
        };
      }
      this.sources.push(source);
      return source;
    }
  }
  const window = { setTimeout, clearTimeout };
  if (!options.unsupported) window.AudioContext = Context;
  vm.runInNewContext(code, { window });
  return { api: window.ATMlibAudition, contexts };
}

function media() { return { src: 'blob:original-wav', currentTime: 2.75, playbackRate: 1, paused: true }; }

// Raw never initializes Web Audio, and toggles retain the exact media identity
// and position. One element is never attached to a second audio source.
{
  const { api, contexts } = makeWindow();
  const original = media();
  const before = { ...original };
  const router = api.createRouter(original);
  assert.equal(await router.select('raw'), 'raw');
  assert.equal(contexts.length, 0);
  assert.equal(await router.select('piezo'), 'piezo');
  assert.equal(contexts.length, 1);
  assert.equal(router.context.sources.length, 1);
  assert.equal(router.source.mediaElement, original);
  assert.equal(router.rawGain.gain.target, 0);
  assert.equal(router.piezoGain.gain.target, 1);
  assert.deepEqual(original, before);
  assert.equal(await router.select('raw'), 'raw');
  assert.equal(router.rawGain.gain.target, 1);
  assert.equal(router.piezoGain.gain.target, 0);
  await router.select('piezo');
  await router.select('raw');
  assert.equal(contexts.length, 1);
  assert.equal(router.context.sources.length, 1);
  assert.deepEqual(original, before);
  router.context.state = 'suspended';
  await router.resume();
  assert.equal(router.context.state, 'running');
  await router.close();
}

// A late initialization cannot turn piezo back on after the user chose Raw.
{
  let release;
  const gate = new Promise(resolve => { release = resolve; });
  const { api, contexts } = makeWindow({ resumeGate: gate });
  const router = api.createRouter(media());
  const first = router.select('piezo');
  const second = router.select('raw');
  release();
  await Promise.all([first, second]);
  assert.equal(router.mode, 'raw');
  assert.equal(router.rawGain.gain.target, 1);
  assert.equal(router.piezoGain.gain.target, 0);
  assert.equal(contexts.length, 1);
  await router.close();
}

// Missing API, a device error or autoplay rejection must leave the native media
// unattached and therefore still usable for raw playback.
for (const options of [{ unsupported: true }, { constructorFails: true }, { denyResume: true }]) {
  const { api, contexts } = makeWindow(options);
  const original = media();
  const before = { ...original };
  const router = api.createRouter(original);
  await assert.rejects(router.select('piezo'));
  assert.equal(router.mode, 'raw');
  assert.equal(router.failed, true);
  assert.equal(router.source, null);
  assert.deepEqual(original, before);
  for (const context of contexts) {
    assert.equal(context.sources.length, 0);
    assert.equal(context.state, 'closed');
  }
  assert.equal(await router.select('raw'), 'raw');
}

// Autoplay policy can leave resume pending instead of rejecting it. The
// bounded wait must still restore raw controls without capturing the element.
{
  const { api, contexts } = makeWindow({ resumeGate: new Promise(() => {}) });
  const router = api.createRouter(media());
  await assert.rejects(router.select('piezo'), /did not enable/);
  assert.equal(router.mode, 'raw');
  assert.equal(router.source, null);
  assert.equal(contexts[0].state, 'closed');
  assert.equal(await router.select('raw'), 'raw');
}

// An exceptional failure after capture retains a live direct raw route rather
// than closing the context and silently muting the media element.
{
  const { api } = makeWindow({ connectionFails: true });
  const router = api.createRouter(media());
  await assert.rejects(router.select('piezo'));
  assert.equal(router.mode, 'raw');
  assert.equal(router.context.state, 'running');
  assert.deepEqual(router.source.connections, [router.context.destination]);
  await router.close();
}

console.log('Piezo routing/lifecycle checks passed (raw bypass, single source, race, fallback, resume).');
