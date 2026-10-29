"""Flow graphs: normalise, validate against the catalog, summarise, check the
safety rules, lay out. Pure functions of (graph dict, catalog); no I/O.

Validation errors name the node and pin ("n2 (Tell): text needs a value") so
she can fix them from the message alone.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import values as V
from .catalog import Catalog, NodeType

MODES = ("ignore", "restart", "queue", "parallel")
MADE_BY = ("ronald", "aries")
MAX_NODES, MAX_LINKS = 80, 300
ID_RE = re.compile(r"[A-Za-z0-9_\-]{1,40}")
# An Ask Ronald answer that means "go ahead". Only these pins count as his
# say-so for the safety rules and for consent (see engine.consent_grant).
AFFIRM = re.compile(r"^\s*(yes|yep|yeah|ok|okay|sure|send|do it|go|go ahead|approve|allow|confirm)\b", re.I)


def is_affirmative(choice) -> bool:
    return bool(AFFIRM.match(str(choice or "")))


@dataclass
class Report:
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    graph: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors


def _pair(x):
    """A link end: ["n1","exec"] or "n1.exec"."""
    if isinstance(x, str) and "." in x:
        a, _, b = x.partition(".")
        return [a, b]
    if isinstance(x, (list, tuple)) and len(x) == 2 and all(isinstance(i, str) for i in x):
        return [x[0], x[1]]
    return None


def normalize(raw) -> dict:
    """The graph with every field present and well-formed; junk is dropped or left for validate to name."""
    raw = raw if isinstance(raw, dict) else {}
    g = {"id": str(raw.get("id") or ""), "name": str(raw.get("name") or "").strip(),
         "enabled": bool(raw.get("enabled", True)), "made_by": raw.get("made_by") or "ronald",
         "approved": bool(raw.get("approved", True)), "mode": raw.get("mode") or "ignore",
         "created": raw.get("created"), "updated": raw.get("updated"), "nodes": [], "links": []}
    for n in raw.get("nodes") if isinstance(raw.get("nodes"), list) else []:
        if not isinstance(n, dict):
            continue
        pos = n.get("pos")
        pos = [float(pos[0]), float(pos[1])] if (isinstance(pos, (list, tuple)) and len(pos) == 2 and
                                                  all(isinstance(i, (int, float)) for i in pos)) else None
        g["nodes"].append({"id": str(n.get("id") or ""), "type": str(n.get("type") or ""),
                           "values": dict(n["values"]) if isinstance(n.get("values"), dict) else {},
                           "pos": pos})
    for ln in raw.get("links") if isinstance(raw.get("links"), list) else []:
        a, b = (_pair(ln.get("from")), _pair(ln.get("to"))) if isinstance(ln, dict) else (None, None)
        g["links"].append({"from": a, "to": b} if a and b else {"from": None, "to": None})
    return g


def _label(node: dict, nt: NodeType | None) -> str:
    return f"{node['id']} ({nt.title})" if nt else node["id"]


def _out_names(nt: NodeType, node: dict) -> list[str]:
    return nt.exec_out_names(node.get("values"))


def validate(raw, catalog: Catalog) -> Report:
    g = normalize(raw)
    rep = Report(graph=g)
    err, warn = rep.errors.append, rep.warnings.append
    if not g["name"]:
        err("the flow needs a name")
    if g["made_by"] not in MADE_BY:
        err(f"made_by must be one of {', '.join(MADE_BY)}")
    if g["mode"] not in MODES:
        err(f"mode must be one of {', '.join(MODES)}")
    if g["id"] and not ID_RE.fullmatch(g["id"]):
        err("the flow id may only use letters, digits, - and _")
    if len(g["nodes"]) > MAX_NODES or len(g["links"]) > MAX_LINKS:
        err(f"too big: at most {MAX_NODES} nodes and {MAX_LINKS} links")
        return rep
    nodes: dict[str, dict] = {}
    for n in g["nodes"]:
        if not ID_RE.fullmatch(n["id"]):
            err(f"node id {n['id']!r} must be 1-40 letters, digits, - or _")
        elif n["id"] in nodes:
            err(f"node id {n['id']} is used twice")
        else:
            nodes[n["id"]] = n
    types: dict[str, NodeType] = {}
    for nid, n in nodes.items():
        nt = catalog.get(n["type"])
        if nt is None:
            hint = catalog.suggest(n["type"])
            err(f"{nid}: unknown node type {n['type']!r}" + (f" (did you mean {', '.join(hint)}?)" if hint else
                                                           "; search with flow_nodes"))
            continue
        types[nid] = nt
        if not nt.available:
            (err if g["enabled"] else warn)(f"{_label(n, nt)} isn't available yet: {nt.note}")
    if not any(nt.category == "start" for nt in types.values()) and not any(
            catalog.get(n["type"]) is None for n in nodes.values()):
        err("the flow has no start node (something has to make it begin)")
    # ---- links ----
    wired: dict[tuple, int] = {}
    exec_edges: dict[str, list[str]] = {}
    data_edges: dict[str, list[str]] = {}
    reached: set[str] = set()
    for i, ln in enumerate(g["links"], 1):
        if not ln["from"] or not ln["to"]:
            err(f"link {i} is malformed: each end is [node, pin]")
            continue
        (fn, fp), (tn, tp) = ln["from"], ln["to"]
        missing = [x for x in (fn, tn) if x not in nodes]
        if missing:
            err(f"link {i} ({fn}.{fp} to {tn}.{tp}): no node {', '.join(missing)}")
            continue
        fnt, tnt = types.get(fn), types.get(tn)
        if fnt is None or tnt is None:
            continue                                    # the unknown type is already an error
        a, b = f"{_label(nodes[fn], fnt)}.{fp}", f"{_label(nodes[tn], tnt)}.{tp}"
        if fp in _out_names(fnt, nodes[fn]):
            if tp != "exec" or not tnt.exec_in:
                err(f"{a} is an exec out; it can only run into the exec input of a node that has one, not {b}")
                continue
            exec_edges.setdefault(fn, []).append(tn)
            reached.add(tn)
            continue
        outs = {o["name"]: o["type"] for o in fnt.outputs}
        if fp not in outs:
            have = ", ".join(_out_names(fnt, nodes[fn]) + list(outs)) or "none"
            err(f"{a}: {fnt.title} has no output pin {fp!r} (it has: {have})")
            continue
        inp = tnt.input(tp)
        if tp == "exec":
            err(f"{a} is data; it can't go into an exec input")
            continue
        if inp is None and not tnt.dynamic_inputs:
            err(f"{b}: {tnt.title} has no input {tp!r} (it has: {', '.join(i['name'] for i in tnt.inputs) or 'none'})")
            continue
        ftype, ttype = outs[fp], (inp["type"] if inp else "any")
        if not V.compatible(ftype, ttype):
            err(f"{a} gives {ftype} but {b} wants {ttype}")
            continue
        wired[(tn, tp)] = wired.get((tn, tp), 0) + 1
        if wired[(tn, tp)] > 1:
            err(f"{b} has two data wires; an input takes one")
        data_edges.setdefault(fn, []).append(tn)
    # ---- values ----
    for nid, n in nodes.items():
        nt = types.get(nid)
        if nt is None:
            continue
        label = _label(n, nt)
        for key, val in n["values"].items():
            inp = nt.input(key)
            if inp is None:
                if not nt.dynamic_inputs:
                    err(f"{label}: no input {key!r} (it has: {', '.join(i['name'] for i in nt.inputs) or 'none'})")
                elif not V.type_ok(val, "any"):
                    err(f"{label}: {key} must be text, a number or yes/no")
                continue
            if val is None:
                continue
            if not V.type_ok(val, inp["type"]):
                err(f"{label}: {key} should be a {inp['type']}, not {val!r}")
            elif inp.get("choices") and inp["type"] == "text" and val not in inp["choices"] and \
                    str(val).lower() not in [str(c).lower() for c in inp["choices"]]:
                err(f"{label}: {key} must be one of {', '.join(map(str, inp['choices']))}")
            elif inp["type"] == "list" and nt.exec_out_from and key == nt.exec_out_from[0]:
                if not val or len(val) > 6 or any(not isinstance(x, str) or not x.strip() for x in val) \
                        or len(set(val)) != len(val) or any(x in ("failed", "timeout") for x in val):
                    err(f"{label}: {key} needs 1-6 different, non-empty texts (not 'failed' or 'timeout')")
        for inp in nt.inputs:
            if not inp["required"] or wired.get((nid, inp["name"])):
                continue
            val = n["values"].get(inp["name"])
            if (val is None or val == "") and inp["default"] is None:
                err(f"{label}: {inp['name']} needs a value")
        _special(n, nt, catalog, err, g)
        if nt.exec_in and nid not in reached and nt.category != "start":
            warn(f"{label} is never reached (nothing runs into its exec input)")
    # ---- loops ----
    for what, edges in (("exec", exec_edges), ("data", data_edges)):
        loop = _cycle(edges)
        if loop:
            err(f"{what} wires loop back on themselves ({' -> '.join(loop)})"
                + ("; use For each to repeat" if what == "exec" else ""))
    return rep


def _special(n, nt, catalog, err, g) -> None:
    """Checks that need more than one input at once."""
    v, label = n["values"], _label(n, nt)
    if nt.kind == "becomes":
        field_ = v.get("field")
        if isinstance(field_, str) and field_ and field_ not in catalog.reads:
            err(f"{label}: no state field {field_!r}; fields are {', '.join(sorted(catalog.reads)) or 'none'}")
    elif nt.kind == "read_state":
        field_ = v.get("field")
        adapter = nt.meta.get("adapter")
        if isinstance(field_, str) and f"{adapter}.{field_}" not in catalog.reads:
            err(f"{label}: no state field {field_!r}")
    elif nt.kind == "at":
        days = v.get("days")
        if days is not None and V.parse_days(days) is None:
            err(f"{label}: days should be like [\"mon\",\"fri\"] or weekdays")
    elif nt.kind == "day_is" and v.get("days") is not None and V.parse_days(v["days"]) is None:
        err(f"{label}: days should be like [\"mon\",\"fri\"] or weekdays")
    elif nt.kind == "run_flow":
        target = v.get("flow")
        if isinstance(target, str) and target in (g.get("id"), g.get("name")) and target:
            err(f"{label}: a flow can't call itself")


def _cycle(edges: dict[str, list[str]]) -> list[str] | None:
    state: dict[str, int] = {}
    stack: list[str] = []

    def dfs(u):
        state[u] = 1
        stack.append(u)
        for w in edges.get(u, ()):
            if state.get(w) == 1:
                return stack[stack.index(w):] + [w]
            if state.get(w) is None:
                found = dfs(w)
                if found:
                    return found
        stack.pop()
        state[u] = 2
        return None

    for u in list(edges):
        if state.get(u) is None:
            found = dfs(u)
            if found:
                return found
    return None


# ------------------------------------------------------------------ compiled

class Compiled:
    """A validated graph indexed for running: who follows which exec pin, who feeds which input."""

    def __init__(self, graph: dict, catalog: Catalog) -> None:
        self.graph = graph
        self.nodes = {n["id"]: n for n in graph["nodes"]}
        self.types = {i: catalog.get(n["type"]) for i, n in self.nodes.items()}
        self.next: dict[tuple, list[str]] = {}        # (node, exec pin) -> target node ids, in link order
        self.feed: dict[tuple, tuple] = {}            # (node, input) -> (source node, output pin)
        for ln in graph["links"]:
            if not ln["from"] or not ln["to"]:
                continue
            (fn, fp), (tn, tp) = ln["from"], ln["to"]
            fnt = self.types.get(fn)
            if fnt is None or tn not in self.nodes:
                continue
            if fp in fnt.exec_out_names(self.nodes[fn]["values"]):
                self.next.setdefault((fn, fp), []).append(tn)
            else:
                self.feed[(tn, tp)] = (fn, fp)
        self.starts = [i for i, nt in self.types.items() if nt and nt.category == "start"]

    def uses_ai(self) -> bool:
        return any(nt and nt.kind in ("ask_aries", "decide") for nt in self.types.values())

    def manual(self) -> bool:
        return any(nt and nt.kind == "run_button" for nt in self.types.values())


# -------------------------------------------------------------------- safety

@dataclass
class Safety:
    consent_nodes: list = field(default_factory=list)       # node ids that speak for him
    outside_nodes: list = field(default_factory=list)       # starts / reads fed by outside content
    violations: list = field(default_factory=list)          # reachable consent verbs with no Ask Ronald between

    def needs_approval(self, made_by: str) -> bool:
        return made_by == "aries" and bool(self.consent_nodes or self.outside_nodes)


def safety(graph: dict, catalog: Catalog) -> Safety:
    """DESIGN §10 Safety: what the flow can do that needs his eye.

    A flow whose start is outside content (a page, a DM) taints every path
    from it; so does reading page text mid-run. A tainted path may not reach a
    consent verb (or call another flow, which could) unless an Ask Ronald
    answered with a "yes"-type option on the way.
    """
    c = Compiled(graph, catalog)
    out = Safety()
    for nid, nt in c.types.items():
        if nt is None:
            continue
        if nt.consent:
            out.consent_nodes.append(nid)
        if nt.outside_content:
            out.outside_nodes.append(nid)
    seen: set = set()

    def walk(nid: str, tainted: bool, asked: bool, start: str) -> None:
        key = (nid, tainted, asked)
        if key in seen:
            return
        seen.add(key)
        nt = c.types.get(nid)
        if nt is None:
            return
        if (nt.consent or nt.kind == "run_flow") and tainted and not asked:
            what = ("spend his Claude usage" if nt.consent == "spend" else "send a message") \
                if nt.consent else "call another flow"
            out.violations.append(f"{_label(c.nodes[nid], nt)} could {what} from outside content "
                                  f"({c.nodes[start]['type']}); put an Ask Ronald before it and wire it "
                                  f"from his yes option")
        if nt.outside_content:
            tainted = True
        for pin in nt.exec_out_names(c.nodes[nid]["values"]):
            now_asked = asked or (nt.kind == "ask_ronald" and is_affirmative(pin))
            for target in c.next.get((nid, pin), ()):
                walk(target, tainted, now_asked, start)

    for s in c.starts:
        nt = c.types[s]
        for pin in nt.exec_out_names(None):
            for target in c.next.get((s, pin), ()):
                walk(target, nt.outside_content, False, s)
    return out


# ------------------------------------------------------------------- summary

def _lit(nt: NodeType, name: str, val) -> str:
    inp = nt.input(name)
    typ = inp["type"] if inp else "any"
    if typ == "duration":
        d = V.parse_duration(val)
        return V.fmt_duration(d) if d is not None else V.text_of(val)
    if typ == "text" and isinstance(val, str):
        return V.clip(val, 40)
    return V.clip(val, 40)


class _Fmt(dict):
    def __missing__(self, key):
        return "?"


def summary(graph: dict, catalog: Catalog, limit: int = 240) -> str:
    """One line written from the graph itself, so it is always true to what the flow does."""
    c = Compiled(graph, catalog)
    seen: set[str] = set()

    def val(nid: str, name: str, depth: int = 0) -> str:
        nt, node = c.types[nid], c.nodes[nid]
        src = c.feed.get((nid, name))
        if src and src[0] in c.nodes and c.types.get(src[0]):
            sn, snt = c.nodes[src[0]], c.types[src[0]]
            if snt.category == "start" or snt.exec_in or depth >= 3:
                return f"‹{src[1]}›"
            return phrase(src[0], depth + 1)
        v = node["values"].get(name)
        if v is None:
            inp = nt.input(name)
            v = inp["default"] if inp else None
        return "?" if v is None else _lit(nt, name, v)

    def phrase(nid: str, depth: int = 0) -> str:
        nt, node = c.types[nid], c.nodes[nid]
        if nt.kind == "at":
            days = V.parse_days(node["values"].get("days") or [])
            tail = f" on {', '.join(days)}" if days and len(days) < 7 else ""
            return f"At {val(nid, 'time')}{tail}"
        if nt.kind == "becomes":
            hold = V.parse_duration(node["values"].get("hold") or 0)
            op = node["values"].get("op") or "is"
            return (f"When {val(nid, 'field')} {'becomes' if op == 'is' else op} {val(nid, 'value')}"
                    + (f" for {V.fmt_duration(hold)}" if hold else ""))
        if nt.kind == "verb":
            args = [val(nid, i["name"], depth) for i in nt.inputs
                    if (nid, i["name"]) in c.feed or node["values"].get(i["name"]) is not None]
            return " ".join([nt.phrase] + args)
        if nt.kind in ("ask_aries", "decide"):
            extra = [i for i in c.feed if i[0] == nid and i[1] != "sentence"]
            return nt.phrase.format_map(_Fmt(sentence=val(nid, "sentence", depth))) + (
                " (with " + ", ".join(f"‹{c.feed[k][1]}›" for k in extra) + ")" if extra else "")
        if nt.kind == "read_state":
            return f"{c.types[nid].meta.get('adapter', '').capitalize()} {val(nid, 'field')}"
        slots = _Fmt({i["name"]: val(nid, i["name"], depth) for i in nt.inputs})
        return nt.phrase.format_map(slots) if nt.phrase else nt.title

    def chain(nid: str, pin: str) -> str:
        targets = c.next.get((nid, pin), [])
        return " and ".join(x for x in (step(t) for t in targets) if x)

    def step(nid: str) -> str:
        nt = c.types.get(nid)
        if nt is None:
            return ""
        if nid in seen:
            return f"(back to {nt.title})"
        seen.add(nid)
        text = phrase(nid)
        outs = nt.exec_out_names(c.nodes[nid]["values"])
        if nt.kind in ("branch", "time_between", "day_is"):
            t, f = chain(nid, "true"), chain(nid, "false")
            text += f" → {t}" if t else ""
            text += f"{', otherwise' if t else ' → otherwise'} → {f}" if f else ""
        elif nt.kind == "sequence":
            parts = [x for x in (chain(nid, p) for p in outs) if x]
            text = ", then ".join(parts)
        elif nt.kind == "for_each":
            body, done = chain(nid, "body"), chain(nid, "done")
            text += f": {body}" if body else ""
            text += f" → {done}" if done else ""
        else:
            main = [p for p in outs if p in ("exec", "done")]
            for p in outs:
                nxt = chain(nid, p)
                if not nxt:
                    continue
                if p in main:
                    text += f" → {nxt}"
                elif p == "failed":
                    text += f" (if it fails: {nxt})"
                else:
                    text += f" ({p}: {nxt})"
        seen.discard(nid)
        return text

    starts = sorted(c.starts, key=lambda i: ((c.nodes[i]["pos"] or [0, 0])[0], i))
    lines = []
    for s in starts:
        head = phrase(s)
        tail = chain(s, "exec")
        lines.append(head + (f" → {tail}" if tail else " (nothing wired yet)"))
    text = "; ".join(lines) or "(no start node)"
    return text if len(text) <= limit else text[:limit - 1] + "…"


# -------------------------------------------------------------------- layout

def layout(graph: dict, catalog: Catalog) -> None:
    """Gives nodes without a position one, in columns by distance from a start (in place)."""
    c = Compiled(graph, catalog)
    depth: dict[str, int] = {s: 0 for s in c.starts}
    frontier = list(c.starts)
    while frontier:
        nid = frontier.pop(0)
        for (n, _pin), targets in c.next.items():
            if n != nid:
                continue
            for t in targets:
                if depth.get(t, -1) < depth[nid] + 1 and depth[nid] < 40:
                    depth[t] = depth[nid] + 1
                    frontier.append(t)
    for (tn, _), (sn, _) in c.feed.items():            # data nodes sit one column before what reads them
        if sn not in depth and tn in depth:
            depth[sn] = max(depth[tn] - 1, 0)
    rows: dict[int, int] = {}
    for node in graph["nodes"]:
        d = depth.get(node["id"], 0)
        row = rows.get(d, 0)
        rows[d] = row + 1
        if node.get("pos") is None:
            node["pos"] = [40 + d * 280, 40 + row * 130]
