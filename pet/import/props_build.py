"""Her room's furniture, built in Blender: pet/models/props.glb.

    blender -b --python pet/import/props_build.py -- pet/models/props.glb

Each prop is one object with its origin on the floor at its centre, its front
toward -Y (the camera, in Godot), real sizes in metres. Soft bevels and warm,
plain colours, so the toon shading in pet.gd reads them like her. The heights
that clips depend on are named: SEAT (chair, the sitting clips' seat), FUTON
(the mattress top she lies on).
"""
import math
import sys

import bpy

SEAT = 0.47          # SIT_DROP in pet.gd: the seat height in her sitting clips
FUTON = 0.14

bpy.ops.wm.read_factory_settings(use_empty=True)
MATS = {}


def mat(name, rgb, rough=0.7):
    if name not in MATS:
        m = bpy.data.materials.new(name)
        m.use_nodes = True
        b = m.node_tree.nodes["Principled BSDF"]
        b.inputs["Base Color"].default_value = (*(c ** 2.2 for c in rgb), 1)   # picked as sRGB
        b.inputs["Roughness"].default_value = rough
        MATS[name] = m
    return MATS[name]


COL = {
    "wood": (0.52, 0.33, 0.2), "wood_dark": (0.3, 0.19, 0.12), "cream": (0.93, 0.89, 0.8),
    "red": (0.62, 0.1, 0.12), "red_soft": (0.78, 0.33, 0.33), "charcoal": (0.12, 0.12, 0.14),
    "steel": (0.55, 0.57, 0.6), "screen": (0.05, 0.09, 0.16), "teal": (0.25, 0.5, 0.52),
    "leaf": (0.25, 0.5, 0.25), "terracotta": (0.72, 0.4, 0.27), "white": (0.95, 0.95, 0.94),
    "book1": (0.2, 0.3, 0.55), "book2": (0.75, 0.6, 0.25), "book3": (0.35, 0.55, 0.4),
    "rug": (0.5, 0.2, 0.22), "rug_edge": (0.8, 0.7, 0.55), "glow": (0.4, 0.7, 1.0),
}


def box(size, loc, color, bevel=0.012, parts=None):
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc)
    o = bpy.context.active_object
    o.scale = size
    bpy.ops.object.transform_apply(scale=True)
    if bevel > 0:
        m = o.modifiers.new("b", "BEVEL")
        m.width = min(bevel, min(size) * 0.45)
        m.segments = 3
        bpy.ops.object.modifier_apply(modifier="b")
    o.data.materials.append(mat(color, COL[color]))
    parts.append(o)
    return o


def cyl(r, h, loc, color, parts, verts=24, bevel=0.0, rot=None):
    bpy.ops.mesh.primitive_cylinder_add(radius=r, depth=h, vertices=verts, location=loc)
    o = bpy.context.active_object
    if rot:
        o.rotation_euler = rot
        bpy.ops.object.transform_apply(rotation=True)
    if bevel > 0:
        m = o.modifiers.new("b", "BEVEL")
        m.width = bevel
        m.segments = 2
        bpy.ops.object.modifier_apply(modifier="b")
    o.data.materials.append(mat(color, COL[color]))
    parts.append(o)
    return o


def ball(r, loc, color, parts, scale=(1, 1, 1)):
    bpy.ops.mesh.primitive_uv_sphere_add(radius=r, location=loc, segments=16, ring_count=10)
    o = bpy.context.active_object
    o.scale = scale
    bpy.ops.object.transform_apply(scale=True)
    bpy.ops.object.shade_smooth()
    o.data.materials.append(mat(color, COL[color]))
    parts.append(o)
    return o


def join(name, parts):
    bpy.ops.object.select_all(action="DESELECT")
    for p in parts:
        p.select_set(True)
    bpy.context.view_layer.objects.active = parts[0]
    bpy.ops.object.join()
    o = bpy.context.active_object
    o.name = name
    bpy.context.scene.cursor.location = (0, 0, 0)
    bpy.ops.object.origin_set(type="ORIGIN_CURSOR")
    return o


