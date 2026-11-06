import os

import gi

# Ubuntu's WebKitGTK turns its GPU path off whenever an NVIDIA driver is present
# (debian/patches/disable-nvidia-dmabuf), which leaves every page drawn on the
# CPU: hardware acceleration "never" in webkit://gpu, glass and animations at
# ~5x the CPU and laggy. Its own override turns the path back on; measured
# 120% -> 24% of a core on a glass stress page, the same pixels.
os.environ.setdefault("WEBKIT_FORCE_DMABUF_RENDERER", "1")
# Skia paints each tile 4x multisampled by default: the widgets' renderer held
# 1060 MB of the card, 433 MB without it, and he saw no difference in the glass.
os.environ.setdefault("WEBKIT_SKIA_MSAA_SAMPLE_COUNT", "0")

# Pinned once here so every desk module gets the GTK 4 stack.
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Gsk", "4.0")
gi.require_version("Graphene", "1.0")
