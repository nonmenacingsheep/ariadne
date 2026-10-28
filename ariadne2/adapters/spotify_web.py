"""Spotify's Web API client, on 1.x's saved login.

The OAuth file (~/.local/share/ariadne/spotify_oauth.json) is read at call
time and refreshed the way 1.x does (Spotify sometimes rotates the refresh
token, so a refresh is written back, mode 0600). Tokens are never logged or
copied anywhere else. Blocking urllib; the adapter calls it from a thread.
"""
from __future__ import annotations

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

TOKEN_URL = "https://accounts.spotify.com/api/token"
API = "https://api.spotify.com/v1"
HTTP_TIMEOUT = 15


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
