import asyncio
import unittest

from ariadne2.adapters import AdapterError
from ariadne2.core.clipboard import MAX_TEXT, ClipboardTools


class Clipboard(unittest.TestCase):
    def setUp(self):
        self.board = {"text": "def f(x):\n    return x * 2\n"}
        self.written = []
        self.c = ClipboardTools(read=lambda: dict(self.board), write=self.written.append)

    def call(self, words="take what's in my clipboard", **a):
        return asyncio.run(self.c.call("clipboard", a, words))

    def test_read_is_quoted_content(self):
        out = self.call(action="read")
        self.assertIn("return x * 2", out)
        self.assertIn("his clipboard", out)                   # framed as content, not instructions

    def test_read_scrubs_credentials_and_cuts_long_text(self):
        self.board = {"text": "token = ghp_" + "a" * 36}
        self.assertNotIn("ghp_" + "a" * 36, self.call(action="read"))
        self.board = {"text": "x" * (MAX_TEXT + 50)}
        self.assertIn("cut:", self.call(action="read"))

    def test_a_copied_picture_comes_back_as_an_image(self):
        self.board = {"png": b"\x89PNG fake"}
        out = self.call(action="read")
        self.assertEqual(out[0]["type"], "image")

    def test_write_needs_his_words(self):
        self.assertIn("ready to paste", self.call(action="write", text="hello"))
        self.assertEqual(self.written, ["hello"])
        with self.assertRaises(AdapterError):
            self.call(words=None, action="write", text="from a flow")
        self.assertEqual(self.written, ["hello"])

    def test_empty(self):
        self.board = {}
        self.assertIn("empty", self.call(action="read"))
