"""The thread that holds the microphone open and the thread that transcribes.

Ported from 1.x Ears._listen/_pump/_work. What it has to get right, and the
reason most always-listening assistants are unpleasant:

* Only transcribe speech: a gate on loudness means Whisper runs on utterances,
  not continuously (the difference between a warm CPU and a hot one).
* Only act on her name: the transcript is dropped unless it opens with the wake
  word. Nothing else is kept, logged, or sent anywhere.
* Never listen to herself: while she speaks, only her name or a skip gets through.
* Hold the mic only while it is wanted, and never let a dying recorder spin.
"""
from __future__ import annotations

import logging
import queue
import subprocess
import threading
import time

from . import mic, transcribe
from .session import IDLE, OVER, PTT

log = logging.getLogger("ariadne2.ears")

PTT_TAIL_S = 0.25                # keep recording a moment after the key is released
PTT_MAX_S = 60.0                 # a stuck key must not record for ever
SHORT_UTTERANCE_S = 2.0          # at or under this, check for "send"/"nevermind" first
BLUETOOTH_RECHECK_S = 30.0       # the default source can change; asking costs a process
MAX_BACKOFF_S = 60.0


class Listener:
    def __init__(self, dialogue, transcriber, *, wake_enabled, is_speaking, barge_in=True,
                 status=None, find_recorder=mic.find_recorder, popen=subprocess.Popen,
                 bluetooth=mic.bluetooth_mic, clock=time.monotonic) -> None:
        self.dialogue, self.transcriber = dialogue, transcriber
        self.wake_enabled, self.is_speaking, self.barge_in = wake_enabled, is_speaking, barge_in
        self._status = status or (lambda text: None)
        self._find_recorder, self._popen, self._bluetooth = find_recorder, popen, bluetooth
        self.clock = clock
        self._stop = threading.Event()
        self._poke = threading.Event()          # something changed: re-decide whether the mic is wanted
        self._threads: list[threading.Thread] = []
        self._process = None
        self._pending: queue.Queue = queue.Queue()
        self._ptt_down = False
        self._ptt_release_at = 0.0
        self._wake_ok: tuple[float, bool] = (-1e9, True)
        self.restarts = 0
        self.heard = 0
        self.dropped = 0

    # ------------------------------------------------------------ lifecycle
    def start(self) -> None:
        self._stop.clear()
        for target in (self._work, self._listen):
            t = threading.Thread(target=target, daemon=True, name=f"ears-{target.__name__}")
            t.start()
            self._threads.append(t)

    def stop(self) -> None:
        self._stop.set()
        self._poke.set()
        self._kill_process()
        self._pending.put(None)
        for t in self._threads:
            t.join(timeout=3)
        self._threads = []

    def poke(self) -> None:
        self._poke.set()

    def reopen(self) -> None:
        """Close the recorder so the loop opens a fresh one (a different device was chosen)."""
        self._kill_process()
        self._poke.set()

    def _kill_process(self) -> None:
        process, self._process = self._process, None
        if process is not None and process.poll() is None:
            try:
                process.terminate()
            except OSError:
                pass

    # ----------------------------------------------------------- push to talk
    def push_to_talk(self, down: bool) -> None:
        if down:
            self._ptt_down, self._ptt_release_at = True, 0.0
            self.dialogue.set_ptt(True)
        elif self._ptt_down:
            self._ptt_down, self._ptt_release_at = False, self.clock() + PTT_TAIL_S
        self._poke.set()

    # --------------------------------------------------------- is the mic wanted
    def wake_allowed(self) -> bool:
        """The Bluetooth guard, for the wake word only (push-to-talk opens the mic
        on demand and for a moment). Cached: each check is a process."""
        checked, ok = self._wake_ok
        if self.clock() - checked >= BLUETOOTH_RECHECK_S:
            ok = not self._bluetooth()
            if not ok and self._wake_ok[1]:
                self._status(mic.BLUETOOTH_MESSAGE)
            self._wake_ok = (self.clock(), ok)
        return ok

    def wanted(self) -> bool:
        return (self._ptt_down or self._ptt_release_at > 0 or self.dialogue.awake
                or (self.wake_enabled() and self.wake_allowed()))

    # ------------------------------------------------------------ the mic loop
    def _listen(self) -> None:
        """Hold the microphone for as long as it is wanted, whatever happens to it.

        Two things kill an always-on listener, and both once ended this thread
        without a word: the recorder exits (dropped for not draining, or the
        audio server restarted), or anything in here raises. So the recorder is
        reopened when it dies and the loop is wrapped.
        """
        wait, first = 1.0, True
        while not self._stop.is_set():
            try:
                if not self.wanted():
                    self._poke.wait(1.0)
                    self._poke.clear()
                    continue
                found = self._find_recorder(fresh=self.restarts > 0 and self.restarts % 5 == 0)
                if found is None:
                    self._status("no microphone")
                    self._give_up_ptt()
                    self._poke.wait(10.0)       # not a hot loop: a mic may be plugged in later
                    self._poke.clear()
                    continue
                name, argv = found
                self._process = self._popen(argv, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
                if first:
                    self._status(f"listening through {name}")
                    first = False
                began = self.clock()
                self._pump()
                healthy = self.clock() - began > 120
            except Exception as exc:
                log.warning("ears: listening hit a problem: %s", exc)
                healthy = False
            finally:
                self._kill_process()
            if self._stop.is_set():
                return
            if not self.wanted():
                wait = 1.0                      # we closed it on purpose; not a failure
                continue
            if healthy:
                wait = 1.0
            # The recorder went away and we still want to hear. Back off: one that
            # keeps dying is being killed by something, and reopening it every
            # second churns the device under whatever else is using it.
            self.restarts += 1
            if self.restarts <= 3:
                self._status("the microphone dropped out; reopening it")
            self._stop.wait(wait)
            wait = min(wait * 2, MAX_BACKOFF_S)

    def _give_up_ptt(self) -> None:
        self._ptt_down, self._ptt_release_at = False, 0.0
        self.dialogue.set_ptt(False)

    def _pump(self) -> None:
        """Read frames and cut them into utterances. Never blocks on a transcription."""
        seg = mic.Segmenter()
        ptt_frames: list[bytes] = []
        ptt_started = 0.0
        d = self.dialogue
        while not self._stop.is_set():
            if not self.wanted():
                return                          # put the mic down: it is not needed
            frame = self._process.stdout.read(mic.FRAME_BYTES)
            if not frame:
                return                          # recorder gone; the caller reopens it
            now = self.clock()

            # Push-to-talk: record everything between press and release; the key
            # is the address, so no gate and no wake word.
            if self._ptt_down or ptt_frames or self._ptt_release_at:
                if not ptt_frames:
                    ptt_started = now
                    seg.reset()
                ptt_frames.append(frame)
                released = not self._ptt_down and now >= self._ptt_release_at
                if released or now - ptt_started > PTT_MAX_S:
                    self._submit(b"".join(ptt_frames), PTT)
                    ptt_frames, self._ptt_release_at = [], 0.0
                    self._ptt_down = False
                    d.set_ptt(False)
                continue

            # Fully deaf only through the chime, a loud noise a foot from the mic.
            if now < d.deaf_until:
                seg.reset()
                continue
            her_voice = bool(self.is_speaking())
            if her_voice and not self.barge_in:
                seg.reset()
                continue
            utterance = seg.feed(frame, her_voice=her_voice, awake=d.awake)
            if utterance is not None:
                self._submit(utterance.pcm, OVER if utterance.interrupting else d.mode)
            elif not seg.speaking:
                d.tick()            # nothing is said or about to be: the safe moment to decide a sentence ended

    # -------------------------------------------------------------- the worker
    def _submit(self, pcm: bytes, mode: str) -> None:
        """Hand an utterance off. Dropping beats blocking the microphone (and beats
        answering minutes late); a push-to-talk clip is deliberate and never dropped."""
        if mode != PTT and self._pending.qsize() >= 2:
            self.dropped += 1
            return
        self.dialogue.began()
        self._pending.put((pcm, mode))

    def _work(self) -> None:
        """Transcribe and act, well away from the thread holding the mic."""
        while not self._stop.is_set():
            try:
                item = self._pending.get(timeout=0.5)
            except queue.Empty:
                continue
            if item is None:
                return
            try:
                self.heard += 1
                text, sure = self._transcribe(*item)
                self.dialogue.consider(text, item[1], sure)
            except Exception as exc:
                # Must not escape: this thread going down is indistinguishable from
                # her ignoring you.
                log.warning("ears: couldn't handle an utterance: %s", exc)
            finally:
                self.dialogue.finished()      # or the auto-send waits for ever on a clip that failed

    def _transcribe(self, pcm: bytes, mode: str) -> tuple[str, bool]:
        t, names = self.transcriber, self.dialogue.names
        seconds = len(pcm) / 2 / mic.RATE
        if mode == PTT:
            h = t.hear(pcm, t.command_model(), transcribe.COMMAND_HINT)
        elif mode == OVER:
            h = t.hear(pcm, transcribe.WAKE_MODEL, names.interrupt_hint)
        elif mode == IDLE:
            h = t.hear(pcm, transcribe.WAKE_MODEL, names.wake_hint)
            if names.heard_name(h.text):
                # Name and words in one breath: the tiny model found the name, but
                # the words deserve the model that is better at words.
                better = t.hear(pcm, t.command_model(), transcribe.COMMAND_HINT)
                if names.heard_name(better.text):
                    h = better
        else:
            h = None
            if seconds <= SHORT_UTTERANCE_S:
                # Short enough to be "send" or "nevermind"? Ask the fast model with a
                # prompt that expects exactly those: the command prompt, primed for
                # this machine, hears "send it" as "Steam games".
                quick = t.hear(pcm, t.control_model(), transcribe.CONTROL_HINT)
                if names.is_send(quick.text) or names.is_dismissal(quick.text):
                    h = quick
            if h is None:
                h = t.hear(pcm, t.command_model(), transcribe.COMMAND_HINT)
        log.debug("ears: %s heard %r (%.1fs, %.2f)", mode, h.text[:80], seconds, h.confidence)
        return h.text, h.sure
