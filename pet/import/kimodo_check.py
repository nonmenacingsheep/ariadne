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


skel = build_skeleton(77)
head_i = list(skel.bone_order_names).index("Head")


def _angle(a, b, top=0):
    """Mean angle (degrees) between two sets of joint rotations (..., 3, 3);
    with top, the mean of only the most-turned joints (an arm typing moves
    a few joints a lot, not all 77 a little)."""
    rel = np.einsum("...ji,...jk->...ik", a, b)
    tr = np.clip((np.trace(rel, axis1=-2, axis2=-1) - 1) / 2, -1, 1)
    deg = np.degrees(np.arccos(tr))
    return (np.sort(deg, axis=-1)[..., -top:] if top else deg).mean(axis=-1)


def pinned_ok(path, want):
    """want: {"start": (rotvecs, root) or None, "end": ...} as kimodo_keyed.pose gives.
    Returns (ok, why): ends on their poses, moving, never upside down or
    through the floor, a lying clip staying down; why also says where her
    head points at the end (x, z) when she ends lying."""
    from scipy.spatial.transform import Rotation as R
    d = np.load(path)
    rots = d["local_rot_mats"].reshape(len(d["root_positions"]), -1, 3, 3)
    pj = d["posed_joints"]
    hips, head = d["root_positions"][:, 1], pj[:, head_i, 1]
    bad = []
    for end, i in (("start", 0), ("end", -1)):
        if want.get(end) is None:
            continue
        r, p = want[end]
        err = _angle(rots[i], R.from_rotvec(r).as_matrix())
        if err > 12 or abs(hips[i] - p[1]) > 0.08:
            bad.append(f"{end} off its pose ({err:.0f} deg, hips {hips[i]:.2f} vs {p[1]:.2f})")
    moved = _angle(rots, rots[0:1], top=8).max()
    if moved < 6:
        bad.append(f"static ({moved:.1f} deg)")
    lying = hips[0] < 0.35 and hips[-1] < 0.35
    if pj[:, :, 1].min() < (-0.2 if lying else -0.12):          # a roll on the bed sinks an arm in a bit
        bad.append(f"through the floor ({pj[:, :, 1].min():.2f})")
    if (head < hips - 0.3).any():
        bad.append("upside down")
    if lying and hips.max() > 0.55:
        bad.append(f"gets up off the floor (hips {hips.max():.2f})")
    hd = pj[-1, head_i] - pj[-1, 0]
    face = f"ends hips {hips[-1]:.2f} head {head[-1]:.2f} dir ({hd[0]:+.2f},{hd[2]:+.2f}) moved {moved:.0f}"
    return not bad, ("; ".join(bad) + " | " if bad else "") + face


bad = 0
for f in (sys.argv[1:] if __name__ == "__main__" else []):
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
if __name__ == "__main__":
    sys.exit(1 if bad else 0)
