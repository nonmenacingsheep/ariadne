"""A Kimodo motion.npz (SOMA skeleton) -> BVH with the standard T-pose rest.

Run with Kimodo's own Python (/var/mnt/games/AI/Kimodo/.venv/bin/python):
    kimodo_npz_to_bvh.py motion.npz out.bvh

kimodo_gen --bvh writes BVH directly; this is for NPZs that carry only global
rotations (the demo examples, its web demo's saves), which its converter
refuses. Global rotations -> local, the root joint's positions as the root
track, then Kimodo's own BVH writer.
"""
import sys

import numpy as np
import torch
from kimodo.exports.bvh import motion_to_bvh
from kimodo.skeleton.registry import build_skeleton

src, out = sys.argv[1], sys.argv[2]
d = np.load(src)
if "local_rot_mats" in d.files:
    local = torch.from_numpy(d["local_rot_mats"]).float()
    joints = d["local_rot_mats"].shape[-3]
else:
    joints = d["global_rot_mats"].shape[-3]
skel = build_skeleton(joints)
if "local_rot_mats" not in d.files:
    local = skel.global_rots_to_local_rots(torch.from_numpy(d["global_rot_mats"]).float())
root = torch.from_numpy(d["root_positions"] if "root_positions" in d.files
                        else d["posed_joints"][:, skel.root_idx]).float()
text = motion_to_bvh(local, root, skeleton=skel, fps=30.0, standard_tpose=True)
open(out, "w").write(text)
print("wrote", out, local.shape[0], "frames,", joints, "joints in")
