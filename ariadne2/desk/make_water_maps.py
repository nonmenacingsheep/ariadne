"""Make the Liquid Glass water maps the desk uses (ariadne2/desk/web/water/).

    python ariadne2/desk/make_water_maps.py

caustic.png  one click's wave packet as light and shade: an uneven ring of wavelets, strongest at the
             front and decaying inward, each a soft lit crest beside a darker trough (desk.js `ripple`
             spreads it across the widget).
lens.png     displacement map of a small clear droplet: magnifies the middle, bends hard at the rim.
             Red/green carry the offset (0.5 = none), alpha its strength, so it can be drawn "over" a
             neutral grey (desk.js `glassOf`, an feDisplacementMap on the widget's face).

Needs numpy and Pillow. Deterministic (fixed seed), so re-running gives the same files.
"""
from pathlib import Path

import numpy as np
from PIL import Image

OUT = Path(__file__).resolve().parent / "web" / "water"


def _grid(n):
    y, x = np.mgrid[0:n, 0:n].astype(np.float64)
    x = (x + .5) / n * 2 - 1
    y = (y + .5) / n * 2 - 1
    return x, y, np.hypot(x, y), np.arctan2(y, x)


def wave_height(n, seed=7):
    """A packet of wavelets at the front of an uneven ring, decaying inward. r = 1 is the front."""
    x, y, r, th = _grid(n)
    rng = np.random.default_rng(seed)
    wobble = sum(np.sin(k * th + rng.uniform(0, 6.3)) * rng.uniform(.4, 1) / k for k in range(3, 11))
    rr = r / (1 + .045 * wobble)                                      # the ring isn't a perfect circle
    depth = np.clip(1 - rr, 0, None)
    lam = .1 + .04 * depth                                         # wavelets a little longer behind the front
    env = np.exp(-depth / .16) * np.clip((1 - rr) / .03, 0, 1)        # soft leading edge, decaying inward
    h = env * np.sin(2 * np.pi * depth / lam)
    h[rr >= 1] = 0
    return h


def caustic(n=512):
    """Light and shade of the wave itself: a soft lit crest beside a darker trough, several px wide."""
    h = wave_height(n)
    k = np.exp(-np.linspace(-2, 2, 9) ** 2)                           # soften: a few px either way
    k /= k.sum()
    for ax in (0, 1):
        h = np.apply_along_axis(lambda v: np.convolve(v, k, mode="same"), ax, h)
    light = np.clip(h, 0, None) / max(h.max(), 1e-9)
    shade = np.clip(-h, 0, None) / max(-h.min(), 1e-9)
    a_light, a_shade = light ** 1.2 * .5, shade ** 1.2 * .3
    a = a_light + a_shade * (1 - a_light)
    with np.errstate(invalid="ignore", divide="ignore"):
        w = np.nan_to_num(a_light / a)
    col = w[..., None] * np.array([.93, .97, 1.0])                   # cool, watery white over dark
    rgba = np.dstack([col, a])
    return Image.fromarray((np.clip(rgba, 0, 1) * 255 + .5).astype(np.uint8), "RGBA")


def lens(n=128):
    x, y, r, _ = _grid(n)
    rim = .8
    v = np.where(r < rim, -.55 * r / rim,                           # sample nearer the middle: magnify
                 np.where(r < 1, .9 * np.sin((r - rim) / (1 - rim) * np.pi), 0))   # bend hard at the rim
    with np.errstate(invalid="ignore", divide="ignore"):
        ux, uy = np.nan_to_num(x / r), np.nan_to_num(y / r)
    sign = np.sign(v)
    rgba = np.zeros((n, n, 4))
    rgba[..., 0] = .5 + .5 * ux * sign
    rgba[..., 1] = .5 + .5 * uy * sign
    rgba[..., 2] = .5
    rgba[..., 3] = np.abs(v)
    return Image.fromarray((np.clip(rgba, 0, 1) * 255 + .5).astype(np.uint8), "RGBA")


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    caustic().save(OUT / "caustic.png", optimize=True)
    lens().save(OUT / "lens.png", optimize=True)
    for f in ("caustic.png", "lens.png"):
        print(f, (OUT / f).stat().st_size, "bytes")
