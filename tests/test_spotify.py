import asyncio
import unittest
from unittest import mock

from ariadne2.adapters import AdapterError, spotify
from ariadne2.adapters.mpris import MprisError
from ariadne2.adapters.spotify_web import WebError

spotify.SETTLE_SCALE = 0

META = {"xesam:title": "E.T.", "xesam:artist": ["NovaX", "Kat"], "xesam:album": "Paparazzi X",
        "mpris:artUrl": "http://open.spotify.com/image/abc123", "mpris:length": 146_000_000,
        "mpris:trackid": "/com/spotify/track/TRACK1"}


def snap(status="Playing", meta=META, pos=80_000_000, vol=0.4):
    return {"running": True, "status": status, "metadata": dict(meta),
            "position_us": pos, "volume": vol}


class FakeMpris:
    def __init__(self, snapshot=None):
        self.snap = snapshot or {"running": False}
        self.sent = []
        self.started = False

    def start(self, on_change):
        self.started = True
        self.on_change = on_change

    def stop(self):
        pass

    def snapshot(self):
        if isinstance(self.snap, Exception):
            raise self.snap
        return self.snap

    def command(self, method):
        self.sent.append(("command", method))

    def set_volume(self, level):
        self.sent.append(("volume", level))

    def set_position(self, tid, seconds):
        self.sent.append(("position", tid, seconds))


class FakeWeb:
    def __init__(self, ok=True, routes=None):
        self.ok = ok
        self.routes = routes or {}
        self.calls = []

    def available(self):
        return self.ok

    def request(self, method, path, body=None, params=None):
        self.calls.append((method, path, body, params))
        r = self.routes.get((method, path), {})
        if isinstance(r, Exception):
            raise r
        return r(body, params) if callable(r) else r


class MapStateTests(unittest.TestCase):
    def test_full_mapping(self):
        s = spotify.map_state(snap(), None, 1000.0)
        self.assertEqual(s, {
            "status": "playing", "title": "E.T.", "artist": "NovaX, Kat", "album": "Paparazzi X",
            "art_url": "https://i.scdn.co/image/abc123", "position_s": 80.0, "length_s": 146.0,
            "updated": 1000.0, "volume": 40, "liked": None, "shuffle": None, "repeat": None,
            "queue": [], "history": []})

    def test_exact_key_set(self):
        self.assertEqual(set(spotify.blank_state()), {
            "status", "title", "artist", "album", "art_url", "position_s", "length_s", "updated",
            "volume", "liked", "shuffle", "repeat", "queue", "history"})

    def test_not_running_and_statuses(self):
        self.assertEqual(spotify.map_state({"running": False}, None, 1.0)["status"], "not running")
        self.assertEqual(spotify.map_state(snap("Paused"), None, 1.0)["status"], "paused")
        self.assertEqual(spotify.map_state(snap("Stopped"), None, 1.0)["status"], "stopped")

    def test_string_artist_missing_fields_and_https_art(self):
        s = spotify.map_state(snap(meta={"xesam:title": "x", "xesam:artist": "Solo",
                                         "mpris:artUrl": "https://i.scdn.co/image/z"}), None, 1.0)
        self.assertEqual((s["artist"], s["album"], s["length_s"], s["art_url"]),
                         ("Solo", "", 0.0, "https://i.scdn.co/image/z"))

    def test_extras_only_apply_to_their_track(self):
        extras = {"track_id": "TRACK1", "liked": True, "shuffle": True, "repeat": "context",
                  "queue": [{"title": f"t{i}", "artist": "a"} for i in range(8)]}
        s = spotify.map_state(snap(), extras, 1.0)
        self.assertEqual((s["liked"], s["shuffle"], s["repeat"], len(s["queue"])),
                         (True, True, "context", 5))
        other = dict(META, **{"mpris:trackid": "/com/spotify/track/OTHER"})
        s = spotify.map_state(snap(meta=other), extras, 1.0)
        self.assertEqual((s["liked"], s["queue"], s["shuffle"]), (None, [], True))

    def test_volume_clamped(self):
        self.assertEqual(spotify.map_state(snap(vol=1.7), None, 1.0)["volume"], 100)

    def test_changed_ignores_clock_drift_but_sees_seeks(self):
        a = spotify.map_state(snap(), None, 100.0)
        drift = spotify.map_state(snap(pos=85_000_000), None, 105.0)
        self.assertFalse(spotify._changed(a, drift))
        seek = spotify.map_state(snap(pos=20_000_000), None, 105.0)
        self.assertTrue(spotify._changed(a, seek))
        paused = spotify.map_state(snap("Paused"), None, 105.0)
        self.assertTrue(spotify._changed(a, paused))