def futon():
    p = []
    box((1.0, 2.0, 0.08), (0, 0, 0.04), "wood_dark", 0.01, p)                  # low frame
    box((0.95, 1.95, FUTON - 0.08), (0, 0, 0.08 + (FUTON - 0.08) / 2), "cream", 0.04, p)
    box((0.55, 0.32, 0.1), (0, 0.78, FUTON + 0.05), "white", 0.045, p)         # pillow (head at the back)
    box((0.97, 0.9, 0.04), (0, -0.45, FUTON + 0.02), "red", 0.02, p)           # blanket over the foot
    box((0.97, 0.12, 0.05), (0, -0.02, FUTON + 0.025), "red_soft", 0.02, p)    # its folded edge
    return join("futon", p)


def desk():
    p = []
    box((1.2, 0.6, 0.035), (0, 0, 0.74), "wood", 0.008, p)
    for x in (-0.56, 0.56):
        for y in (-0.25, 0.25):
            box((0.04, 0.04, 0.72), (x, y, 0.36), "wood_dark", 0.006, p)
    # monitor at the back, facing her (she sits on the -Y side, facing +Y: her back to the camera)
    box((0.62, 0.03, 0.38), (0, 0.18, 1.03), "charcoal", 0.012, p)
    box((0.56, 0.005, 0.32), (0, 0.164, 1.03), "screen", 0.0, p)
    box((0.06, 0.05, 0.16), (0, 0.2, 0.83), "charcoal", 0.01, p)
    box((0.22, 0.14, 0.015), (0, 0.2, 0.765), "charcoal", 0.006, p)
    box((0.42, 0.14, 0.02), (-0.05, -0.08, 0.77), "white", 0.006, p)          # keyboard
    ball(0.035, (0.3, -0.08, 0.77), "white", p, (0.7, 1.0, 0.45))              # mouse
    cyl(0.04, 0.1, (-0.45, 0.12, 0.81), "red", p)                               # mug
    box((0.2, 0.15, 0.02), (0.42, 0.12, 0.765), "book2", 0.004, p)              # notebook
    return join("desk", p)


def chair():
    p = []
    box((0.44, 0.42, 0.06), (0, 0, SEAT - 0.03), "red", 0.025, p)               # seat cushion
    box((0.42, 0.06, 0.42), (0, -0.2, SEAT + 0.24), "red", 0.025, p)            # back (toward the camera)
    cyl(0.025, SEAT - 0.08, (0, 0, (SEAT - 0.08) / 2 + 0.06), "steel", p)
    for a in range(5):
        ang = a * 2 * math.pi / 5
        box((0.03, 0.26, 0.025), (math.sin(ang) * 0.13, math.cos(ang) * 0.13, 0.05), "charcoal", 0.006, p) \
            .rotation_euler = (0, 0, -ang)
        ball(0.025, (math.sin(ang) * 0.25, math.cos(ang) * 0.25, 0.025), "charcoal", p)
    for o in p:
        bpy.context.view_layer.objects.active = o
        o.select_set(True)
    bpy.ops.object.transform_apply(rotation=True)
    return join("chair", p)


def low_table():
    p = []
    box((0.8, 0.5, 0.04), (0, 0, 0.33), "wood", 0.012, p)
    for x in (-0.35, 0.35):
        for y in (-0.2, 0.2):
            box((0.05, 0.05, 0.31), (x, y, 0.155), "wood_dark", 0.008, p)
    cyl(0.1, 0.012, (0.15, 0.05, 0.356), "white", p)                            # plate
    ball(0.045, (0.15, 0.05, 0.37), "book2", p, (1.0, 0.8, 0.5))                 # bun on it
    cyl(0.035, 0.09, (-0.2, 0.1, 0.395), "teal", p)                             # cup
    return join("low_table", p)


def cushion():
    p = []
    box((0.48, 0.48, 0.09), (0, 0, 0.045), "red_soft", 0.04, p)
    return join("cushion", p)


