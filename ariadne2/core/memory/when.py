"""Dates in memory: parsing, "3 weeks ago", and "3 Oct" (DESIGN §6: everything recalled keeps its date)."""
from __future__ import annotations

import datetime
import time


def to_date(x=None) -> datetime.date:
    """A date from a date, datetime, timestamp, 'YYYY-MM-DD' string, or None (today)."""
    if x is None:
        return datetime.date.today()
    if isinstance(x, datetime.datetime):
        return x.date()
    if isinstance(x, datetime.date):
        return x
    if isinstance(x, (int, float)):
        return datetime.datetime.fromtimestamp(float(x)).date()
    return datetime.date.fromisoformat(str(x)[:10])


def now_ts(now=None) -> float:
    """A timestamp from the same kinds of values (None means the clock)."""
    if now is None:
        return time.time()
    if isinstance(now, (int, float)):
        return float(now)
    if isinstance(now, datetime.datetime):
        return now.timestamp()
    return datetime.datetime.combine(to_date(now), datetime.time(12)).timestamp()


def days_between(then, now=None) -> int:
    return (to_date(now) - to_date(then)).days


def ago(then, now=None) -> str:
    d = days_between(then, now)
    if d <= 0:
        return "today"
    if d == 1:
        return "yesterday"
    if d < 14:
        return f"{d} days ago"
    if d < 60:
        return f"{d // 7} weeks ago"
    if d < 365:
        n = round(d / 30.4)
        return f"{n} months ago"
    years = d // 365
    return "over a year ago" if years == 1 else f"{years} years ago"


def short(then, now=None) -> str:
    """'3 Oct', with the year when it isn't this one."""
    t, n = to_date(then), to_date(now)
    text = f"{t.day} {t.strftime('%b')}"
    return text if t.year == n.year else f"{text} {t.year}"
