"""What Dolphin's right-click menu does, on disk: which apps open a file, copies and pastes,
archives, and the Properties facts.

Plain functions with injectable inputs (like dolphin_files.py), so tests run in a temp dir with fake
.desktop files. The adapter (dolphin.py) wraps them in the guard and the verbs.
"""
from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import tarfile
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from . import dolphin_files as df

# ---------------------------------------------------------------- names

TAR_EXTS = (".tar.gz", ".tar.bz2", ".tar.xz", ".tar.zst", ".tar.lz", ".tar.lzma", ".tar.z")


def split_ext(name: str, is_dir: bool = False) -> tuple[str, str]:
    """('report', '.pdf'); '.tar.gz' stays together; folders and dotfiles have no extension."""
    if is_dir:
        return name, ""
    low = name.lower()
    for ext in TAR_EXTS:
        if low.endswith(ext) and len(name) > len(ext):
            return name[:-len(ext)], name[-len(ext):]
    stem, ext = os.path.splitext(name)
    return (stem, ext) if stem else (name, "")


def free_copy(folder: Path, name: str, is_dir: bool = False, tag: str = "") -> Path:
    """folder/name if free, else 'name (2).ext', 'name (3).ext'. With tag: 'name (copy).ext', then
    'name (copy 2).ext'. Nothing is ever overwritten."""
    stem, ext = split_ext(name, is_dir)
    first = f"{stem} ({tag}){ext}" if tag else name
    if not os.path.lexists(folder / first):
        return folder / first
    n = 2
    while True:
        cand = f"{stem} ({tag} {n}){ext}" if tag else f"{stem} ({n}){ext}"
        if not os.path.lexists(folder / cand):
            return folder / cand
        n += 1


def valid_name(name) -> str:
    """A single file name, or ValueError saying what's wrong."""
    text = str(name or "").strip()
    if not text:
        raise ValueError("say what to call it")
    if "/" in text or "\0" in text:
        raise ValueError("a name can't contain a slash")
    if text in (".", ".."):
        raise ValueError(f"{text!r} isn't a usable name")
    if len(text.encode("utf-8")) > 255:
        raise ValueError("that name is too long")
    return text


def inside(child: Path, parent: Path) -> bool:
    return child == parent or parent in child.parents


# ---------------------------------------------------------------- copy and move

def copy_item(src: Path, dest: Path) -> None:
    """Copy a file, a folder tree, or a symlink (kept as a link), never following links out."""
    if src.is_symlink():
        os.symlink(os.readlink(src), dest)
    elif src.is_dir():
        shutil.copytree(src, dest, symlinks=True)
    else:
        shutil.copy2(src, dest)


def move_item(src: Path, dest: Path) -> None:
    shutil.move(str(src), str(dest))


# ---------------------------------------------------------------- archives

ZIP, TARGZ = "zip", "tar.gz"
FORMATS = {ZIP: ".zip", TARGZ: ".tar.gz", "tgz": ".tar.gz", "tar": ".tar.gz"}
MAX_EXTRACT_BYTES = 16 * 1024 ** 3
MAX_EXTRACT_FILES = 200_000
NATIVE_TAR = (".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2", ".tbz", ".tar.xz", ".txz")
OTHER_ARCHIVES = (".7z", ".rar", ".tar.zst", ".zst", ".gz", ".bz2", ".xz", ".lz", ".lzma", ".cab", ".tar.lz",
                  ".tar.lzma", ".tar.z", ".z", ".iso")


class ArchiveError(Exception):
    """Plain English, for her and him."""


def _members(src: Path):
    """(path, arcname) for everything under src worth archiving, plus how many entries were left out
    (symlinks, credential-looking names)."""
    base = src.parent
    skipped = 0
    out = []
    if src.is_symlink():
        return [], 1
    out.append((src, src.relative_to(base).as_posix()))
    if src.is_dir():
        for root, dirs, files in os.walk(src, followlinks=False):
            keep = []
            for d in sorted(dirs):
                p = Path(root) / d
                if p.is_symlink() or df.sensitive_name(d):
                    skipped += 1
                    continue
                keep.append(d)
                out.append((p, p.relative_to(base).as_posix()))
            dirs[:] = keep
            for f in sorted(files):
                p = Path(root) / f
                if p.is_symlink() or df.sensitive_name(f):
                    skipped += 1
                    continue
                out.append((p, p.relative_to(base).as_posix()))
    return out, skipped


