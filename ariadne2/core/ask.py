"""Her `ask` tool: a question for him in the middle of a job, and his answer back.

The question goes to the chat (the protocol `ask` message Flows' Ask Ronald
uses too: one button per option, none when she wants it typed or said). If
her voice is on she says it, and once she has finished his mic opens for a
spoken answer, the way it does for a follow-up. The first answer wins: a
clicked button, a typed chat reply or a spoken one; she gets which it was and
his exact words. Nothing within the timeout is an answer too ("he didn't").

The turn that called the tool is waiting on it, so his reply must not start a
turn of its own: Conversation hands every desk message to `on_desk`, and
core/__main__.py hands every heard utterance to `offer_spoken`, before either
is queued. Both take a message only while a question is open. When it ends
(any way) the desk is told with `ask_done` and greys the buttons.
"""
from __future__ import annotations

import asyncio
import itertools
import logging
import time

from .. import protocol
from ..adapters import AdapterError

log = logging.getLogger("ariadne2.ask")

TIMEOUT = 120.0
MAX_OPTIONS = 6
POLL = 0.2              # how often to see whether she has stopped speaking, to open the mic

TOOL = {
    "name": "ask",
    "description": (
        "Ask him a question and wait for his answer (up to 2 minutes): a choice that's his, or something you "
        "can't know. It shows in the chat with a button per option (2-4 short ones, if the answer is a "
        "choice), you say it aloud and his mic opens. Returns what he clicked, typed or said, or that he "
        "didn't answer. One question at a time; don't use it for things you can decide or look up."),
    "input_schema": {"type": "object", "properties": {
        "question": {"type": "string", "description": "One short question."},
        "options": {"type": "array", "items": {"type": "string"},
                    "description": "Optional short answers, shown as buttons."},
    }, "required": ["question"]},
}


class Asker:
    """The toolset. `say(text) -> bool` speaks (False when her voice is off), `speaking() -> bool`,
    `open_mic() -> bool` opens his mic as if he'd said her name; all optional."""

    def __init__(self, publish, say=None, speaking=None, open_mic=None, timeout: float = TIMEOUT) -> None:
        self.publish = publish
        self.say = say
        self.speaking = speaking or (lambda: False)
        self.open_mic = open_mic
        self.timeout = timeout
        self._boot = format(int(time.time()), "x")
        self._n = itertools.count(1)
        self._open: dict | None = None      # {"id", "question", "options", "done": Future of (how, text, sure)}

    def tools(self) -> list[dict]:
        return [TOOL]

    @property
    def pending(self) -> bool:
        return self._open is not None

    # ---- his answers: the first one wins ----

    def _take(self, how: str, text: str, sure: bool = True) -> bool:
        q = self._open
        if q is None or q["done"].done():
            return False
        q["done"].set_result((how, text, sure))
        return True

    def on_desk(self, msg: dict) -> bool:
        """A message from the desk; True if it was an answer to the open question (so it goes no further)."""
        q = self._open
        t = msg.get("t")
        if t == "hello" and q is not None:      # a desk (re)connecting gets the question that's still open
            asyncio.ensure_future(self.publish(protocol.ask(q["id"], q["question"], q["options"])))
        elif t == "answer" and q is not None and msg.get("id") == q["id"]:
            choice = msg.get("choice")
            if choice in q["options"]:
                self._take("button", choice)
            return True
        elif t == "text" and msg.get("widget") == "chat" and q is not None and not msg.get("attachments"):
            text = str(msg.get("text") or "").strip()
            return bool(text) and self._take("typed", text)
        return False

    def offer_spoken(self, text: str, sure: bool = True) -> bool:
        """An utterance he said; True if it answered the open question."""
        return bool((text or "").strip()) and self._take("spoken", text.strip(), sure)

    # ---- the tool ----

    async def call(self, name: str, args: dict, his_words: str | None = None) -> str:
        a = args or {}
        question = " ".join(str(a.get("question") or "").split())[:400]
        if not question:
            raise AdapterError("say what to ask (question)")
        if self._open is not None:
            raise AdapterError("I'm still waiting on his answer to the last question")
        raw = a.get("options") if isinstance(a.get("options"), list) else []
        options = []
        for o in raw:
            o = " ".join(str(o).split())[:40]
            if o and o not in options:
                options.append(o)
        options = options[:MAX_OPTIONS]
        qid = f"ask-{self._boot}-{next(self._n)}"
        self._open = {"id": qid, "question": question, "options": options,
                      "done": asyncio.get_running_loop().create_future()}
        how, text, sure = "closed", "", True
        try:
            await self.publish(protocol.ask(qid, question, options))
            spoke = self._speak(question)
            how, text, sure = await self._wait(spoke)
            if how in ("typed", "spoken"):          # his bubble in the chat, as a turn of his would have
                await self.publish(protocol.chat(f"{qid}-you", "you", text, done=True))
        finally:
            self._open = None
            await self.publish(protocol.ask_done(qid, how, text if how == "button" else None))
        return self._result(how, text, sure)

    def _speak(self, text: str) -> bool:
        if self.say is None:
            return False
        try:
            return bool(self.say(text))
        except Exception:
            log.exception("couldn't speak the question")
            return False

    async def _wait(self, spoke: bool) -> tuple[str, str, bool]:
        """Until an answer or the timeout; opens the mic once she has finished saying the question."""
        loop = asyncio.get_running_loop()
        done = self._open["done"]
        end = loop.time() + self.timeout
        mic = spoke and self.open_mic is not None
        while not done.done():
            left = end - loop.time()
            if left <= 0:
                return "timeout", "", True
            if mic and not self.speaking():
                mic = False
                try:
                    self.open_mic()
                except Exception:
                    log.exception("couldn't open the mic")
            await asyncio.wait({done}, timeout=min(left, POLL))
        return done.result()

    def _result(self, how: str, text: str, sure: bool) -> str:
        if how == "timeout":
            mins = self.timeout / 60
            return f"He didn't answer within {mins:g} minute{'s' * (mins != 1)}."
        if how == "button":
            return f'He clicked the button: "{text}"'
        if how == "typed":
            return f'He typed in the chat: "{text}"'
        if how == "spoken":
            return f'He said aloud: "{text}"' + ("" if sure else " (speech recognition wasn't sure; it may be misheard)")
        return "The question was dropped before he answered."
