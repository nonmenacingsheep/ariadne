"""Adding a 3D body he (or anyone) dropped in: a .vrm, .glb or .blend, as it came.

The drop folder is the Live2D one (~/Aries Models, body_models.py); a loose
file or an archive/folder with one inside is converted here into
pet/models/dropin/<slug>/ (its own folder: Godot unpacks a GLB's textures beside
it) and checked, and only then listed in Avatar > Model:

- .vrm: copied as it is; the project's VRM importer maps its humanoid bones
  (the way Aries herself, pet/models/aries.vrm, loads).
- .glb: copied, with a humanoid bone map written for it (<slug>_bonemap.tres)
  and an import file that retargets its skeleton onto Godot's humanoid
  profile, as jane/kuromoji/shiromoji are by hand. The map comes from a VRM
  extension if the file has one, else from its bones' names and hierarchy
  (Mixamo, VRoid, Booth/VRChat, Rigify DEF, MMD's Japanese names...).
- .blend: exported to .glb headless by Blender (pet/import/avatar_export.py:
  rest pose, modifiers applied, plain materials, every outfit's pieces), then
  as a .glb. Its outfits come off its collections (--outfits): alternatives
  side by side (Sweater / Swimsuit, one hair style / another) each become an
  outfit in Avatar > Outfit, with the file's own fit keys, what each covers
  hidden in it, and the pieces the file hides kept hidden.

Then Godot imports it headless and pet/import/check_body.gd loads it and
reports its bones and height: a body without the bones her clips drive (or
that won't load) is removed again with the reason, a centimetre-scaled one is
re-imported at 1/100. <slug>.json (the body's own settings, as for the
hand-made ones) names it; settings.bodies() lists a drop-in only once that's
written. Dropping a changed copy of the same file replaces it.

Nothing is run from the download: Blender opens a .blend without its scripts
(-b, auto-run off by default), and archives are unpacked by pet2d.importer.
"""
from __future__ import annotations

import glob
import json
import logging
import os
import re
import shutil
import struct
import subprocess
import tempfile
from pathlib import Path

from ..pet2d import importer as live2d

log = logging.getLogger("ariadne2.body3d")

REPO = Path(__file__).resolve().parents[2]
PET = REPO / "pet"
DROPIN = PET / "models" / "dropin"
KINDS = (".vrm", ".glb", ".blend")
PREFER = {".vrm": 0, ".glb": 1, ".blend": 2}      # in a download with several, the VRM is the finished body
IMPORT_TIMEOUT = 600
BLENDER_TIMEOUT = 1200
# What her clips can't do without (Godot's humanoid profile names).
NEED = ["Hips", "Spine", "Head"] + [f"{s}{b}" for s in ("Left", "Right")
                                     for b in ("UpperArm", "LowerArm", "Hand", "UpperLeg", "LowerLeg", "Foot")]


class ImportError_(Exception):
    """A plain-English reason the body couldn't be added."""


def is_candidate(path: Path) -> bool:
    """A loose 3D file, or a folder with one in it (archives are looked into by import_model)."""
    path = Path(path)
    if path.is_file():
        return path.suffix.lower() in KINDS
    return path.is_dir() and _find_source(path) is not None


def _find_source(root: Path) -> Path | None:
    found = [p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in KINDS
             and not p.name.endswith(".blend1") and "__MACOSX" not in p.parts]
    # The finished body over its source; a shallow, short-named file over a deep or variant one
    # (Shiromoji_v12.1.blend over Shiromoji_v12.1_Blender.blend).
    found.sort(key=lambda p: (PREFER[p.suffix.lower()], len(p.parts), len(p.name), str(p)))
    return found[0] if found else None


# ---- glTF ---------------------------------------------------------------------

def read_gltf(path: Path) -> dict:
    """The JSON chunk of a .glb or .vrm (both are binary glTF)."""
    with open(path, "rb") as f:
        head = f.read(20)
        if len(head) < 20 or head[:4] != b"glTF":
            raise ImportError_(f"{Path(path).name} isn't a binary glTF file")
        length, kind = struct.unpack("<II", head[12:20])
        if kind != 0x4E4F534A:                    # "JSON"
            raise ImportError_(f"{Path(path).name} has no glTF JSON chunk")
        return json.loads(f.read(length).decode("utf-8"))


