"""Mix one folder of clips into rooms and noise and compute openWakeWord features for it.

    python augment.py <clips dir> <out.npy> --rirs <dir> --background <dir> [--also old.npy ...]

What `train.py --augment_clips` does, for one folder, so the four folders can run
side by side (train.py does them one after another on about one core: 35
minutes for round 1). --also appends features computed before (round 1's) to
the new ones, so a retrain adds to what the last one learned from.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

TOTAL_LENGTH = 32000             # 2 s, what train.py settles on for this phrase (16 feature frames)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("clips", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--rirs", required=True, type=Path)
    ap.add_argument("--background", required=True, type=Path)
    ap.add_argument("--also", type=Path, nargs="*", default=[], help="earlier feature files to append")
    ap.add_argument("--batch", type=int, default=16)
    a = ap.parse_args()

    import numpy as np
    import torch
    from numpy.lib.format import open_memmap
    from openwakeword.data import augment_clips
    from openwakeword.utils import compute_features_from_generator

    fresh = a.out.with_suffix(".new.npy") if a.also else a.out
    if not fresh.exists():
        clips = [str(p) for p in sorted(a.clips.glob("*.wav"))]
        gen = augment_clips(clips, total_length=TOTAL_LENGTH, batch_size=a.batch,
                            background_clip_paths=[e.path for e in os.scandir(a.background)],
                            RIR_paths=[e.path for e in os.scandir(a.rirs)])
        compute_features_from_generator(gen, n_total=len(clips), clip_duration=TOTAL_LENGTH,
                                        output_file=str(fresh),
                                        device="gpu" if torch.cuda.is_available() else "cpu", ncpu=1)
    if a.also:
        parts = [np.load(p, mmap_mode="r") for p in (fresh, *a.also)]
        out = open_memmap(a.out, mode="w+", dtype=parts[0].dtype,
                          shape=(sum(len(p) for p in parts), *parts[0].shape[1:]))
        at = 0
        for part in parts:
            out[at:at + len(part)] = part
            at += len(part)
        out.flush()
        print(f"{a.out}: {at} clips ({', '.join(str(len(p)) for p in parts)})")


if __name__ == "__main__":
    main()
