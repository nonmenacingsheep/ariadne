"""The wake phrase, heard by a model of its own: openWakeWord on the CPU.

Listening for her name with Whisper meant transcribing everything said near
the machine and keeping the big model on the card in case she was addressed
(2.3 GB of his VRAM, all day). This is a few hundred kilobytes that scores
every 80 ms of sound for one phrase, "hey Aries", and nothing else: no words
come out of it, so nothing said in the room is ever written down until she
has been woken. Whisper is only loaded once she has been.

Trained for this phrase alone (tools/wakeword/ says how, and how to retrain),
so it only stands in while her name is the one it knows; renamed, she falls
back to Whisper listening for "hey <name>". Missing the package or the model
file does the same, logged once by the caller.
"""
from __future__ import annotations

import importlib.util
import logging
import threading
from pathlib import Path

log = logging.getLogger("ariadne2.ears")

MODELS = Path(__file__).with_name("models")
MODEL = MODELS / "hey_aries.onnx"
# openWakeWord's shared front end: sound to a melspectrogram to Google's speech embedding.
MELSPEC = MODELS / "melspectrogram.onnx"
EMBEDDING = MODELS / "embedding_model.onnx"
PHRASE = "hey Aries"
HINT = "Hey Aries."             # Whisper's prompt for a breath that started with it
NAME = "aries"                   # the only name the model was trained on

# The score that counts as the phrase. tools/wakeword/evaluate.py prints false
# accepts per hour and recall at several; lower hears him more often and
# wakes on the room more often.
THRESHOLD = 0.3
CHUNK = 1280                     # samples per prediction (80 ms), what the model is built around


class Spotter:
    """Feed it the mic; it says when the phrase was said."""

    def __init__(self, model: Path | str = MODEL, threshold: float = THRESHOLD, factory=None) -> None:
        self.path = Path(model)
        self.threshold = threshold
        self._factory = factory           # (path) -> object with predict(np.int16 array) and reset()
        self._model = None
        self._lock = threading.Lock()
        self._pending = b""
        self.score = 0.0                  # the last score, for the log

    @staticmethod
    def missing(path: Path = MODEL) -> str | None:
        """What is absent, found without importing anything heavy."""
        for pkg in ("openwakeword", "onnxruntime", "numpy"):
            if importlib.util.find_spec(pkg) is None:
                return f"{pkg} isn't installed for this Python (pip install openwakeword onnxruntime)"
        for need in (Path(path), MELSPEC, EMBEDDING):
            if not need.is_file():
                return f"the wake model file {need.name} is missing"
        return None

    def available(self) -> str | None:
        return None if self._factory else self.missing(self.path)

    def load(self):
        with self._lock:
            if self._model is None:
                if self._factory is not None:
                    self._model = self._factory(self.path)
                else:
                    from openwakeword.model import Model
                    self._model = Model(wakeword_models=[str(self.path)], inference_framework="onnx",
                                        melspec_model_path=str(MELSPEC), embedding_model_path=str(EMBEDDING))
            return self._model

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def feed(self, pcm: bytes) -> bool:
        """16-bit mono 16 kHz audio, any amount. True when the phrase has just been said;
        it then starts afresh, so the same breath can't wake her twice."""
        import numpy as np
        self._pending += pcm
        fired = False
        while len(self._pending) >= CHUNK * 2:
            chunk, self._pending = self._pending[:CHUNK * 2], self._pending[CHUNK * 2:]
            scores = self.load().predict(np.frombuffer(chunk, dtype="<i2"))
            self.score = max(scores.values(), default=0.0)
            if self.score >= self.threshold:
                fired = True
                self.reset()
                break
        return fired

    def reset(self) -> None:
        """Forget what it has heard (after a wake, and after the mic was deaf or elsewhere)."""
        self._pending = b""
        if self._model is not None:
            self._model.reset()
