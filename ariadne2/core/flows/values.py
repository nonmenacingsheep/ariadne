"""Flow value types: parsing, checking and writing out (DESIGN §10, "Types").

Types: text, number, yes/no, time, duration, path, list, plus "any" (generic
nodes) and whatever an adapter names (track, game, tab ...). Durations are
seconds; times are "HH:MM" strings.
"""
from __future__ import annotations

import json
import re

BASE_TYPES = ("text", "number", "yes/no", "time", "duration", "path", "list")

_DUR = re.compile(r"(\d+(?:\.\d+)?)\s*(d|h|m|s)", re.I)
_DUR_UNITS = {"d": 86400, "h": 3600, "m": 60, "s": 1}
_UNIT_WORDS = {"sec": "s", "second": "s", "min": "m", "minute": "m", "hour": "h", "hr": "h", "day": "d"}
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_FULL = dict(zip(DAYS, ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")))
_DAY_GROUPS = {"weekdays": DAYS[:5], "weekends": DAYS[5:], "daily": DAYS, "everyday": DAYS}


def parse_duration(v) -> float | None:
    """90, "90", "5m", "1h30m", "2 hours" -> seconds; None if it isn't one."""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v) if v >= 0 else None
    if not isinstance(v, str):
        return None
    s = v.strip().lower()
    for word, short in _UNIT_WORDS.items():           # "2 hours" -> "2 h"
        s = re.sub(rf"(?<=\d)\s*{word}s?\b", short, s)
    if re.fullmatch(r"\d+(?:\.\d+)?", s):
        return float(s)
    parts = _DUR.findall(s)
    if not parts or _DUR.sub("", s).strip():
        return None
    return float(sum(float(n) * _DUR_UNITS[u.lower()] for n, u in parts))


def fmt_duration(sec) -> str:
    sec = int(round(float(sec)))
    if sec <= 0:
        return "0s"
    out = []
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60), ("s", 1)):
        if sec >= size:
            out.append(f"{sec // size}{unit}")
            sec %= size
    return "".join(out)


def parse_time(v) -> tuple[int, int] | None:
    """"22:00", "7:05", "10pm", "6:30 am" -> (hour, minute)."""
    if not isinstance(v, str):
        return None
    m = re.fullmatch(r"\s*(\d{1,2})(?:[:.](\d{2}))?\s*(am|pm)?\s*", v.lower())
    if not m:
        return None
    h, mi, mer = int(m.group(1)), int(m.group(2) or 0), m.group(3)
    if mer is None and m.group(2) is None:
        return None                        # a bare "22" is a number, not a time
    if mer:
        if not 1 <= h <= 12:
            return None
        h = h % 12 + (12 if mer == "pm" else 0)
    return (h, mi) if h < 24 and mi < 60 else None


def fmt_time(hm: tuple[int, int]) -> str:
    return f"{hm[0]:02d}:{hm[1]:02d}"


def parse_days(v) -> list[str] | None:
    """["mon","Tuesday"], "weekdays", "mon,wed" -> ["mon", ...]; None if unreadable."""
    items = v if isinstance(v, list) else re.split(r"[,\s]+", v) if isinstance(v, str) else None
    if items is None:
        return None
    out: list[str] = []
    for item in items:
        word = str(item).strip().lower()
        if not word:
            continue
        if word in _DAY_GROUPS:
            out += list(_DAY_GROUPS[word])
        elif word[:3] in DAYS and word in (word[:3], _FULL[word[:3]], word[:3] + "s"):
            out.append(word[:3])
        else:
            return None
    return [d for d in DAYS if d in out]


def text_of(v) -> str:
    """Any value written out as text (any type goes into a text input)."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, float):
        return f"{v:g}"
    if isinstance(v, str):
        return v
    if isinstance(v, (list, tuple)):
        return ", ".join(text_of(x) for x in v)
    return json.dumps(v, ensure_ascii=False, separators=(",", ":"), default=str)


def type_ok(v, typ: str) -> bool:
    """Is this literal acceptable for an input of this type?"""
    if typ in ("any", "text", "path"):
        return isinstance(v, (str, int, float, bool)) or typ == "any"
    if typ == "number":
        return isinstance(v, (int, float)) and not isinstance(v, bool)
    if typ == "yes/no":
        return isinstance(v, bool)
    if typ == "time":
        return parse_time(v) is not None
    if typ == "duration":
        return parse_duration(v) is not None
    if typ == "list":
        return isinstance(v, list)
    return True                            # adapter-defined types: not checkable here


def compatible(src: str, dst: str) -> bool:
    """May a data wire run from an output of type src to an input of type dst?"""
    if dst in ("text", "any") or src == "any" or src == dst:
        return True
    return {src, dst} in ({"number", "duration"}, {"text", "path"}, {"text", "time"})


def clip(s, n: int = 60) -> str:
    s = " ".join(text_of(s).split())
    return s if len(s) <= n else s[:n - 1] + "…"


def loose_eq(a, b) -> bool:
    """Equality as a person means it: 3 = "3", "Running" = "running", yes = true."""
    if isinstance(a, bool) or isinstance(b, bool):
        return _yes(a) == _yes(b)
    try:
        return float(a) == float(b)
    except (TypeError, ValueError):
        return text_of(a).strip().lower() == text_of(b).strip().lower()


def _yes(v) -> bool:
    if isinstance(v, str):
        return v.strip().lower() in ("yes", "true", "on", "1")
    return bool(v)


def as_number(v) -> float | None:
    if isinstance(v, bool) or v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def as_bool(v) -> bool:
    return _yes(v)


def parse_dates(v) -> list | None:
    """Days of the month for At: [1, 15], "1, 15", ["last"]. None if one isn't a date."""
    if v in (None, "", []):
        return []
    items = v if isinstance(v, list) else re.split(r"[\s,]+", str(v).strip())
    out: list = []
    for x in items:
        t = str(x).strip().lower()
        if not t:
            continue
        if t in ("last", "end"):
            out.append("last")
        elif t.isdigit() and 1 <= int(t) <= 31:
            out.append(int(t))
        else:
            return None
    return out
