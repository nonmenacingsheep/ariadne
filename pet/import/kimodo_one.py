"""One clip for the ComfyUI board (pet/comfy): generate, check, report.

Run with Kimodo's Python, its text encoder server up (pet/comfy starts it):
    kimodo_one.py spec.json
spec: {"prompt", "seconds", "seed", "start", "end", "middle", "out"} where
start / end / middle are kimodo_keyed.py poses ("-" free, "clip:frame/deg"),
out the path stem to write (<out>.npz, <out>.bvh). Writes <out>.json:
{"ok", "check" (kimodo_check.pinned_ok's words), "parents" (the skeleton's
joint parents, for drawing it), "fps"}.
"""
import json
import os
import re
import subprocess
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kimodo_check import pinned_ok, skel  # noqa: E402
from kimodo_keyed import K, constraints, pose  # noqa: E402


def main():
    spec = json.load(open(sys.argv[1]))
    out = spec["out"]
    # kimodo_gen makes each sentence its own segment, each the full length, and
    # a pinned pose falls in only one of them (an empty one crashes it): one
    # sentence, so "... feet. Her hands stay at her side" is one take of its length.
    spec["prompt"] = re.sub(r"\.\s+(\S)", lambda m: ", " + m.group(1).lower(), spec["prompt"].strip()).rstrip(".") + "."
    secs = str(float(spec.get("seconds", 5)))
    a, b, mids = spec.get("start", "-"), spec.get("end", "-"), spec.get("middle", "")
    frames = int(float(secs) * 30)
    args = [f"{K}/.venv/bin/kimodo_gen", spec["prompt"], "--duration", secs, "--seed", str(int(spec.get("seed", 1))),
            "--output", out, "--bvh", "--bvh_standard_tpose"]
    if a != "-" or b != "-" or mids:
        cpath = out + ".constraints.json"
        json.dump(constraints(frames, a, b, mids), open(cpath, "w"))
        args[6:6] = ["--constraints", cpath]
    r = subprocess.run(args, capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(out + ".npz"):
        json.dump({"ok": False, "check": "Kimodo failed: " + (r.stderr or r.stdout)[-600:]}, open(out + ".json", "w"))
        return
    ok, why = pinned_ok(out + ".npz", {"start": None if a == "-" else pose(a), "end": None if b == "-" else pose(b)})
    parents = [int(p) for p in np.asarray(skel.joint_parents).tolist()]
    json.dump({"ok": ok, "check": why, "parents": parents, "fps": 30}, open(out + ".json", "w"))


if __name__ == "__main__":
    main()
