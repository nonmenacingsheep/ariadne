import unittest

from ariadne2 import adapters
from ariadne2.adapters import Adapter, AdapterError, Verb


class Fake(Adapter):
    name = "steam"
    events = ("download_done",)

    def __init__(self, publish):
        super().__init__(publish)
        self.calls = []

        async def launch(game):
            self.calls.append(game)
            return f"launched {game}"

        async def boom():
            raise AdapterError("no such game, and a very long reason " * 5)

        async def crash():
            raise RuntimeError("secret detail")

        async def silent():
            return ""

        self.verbs = [
            Verb("launch", "Launch a game.", {"properties": {"game": {"type": "string"}},
                                             "required": ["game"]}, launch, "launch"),
            Verb("boom", "Fails.", {}, boom, "go"),
            Verb("crash", "Crashes.", {}, crash),
            Verb("silent", "Returns nothing.", {}, silent),
        ]
        self.controls = {"play": "launch"}

    def press_args(self, control, value):
        return {"game": value}


class BaseTests(unittest.IsolatedAsyncioTestCase):
    def make(self):
        self.sent = []

        async def publish(msg):
            self.sent.append(msg)
        return Fake(publish)

    def phases(self):
        return [(m["phase"], m["verb"]) for m in self.sent if m["t"] == "action"]

    async def test_started_then_done_same_id_and_control(self):
        a = self.make()
        self.assertEqual(await a.run("launch", {"game": "Elden Ring"}), "launched Elden Ring")
        self.assertEqual(self.phases(), [("started", "launch"), ("done", "launch")])
        self.assertEqual(len({m["id"] for m in self.sent}), 1)
        self.assertEqual({m["control"] for m in self.sent}, {"launch"})
        self.assertEqual({m["widget"] for m in self.sent}, {"steam"})

    async def test_ids_differ_between_runs(self):
        a = self.make()
        await a.run("launch", {"game": "a"})
        await a.run("launch", {"game": "b"})
        self.assertEqual(len({m["id"] for m in self.sent}), 2)

    async def test_failure_publishes_failed_with_short_note_then_raises(self):
        a = self.make()
        with self.assertRaises(AdapterError):
            await a.run("boom")
        self.assertEqual(self.phases(), [("started", "boom"), ("failed", "boom")])
        note = self.sent[-1]["note"]
        self.assertTrue(note.startswith("no such game") and len(note) <= 80)

    async def test_crash_becomes_plain_error_without_leaking_detail_to_widget(self):
        a = self.make()
        with self.assertRaises(AdapterError):
            await a.run("crash")
        self.assertEqual(self.sent[-1]["phase"], "failed")
        self.assertNotIn("secret", self.sent[-1]["note"])

    async def test_announce_false_publishes_nothing(self):
        a = self.make()
        await a.run("launch", {"game": "x"}, announce=False)
        with self.assertRaises(AdapterError):
            await a.run("boom", announce=False)
        self.assertEqual(self.sent, [])

    async def test_bad_args_and_unknown_verb_fail_before_animating(self):
        a = self.make()
        with self.assertRaises(AdapterError):
            await a.run("launch", {"nope": 1})
        with self.assertRaises(AdapterError):
            await a.run("missing")
        self.assertEqual(self.sent, [])

    async def test_empty_result_says_done(self):
        self.assertEqual(await self.make().run("silent"), "done")

    async def test_press_maps_control_to_verb_without_animation(self):
        a = self.make()
        self.assertEqual(await a.press("play", "Doom"), "launched Doom")
        self.assertEqual(a.calls, ["Doom"])
        self.assertEqual(self.sent, [])
        self.assertIsNone(await a.press("unmapped"))

    async def test_publish_state(self):
        a = self.make()
        a.state = lambda: {"n": 1}
        await a.publish_state()
        self.assertEqual(self.sent, [{"t": "state", "widget": "steam", "data": {"n": 1}}])

    async def test_emit_reaches_sync_and_async_subscribers_and_survives_errors(self):
        a = self.make()
        got = []

        async def later(name, fields):
            got.append(("async", name, fields))

        def broken(name, fields):
            raise ValueError("x")

        a.subscribe(broken)
        a.subscribe(lambda n, f: got.append(("sync", n, f)))
        a.subscribe(later)
        a.emit("download_done", game="g")
        import asyncio
        await asyncio.sleep(0)
        self.assertIn(("sync", "steam.download_done", {"game": "g"}), got)
        self.assertIn(("async", "steam.download_done", {"game": "g"}), got)


class RegistryTests(unittest.IsolatedAsyncioTestCase):
    async def test_tool_naming_and_schema(self):
        reg = {"steam": Fake(None)}
        tools = adapters.tools(reg)
        self.assertEqual([t["name"] for t in tools], ["steam_launch", "steam_boom",
                                                       "steam_crash", "steam_silent"])
        t = tools[0]
        self.assertNotIn(".", t["name"])
        self.assertEqual(t["input_schema"], {"type": "object",
                                             "properties": {"game": {"type": "string"}},
                                             "required": ["game"]})
        self.assertEqual(tools[1]["input_schema"], {"type": "object", "properties": {}})

    async def test_call_tool_dispatches_through_run(self):
        sent = []

        async def publish(m):
            sent.append(m)
        reg = {"steam": Fake(publish)}
        self.assertEqual(await adapters.call_tool(reg, "steam_launch", {"game": "Hades"}),
                         "launched Hades")
        self.assertEqual([m["phase"] for m in sent], ["started", "done"])
        with self.assertRaises(AdapterError):
            await adapters.call_tool(reg, "steam_nothing", {})
        with self.assertRaises(AdapterError):
            await adapters.call_tool(reg, "spotify_next", None)

    def test_load_adapters_builds_spotify_with_expected_tools(self):
        reg = adapters.load_adapters(None)
        self.assertEqual(list(reg), ["spotify"])
        names = {t["name"] for t in adapters.tools(reg)}
        self.assertEqual(names, {"spotify_" + v for v in
                                 "play pause next prev volume queue like playlist seek".split()})
        self.assertEqual(adapters.load_adapters(None, only=[]), {})


if __name__ == "__main__":
    unittest.main()
