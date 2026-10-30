"use strict";
// Settings: the core sends a schema and the values; this draws controls for
// them and sends each change back as {t:"set"}. Used twice: the settings
// panel that slides out to the left of her core (General, Models, Voice,
// Desktop), and the Avatar widget (the avatar section, with her live needs).

const Settings = (() => {
  let schema = [], values = {}, send = () => {};
  let panel = null, tab = "general", open = false;
  const listeners = new Set();
  const TABS = [["general", "General"], ["models", "Models"], ["voice", "Voice"], ["desktop", "Desktop"]];

  function init(sendFn) {
    send = sendFn;
    panel = document.createElement("div"); panel.className = "setpanel";
    panel.innerHTML = `<div class="sp-tabs"></div><div class="sp-body"></div>`;
    document.body.appendChild(panel);
    watchRects(panel);
    const tabs = panel.querySelector(".sp-tabs");
    for (const [k, label] of TABS) {
      const b = document.createElement("button"); b.className = "port sp-tab"; b.dataset.k = k;
      b.innerHTML = `<span>${label}</span><i></i>`;
      b.onclick = () => { tab = k; draw(); };
      tabs.appendChild(b);
    }
  }
  function message(msg) {
    schema = msg.schema || schema; values = msg.values || values;
    if (open) draw();
    listeners.forEach(fn => fn());
  }
  const value = (section, key) => (values[section] || {})[key];
  const set = (section, key, v) => send({ t: "set", section, key, value: v });

  // One row per setting: label and a one-line hint on the left, control on the right.
  function rows(section, box) {
    box.innerHTML = "";
    for (const s of schema.filter(x => x.section === section)) {
      const row = document.createElement("div"); row.className = "sp-row";
      const text = document.createElement("div"); text.className = "sp-text";
      const l = document.createElement("div"); l.className = "sp-label"; l.textContent = s.label;
      const h = document.createElement("div"); h.className = "sp-help"; h.textContent = s.help || "";
      text.append(l, h); row.append(text, control(s));
      box.appendChild(row);
    }
  }
  function control(s) {
    const v = value(s.section, s.key) ?? s.default;
    if (s.type === "bool") {
      const b = document.createElement("button"); b.className = `fl-switch${v ? " on" : ""}`;
      b.onclick = () => { b.classList.toggle("on"); set(s.section, s.key, b.classList.contains("on")); };
      return b;
    }
    if (s.type === "choice") {
      const sel = document.createElement("select"); sel.className = "sp-select";
      for (const o of s.options || []) { const op = document.createElement("option"); op.value = o.value; op.textContent = o.label; op.selected = o.value === v; sel.appendChild(op); }
      sel.onchange = () => set(s.section, s.key, sel.value);
      return sel;
    }
    if (s.type === "number") {
      const wrap = document.createElement("div"); wrap.className = "sp-num";
      const r = document.createElement("input"); r.type = "range"; r.min = s.min; r.max = s.max; r.step = s.step || 1; r.value = v;
      const out = document.createElement("span"); const show = x => out.textContent = `${+(+x).toFixed(2)}${s.unit || ""}`; show(v);
      r.oninput = () => show(r.value);
      r.onchange = () => set(s.section, s.key, Number(r.value));
      wrap.append(r, out); return wrap;
    }
    if (s.type === "key") { const k = document.createElement("span"); k.className = "sp-key"; k.textContent = v || ""; return k; }
    if (s.type === "button" || s.type === "action") {
      const b = document.createElement("button"); b.className = "fe-btn"; b.textContent = s.button || s.label;
      twoClick(b, "Sure?", () => set(s.section, s.key, true)); return b;
    }
    const i = document.createElement("input"); i.className = "sp-input"; i.value = v ?? ""; i.spellcheck = false;
    const commit = () => { if (i.value !== String(v ?? "")) set(s.section, s.key, i.value); };
    i.onkeydown = e => { if (e.key === "Enter") i.blur(); };
    i.onblur = commit;
    return i;
  }

  // The panel opens to the left of her core, like the drawer opens below it.
  function toggle() {
    open = !open;
    W.core.root.classList.toggle("settings-open", open);
    if (open) draw();
    place();
    panel.classList.toggle("open", open);
    reportRects();
  }
  function place() {
    if (!rects.core) return;
    const [x, y] = rects.core;
    Object.assign(panel.style, { right: (innerWidth - x + DEPTH + 10) + "px", top: y + "px" });
  }
  function draw() {
    panel.querySelectorAll(".sp-tab").forEach(b => b.classList.toggle("live", b.dataset.k === tab));
    rows(tab, panel.querySelector(".sp-body"));
  }
  const isOpen = () => open;
  const rect = () => panel.getBoundingClientRect();
  return { init, message, toggle, place, isOpen, rect, rows, value, onChange: fn => listeners.add(fn) };
})();

/* ---------------- Avatar ---------------- */
// Her body: live needs and mood up top, then everything she's allowed to do.
const Avatar = (() => {
  let w;
  const NEEDS = [["hunger", "FED"], ["energy", "ENERGY"], ["fun", "FUN"], ["affection", "AFFECTION"]];
  function build(widget) {
    w = widget;
    w.bd.innerHTML = `<div class="av-needs"></div><div class="av-set"></div>`;
    Settings.onChange(() => Settings.rows("avatar", w.bd.querySelector(".av-set")));
    Settings.rows("avatar", w.bd.querySelector(".av-set"));
  }
  function set(st) {
    if (!w) return;
    if (w.tag && !w.tagWas) w.tag.textContent = (st.mood || "").toUpperCase();
    const box = w.bd.querySelector(".av-needs"); box.innerHTML = "";
    const needs = st.needs || {};
    for (const [k, label] of NEEDS) {
      const m = el("div", "sy-m"), top = el("div", "sy-top");
      const v = Math.round(100 * (needs[k] ?? 0));
      top.append(el("span", "sy-l", label), el("span", "sy-v", `${v}%`));
      const b = el("div", "bar"), f = el("b"); f.style.width = `${v}%`;
      f.style.background = v < 20 ? "var(--red-hot)" : "linear-gradient(90deg, rgb(58,4,12), var(--red))";
      b.append(f); m.append(top, b); box.append(m);
    }
  }
  return { build, set, touch: () => {} };
})();
