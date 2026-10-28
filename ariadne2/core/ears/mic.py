"""The microphone: finding a recorder, guarding Bluetooth, cutting speech into utterances.

Carried over from 1.x ears.py. The footprint fixes are all here, each learned
from the audio server complaining:

* status checks never start a recorder (1.x polled eight times a second and
  became a new audio-server client every 125ms; Discord's playout stalled);
* a recorder is proven by running it once per process, not on every reopen;
* a Bluetooth headset's mic is never held open for the wake word.
"""
from __future__ import annotations

import array
import logging
import math
import shutil
import subprocess
import threading

log = logging.getLogger("ariadne2.ears")

RATE = 16000
FRAME_MS = 32
FRAME_BYTES = int(RATE * FRAME_MS / 1000) * 2

# Candidate ways to get raw samples on stdout, probed rather than assumed. The
# low-latency variants come first: the default capture buffer can hold audio
# for a second or more before it reaches us, which reads as her being slow to
# notice you. A flag that is not supported just finds no audio and falls through.
RECORDERS = (
    ("parecord", ["parecord", "--latency-msec=40", "--raw", "--format=s16le",
                  f"--rate={RATE}", "--channels=1"]),
    ("parecord-default", ["parecord", "--raw", "--format=s16le", f"--rate={RATE}", "--channels=1"]),
    ("pw-record", ["pw-record", "--latency=40ms", "--format=s16", f"--rate={RATE}",
                   "--channels=1", "-"]),
    ("pw-record-default", ["pw-record", "--format=s16", f"--rate={RATE}", "--channels=1", "-"]),
    ("arecord", ["arecord", "-q", "-f", "S16_LE", "-r", str(RATE), "-c", "1", "-t", "raw"]),
    ("ffmpeg", ["ffmpeg", "-loglevel", "error", "-f", "pulse", "-i", "default",
                "-ar", str(RATE), "-ac", "1", "-f", "s16le", "-"]),
)

_proven: list = []
_proven_lock = threading.Lock()


def recorder_installed(which=shutil.which) -> bool:
    """Whether any candidate exists. Cheap and safe to poll: starts nothing."""
    return any(which(argv[0]) for _name, argv in RECORDERS)


