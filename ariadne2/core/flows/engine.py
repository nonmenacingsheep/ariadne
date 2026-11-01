"""The flow engine (DESIGN §10, "How they run in the core").

Events come from the adapters' bus (Adapter.emit/subscribe) into an index of
event name -> start nodes; time starts sit in one scheduler; Becomes compares
each new state snapshot with the last. A firing becomes a Run (runner.py walks
it). Modes, the loop guard, pause/resume and publishing live here.
"""
from __future__ import annotations

import asyncio
import collections
import dataclasses
import itertools
import logging
import time

from ... import protocol
from ...adapters import AdapterError
from . import graph as G
from . import nodes
from . import values as V
from .catalog import Catalog, read_path
from .editor import EditorMixin
from .manage import ManageMixin
from .runner import CAUSE_GRACE, MAX_DEPTH, SHARED, Run, RunnerMixin
from .sched import LATE_GRACE, Clock, Scheduler, next_at
from .store import FlowStore

log = logging.getLogger("ariadne2.core.flows")

MAX_PER_MIN = 6
QUEUE_CAP = 20
NOTE_MAX = 140


@dataclasses.dataclass
class _Ctx:
    now: float
    vars: dict
    read: object
    shared: dict = dataclasses.field(default_factory=dict)


async def _notify_send(title: str, text: str) -> None:
    """A desktop toast, asked of the notification server over D-Bus (the
    container has no notify-send, and doesn't need one)."""
    def call() -> None:
        from gi.repository import Gio, GLib
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        bus.call_sync("org.freedesktop.Notifications", "/org/freedesktop/Notifications",
                      "org.freedesktop.Notifications", "Notify",
                      GLib.Variant("(susssasa{sv}i)", ("Ariadne", 0, "", title, text, [], {}, -1)),
                      GLib.VariantType.new("(u)"), Gio.DBusCallFlags.NONE, 5000, None)
    try:
        await asyncio.to_thread(call)
    except Exception as e:
        raise AdapterError(f"the toast didn't show ({getattr(e, 'message', e)})")


