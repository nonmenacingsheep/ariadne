"""Find the low (male-range) voices to weight the training clips toward. Ronald is male.

    python voices.py --piper <piper-sample-generator> --voices <dir of Piper .onnx> --out voices.json

No gender metadata is needed: every speaker (each of the LibriTTS-R generator's
904, and every speaker of every Piper voice in --voices) says one sentence, and
its median pitch decides. Under LOW_HZ is "low". Writes
    {"generator_low": [speaker ids], "generator_all": n,
     "piper": [{"model": path, "speaker": id or null, "f0": hz, "low": bool}, ...]}
Voices the evaluation holds out (UNSEEN) must not be in --voices.
"""
from __future__ import annotations

import argparse
import logging
import json
import sys
from pathlib import Path

LOW_HZ = 155.0
SENTENCE = "The quick brown fox jumps over the lazy dog, and then it rests."
# The six voices evaluate.py --unseen and the ears smoke test use; same speakers in other
# qualities count too (ryan-low is ryan).
UNSEEN = ("alan", "joe", "ryan", "lessac", "amy", "jenny_dioco")
MAX_PER_VOICE = 400              # libritts_r alone has 2,306 speakers; a sample of each big voice will do


def median_f0(audio, sr: int) -> float:
    import librosa
    import numpy as np
    f0, voiced, _ = librosa.pyin(audio.astype("float32"), fmin=60, fmax=400, sr=sr, frame_length=1024)
    f0 = f0[voiced & ~np.isnan(f0)]
    return float(np.median(f0)) if f0.size else 0.0


def generator_speakers(piper_dir: Path, workers: int) -> list[float]:
    import torch
    sys.path.insert(0, str(piper_dir.resolve()))
    from piper_sample_generator.__main__ import generate_audio, get_phonemes
    model_path = piper_dir / "models" / "en_US-libritts_r-medium.pt"
    model = torch.load(model_path, weights_only=False).eval()
    if torch.cuda.is_available():
        model.cuda()
    config = json.loads(Path(f"{model_path}.json").read_text("utf-8"))
    ids = get_phonemes(config["espeak"]["voice"], config, SENTENCE)
    from multiprocessing import Pool
    clips = []
    for start in range(0, config["num_speakers"], 32):
        who = torch.LongTensor(list(range(start, min(start + 32, config["num_speakers"]))))
        with torch.no_grad():
            audio, _ = generate_audio(model, who, who, [ids] * len(who), 0.0, 0.667, 0.8, 1.0, None)
        clips += [(a.flatten(), config["audio"]["sample_rate"]) for a in audio.cpu().numpy()]
    with Pool(workers) as pool:
        return pool.starmap(median_f0, clips, chunksize=8)


_LOADED: dict = {}


def piper_speaker(job) -> dict:
    """(model, speaker) -> its row. In a worker process."""
    import io
    import wave

    import numpy as np
    import onnxruntime
    from piper import PiperVoice, SynthesisConfig
    from piper.config import PiperConfig
    from piper.voice import ESPEAK_DATA_DIR
    model, sid = job
    voice = _LOADED.get(model)
    if voice is None:
        opts = onnxruntime.SessionOptions()
        opts.intra_op_num_threads, opts.inter_op_num_threads = 2, 1
        voice = _LOADED[model] = PiperVoice(
            config=PiperConfig.from_dict(json.loads(Path(f"{model}.json").read_text("utf-8"))),
            session=onnxruntime.InferenceSession(model, sess_options=opts, providers=["CPUExecutionProvider"]),
            espeak_data_dir=Path(ESPEAK_DATA_DIR))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        voice.synthesize_wav(SENTENCE, w, SynthesisConfig(speaker_id=sid))
    buf.seek(0)
    with wave.open(buf) as w:
        sr, a = w.getframerate(), np.frombuffer(w.readframes(w.getnframes()), "<i2") / 32768.0
    f0 = median_f0(a, sr)
    return {"model": model, "speaker": sid, "f0": round(f0, 1), "low": 0 < f0 < LOW_HZ}


def piper_speakers(voices: Path, workers: int) -> list[dict]:
    import random
    from multiprocessing import Pool
    jobs = []
    for onnx in sorted(voices.glob("*.onnx")):
        if any(f"-{u}-" in onnx.name for u in UNSEEN):
            raise SystemExit(f"{onnx.name} is a held-out test voice; leave it out of --voices")
        n = json.loads(Path(f"{onnx}.json").read_text("utf-8")).get("num_speakers", 1)
        ids = sorted(random.Random(1).sample(range(n), min(n, MAX_PER_VOICE))) if n > 1 else [None]
        jobs += [(str(onnx), sid) for sid in ids]
    with Pool(workers) as pool:
        rows = pool.map(piper_speaker, jobs, chunksize=8)
    for onnx in sorted({r["model"] for r in rows}):
        mine = [r for r in rows if r["model"] == onnx]
        print(f"{Path(onnx).name}: {sum(r['low'] for r in mine)} of {len(mine)} low", file=sys.stderr)
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--piper", required=True, type=Path, help="the piper-sample-generator checkout")
    ap.add_argument("--voices", required=True, type=Path, help="a folder of Piper .onnx voices (not the unseen ones)")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--workers", type=int, default=6)
    a = ap.parse_args()
    # piper_sample_generator turns on DEBUG for everything; numba then logs its compiler IR.
    logging.getLogger("numba").setLevel(logging.WARNING)
    gen = generator_speakers(a.piper, a.workers)
    low = [i for i, f in enumerate(gen) if 0 < f < LOW_HZ]
    print(f"generator: {len(low)} of {len(gen)} low", file=sys.stderr)
    a.out.write_text(json.dumps({"generator_low": low, "generator_all": len(gen),
                                 "piper": piper_speakers(a.voices, a.workers)}, indent=1))


if __name__ == "__main__":
    main()
