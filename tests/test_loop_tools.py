import unittest

from ariadne2.adapters import Adapter, AdapterError, Verb
from ariadne2.core import models
from ariadne2.core.loop import MAX_TOOL_ROUNDS, Conversation


class Fake(Adapter):
    name = "spotify"

    def __init__(self, publish):
        super().__init__(publish)
        self.ran = []

        async def next_():
            self.ran.append("next")
            return "Skipped. Now playing: B."

        async def fail():
            raise AdapterError("Spotify isn't running.")

        async def crash():
            raise RuntimeError("x")

        self.verbs = [Verb("next", "Skip.", {}, next_, "next"), Verb("fail", "Fails.", {}, fail),
                      Verb("crash", "Crashes.", {}, crash)]


class ToolModel:
    """Each reply is a list of text deltas and ToolUse objects, like models.stream's."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    async def __call__(self, system, messages, model, tools=None):
        self.calls.append({"messages": messages, "tools": tools})
        for part in self.replies.pop(0):
            yield part


def use(name, id="tu1", **inp):
    return models.ToolUse(id, name, inp)


class ToolLoopTests(unittest.IsolatedAsyncioTestCase):
    def make(self, replies, **kw):
        self.sent = []

        async def publish(m):
            self.sent.append(m)
        self.adapter = Fake(publish)
        self.model = ToolModel(replies)
        return Conversation(publish, lambda: {}, model=self.model,
                            adapters={"spotify": self.adapter}, **kw)

    def her(self):
        return [m for m in self.sent if m["t"] == "chat" and m["role"] == "aries"]

    def actions(self):
        return [(m["verb"], m["phase"]) for m in self.sent if m["t"] == "action"]

    async def test_text_tool_result_then_continued_text_in_one_bubble(self):
        c = self.make([["Skipping. ", use("spotify_next")], ["B is up. ", "Nice."]])
        sentences = []
        c.on_sentence = sentences.append
        c.submit("skip")
        await c.idle()
        self.assertEqual(self.adapter.ran, ["next"])
        self.assertEqual(self.actions(), [("next", "started"), ("next", "done")])
        her = self.her()
        self.assertEqual(len({m["id"] for m in her}), 1)
        self.assertEqual("".join(m["delta"] for m in her), "Skipping. B is up. Nice.")
        self.assertEqual([m["done"] for m in her].count(True), 1)
        self.assertTrue(her[-1]["done"])
        self.assertEqual(sentences, ["Skipping.", "B is up.", "Nice."])
        # the second call saw the assistant tool_use and the user tool_result
        second = self.model.calls[1]["messages"]
        self.assertEqual([m["role"] for m in second], ["user", "assistant", "user"])
        self.assertEqual(second[1]["content"][0], {"type": "text", "text": "Skipping. "})
        self.assertEqual(second[1]["content"][1]["type"], "tool_use")
        self.assertEqual(second[2]["content"], [{"type": "tool_result", "tool_use_id": "tu1",
                                                 "content": "Skipped. Now playing: B."}])
        self.assertEqual(c.history[-1], {"role": "assistant",
                                         "content": "Skipping. B is up. Nice.\n⟦ran: spotify_next → Skipped. Now playing: B.⟧"})
        self.assertEqual(len(c.history), 2)             # tool traffic isn't kept

    async def test_tools_offered_every_round_and_words_join_with_space(self):
        c = self.make([["Hold on.", use("spotify", action="next")], ["Done."]])
        c.submit("x")
        await c.idle()
        self.assertTrue(all(call["tools"] and call["tools"][0]["name"] == "spotify"
                            for call in self.model.calls))
        self.assertEqual("".join(m["delta"] for m in self.her()), "Hold on. Done.")

    async def test_model_content_is_passed_back_verbatim(self):
        done = models.Done([{"type": "thinking", "thinking": "hm", "signature": "s"},
                            {"type": "tool_use", "id": "tu1", "name": "spotify_next", "input": {}}])
        c = self.make([[use("spotify_next"), done], ["ok."]])
        c.submit("x")
        await c.idle()
        self.assertEqual(self.model.calls[1]["messages"][1]["content"], done.content)

    async def test_tool_error_goes_back_as_is_error(self):
        c = self.make([[use("spotify_fail")], ["it isn't running."]])
        c.submit("x")
        await c.idle()
        result = self.model.calls[1]["messages"][-1]["content"][0]
        self.assertEqual((result["is_error"], result["content"]), (True, "Spotify isn't running."))
        self.assertEqual(self.actions(), [("fail", "started"), ("fail", "failed")])
        self.assertEqual("".join(m["delta"] for m in self.her()), "it isn't running.")

    async def test_unknown_tool_and_crashing_tool_are_errors_not_turn_failures(self):
        c = self.make([[use("steam_launch", "a"), use("spotify_crash", "b")], ["sorry."]])
        c.submit("x")
        await c.idle()
        results = self.model.calls[1]["messages"][-1]["content"]
        self.assertTrue(all(r["is_error"] for r in results))
        self.assertEqual([r["tool_use_id"] for r in results], ["a", "b"])
        self.assertEqual("".join(m["delta"] for m in self.her()), "sorry.")

    async def test_cap_then_one_last_call_without_tools(self):
        replies = [[use("spotify_next", f"t{i}")] for i in range(MAX_TOOL_ROUNDS)]
        replies.append(["Enough."])
        c = self.make(replies)
        c.submit("x")
        await c.idle()
        self.assertEqual(len(self.adapter.ran), MAX_TOOL_ROUNDS)
        self.assertEqual(len(self.model.calls), MAX_TOOL_ROUNDS + 1)
        self.assertIsNone(self.model.calls[-1]["tools"])
        self.assertEqual("".join(m["delta"] for m in self.her()), "Enough.")

    async def test_cap_ignores_tool_use_when_none_offered(self):
        replies = [[use("spotify_next", f"t{i}")] for i in range(MAX_TOOL_ROUNDS + 1)]
        c = self.make(replies)
        c.submit("x")
        await c.idle()
        self.assertEqual(len(self.adapter.ran), MAX_TOOL_ROUNDS)      # the 9th was refused
        self.assertEqual(c.history[-1]["role"], "assistant")

    async def test_acting_without_words_makes_no_bubble_but_keeps_alternation(self):
        c = self.make([[use("spotify_next")], []])
        c.submit("x")
        await c.idle()
        self.assertEqual(self.her(), [])
        self.assertEqual([m["role"] for m in c.history], ["user", "assistant"])
        self.assertIn("spotify_next", c.history[-1]["content"])
        self.assertEqual([m["text"] for m in self.sent if m["t"] == "line"][-1], "")

    async def test_core_line_names_the_tool_while_it_runs(self):
        c = self.make([[use("spotify_next")], ["ok."]])
        c.submit("x")
        await c.idle()
        lines = [m["text"] for m in self.sent if m["t"] == "line"]
        self.assertIn("spotify next…", lines)

    async def test_model_error_after_a_tool_keeps_partial(self):
        c = self.make([])
        # raise from the generator the way models.stream does
        async def boom(system, messages, model, tools=None):
            self.model.calls.append(1)
            if len(self.model.calls) == 1:
                yield "Trying. "
                yield use("spotify_next")
            else:
                raise models.ModelError("I couldn't reach the API.")
        c.model = boom
        c.submit("x")
        await c.idle()
        text = " ".join(m["delta"] for m in self.her())
        self.assertIn("Trying.", text)
        self.assertIn("couldn't reach", text)

    async def test_no_adapters_keeps_old_model_signature(self):
        calls = []

        async def old(system, messages, model):          # 3 args, no tools
            calls.append(1)
            yield "plain."
        sent = []

        async def publish(m):
            sent.append(m)
        c = Conversation(publish, lambda: {}, model=old)
        c.submit("hi")
        await c.idle()
        self.assertEqual(calls, [1])


class ModelStreamTests(unittest.IsolatedAsyncioTestCase):
    async def test_stream_yields_text_then_tool_use_then_done(self):
        from types import SimpleNamespace as NS

        class Block(NS):
            def model_dump(self, **kw):
                return {k: v for k, v in vars(self).items()}

        final = NS(content=[Block(type="text", text="hi"),
                            Block(type="tool_use", id="t1", name="spotify_next", input={})],
                   stop_reason="tool_use")

        class S:
            async def __aenter__(s):
                return s

            async def __aexit__(s, *a):
                return False

            @property
            def text_stream(s):
                async def gen():
                    yield "hi"
                return gen()

            async def get_final_message(s):
                return final

        class Client:
            class messages:
                seen = {}

                @classmethod
                def stream(cls, **kw):
                    cls.seen = kw
                    return S()

        tools = [{"name": "a", "description": "d", "input_schema": {"type": "object"}},
                 {"name": "b", "description": "d", "input_schema": {"type": "object"}}]
        orig = models._clients.get("anthropic")
        models._clients["anthropic"] = Client
        try:
            out = [x async for x in models.stream("sys", [], "claude-sonnet-5-5", tools)]
        finally:
            if orig is None:
                models._clients.pop("anthropic", None)
            else:
                models._clients["anthropic"] = orig
        self.assertEqual(out[0], "hi")
        self.assertEqual(out[1], models.ToolUse("t1", "spotify_next", {}))
        self.assertIsInstance(out[2], models.Done)
        self.assertEqual(out[2].stop_reason, "tool_use")
        sent = Client.messages.seen["tools"]
        self.assertEqual(sent[-1]["cache_control"], {"type": "ephemeral"})
        self.assertNotIn("cache_control", tools[-1])          # caller's list untouched


if __name__ == "__main__":
    unittest.main()


class NoPlayByPlayTests(unittest.IsolatedAsyncioTestCase):
    """What she's doing, then what happened: words between later tool calls are dropped."""
    make, her = ToolLoopTests.make, ToolLoopTests.her

    async def test_only_the_opening_and_the_final_word_are_shown_and_spoken(self):
        spoken = []
        c = self.make([["On it.", use("spotify", "t1", action="next")],
                       ["Found it, still loading, one more check.", use("spotify", "t2", action="next")],
                       ["Done: B is playing."]], on_sentence=spoken.append)
        c.submit("x")
        await c.idle()
        self.assertEqual("".join(m["delta"] for m in self.her()), "On it. Done: B is playing.")
        self.assertNotIn("still loading", " ".join(spoken))
        self.assertIn("Done: B is playing.", " ".join(spoken))
        self.assertTrue(c.history[-1]["content"].startswith("On it. Done: B is playing.\n⟦ran: spotify next"))

    async def test_his_words_are_kept_as_his(self):
        turns = []
        c = self.make([["On it.", use("spotify", "t1", action="next")], ["Done: B is playing."]],
                      on_turn=lambda text, reply, when: turns.append((text, reply)))
        c.submit("skip this song")
        await c.idle()
        self.assertEqual(turns[0][0], "skip this song")          # not her final words
        self.assertTrue(turns[0][1].startswith("On it. Done: B is playing."))
        self.assertEqual(c.history[-2], {"role": "user", "content": "skip this song"})


