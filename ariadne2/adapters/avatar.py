"""Her body, as one of her tools: where it is, what it's doing, and moving it.

Whichever body is showing (the 3D one, pet/, or the Live2D one, ariadne2/pet2d)
writes ~/.local/share/ariadne2/pet/body.json about once a second: its kind and
model, where it stands (screen pixels, the widget it's on), what it's doing,
its face. Commands go out on the broadcast every body already listens to, as
{"t": "body", "cmd": ...}; the bodies stay read-only listeners (they can't
type to her or press anything), and only she sends these.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path

from .base import Adapter, AdapterError, Verb

FRESH_S = 5.0
LOOKS = ("smile", "stars", "hearts", "blush", "angry", "tears", "eyeroll", "gloom", "wide", "sleepy",
         "dizzy", "soft", "smirk", "thoughtful", "blood")
SIDES = ("left", "center", "right", "floor")


def status_path() -> Path:
    base = Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share"))
    return base / "ariadne2" / "pet" / "body.json"


def _config(name: str):
    try:
        return json.loads((Path.home() / ".config" / "ariadne2" / name).read_text())
    except (OSError, ValueError):
        return None


def widgets_on_desk() -> list[str]:
    """Widget names she could stand on (shown ones; the core has no top to stand on)."""
    layout = _config("layout.json") or {}
    rects = layout.get("widgets", layout) if isinstance(layout, dict) else {}
    hidden = set(_config("hidden.json") or [])
    return sorted(n for n, r in rects.items() if isinstance(r, list) and n not in hidden and n != "core")


class AvatarAdapter(Adapter):
    name = "avatar"

    def __init__(self, publish) -> None:
        super().__init__(publish)
        self.settings = None             # set by the core: pin and unpin are his Avatar settings
        self.clock = time.time
        self.settle = 1.5                # tests set 0
        target = {"type": "string", "description": "a widget's name (spotify, chat, steam...), "
                  "left, center, right, floor, or an x position in pixels"}
        self.verbs = [
            Verb("status", "Where your body is and what it's doing: which body, where on the screen, "
                 "which widget it's standing on, what it's up to, its face.", {}, self._status),
            Verb("go", "Move your body: walk along where it stands, or jump onto a widget's top or down "
                 "to the floor.", {"properties": {"to": target}, "required": ["to"]}, self._go),
            Verb("dance", "Dance (with or without music) for a while.",
                 {"properties": {"seconds": {"type": "number", "description": "default 20"}}}, self._dance),
            Verb("stop", "Stop what your body is doing (a dance, a walk) and stand.", {}, self._stop),
            Verb("feel", "Pull a face for a few seconds.",
                 {"properties": {"look": {"type": "string", "enum": list(LOOKS)},
                                 "seconds": {"type": "number", "description": "default 4"}},
                  "required": ["look"]}, self._feel),
            Verb("sleep", "Curl up and sleep until something stirs you.", {}, self._sleep),
            Verb("wake", "Wake up.", {}, self._wake),
            Verb("pin", "Pin your body where it is (his Avatar setting): it stays put, even mid-air.",
                 {}, self._pin),
            Verb("unpin", "Unpin your body so it moves about again.", {}, self._unpin),
        ]

    # ---- reading ----
    def read(self) -> dict | None:
        try:
            d = json.loads(status_path().read_text())
        except (OSError, ValueError):
            return None
        return d if isinstance(d, dict) and self.clock() - float(d.get("ts", 0)) <= FRESH_S else None

    def describe(self, d: dict) -> str:
        w = max(1.0, float(d.get("w") or 1))
        x = float(d.get("x") or 0)
        side = "left" if x < w / 3 else "right" if x > 2 * w / 3 else "middle"
        on = d.get("on") or "floor"
        where = "on the floor" if on == "floor" else "in mid-air" if on == "air" else f"on top of the {on} widget"
        doing = {"stand": "standing", "idle": "standing", "walk": "walking", "wander": "walking",
                 "fall": "in the air", "held": "being held by him", "pinned": "pinned in place",
                 "dance": "dancing", "sleep": "asleep", "sit": "sitting", "knocked": "knocked over",
                 "fetch": "chasing the ball", "eat": "eating", "hug": "hugging a plush"}.get(
            str(d.get("mode")), str(d.get("mode") or "standing"))
        if d.get("dancing") and "danc" not in doing:
            doing += ", dancing"
        if d.get("asleep") and "asleep" not in doing:
            doing += ", asleep"
        body = f"{d.get('model') or 'your'} ({'Live2D' if d.get('kind') == 'live2d' else '3D'})"
        face = f", face: {d['look']}" if d.get("look") else ""
        faces = ""
        if d.get("looks"):
            own = [x for x in d.get("own") or [] if x in d["looks"]]
            rest = [x for x in d["looks"] if x not in own]
            faces = (f" Faces it can pull (feel): its own {', '.join(own)}" if own else " Faces it can pull (feel):") \
                + (f"; generic {', '.join(rest)}" if rest else "") + "."
        return f"Your body, {body}: {doing}, {where}, {side} of the screen (x {round(x)} of {round(w)} px){face}.{faces}"

    async def _status(self) -> str:
        d = await asyncio.to_thread(self.read)
        if d is None:
            return self._absent()
        return self.describe(d)

    def _absent(self) -> str:
        try:
            off = self.settings is not None and not self.settings.get("desktop", "body")
        except Exception:
            off = False
        if off:
            return ("Your body is turned off (his setting desktop.body), so it can't move or pull faces. "
                    "If he asks, turn it on with the settings tool: set desktop.body on.")
        return "Your body isn't on screen right now (it isn't running)."

    # ---- moving ----
    async def _cmd(self, cmd: str, **fields) -> None:
        if await asyncio.to_thread(self.read) is None:
            raise AdapterError(self._absent())
        await self.publish({"t": "body", "cmd": cmd, **fields})

    async def _after(self, said: str) -> str:
        await asyncio.sleep(self.settle)
        d = await asyncio.to_thread(self.read)
        return said + (" " + self.describe(d) if d else "")

    async def _go(self, to) -> str:
        t = str(to if to is not None else "").strip().lower()
        if not t:
            raise AdapterError("say where: a widget, left, center, right, floor, or an x in pixels")
        if t.lstrip("-").replace(".", "", 1).isdigit():
            await self._cmd("go", x=float(t))
            return await self._after(f"Going to x {round(float(t))}.")
        if t in SIDES:
            await self._cmd("go", side=t)
            return await self._after(f"Going to the {t}.")
        names = await asyncio.to_thread(widgets_on_desk)
        match = next((n for n in names if n == t), None) or next((n for n in names if n.startswith(t)), None)
        if match is None:
            raise AdapterError(f"no widget called {t!r} on the desk to stand on (there's {', '.join(names) or 'none'})")
        await self._cmd("go", widget=match)
        return await self._after(f"Jumping onto the {match} widget.")

    async def _dance(self, seconds=None) -> str:
        s = max(3.0, min(300.0, float(seconds or 20)))
        await self._cmd("dance", seconds=s)
        return f"Dancing for {round(s)} seconds."

    async def _stop(self) -> str:
        await self._cmd("stop")
        return await self._after("Stopped.")

    async def _feel(self, look: str, seconds=None) -> str:
        if look not in LOOKS:
            raise AdapterError(f"look is one of: {', '.join(LOOKS)}")
        await self._cmd("feel", look=look, seconds=max(1.0, min(30.0, float(seconds or 4))))
        return f"Pulling a {look} face."

    async def _sleep(self) -> str:
        await self._cmd("sleep")
        return "Curled up asleep."

    async def _wake(self) -> str:
        await self._cmd("wake")
        return "Awake."

    async def _pin(self) -> str:
        return self._set_pin(True)

    async def _unpin(self) -> str:
        return self._set_pin(False)

    def _set_pin(self, on: bool) -> str:
        if self.settings is None:
            raise AdapterError("I can't reach the Avatar settings")
        self.settings.set("avatar", "pinned", on)
        return "Pinned where she stands." if on else "Unpinned; she'll move about again."
