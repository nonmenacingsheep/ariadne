"""Her settings tool: list, get and set, with the panel's checks and two hard lines."""
import tempfile
import unittest
from pathlib import Path

from ariadne2.adapters import AdapterError
from ariadne2.core import settings as S
from ariadne2.core.settings_tool import SettingsTools


class SettingsToolTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.st = S.Settings(path=self.tmp / "settings.json", personality_names=lambda: ["aries"])
        self.sent = []

        async def publish(m):
            self.sent.append(m)
        self.t = SettingsTools(self.st, publish)
        self.hooked = []
        self.st.hooks[("voice", "speed")] = self.hooked.append

    async def call(self, his="change it", **a):
        return await self.t.call("settings", a, his)

    async def test_list_shows_values_and_ranges(self):
        out = await self.call(action="list", section="voice")
        self.assertIn("voice.speed (Speed) = 1x  [0.6 to 1.5x]", out)
        self.assertNotIn("avatar.", out)
        everything = await self.call(action="list")
        self.assertIn("models.anthropic_key (Anthropic API key) = ", everything)
        self.assertIn("[he sets it himself]", everything)

    async def test_set_coerces_checks_applies_and_tells_the_desk(self):
        self.assertEqual(await self.call(action="set", section="voice", key="speed", value="1.2x"),
                         "Speed is now 1.2x.")
        self.assertEqual(self.hooked, [1.2])                         # applied at once
        self.assertEqual(self.sent[-1]["t"], "settings")            # the panel moves too
        out = await self.call(action="set", section="general", key="wake_word", value="off")
        self.assertIn("is now off", out)
        out = await self.call(action="set", section="models", key="conversation_model", value="opus")
        self.assertIn("Opus 5.5", out)
        with self.assertRaises(AdapterError):                         # out of range, as the panel refuses
            await self.call(action="set", section="voice", key="speed", value=9)

    async def test_section_dot_key_works_too(self):
        out = await self.call(action="set", key="voice.sounds_master", value="off")
        self.assertIn("Sound effects is now off", out)
        self.assertIn("Speed", await self.call(action="get", key="voice.speed"))

    async def test_never_without_his_words(self):
        with self.assertRaises(AdapterError):
            await self.call(None, action="set", section="voice", key="speed", value=1.1)
        self.assertEqual(self.st.get("voice", "speed"), 1.0)
        self.assertIn("Speed", await self.call(None, action="get", section="voice", key="speed"))   # reading is fine

    async def test_api_keys_are_off_limits(self):
        with self.assertRaises(AdapterError):
            await self.call(action="set", section="models", key="anthropic_key", value="sk-ant-xxxxxxxx")
        out = await self.call(action="get", section="models", key="anthropic_key")
        self.assertNotIn("sk-", out)

    async def test_unknown_setting(self):
        with self.assertRaises(AdapterError):
            await self.call(action="get", section="voice", key="pitch")


if __name__ == "__main__":
    unittest.main()
