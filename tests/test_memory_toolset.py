import asyncio
import tempfile
import time
import unittest
from pathlib import Path

from ariadne2.adapters import AdapterError
from ariadne2.core.loop import Conversation
from ariadne2.core.memory import Facts, MemoryToolset, Talk
from ariadne2.core.memory.toolset import CONTEXT_CHARS
from tests.memfakes import FakeEmbed
from tests.test_loop import FakeModel

NOW = "2026-10-29"
T0 = time.mktime((2026, 10, 3, 12, 0, 0, 0, 0, -1))      # "3 Oct"
T_NOW = time.mktime((2026, 10, 29, 12, 0, 0, 0, 0, -1))


class Base(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = Path(self.tmp.name)
        emb = FakeEmbed()
        self.facts = Facts(d / "facts.jsonl", embed=emb)
        self.talk = Talk(d / "transcript.jsonl", embed=emb)
        self.m = MemoryToolset(self.facts, self.talk, now=NOW)

    async def call(self, name, args, words="I use opera now"):
        return await self.m.call(name, args, words)


class ToolTests(Base):
    async def test_tools_listed(self):
        names = [t["name"] for t in self.m.tools()]
        self.assertEqual(names, ["remember", "forget", "recall"])
        rem = self.m.tools()[0]["input_schema"]["properties"]
        for k in ("text", "kind", "because", "replaces", "rejected"):
            self.assertIn(k, rem)

    async def test_refused_without_his_words(self):
        await self.call("remember", {"text": "likes jazz", "kind": "preference"}, "I like jazz")
        for words in (None, ""):
            with self.assertRaises(AdapterError):
                await self.m.call("remember", {"text": "likes tea", "kind": "preference"}, words)
            with self.assertRaises(AdapterError):
                await self.m.call("forget", {"id": 1}, words)
        self.assertEqual(len(self.facts.all()), 1)                  # nothing saved, nothing forgotten
        self.assertIn("likes jazz", await self.m.call("recall", {"query": "jazz"}, None))   # reading is fine

    async def test_remember_saves_and_hints_closest(self):
        self.facts.add("uses Firefox as his browser", "preference", date="2026-09-02")
        out = await self.call("remember", {"text": "uses Opera GX as his browser", "kind": "preference",
                                           "because": "Discord's web client works better in it"},
                              "I switched to opera gx as my browser")
        self.assertIn("saved #2 (preference, 2026-10-29)", out)
        self.assertIn("#1 'uses Firefox as his browser' (2026-09-02): same subject?", out)
        rec = self.facts.get(2)
        self.assertEqual(rec["source"], "said in chat")
        self.assertEqual(self.facts.get(1)["status"], "current")     # she decides; nothing replaced yet
        # she decides: same text + replaces settles it without a duplicate
        out = await self.call("remember", {"text": "uses Opera GX as his browser", "kind": "preference",
                                           "replaces": 1})
        self.assertIn("linked #2 as replacing #1", out)
        self.assertEqual((self.facts.get(1)["status"], self.facts.get(2)["replaces"]), ("replaced", 1))
        self.assertEqual(len(self.facts.all()), 2)

    async def test_remember_with_replaces_directly(self):
        self.facts.add("uses Firefox as his browser", "preference")
        out = await self.call("remember", {"text": "prefers Opera GX", "kind": "preference", "replaces": "#1"})
        self.assertIn("#1 is now marked replaced", out)
        self.assertNotIn("#1 '", out)               # the one it replaced isn't offered as a "same subject"

    async def test_inferred_source_and_errors(self):
        await self.call("remember", {"text": "tends to work late", "kind": "fact"}, "ok, thanks")
        self.assertEqual(self.facts.get(1)["source"], "inferred by her")
        with self.assertRaises(AdapterError):
            await self.call("remember", {"text": "x", "kind": "bogus"})
        with self.assertRaises(AdapterError):
            await self.call("remember", {"text": "x y", "kind": "fact", "replaces": 40})
        with self.assertRaises(AdapterError):
            await self.call("forget", {"id": 40})

    async def test_credentials_never_saved(self):
        key = "ghp_" + "a1B2c3D4e5" * 3
        out = await self.call("remember", {"text": f"his github token is {key}", "kind": "fact"})
        self.assertIn("credential was removed", out)
        self.assertNotIn(key, str(self.facts.all()))

    async def test_forget_and_recall_history(self):
        await self.call("remember", {"text": "uses Firefox as his browser", "kind": "preference"})
        await self.call("remember", {"text": "uses Opera GX as his browser", "kind": "preference",
                                     "because": "Discord works better", "replaces": 1})
        plain = await self.call("recall", {"query": "which browser"})
        self.assertIn("#2", plain)
        self.assertNotIn("Firefox", plain)
        hist = await self.call("recall", {"query": "which browser", "history": True})
        self.assertIn("#1 uses Firefox", hist)
        self.assertIn("->", hist)
        self.assertIn("because Discord works better", hist)
        self.assertIn("forgot #2", await self.call("forget", {"id": 2}))
        self.assertEqual(await self.call("recall", {"query": "elden ring"}), "nothing I remember matches that.")

    async def test_recall_includes_old_conversations_as_past(self):
        self.talk.append("user", "the tea bench kettle keeps tripping the breaker", T0)
        out = await self.call("recall", {"query": "tea bench kettle"})
        self.assertIn('on 3 Oct (3 weeks ago) you said: "the tea bench kettle', out)


class ContextTests(Base):
    def test_relevant_newest_and_old_talk(self):
        self.facts.add("uses Opera GX as his browser", "preference", date="2026-10-01")
        self.facts.add("keeps a dog called Birdie", "fact", date="2026-09-01")
        self.facts.add("working on the tea bench", "event", date="2026-10-08")
        self.facts.add("plays Elden Ring", "fact", date="2026-10-27")
        self.facts.add("likes oolong", "preference", date="2026-10-28")
        self.facts.add("owns a 4070", "fact", date="2026-10-29")
        self.talk.append("user", "the tea bench kettle keeps tripping the breaker", T0)
        self.m.turn("how is the tea bench kettle doing")
        ctx = self.m.context()
        self.assertIn("working on the tea bench", ctx)
        self.assertIn("happened 3 weeks ago", ctx)                  # an old event is worded as past
        self.assertIn("Newest:", ctx)
        for newest in ("owns a 4070", "likes oolong", "plays Elden Ring"):
            self.assertIn(newest, ctx)
        self.assertNotIn("Birdie", ctx)                             # not relevant, not newest
        self.assertIn('on 3 Oct (3 weeks ago) you said: "the tea bench kettle', ctx)

    def test_what_bore_on_an_earlier_turn_stays_in_view(self):
        # She used a memory one turn; the next turn's block left it out, and she
        # told him she'd made it up. It stays, under its own heading.
        self.facts.add("keeps a dog called Birdie", "fact", date="2026-09-01")
        for i in range(4):
            self.facts.add(f"owns a gadget number {i}", "fact", date="2026-10-2" + str(i))
        self.m.turn("how is my dog Birdie")
        self.assertIn("Birdie", self.m.context())
        self.m.turn("propose some automations")
        ctx = self.m.context()
        self.assertIn("Came up earlier in this talk:", ctx)
        self.assertIn("Birdie", ctx)

    def test_replaced_and_empty(self):
        self.assertEqual(self.m.context(), "")
        self.facts.add("uses Firefox", "preference")
        self.facts.add("uses Opera GX", "preference", replaces=1)
        self.m.turn("which browser")
        ctx = self.m.context()
        self.assertIn("Opera GX", ctx)
        self.assertNotIn("Firefox", ctx)

    def test_talk_already_in_the_thread_is_left_out(self):
        self.talk.append("user", "the tea bench kettle keeps tripping the breaker", T0)
        self.m.on_turn("a new tea bench kettle question", "a reply about it", T_NOW)
        self.m.turn("tea bench kettle")
        ctx = self.m.context()
        self.assertIn("breaker", ctx)                    # from before this run's thread
        self.assertNotIn("a new tea bench kettle question", ctx)
        self.assertIn("a new tea bench kettle question", str(self.talk.rows()))

    def test_size_bound(self):
        for i in range(120):
            self.facts.add(f"tea bench note {i} " + "words about the kettle " * 8, "fact" if i % 2 else "event",
                           date=f"2026-10-{1 + i % 28:02d}", because="reason " * 20,
                           rejected=[f"option {i} -- " + "long reason " * 10])
        for i in range(60):
            self.talk.append("user", f"tea bench kettle conversation {i} " + "blah " * 100, T0 + i)
        self.m.turn("tea bench kettle")
        ctx = self.m.context()
        self.assertTrue(ctx)
        self.assertLessEqual(len(ctx), CONTEXT_CHARS + 200)
        self.assertLess(len(ctx) // 4, 600)

    def test_decision_brings_its_rejected_options(self):
        self.facts.add("uses Opera GX as his browser", "decision", date="2026-10-01",
                       rejected=["Firefox -- Discord's web client is flaky"])
        self.m.turn("should I switch to Firefox")
        self.assertIn("turned down: Firefox -- Discord's web client is flaky", self.m.context())


class LoopHookTests(unittest.IsolatedAsyncioTestCase):
    async def test_on_turn_and_turn_hooks(self):
        seen, told = [], []

        class Spy:
            def tools(self): return []
            async def call(self, *a, **k): return ""
            def turn(self, text): told.append(text)
            def context(self): return "## spy"

        sent = []

        async def publish(msg): sent.append(msg)
        c = Conversation(publish, model=FakeModel([["Sure thing.", ], ["Nice."]]), toolsets=[Spy()],
                         on_turn=lambda u, r, w: seen.append((u, r, w)))
        before = time.time()
        c.submit("hello there")
        await c.idle()
        c.submit("[he dropped a file]", his_words=False)
        await c.idle()
        self.assertEqual(told, ["hello there", "[he dropped a file]"])
        self.assertEqual(len(seen), 1)                              # not for the dropped file
        self.assertEqual(seen[0][:2], ("hello there", "Sure thing."))
        self.assertGreaterEqual(seen[0][2], before)


if __name__ == "__main__":
    unittest.main()
