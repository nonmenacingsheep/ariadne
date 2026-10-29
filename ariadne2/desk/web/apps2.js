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
      const c = el("div", "dp-chip", x.name); c.title = x.path; c.onclick = () => open(x.path); fol.append(c);
    }
    const fil = w.bd.querySelector(".dp-files"); fil.innerHTML = "";
    for (const x of (st.recent_files || []).slice(0, 6)) {
      const row = el("div", "dp-file"); row.title = x.path;
      const dot = el("span", "dp-kind"); dot.style.background = KIND_COLOR[x.kind] || KIND_COLOR.other;
      row.append(dot, el("span", "dp-name", x.name), el("span", "dp-when", sinceText(x.when)));
      row.onclick = () => open(x.path); fil.append(row);
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

/* ---------------- Claude (her hands) ---------------- */
const Claude = (() => {
  let w, send, st = {};
  function build(widget, s) {
    w = widget; send = s;
    w.bd.innerHTML = `<div class="cl-list"></div>`;
    stepScroll(w.bd.querySelector(".cl-list"));
  }
  function set(data) {
    st = data || {}; if (!w) return;
    const ss = st.sessions || [], list = w.bd.querySelector(".cl-list");
    const busy = ss.filter(x => x.state === "working").length;
    if (w.tag && !w.tagWas) w.tag.textContent = st.status === "no claude" ? "NO CLAUDE" : busy ? `${busy} WORKING` : ss.length ? `${ss.length} RECENT` : "";
    list.innerHTML = "";
    if (!ss.length) { list.append(el("div", "dim", st.status === "no claude" ? "Claude Code isn't installed here." : "No Claude Code sessions in the last few hours.")); return; }
    for (const x of ss) {
      const row = el("div", `cl-row ${x.state}`);
      const top = el("div", "cl-top");
      top.append(el("span", `cl-dot ${x.state}`), el("span", "cl-proj", x.project), el("span", "cl-title", x.title));
      if (x.mine) top.append(el("span", "cl-mine", "HER HAND"));
      const sub = el("div", "cl-sub");
      sub.append(el("span", "cl-last", x.last || ""), el("span", "cl-meta", `${x.steps || 0} steps · ${sinceText(x.updated)}`));
      const btns = el("div", "cl-btns");
      const op = el("button", "cl-btn", "Folder"); op.onclick = () => send({ t: "press", widget: "claude", control: "open", value: x.id }); btns.append(op);
      if (x.mine && x.state === "working") {
        const stop = el("button", "cl-btn", "Stop"); stop.dataset.c = "stop";
        twoClick(stop, "Stop?", () => send({ t: "press", widget: "claude", control: "stop", value: x.id })); btns.append(stop);
      }
      row.append(top, sub, btns); list.append(row);
    }
  }
  return { build, set, touch: (c, on) => touchIn(w, c, on) };
})();

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
