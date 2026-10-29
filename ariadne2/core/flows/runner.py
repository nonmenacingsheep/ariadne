"""Walking one run (DESIGN §10, "A run"): the exec wires from the start, data
inputs pulled on demand, actions awaited through the same tool layer as her
own calls. Wait, Wait for, Settle and Ask Ronald pause the run; the walk's
position is an explicit stack of small dicts, so a paused run is plain JSON
and resumes after a restart.

RunnerMixin is the half of the Engine that executes nodes (engine.py has the
other half: events, timers, modes, publishing).
"""
from __future__ import annotations

import asyncio
import datetime
import logging
import os
import pathlib
import re
import shutil
from dataclasses import dataclass, field

from ... import adapters as adapters_mod
from .. import models
from ...adapters import AdapterError, consent
from . import nodes
from . import values as V
from .graph import Compiled

log = logging.getLogger("ariadne2.core.flows.runner")

MAX_STEPS = 400            # nodes one run may execute (a For each of 100 is well inside)
MAX_ITEMS = 100
MAX_DEPTH = 3              # chains of flows causing flows (DESIGN: depth 3)
CAUSE_GRACE = 10.0         # seconds after an action during which its adapter's events count as its doing
_NO_TOUCH = (".ssh", ".gnupg", ".aws", ".password-store")


@dataclass
class Run:
    id: str
    flow_id: str
    depth: int = 1
    dry: bool = False
    started: float = 0.0
    trigger: dict = field(default_factory=dict)       # {"node","type","fields"}
    stack: list = field(default_factory=list)
    outputs: dict = field(default_factory=dict)       # node -> {pin: value}
    path: list = field(default_factory=list)
    grants: list = field(default_factory=list)        # Ask Ronald "yes" answers that may stand for his words once
    waiting: dict | None = None
    steps: int = 0
    note: str | None = None
    results: list = field(default_factory=list)       # what its actions reported, for the one folded chat line
    manual: bool = False

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in ("id", "flow_id", "depth", "dry", "started", "trigger", "stack",
                                              "outputs", "path", "grants", "waiting", "steps", "results", "manual")}

    @classmethod
    def from_dict(cls, d: dict) -> "Run":
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})


@dataclass
class Step:
    pins: list | None = None       # exec pins to follow, in order
    pause: dict | None = None
    stop: bool = False             # end the run now, ok
    quiet: str | None = None       # end the run now, not an error: a gate that didn't pass
    fail: str | None = None        # the action failed


def pick_choice(text: str | None, choices: list[str]) -> str | None:
    """Which named choice a reply means: its first word if that is one, else the only one it mentions."""
    if not text:
        return None
    norm = {c.lower(): c for c in choices}
    words = re.findall(r"[\w']+", text.lower())
    if words and words[0] in norm:
        return norm[words[0]]
    hits = [c for k, c in norm.items() if re.search(rf"\b{re.escape(k)}\b", text.lower())]
    return hits[0] if len(hits) == 1 else None


def _guard_path(p: str) -> pathlib.Path:
    path = pathlib.Path(os.path.expanduser(p)).resolve()
    home = pathlib.Path.home().resolve()
    if path == pathlib.Path("/") or path == home or any(part in _NO_TOUCH for part in path.parts):
        raise AdapterError(f"I won't touch {p}")
    return path


def _copy_or_move(op: str, src: str, dst: str) -> str:
    s, d = _guard_path(src), pathlib.Path(os.path.expanduser(dst))
    if not s.exists():
        raise AdapterError(f"{src} isn't there")
    if d.is_dir():
        d = d / s.name
    d = d.resolve()
    _guard_path(str(d))
    if d.exists():
        raise AdapterError(f"{d} already exists; I won't overwrite it")
    d.parent.mkdir(parents=True, exist_ok=True)
    if op == "move":
        shutil.move(str(s), str(d))
    elif s.is_dir():
        shutil.copytree(s, d)
    else:
        shutil.copy2(s, d)
    return f"{'moved' if op == 'move' else 'copied'} {s.name} to {d.parent}"


