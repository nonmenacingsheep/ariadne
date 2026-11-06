"""The thread that holds the microphone open and the thread that transcribes.

Ported from 1.x Ears._listen/_pump/_work. What it has to get right, and the
reason most always-listening assistants are unpleasant:

* Only transcribe speech: a gate on loudness means Whisper runs on utterances,
  not continuously (the difference between a warm CPU and a hot one).
* Only act on her name: with the wake model (wakeword.py) nothing is
  transcribed at all until it hears "wake Aries"; without it, the transcript is
  dropped unless it opens with the wake word. Nothing else is kept, logged, or
  sent anywhere.
* Never listen to herself: while she speaks, only her name or a skip gets through.
* Hold the mic only while it is wanted, and never let a dying recorder spin.
"""
from __future__ import annotations

import logging
import queue
import subprocess
import threading
import time

from . import mic, transcribe, wakeword
from .session import IDLE, OPEN, OVER, PTT, WOKE

log = logging.getLogger("ariadne2.ears")

# Talking over her: her voice through the speakers keeps the room from going
# quiet, so the utterance wouldn't end (and "skip" wouldn't land) until she
# paused between sentences. So the words so far are peeked at this often, and
# a skip or her name cuts her off at once; the whole utterance still follows.
PEEK_EVERY_MS = 480
PEEKS_MAX = 6
PTT_TAIL_S = 0.25                # keep recording a moment after the key is released
PTT_MAX_S = 60.0                 # a stuck key must not record for ever
SHORT_UTTERANCE_S = 2.0          # at or under this, check for "send"/"nevermind" first
BLUETOOTH_RECHECK_S = 30.0       # the default source can change; asking costs a process
MAX_BACKOFF_S = 60.0
# After the wake phrase, this much more speech in the same breath is a command
# said with it ("wake Aries, play something"); less is a breath or the phrase's tail.
WOKE_WORDS_MS = 250
UNLOAD_CHECK_S = 2.0             # how often idle Whisper models are looked at


