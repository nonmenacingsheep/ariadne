"""The Spotify adapter: MPRIS for what's playing, the Web API for what MPRIS can't do.

State comes from D-Bus (signals, no polling storm): title, art, position,
volume. Writes go through the Web API first when it is authorised, because 1.x
measured Spotify's desktop client accepting MPRIS Play/Pause/Next and doing
nothing; MPRIS is the fallback, and the only way when there's no saved login.
Search-and-play, queue, like, playlists and shuffle/repeat need the Web API and
fail with a clear message without it.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import deque

from .base import Adapter, AdapterError, Verb
from .mpris import Mpris, MprisError
from .spotify_web import SpotifyWeb, WebError

log = logging.getLogger("ariadne2.adapters.spotify")

PERIOD = 5.0               # state is republished this often while playing
EXTRAS_PERIOD = 30.0       # shuffle/repeat/queue/liked refresh while playing
DEBOUNCE = 0.1             # a track change fires several signals at once
SETTLE_SCALE = 1.0         # tests set 0: commands needn't wait for the player to report
SEEK_SLACK = 1.5           # position further than this from expected = a seek
HISTORY = 10               # tracks shown before the current one
SCAN_CAP = 1000            # most context tracks read while looking for the current one
JUMP_PAUSE = 0.4           # between skips, so Spotify keeps up
KINDS = ("track", "artist", "album", "playlist", "liked")
STATUS = {"Playing": "playing", "Paused": "paused", "Stopped": "stopped"}
MPRIS_METHOD = {"play": "Play", "pause": "Pause", "next": "Next", "prev": "Previous"}
WEB_ROUTE = {"play": ("PUT", "/me/player/play"), "pause": ("PUT", "/me/player/pause"),
             "next": ("POST", "/me/player/next"), "prev": ("POST", "/me/player/previous")}


# ---- state mapping (pure, so it's testable without a bus) ----

def _artist(meta: dict) -> str:
    a = meta.get("xesam:artist")
    return ", ".join(a) if isinstance(a, (list, tuple)) else (a or "")


def art_https(url: str) -> str:
    """The widget wants https; old Spotify builds say http and open.spotify.com."""
    url = url or ""
    url = url.replace("open.spotify.com/image/", "i.scdn.co/image/")
    return "https://" + url[7:] if url.startswith("http://") else url


def track_id(meta: dict) -> str:
    """'/com/spotify/track/<id>' -> '<id>' ('' for ads and local files)."""
    raw = str(meta.get("mpris:trackid") or "")
    return raw.rsplit("/", 1)[-1] if "/com/spotify/track/" in raw else ""


def blank_state() -> dict:
    return {"status": "not running", "title": "", "artist": "", "album": "", "art_url": "",
            "position_s": 0.0, "length_s": 0.0, "updated": time.time(), "volume": 0,
            "liked": None, "shuffle": None, "repeat": None, "queue": [], "history": []}


def map_state(snap: dict, extras: dict | None, now: float) -> dict:
    """MPRIS snapshot (+ cached Web API extras) -> the widget's state shape."""
    state = blank_state()
    state["updated"] = now
    if not snap.get("running"):
        return state
    meta = snap.get("metadata") or {}
    extras = extras or {}
    state.update(
        status=STATUS.get(snap.get("status"), "stopped"),
        title=str(meta.get("xesam:title") or ""), artist=_artist(meta),
        album=str(meta.get("xesam:album") or ""),
        art_url=art_https(str(meta.get("mpris:artUrl") or "")),
        position_s=round((snap.get("position_us") or 0) / 1e6, 2),
        length_s=round(float(meta.get("mpris:length") or 0) / 1e6, 2),
        volume=max(0, min(100, round(float(snap.get("volume") or 0) * 100))),
        shuffle=extras.get("shuffle"), repeat=extras.get("repeat"))
    # liked, queue and history belong to one track; stale after a skip, so don't show them.
    if extras.get("track_id") == track_id(meta) and track_id(meta):
        state["liked"] = extras.get("liked")
        state["queue"] = list(extras.get("queue") or [])[:5]
        state["history"] = list(extras.get("history") or [])[:HISTORY]
    return state


