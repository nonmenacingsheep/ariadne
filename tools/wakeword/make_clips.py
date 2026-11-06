"""Synthesise the clips the wake model learns from: "wake Aries", and what it must not be.

    python make_clips.py --piper <piper-sample-generator> --out <run>/wake_aries [--voices voices.json]

Writes 16 kHz WAVs into the four folders openWakeWord's train.py expects
(positive_train, positive_test, negative_train, negative_test), so its own
generation step finds them full and skips. Done here rather than by train.py
because its generator walks speakers in order (the first 904 clips are all
speaker 0 blended with someone), and because the near misses below are the
ones that matter for this phrase and its generic adversarial list misses them.

Every clip is a fresh blend of two of LibriTTS-R's 904 speakers, at a random
speed and expressiveness. Resumable: a folder already holding enough is left.

With --voices (from voices.py; round 2, after the first model missed fast and
low voices -- his), three in four clips come from low voices, a third of all
clips from Piper's own voices (male singles and every speaker of the
multi-speaker ones), a fifth are muffled and quieter, and the phrase is also
said with a pause and at the end of a sentence. Near misses get the same voice
mix, so "a low voice" can't be what it learns as "wake Aries".
"""
from __future__ import annotations

import argparse
import logging
import json
import random
import sys
import uuid
import wave
from pathlib import Path

POSITIVE = ("wake Aries", "wake Aries.", "Wake Aries!", "wake, Aries.", "Wake Aries?",
            "wake Aries,", "Wake Aries...", "wake aries")
# Round 2: a pause in the middle, and the phrase at the end of something longer.
PAUSED = ("wake, Aries", "Wake, Aries!", "wake... Aries", "Wake... Aries.", "Wake. Aries.",
          "wake -- Aries")
LEAD_INS = ("okay", "okay,", "alright,", "hey,", "right,", "uh,", "um,", "so,", "come on,",
            "yo,", "okay so", "hang on,")

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
# Round 2: what it woke on, and the nearest neighbours of the new pause and lead-in forms.
NEAR_MISSES_2 = (
    "wake Harry", "Wake Harry.", "wake, Harry", "wake... Harry", "wake Ari", "wake, Ari",
    "wake carries", "Wake carries.", "make Aries", "Make Aries.", "make, Aries", "take Aries",
    "bake Aries", "wake Larry", "wake Gary", "wake Barry", "wake Carrie's", "okay, wake Harry",
    "okay, make Aries", "okay, wake up", "alright, wake up", "hey, Aries", "okay, Aries",
    "wake... Harry's", "wait, Aries", "wait... Harry", "make a ruse, okay",
)

LENGTHS = (0.7, 0.8, 0.9, 1.0, 1.0, 1.1, 1.25, 1.4)       # speaking speed: 0.7 is quick, 1.4 slow
NOISE = (0.5, 0.667, 0.8, 0.98)
NOISE_W = (0.6, 0.8, 0.98)
RATE = 16000
# Round 2 (--voices)
LENGTHS_2 = (0.62, 0.68, 0.72, 0.76, 0.8, 0.85, 0.9, 1.0, 1.0, 1.1, 1.25)
NOISE_2 = (0.5, 0.667, 0.8, 0.98, 1.1)
LOW_SHARE = 0.75                 # clips in a low voice
PIPER_SHARE = 0.33               # clips from Piper's own voices rather than the generator
SOFT_SHARE = 0.2                 # muffled (low-passed) and quieter: mumbled, or off-axis
MAX_S = 1.9                      # augmentation keeps the first 2 s, so keep the phrase's end


def positive_texts(n: int, round2: bool) -> list[str]:
    if not round2:
        return [random.choice(POSITIVE) for _ in range(n)]
    out = []
    for _ in range(n):
        r = random.random()
        if r < 0.45:
            out.append(random.choice(POSITIVE))
        elif r < 0.7:
            out.append(random.choice(PAUSED))
        else:
            out.append(f"{random.choice(LEAD_INS)} {random.choice(POSITIVE + PAUSED[:2]).lower()}")
    return out


def soften(audio):
    """Muffle and quieten (a float array): a mumble, or speech from across the room."""
    import numpy as np
    from scipy.signal import butter, sosfilt
    sos = butter(4, random.uniform(1100, 3000), btype="low", fs=RATE, output="sos")
    return sosfilt(sos, audio) * 10 ** (-random.uniform(4, 14) / 20) / max(1e-6, float(np.abs(audio).max()))


def finish(pcm, soft: bool):
    """int16 clip -> trimmed, maybe softened, capped to its last MAX_S."""
    import numpy as np
    data = np.trim_zeros(pcm)
    if soft and data.size:
        data = (np.clip(soften(data.astype("float32") / 32768.0), -1, 1) * 32767).astype("<i2")
    return data[-int(MAX_S * RATE):]


def write(path: Path, data) -> None:
    with wave.open(str(path), "wb") as w:
        w.setframerate(RATE)
        w.setsampwidth(2)
        w.setnchannels(1)
        w.writeframes(data.tobytes())


_VOICES: dict = {}


