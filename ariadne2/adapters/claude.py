"""The Claude adapter: Claude Code sessions as her hands (DESIGN §3).

State comes from the transcripts Claude Code writes itself, one JSONL file per
session under ~/.claude/projects/<encoded folder>/<session id>.jsonl. Those files
run to hundreds of megabytes, so only the head (title, folder, start) and the tail
(what it is doing now) are ever read, and the step count is kept incrementally.
Nothing from a message ever reaches the state or the log: a title is the session's
own title entry or the start of his first prompt (credentials removed), and `last`
is a tool name plus a file name or the first words of a command.

Her own hands are `claude -p` runs she starts here. They are tracked in a small
registry under ~/.local/share/ariadne2/hands/ so a restarted core still knows them,
and they are the only sessions she may stop. Starting one spends his Claude usage,
so the verb carries consent="spend" (adapters/consent.py).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import signal
import subprocess
import time
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from .base import Adapter, AdapterError, Verb
from .redact import redact

log = logging.getLogger("ariadne2.adapters.claude")

WINDOW = 6 * 3600           # only sessions active in the last six hours
MAX_ROWS = 8
TITLE_MAX = 60
LAST_MAX = 40
HEAD_BYTES = 128 * 1024
TAIL_BYTES = 256 * 1024     # first try; grows when the last line is one huge tool result
TAIL_LIMIT = 32 * 1024 * 1024
MIDTURN_GRACE = 90.0        # between two steps it may think this long without writing anything
PENDING_MAX = 1800.0        # a tool call with no result this long is probably a dead session
FAST, SLOW = 3.0, 10.0      # poll periods: something happened in the last minute / nothing did
MAX_HANDS = 2               # her runs at once; each one spends his usage
MAX_BUDGET = 5.0            # --max-budget-usd guard per run
KEEP_RECORDS = 24 * 3600    # finished runs stay in the registry this long
KEEP_LOGS = 7 * 86400
ANNOUNCE_WITHIN = 900.0     # a finish found after a restart is still news for this long
STOP_WAIT = 5.0
END_REASONS = ("end_turn", "stop_sequence", "refusal", "max_tokens", "pause_turn")

# Her hands may edit files in the folder (never --dangerously-skip-permissions: that
# is not hers to hand out) and run tests and read-only git. Anything else is denied,
# because a headless run has nobody to ask.
HAND_TOOLS = ("Read", "Grep", "Glob", "Edit", "Write",
              "Bash(python3 -m unittest:*)", "Bash(python3 -m pytest:*)", "Bash(npm test:*)",
              "Bash(git status:*)", "Bash(git diff:*)", "Bash(git log:*)")
STEP = b'"type":"tool_use"'

_SCRIPT = ('task="$1"; log="$2"; done="$3"; shift 3; '
           '"$@" < "$task" >> "$log" 2>&1; echo $? > "$done"')


# ------------------------------------------------------------- reading transcripts

def short_target(name: str, inp) -> str:
    """The short thing a tool call was about: a file name, or the first words of a command."""
    inp = inp if isinstance(inp, dict) else {}
    name = str(name or "")
    if name.startswith("mcp__"):
        return ""
    if name == "Bash":
        return command_words(inp.get("command"))
    if name in ("Grep", "Glob"):
        return _clip(redact(str(inp.get("pattern") or "")), 24)
    if name == "WebFetch":
        try:
            return urlparse(str(inp.get("url") or "")).hostname or ""
        except ValueError:
            return ""
    if name == "Skill":
        return _clip(redact(str(inp.get("skill") or "")), 24)
    for key in ("file_path", "notebook_path", "path"):
        if inp.get(key):
            return _clip(os.path.basename(str(inp[key]).rstrip("/")), LAST_MAX)
    return ""


def command_words(cmd) -> str:
    """First few words of a shell command, past any `cd x &&` and VAR=value, credentials removed."""
    cmd = str(cmd or "").strip()
    for part in re.split(r"\s*(?:&&|\|\||;|\n)\s*", cmd):
        part = re.sub(r"""^(?:\w+=(?:"[^"]*"|'[^']*'|\S*)\s+)+""", "", part.strip())
        if not part or re.match(r"(?:cd|export|set|source|\.|pushd|popd)(?:\s|$)", part):
            continue
        toks = part.split()
        for i, t in enumerate(toks):                     # a quoted argument is prose: leave it out
            if t[:1] in "\"'":
                toks = toks[:i]
                break
        toks = [t for t in toks if t not in ("sudo", "env", "time", "nohup")]
        for i, t in enumerate(toks):                     # stop at a pipe, redirect or heredoc
            if t[:1] in "<>|&":
                toks = toks[:i]
                break
        toks = [os.path.basename(t.rstrip("/")) if "/" in t and not t.startswith("-") else t
                for t in toks[:4]]
        return _clip(redact(" ".join(t for t in toks if t)), LAST_MAX - 6)
    return ""


