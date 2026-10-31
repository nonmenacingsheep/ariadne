"""The one schema core and desk share: JSON objects, one per line.

Both processes import this file, so a field is added in exactly one place.
"""
from __future__ import annotations

import json
import os
import pathlib

VERSION = 1
WIDGETS = ("chat", "core", "spotify", "steam", "browser",
           "dolphin", "claude", "system", "flows", "tasks", "avatar")
PHASES = ("started", "progress", "done", "failed")
ROLES = ("aries", "you")
FLOW_PHASES = ("fired", "node", "done", "failed")
FLOW_CONTROLS = ("toggle", "run", "approve", "delete")      # presses on the flows widget; value = flow id
SETTING_TYPES = ("bool", "choice", "number", "text", "key", "secret")
SETTING_ENTRY = ("section", "key", "label", "type", "default", "help")     # every schema entry has these
FLOW_ROW = ("id", "name", "summary", "enabled", "approved", "made_by", "uses_ai", "manual",
            "last_fired", "last_result", "note")

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
    "speak": ("text", "seconds"),
    "flow": ("flow", "run", "phase"),
    "flow_catalog": (),
    "catalog": ("nodes",),
    "flow_open": ("id",),
    "flow_graph": ("id", "graph", "summary", "errors"),
    "flow_save": ("graph",),
    "flow_saved": ("id", "ok"),
    "flow_test": (),
    "flow_tested": ("id", "ok", "note"),
    "ask": ("id", "question", "options"),
    "answer": ("id", "choice"),
    "menu": ("widget", "path"),
    "attach": ("path",),
    "attached": ("path", "name", "kind"),
    "settings": ("schema", "values"),
    "set": ("section", "key", "value"),
    "cc": ("ev",),              # the Claude widget's live Claude Code session (core/claude_live.py)
    "cc_do": ("op",),
    "update": ("status",),       # core/updater.py: what the update check found
    "update_do": ("op",),
}
MAX_ATTACHMENTS = 8


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
    if msg.get("widget") is not None:
        _widget(msg["widget"])
    if t == "action" and msg["phase"] not in PHASES:
        raise ProtocolError(f"action: bad phase {msg['phase']!r}")
    if t == "chat" and msg["role"] not in ROLES:
        raise ProtocolError(f"chat: bad role {msg['role']!r}")
    if t == "state" and not isinstance(msg["data"], dict):
        raise ProtocolError("state: data is not an object")
    if t == "state" and msg["widget"] == "flows" and "flows" in msg["data"]:
        _check_flow_rows(msg["data"]["flows"])
    if t == "flow":
        if msg["phase"] not in FLOW_PHASES:
            raise ProtocolError(f"flow: bad phase {msg['phase']!r}")
        if not isinstance(msg["flow"], str) or not isinstance(msg["run"], str):
            raise ProtocolError("flow: flow and run must be strings")
    if t == "ask" and not (isinstance(msg["options"], list) and msg["options"]
                           and all(isinstance(o, str) for o in msg["options"])):
        raise ProtocolError("ask: options must be a non-empty list of strings")
    if t == "answer" and not isinstance(msg["choice"], str):
        raise ProtocolError("answer: choice must be a string")
    if t == "settings":
        _check_settings(msg["schema"], msg["values"])
    if t == "set" and not (isinstance(msg["section"], str) and isinstance(msg["key"], str)):
        raise ProtocolError("set: section and key must be strings")
    if t == "text" and "attachments" in msg:
        a = msg["attachments"]
        if not (isinstance(a, list) and len(a) <= MAX_ATTACHMENTS and all(isinstance(x, str) and x for x in a)):
            raise ProtocolError(f"text: attachments must be a list of up to {MAX_ATTACHMENTS} paths")
    if t in ("attach", "attached", "menu") and not (isinstance(msg["path"], str) and msg["path"]):
        raise ProtocolError(f"{t}: path must be a non-empty string")
    if t == "attached" and not (isinstance(msg["name"], str) and isinstance(msg["kind"], str)):
        raise ProtocolError("attached: name and kind must be strings")
    if t == "menu":
        _check_menu(msg)
    if t == "press" and msg["widget"] == "flows" and msg["control"] not in FLOW_CONTROLS:
        raise ProtocolError(f"press: bad flows control {msg['control']!r}")
    if t in _EDITOR_CHECKS:
        _EDITOR_CHECKS[t](msg)
    if t == "hello" and msg["side"] not in ("core", "desk"):
        raise ProtocolError(f"hello: bad side {msg['side']!r}")
    return msg


def _check_flow_errors(errors, what: str) -> None:
    """Editor problems: [{node, pin, message}]; node and pin may be null."""
    if not isinstance(errors, list):
        raise ProtocolError(f"{what}: errors is not a list")
    for e in errors:
        if not (isinstance(e, dict) and isinstance(e.get("message"), str) and "node" in e and "pin" in e):
            raise ProtocolError(f"{what}: an error needs node, pin and message")


def _id_or_null(msg: dict, what: str) -> None:
    if msg["id"] is not None and not isinstance(msg["id"], str):
        raise ProtocolError(f"{what}: id must be a string or null")


