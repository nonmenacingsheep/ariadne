"""The wires from her core to each widget, and the packets that run on them.

Routing is plain geometry (no GTK) so it can be tested: each wire leaves the
core's bottom edge, drops to its own depth on a shared bus, runs across, and
enters its widget from the side facing the core (or the top, for widgets
under it). Depths and lanes are ordered so wires heading the same way never
cross each other. Corners are cut at 45°, like circuit traces.
"""

from __future__ import annotations

import math
import time

from gi.repository import Graphene, Gsk, Gtk

from . import theme

BUS_GAP = 18      # below the core before the first run across
BUS_STEP = 8      # between depths
LANE_GAP = 6      # from a widget's edge to its first lane
LANE_STEP = 5
CUT = 10          # 45° corner size
PACKET_LEN = 70

Rect = tuple  # (x, y, w, h)


def _entry(core: Rect, r: Rect) -> tuple[str, float, float]:
    """Which side of r the wire enters, and the point on it."""
    cx0, cx1 = core[0], core[0] + core[2]
    x, y, w, h = r
    if x >= cx1 + 1:
        return "left", x, y + h / 2
    if x + w <= cx0 - 1:
        return "right", x + w, y + h / 2
    if y >= core[1] + core[3]:
        return "top", x + w / 2, y
    return "bottom", x + w / 2, y + h


def route(core: Rect, targets: dict[str, Rect]) -> dict[str, list]:
    if not targets:
        return {}
    entries = {n: _entry(core, r) for n, r in targets.items()}

    # Exits are spread along the core's bottom edge in the order the wires
    # head off. Within one column the higher widget gets the shallower run
    # and the lane nearest the widget, so no run or stub cuts another's drop.
    def key(n):
        side, ex, ey = entries[n]
        return (ex, -ey if side == "left" else ey)

    order = sorted(targets, key=key)
    bottom = core[1] + core[3]
    exits = {n: core[0] + core[2] * (i + 1) / (len(order) + 1)
             for i, n in enumerate(order)}

    # Same heading: shallower depth for the wire whose exit is further along
    # that heading, so a deeper wire's drop never cuts a shallower run.
    left = sorted((n for n in order if entries[n][1] < exits[n]),
                  key=lambda n: exits[n])
    right = sorted((n for n in order if entries[n][1] >= exits[n]),
                   key=lambda n: -exits[n])
    depth, lane = {}, {}
    for group in (left, right):
        count: dict[tuple, int] = {}
        for i, n in enumerate(group):
            depth[n] = bottom + BUS_GAP + BUS_STEP * i
            side, ex, _ = entries[n]
            k = count.get((side, round(ex)), 0)
            count[(side, round(ex))] = k + 1
            off = LANE_GAP + LANE_STEP * k
            lane[n] = ex - off if side == "left" else ex + off

    out = {}
    for n in order:
        side, ex, ey = entries[n]
        sx, bus = exits[n], depth[n]
        pts = [(sx, bottom), (sx, bus)]
        if side in ("left", "right"):
            pts += [(lane[n], bus), (lane[n], ey), (ex, ey)]
        else:
            pts += [(ex, bus), (ex, ey)]
        out[n] = chamfer(_dedupe(pts))
    return out


def _dedupe(pts: list) -> list:
    clean = [pts[0]]
    for p in pts[1:]:
        if abs(p[0] - clean[-1][0]) > 0.5 or abs(p[1] - clean[-1][1]) > 0.5:
            clean.append(p)
    return clean


def chamfer(pts: list, cut: float = CUT) -> list:
    """Replace each right-angle corner with a 45° cut."""
    if len(pts) < 3:
        return list(pts)
    out = [pts[0]]
    for a, b, c in zip(pts, pts[1:], pts[2:]):
        la, lc = math.dist(a, b), math.dist(b, c)
        k = min(cut, la / 2, lc / 2)
        if k < 1:
            out.append(b)
            continue
        out.append((b[0] + (a[0] - b[0]) * k / la, b[1] + (a[1] - b[1]) * k / la))
        out.append((b[0] + (c[0] - b[0]) * k / lc, b[1] + (c[1] - b[1]) * k / lc))
    out.append(pts[-1])
    return out


