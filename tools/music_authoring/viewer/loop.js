/* Build a browser playback WAV containing exactly one complete musical cycle.
 * The embedded capture and its provenance stay untouched. Native audio.loop
 * repeats the PCM region without reintroducing AVR startup or capture tail.
 */
(function (root) {
  "use strict";
  function prepare(bytes, audio) {
    var fallback = { bytes: bytes, startSample: 0, endSample: audio.sample_count, available: false };
    if (audio.truncated || !audio.first_music_callback_measured ||
        !Number.isInteger(audio.first_music_callback_sample) ||
        audio.first_music_callback_sample < 0 || !(audio.total_ticks > 0) ||
        !(audio.effective_tick_rate > 0)) return fallback;
    var start = audio.first_music_callback_sample;
    var length = Math.round(audio.total_ticks / audio.effective_tick_rate * audio.sample_rate);
    if (length < 1 || start + length > audio.sample_count) return fallback;
    var view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    function tag(at) { return String.fromCharCode.apply(null, bytes.subarray(at, at + 4)); }
    if (bytes.length < 12 || tag(0) !== "RIFF" || tag(8) !== "WAVE") return fallback;
    var fmt = null, pcm = null;
    for (var at = 12; at + 8 <= bytes.length;) {
      var size = view.getUint32(at + 4, true);
      if (at + 8 + size > bytes.length) return fallback;
      if (tag(at) === "fmt ") fmt = bytes.subarray(at + 8, at + 8 + size);
      if (tag(at) === "data") pcm = bytes.subarray(at + 8, at + 8 + size);
      at += 8 + size + (size % 2);
    }
    if (!fmt || fmt.length < 16 || !pcm) return fallback;
    var format = new DataView(fmt.buffer, fmt.byteOffset, fmt.byteLength);
    var align = format.getUint16(12, true);
    if (format.getUint16(0, true) !== 1 || !align ||
        format.getUint32(4, true) !== audio.sample_rate ||
        (start + length) * align > pcm.length) return fallback;
    var result = new Uint8Array(44 + length * align);
    var header = new DataView(result.buffer);
    function writeTag(at, text) {
      for (var i = 0; i < text.length; i++) result[at + i] = text.charCodeAt(i);
    }
    writeTag(0, "RIFF"); header.setUint32(4, result.length - 8, true);
    writeTag(8, "WAVE"); writeTag(12, "fmt "); header.setUint32(16, 16, true);
    result.set(fmt.subarray(0, 16), 20);
    writeTag(36, "data"); header.setUint32(40, length * align, true);
    result.set(pcm.subarray(start * align, (start + length) * align), 44);
    return { bytes: result, startSample: start, endSample: start + length, available: true };
  }
  root.ATMlibLoop = { prepare: prepare };
})(window);
