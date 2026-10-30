"use strict";
// The Claude widget: his own Claude Code, the real CLI, in a slab
// (core/claude_live.py runs `claude` and streams it here). A session picker,
// the folder it works in, permission mode and model on top; the conversation
// with tool calls as cards; Allow / Deny when Claude asks; a composer below.
// Everything Claude or a tool says is set as text, never as HTML.

const Claude = (() => {
  let w, send, st = { state: "idle" }, sessions = [], folders = [];
  let msgs, composer, input, goBtn, banner, picker, live = null, tools = {};
  const MODE_LABEL = { default: "Ask first", acceptEdits: "Accept edits", plan: "Plan" };
  const MODEL_LABEL = { "": "Default model", opus: "Opus", sonnet: "Sonnet", haiku: "Haiku" };
  const base = p => (p || "").replace(/\/+$/, "").split("/").pop() || p;
  const near = () => msgs.scrollHeight - msgs.scrollTop - msgs.clientHeight < 60;
  const keep = stick => { if (stick) msgs.scrollTop = msgs.scrollHeight; };
  const say = m => send({ t: "cc_do", ...m });

  // ---------------------------------------------------------------- markdown
  // Enough of it to read code answers: fences, inline code, bold, headings, lists.
  function inline(text, into) {
    const re = /(`[^`\n]+`|\*\*[^*\n]+\*\*)/g;
    let at = 0, m;
    while ((m = re.exec(text))) {
      if (m.index > at) into.append(document.createTextNode(text.slice(at, m.index)));
      const tok = m[0];
      into.append(tok[0] === "`" ? el("code", "cc-ic", tok.slice(1, -1)) : el("b", null, tok.slice(2, -2)));
      at = m.index + tok.length;
    }
    if (at < text.length) into.append(document.createTextNode(text.slice(at)));
  }
  function md(text) {
    const box = el("div", "cc-md");
    const lines = String(text).split("\n");
    let list = null, para = null;
    const flush = () => { para = null; list = null; };
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      const fence = line.match(/^\s*```(\S*)/);
      if (fence) {
        const code = [];
        for (i++; i < lines.length && !/^\s*```/.test(lines[i]); i++) code.push(lines[i]);
        const pre = el("pre", "cc-code"); pre.textContent = code.join("\n");
        if (fence[1]) pre.dataset.lang = fence[1];
        box.append(pre); flush(); continue;
      }
      if (!line.trim()) { flush(); continue; }
      const h = line.match(/^(#{1,4})\s+(.*)/);
      if (h) { const e = el("div", "cc-h"); inline(h[2], e); box.append(e); flush(); continue; }
      const li = line.match(/^\s*(?:[-*•]|\d+[.)])\s+(.*)/);
      if (li) {
        if (!list) { list = el("ul", "cc-ul"); box.append(list); para = null; }
        const e = el("li"); inline(li[1], e); list.append(e); continue;
      }
      if (!para) { para = el("p"); box.append(para); list = null; } else para.append(document.createElement("br"));
      inline(line, para);
    }
    return box;
  }

  // ------------------------------------------------------------------- build
  function build(widget, s) {
    w = widget; send = s;
    w.bd.innerHTML = "";
    w.bd.classList.add("cc");
    const bar = el("div", "cc-bar");
    const sess = el("button", "cc-sess"); sess.title = "Sessions";
    sess.addEventListener("click", e => { e.stopPropagation(); togglePicker(); });
    const folder = el("span", "cc-folder");
    const mode = el("select", "sp-select cc-mode"), model = el("select", "sp-select cc-model");
    for (const [v, l] of Object.entries(MODE_LABEL)) mode.append(new Option(l, v));
    for (const [v, l] of Object.entries(MODEL_LABEL)) model.append(new Option(l, v));
    mode.title = "Ask first: Claude asks before editing or running anything.\nAccept edits: file edits go through, commands still ask.\nPlan: read and plan only.";
    mode.addEventListener("change", () => say({ op: "mode", mode: mode.value }));
    model.addEventListener("change", () => say({ op: "model", model: model.value }));
    const cost = el("span", "cc-cost");
    bar.append(sess, folder, el("span", "cc-gap"), mode, model, cost);

    banner = el("div", "cc-banner");
    msgs = el("div", "cc-msgs");
    stepScrollSmooth(msgs);
    picker = el("div", "cc-picker");
    composer = el("div", "cc-composer");
    input = el("textarea", "cc-in"); input.rows = 1; input.spellcheck = false;
    input.placeholder = "Ask Claude Code…  (Enter sends, Shift+Enter for a new line)";
    input.addEventListener("input", grow);
    input.addEventListener("keydown", e => {
      if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); go(); }
      if (e.key === "Escape" && st.state === "working") say({ op: "stop" });
    });
    goBtn = el("button", "cc-go", "Send");
    goBtn.addEventListener("click", e => { e.stopPropagation(); st.state === "working" || st.state === "asking" ? say({ op: "stop" }) : go(); });
    composer.append(input, goBtn);
    w.bd.append(bar, banner, msgs, picker, composer);
    empty();
    say({ op: "hello" });
  }
  function grow() { input.style.height = "auto"; input.style.height = Math.min(input.scrollHeight + 2, 140) + "px"; }
  function stepScrollSmooth(list) {
    list.addEventListener("wheel", e => { e.preventDefault(); list.scrollBy({ top: e.deltaY * 0.6 }); }, { passive: false });
  }
  function go() {
    const text = input.value.trim();
    if (!text) return;
    if (st.state === "signed_out") { banner.classList.add("shake"); setTimeout(() => banner.classList.remove("shake"), 400); }
    say({ op: "send", text });
    input.value = ""; grow();
  }
  function empty() {
    if (msgs.childElementCount) return;
    const e = el("div", "cc-empty");
    e.append(el("div", "cc-empty-t", "CLAUDE CODE"),
      el("div", null, "A fresh session in the folder above. Pick an older one from the session menu to carry on with it."));
    msgs.append(e);
  }
  function clearEmpty() { msgs.querySelector(".cc-empty")?.remove(); }

  // ----------------------------------------------------------- session picker
  function togglePicker(open = !picker.classList.contains("open")) {
    picker.classList.toggle("open", open);
    if (!open) return;
    picker.innerHTML = "";
    const head = el("div", "cc-pk-h", "NEW SESSION IN");
    const row = el("div", "cc-pk-new");
    const pick = el("select", "sp-select");
    for (const f of folders) pick.append(new Option(base(f), f));
    pick.value = folders.includes(st.cwd) ? st.cwd : folders[0] || "";
    const start = el("button", "cc-pk-go", "Start");
    start.addEventListener("click", e => { e.stopPropagation(); say({ op: "new", cwd: pick.value }); togglePicker(false); });
    row.append(pick, start);
    picker.append(head, row, el("div", "cc-pk-h", "RECENT SESSIONS"));
    const list = el("div", "cc-pk-list");
    if (!sessions.length) list.append(el("div", "cc-pk-none", "nothing in the last six hours"));
    for (const x of sessions) {
      const r = el("button", `cc-pk-row ${x.state || ""}${x.id === st.session ? " on" : ""}`);
      r.append(el("span", `cl-dot ${x.state || ""}`), el("span", "cc-pk-proj", x.project || ""),
        el("span", "cc-pk-title", x.title || x.id.slice(0, 8)), el("span", "cc-pk-when", x.mine ? "HERS" : ""));
      r.addEventListener("click", e => { e.stopPropagation(); say({ op: "resume", session: x.id }); togglePicker(false); });
      list.append(r);
    }
    picker.append(list);
  }
  addEventListener("pointerdown", e => { if (picker && picker.classList.contains("open") && !picker.contains(e.target) && !e.target.closest(".cc-sess")) togglePicker(false); }, true);

  // ------------------------------------------------------------------- items
  function speakerRow(who, cls) { const s = el("div", `cc-who ${cls}`, who); msgs.append(s); return s; }
  function addUser(text) {
    clearEmpty(); live = null;
    speakerRow("YOU", "you");
    const b = el("div", "cc-user"); b.textContent = text; msgs.append(b);
  }
  function claudeBlock() {
    const last = msgs.lastElementChild;
    if (!last || !last.classList.contains("cc-turn")) {
      speakerRow("CLAUDE", "claude");
      msgs.append(el("div", "cc-turn"));
    }
    return msgs.lastElementChild;
  }
  function delta(text) {
    const stick = near(); clearEmpty();
    if (!live) { live = el("div", "cc-md cc-stream"); claudeBlock().append(live); }
    live.textContent += text; thinking(false); keep(stick);
  }
  function finalText(text) {
    const stick = near(); clearEmpty();
    const done = md(text);
    if (live) live.replaceWith(done); else claudeBlock().append(done);
    live = null; keep(stick);
  }
  function tool(m) {
    const stick = near(); clearEmpty(); live = null;
    const card = el("div", "cc-tool run");
    const head = el("button", "cc-tool-h");
    head.append(el("span", "cc-tool-dot"), el("span", "cc-tool-l", m.label || m.name));
    const body = el("div", "cc-tool-b");
    if (m.input) body.append(el("pre", "cc-pre", m.input));
    head.addEventListener("click", e => { e.stopPropagation(); card.classList.toggle("open"); });
    card.append(head, body);
    claudeBlock().append(card);
    if (m.id) tools[m.id] = card;
    keep(stick);
  }
  function toolDone(m) {
    const card = tools[m.id]; if (!card) return;
    card.classList.remove("run"); card.classList.add(m.error ? "err" : "ok");
    if (m.preview) card.querySelector(".cc-tool-b").append(el("pre", `cc-pre out${m.error ? " err" : ""}`, m.preview));
  }
  function ask(m) {
    clearEmpty(); live = null;
    const card = el("div", "cc-ask"); card.dataset.req = m.req;
    card.append(el("div", "cc-ask-t", "CLAUDE WANTS TO"), el("div", "cc-ask-l", m.label || m.tool));
    if (m.input) card.append(el("pre", "cc-pre", m.input));
    const row = el("div", "cc-ask-row");
    const b = (label, cls, allow, always) => {
      const x = el("button", `cc-ask-b ${cls}`, label);
      x.addEventListener("click", e => { e.stopPropagation(); say({ op: "answer", req: m.req, allow, always }); card.classList.add("answered", allow ? "yes" : "no"); });
      return x;
    };
    row.append(b("Allow", "yes", true, false));
    if (m.always) row.append(b("Allow always", "yes2", true, true));
    row.append(b("Deny", "no", false, false));
    card.append(row);
    claudeBlock().append(card);
    requestAnimationFrame(() => { msgs.scrollTop = msgs.scrollHeight; });   // it needs him: always in view
  }
  function thinking(on) {
    let t = msgs.querySelector(".cc-thinking");
    if (on && !t) { t = el("div", "cc-thinking", "thinking"); msgs.append(t); keep(near()); }
    if (!on && t) t.remove();
  }
  function done(m) {
    thinking(false); live = null;
    if (m.error) { const e = el("div", "cc-err", m.error); msgs.append(e); }
    msgs.querySelectorAll(".cc-tool.run").forEach(c => c.classList.remove("run"));
    keep(true);
  }
  function history(items) {
    for (const it of items) {
      if (it.kind === "user") addUser(it.text);
      else if (it.kind === "text") finalText(it.text);
      else if (it.kind === "tool") tool(it);
      else if (it.kind === "tool_done") toolDone(it);
    }
    msgs.querySelectorAll(".cc-tool.run").forEach(c => c.classList.remove("run"));
    keep(true);
  }

  // -------------------------------------------------------------- the status
  function status(m) {
    st = m;
    const bar = w.bd.querySelector(".cc-bar");
    bar.querySelector(".cc-sess").textContent = (m.title || (m.session ? m.session.slice(0, 8) : "New session")) + "  ▾";
    const f = bar.querySelector(".cc-folder"); f.textContent = base(m.cwd); f.title = m.cwd;
    bar.querySelector(".cc-mode").value = m.mode;
    bar.querySelector(".cc-model").value = m.model || "";
    bar.querySelector(".cc-cost").textContent = m.cost ? `$${m.cost.toFixed(2)}` : "";
    const busy = m.state === "working" || m.state === "asking";
    goBtn.textContent = busy ? "Stop" : "Send";
    goBtn.classList.toggle("stop", busy);
    w.bd.classList.toggle("busy", busy);
    if (m.state === "working" && !live && !msgs.querySelector(".cc-thinking")) thinking(true);
    if (!busy) thinking(false);
    banner.textContent = "";
    banner.className = "cc-banner";
    if (m.state === "signed_out") {
      banner.classList.add("show", "bad");
      banner.append(el("b", null, "Claude Code is signed out. "),
        document.createTextNode("Open a terminal, run "), el("code", "cc-ic", "claude"),
        document.createTextNode(", type "), el("code", "cc-ic", "/login"), document.createTextNode(", then send again."));
    } else if (m.state === "asking") {
      banner.classList.add("show", "ask"); banner.textContent = "Claude is waiting for your answer below.";
    }
    tag();
  }
  function tag() {
    if (!w || !w.tag || w.tagWas) return;
    const hers = sessions.filter(x => x.mine && x.state === "working").length;
    w.tag.textContent = st.state === "asking" ? "NEEDS YOU" : st.state === "working" ? "WORKING"
      : st.state === "signed_out" ? "SIGNED OUT" : hers ? `${hers} OF HER HANDS WORKING` : "";
  }

  function message(m) {
    if (!w) return;
    switch (m.ev) {
      case "status": status(m); break;
      case "folders": folders = m.items || []; break;
      case "clear": msgs.innerHTML = ""; tools = {}; live = null; empty(); break;
      case "history": history(m.items || []); break;
      case "user": addUser(m.text); thinking(true); break;
      case "delta": delta(m.text); break;
      case "text": finalText(m.text); break;
      case "thinking": if (!live) thinking(true); break;
      case "tool": thinking(false); tool(m); break;
      case "tool_done": toolDone(m); break;
      case "ask": thinking(false); ask(m); break;
      case "asked": msgs.querySelector(`.cc-ask[data-req="${CSS.escape(m.req)}"]`)?.classList.add("answered"); break;
      case "done": done(m); break;
      case "error": { const e = el("div", "cc-err", m.text); msgs.append(e); keep(true); break; }
    }
  }
  // The adapter's view of every session (hers and his), for the picker and the tag.
  function set(data) { sessions = (data && data.sessions) || []; tag(); }
  function hello() { if (send) say({ op: "hello" }); }
  return { build, set, message, hello, touch: (c, on) => touchIn(w, c, on) };
})();
