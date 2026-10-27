"""Where each widget sits on the desk. Pure Python so it can be tested without GTK."""
from __future__ import annotations

import json
import logging
import os
import pathlib
import tempfile

log = logging.getLogger("ariadne2.desk.layout")

SCREEN = (3440, 1440)
GRID = 24
MIN_SIZE = (192, 96)

# (x, y, w, h)
DEFAULT = {
    "chat": (24, 24, 736, 912), "claude": (24, 960, 736, 456),
    "core": (1440, 24, 560, 144),
    "spotify": (2680, 24, 736, 336), "discord": (2680, 384, 736, 288),
    "steam": (2680, 696, 736, 360), "browser": (2680, 1080, 736, 336),
    "dolphin": (784, 1176, 912, 240), "flows": (1720, 1176, 584, 240),
    "system": (2328, 1176, 328, 240),
}


def path() -> pathlib.Path:
    override = os.environ.get("ARIADNE2_LAYOUT")
    if override:
        return pathlib.Path(override)
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return pathlib.Path(base) / "ariadne2" / "layout.json"


def snap(v: float) -> int:
    return int(round(v / GRID)) * GRID


def clamp(rect, screen=SCREEN) -> tuple:
    x, y, w, h = (int(round(v)) for v in rect)
    sw, sh = screen
    w = min(max(w, MIN_SIZE[0]), sw)
    h = min(max(h, MIN_SIZE[1]), sh)
    x = min(max(x, 0), sw - w)
    y = min(max(y, 0), sh - h)
    return (x, y, w, h)


def _valid(entry) -> bool:
    # bool is an int subclass; reject it so true/false can't pass as a coordinate
    return (isinstance(entry, (list, tuple)) and len(entry) == 4
            and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in entry))


def load() -> dict[str, tuple]:
    layout = dict(DEFAULT)
    try:
        data = json.loads(path().read_text())
        saved = data["widgets"]
        if not isinstance(saved, dict):
            raise ValueError("widgets is not an object")
    except FileNotFoundError:
        return layout
    except Exception as e:
        log.warning("layout file unusable, using defaults: %s", e)
        return layout
    for name, entry in saved.items():
        if name in DEFAULT and _valid(entry):
            layout[name] = clamp(entry)
    return layout


def save(layout: dict) -> None:
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": 1,
               "widgets": {n: [int(v) for v in r] for n, r in layout.items() if n in DEFAULT}}
    # temp file in the same dir so os.replace is atomic (no half-written layout on a crash)
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".layout-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(payload, f, indent=1)
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def reset() -> dict[str, tuple]:
    try:
        path().unlink()
    except FileNotFoundError:
        pass
    return dict(DEFAULT)


def fit(rects: dict, area: tuple, scale: bool = False) -> dict:
    """Keep every rect inside the usable area (the screen minus panels).

    With scale, the rects are first squeezed proportionally into the area:
    used for the starting layout, so its gutters survive a panel.
    """
    ax, ay, aw, ah = area
    sx, sy = (aw / SCREEN[0], ah / SCREEN[1]) if scale else (1.0, 1.0)
    out = {}
    for name, (x, y, w, h) in rects.items():
        if scale:
            x, y, w, h = round(x * sx), round(y * sy), round(w * sx), round(h * sy)
        else:
            x, y = x - ax, y - ay
        x, y, w, h = clamp((x, y, w, h), (aw, ah))
        out[name] = (x + ax, y + ay, w, h)
    return out
