"""Connecting Spotify from the settings: the Web API login (OAuth with PKCE).

Settings > Models has his Spotify app's Client ID and a Connect button. Connect
opens Spotify's sign-in page in his browser and catches the reply on
http://127.0.0.1:8888/callback (which must be listed under the app's Redirect
URIs), then keeps the login in spotify_oauth.json beside the other keys, mode
0600, where adapters/spotify_web.py reads it. PKCE: no client secret exists or
is needed. Ported from 1.x (ariadne/spotify.py sign_in), same scopes and redirect.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import http.server
import json
import logging
import os
import re
import secrets
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from ..core import models
from .dolphin import host_prefix
from .spotify_web import SpotifyWeb

log = logging.getLogger("ariadne2.spotify_login")

AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
REDIRECT_PORT = 8888
REDIRECT = f"http://127.0.0.1:{REDIRECT_PORT}/callback"    # Spotify refuses "localhost" now
SCOPES = ("playlist-modify-private playlist-modify-public user-library-modify "
          "playlist-read-private playlist-read-collaborative user-library-read user-read-private "
          "user-read-playback-state user-modify-playback-state user-top-read user-read-recently-played")
LOGIN_TIMEOUT = 240.0
CLIENT_ID = re.compile(r"^[0-9a-fA-F]{32}$")


class LoginError(Exception):
    pass


def status() -> str:
    """One line for the settings: who's connected, or that nobody is."""
    data = SpotifyWeb()._load()
    if data.get("refresh_token"):
        return f"Connected as {data.get('display_name') or data.get('user_id') or 'your account'}"
    return "Not connected"


def saved_client_id() -> str:
    return str(SpotifyWeb()._load().get("client_id") or "")


def disconnect() -> str:
    try:
        SpotifyWeb().path.unlink()
    except FileNotFoundError:
        pass
    return "Not connected"


class _Catcher(http.server.BaseHTTPRequestHandler):
    got: dict = {}

    def log_message(self, *a):
        pass

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        if url.path != "/callback":
            self.send_response(404); self.end_headers(); return
        _Catcher.got = {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}
        ok = "code" in _Catcher.got
        page = ("<h2>Spotify is connected.</h2><p>You can close this tab and go back to Aries.</p>" if ok
                else "<h2>Spotify didn't connect.</h2><p>Go back to Aries to see why.</p>")
        body = f"<!doctype html><meta charset=utf-8><title>Ariadne</title><body style='font-family:sans-serif;background:#140a12;color:#f8eef0;padding:40px'>{page}".encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _post_form(fields: dict) -> dict:
    req = urllib.request.Request(TOKEN_URL, data=urllib.parse.urlencode(fields).encode(),
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        raise LoginError(f"Spotify refused it ({e.code}): {e.read(300).decode('utf-8', 'replace')}")
    except (urllib.error.URLError, OSError) as e:
        raise LoginError(f"couldn't reach Spotify: {e}")


def _open_browser(url: str) -> None:
    try:
        subprocess.Popen([*host_prefix(), "xdg-open", url], start_new_session=True,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass


def _sign_in(client: str, on_waiting) -> str:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).decode().rstrip("=")
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    state = secrets.token_urlsafe(16)
    try:
        server = http.server.HTTPServer(("127.0.0.1", REDIRECT_PORT), _Catcher)
    except OSError as e:
        raise LoginError(f"port {REDIRECT_PORT} is busy ({e.strerror}); close whatever uses it and try again")
    _Catcher.got = {}
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": client, "response_type": "code", "redirect_uri": REDIRECT, "scope": SCOPES,
        "code_challenge_method": "S256", "code_challenge": challenge, "state": state})
    _open_browser(url)
    on_waiting()
    deadline = time.monotonic() + LOGIN_TIMEOUT
    try:
        while time.monotonic() < deadline and not _Catcher.got:
            time.sleep(0.25)
    finally:
        server.shutdown()
        server.server_close()
    got, _Catcher.got = dict(_Catcher.got), {}
    if not got:
        raise LoginError("nobody finished signing in within 4 minutes")
    if got.get("error"):
        hint = " (is the Redirect URI in the app exactly " + REDIRECT + "?)" if "redirect" in got["error"] else ""
        raise LoginError(f"Spotify said: {got['error']}{hint}")
    if got.get("state") != state or not got.get("code"):
        raise LoginError("that reply didn't match the request, so it was thrown away")
    tokens = _post_form({"grant_type": "authorization_code", "code": got["code"], "redirect_uri": REDIRECT,
                         "client_id": client, "code_verifier": verifier})
    if not tokens.get("refresh_token"):
        raise LoginError("Spotify didn't send a refresh token back")
    web = SpotifyWeb()
    record = {"client_id": client, "refresh_token": tokens["refresh_token"],
              "access_token": tokens.get("access_token", ""),
              "expires_at": time.time() + int(tokens.get("expires_in", 3600))}
    web.path.parent.mkdir(parents=True, exist_ok=True)
    web._save(record)
    try:
        me = web.request("GET", "/me")
        record["user_id"] = me.get("id", "")
        record["display_name"] = me.get("display_name") or me.get("id", "")
        web._save(record)
    except Exception as e:                 # signed in all the same; the name is a nicety
        log.info("spotify /me after login failed: %s", e)
    return status()


async def connect(client_id: str, on_status) -> None:
    """Run the login, reporting each stage through on_status(text)."""
    client = (client_id or saved_client_id()).strip()
    if not CLIENT_ID.match(client):
        on_status("Paste your app's Client ID first (32 letters and digits)")
        return
    loop = asyncio.get_running_loop()

    def waiting():
        loop.call_soon_threadsafe(on_status, "Waiting for you in the browser…")
    try:
        on_status(await asyncio.to_thread(_sign_in, client, waiting))
    except LoginError as e:
        on_status(f"Didn't connect: {e}")
    except Exception as e:
        log.exception("spotify login failed")
        on_status(f"Didn't connect: {e}")
