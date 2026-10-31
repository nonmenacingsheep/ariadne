"""What a transcribed utterance means: wake, draft, send, dismiss, interrupt.

The state machine behind the mic, with no audio or threads of its own, so it
is tested with a fake clock. Simplified from 1.x: the same wake / draft /
"send" / "nevermind" / barge-in rules, but conversation mode, shutdown,
restart and media words are gone, and silence sends the draft (1.x only did
that in conversation mode).
"""
from __future__ import annotations

import logging
import threading
import time

log = logging.getLogger("ariadne2.ears")

# How long a silence means "I have finished" rather than "I am thinking of the
# next word". It sits in front of everything else -- nothing starts until it
# elapses -- so it is worth being tight: a pause for breath is a third of a
# second; this is nearly four of those.
AUTOSEND_S = 1.2
# After "hey Aries" on its own, how long she waits for the words before closing.
# There is no follow-up window after a message: once one is sent she stops
# listening (he asked: an open mic after her reply drafted whatever was said in
# the room, which she answered, which opened it again).
FOLLOW_UP_S = 8.0
# However loud the room stays (music, a stream), the window never outlives this.
MAX_OPEN_S = 30.0
# Deaf for a moment either side of opening/closing: the desk plays a chime a
# foot from the microphone, which would otherwise read as an utterance.
DEAF_S = 0.6

# Utterance modes, decided by what was true when the speech began.
IDLE, OPEN, OVER, PTT = "idle", "open", "over", "ptt"


class Dialogue:
    def __init__(self, names, *, heard=None, listening=None, interrupt=None, is_speaking=None,
                 is_busy=None, media_playing=None, follow_up_s: float = FOLLOW_UP_S,
                 clock=time.monotonic) -> None:
        self.names = names
        self._heard = heard or (lambda text, sure: None)
        self._listening = listening or (lambda active: None)
        self._interrupt = interrupt or (lambda reason="": None)
        self.is_speaking = is_speaking or (lambda: False)
        self.is_busy = is_busy or (lambda: False)
        # Over her voice, a bare "skip" picked up while a video plays is far
        # likelier the video than them, so with media on those words need her name.
        self.media_playing = media_playing or (lambda: False)
        self.follow_up_s = follow_up_s
        self.clock = clock
        self._lock = threading.RLock()
        self.awake = False              # open after the wake word, until dismissed or idle
        self.ptt = False                # the talk key is down
        self.transcribing = 0           # clips still being transcribed
        self.deaf_until = 0.0
        self.draft: list[str] = []
        self._drafted_at = 0.0
        self._active_at = 0.0
        self._opened_at = 0.0
        self._reported = False
        self.sure = True

    # ----------------------------------------------------------- open state
    @property
    def listening(self) -> bool:
        return self.awake or self.ptt

    def _sync(self) -> None:
        if self.listening != self._reported:
            self._reported = self.listening
            self._listening(self._reported)

    def open(self) -> None:
        with self._lock:
            if self.awake:
                return
            self.awake = True
            self._active_at = self._opened_at = self.clock()
            self.deaf_until = self.clock() + DEAF_S
            self._sync()

    def close(self) -> None:
        """Close again, discarding whatever was being drafted."""
        with self._lock:
            self.awake = False
            self.draft = []
            self.deaf_until = self.clock() + DEAF_S
            self._sync()

    def set_ptt(self, down: bool) -> None:
        with self._lock:
            if self.ptt != down:
                self.ptt = down
                if down:
                    self.draft = []
                self._sync()

    # --------------------------------------------------------------- clips
    def began(self) -> None:
        with self._lock:
            self.transcribing += 1

    def finished(self) -> None:
        with self._lock:
            self.transcribing = max(0, self.transcribing - 1)

    @property
    def mode(self) -> str:
        return OPEN if self.awake else IDLE

    # ------------------------------------------------------------- meaning
    def consider(self, text: str, mode: str, sure: bool = True) -> None:
        """Act on one transcribed utterance."""
        text = (text or "").strip()
        if not text:
            return
        with self._lock:
            self.sure = sure
            if mode == PTT:
                # The key is the address; no name needed.
                self._send(text)
                return
            interrupted = False
            if mode == OVER:
                # She is talking. What is worth hearing over her own voice: a skip
                # (cut her off, leave her alone), or her name (cut her off, listen).
                # Everything else picked up now is her own voice coming back.
                if self.names.is_skip(text):
                    if self.media_playing() and not self.names.addressed(text):
                        log.info("ears: heard %r over her voice while media plays; "
                                 "not stopping her for it", text)
                        return
                    self._interrupt(f"heard {text!r} over her voice")
                    self.deaf_until = self.clock() + 0.25
                    return
                if self.names.heard_name(text) is None:
                    return
                self._interrupt(f"heard her name over her voice: {text!r}")
                self.deaf_until = self.clock() + 0.25
                interrupted = True

            command = self.names.heard_name(text)
            if command is None:
                if not self.awake:
                    return              # not for her; the transcript goes no further
                command = text
            else:
                if self.is_busy() and not interrupted:
                    self._interrupt("addressed while she was working")
                self.open()
                if not command:
                    return              # the name alone: acknowledge, hold the door open

            if self.names.is_dismissal(command):
                self.close()
                return
            if self.names.is_send(command):
                self._flush()           # "send" itself is never part of the message
                return
            self.draft.append(command)
            self._drafted_at = self._active_at = self.clock()

    def peek(self, text: str) -> None:
        """Words so far while he talks over her: a skip or her name cuts her
        off now. Nothing is drafted; the finished utterance does that."""
        text = (text or "").strip()
        if not text or not self.is_speaking():
            return
        with self._lock:
            if self.names.is_skip(text) and (self.names.addressed(text) or not self.media_playing()):
                self._interrupt(f"heard {text!r} over her voice (early)")
            elif self.names.heard_name(text) is not None:
                self._interrupt(f"heard her name over her voice (early): {text!r}")

    def _flush(self) -> None:
        message = " ".join(self.draft).strip()
        self.draft = []
        if message:
            self._send(message)
            self.close()            # sent: stop listening until her name (or the key) again

    def _send(self, message: str) -> None:
        try:
            self._heard(message, self.sure)
        except Exception:
            log.exception("on_heard failed")

    def expire(self) -> None:
        """Called every frame, sound or not: a window held open by a room that is
        never quiet (music, a stream) still closes, and what it drafted goes."""
        with self._lock:
            if self.awake and not self.is_busy() and not self.is_speaking() \
                    and self.clock() - self._opened_at >= MAX_OPEN_S:
                log.info("ears: closing a window the room kept open")
                if self.draft and not self.transcribing:
                    self._flush()           # he did start a message: send it (which closes)
                else:
                    self.close()

    def tick(self) -> None:
        """Called from quiet moments in the audio loop: send a finished draft,
        or close after a follow-up window with nothing in it."""
        with self._lock:
            if not self.awake or self.transcribing:
                return
            now = self.clock()
            if self.is_speaking() or self.is_busy():
                self._active_at = now   # she is talking or working: not idle
                return
            if self.draft:
                if now - self._drafted_at >= AUTOSEND_S:
                    self._flush()
            elif now - self._active_at >= self.follow_up_s:
                self.close()