def _check_catalog(msg: dict) -> None:
    n = msg["nodes"]
    if not (isinstance(n, list) and all(isinstance(x, dict) and isinstance(x.get("type"), str) for x in n)):
        raise ProtocolError("catalog: nodes must be a list of entries with a type")


def _check_flow_graph(msg: dict) -> None:
    _id_or_null(msg, "flow_graph")
    if msg["graph"] is not None and not isinstance(msg["graph"], dict):
        raise ProtocolError("flow_graph: graph is not an object")
    _check_flow_errors(msg["errors"], "flow_graph")


def _check_flow_saved(msg: dict) -> None:
    _id_or_null(msg, "flow_saved")
    if not isinstance(msg["ok"], bool):
        raise ProtocolError("flow_saved: ok must be true or false")
    for key in ("errors", "warnings"):
        if key in msg:
            _check_flow_errors(msg[key], "flow_saved")


def _check_flow_test(msg: dict) -> None:
    if not isinstance(msg.get("id"), str) and not isinstance(msg.get("graph"), dict):
        raise ProtocolError("flow_test: carry an id or a graph")


def _check_flow_tested(msg: dict) -> None:
    _id_or_null(msg, "flow_tested")
    if not isinstance(msg["ok"], bool):
        raise ProtocolError("flow_tested: ok must be true or false")
    if "errors" in msg:
        _check_flow_errors(msg["errors"], "flow_tested")


def _check_flow_save(msg: dict) -> None:
    if not isinstance(msg["graph"], dict):
        raise ProtocolError("flow_save: graph is not an object")


_EDITOR_CHECKS = {
    "catalog": _check_catalog,
    "flow_open": lambda m: _id_or_null(m, "flow_open"),
    "flow_graph": _check_flow_graph,
    "flow_save": _check_flow_save,
    "flow_saved": _check_flow_saved,
    "flow_test": _check_flow_test,
    "flow_tested": _check_flow_tested,
}


def _check_menu(msg: dict) -> None:
    apps, info = msg.get("apps"), msg.get("info")
    if (apps is None) == (info is None):
        raise ProtocolError("menu: carry either apps or info")
    if apps is not None:
        if not (isinstance(apps, list) and all(isinstance(a, dict) and all(k in a for k in ("id", "name", "icon"))
                                               for a in apps)):
            raise ProtocolError("menu: apps must be a list of {id, name, icon}")
    elif not isinstance(info, dict):
        raise ProtocolError("menu: info is not an object")


def _check_flow_rows(rows) -> None:
    if not isinstance(rows, list):
        raise ProtocolError("state: flows is not a list")
    for row in rows:
        if not isinstance(row, dict):
            raise ProtocolError("state: a flows row is not an object")
        for key in FLOW_ROW:
            if key not in row:
                raise ProtocolError(f"state: flows row missing {key!r}")


def _check_settings(schema, values) -> None:
    if not isinstance(schema, list):
        raise ProtocolError("settings: schema is not a list")
    for entry in schema:
        if not isinstance(entry, dict):
            raise ProtocolError("settings: a schema entry is not an object")
        for field in SETTING_ENTRY:
            if field not in entry:
                raise ProtocolError(f"settings: schema entry missing {field!r}")
        if entry["type"] not in SETTING_TYPES:
            raise ProtocolError(f"settings: bad type {entry['type']!r}")
    if not isinstance(values, dict) or not all(isinstance(v, dict) for v in values.values()):
        raise ProtocolError("settings: values is not {section: {key: value}}")


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


def flow(flow: str, run: str, phase: str, node: str | None = None, widget: str | None = None,
         note: str | None = None) -> dict:
    """A flow run moving: `fired` (with the widget where the trigger happened, or null), `node` (entering
    one), `done` or `failed` (with a note). Drives the wires and the editor's live view."""
    if phase not in FLOW_PHASES:
        raise ProtocolError(f"bad flow phase {phase!r}")
    if widget is not None:
        _widget(widget)
    return {"t": "flow", "flow": flow, "run": run, "phase": phase, "node": node, "widget": widget, "note": note}


def flows_state(rows: list[dict]) -> dict:
    """The flows widget's snapshot: one row per flow (keys in FLOW_ROW)."""
    _check_flow_rows(rows)
    return state("flows", {"flows": rows})


def flow_error(message: str, node: str | None = None, pin: str | None = None) -> dict:
    """One editor problem: where (node id, pin name; either may be null) and what."""
    return {"node": node, "pin": pin, "message": message}


def catalog(nodes: list[dict]) -> dict:
    """Every node type the editor can offer (core/flows/catalog.py entries: type, title, category,
    description, inputs, outputs, exec_in, exec_out, consent, outside_content, costly, available)."""
    return {"t": "catalog", "nodes": nodes}


