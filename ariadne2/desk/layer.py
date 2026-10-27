"""The desk: one transparent full-screen layer on the ultrawide.

It holds no logic. It draws what the core sends (state, actions, chat), sends
back what you did, and owns only the things that are purely visual: where
widgets sit, the wires between them, and whether the layer is raised.
"""

from __future__ import annotations

import logging

import cairo
from gi.repository import Gdk, Gio, Gtk

from .. import protocol
from . import frame, kwin, layout, theme, wires
from .link import CoreLink

log = logging.getLogger(__name__)

TITLES = {"chat": "Chat", "core": "Aries", "spotify": "Spotify",
          "steam": "Steam", "discord": "Discord", "browser": "Browser",
          "dolphin": "Dolphin", "claude": "Claude", "system": "System",
          "flows": "Flows"}
HALO = 10   # input region margin around each widget, so the glow is grabbable


class Layer(Gtk.Window):
    def __init__(self, app: Gtk.Application):
        super().__init__(application=app)
        self.set_title(theme.LAYER_TITLE)
        self.set_decorated(False)
        self.set_default_size(*layout.SCREEN)
        self.add_css_class("ariadne2-layer")
        self.raised = False
        self.area = (0, 0) + layout.SCREEN   # until KWin reports panels

        self.rects = layout.load()
        self.frames: dict[str, frame.Frame] = {}
        self.wires = wires.Wires()
        self.fixed = Gtk.Fixed()
        overlay = Gtk.Overlay()
        overlay.set_child(self.wires)
        overlay.add_overlay(self.fixed)
        self.set_child(overlay)

        for name in protocol.WIDGETS:
            self._add_frame(name)
        self._reroute()

        self.link = CoreLink(self._on_message, self._on_status)
        self._drag = None
        drag = Gtk.GestureDrag()
        drag.connect("drag-begin", self._drag_begin)
        drag.connect("drag-update", self._drag_update)
        drag.connect("drag-end", self._drag_end)
        self.fixed.add_controller(drag)
        click = Gtk.GestureClick()
        click.connect("pressed", self._clicked)
        self.fixed.add_controller(click)
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._key)
        self.add_controller(keys)

        self.connect("realize", lambda *_: self._update_input())
        self.connect("map", lambda *_: kwin.load_layer_script())
        self.link.start()

    # -- widgets ----------------------------------------------------------
    def _add_frame(self, name: str) -> None:
        if name == "chat":
            f = frame.ChatFrame(name, TITLES[name], self._send_chat)
        elif name == "core":
            f = frame.CoreFrame(name, TITLES[name])
        elif name == "system":
            f = frame.SystemFrame(name, TITLES[name])
        else:
            f = frame.Frame(name, TITLES[name])
        x, y, w, h = self.rects[name]
        f.set_size_request(w, h)
        self.fixed.put(f, x, y)
        self.frames[name] = f

    def _send_chat(self, text: str) -> bool:
        return self.link.send(protocol.text("chat", text))

    def _reroute(self) -> None:
        core = self.rects["core"]
        others = {n: r for n, r in self.rects.items() if n != "core"}
        self.wires.set_routes(wires.route(core, others))

    def _place(self, name: str, rect: tuple) -> None:
        self.rects[name] = rect
        f = self.frames[name]
        self.fixed.move(f, rect[0], rect[1])
        f.set_size_request(rect[2], rect[3])

    # -- the core ---------------------------------------------------------
    def _on_message(self, msg: dict) -> None:
        t = msg["t"]
        core: frame.CoreFrame = self.frames["core"]
        if t == "state":
            self.frames[msg["widget"]].set_state(msg["data"])
        elif t == "line":
            core.set_line(msg["text"])
        elif t == "chat":
            self.frames["chat"].chat(msg)
        elif t == "action":
            self._action(msg)

    def _action(self, msg: dict) -> None:
        name, phase = msg["widget"], msg["phase"]
        f = self.frames.get(name)
        if f is None or name == "core":
            return
        if phase == "started":
            self.wires.send(name, "out")
            self.frames["core"].mark.twitch()
            f.flare()
            f.touched(msg.get("control"))
        elif phase in ("done", "failed"):
            failed = phase == "failed"
            self.wires.send(name, "back", failed)
            if failed:
                f.flare(failed=True)
                f.failed(msg.get("note"))

    def _on_status(self, status: str) -> None:
        core = self.frames["core"]
        core.status.set_label("" if status == "connected" else "RECONNECTING")
        if status != "connected":
            core.set_line("")

    def set_area(self, area: tuple) -> None:
        if area[2] < 400 or area[3] < 300 or area == self.area:
            return
        self.area = area
        fitted = layout.fit(self.rects, area, scale=not layout.path().exists())
        for name, rect in fitted.items():
            self._place(name, rect)
        self._reroute()
        self._update_input()

    # -- raise / drop -----------------------------------------------------
    def set_raised(self, up: bool) -> None:
        self.raised = up
        self._update_input()
        if up:
            self.frames["core"].mark.twitch()
            self.frames["chat"].entry.grab_focus()

    def _update_input(self) -> None:
        surface = self.get_surface()
        if surface is None:
            return
        if self.raised:   # empty space catches the click that drops her
            w, h = layout.SCREEN
            region = cairo.Region(cairo.RectangleInt(0, 0, w, h))
        else:
            region = cairo.Region([
                cairo.RectangleInt(int(x - HALO), int(y - HALO),
                                   int(w + 2 * HALO), int(h + 2 * HALO))
                for x, y, w, h in self.rects.values()])
        surface.set_input_region(region)

    def _hit(self, x: float, y: float) -> str | None:
        for name, (rx, ry, rw, rh) in self.rects.items():
            if rx - HALO <= x <= rx + rw + HALO and ry - HALO <= y <= ry + rh + HALO:
                return name
        return None

    def _clicked(self, _g, _n, x, y) -> None:
        if self.raised and self._hit(x, y) is None:
            kwin.drop()

    def _key(self, _c, keyval, _code, _state) -> bool:
        if keyval == Gdk.KEY_Escape and self.raised:
            kwin.drop()
            return True
        return False

    # -- move / resize ----------------------------------------------------
    def _drag_begin(self, gesture, x, y) -> None:
        name = self._hit(x, y)
        if name is None:
            gesture.set_state(Gtk.EventSequenceState.DENIED)
            return
        rx, ry, rw, rh = self.rects[name]
        if x >= rx + rw - frame.GRIP and y >= ry + rh - frame.GRIP:
            mode = "size"
        elif y <= ry + theme.HEADER_H:
            mode = "move"
        else:
            gesture.set_state(Gtk.EventSequenceState.DENIED)
            return
        gesture.set_state(Gtk.EventSequenceState.CLAIMED)
        self._drag = (name, mode, self.rects[name])

    def _drag_rect(self, dx, dy) -> tuple:
        name, mode, (x, y, w, h) = self._drag
        if mode == "move":
            return (x + dx, y + dy, w, h)
        return (x, y, w + dx, h + dy)

    def _drag_update(self, _g, dx, dy) -> None:
        if self._drag:
            self._place(self._drag[0], self._fit_one(self._drag_rect(dx, dy)))
            self._reroute()

    def _fit_one(self, rect: tuple) -> tuple:
        return layout.fit({"r": rect}, self.area)["r"]

    def _drag_end(self, _g, dx, dy) -> None:
        if not self._drag:
            return
        name, mode, _ = self._drag
        x, y, w, h = self._drag_rect(dx, dy)
        if mode == "move":
            x, y = layout.snap(x), layout.snap(y)
        else:
            w, h = layout.snap(x + w) - x, layout.snap(y + h) - y
        self._place(name, self._fit_one((x, y, w, h)))
        self._drag = None
        self._reroute()
        self._update_input()
        layout.save(self.rects)


class DeskApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=kwin.SERVICE,
                         flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.layer: Layer | None = None
        self.connect("activate", self._activate)
        self.connect("shutdown", lambda *_: kwin.unload())

    def do_startup(self):
        Gtk.Application.do_startup(self)
        theme.install_css()
        node = Gio.DBusNodeInfo.new_for_xml(kwin.IFACE_XML)
        self.get_dbus_connection().register_object(
            kwin.PATH, node.interfaces[0], self._dbus_call, None, None)

    def _dbus_call(self, _conn, _sender, _path, _iface, method, params, invocation):
        if method == "Raised" and self.layer:
            self.layer.set_raised(bool(params.unpack()[0]))
        elif method == "Area" and self.layer:
            self.layer.set_area(tuple(params.unpack()))
        invocation.return_value(None)

    def _activate(self, _app) -> None:
        if self.layer is None:
            self.layer = Layer(self)
        self.layer.present()