def length(poly: list) -> float:
    return sum(math.dist(a, b) for a, b in zip(poly, poly[1:]))


def segment(poly: list, d0: float, d1: float) -> list:
    """The part of a polyline between two distances along it."""
    d0, d1 = max(0.0, d0), min(length(poly), d1)
    out, walked = [], 0.0
    for a, b in zip(poly, poly[1:]):
        seg = math.dist(a, b)
        if seg == 0:
            continue
        lo, hi = walked, walked + seg
        if hi >= d0 and lo <= d1:
            t0, t1 = max(0, (d0 - lo) / seg), min(1, (d1 - lo) / seg)
            p0 = (a[0] + (b[0] - a[0]) * t0, a[1] + (b[1] - a[1]) * t0)
            p1 = (a[0] + (b[0] - a[0]) * t1, a[1] + (b[1] - a[1]) * t1)
            if not out:
                out.append(p0)
            out.append(p1)
        walked = hi
    return out


def _path(poly: list):
    b = Gsk.PathBuilder.new()
    b.move_to(*poly[0])
    for p in poly[1:]:
        b.line_to(*p)
    return b.to_path()


class Wires(Gtk.Widget):
    """Draws every wire, full-screen, under the widgets."""

    def __init__(self):
        super().__init__()
        self.set_can_target(False)
        self.routes: dict[str, list] = {}
        self._paths: dict[str, object] = {}
        # name -> (started, direction "out"|"back", failed)
        self.packets: dict[str, tuple] = {}
        self._last_idle = 0.0
        self.add_tick_callback(self._tick)

    def set_routes(self, routes: dict[str, list]) -> None:
        self.routes = routes
        self._paths = {n: _path(p) for n, p in routes.items() if len(p) > 1}
        self.queue_draw()

    def send(self, name: str, direction: str, failed: bool = False) -> None:
        self.packets[name] = (time.monotonic(), direction, failed)
        self.queue_draw()

    def _tick(self, _w, _clock) -> bool:
        now = time.monotonic()
        if self.packets:
            self.queue_draw()
        elif now - self._last_idle > 0.1:   # the idle pulse is slow; 10 fps
            self._last_idle = now
            self.queue_draw()
        return True

    def do_snapshot(self, snap: Gtk.Snapshot) -> None:
        now = time.monotonic()
        pulse = 0.8 + 0.2 * math.sin(now * 0.9)
        under = Gsk.Stroke.new(theme.WIRE_WIDTH + 2)
        line = Gsk.Stroke.new(theme.WIRE_WIDTH)
        glow = Gsk.Stroke.new(5)
        shade = theme.rgba((0, 0, 0), 0.45)
        done = []
        for name, path in self._paths.items():
            snap.append_stroke(path, under, shade)
            packet = self.packets.get(name)
            alpha = theme.WIRE_IDLE_ALPHA * pulse
            if packet:
                alpha = 0.7
            snap.append_stroke(path, glow, theme.rgba(theme.RED, alpha * 0.18))
            snap.append_stroke(path, line, theme.rgba(theme.RED, alpha))
            if packet and not self._draw_packet(snap, name, packet, now):
                done.append(name)
        for name in done:
            self.packets.pop(name, None)

    def _draw_packet(self, snap, name, packet, now) -> bool:
        started, direction, failed = packet
        t = (now - started) * 1000 / theme.PACKET_MS
        if t >= 1.0:
            return False
        poly = self.routes[name]
        total = length(poly)
        head = total * (t if direction == "out" else 1 - t)
        if direction == "out":
            part = segment(poly, head - PACKET_LEN, head)
        else:
            part = segment(poly, head, head + PACKET_LEN)
        if len(part) < 2:
            return True
        if failed:   # a red flicker on the way back
            colour = theme.rgba(theme.RED_HOT, 1.0 if int(t * 12) % 2 else 0.25)
        elif direction == "out":
            colour = theme.rgba(theme.RED_HOT, 1.0)
        else:
            colour = theme.rgba(theme.WHITE, 0.9)
        path = _path(part)
        snap.append_stroke(path, Gsk.Stroke.new(7), theme.rgba(theme.RED_HOT, 0.25))
        snap.append_stroke(path, Gsk.Stroke.new(2.5), colour)
        return True