def find_recorder(fresh: bool = False, *, popen=subprocess.Popen, which=shutil.which):
    """A recorder that actually runs here, proven by running it -- once.

    Proving means opening the mic, reading a frame and closing it, and then the
    real one opens it. Doing that on every reopen put two capture streams on
    the device a call app was using every time; one that kept dying made that
    once a second. The proof is kept for the process.
    """
    with _proven_lock:
        if _proven and not fresh:
            return _proven[0]
        for name, argv in RECORDERS:
            if not which(argv[0]):
                continue
            try:
                process = popen(argv, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            except OSError:
                continue
            try:
                data = process.stdout.read(FRAME_BYTES)
            except Exception:
                data = b""
            finally:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
            if data and len(data) >= FRAME_BYTES // 2:
                _proven[:] = [(name, argv)]
                return name, argv
        return None


def forget_proof() -> None:
    with _proven_lock:
        _proven.clear()


# --------------------------------------------------------- Bluetooth guard
def is_bluetooth_source(name: str) -> bool:
    return str(name or "").strip().startswith("bluez_")


def default_source(run=subprocess.run) -> str | None:
    """The audio server's default capture source; the host's pactl as a fallback
    because the dev environment is a container."""
    for argv in (["pactl", "get-default-source"], ["/run/host/usr/bin/pactl", "get-default-source"]):
        try:
            out = run(argv, capture_output=True, text=True, timeout=3)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if out.returncode == 0:
            return out.stdout.strip()
    return None


def bluetooth_mic(run=subprocess.run) -> bool:
    """Whether the default mic is a Bluetooth headset's. Holding one open drops
    the headset from its music profile into the call profile, and everything
    through it -- his call, his music, his game -- sounds like a phone line for
    as long as she listens."""
    return is_bluetooth_source(default_source(run) or "")


BLUETOOTH_MESSAGE = ("the default microphone is a Bluetooth headset's; holding it open for the "
                     "wake word would put it in call mode and make everything sound like a phone "
                     "line, so the wake word is off. Push-to-talk still works.")


def rms(frame: bytes) -> float:
    if len(frame) < 2:
        return 0.0
    samples = array.array("h")
    samples.frombytes(frame[:len(frame) // 2 * 2])
    return math.sqrt(sum(s * s for s in samples) / len(samples)) if samples else 0.0


# ------------------------------------------------------------ segmentation
# Speech has to be this loud, for this long, before it counts. This is only a
# floor: microphones vary enormously, so the real threshold is set from the
# measured noise in the room and this stops a very quiet room being hair-trigger.
SPEECH_RMS = 180
NOISE_MULTIPLE = 3.0
SILENCE_MS = 450                 # quiet this long ends an utterance
# Was 250, and it threw "send" away: the gate only opens on loud frames, so a
# spoken "send" registered as 64-96ms -- the vowel -- with the quiet "s" and "nd"
# counted as silence. The minimum only guards against clicks, and a click
# transcribes to nothing and harms nobody. The model decides; the gate hands over.
MIN_SPEECH_MS = 80
HOLD = 0.5                       # once a word has started, half the gate keeps it going
LEAD_IN_FRAMES = 10              # 320ms before speech: Whisper is unforgiving about a clipped consonant
MAX_UTTERANCE_S = 20


class Utterance:
    __slots__ = ("pcm", "interrupting", "ms")

    def __init__(self, pcm: bytes, interrupting: bool, ms: int) -> None:
        self.pcm, self.interrupting, self.ms = pcm, interrupting, ms


class Segmenter:
    """Cuts a stream of frames into utterances; adapts to how loud the room is."""

    def __init__(self) -> None:
        self.floor: float | None = None
        self.reset()

    def reset(self) -> None:
        self.buffer: list[bytes] = []
        self.speaking = False
        self.interrupting = False
        self.quiet_ms = 0
        self.speech_ms = 0

    def threshold(self) -> float:
        if self.floor is None:
            return float(SPEECH_RMS)
        return max(float(SPEECH_RMS), self.floor * NOISE_MULTIPLE)

    def feed(self, frame: bytes, *, her_voice: bool = False, awake: bool = False) -> Utterance | None:
        level = rms(frame)
        if not self.speaking:
            # Learn the room while nobody is talking. Two traps make her
            # permanently deaf: seeding the estimate from a frame that is
            # someone talking, and letting speech raise the floor above itself.
            # So the first estimate is capped, and only quiet frames move it.
            if self.floor is None:
                self.floor = min(level, float(SPEECH_RMS))
            elif level < self.threshold():
                self.floor = self.floor * 0.95 + level * 0.05
        gate = self.threshold()
        loud = level >= (gate * HOLD if self.speaking else gate)

        if self.speaking:
            self.buffer.append(frame)
            self.speech_ms += FRAME_MS
            self.quiet_ms = 0 if loud else self.quiet_ms + FRAME_MS
            if self.quiet_ms >= SILENCE_MS or self.speech_ms >= MAX_UTTERANCE_S * 1000:
                voiced = self.speech_ms - self.quiet_ms
                # While open there is no minimum to speak of: the lead-in and the
                # trailing quiet are already in the buffer, and the model judges.
                out = (Utterance(b"".join(self.buffer), self.interrupting, voiced)
                       if voiced >= (FRAME_MS if awake else MIN_SPEECH_MS) else None)
                if out is None:
                    log.debug("dropped %dms of sound", voiced)
                self.reset()
                return out
        elif loud:
            self.speaking, self.interrupting = True, her_voice
            self.buffer.append(frame)              # the lead-in already in the buffer is the word's start
            self.speech_ms, self.quiet_ms = FRAME_MS, 0
        else:
            self.buffer.append(frame)
            del self.buffer[:-LEAD_IN_FRAMES]
        return None
