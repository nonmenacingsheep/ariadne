"use strict";
// The Spotify widget: now playing, a progress bar that ticks locally between
// state updates (so the core needn't send one a second), transport, like,
// volume and the queue. Buttons send `press` to the core; her own use of a
// control lights it cyan through `touch()`.
const Spotify = (() => {
  const ICON = {
    prev: '<svg viewBox="0 0 16 16"><path d="M3 2h2v12H3zM14 2v12L6 8z"/></svg>',
    play: '<svg viewBox="0 0 16 16"><path d="M4 2l10 6-10 6z"/></svg>',
    pause: '<svg viewBox="0 0 16 16"><path d="M3 2h3.5v12H3zM9.5 2H13v12H9.5z"/></svg>',
    next: '<svg viewBox="0 0 16 16"><path d="M11 2h2v12h-2zM2 2v12l8-6z"/></svg>',
    like: '<svg viewBox="0 0 16 16"><path d="M8 14S1 9.5 1 5.3A3.3 3.3 0 0 1 8 4a3.3 3.3 0 0 1 7 1.3C15 9.5 8 14 8 14z"/></svg>',
  };
  const fmt = s => { s = Math.max(0, Math.floor(s || 0)); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`; };
  let w = null, st = {}, timer = null, artUrl = "";

  function build(widget, send) {
    w = widget;
    w.bd.innerHTML = `
      <div class="sp-np"><div class="sp-art"><img alt=""></div>
        <div class="sp-meta"><div class="sp-title"></div><div class="sp-artist"></div><div class="sp-album"></div></div></div>
      <div class="sp-prog" data-c="scrub"><div class="bar"><b></b></div><div class="sp-times"><span class="sp-pos"></span><span class="sp-len"></span></div></div>
      <div class="sp-row">
        <div class="sp-ctl"><button data-c="prev" title="Previous">${ICON.prev}</button><button data-c="play" class="sp-play" title="Play or pause">${ICON.play}</button>
          <button data-c="next" title="Next">${ICON.next}</button><button data-c="like" class="sp-like" title="Like">${ICON.like}</button></div>
        <label class="sp-vol" data-c="volume" title="Volume"><span>VOL</span><input type="range" min="0" max="100" step="1"></label>
      </div>
      <div class="sp-queue"></div>`;
    const q = sel => w.bd.querySelector(sel);
    for (const b of w.bd.querySelectorAll(".sp-ctl button")) b.addEventListener("click", () => {
      const c = b.dataset.c;
      if (c === "play") { st.status = st.status === "playing" ? "paused" : "playing"; render(); }   // flip now; the core confirms
      send({ t: "press", widget: "spotify", control: c });
    });
    q(".sp-prog .bar").addEventListener("click", e => {
      const r = e.currentTarget.getBoundingClientRect(), s = (e.clientX - r.left) / r.width * (st.length_s || 0);
      st.position_s = s; st.updated = Date.now() / 1000; tick();
      send({ t: "press", widget: "spotify", control: "scrub", value: Math.round(s) });
    });
    q(".sp-vol input").addEventListener("change", e => send({ t: "press", widget: "spotify", control: "volume", value: +e.target.value }));
    q(".sp-art img").addEventListener("error", e => { e.target.style.visibility = "hidden"; });
  }

  function set(data) { st = data || {}; render(); }

  function render() {
    if (!w) return;
    const q = sel => w.bd.querySelector(sel);
    const running = st.status && st.status !== "not running";
    w.root.classList.toggle("sp-off", !running);
    if (w.tag && !w.tagWas) {
      w.tag.textContent = { playing: "NOW PLAYING", paused: "PAUSED", stopped: "STOPPED" }[st.status] || "NOT RUNNING";
    }
    q(".sp-title").textContent = running ? (st.title || "Nothing playing") : "Spotify isn't open";
    q(".sp-artist").textContent = running ? (st.artist || "") : "";
    q(".sp-album").textContent = running ? (st.album || "") : "";
    if ((st.art_url || "") !== artUrl) {
      artUrl = st.art_url || ""; const img = q(".sp-art img");
      img.style.visibility = artUrl ? "visible" : "hidden"; if (artUrl) img.src = artUrl;
    }
    q(".sp-play").innerHTML = st.status === "playing" ? ICON.pause : ICON.play;
    q(".sp-like").classList.toggle("liked", st.liked === true);
    const vol = q(".sp-vol input");
    if (document.activeElement !== vol && typeof st.volume === "number") vol.value = st.volume;
    q(".sp-queue").innerHTML = (st.queue || []).length
      ? `<div class="sp-qh">UP NEXT</div>` + st.queue.slice(0, 5).map(t => `<div class="sp-qi"><span></span><span></span></div>`).join("") : "";
    (st.queue || []).slice(0, 5).forEach((t, i) => {
      const row = w.bd.querySelectorAll(".sp-qi")[i];
      row.children[0].textContent = t.title || ""; row.children[1].textContent = t.artist || "";
    });
    tick();
    // Tick once a second only while playing: a 1 s repaint of one small bar is cheap.
    if (st.status === "playing" && !timer) timer = setInterval(tick, 1000);
    if (st.status !== "playing" && timer) { clearInterval(timer); timer = null; }
  }

  function tick() {
    if (!w) return;
    const len = st.length_s || 0;
    let pos = st.position_s || 0;
    if (st.status === "playing" && st.updated) pos += Date.now() / 1000 - st.updated;
    pos = Math.min(pos, len || pos);
    w.bd.querySelector(".sp-prog b").style.width = len ? `${(pos / len * 100).toFixed(2)}%` : "0%";
    w.bd.querySelector(".sp-pos").textContent = fmt(pos);
    w.bd.querySelector(".sp-len").textContent = len ? fmt(len) : "";
  }

  // She used a control: light it until her action finishes.
  function touch(control, on) {
    if (!w || !control) return;
    w.bd.querySelectorAll(`[data-c="${control}"]`).forEach(el => el.classList.toggle("on", on));
  }

  return { build, set, touch };
})();