def _bone_name(node: dict, i: int) -> str:
    # Godot names a bone after its node, with ':' and '/' made '_' (mixamorig:Hips -> mixamorig_Hips).
    return (node.get("name") or f"bone_{i}").replace(":", "_").replace("/", "_")


def _node_name(node: dict, i: int) -> str:
    # A scene node's name, as Godot validates it.
    return re.sub(r'[.:@/"%]', "_", node.get("name") or f"Node{i}")


def _mat(node: dict) -> list[float]:
    """The node's local transform, column-major 4x4 (glTF's own layout)."""
    if "matrix" in node:
        return list(node["matrix"])
    tx, ty, tz = node.get("translation", [0, 0, 0])
    x, y, z, w = node.get("rotation", [0, 0, 0, 1])
    sx, sy, sz = node.get("scale", [1, 1, 1])
    return [(1 - 2 * (y * y + z * z)) * sx, (2 * (x * y + z * w)) * sx, (2 * (x * z - y * w)) * sx, 0,
            (2 * (x * y - z * w)) * sy, (1 - 2 * (x * x + z * z)) * sy, (2 * (y * z + x * w)) * sy, 0,
            (2 * (x * z + y * w)) * sz, (2 * (y * z - x * w)) * sz, (1 - 2 * (x * x + y * y)) * sz, 0,
            tx, ty, tz, 1]


def _mul(a: list[float], b: list[float]) -> list[float]:
    return [sum(a[k * 4 + r] * b[c * 4 + k] for k in range(4)) for c in range(4) for r in range(4)]


class Rig:
    """A glTF's skeleton: its joints, their parents and children, rest positions (world)."""

    def __init__(self, gltf: dict) -> None:
        self.nodes = gltf.get("nodes") or []
        self.joints = sorted({j for s in gltf.get("skins") or [] for j in s.get("joints") or []})
        if not self.joints:
            raise ImportError_("it has no skeleton (no skinned mesh), so it can't move")
        self.parent: dict[int, int] = {}
        for i, n in enumerate(self.nodes):
            for c in n.get("children") or []:
                self.parent[c] = i
        self.is_joint = set(self.joints)
        self.children = {j: [c for c in self.nodes[j].get("children") or [] if c in self.is_joint]
                         for j in self.joints}
        self.world: dict[int, list[float]] = {}
        for j in self.joints:
            self.pos(j)

    def name(self, j: int) -> str:
        return _bone_name(self.nodes[j], j)

    def pos(self, i: int) -> tuple[float, float, float]:
        if i not in self.world:
            p = self.parent.get(i)
            local = _mat(self.nodes[i])
            self.world[i] = _mul(self.pos_m(p), local) if p is not None else local
        m = self.world[i]
        return m[12], m[13], m[14]

    def pos_m(self, i: int) -> list[float]:
        self.pos(i)
        return self.world[i]

    def up_chain(self, j: int) -> list[int]:
        """j's ancestors among the joints, nearest first."""
        out = []
        p = self.parent.get(j)
        while p is not None and p in self.is_joint:
            out.append(p)
            p = self.parent.get(p)
        return out

    def below(self, j: int) -> list[int]:
        """Every joint under j, nearest first (breadth first)."""
        out, todo = [], list(self.children.get(j, []))
        while todo:
            c = todo.pop(0)
            out.append(c)
            todo += self.children.get(c, [])
        return out

    def depth(self, j: int) -> int:
        return len(self.up_chain(j))

    def common(self, a: int, b: int) -> int | None:
        up = [a] + self.up_chain(a)
        for x in [b] + self.up_chain(b):
            if x in up:
                return x
        return None

    def armature_path(self) -> str:
        """Where Godot puts its Skeleton3D: under the root joint's non-joint parents."""
        roots = [j for j in self.joints if self.parent.get(j) not in self.is_joint]
        root = min(roots, key=lambda j: len(self.below(j)) * -1)
        chain, p = [], self.parent.get(root)
        while p is not None:
            chain.append(_node_name(self.nodes[p], p))
            p = self.parent.get(p)
        return "/".join(list(reversed(chain)) + ["Skeleton3D"])


# ---- the humanoid map ------------------------------------------------------------

VRM0_THUMB = {"ThumbProximal": "ThumbMetacarpal", "ThumbIntermediate": "ThumbProximal"}


