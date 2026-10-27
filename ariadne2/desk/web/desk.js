"use strict";
// The desk's page: widgets as acrylic slabs, braided wires to her core,
// packets, and the holographic "working on it" effect. It holds no logic:
// layer.py feeds it the core's messages and the layout, and it posts back
// what you did (typing, dragging) and where its widgets are, so the layer can
// let clicks through everywhere else.

const TITLES = { chat: "Chat", core: "Aries", spotify: "Spotify", steam: "Steam", discord: "Discord",
  browser: "Browser", dolphin: "Dolphin", claude: "Claude", system: "System", flows: "Flows" };
const GRID = 24, HALO = 16, DEPTH = 12, MIN = [192, 96];
const PACKET_MS = 650, MIN_WORK_MS = 900;
const STRANDS = [[255, 42, 61], [109, 140, 255], [255, 214, 218]];

const post = m => { try { window.webkit.messageHandlers.desk.postMessage(JSON.stringify(m)); } catch (e) { /* not in the layer */ } };
const lerp = (a, b, t) => a + (b - a) * t;
const dist = (a, b) => Math.hypot(b[0] - a[0], b[1] - a[1]);
const snap = v => Math.round(v / GRID) * GRID;

let rects = {}, area = [0, 0, innerWidth, innerHeight], raised = false;
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
    inner = `<div class="face"><div class="core-row"><div class="mark"><span class="r">ARIES</span><span class="cy">ARIES</span><span class="wt">ARIES</span></div>
      <div class="line"></div><div class="wave">${"<i></i>".repeat(9)}</div></div>`;
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
  if (name === "core") w.line = root.querySelector(".line");
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
    work[name] = { phase: "out", t0: now }; frontBox();
    W.core.root.classList.add("acting");
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
        if (s.end.failed) {
          w.root.classList.add("failed"); burst(name, 60, true);
          if (w.tag) { w.tag.textContent = `✕ ${s.end.note || "failed"}`; w.tag.className = "tag bad"; }
        } else { w.root.classList.add("mending"); mend(name); restoreTag(w); }
        s.phase = "back"; s.t0 = now;
      }
    } else if (s.phase === "back" && now - s.t0 > PACKET_MS) {
      delete work[name];
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
  const [cx, cy, cw, ch] = rects.core, sides = { left: [], right: [], below: [] };
  for (const n of Object.keys(rects)) {
    if (n === "core") continue;
    const [x, y, w, h] = rects[n];
    if (x >= cx + cw) sides.right.push(n); else if (x + w <= cx) sides.left.push(n); else sides.below.push(n);
  }
  const wires_old = wires; wires = {};
  const mid = n => rects[n][1] + rects[n][3] / 2;
  for (const [side, names] of Object.entries(sides)) {
    names.sort((a, b) => side === "below" ? rects[a][0] - rects[b][0] : mid(a) - mid(b));
    names.forEach((n, i) => {
      const [x, y, w, h] = rects[n], f = (i + 1) / (names.length + 1);
      let a, e;
      if (side === "right") { a = [cx + cw, cy + ch * f]; e = [x, y + h / 2]; }
      else if (side === "left") { a = [cx, cy + ch * f]; e = [x + w, y + h / 2]; }
      else { a = [cx + cw * f, cy + ch]; e = [x + w / 2, y]; }
      // Mostly-sideways cables sag under gravity; mostly-vertical ones bow
      // sideways instead, so they never dip through the widget they enter.
      const m = Math.abs(e[0] - a[0]) > Math.abs(e[1] - a[1])
        ? [(a[0] + e[0]) / 2, Math.max(a[1], e[1]) + Math.min(170, 40 + dist(a, e) * .14)]
        : [(a[0] + e[0]) / 2 + (side === "below" ? (f - .5) * 120 : 0), (a[1] + e[1]) / 2];
      const raw = [];
      for (let k = 0; k <= 40; k++) { const u = k / 40; raw.push([(1 - u) ** 2 * a[0] + 2 * u * (1 - u) * m[0] + u * u * e[0], (1 - u) ** 2 * a[1] + 2 * u * (1 - u) * m[1] + u * u * e[1]]); }
      const pts = densify(raw), L = lengths(pts);
      const nrm = pts.map((p, j) => {
        const q0 = pts[Math.max(0, j - 1)], q1 = pts[Math.min(pts.length - 1, j + 1)], dx = q1[0] - q0[0], dy = q1[1] - q0[1], l = Math.hypot(dx, dy) || 1;
        return [-dy / l, dx / l];
      });
      // Each wire gets its own canvas sized to the cable: an action then
      // repaints one cable, not the whole screen.
      const m2 = 30, xs = pts.map(q => q[0]), ys = pts.map(q => q[1]);
      const bx = Math.floor(Math.min(...xs) - m2), by = Math.floor(Math.min(...ys) - m2);
      const bw = Math.ceil(Math.max(...xs) + m2 + 10) - bx, bh = Math.ceil(Math.max(...ys) + m2 + 20) - by;
      const old = wires_old[n], cv = old ? old.cv : document.createElement("canvas");
      if (!old) document.getElementById("wires").appendChild(cv);
      Object.assign(cv.style, { left: bx + "px", top: by + "px", width: bw + "px", height: bh + "px" });
      cv.width = bw; cv.height = bh;
      wires[n] = { pts, L, nrm, spin: old ? old.spin : Math.random() * 6, cv, bx, by };
    });
  }
}

