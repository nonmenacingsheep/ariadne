"""The node catalog (DESIGN §10): ~45 built-in types, plus the nodes every
loaded adapter adds for free (a start per declared event, an action per verb,
one `Read state`).

Each entry is a NodeType; `to_dict()` is the shape the editor and the model
get. Entries also carry what only the core needs: `kind` (which code runs the
node), `phrase` (the template for the one-line summary) and `meta`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# Which pins an input may be wired to besides the listed ones.
OPS_COMPARE = ["=", "≠", "<", ">", "contains", "matches"]
OPS_BECOMES = ["is", "is not", "above", "below", "contains"]
OPS_MATH = ["+", "-", "*", "/", "mod", "min", "max", "round"]
OPS_LIST = ["first", "last", "count", "join", "pick", "contains", "filter"]
SEQUENCE_PINS = ["then_1", "then_2", "then_3", "then_4"]


def pin(name: str, typ: str = "text", required: bool = False, default=None, choices=None) -> dict:
    d = {"name": name, "type": typ, "required": required, "default": default}
    if choices:
        d["choices"] = list(choices)
    return d


@dataclass
class NodeType:
    type: str
    title: str
    category: str                                  # start | check | action | flow | data
    description: str
    kind: str                                      # which implementation runs it
    inputs: list = field(default_factory=list)
    outputs: list = field(default_factory=list)
    exec_in: bool = False
    exec_out: list = field(default_factory=list)
    consent: str | None = None
    outside_content: bool = False
    costly: bool = False
    available: bool = True
    note: str = ""                                 # why it's unavailable
    phrase: str = ""                               # summary template: {input} slots
    dynamic_inputs: bool = False                   # extra data inputs allowed (templates, quoted values)
    exec_out_from: tuple | None = None             # (input name, default list, extra pins): pins named by a value
    meta: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = {"type": self.type, "title": self.title, "category": self.category,
             "description": self.description, "inputs": self.inputs, "outputs": self.outputs,
             "exec_in": self.exec_in, "exec_out": self.exec_out_names(None),
             "consent": self.consent, "outside_content": self.outside_content,
             "costly": self.costly, "available": self.available}
        if self.note:
            d["note"] = self.note
        if self.dynamic_inputs:
            d["dynamic_inputs"] = True
        if self.exec_out_from:
            d["exec_out_from"] = self.exec_out_from[0]
        return d

    def exec_out_names(self, values: dict | None) -> list[str]:
        """The exec outputs, with the ones a node names itself (Ask Ronald's answers)."""
        if not self.exec_out_from:
            return list(self.exec_out)
        key, default, extra = self.exec_out_from
        chosen = (values or {}).get(key)
        names = [str(x) for x in chosen] if isinstance(chosen, list) and chosen else list(default)
        return names + [x for x in extra if x not in names]

    def input(self, name: str) -> dict | None:
        return next((i for i in self.inputs if i["name"] == name), None)


def _t(type_, title, cat, desc, kind, ins=(), outs=(), exec_in=False, exec_out=(), phrase="", **kw):
    return NodeType(type_, title, cat, desc, kind, list(ins), [{"name": n, "type": t} for n, t in outs],
                    exec_in, list(exec_out), phrase=phrase, **kw)


def _builtins() -> list[NodeType]:
    S, A, D = ("exec",), ("done", "failed"), ("done", "failed")
    gone = "needs a desktop source that isn't built yet"
    return [
        # ---- starts ----
        _t("time.at", "At", "start", "Fires at a time of day, on chosen days (none chosen = every day).",
           "at", [pin("time", "time", True), pin("days", "list", False, [])], [("time", "time")], False, S,
           "At {time}{days}"),
        _t("time.every", "Every", "start", "Fires again and again, once per interval.",
           "every", [pin("interval", "duration", True)], [("count", "number")], False, S, "Every {interval}"),
        _t("time.after", "After", "start", "Fires once, a delay after the flow is turned on.",
           "after", [pin("delay", "duration", True)], [], False, S, "{delay} after it's turned on"),
        _t("time.becomes", "Becomes", "start",
           "Fires when an app's state crosses a line, e.g. field spotify.status is playing, or "
           "steam.downloads contains x. 'hold' = it must stay true that long, so it doesn't flap.",
           "becomes", [pin("field", "text", True), pin("op", "text", False, "is", OPS_BECOMES),
                       pin("value", "any", True), pin("hold", "duration", False, 0)],
           [("value", "any")], False, S, "When {field} {op} {value}"),
        _t("ariadne.started", "Ariadne started", "start", "Fires when Ariadne starts up.",
           "started", [], [], False, S, "When Ariadne starts"),
        _t("desktop.window_opened", "Window opened", "start", "A window whose title matches opens.",
           "planned", [pin("match", "text", True)], [("title", "text")], False, S,
           "When a window matching {match} opens", available=False, note=gone),
        _t("desktop.window_closed", "Window closed", "start", "A window whose title matches closes.",
           "planned", [pin("match", "text", True)], [("title", "text")], False, S,
           "When a window matching {match} closes", available=False, note=gone),
        _t("desktop.window_focused", "Window focused", "start", "A window whose title matches gets focus.",
           "planned", [pin("match", "text", True)], [("title", "text")], False, S,
           "When a window matching {match} gets focus", available=False, note=gone),
        _t("desktop.idle", "Idle for", "start", "No keyboard or mouse for this long.",
           "planned", [pin("after", "duration", True)], [], False, S, "When idle for {after}",
           available=False, note=gone),
        _t("desktop.back_from_idle", "Back from idle", "start", "First input after being idle.",
           "planned", [], [], False, S, "When you're back from idle", available=False, note=gone),
        _t("you.say", "You say", "start", "Fires when you say or type a phrase to her.",
           "you_say", [pin("phrase", "text", True)], [("text", "text")], False, S, 'When you say "{phrase}"'),
        _t("you.run_button", "Run button", "start",
           "Fires from the Run button in the Flows widget, or when you say 'run <flow name>'.",
           "run_button", [], [], False, S, "When you press Run"),
        # ---- checks ----
        _t("check.branch", "Branch", "check", "Goes on by the true or the false exec out.", "branch",
           [pin("cond", "yes/no", True)], [], True, ("true", "false"), "if {cond}"),
        _t("check.compare", "Compare", "check", "Compares two values; gives yes/no.", "compare",
           [pin("a", "any", True), pin("op", "text", False, "=", OPS_COMPARE), pin("b", "any", True)],
           [("result", "yes/no")], False, (), "{a} {op} {b}"),
        _t("check.and", "And", "check", "Yes when both are yes.", "and",
           [pin("a", "yes/no", True), pin("b", "yes/no", True)], [("result", "yes/no")], False, (), "{a} and {b}"),
        _t("check.or", "Or", "check", "Yes when either is yes.", "or",
           [pin("a", "yes/no", True), pin("b", "yes/no", True)], [("result", "yes/no")], False, (), "{a} or {b}"),
        _t("check.not", "Not", "check", "Flips yes and no.", "not",
           [pin("value", "yes/no", True)], [("result", "yes/no")], False, (), "not {value}"),
        _t("check.time_between", "Time between", "check",
           "True when the clock is in the window (it may run past midnight: 22:00 to 07:00).", "time_between",
           [pin("from", "time", True), pin("to", "time", True)], [("result", "yes/no")], True,
           ("true", "false"), "if {from}–{to}"),
        _t("check.day_is", "Day is", "check", "True on the chosen days.", "day_is",
           [pin("days", "list", True)], [("result", "yes/no")], True, ("true", "false"), "if it's {days}"),
        _t("check.cooldown", "Cooldown", "check", "Passes at most once per duration; otherwise the run ends.",
           "cooldown", [pin("every", "duration", True)], [], True, S, "at most once per {every}"),
        _t("check.once_per_day", "Once per day", "check", "Passes the first time each day.", "once_per_day",
           [], [], True, S, "once a day"),
        _t("check.settle", "Settle", "check",
           "Waits until the start has stopped firing for a while, then passes once (bursts of files, downloads).",
           "settle", [pin("quiet", "duration", True)], [], True, S, "once quiet for {quiet}"),
        _t("check.count", "Count", "check", "Passes when the start has fired n times within a duration.",
           "count", [pin("n", "number", True), pin("within", "duration", True)], [], True, S,
           "after {n} times within {within}"),
        # ---- actions ----
        _t("file.move", "Move file", "action", "Moves a file or folder; refuses to overwrite.", "file_move",
           [pin("src", "path", True), pin("dst", "path", True)], [], True, A, "Move {src} to {dst}"),
        _t("file.copy", "Copy file", "action", "Copies a file or folder; refuses to overwrite.", "file_copy",
           [pin("src", "path", True), pin("dst", "path", True)], [], True, A, "Copy {src} to {dst}"),
        _t("shell.run", "Run command", "action", "Runs a shell command (same hard refusals as her shell).",
           "planned", [pin("command", "text", True)], [("output", "text")], True, A, "Run {command}",
           available=False, note="her shell tool isn't built in 2.0 yet"),
        _t("window.place", "Place window", "action", "Moves and sizes a window.", "planned",
           [pin("match", "text", True), pin("where", "text", True)], [], True, A, "Place {match} {where}",
           available=False, note=gone),
        _t("desktop.notify", "Notify", "action", "A desktop toast.", "notify",
           [pin("text", "text", True), pin("title", "text", False, "Ariadne")], [], True, A, "Notify {text}"),
        _t("her.say", "Say", "action", "She speaks a line aloud (a chat line when there's no voice).", "say",
           [pin("text", "text", True)], [], True, A, "Say {text}"),
        _t("her.tell", "Tell", "action", "A line in chat, from her.", "tell",
           [pin("text", "text", True)], [], True, A, "Tell me {text}"),
        _t("her.ask_aries", "Ask Aries", "action",
           "Hands her a sentence plus any wired-in values (quoted, as data) as one turn; her reply comes out as "
           "text. Costs a model call. Name extra inputs anything (they are the labels she sees).",
           "ask_aries", [pin("sentence", "text", True)], [("reply", "text")], True, A,
           "Ask Aries: {sentence}", costly=True, dynamic_inputs=True),
        _t("her.decide", "Decide", "action",
           "Like Ask Aries, but she picks one of the named choices; each choice is its own exec out.",
           "decide", [pin("sentence", "text", True), pin("choices", "list", False, ["yes", "no"])],
           [("choice", "text")], True, (), "Decide: {sentence}", costly=True, dynamic_inputs=True,
           exec_out_from=("choices", ["yes", "no"], ("failed",))),
        _t("you.ask_ronald", "Ask Ronald", "action",
           "A question in chat with one button per option; each option is its own exec out, plus timeout. "
           "Pauses the run until he answers.", "ask_ronald",
           [pin("question", "text", True), pin("options", "list", False, ["yes", "no"]),
            pin("timeout", "duration", False, 3600)], [("choice", "text")], True, (),
           "Ask Ronald {question}", exec_out_from=("options", ["yes", "no"], ("timeout",))),
        # ---- flow control ----
        _t("flow.sequence", "Sequence", "flow", "Runs its outputs in order.", "sequence",
           [], [], True, SEQUENCE_PINS, "then"),
        _t("flow.wait", "Wait", "flow", "Pauses for a duration.", "wait",
           [pin("duration", "duration", True)], [], True, S, "wait {duration}"),
        _t("flow.wait_for", "Wait for", "flow",
           "Pauses until an event (like steam.game_closed), or the timeout out after the timeout.", "wait_for",
           [pin("event", "text", True), pin("timeout", "duration", False, 3600)], [("event", "text")], True,
           ("exec", "timeout"), "wait for {event}"),
        _t("flow.for_each", "For each", "flow", "Runs its body once per item of a list.", "for_each",
           [pin("items", "list", True)], [("item", "any"), ("index", "number")], True, ("body", "done"),
           "for each of {items}"),
        _t("flow.run_flow", "Run flow", "flow", "Calls another flow (by id or name) and waits for it.",
           "run_flow", [pin("flow", "text", True)], [], True, A, "run flow {flow}"),
        _t("flow.stop", "Stop", "flow", "Ends this run.", "stop", [], [], True, (), "stop"),
        # ---- data ----
        _t("data.get", "Get", "data", "A variable the flow keeps between runs.", "get",
           [pin("name", "text", True), pin("default", "any", False, "")], [("value", "any")], False, (),
           "‹{name}›"),
        _t("data.set", "Set", "data", "Keeps a value in a variable of the flow.", "set",
           [pin("name", "text", True), pin("value", "any", True)], [], True, S, "set {name} to {value}"),
        _t("data.text", "Text", "data",
           "A template: 'now playing {title} by {artist}'. Each {name} takes the wired or typed input of that name.",
           "text", [pin("template", "text", True)], [("text", "text")], False, (), "“{template}”",
           dynamic_inputs=True),
        _t("data.math", "Math", "data", "Arithmetic on two numbers.", "math",
           [pin("a", "number", True), pin("op", "text", False, "+", OPS_MATH), pin("b", "number", False, 0)],
           [("result", "number")], False, (), "{a} {op} {b}"),
        _t("data.list", "List", "data", "Picks, counts, joins or filters a list.", "list",
           [pin("list", "list", True), pin("op", "text", False, "first", OPS_LIST), pin("arg", "any", False, "")],
           [("result", "any"), ("count", "number")], False, (), "{op} of {list}"),
    ]


# Starts the design names but no source exists for yet. A real adapter that
# declares the same event name replaces the placeholder.
PLANNED_STARTS = [
    ("dolphin.file_appeared", "Dolphin: file appeared", [pin("path", "path", True)], [("name", "text")],
     "When a file appears in {path}", "Dolphin isn't an adapter yet"),
    ("system.disk_low", "System: disk low", [pin("below_gb", "number", True)], [],
     "When free space drops under {below_gb} GB", "no system source for disk space yet"),
    ("screen.sees", "Screen: sees", [pin("thing", "text", True)], [],
     "When {thing} shows on screen", "no screen-watching source yet"),
    ("system.package_update", "System: package update", [pin("package", "text", True)], [("status", "text")],
     "When package {package} has news", "no package source yet"),
]

_JSON_TYPES = {"string": "text", "integer": "number", "number": "number", "boolean": "yes/no", "array": "list"}


def _infer(value) -> str:
    if isinstance(value, bool):
        return "yes/no"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, list):
        return "list"
    return "text"


