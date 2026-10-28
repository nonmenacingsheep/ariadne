"use strict";
// The Steam, browser and Discord widgets. Same contract as spotify.js:
// build(widget, send), set(state), touch(control, on). Everything that comes
// from outside (game names, tab titles, DMs) is set as text, never as HTML,
// so a message or page title can't inject anything into the desk.

const SVG = {
  play: '<svg viewBox="0 0 16 16"><path d="M4 2l10 6-10 6z"/></svg>',
  pause: '<svg viewBox="0 0 16 16"><path d="M3 2h3.5v12H3zM9.5 2H13v12H9.5z"/></svg>',
  next: '<svg viewBox="0 0 16 16"><path d="M11 2h2v12h-2zM2 2v12l8-6z"/></svg>',
};
const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
const ago = t => {
  const s = Math.max(0, Date.now() / 1000 - t);
  if (s < 3600) return `${Math.max(1, Math.round(s / 60))} min`;
  if (s < 86400) return `${Math.round(s / 3600)} h`;
  return `${Math.round(s / 86400)} d`;
};
const bytes = n => n >= 1e9 ? `${(n / 1e9).toFixed(1)} GB` : `${Math.round((n || 0) / 1e6)} MB`;
const touchIn = (w, control, on) => w && control && w.bd.querySelectorAll(`[data-c="${control}"]`).forEach(e => e.classList.toggle("on", on));
// Lists move one row per wheel notch, like the Spotify queue.
const stepScroll = list => list.addEventListener("wheel", e => {
  e.preventDefault();
  const row = list.firstElementChild;
  list.scrollBy({ top: Math.sign(e.deltaY) * (row ? row.offsetHeight + 4 : 24), behavior: "smooth" });
}, { passive: false });
// A button that needs two clicks within 3 s, for things that can lose work.
const twoClick = (btn, label, go) => {
  let armed = 0;
  btn.addEventListener("click", e => {
    e.stopPropagation();
    if (Date.now() - armed < 3000) { go(); return; }
    armed = Date.now(); btn.classList.add("armed"); const was = btn.textContent; btn.textContent = label;
    setTimeout(() => { btn.classList.remove("armed"); btn.textContent = was; }, 3000);
  });
};

/* ---------------- Steam ---------------- */
const Steam = (() => {
  let w, send, st = {};
  const art = id => `https://cdn.akamai.steamstatic.com/steam/apps/${id}/header.jpg`;
  function build(widget, s) {
    w = widget; send = s;
    w.bd.innerHTML = `<div class="st-now"></div><div class="st-dl"></div><div class="st-grid"></div>`;
  }
  function set(data) {
    st = data || {}; if (!w) return;
    const playing = st.playing, dls = st.downloads || [];
    if (w.tag && !w.tagWas) w.tag.textContent = st.status !== "running" ? "NOT RUNNING"
      : playing ? `PLAYING` : dls.length ? `${dls.length} DOWNLOADING` : "";
    const now = w.bd.querySelector(".st-now"); now.innerHTML = "";
    if (playing) {
      const img = el("img"); img.src = art(playing.appid); img.alt = ""; img.onerror = () => img.remove();
      const meta = el("div", "st-nmeta");
      meta.append(el("div", "st-nname", playing.name), el("div", "st-nsince", `playing for ${ago(playing.since)}`));
      const stop = el("button", "st-close", "Close"); stop.dataset.c = "close";
      twoClick(stop, "Close? click again", () => send({ t: "press", widget: "steam", control: "close", value: playing.appid }));
      now.append(img, meta, stop);
    }
    const dl = w.bd.querySelector(".st-dl"); dl.innerHTML = "";
    for (const d of dls.slice(0, 3)) {
      const row = el("div", "st-drow");
      const top = el("div", "kv"); top.append(el("span", null, d.name), el("span", null,
        `${Math.round((d.progress || 0) * 100)}%${d.rate_bps ? " · " + (d.rate_bps / 1e6).toFixed(1) + " MB/s" : ""} · ${bytes(d.bytes_done)}/${bytes(d.bytes_total)}${d.state !== "downloading" ? " · " + d.state : ""}`));
      const bar = el("div", "bar st-dbar"); const b = el("b"); b.style.width = `${(d.progress || 0) * 100}%`; bar.append(b);
      row.append(top, bar); dl.append(row);
    }
    const grid = w.bd.querySelector(".st-grid"); grid.innerHTML = "";
    for (const g of (st.recent || []).slice(0, 8)) {
      const card = el("div", `st-card${g.installed ? "" : " missing"}${playing && playing.appid === g.appid ? " live" : ""}`);
      const img = el("img"); img.src = art(g.appid); img.alt = ""; img.onerror = () => { img.remove(); card.classList.add("noart"); };
      const cap = el("div", "st-cap"); cap.append(el("span", null, g.name), el("span", null, `${Math.round(g.hours || 0)} h`));
      card.append(img, cap);
      if (g.installed && !(playing && playing.appid === g.appid)) {
        const go = el("button", "st-play", "▶ Play"); go.dataset.c = "launch";
        go.addEventListener("click", e => { e.stopPropagation(); go.textContent = "Starting…"; send({ t: "press", widget: "steam", control: "launch", value: g.appid }); });
        card.append(go);
      }
      card.title = `${g.name} — last played ${g.last_played ? ago(g.last_played) + " ago" : "never"}`;
      grid.append(card);
    }
  }
  return { build, set, touch: (c, on) => touchIn(w, c, on) };
})();

