"""The Claude widget's live session: the real `claude` CLI, driven over stream-json.

His own Claude Code, in the widget. One process per session, kept open between
messages (`--input-format stream-json`), so it is the same Claude Code he runs in a
terminal: his login, his settings, his CLAUDE.md, his tools. Permission questions
come back over stdio (`--permission-prompt-tool stdio`) and are put to him as
Allow / Deny cards; nothing is allowed on his behalf.

This is his conversation, not hers: what he types here is never sent to Aries,
and nothing Claude says here reaches her prompt. It is also not one of her hands
(adapters/claude.py), so it carries no spend consent: he is the one typing.

Desk -> core: {"t": "cc_do", "op": ...}
  hello | new {cwd} | resume {session} | send {text} | stop | answer {req, allow, always}
  | mode {mode} | model {model} | end
Core -> desk: {"t": "cc", "ev": ...}
  status {state, session, cwd, model, mode, cost, title} | folders {items}
  | clear | history {items} | user {text} | delta {text} | text {text} | thinking
  | tool {id, name, label, input} | tool_done {id, error, preview}
  | ask {req, tool, label, input, always} | asked {req} | done {cost, error} | error {text}
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import uuid
from pathlib import Path

from ..adapters import claude as cc

log = logging.getLogger("ariadne2.claude_live")

MODES = ("default", "acceptEdits", "plan")          # never bypassPermissions from a widget
MODELS = ("", "opus", "sonnet", "haiku")            # "" = his Claude Code default
LINE_LIMIT = 64 * 1024 * 1024                       # one tool result can be a very long line
PREVIEW = 1500                                      # characters of a tool's input or result shown
HISTORY = 60                                        # items shown when a session is resumed
SIGNED_OUT = ("failed to authenticate", "/login", "not logged in", "oauth")


def _preview(value, n: int = PREVIEW) -> str:
    if not isinstance(value, str):
        try:
            value = json.dumps(value, indent=1, ensure_ascii=False)
        except (TypeError, ValueError):
            value = str(value)
    return value if len(value) <= n else value[:n] + f"\n… ({len(value) - n} more characters)"


def _result_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(b.get("text", "")) if isinstance(b, dict) and b.get("type") == "text"
                         else "[image]" if isinstance(b, dict) and b.get("type") == "image" else ""
                         for b in content).strip()
    return ""


def history_items(entries: list[dict]) -> list[dict]:
    """A transcript's tail as the widget's items: his words, Claude's text, tool calls."""
    items: list[dict] = []
    for e in entries:
        msg = e.get("message") or {}
        content = msg.get("content")
        if e.get("type") == "user" and not e.get("isMeta"):
            if isinstance(content, str):
                if not content.startswith("<"):            # command wrappers, caveats
                    items.append({"kind": "user", "text": content})
            elif isinstance(content, list):
                for b in content:
                    if not isinstance(b, dict):
                        continue
                    if b.get("type") == "text" and not str(b.get("text", "")).startswith("<"):
                        items.append({"kind": "user", "text": b["text"]})
                    elif b.get("type") == "tool_result":
                        items.append({"kind": "tool_done", "id": b.get("tool_use_id", ""),
                                      "error": bool(b.get("is_error")),
                                      "preview": _preview(_result_text(b.get("content")))})
        elif e.get("type") == "assistant" and isinstance(content, list):
            for b in content:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "text" and b.get("text"):
                    items.append({"kind": "text", "text": b["text"]})
                elif b.get("type") == "tool_use":
                    items.append({"kind": "tool", "id": b.get("id", ""), "name": b.get("name", ""),
                                  "label": cc.tool_label(b.get("name"), b.get("input")),
                                  "input": _preview(b.get("input"))})
    return items[-HISTORY:]


