"""Build the clip gallery: every animation on her, to keep, remake or remove.

    PET_SNAPSHOT_SEQ=gallery PET_GALLERY_DIR=<dir> (pet.gd _gallery) films the clips;
    python3 pet/import/gallery.py <dir>   then makes <dir>/index.html.

Each clip becomes a looping WebP (<dir>/webp/<clip>.webp) beside its prompt
(the Kimodo lists in pet/import/*.txt), the file it came from, and what of
hers plays it (a role in pet.gd, an interaction in play.json, an episode beat,
a place state). Every clip is numbered so he can say in chat which need work; the
frames are fan-model renders and stay on this machine.
"""
import json
import re
import shutil
import sys
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
PET = HERE.parent
out = Path(sys.argv[1])
clips = json.loads((out / "clips.json").read_text())

# Prompts: name|seconds|prompt[|...] in the Kimodo lists (takes may be name_sN).
prompts = {}
for f in sorted(HERE.glob("kimodo_*.txt")):
    for line in f.read_text().splitlines():
        if "|" in line and not line.lstrip().startswith("#"):
            bits = line.split("|")
            prompts[bits[0].strip()] = bits[2].strip() if len(bits) > 2 else ""

# What plays it: every quoted name or prefix in her code and data that a clip starts with.
users = {}
for f, what in ((PET / "pet.gd", "role"), (PET / "brain.gd", "brain"), (PET / "play.json", "play"),
                (PET / "episodes.json", "episode"), (PET / "states.json", "place"), (PET / "life.gd", "life")):
    if f.exists():
        for ref in set(re.findall(r'"([A-Za-z][A-Za-z0-9_]{2,})"', f.read_text())):
            users.setdefault(ref, set()).add(what)


def used_by(name: str) -> list[str]:
    hit = set()
    for ref, whats in users.items():
        if name == ref or (ref.endswith("_") and name.startswith(ref)):
            hit |= whats
    return sorted(hit)


def family(name: str) -> str:
    base = re.sub(r"(_s\d+)?$", "", name)
    base = re.sub(r"_\d+$", "", base)
    return base.split("_")[0] if "_" in base else base


webp = out / "webp"
webp.mkdir(exist_ok=True)
rows = []
for c in clips:
    name = c["name"]
    src = out / re.sub(r'[\\/:*?"<>|]', "_", name)
    frames = sorted(src.glob("*.png"))
    dst = webp / f"{name}.webp"
    if frames and not dst.exists():
        ims = [Image.open(p).convert("RGBA") for p in frames]
        ims[0].save(dst, save_all=True, append_images=ims[1:], duration=67, loop=0, quality=72, method=4)
    base = re.sub(r"_s\d+$", "", name)
    rows.append({**c, "num": 0, "family": family(name), "prompt": prompts.get(name) or prompts.get(base, ""),
                 "used": used_by(name), "webp": f"webp/{name}.webp"})
# Numbered in the order the page shows them (by family, then name), so he can
# say "#14 needs work" in chat; clips.txt is the same list as text.
rows.sort(key=lambda r: (r["family"], r["name"]))
for i, r in enumerate(rows, 1):
    r["num"] = i
(out / "clips.txt").write_text("".join(f"#{r['num']} {r['name']}  ({r['seconds']}s, {', '.join(r['used']) or 'not used'})\n" for r in rows))
(out / "data.js").write_text("const CLIPS = " + json.dumps(rows) + ";\n")
shutil.copy(HERE / "gallery.html", out / "index.html")
print(f"{len(rows)} clips -> {out / 'index.html'}")
