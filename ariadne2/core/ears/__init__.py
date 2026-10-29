"""Her ears: the wake word, push-to-talk, and local Whisper.

    ears = Ears(voice=voice, on_heard=handle_text, on_listening=on_mic)
    await ears.start()
    ears.push_to_talk(True) ... ears.push_to_talk(False)    # a hotkey drives these
    ears.set_wake_word(False)                               # stop holding the mic for "hey Aries"
    await ears.stop()

An utterance is whatever you say until you stop for about a second; it is
handed to `on_heard(text)` as a finished piece of text. `on_listening(True)`
fires when the mic opens (the wake phrase, or the talk key down) and
`on_listening(False)` when it closes, for the chime and the desk. Callbacks are
delivered on the asyncio loop.

While she is speaking the mic stays deaf except for her name or "skip", which
call `on_interrupt` (by default `voice.cancel()`): that is how 1.x let you cut
her off, and it is kept over simply not listening at all.

Like the voice, it degrades: no recorder, no faster-whisper, or a Bluetooth
headset as the default mic each log once and leave her unable to hear, never
raising.
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time

from ..voice.dispatch import Dispatcher
from . import mic
from .listener import Listener
from .session import FOLLOW_UP_S, Dialogue
from .transcribe import WAKE_MODEL, Transcriber
from .wake import Names

__all__ = ["Ears"]

log = logging.getLogger("ariadne2.ears")


class Ears:
    def __init__(self, *, name: str = "Aries", aliases=(), wake_word: bool = True,
                 voice=None, is_speaking=None, is_busy=None, media_playing=None,
                 barge_in: bool = True, follow_up_s: float = FOLLOW_UP_S,
                 on_heard=None, on_listening=None, on_interrupt=None, on_status=None,
                 transcriber: Transcriber | None = None, **listener_kw) -> None:
        self.on_heard, self.on_listening = on_heard, on_listening
        self.on_interrupt, self.on_status = on_interrupt, on_status
        self._voice = voice
        self.names = Names(name, aliases)
        self.transcriber = transcriber or Transcriber()
        self._wake_word = bool(wake_word)
        self._dispatch = Dispatcher()
        self.status = "stopped"
        self._warned: set[str] = set()
        speaking = is_speaking or ((lambda: voice.speaking) if voice is not None else (lambda: False))
        self.dialogue = Dialogue(
            self.names, heard=self._heard, listening=self._listening, interrupt=self._interrupt,
            is_speaking=speaking, is_busy=is_busy, media_playing=media_playing,
            follow_up_s=follow_up_s, clock=listener_kw.get("clock") or time.monotonic)
        self.listener = Listener(self.dialogue, self.transcriber,
                                 wake_enabled=lambda: self._wake_word, is_speaking=speaking,
                                 barge_in=barge_in, status=self._note, **listener_kw)
        self.available = False

    # ------------------------------------------------------------ properties
    @property
    def wake_phrase(self) -> str:
        return self.names.phrase

    @property
    def wake_word(self) -> bool:
        return self._wake_word

    @property
    def listening(self) -> bool:
        """The mic is open for something she should act on."""
        return self.dialogue.listening

    @property
    def sure(self) -> bool:
        """Whether the last transcription was more than a guess (so she can ask, not guess)."""
        return self.dialogue.sure

    # ------------------------------------------------------------ lifecycle
    async def start(self) -> None:
        if self.available:
            return
        self._dispatch = Dispatcher(asyncio.get_running_loop())
        # Neither check starts a recorder or loads a model: status must be free.
        problem = self.transcriber.available()
        if problem is None and not mic.recorder_installed():
            problem = "nothing here can record audio (no parecord, pw-record, arecord or ffmpeg)"
        if problem:
            self._warn_once("start", f"she can't hear: {problem}")
            return
        self.available = True
        self.listener.start()
        if self._wake_word:
            self._warm()
        self._note("listening for " + self.names.phrase if self._wake_word
                   else "ready for push-to-talk")

    async def stop(self) -> None:
        if not self.available:
            return
        self.available = False
        await asyncio.to_thread(self.listener.stop)
        self.dialogue.close()
        self.dialogue.set_ptt(False)
        # The recogniser is the biggest thing she keeps on the card; give it back.
        await asyncio.to_thread(self.transcriber.unload)
        self.status = "stopped"

    def _warm(self) -> None:
        """Load and run the models off the critical path, or the first "hey Aries"
        pays for all of it."""
        def go():
            try:
                self.transcriber.warm(WAKE_MODEL)
                self.transcriber.warm(self.transcriber.command_model())
            except Exception as exc:
                self._warn_once("model", f"couldn't load the speech model: {exc}")
        threading.Thread(target=go, daemon=True).start()

    # --------------------------------------------------------------- controls
    def push_to_talk(self, down: bool) -> None:
        """Hold to talk, release to send. Works with the wake word off."""
        if self.available:
            self.listener.push_to_talk(bool(down))

    def set_wake_word(self, on: bool) -> None:
        """Whether to hold the mic open listening for the wake phrase. Off puts
        the mic down entirely until push-to-talk or wake_now()."""
        self._wake_word = bool(on)
        if on and self.available:
            self._warm()
        self.listener.poke()
        self._note("listening for " + self.names.phrase if on else "wake word off")

    def set_name(self, name: str) -> None:
        """Answer to a different name ("hey <name>"). Takes effect for the next thing heard."""
        self.names = Names(name, self.names.aliases)
        self.dialogue.names = self.names
        if self.available:
            self._warm()
        self.listener.poke()
        self._note("listening for " + self.names.phrase if self._wake_word else "wake word off")

    def set_mic(self, source: str) -> None:
        """Listen through a different capture device ("" = the system default), reopening now."""
        mic.set_source(source)
        mic.forget_proof()
        if self.available:
            self.listener.reopen()

    def wake_now(self) -> bool:
        """Open as if her name had been said (a shortcut that is not push-to-talk, or
        she asked a question and wants the answer without it). No-op if already open."""
        if not self.available or self.dialogue.awake:
            return False
        self.dialogue.open()
        self.listener.poke()
        return True

    # ------------------------------------------------- thread -> loop callbacks
    def _heard(self, text: str, sure: bool) -> None:
        log.info("ears: heard %d chars%s", len(text), "" if sure else " (unsure)")
        self._dispatch.call(self.on_heard, text)

    def _listening(self, active: bool) -> None:
        self._dispatch.call(self.on_listening, active)

    def _interrupt(self, reason: str = "") -> None:
        log.info("ears: interrupting her: %s", reason)
        fn = self.on_interrupt or (self._voice.cancel if self._voice is not None else None)
        self._dispatch.call(fn)

    def _note(self, text: str) -> None:
        self.status = text
        log.info("ears: %s", text)
        self._dispatch.call(self.on_status, text)

    def _warn_once(self, key: str, message: str) -> None:
        if key not in self._warned:
            self._warned.add(key)
            log.warning("ears: %s", message)
            self.status = message
