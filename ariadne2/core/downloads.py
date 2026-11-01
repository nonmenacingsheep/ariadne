"""The downloads she starts, for the desk's download bars.

Only hers: a download counts when it first shows up within ACTED_S of a tool
she ran (a page opened, a click, a command), or within STEAM_S of a Steam
install she asked for (Steam waits on his click in its dialog first). One he
starts while she's idle never shows. Three places are watched, merged every
couple of seconds and sent as one `downloads` message (desk.js shows them
under her name while she's quiet, and as rows in the chat where her steps go):

- Steam: the Steam adapter's own download rows (progress, rate).
- Chromium-family browsers (Chrome, Chromium, Opera, Brave, Edge, Vivaldi,
  native or Flatpak): their History database lists each download in progress
  with its total size, so a .crdownload gets a real percentage. Read with
  immutable=1, a snapshot that never locks the browser out.
- Download folders (XDG Downloads, ~/Downloads, the browsers' own download
  folders): a partial file (.crdownload, .part, .partial, .download,
  .opdownload) is a download in progress; so is any other file that keeps
  growing (curl, wget, an app writing straight to its file). Those have no
  known total, so their bar runs without a percentage.

Read-only: nothing here touches the files it watches.
"""
from __future__ import annotations

import asyncio
import glob
import json
import logging
import os
import sqlite3
import time
from collections import deque
from pathlib import Path

log = logging.getLogger("ariadne2.downloads")

EVERY = 2.0
HISTORY_EVERY = 4.0                  # the browsers' databases are read less often
PARTIAL = (".crdownload", ".part", ".partial", ".download", ".opdownload")
ACTED_S = 90.0                       # a new download this soon after one of her tools is hers
STEAM_S = 900.0                      # a Steam download this soon after her install verb is hers
GROWING_FOR = 8.0                    # a plain file counts as downloading while it grew this recently
RATE_WINDOW = 20.0
_BROWSERS = ("google-chrome", "google-chrome-beta", "google-chrome-unstable", "chromium", "opera", "opera-gx",
             "opera-beta", "BraveSoftware/Brave-Browser", "microsoft-edge", "vivaldi")


def _home() -> Path:
    return Path(os.environ.get("HOME") or Path.home())


def browser_profiles(home: Path | None = None) -> list[Path]:
    """Every Chromium-family profile folder (one holding a History file)."""
    home = home or _home()
    roots = [home / ".config" / b for b in _BROWSERS]
    roots += [Path(p) for p in glob.glob(str(home / ".var/app/*/config/*"))]
    out = []
    for root in roots:
        for hist in glob.glob(str(root / "*" / "History")):
            out.append(Path(hist).parent)
    return out


def download_dirs(home: Path | None = None, profiles=None) -> list[Path]:
    """XDG Downloads, ~/Downloads, and each browser's chosen download folder."""
    home = home or _home()
    dirs = [home / "Downloads"]
    try:
        for line in (home / ".config" / "user-dirs.dirs").read_text().splitlines():
            if line.startswith("XDG_DOWNLOAD_DIR="):
                dirs.append(Path(line.split("=", 1)[1].strip().strip('"').replace("$HOME", str(home))))
    except OSError:
        pass
    for prof in profiles if profiles is not None else browser_profiles(home):
        try:
            d = json.loads((prof / "Preferences").read_text("utf-8")).get("download", {}).get("default_directory")
        except (OSError, ValueError, AttributeError):
            d = None
        if d:
            dirs.append(Path(d))
    seen, out = set(), []
    for d in dirs:
        try:
            real = d.resolve()
        except OSError:
            continue
        if real not in seen and real.is_dir():
            seen.add(real)
            out.append(real)
    return out


def browser_downloads(profiles) -> dict[str, dict]:
    """In-progress downloads from each History database: partial path -> {name, total}."""
    out: dict[str, dict] = {}
    for prof in profiles:
        uri = "file:" + str(prof / "History") + "?immutable=1"
        try:
            con = sqlite3.connect(uri, uri=True, timeout=0.5)
            try:
                rows = con.execute("SELECT current_path, target_path, total_bytes FROM downloads "
                                   "WHERE state = 0").fetchall()
            finally:
                con.close()
        except sqlite3.Error:
            continue
        for current, target, total in rows:
            if current:
                out[current] = {"name": os.path.basename(target or current), "total": int(total or 0) or None,
                                "target": target or None}
    return out


