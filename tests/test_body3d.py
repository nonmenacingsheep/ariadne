"""3D bodies from the drop folder: the humanoid bone map, Godot's files, and the folder's dispatch."""
import json
import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ariadne2.core import body3d as B


def rig(tree: dict, armature: str | None = "Armature", ext: dict | None = None) -> dict:
    """A glTF of a skeleton: tree is {name: (x, [children])}; every bone is a skin joint."""
    nodes, index = [], {}

    def add(name):
        index[name] = len(nodes)
        nodes.append({"name": name, "translation": [tree[name][0], 0.1, 0.0]})
        for c in tree[name][1]:
            nodes[index[name]].setdefault("children", []).append(add(c))
        return index[name]
    roots = [n for n in tree if not any(n in v[1] for v in tree.values())]
    tops = [add(r) for r in roots]
    joints = list(range(len(nodes)))
    if armature:
        nodes.append({"name": armature, "children": tops})
    g = {"nodes": nodes, "skins": [{"joints": joints}], "meshes": [{}]}
    if ext:
        g["extensions"] = ext
    return g, index


def chain(names, x=0.0):
    """{name: (x, [next])} for a line of bones."""
    return {n: (x, [names[i + 1]] if i + 1 < len(names) else []) for i, n in enumerate(names)}


def mixamo():
    t = {}
    p = "mixamorig:"
    t.update(chain([p + "Hips", p + "Spine", p + "Spine1", p + "Spine2", p + "Neck", p + "Head", p + "HeadTop_End"]))
    t[p + "Hips"] = (0, [p + "Spine", p + "LeftUpLeg", p + "RightUpLeg"])
    t[p + "Spine2"] = (0, [p + "Neck", p + "LeftShoulder", p + "RightShoulder"])
    for side, x in (("Left", 0.2), ("Right", -0.2)):
        t.update(chain([p + f"{side}Shoulder", p + f"{side}Arm", p + f"{side}ForeArm", p + f"{side}Hand"], x))
        t[p + f"{side}Hand"] = (x, [p + f"{side}HandIndex1", p + f"{side}HandThumb1"])
        t.update(chain([p + f"{side}HandIndex{i}" for i in range(1, 5)], x))
        t.update(chain([p + f"{side}HandThumb{i}" for i in range(1, 5)], x))
        t.update(chain([p + f"{side}UpLeg", p + f"{side}Leg", p + f"{side}Foot", p + f"{side}ToeBase", p + f"{side}Toe_End"], x))
    return t


