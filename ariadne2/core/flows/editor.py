"""The visual editor's half of the core (DESIGN §10, "By you, in the editor" and "In the editor, live").

The desk holds no logic: it asks for the node catalog, opens a flow, sends his
edits to be checked and saved, and asks for a dry run; the core answers with
the messages in protocol.py (flow_catalog / flow_open / flow_save / flow_test).
Whenever SHE saves or changes a flow, the whole graph is broadcast so an open
editor shows it appear.

EditorMixin is the third part of the Engine (see engine.py, manage.py, runner.py).
"""
from __future__ import annotations

import asyncio
import copy
import re

from ... import protocol
from . import graph as G

IN = ("flow_catalog", "flow_open", "flow_save", "flow_test")
TEST_TIMEOUT = 30.0
SAMPLE = {"number": 1, "yes/no": True, "duration": "1m", "time": "12:00", "list": ["sample"]}

_DOTTED = re.compile(r"([A-Za-z0-9_\-]{1,40}) \([^()]*\)\.(\w+)")        # "n2 (Tell).text"
_LABEL = re.compile(r"([A-Za-z0-9_\-]{1,40}) \([^()]*\)")                # "n2 (Tell)"
_LEAD = re.compile(r"([A-Za-z0-9_\-]{1,40}): ")                         # "n3: unknown node type"
_LOOP = re.compile(r"\(([A-Za-z0-9_\-]+)(?: -> [A-Za-z0-9_\-]+)+\)")    # "(n1 -> n2 -> n1)"


def locate(message: str, graph: dict, catalog) -> tuple[str | None, str | None]:
    """Which node (and pin) a validation message is about. graph.py words its errors for the model
    ("n2 (Tell): text needs a value"); the editor wants them on the node, so read them back."""
    ids = {n["id"]: n for n in graph.get("nodes", ())}
    dotted = [(a, b) for a, b in _DOTTED.findall(message) if a in ids]
    if dotted:
        return dotted[-1]                            # a wire problem: the end it arrives at
    labels = [m for m in _LABEL.finditer(message) if m.group(1) in ids]
    node, rest = None, ""
    if labels:
        node, rest = labels[0].group(1), message[labels[0].end():]
    else:
        m = _LEAD.match(message) or None
        if m and m.group(1) in ids:
            node, rest = m.group(1), message[m.end() - 2:]
        else:
            m = _LOOP.search(message)
            if m and m.group(1) in ids:
                return m.group(1), None
    if node is None:
        return None, None
    nt = catalog.get(ids[node]["type"])
    known = set()
    if nt is not None:
        known = {i["name"] for i in nt.inputs} | {o["name"] for o in nt.outputs} | set(nt.exec_out_names(None))
    m = re.match(r":\s*(\w+)", rest)
    if m and m.group(1) in known:
        return node, m.group(1)
    m = re.search(r"no input '(\w+)'", rest)
    if m:
        return node, m.group(1)
    if "state field" in rest and "field" in known:
        return node, "field"
    return node, None


