"""Cut a seamless loop out of a Kimodo locomotion take (walk, strafe, back).

Run with Kimodo's Python:  kimodo_loop.py take.npz out.bvh [contact column]
One steady gait cycle, from a heel-strike of the left foot to its next
(foot_contacts, after the first second of starting up), so the loop's two
ends are the same moment of the stride. What little still differs between
them (each joint's rotation, the hips' height) is spread over the cycle, so
the seam doesn't pop. The travel stays in: the 3D body measures it as the
clip's ground speed and moves her exactly that fast, so her feet stay put.
"""
import sys

import numpy as np
import torch
from scipy.spatial.transform import Rotation as R
from kimodo.exports.bvh import motion_to_bvh
from kimodo.skeleton.registry import build_skeleton

src, out = sys.argv[1], sys.argv[2]
col = int(sys.argv[3]) if len(sys.argv) > 3 else 0
d = np.load(src)
rots, root = d["local_rot_mats"], d["root_positions"].copy()
contact = d["foot_contacts"][:, col] > 0.5
strikes = [i for i in range(31, len(contact)) if contact[i] and not contact[i - 1]]
cycles = [(a, b) for a, b in zip(strikes, strikes[1:]) if 18 <= b - a <= 60]
if not cycles:
    sys.exit(f"no steady gait cycle in {src} (strikes at {strikes})")
a, b = cycles[len(cycles) // 2]                 # one from the middle of the take
n = b - a
seg = rots[a:b].copy()
# Spread the end-to-start mismatch (frame b vs frame a) over the cycle.
delta = R.from_matrix(rots[a].reshape(-1, 3, 3)) * R.from_matrix(rots[b].reshape(-1, 3, 3)).inv()
dv = delta.as_rotvec()
for i in range(n):
    f = i / n
    seg[i] = (R.from_rotvec(dv * f) * R.from_matrix(seg[i].reshape(-1, 3, 3))).as_matrix().reshape(seg[i].shape)
path = root[a:b].copy()
path[:, 1] += np.linspace(0.0, 1.0, n, endpoint=False) * (root[a, 1] - root[b, 1])
path[:, [0, 2]] -= root[a, [0, 2]]
skel = build_skeleton(rots.shape[1])
text = motion_to_bvh(torch.from_numpy(seg).float(), torch.from_numpy(path).float(), skeleton=skel, fps=30.0,
                     standard_tpose=True)
open(out, "w").write(text)
travel = np.linalg.norm((root[b] - root[a])[[0, 2]])
print(f"{out}: frames {a}-{b} ({n / 30:.2f} s), {travel:.2f} m, {travel / (n / 30):.2f} m/s")
