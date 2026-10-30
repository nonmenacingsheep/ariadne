"""Beats in whatever is playing, so she dances on them.

Reads the default output's monitor (what his speakers or headset are playing)
at a low rate, keeps only the bass, and calls on_beat(period, strength) on
each kick it hears. Nothing is recorded or kept: each 23 ms hop is reduced to
one energy number and dropped. It runs only while music is playing and her
Live2D body is showing (the host starts and stops it).

Plain Python, no numpy: at 11 kHz mono it is ~11k samples a second.
"""
from __future__ import annotations

import array
import logging
import math
import statistics
import subprocess
import threading
import time

log = logging.getLogger("ariadne2.pet2d.beats")

RATE = 11025
HOP = 256                         # ~23 ms
BASS_HZ = 150.0
WINDOW = 64                       # hops of history for the adaptive threshold (~1.5 s)
MIN_GAP = 0.27                    # s between beats (≤ 220 BPM)
FLOOR = 60.0                      # bass energy below this is silence, not a beat
PERIOD_MIN, PERIOD_MAX = 0.33, 0.75   # fold tempo into 80-180 BPM


def fold(period: float) -> float:
    while period < PERIOD_MIN:
        period *= 2
    while period > PERIOD_MAX:
        period /= 2
    return period


class BeatTracker:
    """Onsets from a stream of bass energies; the tempo from their spacing."""

    def __init__(self) -> None:
        self.history: list[float] = []
        self.onsets: list[float] = []
        self.period = 0.53
        self.last = -1.0

    def feed(self, energy: float, t: float):
        """(period, strength) when this hop is a beat, else None."""
        hist = self.history
        hit = None
        if len(hist) >= 16:
            mean = sum(hist) / len(hist)
            sd = math.sqrt(sum((e - mean) ** 2 for e in hist) / len(hist))
            if energy > FLOOR and energy > mean + 1.3 * sd + 0.15 * mean and t - self.last >= MIN_GAP:
                self.last = t
                self.onsets = [o for o in self.onsets if t - o < 8.0] + [t]
                gaps = [fold(b - a) for a, b in zip(self.onsets, self.onsets[1:]) if b - a > 0.2]
                if len(gaps) >= 3:
                    self.period = statistics.median(gaps)
                hit = (self.period, min(1.0, (energy - mean) / (mean + 1e-6)))
        hist.append(energy)
        if len(hist) > WINDOW:
            del hist[0]
        return hit


def default_monitor(run=subprocess.run) -> str | None:
    try:
        sink = run(["pactl", "get-default-sink"], capture_output=True, text=True, timeout=3).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    return f"{sink}.monitor" if sink else None


class BeatListener:
    def __init__(self, on_beat) -> None:
        self.on_beat = on_beat
        self._proc = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="pet2d-beats")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        proc, self._proc = self._proc, None
        if proc and proc.poll() is None:
            proc.terminate()

    def _run(self) -> None:
        source = default_monitor()
        if not source:
            return
        try:
            self._proc = subprocess.Popen(["parec", "-d", source, "--raw", "--format=s16le", f"--rate={RATE}",
                                           "--channels=1", "--latency-msec=30"],
                                          stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        except OSError as e:
            log.warning("can't listen for beats: %s", e)
            return
        a = 1.0 - math.exp(-2 * math.pi * BASS_HZ / RATE)
        low, tracker, start = 0.0, BeatTracker(), time.monotonic()
        proc = self._proc
        while not self._stop.is_set():
            data = proc.stdout.read(HOP * 2)
            if not data or len(data) < HOP * 2:
                break
            samples = array.array("h")
            samples.frombytes(data)
            acc = 0.0
            for x in samples:                      # one-pole low-pass: the kick and bass line
                low += a * (x - low)
                acc += low * low
            hit = tracker.feed(math.sqrt(acc / HOP), time.monotonic() - start)
            if hit:
                self.on_beat(*hit)
        if proc.poll() is None:
            proc.terminate()
