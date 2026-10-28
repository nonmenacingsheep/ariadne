import asyncio
import unittest

from ariadne2.core import models
from ariadne2.core.loop import Conversation, SentenceSplitter


def split(*deltas):
    s = SentenceSplitter()
    out = []
    for d in deltas:
        out += s.feed(d)
    return out, s.flush()


class SplitterTests(unittest.TestCase):
    def test_sentences_across_deltas(self):
        done, rest = split("Hello the", "re. How are", " you? Fine")
        self.assertEqual(done, ["Hello there.", "How are you?"])
        self.assertEqual(rest, ["Fine"])

    def test_end_punctuation_waits_for_space(self):
        done, rest = split("It is 3.5", " degrees. ok")
        self.assertEqual(done, ["It is 3.5 degrees."])
        self.assertEqual(rest, ["ok"])

    def test_newline_and_quotes_and_ellipsis(self):
        done, rest = split('she said "no." Then\nleft… and', " gone!\n")
        self.assertEqual(done, ['she said "no."', "Then", "left…", "and gone!"])
        self.assertEqual(rest, [])

    def test_final_period_flushes(self):
        done, rest = split("Done.")
        self.assertEqual((done, rest), ([], ["Done."]))


class FakeModel:
    def __init__(self, replies, gate=None):
        self.replies = list(replies)
        self.calls = []
        self.gate = gate

    async def __call__(self, system, messages, model):
        self.calls.append((system, messages, model))
        if self.gate is not None and len(self.calls) == 1:
            await self.gate.wait()
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        for part in reply:
            if isinstance(part, Exception):
                raise part
            yield part


class LoopTests(unittest.IsolatedAsyncioTestCase):
    def make(self, model, **kw):
        self.sent = []

        async def publish(msg):
            self.sent.append(msg)
        return Conversation(publish, lambda: {"system": {"cpu": 5.0}}, model=model, **kw)

    def chats(self, role):
        return [m for m in self.sent if m["t"] == "chat" and m["role"] == role]

    async def test_deltas_in_order_one_id_last_done(self):
        c = self.make(FakeModel([["Hi ", "there. ", "Bye."]]))
        c.submit("hello")
        await c.idle()
        you = self.chats("you")
        self.assertEqual([(m["delta"], m["done"]) for m in you], [("hello", True)])
        her = self.chats("aries")
        self.assertEqual("".join(m["delta"] for m in her), "Hi there. Bye.")
        self.assertEqual(len({m["id"] for m in her}), 1)
        self.assertEqual([m["done"] for m in her], [False, False, False, True])
        lines = [m["text"] for m in self.sent if m["t"] == "line"]
        self.assertEqual(lines[0], "thinking…")
        self.assertEqual(lines[-1], "")
        self.assertEqual(c.history[-1], {"role": "assistant", "content": "Hi there. Bye."})

    async def test_system_prompt_and_model_passed(self):
        fake = FakeModel([["ok."]])
        c = self.make(fake, model_name="m1")
        c.submit("hi")
        await c.idle()
        system, messages, model = fake.calls[0]
        self.assertIn("You are Aries", system)
        self.assertIn("system: cpu 5", system)
        self.assertEqual((messages, model), ([{"role": "user", "content": "hi"}], "m1"))

    async def test_queueing_runs_one_at_a_time_in_order(self):
        gate = asyncio.Event()
        fake = FakeModel([["one."], ["two."]], gate=gate)
        c = self.make(fake)
        c.submit("a")
        await asyncio.sleep(0.05)
        c.submit("b")
        await asyncio.sleep(0.05)
        self.assertEqual(len(fake.calls), 1)          # b waits behind a
        gate.set()
        await c.idle()
        self.assertEqual([m["delta"] for m in self.chats("you")], ["a", "b"])
        ids = [m["id"] for m in self.chats("aries")]
        self.assertEqual(ids[0], ids[1])
        self.assertNotEqual(ids[1], ids[2])
        self.assertEqual([m["content"] for m in fake.calls[1][1]], ["a", "one.", "b"])

    async def test_sentence_hook(self):
        got = []
        c = self.make(FakeModel([["First one. Sec", "ond!\nThird"]]), on_sentence=got.append)
        c.submit("x")
        await c.idle()
        self.assertEqual(got, ["First one.", "Second!", "Third"])

    async def test_error_before_any_text(self):
        c = self.make(FakeModel([models.ModelError("the API rejected my key.", "credentials")]))
        c.submit("hi")
        await c.idle()
        her = self.chats("aries")
        self.assertEqual(len(her), 1)
        self.assertTrue(her[0]["done"])
        self.assertIn("the API rejected my key.", her[0]["delta"])
        self.assertEqual(c.history, [])               # the failed turn leaves no trace
        self.assertEqual([m["text"] for m in self.sent if m["t"] == "line"][-1], "")

    async def test_error_mid_reply_keeps_partial_and_recovers(self):
        c = self.make(FakeModel([[ "Half a ", models.ModelError("I couldn't reach the API.")],
                                 ["fine."]]))
        c.submit("one")
        c.submit("two")
        await c.idle()
        her = self.chats("aries")
        self.assertEqual(her[0]["delta"], "Half a ")
        self.assertTrue(any(m["done"] and m["id"] == her[0]["id"] for m in her))
        self.assertIn("couldn't reach", " ".join(m["delta"] for m in her))
        self.assertEqual(her[-2]["delta"], "fine.")   # the loop survived

    async def test_history_capped(self):
        c = self.make(FakeModel([["r."]] * 5), max_turns=2)
        for i in range(5):
            c.submit(f"q{i}")
        await c.idle()
        self.assertEqual(len(c.history), 4)
        self.assertEqual(c.history[0], {"role": "user", "content": "q3"})

    async def test_desk_message_routing(self):
        c = self.make(FakeModel([["ok."]]))
        await c.on_desk_message({"t": "press", "widget": "spotify", "control": "next"})
        await c.on_desk_message({"t": "text", "widget": "spotify", "text": "no"})
        await c.on_desk_message({"t": "text", "widget": "chat", "text": "yes"})
        await c.idle()
        self.assertEqual([m["delta"] for m in self.chats("you")], ["yes"])


