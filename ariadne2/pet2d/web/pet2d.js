"use strict";
// Her Live2D body (ariadne2/pet2d). The model sits in a small canvas that moves
// about a full-screen transparent page; only the box around her takes clicks.
//
// She stands on the floor (the panel's top) or on a widget's top edge, wanders
// and hops between them, can be picked up and thrown (a hard landing leaves her
// dizzy), sleeps when left alone, and her face follows the core: lip sync from
// her voice's level, and her voice's emotion marks onto the rig's expression
// switches. Hair, tail and clothes swing from the rig's own physics, driven by
// how she leans and tilts while she moves.

const pet = (() => {
  const post = m => { try { window.webkit.messageHandlers.pet.postMessage(JSON.stringify(m)); } catch (e) {} };
  const log = msg => post({ t: "log", msg: String(msg) });
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
  const now = () => performance.now() / 1000;

  // Her moods. These use the usual Cubism parameter names, so they work on
  // most models; each model's about.json adds the rest ("looks": a mood ->
  // the name of one of its expressions, or -> parameter targets of its own),
  // made by importer.py from its expressions' names. Eased in and out.
  const BASE_LOOKS = {
    smile:   { ParamEyeLSmile: 0.8, ParamEyeRSmile: 0.8, ParamMouthForm: 1 },
    wide:    { ParamBrowLY: 0.8, ParamBrowRY: 0.8, ParamEyeLOpen: 1.15, ParamEyeROpen: 1.15 },
    sleepy:  { ParamEyeLOpen: 0.45, ParamEyeROpen: 0.45, ParamBrowLY: -0.3, ParamBrowRY: -0.3 },
    dizzy:   { ParamMouthForm: -0.4 },
    asleep:  { ParamEyeLOpen: 0, ParamEyeROpen: 0, ParamMouthForm: 0.3 },
    soft:    { ParamBrowLY: -0.4, ParamBrowRY: -0.4, ParamMouthForm: 0.35, ParamEyeLSmile: 0.3, ParamEyeRSmile: 0.3 },
    smirk:   { ParamEyeLSmile: 0.45, ParamEyeRSmile: 0.45, ParamMouthForm: 0.6, ParamBrowRY: 0.5, ParamBrowLY: -0.2 },
    thoughtful: { ParamEyeLOpen: 0.8, ParamEyeROpen: 0.8, ParamBrowLY: 0.35, ParamBrowRY: 0.1, ParamMouthForm: -0.15 },
    angry:   { ParamBrowRForm: -1, ParamBrowLForm: -1, ParamMouthForm: -1 },
    tears:   { ParamMouthForm: -0.8, ParamBrowLY: -0.5, ParamBrowRY: -0.5 },
  };
  // A mood this model can't show falls back to one it can.
  const FALLBACK = { stars: "smile", hearts: "smile", blush: "smile", eyeroll: "smirk", gloom: "sleepy" };
  let LOOKS = { ...BASE_LOOKS }, EXPR = {}, exprOn = "";
  const EMOTION_LOOK = {
    happy: "smile", content: "smile", peaceful: "smile", serene: "smile", calm: "smile", grateful: "blush",
    confident: "smile", proud: "smile", trust: "smile", nostalgic: "smile", determined: "smile",
    excited: "stars", enthusiastic: "stars", elated: "stars", euphoric: "stars", triumphant: "stars", amazed: "stars",
    affectionate: "hearts", flirtatious: "hearts",
    insecure: "blush", hesitant: "blush", apologetic: "blush", guilty: "blush",
    angry: "angry", mad: "angry", outraged: "angry", frustrated: "angry", agitated: "angry",
    sad: "tears", dejected: "tears", melancholic: "tears", hurt: "tears", rejected: "tears",
    sarcastic: "eyeroll", ironic: "eyeroll", contempt: "eyeroll", skeptical: "eyeroll", envious: "eyeroll",
    disappointed: "gloom", disgusted: "gloom", threatened: "gloom", scared: "gloom", panicked: "gloom",
    alarmed: "wide", anxious: "gloom", surprised: "wide", curious: "wide", confused: "wide",
    tired: "sleepy", bored: "sleepy", resigned: "sleepy", wistful: "sleepy", distant: "sleepy",
    sympathetic: "soft", mysterious: "smirk", contemplative: "thoughtful", anticipation: "wide",
  };

  let app = null, model = null, canvas = null, loadingUri = "";
  let W = innerWidth || 3440, H = innerHeight || 1366;
  const opt = { size: 300, fps_cap: 30, sleep_after: 8, wander: true, sit_on_widgets: true,
                walk_off_edges: true, nap: true, lip_sync: true, react_to_work: true,
                pinned: false, dance_to_music: true };
  let surfaces = [];                       // [{x0, x1, y}] widget tops she can stand on
  // Her feet's centre, in page pixels; velocity in px/s.
  const me = { x: 1700, y: 1366, vx: 0, vy: 0, mode: "fall", on: null, target: null, until: 0,
               lastStir: now(), lean: 0, tilt: 0, bob: 0 };
  const face = { look: "", until: 0, w: {}, mouth: 0, speaking: false, level: 0, gaze: { x: 0, y: 0 } };
  let held = null, pokes = [], hitKey = "";
  let dispW = 0, dispH = 0, cw = 0, ch = 0;
  let pinPos = null;                       // where she was pinned (saved by the host)
  // The beat clock: real beats from the music (beats.py) re-anchor it; between
  // and without them it keeps time on its own.
  let music = false;
  const beat = { period: 0.53, last: 0, count: 0, energy: 0.5, heard: 0 };
  const dance = { bob: 0 };
  const MOVES = ["sway", "bounce", "groove", "hop"];

  // ------------------------------------------------------------------ model
  async function load(uri) {
    if (uri === loadingUri) return;
    loadingUri = uri;
    unload();
    try {
      if (!app) {
        app = new PIXI.Application({ width: 10, height: 10, backgroundAlpha: 0, antialias: true,
                                     autoStart: true, resolution: 1 });
        canvas = app.view;
        document.body.appendChild(canvas);
        canvas.addEventListener("pointerdown", down);
        // WebKit's own menu would take the pointer mid-grab; she has no menu, so none at all.
        addEventListener("contextmenu", e => e.preventDefault());
        canvas.addEventListener("pointercancel", () => { if (held) up(); });
        addEventListener("blur", () => { if (held) up(); });
        addEventListener("pointermove", move);
        addEventListener("pointerup", up);
        app.ticker.add(() => frame(Math.min(app.ticker.deltaMS / 1000, 0.1)));
      }
      LOOKS = { ...BASE_LOOKS }; EXPR = {}; exprOn = "";
      try {
        const about = await (await fetch(new URL("about.json", uri))).json();
        for (const [look, v] of Object.entries(about.looks || {})) {
          if (typeof v === "string") EXPR[look] = v;                 // one of its expressions, by name
          else if (v && typeof v === "object") LOOKS[look] = v;      // its own parameter targets
        }
      } catch (e) { /* no about.json: the base looks only */ }
      const m = await PIXI.live2d.Live2DModel.from(uri, { autoInteract: false, autoUpdate: false });
      if (uri !== loadingUri) { m.destroy(); return; }
      model = m;
      app.stage.addChild(model);
      model.internalModel.on("beforeModelUpdate", drive);
      fit();
      me.x = clamp(me.x, dispW / 2, W - dispW / 2);
      me.mode = "fall"; me.vy = 0; me.y = Math.min(me.y, H - 1);
      if (opt.pinned) {
        if (pinPos) { me.x = clamp(pinPos.x, dispW / 2, W - dispW / 2); me.y = clamp(pinPos.y, dispH * 0.3, H); }
        me.mode = "pinned";
      }
      canvas.style.display = "block";
    } catch (e) { log("couldn't load " + uri + ": " + e); loadingUri = ""; }
  }
  function unload() {
    if (model) { app.stage.removeChild(model); model.destroy(); model = null; }
    if (canvas) canvas.style.display = "none";
    report(true);
  }
  // Her height follows the Avatar "size" (px per metre), as the 3D body's does.
  function fit() {
    if (!model) return;
    const h = clamp(opt.size, 200, 840) * 1.62;
    const s = h / model.internalModel.height;
    model.scale.set(s);
    dispW = model.internalModel.width * s; dispH = h;
    cw = Math.ceil(dispW * 2.4); ch = Math.ceil(dispH * 1.15);
    app.renderer.resize(cw, ch);
    model.x = (cw - dispW) / 2; model.y = ch - dispH;
    place();
  }

  // ---------------------------------------------------------------- the world
  function screen(w, h) { W = w; H = h; me.x = clamp(me.x, dispW / 2 || 100, W - (dispW / 2 || 100)); if (me.y > H) me.y = H; place(); }
  function settings(av) {
    let refit = false;
    const wasPinned = opt.pinned;
    for (const k of Object.keys(opt)) if (k in av) {
      const v = typeof opt[k] === "boolean" ? !!av[k] : Number(av[k]);
      if (k === "size" && v !== opt.size) refit = true;
      opt[k] = v;
    }
    if (refit) fit();
    if (model && opt.pinned && !wasPinned) pin();                       // pinned where she is now
    if (model && !opt.pinned && wasPinned && me.mode === "pinned") { me.mode = "fall"; me.vx = me.vy = 0; }
  }
  function pin() {
    me.mode = "pinned"; me.vx = me.vy = 0; me.on = null;
    pinPos = { x: me.x, y: me.y };
    post({ t: "pin", x: Math.round(me.x), y: Math.round(me.y) });
  }
  function pinAt(x, y) { pinPos = { x, y }; }
  function layout(rects, hidden) {
    const skip = new Set(hidden || []);
    surfaces = Object.entries(rects || {}).filter(([n, r]) => !skip.has(n) && Array.isArray(r) && r.length === 4)
      .map(([name, [x, y, w]]) => ({ name, x0: x + 20, x1: x + w - 20, y })).filter(s => s.name !== "core" && s.x1 - s.x0 > 80 && s.y > 120);
    if (me.mode !== "pinned" && me.on && me.on !== "floor" && !surfaces.some(s => Math.abs(s.y - me.y) < 2 && me.x >= s.x0 && me.x <= s.x1)) {
      me.on = null; me.mode = "fall";         // the widget she stood on moved away
    }
  }
  function groundAt(x, fromY) {        // the first surface at or below fromY under x
    let best = { y: H, s: "floor" };
    for (const s of surfaces) if (x >= s.x0 && x <= s.x1 && s.y >= fromY - 1 && s.y < best.y) best = { y: s.y, s };
    return best;
  }

  // ---------------------------------------------------------------- moving
  function frame(dt) {
    if (!model) return;
    model.update(dt * 1000);              // on this ticker, so the frame cap holds for the rig too
    const t = now();
    tick(t);
    tell(t);
    if (me.mode === "held" || me.mode === "pinned") {
      // follows the pointer (move()); velocity is measured there
    } else if (me.mode === "fall") {
      me.vy += 2600 * dt; me.x += me.vx * dt;
      const before = me.y; me.y += me.vy * dt;
      if (me.x < dispW * 0.8 || me.x > W - dispW * 0.8) { me.x = clamp(me.x, dispW * 0.8, W - dispW * 0.8); me.vx *= -0.55; }
      const g = groundAt(me.x, before);
      if (me.y >= g.y) {
        me.y = g.y;
        if (me.vy > 1400) { me.vy *= -0.28; me.vx *= 0.6; feel("dizzy", 2.4); }
        else { land(g.s); }
      }
    } else if (me.mode === "walk") {
      const dir = Math.sign(me.target - me.x), speed = 150;
      me.x += dir * speed * dt;
      me.bob += dt * 9;
      const g = me.on === "floor" ? null : me.on;
      if (g && (me.x < g.x0 || me.x > g.x1)) {
        if (opt.walk_off_edges) { me.mode = "fall"; me.vx = dir * 120; me.vy = -60; me.on = null; }
        else { me.x = clamp(me.x, g.x0, g.x1); stand(); }
      } else if (Math.abs(me.target - me.x) < 4 || t > me.until) stand();
    } else if (me.mode === "stand" && t > me.until) {
      decide(t);
    }
    // Lean into motion and tilt with the swing: the rig's physics does the rest.
    const lean = me.mode === "walk" ? Math.sign(me.target - me.x) * 8 : me.mode === "held" || me.mode === "fall" ? clamp(me.vx / 60, -25, 25) : 0;
    me.lean += (lean - me.lean) * Math.min(1, dt * 6);
    me.tilt += ((me.mode === "held" ? clamp(-me.vx / 45, -30, 30) : 0) - me.tilt) * Math.min(1, dt * 5);
    // Sleep after long quiet.
    if (opt.nap && (me.mode === "stand" || me.mode === "pinned") && !dancing() && t - me.lastStir > opt.sleep_after * 60 && face.look !== "asleep") feel("asleep", 1e9);
    place();
    const busy = (me.mode !== "stand" && me.mode !== "pinned") || dancing() || face.speaking || t < face.until && face.look !== "asleep" || held;
    app.ticker.maxFPS = face.look === "asleep" ? 10 : busy ? clamp(opt.fps_cap, 10, 60) : Math.max(10, opt.fps_cap / 2);
  }
  function land(s) {
    me.vy = 0; me.vx = 0; me.on = s; stand();
  }
  function stand() { me.mode = "stand"; me.until = now() + 4 + Math.random() * 10; }
  function decide(t) {
    if (face.look === "asleep" || face.speaking || dancing()) { me.until = t + 3; return; }
    const r = Math.random();
    if (opt.sit_on_widgets && r < 0.25 && surfaces.length) {
      // hop to a widget top within reach (or back down to the floor)
      const reach = surfaces.filter(s => s !== me.on && Math.abs((s.x0 + s.x1) / 2 - me.x) < 900 && s.y < me.y + 10);
      const s = reach[Math.floor(Math.random() * reach.length)];
      if (s) { hop(s.x0 + 30 + Math.random() * (s.x1 - s.x0 - 60), s.y); return; }
    }
    if (opt.wander && r < 0.7) {
      const g = me.on && me.on !== "floor" ? me.on : { x0: dispW * 0.8, x1: W - dispW * 0.8 };
      me.target = clamp(me.x + (Math.random() - 0.5) * 900, g.x0, g.x1);
      me.mode = "walk"; me.until = t + 12; return;
    }
    if (me.on && me.on !== "floor" && r > 0.92) { hop(me.x + (Math.random() - 0.5) * 500, H); return; }
    me.until = t + 4 + Math.random() * 8;
  }
  // A ballistic jump that peaks above both ends and lands on (tx, ty).
  function hop(tx, ty) {
    const peak = Math.min(me.y, ty) - 140, g = 2600;
    const up = Math.sqrt(2 * g * Math.max(40, me.y - peak));
    const down = Math.sqrt(2 * Math.max(1, ty - peak) / g);
    const tUp = up / g, T = tUp + down;
    me.vx = (tx - me.x) / T; me.vy = -up; me.mode = "fall"; me.on = null;
  }
  function place() {
    if (!canvas || !model) return;
    const left = Math.round(me.x - cw / 2), top = Math.round(me.y - ch + (me.mode === "walk" ? -Math.abs(Math.sin(me.bob)) * 5 : 0) - dance.bob);
    canvas.style.transform = `translate(${left}px, ${top}px)`;
    report(false, left, top);
  }
  // The box around her body is the only part of the screen that takes clicks.
  function report(clear, left, top) {
    if (clear || !model) { if (hitKey !== "none") { hitKey = "none"; post({ t: "hit", rects: [] }); } return; }
    const r = [Math.round(left + (cw - dispW * 0.62) / 2), Math.round(top + ch - dispH * 0.98), Math.round(dispW * 0.62), Math.round(dispH * 0.98)];
    const k = r.map(v => Math.round(v / 3)).join(",");
    if (k !== hitKey) { hitKey = k; post({ t: "hit", rects: [r] }); }
  }

  // ---------------------------------------------------------------- hands on
  function down(e) {
    if (!model || e.button !== 0) return;      // right/middle click: not a grab (see contextmenu below)
    stir();
    held = { dx: e.clientX - me.x, dy: e.clientY - me.y, x: e.clientX, y: e.clientY, t: now(), moved: 0 };
    canvas.setPointerCapture(e.pointerId);
    canvas.classList.add("held");
  }
  function move(e) {
    if (!model) return;
    const r = canvas.getBoundingClientRect();
    face.gaze = { x: e.clientX - r.left, y: e.clientY - r.top, until: now() + 1.5 };
    if (!held) return;
    const t = now(), dt = Math.max(0.008, t - held.t);
    held.moved += Math.abs(e.clientX - held.x) + Math.abs(e.clientY - held.y);
    if (held.moved > 6 && me.mode !== "held") { me.mode = "held"; me.on = null; feel("wide", 0.8); }
    if (me.mode === "held") {
      me.vx = me.vx * 0.5 + (e.clientX - held.x) / dt * 0.5;
      me.vy = me.vy * 0.5 + (e.clientY - held.y) / dt * 0.5;
      me.x = e.clientX - held.dx; me.y = e.clientY - held.dy;
    }
    held.x = e.clientX; held.y = e.clientY; held.t = t;
  }
  function up() {
    if (!held) return;
    canvas.classList.remove("held");
    const wasHeld = me.mode === "held";
    held = null;
    if (wasHeld && opt.pinned) { pin(); return; }
    if (wasHeld) { me.mode = "fall"; me.vx = clamp(me.vx, -3000, 3000); me.vy = clamp(me.vy, -3000, 3000); return; }
    // A click, not a drag: a poke. A few in a row and she's had enough.
    const t = now();
    pokes = pokes.filter(p => t - p < 4); pokes.push(t);
    if (face.look === "asleep") feel("sleepy", 2);
    else if (pokes.length >= 5) feel("angry", 2.2);
    else if (pokes.length >= 3) feel("eyeroll", 1.8);
    else feel(Math.random() < 0.5 ? "blush" : "smile", 1.6);
  }
  function stir() {
    me.lastStir = now();
    if (face.look === "asleep") { face.look = ""; face.until = 0; feel("sleepy", 1.5); }
  }

  // ---------------------------------------------------------------- her face
  // A model with only a few expressions still shows every mood: each mood
  // tries its nearest relatives among the model's own expressions (or looks
  // tuned for it in about.json) before a generic parameter look.
  const KIN = {
    hearts: ["hearts", "blush", "stars", "smile"], stars: ["stars", "hearts", "smile"],
    blush: ["blush", "hearts", "soft", "smile"], smile: ["smile", "stars"], soft: ["soft", "blush", "smile"],
    smirk: ["smirk", "eyeroll", "smile"], eyeroll: ["eyeroll", "smirk", "gloom"],
    gloom: ["gloom", "tears", "sleepy"], tears: ["tears", "gloom", "sleepy"], angry: ["angry", "gloom", "eyeroll"],
    dizzy: ["dizzy", "eyeroll", "wide"], wide: ["wide", "stars"], thoughtful: ["thoughtful", "sleepy"],
    sleepy: ["sleepy"], asleep: ["asleep"],
  };
  function resolve(look) {
    const kin = KIN[look] || [look];
    return kin.find(k => EXPR[k] || (LOOKS[k] && LOOKS[k] !== BASE_LOOKS[k]))       // the model's own
      || kin.find(k => LOOKS[k]) || FALLBACK[look];
  }
  function feel(look, seconds) {
    look = resolve(look);
    if (look && (LOOKS[look] || EXPR[look])) { face.look = look; face.until = now() + seconds; }
  }
  // An expression-mapped mood is the model's own expression, set and cleared
  // as the mood comes and goes (the parameter looks ease in drive()).
  function expression() {
    const want = EXPR[face.look] || "";
    if (want === exprOn || !model) return;
    exprOn = want;
    const em = model.internalModel.motionManager.expressionManager;
    try { if (want) model.expression(want); else if (em) em.resetExpression(); } catch (e) { log("expression " + want + ": " + e); }
  }
  function drive() {
    const core = model.internalModel.coreModel, t = now(), dt = Math.min(app.ticker.deltaMS / 1000, 0.1);
    if (face.look && t > face.until) face.look = "";
    expression();
    const want = LOOKS[face.look] || {};
    const keys = new Set([...Object.keys(face.w), ...Object.keys(want)]);
    for (const id of keys) {
      if (id === "ParamEyeLOpen" || id === "ParamEyeROpen") continue;
      const target = want[id] || 0, cur = face.w[id] || 0;
      const v = cur + (target - cur) * Math.min(1, dt * 7);
      if (Math.abs(v) < 0.002 && !target) { delete face.w[id]; continue; }
      face.w[id] = v;
      core.setParameterValueById(id, v);
    }
    // Eyes scale the blink rather than replace it, so she still blinks while sleepy.
    const eye = want.ParamEyeLOpen ?? 1;
    face.eye = (face.eye ?? 1) + (eye - (face.eye ?? 1)) * Math.min(1, dt * 5);
    core.multiplyParameterValueById("ParamEyeLOpen", face.eye);
    core.multiplyParameterValueById("ParamEyeROpen", face.eye);
    // Lip sync: mouth open with her voice's loudness.
    const open = opt.lip_sync && face.speaking ? clamp(face.level * 4.5, 0.15, 1) * (0.75 + 0.25 * Math.sin(t * 23)) : 0;
    face.mouth += (open - face.mouth) * Math.min(1, dt * 18);
    core.setParameterValueById("ParamMouthOpenY", face.mouth);
    // The rig's looping effects (spinning star/heart eyes, running tears, the
    // pulsing anger mark) are 0-1 phases: cycle them, or they sit still.
    core.setParameterValueById("Anime_Eye", (t * 0.6) % 1);
    core.setParameterValueById("Anime_Cry", (t * 0.8) % 1);
    core.setParameterValueById("AnimeAngry", Math.sin(t * 7));
    core.setParameterValueById("AnimeAngry2", Math.sin(t * 7 + 1.3));
    groove(core, t);
    // Swing and breath (and a woozy wobble when dizzy).
    const wobble = face.look === "dizzy" ? Math.sin(t * 5) * 12 : 0;
    core.setParameterValueById("ParamAngleZ", me.tilt + wobble + Math.sin(t * 0.7) * 2);
    core.addParameterValueById("ParamBodyAngleX0", me.lean);
    core.addParameterValueById("ParamBodyAngleZ0", me.tilt * 0.6);
    // Slow: the rig hangs her tail off this parameter, so a quick breath whips it about.
    core.setParameterValueById("ParamBreath", (Math.sin(t * (face.look === "asleep" ? 0.6 : 1.0)) + 1) / 2);
    // Where she looks: the pointer when it's near her, else idly around.
    if (face.gaze.until && t < face.gaze.until) model.focus(face.gaze.x, face.gaze.y);
    else if (me.mode === "walk") model.focus(Math.sign(me.target - me.x) > 0 ? cw : 0, ch * 0.2);
    else if (Math.random() < dt * 0.25) model.focus(Math.random() * cw, Math.random() * ch * 0.6);
  }

  // ---------------------------------------------------------------- her commands
  // From her avatar tool (adapters/avatar.py): go somewhere, dance, stop, a face, sleep, wake.
  function command(m) {
    stir();
    if (m.cmd === "go") {
      let tx = me.x, ty = H, s = null;
      if (m.widget) {
        s = surfaces.find(x => x.name === m.widget);
        if (!s) return log("no surface for " + m.widget);
        tx = clamp(me.x, s.x0 + 20, s.x1 - 20); ty = s.y;
        if (tx === me.x && (me.x < s.x0 || me.x > s.x1)) tx = (s.x0 + s.x1) / 2;
      } else if (m.side) {
        tx = m.side === "left" ? W * 0.15 : m.side === "right" ? W * 0.85 : m.side === "center" ? W / 2 : me.x;
      } else if (typeof m.x === "number") tx = m.x;
      tx = clamp(tx, dispW * 0.8, W - dispW * 0.8);
      danceUntil = 0;
      if (opt.pinned) { me.x = tx; me.y = ty; pin(); return; }        // pinned: the pin moves
      const onFloor = !me.on || me.on === "floor";
      if (!s && onFloor && me.mode !== "fall") { me.target = tx; me.mode = "walk"; me.until = now() + 30; return; }
      hop(tx, ty);
    } else if (m.cmd === "dance") {
      danceUntil = now() + (Number(m.seconds) || 20);
      if (me.mode === "walk") stand();
    } else if (m.cmd === "stop") {
      danceUntil = 0;
      if (me.mode === "walk") stand();
    } else if (m.cmd === "feel") {
      feel(String(m.look || ""), Number(m.seconds) || 4);
    } else if (m.cmd === "sleep") {
      danceUntil = 0; face.look = "asleep"; face.until = 1e12;
    } else if (m.cmd === "wake") {
      if (face.look === "asleep") { face.look = ""; face.until = 0; feel("wide", 1); }
    }
  }

  // What her body is up to, for her (written by the host to pet/body.json).
  let toldAt = 0;
  function tell(t) {
    if (t - toldAt < 0.8 || !model) return;
    toldAt = t;
    const on = me.mode === "fall" || me.mode === "held" ? "air"
      : me.on && me.on !== "floor" ? me.on.name || "a widget" : me.mode === "pinned" && me.y < H - 2 ? "air" : "floor";
    post({ t: "state", x: Math.round(me.x), y: Math.round(me.y), w: W, h: H, mode: me.mode, on,
           look: face.look, dancing: !!dancing(), asleep: face.look === "asleep" });
  }

  // ---------------------------------------------------------------- dancing
  let danceUntil = 0;                      // her own "dance" command, music or not
  function dancing() {
    const asked = now() < danceUntil;
    return (asked || (opt.dance_to_music && music)) && model && (me.mode === "stand" || me.mode === "pinned")
      && face.look !== "asleep" && !held;
  }
  function onBeat(period, strength) {
    const t = now();
    beat.period = clamp(Number(period) || 0.53, 0.33, 0.75);
    beat.energy = Math.max(beat.energy * 0.7, clamp(Number(strength) || 0.5, 0.2, 1));
    beat.heard = t;
    if (t - beat.last < beat.period * 0.5) beat.last = t;     // our own count was just ahead: re-anchor
    else { beat.count++; beat.last = t; }
    if (music) stir();
  }
  function tick(t) {
    // Keep time between real beats (and without any, at the last tempo).
    while (t - beat.last > beat.period * 1.25 && t - beat.last < 10) { beat.last += beat.period; beat.count++; }
    if (t - beat.last >= 10) beat.last = t;
    beat.energy += ((t - beat.heard < 2 ? 0.6 : 0.35) - beat.energy) * 0.01;
  }
  // Four moves, eight beats each; the rig's physics swings her hair and tail along.
  function groove(core, t) {
    const on = dancing();
    if (!on) { dance.bob += (0 - dance.bob) * 0.2; return; }
    const phi = clamp((t - beat.last) / beat.period, 0, 1), b = beat.count + phi;
    const e = 0.55 + 0.45 * beat.energy, kick = Math.pow(1 - phi, 3);
    const move = MOVES[Math.floor(beat.count / 8) % MOVES.length];
    const sw = Math.sin(Math.PI * b), add = (id, v) => core.addParameterValueById(id, v);
    let bob = 0;
    if (move === "sway") {
      add("ParamBodyAngleX0", 8 * e * sw); add("ParamAngleZ", 8 * e * sw); add("ParamHipAngleX0", -4 * e * sw);
      add("ParamAngleX", 12 * Math.sin(Math.PI * b / 2)); bob = 5 * e * Math.abs(sw);
    } else if (move === "bounce") {
      add("ParamAngleY", -14 * e * kick); add("ParamBodyAngleY0", -6 * e * kick); add("ParamShoulderAngleY", 6 * kick);
      add("ParamAngleZ", 4 * sw); bob = 11 * e * kick;
    } else if (move === "groove") {
      add("ParamBodyAngleZ0", 6 * e * sw); add("ParamHipAngleZ0", 5 * e * Math.sin(Math.PI * b + 1.2));
      add("ParamAngleZ", 6 * sw); add("ParamAngleX", -10 * sw); bob = 4 * e * Math.abs(Math.sin(Math.PI * b + 1.2));
    } else {   // hop: a little jump every other beat
      const up = beat.count % 2 === 0 ? Math.sin(Math.PI * phi) : 0;
      add("ParamAngleY", 8 * up - 6 * kick); add("ParamBodyAngleX0", 3 * sw); bob = 26 * e * up;
    }
    dance.bob += (bob - dance.bob) * 0.5;
    // Happy while she dances, and starry-eyed now and then.
    if (!face.look || face.look === "smile") feel(beat.count % 32 >= 28 ? "stars" : "smile", 0.6);
  }

  // ---------------------------------------------------------------- the core
  function message(m) {
    if (!model) return;
    switch (m.t) {
      case "voice":
        face.speaking = !!m.speaking; face.level = Number(m.level) || 0;
        if (face.speaking) stir();
        break;
      case "speak": {
        stir();
        const look = EMOTION_LOOK[m.emotion];
        if (look) feel(look, (Number(m.seconds) || 1) + 0.6);
        else if (m.emotion === "neutral" && face.look !== "asleep") { face.look = ""; face.until = 0; }
        break;
      }
      case "ears": if (m.listening) { stir(); feel("wide", 1.0); face.gaze = { x: cw / 2, y: ch * 0.15, until: now() + 2 }; } break;
      case "action":
        if (!opt.react_to_work) break;
        stir();
        if (m.phase === "done") feel("smile", 1.6);
        else if (m.phase === "failed") feel("gloom", 2.2);
        break;
      case "chat": stir(); break;
      case "body": command(m); break;
      case "state":
        if (m.widget === "spotify" && m.data) {
          const was = music;
          music = m.data.status === "playing";
          if (music && !was) { stir(); beat.last = now(); }
        }
        break;
    }
  }

  // The page's own size is the window's: KWin sets it to the area above the panel.
  addEventListener("resize", () => screen(innerWidth, innerHeight));
  screen(innerWidth, innerHeight);

  return { load, unload, screen, settings, layout, message, feel, pinAt, beat: onBeat,
           _debug: { me, beat, setMusic: v => { music = v; } } };
})();
