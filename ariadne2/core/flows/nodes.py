"""The nodes that only compute: checks that give yes/no, text, math, lists,
variables, state reads. Pure functions of their inputs and a small context,
so the engine can pull them on demand and tests need no adapters.

ctx needs: ctx.now (epoch seconds), ctx.vars (dict), ctx.read(adapter, field).
"""
from __future__ import annotations

import datetime
import re

from . import values as V

PURE_KINDS = ("compare", "and", "or", "not", "time_between", "day_is", "text", "math", "list",
              "get", "read_state")


def compare(a, op, b) -> bool:
    if op in ("=", "is"):
        return V.loose_eq(a, b)
    if op in ("≠", "is not"):
        return not V.loose_eq(a, b)
    if op in ("<", ">", "above", "below"):
        x, y = V.as_number(a), V.as_number(b)
        if x is None or y is None:
            return False
        return x < y if op in ("<", "below") else x > y
    if op == "contains":
        if isinstance(a, list):
            return any(V.loose_eq(x, b) for x in a)
        return V.text_of(b).lower() in V.text_of(a).lower()
    if op == "matches":
        try:
            return re.search(V.text_of(b)[:200], V.text_of(a), re.I) is not None
        except re.error:
            return False
    return False


def in_window(now: float, frm, to) -> bool:
    """now's clock time in [from, to), wrapping past midnight when from > to."""
    a, b = V.parse_time(frm), V.parse_time(to)
    if a is None or b is None:
        return False
    t = datetime.datetime.fromtimestamp(now)
    m, lo, hi = t.hour * 60 + t.minute, a[0] * 60 + a[1], b[0] * 60 + b[1]
    if lo == hi:
        return True
    return lo <= m < hi if lo < hi else (m >= lo or m < hi)


def day_is(now: float, days) -> bool:
    wanted = V.parse_days(days if days is not None else []) or []
    return V.DAYS[datetime.datetime.fromtimestamp(now).weekday()] in wanted


def _math(a, op, b):
    x, y = V.as_number(a), V.as_number(b)
    if x is None:
        return None
    y = 0.0 if y is None else y
    try:
        r = {"+": lambda: x + y, "-": lambda: x - y, "*": lambda: x * y,
             "/": lambda: x / y, "mod": lambda: x % y, "min": lambda: min(x, y),
             "max": lambda: max(x, y), "round": lambda: round(x, int(y))}[op]()
    except (KeyError, ZeroDivisionError):
        return None
    return int(r) if isinstance(r, float) and r.is_integer() and abs(r) < 1e15 else r


def _list(items, op, arg):
    items = items if isinstance(items, list) else [x for x in re.split(r"[\n,]", V.text_of(items)) if x.strip()]
    n = V.as_number(arg)
    if op == "first":
        return (items[0] if items else None), len(items)
    if op == "last":
        return (items[-1] if items else None), len(items)
    if op == "count":
        return len(items), len(items)
    if op == "join":
        return (V.text_of(arg) or ", ").join(V.text_of(x) for x in items), len(items)
    if op == "pick":                                   # 1-based, as people count
        i = int(n) - 1 if n is not None else -1
        return (items[i] if 0 <= i < len(items) else None), len(items)
    if op == "contains":
        return any(V.loose_eq(x, arg) for x in items), len(items)
    if op == "filter":
        kept = [x for x in items if V.text_of(arg).lower() in V.text_of(x).lower()]
        return kept, len(kept)
    return None, len(items)


def template(text: str, inputs: dict) -> str:
    return re.sub(r"\{(\w+)\}", lambda m: V.text_of(inputs[m.group(1)]) if m.group(1) in inputs else m.group(0),
                  V.text_of(text))


def compute(kind: str, nt, inputs: dict, ctx) -> dict:
    """Outputs of a pure node, by output pin name."""
    g = inputs.get
    if kind == "compare":
        return {"result": compare(g("a"), g("op") or "=", g("b"))}
    if kind == "and":
        return {"result": V.as_bool(g("a")) and V.as_bool(g("b"))}
    if kind == "or":
        return {"result": V.as_bool(g("a")) or V.as_bool(g("b"))}
    if kind == "not":
        return {"result": not V.as_bool(g("value"))}
    if kind == "time_between":
        return {"result": in_window(ctx.now, g("from"), g("to"))}
    if kind == "day_is":
        return {"result": day_is(ctx.now, g("days"))}
    if kind == "text":
        return {"text": template(g("template"), inputs)}
    if kind == "math":
        return {"result": _math(g("a"), g("op") or "+", g("b"))}
    if kind == "list":
        result, count = _list(g("list"), g("op") or "first", g("arg"))
        return {"result": result, "count": count}
    if kind == "get":
        name = V.text_of(g("name"))
        pool = getattr(ctx, "shared", None) if V.as_bool(g("shared")) else ctx.vars
        pool = pool if pool is not None else {}
        return {"value": pool[name] if name in pool else g("default")}
    if kind == "read_state":
        return {"value": ctx.read(nt.meta.get("adapter"), V.text_of(g("field")))}
    raise ValueError(f"{kind} isn't a pure node")