def tool_label(name: str, inp) -> str:
    name = str(name or "")
    if name.startswith("mcp__"):
        return _clip(name.split("__")[-1], LAST_MAX)
    target = short_target(name, inp)
    if name == "Bash":
        return f"Bash: {target}" if target else "Bash"
    return f"{name} {target}".strip()


def _clip(text: str, n: int) -> str:
    text = re.sub(r"[\x00-\x1f\x7f]+", " ", " ".join(str(text).split()))
    return text if len(text) <= n else text[:n - 1].rstrip() + "…"


def make_title(text: str) -> str:
    """A title from prose: credentials out first, then the first ~60 characters."""
    return _clip(redact(" ".join(str(text or "").split())[:600]), TITLE_MAX)


def _content_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(str(b.get("text") or "") for b in content
                        if isinstance(b, dict) and b.get("type") == "text")
    return ""


def _epoch(stamp) -> float | None:
    try:
        return datetime.fromisoformat(str(stamp).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _lines(blob: bytes, drop_first: bool, drop_last: bool) -> list[dict]:
    parts = blob.split(b"\n")
    if drop_first:
        parts = parts[1:]
    if drop_last:
        parts = parts[:-1]
    out = []
    for p in parts:
        if not p.strip():
            continue
        try:
            d = json.loads(p)
        except ValueError:
            continue                      # a half-written last line
        if isinstance(d, dict):
            out.append(d)
    return out


def read_head(path: Path) -> list[dict]:
    with open(path, "rb") as f:
        blob = f.read(HEAD_BYTES)
    return _lines(blob, False, len(blob) == HEAD_BYTES)


def read_tail(path: Path) -> list[dict]:
    """The last entries of the file, growing the window while the last line is one giant result."""
    size = os.path.getsize(path)
    want = TAIL_BYTES
    while True:
        want = min(want, size)
        with open(path, "rb") as f:
            f.seek(size - want)
            blob = f.read(want)
        entries = _lines(blob, want < size, False)
        convo = [e for e in entries if e.get("type") in ("user", "assistant")]
        if len(convo) >= 3 or want >= size or want >= TAIL_LIMIT:
            return entries
        want *= 8


def head_info(entries: list[dict]) -> dict:
    """Things fixed at the start of a session: when, where, and what he first asked."""
    info = {"cwd": None, "started": None, "prompt": None, "title": None}
    for d in entries:
        if info["started"] is None and isinstance(d.get("timestamp"), str):
            info["started"] = _epoch(d["timestamp"])
        if info["cwd"] is None and isinstance(d.get("cwd"), str):
            info["cwd"] = d["cwd"]
        if d.get("type") == "custom-title" and d.get("customTitle"):
            info["title"] = info["title"] or str(d["customTitle"])
        elif d.get("type") == "ai-title" and d.get("aiTitle") and not info["title"]:
            info["title"] = str(d["aiTitle"])
        if info["prompt"] is None and d.get("type") == "user" and not d.get("isMeta"):
            text = _content_text((d.get("message") or {}).get("content")).strip()
            if text and not text.startswith("<") and not text.startswith("Caveat:"):
                info["prompt"] = text
    return info


def tail_info(entries: list[dict]) -> dict:
    """What it is doing now: the last step, whether a tool call is still out, how the turn stands."""
    pending: dict[str, str] = {}
    last_tool = None
    kind = None
    title = {"custom": None, "ai": None}
    cwd = None
    for d in entries:
        t = d.get("type")
        if t == "custom-title" and d.get("customTitle"):
            title["custom"] = str(d["customTitle"])
        elif t == "ai-title" and d.get("aiTitle"):
            title["ai"] = str(d["aiTitle"])
        if t not in ("user", "assistant") or d.get("isSidechain"):
            continue
        if isinstance(d.get("cwd"), str):
            cwd = d["cwd"]
        msg = d.get("message") if isinstance(d.get("message"), dict) else {}
        content = msg.get("content")
        blocks = content if isinstance(content, list) else []
        if t == "assistant":
            used = [b for b in blocks if isinstance(b, dict) and b.get("type") == "tool_use"]
            for b in used:
                label = tool_label(b.get("name"), b.get("input"))
                pending[str(b.get("id"))] = label
                last_tool = label
            if used:
                kind = "tooluse"
            else:
                kind = "ended" if msg.get("stop_reason") in END_REASONS else "midturn"
        else:
            results = [b for b in blocks if isinstance(b, dict) and b.get("type") == "tool_result"]
            if results:
                for b in results:
                    pending.pop(str(b.get("tool_use_id")), None)
                kind = "result"
            elif _content_text(content).lstrip().startswith("[Request interrupted"):
                kind = "ended"
            else:
                kind = "prompt"
    return {"kind": kind, "pending": bool(pending), "last": last_tool or "",
            "title": title["custom"] or title["ai"], "cwd": cwd}


def derive_state(kind: str | None, pending: bool, age: float) -> str:
    """working / waiting from how the last turn stands and how long ago the file moved."""
    if pending:
        return "working" if age < PENDING_MAX else "waiting"
    if kind == "ended" or kind is None:
        return "waiting"
    return "working" if age < MIDTURN_GRACE else "waiting"


def count_steps(path: Path, cache: dict) -> int:
    """Tool calls in the whole file, counted only over the bytes added since last time."""
    size = os.path.getsize(path)
    off, total = cache.get(path, (0, 0))
    if size < off:
        off, total = 0, 0
    keep = b""
    with open(path, "rb") as f:
        f.seek(off)
        while off < size:
            chunk = f.read(min(4 << 20, size - off))
            if not chunk:
                break
            off += len(chunk)
            buf = keep + chunk
            total += buf.count(STEP)
            keep = buf[-(len(STEP) - 1):]       # shorter than a match, so nothing counts twice
    cache[path] = (off, total)
    return total


# ----------------------------------------------------------------- her own runs

def build_command(exe: str, session_id: str, budget: float = MAX_BUDGET) -> list[str]:
    """The claude argv for one hand. The brief arrives on stdin (see _SCRIPT), not in argv."""
    return [exe, "-p", "--output-format", "stream-json", "--verbose",
            "--session-id", session_id, "--permission-mode", "acceptEdits",
            "--max-budget-usd", f"{budget:.2f}", "--allowedTools", *HAND_TOOLS]


def _pid_alive(pid: int, run_id: str = "") -> bool:
    """Alive, not a zombie, and still the process we started (pids get reused)."""
    try:
        os.kill(pid, 0)
        with open(f"/proc/{pid}/stat") as f:
            if f.read().rsplit(")", 1)[1].split()[0] == "Z":
                return False
        if run_id:
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                return run_id.encode() in f.read()
        return True
    except (OSError, IndexError):
        return False


def _killgroup(pid: int, sig: int) -> None:
    try:
        os.killpg(pid, sig)
    except ProcessLookupError:
        pass
    except PermissionError as e:
        raise AdapterError(f"I'm not allowed to stop that run ({e.strerror})")


def _spawn(argv: list[str], cwd: str):
    env = {k: v for k, v in os.environ.items() if k not in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT")}
    return subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            start_new_session=True)


async def _xdg_open(path: str) -> None:
    if not shutil.which("xdg-open"):
        raise AdapterError("xdg-open isn't installed, so I can't open the folder")
    try:
        proc = await asyncio.create_subprocess_exec(
            "xdg-open", path, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL, start_new_session=True)
    except OSError as e:
        raise AdapterError(f"couldn't open the folder: {e.strerror}")
    try:
        code = await asyncio.wait_for(proc.wait(), 5)
    except asyncio.TimeoutError:
        return
    if code:
        raise AdapterError(f"couldn't open the folder (xdg-open exited {code})")


def _ago(seconds: float) -> str:
    s = max(0, int(seconds))
    if s < 90:
        return f"{s}s ago"
    return f"{s // 60}m ago" if s < 5400 else f"{s // 3600}h ago"


def blank_state(status: str = "ok") -> dict:
    return {"status": status, "sessions": []}


class ClaudeAdapter(Adapter):
    name = "claude"
    events = ("hand_finished", "session_waiting")
    event_info = {"hand_finished": {"phrase": "finishes a job she gave it",
                                    "fields": {"title": "text", "state": "text"}},
                  "session_waiting": {"phrase": "stops and waits for him",
                                      "fields": {"project": "text", "title": "text"}}}
    state_fields = {"status": ("text", "status")}

    def __init__(self, publish, projects=None, root=None, launcher=None, alive=None, killer=None,
                 opener=None, exe=None, now=None, home=None) -> None:
        super().__init__(publish)
        self.home = Path(home or Path.home())
        self.projects = Path(projects or self.home / ".claude" / "projects")
        self.root = Path(root or self.home / ".local" / "share" / "ariadne2" / "hands")
        self._launch = launcher or _spawn
        self._alive = alive or _pid_alive
        self._kill = killer or _killgroup
        self._open = opener or _xdg_open
        self._exe = exe                            # tests pass a path; None = look for claude
        self.now = now or time.time
        self.settle = 1.0                          # tests set 0
        self._state = blank_state()
        self._head: dict = {}                      # path -> head_info
        self._tail: dict = {}                      # path -> ((mtime, size), tail_info)
        self._steps: dict = {}                     # path -> (offset, count)
        self._cwd: dict[str, str] = {}             # session id -> folder, for `open`
        self._titles: dict[str, str] = {}
        self._prev: dict[str, str] = {}            # session id -> last published state
        self._baseline = True
        self._procs: dict = {}                     # run id -> Popen, so a child is reaped
        self.runs: list[dict] = self._load_runs()
        self._wake = asyncio.Event()
        self._main: asyncio.Task | None = None
        self._busy_until = 0.0
        self.controls = {"stop": "stop", "open": "open"}
        sess = {"type": "object", "properties": {"session": {"type": "string"}}, "required": ["session"]}
        self.verbs = [
            Verb("start", "Start a headless Claude Code run in a folder, as one of your own hands, and carry "
                 "on talking while it works. It spends his Claude usage, so only do it when he asked for "
                 "Claude or a hand to do the job. Give it a full, self-contained brief; it can edit files "
                 "in the folder and run tests, and nothing else. Two at most at once.",
                 {"type": "object", "properties": {"task": {"type": "string"}, "folder": {"type": "string"}},
                  "required": ["task", "folder"]}, self._start, "start", consent="spend"),
            Verb("status", "What Claude Code sessions are active (his and your own hands): title, state "
                 "(working / waiting / done / failed), the latest step, step count. With a session id, just "
                 "that one. Never shows what was said.",
                 {"type": "object", "properties": {"session": {"type": "string"}}}, self._status),
            Verb("stop", "Stop a run you started. Refuses his own interactive sessions; give the session "
                 "id from status.", sess, self._stop, "stop"),
            Verb("open", "Open a session's folder in the file manager.", sess, self._open_folder, "open"),
        ]

    # ---- lifecycle ----

    async def start(self) -> None:
        self._main = asyncio.create_task(self._loop())
        await self.refresh()

    async def stop(self) -> None:
        if self._main:
            self._main.cancel()
            await asyncio.gather(self._main, return_exceptions=True)

    def state(self) -> dict:
        return self._state

    def _poke(self) -> None:
        self._busy_until = time.monotonic() + 60
        self._wake.set()

    def _period(self) -> float:
        busy = time.monotonic() < self._busy_until or any(
            s["state"] == "working" for s in self._state["sessions"])
        return FAST if busy else SLOW

    async def _loop(self) -> None:
        while True:
            try:
                await asyncio.wait_for(self._wake.wait(), self._period())
                await asyncio.sleep(0.2)
            except asyncio.TimeoutError:
                pass
            self._wake.clear()
            try:
                await self.refresh()
            except Exception:
                log.exception("claude refresh failed")

    # ---- the registry of her runs ----

    def _runs_file(self) -> Path:
        return self.root / "runs.json"

    def _load_runs(self) -> list[dict]:
        try:
            data = json.loads(self._runs_file().read_text())
            return [r for r in data if isinstance(r, dict) and r.get("id")]
        except (OSError, ValueError):
            return []

    def _save_runs(self) -> None:
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            tmp = self._runs_file().with_suffix(".tmp")
            tmp.write_text(json.dumps(self.runs))
            os.replace(tmp, self._runs_file())
        except OSError as e:
            log.warning("couldn't save the hands registry: %s", e.strerror)

    def _prune(self, now: float) -> None:
        keep = []
        for r in self.runs:
            if r.get("finished") and now - r["finished"] > KEEP_RECORDS and r.get("announced"):
                for ext in ("task", "exit"):
                    (self.root / f"{r['id']}.{ext}").unlink(missing_ok=True)
            else:
                keep.append(r)
        self.runs = keep
        try:
            for f in self.root.glob("*.log"):
                if now - f.stat().st_mtime > KEEP_LOGS:
                    f.unlink()
        except OSError:
            pass

    def _settle_runs(self, now: float) -> list[dict]:
        """Notice runs that ended; returns the ones whose finish hasn't been announced yet."""
        news, changed = [], False
        for r in self.runs:
            proc = self._procs.get(r["id"])
            if proc is not None and hasattr(proc, "poll") and proc.poll() is not None:
                self._procs.pop(r["id"], None)          # reaped
            if not r.get("finished"):
                done = self.root / f"{r['id']}.exit"
                code = None
                try:
                    code = int(done.read_text().strip())
                    r["finished"] = done.stat().st_mtime
                except (OSError, ValueError):
                    if not self._alive(r["pid"], r["id"]):
                        r["finished"] = now              # killed or crashed: no exit code was written
                if r.get("finished"):
                    r["code"] = code
                    r["state"] = "done" if code == 0 else "failed"
                    changed = True
            if r.get("finished") and not r.get("announced"):
                r["announced"] = True
                changed = True
                if not r.get("stopped") and now - r["finished"] <= ANNOUNCE_WITHIN:
                    news.append(r)
        if changed:
            self._save_runs()
        return news

    def _run(self, key: str) -> dict | None:
        return next((r for r in self.runs if r["id"] == key), None)

    def _running(self) -> list[dict]:
        return [r for r in self.runs if not r.get("finished")]

    # ---- scanning ----

    def _candidates(self, now: float) -> dict[str, tuple[Path, float]]:
        """session id -> (file, last activity) for transcripts touched inside the window."""
        out: dict[str, tuple[Path, float]] = {}
        try:
            dirs = [d for d in self.projects.iterdir() if d.is_dir()]
        except OSError:
            return out
        for d in dirs:
            try:
                files = list(d.glob("*.jsonl"))
            except OSError:
                continue
            for f in files:
                try:
                    mt = f.stat().st_mtime
                except OSError:
                    continue
                if now - mt > 24 * 3600:
                    continue
                sub = d / f.stem / "subagents"          # background agents write here, not in the main file
                try:
                    for s in os.scandir(sub):
                        mt = max(mt, s.stat().st_mtime)
                except OSError:
                    pass
                if now - mt > WINDOW:
                    continue
                if f.stem not in out or out[f.stem][1] < mt:
                    out[f.stem] = (f, mt)
        return out

    def _read(self, path: Path) -> dict:
        """Everything the rows need from one transcript, parsed only when the file changed."""
        st = path.stat()
        sig = (st.st_mtime, st.st_size)
        head = self._head.get(path)
        if head is None:
            head = head_info(read_head(path))
            if head["prompt"] or st.st_size > HEAD_BYTES:
                self._head[path] = head
        cached = self._tail.get(path)
        if cached and cached[0] == sig:
            tail = cached[1]
        else:
            tail = tail_info(read_tail(path))
            self._tail[path] = (sig, tail)
        title = tail["title"] or head["title"]
        title = make_title(title) if title else make_title(head["prompt"] or "") or "Untitled session"
        cwd = tail["cwd"] or head["cwd"]
        return {"title": title, "cwd": cwd, "started": head["started"] or st.st_ctime,
                "kind": tail["kind"], "pending": tail["pending"], "last": tail["last"],
                "steps": count_steps(path, self._steps)}

    def _project(self, cwd: str | None) -> str:
        if not cwd:
            return "unknown"
        p = Path(cwd)
        return "~" if p == self.home else _clip(p.name or str(p), 24)

    def _scan(self, now: float) -> dict[str, dict]:
        rows = {}
        for sid, (path, updated) in self._candidates(now).items():
            try:
                info = self._read(path)
            except OSError:
                continue
            rows[sid] = {"id": sid, "project": self._project(info["cwd"]), "title": info["title"],
                         "state": derive_state(info["kind"], info["pending"], now - updated),
                         "last": info["last"], "steps": info["steps"],
                         "started": int(info["started"]), "updated": int(updated), "mine": False,
                         "_cwd": info["cwd"]}
        if len(self._head) > 200:                       # forget files that fell out of the window
            keep = {c[0] for c in self._candidates(now).values()}
            for cache in (self._head, self._tail, self._steps):
                for path in [p for p in cache if p not in keep]:
                    cache.pop(path, None)
        return rows

    def _merge_mine(self, rows: dict[str, dict], now: float) -> None:
        for r in self.runs:
            if r.get("finished") and now - r["finished"] > WINDOW:
                continue
            row = rows.get(r["id"])
            state = "working" if not r.get("finished") else r.get("state", "failed")
            base = row or {"id": r["id"], "project": self._project(r["folder"]), "last": "starting",
                           "steps": 0, "started": int(r["started"]), "updated": int(r["started"]),
                           "_cwd": r["folder"]}
            base.update({"title": r["title"], "state": state, "mine": True})
            base["updated"] = int(max(base["updated"], r.get("finished") or 0, r["started"]))
            if not r.get("finished") and base["last"] == "":
                base["last"] = "thinking"
            rows[r["id"]] = base

    async def refresh(self) -> None:
        now = self.now()
        news = self._settle_runs(now)
        self._prune(now)
        rows = await asyncio.to_thread(self._scan, now)
        self._merge_mine(rows, now)
        ordered = sorted(rows.values(), key=lambda r: (-r["updated"], r["id"]))
        self._cwd = {r["id"]: r["_cwd"] for r in ordered if r.get("_cwd")}
        self._titles = {r["id"]: r["title"] for r in ordered}
        shown = [{k: v for k, v in r.items() if not k.startswith("_")} for r in ordered[:MAX_ROWS]]
        has_claude = self.projects.is_dir() or self._find_exe() is not None
        new = {"status": "ok" if has_claude else "no claude", "sessions": shown}
        self._events(ordered, news)
        if new != self._state:
            self._state = new
            await self.publish_state()

    def _events(self, rows: list[dict], news: list[dict]) -> None:
        now_states = {r["id"]: r["state"] for r in rows}
        if not self._baseline:
            for r in rows:
                if not r["mine"] and self._prev.get(r["id"]) == "working" and r["state"] == "waiting":
                    self.emit("session_waiting", project=r["project"], title=r["title"])
        self._baseline = False
        self._prev = now_states
        for r in news:                                    # runs found finished, baseline or not
            self.emit("hand_finished", title=r["title"], state=r["state"])

    # ---- finding sessions by what he or she says ----

    def _resolve(self, ref) -> str:
        ref = str(ref or "").strip()
        if not ref:
            raise AdapterError("say which session (the id from status)")
        ids = list(self._titles)
        for r in self.runs:
            if r["id"] not in ids:
                ids.append(r["id"])
        if ref in ids:
            return ref
        low = ref.lower()
        hits = [i for i in ids if i.lower().startswith(low)] if len(low) >= 4 else []
        if not hits:
            hits = [i for i in ids if low in (self._titles.get(i) or "").lower()]
        if not hits:
            raise AdapterError(f"I can't find a Claude session matching {ref!r}")
        if len(hits) > 1:
            raise AdapterError(f"{ref!r} matches more than one session; use the id from status")
        return hits[0]

    # ---- verbs ----

    def _find_exe(self) -> str | None:
        if self._exe:
            return self._exe
        found = shutil.which("claude")
        if found:
            return found
        for p in (self.home / ".local" / "bin" / "claude", self.home / ".claude" / "local" / "claude"):
            if p.is_file() and os.access(p, os.X_OK):
                return str(p)
        return None

    def _folder(self, folder) -> Path:
        text = str(folder or "").strip()
        if not text:
            raise AdapterError("say which folder it should work in")
        path = Path(os.path.expanduser(text))
        if not path.is_absolute():
            path = self.home / path
        try:
            real = path.resolve(strict=True)
            home = self.home.resolve()
        except OSError:
            raise AdapterError(f"{text} isn't a folder I can find")
        if not real.is_dir():
            raise AdapterError(f"{text} isn't a folder")
        if real != home and home not in real.parents:
            raise AdapterError("it can only work inside his home folder")
        return real

    async def _start(self, task: str, folder: str) -> str:
        brief = str(task or "").strip()
        if len(brief) < 8:
            raise AdapterError("the hand needs a real brief: what to do, in full")
        brief = brief[:20000]
        where = self._folder(folder)
        exe = self._find_exe()
        if not exe:
            raise AdapterError("Claude Code isn't installed here")
        busy = self._running()
        if len(busy) >= MAX_HANDS:
            raise AdapterError(f"both hands are busy ({'; '.join(r['title'] for r in busy)}). "
                               "Wait for one, or stop one.")
        sid = str(uuid.uuid4())
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            os.chmod(self.root, 0o700)
            taskfile = self.root / f"{sid}.task"
            fd = os.open(taskfile, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as f:
                f.write(brief)
        except OSError as e:
            raise AdapterError(f"couldn't prepare the run ({e.strerror})")
        logfile = self.root / f"{sid}.log"
        argv = ["sh", "-c", _SCRIPT, "ariadne2-hand", str(taskfile), str(logfile),
                str(self.root / f"{sid}.exit"), *build_command(exe, sid)]
        try:
            proc = await asyncio.to_thread(self._launch, argv, str(where))
        except OSError as e:
            taskfile.unlink(missing_ok=True)
            raise AdapterError(f"couldn't start Claude Code ({e.strerror})")
        self._procs[sid] = proc
        self.runs.append({"id": sid, "pid": proc.pid, "folder": str(where), "title": make_title(brief) or "Hand",
                          "started": self.now(), "finished": None, "code": None, "state": "working",
                          "stopped": False, "announced": False, "log": str(logfile)})
        self._save_runs()
        self._poke()
        await self.refresh()
        return (f"Started a Claude Code run in {where.name or where} (session {sid[:8]}). It works in the "
                "background; I'll hear when it finishes.")

    async def _status(self, session: str | None = None) -> str:
        await self.refresh()
        now = self.now()
        rows = self._state["sessions"]
        if session:
            sid = self._resolve(session)
            row = next((r for r in rows if r["id"] == sid), None)
            if row is None:
                raise AdapterError("that session isn't active any more")
            rows = [row]
        elif not rows:
            return ("No Claude Code sessions in the last 6 hours."
                    if self._state["status"] == "ok" else "Claude Code doesn't seem to be installed here.")
        lines = []
        for r in rows:
            took = f", {r['steps']} steps" if r["steps"] else ""
            last = f" — {r['last']}" if r["last"] else ""
            hers = " (my hand)" if r["mine"] else ""
            lines.append(f"[{r['state']}] {r['project']}: {r['title']}{last}{took}, "
                         f"updated {_ago(now - r['updated'])}, id {r['id'][:8]}{hers}")
            if session and r["mine"]:
                run = self._run(r["id"])
                if run:
                    lines.append(f"started {_ago(now - r['started'])}; its output is in {run['log']}")
        working = sum(r["state"] == "working" for r in rows)
        head = f"{len(rows)} Claude session{'s' if len(rows) != 1 else ''}, {working} working:" if not session else ""
        return (head + "\n" if head else "") + "\n".join(lines)

    async def _stop(self, session: str) -> str:
        sid = self._resolve(session)
        run = self._run(sid)
        if run is None:
            raise AdapterError("that's one of his own Claude sessions; I only stop runs I started")
        if run.get("finished"):
            return f"{run['title']} had already finished."
        run["stopped"] = True
        self._save_runs()
        self._kill(run["pid"], signal.SIGTERM)
        deadline = time.monotonic() + STOP_WAIT * self.settle
        while self._alive(run["pid"], run["id"]):
            if time.monotonic() >= deadline:
                self._kill(run["pid"], signal.SIGKILL)
                break
            await asyncio.sleep(0.2 * self.settle)
        self._poke()
        await self.refresh()
        return f"Stopped {run['title']}."

    async def _open_folder(self, session: str) -> str:
        sid = self._resolve(session)
        cwd = self._cwd.get(sid) or (self._run(sid) or {}).get("folder")
        if not cwd or not os.path.isdir(cwd):
            raise AdapterError("I don't know that session's folder any more")
        await self._open(cwd)
        return f"Opened {os.path.basename(cwd) or cwd}."

    # ---- his clicks in the widget ----

    def press_args(self, control: str, value) -> dict:
        if value is None:
            raise AdapterError(f"{control} needs a session")
        return {"session": str(value)}
