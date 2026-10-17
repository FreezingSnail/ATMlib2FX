/* Optional browser-only piezo coloration. All values are heuristic, not a
 * measured Arduboy speaker response. The original media/WAV stays untouched.
 */
(function (root) {
  "use strict";

  function createPiezoChain(context) {
    var highpass = context.createBiquadFilter();
    highpass.type = "highpass";
    highpass.frequency.value = 700;
    // Web Audio high/low-pass Q is in dB: -3.0103 dB is linear Q=1/sqrt(2).
    highpass.Q.value = -3.010299956639812;

    var resonance = context.createBiquadFilter();
    resonance.type = "peaking";
    resonance.frequency.value = 3300;
    resonance.Q.value = 1.4; // Peaking-filter Q is linear.
    resonance.gain.value = 6;

    var lowpass = context.createBiquadFilter();
    lowpass.type = "lowpass";
    lowpass.frequency.value = 7000;
    lowpass.Q.value = -3.010299956639812;

    var output = context.createGain();
    output.gain.value = 0.5; // Headroom for the +6 dB resonant band.
    highpass.connect(resonance);
    resonance.connect(lowpass);
    lowpass.connect(output);
    return { input: highpass, output: output, filters: [highpass, resonance, lowpass] };
  }

  function resumeContext(context) {
    if (context.state === "running") return Promise.resolve();
    // Some browsers leave resume pending when processing is disallowed. Do not
    // capture the media element until a running context has been established.
    return new Promise(function (resolve, reject) {
      var timeout = root.setTimeout(function () {
        reject(new Error("Browser did not enable audio processing."));
      }, 2500);
      Promise.resolve().then(function () { return context.resume(); }).then(function () {
        root.clearTimeout(timeout);
        if (context.state === "running") resolve();
        else reject(new Error("Browser did not enable audio processing."));
      }, function (error) {
        root.clearTimeout(timeout);
        reject(error);
      });
    });
  }

  function ramp(param, value, now) {
    param.cancelScheduledValues(now);
    param.setValueAtTime(param.value, now);
    param.linearRampToValueAtTime(value, now + 0.02);
  }

  function createRouter(media) {
    var router = {
      mode: "raw",
      requested: "raw",
      context: null,
      source: null,
      rawGain: null,
      piezoGain: null,
      pending: null,
      failed: false
    };

    function apply() {
      if (!router.rawGain) return;
      var piezo = router.requested === "piezo";
      var now = router.context.currentTime;
      ramp(router.rawGain.gain, piezo ? 0 : 1, now);
      ramp(router.piezoGain.gain, piezo ? 1 : 0, now);
      router.mode = piezo ? "piezo" : "raw";
    }

    function ensureRouting() {
      if (router.rawGain) return Promise.resolve();
      if (router.pending) return router.pending;
      router.pending = (async function () {
        var Constructor = root.AudioContext || root.webkitAudioContext;
        if (!Constructor) throw new Error("Web Audio is unavailable.");
        var context = new Constructor();
        var source = null;
        try {
          await resumeContext(context);
          var rawGain = context.createGain();
          rawGain.gain.value = 1;
          var piezoGain = context.createGain();
          piezoGain.gain.value = 0;
          var chain = createPiezoChain(context);
          rawGain.connect(context.destination);
          chain.output.connect(piezoGain);
          piezoGain.connect(context.destination);
          // A media element can have only one MediaElementAudioSourceNode.
          // Create it once, after all other setup, and reuse both branches.
          source = context.createMediaElementSource(media);
          source.connect(rawGain);
          source.connect(chain.input);
          router.context = context;
          router.source = source;
          router.rawGain = rawGain;
          router.piezoGain = piezoGain;
        } catch (error) {
          if (source) {
            // If attachment succeeded but routing failed, retain a direct raw
            // route. Closing this context would silence the captured element.
            source.disconnect();
            source.connect(context.destination);
            router.context = context;
            router.source = source;
          } else {
            await context.close().catch(function () {});
          }
          throw error;
        }
      })();
      return router.pending.finally(function () { router.pending = null; });
    }

    router.select = async function (mode) {
      if (mode !== "raw" && mode !== "piezo") throw new Error("Unknown sound profile.");
      router.requested = mode;
      if (router.failed) {
        router.mode = "raw";
        router.requested = "raw";
        if (mode === "piezo") throw new Error("Piezo processing is unavailable.");
        return router.mode;
      }
      if (mode === "raw" && !router.context && !router.pending) return router.mode;
      try {
        await ensureRouting();
        apply(); // Read latest requested mode, including changes during setup.
        return router.mode;
      } catch (error) {
        router.failed = true;
        router.mode = "raw";
        router.requested = "raw";
        throw error;
      }
    };
    router.resume = function () {
      return router.context ? resumeContext(router.context) : Promise.resolve();
    };
    router.close = function () {
      return router.context ? router.context.close() : Promise.resolve();
    };
    return router;
  }

  root.ATMlibAudition = { createRouter: createRouter, createPiezoChain: createPiezoChain };
})(window);
