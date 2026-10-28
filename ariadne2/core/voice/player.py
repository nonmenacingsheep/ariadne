"""Playing raw PCM through whatever this machine has. Carried over from 1.x.

Several things in here were learned the hard way and are kept on purpose:
one long-lived player per reply (a process per sentence sounded chopped:
every boundary paid for startup and sink negotiation), candidates proven by
running them (guessing another program's flags broke playback twice), and
stream names that are hers.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import threading

log = logging.getLogger("ariadne2.voice")

# Every stream named as hers. The audio server remembers mute and volume per
# program name, and a generic "pw-play" that anyone might mute in the mixer
# had been muted without anyone knowing what it was. Named, they get their own
# entries and he can find them. (Same names as 1.x, so his mixer settings carry.)
VOICE_NAME = "Ariadne voice"
# No media.role either: "Communication" can make the session manager duck
# everything else -- his music, his call -- while she talks.
_PW_VOICE = ["-P", '{ application.name = "%s" }' % VOICE_NAME]

RAW_PLAYERS = (
    ("paplay", lambda rate: ["paplay", f"--client-name={VOICE_NAME}",
                             f"--stream-name={VOICE_NAME}", "--raw", "--format=s16le",
                             f"--rate={rate}", "--channels=1"]),
    ("aplay", lambda rate: ["aplay", "-q", "-f", "S16_LE", "-r", str(rate), "-c", "1", "-"]),
    ("pw-cat", lambda rate: ["pw-cat", "--playback", *_PW_VOICE, "--format=s16",
                             f"--rate={rate}", "--channels=1", "-"]),
    ("pw-play", lambda rate: ["pw-play", *_PW_VOICE, "--format=s16", f"--rate={rate}",
                              "--channels=1", "-"]),
    # ffmpeg changed how the channel layout is spelled; offer both and let the
    # probe keep whichever the installed version accepts.
    ("ffplay (ch_layout)", lambda rate: ["ffplay", "-nodisp", "-autoexit", "-loglevel", "error",
                                         "-f", "s16le", "-ar", str(rate), "-ch_layout", "mono",
                                         "-i", "-"]),
    ("ffplay (ac)", lambda rate: ["ffplay", "-nodisp", "-autoexit", "-loglevel", "error",
                                  "-f", "s16le", "-ar", str(rate), "-ac", "1", "-i", "-"]),
)

_choice: dict = {}
_choice_lock = threading.Lock()


def player_installed() -> bool:
    """Whether any candidate exists at all. Cheap: opens no stream."""
    return any(shutil.which(build(24000)[0]) for _name, build in RAW_PLAYERS)


def raw_player(rate: int, *, runner=subprocess.run, which=shutil.which):
    """A player that genuinely takes raw PCM on stdin, proven by trying it.

    pw-play hands "-" to libsndfile, which looks for a file of that name and
    reports "format not recognised", so each candidate is run once against
    50ms of silence and the first that exits cleanly is remembered per rate.
    """
    with _choice_lock:
        if rate in _choice:
            return _choice[rate]
        silence = b"\x00\x00" * (rate // 20)
        found = None
        for name, build in RAW_PLAYERS:
            argv = build(rate)
            if not which(argv[0]):
                continue
            try:
                result = runner(argv, input=silence, timeout=15,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except (subprocess.TimeoutExpired, OSError):
                continue
            if result.returncode == 0:
                found = (name, argv)
                break
        _choice[rate] = found
        return found


class PlayerProcess:
    """One running player, fed raw samples on stdin."""

    def __init__(self, name: str, argv: list) -> None:
        self.name = name
        self.proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.PIPE)

    def write(self, pcm: bytes) -> None:
        self.proc.stdin.write(pcm)
        self.proc.stdin.flush()

    def close(self) -> None:
        """Let it finish what it has, then reap it."""
        try:
            if self.proc.stdin and not self.proc.stdin.closed:
                self.proc.stdin.close()
        except OSError:
            pass
        try:
            self.proc.communicate(timeout=30)
        except (subprocess.TimeoutExpired, ValueError):
            self.proc.kill()

    def terminate(self) -> None:
        """Kill it mid-word. Fire-and-forget players left her talking over the
        next question; stopping has to be immediate."""
        try:
            if self.proc.stdin and not self.proc.stdin.closed:
                self.proc.stdin.close()
        except OSError:
            pass
        try:
            self.proc.terminate()
            self.proc.wait(timeout=1)
        except (OSError, subprocess.TimeoutExpired):
            try:
                self.proc.kill()
            except OSError:
                pass


def open_player(rate: int) -> PlayerProcess | None:
    """A new player for this rate, or None when nothing here can play raw audio."""
    found = raw_player(rate)
    if found is None:
        return None
    try:
        return PlayerProcess(*found)
    except OSError as exc:
        log.warning("couldn't start %s: %s", found[0], exc)
        return None
