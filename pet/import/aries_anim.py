"""Aries clips in Blender: load one of her clips onto a body, fix it, send it back.

A Blender add-on (Edit > Preferences > Add-ons > Install from Disk, this file),
and what bin/anim-edit's ready-made scene runs on (anim_studio.py). In the 3D
view's sidebar, the Aries tab: select her skeleton (any of her bodies: the
original .blend or pet/models/*.glb), pick a clip, Load onto her. The clip's
own skeleton (Kimodo's SOMA, a T-pose) comes in as thin sticks over her and
she follows them live; his keys go on a Fixes layer over the take (Kimodo keys
every frame: one key there moves a bone for the whole clip). Send to Aries
writes clips/edited/<clip>.bvh and packs it into her clips in place of
Kimodo's take (every body plays it); Back to Kimodo's deletes it. Kimodo's
takes are never changed (docs/ANIMATING.md).

She follows by the same sums Godot's retarget does: each of her bones turns
the way its SOMA bone turns from rest, in the world, with her rest first
straightened onto SOMA's T-pose (her limbs, bone by bone, along their length;
her middle, head and feet as they are, as Godot's fix_silhouette filter
leaves them); her hips move as SOMA's do, scaled to her legs. Which of her
bones is which comes from pet/models/<body>_bonemap.tres, whichever fits.
"""
bl_info = {
    "name": "Aries clips",
    "author": "Ariadne",
    "version": (1, 0),
    "blender": (4, 2, 0),
    "location": "3D View > Sidebar > Aries",
    "description": "Load one of Aries' clips onto her body, fix it, send it back",
    "category": "Animation",
}

import glob
import os
import re
import subprocess

import bpy
from mathutils import Quaternion

HERE = os.path.dirname(os.path.abspath(__file__))
# Run from the repo (bin/anim-edit), or installed as an add-on (a copy elsewhere).
PET = os.path.dirname(HERE) if os.path.isdir(os.path.join(os.path.dirname(HERE), "models")) else \
    os.path.join(os.environ.get("ARIADNE2_REPO", "/home/Nonmenacinghseep/Claude Projects/ariadne2"), "pet")
K = os.environ.get("KIMODO_DIR", "/var/mnt/games/AI/Kimodo")
CLIPS = f"{K}/clips"
EDITED = f"{CLIPS}/edited"
STICKS = "Aries Bones"
NEED = ["Hips", "Spine", "Head", "LeftUpperArm", "LeftLowerArm", "LeftHand", "RightUpperArm", "RightLowerArm",
        "RightHand", "LeftUpperLeg", "LeftLowerLeg", "LeftFoot", "RightUpperLeg", "RightLowerLeg", "RightFoot"]
UPRIGHT = {"Hips", "Spine", "Chest", "UpperChest", "Neck", "Head", "LeftFoot", "RightFoot", "LeftToes", "RightToes",
           "LeftEye", "RightEye", "Jaw"}
state = {"clip": "", "follow": None}


def clip_names() -> list[str]:
    """Her clips (the ones she plays: not those he took out)."""
    try:
        removed = {l.strip() for l in open(f"{PET}/clips_removed.txt") if l.strip() and not l.startswith("#")}
    except OSError:
        removed = set()
    names = set()
    for d in ("aries", "loops", "edited"):
        for p in glob.glob(f"{CLIPS}/{d}/*.bvh"):
            n = os.path.basename(p)[:-4]
            if not n.endswith("_try") and n not in removed:
                names.add(n)
    return sorted(names)


def take_path(clip: str) -> str:
    """His edit if there is one, else Kimodo's take (one-shots in aries/, loops and stops in loops/)."""
    for d in (EDITED, f"{CLIPS}/aries", f"{CLIPS}/loops"):
        p = f"{d}/{clip}.bvh"
        if os.path.exists(p):
            return p
    raise FileNotFoundError(f"no take called {clip} in {CLIPS}")


def bonemap(path: str) -> dict:
    return dict(re.findall(r'bone_map/(\w+) = &"([^"]*)"', open(path).read()))


def body_map(arm) -> dict:
    """Which of this skeleton's bones is which: the first body's map whose bones it has."""
    for p in sorted(glob.glob(f"{PET}/models/*_bonemap.tres")):
        m = bonemap(p)
        if all(k in m and m[k] in arm.pose.bones for k in NEED):
            return m
    raise ValueError("this skeleton isn't one of her bodies (no bone map in pet/models fits it)")


def load_take(path: str):
    # Kimodo's are Y up; his edits are written as Blender writes them, Z up.
    edited = os.path.dirname(path) == EDITED
    bpy.ops.import_anim.bvh(filepath=path, global_scale=0.01, axis_forward="Y" if edited else "-Z",
                            axis_up="Z" if edited else "Y", rotate_mode="NATIVE",
                            update_scene_fps=True, update_scene_duration=True)
    rig = bpy.context.active_object
    rig.name = STICKS
    return rig


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
        self.scale = ((dw @ ht.head_local) - dw.translation).z / max((sw @ hs.head_local).z - sw.translation.z, 1e-3)
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
        if state.get("follow") is not self:
            return None                            # (another clip took over)
        try:
            key = tuple(round(v, 5) for pb in self.src.pose.bones[:40] for v in pb.matrix.to_quaternion())
        except ReferenceError:
            return None                            # (the sticks were deleted, or the file closed)
        if key != self.last:
            self.last = key
            self.apply()
        return 1 / 30


