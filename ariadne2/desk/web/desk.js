"use strict";
// The desk's page: widgets as acrylic slabs, braided wires to her core,
// packets, and the holographic "working on it" effect. It holds no logic:
// layer.py feeds it the core's messages and the layout, and it posts back
// what you did (typing, dragging) and where its widgets are, so the layer can
// let clicks through everywhere else.

const TITLES = { chat: "Chat", core: "Aries", spotify: "Spotify", steam: "Steam", discord: "Discord",
  browser: "Browser", dolphin: "Dolphin", claude: "Claude", system: "System", flows: "Flows" };
const GRID = 24, HALO = 16, DEPTH = 12, MIN = [192, 96];
const PACKET_MS = 650, MIN_WORK_MS = 900, GLINT_MS = 1200, GLINT_EVERY = 9000;
const STRANDS = [[255, 42, 61], [109, 140, 255], [255, 214, 218]];

const post = m => { try { window.webkit.messageHandlers.desk.postMessage(JSON.stringify(m)); } catch (e) { /* not in the layer */ } };
const lerp = (a, b, t) => a + (b - a) * t;
const dist = (a, b) => Math.hypot(b[0] - a[0], b[1] - a[1]);
const snap = v => Math.round(v / GRID) * GRID;

let rects = {}, area = [0, 0, innerWidth, innerHeight], raised = false, hidden = new Set();
const W = {};            // name -> { root, face, bd, tag, state }
let wires = {};
const packets = {};      // name -> { t0, dir, failed }
const work = {};         // name -> { phase, t0, end }
let frags = [], dirtyFront = false;

// A speckle texture: edges masked by it look eaten away.
(function noise() {
  const c = document.createElement("canvas"); c.width = c.height = 150;
  const x = c.getContext("2d");
  for (let i = 0; i < 150; i += 8) for (let j = 0; j < 150; j += 8)
    if (Math.random() < .5) { x.fillStyle = "#000"; const k = Math.random() < .3 ? 16 : 8; x.fillRect(i, j, k, k); }
  document.documentElement.style.setProperty("--noise", `url(${c.toDataURL()})`);
})();

/* ---------------- widgets ---------------- */
function build(name) {
  const root = document.createElement("div");
  root.className = `w ${name}`; root.dataset.w = name;
  let inner;
  if (name === "core") {
    inner = `<div class="face"><div class="core-top"><div class="wave">${"<i></i>".repeat(7)}</div>
      <div class="mark"><span class="r">ARIES</span><span class="cy">ARIES</span><span class="wt">ARIES</span></div>
      <div class="wave">${"<i></i>".repeat(7)}</div></div><div class="line"></div><div class="ports"></div>`;
  } else {
    inner = `<div class="face"><div class="hd"><span class="ttl">${TITLES[name]}</span><span class="tag"></span></div><div class="bd"></div>`;
  }
  root.innerHTML = inner + `<div class="sheen"></div><div class="rim"></div></div><div class="grip"></div>`;
  document.getElementById("widgets").appendChild(root);
  const w = { root, face: root.querySelector(".face"), bd: root.querySelector(".bd"), tag: root.querySelector(".tag") };
  if (name === "chat") {
    w.bd.innerHTML = `<div class="msgs"></div><input class="say" placeholder="talk to Aries" spellcheck="false">`;
    w.msgs = w.bd.querySelector(".msgs"); w.say = w.bd.querySelector(".say");
    w.say.addEventListener("keydown", e => {
      if (e.key !== "Enter") return;
      const text = w.say.value.trim();
      if (text) { post({ t: "send", msg: { t: "text", widget: "chat", text } }); w.say.value = ""; }
    });
    w.lines = {};
  }
  if (name === "core") { w.line = root.querySelector(".line"); w.ports = root.querySelector(".ports"); }
  W[name] = w;
}

function place(name) {
  const [x, y, w, h] = rects[name], r = W[name].root;
  Object.assign(r.style, { left: x + "px", top: y + "px", width: w + "px", height: h + "px" });
  r.style.boxShadow = extrusion(name);
}

