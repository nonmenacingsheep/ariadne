"""Flow storage (DESIGN §10): one readable JSON file per flow, plus a small
state file per flow beside them (last 50 runs, variables, timers, paused runs).

  <root>/flows/<id>.json        the flow, in the format the desk reads
  <root>/flow_state/<id>.json   engine-owned: runs, vars, paused runs, last result

They are separate so `flows/*.json` is only ever flows, and so the engine's
bookkeeping never shows up as a diff in a flow he edits.
"""
from __future__ import annotations

import datetime
import json
import logging
import os
import pathlib
import re

log = logging.getLogger("ariadne2.core.flows.store")

KEEP_RUNS = 50
_ID = re.compile(r"[A-Za-z0-9_\-]{1,40}")


def data_root() -> pathlib.Path:
    base = os.environ.get("XDG_DATA_HOME") or (pathlib.Path.home() / ".local" / "share")
    return pathlib.Path(base) / "ariadne2"


def iso(epoch: float) -> str:
    return datetime.datetime.fromtimestamp(epoch).astimezone().isoformat(timespec="seconds")


def _write(path: pathlib.Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str), "utf-8")
    os.replace(tmp, path)


class FlowStore:
    def __init__(self, root: str | os.PathLike | None = None) -> None:
        self.root = pathlib.Path(root) if root else data_root()
        self.flows_dir = self.root / "flows"
        self.state_dir = self.root / "flow_state"
        self._state: dict[str, dict] = {}

    # ---- flows ----

    def _path(self, flow_id: str) -> pathlib.Path:
        if not _ID.fullmatch(flow_id or ""):
            raise ValueError(f"bad flow id {flow_id!r}")
        return self.flows_dir / f"{flow_id}.json"

    def ids(self) -> list[str]:
        return sorted(p.stem for p in self.flows_dir.glob("*.json")) if self.flows_dir.is_dir() else []

    def load(self, flow_id: str) -> dict | None:
        try:
            data = json.loads(self._path(flow_id).read_text("utf-8"))
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    def load_all(self) -> dict[str, dict]:
        out = {}
        for fid in self.ids():
            flow = self.load(fid)
            if flow is None:
                log.warning("flow file %s.json is unreadable; skipped", fid)
            else:
                flow.setdefault("id", fid)
                out[fid] = flow
        return out

    def save(self, flow: dict, now: float) -> dict:
        """Write a flow; stamps created (first time) and updated."""
        old = self.load(flow["id"])
        flow = dict(flow)
        flow["created"] = (old or {}).get("created") or flow.get("created") or iso(now)
        flow["updated"] = iso(now)
        order = ("id", "name", "enabled", "made_by", "approved", "mode", "created", "updated", "nodes", "links")
        _write(self._path(flow["id"]), {k: flow[k] for k in order if k in flow})
        return flow

    def delete(self, flow_id: str) -> None:
        for p in (self._path(flow_id), self.state_dir / f"{flow_id}.json"):
            try:
                p.unlink()
            except FileNotFoundError:
                pass
        self._state.pop(flow_id, None)

    # ---- per-flow state ----

    def state(self, flow_id: str) -> dict:
        if flow_id not in self._state:
            try:
                data = json.loads((self.state_dir / f"{flow_id}.json").read_text("utf-8"))
            except (OSError, ValueError):
                data = {}
            data = data if isinstance(data, dict) else {}
            for key, empty in (("runs", []), ("vars", {}), ("paused", []), ("timers", {})):
                data.setdefault(key, empty)
            data.setdefault("last_fired", None)
            data.setdefault("last_result", None)
            data.setdefault("note", None)
            self._state[flow_id] = data
        return self._state[flow_id]

    def save_state(self, flow_id: str) -> None:
        _write(self.state_dir / f"{flow_id}.json", self.state(flow_id))

    def add_run(self, flow_id: str, record: dict) -> None:
        st = self.state(flow_id)
        st["runs"] = (st["runs"] + [record])[-KEEP_RUNS:]
        self.save_state(flow_id)

    def runs(self, flow_id: str) -> list[dict]:
        return list(self.state(flow_id)["runs"])

    def set_note(self, flow_id: str, note: str | None) -> None:
        self.state(flow_id)["note"] = note
        self.save_state(flow_id)

    def all_paused(self) -> list[tuple[str, dict]]:
        out = []
        for fid in self.ids():
            out += [(fid, r) for r in self.state(fid)["paused"]]
        return out