class AdapterCase(unittest.IsolatedAsyncioTestCase):
    def make(self, snapshot=None, web=None, mpris=None):
        self.sent = []

        async def publish(m):
            self.sent.append(m)
        self.mpris = mpris or FakeMpris(snapshot or snap())
        self.web = web or FakeWeb(ok=False)
        a = spotify.SpotifyAdapter(publish, self.mpris, self.web)
        self.events = []
        a.subscribe(lambda n, f: self.events.append((n, f)))
        return a

    def states(self):
        return [m["data"] for m in self.sent if m["t"] == "state"]

    async def asyncTearDown(self):
        if getattr(self, "adapter", None):
            await self.adapter.stop()


class StateFlowTests(AdapterCase):
    async def test_start_publishes_state_and_listens(self):
        a = self.adapter = self.make()
        await a.start()
        self.assertTrue(self.mpris.started)
        self.assertEqual(self.states()[0]["title"], "E.T.")
        self.assertEqual(self.sent[0]["widget"], "spotify")

    async def test_signal_wakes_refresh_and_emits_events(self):
        a = self.adapter = self.make()
        await a.start()
        n = len(self.states())
        self.mpris.snap = snap("Paused")
        self.mpris.on_change()                     # D-Bus thread would do this
        await asyncio.sleep(0.3)
        self.assertEqual(self.states()[-1]["status"], "paused")
        self.assertGreater(len(self.states()), n)
        self.assertEqual([e[0] for e in self.events], ["spotify.paused"])
        self.mpris.snap = snap("Playing", meta=dict(META, **{"xesam:title": "Next"}))
        self.mpris.on_change()
        await asyncio.sleep(0.3)
        names = [e[0] for e in self.events]
        self.assertEqual(names[1:], ["spotify.track_changed", "spotify.playing"])
        self.assertEqual(self.events[1][1], {"title": "Next", "artist": "NovaX, Kat"})

    async def test_unchanged_snapshot_publishes_nothing_extra(self):
        a = self.adapter = self.make()
        await a.start()
        n = len(self.states())
        await a.refresh()
        await a.refresh()
        self.assertEqual(len(self.states()), n)
        self.assertEqual(self.events, [])

    async def test_spotify_not_running_is_a_state_not_an_error(self):
        a = self.adapter = self.make(snapshot={"running": False})
        await a.start()
        self.assertEqual(self.states()[-1]["status"], "not running")
        self.mpris.snap = MprisError("bus gone")
        await a.refresh()
        self.assertEqual(a.state()["status"], "not running")

    async def test_extras_from_web_api_fill_state(self):
        routes = {("GET", "/me/player"): {"shuffle_state": True, "repeat_state": "track"},
                  ("GET", "/me/player/queue"): {"queue": [{"name": "Q1", "artists": [{"name": "A"}]}]},
                  ("GET", "/me/library/contains"): [True]}
        a = self.adapter = self.make(web=FakeWeb(routes=routes))
        await a.start()
        await asyncio.sleep(0.2)
        s = a.state()
        self.assertEqual((s["liked"], s["shuffle"], s["repeat"], s["queue"]),
                         (True, True, "track", [{"title": "Q1", "artist": "A"}]))

    async def test_one_retired_endpoint_only_nulls_its_own_field(self):
        routes = {("GET", "/me/player"): {"shuffle_state": False, "repeat_state": "off"},
                  ("GET", "/me/player/queue"): WebError("Spotify refused that.", "denied"),
                  ("GET", "/me/library/contains"): WebError("gone", "denied"),
                  ("GET", "/me/tracks/contains"): WebError("gone", "denied")}
        a = self.adapter = self.make(web=FakeWeb(routes=routes))
        await a.start()
        await asyncio.sleep(0.2)
        s = a.state()
        self.assertEqual((s["shuffle"], s["repeat"], s["liked"], s["queue"]),
                         (False, "off", None, []))