// The slab's thickness: stacked 1px shadows toward the side facing away from
// her core, lit red near the face and darker further back.
function extrusion(name) {
  const c = rects.core, [x, , w] = rects[name];
  const off = (x + w / 2) - (c[0] + c[2] / 2);
  const dx = name === "core" || Math.abs(off) < c[2] / 2 ? 0 : Math.sign(off);
  const layers = [];
  for (let i = 1; i <= DEPTH; i++) {
    const k = i / DEPTH, r = Math.round(lerp(255, 90, k)), g = Math.round(lerp(110, 10, k)), b = Math.round(lerp(120, 22, k));
    layers.push(`${(dx * i * .7).toFixed(1)}px ${(i * .75).toFixed(1)}px 0 rgb(${r},${g},${b})`);
  }
  // Blurred glows and ground shadows look nicer but are re-rasterised on every
  // repaint without a GPU; crisp rings cost almost nothing.
  layers.push("0 0 0 1px rgba(255,90,105,.45)", "0 0 0 3px rgba(255,42,61,.12)");
  return layers.join(",");
}

function setState(name, data) {
  const w = W[name];
  if (!w || name === "core" || name === "chat") return;
  if (name === "system" && "cpu" in data) {
    if (!w.meters) {
      w.bd.innerHTML = `<div class="meters"><div class="meter"><div class="v cpu"></div>CPU<div class="bar"><b class="cpub"></b></div></div>
        <div class="meter"><div class="v mem"></div>MEM <span class="memgb"></span><div class="bar"><b class="memb"></b></div></div></div>`;
      w.meters = true;
    }
    w.bd.querySelector(".cpu").textContent = `${Math.round(data.cpu)}%`;
    w.bd.querySelector(".cpub").style.width = `${data.cpu}%`;
    w.bd.querySelector(".mem").textContent = `${Math.round(data.mem)}%`;
    w.bd.querySelector(".memb").style.width = `${data.mem}%`;
    w.bd.querySelector(".memgb").textContent = `${(data.mem_used_gb || 0).toFixed(1)}/${(data.mem_total_gb || 0).toFixed(0)} GB`;
    return;
  }
  w.bd.innerHTML = "";
  for (const [k, v] of Object.entries(data)) {
    const row = document.createElement("div");
    if (k === "status") { row.className = "dim"; row.textContent = v; }
    else { row.className = "kv"; row.innerHTML = `<span></span><span></span>`; row.children[0].textContent = k; row.children[1].textContent = v; }
    w.bd.appendChild(row);
  }
}

function chat(msg) {
  const w = W.chat; let el = w.lines[msg.id];
  if (!el) { el = document.createElement("div"); el.className = `msg ${msg.role === "you" ? "you" : ""}`; w.lines[msg.id] = el; w.msgs.appendChild(el); }
  el.textContent += msg.delta;
  w.msgs.scrollTop = w.msgs.scrollHeight;
}

/* ---------------- actions: packet out, work, packet back ---------------- */
function action(msg) {
  const name = msg.widget, w = W[name];
  if (!w || name === "core") return;
  const now = performance.now();
  if (msg.phase === "started") {
    packets[name] = { t0: now, dir: "out" }; kick();
    Sounds.play("send"); Sounds.play(name);
    work[name] = { phase: "out", t0: now }; frontBox();
    W.core.root.classList.add("acting");
    W.core.ports.querySelector(`[data-p="${name}"]`)?.classList.add("live");
    if (w.tag) { w.tagWas = w.tagWas ?? w.tag.textContent; w.tag.textContent = `▸ ${msg.control || msg.verb}`; w.tag.className = "tag on"; }
  } else if (msg.phase === "done" || msg.phase === "failed") {
    const s = work[name] || (work[name] = { phase: "work", t0: now - MIN_WORK_MS });
    s.end = { failed: msg.phase === "failed", note: msg.note }; kick();
  }
}

