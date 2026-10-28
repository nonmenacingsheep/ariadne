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
    shuffle: '<svg viewBox="0 0 16 16"><path d="M11 2l3 2.5L11 7V5.3H9.6L5.3 11.7H2V10h2.4l4.3-6.4H11zM2 4h3.3l1.4 2-1 1.5L4.4 5.7H2zm7.3 6H11V8.3l3 2.5-3 2.5v-1.7H8.5L7.2 9.6l1-1.5z"/></svg>',
    like: '<svg viewBox="0 0 16 16"><path d="M8 14S1 9.5 1 5.3A3.3 3.3 0 0 1 8 4a3.3 3.3 0 0 1 7 1.3C15 9.5 8 14 8 14z"/></svg>',
  };
  const fmt = s => { s = Math.max(0, Math.floor(s || 0)); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`; };
  let w = null, st = {}, timer = null, artUrl = "", volTimer = null, dragging = false, listKey = "", trackKey = "";

  function build(widget, send) {
    w = widget; listKey = ""; trackKey = ""; artUrl = "";
    w.bd.innerHTML = `
      <div class="sp-np"><div class="sp-art"><img alt=""></div>
        <div class="sp-meta"><div class="sp-title"></div><div class="sp-artist"></div><div class="sp-album"></div></div></div>
      <div class="sp-prog" data-c="scrub"><div class="sp-track"><b></b><i></i></div><div class="sp-times"><span class="sp-pos"></span><span class="sp-len"></span></div></div>
      <div class="sp-row">
        <div class="sp-ctl"><button data-c="prev" title="Previous">${ICON.prev}</button><button data-c="play" class="sp-play" title="Play or pause">${ICON.play}</button>
          <button data-c="next" title="Next">${ICON.next}</button><button data-c="like" class="sp-like" title="Like">${ICON.like}</button>
          <button data-c="shuffle" class="sp-shuffle" title="Shuffle">${ICON.shuffle}</button></div>
        <div class="sp-vol" data-c="volume" title="Volume (scroll to change)"><span class="sp-vl">VOL</span><div class="sp-vtrack"><b></b><i></i></div><span class="sp-vn"></span></div>
      </div>
      <div class="sp-list"></div>`;
    const q = sel => w.bd.querySelector(sel);
    for (const b of w.bd.querySelectorAll(".sp-ctl button")) b.addEventListener("click", () => {
      const c = b.dataset.c;
      if (c === "play") { st.status = st.status === "playing" ? "paused" : "playing"; render(); }   // flip now; the core confirms
      if (c === "shuffle") { st.shuffle = !st.shuffle; render(); }
      send({ t: "press", widget: "spotify", control: c });
    });
    q(".sp-track").addEventListener("click", e => {
      const r = e.currentTarget.getBoundingClientRect(), s = (e.clientX - r.left) / r.width * (st.length_s || 0);
      st.position_s = s; st.updated = Date.now() / 1000; tick();
      send({ t: "press", widget: "spotify", control: "scrub", value: Math.round(s) });
    });
    // Volume: drag or click the track, or scroll anywhere on the control.
    // Changes show at once; the press goes out once you pause, not per notch.
    const vol = q(".sp-vol"), vt = q(".sp-vtrack");
    const setVol = v => {
      st.volume = Math.max(0, Math.min(100, Math.round(v))); paintVol();
      clearTimeout(volTimer); volTimer = setTimeout(() => send({ t: "press", widget: "spotify", control: "volume", value: st.volume }), 160);
    };
    const fromX = x => { const r = vt.getBoundingClientRect(); return (x - r.left) / r.width * 100; };
    vt.addEventListener("pointerdown", e => {
      e.stopPropagation(); vt.setPointerCapture(e.pointerId); dragging = true; setVol(fromX(e.clientX));
      const move = ev => setVol(fromX(ev.clientX));
      const up = () => { dragging = false; vt.removeEventListener("pointermove", move); vt.removeEventListener("pointerup", up); };
      vt.addEventListener("pointermove", move); vt.addEventListener("pointerup", up);
    });
    vol.addEventListener("wheel", e => { e.preventDefault(); setVol((st.volume || 0) + (e.deltaY < 0 ? 4 : -4)); }, { passive: false });
    // One wheel notch moves the list one song, not a page.
    q(".sp-list").addEventListener("wheel", e => {
      e.preventDefault();
      const list = e.currentTarget, row = list.querySelector(".sp-qi");
      list.scrollBy({ top: Math.sign(e.deltaY) * (row ? row.offsetHeight + 3 : 20), behavior: "smooth" });
    }, { passive: false });
    // A song in the list: click to jump to it.
    q(".sp-list").addEventListener("click", e => {
      const row = e.target.closest(".sp-qi"); if (!row || !row.dataset.uri) return;
      row.classList.add("going");
      send({ t: "press", widget: "spotify", control: "jump", value: row.dataset.uri });
    });
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
    q(".sp-shuffle").classList.toggle("lit", st.shuffle === true);
    if (!dragging) paintVol();
    renderList();
    tick();
    // Tick once a second only while playing: a 1 s repaint of one small bar is cheap.
    if (st.status === "playing" && !timer) timer = setInterval(tick, 1000);
    if (st.status !== "playing" && timer) { clearInterval(timer); timer = null; }
  }

  function paintVol() {
    const v = typeof st.volume === "number" ? st.volume : 0;
    w.bd.querySelector(".sp-vtrack b").style.width = v + "%";
    w.bd.querySelector(".sp-vtrack i").style.left = v + "%";
    w.bd.querySelector(".sp-vn").textContent = String(v).padStart(2, " ");
  }

  // Earlier songs sit above "up next"; the list opens scrolled to "up next",
  // so scrolling up walks back through the playlist. Rebuilt only when the
  // songs change, so your scroll position survives the periodic updates.
  function renderList() {
    const box = w.bd.querySelector(".sp-list"), hist = st.history || [], queue = (st.queue || []).slice(0, 20);
    const key = JSON.stringify([hist.map(t => t.uri || t.title), queue.map(t => t.uri || t.title)]);
    if (key === listKey) return;
    listKey = key;
    const row = (t, past) => {
      const r = document.createElement("div");
      r.className = `sp-qi${past ? " past" : ""}${t.uri ? " jump" : ""}`; if (t.uri) r.dataset.uri = t.uri;
      r.innerHTML = "<span></span><span></span>"; r.children[0].textContent = t.title || ""; r.children[1].textContent = t.artist || "";
      return r;
    };
    box.innerHTML = "";
    if (hist.length) { const h = document.createElement("div"); h.className = "sp-qh past"; h.textContent = "EARLIER"; box.appendChild(h); hist.forEach(t => box.appendChild(row(t, true))); }
    const next = document.createElement("div"); next.className = "sp-qh"; next.textContent = queue.length ? "UP NEXT" : ""; box.appendChild(next);
    queue.forEach(t => box.appendChild(row(t, false)));
    // Room under the last song so "up next" can always scroll to the top,
    // however short the queue is.
    const pad = document.createElement("div"); pad.className = "sp-pad"; box.appendChild(pad);
    requestAnimationFrame(() => {
      const top = next.offsetTop - box.firstElementChild.offsetTop;
      // Only as much room as "up next" needs to reach the top, so scrolling
      // down stops at the last song instead of running into empty space.
      pad.style.height = Math.max(0, box.clientHeight - (box.scrollHeight - top)) + "px";
      const tk = `${st.title}|${st.artist}`;
      if (tk !== trackKey || !box.dataset.scrolled) { trackKey = tk; box.scrollTop = top; delete box.dataset.scrolled; }
    });
    box.onscroll = () => { box.dataset.scrolled = "1"; };
  }

  function tick() {
    if (!w) return;
    const len = st.length_s || 0;
    let pos = st.position_s || 0;
    if (st.status === "playing" && st.updated) pos += Date.now() / 1000 - st.updated;
    pos = Math.min(pos, len || pos);
    const f = len ? Math.max(0, Math.min(1, pos / len)) : 0, bar = w.bd.querySelector(".sp-track");
    bar.style.setProperty("--f", (f * 100).toFixed(2) + "%");
    bar.style.setProperty("--heat", heat(f));
    w.bd.querySelector(".sp-pos").textContent = fmt(pos);
    w.bd.querySelector(".sp-len").textContent = len ? fmt(len) : "";
  }

  // Dark red at the start of a song, warming to bright red, then almost
  // pink-white in the last stretch.
  function heat(f) {
    const stops = [[0, [90, 8, 20]], [.6, [200, 22, 42]], [.85, [255, 60, 80]], [1, [255, 170, 180]]];
    let i = 1; while (i < stops.length - 1 && f > stops[i][0]) i++;
    const [f0, a] = stops[i - 1], [f1, b] = stops[i], k = (f - f0) / ((f1 - f0) || 1);
    return `rgb(${a.map((v, j) => Math.round(v + (b[j] - v) * k)).join(",")})`;
  }

  // She used a control: light it until her action finishes.
  function touch(control, on) {
    if (!w || !control) return;
    w.bd.querySelectorAll(`[data-c="${control}"]`).forEach(el => el.classList.toggle("on", on));
  }

  return { build, set, touch };
})();
