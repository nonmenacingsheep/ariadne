"""Generate stance clips with their first and last poses pinned.

Text alone can't make Kimodo start crouched or sitting (it starts standing),
so these take real poses from clips that already have them and pin them as
full-body keyframes; Kimodo fills in the motion between.
Run with Kimodo's Python and its text encoder server up:
    kimodo_keyed.py keyed.txt
Lines: name|seconds|prompt|start pose|end pose, a pose being clip:frame from
clips/aries (frame -1 = the last).
"""
import json
import os
import subprocess
import sys

import numpy as np
from scipy.spatial.transform import Rotation as R

K = "/var/mnt/games/AI/Kimodo"
OUT = f"{K}/clips/aries"


def pose(ref: str):
    clip, frame = ref.rsplit(":", 1)
    d = np.load(f"{OUT}/{clip}.npz")
    i = int(frame)
    rot = R.from_matrix(d["local_rot_mats"][i].reshape(-1, 3, 3)).as_rotvec().tolist()
    root = d["root_positions"][i].copy()
    return rot, [0.0, float(root[1]), 0.0]


for line in open(sys.argv[1]):
    if line.strip().startswith("#") or "|" not in line:
        continue
    name, secs, prompt, a, b = line.strip().split("|")
    frames = int(float(secs) * 30)
    ra, pa = pose(a)
    rb, pb = pose(b)
    keys = [0, frames - 8]
    cons = [{"type": "fullbody", "frame_indices": keys, "local_joints_rot": [ra, rb],
             "root_positions": [pa, pb], "smooth_root_2d": [[0.0, 0.0], [0.0, 0.0]]}]
    cpath = f"{OUT}/{name}.constraints.json"
    json.dump(cons, open(cpath, "w"))
    subprocess.run([f"{K}/.venv/bin/kimodo_gen", prompt, "--duration", secs, "--seed", "1",
                    "--constraints", cpath, "--output", f"{OUT}/{name}", "--bvh", "--bvh_standard_tpose"],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print("made", name, flush=True)
