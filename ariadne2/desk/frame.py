"""A widget's frame: chamfered red glass, a header, and what it shows.

The frame draws itself (GTK CSS can't cut corners) and flares when she acts
through its widget. Moving and resizing are handled by the layer, which owns
positions; the frame only says where its header and grip are.
"""

from __future__ import annotations

import random
import time

from gi.repository import Graphene, Gsk, Gtk, Pango

from . import theme

GRIP = 18   # bottom-right resize corner, px


def chamfer_path(w: float, h: float, cut: float = theme.CHAMFER):
    # Top-left and bottom-right cut, the other two square: one diagonal
    # through every frame reads as one family.
    b = Gsk.PathBuilder.new()
    b.move_to(cut, 0)
    b.line_to(w, 0)
    b.line_to(w, h - cut)
    b.line_to(w - cut, h)
    b.line_to(0, h)
    b.line_to(0, cut)
    b.close()
    return b.to_path()


def _line(x0, y0, x1, y1):
    b = Gsk.PathBuilder.new()
    b.move_to(x0, y0)
    b.line_to(x1, y1)
    return b.to_path()


class Frame(Gtk.Widget):
    def __init__(self, name: str, title: str):
        super().__init__()
        self.name = name
        self.set_layout_manager(Gtk.BinLayout.new())
        self._flare = (0.0, False)     # started, failed
        self._touch_until = 0.0

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_margin_start(14)
        box.set_margin_end(12)
        box.set_margin_top(4)
        box.set_margin_bottom(12)
        header = Gtk.Box(spacing=8)
        header.set_size_request(-1, theme.HEADER_H - 4)
        self.title = Gtk.Label(label=title.upper(), xalign=0)
        self.title.add_css_class("a2-header")
        self.title.set_hexpand(True)
        self.status = Gtk.Label(label="", xalign=1)
        self.status.add_css_class("a2-status")
        header.append(self.title)
        header.append(self.status)
        box.append(header)
        self.body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.body.set_vexpand(True)
        box.append(self.body)
        box.set_parent(self)
        self._box = box
        self.add_tick_callback(self._tick)

    # -- what it shows ----------------------------------------------------
    def set_state(self, data: dict) -> None:
        """Generic view: one line per field. Real widgets override this."""
        child = self.body.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self.body.remove(child)
            child = nxt
        for key, value in data.items():
            label = Gtk.Label(xalign=0)
            if key == "status":
                label.set_label(str(value))
                label.add_css_class("a2-dim")
            else:
                label.set_label(f"{key}  {value}")
            label.add_css_class("a2-body")
            label.set_ellipsize(Pango.EllipsizeMode.END)
            self.body.append(label)

    # -- her touch --------------------------------------------------------
    def flare(self, failed: bool = False) -> None:
        self._flare = (time.monotonic(), failed)
        self.queue_draw()

    def touched(self, control: str | None) -> None:
        """Show the control she used, cyan, for a moment."""
        if control:
            self.status.set_label(f"▸ {control}")
            self.status.add_css_class("a2-you")
            self._touch_until = time.monotonic() + 1.2

    def failed(self, note: str | None) -> None:
        self.status.remove_css_class("a2-you")
        self.status.set_label(f"✕ {note or 'failed'}")
        self._touch_until = time.monotonic() + 3.0

    def _tick(self, _w, _clock) -> bool:
        now = time.monotonic()
        if self._touch_until and now > self._touch_until:
            self._touch_until = 0.0
            self.status.set_label("")
            self.status.remove_css_class("a2-you")
        if now - self._flare[0] < theme.FLARE_MS / 1000 + 0.05:
            self.queue_draw()
        return True

    # -- drawing ----------------------------------------------------------
    def do_snapshot(self, snap: Gtk.Snapshot) -> None:
        w, h = self.get_width(), self.get_height()
        path = chamfer_path(w, h)
        since = time.monotonic() - self._flare[0]
        lift = max(0.0, 1 - since * 1000 / theme.FLARE_MS)
        if self._flare[1] and lift:   # failures flicker
            lift *= 1.0 if int(since * 14) % 2 else 0.3
        snap.append_fill(path, Gsk.FillRule.WINDING,
                         theme.rgba(theme.GLASS, theme.GLASS_ALPHA))
        # Glow: wide faint strokes under the hairline.
        for width, alpha in ((9, 0.05), (4, 0.10)):
            snap.append_stroke(path, Gsk.Stroke.new(width),
                               theme.rgba(theme.RED, alpha + 0.25 * lift))
        edge = theme.RED_HOT if lift else theme.RED
        snap.append_stroke(path, Gsk.Stroke.new(1),
                           theme.rgba(edge, theme.HAIRLINE_ALPHA + 0.6 * lift))
        # Header rule, with a brighter tick where the title starts.
        y = theme.HEADER_H + 0.5
        snap.append_stroke(_line(14, y, w - 12, y), Gsk.Stroke.new(1),
                           theme.rgba(theme.RED, 0.28))
        snap.append_stroke(_line(14, y, 46, y), Gsk.Stroke.new(2),
                           theme.rgba(theme.RED_HOT, 0.9))
        # Resize grip: three short diagonals in the cut corner.
        for k in (5, 9, 13):
            snap.append_stroke(_line(w - k - 6, h - 3, w - 3, h - k - 6),
                               Gsk.Stroke.new(1), theme.rgba(theme.RED, 0.35))
        self.snapshot_child(self._box, snap)


