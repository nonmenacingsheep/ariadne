"""Split Ronald's recording of Part A and B into takes and transcribe each one.

    <core venv>/python ronald_segment.py <dir>      # <dir> holds ab16.wav (mono 16 kHz)

Writes segs2.json (start, end and a transcript for every stretch of speech) and cuts_a4.json (where
"hey Aries" ends in the takes that run on into a command). He left about a second between takes, not
two, so the split is at gaps of 0.2 s or more over a floor that follows the room (10th percentile
over 6 s, plus 14 dB), and Whisper (faster-whisper medium.en, on the CPU) says what each stretch is.
Whisper writes "Aries" as Ares, areas and the like, so ronald_build.py labels by block position and
a loose pattern, and leaves out whatever does not look like the phrase. Needs numpy and
faster-whisper (the core's venv has both); the audio and everything derived from it stay in <dir>.
"""
import json
import re
import sys
import wave
from pathlib import Path

import numpy as np
from faster_whisper import WhisperModel

SR = 16000


def load(path: Path):
    w = wave.open(str(path))
    return np.frombuffer(w.readframes(w.getnframes()), "<i2").astype("float32") / 32768


def segments(a):
    fr = SR // 100
    n = len(a) // fr
    db = 20 * np.log10(np.sqrt((a[:n * fr].reshape(n, fr) ** 2).mean(1)) + 1e-9)
    padded = np.pad(db, 300, mode="edge")
    floor = np.percentile(np.lib.stride_tricks.sliding_window_view(padded, 601), 10, axis=1)[:n]
    act = db > floor + 14
    out, i = [], 0
    while i < n:
        if not act[i]:
            i += 1
            continue
        last = j = i
        while j < n and j - last < 20:
            if act[j]:
                last = j
            j += 1
        out.append((i * 0.01, (last + 1) * 0.01))
        i = last + 1
    return [s for s in out if s[1] - s[0] > 0.2], db, floor


def main() -> None:
    d = Path(sys.argv[1])
    a = load(d / "ab16.wav")
    segs, db, floor = segments(a)
    model = WhisperModel("medium.en", device="cpu", compute_type="int8", cpu_threads=4)

    def prep(s, e):
        x = np.concatenate([np.zeros(SR // 4, "float32"), a[max(0, int((s - 0.25) * SR)):int((e + 0.25) * SR)],
                            np.zeros(SR // 4, "float32")])
        return x * (0.5 / max(1e-3, float(np.abs(x).max())))

    out = []
    for s, e in segs:
        r, _ = model.transcribe(prep(s, e), language="en", beam_size=5, temperature=0.0,
                                condition_on_previous_text=False, without_timestamps=True)
        out.append(dict(s=round(s, 2), e=round(e, 2), floor=round(float(floor[int(s * 100)]), 1),
                        pk=round(float(db[int(s * 100):int(e * 100) + 1].max()), 1),
                        text=" ".join(z.text.strip() for z in r)))
    json.dump(out, open(d / "segs2.json", "w"), indent=0)
    # Block 4 (a command after it): where does "Aries" end? Words with timestamps.
    cuts = {}
    for k, seg in enumerate(out):
        if not (77 <= k <= 120) or seg["e"] - seg["s"] < 0.95 or not re.match(r"(hey|he|hate|hay)\b", seg["text"].lower()):
            continue
        r, _ = model.transcribe(prep(seg["s"], seg["e"]), language="en", word_timestamps=True, beam_size=5,
                                temperature=0.0, condition_on_previous_text=False)
        words = [(w.word.strip(), w.end) for z in r for w in z.words][:3]
        end = next((seg["s"] - 0.5 + t for i, (w, t) in enumerate(words) if i >= 1 and re.search(r"(ar|air|er)", w.lower())), None)
        cuts[k] = dict(end=None if end is None else round(end, 2))
    json.dump(cuts, open(d / "cuts_a4.json", "w"))
    print(len(out), "segments;", len(cuts), "cuts")


if __name__ == "__main__":
    main()
