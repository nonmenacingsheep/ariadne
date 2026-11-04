"""Her motion board for ComfyUI: make Kimodo clips for Aries' 3D body,
preview them (a quick skeleton, or on her own body in her room), and add the
good ones to her clip library.

Linked into ComfyUI as custom_nodes/aries_motion. Kimodo runs in its own venv
(pet/import/kimodo_one.py); her body renders in Godot (pet.gd's film: mode).
The Kimodo text encoder (Llama, ~16 GB of RAM, on the CPU) starts on the first
take and is stopped again after 20 idle minutes.
"""
import json
import os
import shutil
import subprocess
import threading
import time
import urllib.request

import numpy as np
import torch
from PIL import Image, ImageDraw

import comfy.utils
import folder_paths

HERE = os.path.dirname(os.path.realpath(__file__))
PET = os.path.dirname(HERE)
IMPORT = os.path.join(PET, "import")
K = "/var/mnt/games/AI/Kimodo"
CLIPS = f"{K}/clips/aries"
GODOT = "/var/mnt/games/DevTools/godot-4.7.2/Godot_v4.7.2-stable_linux.x86_64"
GATE = os.path.expanduser("~/.local/bin/godot-gate.sh")
ENCODER_URL = "http://127.0.0.1:9550/"
ENCODER_IDLE = 20 * 60

# Her base poses (kimodo_keyed.py refs: clip:frame, /degrees turns her).
POSES = {
    "free": "-",
    "standing": "idle_calm_1:0",
    "sitting on a ledge": "sit_idle_1:0",
    "sitting on the floor": "floor_sit_1:0",
    "crouching": "crouch_idle_1:0",
    "kneeling": "cushion_kneel_src_1:-1",
    "lying on her back": "lie_idle_2:0",
    "on her stomach": "lie_idle_1:0",
}
END_POSES = {"same as start": "=", **POSES}

_encoder = {"proc": None, "used": 0.0}


def _encoder_up() -> bool:
    try:
        urllib.request.urlopen(ENCODER_URL, timeout=2)
        return True
    except Exception:
        return False


def _ensure_encoder(pbar) -> None:
    _encoder["used"] = time.time()
    if _encoder_up():
        return
    env = dict(os.environ, HF_HOME="/var/mnt/games/AI/hf", TEXT_ENCODER_DEVICE="cpu", OMP_NUM_THREADS="6",
               GRADIO_SERVER_NAME="127.0.0.1")
    log = open(f"{K}/clips/encoder.log", "w")
    _encoder["proc"] = subprocess.Popen([f"{K}/.venv/bin/kimodo_textencoder"], env=env, stdout=log, stderr=log)
    for i in range(240):                          # loading Llama takes a few minutes the first time
        if _encoder_up():
            return
        if _encoder["proc"].poll() is not None:
            raise RuntimeError(f"Kimodo's text encoder didn't start; see {K}/clips/encoder.log")
        pbar.update_absolute(min(i, 40), 100)
        time.sleep(5)
    raise RuntimeError("Kimodo's text encoder took over 20 minutes to load")


def _watch_encoder() -> None:
    # Frees its ~16 GB of RAM when nobody's made a take for a while (only one we started).
    while True:
        time.sleep(60)
        p = _encoder["proc"]
        if p is not None and p.poll() is None and time.time() - _encoder["used"] > ENCODER_IDLE:
            p.terminate()
            _encoder["proc"] = None


threading.Thread(target=_watch_encoder, daemon=True).start()


def _take_dir() -> str:
    d = os.path.join(folder_paths.get_output_directory(), "aries_motion")
    os.makedirs(d, exist_ok=True)
    return d


