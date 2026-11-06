import asyncio
import unittest

from ariadne2 import protocol
from ariadne2.adapters import AdapterError
from ariadne2.core import models
from ariadne2.core.ask import Asker
from ariadne2.core.loop import Conversation


class Fakes:
    """A voice that speaks until told it's done, and an ears whose mic can be opened."""

    def __init__(self):
        self.sent = []
        self.said = []
        self.is_speaking = False
        self.mic_opened = 0
        self.voice_on = True

    async def publish(self, m):
        self.sent.append(m)

    def say(self, text):
        if not self.voice_on:
            return False
        self.said.append(text)
        self.is_speaking = True
        return True

    def open_mic(self):
        self.mic_opened += 1
        return True

    def kinds(self, t):
        return [m for m in self.sent if m["t"] == t]


class AskTests(unittest.IsolatedAsyncioTestCase):
    def make(self, timeout=5.0, **kw):
        self.f = Fakes()
        self.asker = Asker(self.f.publish, say=self.f.say, speaking=lambda: self.f.is_speaking,
                           open_mic=self.f.open_mic, timeout=timeout, **kw)
        return self.asker

    async def start(self, **args):
        task = asyncio.ensure_future(self.asker.call("ask", args, None))
        for _ in range(5):
            await asyncio.sleep(0)
        return task

    def qid(self):
        return self.f.kinds("ask")[-1]["id"]

    async def test_description_is_short_and_named_generically(self):
        (tool,) = self.make().tools()
        self.assertEqual(tool["name"], "ask")
        self.assertLess(len(tool["description"]), 500)
        self.assertNotIn("Ronald", str(tool))

    async def test_question_shows_with_a_button_per_option(self):
        self.make()
        task = await self.start(question="Send Kai the score?", options=["yes", "no", "yes", " "])
        ask = self.f.kinds("ask")[0]
        self.assertEqual((ask["question"], ask["options"]), ("Send Kai the score?", ["yes", "no"]))
        protocol.decode(protocol.encode(ask).decode())           # fits the wire
        self.assertTrue(self.asker.pending)
        self.asker.on_desk(protocol.answer(ask["id"], "no"))
        await task

    async def test_button_answer(self):
        self.make()
        task = await self.start(question="Which?", options=["tea", "coffee"])
        self.assertTrue(self.asker.on_desk(protocol.answer(self.qid(), "coffee")))
        self.assertEqual(await task, 'He clicked the button: "coffee"')
        done = self.f.kinds("ask_done")
        self.assertEqual([(m["id"], m["how"], m["choice"]) for m in done], [(self.qid(), "button", "coffee")])
        protocol.decode(protocol.encode(done[0]).decode())
        self.assertFalse(self.asker.pending)

    async def test_a_button_that_is_not_an_option_is_ignored(self):
        self.make()
        task = await self.start(question="Which?", options=["tea"])
        self.asker.on_desk(protocol.answer(self.qid(), "wine"))
        await asyncio.sleep(0.05)
        self.assertFalse(task.done())
        self.asker.on_desk(protocol.answer(self.qid(), "tea"))
        await task

    async def test_typed_answer(self):
        self.make()
        task = await self.start(question="What should the file be called?")
        self.assertEqual(self.f.kinds("ask")[0]["options"], [])
        self.assertTrue(self.asker.on_desk(protocol.text("chat", "  notes.txt ")))
        self.assertEqual(await task, 'He typed in the chat: "notes.txt"')
        you = [m for m in self.f.kinds("chat") if m["role"] == "you"]
        self.assertEqual([(m["delta"], m["done"]) for m in you], [("notes.txt", True)])
        self.assertEqual(self.f.kinds("ask_done")[0]["how"], "typed")

    async def test_typing_with_attachments_or_nothing_is_not_an_answer(self):
        self.make()
        task = await self.start(question="Which?")
        self.assertFalse(self.asker.on_desk(protocol.text("chat", "look at this", ["/tmp/x.png"])))
        self.assertFalse(self.asker.on_desk(protocol.text("chat", "   ")))
        self.assertFalse(task.done())
        self.asker.offer_spoken("anything")
        await task

    async def test_spoken_answer_after_she_finishes_speaking(self):
        self.make()
        task = await self.start(question="Shall I go ahead?", options=["yes", "no"])
        self.assertEqual(self.f.said, ["Shall I go ahead?"])
        await asyncio.sleep(0.5)
        self.assertEqual(self.f.mic_opened, 0)                  # still talking: the mic stays shut
        self.f.is_speaking = False
        await asyncio.sleep(0.5)
        self.assertEqual(self.f.mic_opened, 1)                  # opened once, not again every poll
        self.assertTrue(self.asker.offer_spoken("yes please go ahead"))
        self.assertEqual(await task, 'He said aloud: "yes please go ahead"')
        self.assertEqual(self.f.kinds("ask_done")[0]["how"], "spoken")
        self.assertEqual([m["delta"] for m in self.f.kinds("chat") if m["role"] == "you"], ["yes please go ahead"])

    async def test_unsure_transcript_is_flagged(self):
        self.make()
        task = await self.start(question="Name?")
        self.asker.offer_spoken("ari add nay", sure=False)
        self.assertIn("misheard", await task)

    async def test_no_voice_means_no_speech_and_no_mic(self):
        self.make()
        self.f.voice_on = False
        task = await self.start(question="Which?")
        await asyncio.sleep(0.4)
        self.assertEqual((self.f.said, self.f.mic_opened), ([], 0))
        self.asker.on_desk(protocol.text("chat", "this one"))
        await task

    async def test_timeout_and_buttons_close(self):
        self.make(timeout=0.3)
        task = await self.start(question="Which?", options=["a", "b"])
        self.assertEqual(await task, "He didn't answer within 0.005 minutes.")
        self.assertEqual([(m["id"], m["how"]) for m in self.f.kinds("ask_done")], [(self.qid(), "timeout")])
        self.assertFalse(self.asker.pending)
        self.assertFalse(self.asker.on_desk(protocol.text("chat", "too late")))
        self.assertFalse(self.asker.offer_spoken("too late"))

    async def test_two_minute_wording(self):
        self.make(timeout=120.0)
        self.assertEqual(self.asker._result("timeout", "", True), "He didn't answer within 2 minutes.")

    async def test_first_answer_wins(self):
        self.make()
        task = await self.start(question="Which?", options=["a", "b"])
        self.asker.on_desk(protocol.answer(self.qid(), "a"))
        self.assertFalse(self.asker.offer_spoken("b"))
        self.assertEqual(await task, 'He clicked the button: "a"')

    async def test_one_question_at_a_time_and_a_question_is_needed(self):
        self.make()
        task = await self.start(question="First?")
        with self.assertRaises(AdapterError):
            await self.asker.call("ask", {"question": "Second?"}, None)
        self.asker.offer_spoken("ok")
        await task
        with self.assertRaises(AdapterError):
            await self.asker.call("ask", {"question": "  "}, None)

    async def test_cancelled_turn_closes_the_buttons(self):
        self.make()
        task = await self.start(question="Which?", options=["a"])
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(self.f.kinds("ask_done")[0]["how"], "closed")
        self.assertFalse(self.asker.pending)

    async def test_reconnecting_desk_gets_the_open_question_again(self):
        self.make()
        task = await self.start(question="Which?", options=["a"])
        self.f.sent.clear()
        self.assertFalse(self.asker.on_desk({"t": "hello"}))
        await asyncio.sleep(0)
        self.assertEqual(len(self.f.kinds("ask")), 1)
        self.asker.on_desk(protocol.answer(self.qid(), "a"))
        await task