// Runs every frame: moves each widget through out -> work -> back, holding the
// work phase long enough to be seen even when the app answered instantly.
function stepWork(now) {
  for (const [name, s] of Object.entries(work)) {
    const w = W[name];
    if (s.phase === "out" && now - s.t0 > PACKET_MS) { s.phase = "work"; s.t0 = now; w.root.classList.add("working"); }
    else if (s.phase === "work") {
      if (Math.random() < .6) burst(name, 2, false);
      if (s.end && now - s.t0 > MIN_WORK_MS) {
        w.root.classList.remove("working");
        packets[name] = { t0: now, dir: "back", failed: s.end.failed };
        Sounds.play(s.end.failed ? "fail" : "done");
        if (s.end.failed) {
          w.root.classList.add("failed"); burst(name, 60, true);
          if (w.tag) { w.tag.textContent = `✕ ${s.end.note || "failed"}`; w.tag.className = "tag bad"; }
        } else { w.root.classList.add("mending"); mend(name); restoreTag(w); }
        s.phase = "back"; s.t0 = now;
      }
    } else if (s.phase === "back" && now - s.t0 > PACKET_MS) {
      delete work[name];
      W.core.ports.querySelector(`[data-p="${name}"]`)?.classList.remove("live");
      setTimeout(() => { w.root.classList.remove("mending", "failed"); if (s.end.failed) setTimeout(() => restoreTag(w), 2500); }, s.end.failed ? 1300 : 500);
      if (!Object.keys(work).length) W.core.root.classList.remove("acting");
    }
  }
}
function restoreTag(w) { if (w.tag) { w.tag.textContent = w.tagWas || ""; w.tag.className = "tag"; w.tagWas = undefined; } }

/* ---------------- shards ---------------- */
function perimeter(name) {
  const [x, y, w, h] = rects[name], u = Math.random() * 2 * (w + h);
  let p;
  if (u < w) p = [x + u, y]; else if (u < w + h) p = [x + w, y + u - w];
  else if (u < 2 * w + h) p = [x + w - (u - w - h), y + h]; else p = [x, y + h - (u - 2 * w - h)];
  const cx = x + w / 2, cy = y + h / 2, l = Math.hypot(p[0] - cx, p[1] - cy) || 1;
  return { p, n: [(p[0] - cx) / l, (p[1] - cy) / l] };
}
const HUES = [350, 228, 200];
const hue = () => HUES[Math.floor(Math.random() * HUES.length)] + (Math.random() - .5) * 30;
function burst(name, count, failed) {
  for (let k = 0; k < count; k++) {
    const { p, n } = perimeter(name), sp = 20 + Math.random() * (failed ? 140 : 70);
    frags.push({ x: p[0], y: p[1], vx: n[0] * sp + (Math.random() - .5) * 40, vy: n[1] * sp - 20, rot: Math.random() * 6, vr: (Math.random() - .5) * 9,
      size: 4 + Math.random() * (failed ? 10 : 8) * (Math.random() < .25 ? 1.8 : 1), life: 1, max: .9 + Math.random() * 1.1, hue: hue(), failed, g: failed ? 300 : 110 });
  }
}
function mend(name) {
  for (let k = 0; k < 110; k++) {
    const { p, n } = perimeter(name), d = 30 + Math.random() * 50;
    frags.push({ x: p[0] + n[0] * d, y: p[1] + n[1] * d, tx: p[0], ty: p[1], mend: true, size: 3 + Math.random() * 5, rot: Math.random() * 6, life: 1, max: .35 + Math.random() * .3, hue: hue() });
  }
}

/* ---------------- wires: braided cables from her core ---------------- */
function densify(poly, step = 4) {
  const out = [poly[0]];
  for (let i = 1; i < poly.length; i++) {
    const a = poly[i - 1], b = poly[i], n = Math.max(1, Math.ceil(dist(a, b) / step));
    for (let k = 1; k <= n; k++) out.push([lerp(a[0], b[0], k / n), lerp(a[1], b[1], k / n)]);
  }
  return out;
}
function lengths(p) { const L = [0]; for (let i = 1; i < p.length; i++) L.push(L[i - 1] + dist(p[i - 1], p[i])); return L; }
function at(p, L, d) {
  d = Math.max(0, Math.min(L[L.length - 1], d));
  let i = 1; while (i < L.length - 1 && L[i] < d) i++;
  const t = (d - L[i - 1]) / ((L[i] - L[i - 1]) || 1);
  return [lerp(p[i - 1][0], p[i][0], t), lerp(p[i - 1][1], p[i][1], t)];
}

