"""Her `later` tool: check-ins, so "I'll check when it's done" really happens.

Without it a turn ends and nothing brings her back: she'd promise to look at a
download or a long command and never return. A check-in wakes her with a turn
of her own, either after some minutes, or as soon as her downloads finish or
one of her background commands exits (with the minutes as the limit). That
turn carries his words from the turn that set it, so whatever he asked for
then can still be done; a check-in set where he said nothing (a flow's turn)
carries none. Pending check-ins are kept on disk, so a restart doesn't drop
them.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path

from ..adapters import AdapterError
from .tools.common import data_dir

log = logging.getLogger("ariadne2.later")

EVERY = 5.0
MAX_PENDING = 10
SETTLE = 10.0                # a downloads_done check-in waits this long for a download to show up first

TOOL = {
    "name": "later",
    "description": (
        "Set a check-in for when something needs time (a download, an install, a long command, a render): "
        "you'll get a turn of your own then, to carry on. Use it whenever you'd say you'll check, wait or "
        "come back; never promise that without setting one. when: 'time' wakes you after `minutes`; "
        "'downloads_done' as soon as the downloads you started finish; 'job_done' as soon as a background "
        "command (its pid) exits. For those two, `minutes` is the most to wait (default 120). list / cancel "
        "show or drop pending ones."),
    "input_schema": {"type": "object", "properties": {
        "action": {"type": "string", "enum": ["set", "list", "cancel"]},
        "note": {"type": "string", "description": "what to do when it fires, for your future self"},
        "when": {"type": "string", "enum": ["time", "downloads_done", "job_done"]},
        "minutes": {"type": "number", "description": "0.25 to 1440"},
        "pid": {"type": "integer", "description": "for job_done: the background command's pid"},
        "id": {"type": "integer", "description": "for cancel"},
    }, "required": ["action"]},
}


def _path() -> Path:
    return data_dir() / "later.json"


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class Later:
    def __init__(self, wake, downloads=None, path: Path | None = None, clock=time.time, alive=_alive) -> None:
        self.wake = wake                      # wake(text, consent): queue a turn of hers
        self.downloads = downloads            # core/downloads.py DownloadWatch, for downloads_done
        self.path = path or _path()
        self.clock = clock
        self.alive = alive
        self._task: asyncio.Task | None = None
        try:
            self.pending: list[dict] = json.loads(self.path.read_text())
        except (OSError, ValueError):
            self.pending = []

    def tools(self) -> list[dict]:
        return [TOOL]

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.pending))
        except OSError as e:
            log.warning("couldn't save check-ins: %s", e)

    @staticmethod
    def _hm(ts: float) -> str:
        return time.strftime("%H:%M", time.localtime(ts))

    async def call(self, name: str, args: dict, his_words: str | None = None) -> str:
        a = args or {}
        action = a.get("action")
        if action == "list":
            if not self.pending:
                return "No check-ins pending."
            return "\n".join(f"#{p['id']} {p['when']} (by {self._hm(p['due'])}): {p['note']}" for p in self.pending)
        if action == "cancel":
            before = len(self.pending)
            self.pending = [p for p in self.pending if p["id"] != a.get("id")]
            self._save()
            return "Cancelled." if len(self.pending) < before else "No check-in with that id."
        if action != "set":
            raise AdapterError("action is set, list or cancel")
        note = " ".join(str(a.get("note") or "").split())[:400]
        if not note:
            raise AdapterError("say what to do when it fires (note)")
        when = a.get("when") or "time"
        if when not in ("time", "downloads_done", "job_done"):
            raise AdapterError("when is time, downloads_done or job_done")
        if when == "job_done" and not isinstance(a.get("pid"), int):
            raise AdapterError("job_done needs the background command's pid")
        if len(self.pending) >= MAX_PENDING:
            raise AdapterError(f"{MAX_PENDING} check-ins are already pending; cancel one first")
        try:
            minutes = float(a.get("minutes") or (5 if when == "time" else 120))
        except (TypeError, ValueError):
            raise AdapterError("minutes should be a number")
        minutes = max(0.25, min(1440.0, minutes))
        now = self.clock()
        p = {"id": max([q["id"] for q in self.pending] + [0]) + 1, "note": note, "when": when,
             "pid": a.get("pid"), "set": now, "due": now + minutes * 60, "consent": his_words}
        self.pending.append(p)
        self._save()
        what = {"time": f"at {self._hm(p['due'])}",
                "downloads_done": f"when your downloads finish (or at {self._hm(p['due'])})",
                "job_done": f"when pid {p['pid']} exits (or at {self._hm(p['due'])})"}[when]
        return f"Check-in #{p['id']} set: you'll be woken {what}."

    # ---- firing ----

    def _ready(self, p: dict, now: float) -> str | None:
        """Why this check-in fires now, or None."""
        if now >= p["due"]:
            return f"It's {self._hm(now)}." if p["when"] == "time" else \
                f"It's {self._hm(now)} and what you were waiting on hasn't finished; see how it stands."
        if p["when"] == "job_done" and not self.alive(int(p["pid"])):
            return "That command has finished."
        if p["when"] == "downloads_done" and now - p["set"] > SETTLE and self.downloads is not None \
                and not self.downloads.active():
            return "Your downloads have finished."
        return None

    async def tick(self) -> None:
        now = self.clock()
        fired = []
        for p in list(self.pending):
            why = self._ready(p, now)
            if why:
                fired.append(p)
                self.pending.remove(p)
                text = (f"[Check-in you set at {self._hm(p['set'])}: \"{p['note']}\". {why} Carry on with it "
                        "now and tell him how it went. If it needs longer, set another check-in.]")
                self.wake(text, p.get("consent"))
        if fired:
            self._save()

    async def _loop(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception:
                log.exception("check-ins failed")
            await asyncio.sleep(EVERY)

    def start(self) -> None:
        self._task = asyncio.ensure_future(self._loop())

    def stop(self) -> None:
        if self._task:
            self._task.cancel()
