"""What he hands her body (pet/): files dropped on her.

The body can't talk to the core (its port is read-only), so it appends one
JSON line per drop to an inbox file in a user-only folder, and this reads new
lines and starts a turn about them. Those turns are things he did, not things
he said: they never count as his words for consent (a file named
"message Kai hi.png" can't make her send anything).
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)

FOLDER = Path.home() / ".local/share/ariadne2/pet"
INBOX = FOLDER / "inbox.jsonl"
STATE = FOLDER / "state.json"
KINDS = {"image": (".png", ".jpg", ".jpeg", ".webp", ".gif"), "song": (".mp3", ".flac", ".ogg", ".wav", ".m4a"),
         "video": (".mp4", ".mkv", ".webm"), "archive": (".zip", ".7z", ".rar", ".tar", ".gz")}


def kind_of(path: str) -> str:
    low = path.lower()
    return next((k for k, ends in KINDS.items() if low.endswith(ends)), "file")


def describe(paths: list[str]) -> str:
    names = ", ".join(f"{Path(p).name} ({kind_of(p)}, {p})" for p in paths[:5])
    more = f" and {len(paths) - 5} more" if len(paths) > 5 else ""
    return (f"(He dropped {names}{more} onto you. React in a line; if it's a song you can "
            f"offer to play it, if it's a mess of files you can offer to sort them.)")


async def watch(submit, poll: float = 1.0) -> None:
    """Start a turn for each new drop. submit(text, his_words=False)."""
    FOLDER.mkdir(parents=True, exist_ok=True, mode=0o700)
    FOLDER.chmod(0o700)
    pos = INBOX.stat().st_size if INBOX.exists() else 0     # only drops from now on
    while True:
        await asyncio.sleep(poll)
        try:
            size = INBOX.stat().st_size
        except FileNotFoundError:
            continue
        if size < pos:            # truncated or replaced
            pos = 0
        if size == pos:
            continue
        with INBOX.open("rb") as f:
            f.seek(pos)
            chunk = f.read(size - pos)
        pos = size
        for line in chunk.decode("utf-8", "replace").splitlines():
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            paths = [str(p) for p in msg.get("paths", []) if isinstance(p, str)]
            if msg.get("t") == "gave" and paths:
                submit(describe(paths), his_words=False)


def mood_line() -> str | None:
    """Her body's state for the prompt: 'Your body: sleepy (energy 18%, ...)'."""
    try:
        d = json.loads(STATE.read_text())
    except (OSError, ValueError):
        return None
    n = d.get("needs") or {}
    held = f", holding a {d['holding']}" if d.get("holding") else ""
    return (f"Your body on his desktop: {d.get('mood', 'content')} (energy {round(100 * n.get('energy', 0))}%, "
            f"fun {round(100 * n.get('fun', 0))}%, affection {round(100 * n.get('affection', 0))}%, "
            f"fed {round(100 * n.get('hunger', 1))}%){held}. "
            "Mention it only if it fits; you can ask for music or a break like anyone would.")