def load_onto(dst, clip: str):
    """The clip's sticks over her, her following them, a Fixes layer to key on. Returns the Follow."""
    old = bpy.data.objects.get(STICKS)
    if old is not None:
        bpy.data.objects.remove(old, do_unlink=True)
    dmap = body_map(dst)
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    src = load_take(take_path(clip))
    action = src.animation_data.action
    src.location = dst.matrix_world.translation
    follow = Follow(src, dst, bonemap(f"{PET}/assets/anims/kimodo/soma_bonemap.tres"), dmap)
    src.scale = (follow.scale,) * 3                # (drawn her size; written at its own)
    src.data.display_type = "STICK"
    src.show_in_front = True
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
    state.update(clip=clip, follow=follow)
    bpy.app.timers.register(follow.poll, persistent=True)
    return follow


def write_take(path: str) -> None:
    """The sticks' take (the Kimodo layer and his fixes together) as a BVH."""
    src = bpy.data.objects[STICKS]
    f0, f1 = bpy.context.scene.frame_start, bpy.context.scene.frame_end
    keep = src.scale.copy()
    src.scale = (1, 1, 1)
    for o in bpy.context.view_layer.objects:
        o.select_set(o == src)
    bpy.context.view_layer.objects.active = src
    mode = src.mode
    if mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.export_anim.bvh(filepath=path, global_scale=100.0, frame_start=f0, frame_end=f1,
                            rotate_mode="NATIVE", root_transform_only=False)
    src.scale = keep
    if mode != "OBJECT":
        bpy.ops.object.mode_set(mode=mode)


def _pack(clip: str) -> None:
    os.makedirs(EDITED, exist_ok=True)
    subprocess.Popen([f"{PET}/import/anim_send.sh", clip], start_new_session=True,
                     stdout=open(f"{EDITED}/send.log", "w"), stderr=subprocess.STDOUT)


# ---- the sidebar ----------------------------------------------------------------

_items: list = []


def _clip_items(self, context):
    _items[:] = [(n, n, "") for n in clip_names()] or [("", "(no clips found)", "")]
    return _items


class ARIES_OT_load(bpy.types.Operator):
    bl_idname = "aries.load"
    bl_label = "Load onto her"
    bl_description = "Bring the clip in as sticks over the selected skeleton; she follows them"

    @classmethod
    def poll(cls, context):
        o = context.active_object
        return o is not None and o.type == "ARMATURE" and o.name != STICKS

    def execute(self, context):
        clip = context.scene.aries_clip
        try:
            load_onto(context.active_object, clip)
        except (ValueError, FileNotFoundError) as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        src = bpy.data.objects[STICKS]
        context.view_layer.objects.active = src
        src.select_set(True)
        bpy.ops.object.mode_set(mode="POSE")
        self.report({"INFO"}, f"{clip} loaded: pose the sticks; she follows")
        return {"FINISHED"}


class ARIES_OT_send(bpy.types.Operator):
    bl_idname = "aries.send"
    bl_label = "Send to Aries"
    bl_description = "Save this clip as your version and put it into her clips (every body plays it)"

    @classmethod
    def poll(cls, context):
        return bool(state["clip"]) and STICKS in bpy.data.objects

    def execute(self, context):
        os.makedirs(EDITED, exist_ok=True)
        write_take(f"{EDITED}/{state['clip']}.bvh")
        _pack(state["clip"])
        self.report({"INFO"}, f"Sent {state['clip']}: packing it into her clips (a minute or two); "
                              "her body reloads when it's in.")
        return {"FINISHED"}


class ARIES_OT_original(bpy.types.Operator):
    bl_idname = "aries.original"
    bl_label = "Back to Kimodo's"
    bl_description = "Throw away your version of this clip; she plays Kimodo's again"

    @classmethod
    def poll(cls, context):
        return bool(state["clip"]) and os.path.exists(f"{EDITED}/{state['clip']}.bvh")

    def execute(self, context):
        os.remove(f"{EDITED}/{state['clip']}.bvh")
        _pack(state["clip"])
        self.report({"INFO"}, f"{state['clip']} is Kimodo's again (load it again to see it here).")
        return {"FINISHED"}


class ARIES_OT_unload(bpy.types.Operator):
    bl_idname = "aries.unload"
    bl_label = "Let her go"
    bl_description = "Remove the clip's sticks; she goes back to her rest pose"

    @classmethod
    def poll(cls, context):
        return STICKS in bpy.data.objects

    def execute(self, context):
        f = state.get("follow")
        state.update(clip="", follow=None)
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        bpy.data.objects.remove(bpy.data.objects[STICKS], do_unlink=True)
        if f is not None:
            try:
                for pb in f.dst.pose.bones:
                    pb.rotation_quaternion = Quaternion()
                    pb.location = (0, 0, 0)
            except ReferenceError:
                pass
        return {"FINISHED"}


class ARIES_PT_panel(bpy.types.Panel):
    bl_label = "Aries"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Aries"

    def draw(self, context):
        col = self.layout.column()
        if state["clip"] and STICKS in bpy.data.objects:
            col.label(text=f"Clip: {state['clip']}")
            col.label(text="(your edit)" if os.path.exists(f"{EDITED}/{state['clip']}.bvh") else "(Kimodo's take)")
            col.operator("aries.send", icon="EXPORT")
            col.operator("aries.original", icon="LOOP_BACK")
            col.operator("aries.unload", icon="X")
            col.separator()
        col.label(text="Select her skeleton, then:")
        col.prop(context.scene, "aries_clip", text="Clip")
        col.operator("aries.load", icon="IMPORT")


CLASSES = (ARIES_OT_load, ARIES_OT_send, ARIES_OT_original, ARIES_OT_unload, ARIES_PT_panel)


def register():
    bpy.types.Scene.aries_clip = bpy.props.EnumProperty(name="Clip", items=_clip_items)
    for c in CLASSES:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(CLASSES):
        bpy.utils.unregister_class(c)
    del bpy.types.Scene.aries_clip


if __name__ == "__main__":
    register()
