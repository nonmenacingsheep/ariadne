"""The conversation: one turn at a time, her reply streamed into the chat."""
from __future__ import annotations

import asyncio
import inspect
import itertools
import logging
import re
import time

from .. import adapters as adapters_mod
from .. import protocol
from . import models, prompt

log = logging.getLogger("ariadne2.core.loop")

MAX_TURNS = 40                  # exchanges kept in memory (you + her = one)
THINKING = "thinking…"
MAX_TOOL_ROUNDS = 8             # model calls that may end in tool use, per turn

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
    can start speaking before the reply is done. `adapters` is the registry
    (name -> Adapter); its verbs are offered to the model as tools every turn.
    """

    def __init__(self, publish, snapshots=None, model=None, model_name: str = models.DEFAULT_MODEL,
                 personality: str = prompt.DEFAULT_PERSONALITY, on_sentence=None,
                 max_turns: int = MAX_TURNS, adapters=None) -> None:
        self.publish = publish
        self.snapshots = snapshots or (lambda: {})
        self.model = model or models.stream
        self.model_name = model_name
        self.personality = personality
        self.on_sentence = on_sentence
        self.max_turns = max_turns
        self.adapters = adapters or {}
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
        tools = adapters_mod.tools(self.adapters) if self.adapters else None
        # Tool calls and results live only inside the turn; history keeps her words.
        messages = list(self.history)
        splitter = SentenceSplitter()
        reply = ""
        used: list[str] = []
        try:
            for rnd in range(MAX_TOOL_ROUNDS + 1):
                # After the cap she gets no tools, so the last call has to be words.
                offered = tools if rnd < MAX_TOOL_ROUNDS else None
                kw = {"tools": offered} if offered else {}
                calls: list[models.ToolUse] = []
                content = None
                round_text = ""
                async for item in self.model(system, list(messages), self.model_name, **kw):
                    if isinstance(item, models.ToolUse):
                        calls.append(item)
                        continue
                    if isinstance(item, models.Done):
                        content = item.content
                        continue
                    if not item:
                        continue
                    if not round_text and reply and not reply[-1].isspace():
                        item = " " + item          # words after a tool call join the same bubble
                    if not reply:
                        await self.publish(protocol.core_line(""))   # first word is here
                    round_text += item
                    reply += item
                    await self.publish(protocol.chat(her_id, "aries", item))
                    for sentence in splitter.feed(item):
                        await self._sentence(sentence)
                if not calls or offered is None:
                    break
                for sentence in splitter.flush():       # speak it before the tool runs
                    await self._sentence(sentence)
                messages.append({"role": "assistant",
                                 "content": content or self._blocks(round_text, calls)})
                messages.append({"role": "user",
                                 "content": [await self._tool(c) for c in calls]})
                used += [c.name for c in calls]
                await self.publish(protocol.core_line(THINKING))
        except asyncio.CancelledError:
            raise
        except Exception as e:
            await self._failed(e, reply, her_id, n)
            return
        finally:
            await self.publish(protocol.core_line(""))
        if not reply and used:
            # Acted without a word: no bubble, but history must still alternate.
            self.history.append({"role": "assistant",
                                 "content": f"(no words; used {', '.join(used)})"})
            self._trim()
            return
        if not reply:
            # An empty stream still has to close the bubble the user is waiting on.
            reply = "(no answer came back)"
            await self.publish(protocol.chat(her_id, "aries", reply))
        await self.publish(protocol.chat(her_id, "aries", "", done=True))
        for sentence in splitter.flush():
            await self._sentence(sentence)
        self.history.append({"role": "assistant", "content": reply})
        self._trim()

    @staticmethod
    def _blocks(text: str, calls: list) -> list[dict]:
        """The assistant message for a round, when the model didn't hand us its own."""
        blocks = [{"type": "text", "text": text}] if text else []
        return blocks + [{"type": "tool_use", "id": c.id, "name": c.name, "input": c.input}
                         for c in calls]

    async def _tool(self, call: models.ToolUse) -> dict:
        """Run one tool; a failure goes back to the model as an error result."""
        await self.publish(protocol.core_line(call.name.replace("_", " ") + "…"))
        result = {"type": "tool_result", "tool_use_id": call.id}
        try:
            result["content"] = await adapters_mod.call_tool(self.adapters, call.name, call.input)
        except asyncio.CancelledError:
            raise
        except adapters_mod.AdapterError as e:
            result.update(content=str(e), is_error=True)
        except Exception:
            log.exception("tool %s crashed", call.name)
            result.update(content="that tool broke on my side.", is_error=True)
        return result

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
