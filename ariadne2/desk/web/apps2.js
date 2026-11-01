"use strict";
// The Dolphin (files), Claude (her hands) and System widgets. Same contract
// as apps.js: build(widget, send), set(state), touch(control, on); outside
// text goes in as text only (el() normalises it).

const KIND_COLOR = { image: "#6d8cff", audio: "#ff4d8a", video: "#b18cff", doc: "#e8dccb",
  archive: "#ffb347", code: "#00e5ff", other: "#8a7f88" };
const sinceText = t => {
  if (!t) return "";
  const s = Math.max(0, Date.now() / 1000 - t);
  return s < 60 ? "now" : s < 3600 ? `${Math.round(s / 60)}m` : s < 86400 ? `${Math.round(s / 3600)}h` : `${Math.round(s / 86400)}d`;
};

/* ---------------- Dolphin ---------------- */
const Dolphin = (() => {
  let w, send, st = {}, ticker = [];
  function build(widget, s) {
    w = widget; send = s;
    w.bd.innerHTML = `<div class="dp-now"></div><div class="dp-cols"><div class="dp-folders"></div><div class="dp-files"></div></div><div class="dp-ticker"></div>`;
  }
  const open = path => send({ t: "press", widget: "dolphin", control: "open", value: path });
  function set(data) {
    st = data || {}; if (!w) return;
    const watched = st.watched || [], fresh = watched.reduce((n, x) => n + (x.new || 0), 0);
    if (w.tag && !w.tagWas) w.tag.textContent = fresh ? `${fresh} NEW` : "";
    const now = w.bd.querySelector(".dp-now"); now.innerHTML = "";
    if (st.current) { now.append(el("span", "dp-here", "OPEN"), el("span", "dp-path", st.current.path)); now.onclick = () => open(st.current.path); }
    const fol = w.bd.querySelector(".dp-folders"); fol.innerHTML = "";
    for (const x of watched) {
      const c = el("div", "dp-chip watch", x.name); if (x.new) c.append(el("b", null, String(x.new)));
      c.title = x.path; c.onclick = () => open(x.path); fol.append(c);
    }
    for (const x of (st.recent_folders || []).slice(0, 6)) {
      const c = el("div", "dp-chip", x.name); c.title = x.path; c.onclick = () => open(x.path);
      c.prepend(FILE_ICON("folder"));
      c.oncontextmenu = e => { e.preventDefault(); FileMenu.open(e.clientX, e.clientY, { path: x.path, name: x.name, kind: "folder", folder: true }); };
      fol.append(c);
    }
    const fil = w.bd.querySelector(".dp-files"); fil.innerHTML = "";
    for (const x of (st.recent_files || []).slice(0, 6)) {
      const row = el("div", "dp-file"); row.title = x.path;
      row.append(FILE_ICON(x.kind), el("span", "dp-name", x.name), el("span", "dp-when", sinceText(x.when)));
      row.onclick = () => open(x.path);
      row.oncontextmenu = e => { e.preventDefault(); FileMenu.open(e.clientX, e.clientY, { path: x.path, name: x.name, kind: x.kind, folder: false }); };
      fil.append(row);
    }
  }
  // Each file she moves, sorts or bins slides through the ticker.
  function progress(msg) {
    if (!w || !msg.note) return;
    ticker.unshift(`${msg.verb} · ${msg.note}`); ticker = ticker.slice(0, 3);
    const tk = w.bd.querySelector(".dp-ticker"); tk.innerHTML = "";
    ticker.forEach((x, i) => tk.append(el("div", `dp-tick${i ? "" : " new"}`, x)));
  }
  return { build, set, progress, touch: (c, on) => touchIn(w, c, on) };
})();

/* The Claude widget lives in claude_ui.js. */

