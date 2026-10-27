"""The desk: one transparent full-screen layer on the ultrawide.

The widgets themselves are a web page (web/desk.html) in a transparent
WebKit view: CSS does the slab look, the sheen and the crumbling edges far more
easily than hand-drawn GTK. This file is the glue. It forwards the core's
messages into the page, sends back what you did, saves the layout, keeps the
input region to the widgets, and owns raise/drop with KWin.
"""

from __future__ import annotations

import json
import os
import logging
from pathlib import Path

import cairo
import gi

gi.require_version("WebKit", "6.0")
from gi.repository import Gdk, Gio, Gtk, WebKit  # noqa: E402

from .. import protocol  # noqa: E402
from . import kwin, layout, theme  # noqa: E402
from .link import CoreLink  # noqa: E402

log = logging.getLogger(__name__)
PAGE = Path(os.environ.get("ARIADNE2_PAGE", Path(__file__).with_name("web") / "desk.html"))


class Layer(Gtk.Window):
    def __init__(self, app: Gtk.Application):
        super().__init__(application=app)
        self.set_title(theme.LAYER_TITLE)
        self.set_decorated(False)
        self.set_default_size(*layout.SCREEN)
        self.add_css_class("ariadne2-layer")
        self.raised = False
        self.ready = False
        self.area = (0, 0) + layout.SCREEN      # until KWin reports panels
        self.rects = layout.load()
        self.hit_rects: list = []

        ucm = WebKit.UserContentManager()
        ucm.register_script_message_handler("desk", None)
        ucm.connect("script-message-received::desk", self._from_page)
        self.view = WebKit.WebView(user_content_manager=ucm)
        transparent = Gdk.RGBA()
        transparent.parse("rgba(0,0,0,0)")
        self.view.set_background_color(transparent)
        settings = self.view.get_settings()
        settings.set_allow_file_access_from_file_urls(True)
        settings.set_enable_developer_extras(True)
        self.view.load_uri(PAGE.as_uri())
        self.set_child(self.view)

        self.link = CoreLink(self._on_message, self._on_status)
        self.connect("realize", lambda *_: self._update_input())
        self.connect("map", lambda *_: kwin.load_layer_script())

    # -- page <-> python --------------------------------------------------
    def _js(self, fn: str, *args) -> None:
        if not self.ready:
            return
        call = f"desk.{fn}({', '.join(json.dumps(a) for a in args)})"
        self.view.evaluate_javascript(call, -1, None, None, None, None, None)

    def _layout_args(self):
        return {n: list(r) for n, r in self.rects.items()}, list(self.area)

    def _from_page(self, _ucm, value) -> None:
        try:
            msg = json.loads(value.to_string())
        except (ValueError, AttributeError):
            return
        t = msg.get("t")
        if t == "ready":
            self.ready = True
            self._js("init", *self._layout_args())
            self.link.start()
        elif t == "send":
            self.link.send(msg["msg"])
        elif t == "layout":
            self.rects = {n: tuple(int(v) for v in r) for n, r in msg["widgets"].items()}
            layout.save(self.rects)
        elif t == "rects":
            self.hit_rects = msg["rects"]
            self._update_input()
        elif t == "drop":
            kwin.drop()

    def _on_message(self, msg: dict) -> None:
        self._js("message", msg)

    def _on_status(self, status: str) -> None:
        self._js("setStatus", status)

    # -- screen area, raise / drop -----------------------------------------
    def set_area(self, area: tuple) -> None:
        if area[2] < 400 or area[3] < 300 or area == self.area:
            return
        self.area = area
        self.rects = layout.fit(self.rects, area, scale=not layout.path().exists())
        self._js("layout", *self._layout_args())

    def set_raised(self, up: bool) -> None:
        self.raised = up
        self._update_input()
        if up:
            self.view.grab_focus()
        self._js("setRaised", up)

    def _update_input(self) -> None:
        surface = self.get_surface()
        if surface is None:
            return
        if self.raised:   # empty space catches the click that drops her
            w, h = layout.SCREEN
            region = cairo.Region(cairo.RectangleInt(0, 0, w, h))
        else:
            rects = self.hit_rects or [
                (x - 28, y - 28, w + 56, h + 56) for x, y, w, h in self.rects.values()]
            region = cairo.Region([cairo.RectangleInt(int(x), int(y), int(w), int(h))
                                   for x, y, w, h in rects])
        surface.set_input_region(region)


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
