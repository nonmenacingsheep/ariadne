"""Hand a callback from a worker thread to the asyncio loop it belongs to."""
from __future__ import annotations

import asyncio
import inspect
import logging

log = logging.getLogger("ariadne2.voice")


class Dispatcher:
    """Callbacks are written for the loop (they send packets), but the audio
    runs on threads. Everything user-facing goes through here, so a callback
    that raises is logged instead of killing a thread, and a coroutine
    function works as well as a plain one."""

    def __init__(self, loop: asyncio.AbstractEventLoop | None = None) -> None:
        self.loop = loop

    def call(self, fn, *args) -> None:
        if fn is None:
            return
        loop = self.loop
        if loop is not None and not loop.is_closed():
            try:
                loop.call_soon_threadsafe(self._run, fn, args)
            except RuntimeError:            # loop closed between the check and the call
                pass
        else:
            self._run(fn, args)

    def _run(self, fn, args) -> None:
        try:
            result = fn(*args)
            if inspect.isawaitable(result):
                asyncio.ensure_future(self._guard(result))
        except Exception:
            log.exception("callback %r failed", fn)

    @staticmethod
    async def _guard(awaitable) -> None:
        try:
            await awaitable
        except Exception:
            log.exception("async callback failed")