class RunnerMixin:
    # ---- the walk ----

    def _push(self, run: Run, c: Compiled, nid: str, pins: list[str]) -> None:
        targets = [t for pin in pins for t in c.next.get((nid, pin), ())]
        run.stack.extend({"k": "n", "node": t} for t in reversed(targets))

    async def _walk(self, run: Run) -> str:
        """Run until the stack is empty or something pauses. 'ok' | 'failed' | 'skipped' | 'paused'."""
        c = self.compiled.get(run.flow_id)
        if c is None:
            run.note = "the flow is gone"
            return "failed"
        while run.stack:
            if run.steps >= MAX_STEPS:
                run.note = f"stopped after {MAX_STEPS} steps; is something looping?"
                return "failed"
            frame = run.stack.pop()
            if frame["k"] == "fe":
                self._for_each_next(run, c, frame)
                continue
            nid = frame["node"]
            if nid not in c.nodes or c.types.get(nid) is None:
                continue
            run.steps += 1
            run.path.append(nid)
            nt = c.types[nid]
            await self._publish_flow(run, "node", nid, widget=nt.meta.get("adapter"))
            try:
                step = await self._exec(run, c, nid, nt)
            except AdapterError as e:
                step = Step(fail=str(e))
            if step.fail is not None:
                run.outputs.setdefault(nid, {})["error"] = step.fail
                if c.next.get((nid, "failed")):
                    self._push(run, c, nid, ["failed"])
                    continue
                run.note = step.fail
                return "failed"
            if step.quiet:
                run.note = step.quiet
                return "skipped"
            if step.stop:
                run.stack.clear()
                return "ok"
            if step.pause:
                run.waiting = dict(step.pause, node=nid)
                return "paused"
            self._push(run, c, nid, step.pins if step.pins is not None else nt.exec_out_names(c.nodes[nid]["values"])[:1])
        return "ok"

    def _for_each_next(self, run: Run, c: Compiled, frame: dict) -> None:
        nid, items, i = frame["node"], frame["items"], frame["i"]
        if i < len(items):
            run.outputs[nid] = {"item": items[i], "index": i + 1}
            run.stack.append(dict(frame, i=i + 1))
            self._push(run, c, nid, ["body"])
        else:
            self._push(run, c, nid, ["done"])

    def resume_pins(self, run: Run, c: Compiled, pin: str) -> None:
        """A paused run carries on from the pin it was waiting to take."""
        nid = run.waiting["node"]
        run.waiting = None
        self._push(run, c, nid, [pin])

    # ---- data ----

    async def _val(self, run: Run, c: Compiled, nid: str, name: str, depth: int = 0):
        src = c.feed.get((nid, name))
        if src and src[0] in c.nodes:
            return await self._out(run, c, src[0], src[1], depth)
        node, nt = c.nodes[nid], c.types[nid]
        v = node["values"].get(name)
        if v is None:
            inp = nt.input(name)
            v = inp["default"] if inp else None
        return v

    async def _out(self, run: Run, c: Compiled, nid: str, pin: str, depth: int):
        have = run.outputs.get(nid)
        if have is not None and pin in have:
            return have[pin]
        nt = c.types.get(nid)
        if nt is None or depth > 20 or nt.kind not in nodes.PURE_KINDS:
            return None
        return nodes.compute(nt.kind, nt, await self._inputs(run, c, nid, depth + 1), self._ctx(run)).get(pin)

    async def _inputs(self, run: Run, c: Compiled, nid: str, depth: int = 0) -> dict:
        nt, node = c.types[nid], c.nodes[nid]
        out = {i["name"]: await self._val(run, c, nid, i["name"], depth) for i in nt.inputs}
        if nt.dynamic_inputs:
            names = {k for (n, k) in c.feed if n == nid} | set(node["values"])
            for k in sorted(names - set(out)):
                out[k] = await self._val(run, c, nid, k, depth)
        return out

    # ---- nodes ----

    async def _exec(self, run: Run, c: Compiled, nid: str, nt) -> Step:
        kind, node = nt.kind, c.nodes[nid]
        inputs = await self._inputs(run, c, nid)
        now = self.now()
        st = self.store.state(run.flow_id)
        if kind in nodes.PURE_KINDS:
            outs = nodes.compute(kind, nt, inputs, self._ctx(run))
            run.outputs[nid] = outs
            if kind in ("time_between", "day_is"):
                return Step(pins=["true" if outs["result"] else "false"])
            return Step(pins=[])
        if kind == "branch":
            return Step(pins=["true" if V.as_bool(inputs.get("cond")) else "false"])
        if kind == "sequence":
            return Step(pins=list(nt.exec_out))
        if kind == "stop":
            return Step(stop=True)
        if kind == "cooldown":
            gap, key = V.parse_duration(inputs.get("every")) or 0, f"cool:{nid}"
            last = st["timers"].get(key)
            if last is not None and now - last < gap:
                return Step(quiet=f"cooling down ({V.fmt_duration(gap - (now - last))} left)")
            st["timers"][key] = now
            return Step()
        if kind == "once_per_day":
            today, key = datetime.date.fromtimestamp(now).isoformat(), f"day:{nid}"
            if st["timers"].get(key) == today:
                return Step(quiet="already ran today")
            st["timers"][key] = today
            return Step()
        if kind == "count":
            times = self._fire_times.setdefault(run.flow_id, [])
            within, need = V.parse_duration(inputs.get("within")) or 0, int(V.as_number(inputs.get("n")) or 1)
            if sum(1 for t in times if now - t <= within) < need:
                return Step(quiet=f"waiting for {need} within {V.fmt_duration(within)}")
            times.clear()
            return Step()
        if kind == "settle":
            quiet = V.parse_duration(inputs.get("quiet")) or 0
            return Step(pause={"kind": "settle", "until": now + quiet, "quiet": quiet})
        if kind == "wait":
            return Step(pause={"kind": "wait", "until": now + (V.parse_duration(inputs.get("duration")) or 0)})
        if kind == "wait_for":
            return Step(pause={"kind": "wait_for", "event": V.text_of(inputs.get("event")),
                               "until": now + (V.parse_duration(inputs.get("timeout")) or 3600)})
        if kind == "for_each":
            items = inputs.get("items")
            items = items if isinstance(items, list) else [x.strip() for x in re.split(r"[\n,]", V.text_of(items)) if x.strip()]
            run.stack.append({"k": "fe", "node": nid, "items": items[:MAX_ITEMS], "i": 0})
            return Step(pins=[])
        if kind == "set":
            st["vars"][V.text_of(inputs.get("name"))] = inputs.get("value")
            return Step()
        if kind == "run_flow":
            return await self._run_flow_node(run, inputs)
        return await self._action(run, c, nid, nt, inputs)

    async def _action(self, run: Run, c: Compiled, nid: str, nt, inputs: dict) -> Step:
        kind = nt.kind
        out = run.outputs.setdefault(nid, {})
        if run.dry:                       # a test run: wires animate, actions only pretend
            run.results.append("(dry run)")
            return Step(pins=["done"] if "done" in nt.exec_out else nt.exec_out_names(c.nodes[nid]["values"])[:1])
        if kind == "ask_ronald":
            return self._ask(run, c, nid, nt, inputs)
        if kind == "verb":
            args = self._verb_args(nt, inputs)
            text = await self._call_verb(run, nt, args)
            out["result"] = text
            run.results.append(text)
            return Step(pins=["done"])
        if kind == "tell":
            await self.tell(V.text_of(inputs.get("text")))
            return Step(pins=["done"])
        if kind == "say":
            text = V.text_of(inputs.get("text"))
            if self.say_hook:
                self.say_hook(text)
            else:
                await self.tell(text)
            return Step(pins=["done"])
        if kind == "notify":
            await self.notify(V.text_of(inputs.get("title")) or "Ariadne", V.text_of(inputs.get("text")))
            return Step(pins=["done"])
        if kind in ("file_move", "file_copy"):
            msg = await asyncio.to_thread(_copy_or_move, "move" if kind == "file_move" else "copy",
                                          V.text_of(inputs.get("src")), V.text_of(inputs.get("dst")))
            run.results.append(msg)
            return Step(pins=["done"])
        if kind in ("ask_aries", "decide"):
            return await self._ask_aries(run, c, nid, nt, inputs)
        raise AdapterError(f"{nt.title} can't run yet: {nt.note or 'no implementation'}")

    @staticmethod
    def _verb_args(nt, inputs: dict) -> dict:
        args = {}
        for name, jt in nt.meta["json"].items():
            v = inputs.get(name)
            if v is None or v == "":
                continue
            try:
                if jt == "integer":
                    v = int(float(v))
                elif jt == "number":
                    v = float(v)
                elif jt == "boolean":
                    v = V.as_bool(v)
                elif jt == "array":
                    v = v if isinstance(v, list) else [v]
                else:
                    v = V.text_of(v)
            except (TypeError, ValueError):
                raise AdapterError(f"{nt.title}: {name} should be a {jt}")
            args[name] = v
        return args

    async def _call_verb(self, run: Run, nt, args: dict) -> str:
        """An adapter verb, through call_tool like her own calls.

        CONSENT INSIDE FLOWS: a flow has no "his words this turn", so
        call_tool gets his_words=None and a consent verb refuses. The one way
        through: an Ask Ronald whose *typed-in* question named the recipient
        was answered with a yes-type button, wired from that yes pin. That
        answer is held in run.grants as "<his answer>, <the question>" and is
        offered as his_words, once, to the same unchanged consent check (so
        the question must also ask for the message in words like send/tell
        and name the person, or the verb still refuses).
        """
        entry = self._cause_start(nt.meta["adapter"], run)
        try:
            his = None
            if nt.consent:
                person = args.get("person") or args.get("to") or args.get("recipient")
                for g in list(run.grants):
                    if (consent.allows_spend(g) if nt.consent == "spend"
                            else consent.allows_message(g, person)):
                        his = g
                        run.grants.remove(g)       # one run's consent covers one message or run
                        break
            return await adapters_mod.call_tool(self.adapters, nt.meta["tool"], args, his_words=his)
        finally:
            self._cause_end(entry)

    def _ask(self, run: Run, c: Compiled, nid: str, nt, inputs: dict) -> Step:
        node = c.nodes[nid]
        options = [str(x) for x in (inputs.get("options") or nt.exec_out_from[1])]
        timeout = V.parse_duration(inputs.get("timeout")) or 3600
        ask_id = f"ask-{self._boot}-{next(self._n)}"
        # Consent may only come from words he could see as a fixed question: a
        # question wired from data (a DM's text) never counts as his say-so.
        literal = (nid, "question") not in c.feed
        return Step(pause={"kind": "ask", "ask_id": ask_id, "options": options,
                           "question": V.text_of(inputs.get("question")),
                           "literal": literal and isinstance(node["values"].get("question"), str),
                           "until": self.now() + timeout})

    async def _ask_aries(self, run: Run, c: Compiled, nid: str, nt, inputs: dict) -> Step:
        conv = self.conversation
        if conv is None:
            raise AdapterError("I can't think about it right now")
        sentence = V.text_of(inputs.pop("sentence", ""))
        choices = None
        if nt.kind == "decide":
            choices = [str(x) for x in (inputs.pop("choices", None) or ["yes", "no"])]
        values = {k: V.text_of(v) for k, v in inputs.items() if v is not None}
        entry = self._cause_start(None, run)
        try:
            reply = await conv.flow_turn(self.flows[run.flow_id]["name"], sentence, values,
                                         choices=choices, post=nt.kind == "ask_aries")
        except models.ModelError as e:
            raise AdapterError(f"I couldn't get to my model: {e.message}")
        finally:
            self._cause_end(entry)
        out = run.outputs.setdefault(nid, {})
        if choices:
            picked = pick_choice(reply, choices)
            if picked is None:
                raise AdapterError(f"she didn't pick one of: {', '.join(choices)}")
            out["choice"] = picked
            return Step(pins=[picked])
        out["reply"] = reply or ""
        return Step(pins=["done"])

    async def _run_flow_node(self, run: Run, inputs: dict) -> Step:
        target = V.text_of(inputs.get("flow")).strip().lower()
        flow = next((f for f in self.flows.values() if target in (f["id"].lower(), f["name"].lower())), None)
        if flow is None:
            raise AdapterError(f"no flow called {inputs.get('flow')!r}")
        if not flow.get("approved", True):
            raise AdapterError(f"{flow['name']} hasn't been approved")
        if run.depth + 1 > MAX_DEPTH:
            raise AdapterError("flows are calling flows too deep")
        c = self.compiled.get(flow["id"])
        start = next((s for s in c.starts if c.types[s].kind == "run_button"), None) or (c.starts or [None])[0]
        if start is None:
            raise AdapterError(f"{flow['name']} has no start")
        child = self._new_run(flow["id"], start, {}, depth=run.depth + 1, dry=run.dry, manual=True)
        status = await self._drive(child, first=True)
        if status == "failed":
            raise AdapterError(f"{flow['name']} failed: {child.note}")
        return Step(pins=["done"])