class EditorMixin:
    def structured(self, graph: dict, messages: list[str]) -> list[dict]:
        """Validation messages as protocol errors: {node, pin, message}."""
        return [protocol.flow_error(m, *locate(m, graph, self.catalog)) for m in messages]

    # ---- what goes out ----

    def fresh_graph(self) -> dict:
        """An empty flow, not saved. Off until he turns it on (DESIGN: save, then the toggle)."""
        return {"id": "", "name": "", "enabled": False, "made_by": "ronald", "approved": True, "mode": "ignore",
                "created": None, "updated": None, "nodes": [], "links": []}

    def graph_message(self, fid: str, by: str | None = None) -> dict:
        """The whole flow file as flow_graph; nodes always have a position."""
        flow = copy.deepcopy(self.flows[fid])
        G.layout(flow, self.catalog)
        rep = G.validate(flow, self.catalog)
        return protocol.flow_graph(fid, flow, self._summaries.get(fid, ""),
                                   self.structured(flow, rep.errors), by)

    async def broadcast_graph(self, fid: str, by: str | None = "aries") -> None:
        """Tell an open editor this flow was just saved or changed by someone else."""
        if fid in self.flows:
            await self._pub(self.graph_message(fid, by))

    # ---- what comes in ----

    async def on_editor(self, msg: dict) -> None:
        t = msg.get("t")
        if t == "flow_catalog":
            await self._pub(protocol.catalog([nt.to_dict() for nt in self.catalog.types.values()]))
        elif t == "flow_open":
            await self._open(msg.get("id"))
        elif t == "flow_save":
            await self._editor_save(msg["graph"])
        elif t == "flow_test":
            await self._editor_test(msg)

    async def _open(self, fid) -> None:
        if fid is None:
            fresh = self.fresh_graph()
            await self._pub(protocol.flow_graph(None, fresh, G.summary(fresh, self.catalog), []))
        elif fid in self.flows:
            await self._pub(self.graph_message(fid))
        else:
            await self._pub(protocol.flow_graph(fid, None, "", [protocol.flow_error("there's no such flow")]))

    async def _editor_save(self, raw) -> None:
        g = G.normalize(raw)
        old = self.flows.get(g["id"]) if g["id"] else None
        g["approved"] = True                    # his flows are trusted; saving one of hers is his approval (he saw the graph)
        if old is not None:
            # the Flows widget's toggle is the truth about on/off, not the editor's copy; approving one of
            # hers turns it on, as the Approve button does
            g["enabled"] = True if not old["approved"] else old["enabled"]
        res = self.save_graph(g, made_by="ronald")
        if not res.ok:
            await self._pub(protocol.flow_saved(g["id"] or None, False, errors=self.structured(g, res.errors)))
            return
        await self._pub(protocol.flow_saved(res.id, True, res.summary, warnings=self.structured(g, res.warnings)))

    # ---- test: a dry run on a copy ----

    def _sample_fields(self, real_id: str, c: G.Compiled, start: str) -> dict:
        """What the start puts out: the last real firing of this flow if it has one, else a sample of each type."""
        if real_id in self.flows:
            runs = [r for r in self.store.runs(real_id) if r["trigger"]["node"] == start]
            if runs:
                return dict(runs[-1]["trigger"]["fields"])
        return {o["name"]: SAMPLE.get(o["type"], "sample") for o in c.types[start].outputs}

    async def _editor_test(self, msg: dict) -> None:
        """Dry-run the graph as given (or the saved flow). It runs on a throwaway copy, so a test never
        touches the real flow's variables, cooldowns or history, and needs no approval or switch-on; its
        events carry the real flow's id so the editor lights the nodes."""
        shown = msg["id"] if isinstance(msg.get("id"), str) else ""
        raw = msg.get("graph")
        if raw is None:
            if shown not in self.flows:
                await self._pub(protocol.flow_tested(shown or None, False, "there's no such flow"))
                return
            raw = self.flows[shown]
        g = G.normalize(raw)
        shown = shown or g["id"]
        g.update(enabled=True, approved=True)
        rep = G.validate(g, self.catalog)
        if rep.errors:
            await self._pub(protocol.flow_tested(shown or None, False, f"can't test yet: {rep.errors[0]}",
                                                 self.structured(rep.graph, rep.errors)))
            return
        g = rep.graph
        c = G.Compiled(g, self.catalog)
        usable = [s for s in c.starts if c.types[s].available]
        start = msg.get("start") if msg.get("start") in usable else \
            next((s for s in usable if c.types[s].kind == "run_button"), None) or (usable[0] if usable else None)
        if start is None:
            await self._pub(protocol.flow_tested(shown or None, False, "it has no start I can run"))
            return
        tmp = f"_test_{next(self._n)}"
        g["id"] = tmp
        self._load(tmp, g)
        self._alias[tmp] = shown
        run = None
        try:
            if shown in self.flows:                                  # Get nodes see his real variables
                self.store.state(tmp)["vars"] = copy.deepcopy(self.store.state(shown)["vars"])
            run = self.fire(tmp, start, self._sample_fields(shown, c, start), widget="flows", manual=True, dry=True)
            if run is None:
                await self._pub(protocol.flow_tested(shown or None, False, self.last_refusal or "it didn't start"))
                return
            try:
                await asyncio.wait_for(asyncio.shield(run.task), TEST_TIMEOUT)
            except asyncio.TimeoutError:
                pass
            if run.id in self.runs:                                  # still going: stop it where it stands
                self._cancel(run, "the test stopped at a pause")
            ok = run.status in ("ok", "skipped")
            note = run.note or (f"{len(run.path)} nodes ran" if ok else "it didn't finish")
            await self._pub(protocol.flow_tested(shown or None, ok, note))
        finally:
            for d in (self.flows, self.compiled, self.invalid, self._summaries, self._queues, self._fire_times,
                      self._alias):
                d.pop(tmp, None)
            self.store.delete(tmp)
