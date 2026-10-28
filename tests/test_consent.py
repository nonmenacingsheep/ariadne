import asyncio
import unittest

from ariadne2.adapters import AdapterError, call_tool, consent
from ariadne2.adapters.base import Adapter, Verb


class ConsentTest(unittest.TestCase):
    def test_his_words_must_ask_and_name_them(self):
        ok = consent.allows_message
        self.assertTrue(ok("can you message Kai this: on at 9", "Kai"))
        self.assertTrue(ok("tell mira thanks for the clip", "Mira"))
        self.assertTrue(ok("dm kai_99 that I'm late", "Kai_99"))
        self.assertTrue(ok("let Kai know I'll be on soon", "Kai"))
        self.assertFalse(ok("what did Kai say?", "Kai"))              # no ask
        self.assertFalse(ok("message Mira that I'm late", "Kai"))     # wrong person
        self.assertFalse(ok("", "Kai"))
        self.assertFalse(ok("send it", None))

    def test_call_tool_refuses_without_his_words(self):
        sent = []

        async def send(person, text):
            sent.append((person, text))
            return "sent"

        class Fake(Adapter):
            name = "discord"

            def __init__(self):
                super().__init__(publish=lambda m: asyncio.sleep(0))
                self.verbs = [Verb("send", "send a DM", {"properties": {"person": {}, "text": {}}}, send, consent="message")]

        adapters = {"discord": Fake()}
        run = lambda words: asyncio.run(call_tool(adapters, "discord_send", {"person": "Kai", "text": "hi"}, his_words=words))
        with self.assertRaises(AdapterError):
            run("anything from Kai?")
        with self.assertRaises(AdapterError):
            run(None)                       # e.g. a flow, or text read from a DM
        self.assertEqual(sent, [])
        self.assertEqual(run("message Kai hi"), "sent")
        self.assertEqual(sent, [("Kai", "hi")])


if __name__ == "__main__":
    unittest.main()