def flow_graph(id: str | None, graph: dict | None, summary: str, errors: list[dict] | None = None,
               by: str | None = None) -> dict:
    """A whole flow file for the editor: the answer to `flow_open`, or (with `by`) a broadcast that
    someone else just saved or changed it. `id` null = a fresh unsaved graph; `graph` null = no such flow."""
    msg = {"t": "flow_graph", "id": id, "graph": graph, "summary": summary, "errors": list(errors or [])}
    if by is not None:
        msg["by"] = by
    return msg


def flow_saved(id: str | None, ok: bool, summary: str | None = None, errors: list[dict] | None = None,
               warnings: list[dict] | None = None) -> dict:
    """The answer to `flow_save`: saved (with the one-line summary) or refused (errors = [{node, pin, message}])."""
    msg = {"t": "flow_saved", "id": id, "ok": bool(ok)}
    if ok:
        msg["summary"] = summary or ""
    else:
        msg["errors"] = list(errors or [])
    if warnings:
        msg["warnings"] = list(warnings)
    return msg


def flow_tested(id: str | None, ok: bool, note: str, errors: list[dict] | None = None) -> dict:
    """A dry run is over (its `flow` events were published as it went). `errors` only when the graph
    couldn't be tested because it doesn't validate."""
    msg = {"t": "flow_tested", "id": id, "ok": bool(ok), "note": note}
    if errors:
        msg["errors"] = list(errors)
    return msg


def menu(widget: str, path: str, apps: list[dict] | None = None, info: dict | None = None) -> dict:
    """A one-off answer to a context-menu question about a path: the apps that can open it
    (`apps`: [{id, name, icon}]) or its Properties (`info`). Not a snapshot; nothing replays it."""
    msg = {"t": "menu", "widget": _widget(widget), "path": path}
    if apps is not None:
        msg["apps"] = apps
    if info is not None:
        msg["info"] = info
    _check_menu(msg)
    return msg


def attached(path: str, name: str, kind: str, error: str | None = None) -> dict:
    """The core's answer to `attach`: a chip for the chat input. `error` (and an empty kind) when the
    file can't be sent."""
    msg = {"t": "attached", "path": path, "name": name, "kind": kind}
    if error:
        msg["error"] = error
    return msg


def ask(id: str, question: str, options: list[str]) -> dict:
    """An Ask Ronald question for the chat, one button per option."""
    if not options or not all(isinstance(o, str) for o in options):
        raise ProtocolError("ask needs a list of option strings")
    return {"t": "ask", "id": id, "question": question, "options": list(options)}


def settings(schema: list[dict], values: dict) -> dict:
    """Every setting: its schema (core/settings.py) and the current `{section: {key: value}}`.
    Sent on hello and after any change."""
    _check_settings(schema, values)
    return {"t": "settings", "schema": schema, "values": values}


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


def answer(id: str, choice: str) -> dict:
    """The option he picked for an `ask`."""
    return {"t": "answer", "id": id, "choice": choice}


def text(widget: str, text: str, attachments: list[str] | None = None) -> dict:
    """Something he typed. `attachments`: paths of files he attached (the chips he accepted)."""
    msg = {"t": "text", "widget": _widget(widget), "text": text}
    if attachments:
        msg["attachments"] = list(attachments)
    return msg


def attach(path: str) -> dict:
    """He picked "Paste into chat" on a file; the core answers with `attached`."""
    return {"t": "attach", "path": path}


def flow_catalog() -> dict:
    """Ask for the node catalog; the core answers with `catalog`."""
    return {"t": "flow_catalog"}


def flow_open(id: str | None) -> dict:
    """Open a flow in the editor (`flow_graph` comes back); id null = a fresh empty graph."""
    return {"t": "flow_open", "id": id}


def flow_save(graph: dict) -> dict:
    """Save his edit of a flow (the whole file, node `pos` included); `flow_saved` comes back."""
    return {"t": "flow_save", "graph": graph}


def flow_test(id: str | None = None, graph: dict | None = None, start: str | None = None) -> dict:
    """Dry-run a saved flow (id) or the graph as edited (graph, saved or not); `start` picks the start node."""
    if id is None and graph is None:
        raise ProtocolError("flow_test needs an id or a graph")
    msg = {"t": "flow_test"}
    if id is not None:
        msg["id"] = id
    if graph is not None:
        msg["graph"] = graph
    if start is not None:
        msg["start"] = start
    return msg


def voice(speaking: bool, level: float = 0.0) -> dict:
    """Her voice: whether she's audible, and its loudness 0-1 (drives the waveform)."""
    return {"t": "voice", "speaking": bool(speaking), "level": round(float(level), 3)}


def ears(listening: bool) -> dict:
    """The mic opened (she's listening for a command) or closed."""
    return {"t": "ears", "listening": bool(listening)}


def speak(text: str, seconds: float, emotion: str = "") -> dict:
    """A sentence she's starting to say, how long it lasts, and its emotion
    mark if any: her body shapes its mouth to the vowels (pet/)."""
    return {"t": "speak", "text": text, "seconds": round(float(seconds), 2), "emotion": emotion or ""}


def set_setting(section: str, key: str, value) -> dict:
    """He changed one setting; the core validates, applies, saves and answers with a `settings`."""
    return {"t": "set", "section": str(section), "key": str(key), "value": value}