class MakeHerMotion:
    """A Kimodo take from a prompt, optionally starting and ending in one of her poses."""

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "prompt": ("STRING", {"multiline": True, "default": "A woman waves happily with her right hand."}),
            "seconds": ("FLOAT", {"default": 5.0, "min": 1.0, "max": 12.0, "step": 0.5}),
            "seed": ("INT", {"default": 1, "min": 1, "max": 99999}),
            "start_pose": (list(POSES), {"default": "standing"}),
            "end_pose": (list(END_POSES), {"default": "same as start"}),
        }, "optional": {
            "custom_start": ("STRING", {"default": "", "tooltip": "a pose of your own: clip:frame or clip:frame/degrees"}),
            "custom_end": ("STRING", {"default": ""}),
        }}

    RETURN_TYPES = ("ARIES_MOTION", "STRING")
    RETURN_NAMES = ("motion", "check")
    FUNCTION = "make"
    CATEGORY = "Aries"

    def make(self, prompt, seconds, seed, start_pose, end_pose, custom_start="", custom_end=""):
        pbar = comfy.utils.ProgressBar(100)
        _ensure_encoder(pbar)
        a = custom_start.strip() or POSES[start_pose]
        b = custom_end.strip() or (a if END_POSES[end_pose] == "=" else END_POSES[end_pose])
        out = os.path.join(_take_dir(), f"take_{int(time.time())}_{seed}")
        spec = {"prompt": prompt, "seconds": seconds, "seed": seed, "start": a, "end": b, "out": out}
        json.dump(spec, open(out + ".spec.json", "w"))
        pbar.update_absolute(50, 100)
        subprocess.run([f"{K}/.venv/bin/python", os.path.join(IMPORT, "kimodo_one.py"), out + ".spec.json"],
                       cwd=IMPORT, capture_output=True, text=True)
        _encoder["used"] = time.time()
        pbar.update_absolute(100, 100)
        res = json.load(open(out + ".json")) if os.path.exists(out + ".json") else {"ok": False, "check": "no result"}
        if not os.path.exists(out + ".npz"):
            raise RuntimeError(res.get("check", "Kimodo made nothing"))
        words = ("passed the checks: " if res.get("ok") else "FAILED the checks: ") + res.get("check", "")
        return ({"stem": out, "prompt": prompt, "parents": res.get("parents", [])}, words)


def _frames_to_tensor(frames):
    return torch.from_numpy(np.stack([np.asarray(f.convert("RGB"), dtype=np.float32) / 255.0 for f in frames]))


class PreviewSkeleton:
    """A quick look: her skeleton drawn front and side, at 15 frames a second."""

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"motion": ("ARIES_MOTION",), "view": (["front and side", "front", "side"],)}}

    RETURN_TYPES = ("IMAGE",)
    FUNCTION = "draw"
    CATEGORY = "Aries"

    def draw(self, motion, view):
        d = np.load(motion["stem"] + ".npz")
        pj = d["posed_joints"][::2]                   # 30 -> 15 frames a second
        parents = motion.get("parents") or []
        views = {"front and side": [0, 2], "front": [0], "side": [2]}[view]
        size, scale = 320, 130.0
        lo = pj.reshape(-1, 3).min(0)
        hi = pj.reshape(-1, 3).max(0)
        frames = []
        for p in pj:
            img = Image.new("RGB", (size * len(views), size), (44, 46, 54))
            g = ImageDraw.Draw(img)
            for vi, axis in enumerate(views):
                ox = vi * size + size / 2
                mid = (lo[axis] + hi[axis]) / 2
                def at(j):
                    x = (p[j][axis] - mid) * scale            # front: her left (+x) on your right; side: facing right
                    return (ox + x, size - 24 - p[j][1] * scale)
                g.line([(vi * size + 10, size - 24), (vi * size + size - 10, size - 24)], fill=(90, 90, 100), width=2)
                for j, pa in enumerate(parents):
                    if pa >= 0:
                        g.line([at(pa), at(j)], fill=(235, 90, 110) if p[j][0] > 0 else (120, 190, 255), width=3)
                g.text((vi * size + 8, 6), ["front", "", "side"][axis], fill=(200, 200, 210))
            frames.append(img)
        return (_frames_to_tensor(frames),)