def mat_():
    p = []
    box((0.62, 1.8, 0.008), (0, 0, 0.004), "teal", 0.003, p)
    cyl(0.03, 0.22, (0.42, 0.75, 0.035), "charcoal", p, rot=(0, math.pi / 2, 0))   # a dumbbell by it
    cyl(0.055, 0.03, (0.32, 0.75, 0.055), "charcoal", p, rot=(0, math.pi / 2, 0))
    cyl(0.055, 0.03, (0.52, 0.75, 0.055), "charcoal", p, rot=(0, math.pi / 2, 0))
    cyl(0.035, 0.6, (-0.45, 0.6, 0.035), "red", p, rot=(math.pi / 2, 0, 0))        # rolled towel
    return join("mat", p)


def shelf():
    p = []
    box((0.8, 0.3, 0.025), (0, 0, 1.2), "wood", 0.006, p)
    for z in (0.02, 0.42, 0.81):
        box((0.76, 0.28, 0.02), (0, 0, z), "wood", 0.004, p)
    for x in (-0.39, 0.39):
        box((0.025, 0.3, 1.2), (x, 0, 0.6), "wood_dark", 0.006, p)
    box((0.8, 0.02, 1.2), (0, 0.14, 0.6), "wood_dark", 0.0, p)
    import random
    random.seed(4)
    for z in (0.03, 0.43, 0.82):
        x = -0.35
        while x < 0.3:
            w = random.uniform(0.03, 0.06)
            h = random.uniform(0.22, 0.32)
            box((w, 0.2, h), (x + w / 2, 0, z + h / 2), random.choice(["book1", "book2", "book3", "red"]), 0.004, p)
            x += w + 0.005
            if random.random() < 0.12:
                x += 0.1
    return join("shelf", p)


def plant():
    p = []
    cyl(0.16, 0.3, (0, 0, 0.15), "terracotta", p, bevel=0.01)
    cyl(0.14, 0.02, (0, 0, 0.29), "wood_dark", p)
    for i in range(7):
        a = i * 2 * math.pi / 7
        ball(0.13, (math.cos(a) * 0.1, math.sin(a) * 0.1, 0.5 + (i % 3) * 0.1), "leaf", p, (1, 1, 1.3))
    ball(0.15, (0, 0, 0.75), "leaf", p, (1, 1, 1.2))
    return join("plant", p)


def kitchen():
    p = []
    box((1.2, 0.6, 0.86), (0, 0, 0.43), "white", 0.015, p)                      # cabinet
    box((1.24, 0.64, 0.04), (0, 0, 0.88), "wood", 0.01, p)                     # worktop
    for x in (-0.3, 0.3):
        box((0.56, 0.01, 0.78), (x, -0.3, 0.42), "cream", 0.006, p)            # doors
        box((0.12, 0.02, 0.015), (x, -0.31, 0.75), "steel", 0.005, p)
    box((0.5, 0.4, 0.012), (0.25, 0.05, 0.906), "charcoal", 0.004, p)          # hob
    cyl(0.12, 0.13, (0.25, 0.05, 0.975), "steel", p, bevel=0.005)              # pot
    cyl(0.1, 0.02, (-0.3, 0.05, 0.91), "white", p)                              # chopping board-ish plate
    return join("kitchen", p)


def rug():
    p = []
    cyl(1.0, 0.008, (0, 0, 0.004), "rug_edge", p, verts=48)
    cyl(0.9, 0.01, (0, 0, 0.005), "rug", p, verts=48)
    return join("rug", p)


def can():
    p = []
    cyl(0.07, 0.16, (0, 0, 0.08), "teal", p, bevel=0.01)
    cyl(0.012, 0.2, (0, -0.13, 0.12), "teal", p, rot=(math.radians(-60), 0, 0))
    return join("watering_can", p)


for f in (futon, desk, chair, low_table, cushion, mat_, shelf, plant, kitchen, rug, can):
    o = f()
bpy.ops.object.select_all(action="SELECT")
out = sys.argv[sys.argv.index("--") + 1]
bpy.ops.export_scene.gltf(filepath=out, export_format="GLB", use_selection=True, export_apply=True)
print("PROPS", [o.name for o in bpy.data.objects])
