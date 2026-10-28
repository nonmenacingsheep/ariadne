"""The one schema core and desk share: JSON objects, one per line.

Both processes import this file, so a field is added in exactly one place.
"""
from __future__ import annotations

import json
import os
import pathlib

VERSION = 1
WIDGETS = ("chat", "core", "spotify", "steam", "browser",
           "dolphin", "claude", "system", "flows")
PHASES = ("started", "progress", "done", "failed")
ROLES = ("aries", "you")

# Required fields per message type (beyond "t"), checked on decode.
_REQUIRED = {
    "hello": ("v", "side", "pid"),
    "state": ("widget", "data"),
    "action": ("id", "widget", "verb", "phase"),
    "line": ("text", "speaking"),
    "chat": ("id", "role", "delta"),
    "press": ("widget", "control"),
    "text": ("widget", "text"),
    "voice": ("speaking", "level"),
    "ears": ("listening",),
}


class ProtocolError(ValueError):
    pass


def _widget(name: str) -> str:
    if name not in WIDGETS:
        raise ProtocolError(f"unknown widget: {name!r}")
    return name


def encode(msg: dict) -> bytes:
    return json.dumps(msg, separators=(",", ":"), ensure_ascii=False).encode("utf-8") + b"\n"


def decode(line: bytes | str) -> dict:
    if isinstance(line, bytes):
        try:
            line = line.decode("utf-8")
        except UnicodeDecodeError as e:
            raise ProtocolError(f"not utf-8: {e}") from e
    try:
        msg = json.loads(line)
    except json.JSONDecodeError as e:
        raise ProtocolError(f"bad json: {e}") from e
    if not isinstance(msg, dict):
        raise ProtocolError("message is not an object")
    t = msg.get("t")
    if t not in _REQUIRED:
        raise ProtocolError(f"missing or unknown t: {t!r}")
    for field in _REQUIRED[t]:
        if field not in msg:
            raise ProtocolError(f"{t}: missing field {field!r}")
    if "widget" in msg:
        _widget(msg["widget"])
    if t == "action" and msg["phase"] not in PHASES:
        raise ProtocolError(f"action: bad phase {msg['phase']!r}")
    if t == "chat" and msg["role"] not in ROLES:
        raise ProtocolError(f"chat: bad role {msg['role']!r}")
    if t == "state" and not isinstance(msg["data"], dict):
        raise ProtocolError("state: data is not an object")
    if t == "hello" and msg["side"] not in ("core", "desk"):
        raise ProtocolError(f"hello: bad side {msg['side']!r}")
    return msg


def socket_path() -> pathlib.Path:
    override = os.environ.get("ARIADNE2_SOCKET")
    if override:
        return pathlib.Path(override)
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if runtime:
        return pathlib.Path(runtime) / "ariadne2" / "core.sock"
    return pathlib.Path(f"/tmp/ariadne2-{os.getuid()}") / "core.sock"


# ---- core -> desk ----

def hello_core() -> dict:
    return {"t": "hello", "v": VERSION, "side": "core", "pid": os.getpid()}


def state(widget: str, data: dict) -> dict:
    return {"t": "state", "widget": _widget(widget), "data": data}


def action(id: str, widget: str, verb: str, phase: str,
           control: str | None = None, note: str | None = None) -> dict:
    if phase not in PHASES:
        raise ProtocolError(f"bad phase {phase!r}")
    msg = {"t": "action", "id": id, "widget": _widget(widget), "verb": verb, "phase": phase}
    if control is not None:
        msg["control"] = control
    if note is not None:
        msg["note"] = note
    return msg


def core_line(text: str, speaking: bool = False) -> dict:
    return {"t": "line", "text": text, "speaking": speaking}


def chat(id: str, role: str, delta: str, done: bool = False) -> dict:
    if role not in ROLES:
        raise ProtocolError(f"bad role {role!r}")
    return {"t": "chat", "id": id, "role": role, "delta": delta, "done": done}


# ---- desk -> core ----

def hello_desk() -> dict:
    return {"t": "hello", "v": VERSION, "side": "desk", "pid": os.getpid()}


def press(widget: str, control: str, value=None) -> dict:
    """A click in a widget. `value` rides along for sliders (volume 0-100,
    scrub position in seconds); plain buttons leave it out."""
    msg = {"t": "press", "widget": _widget(widget), "control": control}
    if value is not None:
        msg["value"] = value
    return msg


def text(widget: str, text: str) -> dict:
    return {"t": "text", "widget": _widget(widget), "text": text}


def voice(speaking: bool, level: float = 0.0) -> dict:
    """Her voice: whether she's audible, and its loudness 0-1 (drives the waveform)."""
    return {"t": "voice", "speaking": bool(speaking), "level": round(float(level), 3)}


def ears(listening: bool) -> dict:
    """The mic opened (she's listening for a command) or closed."""
    return {"t": "ears", "listening": bool(listening)}
