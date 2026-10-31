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

from .beats import BeatListener  # noqa: E402

log = logging.getLogger("ariadne2.pet2d")

TITLE = "ariadne2-pet-l2d"            # KWin's script matches the "ariadne2-pet" prefix
PORT = 47120
WEB = Path(__file__).with_name("web")
MODELS = WEB / "models"
CONFIG = Path.home() / ".config" / "ariadne2"
SCREEN = (3440, 1440)
BODY_FILE = Path.home() / ".local" / "share" / "ariadne2" / "pet" / "body.json"
PIN_FILE = Path.home() / ".local" / "share" / "ariadne2" / "pet" / "pin2d.json"
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


def biggest_monitor() -> tuple[int, int]:
    """The size to start at: the biggest monitor (KWin then pins the window to it)."""
    best = SCREEN
    try:
        mons = Gdk.Display.get_default().get_monitors()
        sizes = [(m.get_geometry().width, m.get_geometry().height) for m in (mons.get_item(i) for i in range(mons.get_n_items()))]
        if sizes:
            best = max(sizes, key=lambda wh: wh[0] * wh[1])
    except Exception:
        pass
    return best


CORE = WEB / "vendor" / "live2dcubismcore.min.js"


def wanted_model(settings: dict) -> str | None:
    """The Live2D model to show, or None while the 3D body (or no body) is chosen."""
    av = settings.get("avatar") if isinstance(settings.get("avatar"), dict) else {}
    desk = settings.get("desktop") if isinstance(settings.get("desktop"), dict) else {}
    name = str(av.get("model") or "aries")
    if not desk.get("body", True) or name == "aries" or not CORE.exists():
        return None            # no Cubism Core yet: nothing could draw it (the core says so in the chat)
    return name if name in live2d_models() else None


class PetWindow(Gtk.Window):
    def __init__(self, app):
        super().__init__(application=app)
        self.set_title(TITLE)
        self.set_decorated(False)
        self.set_default_size(*biggest_monitor())
        self.add_css_class("ariadne2-pet2d")
        self.ready = False
        self.model: str | None = None
        self.hit: list = []
        self.settings: dict = {}
        self.settings_mtime = 0.0
        self.layout_mtime = 0.0
        self.music = False                         # Spotify is playing
        self._voice_latest = None                  # the newest voice level, waiting to go to the page
        self._voice_pending = False
        self.beats = BeatListener(lambda period, strength: GLib.idle_add(self._beat, period, strength))

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
        self.view.connect("context-menu", lambda *_: True)      # no Back/Reload menu on her
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
        elif msg.get("t") == "pin":
            try:
                PIN_FILE.parent.mkdir(parents=True, exist_ok=True)
                PIN_FILE.write_text(json.dumps({"x": float(msg["x"]), "y": float(msg["y"])}))
            except (OSError, KeyError, TypeError, ValueError):
                pass
        elif msg.get("t") == "state" and self.model:
            # What her body is doing, for her avatar tool (adapters/avatar.py).
            try:
                about = json.loads((MODELS / self.model / "about.json").read_text())
            except (OSError, ValueError):
                about = {}
            data = {k: msg.get(k) for k in ("x", "y", "w", "h", "mode", "on", "look", "dancing", "asleep", "own", "looks")}
            data.update(kind="live2d", model=about.get("name") or self.model, ts=time.time())
            try:
                BODY_FILE.parent.mkdir(parents=True, exist_ok=True)
                tmp = BODY_FILE.with_suffix(".tmp")
                tmp.write_text(json.dumps(data, ensure_ascii=False))
                tmp.replace(BODY_FILE)
            except OSError:
                pass
        elif msg.get("t") == "log":
            log.warning("page: %s", msg.get("msg"))
        elif msg.get("t") == "face":
            log.info("face %r on the body (for %r)", msg.get("look"), msg.get("emotion"))

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
        # Cubism Core arrived (Avatar > Live2D support > Download): the page
        # loaded without it, so load it again, then the chosen model.
        if CORE.exists() != getattr(self, "_had_core", CORE.exists()):
            self._had_core = True
            self.ready = False
            self.model = None
            self.view.reload()
            return True
        self._had_core = CORE.exists()
        data, self.settings_mtime = self._read("settings.json", self.settings_mtime)
        if isinstance(data, dict):
            self.settings = data
            self._js("settings", data.get("avatar") or {})
            self._apply()
            self._beats_wanted()
        layout, self.layout_mtime = self._read("layout.json", self.layout_mtime)
        if isinstance(layout, dict):
            hidden, _ = self._read("hidden.json", 0.0)
            # layout.json is {"version": 1, "widgets": {name: [x, y, w, h]}}; the
            # page wants the widgets (handed the whole file, she found no widget
            # to stand on and only ever used the floor).
            widgets = layout.get("widgets") if isinstance(layout.get("widgets"), dict) else layout
            self._js("layout", widgets, hidden if isinstance(hidden, list) else [])
        return True

    def _apply(self) -> None:
        want = wanted_model(self.settings)
        if want == self.model:
            return
        self.model = want
        if want:
            try:
                pin = json.loads(PIN_FILE.read_text())
                self._js("pinAt", float(pin["x"]), float(pin["y"]))
            except (OSError, ValueError, KeyError, TypeError):
                pass
            self._js("load", Path(live2d_models()[want]).as_uri())
            self.set_visible(True)
            self.present()
        else:
            self._js("unload")
            self.set_visible(False)       # nothing drawn, nothing to composite
        self._update_input()
        self._beats_wanted()

    # ---- dancing: listen for beats only while music plays and she shows -----
    def _beats_wanted(self) -> None:
        av = self.settings.get("avatar") if isinstance(self.settings.get("avatar"), dict) else {}
        if self.model and self.music and av.get("dance_to_music", True):
            self.beats.start()
        else:
            self.beats.stop()

    def _beat(self, period: float, strength: float) -> bool:
        self._js("beat", round(period, 3), round(strength, 2))
        return False

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
                            if not isinstance(msg, dict):
                                continue
                            if msg.get("t") == "voice":
                                # ~12 a second while she talks (lip sync). Queued one by one
                                # at idle priority behind the drawing, they backed up and her
                                # faces (the speak messages behind them) came seconds late or
                                # not at all. Only the newest level matters: keep that one.
                                self._voice_latest = msg
                                if not self._voice_pending:
                                    self._voice_pending = True
                                    GLib.idle_add(self._flush_voice, priority=GLib.PRIORITY_HIGH)
                            elif msg.get("t") == "chat" and not msg.get("done"):
                                continue        # every streamed fragment of her text: the body only needs the end
                            elif msg.get("t") in ("speak", "ears", "action", "chat", "state", "body"):
                                if msg.get("t") == "speak":
                                    log.info("speak %r arrived", msg.get("emotion"))
                                GLib.idle_add(self._forward, msg, priority=GLib.PRIORITY_HIGH)
            except OSError:
                pass
            time.sleep(2)

    def _flush_voice(self) -> bool:
        self._voice_pending = False
        msg, self._voice_latest = self._voice_latest, None
        if msg is not None:
            self._forward(msg)
        return False

    def _forward(self, msg: dict) -> bool:
        if msg.get("t") == "state":
            if msg.get("widget") != "spotify" or not isinstance(msg.get("data"), dict):
                return False
            playing = msg["data"].get("status") == "playing"
            if playing != self.music:
                self.music = playing
                self._beats_wanted()
            msg = {"t": "state", "widget": "spotify", "data": {"status": msg["data"].get("status")}}
        if self.model:
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
