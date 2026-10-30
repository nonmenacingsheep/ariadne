"""Her Live2D body: a transparent window on the ultrawide with the model in it.

The other body choice to pet/ (Godot, VRM). Which one shows is the Avatar
setting `model`: "aries" is the 3D body, anything else names a folder in
web/models/ holding a Live2D model. This process idles (window hidden) while the
3D body is chosen, so switching in the Avatar widget is instant.

Like pet/, it only watches: it reads the core's broadcasts on the read-only
localhost port and forwards them to the page; nothing here can type to her.
The page reports the box around her body and only that box takes clicks;
everything else on the screen passes through to the desk and his windows.

    python3 -m ariadne2.pet2d
"""
from __future__ import annotations

import json
import logging
import os
import signal
import socket
import sys
import threading
import time
from pathlib import Path

import cairo
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("WebKit", "6.0")
from gi.repository import Gdk, GLib, Gtk, WebKit  # noqa: E402

log = logging.getLogger("ariadne2.pet2d")

TITLE = "ariadne2-pet-l2d"            # KWin's script matches the "ariadne2-pet" prefix
PORT = 47120
WEB = Path(__file__).with_name("web")
MODELS = WEB / "models"
CONFIG = Path.home() / ".config" / "ariadne2"
SCREEN = (3440, 1440)
CSS = "window.ariadne2-pet2d, window.ariadne2-pet2d > * { background: transparent; }"


def live2d_models() -> dict[str, str]:
    """name -> model3.json path, for every Live2D model folder in web/models/."""
    out = {}
    try:
        for d in sorted(MODELS.iterdir()):
            hit = next(iter(sorted(d.glob("*.model3.json"))), None) if d.is_dir() else None
            if hit:
                out[d.name] = str(hit)
    except OSError:
        pass
    return out


def wanted_model(settings: dict) -> str | None:
    """The Live2D model to show, or None while the 3D body (or no body) is chosen."""
    av = settings.get("avatar") if isinstance(settings.get("avatar"), dict) else {}
    desk = settings.get("desktop") if isinstance(settings.get("desktop"), dict) else {}
    name = str(av.get("model") or "aries")
    if not desk.get("body", True) or name == "aries":
        return None
    return name if name in live2d_models() else None


