import io
import json
import os
import tempfile
import unittest
import urllib.error
from unittest import mock

from ariadne2.core.voice import cartesia as c

UUID = "a7beff01-8f8b-4809-bfe6-e2166e57e0c2"


class Env(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patch = mock.patch.dict(os.environ, {"XDG_DATA_HOME": self.tmp.name}, clear=False)
        patch.start()
        self.addCleanup(patch.stop)
        os.environ.pop("CARTESIA_API_KEY", None)
        os.environ.pop("CARTESIA_DICT_ID", None)

    def write_key(self, text):
        d = os.path.join(self.tmp.name, "ariadne")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "cartesia_key"), "w") as f:
            f.write(text)


class Key(Env):
    def test_none_when_missing(self):
        self.assertIsNone(c.key())

    def test_file_is_read_from_the_1x_location(self):
        self.write_key("  from-file\n")
        self.assertEqual(c.key(), "from-file")
        self.assertTrue(str(c.key_path()).endswith("ariadne/cartesia_key"))

    def test_env_wins(self):
        self.write_key("from-file")
        os.environ["CARTESIA_API_KEY"] = "from-env"
        self.assertEqual(c.key(), "from-env")

    def test_blank_file_is_no_key(self):
        self.write_key("\n")
        self.assertIsNone(c.key())


class Body(Env):
    def test_voice_resolution(self):
        self.assertEqual(c.resolve_voice(UUID), UUID)
        self.assertEqual(c.resolve_voice("Skylar"), c.DEFAULT_ID)
        self.assertEqual(c.resolve_voice("bf_emma"), c.DEFAULT_ID)    # a local name must not mean silence
        self.assertEqual(c.resolve_voice(None), c.DEFAULT_ID)

    def test_speed_and_emotion_live_in_generation_config(self):
        b = c.build_body("hi", UUID, speed=2.0, emotion="sarcastic")
        self.assertEqual(b["generation_config"], {"speed": 1.5, "emotion": "sarcastic"})
        self.assertNotIn("speed", b)
        self.assertEqual(b["output_format"]["encoding"], "pcm_s16le")

    def test_neutral_and_unknown_emotion_are_not_sent(self):
        self.assertNotIn("emotion", c.build_body("hi", UUID, 1.0, "neutral")["generation_config"])
        self.assertNotIn("emotion", c.build_body("hi", UUID, 1.0, "grumpy")["generation_config"])

    def test_pronunciations_whole_words_only(self):
        t = {"aries": "ɛ|r|iː|z"}
        self.assertEqual(c.with_pronunciations("Hey Aries! Ariesx", t), "Hey <<ɛ|r|iː|z>>! Ariesx")


class Request(Env):
    class Reply(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def test_posts_with_the_key_and_returns_pcm(self):
        os.environ["CARTESIA_API_KEY"] = "sekrit"
        seen = {}

        def fake(request, timeout):
            seen["auth"] = request.get_header("Authorization")
            seen["body"] = json.loads(request.data)
            seen["url"] = request.full_url
            return self.Reply(b"\x01\x00" * 10)

        pcm, rate = c.synthesize_pcm("hello there", UUID, 1.0, "calm", urlopen=fake)
        self.assertEqual((len(pcm), rate), (20, 24000))
        self.assertEqual(seen["auth"], "Bearer sekrit")
        self.assertTrue(seen["url"].endswith("/tts/bytes"))
        self.assertEqual(seen["body"]["transcript"], "hello there")

    def test_no_key_is_fatal_and_does_not_leak(self):
        with self.assertRaises(c.TTSError) as cm:
            c.synthesize_pcm("hi", urlopen=lambda *a, **k: self.fail("no request without a key"))
        self.assertTrue(cm.exception.fatal)

    def test_empty_text_makes_no_request(self):
        self.assertEqual(c.synthesize_pcm("  ", urlopen=lambda *a, **k: self.fail("x")), (b"", 24000))

    def test_refused_key_is_fatal_and_message_has_no_key(self):
        os.environ["CARTESIA_API_KEY"] = "sekrit"

        def fake(request, timeout):
            raise urllib.error.HTTPError(request.full_url, 401, "no", {}, io.BytesIO(b"bad"))

        with self.assertRaises(c.TTSError) as cm:
            c.synthesize_pcm("hi", urlopen=fake)
        self.assertTrue(cm.exception.fatal)
        self.assertNotIn("sekrit", str(cm.exception))

    def test_server_and_network_errors_are_transient(self):
        os.environ["CARTESIA_API_KEY"] = "k"

        def five(request, timeout):
            raise urllib.error.HTTPError(request.full_url, 503, "x", {}, io.BytesIO(b"down"))

        def down(request, timeout):
            raise urllib.error.URLError("unreachable")

        def slow(request, timeout):
            raise TimeoutError("timed out")

        for fake in (five, down, slow):
            with self.assertRaises(c.TTSError) as cm:
                c.synthesize_pcm("hi", urlopen=fake)
            self.assertFalse(cm.exception.fatal)


if __name__ == "__main__":
    unittest.main()
