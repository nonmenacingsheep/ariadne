"""Connecting Spotify from the settings (PKCE login on 127.0.0.1:8888)."""
import asyncio
import json
import os
import tempfile
import threading
import unittest
import urllib.parse
import urllib.request
from pathlib import Path
from unittest import mock

from ariadne2.adapters import spotify_login as L

CLIENT = "0123456789abcdef0123456789abcdef"


class LoginTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        p = mock.patch.dict(os.environ, {"XDG_DATA_HOME": str(self.tmp)})
        p.start(); self.addCleanup(p.stop)
        self.said = []

    def browser(self, reply):
        """Stands in for him signing in: hits the callback with what Spotify would send."""
        def open_(url):
            q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
            self.asked = q
            params = reply(q)
            threading.Timer(0.2, lambda: urllib.request.urlopen(
                L.REDIRECT + "?" + urllib.parse.urlencode(params), timeout=5).read()).start()
        return open_

    async def test_a_full_sign_in_saves_a_private_login(self):
        tokens = {"access_token": "AT", "refresh_token": "RT", "expires_in": 3600}
        with mock.patch.object(L, "_open_browser", self.browser(lambda q: {"code": "C", "state": q["state"]})), \
             mock.patch.object(L, "_post_form", return_value=tokens) as post, \
             mock.patch.object(L.SpotifyWeb, "request", return_value={"id": "u1", "display_name": "Ronald"}):
            await L.connect(CLIENT, self.said.append)
        self.assertEqual(self.said, ["Waiting for you in the browser…", "Connected as Ronald"])
        self.assertEqual(self.asked["code_challenge_method"], "S256")
        self.assertEqual(self.asked["redirect_uri"], "http://127.0.0.1:8888/callback")
        self.assertIn("user-modify-playback-state", self.asked["scope"])
        sent = post.call_args[0][0]
        self.assertEqual((sent["code"], sent["client_id"]), ("C", CLIENT))
        self.assertNotIn("client_secret", sent)
        path = self.tmp / "ariadne2" / "spotify_oauth.json"
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(json.loads(path.read_text())["refresh_token"], "RT")
        self.assertEqual(L.status(), "Connected as Ronald")
        self.assertEqual(L.disconnect(), "Not connected")
        self.assertFalse(path.exists())

    async def test_a_reply_for_someone_elses_request_is_thrown_away(self):
        with mock.patch.object(L, "_open_browser", self.browser(lambda q: {"code": "C", "state": "forged"})), \
             mock.patch.object(L, "_post_form") as post:
            await L.connect(CLIENT, self.said.append)
        self.assertIn("didn't match", self.said[-1])
        post.assert_not_called()

    async def test_spotify_errors_are_explained(self):
        with mock.patch.object(L, "_open_browser", self.browser(lambda q: {"error": "invalid redirect uri", "state": q["state"]})):
            await L.connect(CLIENT, self.said.append)
        self.assertIn("Redirect URI", self.said[-1])

    async def test_needs_a_client_id_first(self):
        await L.connect("not an id", self.said.append)
        self.assertIn("Client ID", self.said[0])
        self.assertEqual(L.status(), "Not connected")


if __name__ == "__main__":
    unittest.main()
