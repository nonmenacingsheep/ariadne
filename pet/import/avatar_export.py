"""Export a VRChat-style Booth avatar .blend as a GLB for the 3D body (pet/).

blender -b <avatar>.blend --python pet/import/avatar_export.py -- pet/models/<name>.glb [--all] [--cover Body=Pants+Top] [--outfits <name>.json] [skip collection ...]

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
  (a shoulder cut-out, the leg openings) sees out and stays;
- with --outfits <file> (drop-ins, ariadne2/core/body3d.py), its outfits are
  read off the collections and written as pet/models/<name>.json's: a
  collection whose child collections are alternatives (Sweater, Swimsuit; a
  hair style and another), not category folders (Cloth, Footwear, Hair), is
  a choice, and each alternative an outfit; the one showing in the file is
  the default (the biggest, if several show). Pieces hidden in the file stay
  hidden. A fit key named after an outfit (Body_2's "Sweater") is on in it.
  A loose piece an outfit covers entirely (her underwear under the sweater)
  is hidden in it, and the body's skin the default outfit covers is split
  off (as --cover) and shown only in the others.
The .blend itself is never saved.
"""
import os
import sys

import bpy

args = sys.argv[sys.argv.index("--") + 1:]
out = args[0]
every = "--all" in args
cover = args[args.index("--cover") + 1] if "--cover" in args else ""
outfits_out = args[args.index("--outfits") + 1] if "--outfits" in args else ""
skip = {a for a in args[1:] if a not in ("--all", "--cover", cover, "--outfits", outfits_out)}
FACE_KEYS = ("vrc.v_aa", "vrc.Blink", "まばたき")
HELPERS = ("DataTransfer",)

arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")

# How the file shows things, before everything is unhidden for the export (--outfits).
import re
CATEGORY = {"cloth", "clothes", "clothing", "outfit", "outfits", "costume", "costumes", "footwear", "shoes",
            "headwear", "hats", "accessory", "accessories", "acc", "hair", "body", "base", "armature", "props",
            "other", "others", "misc", "extra", "extras", "option", "options", "mesh", "meshes"}
shown_in_file = {o.name: o.visible_get() for o in bpy.data.objects if o.type == "MESH"}
own_hidden = {o.name: bool(o.hide_render or o.hide_get() or o.hide_viewport)
              for o in bpy.data.objects if o.type == "MESH"}
coll_parent = {}
for c in [bpy.context.scene.collection, *bpy.data.collections]:
    for ch in c.children:
        coll_parent[ch.name] = c
def meshes_in(c):
    return [o.name for o in c.all_objects if o.type == "MESH" and not any(h in o.name for h in ("DataTransfer",))]
groups = []      # [[alternative collection, ...], ...]
for c in [bpy.context.scene.collection, *bpy.data.collections]:
    alts = [ch for ch in c.children if meshes_in(ch) and re.sub(r"[^a-z]", "", ch.name.lower()) not in CATEGORY]
    if len(alts) >= 2:
        groups.append(alts)
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

# Skin under clothes (--cover, and --outfits' default outfit).
import math
from mathutils.bvhtree import BVHTree

def _rays(n):
    """Across the hemisphere a point faces: its normal, then rings at 35 and 70 degrees."""
    t = n.orthogonal().normalized()
    b = n.cross(t)
    out = [n]
    for tilt in (math.radians(35), math.radians(70)):
        for k in range(8):
            a = k * math.tau / 8
            out.append((n * math.cos(tilt) + (t * math.cos(a) + b * math.sin(a)) * math.sin(tilt)).normalized())
    return out

def cloth_tree(cloth):
    dg = bpy.context.evaluated_depsgraph_get()
    verts, polys = [], []
    for c in cloth:
        ev = c.evaluated_get(dg)
        me = ev.to_mesh()
        base = len(verts)
        verts += [ev.matrix_world @ v.co for v in me.vertices]
        polys += [[base + i for i in p.vertices] for p in me.polygons]
        ev.to_mesh_clear()
    return BVHTree.FromPolygons(verts, polys) if polys else None

def hidden_by(ob, cloth):
    """Per vertex of ob: True if every ray out of it hits the cloth (objects, or a cloth_tree)."""
    tree = cloth if isinstance(cloth, BVHTree) or cloth is None else cloth_tree(cloth)
    if tree is None:
        return [False] * len(ob.data.vertices)
    mw = ob.matrix_world
    nm = mw.to_3x3().inverted().transposed()
    out = []
    for v in ob.data.vertices:
        p = mw @ v.co
        n = (nm @ v.normal).normalized()
        out.append(all(tree.ray_cast(p + n * 0.001, d, 0.3)[0] is not None for d in _rays(n)))
    return out

def under_frac(ob, tree, within=0.03):
    """How much of ob (by vertex) has the cloth just outside it, along its outward
    normal: under it (underwear under a sweater), not on it (a pin in the hair)."""
    if tree is None or not ob.data.vertices:
        return 0.0
    mw = ob.matrix_world
    nm = mw.to_3x3().inverted().transposed()
    hit = 0
    for v in ob.data.vertices:
        n = (nm @ v.normal).normalized()
        hit += tree.ray_cast(mw @ v.co + n * 0.001, n, within)[0] is not None
    return hit / len(ob.data.vertices)