class ModelKeyTests(unittest.TestCase):
    def setUp(self):
        import os, tempfile, pathlib
        self._env = dict(os.environ)
        for k in list(os.environ):
            if k.startswith(("ANTHROPIC_", "DEEPSEEK_")):
                del os.environ[k]
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["XDG_DATA_HOME"] = self.tmp.name
        os.environ["ANTHROPIC_CONFIG_DIR"] = self.tmp.name + "/none"
        self.dir = pathlib.Path(self.tmp.name) / "ariadne"
        self.dir.mkdir()

    def tearDown(self):
        import os
        os.environ.clear()
        os.environ.update(self._env)
        self.tmp.cleanup()

    def test_no_key_is_a_plain_error(self):
        with self.assertRaises(models.ModelError) as cm:
            models.client_kwargs("anthropic")
        self.assertEqual(cm.exception.kind, "credentials")

    def test_saved_key_file_and_workspace(self):
        (self.dir / "api_key").write_text("sk-test\n")
        (self.dir / "state.json").write_text('{"workspace_id": "wrkspc_1"}')
        kw = models.client_kwargs("anthropic")
        self.assertEqual(kw["api_key"], "sk-test")
        self.assertEqual(kw["default_headers"], {"anthropic-workspace-id": "wrkspc_1"})

    def test_env_wins_over_file(self):
        import os
        (self.dir / "api_key").write_text("from-file")
        os.environ["ANTHROPIC_API_KEY"] = "from-env"
        self.assertEqual(models.client_kwargs("anthropic")["api_key"], "from-env")

    def test_deepseek_routing(self):
        (self.dir / "deepseek_key").write_text("ds")
        self.assertEqual(models.provider_for("deepseek-flash"), "deepseek")
        kw = models.client_kwargs("deepseek")
        self.assertIn("deepseek.com", kw["base_url"])

    def test_classify(self):
        class RateLimitError(Exception):
            pass
        self.assertEqual(models.classify(RateLimitError("x")).kind, "busy")
        self.assertEqual(models.classify(ValueError("no workspace")).kind, "workspace")


if __name__ == "__main__":
    unittest.main()
