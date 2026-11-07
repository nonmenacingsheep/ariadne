"""Kimodo BVH clips -> one GLB of animations for the 3D body (pet/).

blender -b --python pet/import/bvh_to_glb.py -- out.glb a.bvh b.bvh ...

Each BVH (SOMA skeleton, standard T-pose rest, centimetres, Y up) becomes an
action named after its file; the first one's armature carries them all.
Godot imports the bare skeleton as bones (import_as_skeleton_bones) and
soma_bonemap.tres maps it to its humanoid profile, so the clips play on every
body the same way the Quaternius ones do.
"""
import os
import sys

import bpy

args = sys.argv[sys.argv.index("--") + 1:]
out, bvhs = args[0], args[1:]
bpy.ops.wm.read_factory_settings(use_empty=True)
rig = None
for path in bvhs:
    # (his edits, anim_studio.py's, are written as Blender writes BVH: Z up)
    edited = os.path.basename(os.path.dirname(path)) == "edited"
    bpy.ops.import_anim.bvh(filepath=path, global_scale=0.01, axis_forward="Y" if edited else "-Z",
                            axis_up="Z" if edited else "Y",
                            rotate_mode="NATIVE", update_scene_fps=True, update_scene_duration=True)
    new = bpy.context.active_object
    action = new.animation_data.action
    action.name = os.path.splitext(os.path.basename(path))[0]
    action.use_fake_user = True
    if rig is None:
        rig = new
        rig.name = "Armature"
    else:
        bpy.data.objects.remove(new, do_unlink=True)
# Every action as its own glTF animation, on the one armature.
rig.animation_data.action = None
for action in bpy.data.actions:
    track = rig.animation_data.nla_tracks.new()
    track.name = action.name
    track.strips.new(action.name, int(action.frame_range[0]), action)
for o in bpy.data.objects:
    o.select_set(o == rig)
bpy.ops.export_scene.gltf(filepath=out, export_format="GLB", use_selection=True, export_animations=True,
                          export_animation_mode="NLA_TRACKS", export_yup=True, export_skins=False)
print("EXPORTED", out, [a.name for a in bpy.data.actions])
