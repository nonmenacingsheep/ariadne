"""Cut a stop out of a Kimodo take: from its last steady step to standing.

Run with Kimodo's Python:  kimodo_stop.py take.npz out.bvh
The take walks (or side-steps, or backs up) and then stands. The cut starts
at the last heel-strike while she's still at speed and ends a half second
after she's still, travel left in: the 3D body reads it as a slowing curve,
starts the stop when the distance left matches it, and follows it.
"""
import sys

import numpy as np
import torch
from kimodo.exports.bvh import motion_to_bvh
from kimodo.skeleton.registry import build_skeleton

src, out = sys.argv[1], sys.argv[2]
d = np.load(src)
rots, root = d["local_rot_mats"], d["root_positions"].copy()
T = len(root)
speed = np.zeros(T)
speed[1:] = np.linalg.norm(np.diff(root[:, [0, 2]], axis=0), axis=1) * 30.0
moving = speed > 0.25
still = next((i for i in range(T - 10) if not moving[i:i + 10].any() and moving[:i].any()), T - 1)
contact = (d["foot_contacts"][:, 0] > 0.5) | (d["foot_contacts"][:, 3] > 0.5)
strikes = [i for i in range(20, still) if contact[i] and not contact[i - 1] and speed[i] > 0.3]
start = strikes[-2] if len(strikes) >= 2 else max(0, still - 30)      # a step before the last: room to slow
end = min(T, still + 15)
# Kimodo sometimes drags a foot while she settles (16 cm in one walk stop):
# the cut ends just before any planted foot that slides more than 5 cm.
from kimodo.skeleton.registry import build_skeleton as _bs
names = list(_bs(rots.shape[1]).bone_order_names)
for toe in ("LeftToeBase", "RightToeBase"):
    j = names.index(toe)
    y, xz = d["posed_joints"][:, j, 1], d["posed_joints"][:, j][:, [0, 2]]
    k = start
    while k < end:
        if y[k] < 0.06:
            r = k
            while r + 1 < T and y[r + 1] < 0.06:
                r += 1
            if r - k > 5 and np.linalg.norm(xz[r] - xz[k]) > 0.05 and k > start + 20:
                end = min(end, k + 2)
            k = r + 1
        else:
            k += 1
seg = rots[start:end]
path = root[start:end].copy()
path[:, [0, 2]] -= root[start, [0, 2]]
text = motion_to_bvh(torch.from_numpy(seg).float(), torch.from_numpy(path).float(),
                     skeleton=build_skeleton(rots.shape[1]), fps=30.0, standard_tpose=True)
open(out, "w").write(text)
print(f"{out}: frames {start}-{end} ({(end - start) / 30:.2f} s), slows over "
      f"{np.linalg.norm((root[still] - root[start])[[0, 2]]):.2f} m")
