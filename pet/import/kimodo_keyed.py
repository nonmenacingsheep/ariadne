"""Generate clips with poses pinned, check them, re-roll the ones that fail.

Text alone can't make Kimodo start crouched or sitting (it starts standing),
so these take real poses from clips that already have them and pin them as
full-body keyframes; Kimodo fills in the motion between.
Run with Kimodo's Python and its text encoder server up:
    kimodo_keyed.py keyed.txt [only_this_name ...]
Lines: name|seconds|prompt|start pose|end pose[|middle poses]
  a pose: clip:frame from clips/aries (frame -1 = the last), optionally
  turned about the vertical, clip:frame/degrees (lying along the bed);
  "-" leaves that end free (a clip that makes a new base pose; both free
  is text alone, from standing: "kneels down" ends in a kneeling pose);
  middle poses: pose@fraction, comma separated ("lie_idle_2:0/90@0.5"),
  so a big move (sitting up) can't be skipped by lying there.
Each clip is checked (kimodo_check.py's pinned_ok): its ends match the pinned
poses, it moves, it doesn't go upside down or through the floor, and a lying
clip stays lying. A failure is re-rolled with the next seed, up to 3; a clip
still failing is reported and kept as <name>.bad.npz for a look.
"""
import json
import os
import subprocess
import sys

import numpy as np
from scipy.spatial.transform import Rotation as R

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kimodo_check import pinned_ok  # noqa: E402

K = os.environ.get("KIMODO_DIR", "/var/mnt/games/AI/Kimodo")   # (the author's; see CLAUDE.md)
OUT = f"{K}/clips/aries"
TRIES = 3


def pose(ref: str):
    turn = 0.0
    if "/" in ref:
        ref, deg = ref.split("/")
        turn = float(deg)
    clip, frame = ref.rsplit(":", 1)
    d = np.load(f"{OUT}/{clip}.npz")
    i = int(frame)
    mats = d["local_rot_mats"][i].reshape(-1, 3, 3).copy()
    if turn:
        mats[0] = R.from_euler("y", turn, degrees=True).as_matrix() @ mats[0]   # the root carries the facing
    rot = R.from_matrix(mats).as_rotvec().tolist()
    root = d["root_positions"][i].copy()
    return rot, [0.0, float(root[1]), 0.0]


def lines(path, only):
    for line in open(path):
        if line.strip().startswith("#") or "|" not in line:
            continue
        f = line.strip().split("|")
        if only and f[0] not in only:
            continue
        yield f[0], f[1], f[2], f[3], f[4], (f[5] if len(f) > 5 else "")


def constraints(frames, a, b, mids):
    keys, rots, roots = [], [], []
    for at, ref in [(0, a), (frames - 2, b)] + [(int(float(m.rsplit("@", 1)[1]) * frames), m.rsplit("@", 1)[0])
                                                for m in mids.split(",") if m]:
        if ref == "-":
            continue
        r, p = pose(ref)
        keys.append(at)
        rots.append(r)
        roots.append(p)
    order = sorted(range(len(keys)), key=lambda i: keys[i])
    return [{"type": "fullbody", "frame_indices": [keys[i] for i in order],
             "local_joints_rot": [rots[i] for i in order], "root_positions": [roots[i] for i in order],
             "smooth_root_2d": [[0.0, 0.0] for _ in order]}]


def main():
    bad = []
    for name, secs, prompt, a, b, mids in lines(sys.argv[1], set(sys.argv[2:])):
        if os.path.exists(f"{OUT}/{name}.npz"):
            continue                                       # already made and passed: keep it
        try:
            made = make(name, secs, prompt, a, b, mids)
        except (OSError, KeyError, ValueError) as e:            # a base pose it needs isn't there
            print(f"BAD {name}: {e}", flush=True)
            made = False
        if not made:
            bad.append(name)
    print("FAILED:", " ".join(bad) if bad else "none", flush=True)


def make(name, secs, prompt, a, b, mids):
        frames = int(float(secs) * 30)
        cpath = f"{OUT}/{name}.constraints.json"
        json.dump(constraints(frames, a, b, mids), open(cpath, "w"))
        want = {"start": None if a == "-" else pose(a), "end": None if b == "-" else pose(b)}
        for seed in range(1, TRIES + 1):
            stem = f"{OUT}/{name}_try"
            pin = ["--constraints", cpath] if a != "-" or b != "-" or mids else []     # both free: text alone
            subprocess.run([f"{K}/.venv/bin/kimodo_gen", prompt, "--duration", secs, "--seed", str(seed),
                            *pin, "--output", stem, "--bvh", "--bvh_standard_tpose"],
                           check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            ok, why = pinned_ok(f"{stem}.npz", want)
            print(f"{'ok ' if ok else 'BAD'} {name} seed {seed}: {why}", flush=True)
            if ok:
                os.replace(f"{stem}.npz", f"{OUT}/{name}.npz")
                os.replace(f"{stem}.bvh", f"{OUT}/{name}.bvh")
                return True
        os.replace(f"{stem}.npz", f"{OUT}/{name}.bad.npz")
        os.remove(f"{stem}.bvh")
        return False


if __name__ == "__main__":
    main()