function routeWires() {
  const [cx, cy, cw, ch] = rects.core, ccx = cx + cw / 2, ccy = cy + ch / 2;
  const names = Object.keys(rects).filter(n => n !== "core" && W[n]);
  // Where each cable enters its widget: the edge facing the core.
  const entry = n => {
    const [x, y, w, h] = rects[n];
    if (x >= cx + cw) return { p: [x, y + h / 2], d: [1, 0] };
    if (x + w <= cx) return { p: [x + w, y + h / 2], d: [-1, 0] };
    return y > cy ? { p: [x + w / 2, y], d: [0, 1] } : { p: [x + w / 2, y + h], d: [0, -1] };
  };
  const ang = n => { const e = entry(n).p; let a = Math.atan2(e[1] - ccy, e[0] - ccx); if (a < -Math.PI / 2) a += 2 * Math.PI; return a; };
  names.sort((a, b) => ang(b) - ang(a));   // left side, round the bottom, to the right side
  // One port button per widget on the core, in the same left-to-right order
  // the cables fan out, so no two cables cross; each cable plugs into its port.
  const ports = buildPorts(names);
  const old = wires; wires = {};
  for (const n of Object.keys(old)) if (!names.includes(n) || hidden.has(n)) old[n].cv.remove();
  names.forEach((n, i) => {
    if (hidden.has(n)) return;
    const A = { p: ports[n], d: [0, 1] }, E = entry(n);
    const a = A.p, e = E.p, k = Math.min(260, dist(a, e) * .38), sag = 30 + (i % 3) * 18;
    const c1 = [a[0] + A.d[0] * k, a[1] + A.d[1] * k + sag], c2 = [e[0] - E.d[0] * k, e[1] - E.d[1] * k + sag];
    const raw = [];
    for (let q = 0; q <= 48; q++) { const u = q / 48, v = 1 - u;
      raw.push([v ** 3 * a[0] + 3 * v * v * u * c1[0] + 3 * v * u * u * c2[0] + u ** 3 * e[0],
                v ** 3 * a[1] + 3 * v * v * u * c1[1] + 3 * v * u * u * c2[1] + u ** 3 * e[1]]); }
    const pts = densify(raw), L = lengths(pts);
    const nrm = pts.map((p, j) => {
      const q0 = pts[Math.max(0, j - 1)], q1 = pts[Math.min(pts.length - 1, j + 1)], dx = q1[0] - q0[0], dy = q1[1] - q0[1], l = Math.hypot(dx, dy) || 1;
      return [-dy / l, dx / l];
    });
    // Each wire gets its own canvas sized to the cable: an action then
    // repaints one cable, not the whole screen.
    const m2 = 26, xs = pts.map(q => q[0]), ys = pts.map(q => q[1]);
    const bx = Math.floor(Math.min(...xs) - m2), by = Math.floor(Math.min(...ys) - m2);
    const bw = Math.ceil(Math.max(...xs) + m2) - bx, bh = Math.ceil(Math.max(...ys) + m2) - by;
    const reuse = old[n] && old[n].cv.isConnected, cv = reuse ? old[n].cv : document.createElement("canvas");
    if (!reuse) document.getElementById("wires").appendChild(cv);
    Object.assign(cv.style, { left: bx + "px", top: by + "px", width: bw + "px", height: bh + "px" });
    cv.width = bw; cv.height = bh;
    wires[n] = { pts, L, nrm, spin: old[n] ? old[n].spin : Math.random() * 6, cv, bx, by };
  });
}

const SHORT = { chat: "Chat", spotify: "Spotify", steam: "Steam", discord: "Discord", browser: "Browser",
  dolphin: "Files", claude: "Claude", system: "System", flows: "Flows" };
function buildPorts(names) {
  const box = W.core.ports, key = names.join();
  if (box.dataset.key !== key) {
    box.dataset.key = key; box.innerHTML = "";
    for (const n of names) {
      const b = document.createElement("button");
      b.className = "port"; b.dataset.p = n; b.title = `Show or hide ${TITLES[n]}`;
      b.innerHTML = `<span>${SHORT[n] || n}</span><i></i>`;
      b.addEventListener("click", () => toggle(n));
      box.appendChild(b);
    }
  }
  const out = {};
  for (const b of box.children) {
    b.classList.toggle("off", hidden.has(b.dataset.p));
    const r = b.getBoundingClientRect();
    out[b.dataset.p] = [r.left + r.width / 2, r.bottom];
  }
  return out;
}
function toggle(n) {
  hidden.has(n) ? hidden.delete(n) : hidden.add(n);
  W[n].root.style.display = hidden.has(n) ? "none" : "";
  relayout(true);
  post({ t: "hidden", names: [...hidden] });
}

