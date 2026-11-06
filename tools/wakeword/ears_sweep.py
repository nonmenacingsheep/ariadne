"""Through her real ears: each clip streamed into Ears -> Listener -> Spotter by a fake recorder,
at a speaking level over low room noise, and the wake model's peak score kept. A clip wakes her
at threshold t exactly when its peak reaches t (until it fires, the path is the same), so one
pass gives the whole sweep. Room noise moves the result by +-3 of 54 clips, so it pools seeds.

    <core venv>/python ears_sweep.py <model.onnx> <unseen_clips.py out dir> [--seeds 3]

Runs in the core's venv (it imports ariadne2), not the training one.
"""
import argparse
import asyncio
import sys
import time
import wave
from pathlib import Path
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from ariadne2.core.ears import Ears, mic  # noqa: E402
from ariadne2.core.ears.mic import FRAME_BYTES  # noqa: E402
from ariadne2.core.ears.transcribe import Heard  # noqa: E402
from ariadne2.core.ears.wakeword import Spotter  # noqa: E402

THRESHOLDS = (0.05, 0.1, 0.2, 0.3, 0.5, 0.7, 0.9)
ROOM_RMS = 60                    # a quiet room through a desk mic, against speech peaking at 9000


class Whisper:
    """Never consulted before a wake; here only so the ears start."""
    def available(self): return None
    def command_model(self): return "cmd"
    def control_model(self): return "cmd"
    def warm(self, name, park=False): pass
    def prefetch(self, name): pass
    def unload_idle(self, *a): return ()
    def unload(self): pass
    def hear(self, pcm, model, hint): return Heard("", -0.2)


class Peak(Spotter):
    peak = 0.0

    def feed(self, pcm):
        fired = super().feed(pcm)
        self.peak = max(self.peak, self.score)
        return fired


async def peak_score(model: Path, path: Path, rng) -> float:
    with wave.open(str(path)) as w:
        a = np.frombuffer(w.readframes(w.getnframes()), "<i2").astype("float32")
    a *= 9000 / max(1.0, float(np.abs(a).max()))
    pcm = np.concatenate([rng.normal(0, ROOM_RMS, 24000), a + rng.normal(0, ROOM_RMS, len(a)),
                          rng.normal(0, ROOM_RMS, 40000)])
    data = np.clip(pcm, -32768, 32767).astype("<i2").tobytes()
    frames = [data[i:i + FRAME_BYTES] for i in range(0, len(data) - FRAME_BYTES, FRAME_BYTES)]
    now = [1000.0]

    def popen(argv, **kw):
        p = mock.Mock()
        p.alive = True
        p.poll = lambda: None if p.alive else 0
        p.terminate = lambda: setattr(p, "alive", False)

        def read(n):
            if not p.alive or not frames:
                return b""
            now[0] += 0.032
            return frames.pop(0)
        p.stdout.read = read
        return p

    spot = Peak(model=model, threshold=2.0)          # never fires: the peak is what is wanted
    ears = Ears(transcriber=Whisper(), spotter=spot, clock=lambda: now[0], bluetooth=lambda: False,
                find_recorder=lambda fresh=False: ("wav", ["wav"]), popen=popen)
    with mock.patch.object(mic, "recorder_installed", return_value=True):
        await ears.start()
    if ears._spotting() is None:
        raise SystemExit(f"the wake model isn't listening: {ears.status}")
    end = time.monotonic() + 20
    while frames and time.monotonic() < end:
        await asyncio.sleep(0.005)
    await asyncio.sleep(0.1)
    await ears.stop()
    return spot.peak


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("model", type=Path)
    ap.add_argument("clips", type=Path)
    ap.add_argument("--seeds", type=int, default=3)
    a = ap.parse_args()
    peaks = {k: [] for k in ("pos", "cmd", "neg", "old") if (a.clips / k).is_dir()}
    for seed in range(a.seeds):
        rng = np.random.default_rng(seed)
        for kind in peaks:
            for clip in sorted((a.clips / kind).glob("*.wav")):
                peaks[kind].append(await peak_score(a.model, clip, rng))
    print(f"{'thr':>5} {'phrase woke':>12} {'with command':>13} {'near miss woke':>15} {'old phrase':>11}")
    for t in THRESHOLDS:
        cells = [f"{sum(p >= t for p in v)}/{len(v)}" for v in peaks.values()]
        print(f"{t:>5} {cells[0]:>12} {cells[1]:>13} {cells[2]:>15} {(cells[3:] or ['-'])[0]:>11}")


if __name__ == "__main__":
    asyncio.run(main())