def compress(src: Path, fmt: str = ZIP) -> tuple[Path, int, int]:
    """Archive src (file or folder) next to itself. (archive path, entries added, entries left out)."""
    key = str(fmt or ZIP).lower().lstrip(".")
    if key not in FORMATS:
        raise ArchiveError("I can make zip or tar.gz archives")
    ext = FORMATS[key]
    is_dir = src.is_dir()
    final = free_copy(src.parent, split_ext(src.name, is_dir)[0] + ext)
    part = src.parent / f".{final.name}.part"
    members, skipped = _members(src)
    try:
        if ext == ".zip":
            with zipfile.ZipFile(part, "w", zipfile.ZIP_DEFLATED) as zf:
                for p, arc in members:
                    if p.is_dir():
                        zf.write(p, arc + "/")
                    else:
                        zf.write(p, arc)
        else:
            with tarfile.open(part, "w:gz") as tf:
                for p, arc in members:
                    tf.add(p, arcname=arc, recursive=False)
        os.rename(part, final)
    except BaseException:
        try:
            part.unlink()
        except OSError:
            pass
        raise
    return final, len(members), skipped


def archive_ext(name: str) -> str | None:
    low = name.lower()
    if low.endswith(".zip"):
        return ".zip"
    for e in sorted(NATIVE_TAR + OTHER_ARCHIVES, key=len, reverse=True):
        if low.endswith(e):
            return e
    return None


def _unsafe(name: str) -> bool:
    n = name.replace("\\", "/")
    return n.startswith("/") or ".." in n.split("/") or bool(re.match(r"^[A-Za-z]:", n))


def _extract_native(src: Path, ext: str, dest: Path) -> None:
    if ext == ".zip":
        try:
            zf = zipfile.ZipFile(src)
        except zipfile.BadZipFile:
            raise ArchiveError("that isn't a readable zip file")
        with zf:
            infos = zf.infolist()
            if len(infos) > MAX_EXTRACT_FILES or sum(i.file_size for i in infos) > MAX_EXTRACT_BYTES:
                raise ArchiveError("that archive unpacks to far too much; I won't extract it")
            for i in infos:
                if _unsafe(i.filename):
                    raise ArchiveError("that archive has paths that climb out of its folder; I won't extract it")
            for i in infos:
                if stat.S_ISLNK(i.external_attr >> 16):
                    continue                                    # links inside archives are not recreated
                zf.extract(i, dest)
        return
    try:
        tf = tarfile.open(src)
    except (tarfile.TarError, OSError, EOFError) as e:
        raise ArchiveError(f"that isn't a readable archive ({e.__class__.__name__})")
    with tf:
        try:
            members = tf.getmembers()
            if len(members) > MAX_EXTRACT_FILES or sum(m.size for m in members) > MAX_EXTRACT_BYTES:
                raise ArchiveError("that archive unpacks to far too much; I won't extract it")
            for m in members:
                if _unsafe(m.name):
                    raise ArchiveError("that archive has paths that climb out of its folder; I won't extract it")
            tf.extractall(dest, filter="data")
        except tarfile.FilterError:
            raise ArchiveError("that archive has links or paths that climb out of its folder; I won't extract it")
        except (tarfile.TarError, EOFError) as e:
            raise ArchiveError(f"that archive is damaged ({e.__class__.__name__})")


def _extract_external(src: Path, dest: Path) -> None:
    """7z or bsdtar, for the formats Python can't read."""
    for tool in ("7z", "7zz", "7za"):
        if shutil.which(tool):
            cmd = [tool, "x", "-y", f"-o{dest}", "--", str(src)]
            break
    else:
        if shutil.which("bsdtar"):
            cmd = ["bsdtar", "-xf", str(src), "-C", str(dest)]
        else:
            raise ArchiveError("I need 7z or bsdtar to open that kind of archive, and neither is here")
    try:
        done = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, timeout=600)
    except (OSError, subprocess.TimeoutExpired):
        raise ArchiveError("the archive tool didn't finish; nothing was kept")
    if done.returncode:
        raise ArchiveError("the archive tool couldn't open it; nothing was kept")
    # An external tool may have written links that point out of the folder; drop those.
    for root, dirs, files in os.walk(dest):
        for n in dirs + files:
            p = Path(root) / n
            if p.is_symlink() and not inside(Path(os.path.realpath(p)), Path(os.path.realpath(dest))):
                p.unlink()