/* ---------------- Browser ---------------- */
const Browser = (() => {
  let w, send, st = {}, key = "";
  const host = u => { try { return new URL(u).hostname.replace(/^www\./, ""); } catch (e) { return ""; } };
  function build(widget, s) {
    w = widget; send = s;
    w.bd.innerHTML = `<div class="br-media"></div><div class="br-tabs"></div>`;
    stepScroll(w.bd.querySelector(".br-tabs"));
  }
  function set(data) {
    st = data || {}; if (!w) return;
    const tabs = st.tabs || [];
    if (w.tag && !w.tagWas) w.tag.textContent = st.status !== "connected" ? "NOT CONNECTED" : `${tabs.length} TABS`;
    const m = st.media, media = w.bd.querySelector(".br-media"); media.innerHTML = "";
    if (m) {
      const info = el("div", "br-minfo"); info.append(el("div", "br-mtitle", m.title || ""), el("div", "br-msite", m.site || ""));
      const play = el("button", "br-btn"); play.innerHTML = m.playing ? SVG.pause : SVG.play; play.dataset.c = "play";
      play.addEventListener("click", () => send({ t: "press", widget: "browser", control: "play" }));
      const next = el("button", "br-btn"); next.innerHTML = SVG.next; next.dataset.c = "next"; next.title = "Next episode";
      next.addEventListener("click", () => send({ t: "press", widget: "browser", control: "next" }));
      media.append(info, play, next);
    }
    // Rebuild the tab list only when it changes, so its scroll position holds.
    const k = JSON.stringify(tabs.map(t => [t.id, t.title, t.active, t.audible]));
    if (k === key) return; key = k;
    const list = w.bd.querySelector(".br-tabs"); list.innerHTML = "";
    for (const t of tabs) {
      const row = el("div", `br-tab${t.active ? " active" : ""}`); row.dataset.c = "tab";
      // No favicon (or a broken one) gets a small dot, never a broken-image box.
      const ic = t.favicon ? el("img", "br-fav") : el("span", "br-fav dot");
      if (t.favicon) { ic.alt = ""; ic.src = t.favicon; ic.onerror = () => ic.replaceWith(el("span", "br-fav dot")); }
      const txt = el("div", "br-ttxt"); txt.append(el("span", "br-ttitle", t.title || t.url), el("span", "br-thost", host(t.url)));
      const x = el("button", "br-x", "✕"); x.title = "Close tab"; x.dataset.c = "close";
      x.addEventListener("click", e => { e.stopPropagation(); row.classList.add("closing"); send({ t: "press", widget: "browser", control: "close", value: t.id }); });
      row.append(ic, txt);
      if (t.audible) row.append(el("span", "br-aud", "♪"));
      row.append(x);
      row.addEventListener("click", () => send({ t: "press", widget: "browser", control: "tab", value: t.id }));
      list.append(row);
    }
  }
  return { build, set, touch: (c, on) => touchIn(w, c, on) };
})();

/* ---------------- Discord ---------------- */
const Discord = (() => {
  let w, send, st = {};
  function build(widget, s) {
    w = widget; send = s;
    w.bd.innerHTML = `<div class="dc-top"><div class="dc-self">
        <button class="dc-btn" data-c="mute">Mute</button><button class="dc-btn" data-c="deafen">Deafen</button></div>
        <div class="dc-unread"></div></div><div class="dc-voice"></div><div class="dc-dms"></div>`;
    for (const b of w.bd.querySelectorAll(".dc-btn")) b.addEventListener("click", () => send({ t: "press", widget: "discord", control: b.dataset.c }));
  }
  function set(data) {
    st = data || {}; if (!w) return;
    const ok = st.status === "connected";
    if (w.tag && !w.tagWas) w.tag.textContent = ok ? (st.voice ? "IN VOICE" : "") : st.status === "not open" ? "NOT OPEN" : "NOT CONNECTED";
    w.root.classList.toggle("dc-off", !ok);
    const self = st.self || {};
    w.bd.querySelector('[data-c="mute"]').classList.toggle("lit", !!self.muted);
    w.bd.querySelector('[data-c="deafen"]').classList.toggle("lit", !!self.deafened);
    const un = st.unread || {}, ub = w.bd.querySelector(".dc-unread"); ub.innerHTML = "";
    if (un.dms) ub.append(el("span", "dc-badge", `${un.dms} DM${un.dms > 1 ? "s" : ""}`));
    if (un.mentions) ub.append(el("span", "dc-badge hot", `${un.mentions} @`));
    const v = st.voice, vb = w.bd.querySelector(".dc-voice"); vb.innerHTML = "";
    if (v) {
      vb.append(el("div", "dc-chan", `${v.channel}${v.server ? " · " + v.server : ""}`));
      const people = el("div", "dc-people");
      for (const m of v.members || []) people.append(el("span", `dc-person${m.speaking ? " speaking" : ""}${m.muted ? " muted" : ""}`, m.name));
      vb.append(people);
    } else if (!ok) {
      vb.append(el("div", "dim", st.status === "not open" ? "Discord isn't open in Opera. Ask her to open it." : "Can't reach Opera's debugging port."));
    }
    const dms = w.bd.querySelector(".dc-dms"); dms.innerHTML = "";
    for (const d of (st.recent_dms || []).slice(0, 5)) {
      const row = el("div", "dc-dm"); row.append(el("span", "dc-from", d.from), el("span", "dc-prev", d.preview), el("span", "dc-time", d.time || ""));
      dms.append(row);
    }
  }
  return { build, set, touch: (c, on) => touchIn(w, c, on) };
})();
