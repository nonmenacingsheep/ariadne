"""How good the trained wake model is, at a few thresholds.

    python evaluate.py --model <run>/hey_aries.onnx --run <run>/hey_aries --val <validation_set_features.npy>

* False accepts per hour: the ~11.3 h validation set (speech, music, noise),
  counted as events -- a run of firing frames within REFRACTORY_FRAMES of each
  other is one wake, as the ears debounce it -- and as raw frames (train.py's
  stricter count).
* Recall on held-out synthetic positives, augmented (noise, reverb, as
  trained) and clean through the real openWakeWord pipeline on the WAVs.
* Near misses: the share of held-out adversarial clips ("hey there", "hey
  Harry", "Aries", ...) that fire.
* --unseen DIR: WAVs in DIR/pos and DIR/neg, ideally voices it never trained
  on (other Piper voices, or real recordings), end to end and clip by clip.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

THRESHOLDS = (0.1, 0.2, 0.3, 0.5, 0.7, 0.9)
WINDOW = 16                     # embedding frames per prediction (1.28 s)
REFRACTORY_FRAMES = 25          # 2 s: the ears ignore a second firing this soon
VAL_HOURS = 11.3


def batched(path: Path) -> bytes:
    """The exported model takes one window at a time; let it take many (same weights)."""
    import onnx
    model = onnx.load(str(path))
    for tensor in (*model.graph.input, *model.graph.output):
        tensor.type.tensor_type.shape.dim[0].dim_param = "batch"
    return model.SerializeToString()


def scores_over(session, features, step: int = 1, batch: int = 4096):
    """Model scores for every WINDOW-frame slice of a (frames, 96) feature stream."""
    import numpy as np
    name = session.get_inputs()[0].name
    starts = range(0, features.shape[0] - WINDOW, step)
    out = []
    for i in range(0, len(starts), batch):
        idx = starts[i:i + batch]
        x = np.stack([features[j:j + WINDOW] for j in idx]).astype("float32")
        out.append(session.run(None, {name: x})[0].reshape(-1))
    return np.concatenate(out) if out else np.zeros(0)


def clip_max_scores(session, clips):
    """Highest score anywhere in each (n, frames, 96) clip."""
    import numpy as np
    name = session.get_inputs()[0].name
    n, frames, _ = clips.shape
    windows = np.stack([clips[:, j:j + WINDOW] for j in range(frames - WINDOW + 1)], axis=1)
    flat = windows.reshape(-1, WINDOW, clips.shape[2]).astype("float32")
    scores = np.concatenate([session.run(None, {name: flat[i:i + 8192]})[0].reshape(-1)
                             for i in range(0, len(flat), 8192)])
    return scores.reshape(n, -1).max(axis=1)


def events(above) -> int:
    count, last = 0, -10 ** 9
    for i in above.nonzero()[0]:
        if i - last > REFRACTORY_FRAMES:
            count += 1
        last = i
    return count


def main() -> None:
    import numpy as np
    import onnxruntime as ort

    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--model", required=True, type=Path)
    ap.add_argument("--run", required=True, type=Path, help="<output_dir>/<model_name>: features and clips")
    ap.add_argument("--val", required=True, type=Path, help="validation_set_features.npy")
    ap.add_argument("--clean", type=int, default=600, help="clean held-out WAVs to run end to end (0 skips)")
    ap.add_argument("--unseen", type=Path, help="a folder with pos/ and neg/ WAVs to run end to end")
    ap.add_argument("--json", type=Path, help="also write the figures here")
    a = ap.parse_args()

    opts = ort.SessionOptions()
    opts.intra_op_num_threads = opts.inter_op_num_threads = 4
    session = ort.InferenceSession(batched(a.model), opts, providers=["CPUExecutionProvider"])

    val = scores_over(session, np.load(a.val, mmap_mode="r"))
    pos = clip_max_scores(session, np.load(a.run / "positive_features_test.npy"))
    neg = clip_max_scores(session, np.load(a.run / "negative_features_test.npy"))

    from openwakeword.model import Model
    res = Path(__import__("openwakeword").__file__).parent / "resources" / "models"
    oww = Model(wakeword_models=[str(a.model)], inference_framework="onnx",
                melspec_model_path=str(res / "melspectrogram.onnx"),
                embedding_model_path=str(res / "embedding_model.onnx"))

    def end_to_end(wavs):
        """Each clip at a speaking level, with a second of quiet before and two after."""
        import wave
        out = []
        for wav in wavs:
            with wave.open(str(wav)) as w:
                x = np.frombuffer(w.readframes(w.getnframes()), "<i2").astype("float32")
            x = (x * 9000 / max(1.0, float(np.abs(x).max()))).astype("<i2")
            x = np.concatenate([np.zeros(16000, "<i2"), x, np.zeros(32000, "<i2")])
            oww.reset()
            out.append(max(p[a.model.stem] for p in oww.predict_clip(x)))
        return np.array(out)

    clean = end_to_end(sorted((a.run / "positive_test").glob("*.wav"))[:a.clean]) if a.clean else None
    unseen_pos = unseen_neg = None
    if a.unseen:
        unseen_pos = end_to_end(sorted((a.unseen / "pos").glob("*.wav")))
        unseen_neg = end_to_end(sorted((a.unseen / "neg").glob("*.wav")))

    report = {"validation_hours": VAL_HOURS, "held_out_positives": int(len(pos)),
              "held_out_near_misses": int(len(neg)), "thresholds": {}}
    if unseen_pos is not None:
        report["unseen_positives"], report["unseen_negatives"] = len(unseen_pos), len(unseen_neg)
    print(f"{'thr':>5} {'FA/h events':>12} {'FA/h frames':>12} {'recall aug':>11} "
          f"{'recall clean':>13} {'near-miss FA':>13} {'unseen recall':>14} {'unseen FA':>10}")
    for t in THRESHOLDS:
        row = {"fa_per_hour": events(val >= t) / VAL_HOURS,
               "fa_frames_per_hour": float((val >= t).sum()) / VAL_HOURS,
               "recall_augmented": float((pos >= t).mean()),
               "recall_clean": float((clean >= t).mean()) if clean is not None else None,
               "near_miss_accept_rate": float((neg >= t).mean())}
        if unseen_pos is not None:
            row["unseen_recall"] = float((unseen_pos >= t).mean())
            row["unseen_accept_rate"] = float((unseen_neg >= t).mean())
        report["thresholds"][str(t)] = row
        rc = f"{row['recall_clean']:.3f}" if clean is not None else "-"
        ur = f"{row['unseen_recall']:.3f}" if unseen_pos is not None else "-"
        ua = f"{row['unseen_accept_rate']:.3f}" if unseen_pos is not None else "-"
        print(f"{t:>5} {row['fa_per_hour']:>12.3f} {row['fa_frames_per_hour']:>12.3f} "
              f"{row['recall_augmented']:>11.3f} {rc:>13} {row['near_miss_accept_rate']:>13.3f} "
              f"{ur:>14} {ua:>10}")
    if a.json:
        a.json.write_text(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
