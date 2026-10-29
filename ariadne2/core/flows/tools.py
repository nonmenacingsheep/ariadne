"""Her three flow tools (DESIGN §4/§10): flow_nodes, flow_save, flow_manage.

Tool names use underscores (the API forbids dots). Every state-changing call
needs his own words this turn (his_words) -- a flow's Ask Aries or Decide turn
runs with none, so a DM can't talk her into building, running or deleting
flows. His own flows additionally need him to name them.
"""
from __future__ import annotations

import json

from ...adapters import AdapterError
from .catalog import compact

OPS = ("list", "explain", "run", "enable", "disable", "delete")
NAMES = ("flow_nodes", "flow_save", "flow_manage")

TOOL_DEFS = [
    {"name": "flow_nodes",
     "description": "Search the flow node catalog (what a flow can start from, check, and do). Returns compact "
                    "entries: type, what it does, inputs name:type (* = required), outputs, exec pins. "
                    "Search before building; node types are never guessed.",
     "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
    {"name": "flow_save",
     "description": "Save a flow (a small graph: a start node wired to checks and actions). graph = "
                    "{name, nodes:[{id,type,values:{input:value}}], links:[{from:[node,pin], to:[node,pin]}], "
                    "mode?:ignore|restart|queue|parallel}. An exec link runs the next node: from an exec-out pin "
                    "(start nodes: exec; Branch: true/false; actions: done/failed) to the target's exec pin, "
                    "always named exec. A data link carries a value from an output pin to an input. An unwired "
                    "input takes its typed-in value from values. Errors come back by name; fix and save again "
                    "(at most twice). Pass id to replace one of your flows.",
     "input_schema": {"type": "object", "properties": {"graph": {"type": "object"}}, "required": ["graph"]}},
    {"name": "flow_manage",
     "description": "Look after flows: op list (all, one line each), explain (what it does and how it ran), run, "
                    "enable, disable, delete. id is a flow id or its name. Only touch his own flows when he "
                    "names them.",
     "input_schema": {"type": "object", "properties": {"id": {"type": "string"},
                                                       "op": {"type": "string", "enum": list(OPS)}},
                      "required": ["op"]}},
]

OVERVIEW = ("Categories: start (time.at/every/after, time.becomes, you.say, you.run_button, <app>.<event>), "
            "check (check.branch, compare, time_between, cooldown, settle, count...), action (<app>.<verb>, "
            "her.tell, her.say, her.ask_aries, her.decide, you.ask_ronald, desktop.notify, file.move), "
            "flow (flow.wait, wait_for, sequence, for_each, stop), data (data.text, get, set, math, list). "
            "Search with a few words, e.g. 'steam download'.")


def _find(engine, key: str) -> str | None:
    key = (key or "").strip().lower()
    for fid, f in engine.flows.items():
        if key in (fid.lower(), f["name"].lower()):
            return fid
    hits = [fid for fid, f in engine.flows.items() if key and key in f["name"].lower()]
    return hits[0] if len(hits) == 1 else None


def _may_touch(flow: dict, his_words: str | None) -> bool:
    if not his_words:
        return False
    if flow["made_by"] == "aries":
        return True
    low = his_words.lower()
    return flow["name"].lower() in low or flow["id"].lower() in low


async def call(engine, name: str, args: dict, his_words: str | None = None) -> str:
    args = args or {}
    if name == "flow_nodes":
        found = engine.catalog.search(str(args.get("query") or ""), 8)
        if not found:
            return "No node matches. " + OVERVIEW
        return json.dumps([compact(nt) for nt in found], ensure_ascii=False, separators=(",", ":"))
    if name == "flow_save":
        return await _save(engine, args.get("graph"), his_words)
    if name == "flow_manage":
        return await _manage(engine, args, his_words)
    raise AdapterError(f"I have no tool called {name!r}")


async def _save(engine, graph, his_words) -> str:
    if not his_words:
        raise AdapterError("Not saved: building flows needs him to ask in his own words, not a flow's turn.")
    if not isinstance(graph, dict):
        raise AdapterError("Not saved: graph must be an object with name, nodes and links.")
    existing = engine.flows.get(str(graph.get("id") or ""))
    if existing and not _may_touch(existing, his_words):
        raise AdapterError(f"Not saved: {existing['name']} is his own flow; he has to name it before you change it.")
    res = engine.save_graph(graph, made_by="aries", keep_id=bool(existing))
    if not res.ok:
        raise AdapterError("Not saved. Fix these and save again:\n" + "\n".join(f"- {e}" for e in res.errors))
    await engine.broadcast_graph(res.id, "aries")            # an open editor sees it appear
    out = f"Saved {res.id}: {res.summary}"
    if res.needs_approval:
        out += ("\nIt uses a message verb or outside content, so it's saved OFF until he approves it "
                "(Approve in the Flows widget, where he can see the graph). Tell him so.")
    elif res.enabled:
        out += "\nIt's on."
    if res.warnings:
        out += "\nNote: " + "; ".join(res.warnings)
    return out


async def _manage(engine, args: dict, his_words) -> str:
    op = args.get("op")
    if op not in OPS:
        raise AdapterError(f"op must be one of {', '.join(OPS)}")
    if op == "list":
        rows = engine.rows()
        if not rows:
            return "No flows yet."
        return "\n".join(f"{r['id']} {r['name']} [{'on' if r['enabled'] else 'off'}"
                         f"{'' if r['approved'] else ', needs approval'}]: {r['summary']}" for r in rows)
    fid = _find(engine, str(args.get("id") or ""))
    if fid is None:
        raise AdapterError(f"No flow matches {args.get('id')!r}; use op list.")
    if op == "explain":
        return engine.explain(fid)
    if not _may_touch(engine.flows[fid], his_words):
        raise AdapterError("Not done: that needs him to ask in his own words, naming the flow if it's his.")
    if op == "run":
        result = engine.run_now(fid)
        return "Started." if result == "started" else f"Didn't start: {result}"
    if op in ("enable", "disable"):
        result = await engine.set_enabled(fid, op == "enable", by="aries")
        if result not in ("on", "off"):
            raise AdapterError(f"Not changed: {result}")
        return f"{engine.flows[fid]['name']} is {result}."
    result = await engine.delete(fid)
    return f"{result}."
