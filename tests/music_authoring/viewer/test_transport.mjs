// DOM/media adapter test: production viewer wiring with real embedded metadata.
// This exercises clock translation and controls; native browser decoding/loop
// scheduling is covered separately by walkthrough.mjs when Chrome is available.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
const assets = new URL('../../../tools/music_authoring/viewer/', import.meta.url);
const html = readFileSync(new URL('../../../examples/music_authoring/basic/review.html', import.meta.url), 'utf8');
const original = JSON.parse(html.match(/<script type="application\/json" id="atmlib-data">(.*?)<\/script>/s)[1]);

class Element {
  constructor(tag='div') {
    this.tagName=tag.toUpperCase(); this.style={}; this.children=[]; this.events={}; this.dataset={};
    this.textContent=''; this.clientWidth=640; this.currentTime=0; this.paused=true; this.ended=false;
  }
  get firstChild() { return this.children[0]; }
  appendChild(node) { this.children.push(node); node.parentNode=this; return node; }
  removeChild(node) { this.children.splice(this.children.indexOf(node),1); }
  setAttribute(key,value) { this[key]=value; }
  addEventListener(name,fn) { (this.events[name] ||= []).push(fn); }
  async emit(name,event={}) { for(const fn of this.events[name] || []) await fn({target:this,...event}); }
  querySelector() { return new Element(); }
  querySelectorAll() { return []; }
  getBoundingClientRect() { return {left:0,top:0,width:640}; }
  getContext() { return new Proxy({}, {get:(_,key)=>key==='measureText' ? ()=>({width:10}) : ()=>{},set:()=>true}); }
  async play() { this.paused=false; }
  pause() { this.paused=true; }
}
for(const truncated of [false,true]) {
  const data=structuredClone(original);
  data.audio.truncated=truncated;
  const nodes=new Map(); const created=[]; const blobs=[];
  const get=id=>{if(!nodes.has(id)) nodes.set(id,new Element());return nodes.get(id);};
  get('atmlib-data').textContent=JSON.stringify(data);
  const document={ getElementById:get, createElement:tag=>{const e=new Element(tag);created.push(e);return e;},
    createTextNode:text=>({textContent:text}),body:new Element('body'),
    querySelector:get,addEventListener(){} };
  const window={ atob:value=>Buffer.from(value,'base64').toString('binary'),addEventListener(){},
    ATMlibAudition:{createRouter:()=>({mode:'raw',async resume(){},async select(mode){this.mode=mode;},async close(){}})} };
  const context={ window,document,Blob,URL:{createObjectURL:blob=>{blobs.push(blob);return 'blob:test';},revokeObjectURL(){}},
    requestAnimationFrame(){}, Uint8Array,DataView };
  for(const file of ['loop.js','viewer.js']) vm.runInNewContext(readFileSync(new URL(file,assets),'utf8'),context);
  const media=created.find(e=>e.tagName==='AUDIO'); assert.ok(media);
  await media.emit('loadedmetadata');
  const loop=get('loop-preview');
  assert.equal(loop.disabled,truncated);assert.equal(loop.checked,!truncated);assert.equal(media.loop,!truncated);
  const first=data.audio.first_music_callback_sample/data.audio.sample_rate;
  const seconds=data.audio.total_ticks/data.audio.effective_tick_rate;
  const offset=truncated ? first : 0;
  await get('btn-restart').emit('click');assert.equal(media.currentTime,offset);
  get('seek').value=500;await get('seek').emit('input');
  const end=truncated ? Math.min(data.audio.sample_count/data.audio.sample_rate,first+data.audio.rendered_ticks/data.audio.effective_tick_rate) : seconds;
  assert.ok(Math.abs(media.currentTime-(offset+(end-offset)/2))<0.00003);
  await get('roll').emit('click',{clientX:320,clientY:10});
  assert.ok(Math.abs(media.currentTime-(seconds/2+offset))<0.00003,'ruler maps the cropped media clock');
  await get('btn-play').emit('click');assert.equal(media.paused,false);assert.equal(get('btn-play').textContent,'Pause');
  await get('btn-play').emit('click');assert.equal(media.paused,true);
  loop.checked=false;await loop.emit('change');assert.equal(media.loop,false);
  await media.emit('ended');assert.equal(get('btn-play').textContent,'Play');
  get('sound-profile').value='piezo';await get('sound-profile').emit('change');assert.equal(get('sound-profile').value,'piezo');
  if(!truncated) {
    const bytes=new Uint8Array(await blobs[0].arrayBuffer());const view=new DataView(bytes.buffer);
    assert.equal(view.getUint32(40,true)/2,Math.round(seconds*data.audio.sample_rate));
  }
}
console.log('Viewer transport checks passed (loop default, cropped clock, slider/ruler, restart, pause, end, sound profile, truncated fallback).');
