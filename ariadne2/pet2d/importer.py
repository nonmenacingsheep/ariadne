"""Adding a Live2D model he downloaded: a folder or an archive, as it came.

Anything VTube Studio-shaped works: somewhere inside is a *.model3.json with
its .moc3, textures, physics and *.exp3.json expressions. This copies the
model's folder into web/models/<slug>/ and tidies it so the body can use it:

- every expression file that parses is listed in the model3.json (VTube
  Studio models often leave them out and bind them to hotkeys instead);
  broken ones are skipped and said so;
- blinking and lip sync are wired when the model left those groups empty,
  from the .vtube.json mapping or the usual Cubism parameter names;
- textures over 4096 px are shrunk (a desktop-pet sized body never needs
  more, and an 8192 one is 256 MB of GPU memory);
- about.json names it and maps her moods to its expressions by their names
  (angry/生气, blush/脸红, star/星星, heart/爱心, tears/泪 ...).

Archives are unpacked into a fresh empty folder with the system's own tools
(zip in Python; rar and 7z with unar or 7z), never run, and only the model's
folder is kept. Nothing outside web/models/ is written.
"""
from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import tempfile
import unicodedata
import zipfile
from pathlib import Path

log = logging.getLogger("ariadne2.pet2d.importer")

MODELS = Path(__file__).with_name("web") / "models"
ARCHIVES = (".zip", ".rar", ".7z")
MAX_TEXTURE = 4096
MAX_UNPACKED = 2 * 1024 ** 3          # an archive that unpacks past 2 GB isn't a model

# Her moods (pet2d.js LOOKS) -> words an expression's name or file might use.
LOOK_WORDS = {
    "angry": ("angry", "anger", "mad", "生气", "怒"),
    "blush": ("blush", "shy", "脸红", "害羞", "红"),
    "stars": ("star", "sparkle", "星星", "星"),
    "hearts": ("heart", "love", "爱心", "心"),
    "tears": ("tear", "cry", "sad", "泪", "哭"),
    "eyeroll": ("eyeroll", "roll", "白眼"),
    "gloom": ("dark", "gloom", "shadow", "脸黑", "黑"),
    "dizzy": ("dizzy", "swirl", "spin", "晕", "转圈"),
    "blood": ("blood", "bloody", "血"),
}


class ImportError_(Exception):
    pass


def is_candidate(path: Path) -> bool:
    """A download that might hold a model: an archive, or a folder with a model3.json in it."""
    path = Path(path)
    if path.is_file():
        return path.suffix.lower() in ARCHIVES or path.name.endswith(".model3.json")
    return path.is_dir() and next(path.rglob("*.model3.json"), None) is not None


def _slug(name: str, taken) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")[:24] or "model"
    base, n = s, 2
    while s in taken:
        s, n = f"{base}_{n}", n + 1
    return s


def _unpack(archive: Path, into: Path) -> None:
    suffix = archive.suffix.lower()
    if suffix == ".zip":
        with zipfile.ZipFile(archive) as z:
            if sum(i.file_size for i in z.infolist()) > MAX_UNPACKED:
                raise ImportError_("that archive unpacks to more than 2 GB; it isn't just a model")
            for info in z.infolist():
                target = (into / info.filename).resolve()
                if not str(target).startswith(str(into.resolve()) + "/") and target != into.resolve():
                    raise ImportError_("that archive tries to write outside its folder; not unpacking it")
            z.extractall(into)
        return
    for argv in (["unar", "-q", "-f", "-o", str(into), str(archive)], ["7z", "x", "-y", f"-o{into}", str(archive)]):
        if shutil.which(argv[0]):
            proc = subprocess.run(argv, capture_output=True, timeout=300, stdin=subprocess.DEVNULL)
            # unar reports a damaged member but keeps the rest; judge by what came out
            if any(into.rglob("*.model3.json")):
                return
            log.info("%s couldn't unpack %s: %s", argv[0], archive.name, proc.stderr[-300:])
    raise ImportError_(f"couldn't unpack {archive.name} (install unar or 7zip for {suffix} files)")


def _model_dir(root: Path) -> Path:
    found = sorted(root.rglob("*.model3.json"), key=lambda p: (len(p.parts), str(p)))
    if not found:
        raise ImportError_("there's no Live2D model in it (no .model3.json)")
    return found[0].parent


def _read(path: Path):
    return json.loads(path.read_text("utf-8-sig"))


def _params(folder: Path, model: dict) -> set[str]:
    """Parameter ids the model names in its display info (cdi3), if it has one."""
    ref = (model.get("FileReferences") or {}).get("DisplayInfo")
    try:
        return {p["Id"] for p in _read(folder / ref).get("Parameters", [])} if ref else set()
    except (OSError, ValueError, KeyError, TypeError):
        return set()


