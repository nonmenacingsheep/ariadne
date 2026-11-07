"""Edit one of her clips in Blender, on her own body (docs/ANIMATING.md).

    bin/anim-edit <clip> [body]          (body: shiromoji, kuromoji, jane...; default shiromoji)

Her clips are Kimodo takes on its own skeleton (SOMA: 77 bones, a T-pose rest,
BVH files in $KIMODO_DIR/clips). This opens the take with that skeleton drawn
as thin sticks over her body, which follows it live: the sticks are what he
poses and keys, and she shows what it'll look like. "Send to Aries" (the
sidebar's Aries tab) writes the take to clips/edited/<clip>.bvh, which packing
(kimodo_batch.sh) uses instead of Kimodo's own, so the fix plays on every body;
"Back to Kimodo's" deletes it. The original takes are never changed.

Her body follows by the same sums Godot's retarget does: each of her bones
turns the way its SOMA bone turns from rest, in the world, with her rest first
straightened onto SOMA's T-pose (her limbs, bone by bone, along their length;
her middle, head and feet as they are); her hips move as SOMA's do, scaled to
her legs.

    blender -b --python pet/import/anim_studio.py -- <clip> [body] --selftest <dir>
checks the round trip (an unedited take written and read back: no joint may
move) and renders three frames of her for a look.
"""
import json
import os
import re
import subprocess
import sys

import bpy
from mathutils import Matrix, Quaternion, Vector

HERE = os.path.dirname(os.path.abspath(__file__))
PET = os.path.dirname(HERE)
K = os.environ.get("KIMODO_DIR", "/var/mnt/games/AI/Kimodo")
CLIPS = f"{K}/clips"
EDITED = f"{CLIPS}/edited"

args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
TEST = args[args.index("--selftest") + 1] if "--selftest" in args else ""
args = [a for a in args if a not in ("--selftest", TEST)]
CLIP = args[0] if args else "idle_calm_1"
BODY = args[1] if len(args) > 1 else "shiromoji"


def take_path(clip: str) -> str:
    """His edit if there is one, else Kimodo's take (one-shots in aries/, loops and stops in loops/)."""
    for d in (EDITED, f"{CLIPS}/aries", f"{CLIPS}/loops"):
        p = f"{d}/{clip}.bvh"
        if os.path.exists(p):
            return p
    raise SystemExit(f"no take called {clip} in {CLIPS}")


def bonemap(path: str) -> dict:
    return dict(re.findall(r'bone_map/(\w+) = &"([^"]*)"', open(path).read()))


def load_take(path: str):
    # Kimodo's are Y up; his edits are written as Blender writes them, Z up.
    edited = os.path.dirname(path) == EDITED
    bpy.ops.import_anim.bvh(filepath=path, global_scale=0.01, axis_forward="Y" if edited else "-Z",
                            axis_up="Z" if edited else "Y", rotate_mode="NATIVE",
                            update_scene_fps=True, update_scene_duration=True)
    rig = bpy.context.active_object
    rig.name = "Bones"
    return rig


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


UPRIGHT = {"Hips", "Spine", "Chest", "UpperChest", "Neck", "Head", "LeftFoot", "RightFoot", "LeftToes", "RightToes",
           "LeftEye", "RightEye", "Jaw"}


