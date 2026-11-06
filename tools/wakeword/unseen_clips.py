"""Test clips in six Piper voices no training clip uses (voices.py UNSEEN), for evaluate.py
--unseen and ears_sweep.py.

    python unseen_clips.py <dir of the six .onnx voices> <out dir>

Writes out/pos ("hey Aries" three ways), out/cmd (the phrase with a command after it),
out/neg (near misses and ordinary sentences) and out/old (the retired "wake Aries"), each at
three speeds: 54, 18, 180 and 54 clips.
"""
import io
import sys
import wave
from pathlib import Path

import numpy as np
from piper import PiperVoice, SynthesisConfig
from scipy.signal import resample_poly

POS = ["Hey Aries.", "hey Aries", "Hey, Aries!"]
NEG = ["Hey there.", "Hey Harry.", "Hey Siri.", "Hey Ari.", "Aries.", "Okay Aries.",
       "Hey, are you ready?", "Hey!", "The weather is nice today.", "Make a reservation for two."]
CMD = ["Hey Aries, play some music."]
OLD = ["Wake Aries.", "wake Aries", "Wake, Aries!"]    # the retired phrase: should no longer wake her


def main() -> None:
    voices, out = Path(sys.argv[1]), Path(sys.argv[2])
    for d in ("pos", "neg", "cmd", "old"):
        (out / d).mkdir(parents=True, exist_ok=True)
    for vp in sorted(voices.glob("*.onnx")):
        v = PiperVoice.load(str(vp))
        for scale in (0.85, 1.0, 1.2):
            for kind, texts in (("pos", POS), ("neg", NEG), ("cmd", CMD), ("old", OLD)):
                for i, t in enumerate(texts):
                    buf = io.BytesIO()
                    with wave.open(buf, "wb") as w:
                        v.synthesize_wav(t, w, SynthesisConfig(length_scale=scale))
                    buf.seek(0)
                    with wave.open(buf) as w:
                        sr, a = w.getframerate(), np.frombuffer(w.readframes(w.getnframes()), "<i2")
                    a = resample_poly(a.astype("float32"), 16000, sr).astype("<i2")
                    with wave.open(str(out / kind / f"{vp.stem}_{scale}_{i}.wav"), "wb") as w:
                        w.setframerate(16000)
                        w.setsampwidth(2)
                        w.setnchannels(1)
                        w.writeframes(a.tobytes())


if __name__ == "__main__":
    main()
