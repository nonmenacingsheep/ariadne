import asyncio
import os
import tempfile
import threading
import unittest

import gi
gi.require_version("GLib", "2.0")
from gi.repository import GLib

from ariadne2 import protocol
from ariadne2.core.server import CoreServer
from ariadne2.desk.link import CoreLink


class ServerThread:
    """CoreServer on its own asyncio loop so the GLib loop can stay in the test thread."""

    def __init__(self, path):
        self.path = path
        self.loop = asyncio.new_event_loop()
        self.server = CoreServer(demo=True, path=path)
        self.ready = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self.server.start())
        self.ready.set()
        self.loop.run_forever()

    def start(self):
        self.thread.start()
        assert self.ready.wait(5)

    def call(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(5)

    def stop(self):
        self.call(self.server.stop())
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(5)
        self.loop.close()


def run_until(pred, timeout=5.0):
    loop = GLib.MainLoop()
    ctx = loop.get_context()
    timed_out = []

    def tick():
        if pred():
            loop.quit()
            return False
        return True
    GLib.timeout_add(20, tick)
    GLib.timeout_add(int(timeout * 1000), lambda: (timed_out.append(1), loop.quit(), False)[2])
    loop.run()
    return not timed_out


class LinkTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.sock = os.path.join(self.tmp.name, "core.sock")
        self.srv = ServerThread(self.sock)
        self.srv.start()
        self.msgs, self.status = [], []
        self.link = CoreLink(self.msgs.append, self.status.append, path=self.sock)
        self.addCleanup(self.link.stop)

    def test_connect_receive_send_and_reconnect(self):
        self.link.start()
        self.assertTrue(run_until(lambda: len([m for m in self.msgs if m["t"] == "state"]) >= 10))
        self.assertEqual(self.status[0], "connected")
        self.assertEqual(self.msgs[0]["t"], "hello")

        # desk -> core: a press comes back as demo activity
        self.assertTrue(self.link.send(protocol.press("spotify", "next")))
        self.assertTrue(run_until(
            lambda: any(m["t"] == "action" and m["phase"] == "started" for m in self.msgs)))

        # core goes away -> reconnecting
        self.srv.stop()
        self.assertTrue(run_until(lambda: "reconnecting" in self.status))
        self.assertFalse(self.link.send(protocol.press("spotify", "next")))

    def test_reconnects_when_core_comes_back(self):
        self.srv.stop()
        self.link.start()
        self.assertTrue(run_until(lambda: "reconnecting" in self.status))
        self.srv = ServerThread(self.sock)
        self.srv.start()
        self.addCleanup(self.srv.stop)
        self.assertTrue(run_until(lambda: "connected" in self.status, timeout=8))

    def test_send_before_start_is_dropped(self):
        self.assertFalse(self.link.send(protocol.press("spotify", "next")))
        self.srv.stop()


if __name__ == "__main__":
    unittest.main()
