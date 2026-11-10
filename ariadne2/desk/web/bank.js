"use strict";
// The Money widget (adapters/bank.py): cash on hand and what's safe to spend
// before payday up top, his accounts under it, then the next bills and
// paydays with the balance after each: one that takes it below zero is red.
// Read-only, like the bank side: the only button fetches fresh numbers.
const Bank = (() => {
  let w = null, send = null;
  const money = v => (v < 0 ? "-$" : "$") + Math.abs(v || 0).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const day = iso => {
    const d = new Date(iso + "T00:00:00"), t = new Date(); t.setHours(0, 0, 0, 0);
    const n = Math.round((d - t) / 86400000);
    return n === 0 ? "today" : n === 1 ? "tomorrow" : d.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });
  };
  const ago = ts => {
    if (!ts) return "never";
    const s = Date.now() / 1000 - ts;
    return s < 3600 ? `${Math.max(1, Math.round(s / 60))}m ago` : s < 86400 ? `${Math.round(s / 3600)}h ago` : `${Math.round(s / 86400)}d ago`;
  };

  function build(widget, sender) {
    w = widget; send = sender;
    w.bd.innerHTML = `<div class="bk"></div>`;
  }

  function set(d) {
    if (!w) return;
    const box = w.bd.querySelector(".bk"); box.innerHTML = "";
    if (!d.connected) {
      box.append(el("div", "bk-off", "Not connected. Make a setup token at bridge.simplefin.org and paste it in Settings > Models > Bank (SimpleFIN)."));
      return;
    }
    if (!(d.accounts || []).length) {
      box.append(el("div", "bk-off", d.note ? `SimpleFIN: ${d.note}` : "Connected. The first numbers are on their way."));
      return;
    }
    const top = el("div", "bk-top");
    const cash = el("div", "bk-big"); cash.append(el("span", "bk-l", "CASH"), el("span", "bk-v", money(d.cash)));
    const safe = el("div", "bk-big" + (d.safe < 0 ? " bad" : "")); safe.append(el("span", "bk-l", d.payday ? `SAFE TILL ${day(d.payday).toUpperCase()}` : "AFTER BILLS"), el("span", "bk-v", money(d.safe)));
    top.append(cash, safe);
    box.append(top);
    const accts = el("div", "bk-accts");
    for (const a of d.accounts) {
      const r = el("div", "bk-acct"); r.append(el("span", "bk-an", a.name), el("span", "bk-av" + (a.balance < 0 ? " neg" : ""), money(a.balance)));
      accts.append(r);
    }
    box.append(accts);
    const list = el("div", "bk-list");
    for (const u of d.upcoming || []) {
      const r = el("div", "bk-row" + (u.income ? " in" : "") + (u.after < 0 ? " bad" : ""));
      r.append(el("span", "bk-d", day(u.date)), el("span", "bk-n", u.name), el("span", "bk-a", (u.income ? "+" : "") + money(u.amount)),
               el("span", "bk-after", money(u.after)));
      list.append(r);
    }
    if (!(d.upcoming || []).length) list.append(el("div", "bk-off", "No bills or paydays found in the next 30 days yet."));
    box.append(list);
    const foot = el("div", "bk-foot");
    foot.append(el("span", "", `synced ${ago(d.synced)}` + (d.note ? ` · ${d.note}` : "")));
    const b = el("button", "fe-btn", "Refresh"); b.dataset.c = "refresh";
    b.onclick = () => send({ t: "press", widget: "bank", control: "refresh" });
    foot.append(b);
    box.append(foot);
    if (w.tag && !w.tagWas) w.tag.textContent = d.low < 0 ? `LOW ${day(d.low_on).toUpperCase()}` : "";
    if (w.tag && !w.tagWas) w.tag.className = d.low < 0 ? "tag bad" : "tag";
  }

  return { build, set, touch: (c, on) => touchIn(w, c, on) };
})();
