"""The Claude widget's body: claude.ai itself, in a browser view laid over it.

claude.ai can't be put in a frame inside the desk page (it forbids that), so
it gets its own WebKit view, positioned exactly over the widget's body as an
overlay on the desk window. Its sign-in lives in its own storage under
~/.local/share/ariadne2/claude-web, apart from the desk page. Sign-in popups
(Google and the like) open as small windows of their own.
"""

from __future__ import annotations

import logging
from pathlib import Path

import gi

gi.require_version("WebKit", "6.0")
from gi.repository import Gtk, WebKit  # noqa: E402

log = logging.getLogger(__name__)
HOME_URL = "https://claude.ai/"
DATA = Path.home() / ".local/share/ariadne2/claude-web"


class ClaudePane:
    def __init__(self, overlay: Gtk.Overlay):
        DATA.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.session = WebKit.NetworkSession.new(str(DATA / "data"), str(DATA / "cache"))
        self.view = WebKit.WebView(network_session=self.session)
        self.view.set_halign(Gtk.Align.START)
        self.view.set_valign(Gtk.Align.START)
        self.view.set_visible(False)
        self.view.connect("create", self._popup)
        overlay.add_overlay(self.view)
        self.loaded = False

    def place(self, rect) -> None:
        """rect = [x, y, w, h] of the widget's body, or None to hide it."""
        if not rect:
            self.view.set_visible(False)
            return
        x, y, w, h = (int(v) for v in rect)
        self.view.set_margin_start(max(0, x))
        self.view.set_margin_top(max(0, y))
        self.view.set_size_request(max(50, w), max(50, h))
        if not self.loaded:              # only load claude.ai once the widget is on the desk
            self.loaded = True
            self.view.load_uri(HOME_URL)
        self.view.set_visible(True)

    def _popup(self, view, action):
        # Sign-in flows open a popup; give it a real little window.
        win = Gtk.Window(title="Sign in")
        win.set_default_size(520, 680)
        child = WebKit.WebView(related_view=view)
        child.connect("close", lambda *_: win.destroy())
        win.set_child(child)
        child.connect("ready-to-show", lambda *_: win.present())
        return child