function line(ctx, pts, width, col) {
  ctx.beginPath(); ctx.moveTo(pts[0][0], pts[0][1]);
  for (const p of pts) ctx.lineTo(p[0], p[1]);
  ctx.lineWidth = width; ctx.strokeStyle = col; ctx.stroke();
}

// Three thin black strands wound round the cable: offset sin(phase), depth
// cos(phase). One colour; the strands behind are just fainter.
function braid(ctx, w, active, dt, sheen) {
  const R = 2.6, TWIST = .11, { pts, L, nrm } = w;
  if (active) w.spin += 7 * dt;   // still at rest: an idle redraw costs CPU
  ctx.lineCap = "round";
  for (const front of [false, true]) for (let k = 0; k < 3; k++) {
    ctx.beginPath(); let pen = false;
    for (let i = 0; i < pts.length; i++) {
      const ph = L[i] * TWIST - w.spin + k * 2.094, off = Math.sin(ph) * R;
      if ((Math.cos(ph) >= 0) === front) {
        const x = pts[i][0] + nrm[i][0] * off, y = pts[i][1] + nrm[i][1] * off;
        pen ? ctx.lineTo(x, y) : ctx.moveTo(x, y); pen = true;
      } else pen = false;
    }
    ctx.lineWidth = front ? 1.6 : 1.1;
    ctx.strokeStyle = front ? "rgba(0,0,0,.95)" : "rgba(0,0,0,.5)";
    ctx.stroke();
    if (front && sheen) sheenPass(ctx, w, k, sheen);
  }
  ctx.lineCap = "butt";
  for (const p of [pts[0], pts[pts.length - 1]]) { ctx.fillStyle = "#000"; ctx.fillRect(p[0] - 4, p[1] - 4, 8, 8); }
}

// The holographic sheen: a band of shifting colour slides along the front
// strands, fading out either side of its centre (s0, a distance along the wire).
function sheenPass(ctx, w, k, { s0, hue, strength }) {
  const R = 2.6, TWIST = .11, { pts, L, nrm } = w, BAND = 110;
  ctx.save(); ctx.globalCompositeOperation = "lighter"; ctx.lineWidth = 1.9; ctx.lineCap = "round";
  let prev = null;
  for (let i = 0; i < pts.length; i++) {
    const ph = L[i] * TWIST - w.spin + k * 2.094, d = Math.abs(L[i] - s0);
    const x = pts[i][0] + nrm[i][0] * Math.sin(ph) * R, y = pts[i][1] + nrm[i][1] * Math.sin(ph) * R;
    if (prev && d < BAND && Math.cos(ph) >= 0) {
      const a = strength * (1 - d / BAND) ** 1.5;
      ctx.strokeStyle = `hsla(${(hue + L[i] * .9 + k * 40) % 360},100%,68%,${a})`;
      ctx.beginPath(); ctx.moveTo(prev[0], prev[1]); ctx.lineTo(x, y); ctx.stroke();
    }
    prev = [x, y];
  }
  ctx.restore();
}

function drawPacket(ctx, w, pk, now) {
  const u = Math.min(1, (now - pk.t0) / PACKET_MS), total = w.L[w.L.length - 1], back = pk.dir === "back";
  const head = total * (back ? 1 - u : u), len = 140;
  const seg = [];
  for (let d = back ? head : head - len; d <= (back ? head + len : head); d += 3) if (d >= 0 && d <= total) seg.push(at(w.pts, w.L, d));
  const col = pk.failed ? (Math.floor(now / 55) % 2 ? "#ff1030" : "rgba(255,16,48,.25)") : back ? "#ffe9ec" : "#ff4d5e";
  ctx.save(); ctx.globalCompositeOperation = "lighter";
  if (seg.length > 1) {
    line(ctx, seg, 8, pk.failed ? "rgba(255,16,48,.22)" : "rgba(255,60,80,.22)");
    for (let i = 1; i < seg.length; i++) {
      const k = back ? 1 - i / seg.length : i / seg.length;
      ctx.globalAlpha = .15 + .85 * k; line(ctx, [seg[i - 1], seg[i]], 1 + 1.6 * k, col);
    }
  }
  ctx.globalAlpha = 1;
  const hp = at(w.pts, w.L, head);
  ctx.beginPath(); ctx.arc(hp[0], hp[1], 3, 0, 7); ctx.fillStyle = "#fff"; ctx.fill();
  ctx.restore();
  return u < 1;
}

