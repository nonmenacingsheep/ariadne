"""Export the [ZZZ] Jane Doe .blend as a game-ready GLB for the 3D body (pet/).

blender -b "<...>/[ZZZ]_JaneDoe.blend" --python pet/import/jane_export.py -- pet/models/jane.glb

MMD rigs drive their deforming bones through constraints (the legs' D bones
copy the control legs, IK targets pull the feet), which a game engine doesn't
run. So: rest pose, constraints off, the IK / control-only bones gone, the
outline (Solidify) and normal-transfer modifiers off (Godot does outlines in
a shader), helper meshes and the weapon left out, and shape keys kept as
morph targets for her faces. The .blend itself is never saved.
"""
import sys

import bpy
import mathutils

out = sys.argv[sys.argv.index("--") + 1]
rig = bpy.data.objects["[ZZZ]_JaneDoe_Basic"]
DROP_SHAPES = ("CHIKUBI",)

bpy.context.view_layer.objects.active = rig
bpy.ops.object.mode_set(mode="POSE")
for pb in rig.pose.bones:
    for c in list(pb.constraints):
        pb.constraints.remove(c)
    pb.location = (0, 0, 0)
    pb.rotation_quaternion = (1, 0, 0, 0)
    pb.rotation_euler = (0, 0, 0)
    pb.scale = (1, 1, 1)
bpy.ops.object.mode_set(mode="EDIT")
eb = rig.data.edit_bones
# Control-only bones: IK chains and the non-deforming leg copies (their D twins deform).
for name in [b.name for b in eb if b.name.startswith(("IK_", "Leg_Upper", "Leg_Lower", "Foot.", "Foot_tip"))
             or b.name.startswith(("_dummy", "_shadow"))]:
    eb.remove(eb[name])
# MMD's Center and Groove sit ~0.8 m up between Root and the hips. A clip sets
# the hips' height relative to their parent, so with those in between she
# floated that far above the floor. The hips hang straight off Root instead.
for name in ("Center", "Groove"):
    if name in eb:
        for child in [c for c in eb if c.parent == eb[name]]:
            child.parent = eb[name].parent
        eb.remove(eb[name])
# MMD splits the hips: a non-deforming hub ("Spine") with the upper body
# (Waist) and the lower body (Pelvis) hanging off it side by side. A humanoid
# rig wants one Hips that carries both, so Pelvis becomes the hips, the upper
# body and the bag hang off it, and the hub goes. (Mapping Hips to the hub
# tilted every clip back from the hips.)
if "Spine" in eb and "Pelvis" in eb:
    hub, pelvis = eb["Spine"], eb["Pelvis"]
    pelvis.parent = hub.parent
    for child in [c for c in eb if c.parent == hub and c != pelvis]:
        child.parent = pelvis
    eb.remove(hub)
    # MMD's pelvis points down its legs; a humanoid's hips point up the spine
    # (Godot's rest fixer otherwise tips the whole upper body back to match).
    pelvis.tail = pelvis.head + mathutils.Vector((0.0, 0.0, 0.1))
    pelvis.roll = 0.0
bpy.ops.object.mode_set(mode="OBJECT")

keep = []
for o in list(bpy.data.objects):
    if o.type == "MESH" and o.parent == rig and o.name != "Face_DataTransfer":
        for m in list(o.modifiers):
            if m.type in ("SOLIDIFY", "DATA_TRANSFER"):
                o.modifiers.remove(m)
        if o.data.shape_keys:
            for kb in list(o.data.shape_keys.key_blocks):
                if kb.name in DROP_SHAPES or kb.name.startswith("==="):
                    o.shape_key_remove(kb)
        keep.append(o)
# The MMD materials are node groups of matcaps and masks the glTF exporter
# can't read (it picked a rim-light mask as the colour). Each becomes its
# plain base texture, cut out by its clip mask where it has one; the toon
# look is the engine's job.
for m in {s.material for o in keep for s in o.material_slots if s.material}:
    if not m.use_nodes:
        continue
    imgs = {n.image.name: n.image for n in m.node_tree.nodes if n.type == "TEX_IMAGE" and n.image}
    base = next((i for n, i in imgs.items() if n.endswith("_base.png")), None)
    clip = next((i for n, i in imgs.items() if n.endswith("_clip.png")), None)
    if base is None:
        continue
    nt = m.node_tree
    nt.nodes.clear()
    out_n = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = base
    nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = 1.0
    bsdf.inputs["Metallic"].default_value = 0.0
    if clip is not None:
        mask = nt.nodes.new("ShaderNodeTexImage")
        mask.image = clip
        nt.links.new(mask.outputs["Color"], bsdf.inputs["Alpha"])
        m.blend_method = "CLIP"
    nt.links.new(bsdf.outputs["BSDF"], out_n.inputs["Surface"])

for o in bpy.data.objects:
    o.select_set(o == rig or o in keep)

bpy.ops.export_scene.gltf(filepath=out, export_format="GLB", use_selection=True, export_apply=False,
                          export_skins=True, export_morph=True, export_morph_normal=False,
                          export_animations=False, export_yup=True, export_image_format="AUTO")
print("EXPORTED", out, "meshes:", [o.name for o in keep])
