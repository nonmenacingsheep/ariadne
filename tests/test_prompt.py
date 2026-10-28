import datetime
import unittest

from ariadne2.core import prompt

NOW = datetime.datetime(2026, 10, 27, 20, 41)


class PromptTests(unittest.TestCase):
    def test_personality_included(self):
        text = prompt.build("aries", {}, NOW)
        self.assertIn("You are Aries", text)
        self.assertIn("How replies look", text)

    def test_unknown_or_hostile_name_falls_back(self):
        for name in ("nope", "../../etc/passwd", ""):
            self.assertIn("You are Aries", prompt.personality_text(name))

    def test_state_skips_empty_and_unwired(self):
        snaps = {"chat": {"messages": []}, "core": {"x": 1},
                 "spotify": {"status": "no adapter yet"},
                 "steam": {},
                 "system": {"cpu": 12.5, "mem": 41.0}}
        block = prompt.state_block(snaps, NOW)
        self.assertIn("system: cpu 12.5, mem 41", block)
        for gone in ("spotify", "steam", "chat", "core"):
            self.assertNotIn(gone + ":", block)
        self.assertIn("Tuesday 27 October, 20:41", block)

    def test_one_line_per_widget_and_capped(self):
        block = prompt.state_block({"browser": {"tabs": ["x" * 50] * 20}}, NOW)
        line = [l for l in block.splitlines() if l.startswith("browser:")][0]
        self.assertLessEqual(len(line), prompt.LINE_MAX)

    def test_spotify_one_line(self):
        d = {"status": "playing", "title": "Paparazzi X E.T.", "artist": "NovaX",
             "position_s": 80.0, "length_s": 146.0, "updated": NOW.timestamp(), "volume": 40,
             "liked": None, "shuffle": False, "repeat": "off", "queue": []}
        block = prompt.state_block({"spotify": d}, NOW)
        self.assertIn("Spotify: playing Paparazzi X E.T. — NovaX, 1:20/2:26, vol 40", block)
        self.assertNotIn("spotify:", block)
        # the bar keeps moving while playing, and stops when paused
        later = prompt._spotify_line(d, NOW.timestamp() + 10)
        self.assertIn("1:30/2:26", later)
        self.assertIn("1:20/2:26", prompt._spotify_line(dict(d, status="paused"), NOW.timestamp() + 10))
        self.assertEqual(prompt._spotify_line({"status": "not running"}), "Spotify: not running")
        self.assertIn(", liked, shuffle on, repeat track",
                      prompt._spotify_line(dict(d, liked=True, shuffle=True, repeat="track"), NOW.timestamp()))

    def test_she_knows_she_has_spotify_only(self):
        text = prompt.build("aries", {}, NOW)
        self.assertIn("reach Spotify and nothing", text)
        self.assertNotIn("aren't wired in", text)

    def test_size_bound(self):
        text = prompt.build("aries", {"system": {"cpu": 1.0}}, NOW)
        self.assertLess(len(text) // 4, 2000)     # ~tokens, well under 2k


if __name__ == "__main__":
    unittest.main()