def _from_vrm(gltf: dict, rig: Rig) -> dict[str, str]:
    ext = gltf.get("extensions") or {}
    out = {}
    if "VRMC_vrm" in ext:                         # VRM 1.0
        for bone, v in ((ext["VRMC_vrm"].get("humanoid") or {}).get("humanBones") or {}).items():
            if isinstance(v, dict) and isinstance(v.get("node"), int):
                out[bone[0].upper() + bone[1:]] = rig.name(v["node"])
    elif "VRM" in ext:                            # VRM 0.x: its thumb is a bone further out
        for v in (ext["VRM"].get("humanoid") or {}).get("humanBones") or []:
            if isinstance(v.get("node"), int) and v.get("bone"):
                prof = v["bone"][0].upper() + v["bone"][1:]
                for old, new in VRM0_THUMB.items():
                    prof = prof.replace(old, new)
                out[prof] = rig.name(v["node"])
    return out


_DROP = {"j", "bip", "bip01", "c", "def", "org", "mch", "b", "bone", "cc", "base", "valvebiped", "mixamorig",
         "jnt", "sk", "skel"}
FINGERS = (("Thumb", ("thumb", "親指")), ("Index", ("index", "人指", "人差指", "pointer")),
           ("Middle", ("middle", "中指")), ("Ring", ("ring", "薬指")), ("Little", ("little", "pinky", "小指")))


def _words(name: str) -> tuple[str | None, set[str], str]:
    """(side, the words, all of it run together) of a bone name."""
    n = re.sub(r"^.*[:|]", "", name)
    n = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", n)
    side = "Left" if "左" in n else ("Right" if "右" in n else None)
    n = n.replace("左", " ").replace("右", " ")
    words = [w for w in re.split(r"[\s._\-]+", n.lower()) if w]
    for w in list(words):
        if w in ("l", "left"):
            side = "Left"
        elif w in ("r", "right"):
            side = "Right"
    words = [w for w in words if w not in ("l", "r", "left", "right") and w not in _DROP]
    # "LeftArm" became "left arm"; "Arm_L" became "arm"; "lhand"/"rhand" are rare enough to leave.
    return side, set(words), "".join(words)


def _helper(name: str) -> bool:
    side, words, flat = _words(name)
    return bool(words & {"twist", "roll", "helper", "ik", "pole", "target", "end", "nub", "tip", "dummy", "socket"}
                or any(k in flat for k in ("twist", "捩", "ダミー", "ｉｋ")))


def _part(name: str) -> str | None:
    """What part of a body a bone name says it is, without the side."""
    side, words, flat = _words(name)
    for fid, keys in FINGERS:
        if any(k in flat for k in keys):
            return "finger:" + fid
    if _helper(name):
        return None                               # rig helpers, not body parts
    if "手首" in flat or "hand" in flat or "wrist" in flat:
        return "Hand"
    if "ひじ" in flat or "肘" in flat or "forearm" in flat or "lowerarm" in flat or "armlower" in flat \
            or "elbow" in flat:
        return "LowerArm"
    if "肩" in flat or "shoulder" in flat or "clavicle" in flat or "collar" in flat:
        return "Shoulder"
    if "腕" in flat or "upperarm" in flat or "armupper" in flat or flat in ("arm", "uparm"):
        return "UpperArm"
    if "つま先" in flat or "toe" in flat:
        return "Toes"
    if "足首" in flat or "foot" in flat or "ankle" in flat:
        return "Foot"
    if "ひざ" in flat or "膝" in flat or "calf" in flat or "shin" in flat or "knee" in flat \
            or "lowerleg" in flat or "leglower" in flat or flat == "leg":
        return "LowerLeg"
    if "thigh" in flat or "upperleg" in flat or "legupper" in flat or "upleg" in flat or flat == "足":
        return "UpperLeg"
    if "目" in flat or (flat.startswith(("eye", "pupil")) and "brow" not in flat and "lid" not in flat):
        return "Eye"
    if flat in ("head", "頭"):
        return "Head"
    if flat in ("neck", "首"):
        return "Neck"
    if flat in ("hips", "hip", "pelvis", "下半身", "root hips") and side is None:
        return "Hips"
    return None


