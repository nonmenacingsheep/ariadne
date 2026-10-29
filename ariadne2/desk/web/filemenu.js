"use strict";
// Files: an icon per kind, and a right-click menu that does what Dolphin's
// does, plus "Ask Aries about it" and "Paste into chat". Every action is a
// press to the core's Dolphin adapter (his own click: no wire animation).

const FILE_ICON = (() => {
  const P = {
    folder: '<path d="M2 5h5l2 2h9v9H2z"/>',
    image: '<rect x="2.5" y="3.5" width="15" height="13"/><circle cx="7" cy="8" r="1.6"/><path d="M3 15l4.5-4.5 3 3 2.5-2.5 4.5 4.5"/>',
    audio: '<path d="M8 15V4l8-1.5V13"/><circle cx="6" cy="15" r="2"/><circle cx="14" cy="13" r="2"/>',
    video: '<rect x="2.5" y="4.5" width="11" height="11"/><path d="M13.5 8l4-2.5v9l-4-2.5z"/>',
    doc: '<path d="M5 2.5h7l3.5 3.5v11.5H5z"/><path d="M8 9h5M8 12h5M8 15h3"/>',
    archive: '<rect x="3.5" y="3" width="13" height="14"/><path d="M10 3v2M10 6v2M10 9v2"/><rect x="8.6" y="11.5" width="2.8" height="2.6"/>',
    code: '<path d="M7.5 6L3.5 10l4 4M12.5 6l4 4-4 4"/>',
    other: '<path d="M5 2.5h7l3.5 3.5v11.5H5z"/>',
  };
  const C = { folder: "#ffb347", image: "#6d8cff", audio: "#ff4d8a", video: "#b18cff", doc: "#e8dccb", archive: "#ffd36b", code: "#00e5ff", other: "#8a7f88" };
  return kind => {
    const k = P[kind] ? kind : "other", s = document.createElement("span");
    s.className = "ficon";
    s.innerHTML = `<svg viewBox="0 0 20 20" style="stroke:${C[k]}">${P[k]}</svg>`;
    return s;
  };
})();

const FileMenu = (() => {
  let box = null, send = () => {}, here = null;
  const press = (control, value) => send({ t: "press", widget: "dolphin", control, value });
  function init(sendFn) {
    send = sendFn;
    box = document.createElement("div"); box.className = "fmenu"; document.body.appendChild(box);
    addEventListener("pointerdown", e => { if (box.classList.contains("open") && !box.contains(e.target)) close(); }, true);
    addEventListener("keydown", e => { if (e.key === "Escape") close(); });
  }
  const item = (label, fn, cls = "") => {
    const b = document.createElement("button"); b.className = `fm-item ${cls}`; b.textContent = label;
    b.addEventListener("click", e => { e.stopPropagation(); fn(b); });
    return b;
  };
  const sep = () => { const d = document.createElement("div"); d.className = "fm-sep"; return d; };
  function open(x, y, f) {   // f = {path, name, kind, folder}
    here = f; box.innerHTML = "";
    const head = document.createElement("div"); head.className = "fm-head"; head.append(FILE_ICON(f.folder ? "folder" : f.kind)); 
    const nm = document.createElement("span"); nm.textContent = f.name; head.append(nm); box.append(head);
    box.append(item(f.folder ? "Open" : "Open", () => { press("open", { path: f.path }); close(); }));
    if (!f.folder) {
      const ow = item("Open with ▸", () => press("apps_for", { path: f.path }), "sub");
      ow.dataset.sub = "apps"; box.append(ow);
    }
    box.append(item("Show in Dolphin", () => { press("reveal", { path: f.path }); close(); }), sep());
    box.append(item("Copy", () => { press("copy", { path: f.path }); close(); }),
      item("Cut", () => { press("cut", { path: f.path }); close(); }));
    if (f.folder) box.append(item("Paste here", () => { press("paste", { folder: f.path }); close(); }),
      item("New folder…", b => ask(b, "New Folder", name => press("new_folder", { folder: f.path, name }))));
    box.append(item("Duplicate", () => { press("duplicate", { path: f.path }); close(); }),
      item("Rename…", b => ask(b, f.name, name => press("rename", { path: f.path, name }))),
      item("Compress", () => { press("compress", { path: f.path }); close(); }));
    if (f.kind === "archive") box.append(item("Extract here", () => { press("extract", { path: f.path }); close(); }));
    box.append(sep(), item("Copy path", () => { press("copy_path", { path: f.path }); close(); }),
      item("Properties", () => press("properties", { path: f.path })), sep());
    box.append(item("Ask Aries about it", () => {
      send({ t: "text", widget: "chat", text: "What's this?", attachments: [f.path] }); close();
    }, "aries"), item("Paste into chat", () => { send({ t: "attach", path: f.path }); close(); }, "aries"), sep());
    box.append(item("Move to trash", () => { press("trash", { path: f.path }); close(); }, "bad"));
    const r = { w: 230, h: Math.min(innerHeight - 20, 560) };
    Object.assign(box.style, { left: Math.min(x, innerWidth - r.w - 10) + "px", top: Math.min(y, innerHeight - r.h) + "px" });
    box.classList.add("open");
    reportRects();
  }
  // An inline text box in place of the item (rename, new folder).
  function ask(btn, value, done) {
    const i = document.createElement("input"); i.className = "fm-input"; i.value = value; i.spellcheck = false;
    btn.replaceWith(i); i.focus(); i.select();
    i.addEventListener("keydown", e => { if (e.key === "Enter" && i.value.trim()) { done(i.value.trim()); close(); } });
  }
  // Replies from the core: the apps that can open it, or its properties.
  function reply(msg) {
    if (!box.classList.contains("open") || !here) return;
    if (msg.apps) {
      box.querySelectorAll(".fm-app").forEach(e => e.remove());
      const anchor = box.querySelector('[data-sub="apps"]');
      for (const a of msg.apps.slice(0, 10).reverse())
        anchor.after(item(a.name, () => { press("open_with", { path: here.path, app: a.id }); close(); }, "fm-app"));
    }
    if (msg.info) {
      box.querySelectorAll(".fm-info").forEach(e => e.remove());
      const i = msg.info, d = document.createElement("div"); d.className = "fm-info";
      const size = i.size >= 1e9 ? `${(i.size / 1e9).toFixed(2)} GB` : i.size >= 1e6 ? `${(i.size / 1e6).toFixed(1)} MB` : `${Math.round((i.size || 0) / 1e3)} KB`;
      d.textContent = [`${size}${i.partial ? "+" : ""}${i.items != null ? ` · ${i.items} items` : ""}`, i.mime || i.kind,
        i.modified ? new Date(i.modified * 1000).toLocaleString() : "", i.permissions || ""].filter(Boolean).join("\n");
      box.append(d);
    }
  }
  function close() { if (box) box.classList.remove("open"); here = null; reportRects(); }
  const isOpen = () => box && box.classList.contains("open");
  const rect = () => box.getBoundingClientRect();
  return { init, open, reply, close, isOpen, rect };
})();
