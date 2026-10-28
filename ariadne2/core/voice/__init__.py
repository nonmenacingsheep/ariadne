"""Her voice: Cartesia Sonic, spoken a sentence at a time through a raw-PCM player.

    voice = Voice(on_start=..., on_stop=..., on_level=...)
    await voice.start()
    voice.say("Right, so that worked.")          # queued; plays in order
    voice.feed(delta); voice.flush(); voice.finish()   # or stream the reply in
    voice.cancel()                                # stop now (you interrupted)
    await voice.stop()

Three threads behind it, as in 1.x: one makes the next sentence while another
plays the last (you hear the first sentence after one short synthesis, not
after the whole reply), and a meter that reports level 20 times a second
against the real playback clock. Callbacks are delivered on the asyncio loop.

If Cartesia or audio output is unavailable it logs once and becomes a no-op.
"""
from __future__ import annotations

import asyncio
import logging
import queue
import threading
import time
from dataclasses import dataclass

from . import cartesia, player as player_mod
from .dispatch import Dispatcher
from .text import (MAX_CHUNK, MarkStream, SkipTracker, chunks, ends_sentence, next_chunk,
                   speakable, split_at_marks, split_first_sentence, strip_marks)
from .timeline import RUNWAY_WAIT_S, WINDOW_S, Timeline, runway_needed

__all__ = ["Voice", "MarkStream", "strip_marks", "speakable"]

log = logging.getLogger("ariadne2.voice")

LOOKAHEAD = 2                     # sentences made ahead of the one playing
_STOP = object()


@dataclass
class Piece:
    text: str
    speed: float
    emotion: str