def _row(t: dict) -> dict:
    """A Web API track object -> the widget's row. `uri` only when Spotify gave one."""
    row = {"title": t.get("name", ""),
           "artist": ", ".join(a.get("name", "") for a in t.get("artists") or [])}
    if t.get("uri"):
        row["uri"] = t["uri"]
    return row


def _changed(old: dict, new: dict) -> bool:
    quiet = ("position_s", "updated")
    if {k: v for k, v in old.items() if k not in quiet} != {k: v for k, v in new.items() if k not in quiet}:
        return True
    expected = old["position_s"] + ((new["updated"] - old["updated"]) if old["status"] == "playing" else 0)
    return abs(new["position_s"] - expected) > SEEK_SLACK


def _clock(s: float) -> str:
    return f"{int(s) // 60}:{int(s) % 60:02d}"


class SpotifyAdapter(Adapter):
    name = "spotify"
    events = ("track_changed", "paused", "playing")

    def __init__(self, publish, mpris=None, web=None) -> None:
        super().__init__(publish)
        self.mpris = mpris or Mpris()
        self.web = web or SpotifyWeb()
        self._state = blank_state()
        self._snap: dict = {"running": False}
        self._extras: dict = {}
        self._extras_at = 0.0
        self._hist_key: tuple | None = None       # (track id, context uri) the history is for
        self._history: list[dict] = []
        self._pl_path = "/playlists/{}/items"     # Spotify renamed /tracks; fallback below
        self._ident: tuple | None = None          # (title, artist, status) last seen
        self._wake = asyncio.Event()
        self._tasks: set[asyncio.Task] = set()
        self._main: asyncio.Task | None = None
        self._aloop: asyncio.AbstractEventLoop | None = None
        self.controls = {"next": "next", "prev": "prev", "like": "like",
                         "volume": "volume", "scrub": "seek"}
        s = lambda **p: {"type": "object", "properties": p}          # noqa: E731
        self.verbs = [
            Verb("play", "Play music. With a query, search Spotify and play the best match "
                 "(kind picks what to search; 'liked' plays his Liked Songs). With no query, resume.",
                 s(query={"type": "string"}, kind={"type": "string", "enum": list(KINDS)}),
                 self._play, "play"),
            Verb("pause", "Pause the music.", s(), self._pause, "play"),
            Verb("next", "Skip to the next track.", s(), self._next, "next"),
            Verb("prev", "Go back to the previous track.", s(), self._prev, "prev"),
            Verb("volume", "Set Spotify's volume, 0 to 100.",
                 {"type": "object", "properties": {"level": {"type": "integer", "minimum": 0,
                                                              "maximum": 100}},
                  "required": ["level"]}, self._volume, "volume"),
            Verb("queue", "Add the best match for a song search to the queue, to play next.",
                 {"type": "object", "properties": {"query": {"type": "string"}},
                  "required": ["query"]}, self._queue),
            Verb("like", "Like the current track (Liked Songs); remove=true unlikes it.",
                 s(remove={"type": "boolean"}), self._like, "like"),
            Verb("playlist", "Play one of his playlists by name.",
                 {"type": "object", "properties": {"name": {"type": "string"}},
                  "required": ["name"]}, self._playlist),
            Verb("seek", "Jump to a position in the current track, in seconds.",
                 {"type": "object", "properties": {"seconds": {"type": "number", "minimum": 0}},
                  "required": ["seconds"]}, self._seek, "scrub"),
            Verb("jump", "Skip to a song in the up-next list or the recent history, by title.",
                 {"type": "object", "properties": {"title": {"type": "string"}},
                  "required": ["title"]}, self._jump_title),
        ]

    # ---- lifecycle ----

    async def start(self) -> None:
        self._aloop = asyncio.get_running_loop()
        try:
            await asyncio.to_thread(self.mpris.start, self._poke)
        except MprisError as e:
            log.warning("Spotify state unavailable: %s", e)
        self._main = asyncio.create_task(self._loop())
        await self.refresh(force=True)

    async def stop(self) -> None:
        tasks = [t for t in (self._main, *self._tasks) if t]
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await asyncio.to_thread(self.mpris.stop)

    def _poke(self) -> None:
        """Called from the GLib thread when D-Bus says something changed."""
        if self._aloop:
            self._aloop.call_soon_threadsafe(self._wake.set)

    def state(self) -> dict:
        return self._state

    def _spawn(self, coro) -> None:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    # ---- keeping state fresh ----

    async def _loop(self) -> None:
        while True:
            try:
                await asyncio.wait_for(self._wake.wait(), PERIOD)
                tick = False
                await asyncio.sleep(DEBOUNCE)
                self._wake.clear()
            except asyncio.TimeoutError:
                tick = True
            try:
                await self.refresh(force=tick and self._state["status"] == "playing")
            except Exception:
                log.exception("spotify refresh failed")

    async def refresh(self, force: bool = False) -> None:
        try:
            snap = await asyncio.to_thread(self.mpris.snapshot)
        except Exception as e:
            log.debug("mpris snapshot failed: %s", e)
            snap = {"running": False}
        self._snap = snap
        new = map_state(snap, self._extras, time.time())
        ident = (new["title"], new["artist"], new["status"])
        old_ident, self._ident = self._ident, ident
        track_moved = old_ident is not None and old_ident[:2] != ident[:2] and bool(new["title"])
        if old_ident is not None:
            self._events(old_ident, ident, track_moved)
        due = new["status"] == "playing" and time.monotonic() - self._extras_at > EXTRAS_PERIOD
        if (track_moved or due or self._extras_at == 0.0) and self.web.available() \
                and new["status"] != "not running":
            self._extras_at = time.monotonic()
            self._spawn(self._refresh_extras())
        if force or _changed(self._state, new):
            self._state = new
            await self.publish_state()

    def _events(self, old: tuple, new: tuple, track_moved: bool) -> None:
        if track_moved and new[2] != "stopped":
            self.emit("track_changed", title=new[0], artist=new[1])
        if old[2] != new[2]:
            if new[2] == "playing":
                self.emit("playing")
            elif new[2] == "paused" and old[2] == "playing":
                self.emit("paused")

    async def _refresh_extras(self) -> None:
        """shuffle/repeat, the queue and liked-ness: three calls, each allowed to fail
        alone (Spotify has retired endpoints before) and leave its field null."""
        tid = track_id(self._snap.get("metadata") or {})
        extras: dict = {"track_id": tid, "liked": None, "shuffle": None, "repeat": None,
                        "queue": [], "history": []}
        ctx = None
        try:
            pl = await self._web("GET", "/me/player")
            extras["shuffle"] = pl.get("shuffle_state")
            extras["repeat"] = pl.get("repeat_state")
            ctx = pl.get("context") or {}
        except AdapterError as e:
            log.debug("player state: %s", e)
        if tid and ctx is not None:               # without the context the history would be a guess
            key = (tid, ctx.get("uri") or "")
            if key != self._hist_key:             # only a new track or context costs calls
                try:
                    self._history, self._hist_key = await self._history_for(tid, ctx), key
                except AdapterError as e:         # not cached: the next refresh retries
                    log.debug("history: %s", e)
                    self._history, self._hist_key = [], None
            extras["history"] = self._history
        try:
            q = await self._web("GET", "/me/player/queue")
            extras["queue"] = [_row(t) for t in (q.get("queue") or [])[:5]]
        except AdapterError as e:
            log.debug("queue: %s", e)
        if tid:
            try:
                got = await self._library("GET", tid)
                extras["liked"] = bool(got[0]) if isinstance(got, list) and got else None
            except AdapterError as e:
                log.debug("liked: %s", e)
        self._extras = extras
        await self.refresh()

    # ---- history: what came before the current track ----

    async def _context_rows(self, ctx: dict):
        """The context's tracks in order, page by page (a playlist or an album)."""
        cid, playlist = ctx["uri"].rsplit(":", 1)[-1], ctx.get("type") == "playlist"
        size, seen = (100 if playlist else 50), 0
        while seen < SCAN_CAP:
            params = {"limit": size, "offset": seen}
            if playlist:
                try:
                    page = await self._web("GET", self._pl_path.format(cid), params=params)
                except AdapterError:              # the other name for the same endpoint
                    other = "/playlists/{}/tracks" if "items" in self._pl_path else "/playlists/{}/items"
                    page = await self._web("GET", other.format(cid), params=params)
                    self._pl_path = other
            else:
                page = await self._web("GET", f"/albums/{cid}/tracks", params=params)
            items = page.get("items") or []
            for it in items:
                # Playlist entries wrap the track ("track", or "item" on the newer API).
                t = (it.get("track") or it.get("item")) if playlist and it else it
                if t and t.get("uri"):
                    yield _row(t)
            seen += len(items)
            if not items or not page.get("next"):
                return

    async def _history_for(self, tid: str, ctx: dict) -> list[dict]:
        cur = f"spotify:track:{tid}"
        if ctx.get("type") in ("playlist", "album") and ctx.get("uri"):
            window: deque = deque(maxlen=HISTORY)
            try:
                async for row in self._context_rows(ctx):
                    if row["uri"] == cur:
                        return list(window)
                    window.append(row)
            except AdapterError as e:             # e.g. a playlist he can't read: use recents
                log.debug("context scan: %s", e)
        recent = await self._web("GET", "/me/player/recently-played", params={"limit": HISTORY})
        rows = [_row(i["track"]) for i in recent.get("items") or [] if i and i.get("track")]
        return [r for r in reversed(rows) if r.get("uri") and r["uri"] != cur]

    async def _settle(self, delay: float = 0.5) -> None:
        """Players take a moment to report what a command did."""
        await asyncio.sleep(delay * SETTLE_SCALE)
        await self.refresh()

    # ---- Web API plumbing ----

    async def _web(self, method: str, path: str, body=None, params=None):
        if not self.web.available():
            raise AdapterError("Spotify's Web API isn't authorised (no saved login), so I can't "
                               "do that. Play, pause, skip and volume still work.")
        try:
            return await asyncio.to_thread(self.web.request, method, path, body, params)
        except WebError as e:
            raise AdapterError(str(e)) from e

    async def _library(self, method: str, tid: str):
        """Saved-track calls. Spotify's 2026 migration moved them to /me/library (by URI)
        and 403s the old /me/tracks/contains; try the new one, keep the old as fallback."""
        uri = f"spotify:track:{tid}"
        new = {"GET": "/me/library/contains"}.get(method, "/me/library")
        try:
            return await self._web(method, new, params={"uris": uri})
        except AdapterError:
            old = "/me/tracks/contains" if method == "GET" else "/me/tracks"
            return await self._web(method, old, params={"ids": tid})

    async def _mpris(self, fn, *args) -> None:
        try:
            await asyncio.to_thread(fn, *args)
        except MprisError as e:
            raise AdapterError(str(e)) from e

    def _now_line(self) -> str:
        s = self._state
        return f"Now playing: {s['title']} — {s['artist']}." if s["title"] else "Nothing is playing."

    # ---- transport ----

    async def _transport(self, action: str) -> None:
        """Web API first (1.x found MPRIS writes ignored by the desktop client), MPRIS second."""
        failure: AdapterError | None = None
        if self.web.available():
            try:
                await self._web(*WEB_ROUTE[action])
                return
            except AdapterError as e:
                failure = e
        if self._state["status"] == "not running" and failure is None:
            raise AdapterError("Spotify isn't running.")
        try:
            await self._mpris(self.mpris.command, MPRIS_METHOD[action])
        except AdapterError as e:
            raise failure or e

    async def _pause(self) -> str:
        await self._transport("pause")
        await self._settle(0.3)
        return "Paused."

    async def _next(self) -> str:
        await self._transport("next")
        await self._settle()
        return "Skipped. " + self._now_line()

    async def _prev(self) -> str:
        await self._transport("prev")
        await self._settle()
        return "Went back. " + self._now_line()

    async def _resume(self) -> str:
        await self._transport("play")
        await self._settle()
        return "Playing. " + self._now_line()

    async def _volume(self, level) -> str:
        try:
            level = max(0, min(100, int(round(float(level)))))
        except (TypeError, ValueError):
            raise AdapterError("volume needs a number from 0 to 100")
        try:
            await self._web("PUT", "/me/player/volume", params={"volume_percent": level})
        except AdapterError:
            await self._mpris(self.mpris.set_volume, level / 100)
        await self._settle(0.3)
        return f"Volume set to {level}."

    async def _seek(self, seconds) -> str:
        try:
            seconds = max(0.0, float(seconds))
        except (TypeError, ValueError):
            raise AdapterError("seek needs a number of seconds")
        try:
            await self._web("PUT", "/me/player/seek", params={"position_ms": int(seconds * 1000)})
        except AdapterError:
            tid = (self._snap.get("metadata") or {}).get("mpris:trackid")
            if not tid:
                raise
            await self._mpris(self.mpris.set_position, tid, seconds)
        await self._settle(0.3)
        return f"Jumped to {_clock(seconds)}."

    # ---- search, play, queue ----

    async def _search(self, query: str, kind: str) -> dict:
        found = await self._web("GET", "/search", params={"q": query, "type": kind, "limit": 1})
        items = [i for i in (found.get(kind + "s") or {}).get("items") or [] if i]
        if not items:
            raise AdapterError(f"nothing on Spotify matches {query!r}")
        return items[0]

    async def _device(self) -> str:
        """Somewhere to play: the active device, else the desktop app, else any."""
        devices = [d for d in (await self._web("GET", "/me/player/devices")).get("devices") or [] if d]
        for pick in (lambda d: d.get("is_active"),
                     lambda d: (d.get("type") or "").lower() == "computer", lambda d: True):
            for d in devices:
                if pick(d) and d.get("id"):
                    return d["id"]
        raise AdapterError("Spotify has no device to play on. Open the Spotify app, then ask again.")

    async def _start(self, body: dict) -> None:
        await self._web("PUT", "/me/player/play", body, {"device_id": await self._device()})

    @staticmethod
    def _describe(item: dict) -> str:
        who = ", ".join(a.get("name", "") for a in item.get("artists", []))
        return f"{item.get('name', '?')} — {who}" if who else item.get("name", "?")

    async def _play(self, query: str | None = None, kind: str | None = None) -> str:
        kind = (kind or "track").lower()
        if kind not in KINDS:
            raise AdapterError(f"kind must be one of {', '.join(KINDS)}")
        if kind == "liked":
            page = await self._web("GET", "/me/tracks", params={"limit": 50})
            uris = [i["track"]["uri"] for i in page.get("items") or [] if i.get("track")]
            if not uris:
                raise AdapterError("there are no liked songs on that account")
            await self._start({"uris": uris})
            await self._settle(0.8)
            return f"Playing his Liked Songs. {self._now_line()}"
        if not (query or "").strip():
            return await self._resume()
        item = await self._search(query.strip(), kind)
        await self._start({"uris": [item["uri"]]} if kind == "track" else {"context_uri": item["uri"]})
        await self._settle(0.8)
        return f"Playing {kind} {self._describe(item)}."

    async def _queue(self, query: str) -> str:
        if not (query or "").strip():
            raise AdapterError("say which song to queue")
        item = await self._search(query.strip(), "track")
        await self._web("POST", "/me/player/queue", params={"uri": item["uri"]})
        self._extras_at = 0.0               # let the widget's queue catch up
        await self._settle(0.5)
        return f"Queued {self._describe(item)}."

    async def _playlist(self, name: str) -> str:
        want = (name or "").strip().lower()
        if not want:
            raise AdapterError("say which playlist")
        mine = (await self._web("GET", "/me/playlists", params={"limit": 50})).get("items") or []
        mine = [p for p in mine if p]
        pick = next((p for p in mine if p.get("name", "").lower() == want), None) \
            or next((p for p in mine if p.get("name", "").lower().startswith(want)), None) \
            or next((p for p in mine if want in p.get("name", "").lower()), None) \
            or await self._search(want, "playlist")
        await self._start({"context_uri": pick["uri"]})
        await self._settle(0.8)
        return f"Playing playlist {pick.get('name', want)}."

    async def _in_context(self, ctx: dict, uri: str) -> bool:
        async for row in self._context_rows(ctx):
            if row["uri"] == uri:
                return True
        return False

    async def _jump(self, uri) -> str:
        """Skip to a track from the history or the queue. Checks Spotify live, not the
        cached lists, so a click on a list that has since moved still lands right."""
        if not isinstance(uri, str) or not uri.startswith("spotify:"):
            raise AdapterError("jump needs a track uri")
        ctx = (await self._web("GET", "/me/player")).get("context") or {}
        if ctx.get("type") in ("playlist", "album") and ctx.get("uri") \
                and await self._in_context(ctx, uri):
            await self._start({"context_uri": ctx["uri"], "offset": {"uri": uri}})
        else:
            queue = [t.get("uri") for t in (await self._web("GET", "/me/player/queue")).get("queue") or [] if t]
            if uri in queue:
                for n in range(queue.index(uri) + 1):
                    if n:
                        await asyncio.sleep(JUMP_PAUSE * SETTLE_SCALE)
                    await self._transport("next")
            else:
                await self._start({"uris": [uri]})
        self._extras_at = 0.0                     # new track: history and queue must follow
        await self._settle(0.8)
        return "Jumped. " + self._now_line()

    async def _jump_title(self, title: str) -> str:
        want = (title or "").strip().lower()
        if not want:
            raise AdapterError("say which song to jump to")
        # Up next first (that is what "skip to" usually means), then recent history, nearest first.
        rows = [r for r in (*self._state["queue"], *reversed(self._state["history"])) if r.get("uri")]
        pick = next((r for r in rows if r["title"].lower() == want), None) \
            or next((r for r in rows if want in r["title"].lower()), None)
        if not pick:
            raise AdapterError(f"{title!r} isn't in the up-next list or the recent history")
        return await self._jump(pick["uri"])

    async def _like(self, remove: bool = False) -> str:
        tid = track_id(self._snap.get("metadata") or {})
        if not tid:
            raise AdapterError("nothing is playing that can be liked")
        await self._library("DELETE" if remove else "PUT", tid)
        self._extras = {**self._extras, "track_id": tid, "liked": not remove}
        await self.refresh()
        what = f"{self._state['title']} — {self._state['artist']}"
        return f"Removed from Liked Songs: {what}." if remove else f"Liked: {what}."

    # ---- his own clicks in the widget ----

    async def press(self, control: str, value=None):
        if control == "play":                       # the widget's one button toggles
            verb = "pause" if self._state["status"] == "playing" else "play"
            return await self.run(verb, {}, announce=False)
        if control == "jump":                       # his click on a row: value is the track uri
            return await self._jump(value)
        return await super().press(control, value)

    def press_args(self, control: str, value) -> dict:
        if control == "like":
            return {"remove": self._state["liked"] is True}
        if control in ("volume", "scrub"):
            if value is None:
                raise AdapterError(f"{control} needs a value")
            return {"level": value} if control == "volume" else {"seconds": value}
        return {}