def _vtube_map(folder: Path) -> dict[str, str]:
    """VTube Studio's input -> model parameter mapping, if the model came with one."""
    for p in folder.glob("*.vtube.json"):
        try:
            return {s.get("Input"): s.get("OutputLive2D") for s in _read(p).get("ParameterSettings", [])
                    if s.get("Input") and s.get("OutputLive2D")}
        except (OSError, ValueError, AttributeError):
            pass
    return {}


def _shrink_textures(folder: Path, model: dict) -> int:
    try:
        from PIL import Image
    except ImportError:
        return 0
    Image.MAX_IMAGE_PIXELS = None
    n = 0
    for ref in (model.get("FileReferences") or {}).get("Textures", []):
        p = folder / ref
        try:
            with Image.open(p) as im:
                if max(im.size) <= MAX_TEXTURE:
                    continue
                scale = MAX_TEXTURE / max(im.size)
                small = im.resize((round(im.width * scale), round(im.height * scale)), Image.LANCZOS)
            small.save(p, optimize=True)
            n += 1
        except OSError as e:
            log.warning("couldn't shrink %s: %s", p.name, e)
    return n


def map_looks(expressions: list[dict]) -> dict[str, str]:
    """Her moods to the model's expressions, by what they're called."""
    looks: dict[str, str] = {}
    for look, words in LOOK_WORDS.items():
        for e in expressions:
            label = f"{e['Name']} {Path(e['File']).stem}".lower()
            if any(w in label for w in words):
                looks[look] = e["Name"]
                break
    return looks


def import_model(src: Path, root: Path | None = None) -> tuple[str, str]:
    """(slug, a line saying what happened). Raises ImportError_ with a plain reason."""
    src, root = Path(src), Path(root or MODELS)
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="aries-model-") as tmp:
        tmp = Path(tmp)
        if src.is_file() and src.suffix.lower() in ARCHIVES:
            _unpack(src, tmp / "x")
            folder = _model_dir(tmp / "x")
        elif src.is_file() and src.name.endswith(".model3.json"):
            folder = src.parent
        elif src.is_dir():
            folder = _model_dir(src)
        else:
            raise ImportError_("pick an archive (.zip, .rar, .7z) or a folder with a Live2D model in it")
        model_file = sorted(folder.glob("*.model3.json"))[0]
        display = model_file.name[: -len(".model3.json")] or folder.name
        slug = _slug(display if display.isascii() else folder.name, {p.name for p in root.iterdir()})
        dest = root / slug
        shutil.copytree(folder, dest, symlinks=False, ignore=shutil.ignore_patterns("*.exe", "*.dll", "*.bat", "*.sh"))
    model_path = dest / model_file.name
    try:
        model = _read(model_path)
    except ValueError as e:
        shutil.rmtree(dest)
        raise ImportError_(f"its .model3.json is broken ({e})")
    refs = model.setdefault("FileReferences", {})
    notes = []
    # Expressions: what the file lists, plus every *.exp3.json beside it, minus broken ones.
    listed = {e.get("File"): e.get("Name") for e in refs.get("Expressions", []) if e.get("File")}
    for p in sorted(dest.rglob("*.exp3.json")):
        listed.setdefault(p.relative_to(dest).as_posix(), p.name[: -len(".exp3.json")])
    exps, broken = [], []
    for file, name in listed.items():
        try:
            _read(dest / file)
            exps.append({"Name": name or Path(file).stem, "File": file})
        except (OSError, ValueError):
            broken.append(name or file)
    refs["Expressions"] = exps
    if broken:
        notes.append(f"skipped broken expression{'s' if len(broken) > 1 else ''}: {', '.join(broken)}")
    # Blinking and lip sync, when the model left the groups empty.
    groups = {g.get("Name"): g for g in model.setdefault("Groups", []) if isinstance(g, dict)}
    params, vts = _params(dest, model), _vtube_map(dest)
    want = {"EyeBlink": [vts.get("EyeOpenLeft", "ParamEyeLOpen"), vts.get("EyeOpenRight", "ParamEyeROpen")],
            "LipSync": [vts.get("MouthOpen", "ParamMouthOpenY")]}
    for name, ids in want.items():
        ids = [i for i in ids if not params or i in params]
        g = groups.get(name)
        if g is None:
            model["Groups"].append({"Target": "Parameter", "Name": name, "Ids": ids})
        elif not g.get("Ids"):
            g["Ids"] = ids
    model_path.write_text(json.dumps(model, ensure_ascii=False, indent=1), "utf-8")
    if _shrink_textures(dest, model):
        notes.append("shrank its textures to 4096 px")
    looks = map_looks(exps)
    about = {"name": display, "kind": "live2d", "model": model_file.name, "looks": looks,
             "imported_from": src.name}
    (dest / "about.json").write_text(json.dumps(about, ensure_ascii=False, indent=1), "utf-8")
    said = f"Added {display} as a Live2D body"
    if looks:
        said += f" ({len(exps)} expressions, {len(looks)} matched to her moods)"
    return slug, said + ("; " + "; ".join(notes) if notes else "") + "."
