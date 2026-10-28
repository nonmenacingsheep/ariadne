"use strict";
// Her small sound effects, synthesised with Web Audio so there are no files
// to ship. Each one can be muted on its own, plus a master switch and volume
// (from ~/.config/ariadne2/sounds.json, via layer.py). Bursts are coalesced:
// one of a kind per 150 ms, so sorting 200 files is a patter, not 200 clicks.
const Sounds = (() => {
  let ctx = null, out = null, cfg = { master: true, volume: 0.5, muted: [] };
  const lastAt = {};
  function audio() {
    if (!ctx) { ctx = new AudioContext(); out = ctx.createGain(); out.connect(ctx.destination); }
    out.gain.value = 0.35 * cfg.volume;
    return ctx;
  }
  // One enveloped oscillator: frequency glides f0 -> f1 over dur seconds.
  function tone(t, type, f0, f1, dur, peak, attack = 0.004) {
    const c = audio(), o = c.createOscillator(), g = c.createGain();
    o.type = type; o.frequency.setValueAtTime(f0, t); o.frequency.exponentialRampToValueAtTime(f1, t + dur);
    g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(peak, t + attack);
    g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    o.connect(g); g.connect(out); o.start(t); o.stop(t + dur + 0.02);
  }
  // Filtered noise sweep: whooshes and swishes.
  function sweep(t, f0, f1, dur, peak, q = 4) {
    const c = audio(), n = c.createBufferSource(), b = c.createBuffer(1, Math.ceil(c.sampleRate * dur), c.sampleRate);
    const d = b.getChannelData(0); for (let i = 0; i < d.length; i++) d[i] = Math.random() * 2 - 1;
    const f = c.createBiquadFilter(), g = c.createGain();
    f.type = "bandpass"; f.Q.value = q; f.frequency.setValueAtTime(f0, t); f.frequency.exponentialRampToValueAtTime(f1, t + dur);
    g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(peak, t + dur * 0.3); g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    n.buffer = b; n.connect(f); f.connect(g); g.connect(out); n.start(t);
  }
  const KINDS = {
    send:    t => { tone(t, "sine", 880, 1320, 0.07, 0.25); },
    done:    t => { tone(t, "sine", 1320, 1320, 0.06, 0.18); tone(t + 0.06, "sine", 990, 990, 0.09, 0.15); },
    fail:    t => { tone(t, "square", 150, 110, 0.16, 0.08); tone(t + 0.09, "square", 120, 90, 0.16, 0.07); },
    flow:    t => { [660, 880, 1100].forEach((f, i) => tone(t + i * 0.045, "triangle", f, f, 0.08, 0.14)); },
    spotify: t => { tone(t, "triangle", 520, 260, 0.18, 0.2); },
    steam:   t => { tone(t, "sawtooth", 70, 110, 0.25, 0.08, 0.04); },
    browser: t => { tone(t, "sine", 2400, 2200, 0.03, 0.12); },
    dolphin: t => { sweep(t, 800, 3000, 0.16, 0.2); },
    claude:  t => { tone(t, "sine", 1760, 1760, 0.22, 0.12); tone(t, "sine", 2637, 2637, 0.18, 0.05); },
    mic:     t => { tone(t, "sine", 988, 988, 0.08, 0.16); tone(t + 0.08, "sine", 1319, 1319, 0.12, 0.14); },
    raise:   t => { sweep(t, 300, 2600, 0.22, 0.22, 2); },
    drop:    t => { sweep(t, 2600, 300, 0.2, 0.18, 2); },
  };
  return {
    configure(c) { cfg = Object.assign(cfg, c || {}); },
    play(kind) {
      if (!cfg.master || !KINDS[kind] || (cfg.muted || []).includes(kind)) return;
      const now = performance.now();
      if (now - (lastAt[kind] || 0) < 150) return;
      lastAt[kind] = now;
      try { const c = audio(); if (c.state === "suspended") c.resume(); KINDS[kind](c.currentTime + 0.01); } catch (e) { /* no audio device */ }
    },
    kinds: Object.keys(KINDS),
  };
})();