/* ---------------- drawing loop ---------------- */
const front = document.getElementById("front");
function sizeCanvases() {}
// The shard canvas covers only the widgets being worked on, plus room to fly.
let fb = [0, 0, 1, 1];
function frontBox() {
  const names = Object.keys(work);
  if (!names.length) return;
  const M = 220, xs = [], ys = [];
  for (const n of names) { const [x, y, w, h] = rects[n]; xs.push(x - M, x + w + M); ys.push(y - M, y + h + M); }
  const x0 = Math.max(0, Math.min(...xs)), y0 = Math.max(0, Math.min(...ys));
  const nb = [x0, y0, Math.min(innerWidth, Math.max(...xs)) - x0, Math.min(innerHeight, Math.max(...ys)) - y0];
  if (nb.join() === fb.join()) return;
  fb = nb; frags = [];
  Object.assign(front.style, { left: fb[0] + "px", top: fb[1] + "px", width: fb[2] + "px", height: fb[3] + "px" });
  front.width = fb[2]; front.height = fb[3];
}
let last = 0, lastDraw = 0, needsDraw = true;
// The loop only runs while something moves; kick() wakes it.
let looping = false;
function kick() { if (!looping) { looping = true; requestAnimationFrame(frame); } }
function frame(now) {
  const glinting = Object.values(wires).some(w => w.glint && now < w.glint + GLINT_MS + 50);
  const busy = Object.keys(packets).length || Object.keys(work).length || frags.length || dirtyFront || glinting;
  if (busy || needsDraw) requestAnimationFrame(frame); else { looping = false; return; }
  // The desk renders without a GPU, so every full-screen frame costs CPU:
  // nothing is redrawn at rest, and actions animate at 30 fps.
  if (!busy && !needsDraw) { last = now; return; }
  if (busy && now - lastDraw < 33) return;
  lastDraw = now;
  const dt = Math.min(.1, (now - (last || now)) / 1000); last = now;
  const full = needsDraw; needsDraw = false;
  stepWork(now);
  for (const [n, w] of Object.entries(wires)) {
    const active = !!(packets[n] || work[n]), total = w.L[w.L.length - 1];
    let sheen = null;
    if (active) sheen = { s0: ((now / 850) % 1) * (total + 240) - 120, hue: now / 8 % 360, strength: 1 };
    else if (w.glint && now < w.glint + GLINT_MS) sheen = { s0: (now - w.glint) / GLINT_MS * (total + 240) - 120, hue: now / 8 % 360, strength: .7 };
    const glinting = !!sheen && !active;
    if (!full && !active && !w.wasActive && !glinting && !w.wasGlint) continue;   // untouched cables stay as drawn
    w.wasActive = active; w.wasGlint = glinting;
    const ctx = w.cv.getContext("2d");
    ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.clearRect(0, 0, w.cv.width, w.cv.height);
    ctx.setTransform(1, 0, 0, 1, -w.bx, -w.by);
    braid(ctx, w, active, dt, sheen);
    if (packets[n] && !drawPacket(ctx, w, packets[n], now)) delete packets[n];
  }
  drawFrags(front.getContext("2d"), dt, now);
}
function drawFrags(ctx, dt, now) {
  if (!frags.length && !dirtyFront) return;
  ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.clearRect(0, 0, front.width, front.height);
  ctx.setTransform(1, 0, 0, 1, -fb[0], -fb[1]);
  dirtyFront = frags.length > 0;
  ctx.save(); ctx.globalCompositeOperation = "lighter";
  frags = frags.filter(f => (f.life -= dt / f.max) > 0);
  const t = now / 1000;
  for (const f of frags) {
    if (f.mend) { const k = 1 - f.life; f.x = lerp(f.x, f.tx, Math.min(1, k * .5 + .12)); f.y = lerp(f.y, f.ty, Math.min(1, k * .5 + .12)); }
    else { f.vy += f.g * dt; f.x += f.vx * dt; f.y += f.vy * dt; f.rot += f.vr * dt; }
    const a = f.mend ? Math.min(1, f.life * 2) : f.life;
    ctx.fillStyle = f.failed ? `rgba(255,${30 + 60 * a | 0},50,${a})` : `hsla(${(f.hue + Math.sin(t * 6 + f.rot) * 25 + 360) % 360},100%,70%,${a})`;
    ctx.save(); ctx.translate(f.x, f.y); ctx.rotate(f.rot);
    const s = f.size; ctx.beginPath(); ctx.moveTo(-s, -s * .4); ctx.lineTo(s * .7, -s * .6); ctx.lineTo(s * .3, s * .7); ctx.closePath(); ctx.fill();
    ctx.restore();
  }
  ctx.restore();
}

