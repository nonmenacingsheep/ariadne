import asyncio
import json
import os
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
        self.procs = [("100", "python main.py --listen 8188", "9-1"), ("200", "/usr/bin/bwrap -- steam", None)]
        self.ports = set()
        l = Later(lambda text, consent: self.woke.append((text, consent)), downloads=self.dl, path=self.path,
                  clock=lambda: self.t[0], alive=lambda pid: self.alive.get(pid, False),
                  procs=lambda: self.procs, port_open=lambda port: port in self.ports)

        async def sleep(s):                          # (a `wait` second passes at once)
            self.t[0] += s
        l.sleep = sleep
        return l

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


    def test_a_job_by_its_tag_and_how_long_it_took(self):
        self.assertIn("job 9-1 ends", self.call(action="set", note="read the render", when="job_done", job="9-1"))
        self.tick(5)
        self.assertEqual(self.woke, [])
        self.procs = [p for p in self.procs if p[2] != "9-1"]   # it, and anything it started, ended
        self.tick(200)
        self.assertIn("job has finished", self.woke[-1][0])
        self.assertIn("took 3 min 25 s", self.woke[-1][0])

    def test_a_file_fires_once_it_stops_growing(self):
        f = Path(self.tmp.name) / "song.flac"
        self.call(action="set", note="play it", when="file_ready", path=str(f))
        self.tick(30)
        self.assertEqual(self.woke, [])                   # not there yet
        f.write_bytes(b"x" * 1000)
        self.tick(5)
        f.write_bytes(b"x" * 5000)
        self.tick(5)
        self.assertEqual(self.woke, [])                   # still being written
        self.tick(5)
        self.tick(6)
        self.assertIn("stopped growing", self.woke[-1][0])

    def test_a_log_line_a_process_and_a_port(self):
        log = Path(self.tmp.name) / "install.log"
        log.write_text("Collecting torch\n")
        self.call(action="set", note="launch the gui", when="log_says", path=str(log), match=r"FIX_DONE|error")
        self.call(action="set", note="say it's closed", when="process_gone", match="steam")
        self.call(action="set", note="open the page", when="port_open", port=7865)
        self.tick(5)
        self.assertEqual(self.woke, [])
        with open(log, "a") as fh:
            fh.write("Installing...\nFIX_DONE cuda True\n")
        self.procs = self.procs[:1]
        self.ports.add(7865)
        self.tick(5)
        said = " ".join(w[0] for w in self.woke)
        self.assertIn("says: FIX_DONE cuda True", said)
        self.assertIn("Nothing matching 'steam'", said)
        self.assertIn("Port 7865 answers", said)

    def test_already_done_says_so_instead_of_setting_one(self):
        self.assertIn("No need to wait", self.call(action="set", note="x", when="process_up", match="listen 8188"))
        self.assertIn("No need to wait", self.call(action="set", note="x", when="job_done", job="1-404"))
        self.assertEqual(self.l.pending, [])

    def test_wait_holds_the_turn_until_it_happens_or_two_minutes(self):
        async def comes_up():
            await asyncio.sleep(0)
        self.ports = set()
        orig = self.l.sleep

        async def sleep(s):
            await orig(s)
            if self.t[0] >= 1_000_000 + 7:
                self.ports.add(8080)
        self.l.sleep = sleep
        out = self.call(action="wait", when="port_open", port=8080)
        self.assertIn("Port 8080 answers", out)
        self.assertIn("after 7 s", out)
        out = self.call(action="wait", when="process_up", match="blender", minutes=30)
        self.assertIn("Not yet after 2 min 00 s", out)    # capped: a long one is a check-in
        self.assertEqual(self.woke, [])
        with self.assertRaises(AdapterError):
            self.call(action="wait", when="time", minutes=1)

    def test_a_limit_hit_says_how_it_is_moving(self):
        log = Path(self.tmp.name) / "dl.log"
        log.write_text("x" * 100)
        self.call(action="set", note="x", when="log_says", path=str(log), match="DONE", minutes=1)
        log.write_text("x" * 5000)
        self.tick(61)
        self.assertIn("hasn't happened yet", self.woke[-1][0])
        self.assertIn("more than when you set it", self.woke[-1][0])


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