class PreviewOnHer:
    """Her own body in her room playing the take (about a minute: Blender, then Godot)."""

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"motion": ("ARIES_MOTION",), "view": (["front", "three-quarter", "side"],)}}

    RETURN_TYPES = ("IMAGE",)
    FUNCTION = "film"
    CATEGORY = "Aries"

    def film(self, motion, view):
        pbar = comfy.utils.ProgressBar(100)
        stem = motion["stem"]
        name = "preview_" + os.path.basename(stem).replace("take_", "")
        work = stem + "_film"
        shutil.rmtree(work, ignore_errors=True)
        os.makedirs(work)
        shutil.copy(stem + ".bvh", os.path.join(work, name + ".bvh"))
        pdir = os.path.join(PET, "assets", "anims", "preview")
        os.makedirs(pdir, exist_ok=True)
        glb = os.path.join(pdir, "preview.glb")
        for f in os.listdir(pdir):
            os.remove(os.path.join(pdir, f))
        subprocess.run([GATE, "blender", "-b", "--python", os.path.join(IMPORT, "bvh_to_glb.py"), "--", glb,
                        os.path.join(work, name + ".bvh")], capture_output=True)
        if not os.path.exists(glb):
            raise RuntimeError("Blender couldn't turn the take into a clip")
        # the same retarget onto her as her clip pack (kimodo.glb.import's settings)
        src = open(os.path.join(PET, "assets", "anims", "kimodo", "kimodo.glb.import")).read()
        params = src[src.index("[params]"):]
        open(glb + ".import", "w").write('[remap]\n\nimporter="scene"\nimporter_version=1\ntype="PackedScene"\n\n' + params)
        pbar.update_absolute(40, 100)
        env = dict(os.environ)
        env.setdefault("DISPLAY", ":0")
        subprocess.run([GATE, GODOT, "--headless", "--path", PET, "--import"], env=env, capture_output=True)
        pbar.update_absolute(60, 100)
        env.update(PET_PREVIEW_GLB="res://assets/anims/preview/preview.glb", PET_SNAPSHOT_SEQ="film:" + name,
                   PET_FILM_VIEW=view, PET_MODEL="res://models/jane.glb", PET_SNAPSHOT=os.path.join(work, "f.png"))
        r = subprocess.run([GATE, GODOT, "--path", PET, "--display-driver", "x11"], env=env, capture_output=True,
                           text=True, timeout=300)
        shots = sorted(f for f in os.listdir(work) if f.startswith("f_film_"))
        if not shots:
            raise RuntimeError("Her body didn't film: " + (r.stdout + r.stderr)[-500:])
        pbar.update_absolute(90, 100)
        ims = [Image.open(os.path.join(work, f)).convert("RGBA") for f in shots]
        box = None
        for im in ims:                                # one crop round everywhere she goes
            b = im.getchannel("A").point(lambda v: 255 if v > 0 else 0).getbbox()
            if b:
                box = b if box is None else (min(box[0], b[0]), min(box[1], b[1]), max(box[2], b[2]), max(box[3], b[3]))
        box = box or (0, 0, *ims[0].size)
        pad = 30
        box = (max(0, box[0] - pad), max(0, box[1] - pad), min(ims[0].width, box[2] + pad), min(ims[0].height, box[3] + pad))
        frames = []
        for im in ims:
            bg = Image.new("RGBA", im.size, (44, 46, 54, 255))
            bg.alpha_composite(im)
            c = bg.crop(box)
            if c.height > 540:
                c = c.resize((int(c.width * 540 / c.height), 540))
            frames.append(c)
        return (_frames_to_tensor(frames),)


class AddToHerClips:
    """Keeps a take: into her clip library under a name (role prefixes like play_, solo_,
    idle_happy_ decide where she uses it), and repacks her clips (a few minutes)."""

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"motion": ("ARIES_MOTION",),
                             "name": ("STRING", {"default": "idle_happy_9"}),
                             "repack": ("BOOLEAN", {"default": True})}}

    RETURN_TYPES = ("STRING",)
    FUNCTION = "add"
    OUTPUT_NODE = True
    CATEGORY = "Aries"

    def add(self, motion, name, repack):
        name = "".join(c for c in name.strip() if c.isalnum() or c == "_")
        if not name:
            raise RuntimeError("give it a name (letters, digits, _)")
        if os.path.exists(os.path.join(CLIPS, name + ".npz")):
            raise RuntimeError(f"she already has a clip called {name}")
        for ext in (".npz", ".bvh"):
            shutil.copy(motion["stem"] + ext, os.path.join(CLIPS, name + ext))
        msg = f"Added {name} to her clips."
        if repack:
            r = subprocess.run([os.path.join(IMPORT, "kimodo_batch.sh"), "--pack"], capture_output=True, text=True,
                               env=dict(os.environ, KIMODO_THREADS="6"))
            msg += " " + (r.stdout.strip().splitlines() or ["repacked"])[-1] + ". Restart her body to use it."
        return {"ui": {"text": [msg]}, "result": (msg,)}


NODE_CLASS_MAPPINGS = {
    "AriesMakeMotion": MakeHerMotion,
    "AriesPreviewSkeleton": PreviewSkeleton,
    "AriesPreviewOnHer": PreviewOnHer,
    "AriesAddToClips": AddToHerClips,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "AriesMakeMotion": "Make Her Motion (Kimodo)",
    "AriesPreviewSkeleton": "Preview: Skeleton",
    "AriesPreviewOnHer": "Preview: On Her Body",
    "AriesAddToClips": "Add To Her Clips",
}
