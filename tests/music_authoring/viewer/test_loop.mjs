// Exact PCM boundaries, extra RIFF chunks, and bounded-preview rejection.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
const window = {};
vm.runInNewContext(readFileSync(new URL('../../../tools/music_authoring/viewer/loop.js', import.meta.url), 'utf8'), { window });
const wav = new Uint8Array(60 + 20);
const view = new DataView(wav.buffer);
function tag(at, value) { for (let i=0;i<value.length;i++) wav[at+i]=value.charCodeAt(i); }
tag(0,'RIFF'); view.setUint32(4,wav.length-8,true); tag(8,'WAVE');
tag(12,'JUNK'); view.setUint32(16,7,true); // odd-sized chunk and padding
 tag(28,'fmt '); view.setUint32(32,16,true); view.setUint16(36,1,true);
view.setUint16(38,1,true); view.setUint32(40,100,true); view.setUint32(44,200,true);
view.setUint16(48,2,true); view.setUint16(50,16,true);
tag(52,'data'); view.setUint32(56,20,true);
for(let i=0;i<10;i++) view.setInt16(60+i*2,1000+i,true);
const meta = { sample_count:10, sample_rate:100, total_ticks:4, effective_tick_rate:100, first_music_callback_sample:2, first_music_callback_measured:true, truncated:false };
const prepared = window.ATMlibLoop.prepare(wav,meta);
assert.equal(prepared.available,true);
assert.equal(prepared.startSample,2); assert.equal(prepared.endSample,6);
assert.equal(prepared.bytes.length,52);
const pcm = new DataView(prepared.bytes.buffer);
assert.equal(pcm.getUint32(40,true),8);
assert.deepEqual(Array.from({length:4},(_,i)=>pcm.getInt16(44+i*2,true)),[1002,1003,1004,1005]);
assert.equal(view.getInt16(60,true),1000); // original capture untouched
for(const patch of [{truncated:true},{first_music_callback_measured:false},{first_music_callback_sample:null},{first_music_callback_sample:-1},{total_ticks:9}]) {
 const result = window.ATMlibLoop.prepare(wav,{...meta,...patch});
 assert.equal(result.available,false); assert.equal(result.bytes,wav);
}
assert.equal(window.ATMlibLoop.prepare(wav.subarray(0,70),meta).available,false);
console.log('Loop PCM checks passed (sample boundaries, RIFF chunks, immutable capture, bounded preview).');