class SystemFrame(Frame):
    def set_state(self, data: dict) -> None:
        if "cpu" not in data:
            return super().set_state(data)
        rows = (f"CPU  {data['cpu']:5.1f} %",
                f"MEM  {data['mem']:5.1f} %   "
                f"{data.get('mem_used_gb', 0):.1f} / {data.get('mem_total_gb', 0):.1f} GB")
        child = self.body.get_first_child()
        if child is None:
            for _ in rows:
                label = Gtk.Label(xalign=0)
                label.add_css_class("a2-num")
                self.body.append(label)
            child = self.body.get_first_child()
        for text in rows:
            child.set_label(text)
            child = child.get_next_sibling()


class ChatFrame(Frame):
    """Step-1 chat: a scrolling list and an entry. Step 2 replaces it."""

    def __init__(self, name, title, on_send):
        super().__init__(name, title)
        self.on_send = on_send
        self.messages: dict[str, Gtk.Label] = {}
        self.list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.list.set_valign(Gtk.Align.END)
        self.scroll = Gtk.ScrolledWindow()
        self.scroll.add_css_class("a2-scroll")
        self.scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.scroll.set_vexpand(True)
        self.scroll.set_child(self.list)
        self.entry = Gtk.Entry(placeholder_text="talk to Aries")
        self.entry.add_css_class("a2-entry")
        self.entry.connect("activate", self._send)
        self.body.append(self.scroll)
        self.body.append(self.entry)

    def set_state(self, data: dict) -> None:
        pass   # history arrives as chat messages

    def _send(self, entry) -> None:
        text = entry.get_text().strip()
        if text and self.on_send(text):
            entry.set_text("")

    def chat(self, msg: dict) -> None:
        label = self.messages.get(msg["id"])
        if label is None:
            label = Gtk.Label(xalign=0, wrap=True)
            label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
            label.add_css_class("a2-body")
            if msg["role"] == "you":
                label.add_css_class("a2-you")
            self.messages[msg["id"]] = label
            self.list.append(label)
        label.set_label(label.get_label() + msg["delta"])
        adj = self.scroll.get_vadjustment()
        Gtk.Widget.add_tick_callback(
            self.scroll, lambda *_: (adj.set_value(adj.get_upper()), False)[1])


class CoreMark(Gtk.Widget):
    """Her glitch wordmark: white, with red and cyan misregistered copies."""

    def __init__(self):
        super().__init__()
        self.set_size_request(200, 52)
        self._twitch = 0.0
        self.add_tick_callback(lambda *_: (self.queue_draw() if
                               time.monotonic() - self._twitch < 0.4 else None, True)[1])

    def twitch(self) -> None:
        self._twitch = time.monotonic()

    def do_snapshot(self, snap: Gtk.Snapshot) -> None:
        layout = self.create_pango_layout("ARIES")
        layout.set_font_description(Pango.FontDescription.from_string("Rajdhani Bold 40"))
        jolt = time.monotonic() - self._twitch < 0.4
        def at(dx, dy, rgb, alpha):
            snap.save()
            snap.translate(Graphene.Point().init(dx, dy))
            snap.append_layout(layout, theme.rgba(rgb, alpha))
            snap.restore()
        j = (lambda: random.uniform(-4, 4)) if jolt else (lambda: 0.0)
        at(-2 + j(), 0, theme.RED, 0.85)
        at(2 + j(), 1, theme.CYAN, 0.55)
        at(0, 0, theme.WHITE, 1.0)
        if jolt:   # one torn slice
            snap.push_clip(_rect(0, 18 + random.uniform(0, 14), 220, 5))
            at(random.uniform(-10, 10), 0, theme.WHITE, 1.0)
            snap.pop()


def _rect(x, y, w, h):
    return Graphene.Rect().init(x, y, w, h)


class CoreFrame(Frame):
    def __init__(self, name, title):
        super().__init__(name, title)
        self.title.set_label("")
        row = Gtk.Box(spacing=18)
        self.mark = CoreMark()
        self.line = Gtk.Label(label="", xalign=0)
        self.line.add_css_class("a2-body")
        self.line.set_ellipsize(Pango.EllipsizeMode.END)
        self.line.set_hexpand(True)
        row.append(self.mark)
        row.append(self.line)
        self.body.append(row)

    def set_state(self, data: dict) -> None:
        pass

    def set_line(self, text: str) -> None:
        self.line.set_label(text)