class PetWindow(Gtk.Window):
    def __init__(self, app):
        super().__init__(application=app)
        self.set_title(TITLE)
        self.set_decorated(False)
        self.set_default_size(*SCREEN)
        self.add_css_class("ariadne2-pet2d")
        self.ready = False
        self.model: str | None = None
        self.hit: list = []
        self.settings: dict = {}
        self.settings_mtime = 0.0
        self.layout_mtime = 0.0

        ctx = WebKit.WebContext.get_default()     # the host GPU driver, as the desk does
        for d in ("/run/host/usr/lib64", "/run/host/usr/share/egl", "/run/host/usr/share/glvnd",
                  str(Path.home() / ".local/lib/nvidia-host"), str(Path.home() / ".local/share/glvnd")):
            if Path(d).exists():
                ctx.add_path_to_sandbox(d, True)
        ucm = WebKit.UserContentManager()
        ucm.register_script_message_handler("pet", None)
        ucm.connect("script-message-received::pet", self._from_page)
        self.view = WebKit.WebView(user_content_manager=ucm)
        clear = Gdk.RGBA()
        clear.parse("rgba(0,0,0,0)")
        self.view.set_background_color(clear)
        s = self.view.get_settings()
        s.set_allow_file_access_from_file_urls(True)
        s.set_allow_universal_access_from_file_urls(True)    # the model's files, fetched from file://
        self.view.connect("load-changed", self._loaded)
        self.view.load_uri((WEB / "index.html").as_uri())
        self.set_child(self.view)
        self.connect("realize", lambda *_: self._update_input())
        self.connect("notify::default-width", lambda *_: self._size())
        self.connect("notify::default-height", lambda *_: self._size())
        GLib.timeout_add_seconds(2, self._poll_files)
        threading.Thread(target=self._listen, daemon=True, name="pet2d-core").start()

    # ---- page --------------------------------------------------------------
    def _js(self, fn: str, *args) -> None:
        if self.ready:
            call = f"pet.{fn}({', '.join(json.dumps(a) for a in args)})"
            self.view.evaluate_javascript(call, -1, None, None, None, None, None)

    def _loaded(self, _view, event) -> None:
        if event == WebKit.LoadEvent.FINISHED:
            self.ready = True
            self.settings_mtime = self.layout_mtime = 0.0
            self._poll_files()
            self._size()

    def _size(self) -> None:
        w, h = self.get_width(), self.get_height()
        if w > 0 and h > 0:
            self._js("screen", w, h)

    def _from_page(self, _ucm, value) -> None:
        try:
            msg = json.loads(value.to_string())
        except ValueError:
            return
        if msg.get("t") == "hit":
            self.hit = [r for r in msg.get("rects", []) if isinstance(r, list) and len(r) == 4]
            self._update_input()
        elif msg.get("t") == "log":
            log.warning("page: %s", msg.get("msg"))

    def _update_input(self) -> None:
        surface = self.get_surface()
        if surface is None:
            return
        rects = self.hit if self.model else []
        region = cairo.Region([cairo.RectangleInt(int(x), int(y), max(1, int(w)), max(1, int(h)))
                               for x, y, w, h in rects]) if rects else cairo.Region(cairo.RectangleInt(0, 0, 1, 1))
        surface.set_input_region(region)

    # ---- settings and the desk's layout -----------------------------------
    def _read(self, name: str, mtime: float):
        path = CONFIG / name
        try:
            m = path.stat().st_mtime
            if m == mtime:
                return None, mtime
            return json.loads(path.read_text()), m
        except (OSError, ValueError):
            return None, mtime

    def _poll_files(self) -> bool:
        data, self.settings_mtime = self._read("settings.json", self.settings_mtime)
        if isinstance(data, dict):
            self.settings = data
            self._js("settings", data.get("avatar") or {})
            self._apply()
        layout, self.layout_mtime = self._read("layout.json", self.layout_mtime)
        if isinstance(layout, dict):
            hidden, _ = self._read("hidden.json", 0.0)
            self._js("layout", layout, hidden if isinstance(hidden, list) else [])
        return True

    def _apply(self) -> None:
        want = wanted_model(self.settings)
        if want == self.model:
            return
        self.model = want
        if want:
            self._js("load", Path(live2d_models()[want]).as_uri())
            self.set_visible(True)
            self.present()
        else:
            self._js("unload")
            self.set_visible(False)       # nothing drawn, nothing to composite
        self._update_input()

    # ---- the core's broadcasts (read-only port) ----------------------------
    def _listen(self) -> None:
        while True:
            try:
                with socket.create_connection(("127.0.0.1", PORT), timeout=5) as sock:
                    sock.settimeout(None)
                    sock.sendall(json.dumps({"t": "hello", "v": 1, "side": "desk", "pid": os.getpid()}).encode() + b"\n")
                    buf = b""
                    while chunk := sock.recv(65536):
                        buf += chunk
                        *lines, buf = buf.split(b"\n")
                        for line in lines:
                            try:
                                msg = json.loads(line)
                            except ValueError:
                                continue
                            if isinstance(msg, dict) and msg.get("t") in ("voice", "speak", "ears", "action", "chat", "state"):
                                GLib.idle_add(self._forward, msg)
            except OSError:
                pass
            time.sleep(2)

    def _forward(self, msg: dict) -> bool:
        if self.model:
            if msg.get("t") == "state" and msg.get("widget") not in ("spotify",):
                return False
            self._js("message", msg)
        return False


class PetApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="io.ariadne2.pet2d")
        self.win = None
        self.connect("activate", self._activate)

    def _activate(self, _app):
        if self.win is None:
            provider = Gtk.CssProvider()
            provider.load_from_string(CSS)
            Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider,
                                                      Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
            self.win = PetWindow(self)
            self.hold()            # stays alive while hidden (the 3D body chosen)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s pet2d %(levelname)s %(name)s: %(message)s")
    app = PetApp()
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, app.quit)
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, app.quit)
    return app.run([])


if __name__ == "__main__":
    sys.exit(main())
