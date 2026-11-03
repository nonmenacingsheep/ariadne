"""Check Kimodo stance clips start and end where their names say.

Run with Kimodo's Python:  kimodo_check.py clips/aries/*.npz
A clip's stance at a moment, from its hips' and head's heights (SOMA, metres):
stand (hips > 0.8), crouch (hips 0.3-0.8), floor (sitting: hips < 0.3, head
> 0.5), lie (head < 0.5). tr_<from>_<to>_N must start in <from> and end in
<to>; crouch_idle_/nap_/floor_sit_/lie_idle_ must stay in theirs. Prints one
line per clip, ok or why not; exits 1 if any failed.
"""
import os
import sys

import numpy as np
from kimodo.skeleton.registry import build_skeleton

HOLD = {"crouch_idle_": "crouch", "nap_": "floor", "floor_sit_": "floor", "lie_idle_": "lie", "sit_idle_": "chair"}


def stance(hips: float, head: float) -> str:
    if head < 0.5:
        return "lie"
    if hips > 0.8:
        return "stand"
    if hips > 0.3:
        return "crouch"
    return "floor"


bad = 0
skel = build_skeleton(77)
head_i = list(skel.bone_order_names).index("Head")
for f in sys.argv[1:]:
    name = os.path.basename(f)[:-4]
    d = np.load(f)
    pj = d["posed_joints"]
    hips, head = d["root_positions"][:, 1], pj[:, head_i, 1]
    a = stance(np.median(hips[:5]), np.median(head[:5]))
    b = stance(np.median(hips[-5:]), np.median(head[-5:]))
    want = None
    if name.startswith("tr_"):
        frm, to = name.split("_")[1:3]
        want = (frm, to)
    else:
        for p, s in HOLD.items():
            if name.startswith(p) and s != "chair":
                want = (s, s)
    if want is None:
        continue
    ok = (a, b) == want
    bad += not ok
    print(f"{'ok ' if ok else 'BAD'} {name:22s} {a}->{b}" + ("" if ok else f"  (wants {want[0]}->{want[1]})"))
sys.exit(1 if bad else 0)