def extract(src: Path) -> tuple[Path, int]:
    """Unpack into a new sibling folder (named after the archive, or after the one folder it holds).
    (folder, entries in it). Nothing is overwritten; a failed extract leaves nothing behind."""
    ext = archive_ext(src.name)
    if ext is None:
        raise ArchiveError("that doesn't look like an archive (zip, tar, 7z, rar...)")
    stem = src.name[:-len(ext)] or src.name
    parent = src.parent
    stage = parent / f".{stem}.extracting"
    n = 2
    while os.path.lexists(stage):
        stage = parent / f".{stem}.extracting{n}"
        n += 1
    stage.mkdir()
    try:
        if ext == ".zip" or ext in NATIVE_TAR:
            _extract_native(src, ext, stage)
        else:
            _extract_external(src, stage)
        entries = sorted(os.listdir(stage))
        if not entries:
            raise ArchiveError("that archive is empty")
        one = stage / entries[0]
        if len(entries) == 1 and one.is_dir() and not one.is_symlink():
            final = free_copy(parent, entries[0], True)
            os.rename(one, final)
            stage.rmdir()
        else:
            final = free_copy(parent, stem, True)
            os.rename(stage, final)
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    count = sum(len(f) + len(d) for _, d, f in os.walk(final))
    return final, count


# ---------------------------------------------------------------- facts (Properties)

def mime_of(p: Path) -> str:
    """The MIME type: folders, then the extension, then whether the content is text."""
    import mimetypes
    if p.is_dir():
        return "inode/directory"
    guess = mimetypes.guess_type(p.name, strict=False)[0]
    if guess:
        return guess
    if p.name.lower().endswith(TAR_EXTS):
        return "application/x-tar"
    return "text/plain" if df.looks_text(p) else "application/octet-stream"


def tree_size(p: Path, limit: int = 50_000, seconds: float = 2.0, clock=time.monotonic) -> tuple[int, bool]:
    """Total bytes under a folder, and whether the count was cut short. Links aren't followed."""
    total, seen, partial = 0, 0, False
    deadline = clock() + seconds
    stack = [p]
    while stack:
        cur = stack.pop()
        try:
            with os.scandir(cur) as it:
                for e in it:
                    seen += 1
                    if seen > limit or clock() > deadline:
                        return total, True
                    try:
                        if e.is_dir(follow_symlinks=False):
                            stack.append(Path(e.path))
                        else:
                            total += e.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
        except OSError:
            continue
    return total, partial


def info(p: Path) -> dict:
    """{size, modified, kind, mime, items (folders), permissions}; size is bytes, modified epoch seconds."""
    st = p.lstat()
    is_dir = p.is_dir() and not p.is_symlink()
    out = {"kind": "folder" if is_dir else df.kind_of(p.name), "mime": mime_of(p),
           "modified": int(st.st_mtime),
           "permissions": f"{stat.filemode(st.st_mode)[1:]} ({stat.S_IMODE(st.st_mode):o})"}
    if is_dir:
        out["size"], partial = tree_size(p)
        try:
            out["items"] = len(os.listdir(p))
        except OSError:
            out["items"] = 0
        if partial:
            out["partial"] = True
    else:
        out["size"] = st.st_size
    return out


def info_text(p: Path, facts: dict, guard: df.Guard) -> str:
    when = time.strftime("%Y-%m-%d %H:%M", time.localtime(facts["modified"]))
    bits = [facts["kind"], facts["mime"], df._size(facts["size"]) + ("+" if facts.get("partial") else "")]
    if "items" in facts:
        bits.append(f"{facts['items']} items")
    bits += [f"modified {when}", f"permissions {facts['permissions']}"]
    return f"{guard.shorten(p)}: " + ", ".join(bits) + "."


# ---------------------------------------------------------------- apps that open a file

@dataclass
class App:
    id: str                                  # 'org.kde.kate.desktop'
    name: str
    icon: str
    mimes: set = field(default_factory=set)
    path: Path = None

    def row(self) -> dict:
        return {"id": self.id, "name": self.name, "icon": self.icon}


