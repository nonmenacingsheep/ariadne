"""The Steam adapter: local files and the process list for state, steam:// for commands.

State is read from what Steam leaves on disk (appmanifests, localconfig.vdf) and from
the process list; there is no Steam API to call. Commands are handed to the host's
Steam with `xdg-open steam://...`. In the container /usr/local/bin/xdg-open is
distrobox's wrapper, which runs the host's xdg-open through host-spawn, which is the
same route 1.x used. Host processes are visible in the container's /proc, so closing a
game is a plain signal, with no host-exec at all.
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import signal
import time
from collections import deque

from .base import Adapter, AdapterError, Verb
from .steam_files import (BUSY_BITS, INSTALLED, PAUSED, UPDATE_REQUIRED, UPDATE_STARTED,
                          SteamFiles, is_tool, match_game, scan_processes)

log = logging.getLogger("ariadne2.adapters.steam")

FAST = 4.0                 # poll period while a download or a game is going
SLOW = 15.0                # and when nothing is
HOT = 90.0                 # after launch/close/install, stay fast this long
RECENT = 8
RATE_WINDOW = 60.0         # the manifest is rewritten in bursts, so average over a minute
RATE_STALE = 45.0          # no progress for this long while "downloading" = rate 0
CLOSE_WAIT = 10.0          # seconds a game gets to exit after SIGTERM
LIB_ROWS = 25
RANK = {"downloading": 0, "updating": 1, "queued": 2, "paused": 3}


def download_state(m: dict) -> str | None:
    """What an appmanifest says about a transfer, or None when it isn't transferring.

    StateFlags 6 (installed, update required) is just an update that is available or
    scheduled, not in progress, so it is left out. 1026/1030 are Steam's "started"
    states: with nothing downloaded yet they are a queue entry."""
    f = m["flags"]
    busy = f & BUSY_BITS
    if f & PAUSED and (busy or f & (UPDATE_REQUIRED | UPDATE_STARTED) or not f & INSTALLED):
        return "paused"
    if not (busy or f & UPDATE_STARTED or (f & UPDATE_REQUIRED and not f & INSTALLED)):
        return None
    if not busy and m["bytes_done"] == 0:
        return "queued"
    return "updating" if f & INSTALLED else "downloading"


def _ago(stamp: int, now: float) -> str:
    if not stamp:
        return "never played"
    days = int((now - stamp) / 86400)
    return "today" if days <= 0 else f"{days}d ago" if days < 60 else f"{days // 30}mo ago"


def blank_state() -> dict:
    return {"status": "not running", "playing": None, "recent": [], "downloads": []}


async def _xdg_open(url: str) -> None:
    if not shutil.which("xdg-open"):
        raise AdapterError("xdg-open isn't installed, so I can't hand this to Steam")
    try:
        proc = await asyncio.create_subprocess_exec(
            "xdg-open", url, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL, start_new_session=True)
    except OSError as e:
        raise AdapterError(f"couldn't reach Steam: {e.strerror}")
    try:
        code = await asyncio.wait_for(proc.wait(), 5)
    except asyncio.TimeoutError:
        return                      # still starting Steam; that's fine
    if code:
        raise AdapterError(f"couldn't reach Steam (xdg-open exited {code})")


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        with open(f"/proc/{pid}/stat") as f:        # a zombie is already gone
            return f.read().rsplit(")", 1)[1].split()[0] != "Z"
    except (OSError, IndexError):
        return False


def _send(pid: int, sig: int) -> None:
    try:
        os.kill(pid, sig)
    except ProcessLookupError:
        pass
    except PermissionError as e:
        raise AdapterError(f"I'm not allowed to signal that game ({e.strerror})")


class SteamAdapter(Adapter):
    name = "steam"
    events = ("game_started", "game_closed", "download_done")

    def __init__(self, publish, files=None, proc="/proc", opener=None, send=None, alive=None) -> None:
        super().__init__(publish)
        self.files = files or SteamFiles()
        self.proc = proc
        self._open = opener or _xdg_open
        self._send = send or _send
        self._alive = alive or _pid_alive
        self.now = time.time                       # tests replace these two
        self.mono = time.monotonic
        self._state = blank_state()
        self._scan_cache: dict = {}
        self._baseline = True                      # first scan sets state, emits nothing
        self._prev_playing: dict | None = None
        self._prev_dl: dict[int, str] = {}
        self._samples: dict[int, deque] = {}       # appid -> (time, bytes_done) on each change
        self._hot_until = 0.0
        self._wake = asyncio.Event()
        self._main: asyncio.Task | None = None
        self.settle = 1.0                          # tests set 0
        self.controls = {"launch": "launch", "close": "close"}
        game = {"type": "object", "properties": {"game": {"type": "string"}}, "required": ["game"]}
        self.verbs = [
            Verb("launch", "Start an installed Steam game by name (fuzzy: 'elden', 'helldivers'). "
                 "Steam launches it; the game takes a while to appear.", game, self._launch, "launch"),
            Verb("close", "Close the running Steam game. This kills the game process, so any unsaved "
                 "progress is lost: confirm with him first unless he asked you to close it. With no "
                 "game given, closes the one that's running.",
                 {"type": "object", "properties": {"game": {"type": "string"}}}, self._close, "close"),
            Verb("install", "Install a game he owns that isn't installed (by name, or appid). Steam "
                 "shows its own install dialog for him to confirm.", game, self._install, "install"),
            Verb("library", "Look up his Steam library as text: with a query, matching games (installed "
                 "or just owned) with appid, hours played and last played; without, the installed "
                 "games, most recently played first.",
                 {"type": "object", "properties": {"query": {"type": "string"}}}, self._library),
        ]

    # ---- lifecycle ----

    async def start(self) -> None:
        self._main = asyncio.create_task(self._loop())
        await self.refresh()

    async def stop(self) -> None:
        if self._main:
            self._main.cancel()
            await asyncio.gather(self._main, return_exceptions=True)

    def state(self) -> dict:
        return self._state

    def _poke(self, hot: bool = True) -> None:
        if hot:
            self._hot_until = time.monotonic() + HOT
        self._wake.set()

    # ---- keeping state fresh ----

    def _period(self) -> float:
        s = self._state
        busy = s["playing"] or any(d["state"] != "paused" for d in s["downloads"])
        return FAST if busy or time.monotonic() < self._hot_until else SLOW

    async def _loop(self) -> None:
        while True:
            try:
                await asyncio.wait_for(self._wake.wait(), self._period())
                await asyncio.sleep(0.2)
            except asyncio.TimeoutError:
                pass
            self._wake.clear()
            try:
                await self.refresh()
            except Exception:
                log.exception("steam refresh failed")

    def _scan(self) -> dict:
        return {"man": self.files.manifests(), "play": self.files.playtime(),
                "names": self.files.names(), "procs": scan_processes(self.proc)}

    async def _fresh(self) -> dict:
        try:
            self._scan_cache = await asyncio.to_thread(self._scan)
        except Exception as e:
            log.debug("steam scan failed: %s", e)
        return self._scan_cache

    async def refresh(self) -> None:
        scan = await self._fresh()
        if not scan:
            return
        new = self._build(scan)
        self._events(scan, new)
        if new != self._state:
            self._state = new
            await self.publish_state()

    def _name(self, scan: dict, appid: int) -> str:
        m = scan["man"].get(appid)
        return (m and m["name"]) or scan["names"].get(appid) or f"app {appid}"

    def _build(self, scan: dict) -> dict:
        man, play, procs = scan["man"], scan["play"], scan["procs"]
        playing = None
        if procs["games"]:
            g = procs["games"][-1]                      # newest, if two are somehow up
            playing = {"appid": g["appid"], "name": self._name(scan, g["appid"]),
                       "since": int(g["started"])}
        rows = {}
        for appid in {*man, *play}:
            m, p = man.get(appid), play.get(appid, {})
            name = (m and m["name"]) or scan["names"].get(appid) or ""
            last = max(p.get("last_played", 0), (m or {}).get("last_played", 0))
            if playing and appid == playing["appid"]:
                last = max(last, playing["since"])      # Steam writes it back only later
            if last and name and not is_tool(name):
                rows[appid] = {"appid": appid, "name": name, "last_played": last,
                               "hours": round(p.get("minutes", 0) / 60, 1),
                               "installed": bool(m and m["installed"])}
        if playing and playing["appid"] not in rows and not is_tool(playing["name"]) \
                and not playing["name"].startswith("app "):
            rows[playing["appid"]] = {"appid": playing["appid"], "name": playing["name"],
                                      "last_played": playing["since"], "hours": 0.0, "installed": True}
        recent = sorted(rows.values(), key=lambda r: (-r["last_played"], r["name"]))[:RECENT]
        return {"status": "running" if procs["steam"] else "not running", "playing": playing,
                "recent": recent, "downloads": self._downloads(man)}

    def _downloads(self, man: dict) -> list[dict]:
        out = []
        now = self.mono()
        for appid, m in man.items():
            st = download_state(m)
            if st is None:
                self._samples.pop(appid, None)
                continue
            done, total = m["bytes_done"], m["bytes_total"]
            if total and done >= total and m["to_stage"] and m["staged"] < m["to_stage"]:
                done, total = m["staged"], m["to_stage"]      # files downloaded, now being written
                st = "updating" if m["installed"] else "downloading"
            out.append({"appid": appid, "name": m["name"],
                        "progress": round(min(1.0, done / total), 4) if total else 0.0,
                        "bytes_done": done, "bytes_total": total,
                        "rate_bps": self._rate(appid, done, st, now), "state": st})
        out.sort(key=lambda d: (RANK[d["state"]], d["name"]))
        return out

    def _rate(self, appid: int, done: int, st: str, now: float) -> float | None:
        """Bytes per second from the change in bytes_done across the last minute."""
        s = self._samples.setdefault(appid, deque())
        if s and done < s[-1][1]:
            s.clear()                                  # a restart or re-verify: start over
        if not s or done != s[-1][1]:
            s.append((now, done))
        while len(s) > 2 and now - s[1][0] > RATE_WINDOW:
            s.popleft()
        if st in ("paused", "queued") or len(s) < 2:
            return None
        if now - s[-1][0] > RATE_STALE:
            return 0.0
        (t0, d0), (t1, d1) = s[0], s[-1]
        return round((d1 - d0) / (t1 - t0), 1) if t1 > t0 else None

    def _events(self, scan: dict, new: dict) -> None:
        playing, dl = new["playing"], {d["appid"]: d["name"] for d in new["downloads"]}
        if not self._baseline:
            old = self._prev_playing
            if old and (not playing or playing["appid"] != old["appid"]):
                self.emit("game_closed", name=old["name"], appid=old["appid"])
            if playing and (not old or old["appid"] != playing["appid"]):
                self.emit("game_started", name=playing["name"], appid=playing["appid"])
            for appid, name in self._prev_dl.items():
                m = scan["man"].get(appid)
                # Gone from the list AND installed with no transfer flags: it finished
                # (a cancelled or removed one has no manifest, or isn't installed).
                if appid not in dl and m and m["installed"] and download_state(m) is None:
                    self.emit("download_done", name=m["name"] or name, appid=appid)
        self._baseline = False
        self._prev_playing, self._prev_dl = playing, dl

    # ---- finding games ----

    def _known(self, scan: dict) -> list[dict]:
        """Every game we know of: installed, plus owned ones seen in his play history."""
        out = []
        for appid in {*scan["man"], *scan["play"]}:
            m, p = scan["man"].get(appid), scan["play"].get(appid, {})
            name = (m and m["name"]) or scan["names"].get(appid) or ""
            if not name or is_tool(name):
                continue
            out.append({"appid": appid, "name": name, "installed": bool(m and m["installed"]),
                        "minutes": p.get("minutes", 0),
                        "last_played": max(p.get("last_played", 0), (m or {}).get("last_played", 0))})
        return out

    def _pick(self, rows: list[dict], query, what: str) -> dict:
        q = str(query or "").strip()
        if not q:
            raise AdapterError("say which game")
        hits, _ = match_game(q, rows)
        if not hits:
            raise AdapterError(f"I can't find {what} matching {q!r}")
        if len(hits) > 1:
            raise AdapterError(f"{q!r} could be " + ", ".join(h["name"] for h in hits[:5])
                               + "; which one?")
        return hits[0]

    # ---- verbs ----

    async def _launch(self, game: str) -> str:
        scan = await self._fresh()
        if not self.files.available() and not scan.get("man"):
            raise AdapterError("I can't find Steam's library on this machine")
        known = self._known(scan)
        try:
            pick = self._pick([g for g in known if g["installed"]], game, "an installed game")
        except AdapterError as first:
            near, _ = match_game(str(game or ""), [g for g in known if not g["installed"]])
            if near and len(near) == 1:
                raise AdapterError(f"{near[0]['name']} is owned but not installed; "
                                   "I can install it if he wants") from None
            raise first
        if any(g["appid"] == pick["appid"] for g in scan["procs"]["games"]):
            return f"{pick['name']} is already running."
        await self._open(f"steam://rungameid/{pick['appid']}")
        self._poke()
        extra = "" if scan["procs"]["steam"] else " Steam wasn't running, so it has to start first."
        return f"Told Steam to launch {pick['name']}. It takes a moment.{extra}"

    async def _close(self, game: str | None = None) -> str:
        scan = await self._fresh()
        running = [{"appid": g["appid"], "name": self._name(scan, g["appid"]), **g}
                   for g in scan["procs"]["games"]]
        if not running:
            raise AdapterError("no Steam game is running")
        want = str(game or "").strip()
        if want:
            pick = self._pick(running, want, "a running game")
        elif len(running) == 1:
            pick = running[0]
        else:
            raise AdapterError("more than one game is running: " + ", ".join(r["name"] for r in running))
        for pid in reversed(pick["pids"]):             # children first, the reaper last
            self._send(pid, signal.SIGTERM)
        deadline = time.monotonic() + CLOSE_WAIT * self.settle
        while any(self._alive(p) for p in pick["pids"]):
            if time.monotonic() >= deadline:
                raise AdapterError(f"{pick['name']} didn't exit; it may be saving or stuck")
            await asyncio.sleep(0.25 * self.settle)
        self._poke()
        await self.refresh()
        return f"Closed {pick['name']}."

    async def _install(self, game: str) -> str:
        scan = await self._fresh()
        q = str(game or "").strip()
        if not q:
            raise AdapterError("say which game")
        known = self._known(scan)
        hits, _ = match_game(q, known)
        if q.isdigit() and not hits:
            appid, name = int(q), f"app {q}"            # not in his history: trust the id
        else:
            pick = self._pick(known, q, "a game in his library")
            appid, name = pick["appid"], pick["name"]
            m = scan["man"].get(appid)
            if m and download_state(m):
                return f"{name} is already {download_state(m)}."
            if m and m["installed"]:
                return f"{name} is already installed."
        await self._open(f"steam://install/{appid}")
        self._poke()
        return f"Asked Steam to install {name}. Steam shows an install dialog he has to confirm."

    async def _library(self, query: str | None = None) -> str:
        scan = await self._fresh()
        known = self._known(scan)
        if not known:
            raise AdapterError("I can't find Steam's library on this machine")
        now, q = self.now(), str(query or "").strip()
        if q:
            hits, _ = match_game(q, known)
            words = q.lower().split()
            hits = [g for g in known if all(w in g["name"].lower() for w in words)] or hits
            head = f"{len(hits)} match {q!r} among {len(known)} games he has installed or played"
            if not hits:
                return head + "."
        else:
            hits = [g for g in known if g["installed"]]
            head = (f"{len(hits)} installed of {len(known)} games he has installed or played; "
                    "pass a query to search the rest")
        hits.sort(key=lambda g: (not g["installed"], -g["last_played"], g["name"]))
        rows = "\n".join(
            f"{g['name']} (appid {g['appid']}) — {'installed' if g['installed'] else 'not installed'}, "
            f"{g['minutes'] / 60:.1f}h, {_ago(g['last_played'], now)}" for g in hits[:LIB_ROWS])
        more = f"\n({len(hits) - LIB_ROWS} more; narrow the query)" if len(hits) > LIB_ROWS else ""
        return f"{head}:\n{rows}{more}"

    # ---- his clicks in the widget ----

    def press_args(self, control: str, value) -> dict:
        if value is None:
            raise AdapterError(f"{control} needs a game")
        return {"game": str(value)}
