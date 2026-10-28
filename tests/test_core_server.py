import asyncio
import os
import tempfile
import unittest

from ariadne2 import protocol
from ariadne2.core.server import CoreServer

T = 3.0


class Client:
    def __init__(self, reader, writer):
        self.r, self.w = reader, writer

    @classmethod
    async def connect(cls, path):
        return cls(*await asyncio.open_unix_connection(path))

    async def recv(self):
        return protocol.decode(await asyncio.wait_for(self.r.readline(), T))

    async def recv_until(self, pred):
        while True:
            m = await self.recv()
            if pred(m):
                return m

    def send(self, msg):
        self.w.write(protocol.encode(msg))

    async def close(self):
        self.w.close()
        await self.w.wait_closed()


class ServerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.sock = os.path.join(self.tmp.name, "run", "core.sock")
        self.server = CoreServer(demo=True, path=self.sock)
        await self.server.start()
        self.addAsyncCleanup(self.server.stop)

    async def connect(self):
        c = await Client.connect(self.sock)
        self.addAsyncCleanup(c.close)
        return c

    async def test_catch_up(self):
        c = await self.connect()
        self.assertEqual((await c.recv())["side"], "core")
        states = [await c.recv() for _ in protocol.WIDGETS]
        self.assertEqual([m["t"] for m in states], ["state"] * len(protocol.WIDGETS))
        self.assertEqual({m["widget"] for m in states}, set(protocol.WIDGETS))
        by = {m["widget"]: m["data"] for m in states}
        self.assertEqual(by["chat"], {"messages": []})
        self.assertEqual(by["spotify"], {"status": "no adapter yet"})
        self.assertEqual(set(by["system"]), {"cpu", "mem", "mem_used_gb", "mem_total_gb"})
        line = await c.recv()
        self.assertEqual(line["t"], "line")
        self.assertEqual(line["text"], "")

    async def test_socket_dir_private_and_removed_on_stop(self):
        self.assertEqual(os.stat(os.path.dirname(self.sock)).st_mode & 0o777, 0o700)
        await self.server.stop()
        self.assertFalse(os.path.exists(self.sock))
        await self.server.start()      # asyncCleanup stops again

    async def test_stale_socket_replaced(self):
        await self.server.stop()
        open(self.sock, "w").close()
        await self.server.start()
        c = await self.connect()
        self.assertEqual((await c.recv())["t"], "hello")

    async def test_press_gives_started_then_done(self):
        c = await self.connect()
        c.send(protocol.press("spotify", "next"))
        a = await c.recv_until(lambda m: m["t"] == "action")
        self.assertEqual((a["widget"], a["phase"], a["control"]), ("spotify", "started", "next"))
        b = await c.recv_until(lambda m: m["t"] == "action")
        self.assertEqual((b["id"], b["phase"]), (a["id"], "done"))

    async def test_text_echo(self):
        c = await self.connect()
        c.send(protocol.text("chat", "abcdef"))
        you = await c.recv_until(lambda m: m["t"] == "chat")
        self.assertEqual((you["role"], you["delta"], you["done"]), ("you", "abcdef", True))
        deltas = [await c.recv_until(lambda m: m["t"] == "chat") for _ in range(3)]
        self.assertTrue(all(d["role"] == "aries" and d["id"] == deltas[0]["id"] for d in deltas))
        self.assertEqual([d["done"] for d in deltas], [False, False, True])
        self.assertEqual("".join(d["delta"] for d in deltas), "heard: abcdef")

    async def test_publish_reaches_all_and_updates_snapshot(self):
        a, b = await self.connect(), await self.connect()
        for c in (a, b):
            await c.recv_until(lambda m: m["t"] == "line")
        await self.server.publish(protocol.state("steam", {"games": 3}))
        for c in (a, b):
            m = await c.recv()
            self.assertEqual((m["widget"], m["data"]), ("steam", {"games": 3}))
        late = await self.connect()
        got = {}
        for _ in range(12):
            m = await late.recv()
            if m["t"] == "state":
                got[m["widget"]] = m["data"]
        self.assertEqual(got["steam"], {"games": 3})

    async def test_bad_line_keeps_connection(self):
        c = await self.connect()
        await c.recv_until(lambda m: m["t"] == "line")
        c.w.write(b"not json\n")
        c.w.write(b'{"t":"press","widget":"nope","control":"x"}\n')
        c.send(protocol.press("steam", "go"))
        a = await c.recv_until(lambda m: m["t"] == "action")
        self.assertEqual(a["widget"], "steam")

    async def test_disconnect_does_not_affect_others(self):
        a, b = await self.connect(), await self.connect()
        await a.close()
        await asyncio.sleep(0.05)
        await self.server.publish(protocol.core_line("still here"))
        m = await b.recv_until(lambda m: m["t"] == "line" and m["text"] == "still here")
        self.assertEqual(m["text"], "still here")

    async def test_hook_called(self):
        seen = []
        self.server.on_desk_message = seen.append
        c = await self.connect()
        c.send(protocol.press("steam", "go"))
        await c.recv_until(lambda m: m["t"] == "action")
        self.assertEqual(seen[0]["control"], "go")


class NoDemo(unittest.IsolatedAsyncioTestCase):
    async def test_press_ignored_without_demo(self):
        with tempfile.TemporaryDirectory() as d:
            sock = os.path.join(d, "s")
            server = CoreServer(path=sock)
            await server.start()
            try:
                c = await Client.connect(sock)
                await c.recv_until(lambda m: m["t"] == "line")
                c.send(protocol.press("steam", "go"))
                with self.assertRaises(asyncio.TimeoutError):
                    await asyncio.wait_for(c.r.readline(), 0.3)
                await c.close()
            finally:
                await server.stop()


if __name__ == "__main__":
    unittest.main()