class MapTests(unittest.TestCase):
    def test_mixamo_names_and_hierarchy(self):
        g, _ = rig(mixamo())
        m, path = B.humanoid_map(g)
        self.assertEqual(path, "Armature/Skeleton3D")
        self.assertEqual(m["Hips"], "mixamorig_Hips")                # Godot's ':' -> '_'
        self.assertEqual([m["Spine"], m["Chest"], m["UpperChest"]],
                         ["mixamorig_Spine", "mixamorig_Spine1", "mixamorig_Spine2"])
        self.assertEqual(m["Head"], "mixamorig_Head")
        self.assertEqual(m["LeftUpperArm"], "mixamorig_LeftArm")
        self.assertEqual(m["LeftLowerArm"], "mixamorig_LeftForeArm")
        self.assertEqual(m["RightUpperLeg"], "mixamorig_RightUpLeg")
        self.assertEqual(m["RightLowerLeg"], "mixamorig_RightLeg")
        self.assertEqual(m["LeftToes"], "mixamorig_LeftToeBase")
        # the finger's tip (Index4) is no joint of hers
        self.assertEqual([m["LeftIndexProximal"], m["LeftIndexDistal"]],
                         ["mixamorig_LeftHandIndex1", "mixamorig_LeftHandIndex3"])
        self.assertEqual(m["LeftThumbMetacarpal"], "mixamorig_LeftHandThumb1")

    def test_rigify_split_bones_and_an_unnamed_head(self):
        t = chain(["DEF-spine", "DEF-spine.001", "DEF-spine.002", "DEF-spine.003", "DEF-spine.004",
                   "DEF-spine.005", "DEF-spine.006"])
        t["DEF-spine"] = (0, ["DEF-spine.001", "DEF-thigh.L", "DEF-thigh.R"])
        t["DEF-spine.003"] = (0, ["DEF-spine.004", "DEF-shoulder.L", "DEF-shoulder.R"])
        t["DEF-spine.006"] = (0, ["DEF-jaw", "DEF-forehead"])
        t["DEF-jaw"] = (0, [])
        t["DEF-forehead"] = (0, [])
        for s, x in (("L", 0.2), ("R", -0.2)):
            t.update(chain([f"DEF-shoulder.{s}", f"DEF-upper_arm.{s}", f"DEF-upper_arm.{s}.001",
                            f"DEF-forearm.{s}", f"DEF-forearm.{s}.001", f"DEF-hand.{s}"], x))
            t.update(chain([f"DEF-thigh.{s}", f"DEF-thigh.{s}.001", f"DEF-shin.{s}", f"DEF-shin.{s}.001",
                            f"DEF-foot.{s}", f"DEF-toe.{s}"], x))
        m, _ = B.humanoid_map(rig(t)[0])
        self.assertEqual(m["Hips"], "DEF-spine")
        self.assertEqual(m["LeftUpperArm"], "DEF-upper_arm.L")      # the top half of the split bone
        self.assertEqual(m["LeftLowerArm"], "DEF-forearm.L")
        self.assertEqual(m["RightLowerLeg"], "DEF-shin.R")
        self.assertEqual(m["Head"], "DEF-spine.006")                # up the neck to where the face branches
        self.assertEqual(m["Neck"], "DEF-spine.004")

    def test_side_from_place_when_names_dont_say(self):
        t = mixamo()
        g, idx = rig(t)
        for side in ("Left", "Right"):                              # "Hand.001"-style names, no side
            for n in g["nodes"]:
                n["name"] = n["name"].replace(f"mixamorig:{side}", "mixamorig:" + ("A" if side == "Left" else "B"))
        m, _ = B.humanoid_map(g)
        self.assertEqual(m["LeftHand"], "mixamorig_AHand")          # +X is a glTF body's left
        self.assertEqual(m["RightFoot"], "mixamorig_BFoot")

    def test_vrm0_extension_wins_and_its_thumb_moves_out_one(self):
        g, idx = rig(mixamo(), ext={"VRM": {"humanoid": {"humanBones": []}}})
        bones = [("hips", "Hips"), ("spine", "Spine"), ("head", "Head"), ("leftThumbProximal", "LeftHandThumb1"),
                 ("leftThumbIntermediate", "LeftHandThumb2")]
        for side in ("left", "right"):
            S = side.title()
            bones += [(f"{side}UpperArm", f"{S}Arm"), (f"{side}LowerArm", f"{S}ForeArm"), (f"{side}Hand", f"{S}Hand"),
                      (f"{side}UpperLeg", f"{S}UpLeg"), (f"{side}LowerLeg", f"{S}Leg"), (f"{side}Foot", f"{S}Foot")]
        g["extensions"]["VRM"]["humanoid"]["humanBones"] = [{"bone": b, "node": idx["mixamorig:" + n]} for b, n in bones]
        m, _ = B.humanoid_map(g)
        self.assertEqual(m["LeftThumbMetacarpal"], "mixamorig_LeftHandThumb1")
        self.assertEqual(m["LeftThumbProximal"], "mixamorig_LeftHandThumb2")
        self.assertNotIn("UpperChest", m)                           # only what the file says

    def test_not_a_humanoid(self):
        with self.assertRaises(B.ImportError_) as cm:
            B.humanoid_map(rig(chain(["Tail_1", "Tail_2", "Tail_3"]))[0])
        self.assertIn("Hips", str(cm.exception))
        with self.assertRaises(B.ImportError_) as cm:
            B.humanoid_map({"nodes": [{"name": "Cube"}], "meshes": [{}]})
        self.assertIn("no skeleton", str(cm.exception))

    def test_skeleton_at_the_scene_root(self):
        self.assertEqual(B.humanoid_map(rig(mixamo(), armature=None)[0])[1], "Skeleton3D")


