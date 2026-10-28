"""The JavaScript the browser adapter runs inside pages.

Kept apart from browser.py so the adapter reads as logic. Each snippet is an
expression that evaluates to a plain object (CDP returns it by value).
Same-origin frames are walked because plenty of players live in one; players in
cross-origin iframes are separate CDP targets and the adapter probes those too.
"""

# Shared prologue: every document we can reach, and the media worth acting on.
# Muted looping videos (hover previews, decorative backgrounds) and tiny videos
# (ad slots) are not "what he's watching".
_PRELUDE = r"""
const docs = [document];
const walk = (win, depth) => {
  if (depth > 3) return;
  let frames; try { frames = win.frames; } catch (e) { return; }
  for (let i = 0; i < (frames.length || 0); i++) {
    try { const d = frames[i].document; if (d) { docs.push(d); walk(frames[i], depth + 1); } }
    catch (e) {}
  }
};
walk(window, 0);
const area = v => (v.clientWidth || 0) * (v.clientHeight || 0);
const media = () => {
  const out = [];
  for (const d of docs) { try { out.push(...d.querySelectorAll('video,audio')); } catch (e) {} }
  return out.filter(v => !(v.muted && v.loop) && !(v.tagName === 'VIDEO' && area(v) < 4000))
            .filter(v => v.readyState > 0 || v.currentSrc || v.src)
            .sort((a, b) => ((!b.paused && !b.ended) - (!a.paused && !a.ended))
                            || (area(b) - area(a)) || ((b.duration || 0) - (a.duration || 0)));
};
const visible = el => el && el.offsetParent !== null;
const clickFirst = (sels) => {
  for (const d of docs) for (const s of sels) {
    let el = null; try { el = d.querySelector(s); } catch (e) {}
    if (visible(el)) { el.click(); return s; }
  }
  return null;
};
"""

# What's on this page: is it the visible tab, and what media does it have.
PROBE = "(() => {" + _PRELUDE + r"""
const v = media()[0];
return {
  visible: document.visibilityState === 'visible',
  media: !v ? null : {
    playing: !v.paused && !v.ended, ended: !!v.ended,
    position: v.currentTime || 0,
    length: isFinite(v.duration) ? v.duration : 0,
    muted: !!v.muted, volume: v.volume
  }
};
})()"""

# Flip play/pause on the best media element. Runs with a user gesture, or the
# page's autoplay policy silently ignores play().
TOGGLE = "(() => {" + _PRELUDE + r"""
const v = media()[0];
if (!v) return {ok: false};
if (v.paused || v.ended) { v.muted = false; const p = v.play(); if (p && p.catch) p.catch(() => {}); return {ok: true, now: 'playing'}; }
v.pause();
return {ok: true, now: 'paused'};
})()"""

# Site-aware where there's a known control; otherwise any button or link that
# plainly says "next (episode)". The known selectors are the sites' own player
# buttons; the generic fallback is a guess and says so by returning its label.
NEXT = "(() => {" + _PRELUDE + r"""
const SITES = [
  [/(^|\.)youtube\.com$/, ['.ytp-next-button']],
  [/(^|\.)netflix\.com$/, ['[data-uia="next-episode-seamless-button"]',
                            '[data-uia="next-episode-seamless-button-draining"]',
                            '[data-uia="control-next"]']],
  [/(^|\.)crunchyroll\.com$/, ['[data-t="next-episode"]']],
  [/(^|\.)primevideo\.com$|(^|\.)amazon\.[a-z.]+$/, ['.atvwebplayersdk-nextupcard-button']],
];
for (const [re, sels] of SITES) {
  if (re.test(location.hostname)) { const via = clickFirst(sels); if (via) return {ok: true, via}; }
}
const rx = /^(play )?next( episode| ep\.?| video| chapter)?\s*[›»>→]*$/i;
for (const d of docs) {
  let hit = null;
  try { hit = d.querySelector('a[rel=next]'); } catch (e) {}
  if (!visible(hit)) {
    hit = null;
    for (const el of d.querySelectorAll('a,button,[role=button]')) {
      const label = (el.getAttribute('aria-label') || el.title || el.innerText || '').trim();
      if (label.length <= 30 && rx.test(label) && visible(el)) { hit = el; break; }
    }
  }
  if (hit) { const label = (hit.innerText || hit.getAttribute('aria-label') || 'next').trim().slice(0, 30);
             hit.click(); return {ok: true, via: 'link: ' + label}; }
}
return {ok: false};
})()"""

# Fullscreen toggle: leave if already in it; else the site's own button (the
# only thing that makes YouTube resize its player), else the player element.
FULLSCREEN = "(() => {" + _PRELUDE + r"""
if (document.fullscreenElement) { document.exitFullscreen(); return {ok: true, now: 'left'}; }
const via = clickFirst(['.ytp-fullscreen-button', '[data-plyr=fullscreen]', '.vjs-fullscreen-control',
  '.jw-icon-fullscreen', "button[aria-label*='ull screen' i]", "button[title*='ull screen' i]",
  "button[aria-label*='ullscreen' i]", "button[title*='ullscreen' i]"]);
if (via) return {ok: true, now: 'entered', via};
const v = media()[0];
if (!v) return {ok: false};
let el = v, up = v.parentElement, hops = 0;
while (up && hops < 4) { if (/player|video|jw|vjs|plyr|art-/i.test(String(up.className || ''))) { el = up; break; } up = up.parentElement; hops++; }
const go = el.requestFullscreen || el.webkitRequestFullscreen;
if (!go) return {ok: false};
try { const p = go.call(el); if (p && p.catch) p.catch(() => {}); } catch (e) { return {ok: false}; }
return {ok: true, now: 'entered', via: 'player'};
})()"""

# The page's main text. Prefers <main>/article when it is most of the page,
# drops nav and chrome, and includes same-origin frames (1.x lesson: YouTube's
# sidebar otherwise comes back before the video).
READ = r"""
(() => {
  const drop = ['script','style','noscript','svg','nav','footer','header','aside',
                '[role=navigation]','[role=complementary]','[role=banner]'];
  const textOf = doc => {
    try {
      if (!doc.body) return '';
      let root = doc.body;
      const whole = (doc.body.innerText || '').length || 1;
      for (const sel of ['main', '[role=main]', '#primary', '#content', 'article']) {
        let el = null; try { el = doc.querySelector(sel); } catch (e) {}
        if (el && ((el.innerText || '').length / whole) >= 0.35) { root = el; break; }
      }
      const clone = root.cloneNode(true);
      drop.forEach(t => { try { clone.querySelectorAll(t).forEach(e => e.remove()); } catch (e) {} });
      return (clone.innerText || '').trim();
    } catch (e) { return ''; }
  };
  const parts = [textOf(document)];
  const walk = (win, depth) => {
    if (depth > 2) return;
    let frames; try { frames = win.frames; } catch (e) { return; }
    for (let i = 0; i < (frames.length || 0); i++) {
      try {
        const text = textOf(frames[i].document);
        if (text) parts.push(text);
        walk(frames[i], depth + 1);
      } catch (e) {}
    }
  };
  walk(window, 0);
  return parts.filter(Boolean).join('\n\n').replace(/\n{3,}/g, '\n\n').trim();
})()
"""
