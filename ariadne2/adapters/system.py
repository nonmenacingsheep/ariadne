"""The System adapter: CPU, memory, GPU and disks for the small system widget, read-only.

It took over the publishing the core server used to do (core/sysinfo.py still supplies the CPU and
memory numbers). Events: disk_low, once each time a disk drops under 10 GB or 5% free; cpu_hot, once
per stretch of 30 seconds above 90%.
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import time
from pathlib import Path

from ..core import sysinfo
from .base import Adapter, Verb

log = logging.getLogger("ariadne2.adapters.system")

PERIOD = 2.0                    # same rhythm the server used
GPU_EVERY = 2                   # nvidia-smi costs a process, so every other round
LOW_GB, LOW_PCT = 10.0, 5.0     # a disk is low under either
CLEAR_GB, CLEAR_PCT = 11.0, 5.5  # ...and counts as recovered above both (so it can't flap at the line)
HOT_PCT, HOT_CLEAR, HOT_SECONDS = 90.0, 80.0, 30.0
GIB = 1024 ** 3
MOUNTS = "/var/mnt"


def parse_gpu(text: str) -> tuple[float | None, float | None]:
    """(busy %, memory %) from `nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total
    --format=csv,noheader,nounits`; the first GPU. (None, None) for anything else."""
    for line in (text or "").splitlines():
        parts = [p.strip() for p in line.split(",")]
        try:
            util, used, total = float(parts[0]), float(parts[1]), float(parts[2])
        except (ValueError, IndexError):
            continue
        return round(util, 1), round(100.0 * used / total, 1) if total > 0 else None
    return None, None


async def read_gpu() -> tuple[float | None, float | None]:
    if not shutil.which("nvidia-smi"):
        return None, None
    try:
        proc = await asyncio.create_subprocess_exec(
            "nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total",
            "--format=csv,noheader,nounits", stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        out, _ = await asyncio.wait_for(proc.communicate(), 4)
    except (OSError, asyncio.TimeoutError):
        return None, None
    return parse_gpu(out.decode("utf-8", "replace")) if proc.returncode == 0 else (None, None)


def mount_label(path: str) -> str | None:
    """The filesystem label of the drive holding `path` (findmnt), or None."""
    if not shutil.which("findmnt"):
        return None
    import subprocess
    try:
        out = subprocess.run(["findmnt", "-n", "-o", "LABEL", "--target", path], capture_output=True,
                             text=True, timeout=3).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    return out.splitlines()[0].strip() if out else None


def disk_row(name: str, path: str) -> dict | None:
    """Usage the way df reports it: used / (used + available to him)."""
    try:
        st = os.statvfs(path)
    except OSError:
        return None
    used = (st.f_blocks - st.f_bfree) * st.f_frsize
    avail = st.f_bavail * st.f_frsize
    if used + avail <= 0:
        return None
    return {"name": name, "path": path, "used_pct": round(100.0 * used / (used + avail), 1),
            "free_gb": round(avail / GIB, 1)}


def scan_disks(home: str, mounts: str = MOUNTS, label=mount_label) -> list[dict]:
    """Home, then every separate drive mounted directly under /var/mnt (named by its label)."""
    rows, seen = [], set()
    row = disk_row("Home", home)
    if row:
        rows.append(row)
        seen.add(os.stat(home).st_dev)
    try:
        entries = sorted(os.scandir(mounts), key=lambda e: e.name)
    except OSError:
        entries = []
    for e in entries:
        if not e.is_dir() or not os.path.ismount(e.path):
            continue
        try:
            dev = os.stat(e.path).st_dev
        except OSError:
            continue
        if dev in seen:
            continue
        seen.add(dev)
        row = disk_row(label(e.path) or e.name.capitalize(), e.path)
        if row:
            rows.append(row)
    return rows


def is_low(row: dict) -> bool:
    return row["free_gb"] < LOW_GB or 100.0 - row["used_pct"] < LOW_PCT


def recovered(row: dict) -> bool:
    return row["free_gb"] >= CLEAR_GB and 100.0 - row["used_pct"] >= CLEAR_PCT


class SystemAdapter(Adapter):
    name = "system"
    events = ("disk_low", "cpu_hot")
    event_info = {"disk_low": {"phrase": "runs low on disk space (under 10 GB or 5% free)",
                               "fields": {"name": "text", "free_gb": "number"}},
                  "cpu_hot": {"phrase": "has the CPU above 90% for 30 seconds",
                              "fields": {"percent": "number"}}}
    state_fields = {"cpu": ("number", "cpu"), "memory": ("number", "mem"), "gpu": ("number", "gpu"),
                    "gpu_memory": ("number", "gpu_mem")}

    def __init__(self, publish, sampler=None, gpu=None, disks=None, home=None, mounts=MOUNTS) -> None:
        super().__init__(publish)
        self.sampler = sampler or sysinfo.Sampler()
        self._gpu = gpu or read_gpu
        home = home or os.path.expanduser("~")
        mounts = str(mounts)
        self._labels: dict[str, str | None] = {}

        def cached_label(path: str) -> str | None:
            if path not in self._labels:
                self._labels[path] = mount_label(path)
            return self._labels[path]

        self._disks = disks or (lambda: scan_disks(home, mounts, cached_label))
        self.mono = time.monotonic
        self._state: dict = dict(self.sampler.snapshot(), gpu=None, gpu_mem=None, disks=[])
        self._round = 0
        self._low: set[str] | None = None            # None until the first look, which announces nothing
        self._hot_since: float | None = None
        self._hot_fired = False
        self._main: asyncio.Task | None = None
        self.verbs = [Verb("report", "A one-paragraph read of the machine right now: CPU, memory, GPU and "
                           "how full each drive is. Read-only.", {}, self._report)]

    # ---- lifecycle ----

    async def start(self) -> None:
        self._main = asyncio.create_task(self._loop())
        await self.refresh()

    async def stop(self) -> None:
        if self._main:
            self._main.cancel()
            await asyncio.gather(self._main, return_exceptions=True)

    def state(self) -> dict:
        return self._state

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(PERIOD)
            try:
                await self.refresh()
            except Exception:
                log.exception("system refresh failed")

    async def refresh(self) -> None:
        old = self._state
        snap = self.sampler.snapshot()
        if self._round % GPU_EVERY == 0:
            util, mem = await self._gpu()
        else:
            util, mem = old.get("gpu"), old.get("gpu_mem")
        self._round += 1
        disks = await asyncio.to_thread(self._disks)
        new = dict(snap, gpu=util, gpu_mem=mem, disks=disks)
        self.observe(new, self.mono())
        if new != old or self._round == 1:
            self._state = new
            await self.publish_state()

    # ---- events ----

    def observe(self, sample: dict, now: float) -> None:
        """Look for crossings in one sample. `now` is a monotonic clock reading."""
        low = {d["name"] for d in sample.get("disks") or [] if is_low(d)}
        if self._low is not None:
            for d in sample.get("disks") or []:
                if d["name"] in low and d["name"] not in self._low:
                    self.emit("disk_low", name=d["name"], free_gb=d["free_gb"])
            # a disk that has recovered leaves the set; one still between the lines stays in it
            keep = {d["name"] for d in sample.get("disks") or [] if d["name"] in self._low and not recovered(d)}
            self._low = low | keep
        else:
            self._low = low
        cpu = sample.get("cpu")
        if cpu is None:
            return
        if cpu > HOT_PCT:
            if self._hot_since is None:
                self._hot_since = now
            if not self._hot_fired and now - self._hot_since >= HOT_SECONDS:
                self._hot_fired = True
                self.emit("cpu_hot", percent=cpu)
        else:
            self._hot_since = None
            if cpu < HOT_CLEAR:
                self._hot_fired = False

    # ---- verbs ----

    async def _report(self) -> str:
        s = self._state
        parts = [f"CPU {s['cpu']:.0f}%", f"memory {s['mem_used_gb']}/{s['mem_total_gb']} GB ({s['mem']:.0f}%)"]
        parts.append(f"GPU {s['gpu']:.0f}% (memory {s['gpu_mem']:.0f}%)" if s.get("gpu") is not None
                     else "no GPU reading")
        text = "; ".join(parts) + "."
        for d in s.get("disks") or []:
            text += f" {d['name']} is {d['used_pct']:.0f}% full with {d['free_gb']} GB free" \
                    + (" (low)." if is_low(d) else ".")
        return text
