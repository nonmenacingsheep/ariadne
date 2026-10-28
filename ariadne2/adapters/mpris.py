"""Spotify's MPRIS player over D-Bus, kept off the asyncio loop.

1.x reaches the bus through Gio (PyGObject), no playerctl and no dbus-python;
so does this. Signals arrive on a private GLib main loop in its own thread and
only poke the asyncio side through `on_change`; calls are plain blocking Gio
calls that the adapter runs with asyncio.to_thread. `gi` is imported lazily so
the module loads, and everything degrades to "not running", where there is no bus.
"""
from __future__ import annotations

import logging
import threading

log = logging.getLogger("ariadne2.adapters.mpris")

NAME = "org.mpris.MediaPlayer2.spotify"
PATH = "/org/mpris/MediaPlayer2"
PLAYER = "org.mpris.MediaPlayer2.Player"
PROPS = "org.freedesktop.DBus.Properties"
TIMEOUT_MS = 3000


class MprisError(Exception):
    pass


class Mpris:
    def __init__(self) -> None:
        self._bus = None
        self._Gio = None
        self._GLib = None
        self._loop = None
        self._thread: threading.Thread | None = None

    # ---- lifecycle ----

    def start(self, on_change) -> None:
        """Connect and listen. `on_change()` is called from the GLib thread."""
        try:
            from gi.repository import Gio, GLib
        except Exception as e:
            raise MprisError("the GObject bindings aren't available here") from e
        self._Gio, self._GLib = Gio, GLib
        ready = threading.Event()
        failure: list[Exception] = []

        def run() -> None:
            # A signal is delivered to the context that is thread-default when
            # it is subscribed, so build the whole subscription inside this thread.
            ctx = GLib.MainContext.new()
            ctx.push_thread_default()
            try:
                self._bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
                cb = lambda *_a: on_change()          # noqa: E731
                flags = Gio.DBusSignalFlags.NONE
                self._bus.signal_subscribe(None, PROPS, "PropertiesChanged", PATH, PLAYER,
                                           flags, cb)
                self._bus.signal_subscribe(None, PLAYER, "Seeked", PATH, None, flags, cb)
                self._bus.signal_subscribe("org.freedesktop.DBus", "org.freedesktop.DBus",
                                           "NameOwnerChanged", "/org/freedesktop/DBus",
                                           NAME, flags, cb)
            except Exception as e:
                failure.append(e)
                ready.set()
                return
            self._loop = GLib.MainLoop(ctx)
            ready.set()
            self._loop.run()

        self._thread = threading.Thread(target=run, name="mpris-glib", daemon=True)
        self._thread.start()
        ready.wait(5)
        if failure or self._bus is None:
            raise MprisError(f"couldn't reach the session bus ({failure[0] if failure else 'timeout'})")

    def stop(self) -> None:
        if self._loop:
            self._loop.quit()
        if self._thread:
            self._thread.join(2)

    # ---- blocking calls (run these in a thread) ----

    def _call(self, iface: str, method: str, args=None, reply: str | None = None,
              name: str = NAME, path: str = PATH):
        if self._bus is None:
            raise MprisError("no session bus")
        GLib = self._GLib
        return self._bus.call_sync(
            name, path, iface, method, args,
            GLib.VariantType.new(reply) if reply else None,
            self._Gio.DBusCallFlags.NONE, TIMEOUT_MS, None)

    def snapshot(self) -> dict:
        """What Spotify's player says right now; {"running": False} if it isn't there."""
        GLib = self._GLib
        try:
            props = self._call(PROPS, "GetAll", GLib.Variant("(s)", (PLAYER,)),
                               "(a{sv})").unpack()[0]
        except Exception as e:
            if "ServiceUnknown" in str(e) or "NameHasNoOwner" in str(e) or "not provided" in str(e):
                return {"running": False}
            raise MprisError(str(e)) from e
        return {"running": True,
                "status": props.get("PlaybackStatus", "Stopped"),
                "metadata": props.get("Metadata") or {},
                "position_us": props.get("Position", 0),
                "volume": props.get("Volume", 0.0)}

    def command(self, method: str) -> None:
        """Play, Pause, Next, Previous."""
        try:
            self._call(PLAYER, method)
        except Exception as e:
            raise MprisError(f"Spotify wouldn't {method.lower()} ({e})") from e

    def set_volume(self, level: float) -> None:
        GLib = self._GLib
        try:
            self._call(PROPS, "Set", GLib.Variant("(ssv)", (PLAYER, "Volume",
                                                            GLib.Variant("d", float(level)))))
        except Exception as e:
            raise MprisError(f"Spotify wouldn't change volume ({e})") from e

    def set_position(self, track_id: str, seconds: float) -> None:
        GLib = self._GLib
        try:
            self._call(PLAYER, "SetPosition",
                       GLib.Variant("(ox)", (track_id, int(seconds * 1_000_000))))
        except Exception as e:
            raise MprisError(f"Spotify wouldn't seek ({e})") from e