class Follow:
    """Her rig posed from the sticks', frame by frame."""

    def __init__(self, src, dst, smap: dict, dmap: dict) -> None:
        self.src, self.dst = src, dst
        self.pairs = {dmap[k]: smap[k] for k in dmap if k in smap and smap[k] in src.pose.bones
                      and dmap[k] in dst.pose.bones}
        prof = {dmap[k]: k for k in dmap}
        sw, dw = src.matrix_world, dst.matrix_world
        self.dw_inv = dw.to_quaternion().inverted()
        self.fix = {}
        for t, s in self.pairs.items():
            sb, tb = src.data.bones[s], dst.data.bones[t]
            sdir = (sw.to_3x3() @ (sb.tail_local - sb.head_local)).normalized()
            tdir = (dw.to_3x3() @ (tb.tail_local - tb.head_local)).normalized()
            # Her rest, straightened onto SOMA's T-pose along the bone: her arms,
            # legs and fingers. Not her middle, head and feet (as Godot's
            # fix_silhouette filter leaves them): their bones point their own
            # ways on each rig, and lining hers up along SOMA's flipped her
            # pelvis (and the tail on it) over.
            line = Quaternion() if prof.get(t) in UPRIGHT else tdir.rotation_difference(sdir)
            self.fix[t] = (line @ (dw @ tb.matrix_local).to_quaternion(),
                           (sw @ sb.matrix_local).to_quaternion().inverted())
        hs, ht = src.data.bones[smap["Hips"]], dst.data.bones[dmap["Hips"]]
        self.hips = (smap["Hips"], dmap["Hips"])
        self.scale = (dw @ ht.head_local).z / max((sw @ hs.head_local).z, 1e-3)
        self.order = [b.name for b in dst.data.bones if b.parent is None]
        i = 0
        while i < len(self.order):
            self.order += [c.name for c in dst.data.bones[self.order[i]].children]
            i += 1
        self.last = None

    def apply(self) -> None:
        src, dst = self.src, self.dst
        sw = src.matrix_world
        rot = {}                                   # her bones' armature-space rotations as posed
        for name in self.order:
            b, pb = dst.data.bones[name], dst.pose.bones[name]
            par = rot.get(b.parent.name) if b.parent else Quaternion()
            rest_rel = (b.parent.matrix_local.inverted() @ b.matrix_local).to_quaternion() if b.parent \
                else b.matrix_local.to_quaternion()
            s = self.pairs.get(name)
            if s is None:
                rot[name] = par @ rest_rel           # not hers to follow (hair, tail...): as it rests
                pb.rotation_mode = "QUATERNION"
                pb.rotation_quaternion = Quaternion()
                continue
            fixed, src_rest_inv = self.fix[name]
            world = (sw @ src.pose.bones[s].matrix).to_quaternion() @ src_rest_inv @ fixed
            want = self.dw_inv @ world
            pb.rotation_mode = "QUATERNION"
            pb.rotation_quaternion = (par @ rest_rel).inverted() @ want
            rot[name] = want
        # Her hips go where SOMA's go, from their rests, scaled to her.
        s, t = self.hips
        sb, tb = src.data.bones[s], dst.data.bones[t]
        moved = (sw @ src.pose.bones[s].matrix).translation - (sw @ sb.matrix_local).translation
        here = self.dst.matrix_world.inverted().to_3x3() @ (moved * self.scale)
        dst.pose.bones[t].location = tb.matrix_local.to_3x3().inverted() @ here

    def poll(self):
        """30 times a second: re-pose her if the sticks moved (a frame change, or his edit)."""
        try:
            key = tuple(round(v, 5) for pb in self.src.pose.bones[:40] for v in pb.matrix.to_quaternion())
        except ReferenceError:
            return None                            # (the file was closed)
        if key != self.last:
            self.last = key
            self.apply()
        return 1 / 30


def send() -> str:
    """Write the sticks' take to clips/edited and pack it into her clips."""
    os.makedirs(EDITED, exist_ok=True)
    rig = bpy.data.objects["Bones"]
    f0, f1 = (int(x) for x in rig.animation_data.action.frame_range)
    keep = rig.scale.copy()
    rig.scale = (1, 1, 1)                          # (drawn her size; written at its own)
    for o in bpy.context.view_layer.objects:
        o.select_set(o == rig)
    bpy.context.view_layer.objects.active = rig
    mode = rig.mode
    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.export_anim.bvh(filepath=f"{EDITED}/{CLIP}.bvh", global_scale=100.0, frame_start=f0,
                            frame_end=f1, rotate_mode="NATIVE", root_transform_only=False)
    rig.scale = keep
    bpy.ops.object.mode_set(mode=mode)
    subprocess.Popen([f"{HERE}/anim_send.sh", CLIP], start_new_session=True,
                     stdout=open(f"{EDITED}/send.log", "w"), stderr=subprocess.STDOUT)
    return f"Sent {CLIP}: packing it into her clips (a minute or two); her body reloads when it's in."


class ARIES_OT_send(bpy.types.Operator):
    bl_idname = "aries.send"
    bl_label = "Send to Aries"
    bl_description = "Save this clip as your version and put it into her clips (every body plays it)"

    def execute(self, context):
        self.report({"INFO"}, send())
        return {"FINISHED"}


