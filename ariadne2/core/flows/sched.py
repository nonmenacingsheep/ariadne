"""One scheduler for every timed thing in flows (DESIGN §10: "a single timer
to the next due time, not a polling tick").

Entries are keyed; scheduling a key again replaces it. A background task
sleeps until the earliest due time (capped, so a clock jump after suspend is
noticed) and wakes early when something earlier is added. Tests use a fake
clock and call `run_due()` themselves.
"""
from __future__ import annotations

import asyncio
import datetime
import heapq
import inspect
import itertools
import logging
import time

from . import values as V

log = logging.getLogger("ariadne2.core.flows.sched")

MAX_SLEEP = 30.0          # re-read the clock at least this often
LATE_GRACE = 300.0        # an "At" this far past due was missed (machine was off), not late


class Clock:
    def now(self) -> float:
        return time.time()


class Scheduler:
    def __init__(self, clock=None) -> None:
        self.clock = clock or Clock()
        self._heap: list = []
        self._live: dict = {}                       # key -> (due, seq, callback)
        self._seq = itertools.count()
        self._wake = asyncio.Event()
        self._task: asyncio.Task | None = None

    def schedule(self, key, due: float, callback) -> None:
        entry = (due, next(self._seq), callback)
        self._live[key] = entry
        heapq.heappush(self._heap, (due, entry[1], key))
        self._wake.set()

    def cancel(self, key) -> None:
        self._live.pop(key, None)

    def cancel_where(self, pred) -> None:
        for key in [k for k in self._live if pred(k)]:
            del self._live[key]

    def due_of(self, key) -> float | None:
        e = self._live.get(key)
        return e[0] if e else None

    def keys(self) -> list:
        return list(self._live)

    def _next_due(self) -> float | None:
        while self._heap:
            due, seq, key = self._heap[0]
            live = self._live.get(key)
            if live and live[1] == seq:
                return due
            heapq.heappop(self._heap)               # replaced or cancelled
        return None

    async def run_due(self) -> int:
        """Run everything due now. Returns how many ran."""
        ran = 0
        while True:
            due = self._next_due()
            if due is None or due > self.clock.now():
                return ran
            _, seq, key = heapq.heappop(self._heap)
            _, _, cb = self._live.pop(key)
            ran += 1
            try:
                result = cb()
                if inspect.isawaitable(result):
                    await result
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("scheduled job %r failed", key)

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None

    async def _loop(self) -> None:
        while True:
            await self.run_due()
            due = self._next_due()
            wait = MAX_SLEEP if due is None else max(0.0, min(due - self.clock.now(), MAX_SLEEP))
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), wait)
            except asyncio.TimeoutError:
                pass


def next_at(now: float, hm: tuple[int, int], days: list[str] | None = None, dates=None) -> float:
    """The next time of day strictly after `now` on one of the weekdays and one of
    the dates of the month (1-31, or "last"); none of either = any."""
    base = datetime.datetime.fromtimestamp(now)
    dates = V.parse_dates(dates) or []
    for offset in range(0, 70):
        day = base.date() + datetime.timedelta(days=offset)
        cand = datetime.datetime(day.year, day.month, day.day, hm[0], hm[1])
        last = (day + datetime.timedelta(days=1)).month != day.month
        if (cand.timestamp() > now and (not days or V.DAYS[cand.weekday()] in days)
                and (not dates or day.day in dates or (last and "last" in dates))):
            return cand.timestamp()
    return now + 86400
