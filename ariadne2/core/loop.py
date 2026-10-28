"""The conversation: one turn at a time, her reply streamed into the chat."""
from __future__ import annotations

import asyncio
import inspect
import itertools
import logging
import re
import time

from .. import protocol
from . import models, prompt

log = logging.getLogger("ariadne2.core.loop")

MAX_TURNS = 40                  # exchanges kept in memory (you + her = one)
THINKING = "thinking…"

# A sentence ends at . ! ? … (plus closing quotes) followed by whitespace, or
# at a newline. Needing the whitespace keeps "3.5" and "e.g.x" whole.
_BOUNDARY = re.compile(r"[.!?…]+[\"')\]]*(?=\s)|\n")


class SentenceSplitter:
    """Cuts a stream of text deltas into complete sentences."""

    def __init__(self) -> None:
        self._buf = ""

    def feed(self, delta: str) -> list[str]:
        self._buf += delta
        out = []
        while (m := _BOUNDARY.search(self._buf)):
            sentence = self._buf[:m.end()].strip()
            self._buf = self._buf[m.end():]
            if sentence:
                out.append(sentence)
        return out

    def flush(self) -> list[str]:
        rest, self._buf = self._buf.strip(), ""
        return [rest] if rest else []


class Conversation:
    """Holds the session history and runs queued user texts through the model.

    `publish` is the server's publish; `snapshots` returns the current widget
    state; `model` is `models.stream`-shaped (swapped for a fake in tests).
    `on_sentence(text)` gets each finished sentence as it streams, so a voice
    can start speaking before the reply is done.
    """

    def __init__(self, publish, snapshots=None, model=None, model_name: str = models.DEFAULT_MODEL,
                 personality: str = prompt.DEFAULT_PERSONALITY, on_sentence=None,
                 max_turns: int = MAX_TURNS) -> None:
        self.publish = publish
        self.snapshots = snapshots or (lambda: {})
        self.model = model or models.stream
        self.model_name = model_name
        self.personality = personality
        self.on_sentence = on_sentence
        self.max_turns = max_turns
        self.history: list[dict] = []
        # Boot stamp in ids: a restarted core must not reuse ids a desk still holds.
        self._boot = format(int(time.time()), "x")
        self._n = itertools.count(1)
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._worker: asyncio.Task | None = None

    # ---- input ----

    async def on_desk_message(self, msg: dict) -> None:
        if msg.get("t") == "text" and msg.get("widget") == "chat":
            self.submit(msg["text"])

    def submit(self, text: str) -> None:
        """Queue a user text (typed, or spoken later); turns run one at a time."""
        text = text.strip()
        if not text:
            return
        self._queue.put_nowait(text)
        if self._worker is None or self._worker.done():
            self._worker = asyncio.create_task(self._run())

    async def idle(self) -> None:
        """Wait until every queued text has been answered."""
        await self._queue.join()

    async def stop(self) -> None:
        if self._worker:
            self._worker.cancel()
            await asyncio.gather(self._worker, return_exceptions=True)

    async def _run(self) -> None:
        while True:
            text = await self._queue.get()
            try:
                await self._turn(text)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("turn failed")
            finally:
                self._queue.task_done()

    # ---- one turn ----

    async def _turn(self, text: str) -> None:
        n = next(self._n)
        you_id, her_id = f"{self._boot}-{n}-you", f"{self._boot}-{n}-aries"
        await self.publish(protocol.chat(you_id, "you", text, done=True))
        await self.publish(protocol.core_line(THINKING))
        self.history.append({"role": "user", "content": text})
        system = prompt.build(self.personality, self.snapshots())
        splitter = SentenceSplitter()
        reply = ""
        try:
            async for delta in self.model(system, list(self.history), self.model_name):
                if not delta:
                    continue
                if not reply:
                    await self.publish(protocol.core_line(""))   # first word is here
                reply += delta
                await self.publish(protocol.chat(her_id, "aries", delta))
                for sentence in splitter.feed(delta):
                    await self._sentence(sentence)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            await self._failed(e, reply, her_id, n)
            return
        finally:
            await self.publish(protocol.core_line(""))
        if not reply:
            # An empty stream still has to close the bubble the user is waiting on.
            reply = "(no answer came back)"
            await self.publish(protocol.chat(her_id, "aries", reply))
        await self.publish(protocol.chat(her_id, "aries", "", done=True))
        for sentence in splitter.flush():
            await self._sentence(sentence)
        self.history.append({"role": "assistant", "content": reply})
        self._trim()

    async def _failed(self, exc: Exception, partial: str, her_id: str, n: int) -> None:
        if isinstance(exc, models.ModelError):
            what = exc.message
            log.warning("model unreachable (%s): %s", exc.kind, what)
        else:
            what = "something broke on my side."
            log.error("conversation error", exc_info=exc)
        line = f"I couldn't get to my model: {what}"
        if partial:
            # What was already shown stays; the failure gets its own bubble.
            await self.publish(protocol.chat(her_id, "aries", "", done=True))
            self.history.append({"role": "assistant", "content": partial})
            her_id = f"{self._boot}-{n}-err"
        else:
            self.history.pop()      # keep roles alternating; she never saw it
        await self.publish(protocol.chat(her_id, "aries", line, done=True))
        self._trim()

    async def _sentence(self, text: str) -> None:
        if not self.on_sentence:
            return
        try:
            result = self.on_sentence(text)
            if inspect.isawaitable(result):
                await result
        except Exception:
            log.exception("on_sentence hook failed")

    def _trim(self) -> None:
        extra = len(self.history) - self.max_turns * 2
        if extra > 0:
            del self.history[:extra]
        while self.history and self.history[0]["role"] != "user":
            self.history.pop(0)
