"""Colours, type and the one stylesheet for the desk.

Everything visual that more than one file needs lives here, so a recolour is
one edit. Values come from DESIGN.md §2 (red cyberpunk, cyan only as the rare
highlight).
"""

from __future__ import annotations

import gi

gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, Gtk  # noqa: E402

LAYER_TITLE = "ariadne2-desk"     # the KWin script finds the layer by this
OUTPUT = "DP-2"                    # the ultrawide

RED = (1.0, 0x2A / 255, 0x3D / 255)          # #ff2a3d structure, live state
RED_HOT = (1.0, 0x4D / 255, 0x5E / 255)      # #ff4d5e something active
CYAN = (0.0, 0xE5 / 255, 1.0)                # #00e5ff the control she touched
GLASS = (0x2A / 255, 0x0A / 255, 0x0E / 255)  # #2a0a0e widget body
WHITE = (0.96, 0.92, 0.93)

GLASS_ALPHA = 0.80     # more opaque than the mock: the wallpaper moves
HAIRLINE_ALPHA = 0.35
CHAMFER = 14           # cut corners, px
HEADER_H = 30

WIRE_IDLE_ALPHA = 0.28
WIRE_WIDTH = 1.5
PACKET_MS = 450        # core to widget, and back
FLARE_MS = 700


def rgba(rgb: tuple, alpha: float = 1.0) -> Gdk.RGBA:
    c = Gdk.RGBA()
    c.red, c.green, c.blue, c.alpha = rgb[0], rgb[1], rgb[2], alpha
    return c


CSS = """
window.ariadne2-layer, window.ariadne2-layer > * { background: transparent; }

.a2-header {
  font-family: Rajdhani, sans-serif; font-weight: 600; font-size: 15px;
  letter-spacing: 2px; color: #ff4d5e;
  text-shadow: 0 1px 2px rgba(0,0,0,0.85);
}
.a2-body {
  font-family: "Noto Sans", Cantarell, sans-serif; font-size: 13px;
  color: #f5ebed; text-shadow: 0 1px 2px rgba(0,0,0,0.85);
}
.a2-dim { color: rgba(245,235,237,0.55); }
.a2-num {
  font-family: "Fira Code", "Noto Sans Mono", monospace; font-size: 13px;
  color: #f5ebed; text-shadow: 0 1px 2px rgba(0,0,0,0.85);
}
.a2-you { color: #00e5ff; }
.a2-status {
  font-family: "Fira Code", "Noto Sans Mono", monospace; font-size: 12px;
  color: #ff4d5e;
}

entry.a2-entry {
  background: rgba(11,7,8,0.75); color: #f5ebed;
  border: 1px solid rgba(255,42,61,0.45); border-radius: 0;
  box-shadow: none; min-height: 30px; padding: 0 8px;
  font-family: "Noto Sans", Cantarell, sans-serif; font-size: 13px;
  caret-color: #00e5ff;
}
entry.a2-entry:focus-within { border-color: #00e5ff; }
scrolledwindow.a2-scroll, scrolledwindow.a2-scroll > viewport { background: transparent; }
"""


def install_css() -> None:
    provider = Gtk.CssProvider()
    provider.load_from_string(CSS)
    Gtk.StyleContext.add_provider_for_display(
        Gdk.Display.get_default(), provider,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
