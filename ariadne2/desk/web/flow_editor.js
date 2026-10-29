"use strict";
// The flow editor: a node canvas in the spirit of Unreal's Blueprints and
// ComfyUI. Starts, checks and actions are cards with pins; drag from an
// output to an input to wire them. Right-click (or Space) opens a search of
// every node type; dropping a wire on empty space opens it filtered to nodes
// that fit. When she builds a flow, it appears here node by node; when a
// flow runs, each node lights up as the run reaches it.
//
// Talks to the core with flow_catalog / flow_open / flow_save / flow_test;
// the core checks every graph (the page holds no flow logic).

const FlowEditor = (() => {
  const CAT_COLOR = { start: "#ff2a3d", check: "#ffb347", action: "#6d8cff", flow: "#b18cff", data: "#8a8f9a" };
  const TYPE_COLOR = { text: "#e8dccb", number: "#6d8cff", "yes/no": "#ff4d8a", time: "#ffb347", duration: "#ffd36b",
    path: "#3cffd0", list: "#b18cff" };
  const colorOf = t => TYPE_COLOR[t] || "#9aa4ad";
  let root, world, svg, palette, status, nameBox;
  let catalog = {}, graph = null, open = false, view = { x: 80, y: 80, k: 1 };
  let sel = null, wiring = null, panning = null, moving = null;
  let send = () => {};

  // ----- setup -----
  function init(sendFn) {
    send = sendFn;
    root = document.createElement("div");
    root.className = "fe";
    root.innerHTML = `
      <div class="fe-bar"><input class="fe-name" spellcheck="false" placeholder="name this flow">
        <span class="fe-status"></span>
        <button class="fe-btn" data-a="test">Test</button><button class="fe-btn hot" data-a="save">Save</button>
        <button class="fe-btn" data-a="close">Close</button></div>
      <div class="fe-canvas"><div class="fe-world"><svg class="fe-wires" width="1" height="1"></svg></div></div>
      <div class="fe-palette"><input class="fe-search" placeholder="search nodes…" spellcheck="false"><div class="fe-list"></div></div>`;
    document.body.appendChild(root);
    world = root.querySelector(".fe-world"); svg = root.querySelector(".fe-wires");
    palette = root.querySelector(".fe-palette"); status = root.querySelector(".fe-status");
    nameBox = root.querySelector(".fe-name");
    root.querySelector('[data-a="close"]').onclick = close;
    root.querySelector('[data-a="save"]').onclick = save;
    root.querySelector('[data-a="test"]').onclick = () => { status.textContent = "testing…"; send({ t: "flow_test", graph: snapshot() }); };
    const canvas = root.querySelector(".fe-canvas");
    canvas.addEventListener("pointerdown", onCanvasDown);
    canvas.addEventListener("contextmenu", e => { e.preventDefault(); showPalette(e.clientX, e.clientY, null); });
    canvas.addEventListener("wheel", onWheel, { passive: false });
    addEventListener("pointermove", onMove);
    addEventListener("pointerup", onUp);
    addEventListener("keydown", onKey);
    root.querySelector(".fe-search").addEventListener("input", () => fillPalette());
    send({ t: "flow_catalog" });
  }

  // ----- opening and closing -----
  function openFlow(id) { send({ t: "flow_open", id: id || null }); show(); }
  function show() { open = true; root.classList.add("open"); }
  function close() { open = false; root.classList.remove("open"); hidePalette(); send({ t: "__closed" }); }
  const isOpen = () => open;

  // ----- messages from the core -----
  function message(msg) {
    if (msg.t === "catalog") { catalog = {}; for (const n of msg.nodes || []) catalog[n.type] = n; return; }
    if (msg.t === "flow_graph") {
      // Her edits arrive live: show them if this flow is open, or if nothing is.
      const theirs = msg.by === "aries";
      if (!open && !theirs) return;
      if (open && graph && graph.id && msg.id && msg.id !== graph.id && !theirs) return;
      const before = graph && graph.id === msg.id ? new Set(graph.nodes.map(n => n.id)) : new Set();
      load(msg.graph || { nodes: [], links: [] }, msg.id);
      if (theirs) { show(); arrive(before); status.textContent = `${msg.summary || ""} — built by her`; }
      else status.textContent = msg.summary || "";
      return;
    }
    if (msg.t === "flow_saved") {
      clearErrors();
      if (msg.ok) { if (graph) graph.id = msg.id; status.textContent = `saved — ${msg.summary || ""}`; }
      else { status.textContent = `${(msg.errors || []).length} problem(s)`; for (const e of msg.errors || []) markError(e); }
      return;
    }
    if (msg.t === "flow_tested") { status.textContent = msg.ok ? "test ran" : `test stopped: ${msg.note || ""}`; return; }
    if (msg.t === "flow" && open && graph && (msg.flow === graph.id || !graph.id)) {
      if (msg.phase === "node" && msg.node) flash(msg.node, "run");
      if (msg.phase === "failed" && msg.node) flash(msg.node, "bad");
    }
  }

  // ----- the model -----
  function load(g, id) {
    graph = { id: id || g.id || null, name: g.name || "", enabled: g.enabled !== false, mode: g.mode || "ignore",
      nodes: (g.nodes || []).map(n => ({ ...n, values: { ...(n.values || {}) }, pos: n.pos || [100, 100] })),
      links: (g.links || []).map(l => ({ from: [...l.from], to: [...l.to] })), made_by: g.made_by || "ronald" };
    nameBox.value = graph.name;
    render();
  }
  function snapshot() {
    return { ...graph, name: nameBox.value.trim() || "Untitled flow", nodes: graph.nodes, links: graph.links };
  }
  function save() { status.textContent = "saving…"; send({ t: "flow_save", graph: snapshot() }); }
  const newId = () => "n" + Math.random().toString(36).slice(2, 7);
  const def = type => catalog[type] || { title: type, category: "data", inputs: [], outputs: [], exec_in: false, exec_out: [] };

  // ----- drawing -----
  function render() {
    world.querySelectorAll(".fe-node").forEach(e => e.remove());
    if (!graph) return;
    for (const n of graph.nodes) world.appendChild(nodeEl(n));
    applyView(); drawWires();
  }
  function nodeEl(n) {
    const d = def(n.type), el = document.createElement("div");
    el.className = `fe-node cat-${d.category}${d.costly ? " costly" : ""}`; el.dataset.node = n.id;
    el.style.left = n.pos[0] + "px"; el.style.top = n.pos[1] + "px";
    const head = document.createElement("div"); head.className = "fe-head"; head.textContent = d.title || n.type;
    head.style.borderTopColor = CAT_COLOR[d.category] || "#888";
    if (d.available === false) head.title = "not available yet";
    el.appendChild(head);
    const body = document.createElement("div"); body.className = "fe-body";
    const left = document.createElement("div"), right = document.createElement("div");
    left.className = "fe-col"; right.className = "fe-col right";
    if (d.exec_in) left.appendChild(pinRow(n, "exec", "exec", "in", ""));
    for (const p of d.inputs || []) left.appendChild(pinRow(n, p.name, p.type, "in", p.name, p));
    for (const name of d.exec_out || []) right.appendChild(pinRow(n, name, "exec", "out", name === "exec" ? "" : name));
    for (const p of d.outputs || []) right.appendChild(pinRow(n, p.name, p.type, "out", p.name));
    body.append(left, right); el.appendChild(body);
    head.addEventListener("pointerdown", e => {
      e.stopPropagation(); select(n.id);
      moving = { id: n.id, x0: e.clientX, y0: e.clientY, p0: [...n.pos] };
    });
    el.addEventListener("pointerdown", e => { e.stopPropagation(); select(n.id); });
    return el;
  }
  function pinRow(n, name, type, side, label, spec) {
    const row = document.createElement("div"); row.className = `fe-pin ${side}`;
    const dot = document.createElement("span");
    dot.className = `dot ${type === "exec" ? "exec" : ""}`; dot.style.setProperty("--c", type === "exec" ? "#f5f5f5" : colorOf(type));
    dot.dataset.node = n.id; dot.dataset.pin = name; dot.dataset.side = side; dot.dataset.type = type;
    dot.addEventListener("pointerdown", e => { e.stopPropagation(); startWire(dot, e); });
    const txt = document.createElement("span"); txt.className = "lbl"; txt.textContent = label;
    if (side === "in") row.append(dot, txt); else row.append(txt, dot);
    // An unwired input takes a typed-in value.
    if (side === "in" && type !== "exec" && spec && !isWired(n.id, name)) {
      const f = field(spec, n.values[name], v => { n.values[name] = v; });
      row.appendChild(f);
    }
    return row;
  }
  function field(spec, value, set) {
    if (spec.type === "yes/no") {
      const c = document.createElement("input"); c.type = "checkbox"; c.checked = !!(value ?? spec.default);
      c.onchange = () => set(c.checked); return c;
    }
    const i = document.createElement("input"); i.className = "fe-val"; i.spellcheck = false;
    i.type = spec.type === "number" ? "number" : "text";
    i.value = value ?? spec.default ?? ""; i.placeholder = spec.type || "";
    i.onchange = () => set(spec.type === "number" ? Number(i.value) : i.value);
    i.addEventListener("pointerdown", e => e.stopPropagation());
    return i;
  }
  const isWired = (node, pin) => graph.links.some(l => l.to[0] === node && l.to[1] === pin);

  function pinPos(node, pin, side) {
    const dot = world.querySelector(`.dot[data-node="${node}"][data-pin="${CSS.escape(pin)}"][data-side="${side}"]`);
    if (!dot) return null;
    const r = dot.getBoundingClientRect(), w = world.getBoundingClientRect();
    return [(r.left + r.width / 2 - w.left) / view.k, (r.top + r.height / 2 - w.top) / view.k];
  }
  function curve(a, b) {
    const dx = Math.max(40, Math.abs(b[0] - a[0]) * 0.5);
    return `M${a[0]},${a[1]} C${a[0] + dx},${a[1]} ${b[0] - dx},${b[1]} ${b[0]},${b[1]}`;
  }
  function drawWires() {
    svg.innerHTML = "";
    if (!graph) return;
    for (const l of graph.links) {
      const a = pinPos(l.from[0], l.from[1], "out"), b = pinPos(l.to[0], l.to[1], "in");
      if (!a || !b) continue;
      const exec = l.to[1] === "exec";
      const fromDef = def((graph.nodes.find(n => n.id === l.from[0]) || {}).type);
      const out = (fromDef.outputs || []).find(o => o.name === l.from[1]);
      const p = document.createElementNS("http://www.w3.org/2000/svg", "path");
      p.setAttribute("d", curve(a, b));
      p.setAttribute("class", exec ? "w exec" : "w");
      p.style.stroke = exec ? "#f2e6e8" : colorOf(out && out.type);
      p.dataset.from = l.from[0]; p.dataset.to = l.to[0];
      svg.appendChild(p);
    }
    if (wiring && wiring.at) {
      const p = document.createElementNS("http://www.w3.org/2000/svg", "path");
      const a = wiring.side === "out" ? wiring.start : wiring.at, b = wiring.side === "out" ? wiring.at : wiring.start;
      p.setAttribute("d", curve(a, b)); p.setAttribute("class", "w live"); svg.appendChild(p);
    }
  }
  function applyView() {
    world.style.transform = `translate(${view.x}px, ${view.y}px) scale(${view.k})`;
    const c = root.querySelector(".fe-canvas");
    c.style.backgroundPosition = `${view.x}px ${view.y}px`;
    c.style.backgroundSize = `${24 * view.k}px ${24 * view.k}px`;
  }
  const toWorld = (cx, cy) => {
    const r = root.querySelector(".fe-canvas").getBoundingClientRect();
    return [(cx - r.left - view.x) / view.k, (cy - r.top - view.y) / view.k];
  };

  // ----- interaction -----
  function select(id) {
    sel = id;
    world.querySelectorAll(".fe-node").forEach(e => e.classList.toggle("sel", e.dataset.node === id));
  }
  function startWire(dot, e) {
    const node = dot.dataset.node, pin = dot.dataset.pin, side = dot.dataset.side;
    if (side === "in" && isWired(node, pin)) {
      // Pull an existing wire off an input and carry it.
      const l = graph.links.find(l => l.to[0] === node && l.to[1] === pin);
      graph.links = graph.links.filter(x => x !== l);
      wiring = { node: l.from[0], pin: l.from[1], side: "out", type: dot.dataset.type, start: pinPos(l.from[0], l.from[1], "out") };
      render();
    } else {
      wiring = { node, pin, side, type: dot.dataset.type, start: pinPos(node, pin, side) };
    }
    wiring.at = toWorld(e.clientX, e.clientY);
  }
  function onCanvasDown(e) {
    hidePalette();
    if (e.button === 1 || e.button === 0) { panning = { x0: e.clientX, y0: e.clientY, v0: { ...view } }; select(null); }
  }
  function onMove(e) {
    if (!open) return;
    if (panning) { view.x = panning.v0.x + e.clientX - panning.x0; view.y = panning.v0.y + e.clientY - panning.y0; applyView(); }
    if (moving) {
      const n = graph.nodes.find(n => n.id === moving.id);
      n.pos = [moving.p0[0] + (e.clientX - moving.x0) / view.k, moving.p0[1] + (e.clientY - moving.y0) / view.k];
      const el = world.querySelector(`.fe-node[data-node="${n.id}"]`);
      el.style.left = n.pos[0] + "px"; el.style.top = n.pos[1] + "px";
      drawWires();
    }
    if (wiring) { wiring.at = toWorld(e.clientX, e.clientY); drawWires(); }
  }
  function onUp(e) {
    if (!open) return;
    panning = null; moving = null;
    if (!wiring) return;
    const t = document.elementFromPoint(e.clientX, e.clientY);
    const dot = t && t.closest && t.closest(".dot");
    const w = wiring; wiring = null;
    if (dot && dot.dataset.side !== w.side && dot.dataset.node !== w.node) link(w, dot.dataset.node, dot.dataset.pin, dot.dataset.type);
    else if (!dot) showPalette(e.clientX, e.clientY, w);
    render();
  }
  function compatible(a, b) {
    if ((a === "exec") !== (b === "exec")) return false;
    return a === b || a === "exec" || b === "text" || a === "any" || b === "any";   // anything writes out as text
  }
  function link(w, node, pin, type) {
    const out = w.side === "out" ? [w.node, w.pin] : [node, pin];
    const inn = w.side === "out" ? [node, pin] : [w.node, w.pin];
    const outType = w.side === "out" ? w.type : type, inType = w.side === "out" ? type : w.type;
    if (!compatible(outType, inType)) { status.textContent = `${outType} can't go into ${inType}`; return; }
    if (inType !== "exec") graph.links = graph.links.filter(l => !(l.to[0] === inn[0] && l.to[1] === inn[1]));
    if (outType === "exec") graph.links = graph.links.filter(l => !(l.from[0] === out[0] && l.from[1] === out[1]));
    graph.links.push({ from: out, to: inn });
  }
  function onWheel(e) {
    e.preventDefault();
    const r = root.querySelector(".fe-canvas").getBoundingClientRect(), k = Math.min(2, Math.max(0.3, view.k * (e.deltaY < 0 ? 1.1 : 0.9)));
    const mx = e.clientX - r.left, my = e.clientY - r.top;
    view.x = mx - (mx - view.x) * (k / view.k); view.y = my - (my - view.y) * (k / view.k); view.k = k;
    applyView(); drawWires();
  }
  function onKey(e) {
    if (!open || e.target.tagName === "INPUT") return;
    if ((e.key === "Delete" || e.key === "Backspace") && sel) {
      graph.nodes = graph.nodes.filter(n => n.id !== sel);
      graph.links = graph.links.filter(l => l.from[0] !== sel && l.to[0] !== sel);
      sel = null; render();
    } else if (e.key === " ") {
      e.preventDefault(); const r = root.getBoundingClientRect(); showPalette(r.left + r.width / 2, r.top + r.height / 2, null);
    } else if (e.key === "Escape") { if (palette.classList.contains("open")) hidePalette(); else close(); }
  }

  // ----- the palette -----
  let pending = null;
  function showPalette(cx, cy, fromWire) {
    pending = { at: toWorld(cx, cy), wire: fromWire };
    const r = root.getBoundingClientRect();
    palette.style.left = Math.min(cx - r.left, r.width - 320) + "px";
    palette.style.top = Math.min(cy - r.top, r.height - 380) + "px";
    palette.classList.add("open");
    const s = palette.querySelector(".fe-search"); s.value = ""; fillPalette(); s.focus();
  }
  function hidePalette() { palette.classList.remove("open"); pending = null; }
  function fits(d) {
    const w = pending && pending.wire;
    if (!w) return true;
    if (w.side === "out") {
      if (w.type === "exec") return d.exec_in;
      return (d.inputs || []).some(p => compatible(w.type, p.type));
    }
    if (w.type === "exec") return (d.exec_out || []).length > 0;
    return (d.outputs || []).some(p => compatible(p.type, w.type));
  }
  function fillPalette() {
    const q = palette.querySelector(".fe-search").value.toLowerCase().split(/\s+/).filter(Boolean);
    const list = palette.querySelector(".fe-list"); list.innerHTML = "";
    const all = Object.values(catalog).filter(d => fits(d) && q.every(w => `${d.title} ${d.type} ${d.description || ""}`.toLowerCase().includes(w)));
    const order = ["start", "check", "action", "flow", "data"];
    all.sort((a, b) => order.indexOf(a.category) - order.indexOf(b.category) || a.title.localeCompare(b.title));
    let cat = "";
    for (const d of all.slice(0, 80)) {
      if (d.category !== cat) { cat = d.category; const h = document.createElement("div"); h.className = "fe-cat"; h.textContent = cat.toUpperCase(); h.style.color = CAT_COLOR[cat]; list.appendChild(h); }
      const it = document.createElement("div"); it.className = `fe-item${d.available === false ? " off" : ""}`;
      const t = document.createElement("b"); t.textContent = d.title;
      const s = document.createElement("span"); s.textContent = d.description || "";
      it.append(t, s); it.onclick = () => add(d);
      list.appendChild(it);
    }
  }
  function add(d) {
    if (!graph) load({ nodes: [], links: [] }, null);
    const n = { id: newId(), type: d.type, values: {}, pos: pending ? pending.at : [100, 100] };
    graph.nodes.push(n);
    const w = pending && pending.wire;
    hidePalette(); render();
    if (w) {
      // Connect the wire that was dropped here to the first pin that fits.
      if (w.side === "out") {
        const pin = w.type === "exec" ? "exec" : ((d.inputs || []).find(p => compatible(w.type, p.type)) || {}).name;
        if (pin) link(w, n.id, pin, w.type === "exec" ? "exec" : (d.inputs.find(p => p.name === pin) || {}).type);
      } else {
        const pin = w.type === "exec" ? (d.exec_out || [])[0] : ((d.outputs || []).find(p => compatible(p.type, w.type)) || {}).name;
        if (pin) link(w, n.id, pin, w.type === "exec" ? "exec" : (d.outputs.find(p => p.name === pin) || {}).type);
      }
      render();
    }
    select(n.id);
  }

  // ----- live -----
  // New nodes from her build pop in one after another.
  function arrive(before) {
    let i = 0;
    for (const n of graph.nodes) {
      if (before.has(n.id)) continue;
      const el = world.querySelector(`.fe-node[data-node="${n.id}"]`);
      if (!el) continue;
      el.classList.add("arriving"); el.style.animationDelay = `${i++ * 0.18}s`;
    }
  }
  function flash(id, kind) {
    const el = world.querySelector(`.fe-node[data-node="${id}"]`);
    if (!el) return;
    el.classList.remove(kind); void el.offsetWidth; el.classList.add(kind);
    svg.querySelectorAll(`path[data-to="${id}"]`).forEach(p => { p.classList.remove("hot"); void p.getBBox(); p.classList.add("hot"); });
  }
  function clearErrors() { world.querySelectorAll(".fe-node.err").forEach(e => { e.classList.remove("err"); e.title = ""; }); }
  function markError(e) {
    const el = e.node && world.querySelector(`.fe-node[data-node="${e.node}"]`);
    if (el) { el.classList.add("err"); el.title = (e.pin ? `${e.pin}: ` : "") + e.message; }
  }

  return { init, openFlow, message, isOpen, close };
})();
