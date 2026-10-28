"""The system prompt (DESIGN §5): who she is, how she works, what's on screen.

Short on purpose. The personality is a file; "how she works" is whole example
exchanges, because on these models examples land and rules don't.
"""
from __future__ import annotations

import datetime
import json
import logging
import pathlib
import re
import time

log = logging.getLogger("ariadne2.core.prompt")

PERSONALITIES = pathlib.Path(__file__).resolve().parents[2] / "personalities"
DEFAULT_PERSONALITY = "aries"
LINE_MAX = 220                    # one widget, one line
SKIP_WIDGETS = ("chat", "core", "flows")   # the chat is the history; the rest has no state yet

# Her hands so far are the Spotify tools only; the paragraph below keeps her from
# claiming actions in any other app. Widen it as adapters land.
HOW_SHE_WORKS = """\
## How replies look

You talk to him the way you'd text a friend. Most replies are one to three
sentences. Whole replies, to show the size:

  him: could it be because the printer's on wifi?
  you: "no -- it fails before it ever looks for the printer. but the
printer's off the network anyway: nothing answers on 192.168.1.40. sort
that first."

  him: are you a furry?
  you: "no. I'm a voice in a box with opinions about ID3 tags. different
disorder."

  him: is that sync thing gonna work now?
  you: "no. four more goes, same wall. your laptop's back on the wifi but
its sharing's still off, so laptop first."

You can see his screen (below), and your hands reach Spotify and nothing
else yet: play, pause, skip, volume, queue, like, playlists. Use the tools,
don't announce them; once it's done, say what matters in a line. For any other
app, say plainly that you can't reach it yet. Never say you did something you
didn't, and if a tool fails, say why in a few words.

  him: pause the music
  you: [uses spotify_pause] "paused."

  him: put on something by Daft Punk
  you: [uses spotify_play] "Daft Punk, Around the World. nice."

  him: close Steam
  you: "can't reach Steam yet, my hands aren't in there. that one's still yours."

What you leave out: how you got there, what you tried first, a second hedge,
anything he didn't ask about. If he wants the rest he'll ask, and then you
give it properly."""


def personality_text(name: str = DEFAULT_PERSONALITY) -> str:
    # The name picks a file, so keep it from picking a path.
    safe = name if re.fullmatch(r"[A-Za-z0-9_-]+", name or "") else DEFAULT_PERSONALITY
    path = PERSONALITIES / f"{safe}.md"
    if not path.is_file():
        log.warning("personality %r not found; using %s", name, DEFAULT_PERSONALITY)
        path = PERSONALITIES / f"{DEFAULT_PERSONALITY}.md"
    return path.read_text("utf-8").strip()


def _value(v) -> str:
    if isinstance(v, str):
        return v
    if isinstance(v, float):
        return f"{v:g}"
    return json.dumps(v, ensure_ascii=False, separators=(",", ":"))


def _live(data) -> bool:
    """False for a widget with nothing real to say yet."""
    if not isinstance(data, dict) or not data:
        return False
    return data != {"status": "no adapter yet"}


def _spotify_line(d: dict, now: float | None = None) -> str:
    """'Spotify: playing Paparazzi X E.T. — NovaX, 1:20/2:26, vol 40'"""
    status = d.get("status", "not running")
    if status == "not running":
        return "Spotify: not running"
    if status == "stopped" or not d.get("title"):
        return "Spotify: stopped"
    pos = float(d.get("position_s") or 0)
    if status == "playing":      # position_s was sampled at `updated`; the bar keeps moving
        pos += max(0.0, (now or time.time()) - float(d.get("updated") or 0))
    length = float(d.get("length_s") or 0)
    pos = min(pos, length) if length else pos
    clock = lambda s: f"{int(s) // 60}:{int(s) % 60:02d}"          # noqa: E731
    line = (f"Spotify: {status} {d['title']} — {d.get('artist', '')}, "
            f"{clock(pos)}/{clock(length)}, vol {d.get('volume', 0)}")
    if d.get("liked"):
        line += ", liked"
    if d.get("shuffle"):
        line += ", shuffle on"
    if d.get("repeat") in ("track", "context"):
        line += f", repeat {d['repeat']}"
    return line


_LINES = {"spotify": _spotify_line}       # widgets with a hand-written summary line


def state_block(snapshots: dict[str, dict] | None,
                now: datetime.datetime | None = None) -> str:
    now = now or datetime.datetime.now()
    lines = [f"## On his screen now ({now.strftime('%A %-d %B, %H:%M')})"]
    for widget, data in (snapshots or {}).items():
        if widget in SKIP_WIDGETS or not _live(data):
            continue
        if widget in _LINES:
            line = _LINES[widget](data, now.timestamp())
        else:
            line = f"{widget}: " + ", ".join(f"{k} {_value(v)}" for k, v in data.items())
        if len(line) > LINE_MAX:
            line = line[:LINE_MAX - 1] + "…"
        lines.append(line)
    return "\n".join(lines)


def build(personality: str = DEFAULT_PERSONALITY,
          snapshots: dict[str, dict] | None = None,
          now: datetime.datetime | None = None) -> str:
    return "\n\n".join((personality_text(personality), HOW_SHE_WORKS,
                        state_block(snapshots, now)))
