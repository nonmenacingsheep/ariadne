"""Where her voice has got to, in audio seconds, and how loud it is there.

Audio leaves the synthesiser far faster than it is heard: the player consumes
its pipe at exactly one second per second, so elapsed wall clock since the
first sample is the true position, capped by how much has been handed over.
Ported from 1.x's Speaker bookkeeping, with the clock injectable.
"""
from __future__ import annotations

import array
import math
import time

WINDOW_S = 0.05                  # one level reading per 50ms = 20 a second


def window_levels(pcm: bytes, rate: int) -> list[float]:
    """RMS of each 50ms window of 16-bit mono samples, 0..1 of full scale."""
    samples = array.array("h")
    samples.frombytes(pcm[:len(pcm) // 2 * 2])
    size = max(1, int(rate * WINDOW_S))
    out = []
    for i in range(0, len(samples), size):
        window = samples[i:i + size]
        out.append(math.sqrt(sum(s * s for s in window) / len(window)) / 32768.0)
    return out


class Timeline:
    def __init__(self, clock=time.monotonic) -> None:
        self.clock = clock
        self.reset()

    def reset(self) -> None:
        self.start: float | None = None    # when the first sample went to the player
        self.end = 0.0                     # seconds of audio written so far
        self._segments: list[tuple[float, list[float]]] = []   # (offset, window levels)

    def note(self, pcm: bytes, rate: int) -> float:
        """Record that this audio starts being handed over now. Called before
        the write: the write blocks once the pipe (~1.4s) is full, and the
        clock has to start when the player first has something to do."""
        now = self.clock()
        if self.start is None:
            self.start = now
        # A player that has already got through everything it was given ran
        # dry (a slow request, a tool call mid-reply): this audio starts now,
        # not where the last ended, or the position runs ahead of her for good.
        elapsed = now - self.start
        if elapsed > self.end:
            self.end = elapsed
        first = self.end
        self.end += len(pcm) / (2.0 * rate)
        self._segments.append((first, window_levels(pcm, rate)))
        return first

    def position(self) -> float:
        if self.start is None:
            return 0.0
        return min(self.clock() - self.start, self.end)

    def finished(self) -> bool:
        """Everything handed over has been heard."""
        return self.start is not None and self.clock() - self.start >= self.end

    def level(self) -> float:
        """How loud it is at the current position; 0 in a gap."""
        if self.start is None:
            return 0.0
        pos = self.clock() - self.start
        for offset, levels in reversed(self._segments):
            if pos >= offset:
                index = int((pos - offset) / WINDOW_S)
                return levels[index] if index < len(levels) else 0.0
        return 0.0


# The first chunk is the whole wait before she speaks. A short opener is a
# second of audio and the chunk after it can take longer than that to make, so
# the player would run dry mid-reply -- heard as a hang after the first
# sentence. When the opener is short, wait for the next chunk first: spending
# the time before she speaks, not in the middle of what she says.
RUNWAY_WAIT_S = 4.0
FALLBACK_RUNWAY_S = 4.0


def runway_needed(runway_s: float, cost_s: float, chars: int, max_chunk: int) -> float:
    """Seconds of audio in hand that cover the worst the next chunk can cost,
    measured rather than assumed. A fixed 4s was set for a slow processor and
    is pure latency on anything quicker."""
    if runway_s > 0 and cost_s > 0:
        return (cost_s / runway_s) * max_chunk * (runway_s / max(1, chars))
    return FALLBACK_RUNWAY_S
