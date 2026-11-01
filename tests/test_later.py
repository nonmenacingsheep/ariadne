import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from ariadne2.adapters import AdapterError
from ariadne2.core.later import Later


class FakeDownloads:
    def __init__(self):
        self.going = True

    def active(self):
        return self.going


class CheckIns(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "later.json"
        self.t = [1_000_000.0]
        self.woke = []
        self.alive = {4242: True}
        self.dl = FakeDownloads()
        self.l = self.make()

    def make(self):
        return Later(lambda text, consent: self.woke.append((text, consent)), downloads=self.dl, path=self.path,
                     clock=lambda: self.t[0], alive=lambda pid: self.alive.get(pid, False))

    def call(self, **a):
        return asyncio.run(self.l.call("later", a, "install yue2 and make a test song"))

    def tick(self, seconds):
        self.t[0] += seconds
        asyncio.run(self.l.tick())

    def test_time_fires_once_with_his_words(self):
        self.assertIn("#1", self.call(action="set", note="check the YuE2 log", when="time", minutes=2))
        self.tick(60)
        self.assertEqual(self.woke, [])
        self.tick(61)
        self.assertEqual(len(self.woke), 1)
        self.assertIn("check the YuE2 log", self.woke[0][0])
        self.assertEqual(self.woke[0][1], "install yue2 and make a test song")   # what he asked still counts
        self.tick(600)
        self.assertEqual(len(self.woke), 1)

    def test_downloads_done_and_job_done_fire_early(self):
        self.call(action="set", note="run the test song", when="downloads_done", minutes=60)
        self.call(action="set", note="read install.log", when="job_done", pid=4242, minutes=60)
        self.tick(30)
        self.assertEqual(self.woke, [])
        self.dl.going = False
        self.tick(5)
        self.assertIn("downloads have finished", self.woke[-1][0])
        self.alive[4242] = False
        self.tick(5)
        self.assertIn("command has finished", self.woke[-1][0])
        self.assertEqual(self.l.pending, [])

    def test_a_restart_keeps_them_and_list_cancel(self):
        self.call(action="set", note="a", minutes=10)
        self.call(action="set", note="b", minutes=10)
        self.l = self.make()                                       # a restart
        self.assertIn("#2", self.call(action="list"))
        self.call(action="cancel", id=1)
        self.assertEqual([p["note"] for p in json.loads(self.path.read_text())], ["b"])
        with self.assertRaises(AdapterError):
            self.call(action="set", note="", minutes=1)
        with self.assertRaises(AdapterError):
            self.call(action="set", note="x", when="job_done")


class WakeTurn(unittest.IsolatedAsyncioTestCase):
    async def test_a_check_in_is_her_turn_with_his_earlier_words(self):
        from ariadne2.core.loop import Conversation
        from tests.test_loop import FakeModel
        sent = []

        async def publish(m):
            sent.append(m)
        model = FakeModel([["Done, the song's in outputs."]])
        c = Conversation(publish, model=model)
        c.wake("[Check-in you set at 17:10: \"run the test song\". It's 17:20.]", "make a test song")
        await c.idle()
        self.assertFalse(any(m.get("role") == "you" for m in sent if m["t"] == "chat"))   # no bubble of his
        self.assertEqual(c._his_words, "make a test song")
        self.assertIn("Done", c.history[-1]["content"])