class WebMissingTests(AdapterCase):
    async def test_web_verbs_fail_clearly_without_login(self):
        a = self.adapter = self.make()          # FakeWeb(ok=False)
        await a.start()
        for verb, args in (("play", {"query": "daft punk"}), ("queue", {"query": "x"}),
                           ("like", {}), ("playlist", {"name": "gym"}),
                           ("play", {"kind": "liked"})):
            with self.assertRaises(AdapterError) as cm:
                await a.run(verb, args)
            self.assertIn("Web API isn't authorised", str(cm.exception), verb)
        failed = [m for m in self.sent if m["t"] == "action" and m["phase"] == "failed"]
        self.assertEqual(len(failed), 5)

    async def test_transport_volume_seek_still_work_over_mpris(self):
        a = self.adapter = self.make()
        await a.start()
        await a.run("pause")
        await a.run("next")
        await a.run("prev")
        await a.run("play")                      # no query = resume
        await a.run("volume", {"level": 55})
        await a.run("seek", {"seconds": 30})
        self.assertEqual(self.mpris.sent, [
            ("command", "Pause"), ("command", "Next"), ("command", "Previous"),
            ("command", "Play"), ("volume", 0.55), ("position", "/com/spotify/track/TRACK1", 30.0)])

    async def test_not_running_transport_says_so(self):
        a = self.adapter = self.make(snapshot={"running": False})
        await a.start()
        with self.assertRaises(AdapterError) as cm:
            await a.run("next")
        self.assertIn("isn't running", str(cm.exception))


class WebVerbTests(AdapterCase):
    def routes(self):
        return {("GET", "/search"): lambda b, p: {"tracks": {"items": [
                    {"name": "Around the World", "uri": "spotify:track:T9",
                     "artists": [{"name": "Daft Punk"}]}]},
                    "playlists": {"items": [{"name": "Gym Mix", "uri": "spotify:playlist:P1"}]}},
                ("GET", "/me/player/devices"): {"devices": [
                    {"id": "phone", "type": "Smartphone"}, {"id": "pc", "type": "Computer"}]},
                ("GET", "/me/playlists"): {"items": [{"name": "Chill", "uri": "spotify:playlist:C"},
                                                     {"name": "Gym Mix", "uri": "spotify:playlist:P1"}]},
                ("GET", "/me/tracks"): {"items": [{"track": {"uri": "spotify:track:L1"}}]}}

    async def test_search_and_play_track(self):
        web = FakeWeb(routes=self.routes())
        a = self.adapter = self.make(web=web)
        await a.start()
        out = await a.run("play", {"query": "around the world"})
        self.assertIn("Around the World — Daft Punk", out)
        play = [c for c in web.calls if c[1] == "/me/player/play"][0]
        self.assertEqual(play[2], {"uris": ["spotify:track:T9"]})
        self.assertEqual(play[3], {"device_id": "pc"})          # computer beats phone

    async def test_play_album_uses_context_and_bad_kind_rejected(self):
        r = self.routes()
        r[("GET", "/search")] = {"albums": {"items": [{"name": "Discovery", "uri": "spotify:album:A"}]}}
        web = FakeWeb(routes=r)
        a = self.adapter = self.make(web=web)
        await a.start()
        await a.run("play", {"query": "discovery", "kind": "album"})
        self.assertEqual([c for c in web.calls if c[1] == "/me/player/play"][0][2],
                         {"context_uri": "spotify:album:A"})
        with self.assertRaises(AdapterError):
            await a.run("play", {"query": "x", "kind": "podcast"})

    async def test_liked_playlist_queue_like(self):
        web = FakeWeb(routes=self.routes())
        a = self.adapter = self.make(web=web)
        await a.start()
        await a.run("play", {"kind": "liked"})
        self.assertEqual([c for c in web.calls if c[1] == "/me/player/play"][-1][2],
                         {"uris": ["spotify:track:L1"]})
        await a.run("playlist", {"name": "gym"})
        self.assertEqual([c for c in web.calls if c[1] == "/me/player/play"][-1][2],
                         {"context_uri": "spotify:playlist:P1"})
        await a.run("queue", {"query": "daft"})
        self.assertIn(("POST", "/me/player/queue", None, {"uri": "spotify:track:T9"}), web.calls)
        out = await a.run("like")
        self.assertIn(("PUT", "/me/library", None, {"uris": "spotify:track:TRACK1"}), web.calls)
        self.assertIn("Liked: E.T.", out)
        self.assertTrue(a.state()["liked"])

    async def test_like_falls_back_to_old_endpoint(self):
        r = self.routes()
        r[("PUT", "/me/library")] = WebError("Spotify refused that.", "denied")
        web = FakeWeb(routes=r)
        a = self.adapter = self.make(web=web)
        await a.start()
        await a.run("like")
        self.assertIn(("PUT", "/me/tracks", None, {"ids": "TRACK1"}), web.calls)

    async def test_no_match_and_no_device_are_plain_errors(self):
        r = self.routes()
        r[("GET", "/search")] = {"tracks": {"items": []}}
        a = self.adapter = self.make(web=FakeWeb(routes=r))
        await a.start()
        with self.assertRaises(AdapterError) as cm:
            await a.run("play", {"query": "zzzz"})
        self.assertIn("nothing on Spotify matches", str(cm.exception))
        r2 = self.routes()
        r2[("GET", "/me/player/devices")] = {"devices": []}
        a2 = self.make(web=FakeWeb(routes=r2))
        await a2.start()
        with self.assertRaises(AdapterError) as cm:
            await a2.run("play", {"query": "around"})
        self.assertIn("no device", str(cm.exception))
        await a2.stop()

    async def test_transport_prefers_web_and_falls_back_to_mpris_on_error(self):
        web = FakeWeb(routes={("POST", "/me/player/next"): {}})
        a = self.adapter = self.make(web=web)
        await a.start()
        await a.run("next")
        self.assertEqual(self.mpris.sent, [])
        self.assertIn(("POST", "/me/player/next", None, None), web.calls)
        web.routes[("POST", "/me/player/next")] = WebError("Spotify is rate limiting", "rate")
        await a.run("next")
        self.assertEqual(self.mpris.sent, [("command", "Next")])

    async def test_volume_web_then_mpris_fallback(self):
        web = FakeWeb(routes={("PUT", "/me/player/volume"): WebError("no device", "http")})
        a = self.adapter = self.make(web=web)
        await a.start()
        await a.run("volume", {"level": 250})
        self.assertEqual(self.mpris.sent, [("volume", 1.0)])