class Listener:
    def __init__(self, dialogue, transcriber, *, wake_enabled, is_speaking, barge_in=True,
                 status=None, spotting=None, spot_failed=None, find_recorder=mic.find_recorder,
                 popen=subprocess.Popen, bluetooth=mic.bluetooth_mic, clock=time.monotonic) -> None:
        self.dialogue, self.transcriber = dialogue, transcriber
        self.wake_enabled, self.is_speaking, self.barge_in = wake_enabled, is_speaking, barge_in
        # The wake model when it is the one listening for her name, else None (Whisper listens).
        self.spotting = spotting or (lambda: None)
        self._spot_failed = spot_failed or (lambda exc: None)
        self._status = status or (lambda text: None)
        self._find_recorder, self._popen, self._bluetooth = find_recorder, popen, bluetooth
        self.clock = clock
        self._stop = threading.Event()
        self._poke = threading.Event()          # something changed: re-decide whether the mic is wanted
        self._threads: list[threading.Thread] = []
        self._process = None
        self._pending: queue.Queue = queue.Queue()
        self._ptt_down = False
        self._peeking = False                   # one peek in flight at a time
        self._ptt_release_at = 0.0
        self._wake_ok: tuple[float, bool] = (-1e9, True)
        self._woke_at: int | None = None        # frames into the utterance where the wake model fired
        self._spot_stale = True                 # it missed audio: reset before trusting it again
        self._her_voice = False
        self._unload_at = 0.0
        self._her_quiet_at = 0.0         # when she last stopped talking (clock)
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
    def ptt_recording(self) -> bool:
        return self._ptt_down

    def push_to_talk(self, down: bool) -> None:
        if down:
            self._ptt_down, self._ptt_release_at = True, 0.0
            self.dialogue.set_ptt(True)
            if self.spotting() is not None:
                self.transcriber.prefetch(self.transcriber.command_model())    # loads while he talks
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
        peek_at = PEEK_EVERY_MS
        ptt_frames: list[bytes] = []
        ptt_started = 0.0
        d = self.dialogue
        self._spot_stale = True                 # a fresh recorder: what it heard before is gone
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
                    self._woke_at, self._spot_stale = None, True
                ptt_frames.append(frame)
                released = not self._ptt_down and now >= self._ptt_release_at
                if released or now - ptt_started > PTT_MAX_S:
                    self._submit(b"".join(ptt_frames), PTT)
                    ptt_frames, self._ptt_release_at = [], 0.0
                    self._ptt_down = False
                    d.set_ptt(False)
                continue

            # Fully deaf only through the chime, a loud noise a foot from the mic.
            # Deaf, not discarding: once she is open he may already be talking over
            # it, so the audio is held and leads in his first utterance.
            if now < d.deaf_until:
                if d.awake and not seg.speaking:
                    seg.hold(frame)
                else:
                    seg.reset()
                self._woke_at, self._spot_stale = None, True
                continue
            her_voice = bool(self.is_speaking())
            spotter = self.spotting()
            if spotter is not None and her_voice and not self._her_voice:
                # Over her voice only Whisper hears "skip"; tiny.en is loaded while she talks.
                self.transcriber.prefetch(transcribe.WAKE_MODEL)
            if self._her_voice and not her_voice:
                self._her_quiet_at = self.clock()
            self._her_voice = her_voice
            if her_voice and not self.barge_in:
                seg.reset()
                self._spot_stale = True
                continue
            if spotter is not None and self._woke_at is None and not d.awake:
                if self._spot(spotter, frame):
                    self._woken(spotter, seg, her_voice)
            else:
                self._spot_stale = True
            utterance = seg.feed(frame, her_voice=her_voice, awake=d.awake)
            if self._woke_at is not None and not seg.speaking:
                self._after_wake(utterance, seg)
            elif utterance is not None:
                # While she works on a reply, the open mic is held to the rules for
                # over her voice: her name or a skip, nothing else. Otherwise talk in
                # the room is drafted while she works and sent the moment she's done.
                busy = d.mode == OPEN and d.is_busy()
                mode = OVER if utterance.interrupting or busy else d.mode
                if mode != IDLE or spotter is None:
                    self._submit(utterance.pcm, mode)
                # else: not woken, and the wake model is what listens -- never transcribed
            elif not seg.speaking:
                peek_at = PEEK_EVERY_MS
                d.tick()            # nothing is said or about to be: the safe moment to decide a sentence ended
            elif seg.interrupting and her_voice and not self._peeking and seg.speech_ms >= peek_at \
                    and peek_at <= PEEK_EVERY_MS * PEEKS_MAX and self._woke_at is None:
                peek_at += PEEK_EVERY_MS
                self._peeking = True
                self._pending.put((b"".join(seg.buffer), "peek"))
            d.expire()

    # ------------------------------------------------------------ the wake model
    def _spot(self, spotter, frame: bytes) -> bool:
        try:
            if self._spot_stale:
                spotter.reset()
                self._spot_stale = False
            return spotter.feed(frame)
        except Exception as exc:
            self._spot_failed(exc)          # she goes back to Whisper for her name
            return False

    def _woken(self, spotter, seg, her_voice: bool) -> None:
        """The wake model heard the phrase. Load what will hear the words now, so it
        loads while he says them. Mid-sentence, opening waits for him to finish:
        the chime and its deafness would cut off "wake Aries, play something"."""
        log.info("ears: heard the wake phrase (%.2f)", spotter.score)
        t = self.transcriber
        for name in dict.fromkeys((t.command_model(), t.control_model())):
            t.prefetch(name)
        d = self.dialogue
        if not seg.speaking:
            d.named(OVER if her_voice else IDLE)
            return
        self._woke_at = len(seg.buffer)
        if her_voice or d.is_busy():
            # But she stops now, not when he does.
            d.cut_off("heard the wake phrase" + (" over her voice" if her_voice else " while she worked"))

    def _after_wake(self, utterance, seg) -> None:
        """The breath with the wake phrase in it has ended: open, and if he went
        on talking after the phrase, have those words transcribed as the command."""
        woke_at, self._woke_at = self._woke_at, None
        self.dialogue.named(IDLE)           # (anyone talking or working was cut off when it fired)
        if utterance is None:
            return
        frames = [utterance.pcm[i:i + mic.FRAME_BYTES]
                  for i in range(woke_at * mic.FRAME_BYTES, len(utterance.pcm), mic.FRAME_BYTES)]
        gate = seg.threshold() * mic.HOLD
        if sum(mic.FRAME_MS for f in frames if mic.rms(f) >= gate) >= WOKE_WORDS_MS:
            self._submit(utterance.pcm, WOKE, b"".join(frames))

    def _unload_idle(self) -> None:
        """With the wake model listening, Whisper is dropped once nobody has needed it
        for a while; never while she talks or listens, when it is about to be."""
        now = self.clock()
        if now < self._unload_at:
            return
        self._unload_at = now + UNLOAD_CHECK_S
        if self.spotting() is None or self.dialogue.awake or self.dialogue.ptt \
                or self.is_speaking() or not self._pending.empty() \
                or now - self._her_quiet_at < transcribe.IDLE_UNLOAD_S:
            return
        self.transcriber.unload_idle()

    # -------------------------------------------------------------- the worker
    def _submit(self, pcm: bytes, mode: str, rest: bytes = b"") -> None:
        """Hand an utterance off. The queue is what holds his words while Whisper
        loads (the worker waits for the model; the mic never does), so anything said
        to her -- push-to-talk, or with her open -- is never dropped. Room talk and
        speech over her voice are: dropping those beats answering minutes late."""
        if mode in (IDLE, OVER) and self._pending.qsize() >= 2:
            self.dropped += 1
            return
        self.dialogue.began()
        self._pending.put((pcm, mode, rest))

    def _work(self) -> None:
        """Transcribe and act, well away from the thread holding the mic."""
        while not self._stop.is_set():
            try:
                item = self._pending.get(timeout=0.5)
            except queue.Empty:
                try:
                    self._unload_idle()
                except Exception as exc:
                    log.warning("ears: couldn't unload idle models: %s", exc)
                continue
            if item is None:
                return
            if item[1] == "peek":
                try:
                    text, _sure = self._transcribe(item[0], OVER)
                    self.dialogue.peek(text)
                except Exception as exc:
                    log.warning("ears: couldn't peek: %s", exc)
                finally:
                    self._peeking = False
                continue
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

    def _transcribe(self, pcm: bytes, mode: str, rest: bytes = b"") -> tuple[str, bool]:
        t, names = self.transcriber, self.dialogue.names
        seconds = len(pcm) / 2 / mic.RATE
        if mode == PTT:
            h = t.hear(pcm, t.command_model(), transcribe.COMMAND_HINT)
        elif mode == WOKE:
            # The whole breath, so the words keep their first consonant; the phrase
            # comes back as her name nearly always, and what follows it is the command.
            h = t.hear(pcm, t.command_model(), f"{wakeword.HINT} {transcribe.COMMAND_HINT}")
            if names.heard_name(h.text) is None and rest:
                # It wrote the phrase as something else: keep only what came after it.
                h = t.hear(rest, t.command_model(), transcribe.COMMAND_HINT)
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