def piper_clip(job) -> None:
    """One clip from a Piper voice (in a worker process: CPU onnxruntime, two threads)."""
    import io

    import numpy as np
    import onnxruntime
    from piper import PiperVoice, SynthesisConfig
    from piper.config import PiperConfig
    from piper.voice import ESPEAK_DATA_DIR
    from scipy.signal import resample_poly
    text, model, speaker, length, noise, noise_w, soft, seed, path = job
    random.seed(seed)
    voice = _VOICES.get(model)
    if voice is None:
        opts = onnxruntime.SessionOptions()
        opts.intra_op_num_threads, opts.inter_op_num_threads = 2, 1
        voice = _VOICES[model] = PiperVoice(
            config=PiperConfig.from_dict(json.loads(Path(f"{model}.json").read_text("utf-8"))),
            session=onnxruntime.InferenceSession(model, sess_options=opts, providers=["CPUExecutionProvider"]),
            espeak_data_dir=Path(ESPEAK_DATA_DIR))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        voice.synthesize_wav(text, w, SynthesisConfig(speaker_id=speaker, length_scale=length,
                                                      noise_scale=noise, noise_w_scale=noise_w))
    buf.seek(0)
    with wave.open(buf) as w:
        sr, a = w.getframerate(), np.frombuffer(w.readframes(w.getnframes()), "<i2").astype("float32")
    if sr != RATE:
        a = resample_poly(a, RATE, sr)
    write(Path(path), finish(np.clip(a, -32768, 32767).astype("<i2"), soft))


def synthesise_piper(texts: list[str], out: Path, voices: dict, workers: int) -> None:
    from multiprocessing import Pool
    out.mkdir(parents=True, exist_ok=True)
    low = [v for v in voices["piper"] if v["low"]]
    jobs = []
    for t in texts:
        v = random.choice(low if random.random() < LOW_SHARE else voices["piper"])
        jobs.append((t, v["model"], v["speaker"], random.choice(LENGTHS_2), random.choice(NOISE_2),
                     random.choice(NOISE_W), random.random() < SOFT_SHARE, random.random(),
                     str(out / f"{uuid.uuid4().hex}.wav")))
    with Pool(workers) as pool:
        for i, _ in enumerate(pool.imap_unordered(piper_clip, jobs, chunksize=16), 1):
            if i % 200 == 0 or i == len(jobs):
                print(f"\r{out.name} (piper): {i}/{len(jobs)}", end="", file=sys.stderr, flush=True)
    print(file=sys.stderr)


def phrases_for_negatives(n: int, round2: bool = False) -> list[str]:
    """Half the hand list, half openWakeWord's phoneme-overlap generator. Round 2:
    a third the new near misses, a third the old list, a third generated."""
    from openwakeword.data import generate_adversarial_texts
    made = list(generate_adversarial_texts(input_text="wake aries", N=n // (3 if round2 else 2),
                                           include_partial_phrase=1.0, include_input_words=0.2))
    if round2:
        made += [random.choice(NEAR_MISSES_2) for _ in range(n // 3)]
    return [random.choice(NEAR_MISSES) for _ in range(n - len(made))] + made


def synthesise(texts: list[str], out: Path, model_path: Path, batch: int, voices: dict | None = None) -> None:
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
        pool = voices["generator_low"] if voices and random.random() < LOW_SHARE else range(speakers)
        s1 = torch.LongTensor([random.choice(pool) for _ in chunk])
        s2 = torch.LongTensor([random.choice(pool) for _ in chunk])
        lengths, noises = (LENGTHS_2, NOISE_2) if voices else (LENGTHS, NOISE)
        with torch.no_grad():
            audio, samples = generate_audio(model, s1, s2, ids, random.random(), random.choice(noises),
                                            random.choice(NOISE_W), random.choice(lengths), None)
            ends = [int((samples[i].flatten().sum().item() + 1) * RATE / sr) for i in range(audio.shape[0])]
            audio = resample(audio.cpu())
        pcm = audio_float_to_int16(audio.numpy())
        for i in range(pcm.shape[0]):
            data = pcm[i].flatten()[:ends[i]]
            if voices:
                data = finish(data, random.random() < SOFT_SHARE)
            write(out / f"{uuid.uuid4().hex}.wav", np.trim_zeros(data))
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
    ap.add_argument("--voices", type=Path, help="voices.json from voices.py: round 2's voice mix")
    ap.add_argument("--workers", type=int, default=6, help="processes for Piper's own voices")
    a = ap.parse_args()
    # piper_sample_generator turns on DEBUG for everything; numba then logs its compiler IR.
    logging.getLogger("numba").setLevel(logging.WARNING)
    voices = json.loads(a.voices.read_text()) if a.voices else None
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
        texts = positive_texts(n - have, voices is not None) if positive \
            else phrases_for_negatives(n - have, voices is not None)
        random.shuffle(texts)
        if voices:
            cut = int(len(texts) * PIPER_SHARE)
            synthesise_piper(texts[:cut], out, voices, a.workers)
            texts = texts[cut:]
        # Similar lengths per batch: the padding of a short line to a long one is wasted work.
        texts.sort(key=len)
        synthesise(texts, out, model, a.batch, voices)


if __name__ == "__main__":
    main()