class FileTests(unittest.TestCase):
    def test_godot_files(self):
        tres = B.bonemap_tres({"Hips": 'we"ird', "Head": "Head"})
        self.assertIn('bone_map/Hips = &"we\\"ird"', tres)
        self.assertIn('[sub_resource type="SkeletonProfileHumanoid" id="1"]', tres)
        imp = B.glb_import("mika", "Armature/Skeleton3D", 0.01)
        self.assertIn('"PATH:Armature/Skeleton3D": {', imp)
        self.assertIn('Resource("res://models/dropin/mika/mika_bonemap.tres")', imp)
        self.assertIn("nodes/root_scale=0.01", imp)
        self.assertIn('"retarget/bone_renamer/unique_node/skeleton_name": "GeneralSkeleton"', imp)

    def test_read_gltf_and_what_counts(self):
        tmp = Path(tempfile.mkdtemp())
        doc = json.dumps({"asset": {"version": "2.0"}}).encode()
        doc += b" " * (-len(doc) % 4)
        (tmp / "a.glb").write_bytes(b"glTF" + struct.pack("<II", 2, 20 + len(doc)) + struct.pack("<II", len(doc), 0x4E4F534A) + doc)
        self.assertEqual(B.read_gltf(tmp / "a.glb")["asset"]["version"], "2.0")
        (tmp / "b.glb").write_bytes(b"nope")
        with self.assertRaises(B.ImportError_):
            B.read_gltf(tmp / "b.glb")
        d = tmp / "download"
        (d / "textures").mkdir(parents=True)
        for f in ("Mika_v1.blend", "Mika_v1_Blender.blend", "Mika.vrm", "Mika.blend1", "readme.txt"):
            (d / f).write_bytes(b"x")
        self.assertEqual(B._find_source(d).name, "Mika.vrm")      # the finished body first
        (d / "Mika.vrm").unlink()
        self.assertEqual(B._find_source(d).name, "Mika_v1.blend")
        self.assertTrue(B.is_candidate(d) and B.is_candidate(d / "Mika_v1.blend"))
        self.assertFalse(B.is_candidate(d / "readme.txt"))

    def test_listed_once_converted(self):
        tmp = Path(tempfile.mkdtemp())
        with mock.patch.object(B, "DROPIN", tmp):
            (tmp / "mika").mkdir()
            (tmp / "mika" / "mika.glb").write_bytes(b"x")
            self.assertEqual(B.bodies(), [])                          # not checked yet: no <slug>.json
            (tmp / "mika" / "mika.json").write_text(json.dumps({"name": "Mika v2", "imported_from": "Mika.zip"}))
            self.assertEqual(B.bodies(), [("3d:mika", "Mika v2 (3D, walks about)")])
            self.assertEqual(B._slug_for("Mika v2", "Mika.zip"), "mika")      # a new copy replaces it
            from ariadne2.core import settings
            self.assertIn(("3d:mika", "Mika v2 (3D, walks about)"), settings.bodies())
            # A .blend's outfits (avatar_export.py --outfits) are its Outfit choices.
            (tmp / "mika" / "mika.json").write_text(json.dumps({"name": "Mika v2", "default": "Sweater",
                                                                 "outfits": {"Sweater": {}, "Swimsuit": {}}}))
            with mock.patch.object(settings, "PET_MODELS", tmp.parent), mock.patch.object(B, "DROPIN", tmp):
                (tmp.parent / "dropin").mkdir(exist_ok=True)
                (tmp.parent / "dropin" / "mika").mkdir(exist_ok=True)
                (tmp.parent / "dropin" / "mika" / "mika.json").write_text((tmp / "mika" / "mika.json").read_text())
                self.assertEqual(settings.outfits("3d:mika"),
                                 [("", "Usual (Sweater)"), ("Sweater", "Sweater"), ("Swimsuit", "Swimsuit")])


class DispatchTests(unittest.TestCase):
    def test_3d_files_go_to_body3d_and_archives_fall_back_to_it(self):
        from ariadne2.core import body_models
        bm = body_models.BodyModels(publish=mock.AsyncMock(), settings=mock.Mock())
        tmp = Path(tempfile.mkdtemp())
        (tmp / "Mika.vrm").write_bytes(b"x")
        with mock.patch.object(B, "import_model", return_value=("3d:mika", "Added")) as three:
            self.assertEqual(bm._import(tmp / "Mika.vrm"), ("3d:mika", "Added"))
            three.assert_called_once()
        (tmp / "Mika.zip").write_bytes(b"x")
        from ariadne2.pet2d import importer
        with mock.patch.object(importer, "import_model",
                               side_effect=importer.ImportError_("there's no Live2D model in it (no .model3.json)")), \
                mock.patch.object(B, "import_model", return_value=("3d:mika", "Added")) as three:
            self.assertEqual(bm._import(tmp / "Mika.zip")[0], "3d:mika")


if __name__ == "__main__":
    unittest.main()
