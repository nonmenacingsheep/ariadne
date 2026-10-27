"""Talking to KWin: the persistent layer script, and one-shot scripts.

KWin runs scripts on our behalf over D-Bus; that is the only way a Wayland
client gets placed, kept below, or given a global shortcut. The persistent
script (kwin_layer.js) calls back to the desk's own D-Bus name.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from gi.repository import Gio, GLib

log = logging.getLogger(__name__)

KWIN = "org.kde.KWin"
PLUGIN = "ariadne2-layer"
SCRIPT = Path(__file__).with_name("kwin_layer.js")

# The desk's callback object (see layer.py), named in kwin_layer.js too.
SERVICE = "io.ariadne2.desk"
PATH = "/io/ariadne2/desk"
IFACE_XML = """
<node><interface name='io.ariadne2.Layer'>
  <method name='Raised'><arg type='b' name='up' direction='in'/></method>
  <method name='Area'>
    <arg type='i' name='x' direction='in'/><arg type='i' name='y' direction='in'/>
    <arg type='i' name='w' direction='in'/><arg type='i' name='h' direction='in'/>
  </method>
</interface></node>
"""

_DROP_JS = """
var list = workspace.windowList();
for (var i = 0; i < list.length; i++) {
    var w = list[i];
    if (w.caption === "ariadne2-desk") {
        w.keepAbove = false; w.keepBelow = true;
        callDBus("io.ariadne2.desk", "/io/ariadne2/desk", "io.ariadne2.Layer",
                 "Raised", false);
    }
}
"""


def _bus():
    return Gio.bus_get_sync(Gio.BusType.SESSION, None)


def _call(bus, path, iface, method, args=None, reply=None):
    return bus.call_sync(KWIN, path, iface, method, args,
                         GLib.VariantType.new(reply) if reply else None,
                         Gio.DBusCallFlags.NONE, 5000, None)


def _load(path: Path, plugin: str) -> bool:
    bus = _bus()
    unload(plugin)   # a crashed desk can leave the old one loaded
    try:
        sid = _call(bus, "/Scripting", "org.kde.kwin.Scripting", "loadScript",
                    GLib.Variant("(ss)", (str(path), plugin)), "(i)").unpack()[0]
        if sid < 0:
            log.warning("KWin refused %s", plugin)
            return False
        _call(bus, f"/Scripting/Script{sid}", "org.kde.kwin.Script", "run")
        return True
    except GLib.Error as exc:
        log.warning("KWin script %s failed: %s", plugin, exc.message)
        return False


def unload(plugin: str = PLUGIN) -> None:
    try:
        _call(_bus(), "/Scripting", "org.kde.kwin.Scripting", "unloadScript",
              GLib.Variant("(s)", (plugin,)), "(b)")
    except GLib.Error:
        pass


def load_layer_script() -> bool:
    return _load(SCRIPT, PLUGIN)


def run_once(js: str, plugin: str = "ariadne2-once") -> bool:
    cache = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    path = cache / "ariadne2" / f"{plugin}.js"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(js, "utf-8")
    ok = _load(path, plugin)
    # One-shot scripts have done their work by the time run() returns.
    GLib.timeout_add(500, lambda: (unload(plugin), False)[1])
    return ok


def drop() -> bool:
    """Send the layer back behind the windows (Esc, click on empty space)."""
    return run_once(_DROP_JS, "ariadne2-drop")