/* ---------------- System ---------------- */
const System = (() => {
  let w;
  const bar = (label, pct, extra) => {
    const m = el("div", "sy-m");
    const top = el("div", "sy-top"); top.append(el("span", "sy-l", label), el("span", "sy-v", pct == null ? "—" : `${Math.round(pct)}%`));
    const b = el("div", "bar"); const f = el("b"); f.style.width = `${pct || 0}%`;
    // Red like the rest of her; hotter and glowing as it climbs.
    f.style.background = pct > 85 ? "var(--red-hot)" : pct > 65 ? "#e0263a" : "linear-gradient(90deg, rgb(58,4,12), var(--red))";
    if (pct > 85) f.style.boxShadow = "0 0 8px var(--red-hot)";
    b.append(f);
    m.append(top, b); if (extra) m.append(el("div", "sy-x", extra)); return m;
  };
  function build(widget) { w = widget; w.bd.innerHTML = `<div class="sy-grid"></div>`; }
  function set(d) {
    if (!w) return;
    const g = w.bd.querySelector(".sy-grid"); g.innerHTML = "";
    g.append(bar("CPU", d.cpu), bar("MEM", d.mem, d.mem_total_gb ? `${(d.mem_used_gb || 0).toFixed(1)}/${Math.round(d.mem_total_gb)} GB` : ""));
    if (d.gpu != null) g.append(bar("GPU", d.gpu, d.gpu_mem != null ? `vram ${Math.round(d.gpu_mem)}%` : ""));
    for (const k of (d.disks || []).slice(0, 2)) g.append(bar(k.name.toUpperCase(), k.used_pct, `${Math.round(k.free_gb)} GB free`));
    const low = (d.disks || []).find(k => k.free_gb < 10);
    if (w.tag && !w.tagWas) w.tag.textContent = low ? `${low.name.toUpperCase()} LOW` : "";
  }
  return { build, set, touch: () => {} };
})();

/* ---------------- Tasks ---------------- */
// Open apps and what they use; hover a row to focus it or close it (two clicks).
const Tasks = (() => {
  let w, send;
  const hue = name => [...(name || "")].reduce((h, c) => (h * 31 + c.charCodeAt(0)) % 360, 11);
  const mb = n => n >= 1024 ? `${(n / 1024).toFixed(1)} GB` : `${Math.round(n || 0)} MB`;
  function build(widget, s) {
    w = widget; send = s;
    w.bd.innerHTML = `<div class="tk-head"><span>APP</span><span>CPU</span><span>MEM</span><span>GPU</span></div><div class="tk-list"></div>`;
    stepScroll(w.bd.querySelector(".tk-list"));
  }
  function set(st) {
    if (!w) return;
    const tot = st.total || {};
    if (w.tag && !w.tagWas) w.tag.textContent = `CPU ${Math.round(tot.cpu || 0)}% · MEM ${Math.round(tot.mem_pct || 0)}%`;
    const list = w.bd.querySelector(".tk-list"), keep = list.scrollTop;
    list.innerHTML = "";
    for (const a of st.apps || []) {
      const row = el("div", "tk-row" + (a.pinned ? " pinned" : ""));
      row.title = a.pinned ? "Right-click to unpin" : "Right-click to pin to the top";
      row.oncontextmenu = e => { e.preventDefault(); send({ t: "press", widget: "tasks", control: "pin", value: a.name }); };
      const tile = el("span", "tk-tile", (a.name || "?").charAt(0).toUpperCase());
      tile.style.background = `hsl(${hue(a.name)} 40% 30%)`;
      const nm = el("span", "tk-name", a.name); if (a.windows) nm.title = `${a.windows} window${a.windows > 1 ? "s" : ""}`;
      const cpu = el("span", "tk-cpu"); const bar = el("i"); bar.style.width = `${Math.min(100, (a.cpu || 0) / 4)}%`;
      cpu.append(bar, el("b", null, `${Math.round(a.cpu || 0)}%`));
      row.append(tile, nm, cpu, el("span", "tk-num", mb(a.mem_mb)), el("span", "tk-num", a.gpu_mb == null ? "—" : mb(a.gpu_mb)));
      const btns = el("span", "tk-btns");
      if (a.windows) { const f = el("button", "cl-btn", "Focus"); f.onclick = () => send({ t: "press", widget: "tasks", control: "focus", value: a.name }); btns.append(f); }
      if (a.name !== "System") {
        const x = el("button", "cl-btn", "Close"); x.dataset.c = "close";
        twoClick(x, "Close?", () => send({ t: "press", widget: "tasks", control: "close", value: a.name })); btns.append(x);
      }
      row.append(btns); list.append(row);
    }
    list.scrollTop = keep;
  }
  return { build, set, touch: (c, on) => touchIn(w, c, on) };
})();
