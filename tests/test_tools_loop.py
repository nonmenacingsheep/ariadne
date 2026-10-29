"""The toolset hook in the conversation loop, with a fake model."""
import unittest

from ariadne2.adapters import Adapter, AdapterError, Verb
from ariadne2.core import models
from ariadne2.core.loop import MAX_TOOL_ROUNDS, Conversation
from tests.toolsbase import ToolsCase


class FakeSet:
    def __init__(self, names=("ping", "shot", "boom", "hurt"), ctx="", rounds=None):
        self.names, self.ctx, self.n = names, ctx, rounds
        self.calls = []

    def tools(self):
        return [{"name": n, "description": n, "input_schema": {"type": "object", "properties": {}}} for n in self.names]

    async def call(self, name, args, his_words=None):
        self.calls.append((name, args, his_words))
        if name == "shot":
            return [{"type": "text", "text": "a screenshot"},
                    {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "AAAA"}}]
        if name == "boom":
            raise RuntimeError("secret internals")
        if name == "hurt":
            raise AdapterError("Not done: refused.")
        return f"pong {args.get('x', '')}"

    def context(self):
        return self.ctx

    def rounds(self):
        return self.n


class Model:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    async def __call__(self, system, messages, model, tools=None):
        self.calls.append({"system": system, "messages": messages, "tools": tools})
        for part in self.replies.pop(0):
            yield part


def use(name, id="t1", **inp):
    return models.ToolUse(id, name, inp)


class Spot(Adapter):
    name = "spotify"

    def __init__(self, publish):
        super().__init__(publish)

        async def ping():
            return "adapter ping"
        self.verbs = [Verb("ping", "adapter ping", {}, ping)]


class ToolsetLoop(ToolsCase):
    def make(self, replies, toolsets, **kw):
        self.sent = []

        async def publish(m):
            self.sent.append(m)
        self.model = Model(replies)
        return Conversation(publish, lambda: {}, model=self.model, toolsets=toolsets, **kw)

    async def go(self, c, text="hi"):
        c.submit(text)
        await c.idle()

    def results(self, call_index):
        return self.model.calls[call_index]["messages"][-1]["content"]