class PressTests(AdapterCase):
    async def test_buttons_map_without_animation(self):
        a = self.adapter = self.make()           # no Web API: MPRIS takes the writes
        await a.start()
        before = len(self.sent)
        await a.press("next")
        await a.press("prev")
        await a.press("volume", 25)
        await a.press("scrub", 12.5)
        await a.press("play")                    # playing -> pause
        self.assertEqual(self.mpris.sent, [
            ("command", "Next"), ("command", "Previous"), ("volume", 0.25),
            ("position", "/com/spotify/track/TRACK1", 12.5), ("command", "Pause")])
        actions = [m for m in self.sent[before:] if m["t"] == "action"]
        self.assertEqual(actions, [])

    async def test_play_toggles_and_like_uses_current_state(self):
        a = self.adapter = self.make(snapshot=snap("Paused"))
        await a.start()
        await a.press("play")
        self.assertEqual(self.mpris.sent[-1], ("command", "Play"))
        a._state["liked"] = True
        self.assertEqual(a.press_args("like", None), {"remove": True})
        a._state["liked"] = None
        self.assertEqual(a.press_args("like", None), {"remove": False})
        with self.assertRaises(AdapterError):
            a.press_args("volume", None)

    async def test_verbs_light_the_right_controls(self):
        a = self.adapter = self.make()
        await a.start()
        got = {}
        for verb, args in (("pause", {}), ("next", {}), ("prev", {}), ("volume", {"level": 5}),
                           ("seek", {"seconds": 1}), ("play", {})):
            self.sent.clear()
            await a.run(verb, args)
            got[verb] = self.sent[0]["control"]
        self.assertEqual(got, {"pause": "play", "next": "next", "prev": "prev",
                               "volume": "volume", "seek": "scrub", "play": "play"})


def _tracks(names, wrap=False):
    rows = [{"name": n, "uri": f"spotify:track:{n}", "artists": [{"name": "Art"}]} for n in names]
    return [{"track": r} for r in rows] if wrap else rows


