"""Demo mode: fake activity so the desk's wires can be tested with no adapters."""
from __future__ import annotations

import asyncio
import itertools

from .. import protocol

# chat/core/flows have no wire to animate
ROTATION = tuple(w for w in protocol.WIDGETS if w not in ("chat", "core", "flows"))
PERIOD = 4.0
HOLD = 0.8


class Demo:
    def __init__(self, server, period: float = PERIOD, hold: float = HOLD) -> None:
        self.server = server
        self.period = period
        self.hold = hold
        # Off when the real conversation loop answers chat instead.
        self.echo_chat = True
        self._ids = itertools.count(1)
        self._task: asyncio.Task | None = None
        self._side: set[asyncio.Task] = set()

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        tasks = [t for t in (self._task, *self._side) if t]
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _loop(self) -> None:
        for n, widget in enumerate(itertools.cycle(ROTATION), start=1):
            await asyncio.sleep(self.period)
            await self.touch(widget, "demo", fail=(n % 6 == 0), speak_line=True)

    async def touch(self, widget: str, control: str, fail: bool = False,
                    speak_line: bool = False) -> None:
        pub = self.server.publish
        aid = f"demo{next(self._ids)}"
        if speak_line:
            await pub(protocol.core_line(f"touching {widget}…"))
        await pub(protocol.action(aid, widget, "demo", "started", control=control))
        await asyncio.sleep(self.hold)
        if fail:
            await pub(protocol.action(aid, widget, "demo", "failed",
                                      control=control, note="demo failure"))
        else:
            await pub(protocol.action(aid, widget, "demo", "done", control=control))
        if speak_line:
            await pub(protocol.core_line(""))

    async def echo(self, text: str) -> None:
        n = next(self._ids)
        await self.server.publish(protocol.chat(f"you{n}", "you", text, done=True))
        reply = f"heard: {text}"
        third = max(1, len(reply) // 3)
        parts = [reply[:third], reply[third:2 * third], reply[2 * third:]]
        for i, part in enumerate(parts):
            await asyncio.sleep(0.15)
            await self.server.publish(protocol.chat(f"aries{n}", "aries", part, done=(i == 2)))

    async def on_desk_message(self, msg: dict) -> None:
        # Run in a side task: the server's read loop must not stall on our sleeps.
        t = msg.get("t")
        if t == "press":
            coro = self.touch(msg["widget"], msg["control"])
        elif t == "text" and msg["widget"] == "chat" and self.echo_chat:
            coro = self.echo(msg["text"])
        else:
            return
        task = asyncio.create_task(coro)
        self._side.add(task)
        task.add_done_callback(self._side.discard)
