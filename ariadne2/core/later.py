"""Her `later` tool: check-ins, so "I'll check when it's done" really happens.

Without it a turn ends and nothing brings her back: she'd promise to look at a
download or a long command and never return. A check-in wakes her with a turn
of her own when something has happened: her downloads finished, a job of hers
ended (by its tag, so one she detached with nohup or setsid counts), a file
stopped growing, a log said something, a program started or quit, a port
opened. The minutes are only the limit. A bare time is for "remind me at".
She used to guess the minutes, and was wrong both ways: woken too early to
find it unfinished, or a minute late for a download he was waiting on.

`wait` is the same conditions inside a turn, for short things (an app coming
up, a server starting), instead of `sleep 8; check`.

That turn carries his words from the turn that set it, so whatever he asked
for then can still be done; a check-in set where he said nothing (a flow's
turn) carries none. Pending check-ins are kept on disk, so a restart doesn't
drop them.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import socket
import time
from pathlib import Path

from ..adapters import AdapterError
from .tools.common import data_dir

log = logging.getLogger("ariadne2.later")

EVERY = 5.0
MAX_PENDING = 10
SETTLE = 10.0                # a downloads_done check-in waits this long for a download to show up first
QUIET = 10.0                 # file_ready: unchanged this long (a writer flushing in bursts pauses less)
WAIT_MAX = 120.0             # the longest `wait` holds a turn; past that it's a check-in
WHENS = ("time", "downloads_done", "job_done", "file_ready", "log_says", "process_gone", "process_up", "port_open")

TOOL = {
    "name": "later",
    "description": (
        "Wait for something to finish without guessing how long it takes. set: a check-in that wakes you "
        "with a turn of your own the moment it happens (use it whenever you'd say you'll check, wait or come "
        "back; never promise that without one). wait: the same, inside this turn, up to 2 minutes, for short "
        "things like an app or a server coming up; never `sleep N` in the shell to wait. when: job_done (job: "
        "the tag the shell gave you, or pid; anything it started, even with nohup/setsid), downloads_done, "
        "file_ready (path: exists and stopped growing), log_says (path + match: a regex), process_gone / "
        "process_up (match: part of its command line), port_open (port), or time (only for a set hour or "
        "'remind me in'). minutes is just the limit (default 120). list / cancel."),
    "input_schema": {"type": "object", "properties": {
        "action": {"type": "string", "enum": ["set", "wait", "list", "cancel"]},
        "note": {"type": "string", "description": "for set: what to do when it fires, for your future self"},
        "when": {"type": "string", "enum": list(WHENS)},
        "minutes": {"type": "number", "description": "the limit: 0.25 to 1440 (wait: up to 2)"},
        "job": {"type": "string", "description": "job_done: the job tag the shell reported"},
        "pid": {"type": "integer", "description": "job_done: a pid, if there's no tag"},
        "path": {"type": "string", "description": "file_ready / log_says"},
        "match": {"type": "string", "description": "log_says: a regex; process_*: part of the command line"},
        "port": {"type": "integer", "description": "port_open (on this machine)"},
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


def _procs(proc: str = "/proc") -> list[tuple[str, str, str | None]]:
    """(pid, command line, job tag) for his live processes, hers left out."""
    from .downloads import _job_of
    me, out = os.getuid(), []
    for pid in os.listdir(proc):
        if not pid.isdigit() or int(pid) == os.getpid():
            continue
        try:
            if os.stat(f"{proc}/{pid}").st_uid != me:
                continue
            with open(f"{proc}/{pid}/stat", "rb") as fh:
                if fh.read().rsplit(b")", 1)[-1].split()[:1] == [b"Z"]:
                    continue                  # (a zombie has finished)
            with open(f"{proc}/{pid}/cmdline", "rb") as fh:
                cmd = fh.read().replace(b"\0", b" ").decode("utf-8", "replace").strip()
        except OSError:
            continue
        if cmd and not re.search(r"-m ariadne2\.(core|desk)\b", cmd):
            out.append((pid, cmd, _job_of(pid, proc)))
    return out


def _port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


def _size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def _ago(seconds: float) -> str:
    s = int(seconds)
    return f"{s} s" if s < 90 else f"{s // 60} min {s % 60:02d} s" if s < 3600 else f"{s // 3600} h {s % 3600 // 60} min"


class Later:
    def __init__(self, wake, downloads=None, path: Path | None = None, clock=time.time, alive=_alive,
                 procs=_procs, port_open=_port_open) -> None:
        self.wake = wake                      # wake(text, consent): queue a turn of hers
        self.downloads = downloads            # core/downloads.py DownloadWatch, for downloads_done
        self.path = path or _path()
        self.clock = clock
        self.alive = alive
        self.procs = procs
        self.port_open = port_open
        self.sleep = asyncio.sleep
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
            return "\n".join(f"#{p['id']} {self._what(p)} (limit {self._hm(p['due'])}): {p['note']}"
                             for p in self.pending)
        if action == "cancel":
            before = len(self.pending)
            self.pending = [p for p in self.pending if p["id"] != a.get("id")]
            self._save()
            return "Cancelled." if len(self.pending) < before else "No check-in with that id."
        if action not in ("set", "wait"):
            raise AdapterError("action is set, wait, list or cancel")
        when = a.get("when") or ("time" if action == "set" else "")
        if when not in WHENS or (action == "wait" and when == "time"):
            raise AdapterError("when is one of " + ", ".join(WHENS[1:] if action == "wait" else WHENS))
        p = self._condition(when, a)
        try:
            minutes = float(a.get("minutes") or (5 if when == "time" else 1 if action == "wait" else 120))
        except (TypeError, ValueError):
            raise AdapterError("minutes should be a number")
        now = self.clock()
        p["set"] = now
        if when != "time":
            already = self._ready(p, now, first=True)
            if already:
                return f"No need to wait: {already}"
        if action == "wait":
            return await self._wait(p, min(WAIT_MAX, max(1.0, minutes * 60)))
        note = " ".join(str(a.get("note") or "").split())[:400]
        if not note:
            raise AdapterError("say what to do when it fires (note)")
        if len(self.pending) >= MAX_PENDING:
            raise AdapterError(f"{MAX_PENDING} check-ins are already pending; cancel one first")
        minutes = max(0.25, min(1440.0, minutes))
        p.update(id=max([q["id"] for q in self.pending] + [0]) + 1, note=note, due=now + minutes * 60,
                 consent=his_words)
        self.pending.append(p)
        self._save()
        if when == "time":
            return f"Check-in #{p['id']} set: you'll be woken at {self._hm(p['due'])}."
        return f"Check-in #{p['id']} set: you'll be woken the moment {self._what(p)} (limit {self._hm(p['due'])})."

    def _condition(self, when: str, a: dict) -> dict:
        """The check-in's condition from her arguments, checked."""
        p: dict = {"when": when}
        if when == "job_done":
            job, pid = str(a.get("job") or "").strip(), a.get("pid")
            if not job and not isinstance(pid, int):
                raise AdapterError("job_done needs the job tag the shell reported (or a pid)")
            p.update(job=job or None, pid=pid if isinstance(pid, int) else None)
        elif when in ("file_ready", "log_says"):
            path = str(a.get("path") or "").strip()
            if not path:
                raise AdapterError(f"{when} needs a path")
            p["path"] = str(Path(os.path.expanduser(path)))
            try:
                p["start_size"] = os.path.getsize(p["path"])
            except OSError:
                p["start_size"] = 0
        if when in ("log_says", "process_gone", "process_up"):
            match = str(a.get("match") or "").strip()
            if not match:
                raise AdapterError(f"{when} needs match")
            try:
                re.compile(match)
            except re.error:
                if when == "log_says":
                    raise AdapterError("match isn't a valid regex")
            p["match"] = match
        if when == "port_open":
            if not isinstance(a.get("port"), int) or not 0 < a["port"] < 65536:
                raise AdapterError("port_open needs a port number")
            p["port"] = a["port"]
        return p

    def _what(self, p: dict) -> str:
        return {"time": "the time comes",
                "downloads_done": "your downloads finish",
                "job_done": f"job {p.get('job') or 'pid ' + str(p.get('pid'))} ends",
                "file_ready": f"{p.get('path')} is there and has stopped growing",
                "log_says": f"{p.get('path')} says /{p.get('match')}/",
                "process_gone": f"nothing running matches '{p.get('match')}'",
                "process_up": f"something running matches '{p.get('match')}'",
                "port_open": f"port {p.get('port')} answers"}[p["when"]]

    async def _wait(self, p: dict, limit: float) -> str:
        """Hold this turn until the condition is met, polling each second, at most `limit` seconds."""
        start = self.clock()
        while True:
            await self.sleep(1.0)
            now = self.clock()
            why = self._ready(p, now)
            if why:
                return f"{why} (after {_ago(now - start)})"
            if now - start >= limit:
                return (f"Not yet after {_ago(now - start)}: still waiting for {self._what(p)}. "
                        f"{self._progress(p)}If it's slow, set a check-in with the same condition rather "
                        "than waiting longer here.")

    # ---- firing ----

    def _ready(self, p: dict, now: float, first: bool = False) -> str | None:
        """Why this check-in fires now, or None. `first`: checked as it's set (a file
        can't have stopped growing yet, and downloads may not have shown up)."""
        when = p["when"]
        if "due" in p and now >= p["due"]:
            return f"It's {self._hm(now)}." if when == "time" else \
                (f"It's {self._hm(now)} and {self._what(p)} hasn't happened yet ({_ago(now - p['set'])} on). "
                 f"{self._progress(p)}See how it stands.")
        took = f" It took {_ago(now - p['set'])}." if not first else ""
        if when == "job_done":
            if p.get("job"):
                left = [cmd for _, cmd, job in self.procs() if job == p["job"]]
                if not left:
                    return "That job has finished: nothing it started is still running." + took
            elif not self.alive(int(p["pid"])):
                return "That command has finished." + took
        elif when == "downloads_done":
            if not first and now - p["set"] > SETTLE and self.downloads is not None and not self.downloads.active():
                return "Your downloads have finished." + took
        elif when == "file_ready":
            try:
                st = os.stat(p["path"])
            except OSError:
                return None
            if (st.st_size, st.st_mtime) != (p.get("size"), p.get("mtime")):
                p.update(size=st.st_size, mtime=st.st_mtime, still=now)
            elif not first and st.st_size > 0 and now - p["still"] >= QUIET:
                return f"{p['path']} is there ({_size(st.st_size)}) and has stopped growing." + took
        elif when == "log_says":
            hit = self._log_hit(p)
            if hit:
                return f"{p['path']} says: {hit}" + took
        elif when in ("process_gone", "process_up"):
            running = [cmd for _, cmd, _ in self.procs() if self._matches(p["match"], cmd)]
            if when == "process_gone" and not running:
                return (f"Nothing matching '{p['match']}' is running" + (" now." if not first else ".") + took)
            if when == "process_up" and running:
                return f"It's running: {running[0][:100]}." + took
        elif when == "port_open":
            if self.port_open(p["port"]):
                return f"Port {p['port']} answers." + took
        return None

    @staticmethod
    def _matches(match: str, cmd: str) -> bool:
        try:
            return re.search(match, cmd, re.I) is not None
        except re.error:
            return match.lower() in cmd.lower()

    @staticmethod
    def _log_hit(p: dict) -> str | None:
        try:
            with open(p["path"], "rb") as fh:
                fh.seek(max(0, os.path.getsize(p["path"]) - 65536))
                text = fh.read().decode("utf-8", "replace")
        except OSError:
            return None
        m = None
        for m in re.finditer(p["match"], text, re.I | re.M):
            pass                                  # (the last one: the freshest)
        if not m:
            return None
        start = text.rfind("\n", 0, m.start()) + 1
        end = text.find("\n", m.end())
        return text[start:end if end >= 0 else None].strip()[:200]

    def _progress(self, p: dict) -> str:
        """How it's moving, for a limit hit: so she can tell slow from stuck."""
        when = p["when"]
        if when in ("file_ready", "log_says") and p.get("path"):
            try:
                size = os.path.getsize(p["path"])
            except OSError:
                return "The file isn't there yet. "
            grew = size - p.get("start_size", size)
            return f"The file is {_size(size)}" + (f", {_size(grew)} more than when you set it. " if grew > 0 else ", not growing. ")
        if when == "job_done" and p.get("job"):
            left = [cmd[:80] for _, cmd, job in self.procs() if job == p["job"]]
            return ("Still running: " + "; ".join(left[:3]) + ". ") if left else ""
        return ""

    async def tick(self) -> None:
        """Fire every check-in whose condition is met (or whose limit has passed)."""
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
