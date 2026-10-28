"use strict";
// The Flows widget: one row per flow (on/off, its one-line summary, when it
// last fired and how it went), Run for manual flows, Approve for flows she
// built that need his OK, and a row that flares when its flow fires.
const Flows = (() => {
  let w, send, st = {};
  const ago = t => {
    if (!t) return "never";
    const s = Math.max(0, Date.now() / 1000 - t);
    return s < 60 ? "just now" : s < 3600 ? `${Math.round(s / 60)} min ago` : s < 86400 ? `${Math.round(s / 3600)} h ago` : `${Math.round(s / 86400)} d ago`;
  };
  const press = (control, id) => send({ t: "press", widget: "flows", control, value: id });
  function build(widget, s) {
    w = widget; send = s;
    w.bd.innerHTML = `<div class="fl-list"></div>`;
    stepScroll(w.bd.querySelector(".fl-list"));
  }
  function set(data) {
    st = data || {}; if (!w) return;
    const flows = st.flows || [], list = w.bd.querySelector(".fl-list");
    if (w.tag && !w.tagWas) w.tag.textContent = flows.length ? `${flows.filter(f => f.enabled).length} ON` : "";
    list.innerHTML = "";
    if (!flows.length) { list.append(el("div", "dim", "No flows yet. Tell her \"whenever…\" and she'll make one.")); return; }
    for (const f of flows) {
      const row = el("div", `fl-row${f.enabled ? "" : " off"}${f.approved === false ? " pending" : ""}`); row.dataset.flow = f.id;
      const sw = el("button", `fl-switch${f.enabled ? " on" : ""}`); sw.title = f.enabled ? "Turn off" : "Turn on";
      sw.addEventListener("click", () => { sw.classList.toggle("on"); press("toggle", f.id); });
      const txt = el("div", "fl-txt");
      const name = el("div", "fl-name", f.name);
      if (f.uses_ai) name.append(el("span", "fl-ai", " ✦"));
      if (f.made_by === "aries") name.append(el("span", "fl-by", " by her"));
      txt.append(name, el("div", "fl-sum", f.summary || ""));
      if (f.note) txt.append(el("div", "fl-note", f.note));
      const side = el("div", "fl-side");
      side.append(el("span", `fl-last ${f.last_result || ""}`, ago(f.last_fired)));
      if (f.approved === false) {
        const ok = el("button", "fl-btn hot", "Approve"); ok.title = f.summary || "";
        ok.addEventListener("click", () => press("approve", f.id)); side.append(ok);
      } else if (f.manual) {
        const run = el("button", "fl-btn", "Run"); run.addEventListener("click", () => press("run", f.id)); side.append(run);
      }
      const del = el("button", "fl-x", "✕"); del.title = "Delete";
      twoClick(del, "delete?", () => press("delete", f.id)); side.append(del);
      row.append(sw, txt, side); list.append(row);
    }
  }
  // A flow fired, finished or failed: flare its row.
  function event(msg) {
    if (!w) return;
    const row = w.bd.querySelector(`[data-flow="${msg.flow}"]`);
    if (!row) return;
    if (msg.phase === "fired") { row.classList.remove("fired"); void row.offsetWidth; row.classList.add("fired"); }
    if (msg.phase === "failed") { row.classList.add("bad"); setTimeout(() => row.classList.remove("bad"), 2500); }
  }
  return { build, set, event, touch: () => {} };
})();
