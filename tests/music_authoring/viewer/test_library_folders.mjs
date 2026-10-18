// Folder navigation must retain one review and stop outgoing audio.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

let paused = 0;
const frames = [];
class Element {
  constructor(tag = 'div') {
    this.tagName = tag.toUpperCase();
    this.children = [];
    this.listeners = {};
    this.attributes = {};
    this.value = '';
    this._text = '';
    if (tag === 'iframe') {
      frames.push(this);
      this.contentWindow = { document: { querySelectorAll: () => [{ pause() { paused++; } }] } };
    }
  }
  set textContent(value) {
    this._text = value;
    this.children = [];
  }
  get textContent() { return this._text; }
  appendChild(child) { this.children.push(child); child.parentNode = this; }
  removeChild(child) { this.children = this.children.filter(c => c !== child); child.parentNode = null; }
  remove() { this.parentNode?.removeChild(this); }
  setAttribute(key, value) { this.attributes[key] = value; }
  removeAttribute(key) { delete this.attributes[key]; }
  addEventListener(type, listener) { this.listeners[type] = listener; }
  dispatch(type, extra = {}) { this.listeners[type]?.({ target: this, ...extra }); }
}
const catalog = JSON.parse(readFileSync(new URL('../../../examples/music_authoring/catalog.json', import.meta.url)));
const entries = catalog.entries.map(e => ({ ...e, html: '<p>Review</p>' }));
const ids = ['atmlib-library','lp-stage','lp-select','lp-folder','lp-prev','lp-next','lp-context','lp-status','lp-meta','lp-empty'];
const elements = Object.fromEntries(ids.map(id => [id, new Element(id.includes('select') || id === 'lp-folder' ? 'select' : 'div')]));
elements['atmlib-library'].textContent = JSON.stringify({ entries });
elements['lp-stage'].appendChild(elements['lp-empty']);
const document = {
  getElementById: id => elements[id],
  createElement: tag => new Element(tag),
  addEventListener(type, fn) { this[type] = fn; },
};
const script = readFileSync(new URL('../../../tools/music_authoring/library_player/shell.js', import.meta.url), 'utf8');
vm.runInNewContext(script, { document });
const songs = elements['lp-select'];
const folders = elements['lp-folder'];
const stage = elements['lp-stage'];
const previous = elements['lp-prev'];
const next = elements['lp-next'];
assert.equal(songs.children.length, 21);
assert.deepEqual(folders.children.map(o => o.textContent), [
  'All folders (21)', 'Creature Gatherer (11)', 'Authoring Examples (3)', 'Creature Frontiers (7)',
]);
assert.equal(stage.children.length, 1);
assert.equal(previous.disabled, true);

folders.value = 'Creature Frontiers';
folders.dispatch('change');
assert.equal(songs.children.length, 7);
assert.equal(songs.children[0].textContent, 'Pocket Nursery');
assert.equal(songs.value, '14');
assert.equal(paused, 1);
assert.equal(stage.children.length, 1);
assert.match(elements['lp-status'].textContent, /Showing 1 of 7 in Creature Frontiers/);
for (let i = 0; i < 6; i++) next.dispatch('click');
assert.equal(songs.value, '20');
assert.equal(next.disabled, true);
const last = stage.children[0];
next.dispatch('click');
assert.equal(stage.children[0], last);

// All folders retains the active review and its playback state.
const pausedBefore = paused;
folders.value = '';
folders.dispatch('change');
assert.equal(stage.children[0], last);
assert.equal(paused, pausedBefore);
assert.equal(songs.children.length, 21);

folders.value = 'Authoring Examples';
folders.dispatch('change');
assert.equal(songs.children.length, 3);
assert.equal(songs.value, '5');
document.keydown({ target: { tagName: 'BODY' }, key: ']' });
assert.equal(songs.value, '6');
document.keydown({ target: { tagName: 'SELECT' }, key: ']' });
assert.equal(songs.value, '6');
previous.dispatch('click');
assert.equal(songs.value, '5');
assert.equal(previous.disabled, true);
assert.equal(stage.children.length, 1);
assert.equal(frames.filter(f => f.parentNode).length, 1);
assert.equal(frames.filter(f => !f.parentNode).every(f => !('srcdoc' in f.attributes)), true);

// Older catalogs fall back to category; authored folder names remain literal text.
const legacy = [
  { id: 'one', name: 'Legacy', category: 'Old category' },
  { id: 'two', name: 'Literal', folder: '<img src=x onerror=alert(1)>' },
  { id: 'three', name: 'Unfiled' },
];
for (const id of ['lp-select','lp-folder']) elements[id] = new Element('select');
elements['lp-stage'] = new Element();
elements['atmlib-library'].textContent = JSON.stringify({ entries: legacy });
vm.runInNewContext(script, { document });
assert.deepEqual(elements['lp-folder'].children.map(o => o.textContent), [
  'All folders (3)', 'Old category (1)', '<img src=x onerror=alert(1)> (1)', 'Other (1)',
]);
assert.equal(elements['lp-folder'].children[2].children.length, 0);
console.log('Library folders passed: all 21 tracks, counts, filtering, bounded navigation, keyboard, retained playback, teardown and legacy catalogs.');
