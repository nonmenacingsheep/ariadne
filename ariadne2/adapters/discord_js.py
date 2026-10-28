"""JavaScript the Discord adapter runs inside the discord.com tab.

Everything here is read-only except CLICK (the user panel's own mute/deafen
buttons) and the DM scripts, which navigate to a conversation (READ_DM goes
back by itself; SEND_* leave the restore to the adapter). Typing and Enter for
a send are CDP Input events sent by the adapter, not page script; the page
scripts never read tokens, storage or cookies and make no network calls.

Discord's class names are hashed ("voiceUser__a1b2c"), so selectors use
aria-labels, data-list-item-id, hrefs and class-name *prefixes* (`[class*=...]`),
and they all live in this one table so a Discord redesign is a one-place fix.
Labels assume Discord is set to English.
"""

import json

SELECTORS = r"""
const Q = {
  mute: 'button[aria-label="Mute"], button[aria-label="Unmute"]',
  deafen: 'button[aria-label="Deafen"], button[aria-label="Undeafen"]',
  disconnect: 'button[aria-label="Disconnect"]',
  voicePanel: '[class*="rtcConnectionStatus"], [class*="connection"]',
  voiceRow: '[class*="voiceUser"]',
  callTile: '[class*="voiceCallWrapper"] [class*="tile"]',
  channelItem: '[data-list-item-id^="channels___"]',
  home: '[data-list-item-id="guildsnav___home"]',
  guild: '[data-list-item-id^="guildsnav___"]',
  badge: '[class*="numberBadge"]',
  box: 'div[role="textbox"][data-slate-editor="true"]',
};
const dmHref = a => /^\/channels\/@me\/\d+$/.test(a.getAttribute('href') || '');
const dmLinks = () => [...document.querySelectorAll('a[href^="/channels/@me/"]')].filter(dmHref);
const num = el => { const m = ((el && el.textContent) || '').match(/\d+/); return m ? +m[0] : 0; };
const label = el => (el && el.getAttribute('aria-label')) || '';
const dmName = a => ((a.querySelector('[class*="name"]') || a).textContent || '').trim().split('\n')[0];
"""

# One snapshot of everything the widget shows.
PROBE = "(() => {" + SELECTORS + r"""
const mute = document.querySelector(Q.mute), deaf = document.querySelector(Q.deafen);
if (!mute) return {ready: false};
// A button is "on" if its label offers the opposite action, or (when the label
// stays put) its switch state says so.
const on = (b, word) => /^un/i.test(label(b)) || (new RegExp('^' + word, 'i').test(label(b)) && b.getAttribute('aria-checked') === 'true');
const out = {ready: true, muted: on(mute, 'mute'), deafened: on(deaf, 'deafen'), voice: null};

const dis = document.querySelector(Q.disconnect);
if (dis) {
  const panel = dis.closest(Q.voicePanel) || dis.parentElement.parentElement;
  let where = '';
  for (const el of panel.querySelectorAll('a, [class*="channel"], [class*="info"]')) {
    const t = (el.getAttribute('aria-label') || el.textContent || '').trim();
    if (t.includes(' / ')) { where = t; break; }
  }
  const cut = where.indexOf(' / ');
  const channel = cut < 0 ? where : where.slice(0, cut), server = cut < 0 ? '' : where.slice(cut + 3);
  // Voice rows sit under their channel in the list; fall back to every row on screen.
  let scope = document;
  for (const c of document.querySelectorAll(Q.channelItem)) {
    if (channel && (label(c) + ' ' + c.textContent).includes(channel)) { scope = c.closest('li') || c.parentElement.parentElement; break; }
  }
  let rows = [...scope.querySelectorAll(Q.voiceRow)];
  if (!rows.length) rows = [...document.querySelectorAll(Q.voiceRow)];
  if (!rows.length) rows = [...document.querySelectorAll(Q.callTile)];
  const seen = new Set(), members = [];
  for (const r of rows) {
    const name = ((r.querySelector('[class*="username"], [class*="participantName"]') || r).textContent || label(r)).trim();
    if (!name || seen.has(name)) continue;
    seen.add(name);
    members.push({name, speaking: !!r.querySelector('[class*="speaking"]') || /speaking/i.test(String(r.className)),
                  muted: !!r.querySelector('[aria-label*="Muted" i], [aria-label*="Deafened" i], [class*="iconMute"], [class*="iconDeafen"]')});
  }
  out.voice = {channel, server, members};
}

const badgeOf = el => { const w = el && (el.closest('[class*="listItem"]') || el.parentElement); const b = w && w.querySelector(Q.badge); return b ? num(b) : 0; };
const home = document.querySelector(Q.home);
out.homeBadge = home ? badgeOf(home) : null;
out.guilds = [...document.querySelectorAll(Q.guild)]
  .filter(e => /^guildsnav___\d+$/.test(e.getAttribute('data-list-item-id')))
  .map(e => ({name: e.getAttribute('data-dnd-name') || label(e) || '', count: badgeOf(e)}))
  .filter(g => g.count > 0);
// DM list is in sidebar order (most recent first) and only exists on the Home view.
out.dms = dmLinks().slice(0, 10).map(a => {
  const li = a.closest('li') || a.parentElement;
  const count = num(li.querySelector(Q.badge)) || (li.querySelector('[class*="unread"]') ? 1 : 0);
  return {name: dmName(a), count};
});
return out;
})()"""


