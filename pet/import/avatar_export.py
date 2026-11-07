"""Export a VRChat-style Booth avatar .blend as a GLB for the 3D body (pet/).

blender -b <avatar>.blend --python pet/import/avatar_export.py -- pet/models/<name>.glb [--all] [--cover Body=Pants+Top] [skip collection ...]

These come rigged with the humanoid bone names (Hips, Spine, Chest,
UpperArm_L...), VRChat mouth shapes and blink, and MMD expressions, so the
work is making the file game-ready, the way jane_export.py does for an MMD rig:
- what's shown: the meshes the author has visible and renderable, minus any
  collection named after the output; with --all, every outfit's pieces too,
  hidden or not (pet/models/<name>.json says which an outfit shows);
- rest pose, constraints off; a loose bone root (Kuromoji's Hair_Root rode her
  head by an Armature constraint) goes under the Head (hair, ears) or Hips;
- an Armature modifier the author left pointing at nothing (Kuromoji's
  sandals, boots, belts and hats, hooked up as she changes outfit) gets the
  armature, so the piece moves with her instead of standing where it was made;
- outline (Solidify) modifiers off (Godot draws outlines), the rest (mirror,
  bevel, geometry nodes) applied; a mesh with modifiers to apply has its shape
  keys baked as they're set, the rest keep theirs: the face's expressions and
  each piece's fit keys (the ear band under a cap, the body tucked in for a
  bikini), which pet/models/<name>.json sets per outfit;
- each material rebuilt as a plain Principled BSDF on its main texture (their
  own toon node trees don't export), alpha from it where it has any;
- with --cover Body=Pants+Top, the body's skin those clothes hide is split off
  as Body_Under, for the outfit to hide: shrink keys alone left her hips
  peeking through wide pants when she sat or bent. A face goes if every ray
  out of it, across the half it faces, hits the clothes; skin under a gap
  (a shoulder cut-out, the leg openings) sees out and stays.
The .blend itself is never saved.
"""
import os
import sys

import bpy

args = sys.argv[sys.argv.index("--") + 1:]
out = args[0]
every = "--all" in args
cover = args[args.index("--cover") + 1] if "--cover" in args else ""
skip = {a for a in args[1:] if a not in ("--all", "--cover", cover)}
FACE_KEYS = ("vrc.v_aa", "vrc.Blink", "まばたき")
HELPERS = ("DataTransfer",)

arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
keep = []
for o in bpy.data.objects:
    if o.type != "MESH":
        continue
    if (not every and (not o.visible_get() or o.hide_render)) or any(h in o.name for h in HELPERS) \
            or any(c.name in skip for c in o.users_collection):
        continue
    keep.append(o)
for o in [o for o in bpy.data.objects if o.type == "MESH" and o not in keep]:
    bpy.data.objects.remove(o, do_unlink=True)
for coll in bpy.data.collections:          # an excluded or hidden collection hides what's in it from the exporter
    coll.hide_render = False
    coll.hide_viewport = False
for lc in bpy.context.view_layer.layer_collection.children:
    def show(c):
        c.exclude = False
        c.hide_viewport = False
        for ch in c.children:
            show(ch)
    show(lc)
for o in keep + [arm]:
    o.hide_set(False)
    o.hide_viewport = False

# Rest pose, no constraints; loose roots under the head or hips.
bpy.context.view_layer.objects.active = arm
bpy.ops.object.mode_set(mode="POSE")
for pb in arm.pose.bones:
    for c in list(pb.constraints):
        pb.constraints.remove(c)
    pb.location = (0, 0, 0)
    pb.rotation_quaternion = (1, 0, 0, 0)
    pb.rotation_euler = (0, 0, 0)
    pb.scale = (1, 1, 1)
bpy.ops.object.mode_set(mode="EDIT")
eb = arm.data.edit_bones
for b in eb:
    if b.parent is None and b.name != "Hips":
        b.parent = eb["Head"] if b.name.lower().startswith(("hair", "kemo", "ear", "head")) else eb["Hips"]
        b.use_connect = False
bpy.ops.object.mode_set(mode="OBJECT")

# Modifiers and shape keys.
for o in keep:
    for m in [m for m in o.modifiers if m.type == "SOLIDIFY"]:
        o.modifiers.remove(m)
    for m in o.modifiers:
        if m.type == "ARMATURE" and m.object is None:
            m.object = arm
            print("armature", o.name)
    keys = o.data.shape_keys.key_blocks.keys() if o.data.shape_keys else []
    face = any(k in keys for k in FACE_KEYS)
    others = [m for m in o.modifiers if m.type != "ARMATURE"]
    if keys and not face and others:
        # Baked as set, then gone: the author's fit, and nothing stopping the modifiers.
        bpy.context.view_layer.objects.active = o
        mix = o.shape_key_add(name="__mix", from_mix=True)
        basis = o.data.shape_keys.key_blocks[0]
        for i, v in enumerate(o.data.vertices):
            basis.data[i].co = mix.data[i].co
            v.co = mix.data[i].co
        o.shape_key_clear()
    if others and not face:
        bpy.context.view_layer.objects.active = o
        for m in list(o.modifiers):
            if m.type == "ARMATURE":
                continue
            try:
                bpy.ops.object.modifier_apply(modifier=m.name)
            except RuntimeError as e:
                print("couldn't apply", o.name, m.name, e)
                o.modifiers.remove(m)
    elif others:
        for m in others:
            print("dropped", o.name, m.name)
            o.modifiers.remove(m)

