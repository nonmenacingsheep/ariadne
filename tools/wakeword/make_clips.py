"""Synthesise the clips the wake model learns from: "wake Aries", and what it must not be.

    python make_clips.py --piper <piper-sample-generator> --out <run>/wake_aries

Writes 16 kHz WAVs into the four folders openWakeWord's train.py expects
(positive_train, positive_test, negative_train, negative_test), so its own
generation step finds them full and skips. Done here rather than by train.py
because its generator walks speakers in order (the first 904 clips are all
speaker 0 blended with someone), and because the near misses below are the
ones that matter for this phrase and its generic adversarial list misses them.

Every clip is a fresh blend of two of LibriTTS-R's 904 speakers, at a random
speed and expressiveness. Resumable: a folder already holding enough is left.
"""
from __future__ import annotations

import argparse
import random
import sys
import uuid
import wave
from pathlib import Path

POSITIVE = ("wake Aries", "wake Aries.", "Wake Aries!", "wake, Aries.", "Wake Aries?",
            "wake Aries,", "Wake Aries...", "wake aries")

# Said near the machine all day, and close enough to the phrase to be worth
# teaching as "no". Homophones of the phrase ("wake Ares", "wake airies") are
# left out on purpose: they are the phrase, and teaching them as negatives
# would only make it deaf.
NEAR_MISSES = (
    "make a ruse", "make a ruse.", "wake up", "wake up!", "wake", "awake", "Aries", "Aries.",
    "wait, Harry's", "wait, Harry's here", "hey Aries", "hey Aries.", "hi Aries", "okay Aries",
    "yo Aries", "Aries, wake up", "wake Larry's", "wake Harry", "wake Harry's", "wake Gary's",
    "wake Mary's", "wake every", "wake her", "wake her up", "wake theories", "wake Ari",
    "wake Iris", "wake arrays", "wake area", "wake Eric", "wake Aaron", "wake Arizona",
    "make airy", "take a rest", "take a reason", "bake a pie", "make it easy", "make a reservation",
    "what's that", "way carries", "great series", "the series", "rake the leaves", "wait, it is",
    "wake Erin's", "make a wish", "weekend series", "a wake of ease", "make Harry's", "fake Aries",
    "lake Erie's", "wake Siri", "hey Siri", "Alexa", "okay Google", "hey Jarvis", "wake word",
    "wait a second", "wait, really?", "waiting", "wakeful", "Wake Forest", "awakening", "Ariel",
    "Arya", "Aries is my sign", "aerial", "hairy", "carries", "berries", "cherries", "ferries",
    "wake the kids", "it's late, Harry", "we carry these", "way to go", "make dinner",
)

LENGTHS = (0.7, 0.8, 0.9, 1.0, 1.0, 1.1, 1.25, 1.4)       # speaking speed: 0.7 is quick, 1.4 slow
NOISE = (0.5, 0.667, 0.8, 0.98)
NOISE_W = (0.6, 0.8, 0.98)
RATE = 16000


def phrases_for_negatives(n: int) -> list[str]:
    """Half the hand list, half openWakeWord's phoneme-overlap generator."""
    from openwakeword.data import generate_adversarial_texts
    made = generate_adversarial_texts(input_text="wake aries", N=n // 2,
                                      include_partial_phrase=1.0, include_input_words=0.2)
    return [random.choice(NEAR_MISSES) for _ in range(n - len(made))] + list(made)


def synthesise(texts: list[str], out: Path, model_path: Path, batch: int) -> None:
    import json

    import numpy as np
    import torch
    import torchaudio
    from piper_sample_generator.__main__ import audio_float_to_int16, generate_audio, get_phonemes

    out.mkdir(parents=True, exist_ok=True)
    model = torch.load(model_path, weights_only=False).eval()
    cuda = torch.cuda.is_available()
    if cuda:
        model.cuda()
    config = json.loads(Path(f"{model_path}.json").read_text("utf-8"))
    voice, sr, speakers = config["espeak"]["voice"], config["audio"]["sample_rate"], config["num_speakers"]
    resample = torchaudio.transforms.Resample(sr, RATE)
    done = 0
    while done < len(texts):
        chunk = texts[done:done + batch]
        ids = [get_phonemes(voice, config, t) for t in chunk]
        longest = max(map(len, ids))
        ids = [i + [1] * (longest - len(i)) for i in ids]          # pad with '^', as piper does
        s1 = torch.LongTensor([random.randrange(speakers) for _ in chunk])
        s2 = torch.LongTensor([random.randrange(speakers) for _ in chunk])
        with torch.no_grad():
            audio, samples = generate_audio(model, s1, s2, ids, random.random(), random.choice(NOISE),
                                            random.choice(NOISE_W), random.choice(LENGTHS), None)
            ends = [int((samples[i].flatten().sum().item() + 1) * RATE / sr) for i in range(audio.shape[0])]
            audio = resample(audio.cpu())
        pcm = audio_float_to_int16(audio.numpy())
        for i in range(pcm.shape[0]):
            data = np.trim_zeros(pcm[i].flatten()[:ends[i]])
            with wave.open(str(out / f"{uuid.uuid4().hex}.wav"), "wb") as w:
                w.setframerate(RATE)
                w.setsampwidth(2)
                w.setnchannels(1)
                w.writeframes(data.tobytes())
        done += len(chunk)
        print(f"\r{out.name}: {done}/{len(texts)}", end="", file=sys.stderr, flush=True)
    print(file=sys.stderr)
    if cuda:
        torch.cuda.empty_cache()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--piper", required=True, type=Path, help="the piper-sample-generator checkout")
    ap.add_argument("--model", type=Path, help="generator .pt (default: its models/en_US-libritts_r-medium.pt)")
    ap.add_argument("--out", required=True, type=Path, help="<output_dir>/<model_name> from the training yml")
    ap.add_argument("--n", type=int, default=30000, help="training clips of each kind")
    ap.add_argument("--n-val", type=int, default=3000, help="held-out clips of each kind")
    ap.add_argument("--batch", type=int, default=48)
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    sys.path.insert(0, str(a.piper.resolve()))                 # piper_train lives beside the package
    random.seed(a.seed)
    model = a.model or a.piper / "models" / "en_US-libritts_r-medium.pt"
    jobs = (("positive_train", a.n, True), ("positive_test", a.n_val, True),
            ("negative_train", a.n, False), ("negative_test", a.n_val, False))
    for folder, n, positive in jobs:
        out = a.out / folder
        have = len(list(out.glob("*.wav"))) if out.exists() else 0
        if have >= 0.95 * n:
            print(f"{folder}: {have} already", file=sys.stderr)
            continue
        texts = [random.choice(POSITIVE) for _ in range(n - have)] if positive \
            else phrases_for_negatives(n - have)
        random.shuffle(texts)
        # Similar lengths per batch: the padding of a short line to a long one is wasted work.
        texts.sort(key=len)
        synthesise(texts, out, model, a.batch)


if __name__ == "__main__":
    main()
