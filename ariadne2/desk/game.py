"""Is the window in front a game? KWin says which process owns a fullscreen
window (kwin_layer.js); a game is one whose process, or something that started
it, is a Steam launch, Proton or Wine, gamescope, a Windows .exe, or another
game launcher's. A fullscreen video, browser or editor isn't, so she stays.

While one is in front she drops to her core alone (layer.py, pet/pet.gd and
bin/ariadne2): the widgets close their renderer, her body closes, and she
still hears "Hey Aries" and answers by voice.
"""
from __future__ import annotations

import os
from pathlib import Path

# Words in a process's command line (or any of its parents') that mean a game.
MARKERS = ("steamlaunch", "proton", "wine", "gamescope", "steam_app",
           "lutris", "heroic", "legendary", "umu-run", "appid=")
DEPTH = 16                      # parents looked at, at most


def flag_path() -> Path:
    """Present while a game is in front: bin/ariadne2 waits on it to bring her body back."""
    return Path(os.environ.get("XDG_RUNTIME_DIR") or "/tmp") / "ariadne2-game"


def _proc(pid: int, root: str) -> tuple[int, list[str]] | None:
    """(parent pid, command line) or None."""
    try:
        raw = Path(root, str(pid), "cmdline").read_bytes()
        stat = Path(root, str(pid), "stat").read_text()
    except OSError:
        return None
    try:
        ppid = int(stat.rsplit(")", 1)[1].split()[1])
    except (IndexError, ValueError):
        ppid = 0
    return ppid, [a for a in raw.decode("utf-8", "replace").split("\0") if a]


def is_game(pid: int, root: str = "/proc") -> bool:
    seen: set = set()
    while pid > 1 and pid not in seen and len(seen) < DEPTH:
        seen.add(pid)
        got = _proc(pid, root)
        if got is None:
            return False
        ppid, cmd = got
        for a in cmd:
            low = a.lower()
            if low.endswith(".exe") or any(m in low for m in MARKERS):
                return True
        pid = ppid
    return False
