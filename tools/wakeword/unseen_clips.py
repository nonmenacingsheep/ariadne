"""Test clips in six Piper voices no training clip uses (voices.py UNSEEN), for evaluate.py
--unseen and ears_sweep.py.

    python unseen_clips.py <dir of the six .onnx voices> <out dir>

Writes out/pos ("wake Aries" three ways), out/cmd (the phrase with a command after it) and
out/neg (near misses and ordinary sentences), each at three speeds: 54, 18 and 180 clips.
"""
import io
import sys
import wave
from pathlib import Path

import numpy as np
from piper import PiperVoice, SynthesisConfig
from scipy.signal import resample_poly

POS = ["Wake Aries.", "wake Aries", "Wake, Aries!"]
NEG = ["Make a ruse.", "Hey Aries.", "Wake up.", "Aries.", "Wait, Harry's here.", "Wake Harry.",
       "The weather is nice today.", "Make a reservation for two.", "Okay Aries.", "Wake every one of them."]
CMD = ["Wake Aries, play some music."]


def main() -> None:
    voices, out = Path(sys.argv[1]), Path(sys.argv[2])
    for d in ("pos", "neg", "cmd"):
        (out / d).mkdir(parents=True, exist_ok=True)
    for vp in sorted(voices.glob("*.onnx")):
        v = PiperVoice.load(str(vp))
        for scale in (0.85, 1.0, 1.2):
            for kind, texts in (("pos", POS), ("neg", NEG), ("cmd", CMD)):
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
