"""The adapter framework (DESIGN §4): one adapter per app.

An adapter declares verbs (her tools), owns the widget's state, and wraps every
verb in action events -- that wrapping is what animates the wires, so a verb
author never touches the protocol.
"""
from __future__ import annotations

import asyncio
import inspect
import itertools
import logging
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from .. import protocol

log = logging.getLogger("ariadne2.adapters")

NOTE_MAX = 80                    # the failure note is one line in the widget


class AdapterError(Exception):
    """A verb couldn't do its job. The message is plain English for her and him."""


@dataclass
class Verb:
    name: str
    description: str                     # written for the model; short
    params: dict = field(default_factory=dict)    # JSON schema of the args object
    fn: Callable[..., Awaitable[str]] = None
    control: str | None = None           # widget control to light cyan when she uses it

    def schema(self) -> dict:
        schema = {"type": "object", "properties": {}}
        schema.update(self.params)
        return schema


class Adapter:
    name = ""                            # = the widget name
    events: tuple[str, ...] = ()         # declared event names, for flows later

    def __init__(self, publish) -> None:
        self.publish = publish
        self.verbs: list[Verb] = []
        self.controls: dict[str, str] = {}      # widget control -> verb name, for press()
        self.subscribers: list[Callable] = []
        # Boot stamp, like chat ids: a restarted core must not reuse ids a desk holds.
        self._boot = format(int(time.time()), "x")
        self._ids = itertools.count(1)

    # ---- lifecycle and state ----

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    def state(self) -> dict:
        return {}

    async def publish_state(self) -> None:
        await self.publish(protocol.state(self.name, self.state()))

    # ---- verbs ----

    def verb(self, name: str) -> Verb:
        for v in self.verbs:
            if v.name == name:
                return v
        raise AdapterError(f"{self.name} has no verb called {name!r}")

    async def run(self, verb: str, args: dict | None = None, *, announce: bool = True) -> str:
        """Run a verb. With `announce`, the desk sees started, then done or failed."""
        v = self.verb(verb)
        args = dict(args or {})
        try:
            inspect.signature(v.fn).bind(**args)
        except TypeError as e:
            raise AdapterError(f"bad arguments for {self.name} {verb}: {e}") from e
        aid = f"{self.name}-{self._boot}-{next(self._ids)}"

        async def say(phase: str, note: str | None = None) -> None:
            if announce:
                await self.publish(protocol.action(aid, self.name, verb, phase,
                                                   control=v.control, note=note))

        await say("started")
        try:
            result = await v.fn(**args)
        except AdapterError as e:
            await say("failed", str(e)[:NOTE_MAX])
            raise
        except asyncio.CancelledError:
            await say("failed", "cancelled")
            raise
        except Exception as e:
            log.exception("%s.%s crashed", self.name, verb)
            await say("failed", "something broke")
            raise AdapterError(f"{self.name} {verb} broke on my side ({e.__class__.__name__})") from e
        await say("done")
        return result or "done"

    async def press(self, control: str, value=None) -> str | None:
        """A button pressed in the widget by him: no animation, it's his own click."""
        verb = self.controls.get(control)
        if verb is None:
            log.warning("%s: no verb for control %r", self.name, control)
            return None
        return await self.run(verb, self.press_args(control, value), announce=False)

    def press_args(self, control: str, value) -> dict:
        """Arguments for the verb a control maps to; adapters with sliders override."""
        return {}

    # ---- events (flows subscribe later) ----

    def subscribe(self, fn: Callable[[str, dict], object]) -> None:
        """fn("spotify.track_changed", {"title": ..}) -- sync, or async (scheduled)."""
        self.subscribers.append(fn)

    def emit(self, event: str, **fields) -> None:
        if event not in self.events:
            log.warning("%s emitted undeclared event %r", self.name, event)
        for fn in list(self.subscribers):
            try:
                result = fn(f"{self.name}.{event}", fields)
                if inspect.isawaitable(result):
                    asyncio.ensure_future(result)
            except Exception:
                log.exception("%s.%s subscriber failed", self.name, event)