def split_under(body, cloth):
    """Splits off the body's faces the cloth hides, as <body>_Under; returns it (or None)."""
    hid = hidden_by(body, cloth)
    under = [f.index for f in body.data.polygons if all(hid[i] for i in f.vertices)]
    print("COVER", body.name, len(under), "of", len(body.data.polygons), "faces hidden by", [c.name for c in cloth])
    if not under:
        return None
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
    piece.name = body.name + "_Under"
    keep.append(piece)
    return piece

if cover:
    body_name, cloth = cover.split("=")
    split_under(bpy.data.objects[body_name], [bpy.data.objects[n] for n in cloth.split("+")])

# Outfits off the collections (--outfits).
UNDER_GARMENT = 0.5      # how much of a loose piece an outfit's garments lie over for it to come off
if outfits_out:
    import json
    node = lambda n: re.sub(r'[.:@/"%]', "_", n)          # as Godot names the mesh's node
    pretty = lambda n: re.sub(r"[_\-]+", " ", n).strip()
    kept = {o.name for o in keep}
    grouped = {m for g in groups for c in g for m in meshes_in(c)}
    loose = [o for o in keep if o.name not in grouped and o.type == "MESH" and "_Under" not in o.name]
    always_hidden = sorted(node(o.name) for o in loose if not shown_in_file.get(o.name, True) or own_hidden.get(o.name))
    shown_loose = [o for o in loose if node(o.name) not in always_hidden]
    body = max(shown_loose, key=lambda o: len(o.data.polygons), default=None)    # the skin: the biggest loose piece
    worn = lambda c: [m for m in meshes_in(c) if m in kept and not own_hidden.get(m)]
    groups = [[c for c in g if worn(c)] for g in groups]
    groups = [g for g in groups if len(g) >= 2]          # (an alternative the file keeps hidden inside isn't one)
    # Each choice's default: what shows in the file; if several do (Shiromoji's
    # sweater and swimsuit both, in hers), the one covering most of her skin.
    picks = []
    for g in groups:
        on = [c for c in g if any(shown_in_file.get(m) for m in meshes_in(c))] or g[:1]
        if len(on) > 1 and body is not None:
            on.sort(key=lambda c: -sum(hidden_by(body, [bpy.data.objects[m] for m in worn(c)])))
        picks.append(on[0])
    combos = []
    if groups:
        first = pretty(picks[0].name) if len(groups) == 1 else "As made"
        combos.append((first, picks))
        for gi, g in enumerate(groups):
            for c in g:
                if c is not picks[gi]:
                    combos.append((pretty(c.name), picks[:gi] + [c] + picks[gi + 1:]))
    else:
        first = ""
    doc = {"default": first, "outfits": {}, "shapes": {}, "hide": always_hidden}
    # What each outfit has on: its choices' pieces and every loose piece showing but the skin.
    on_of = lambda chosen: [bpy.data.objects[m] for c in chosen for m in worn(c)] + [lp for lp in shown_loose if lp is not body]
    under = split_under(body, on_of(combos[0][1])) if combos and body is not None else None
    check = [lp for lp in shown_loose if lp is not body] + ([under] if under else [])
    has_face = lambda ob: bool(ob.data.shape_keys) and any(k in ob.data.shape_keys.key_blocks for k in FACE_KEYS)
    for name, chosen in combos:
        everything = cloth_tree(on_of(chosen))
        garments = cloth_tree([bpy.data.objects[m] for c in chosen for m in worn(c)])
        o = {"show": sorted(node(m) for c in chosen for m in worn(c)), "shapes": {}, "hide": []}
        # Hidden in it: the skin split off under the default, where all it has on
        # covers it; and a loose piece its own garments mostly cover (her
        # underwear under the sweater and pants), never her face.
        for lp in check:
            if lp is under:
                hid = hidden_by(lp, everything)
                frac = sum(hid) / max(len(hid), 1)
            else:
                frac = under_frac(lp, garments)
            print("COVERED", name, lp.name, round(frac, 3))
            if frac >= (0.9 if lp is under else UNDER_GARMENT) and not has_face(lp):
                o["hide"].append(node(lp.name))
        # Fit keys named after what it wears ("Sweater", "!_Shrink_Chest_Sweater").
        words = {re.sub(r"[^a-z]", "", w.lower()) for c in chosen for w in [c.name, *meshes_in(c)]}
        words = {w for w in words if len(w) >= 4}
        for lp in shown_loose:
            if lp.data.shape_keys:
                for key in lp.data.shape_keys.key_blocks[1:]:
                    flat = re.sub(r"[^a-z]", "", key.name.lower())
                    if any(w in flat for w in words):
                        o["shapes"][f"{node(lp.name)}/{key.name}"] = 1.0
                        doc["shapes"][f"{node(lp.name)}/{key.name}"] = 0.0
        doc["outfits"][name] = o
    # Hidden always: whatever the file hides that no outfit shows (a loose piece,
    # or an alternative it keeps hidden, like Kuromoji's flower earrings).
    shows = {m for o in doc["outfits"].values() for m in o["show"]}
    doc["hide"] = sorted(node(o.name) for o in keep if o.type == "MESH" and node(o.name) not in shows
                         and "_Under" not in o.name and (not shown_in_file.get(o.name, True) or own_hidden.get(o.name)))
    always_hidden = doc["hide"]
    if len(doc["outfits"]) < 2:
        doc = {"hide": always_hidden}                    # one way to dress: nothing to choose
    with open(outfits_out, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent="\t")
    print("OUTFITS", list(doc.get("outfits", {})), "hidden:", always_hidden)

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
