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

    def test_size_bound(self):
        text = prompt.build("aries", {"system": {"cpu": 1.0}}, NOW)
        self.assertLess(len(text) // 4, 2000)     # ~tokens, well under 2k


if __name__ == "__main__":
    unittest.main()