class HistoryJumpTests(AdapterCase):
    PL = {"type": "playlist", "uri": "spotify:playlist:P1"}

    def web(self, ctx=PL, order=None, queue=("Q1", "Q2", "Q3")):
        order = order or [f"S{i}" for i in range(12)] + ["TRACK1", "S13"]
        routes = {("GET", "/me/player"): {"context": ctx} if ctx else {},
                  ("GET", "/me/player/queue"): {"queue": _tracks(queue)},
                  ("GET", "/playlists/P1/items"): {"items": _tracks(order, wrap=True)},
                  ("GET", "/me/player/recently-played"): {"items": [
                      {"track": t} for t in reversed(_tracks([f"R{i}" for i in range(9)] + ["TRACK1"]))]},
                  ("GET", "/me/player/devices"): {"devices": [{"id": "pc", "is_active": True}]},
                  ("PUT", "/me/player/play"): {}, ("POST", "/me/player/next"): {}}
        return FakeWeb(routes=routes)

    def hits(self, web, path):
        return [c for c in web.calls if c[1] == path]

    async def test_history_from_playlist_context(self):
        web = self.web()
        a = self.adapter = self.make(web=web)
        await a.start()
        await asyncio.sleep(0.2)
        h = a.state()["history"]
        self.assertEqual([r["title"] for r in h], [f"S{i}" for i in range(2, 12)])   # oldest first
        self.assertEqual(h[-1], {"title": "S11", "artist": "Art", "uri": "spotify:track:S11"})
        self.assertEqual(a.state()["queue"][0]["uri"], "spotify:track:Q1")
        self.assertEqual(self.hits(web, "/me/player/recently-played"), [])

    async def test_context_without_current_track_falls_back_to_recents(self):
        web = self.web(order=["S0", "S1"])
        a = self.adapter = self.make(web=web)
        await a.start()
        await asyncio.sleep(0.2)
        h = a.state()["history"]
        self.assertEqual([r["title"] for r in h], [f"R{i}" for i in range(9)])        # no TRACK1
        self.assertEqual(h[0]["uri"], "spotify:track:R0")

    async def test_no_context_uses_recently_played(self):
        web = self.web(ctx=None)
        a = self.adapter = self.make(web=web)
        await a.start()
        await asyncio.sleep(0.2)
        self.assertEqual(len(a.state()["history"]), 9)
        self.assertEqual(self.hits(web, "/playlists/P1/items"), [])

    async def test_scan_is_capped(self):
        web = self.web(order=[f"S{i}" for i in range(1500)])
        web.routes[("GET", "/playlists/P1/items")] = lambda b, p: {
            "items": _tracks([f"S{i}" for i in range(p["offset"], p["offset"] + 100)], wrap=True),
            "next": "more"}
        a = self.adapter = self.make(web=web)
        await a.start()
        await asyncio.sleep(0.2)
        self.assertEqual(len(self.hits(web, "/playlists/P1/items")), 10)              # 1000 tracks

    async def test_history_cached_until_track_or_context_changes(self):
        web = self.web()
        a = self.adapter = self.make(web=web)
        await a.start()
        await asyncio.sleep(0.2)
        n = len(self.hits(web, "/playlists/P1/items"))
        self.assertEqual(n, 1)
        await a._refresh_extras()
        await a._refresh_extras()
        self.assertEqual(len(self.hits(web, "/playlists/P1/items")), n)
        self.assertEqual(len(a.state()["history"]), 10)
        web.routes[("GET", "/me/player")] = {"context": {"type": "playlist", "uri": "spotify:playlist:P2"}}
        web.routes[("GET", "/playlists/P2/items")] = {"items": _tracks(["X", "TRACK1"], wrap=True)}
        await a._refresh_extras()
        self.assertEqual([r["title"] for r in a.state()["history"]], ["X"])
        self.mpris.snap = snap(meta=dict(META, **{"mpris:trackid": "/com/spotify/track/OTHER",
                                                   "xesam:title": "Other"}))
        web.routes[("GET", "/playlists/P2/items")] = {"items": _tracks(["TRACK1", "OTHER"], wrap=True)}
        await a.refresh()                                  # sees the new track, then the extras follow
        await asyncio.sleep(0.2)
        self.assertEqual([r["title"] for r in a.state()["history"]], ["TRACK1"])

    async def test_history_empty_without_web_api(self):
        a = self.adapter = self.make()
        await a.start()
        self.assertEqual((a.state()["history"], a.state()["queue"]), ([], []))

    async def test_jump_inside_playlist_context_plays_with_offset(self):
        web = self.web()
        a = self.adapter = self.make(web=web)
        await a.start()
        await a.press("jump", "spotify:track:S5")
        play = self.hits(web, "/me/player/play")[-1]
        self.assertEqual(play[2], {"context_uri": "spotify:playlist:P1",
                                   "offset": {"uri": "spotify:track:S5"}})
        self.assertEqual(self.hits(web, "/me/player/next"), [])

    async def test_jump_to_queue_item_skips_forward(self):
        web = self.web()
        a = self.adapter = self.make(web=web)
        await a.start()
        await a.press("jump", "spotify:track:Q3")           # not in the playlist: third in the queue
        self.assertEqual(len(self.hits(web, "/me/player/next")), 3)
        self.assertEqual(self.hits(web, "/me/player/play"), [])

    async def test_jump_elsewhere_plays_the_track_directly(self):
        web = self.web(ctx=None)
        a = self.adapter = self.make(web=web)
        await a.start()
        await a.press("jump", "spotify:track:R3")
        self.assertEqual(self.hits(web, "/me/player/play")[-1][2], {"uris": ["spotify:track:R3"]})
        self.assertEqual(self.hits(web, "/me/player/next"), [])

    async def test_jump_by_title_and_errors(self):
        web = self.web()
        a = self.adapter = self.make(web=web)
        await a.start()
        await asyncio.sleep(0.2)
        out = await a.run("jump", {"title": "s7"})
        self.assertIn("Jumped", out)
        self.assertEqual(self.hits(web, "/me/player/play")[-1][2]["offset"],
                         {"uri": "spotify:track:S7"})
        with self.assertRaises(AdapterError) as cm:
            await a.run("jump", {"title": "nothing like it"})
        self.assertIn("isn't in the up-next", str(cm.exception))
        with self.assertRaises(AdapterError):
            await a.press("jump", "not-a-uri")
        web.routes[("PUT", "/me/player/play")] = WebError("Spotify has no active device", "http")
        with self.assertRaises(AdapterError):
            await a.press("jump", "spotify:track:S5")

    async def test_jump_without_login_says_so(self):
        a = self.adapter = self.make()
        await a.start()
        with self.assertRaises(AdapterError) as cm:
            await a.press("jump", "spotify:track:S5")
        self.assertIn("Web API isn't authorised", str(cm.exception))