/* ---------------- moving and resizing ---------------- */
function clampRect([x, y, w, h]) {
  const [ax, ay, aw, ah] = area;
  w = Math.max(MIN[0], Math.min(w, aw)); h = Math.max(MIN[1], Math.min(h, ah));
  x = Math.max(ax, Math.min(x, ax + aw - w)); y = Math.max(ay, Math.min(y, ay + ah - h));
  return [x, y, w, h];
}
let drag = null;
document.addEventListener("pointerdown", e => {
  const root = e.target.closest(".w");
  if (!root) { if (raised) post({ t: "drop" }); return; }
  const name = root.dataset.w, isGrip = e.target.classList.contains("grip");
  if (!isGrip && !e.target.closest(".hd") && !(name === "core" && !e.target.closest("input"))) return;
  drag = { name, mode: isGrip ? "size" : "move", x0: e.clientX, y0: e.clientY, r0: rects[name].slice() };
  e.preventDefault();
});
addEventListener("pointermove", e => {
  if (!drag) return;
  const dx = e.clientX - drag.x0, dy = e.clientY - drag.y0, [x, y, w, h] = drag.r0;
  rects[drag.name] = clampRect(drag.mode === "move" ? [x + dx, y + dy, w, h] : [x, y, w + dx, h + dy]);
  relayout(false);
});
addEventListener("pointerup", () => {
  if (!drag) return;
  const [x, y, w, h] = rects[drag.name];
  rects[drag.name] = clampRect(drag.mode === "move" ? [snap(x), snap(y), w, h] : [x, y, snap(x + w) - x, snap(y + h) - y]);
  drag = null;
  relayout(true);
  post({ t: "layout", widgets: rects });
});
addEventListener("keydown", e => { if (e.key === "Escape" && raised) post({ t: "drop" }); });

function relayout(report) {
  for (const n of Object.keys(rects)) place(n);
  routeWires(); needsDraw = true; kick();
  if (report) reportRects();
}
// Where clicks should land on the layer: each slab plus its thickness and glow.
function reportRects() {
  const m = HALO + DEPTH;
  post({ t: "rects", rects: Object.entries(rects).filter(([n]) => !hidden.has(n)).map(([, [x, y, w, h]]) => [x - m, y - m, w + 2 * m, h + 2 * m]) });
}

/* ---------------- what layer.py calls ---------------- */
window.desk = {
  init(layout, ar, hid, sounds) {
    area = ar; rects = layout; hidden = new Set(hid || []); Sounds.configure(sounds);
    for (const n of Object.keys(TITLES)) if (rects[n] && !W[n]) build(n);
    for (const n of hidden) if (W[n]) W[n].root.style.display = "none";
    sizeCanvases(); relayout(true);
  },
  layout(layout, ar) { area = ar; rects = layout; relayout(true); },
  message(msg) {
    switch (msg.t) {
      case "state": setState(msg.widget, msg.data); break;
      case "line": if (W.core) W.core.line.textContent = msg.text; break;
      case "chat": if (W.chat) chat(msg); break;
      case "action": action(msg); break;
    }
  },
  setRaised(up) {
    if (up !== raised) Sounds.play(up ? "raise" : "drop");
    raised = up; document.body.classList.toggle("raised", up);
    if (up && W.chat) W.chat.say.focus();
  },
  sound(kind) { Sounds.play(kind); },
  configureSounds(c) { Sounds.configure(c); },
  setStatus(s) { if (W.core) W.core.line.textContent = s === "connected" ? "" : "reconnecting…"; },
};
addEventListener("resize", () => { sizeCanvases(); needsDraw = true; kick(); });
// At rest a glint runs down one wire every few seconds; only that small
// canvas redraws while it does.
setInterval(() => {
  const ws = Object.values(wires); if (!ws.length || Object.keys(work).length) return;
  ws[Math.floor(Math.random() * ws.length)].glint = performance.now(); kick();
}, GLINT_EVERY / 2);
kick();
post({ t: "ready" });
