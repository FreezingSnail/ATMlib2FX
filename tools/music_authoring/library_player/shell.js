/*
 * Library player shell (ATMlib2FX-3ii.12).
 *
 * One page, one active review. The shell reads the inert embedded bundle
 * (canonical standalone review HTML per song), mounts exactly ONE iframe on
 * selection, and tears the previous document down before mounting the next so
 * there is never more than one live review/audio element.
 *
 * The embedded viewer is reused unchanged: the shell never draws the timeline,
 * never parses a score and never plays audio on its own. Playback only ever
 * starts when the user presses the viewer's Play button (no autoplay).
 */
(function () {
  "use strict";

  var bundleEl = document.getElementById("atmlib-library");
  var stage = document.getElementById("lp-stage");
  var select = document.getElementById("lp-select");
  var folderSelect = document.getElementById("lp-folder");
  var prevBtn = document.getElementById("lp-prev");
  var nextBtn = document.getElementById("lp-next");
  var contextEl = document.getElementById("lp-context");
  var statusEl = document.getElementById("lp-status");
  var metaEl = document.getElementById("lp-meta");

  function setStatus(message) {
    if (statusEl) statusEl.textContent = message;
  }

  var bundle = null;
  try {
    bundle = JSON.parse(bundleEl.textContent || "{}");
  } catch (err) {
    setStatus("The embedded library bundle could not be parsed; the page cannot list songs.");
    return;
  }

  var entries = (bundle && Array.isArray(bundle.entries)) ? bundle.entries : [];
  if (!entries.length) {
    setStatus("The library bundle contains no songs.");
    return;
  }

  var index = -1;
  var frame = null;
  var visibleIndices = [];

  function folderFor(entry) {
    return entry.folder || entry.category || "Other";
  }

  function addOption(target, value, label) {
    var opt = document.createElement("option");
    opt.value = value;
    opt.textContent = label;
    target.appendChild(opt);
  }

  var folders = [];
  entries.forEach(function (entry) {
    var name = folderFor(entry);
    if (folders.indexOf(name) === -1) folders.push(name);
  });
  addOption(folderSelect, "", "All folders (" + entries.length + ")");
  folders.forEach(function (name) {
    var count = entries.filter(function (entry) { return folderFor(entry) === name; }).length;
    addOption(folderSelect, name, name + " (" + count + ")");
  });
  folderSelect.value = "";

  function populateSongs() {
    select.textContent = "";
    visibleIndices = [];
    entries.forEach(function (entry, i) {
      if (folderSelect.value && folderFor(entry) !== folderSelect.value) return;
      visibleIndices.push(i);
      // Authored names and folder labels are always inserted as text.
      addOption(select, String(i), entry.name || entry.id || ("Song " + (i + 1)));
    });
    // Retain the playing review when it is still in the selected folder.
    mount(visibleIndices.indexOf(index) !== -1 ? index : visibleIndices[0]);
  }

  function stopAndRemoveFrame() {
    if (!frame) return;
    // Best-effort: pause any media in the outgoing review before its document
    // is destroyed. srcdoc frames are same-origin, so this normally reaches the
    // viewer's audio element; removal guarantees teardown regardless.
    try {
      var cw = frame.contentWindow;
      if (cw && cw.document) {
        var media = cw.document.querySelectorAll("audio, video");
        for (var i = 0; i < media.length; i++) {
          try { media[i].pause(); } catch (e) { /* ignore */ }
        }
      }
    } catch (e) { /* cross-document access is not required */ }
    // Clear the srcdoc first so the outgoing document cannot be reused, then
    // drop the node. There is no frame/document URL or object URL created by
    // this shell to revoke (srcdoc uses about:srcdoc).
    frame.removeAttribute("srcdoc");
    frame.remove();
    frame = null;
  }

  function mount(i) {
    var entry = entries[i];
    if (!entry) return;
    if (i !== index || !frame) {
      stopAndRemoveFrame();
      var el = document.createElement("iframe");
      el.className = "lp-frame";
      el.title = (entry.name || "Song") + " track review";
      // Playback starts only on a user gesture inside the review.
      el.setAttribute("srcdoc", entry.html || "");
      stage.appendChild(el);
      frame = el;
    }
    index = i;

    select.value = String(i);
    contextEl.textContent = entry.context || "";

    var parts = [];
    if (entry.category) parts.push(entry.category);
    if (typeof entry.song_seconds === "number") parts.push(entry.song_seconds.toFixed(2) + " s");
    if (typeof entry.wav_bytes === "number") parts.push(entry.wav_bytes.toLocaleString() + " B WAV");
    if (entry.source_sha256) parts.push("source " + String(entry.source_sha256).slice(0, 12));
    if (entry.event_digest_hex) parts.push("events " + String(entry.event_digest_hex).slice(0, 12));
    metaEl.textContent = parts.join(" \u00b7 ");

    var position = visibleIndices.indexOf(i);
    setStatus("Showing " + (position + 1) + " of " + visibleIndices.length +
      (folderSelect.value ? " in " + folderSelect.value : " across all folders") +
      ": " + (entry.name || ""));
    prevBtn.disabled = position <= 0;
    nextBtn.disabled = position >= visibleIndices.length - 1;
    document.title = "ATMlib example song library \u2014 " + (entry.name || "");
  }

  select.addEventListener("change", function () {
    var i = parseInt(select.value, 10);
    if (!isNaN(i)) mount(i);
  });
  folderSelect.addEventListener("change", populateSongs);
  function moveSong(step) {
    var position = visibleIndices.indexOf(index) + step;
    if (position >= 0 && position < visibleIndices.length) mount(visibleIndices[position]);
  }
  prevBtn.addEventListener("click", function () { moveSong(-1); });
  nextBtn.addEventListener("click", function () { moveSong(1); });

  // Keyboard shortcut: [ and ] move between songs when focus is not in a field.
  document.addEventListener("keydown", function (ev) {
    var t = ev.target;
    var tag = t && t.tagName;
    if (tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA") return;
    if (ev.key === "[") moveSong(-1);
    else if (ev.key === "]") moveSong(1);
  });

  var empty = document.getElementById("lp-empty");
  if (empty && empty.parentNode) empty.parentNode.removeChild(empty);

  // Show the first song's review immediately (paused; no audio until the user
  // presses Play inside the embedded viewer).
  populateSongs();
})();
