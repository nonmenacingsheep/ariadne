"""CPU and memory numbers straight from /proc (no psutil: stdlib only)."""
from __future__ import annotations


def _cpu_times() -> tuple[int, int]:
    """(busy, total) jiffies from the aggregate cpu line."""
    with open("/proc/stat") as f:
        fields = [int(x) for x in f.readline().split()[1:]]
    idle = fields[3] + (fields[4] if len(fields) > 4 else 0)  # idle + iowait
    return sum(fields) - idle, sum(fields)


def read_meminfo() -> dict[str, float]:
    kb: dict[str, int] = {}
    with open("/proc/meminfo") as f:
        for row in f:
            key, _, rest = row.partition(":")
            if key in ("MemTotal", "MemAvailable"):
                kb[key] = int(rest.split()[0])
    total = kb["MemTotal"]
    used = total - kb["MemAvailable"]
    gb = 1024 * 1024
    return {
        "mem": round(100.0 * used / total, 1),
        "mem_used_gb": round(used / gb, 1),
        "mem_total_gb": round(total / gb, 1),
    }


class Sampler:
    """CPU percent is a delta between two reads, so we keep the last one."""

    def __init__(self) -> None:
        self._last = _cpu_times()

    def snapshot(self) -> dict:
        busy, total = _cpu_times()
        d_busy, d_total = busy - self._last[0], total - self._last[1]
        self._last = (busy, total)
        cpu = round(100.0 * d_busy / d_total, 1) if d_total > 0 else 0.0
        return {"cpu": cpu, **read_meminfo()}