class Voice:
    def __init__(self, voice: str | None = None, speed: float = 1.0, emotion: str = "",
                 *, on_start=None, on_stop=None, on_level=None, synth=None, open_player=None,
                 clock=time.monotonic) -> None:
        self.voice, self.speed, self.emotion = voice, speed, emotion   # emotion: default when unmarked
        self.on_start, self.on_stop, self.on_level = on_start, on_stop, on_level
        self._synth = synth or cartesia.synthesize_pcm      # (text, voice, speed, emotion) -> (pcm, rate)
        self._open_player = open_player or player_mod.open_player
        self._injected = synth is not None
        self._clock = clock
        self._dispatch = Dispatcher()
        self._lock = threading.RLock()
        self._q: queue.Queue = queue.Queue()
        self._ready: queue.Queue = queue.Queue(maxsize=LOOKAHEAD)
        self._threads: list[threading.Thread] = []
        self._timeline = Timeline(clock)
        self._gen = 0                  # bumped by cancel(); stale work is dropped
        self._pending = 0              # pieces queued, being made, or being handed over
        self._audible = False
        self._player = None
        self._stopping = False
        self._started = False
        self._more_coming = False      # a streamed reply is open: more text may follow
        self._warned: set[str] = set()
        self._fail_streak = False
        self.available = False
        # Stream state, kept apart from the queue: text still arriving.
        self._buffer, self._first = "", True
        self._skip, self._carry = SkipTracker(), None

    # ------------------------------------------------------------ lifecycle

    async def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._dispatch = Dispatcher(asyncio.get_running_loop())
        problem = None if self._injected else await asyncio.to_thread(self._check)
        if problem:
            self._warn_once("start", problem)
            return
        self.available = True
        for target in (self._make_loop, self._play_loop, self._meter_loop):
            t = threading.Thread(target=target, daemon=True, name=f"voice-{target.__name__}")
            t.start()
            self._threads.append(t)

    async def stop(self) -> None:
        self._stopping = True
        self.cancel()
        self._q.put(_STOP)
        threads, self._threads = self._threads, []
        await asyncio.to_thread(lambda: [t.join(timeout=3) for t in threads])
        self.available = False

    @staticmethod
    def _check() -> str | None:
        """What is missing, found without opening a stream or making a request."""
        if cartesia.key() is None:
            return (f"no Cartesia key (CARTESIA_API_KEY or {cartesia.key_path()}); "
                    "she will be silent")
        if not player_mod.player_installed():
            return "nothing here can play audio (no paplay, aplay, pw-cat, pw-play or ffplay)"
        return None

    def _warn_once(self, key: str, message: str) -> None:
        if key not in self._warned:
            self._warned.add(key)
            log.warning("voice: %s", message)

    def _disable(self, why: str) -> None:
        self._warn_once("disabled", why)
        self.available = False
        self.cancel()

    # --------------------------------------------------------------- state

    @property
    def speaking(self) -> bool:
        """True from the moment text is queued until it has all been heard.
        Includes the wait for synthesis, so the mic never opens in the gap."""
        with self._lock:
            return self._pending > 0 or self._audible

    # ------------------------------------------------------------- queueing

    def say(self, text: str) -> None:
        """Queue some finished text. Non-blocking; plays after whatever is queued."""
        if not self.available or self._stopping:
            return
        with self._lock:
            for raw in chunks(text):
                self._enqueue(raw)

    def feed(self, delta: str) -> None:
        """More of a reply that is still being written. Whole phrases are
        handed off as they complete; the tail waits for its sentence end."""
        if not self.available or self._stopping or not delta:
            return
        with self._lock:
            if not self._buffer and self._pending == 0 and not self._audible:
                self._first = True
            self._more_coming = True
            self._buffer += delta
            while True:
                raw, self._buffer = next_chunk(self._buffer, first=self._first)
                if raw is None:
                    break
                self._first = False
                self._enqueue(raw)

    def flush(self) -> None:
        """Say what is buffered and keep the stream open. Between a reply's
        words and a tool call the chunker would otherwise hold the tail of a
        sentence for seconds, and half a sentence is what gets heard."""
        if not self.available:
            return
        with self._lock:
            raw, self._buffer = next_chunk(self._buffer, first=self._first, final=True)
            if raw:
                self._first = False
                self._enqueue(raw)

    def finish(self) -> None:
        """No more is coming for this reply: say the rest and reset the stream."""
        self.flush()
        with self._lock:
            self._first, self._more_coming, self._carry = True, False, None
            self._skip.reset()

    def _enqueue(self, raw: str) -> None:
        """Turn one cut of text into Pieces. Caller holds the lock.

        A mark holds for the sentence it opens and the next sentence goes back
        to unmarked. A cut that fell mid-sentence (the first chunk may break
        on a comma) leaves its mark standing for the rest of that sentence.
        """
        for part in split_at_marks(self._skip.apply(raw)):
            words, rate, emotion = strip_marks(part)
            marked = bool(emotion) or rate != 1.0
            if not marked and self._carry:
                rate, emotion = self._carry
                marked = True
            self._carry = None
            parts = [(words, 1.0, "")]
            if marked:
                head, tail = split_first_sentence(words)
                parts = [(head, rate, emotion)] + ([(tail, 1.0, "")] if tail.strip() else [])
                if not tail.strip() and not ends_sentence(head):
                    self._carry = (rate, emotion)
            for text, r, e in parts:
                self._queue_piece(text, r, e)

    def _queue_piece(self, text: str, rate: float, emotion: str) -> None:
        words = speakable(text)
        if not words or not any(c.isalnum() for c in words):
            return
        speed = max(0.6, min(float(self.speed or 1.0) * rate, 1.5))
        self._pending += 1
        self._q.put((self._gen, Piece(words, round(speed, 2), emotion or self.emotion)))
        log.debug("queued %dc %r", len(words), words[:60])

    def cancel(self) -> None:
        """Stop speaking now: drop everything queued, kill the player mid-word."""
        with self._lock:
            self._gen += 1
            self._pending = 0
            self._buffer, self._first, self._carry, self._more_coming = "", True, None, False
            self._skip.reset()
            was_audible, self._audible = self._audible, False
            player, self._player = self._player, None
            self._timeline.reset()
            for q in (self._q, self._ready):
                while True:
                    try:
                        item = q.get_nowait()
                    except queue.Empty:
                        break
                    if item is _STOP:          # not ours to swallow
                        q.put(_STOP)
                        break
        if player is not None:
            player.terminate()
        if was_audible:
            log.info("voice: cancelled mid-speech")
            self._dispatch.call(self.on_level, 0.0)
            self._dispatch.call(self.on_stop)

    # -------------------------------------------------------------- threads

    def _make_loop(self) -> None:
        """Synthesise in order, a sentence or two ahead of the player."""
        while True:
            item = self._q.get()
            if item is _STOP:
                self._ready.put(_STOP)
                return
            gen, piece = item
            if gen != self._gen:
                continue
            began = self._clock()
            try:
                pcm, rate = self._synth(piece.text, self.voice, piece.speed, piece.emotion)
            except Exception as exc:
                self._made_nothing(gen, exc)
                continue
            self._fail_streak = False
            if not pcm:
                self._done(gen)
                continue
            item = (gen, piece, pcm, rate, self._clock() - began)
            while gen == self._gen and not self._stopping:
                try:
                    self._ready.put(item, timeout=0.1)     # not forever: cancel must free us
                    break
                except queue.Full:
                    continue

    def _made_nothing(self, gen: int, exc: Exception) -> None:
        self._done(gen)
        if getattr(exc, "fatal", False):
            self._disable(str(exc))
        elif not self._fail_streak:            # once per streak, not once per sentence
            self._fail_streak = True
            log.warning("voice: skipping a sentence: %s", exc)

    def _done(self, gen: int) -> None:
        with self._lock:
            if gen == self._gen and self._pending > 0:
                self._pending -= 1

    def _play_loop(self) -> None:
        while True:
            item = self._ready.get()
            if item is _STOP:
                return
            gen, piece, pcm, rate, cost = item
            if gen != self._gen:
                continue
            try:
                if not self._audible:          # this one opens a reply
                    self._wait_for_runway(gen, piece, pcm, rate, cost)
                self._hand_over(gen, pcm, rate)
            except Exception as exc:
                log.warning("voice: playback failed: %s", exc)
            finally:
                self._done(gen)

    def _wait_for_runway(self, gen: int, piece: Piece, pcm: bytes, rate: int, cost: float) -> None:
        """Hold a short opening sentence until the next one exists, if one is
        on its way. A lone say() is never held: nothing is coming."""
        runway = len(pcm) / (2.0 * rate)
        needed = runway_needed(runway, cost, len(piece.text), MAX_CHUNK)
        waited = 0.0
        while (runway < needed and waited < RUNWAY_WAIT_S and gen == self._gen
               and (self._pending > 1 or self._more_coming) and self._ready.empty()):
            time.sleep(0.02)
            waited += 0.02

    def _hand_over(self, gen: int, pcm: bytes, rate: int) -> None:
        with self._lock:
            if gen != self._gen:
                return
            player = self._player
        if player is None:
            player = self._open_player(rate)
            if player is None:
                self._disable("no player here takes raw audio on stdin")
                return
            with self._lock:
                if gen != self._gen:
                    player.terminate()
                    return
                self._player = player
        with self._lock:
            if gen != self._gen:
                return
            self._timeline.note(pcm, rate)
            started, self._audible = not self._audible, True
        if started:
            self._dispatch.call(self.on_start)
        try:
            player.write(pcm)
        except (BrokenPipeError, ValueError, OSError):
            # The player went away -- the sink is closed under an idle process
            # when a reply has a long silence in it (a tool that runs for
            # minutes). Not a reason to stop talking: reopen once, and if a
            # fresh one dies too, stop rather than spin.
            if gen != self._gen:
                return
            log.info("voice: player pipe broke; reopening")
            fresh = self._open_player(rate)
            with self._lock:
                self._player = fresh if gen == self._gen else self._player
            if fresh is None or gen != self._gen:
                return
            try:
                fresh.write(pcm)
            except (BrokenPipeError, ValueError, OSError):
                log.warning("voice: a fresh player died too; dropping this sentence")

    def _meter_loop(self) -> None:
        """Report level against the playback clock, and notice when it is over."""
        while not self._stopping:
            time.sleep(WINDOW_S)
            finished, over = None, False
            with self._lock:
                if not self._audible:
                    continue
                level = self._timeline.level()
                if self._pending == 0 and self._timeline.finished():
                    finished, self._player, over = self._player, None, True
                    self._audible = False
                    self._timeline.reset()
                    level = 0.0
            self._dispatch.call(self.on_level, level)
            if over:
                # Close at the end of a reply, as 1.x did: a player left idle
                # gets its sink closed under it.
                if finished is not None:
                    finished.close()
                self._dispatch.call(self.on_stop)
