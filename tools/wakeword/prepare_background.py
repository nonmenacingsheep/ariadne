"""AudioSet shards (parquet of FLAC) to the 16 kHz mono WAVs the augmenter mixes under the clips.

    python prepare_background.py <shard.parquet>... --out <data>/audioset_16k

The balanced AudioSet split is speech, music, household noise, traffic, TV:
the room she listens in. Ten-second clips, about 1.4 hours per shard.
"""
from __future__ import annotations

import argparse
import io
import sys
import wave
from pathlib import Path

RATE = 16000


def main() -> None:
    import numpy as np
    import pyarrow.parquet as pq
    import soundfile
    from scipy.signal import resample_poly

    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("shards", nargs="+", type=Path)
    ap.add_argument("--out", required=True, type=Path)
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    written = 0
    for shard in a.shards:
        table = pq.read_table(shard, columns=["video_id", "audio"])
        for vid, audio in zip(table.column("video_id").to_pylist(), table.column("audio").to_pylist()):
            target = a.out / f"{vid}.wav"
            if target.exists():
                continue
            try:
                data, sr = soundfile.read(io.BytesIO(audio["bytes"]), dtype="float32", always_2d=True)
            except Exception as exc:
                print(f"skipping {vid}: {exc}", file=sys.stderr)
                continue
            mono = data.mean(axis=1)
            if sr != RATE:
                mono = resample_poly(mono, RATE, sr)
            pcm = (np.clip(mono, -1, 1) * 32767).astype("<i2")
            with wave.open(str(target), "wb") as w:
                w.setframerate(RATE)
                w.setsampwidth(2)
                w.setnchannels(1)
                w.writeframes(pcm.tobytes())
            written += 1
    print(f"{written} clips written to {a.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