def _side(rig: Rig, j: int) -> str | None:
    side = _words(rig.nodes[j].get("name") or "")[0]
    if side:
        return side
    x = rig.pos(j)[0]
    # glTF bodies face +Z, so their left is +X.
    return "Left" if x > 0.01 else ("Right" if x < -0.01 else None)


def _from_names(rig: Rig) -> dict[str, str]:
    parts = {j: _part(rig.nodes[j].get("name") or "") for j in rig.joints}
    out: dict[str, int] = {}
    limb = {}
    for side in ("Left", "Right"):
        for end, ups in (("Hand", ("LowerArm", "UpperArm", "Shoulder")), ("Foot", ("LowerLeg", "UpperLeg"))):
            ends = [j for j in rig.joints if parts[j] == end and _side(rig, j) == side]
            if not ends:
                continue
            e = min(ends, key=rig.depth)          # the wrist, not a hand helper under it
            out[side + end] = e
            # (a twist or helper bone between them isn't a joint of hers)
            chain = [a for a in rig.up_chain(e) if not _helper(rig.nodes[a].get("name") or "")]
            for k, up in enumerate(ups):
                named = [a for a in chain if parts[a] == up]
                if named:
                    # the top one of a split bone (Rigify's upper_arm, .001); the shoulder
                    # nearest the arm (MMD's ShoulderP is a helper above it)
                    out[side + up] = named[0] if up == "Shoulder" else named[-1]
                elif k < len(chain) and up != "Shoulder":
                    out[side + up] = chain[k]     # by place: the hand's parent is the forearm
            limb[side + end] = e
    if "LeftUpperLeg" in out and "RightUpperLeg" in out:
        hips = rig.common(out["LeftUpperLeg"], out["RightUpperLeg"])
        if hips is not None and hips not in (out["LeftUpperLeg"], out["RightUpperLeg"]):
            out["Hips"] = hips
    named_hips = [j for j in rig.joints if parts[j] == "Hips"]
    if "Hips" not in out and named_hips:
        out["Hips"] = min(named_hips, key=rig.depth)
    # The spine: from where the arms meet down to (not including) the hips or what holds them.
    top = None
    if "LeftUpperArm" in out and "RightUpperArm" in out:
        top = rig.common(out["LeftUpperArm"], out["RightUpperArm"])
    heads = [j for j in rig.joints if parts[j] == "Head"]
    if heads:
        out["Head"] = min(heads, key=rig.depth)
        necks = [a for a in rig.up_chain(out["Head"]) if parts[a] == "Neck"]
        if necks:
            out["Neck"] = necks[0]
        elif top is not None and rig.parent.get(out["Head"]) not in (top, None):
            out["Neck"] = rig.parent[out["Head"]]
    if "Head" not in out and top is not None:
        # No bone called head (Rigify's DEF-spine.006): up the neck from where the
        # arms meet, along its single line, to where it branches (the face) or ends.
        arm_line = {a for k in ("LeftHand", "RightHand") if k in out for a in rig.up_chain(out[k])}
        kids = [c for c in rig.children.get(top, []) if c not in arm_line and c not in out.values()]
        if kids:
            n = max(kids, key=lambda c: len(rig.below(c)))
            out["Neck"] = n
            while len(rig.children.get(n, [])) == 1 and rig.children[rig.children[n][0]]:
                n = rig.children[n][0]
            if n != out["Neck"]:
                out["Head"] = n
            else:
                out["Head"], out["Neck"] = n, None
                del out["Neck"]
    if top is not None and "Hips" in out:
        hips_line = {out["Hips"], *rig.up_chain(out["Hips"])}
        spine = []
        j = top
        while j is not None and j in rig.is_joint and j not in hips_line:
            spine.append(j)
            j = rig.parent.get(j)
        spine.reverse()                           # hips end first
        spine = [s for s in spine if s != out.get("Neck")]
        if spine:
            out["Spine"] = spine[0]
            if len(spine) == 2:
                out["Chest"] = spine[1]
            elif len(spine) >= 3:
                out["Chest"] = spine[len(spine) // 2] if len(spine) > 3 else spine[1]
                out["UpperChest"] = spine[-1]
    for side in ("Left", "Right"):
        foot = out.get(side + "Foot")
        if foot is not None:
            toes = [c for c in rig.below(foot) if parts[c] == "Toes"] or rig.children.get(foot, [])[:1]
            if toes:
                out[side + "Toes"] = toes[0]
        head = out.get("Head")
        if head is not None:
            eyes = [c for c in rig.below(head) if parts[c] == "Eye" and _side(rig, c) == side]
            if eyes:
                out[side + "Eye"] = eyes[0]
        hand = out.get(side + "Hand")
        if hand is None:
            continue
        for fid, _ in FINGERS:
            chain = sorted((c for c in rig.below(hand) if parts[c] == "finger:" + fid), key=rig.depth)
            # one bone per depth (a finger's own helpers sit beside it)
            seen, line = set(), []
            for c in chain:
                if rig.depth(c) not in seen:
                    seen.add(rig.depth(c))
                    line.append(c)
            names = (["Metacarpal", "Proximal", "Distal"] if fid == "Thumb"
                     else ["Proximal", "Intermediate", "Distal"])
            # Not its tip (Mixamo's Index4, an "_end" leaf), and not a metacarpal
            # before the knuckle (Index0) where the profile starts at the knuckle.
            line = [c for c in line if rig.children.get(c) or not re.search(r"([4-9]|end|tip|nub)$",
                                                                            rig.name(c).lower())]
            if fid != "Thumb" and len(line) >= 4 and re.search(r"(0|meta\w*)$", rig.name(line[0]).lower()):
                line = line[1:]
            for k, c in enumerate(line[:3]):
                out[f"{side}{fid}{names[k]}"] = c
    return {k: rig.name(v) for k, v in out.items()}


def humanoid_map(gltf: dict) -> tuple[dict[str, str], str]:
    """(Godot humanoid profile bone -> this file's bone, where its skeleton goes in the scene)."""
    rig = Rig(gltf)
    found = _from_vrm(gltf, rig) or _from_names(rig)
    missing = [b for b in NEED if b not in found]
    if missing:
        raise ImportError_("I couldn't tell which of its bones are her " + ", ".join(missing)
                           + " (its skeleton isn't a humanoid one I know)")
    return found, rig.armature_path()


# ---- files Godot reads -------------------------------------------------------------

def bonemap_tres(mapping: dict[str, str]) -> str:
    esc = lambda s: s.replace("\\", "\\\\").replace('"', '\\"')
    lines = ['[gd_resource type="BoneMap" load_steps=2 format=3]', "",
             '[sub_resource type="SkeletonProfileHumanoid" id="1"]', "", "[resource]",
             'profile = SubResource("1")']
    lines += [f'bone_map/{k} = &"{esc(v)}"' for k, v in sorted(mapping.items())]
    return "\n".join(lines) + "\n"


def glb_import(slug: str, skeleton_path: str, scale: float = 1.0) -> str:
    """The import settings jane/kuromoji/shiromoji use: renamed onto the humanoid profile, rest fixed."""
    return f"""[remap]

importer="scene"
importer_version=1
type="PackedScene"

[deps]

source_file="res://models/dropin/{slug}/{slug}.glb"

[params]

nodes/root_type=""
nodes/root_name="{slug}"
nodes/apply_root_scale=true
nodes/root_scale={scale}
nodes/import_as_skeleton_bones=false
meshes/ensure_tangents=true
meshes/generate_lods=true
meshes/create_shadow_meshes=false
skins/use_named_skins=true
animation/import=false
_subresources={{
"nodes": {{
"PATH:{skeleton_path}": {{
"retarget/bone_map": Resource("res://models/dropin/{slug}/{slug}_bonemap.tres"),
"retarget/bone_renamer/rename_bones": true,
"retarget/bone_renamer/unique_node/make_unique": true,
"retarget/bone_renamer/unique_node/skeleton_name": "GeneralSkeleton",
"retarget/remove_tracks/except_bone_transform": true,
"retarget/remove_tracks/unimportant_positions": false,
"retarget/remove_tracks/unmapped_bones": false,
"retarget/rest_fixer/apply_node_transforms": true,
"retarget/rest_fixer/fix_silhouette/enable": true,
"retarget/rest_fixer/fix_silhouette/filter": [&"Hips", &"Spine", &"Chest", &"UpperChest", &"Neck", &"Head", &"LeftFoot", &"RightFoot", &"LeftToes", &"RightToes"],
"retarget/rest_fixer/normalize_position_tracks": true,
"retarget/rest_fixer/retarget_method": 1
}}
}}
}}
gltf/naming_version=2
gltf/embedded_image_handling=1
"""


# ---- the tools ---------------------------------------------------------------------

def _first(*cands) -> str | None:
    for c in cands:
        if c and Path(c).is_file() and os.access(c, os.X_OK):
            return str(c)
    return None


def godot() -> str | None:
    return _first(os.environ.get("ARIADNE2_GODOT"),
                  "/var/mnt/games/DevTools/godot-4.7.2/Godot_v4.7.2-stable_linux.x86_64",
                  REPO / "tools" / "godot" / "godot", shutil.which("godot4"), shutil.which("godot"))


def blender() -> str | None:
    return _first(os.environ.get("ARIADNE2_BLENDER"), *sorted(glob.glob("/var/mnt/games/DevTools/blender-*/blender"),
                                                               reverse=True),
                  REPO / "tools" / "blender" / "blender", shutil.which("blender"))


def _gate() -> list[str]:
    # Ronald's machine: heavy runs wait for the CPU and GPU to have room (godot-gate.sh).
    g = Path.home() / ".local" / "bin" / "godot-gate.sh"
    return [str(g)] if g.is_file() and os.access(g, os.X_OK) else []


def _run(argv: list[str], timeout: int) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(argv, capture_output=True, text=True, errors="replace", timeout=timeout,
                              stdin=subprocess.DEVNULL, cwd=str(REPO))
    except subprocess.TimeoutExpired:
        raise ImportError_(f"{Path(argv[len(_gate())]).name} took over {timeout // 60} minutes; gave up")


def _export_blend(src: Path, out: Path) -> list[str]:
    """Blender's export of it; the textures it couldn't find."""
    exe = blender()
    if not exe:
        raise ImportError_("a .blend needs Blender to convert it, and I can't find Blender "
                           "(set ARIADNE2_BLENDER to its path, or export a .glb or .vrm from it)")
    proc = _run(_gate() + [exe, "-b", str(src), "--python", str(PET / "import" / "avatar_export.py"),
                           "--", str(out), "--all", "--outfits", str(out.with_suffix(".outfits.json"))],
                BLENDER_TIMEOUT)
    missing = sorted({ln.split(" ", 1)[1] for ln in proc.stdout.splitlines() if ln.startswith("MISSING_TEXTURE ")})
    if not out.exists():
        tail = (proc.stdout + proc.stderr)[-600:]
        reason = "it has no armature" if "StopIteration" in tail else "Blender couldn't export it"
        log.warning("blender export of %s failed: %s", src.name, tail)
        raise ImportError_(reason)
    return missing


def _import(exe: str) -> None:
    _run([exe, "--headless", "--path", str(PET), "--import"], IMPORT_TIMEOUT)


def check(exe: str, res_path: str) -> dict:
    """pet/import/check_body.gd's report on a body: its bones, skeleton path and size."""
    proc = _run([exe, "--headless", "--path", str(PET), "--script", "res://import/check_body.gd", "--", res_path], 180)
    for line in (proc.stdout or "").splitlines():
        if line.startswith("BODYCHECK "):
            try:
                return json.loads(line[len("BODYCHECK "):])
            except ValueError:
                break
    return {"ok": False, "why": "Godot couldn't load it"}


# ---- the whole of it ---------------------------------------------------------------

def _slug_for(display: str, src_name: str) -> str:
    """The same slug for a new copy of the same download; else a fresh one."""
    DROPIN.mkdir(parents=True, exist_ok=True)
    for cfg in DROPIN.glob("*/*.json"):
        try:
            if cfg.stem == cfg.parent.name and json.loads(cfg.read_text()).get("imported_from") == src_name:
                return cfg.stem
        except (OSError, ValueError):
            continue
    taken = {p.name for p in DROPIN.iterdir()} | {p.name.split(".")[0] for p in (PET / "models").iterdir()}
    taken |= {"aries", "dropin"}
    return live2d._slug(display, taken)


def _clear(slug: str) -> None:
    shutil.rmtree(DROPIN / slug, ignore_errors=True)


def import_model(src: Path) -> tuple[str, str]:
    """("3d:<slug>", a line saying what happened). Raises ImportError_ with a plain reason."""
    src = Path(src)
    exe = godot()
    if not exe:
        raise ImportError_("3D bodies need Godot 4, and I can't find it (install.sh can fetch it)")
    with tempfile.TemporaryDirectory(prefix="aries-body3d-") as tmp:
        tmp = Path(tmp)
        if src.is_file() and src.suffix.lower() in live2d.ARCHIVES:
            live2d._unpack(src, tmp / "x")
            found = _find_source(tmp / "x")
        elif src.is_dir():
            found = _find_source(src)
        else:
            found = src if src.suffix.lower() in KINDS else None
        if found is None:
            raise ImportError_("there's no .vrm, .glb or .blend in it")
        kind = found.suffix.lower()
        display = re.sub(r"[_\-]+", " ", found.stem).strip() or src.stem
        slug = _slug_for(display if display.isascii() else src.stem, src.name)
        _clear(slug)
        home = DROPIN / slug
        home.mkdir(parents=True)
        notes = []
        if kind == ".vrm":
            model = home / f"{slug}.vrm"
            shutil.copyfile(found, model)
        else:
            model = home / f"{slug}.glb"
            if kind == ".blend":
                lost = _export_blend(found, model)
                notes.append("converted from Blender")
                if lost:
                    notes.append(f"{len(lost)} of its textures weren't beside the .blend, so it's plain where they go "
                                 "(drop the whole download, or pack them into the .blend in Blender)")
            else:
                shutil.copyfile(found, model)
            try:
                mapping, skel_path = humanoid_map(read_gltf(model))
            except ImportError_:
                _clear(slug)
                raise
            (home / f"{slug}_bonemap.tres").write_text(bonemap_tres(mapping))
            (home / f"{slug}.glb.import").write_text(glb_import(slug, skel_path))
    res = f"res://models/dropin/{slug}/{model.name}"
    _import(exe)
    got = check(exe, res)
    if kind != ".vrm" and not got.get("ok") and got.get("skeleton_path") and got["skeleton_path"] != skel_path:
        # Godot put the skeleton somewhere else than guessed: point the retarget there and go again.
        (home / f"{slug}.glb.import").write_text(glb_import(slug, got["skeleton_path"]))
        skel_path = got["skeleton_path"]
        _import(exe)
        got = check(exe, res)
    if kind != ".vrm" and got.get("ok") and float(got.get("height", 0)) > 20:
        # Made in centimetres (a 170 m tall body): at 1/100 she's her own height.
        (home / f"{slug}.glb.import").write_text(glb_import(slug, skel_path, 0.01))
        _import(exe)
        got = check(exe, res)
        notes.append("scaled from centimetres")
    if not got.get("ok"):
        _clear(slug)
        why = got.get("why") or ("it's missing bones her moves need: " + ", ".join(got.get("missing", [])))
        raise ImportError_(why)
    cfg = {"_doc": "A body added from the drop folder (ariadne2/core/body3d.py); outfits etc. as models/*.json.",
           "name": display, "imported_from": src.name}
    worn = model.with_suffix(".outfits.json")         # a .blend's outfits, off its collections (avatar_export.py)
    if worn.exists():
        try:
            cfg.update(json.loads(worn.read_text()))
        except (OSError, ValueError):
            pass
        worn.unlink()
    if cfg.get("outfits"):
        notes.append(f"{len(cfg['outfits'])} outfits ({', '.join(cfg['outfits'])})")
    (home / f"{slug}.json").write_text(json.dumps(cfg, ensure_ascii=False, indent="\t") + "\n")
    bones = int(got.get("mapped", 0))
    said = f"Added {display} as a 3D body ({bones} bones matched to her moves"
    said += (", fingers too" if got.get("fingers") else "") + ")"
    return f"3d:{slug}", said + ("; " + "; ".join(notes) if notes else "") + "."


def bodies() -> list[tuple[str, str]]:
    """The drop-ins ready to wear: [("3d:<slug>", label)], for settings.bodies()."""
    out = []
    try:
        cfgs = sorted(DROPIN.glob("*/*.json"))
    except OSError:
        return out
    for cfg in cfgs:
        if cfg.stem != cfg.parent.name or not any((cfg.parent / f"{cfg.stem}{ext}").exists() for ext in (".glb", ".vrm")):
            continue
        try:
            name = json.loads(cfg.read_text()).get("name") or cfg.stem
        except (OSError, ValueError):
            continue
        out.append((f"3d:{cfg.stem}", f"{name} (3D, walks about)"))
    return out