function line(ctx, pts, width, col) {
  ctx.beginPath(); ctx.moveTo(pts[0][0], pts[0][1]);
  for (const p of pts) ctx.lineTo(p[0], p[1]);
  ctx.lineWidth = width; ctx.strokeStyle = col; ctx.stroke();
}

// Three strands wound round the cable: offset sin(phase), depth cos(phase).
// Back halves are drawn first and dim, front halves last and bright.
function braid(ctx, w, active, dt) {
  const R = 5, TWIST = .085, { pts, L, nrm } = w;
  if (active) w.spin += 7 * dt;   // still at rest: an idle redraw costs CPU
  ctx.lineCap = "round";
  line(ctx, pts.map(p => [p[0] + 6, p[1] + 16]), 9, "rgba(0,0,0,.22)");
  line(ctx, pts, 12, "rgba(8,4,12,.55)");
  for (const front of [false, true]) STRANDS.forEach((c, k) => {
    ctx.beginPath(); let pen = false;
    for (let i = 0; i < pts.length; i++) {
      const ph = L[i] * TWIST - w.spin + k * 2.094, off = Math.sin(ph) * R;
      if ((Math.cos(ph) >= 0) === front) {
        const x = pts[i][0] + nrm[i][0] * off, y = pts[i][1] + nrm[i][1] * off;
        pen ? ctx.lineTo(x, y) : ctx.moveTo(x, y); pen = true;
      } else pen = false;
    }
    // Glow as a wide faint stroke under the strand: shadowBlur is far too
    // slow on a full-screen canvas without a GPU.
    if (front) { ctx.lineWidth = active ? 8 : 6; ctx.strokeStyle = `rgba(${c},${active ? .28 : .16})`; ctx.stroke(); }
    ctx.lineWidth = front ? 2.6 : 1.6;
    ctx.strokeStyle = `rgba(${c},${front ? (active ? 1 : .92) : .32})`;
    ctx.stroke();
  });
  ctx.lineCap = "butt";
  for (const p of [pts[0], pts[pts.length - 1]]) { ctx.fillStyle = "#2a2023"; ctx.fillRect(p[0] - 7, p[1] - 6, 14, 12); ctx.fillStyle = "#ff2a3d"; ctx.fillRect(p[0] - 2, p[1] - 2, 4, 4); }
}

function drawPacket(ctx, w, pk, now) {
  const u = Math.min(1, (now - pk.t0) / PACKET_MS), total = w.L[w.L.length - 1], back = pk.dir === "back";
  const head = total * (back ? 1 - u : u), len = 140;
  const seg = [];
  for (let d = back ? head : head - len; d <= (back ? head + len : head); d += 3) if (d >= 0 && d <= total) seg.push(at(w.pts, w.L, d));
  const col = pk.failed ? (Math.floor(now / 55) % 2 ? "#ff1030" : "rgba(255,16,48,.25)") : back ? "#ffe9ec" : "#ff4d5e";
  ctx.save(); ctx.globalCompositeOperation = "lighter";
  if (seg.length > 1) {
    line(ctx, seg, 18, pk.failed ? "rgba(255,16,48,.2)" : "rgba(255,60,80,.2)");
    for (let i = 1; i < seg.length; i++) {
      const k = back ? 1 - i / seg.length : i / seg.length;
      ctx.globalAlpha = .15 + .85 * k; line(ctx, [seg[i - 1], seg[i]], 1 + 3.5 * k, col);
    }
  }
  ctx.globalAlpha = 1;
  const hp = at(w.pts, w.L, head);
  ctx.beginPath(); ctx.arc(hp[0], hp[1], 5, 0, 7); ctx.fillStyle = "#fff"; ctx.shadowColor = col; ctx.shadowBlur = 18; ctx.fill();
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
  const busy = Object.keys(packets).length || Object.keys(work).length || frags.length || dirtyFront;
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
    const active = !!(packets[n] || work[n]);
    if (!full && !active && !w.wasActive) continue;   // untouched cables stay as drawn
    w.wasActive = active;
    const ctx = w.cv.getContext("2d");
    ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.clearRect(0, 0, w.cv.width, w.cv.height);
    ctx.setTransform(1, 0, 0, 1, -w.bx, -w.by);
    braid(ctx, w, active, dt);
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
  post({ t: "rects", rects: Object.values(rects).map(([x, y, w, h]) => [x - m, y - m, w + 2 * m, h + 2 * m]) });
}

/* ---------------- what layer.py calls ---------------- */
window.desk = {
  init(layout, ar) {
    area = ar; rects = layout;
    for (const n of Object.keys(TITLES)) if (rects[n] && !W[n]) build(n);
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
    raised = up; document.body.classList.toggle("raised", up);
    if (up && W.chat) W.chat.say.focus();
  },
  setStatus(s) { if (W.core) W.core.line.textContent = s === "connected" ? "" : "reconnecting…"; },
};
addEventListener("resize", () => { sizeCanvases(); needsDraw = true; kick(); });
kick();
post({ t: "ready" });