def use(name, id="tu1", **inp):
    return models.ToolUse(id, name, inp)


class ScriptedModel:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    async def __call__(self, system, messages, model, tools=None):
        self.calls.append({"messages": messages, "tools": tools})
        for part in self.replies.pop(0):
            yield part


class InTheLoop(unittest.IsolatedAsyncioTestCase):
    """The reply has to reach the waiting tool, not start a turn of its own."""

    def make(self):
        self.f = Fakes()
        self.asker = Asker(self.f.publish, say=self.f.say, speaking=lambda: self.f.is_speaking,
                           open_mic=self.f.open_mic, timeout=5.0)
        self.model = ScriptedModel([[use("ask", question="Tea or coffee?", options=["tea", "coffee"])],
                                    ["Coffee it is."]])
        self.conv = Conversation(self.f.publish, lambda: {}, model=self.model, toolsets=[self.asker])
        self.conv.asker = self.asker
        return self.conv

    async def waiting(self):
        self.conv.submit("make me a drink")
        for _ in range(50):
            await asyncio.sleep(0.01)
            if self.asker.pending:
                return
        self.fail("the question never opened")

    def result_seen(self):
        last = self.model.calls[1]["messages"][-1]["content"][0]
        return last["content"]

    async def test_typed_reply_goes_to_the_tool(self):
        self.make()
        await self.waiting()
        await self.conv.on_desk_message(protocol.text("chat", "tea please"))
        await self.conv.idle()
        self.assertEqual(self.result_seen(), 'He typed in the chat: "tea please"')
        self.assertEqual(len(self.model.calls), 2)                          # one turn, not two
        self.assertEqual(len([m for m in self.f.sent if m["t"] == "chat" and m["role"] == "you"]), 2)

    async def test_button_reply_goes_to_the_tool(self):
        self.make()
        await self.waiting()
        qid = [m for m in self.f.sent if m["t"] == "ask"][0]["id"]
        await self.conv.on_desk_message(protocol.answer(qid, "coffee"))
        await self.conv.idle()
        self.assertEqual(self.result_seen(), 'He clicked the button: "coffee"')

    async def test_spoken_reply_goes_to_the_tool(self):
        self.make()
        await self.waiting()
        self.assertTrue(self.asker.offer_spoken("coffee"))
        await self.conv.idle()
        self.assertEqual(self.result_seen(), 'He said aloud: "coffee"')

    async def test_after_the_answer_typing_is_a_new_turn_again(self):
        self.make()
        self.model.replies.append(["Fine."])
        await self.waiting()
        await self.conv.on_desk_message(protocol.text("chat", "tea"))
        await self.conv.idle()
        await self.conv.on_desk_message(protocol.text("chat", "thanks"))
        await self.conv.idle()
        self.assertEqual(len(self.model.calls), 3)


if __name__ == "__main__":
    unittest.main()