def desktop_dirs(env=None, home: Path | None = None) -> list[Path]:
    """Where .desktop files live, most personal first. From a toolbox the host's are under /run/host."""
    env = os.environ if env is None else env
    home = home or Path(os.path.expanduser("~"))
    data_home = Path(env.get("XDG_DATA_HOME") or home / ".local/share")
    data_dirs = [Path(d) for d in (env.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share").split(":") if d]
    dirs = [data_home / "applications", data_home / "flatpak/exports/share/applications"]
    dirs += [d / "applications" for d in data_dirs]
    dirs += [Path("/var/lib/flatpak/exports/share/applications")]
    host = Path("/run/host")
    if host.is_dir():
        dirs += [host / "usr/share/applications", host / "usr/local/share/applications",
                 host / "var/lib/flatpak/exports/share/applications"]
    seen, out = set(), []
    for d in dirs:
        if d not in seen:
            seen.add(d)
            out.append(d)
    return out


def parse_desktop(text: str) -> dict | None:
    """The [Desktop Entry] keys we need, or None for a launcher that shouldn't be offered."""
    fields: dict[str, str] = {}
    inside_entry = False
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("["):
            if inside_entry:
                break
            inside_entry = line == "[Desktop Entry]"
            continue
        if inside_entry and "=" in line and not line.startswith("#"):
            k, _, v = line.partition("=")
            fields.setdefault(k.strip(), v.strip())
    if fields.get("Type", "Application") != "Application":
        return None
    if fields.get("NoDisplay", "").lower() == "true" or fields.get("Hidden", "").lower() == "true":
        return None
    if not fields.get("Name") or not re.search(r"%[fFuU]", fields.get("Exec", "")):
        return None                                   # can't be handed a file
    return fields


def scan_apps(dirs) -> dict[str, App]:
    """id -> App for every launcher that takes a file. An earlier folder's copy of an id wins."""
    apps: dict[str, App] = {}
    for d in dirs:
        d = Path(d)
        try:
            files = sorted(d.rglob("*.desktop"))
        except OSError:
            continue
        for f in files:
            app_id = f.relative_to(d).as_posix().replace("/", "-")
            if app_id in apps:
                continue
            try:
                fields = parse_desktop(f.read_text("utf-8", "replace"))
            except OSError:
                continue
            if fields is None:
                apps[app_id] = App(app_id, "", "", set(), f)          # a hidden copy still shadows later ones
                continue
            mimes = {m for m in fields.get("MimeType", "").split(";") if m}
            apps[app_id] = App(app_id, fields["Name"], fields.get("Icon", ""), mimes, f)
    return {k: a for k, a in apps.items() if a.name}


def user_associations(paths) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """(defaults, added) from mimeapps.list files: mime -> [desktop ids], first file first."""
    defaults: dict[str, list[str]] = {}
    added: dict[str, list[str]] = {}
    for path in paths:
        try:
            text = Path(path).read_text("utf-8", "replace")
        except OSError:
            continue
        section = ""
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("["):
                section = line
            elif "=" in line and not line.startswith("#"):
                mime, _, ids = line.partition("=")
                target = defaults if section == "[Default Applications]" else added \
                    if section == "[Added Associations]" else None
                if target is not None:
                    target.setdefault(mime.strip(), []).extend(i for i in ids.split(";") if i)
    return defaults, added


def apps_for(apps: dict[str, App], mime: str, text_like: bool = False,
             assoc: tuple[dict, dict] = ({}, {})) -> list[App]:
    """Apps that can open this MIME type: his chosen defaults first, then the rest by name."""
    want = {mime}
    if text_like or mime.startswith("text/"):
        want.add("text/plain")
    defaults, added = assoc
    chosen = [i for m in (mime, *sorted(want - {mime})) for i in defaults.get(m, []) + added.get(m, [])]
    found = {i: a for i, a in apps.items() if a.mimes & want}
    for i in chosen:
        if i in apps:
            found.setdefault(i, apps[i])
    first = [found[i] for i in dict.fromkeys(chosen) if i in found]
    rest = sorted((a for i, a in found.items() if i not in chosen), key=lambda a: a.name.casefold())
    return first + rest
