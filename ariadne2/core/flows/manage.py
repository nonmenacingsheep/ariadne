"""Editing and desk control of flows: save (with the safety rules), turn on and
off, approve, delete, run now, the Flows widget's presses, and "explain".
The other half of the Engine (engine.py); used by her tools, the desk and the importer.
"""
from __future__ import annotations

import dataclasses
import itertools
import secrets
import time

from . import graph as G


@dataclasses.dataclass
class SaveResult:
    ok: bool
    id: str | None = None
    summary: str = ""
    errors: list = dataclasses.field(default_factory=list)
    warnings: list = dataclasses.field(default_factory=list)
    needs_approval: bool = False
    enabled: bool = False


class ManageMixin:
    # ---- editing: used by her tools, the desk's presses and the importer ----

    def save_graph(self, raw, *, made_by: str = "ronald", keep_id: bool = True) -> SaveResult:
        g = G.normalize(raw)
        if made_by:
            g["made_by"] = made_by
        if not keep_id and g["id"] not in self.flows:
            g["id"] = ""
        rep = G.validate(g, self.catalog)
        g = rep.graph
        res = SaveResult(False, errors=list(rep.errors), warnings=list(rep.warnings))
        sf = G.safety(g, self.catalog)
        res.errors += sf.violations
        if res.errors:
            return res
        res.needs_approval = sf.needs_approval(g["made_by"])
        if g["made_by"] == "aries":
            g["approved"] = not res.needs_approval
            if res.needs_approval:
                g["enabled"] = False
        if not g["id"]:
            g["id"] = next(i for i in (f"f_{secrets.token_hex(2)}" for _ in itertools.count())
                           if i not in self.flows)
        G.layout(g, self.catalog)
        for r in [r for r in self.runs.values() if r.flow_id == g["id"]]:
            self._cancel(r, "the flow was edited")
        g = self.store.save(g, self.now())
        self._load(g["id"], g)
        self._reindex()
        self._baseline_becomes()
        self._arm(g["id"], fresh=True)
        self._spawn(self.publish_flows())
        res.ok, res.id, res.enabled = True, g["id"], g["enabled"]
        res.summary = self._summaries[g["id"]]
        return res

    def _write(self, fid: str, **changes) -> None:
        flow = dict(self.flows[fid], **changes)
        self.store.save(flow, self.now())
        self._load(fid, flow)
        self._reindex()

    async def set_enabled(self, fid: str, on: bool) -> str:
        flow = self.flows.get(fid)
        if flow is None:
            return "no such flow"
        if on and not flow["approved"]:
            return "it needs your approval first"
        if on:
            rep = G.validate(dict(flow, enabled=True), self.catalog)
            if rep.errors:
                return f"can't turn it on: {rep.errors[0]}"
        self._write(fid, enabled=on)
        self.store.set_note(fid, None)
        if not on:
            for r in [r for r in self.runs.values() if r.flow_id == fid]:
                self._cancel(r, "turned off")
        self._baseline_becomes()
        self._arm(fid, fresh=on)
        await self.publish_flows()
        return "on" if on else "off"

    async def approve(self, fid: str) -> str:
        if fid not in self.flows:
            return "no such flow"
        self._write(fid, approved=True)
        return await self.set_enabled(fid, True)

    async def delete(self, fid: str) -> str:
        if fid not in self.flows:
            return "no such flow"
        for r in [r for r in self.runs.values() if r.flow_id == fid]:
            self._cancel(r, "deleted")
        self._disarm(fid)
        self.store.delete(fid)
        for d in (self.flows, self.compiled, self.invalid, self._summaries, self._queues, self._fire_times):
            d.pop(fid, None)
        self._reindex()
        self._baseline_becomes()
        await self.publish_flows()
        return "deleted"

    def run_now(self, fid: str, fields: dict | None = None, dry: bool = False) -> str:
        c = self.compiled.get(fid)
        if c is None:
            return "no such flow"
        start = next((s for s in c.starts if c.types[s].kind == "run_button"), None) or \
            next((s for s in c.starts if c.types[s].available), None)
        if start is None:
            return "it has no start I can run"
        run = self.fire(fid, start, fields or {}, widget="flows", manual=True, dry=dry)
        return "started" if run else (self.last_refusal or "didn't start")

    async def on_press(self, msg: dict) -> None:
        fid, control = msg.get("value"), msg.get("control")
        if fid not in self.flows:
            return
        if control == "toggle":
            result = await self.set_enabled(fid, not self.flows[fid]["enabled"])
        elif control == "run":
            result = self.run_now(fid)
        elif control == "approve":
            result = await self.approve(fid)
        elif control == "delete":
            await self.delete(fid)
            return
        else:
            return
        if result not in ("on", "off", "started"):               # a refusal shows on the row
            self.store.set_note(fid, result)
            await self.publish_flows()

    async def on_desk(self, msg: dict) -> None:
        """The core's hook for desk messages that concern flows."""
        t = msg.get("t")
        if t == "hello" and msg.get("side") == "desk":
            await self.republish_asks()
        elif t == "answer":
            await self.on_answer(msg)
        elif t == "press" and msg.get("widget") == "flows":
            await self.on_press(msg)

    def explain(self, fid: str) -> str:
        f = self.flows.get(fid)
        if f is None:
            return "no such flow"
        st = self.store.state(fid)
        lines = [f"{f['name']} ({fid}), made by {f['made_by']}: {self._summaries.get(fid, '')}",
                 f"{'on' if f['enabled'] else 'off'}, {'approved' if f['approved'] else 'NOT approved yet'}, "
                 f"mode {f['mode']}"]
        if fid in self.invalid:
            lines.append(f"problem: {self.invalid[fid]}")
        if st["note"]:
            lines.append(f"note: {st['note']}")
        for r in st["runs"][-3:]:
            when = time.strftime("%a %H:%M", time.localtime(r["started"]))
            lines.append(f"ran {when}: {r['result']}" + (f" ({r['note']})" if r.get("note") else ""))
        return "\n".join(lines)