class LiveClaude:
    def __init__(self, publish, *, home: Path | None = None, projects: Path | None = None,
                 exe: str | None = None, spawn=asyncio.create_subprocess_exec) -> None:
        self.publish = publish
        self.home = home or Path.home()
        self.projects = projects or self.home / ".claude" / "projects"
        self._exe = exe
        self._spawn = spawn
        self.proc = None
        self._reader: asyncio.Task | None = None
        self._stderr: list[str] = []
        self.state = "idle"
        self.session: str | None = None
        self.cwd = str(self.home / "Claude Projects")
        self.mode = "default"
        self.model = ""
        self.cost = 0.0
        self.title = ""
        self.asks: dict[str, dict] = {}          # request id -> the can_use_tool request
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------ out
    async def _ev(self, ev: str, **fields) -> None:
        await self.publish({"t": "cc", "ev": ev, **fields})

    async def _status(self, state: str | None = None) -> None:
        if state:
            self.state = state
        await self._ev("status", state=self.state, session=self.session or "", cwd=self.cwd,
                       model=self.model, mode=self.mode, cost=round(self.cost, 4), title=self.title,
                       modes=list(MODES), models=list(MODELS))

    def folders(self) -> list[str]:
        root = self.home / "Claude Projects"
        try:
            out = [str(p) for p in sorted(root.iterdir()) if p.is_dir() and not p.name.startswith(".")]
        except OSError:
            out = []
        return [str(root), *out]

    # ------------------------------------------------------------------- in
    async def on_desk(self, msg: dict) -> None:
        op = msg.get("op")
        try:
            if op == "hello":
                await self._ev("folders", items=self.folders())
                await self._status()
            elif op == "new":
                await self.end()
                cwd = str(msg.get("cwd") or self.cwd)
                if not Path(cwd).is_dir():
                    raise ValueError(f"no folder {cwd}")
                self.cwd, self.session, self.cost, self.title = cwd, None, 0.0, ""
                await self._ev("clear")
                await self._status("idle")
            elif op == "resume":
                await self.resume(str(msg.get("session") or ""))
            elif op == "send":
                await self.send(str(msg.get("text") or ""))
            elif op == "stop":
                await self._control({"subtype": "interrupt"})
            elif op == "answer":
                await self.answer(str(msg.get("req") or ""), bool(msg.get("allow")), bool(msg.get("always")))
            elif op == "mode" and msg.get("mode") in MODES:
                self.mode = msg["mode"]
                await self._control({"subtype": "set_permission_mode", "mode": self.mode})
                await self._status()
            elif op == "model" and msg.get("model") in MODELS:
                self.model = msg["model"]
                await self._control({"subtype": "set_model", "model": self.model or None})
                await self._status()
            elif op == "end":
                await self.end()
                await self._status("idle")
        except Exception as e:
            log.warning("claude widget %s failed: %s", op, e)
            await self._ev("error", text=str(e)[:300])

    def _find_exe(self) -> str | None:
        if self._exe:
            return self._exe
        found = shutil.which("claude")
        if found:
            return found
        p = self.home / ".local" / "bin" / "claude"
        return str(p) if p.is_file() and os.access(p, os.X_OK) else None

    def _session_file(self, session: str) -> Path | None:
        if not session or "/" in session or ".." in session:
            return None
        try:
            return next(self.projects.glob(f"*/{session}.jsonl"), None)
        except OSError:
            return None

    async def resume(self, session: str) -> None:
        path = self._session_file(session)
        if path is None:
            raise ValueError("I can't find that session's transcript")
        await self.end()
        head = await asyncio.to_thread(cc.read_head, path)
        info = cc.head_info(head)
        tail = await asyncio.to_thread(cc.read_tail, path)
        self.session, self.cost = session, 0.0
        self.cwd = info.get("cwd") or self.cwd
        self.title = info.get("title") or ""
        await self._ev("clear")
        await self._ev("history", items=history_items(tail))
        await self._status("idle")

    # ------------------------------------------------------------- process
    async def _ensure(self) -> None:
        if self.proc and self.proc.returncode is None:
            return
        exe = self._find_exe()
        if not exe:
            raise RuntimeError("Claude Code isn't installed (no `claude` on the PATH)")
        argv = [exe, "-p", "--input-format", "stream-json", "--output-format", "stream-json",
                "--verbose", "--include-partial-messages", "--permission-prompt-tool", "stdio",
                "--permission-mode", self.mode]
        if self.model:
            argv += ["--model", self.model]
        if self.session:
            argv += ["--resume", self.session]
        # His login, not her API key: with ANTHROPIC_API_KEY set the CLI would bill that instead.
        env = {k: v for k, v in os.environ.items()
               if k not in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "ANTHROPIC_API_KEY")}
        self._stderr = []
        self.proc = await self._spawn(*argv, cwd=self.cwd, env=env, stdin=asyncio.subprocess.PIPE,
                                      stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                                      limit=LINE_LIMIT, start_new_session=True)
        self._reader = asyncio.create_task(self._read(self.proc))
        asyncio.create_task(self._read_err(self.proc))
        await self._write({"type": "control_request", "request_id": f"init-{uuid.uuid4().hex[:8]}",
                           "request": {"subtype": "initialize"}})

    async def _write(self, obj: dict) -> None:
        if not (self.proc and self.proc.returncode is None and self.proc.stdin):
            return
        self.proc.stdin.write((json.dumps(obj) + "\n").encode())
        await self.proc.stdin.drain()

    async def _control(self, request: dict) -> None:
        if self.proc and self.proc.returncode is None:
            await self._write({"type": "control_request", "request_id": f"r-{uuid.uuid4().hex[:8]}",
                               "request": request})

    async def send(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        async with self._lock:
            await self._ensure()
            if not self.title:
                self.title = cc.make_title(text)
            await self._ev("user", text=text)
            await self._write({"type": "user", "message": {"role": "user", "content": text}})
            await self._status("working")

    async def answer(self, req: str, allow: bool, always: bool) -> None:
        ask = self.asks.pop(req, None)
        if ask is None:
            return
        if allow:
            response = {"behavior": "allow", "updatedInput": ask.get("input") or {}}
            if always and ask.get("permission_suggestions"):
                response["updatedPermissions"] = ask["permission_suggestions"]
        else:
            response = {"behavior": "deny", "message": "He said no."}
        await self._write({"type": "control_response",
                           "response": {"subtype": "success", "request_id": req, "response": response}})
        await self._ev("asked", req=req)
        await self._status("asking" if self.asks else "working")

    async def end(self) -> None:
        proc, self.proc = self.proc, None
        self.asks.clear()
        if proc and proc.returncode is None:
            try:
                proc.stdin.close()
                await asyncio.wait_for(proc.wait(), 3)
            except (asyncio.TimeoutError, OSError, AttributeError):
                try:
                    os.killpg(proc.pid, 15)
                except (ProcessLookupError, PermissionError, AttributeError):
                    pass
        if self._reader:
            self._reader.cancel()
            self._reader = None

    # ---------------------------------------------------------------- read
    async def _read_err(self, proc) -> None:
        try:
            async for line in proc.stderr:
                self._stderr = (self._stderr + [line.decode(errors="replace").strip()])[-20:]
        except (ValueError, OSError):
            pass

    async def _read(self, proc) -> None:
        try:
            async for line in proc.stdout:
                try:
                    m = json.loads(line)
                except ValueError:
                    continue
                if isinstance(m, dict):
                    await self.handle(m)
        except (ValueError, OSError, asyncio.LimitOverrunError) as e:
            log.warning("claude widget stream broke: %s", e)
        finally:
            if proc is self.proc:
                await proc.wait()
                self.proc = None
                self.asks.clear()
                tail = " ".join(self._stderr[-3:])
                if proc.returncode not in (0, None) and tail:
                    await self._ev("error", text=tail[:300])
                await self._status("signed_out" if any(s in tail.lower() for s in SIGNED_OUT) else "idle")

    async def handle(self, m: dict) -> None:
        """One line from the CLI, turned into what the widget draws."""
        t = m.get("type")
        if t == "system" and m.get("subtype") == "init":
            self.session = m.get("session_id") or self.session
            await self._status()
        elif t == "stream_event":
            ev = m.get("event") or {}
            if ev.get("type") == "content_block_delta":
                d = ev.get("delta") or {}
                if d.get("type") == "text_delta" and d.get("text"):
                    await self._ev("delta", text=d["text"])
                elif d.get("type") == "thinking_delta":
                    await self._ev("thinking")
        elif t == "assistant":
            for b in (m.get("message") or {}).get("content") or []:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "text" and b.get("text"):
                    await self._ev("text", text=b["text"])
                elif b.get("type") == "tool_use":
                    await self._ev("tool", id=b.get("id", ""), name=b.get("name", ""),
                                   label=cc.tool_label(b.get("name"), b.get("input")),
                                   input=_preview(b.get("input")))
        elif t == "user":
            for b in (m.get("message") or {}).get("content") or []:
                if isinstance(b, dict) and b.get("type") == "tool_result":
                    await self._ev("tool_done", id=b.get("tool_use_id", ""), error=bool(b.get("is_error")),
                                   preview=_preview(_result_text(b.get("content"))))
        elif t == "control_request":
            req = m.get("request") or {}
            if req.get("subtype") == "can_use_tool":
                rid = m.get("request_id", "")
                self.asks[rid] = req
                await self._ev("ask", req=rid, tool=req.get("tool_name", ""),
                               label=cc.tool_label(req.get("tool_name"), req.get("input")),
                               input=_preview(req.get("input")),
                               always=bool(req.get("permission_suggestions")))
                await self._status("asking")
            else:                       # nothing else is ours to answer; say so rather than hang it
                await self._write({"type": "control_response", "response": {
                    "subtype": "error", "request_id": m.get("request_id", ""), "error": "not supported"}})
        elif t == "result":
            self.cost += float(m.get("total_cost_usd") or 0)
            text = str(m.get("result") or "")
            signed_out = m.get("is_error") and any(s in text.lower() for s in SIGNED_OUT)
            await self._ev("done", cost=round(self.cost, 4), error=text[:300] if m.get("is_error") else "")
            await self._status("signed_out" if signed_out else "idle")
