"""Spotify's Web API client, on 1.x's saved login.

The OAuth file (~/.local/share/ariadne/spotify_oauth.json) is read at call
time and refreshed the way 1.x does (Spotify sometimes rotates the refresh
token, so a refresh is written back, mode 0600). Tokens are never logged or
copied anywhere else. Blocking urllib; the adapter calls it from a thread.
"""
from __future__ import annotations

import asyncio
import json
import os
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from ..core import models
from .base import AdapterError

TOKEN_URL = "https://accounts.spotify.com/api/token"
API = "https://api.spotify.com/v1"
HTTP_TIMEOUT = 15
SCAN_CAP = 1000            # most context tracks read while looking for the current one


class WebError(Exception):
    """`message` is plain English; `kind` is auth / denied / rate / network / http."""

    def __init__(self, message: str, kind: str = "http") -> None:
        super().__init__(message)
        self.kind = kind


class SpotifyWeb:
    def __init__(self, path: str | os.PathLike | None = None) -> None:
        self._path = Path(path) if path else None
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        # Resolved late so tests (and XDG_DATA_HOME changes) are honoured.
        return self._path or models.data_dir() / "spotify_oauth.json"

    def _load(self) -> dict:
        try:
            return json.loads(self.path.read_text("utf-8"))
        except (OSError, ValueError):
            return {}

    def _save(self, data: dict) -> None:
        # Create closed, then fill: never world-readable, even for a moment.
        fd = os.open(str(self.path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        os.chmod(self.path, 0o600)

    def available(self) -> bool:
        return bool(self._load().get("refresh_token"))

    def _post_form(self, fields: dict) -> dict:
        req = urllib.request.Request(TOKEN_URL, data=urllib.parse.urlencode(fields).encode(),
                                     headers={"Content-Type": "application/x-www-form-urlencoded"})
        try:
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            raise WebError("Spotify wouldn't renew the saved login; it needs signing in "
                           "again from the old Ariadne.", "auth") from e
        except (urllib.error.URLError, TimeoutError, socket.timeout) as e:
            raise WebError(f"couldn't reach Spotify ({e.__class__.__name__}).", "network") from e

    def _token(self) -> str:
        with self._lock:
            saved = self._load()
            if not saved.get("refresh_token"):
                raise WebError("Spotify's Web API isn't authorised (no saved login).", "auth")
            if saved.get("access_token") and time.time() < saved.get("expires_at", 0) - 60:
                return saved["access_token"]
            fresh = self._post_form({"grant_type": "refresh_token",
                                     "refresh_token": saved["refresh_token"],
                                     "client_id": saved.get("client_id", "")})
            token = fresh.get("access_token", "")
            if not token:
                raise WebError("Spotify wouldn't renew the saved login.", "auth")
            saved["access_token"] = token
            saved["expires_at"] = time.time() + int(fresh.get("expires_in", 3600))
            if fresh.get("refresh_token"):
                saved["refresh_token"] = fresh["refresh_token"]
            try:
                self._save(saved)
            except OSError:
                pass            # still usable this run
            return token

    def request(self, method: str, path: str, body: dict | None = None,
                params: dict | None = None) -> dict:
        url = API + path + (("?" + urllib.parse.urlencode(params)) if params else "")
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", f"Bearer {self._token()}")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as r:
                raw = r.read().decode("utf-8", "replace")
                return json.loads(raw) if raw.strip() else {}
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:200]
            if e.code == 401:
                raise WebError("Spotify rejected the saved login.", "auth") from e
            if e.code == 403:
                raise WebError(f"Spotify refused that ({detail or 'forbidden'}).", "denied") from e
            if e.code == 404 and "device" in detail.lower():
                raise WebError("Spotify has no active device; open the Spotify app first.",
                               "http") from e
            if e.code == 429:
                raise WebError("Spotify is rate limiting; wait a moment.", "rate") from e
            raise WebError(f"Spotify said {e.code}: {detail}", "http") from e
        except (urllib.error.URLError, TimeoutError, socket.timeout) as e:
            raise WebError(f"couldn't reach Spotify ({e.__class__.__name__}).", "network") from e


def _row(t: dict) -> dict:
    """A Web API track object -> the widget's row. `uri` only when Spotify gave one."""
    row = {"title": t.get("name", ""),
           "artist": ", ".join(a.get("name", "") for a in t.get("artists") or [])}
    if t.get("uri"):
        row["uri"] = t["uri"]
    return row


class WebCalls:
    """The adapter's Web API helpers (mixed into SpotifyAdapter; needs self.web)."""

    _pl_path = "/playlists/{}/items"          # Spotify renamed /tracks; fallback below

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


    async def _in_context(self, ctx: dict, uri: str) -> bool:
        async for row in self._context_rows(ctx):
            if row["uri"] == uri:
                return True
        return False

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


    async def _set_shuffle(self, on: bool) -> None:
        await self._web("PUT", "/me/player/shuffle", params={"state": "true" if on else "false"})

    async def _recent_rows(self, limit: int) -> list[dict]:
        """Recently played, oldest first (Spotify returns newest first)."""
        recent = await self._web("GET", "/me/player/recently-played", params={"limit": limit})
        rows = [_row(i["track"]) for i in recent.get("items") or [] if i and i.get("track")]
        return [r for r in reversed(rows) if r.get("uri")]