class WebClientTests(unittest.TestCase):
    def test_unauthorised_when_no_file(self):
        import tempfile, pathlib
        from ariadne2.adapters.spotify_web import SpotifyWeb
        with tempfile.TemporaryDirectory() as d:
            w = SpotifyWeb(pathlib.Path(d) / "none.json")
            self.assertFalse(w.available())
            with self.assertRaises(WebError) as cm:
                w.request("GET", "/me/player")
            self.assertEqual(cm.exception.kind, "auth")

    def test_fresh_token_used_without_network_and_refresh_written_back(self):
        import json, os, tempfile, pathlib, time
        from ariadne2.adapters import spotify_web
        with tempfile.TemporaryDirectory() as d:
            path = pathlib.Path(d) / "o.json"
            path.write_text(json.dumps({"refresh_token": "r", "client_id": "c",
                                        "access_token": "old", "expires_at": 0}))
            w = spotify_web.SpotifyWeb(path)
            self.assertTrue(w.available())
            with mock.patch.object(w, "_post_form",
                                   return_value={"access_token": "new", "expires_in": 3600,
                                                 "refresh_token": "r2"}) as post:
                self.assertEqual(w._token(), "new")
                self.assertEqual(w._token(), "new")      # cached now
                self.assertEqual(post.call_count, 1)
            saved = json.loads(path.read_text())
            self.assertEqual((saved["access_token"], saved["refresh_token"]), ("new", "r2"))
            self.assertEqual(oct(os.stat(path).st_mode & 0o777), "0o600")
            self.assertGreater(saved["expires_at"], time.time())


if __name__ == "__main__":
    unittest.main()
