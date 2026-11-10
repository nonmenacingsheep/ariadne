"use strict";
// The Money widget (adapters/bank.py): each account up top (checking, savings,
// cards) and what's left in checking after the bills, then three sections:
// subscriptions and bills coming up, each with checking's balance after it
// (red below zero), and the expenses that have already gone through.
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
    for (const a of d.accounts) {
      const t = el("div", "bk-big k-" + a.kind + (a.balance < 0 ? " bad" : ""));
      t.title = a.name + (a.bank ? ` (${a.bank})` : "");
      t.append(el("span", "bk-l", a.kind.toUpperCase() + (a.id === d.main ? " · BILLS" : "")), el("span", "bk-v", money(a.available ?? a.balance)));
      top.append(t);
    }
    const safe = el("div", "bk-big k-safe" + (d.safe < 0 ? " bad" : ""));
    safe.title = "checking, less the subscriptions and bills due " + (d.payday ? "before payday" : "in the next 30 days");
    safe.append(el("span", "bk-l", d.payday ? `SAFE TILL ${day(d.payday).toUpperCase()}` : "AFTER 30 DAYS"), el("span", "bk-v", money(d.safe)));
    top.append(safe);
    box.append(top);
    const list = el("div", "bk-list");
    const section = (title, sum, rows, row, none) => {
      const h = el("div", "bk-h"); h.append(el("span", "", title), el("span", "bk-hs", sum || ""));
      list.append(h);
      for (const u of rows) list.append(row(u));
      if (!rows.length) list.append(el("div", "bk-off", none));
    };
    const ahead = u => {
      const r = el("div", "bk-row" + (u.income ? " in" : "") + (u.after < 0 ? " bad" : ""));
      r.append(el("span", "bk-d", day(u.date)), el("span", "bk-n", u.name), el("span", "bk-a", (u.income ? "+" : "") + money(u.amount)),
               el("span", "bk-after", money(u.after)));
      return r;
    };
    section("SUBSCRIPTIONS", d.subs_month ? `${money(d.subs_month)}/mo` : "", d.subs || [], ahead, "None found in your history yet.");
    if ((d.bills || []).length) section("BILLS & PAYDAYS", "", d.bills, ahead, "");
    section("EXPENSES · LAST 7 DAYS", d.spent_week ? money(-d.spent_week) : "", d.spent || [], s => {
      const r = el("div", "bk-row went");
      r.append(el("span", "bk-d", day(s.date)), el("span", "bk-n", s.name + (s.pending ? " (pending)" : "")), el("span", "bk-a", money(s.amount)),
               el("span", "bk-acct k-" + s.account, s.account === "checking" ? "CHK" : s.account === "savings" ? "SAV" : s.account.slice(0, 4).toUpperCase()));
      return r;
    }, "Nothing has gone out this week.");
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