class DownloadWatch:
    def __init__(self, publish, steam=None, home: Path | None = None, clock=time.monotonic) -> None:
        self.publish = publish
        self.steam = steam                   # the Steam adapter, or None
        self.home = home
        self.clock = clock
        self._sizes: dict[str, tuple[int, float]] = {}      # path -> (size, when it last grew)
        self._samples: dict[str, deque] = {}
        self._browser: dict[str, dict] = {}
        self._browser_at = -1e9
        self._dirs_at = -1e9
        self._dirs: list[Path] = []
        self._profiles: list[Path] = []
        self._last: list | None = None
        self._task: asyncio.Task | None = None
        self._acted = -1e9                   # when she last ran a tool
        self._steam_asked = -1e9             # when she last asked Steam to install
        self._hers: dict[str, bool] = {}     # download id -> hers, decided when first seen

    def note_tool(self, name: str, args) -> None:
        """Conversation.on_tool: she just ran something that may start a download."""
        now = self.clock()
        self._acted = now
        action = args.get("action") if isinstance(args, dict) else None
        if name == "steam_install" or (name == "steam" and action == "install"):
            self._steam_asked = now

    def _mine(self, items: list[dict]) -> list[dict]:
        now, out = self.clock(), []
        for i in items:
            if i["id"] not in self._hers:
                window = STEAM_S if i["source"] == "steam" else ACTED_S
                since = (self._steam_asked if i["source"] == "steam" else self._acted)
                self._hers[i["id"]] = now - since <= window
            if self._hers[i["id"]]:
                out.append(i)
        live = {i["id"] for i in items}
        for k in [k for k in self._hers if k not in live]:
            del self._hers[k]                # gone: a later download with the same id is judged afresh
        return out

    # ---- reading ----

    def _rate(self, key: str, done: int, now: float) -> float | None:
        s = self._samples.setdefault(key, deque())
        s.append((now, done))
        while s and now - s[0][0] > RATE_WINDOW:
            s.popleft()
        if len(s) < 2 or s[-1][0] - s[0][0] < 1.5:
            return None
        return max(0.0, (s[-1][1] - s[0][1]) / (s[-1][0] - s[0][0]))

    def files(self) -> list[dict]:
        now = self.clock()
        if now - self._dirs_at > 60:                         # folders and profiles barely change
            self._profiles = browser_profiles(self.home)
            self._dirs = download_dirs(self.home, self._profiles)
            self._dirs_at = now
        if now - self._browser_at > HISTORY_EVERY:
            self._browser = browser_downloads(self._profiles)
            self._browser_at = now
        seen, items = set(), []
        candidates = [Path(p) for p in self._browser]
        for d in self._dirs:
            try:
                candidates += [Path(e.path) for e in os.scandir(d) if e.is_file(follow_symlinks=False)]
            except OSError:
                pass
        for p in candidates:
            key = str(p)
            if key in seen:
                continue
            seen.add(key)
            try:
                size = p.stat().st_size
            except OSError:
                continue
            old = self._sizes.get(key)
            grew = now if old is None or size > old[0] else old[1]
            if old is None:
                grew = -1e9                                  # first sight: not growing yet
            self._sizes[key] = (size, grew)
            known = self._browser.get(key)
            partial = p.name.lower().endswith(PARTIAL)
            if not (known or partial or now - grew < GROWING_FOR):
                continue
            name = known["name"] if known else (p.name[: -len(p.suffix)] if partial else p.name)
            total = known["total"] if known else None
            final = known.get("target") if known else (str(p)[: -len(p.suffix)] if partial else key)
            items.append({"id": "file:" + key, "name": name, "final": final, "source": "browser" if (known or partial) else "file",
                          "done": size, "total": total,
                          "progress": round(min(1.0, size / total), 4) if total else None,
                          "rate": self._rate(key, size, now), "state": "downloading"})
        for key in [k for k in self._sizes if k not in seen]:
            self._sizes.pop(key, None)
            self._samples.pop(key, None)
        return items

    def steam_items(self) -> list[dict]:
        if self.steam is None:
            return []
        try:
            rows = (self.steam.state() or {}).get("downloads") or []
        except Exception:
            return []
        return [{"id": f"steam:{d['appid']}", "name": d["name"], "source": "steam", "done": d.get("bytes_done"),
                 "total": d.get("bytes_total") or None, "progress": d.get("progress"), "rate": d.get("rate_bps"),
                 "state": d.get("state") or "downloading"} for d in rows]

    def collect(self) -> list[dict]:
        return self._mine(self.steam_items() + self.files())

    def finished(self, item: dict) -> bool:
        """Whether a download that just left the list completed (else it was stopped)."""
        if item["source"] == "steam":
            try:
                m = self.steam.files.manifests().get(int(item["id"].split(":", 1)[1]))
            except Exception:
                return True
            return bool(m and m.get("installed"))
        final = item.get("final")
        return bool(final) and os.path.exists(final)

    # ---- running ----

    async def tick(self) -> None:
        items = await asyncio.to_thread(self.collect)
        now_ids = {i["id"] for i in items}
        gone = [i for i in (self._last or []) if i["id"] not in now_ids]
        ended = [{"id": i["id"], "name": i["name"], "ok": await asyncio.to_thread(self.finished, i)} for i in gone]
        # Sent while anything is going (the numbers move), and once when the last one ends.
        if items or ended:
            await self.publish({"t": "downloads", "items": items, "ended": ended})
        self._last = items

    async def _loop(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception:
                log.exception("download watch failed")
            await asyncio.sleep(EVERY)

    def start(self) -> None:
        self._task = asyncio.ensure_future(self._loop())

    def stop(self) -> None:
        if self._task:
            self._task.cancel()