class Engine(RunnerMixin, ManageMixin, EditorMixin):
    def __init__(self, publish, adapters: dict, *, store: FlowStore | None = None, clock=None,
                 conversation=None, say=None, notify=None) -> None:
        self._publish = publish
        self.adapters = adapters
        self.store = store or FlowStore()
        self.clock = clock or Clock()
        self.sched = Scheduler(self.clock)
        self.conversation = conversation      # needs flow_turn(); set after the Conversation exists
        self.say_hook = say
        self._notify = notify or _notify_send
        self.catalog = Catalog.build(adapters)
        self.flows: dict[str, dict] = {}
        self.compiled: dict[str, G.Compiled] = {}
        self.invalid: dict[str, str] = {}
        self.runs: dict[str, Run] = {}
        self._boot = format(int(time.time()), "x")
        self._n = itertools.count(1)
        self._bg: set[asyncio.Task] = set()
        self._index: dict[str, list] = {}
        self._becomes: dict[tuple, bool] = {}
        self._causes: list[dict] = []
        self._fire_times: dict[str, list] = {}
        self._rate: dict[str, collections.deque] = {}
        self._queues: dict[str, collections.deque] = {}
        self._summaries: dict[str, str] = {}
        self.her_runs = False                 # his setting general.flows_on_her_own: she runs flows unasked
        self._alias: dict[str, str] = {}      # a test copy's id -> the flow id its events carry (editor.py)
        self.last_refusal = ""
        self._started = False

    def now(self) -> float:
        return self.clock.now()

    # ---- lifecycle ----

    async def start(self, timers: bool = True) -> None:
        self.reload_all()
        for a in self.adapters.values():
            a.subscribe(self.on_event)
        self._started = True
        self._baseline_becomes()
        for fid in self.flows:
            self._arm(fid, fresh=False)
        await self._resume_paused()
        if timers:
            self.sched.start()
        await self.publish_flows()
        for fid, nid in self._starts_of("started"):
            self.fire(fid, nid, {}, widget=None)

    async def stop(self) -> None:
        self._started = False
        for a in self.adapters.values():
            if self.on_event in a.subscribers:
                a.subscribers.remove(self.on_event)
        await self.sched.stop()
        for t in list(self._bg):
            t.cancel()
        await asyncio.gather(*self._bg, return_exceptions=True)

    async def idle(self) -> None:
        """Wait for every run in motion to finish or pause (tests, shutdown)."""
        while True:
            pending = [t for t in self._bg if not t.done()]
            if not pending:
                return
            await asyncio.gather(*pending, return_exceptions=True)

    def _spawn(self, coro) -> asyncio.Task:
        task = asyncio.ensure_future(coro)
        self._bg.add(task)
        task.add_done_callback(self._bg.discard)
        return task

    def _ctx(self, run: Run) -> _Ctx:
        return _Ctx(self.now(), self.store.state(run.flow_id)["vars"], self.read,
                    self.store.state(SHARED)["vars"])

    def read(self, adapter: str | None, field: str):
        spec = self.catalog.reads.get(f"{adapter}.{field}")
        a = self.adapters.get(adapter)
        if spec is None or a is None:
            return None
        try:
            return read_path(a.state(), spec[1])
        except Exception:
            return None

    # ---- loading and indexing ----

    def reload_all(self) -> None:
        self.flows, self.compiled, self.invalid = {}, {}, {}
        for fid, raw in self.store.load_all().items():
            self._load(fid, raw)
        self._reindex()

    def _load(self, fid: str, raw: dict) -> None:
        rep = G.validate(dict(raw, id=fid), self.catalog)
        self.flows[fid] = rep.graph
        self.compiled[fid] = G.Compiled(rep.graph, self.catalog)
        self._summaries[fid] = G.summary(rep.graph, self.catalog)
        if rep.errors:
            self.invalid[fid] = rep.errors[0]
        else:
            self.invalid.pop(fid, None)

    def runnable(self, fid: str) -> bool:
        f = self.flows.get(fid)
        return bool(f and f["enabled"] and f["approved"] and fid not in self.invalid)

    def _starts_of(self, kind: str) -> list[tuple[str, str]]:
        return [(fid, nid) for fid, c in self.compiled.items() if self.runnable(fid)
                for nid in c.starts if c.types[nid].kind == kind]

    def _reindex(self) -> None:
        self._index = {}
        for fid, c in self.compiled.items():
            if fid in self.invalid:
                continue
            for nid in c.starts:
                nt = c.types[nid]
                if nt.kind == "event":
                    self._index.setdefault(nt.meta["event"], []).append((fid, nid))

    def _baseline_becomes(self) -> None:
        """First sight of a condition sets what 'was'; it never fires by itself."""
        live = set()
        for fid, nid in self._starts_of("becomes"):
            live.add((fid, nid))
            if (fid, nid) not in self._becomes:
                self._becomes[(fid, nid)] = self._truth(fid, nid)
        for key in [k for k in self._becomes if k not in live]:
            del self._becomes[key]

    def _truth(self, fid: str, nid: str) -> bool:
        v = self.flows[fid]["nodes"]
        node = next(n for n in v if n["id"] == nid)["values"]
        adapter, _, fld = V.text_of(node.get("field")).partition(".")
        return nodes.compare(self.read(adapter, fld), node.get("op") or "is", node.get("value"))

    # ---- time starts ----

    def _disarm(self, fid: str) -> None:
        self.sched.cancel_where(lambda k: k[0] in ("t", "hold") and k[1] == fid)

    def _arm(self, fid: str, fresh: bool) -> None:
        self._disarm(fid)
        if not self.runnable(fid):
            return
        c, now, st = self.compiled[fid], self.now(), self.store.state(fid)
        for nid in c.starts:
            nt, v = c.types[nid], c.nodes[nid]["values"]
            key = ("t", fid, nid)
            if nt.kind == "at":
                hm = V.parse_time(v.get("time"))
                if hm:
                    self._sched_at(key, fid, nid, next_at(now, hm, V.parse_days(v.get("days") or []), v.get("dates")))
            elif nt.kind == "every":
                iv = V.parse_duration(v.get("interval"))
                if iv:
                    self._sched_every(key, fid, nid, now + iv, 0)
            elif nt.kind == "after":
                tkey, delay = f"after:{nid}", V.parse_duration(v.get("delay")) or 0
                if fresh or tkey not in st["timers"]:
                    st["timers"][tkey] = now + delay
                    self.store.save_state(fid)
                if st["timers"][tkey] != "done":
                    self.sched.schedule(key, st["timers"][tkey], lambda f=fid, n=nid: self._after_due(f, n))

    def _sched_at(self, key, fid, nid, due) -> None:
        self.sched.schedule(key, due, lambda: self._at_due(key, fid, nid, due))

    def _at_due(self, key, fid, nid, due) -> None:
        v = self.compiled[fid].nodes[nid]["values"]
        hm = V.parse_time(v.get("time"))
        self._sched_at(key, fid, nid, next_at(max(due, self.now()), hm, V.parse_days(v.get("days") or []), v.get("dates")))
        if self.now() - due <= LATE_GRACE:                  # a missed one (machine off) is skipped, not replayed
            self.fire(fid, nid, {"time": V.fmt_time(hm)})

    def _sched_every(self, key, fid, nid, due, count) -> None:
        self.sched.schedule(key, due, lambda: self._every_due(key, fid, nid, due, count))

    def _every_due(self, key, fid, nid, due, count) -> None:
        iv = V.parse_duration(self.compiled[fid].nodes[nid]["values"].get("interval")) or 60
        nxt = due + iv
        self._sched_every(key, fid, nid, nxt if nxt > self.now() else self.now() + iv, count + 1)
        self.fire(fid, nid, {"count": count + 1})

    def _after_due(self, fid: str, nid: str) -> None:
        st = self.store.state(fid)
        st["timers"][f"after:{nid}"] = "done"
        self.store.save_state(fid)
        self.fire(fid, nid, {})

    # ---- events, state, words ----

    def on_event(self, name: str, fields: dict) -> None:
        """An adapter's declared event (sync: the cause must be read while the action is still running)."""
        cause = self._cause_for(name.split(".")[0])
        for run in list(self.runs.values()):
            w = run.waiting
            if w and w["kind"] == "wait_for" and w["event"] == name:
                run.outputs.setdefault(w["node"], {})["event"] = f"{name} " + V.text_of(fields)
                self._resume(run, "exec")
        for fid, nid in list(self._index.get(name, ())):
            self.fire(fid, nid, dict(fields), widget=name.split(".")[0], cause=cause)

    def observe(self, msg: dict) -> None:
        """Tap on the publish path: a state snapshot of an adapter's widget."""
        if msg.get("t") == "state" and msg.get("widget") in self.adapters and self._started:
            self.on_state(msg["widget"])

    def on_state(self, widget: str) -> None:
        for fid, nid in self._starts_of("becomes"):
            v = self.compiled[fid].nodes[nid]["values"]
            if V.text_of(v.get("field")).partition(".")[0] != widget:
                continue
            key, truth = (fid, nid), self._truth(fid, nid)
            was = self._becomes.get(key)
            self._becomes[key] = truth
            if was is None or truth == was:
                continue
            hold_key = ("hold", fid, nid)
            if not truth:
                self.sched.cancel(hold_key)
                continue
            hold = V.parse_duration(v.get("hold") or 0) or 0
            if hold <= 0:
                self.fire(fid, nid, {"value": self.read(*V.text_of(v["field"]).split(".", 1))}, widget=widget)
            else:
                self.sched.schedule(hold_key, self.now() + hold, lambda f=fid, n=nid, w=widget: self._hold_due(f, n, w))

    def _hold_due(self, fid: str, nid: str, widget: str) -> None:
        if self.runnable(fid) and self._truth(fid, nid):       # still true after the hold
            v = self.compiled[fid].nodes[nid]["values"]
            self.fire(fid, nid, {"value": self.read(*V.text_of(v["field"]).split(".", 1))}, widget=widget)

    def hear(self, text: str) -> None:
        """What he said or typed to her: You say starts, and 'run <flow name>'."""
        low = " ".join((text or "").lower().split())
        if not low:
            return
        for fid, nid in self._starts_of("you_say"):
            phrase = V.text_of(self.compiled[fid].nodes[nid]["values"].get("phrase")).strip().lower()
            if phrase and phrase in low:
                self.fire(fid, nid, {"text": text}, widget="chat")
        if low.startswith("run "):
            wanted = low[4:].strip(" .!")
            for fid, nid in self._starts_of("run_button"):
                if self.flows[fid]["name"].lower() == wanted:
                    self.fire(fid, nid, {}, widget="chat", manual=True)

    # ---- who caused what (loop guard) ----

    def _cause_start(self, adapter: str | None, run: Run) -> dict:
        entry = {"adapter": adapter, "flow": run.flow_id, "depth": run.depth, "until": float("inf"),
                 "seq": next(self._n)}
        self._causes.append(entry)
        return entry

    def _cause_end(self, entry: dict) -> None:
        entry["until"] = self.now() + CAUSE_GRACE

    def _cause_for(self, adapter: str):
        now = self.now()
        self._causes = [e for e in self._causes if e["until"] >= now]
        mine = [e for e in self._causes if e["adapter"] in (adapter, None)]
        return (max(mine, key=lambda e: e["seq"]) if mine else None)

    # ---- firing ----

    def fire(self, fid: str, nid: str, fields: dict | None = None, *, widget: str | None = None,
             cause: dict | None = None, manual: bool = False, dry: bool = False) -> Run | None:
        self.last_refusal = ""
        flow = self.flows.get(fid)
        if flow is None:
            self.last_refusal = "no such flow"
            return None
        if fid in self.invalid:
            self.last_refusal = f"it has a problem: {self.invalid[fid]}"
            return None
        if not flow["approved"]:
            self.last_refusal = "it needs your approval first"
            return None
        if not flow["enabled"] and not manual:
            return None
        depth = 1
        if cause:
            depth = cause["depth"] + 1
            if cause["flow"] == fid:
                return None                             # a flow can't retrigger itself from its own action
            if depth > MAX_DEPTH:
                self.last_refusal = f"chain too deep (>{MAX_DEPTH})"
                return None
        now = self.now()
        for r in self.runs.values():                    # Settle: another firing resets its quiet timer
            if r.flow_id == fid and r.waiting and r.waiting["kind"] == "settle" and not dry:
                r.waiting["until"] = now + r.waiting["quiet"]
                r.trigger["fields"] = dict(fields or {})
                r.outputs[r.trigger["node"]] = dict(fields or {})
                self.sched.schedule(("run", r.id), r.waiting["until"], lambda r=r: self._resume(r, "exec"))
                self._save_paused(fid)
                return None
        times = self._fire_times.setdefault(fid, [])
        times.append(now)
        del times[:-200]
        if not manual and not dry:
            q = self._rate.setdefault(fid, collections.deque())
            q.append(now)
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) > MAX_PER_MIN:
                self._rate_pause(fid)
                return None
        live = [r for r in self.runs.values() if r.flow_id == fid]
        if live and not dry:
            mode = flow["mode"]
            if mode == "ignore":
                self.last_refusal = "it's already running"
                return None
            if mode == "queue":
                q = self._queues.setdefault(fid, collections.deque())
                if len(q) < QUEUE_CAP:
                    q.append((nid, dict(fields or {}), widget, depth, manual))
                self.last_refusal = "queued behind the run in progress"
                return None
            if mode == "restart":
                for r in live:
                    self._cancel(r, "restarted by a new firing")
        return self._launch(fid, nid, fields or {}, widget, depth, dry, manual)

    def _new_run(self, fid, nid, fields, depth=1, dry=False, manual=False, widget=None) -> Run:
        c = self.compiled[fid]
        run = Run(id=f"r_{self._boot}_{next(self._n)}", flow_id=fid, depth=depth, dry=dry, started=self.now(),
                  trigger={"node": nid, "type": c.nodes[nid]["type"], "fields": dict(fields), "widget": widget},
                  manual=manual)
        run.outputs[nid] = dict(fields)
        self._push(run, c, nid, c.types[nid].exec_out_names(c.nodes[nid]["values"]))
        self.runs[run.id] = run
        if not dry:
            st = self.store.state(fid)
            st["last_fired"] = run.started
            self.store.save_state(fid)
        return run

    def _launch(self, fid, nid, fields, widget, depth, dry, manual) -> Run:
        run = self._new_run(fid, nid, fields, depth, dry, manual, widget)
        run.task = self._spawn(self._drive(run, first=True))
        return run

    async def _drive(self, run: Run, first: bool = False) -> str:
        try:
            if first:
                await self._publish_flow(run, "fired", run.trigger["node"], widget=run.trigger.get("widget"))
                await self.publish_flows()
            status = await self._walk(run)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("flow %s run crashed", run.flow_id)
            run.note, status = "something broke on my side", "failed"
        if status == "paused":
            await self._on_paused(run)
            return status
        await self._finish(run, status)
        return status

    # ---- pausing and resuming ----

    async def _on_paused(self, run: Run) -> None:
        w = run.waiting
        pin = "timeout" if w["kind"] in ("ask", "wait_for") else "exec"
        if w.get("until") is not None:
            self.sched.schedule(("run", run.id), w["until"], lambda: self._resume(run, pin))
        self._save_paused(run.flow_id)
        if w["kind"] == "ask":
            await self._pub(protocol.ask(w["ask_id"], w["question"], w["options"]))
        await self.publish_flows()

    def _resume(self, run: Run, pin: str) -> None:
        if run.waiting is None or run.id not in self.runs:
            return
        c = self.compiled.get(run.flow_id)
        self.sched.cancel(("run", run.id))
        self.resume_pins(run, c, pin)
        self._save_paused(run.flow_id)
        self._spawn(self._drive(run))

    def _save_paused(self, fid: str) -> None:
        st = self.store.state(fid)
        st["paused"] = [r.to_dict() for r in self.runs.values() if r.flow_id == fid and r.waiting and not r.dry]
        self.store.save_state(fid)

    async def _resume_paused(self) -> None:
        for fid, d in self.store.all_paused():
            self.store.state(fid)["paused"] = []
            if fid not in self.compiled or not self.runnable(fid):
                self.store.save_state(fid)
                continue
            run = Run.from_dict(d)
            self.runs[run.id] = run
            await self._on_paused(run)

    async def republish_asks(self) -> None:
        for r in list(self.runs.values()):
            w = r.waiting
            if w and w["kind"] == "ask":
                await self._pub(protocol.ask(w["ask_id"], w["question"], w["options"]))

    async def on_answer(self, msg: dict) -> None:
        for r in list(self.runs.values()):
            w = r.waiting
            if not (w and w["kind"] == "ask" and w["ask_id"] == msg.get("id")):
                continue
            choice = msg.get("choice")
            if choice not in w["options"]:
                return
            r.outputs.setdefault(w["node"], {})["choice"] = choice
            if w["literal"] and G.is_affirmative(choice):
                r.grants.append(f"{choice}, {w['question']}")   # see RunnerMixin._call_verb
            self._resume(r, choice)
            return

    # ---- finishing ----

    def _cancel(self, run: Run, note: str) -> None:
        run.note = note
        run.status = "cancelled"
        self.sched.cancel(("run", run.id))
        self._record(run, "cancelled")
        self.runs.pop(run.id, None)
        self._save_paused(run.flow_id)

    def _record(self, run: Run, result: str) -> None:
        if run.dry:
            return
        def clip(v):
            return v if isinstance(v, (bool, int, float)) or v is None else V.clip(v, 200)
        self.store.add_run(run.flow_id, {
            "run": run.id, "started": run.started, "finished": self.now(), "result": result, "note": run.note,
            "trigger": {"node": run.trigger["node"], "type": run.trigger["type"],
                        "fields": {k: clip(v) for k, v in run.trigger["fields"].items()}},
            "path": run.path, "values": {n: {p: clip(v) for p, v in o.items()} for n, o in run.outputs.items()}})

    async def _finish(self, run: Run, status: str) -> None:
        fid, flow = run.flow_id, self.flows.get(run.flow_id)
        run.status = status
        self.runs.pop(run.id, None)
        self.sched.cancel(("run", run.id))
        self._record(run, status)
        st = self.store.state(fid)
        prev = (st["last_result"], st["note"])
        if not run.dry and status in ("ok", "failed"):
            st["last_result"] = status
            st["note"] = (run.note or "failed")[:NOTE_MAX] if status == "failed" else None
        self._save_paused(fid)
        name = flow["name"] if flow else fid
        await self._publish_flow(run, "failed" if status == "failed" else "done", note=run.note)
        if status == "failed" and not run.dry and prev != ("failed", st["note"]):
            await self.tell(f"{name}: stopped, {run.note}")     # once, not on every repeat
        elif status == "ok" and run.results and not run.dry:
            await self.tell(f"{name}: " + V.clip("; ".join(dict.fromkeys(run.results)), 120))
        await self.publish_flows()
        q = self._queues.get(fid)
        if q and not any(r.flow_id == fid for r in self.runs.values()) and self.runnable(fid):
            nid, fields, widget, depth, manual = q.popleft()
            self._launch(fid, nid, fields, widget, depth, False, manual)

    def _rate_pause(self, fid: str) -> None:
        flow = self.flows[fid]
        flow["enabled"] = False
        self.store.save(flow, self.now())
        self.store.set_note(fid, f"paused itself: it fired more than {MAX_PER_MIN} times in a minute")
        self._disarm(fid)
        self._rate.pop(fid, None)
        self._spawn(self._after_rate_pause(flow["name"]))

    async def _after_rate_pause(self, name: str) -> None:
        await self.tell(f"{name}: fired more than {MAX_PER_MIN} times in a minute, so I switched it off.")
        await self.publish_flows()

    # ---- publishing ----

    async def _pub(self, msg: dict) -> None:
        try:
            await self._publish(msg)
        except Exception:
            log.exception("flow publish failed")

    async def _publish_flow(self, run: Run, phase: str, node: str | None = None, widget: str | None = None,
                            note: str | None = None) -> None:
        if widget is not None and widget not in protocol.WIDGETS:
            widget = None
        await self._pub(protocol.flow(self._alias.get(run.flow_id, run.flow_id), run.id, phase, node, widget, note))

    async def tell(self, text: str) -> None:
        await self._pub(protocol.chat(f"flow-{self._boot}-{next(self._n)}", "aries", text, done=True))

    async def notify(self, title: str, text: str) -> None:
        await self._notify(title, text)

    def rows(self) -> list[dict]:
        out = []
        for fid, f in sorted(self.flows.items(), key=lambda kv: kv[1]["name"].lower()):
            if fid in self._alias:
                continue                    # a test copy, not a flow
            c, st = self.compiled[fid], self.store.state(fid)
            note = f"problem: {self.invalid[fid]}" if fid in self.invalid else st["note"]
            out.append({"id": fid, "name": f["name"], "summary": self._summaries.get(fid, ""),
                        "enabled": f["enabled"], "approved": f["approved"], "made_by": f["made_by"],
                        "uses_ai": c.uses_ai(), "manual": c.manual(), "last_fired": st["last_fired"],
                        "last_result": st["last_result"], "note": note})
        return out

    async def publish_flows(self) -> None:
        await self._pub(protocol.state("flows", {"flows": self.rows()}))