class ARIES_OT_original(bpy.types.Operator):
    bl_idname = "aries.original"
    bl_label = "Back to Kimodo's"
    bl_description = "Throw away your version of this clip; she plays Kimodo's again (after packing)"

    def execute(self, context):
        p = f"{EDITED}/{CLIP}.bvh"
        if os.path.exists(p):
            os.remove(p)
            subprocess.Popen([f"{HERE}/anim_send.sh", CLIP], start_new_session=True,
                             stdout=open(f"{EDITED}/send.log", "w"), stderr=subprocess.STDOUT)
            self.report({"INFO"}, f"{CLIP} is Kimodo's again (packing it in; reopen to see it here).")
        else:
            self.report({"INFO"}, f"{CLIP} has no edit of yours.")
        return {"FINISHED"}


class ARIES_PT_panel(bpy.types.Panel):
    bl_label = "Aries"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Aries"

    def draw(self, context):
        col = self.layout.column()
        col.label(text=f"Clip: {CLIP}")
        col.label(text=f"On: {BODY}")
        col.label(text="(your edit)" if os.path.exists(f"{EDITED}/{CLIP}.bvh") else "(Kimodo's take)")
        col.operator("aries.send", icon="EXPORT")
        col.operator("aries.original", icon="LOOP_BACK")


def build():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    src = load_take(take_path(CLIP))
    action = src.animation_data.action
    dst = load_body(BODY)
    follow = Follow(src, dst, bonemap(f"{PET}/assets/anims/kimodo/soma_bonemap.tres"),
                    bonemap(f"{PET}/models/{BODY}_bonemap.tres"))
    # The sticks drawn her size, over her: thin, in front, the only thing to pick.
    src.scale = (follow.scale,) * 3
    src.data.display_type = "STICK"
    src.show_in_front = True
    dst.hide_set(True)
    for o in bpy.data.objects:
        o.hide_select = o != src
    sc = bpy.context.scene
    sc.frame_start, sc.frame_end = (int(x) for x in action.frame_range)
    sc.frame_set(sc.frame_start)
    sc.tool_settings.use_keyframe_insert_auto = True          # a turn of a bone keys it
    # Kimodo keys every bone on every frame: a change to one frame alone just
    # flickers. So the take is a locked layer underneath, and his keys go on a
    # "Fixes" layer added on top: one key moves the bone that much for the
    # whole clip; keys either side of it bring a fix in and out.
    ad = src.animation_data
    base = ad.nla_tracks.new()
    base.name = "Kimodo's take"
    base.strips.new(action.name, int(action.frame_range[0]), action)
    base.lock = True
    ad.action = bpy.data.actions.new("Fixes")
    ad.action_blend_type = "COMBINE"
    follow.apply()
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
    bpy.ops.export_anim.bvh(filepath=out, global_scale=100.0, frame_start=f0, frame_end=f1,
                            rotate_mode="NATIVE", root_transform_only=False)
    bpy.ops.import_anim.bvh(filepath=out, global_scale=0.01, axis_forward="Y", axis_up="Z", rotate_mode="NATIVE")
    back = bpy.context.active_object
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
    bpy.ops.export_anim.bvh(filepath=out, global_scale=100.0, frame_start=f0, frame_end=f1,
                            rotate_mode="NATIVE", root_transform_only=False)
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
        follow.apply()
        bpy.context.view_layer.update()
        sc.render.filepath = f"{TEST}/{CLIP}_{k}.png"
        bpy.ops.render.render(write_still=True)
    print("RENDERED", TEST)
else:
    bpy.utils.register_class(ARIES_OT_send)
    bpy.utils.register_class(ARIES_OT_original)
    bpy.utils.register_class(ARIES_PT_panel)
    bpy.app.timers.register(follow.poll, persistent=True)

    def setup_view():
        # Pose mode on the sticks, the sidebar's Aries tab open, framed on her.
        # (A nicety: if any of it fails, everything still works from the menus.)
        try:
            _setup_view()
        except Exception as e:
            print("anim_studio: couldn't set up the view:", e)
        return None

    def _setup_view():
        for win in bpy.context.window_manager.windows:
            for area in win.screen.areas:
                if area.type == "VIEW_3D":
                    space = area.spaces.active
                    space.show_region_ui = True
                    space.shading.type = "SOLID"
                    with bpy.context.temp_override(window=win, area=area, region=area.regions[-1]):
                        bpy.context.view_layer.objects.active = src
                        src.select_set(True)
                        bpy.ops.object.mode_set(mode="POSE")
                        bpy.ops.view3d.view_axis(type="FRONT")
                        bpy.ops.view3d.view_all()
    bpy.app.timers.register(setup_view, first_interval=0.5)