def state_fields_of(adapter) -> dict:
    """name -> (type, dotted path): declared by the adapter, else its scalar state keys."""
    declared = getattr(adapter, "state_fields", None)
    if declared:
        return {k: tuple(v) for k, v in declared.items()}
    out = {}
    try:
        state = adapter.state() or {}
    except Exception:
        state = {}
    for k, v in state.items():
        if isinstance(v, (str, int, float, bool, list)) or v is None:
            out[k] = (_infer(v), k)
    return out


def read_path(state, path: str):
    """A dotted path into a state dict; None when any step is missing."""
    cur = state
    for part in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


class Catalog:
    def __init__(self) -> None:
        self.types: dict[str, NodeType] = {}
        self.reads: dict[str, tuple[str, str]] = {}          # "spotify.title" -> (type, path)
        self.adapter_names: dict[str, str] = {}              # adapter -> display name

    def add(self, nt: NodeType) -> None:
        self.types[nt.type] = nt

    def get(self, type_: str) -> NodeType | None:
        return self.types.get(type_)

    def __contains__(self, type_: str) -> bool:
        return type_ in self.types

    def __len__(self) -> int:
        return len(self.types)

    @classmethod
    def build(cls, adapters: dict | None = None) -> "Catalog":
        cat = cls()
        for nt in _builtins():
            cat.add(nt)
        adapters = adapters or {}
        for name, adapter in adapters.items():
            cat._add_adapter(name, adapter)
        for type_, title, ins, outs, phrase, note in PLANNED_STARTS:
            if type_ not in cat.types:
                cat.add(_t(type_, title, "start", note and f"Planned: {note}.", "planned", ins, outs, False,
                           ("exec",), phrase, available=False, note=note))
        return cat

    def _add_adapter(self, name: str, adapter) -> None:
        shown = name.capitalize()
        self.adapter_names[name] = shown
        info = getattr(adapter, "event_info", None) or {}
        for ev in getattr(adapter, "events", ()):
            i = info.get(ev, {})
            fields = i.get("fields") or {}
            words = i.get("phrase") or ev.replace("_", " ")
            self.add(_t(f"{name}.{ev}", f"{shown}: {ev.replace('_', ' ')}", "start",
                        f"Fires when {shown} reports: {ev.replace('_', ' ')}.", "event", [],
                        list(fields.items()), False, ("exec",), f"When {shown} {words}",
                        outside_content=bool(i.get("outside")),
                        meta={"adapter": name, "event": f"{name}.{ev}"}))
        for v in getattr(adapter, "verbs", []):
            schema = v.schema()
            props = schema.get("properties") or {}
            required = set(schema.get("required") or [])
            ins, jt = [], {}
            for pname, spec in props.items():
                spec = spec if isinstance(spec, dict) else {}
                jt[pname] = spec.get("type", "string")
                ins.append(pin(pname, _JSON_TYPES.get(spec.get("type"), "text"), pname in required,
                               spec.get("default"), spec.get("enum")))
            type_ = f"{name}.{v.name}"
            if type_ in self.types:                       # an event of the same name: the verb gets "do_"
                type_ = f"{name}.do_{v.name}"
            self.add(_t(type_, f"{shown}: {v.name.replace('_', ' ')}", "action", v.description, "verb",
                        ins, [("result", "text")], True, ("done", "failed"),
                        f"{shown} {v.name.replace('_', ' ')}", consent=v.consent,
                        outside_content=bool(getattr(v, "outside_content", False)),
                        meta={"adapter": name, "verb": v.name, "json": jt,
                              "tool": f"{name}_{v.name}"}))
        fields = state_fields_of(adapter)
        for fname, (ftype, path) in fields.items():
            self.reads[f"{name}.{fname}"] = (ftype, path)
        if fields:
            self.add(_t(f"{name}.read_state", f"{shown}: read state", "data",
                        f"A value from {shown}'s state: " + ", ".join(fields) + ".", "read_state",
                        [pin("field", "text", True, None, list(fields))], [("value", "any")], False, (),
                        f"{shown} {{field}}", meta={"adapter": name}))

    # ---- looking things up ----

    def search(self, query: str, limit: int = 8) -> list[NodeType]:
        tokens = re.findall(r"[a-z0-9]+", (query or "").lower())
        scored = []
        for nt in self.types.values():
            words = re.findall(r"[a-z0-9]+", f"{nt.type} {nt.title}".lower())
            desc = nt.description.lower()
            score = 0
            for t in tokens:
                if any(w == t for w in words):
                    score += 4
                elif any(w.startswith(t) for w in words):
                    score += 3
                elif t in desc or t in nt.category:
                    score += 1
                else:
                    score = -1
                    break
            if score > 0 or not tokens:
                scored.append((-score, nt.title, nt))
        scored.sort(key=lambda x: x[:2])
        return [nt for _, _, nt in scored[:limit]]

    def suggest(self, wrong: str, n: int = 3) -> list[str]:
        import difflib
        return difflib.get_close_matches(wrong, list(self.types), n=n, cutoff=0.5)


def compact(nt: NodeType) -> dict:
    """The short entry she gets from flow_nodes: enough to wire it, nothing more."""
    d = {"type": nt.type, "title": nt.title, "does": nt.description}
    if nt.inputs:
        d["in"] = [f"{i['name']}:{i['type']}{'*' if i['required'] else ''}"
                   + (f"={i['default']!r}" if i["default"] not in (None, "") and not i["required"] else "")
                   + (f"[{'|'.join(map(str, i['choices']))}]" if i.get("choices") else "") for i in nt.inputs]
    if nt.outputs:
        d["out"] = [f"{o['name']}:{o['type']}" for o in nt.outputs]
    if nt.category == "start":
        d["start"] = True
    if nt.exec_in:
        d["exec_in"] = "exec"
    names = nt.exec_out_names(None)
    if names:
        d["exec_out"] = names
        if nt.exec_out_from:
            d["exec_out_named_by"] = nt.exec_out_from[0]
    if nt.dynamic_inputs:
        d["extra_inputs"] = "any name"
    for key, flag in (("consent", nt.consent), ("outside", nt.outside_content), ("costly", nt.costly)):
        if flag:
            d[key] = flag
    if not nt.available:
        d["unavailable"] = nt.note
    return d