def click(kind: str) -> str:
    """Click the user panel's mute or deafen button."""
    return "(() => {" + SELECTORS + f"""
const b = document.querySelector(Q.{kind});
if (!b) return {{ok: false}};
b.click();
return {{ok: true}};
}})()"""


# Shared by read and send: open a DM from the sidebar (Home first if needed).
# `strict` (send) refuses an ambiguous partial name instead of taking the first.
_OPEN = r"""
const sleep = ms => new Promise(r => setTimeout(r, ms));
const msgs = () => [...document.querySelectorAll('li[id^="chat-messages-"]')];
const back = async n => { if (n) { history.go(-n); await sleep(400); } };
async function openDm(want, strict) {
  let steps = 0;
  let links = dmLinks();
  if (!links.length) {                     // the DM list only exists on the Home view
    const home = document.querySelector(Q.home);
    if (home) { home.click(); steps++; for (let i = 0; i < 20 && !links.length; i++) { await sleep(150); links = dmLinks(); } }
  }
  const lc = a => dmName(a).toLowerCase();
  let pick = links.find(a => lc(a) === want);
  if (!pick) {
    const part = links.filter(a => lc(a).includes(want));
    if (part.length === 1 || (part.length > 1 && !strict)) pick = part[0];
    else if (part.length > 1) return {ok: false, steps, ambiguous: true, names: part.map(dmName).slice(0, 8)};
  }
  if (!pick) return {ok: false, steps, names: links.map(dmName).slice(0, 8)};
  const target = pick.getAttribute('href');
  if (location.pathname !== target) {
    pick.click(); steps++;
    for (let i = 0; i < 27 && !(location.pathname === target && msgs().length); i++) await sleep(150);
  }
  await sleep(500);                        // rows render a beat after the route changes
  return {ok: true, steps, name: dmName(pick), target};
}
"""


def read_dm(person: str) -> str:
    """Open a DM from the sidebar, read the rendered messages, go back."""
    return "(async () => {" + SELECTORS + _OPEN + r"""
const o = await openDm(%s.toLowerCase().trim(), false);
if (!o.ok) { await back(o.steps); return o; }
let author = '';
const out = msgs().map(li => {
  const u = li.querySelector('[id^="message-username-"]');
  if (u) author = u.textContent.trim();    // grouped messages omit the name
  const c = li.querySelector('[id^="message-content-"]');
  let text = c ? c.innerText.trim() : '';
  if (li.querySelector('[class*="attachment"], [class*="embed"], [class*="imageWrapper"]')) text += (text ? ' ' : '') + '[attachment or embed]';
  const t = li.querySelector('time');
  return {author, time: t ? t.getAttribute('datetime') || '' : '', text};
}).filter(m => m.text).slice(-15);
await back(o.steps);
return {ok: true, name: o.name, messages: out};
})()""" % json.dumps(person)


def send_open(person: str) -> str:
    """Step 1 of a send: open the DM and focus its empty message box. Stays there."""
    return "(async () => {" + SELECTORS + _OPEN + r"""
const o = await openDm(%s.toLowerCase().trim(), true);
if (!o.ok) { await back(o.steps); return o; }
const box = document.querySelector(Q.box);
const fail = async why => { await back(o.steps); return {ok: false, why, steps: 0}; };
if (!box || location.pathname !== o.target) return fail('box');
if ((box.innerText || '').replace(/\s/g, '')) return fail('draft');   // never clobber his unsent text
box.focus();
return {ok: true, steps: o.steps, name: o.name, target: o.target, before: msgs().map(li => li.id)};
})()""" % json.dumps(person)


def send_confirm(before: list, text: str) -> str:
    """Step 3: wait for a new message matching what was sent to show up."""
    return "(async () => {" + SELECTORS + _OPEN + r"""
const norm = s => (s || '').toLowerCase().replace(/[^a-z0-9]/g, '');   // markdown renders differently
const before = %s, want = norm(%s);
for (let i = 0; i < 30; i++) {
  await sleep(150);
  for (const li of msgs().filter(li => !before.includes(li.id))) {
    const c = li.querySelector('[id^="message-content-"]');
    const t = norm(c ? c.innerText : '');
    if (c && (!want || (t && (t === want || t.includes(want) || want.includes(t))))) return {ok: true};
  }
}
return {ok: false};
})()""" % (json.dumps(before), json.dumps(text))


def restore(steps: int) -> str:
    """Step 4: put his view back where it was."""
    return "(async () => {" + SELECTORS + _OPEN + f"await back({int(steps)}); return {{ok: true}}; }})()"