class Tests(unittest.IsolatedAsyncioTestCase, ToolsetLoop):
    def setUp(self):
        ToolsCase.setUp(self)

    async def test_call_is_routed_with_his_words_and_result_goes_back(self):
        ts = FakeSet()
        c = self.make([["ok ", use("ping", x="1")], ["done."]], [ts])
        await self.go(c, "please ping")
        self.assertEqual(ts.calls, [("ping", {"x": "1"}, "please ping")])
        r = self.results(1)
        self.assertEqual(r[0]["tool_use_id"], "t1")
        self.assertEqual(r[0]["content"], "pong 1")
        self.assertNotIn("is_error", r[0])
        tool_names = [t["name"] for t in self.model.calls[0]["tools"]]
        self.assertEqual(tool_names, ["ping", "shot", "boom", "hurt"])

    async def test_image_content_blocks_pass_back_to_the_model(self):
        c = self.make([[use("shot")], ["I see it."]], [FakeSet()])
        await self.go(c)
        content = self.results(1)[0]["content"]
        self.assertEqual([b["type"] for b in content], ["text", "image"])
        self.assertEqual(content[1]["source"]["media_type"], "image/png")

    async def test_failures_become_error_results_and_crashes_leak_nothing(self):
        c = self.make([[use("hurt", "a"), use("boom", "b")], ["ok"]], [FakeSet()])
        await self.go(c)
        a, b = self.results(1)
        self.assertEqual((a["is_error"], a["content"]), (True, "Not done: refused."))
        self.assertTrue(b["is_error"])
        self.assertNotIn("secret internals", b["content"])

    async def test_merged_with_adapter_tools_and_clashes_keep_the_adapter(self):
        ts = FakeSet(names=("spotify_ping", "ping"))
        async def quiet(m):
            pass
        c = self.make([[use("spotify_ping"), use("ping", "t2")], ["ok"]], [ts], adapters={"spotify": Spot(quiet)})
        await self.go(c)
        offered = [t["name"] for t in self.model.calls[0]["tools"]]
        self.assertEqual(offered, ["spotify_ping", "ping"])      # the clashing toolset tool is dropped
        a, b = self.results(1)
        self.assertEqual(a["content"], "adapter ping")           # went to the adapter
        self.assertEqual(b["content"], "pong ")                  # the other to the toolset

    async def test_two_toolsets_and_first_wins_on_a_clash(self):
        one, two = FakeSet(names=("ping",)), FakeSet(names=("ping", "shot"))
        c = self.make([[use("ping"), use("shot", "t2")], ["ok"]], [one, two])
        await self.go(c)
        self.assertEqual([t["name"] for t in self.model.calls[0]["tools"]], ["ping", "shot"])
        self.assertEqual((len(one.calls), len(two.calls)), (1, 1))

    async def test_context_is_appended_to_the_system_prompt_only_when_present(self):
        c = self.make([["a"], ["b"]], [FakeSet(ctx="You are in a project: /x")])
        await self.go(c)
        self.assertTrue(self.model.calls[0]["system"].endswith("You are in a project: /x"))
        c = self.make([["a"]], [FakeSet(ctx="")])
        await self.go(c)
        self.assertNotIn("project", self.model.calls[0]["system"])

    async def test_a_toolset_can_extend_the_tool_rounds(self):
        endless = [[use("ping", f"t{i}")] for i in range(MAX_TOOL_ROUNDS + 3)] + [["ok"]]
        c = self.make(endless, [FakeSet()])
        await self.go(c)
        self.assertEqual(len(self.model.calls), MAX_TOOL_ROUNDS + 1)     # default cap, then words only
        self.assertIsNone(self.model.calls[-1]["tools"])
        c = self.make([[use("ping", f"t{i}")] for i in range(12)] + [["ok"]], [FakeSet(rounds=12)])
        await self.go(c)
        self.assertEqual(len(self.model.calls), 13)

    async def test_flow_turns_have_no_words_of_his_behind_them(self):
        ts = FakeSet()
        c = self.make([[use("ping")], ["done"]], [ts])
        await c.flow_turn("morning", "check things", post=False)
        self.assertEqual(ts.calls, [("ping", {}, None)])

    async def test_no_toolsets_changes_nothing(self):
        c = self.make([["just words."]], [])
        await self.go(c)
        self.assertIsNone(self.model.calls[0]["tools"])


class WithRealTools(unittest.IsolatedAsyncioTestCase, ToolsetLoop):
    def setUp(self):
        ToolsCase.setUp(self)

    async def test_general_tools_through_the_loop(self):
        from ariadne2.core.tools import GeneralTools
        f = self.put("note.txt", "buy milk\n")
        c = self.make([[use("read_file", path=str(f)), use("shell", "t2", command="sudo true")], ["ok"]],
                      [GeneralTools()])
        await self.go(c, "what's in my note")
        self.assertEqual(len(self.model.calls[0]["tools"]), 13)
        a, b = self.results(1)
        self.assertIn("buy milk", a["content"])
        self.assertTrue(b["is_error"])
        self.assertIn("won't run that", b["content"])

    async def test_writes_need_a_turn_of_his_own(self):
        from ariadne2.core.tools import GeneralTools
        target = self.path("out.txt")
        c = self.make([[use("write_file", path=str(target), text="x")], ["ok"]], [GeneralTools()])
        await c.flow_turn("f", "write it", post=False)       # no words of his
        self.assertFalse(target.exists())
        c = self.make([[use("write_file", path=str(target), text="x")], ["ok"]], [GeneralTools()])
        await self.go(c, "write x to out.txt")
        self.assertEqual(target.read_text(), "x")


if __name__ == "__main__":
    unittest.main()
