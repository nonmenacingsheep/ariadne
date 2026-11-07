"""Is the window in front a game? KWin says which process owns a fullscreen
window (kwin_layer.js); a game is one whose process, or something that started
it, is a Steam launch, Proton or Wine, gamescope, a Windows .exe, or another
game launcher's. A fullscreen video, browser or editor isn't, so she stays.

While one is in front the widgets close their renderer at once and her body
closes (layer.py, pet/pet.gd). With "Turn off during games" on (the default)
the core then finishes what she's in the middle of and quits, and all that's
left is the launcher watching the game's process (watch_pid) till it's gone,
then starting her up (core/__main__.py, bin/ariadne2). Off, she stays up
listening for "Hey Aries" and answers by voice.
"""
from __future__ import annotations

import os
from pathlib import Path

# Words in a process's command line (or any of its parents') that mean a game.
MARKERS = ("steamlaunch", "proton", "wine", "gamescope", "steam_app",
           "lutris", "heroic", "legendary", "umu-run", "appid=")
DEPTH = 16                      # parents looked at, at most
# A game launcher's own window (Heroic, Lutris) stays open after its game ends:
# not the one to wait on.
LAUNCHERS = ("lutris", "heroic", "legendary")


def flag_path() -> Path:
    """Present while a game is in front, holding the pid of the process to wait on
    (watch_pid): bin/ariadne2 starts her again when it's gone."""
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


def watch_pid(pid: int, root: str = "/proc") -> int:
    """The process whose end is the game's end: the topmost game-marked one above
    the window's (Steam's reaper lives the whole session; a Wine or Proton
    game's own), not a launcher app; the window's own if nothing above is."""
    best, seen = pid, set()
    while pid > 1 and pid not in seen and len(seen) < DEPTH:
        seen.add(pid)
        got = _proc(pid, root)
        if got is None:
            break
        ppid, cmd = got
        low = " ".join(cmd).lower()
        if not any(x in low for x in LAUNCHERS) and \
                (any(a.lower().endswith(".exe") for a in cmd) or any(m in low for m in MARKERS)):
            best = pid
        pid = ppid
    return best