# Skin under clothes, split off (--cover).
if cover:
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree
    body_name, cloth = cover.split("=")
    body = bpy.data.objects[body_name]
    dg = bpy.context.evaluated_depsgraph_get()
    verts, polys = [], []
    for name in cloth.split("+"):
        ob = bpy.data.objects[name].evaluated_get(dg)
        me = ob.to_mesh()
        base = len(verts)
        verts += [ob.matrix_world @ v.co for v in me.vertices]
        polys += [[base + i for i in p.vertices] for p in me.polygons]
        ob.to_mesh_clear()
    tree = BVHTree.FromPolygons(verts, polys)
    mw = body.matrix_world
    nm = mw.to_3x3().inverted().transposed()
    # Rays across the hemisphere a point faces: its normal, then rings at 35 and 70 degrees.
    import math
    def rays(n):
        t = n.orthogonal().normalized()
        b = n.cross(t)
        out = [n]
        for tilt in (math.radians(35), math.radians(70)):
            for k in range(8):
                a = k * math.tau / 8
                out.append((n * math.cos(tilt) + (t * math.cos(a) + b * math.sin(a)) * math.sin(tilt)).normalized())
        return out
    hid = []
    for v in body.data.vertices:
        p = mw @ v.co
        n = (nm @ v.normal).normalized()
        hid.append(all(tree.ray_cast(p + n * 0.001, d, 0.3)[0] is not None for d in rays(n)))
    under = [f.index for f in body.data.polygons if all(hid[i] for i in f.vertices)]
    print("COVER", body_name, len(under), "of", len(body.data.polygons), "faces hidden by", cloth)
    if under:
        bpy.ops.object.select_all(action="DESELECT")
        bpy.context.view_layer.objects.active = body
        body.select_set(True)
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="DESELECT")
        bpy.ops.object.mode_set(mode="OBJECT")
        for i in under:
            body.data.polygons[i].select = True
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.separate(type="SELECTED")
        bpy.ops.object.mode_set(mode="OBJECT")
        piece = next(o for o in bpy.context.selected_objects if o is not body)
        piece.name = body_name + "_Under"
        keep.append(piece)

# Materials: a Principled BSDF on the main texture.
def main_image(mat):
    imgs = [n.image for n in mat.node_tree.nodes if n.type == "TEX_IMAGE" and n.image]
    good = [i for i in imgs if i.name.startswith("T_") and not any(w in i.name for w in
            ("Flat", "Shadow", "Mask", "Highlight", "Outline", "Normal", "HairShadow"))]
    return (good or imgs or [None])[0]

for mat in {s.material for o in keep for s in o.material_slots if s.material}:
    img = main_image(mat) if mat.use_nodes else None
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    outn = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.inputs["Roughness"].default_value = 1.0
    nt.links.new(bsdf.outputs["BSDF"], outn.inputs["Surface"])
    if img:
        tex = nt.nodes.new("ShaderNodeTexImage")
        tex.image = img
        nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
        if img.channels == 4 and img.alpha_mode != "NONE":
            if "Alpha" in mat.name:
                nt.links.new(tex.outputs["Alpha"], bsdf.inputs["Alpha"])       # soft: blended (face shading, blush)
            else:
                # Hair cards and lace: cut out, not blended. Blended, their many
                # layers can't be sorted and the hair went see-through and glassy.
                # (A Greater Than on the alpha is what the glTF exporter reads as MASK.)
                cut = nt.nodes.new("ShaderNodeMath")
                cut.operation = "GREATER_THAN"
                cut.inputs[1].default_value = 0.5
                nt.links.new(tex.outputs["Alpha"], cut.inputs[0])
                nt.links.new(cut.outputs["Value"], bsdf.inputs["Alpha"])
    print("MAT", mat.name, img.name if img else "-")
    if img and not img.packed_file and not os.path.exists(bpy.path.abspath(img.filepath)):
        print("MISSING_TEXTURE", img.name)          # (body3d.py: the .blend came without its textures)

bpy.ops.object.select_all(action="DESELECT")
for o in keep + [arm]:
    o.select_set(True)
bpy.ops.export_scene.gltf(filepath=out, export_format="GLB", use_selection=True, export_skins=True,
                          export_morph=True, export_morph_normal=False, export_apply=False,
                          export_animations=False, export_yup=True)
print("EXPORTED", out, [o.name for o in keep])