class HushTests(unittest.IsolatedAsyncioTestCase):
    """'Aries, skip': the rest of the reply still streaming isn't spoken; the next reply is."""
    make, her = ToolLoopTests.make, ToolLoopTests.her

    async def test_skip_silences_the_rest_of_this_reply_only(self):
        spoken = []
        c = self.make([["One. Two. Three."], ["Next reply."]], on_sentence=spoken.append)

        def on_sentence(s):
            spoken.append(s)
            if s.startswith("One"):
                c.hush()                      # he said skip while she was on the first sentence
        c.on_sentence = on_sentence
        c.submit("x")
        await c.idle()
        self.assertEqual(spoken, ["One."])
        self.assertEqual("".join(m["delta"] for m in self.her()), "One. Two. Three.")   # still shown
        c.submit("y")
        await c.idle()
        self.assertEqual(spoken[-1], "Next reply.")


class BareMarkTests(unittest.IsolatedAsyncioTestCase):
    """'amazed Wait, what?' reaches her voice and face as the mark it meant to be."""
    make, her = ToolLoopTests.make, ToolLoopTests.her

    async def test_a_bare_emotion_word_becomes_a_mark(self):
        spoken = []
        c = self.make([["amaz", "ed Wait, what? sympathetic Oh no."]], on_sentence=spoken.append)
        c.submit("x")
        await c.idle()
        self.assertEqual("".join(m["delta"] for m in self.her()), "Wait, what? Oh no.")   # nothing bare, no stray spaces
        self.assertEqual(spoken, ["((amazed)) Wait, what?", "((sympathetic)) Oh no."])      # the voice gets the marks
        self.assertTrue(c.history[-1]["content"].startswith("((amazed)) Wait, what?"))

    def test_ordinary_sentences_are_left_alone(self):
        from ariadne2.core.voice.text import BareMarks
        for text in ("content is king. Okay.", "Proud of you.", "((happy)) Hi.", "hey there"):
            b = BareMarks()
            self.assertEqual(b.feed(text) + b.flush(), text)


class RecordTests(unittest.TestCase):
    """What she ran stays in her history, so she never disowns real work."""

    def test_brief_names_the_tool_and_its_point(self):
        from ariadne2.core.loop import brief
        self.assertEqual(brief("look", {"what": "DP-2"}), 'look "DP-2"')
        self.assertEqual(brief("spotify", {"action": "play", "query": "lofi"}), 'spotify play "lofi"')
        self.assertEqual(brief("todo", {}), "todo")
        self.assertTrue(brief("shell", {"command": "x" * 200}).endswith('…"'))

    def test_record_is_ours_alone(self):
        from ariadne2.core.loop import record
        self.assertEqual(record("done.", []), "done.")
        self.assertEqual(record("done.", ["look"]), "done.\n⟦ran: look⟧")
        # she can't write one herself: a fake record in her words is dropped
        self.assertEqual(record("searched it ⟦ran: web_search⟧", []), "searched it")
        self.assertEqual(record("", ["shell \"ls\""]), '⟦ran: shell "ls"⟧')
