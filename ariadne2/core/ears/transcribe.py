"""Speech to text, locally: faster-whisper. Carried over from 1.x ears.py.

Everything runs on this machine; no audio or transcript leaves it, and there
is no key. The package is imported lazily so a machine without it degrades to
"can't hear" rather than failing to start.
"""
from __future__ import annotations

import array
import importlib.util
import logging
import os
import threading
from dataclasses import dataclass

from . import gpu

log = logging.getLogger("ariadne2.ears")

RATE = 16000                     # what Whisper wants

# Two models, because the two jobs want different things. Spotting the wake
# phrase wants speed, and tiny.en is also measurably better at a short name
# than base ("hey Ida" came back "hey either" often enough to lose wakes).
# Once she is open the words matter, so a larger model takes over.
WAKE_MODEL = "tiny.en"
COMMAND_MODEL_CPU = "base.en"          # 450ms on a CPU, 35ms on a GPU
COMMAND_MODEL_GPU = "large-v3-turbo"   # 92.9% vs 89.5%: +3.5 points for 95ms on a card,
                                       # but 6.4s on a CPU, which is why it is GPU-only

# Primed with the words this desktop involves, which is how "firebox" becomes Firefox.
COMMAND_HINT = ("Commands to a desktop assistant about music, Spotify, Steam games, Discord, "
                "Firefox, files, folders, downloads, and Claude Code.")
# "Send" is one short word and the command prompt actively works against it
# (base.en rendered "send it" as "Steam games"); a separate prompt and the
# smaller model get every control word right in half the time.
CONTROL_HINT = "Send. Send it. Send that. Nevermind. Go ahead. That's all."

# Whisper never says "I did not catch that": it returns fluent words whatever it
# heard. Below this average log probability it was guessing.
UNSURE_BELOW = -0.85
# Whisper is markedly better on well-levelled audio (about nine points on quiet
# input). Capped so near-silence is not amplified into hiss it hallucinates from.
TARGET_PEAK = 0.7
MAX_GAIN = 40.0


@dataclass
class Heard:
    text: str
    confidence: float = 0.0

    @property
    def sure(self) -> bool:
        return self.confidence >= UNSURE_BELOW


def levelled(pcm: bytes):
    """16-bit mono PCM to float samples brought up to a consistent loudness."""
    try:
        import numpy as np
    except ImportError:               # faster-whisper needs it too; this keeps tests honest
        raw = array.array("h")
        raw.frombytes(pcm[:len(pcm) // 2 * 2])
        peak = max((abs(s) for s in raw), default=0) / 32768.0
        gain = min(TARGET_PEAK / peak, MAX_GAIN) if peak > 0 else 1.0
        return array.array("f", (s / 32768.0 * gain for s in raw))
    samples = np.frombuffer(pcm, dtype="<i2").astype("float32") / 32768.0
    peak = float(np.max(np.abs(samples))) if samples.size else 0.0
    return samples * min(TARGET_PEAK / peak, MAX_GAIN) if peak > 0 else samples


class Transcriber:
    def __init__(self, model_factory=None, device: tuple | None = None) -> None:
        self._factory = model_factory           # (name, device, compute_type) -> model
        self._device = device
        self._models: dict = {}
        self._lock = threading.Lock()

    @staticmethod
    def missing() -> str | None:
        """What is absent, found without importing the heavy package."""
        for pkg in ("faster_whisper", "numpy"):
            if importlib.util.find_spec(pkg) is None:
                return (f"{pkg.replace('_', '-')} isn't installed for this Python "
                        "(pip install faster-whisper)")
        return None

    def available(self) -> str | None:
        return None if self._factory else self.missing()

    def device(self) -> tuple[str, str]:
        """GPU when it genuinely works, CPU otherwise -- and never an error: a
        transcription that runs slowly beats one that does not run."""
        if self._device is None:
            wanted = (os.environ.get("ARIADNE2_SPEECH_DEVICE") or "auto").lower()
            if wanted == "cpu" or not gpu.cuda_works():
                self._device = ("cpu", "int8")
            else:
                self._device = ("cuda", "float16")
        return self._device

    def command_model(self) -> str:
        return COMMAND_MODEL_GPU if self.device()[0] == "cuda" else COMMAND_MODEL_CPU

    def control_model(self) -> str:
        """Measured on 152 synthesised clips: tiny.en missed one clean "send" in eight
        and one noisy in four; the command model got all of them. On CPU, base.en."""
        return self.command_model() if self.device()[0] == "cuda" else "base.en"

    def load(self, name: str):
        with self._lock:
            if name in self._models:
                return self._models[name]
            factory = self._factory
            if factory is None:
                from faster_whisper import WhisperModel as factory
            where, precision = self.device()
            try:
                model = factory(name, device=where, compute_type=precision)
                if where != "cpu":
                    # Prove it before trusting it: building the model touches none of
                    # the maths libraries; the first transcription does.
                    list(model.transcribe(array.array("f", [0.0] * (RATE // 2)),
                                          beam_size=1, language="en")[0])
            except Exception as exc:
                if where == "cpu":
                    raise
                log.warning("ears: GPU speech failed (%s); using the CPU", str(exc)[:100])
                self._device = ("cpu", "int8")
                model = factory(name, device="cpu", compute_type="int8")
            self._models[name] = model
            return model

    def hear(self, pcm: bytes, model: str, hint: str) -> Heard:
        """Transcribe, and keep how sure the model was."""
        segments, _ = self.load(model).transcribe(
            levelled(pcm), beam_size=1, language="en", vad_filter=True,
            condition_on_previous_text=False, initial_prompt=hint)
        parts, scores = [], []
        for seg in segments:
            parts.append(seg.text)
            score = getattr(seg, "avg_logprob", None)
            if score is not None:
                scores.append(float(score))
        return Heard(" ".join(p.strip() for p in parts).strip(), sum(scores) / len(scores) if scores else 0.0)

    def warm(self, name: str) -> None:
        """One throwaway transcription so the first real one isn't the slow one."""
        try:
            # The result is lazy; the decoding (and the first-use cost) happens on iteration.
            list(self.load(name).transcribe(array.array("f", [0.0] * (RATE // 2)),
                                            beam_size=1, language="en")[0])
        except Exception:
            pass

    def unload(self) -> int:
        """Drop the models and give the card its memory back (2.3 GB on his)."""
        with self._lock:
            dropped = len(self._models)
            self._models.clear()
        if dropped:
            import gc
            gc.collect()
        return dropped
