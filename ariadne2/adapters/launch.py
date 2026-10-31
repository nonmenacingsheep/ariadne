"""Starting his apps by name ("Spotify", "Steam", "Firefox").

The apps are the desktop's own launchers (.desktop files: system, Flatpak and
his own, as the Files menu finds them). From inside the toolbox they're
started on the host through host-spawn, so they open as if he'd clicked them.
"""
from __future__ import annotations

import asyncio
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from .base import AdapterError
from .dolphin import host_prefix
from .dolphin_menu import desktop_dirs


@dataclass
class Launcher:
    id: str               # 'com.spotify.Client.desktop'
    name: str             # 'Spotify'
    generic: str          # 'Music Player'
    keywords: str
    path: Path


def _fields(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    inside = False
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("["):
            if inside:
                break
            inside = line == "[Desktop Entry]"
            continue
        if inside and "=" in line and not line.startswith("#"):
            k, _, v = line.partition("=")
            out.setdefault(k.strip(), v.strip())
    return out


def launchers(dirs=None) -> dict[str, Launcher]:
    """id -> every app he could start from the menu. An earlier folder's copy of an id wins."""
    found: dict[str, Launcher | None] = {}
    for d in (dirs if dirs is not None else desktop_dirs()):
        d = Path(d)
        try:
            files = sorted(d.rglob("*.desktop"))
        except OSError:
            continue
        for f in files:
            app_id = f.relative_to(d).as_posix().replace("/", "-")
            if app_id in found:
                continue
            try:
                e = _fields(f.read_text("utf-8", "replace"))
            except OSError:
                continue
            visible = (e.get("Type", "Application") == "Application" and e.get("Name") and e.get("Exec")
                       and e.get("NoDisplay", "").lower() != "true" and e.get("Hidden", "").lower() != "true")
            found[app_id] = Launcher(app_id, e["Name"], e.get("GenericName", ""), e.get("Keywords", ""), f) if visible else None
    return {k: v for k, v in found.items() if v}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def find(name: str, apps: dict[str, Launcher] | None = None) -> list[Launcher]:
    """The best matches for a spoken name, best first: exact name, then a name
    starting with it, then a word of the name or the app id, then its kind
    (GenericName), then its keywords."""
    want = _norm(name)
    if not want:
        return []
    apps = launchers() if apps is None else apps
    tiers: list[list[Launcher]] = [[], [], [], [], [], []]
    for a in apps.values():
        n, ident = _norm(a.name), _norm(a.id.removesuffix(".desktop"))
        if n == want:
            tiers[0].append(a)
        elif n.startswith(want):
            tiers[1].append(a)
        elif want in n.split() or want in ident.split() or f" {want}" in f" {ident}":
            tiers[2].append(a)
        elif _norm(a.generic) == want:
            tiers[3].append(a)                       # "terminal" -> Konsole, whose kind is Terminal
        elif want in _norm(a.generic):
            tiers[4].append(a)
        elif want in _norm(a.keywords).split():
            tiers[5].append(a)
    for tier in tiers:
        if tier:
            return sorted(tier, key=lambda a: (len(a.name), a.name))
    return []


def _host_path(p: Path) -> str:
    """A launcher path as the host sees it (the toolbox mounts the host's at /run/host)."""
    s = str(p)
    return s[len("/run/host"):] if s.startswith("/run/host/") else s


async def start(app: Launcher) -> None:
    prefix = host_prefix()
    if prefix or shutil.which("gtk-launch"):
        argv = [*prefix, "gtk-launch", app.id.removesuffix(".desktop")]
    elif shutil.which("gio"):
        argv = ["gio", "launch", _host_path(app.path)]
    else:
        raise AdapterError("there's no gtk-launch or gio here to start apps with")
    try:
        proc = await asyncio.create_subprocess_exec(*argv, stdin=asyncio.subprocess.DEVNULL,
                                                    stdout=asyncio.subprocess.DEVNULL,
                                                    stderr=asyncio.subprocess.PIPE, start_new_session=True)
        _, err = await asyncio.wait_for(proc.communicate(), 15)
    except (OSError, asyncio.TimeoutError) as e:
        raise AdapterError(f"couldn't start {app.name}: {e}")
    if proc.returncode not in (0, None):
        raise AdapterError(f"{app.name} wouldn't start ({err.decode(errors='replace').strip()[-120:] or 'no reason given'})")


async def open_app(name: str) -> str:
    """Start an app by name; says which one, or which names to choose between."""
    matches = await asyncio.to_thread(find, name)
    if not matches:
        raise AdapterError(f"I can't find an app called {name!r} in his menu")
    best = matches[0]
    if len(matches) > 1 and _norm(best.name) != _norm(name):
        others = ", ".join(a.name for a in matches[1:5])
        await start(best)
        return f"Opened {best.name} (other matches: {others})."
    await start(best)
    return f"Opened {best.name}."
