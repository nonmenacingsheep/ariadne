"""His held-out clips through her real ears (the same path as ears_sweep.py), at every threshold.

    <core venv>/python ronald_eval.py <model.onnx> <ronald clips dir> [<unseen_clips.py out dir>] [--seeds 3]

<ronald clips dir> is ronald_build.py's output (held-out "hey Aries" takes by block, near-miss lines
and 10 s stretches of normal talking); the optional second directory is unseen_clips.py's, to see the
model has not collapsed onto his voice alone. Room noise is added as in ears_sweep.py and the seeds are
pooled. Run it in the core's venv (it imports ariadne2 via ears_sweep).
"""
import argparse
import asyncio
import collections
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ears_sweep import THRESHOLDS, peak_score  # noqa: E402


async def peaks(model: Path, folder: Path, seeds: int) -> dict[str, list[float]]:
    out: dict[str, list[float]] = {}
    for clip in sorted(folder.glob("*.wav")):
        out[clip.stem] = []
        for seed in range(seeds):
            out[clip.stem].append(await peak_score(model, clip, np.random.default_rng(seed)))
    return out


def woke(v: list[float], t: float) -> int:
    return sum(p >= t for p in v)


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("model", type=Path)
    ap.add_argument("ronald", type=Path)
    ap.add_argument("unseen", type=Path, nargs="?")
    ap.add_argument("--seeds", type=int, default=3)
    a = ap.parse_args()
    pos = await peaks(a.model, a.ronald / "test/pos", a.seeds)
    near = await peaks(a.model, a.ronald / "test/near", a.seeds)
    talk = await peaks(a.model, a.ronald / "test/c", a.seeds)
    n_talk = len(talk) * a.seeds
    hours = n_talk * 10 / 3600
    print(f"his held-out takes: {len(pos)} x {a.seeds} seeds; near misses {len(near)}; "
          f"normal talking {len(talk)} stretches of 10 s ({hours * 60:.1f} min pooled)")
    print(f"{'thr':>5} {'hey Aries':>11} " + " ".join(f"a{b}" for b in range(1, 9)) + f" {'near':>6} {'talk':>6}")
    for t in THRESHOLDS:
        by = collections.defaultdict(list)
        for name, v in pos.items():
            by[name.split("_")[0]] += [woke(v, t), len(v)]
        total = sum(woke(v, t) for v in pos.values())
        n = sum(len(v) for v in pos.values())
        blocks = " ".join(f"{sum(by[f'a{b}'][0::2])}/{sum(by[f'a{b}'][1::2])}" for b in range(1, 9))
        print(f"{t:>5} {total:>4}/{n} {100 * total / n:>3.0f}% {blocks} "
              f"{sum(woke(v, t) for v in near.values()):>3}/{sum(len(v) for v in near.values())} "
              f"{sum(woke(v, t) for v in talk.values()):>3}/{n_talk}")
    print("\nnear-miss lines that woke her (of", a.seeds, "passes each):")
    for t in THRESHOLDS:
        print(f"  {t}: " + ", ".join(f"{k} {woke(v, t)}" for k, v in near.items()))
    if a.unseen:
        kinds = {k: await peaks(a.model, a.unseen / k, a.seeds) for k in ("pos", "neg", "cmd", "old")
                 if (a.unseen / k).is_dir()}
        print("\nsynthetic voices it never heard:", {k: len(v) * a.seeds for k, v in kinds.items()})
        for t in THRESHOLDS:
            print(f"  {t}: " + "  ".join(f"{k} {sum(woke(v, t) for v in d.values())}/{len(d) * a.seeds}"
                                         for k, d in kinds.items()))


if __name__ == "__main__":
    asyncio.run(main())
