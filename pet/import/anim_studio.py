"""Edit one of her clips in Blender, on her own body (docs/ANIMATING.md).

    bin/anim-edit <clip> [body]          (body: shiromoji, kuromoji, jane...; default shiromoji)

A ready-made scene for aries_anim.py (the Aries clips add-on, which does the
work): her body from pet/models/<body>.glb in her usual outfit, the clip
loaded onto it (its sticks over her, her following them, a Fixes layer to
key on), and the sidebar's Aries tab open for Send to Aries.

    blender -b --python pet/import/anim_studio.py -- <clip> [body] --selftest <dir>
checks the round trip (an unedited take written and read back: no joint may
move; one key on the Fixes layer comes back exact) and renders her.
"""
import json
import os
import sys

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import aries_anim  # noqa: E402

PET = aries_anim.PET
args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
TEST = args[args.index("--selftest") + 1] if "--selftest" in args else ""
args = [a for a in args if a not in ("--selftest", TEST)]
CLIP = args[0] if args else "idle_calm_1"
BODY = args[1] if len(args) > 1 else "shiromoji"


def load_body(name: str):
    bpy.ops.import_scene.gltf(filepath=f"{PET}/models/{name}.glb")
    arm = next(o for o in bpy.context.selected_objects if o.type == "ARMATURE")
    arm.name = "Her"
    # Dressed as in her room: her usual outfit, its shapes (pet.gd _dress).
    try:
        cfg = json.load(open(f"{PET}/models/{name}.json"))
    except (OSError, ValueError):
        cfg = {}
    outfits = cfg.get("outfits", {})
    pick = outfits.get(cfg.get("default", ""), {})
    pieces = {m for o in outfits.values() for m in o.get("show", [])}
    shapes = dict(cfg.get("shapes", {}))
    shapes.update(pick.get("shapes", {}))
    for o in bpy.data.objects:
        if o.type != "MESH":
            continue
        if o.name in pieces:
            o.hide_set(o.name not in pick.get("show", []))
        if o.name in cfg.get("hide", []):
            o.hide_set(True)
        keys = o.data.shape_keys.key_blocks if o.data.shape_keys else {}
        for full, v in shapes.items():
            mesh, _, key = full.rpartition("/")
            if (not mesh or mesh == o.name) and key in keys:
                keys[key].value = float(v)
    return arm


def build():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    dst = load_body(BODY)
    follow = aries_anim.load_onto(dst, CLIP)
    src = follow.src
    # In this scene only the sticks can be clicked: no moving her by accident.
    dst.hide_set(True)
    for o in bpy.data.objects:
        o.hide_select = o != src
    return src, dst, follow


src, dst, follow = build()

if TEST:
    # Round trip: written and read back unedited, nothing may move.
    os.makedirs(TEST, exist_ok=True)
    f0, f1 = bpy.context.scene.frame_start, bpy.context.scene.frame_end
    for o in bpy.context.view_layer.objects:
        o.select_set(o == src)
    bpy.context.view_layer.objects.active = src
    src.scale = (1, 1, 1)
    out = f"{TEST}/{CLIP}.bvh"
    src.scale = (follow.scale,) * 3
    aries_anim.write_take(out)
    bpy.ops.import_anim.bvh(filepath=out, global_scale=0.01, axis_forward="Y", axis_up="Z", rotate_mode="NATIVE")
    back = bpy.context.active_object
    src.scale = (1, 1, 1)
    worst = 0.0
    for f in range(f0, f1 + 1, 5):
        bpy.context.scene.frame_set(f)
        for pb in src.pose.bones:
            a = (src.matrix_world @ pb.matrix).translation
            b = (back.matrix_world @ back.pose.bones[pb.name].matrix).translation
            worst = max(worst, (a - b).length)
    print("ROUNDTRIP worst joint drift %.6f m over frames %d-%d" % (worst, f0, f1))
    bpy.data.objects.remove(back, do_unlink=True)
    bpy.context.view_layer.objects.active = src
    src.select_set(True)
    # A fix on the Fixes layer comes through: his left arm 25 degrees out, one key.
    arm = src.pose.bones["LeftArm"]
    sc0 = bpy.context.scene
    sc0.frame_set(f0)
    before = (src.matrix_world @ src.pose.bones["LeftHand"].matrix).translation.copy()
    arm.rotation_euler.rotate_axis("Z", 0.436)
    arm.keyframe_insert("rotation_euler", frame=f0)
    sc0.frame_set(f0 + 1)
    sc0.frame_set(f0)
    moved = ((src.matrix_world @ src.pose.bones["LeftHand"].matrix).translation - before).length
    src.scale = (follow.scale,) * 3
    aries_anim.write_take(out)
    src.scale = (1, 1, 1)
    bpy.ops.import_anim.bvh(filepath=out, global_scale=0.01, axis_forward="Y", axis_up="Z", rotate_mode="NATIVE")
    back = bpy.context.active_object
    sc0.frame_set((f0 + f1) // 2)
    a = (src.matrix_world @ src.pose.bones["LeftHand"].matrix).translation
    b = (back.matrix_world @ back.pose.bones["LeftHand"].matrix).translation
    print("FIX hand moved %.3f m by the key; written and read back, mid-clip off by %.6f m" % (moved, (a - b).length))
    bpy.data.objects.remove(back, do_unlink=True)
    src.scale = (follow.scale,) * 3
    # Three frames of her, for a look.
    cam = bpy.data.objects.new("Cam", bpy.data.cameras.new("Cam"))
    bpy.context.scene.collection.objects.link(cam)
    cam.location = (0.0, -3.4, 0.85)
    cam.rotation_euler = (1.5708, 0, 0)
    sun = bpy.data.objects.new("Sun", bpy.data.lights.new("Sun", "SUN"))
    bpy.context.scene.collection.objects.link(sun)
    sun.rotation_euler = (0.8, 0.2, 0.3)
    sc = bpy.context.scene
    sc.camera = cam
    sc.render.engine = "BLENDER_WORKBENCH"
    sc.render.resolution_x, sc.render.resolution_y = 480, 640
    picks = [int(x) for x in os.environ.get("ANIM_TEST_FRAMES", "").split(",") if x] or [f0, (f0 + f1) // 2, (f0 + 3 * f1) // 4]
    for k, f in enumerate(picks):
        sc.frame_set(f)
        bpy.context.view_layer.update()
        sc.render.filepath = f"{TEST}/{CLIP}_{k}.png"
        bpy.ops.render.render(write_still=True)
    print("RENDERED", TEST)
else:
    aries_anim.register()
    bpy.context.scene.aries_clip = CLIP

    def setup_view():
        # Pose mode on the sticks, the sidebar's Aries tab open, framed on her.
        # (A nicety: if any of it fails, everything still works from the menus.)
        try:
            for win in bpy.context.window_manager.windows:
                for area in win.screen.areas:
                    if area.type == "VIEW_3D":
                        space = area.spaces.active
                        space.show_region_ui = True
                        space.shading.type = "MATERIAL"
                        with bpy.context.temp_override(window=win, area=area, region=area.regions[-1]):
                            bpy.context.view_layer.objects.active = src
                            src.select_set(True)
                            bpy.ops.object.mode_set(mode="POSE")
                            bpy.ops.view3d.view_axis(type="FRONT")
                            bpy.ops.view3d.view_all()
        except Exception as e:
            print("anim_studio: couldn't set up the view:", e)
        return None
    bpy.app.timers.register(setup_view, first_interval=0.5)
