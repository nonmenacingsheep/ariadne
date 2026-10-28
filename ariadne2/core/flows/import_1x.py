"""Import 1.x watch rules as flows (DESIGN §10, "1.x import").

    python3 -m ariadne2.core.flows.import_1x [--dry-run] [--watches PATH] [--root PATH]

Each rule becomes: its trigger as the start node, its sentence as an Ask Aries
node, which is exactly what it was. Time rules become At/Every (a one-shot
becomes After); player rules become a Spotify start. Kinds with no source in
2.0 yet (window, disk, folder, screen, package) are imported *disabled*, with
a note on the row saying what's missing. Recipes aren't imported.

Idempotent: a flow's id is derived from the 1.x rule's key (f_1x<key>), and an
existing file is never overwritten.
"""
from __future__ import annotations

import argparse
import collections
import datetime
import json
import os
import pathlib
import time
from dataclasses import dataclass, field

from . import graph as G
from . import values as V
from .catalog import Catalog
from .store import FlowStore

# kind -> (start type, input name for the rule's field, rule field)
_PLANNED = {"window": "desktop.window_opened", "disk": "system.disk_low",
            "folder": "dolphin.file_appeared", "screen": "screen.sees", "package": "system.package_update"}


def watches_path() -> pathlib.Path:
    base = os.environ.get("XDG_DATA_HOME") or (pathlib.Path.home() / ".local" / "share")
    return pathlib.Path(base) / "ariadne" / "watches.json"


@dataclass
class Plan:
    key: str
    kind: str
    flow: dict | None = None
    enabled: bool = True
    note: str | None = None
    skipped: str | None = None            # why nothing is created


@dataclass
class Summary:
    plans: list = field(default_factory=list)

    def count(self, pred) -> int:
        return sum(1 for p in self.plans if pred(p))

    @property
    def by_kind(self) -> dict:
        out: dict = collections.OrderedDict()
        for p in self.plans:
            d = out.setdefault(p.kind, {"enabled": 0, "disabled": 0, "skipped": 0})
            d["skipped" if p.skipped else "enabled" if p.enabled else "disabled"] += 1
        return out


def _start_for(kind: str, rule: dict, now: float, catalog: Catalog) -> tuple[str, dict, str | None] | None:
    """(start type, values, note when it can't run yet) for a 1.x rule, or None if unreadable."""
    if kind == "time":
        due, repeat = float(rule.get("due") or 0), float(rule.get("repeat") or 0)
        if repeat == 86400:
            return "time.at", {"time": datetime.datetime.fromtimestamp(due).strftime("%H:%M")}, None
        if repeat > 0:
            return "time.every", {"interval": int(repeat)}, None
        return "time.after", {"delay": int(max(due - now, 60))}, None
    if kind == "player":
        ev = "spotify.playing" if rule.get("on") == "starts" else "spotify.paused"
        if ev in catalog:
            return ev, {}, None
        return None
    planned = _PLANNED.get(kind)
    if planned is None:
        return None
    values = {"window": {"match": rule.get("match") or ""},
              "disk": {"below_gb": float(rule.get("below_gb") or 0)},
              "folder": {"path": rule.get("path") or "~/Downloads"},
              "screen": {"thing": rule.get("looking_for") or ""},
              "package": {"package": rule.get("package") or ""}}[kind]
    if kind == "window" and rule.get("on") == "closes":
        planned = "desktop.window_closed"
    nt = catalog.get(planned)
    return planned, values, f"waiting for a source: {nt.note}" if nt else "waiting for a source"


def convert(key: str, rule: dict, catalog: Catalog, now: float) -> Plan:
    kind = str(rule.get("kind") or "?")
    plan = Plan(key, kind)
    found = _start_for(kind, rule, now, catalog) if isinstance(rule, dict) else None
    if found is None:
        plan.skipped = f"don't know how to import a {kind!r} rule"
        return plan
    start, values, note = found
    sentence = str(rule.get("what") or rule.get("why") or "").strip()
    if not sentence:
        plan.skipped = "the rule has no sentence"
        return plan
    name = V.clip(rule.get("why") or sentence, 60)
    plan.enabled, plan.note = note is None, note
    plan.flow = {"id": f"f_1x{key}", "name": name, "enabled": plan.enabled, "made_by": "ronald",
                 "approved": True, "mode": "ignore",
                 "nodes": [{"id": "n1", "type": start, "values": values, "pos": [40, 40]},
                           {"id": "n2", "type": "her.ask_aries", "values": {"sentence": sentence},
                            "pos": [320, 40]}],
                 "links": [{"from": ["n1", "exec"], "to": ["n2", "exec"]}]}
    rep = G.validate(plan.flow, catalog)
    if rep.errors:
        plan.flow, plan.skipped = None, "; ".join(rep.errors)
    return plan


def run_import(watches: pathlib.Path, store: FlowStore, catalog: Catalog, dry_run: bool = False,
               now: float | None = None, out=print) -> Summary:
    now = now if now is not None else time.time()
    try:
        rules = json.loads(watches.read_text("utf-8"))
        rules = rules if isinstance(rules, dict) else {}
    except (OSError, ValueError) as e:
        out(f"can't read {watches}: {e}")
        return Summary()
    summary = Summary()
    for key in sorted(rules, key=lambda k: (len(k), k)):
        plan = convert(key, rules[key], catalog, now)
        summary.plans.append(plan)
        if plan.skipped:
            out(f"skip  1.x rule {key} [{plan.kind}]: {plan.skipped}")
            continue
        fid = plan.flow["id"]
        if store.load(fid) is not None:
            plan.skipped = "already imported"
            out(f"skip  {fid} [{plan.kind}]: already imported")
            continue
        state = "on" if plan.enabled else f"OFF ({plan.note})"
        out(f"{'would create' if dry_run else 'create'}  {fid} {plan.flow['name']!r} [{plan.kind}] "
            f"{G.summary(G.normalize(plan.flow), catalog)}  -> {state}")
        if not dry_run:
            store.save(plan.flow, now)
            if plan.note:
                store.set_note(fid, plan.note)
    made = [p for p in summary.plans if not p.skipped]
    out(f"{'would create' if dry_run else 'created'} {len(made)} flows "
        f"({sum(p.enabled for p in made)} on, {sum(not p.enabled for p in made)} off), "
        f"skipped {len(summary.plans) - len(made)}")
    for kind, d in summary.by_kind.items():
        out(f"  {kind}: {d['enabled']} on, {d['disabled']} off, {d['skipped']} skipped")
    return summary


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="ariadne2.core.flows.import_1x")
    ap.add_argument("--dry-run", action="store_true", help="print what would be created; write nothing")
    ap.add_argument("--watches", type=pathlib.Path, default=None, help="1.x watches.json")
    ap.add_argument("--root", default=None, help="2.0 data folder (default ~/.local/share/ariadne2)")
    args = ap.parse_args(argv)
    from ... import adapters as adapters_mod

    async def noop(_msg) -> None:
        return None

    catalog = Catalog.build(adapters_mod.load_adapters(noop))
    run_import(args.watches or watches_path(), FlowStore(args.root), catalog, args.dry_run)


if __name__ == "__main__":
    main()
