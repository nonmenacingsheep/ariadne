"""What the Dolphin adapter reads and does on disk: kinds, KDE's recent lists, the path guard,
the sort plan, find/list text, and the D-Bus questions it asks of Dolphin.

Everything here is plain functions or small classes with injectable inputs, so tests run in a temp
dir with no Dolphin. The adapter (dolphin.py) is the async shell around it.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import os
import re
import sqlite3
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

MOUNTS = "/var/mnt"                     # the games drive and friends live under here
DOLPHIN_AGENT = "org.kde.dolphin"       # KActivities' name for Dolphin
PARTIAL = (".part", ".crdownload", ".download", ".tmp", ".partial", ".!qb", ".opdownload", ".aria2")

EXT = {
    "image": "png jpg jpeg gif webp bmp svg tif tiff heic avif ico xcf psd kra",
    "audio": "mp3 flac ogg opus wav m4a aac wma mid midi",
    "video": "mp4 mkv webm mov avi wmv flv m4v mpg mpeg ogv",
    "doc": "pdf doc docx odt rtf txt md epub mobi xls xlsx ods csv ppt pptx odp tex",
    "archive": "zip tar gz tgz xz bz2 zst 7z rar lz lzma cab",
    "code": "py js ts jsx tsx c cc cpp h hpp rs go java kt cs gd gdshader lua rb php sh json yaml yml "
            "toml html css xml sql ini cfg",
}
INSTALLER_EXT = "appimage deb rpm flatpak flatpakref apk exe msi iso dmg run"
KIND_OF_EXT = {e: k for k, exts in EXT.items() for e in exts.split()}

# The folder names sort() files into, by widget kind.
SORT_FOLDER = {"image": "Images", "audio": "Audio", "video": "Video", "doc": "Documents",
               "archive": "Archives", "code": "Other", "other": "Other"}
SORT_NAMES = ("Images", "Audio", "Video", "Documents", "Archives", "Installers", "Other")
PROJECT_MARKS = (".git", "pyproject.toml", "package.json", "Makefile", "Cargo.toml", "project.godot",
                 "CMakeLists.txt")
SORT_MAX = 300                          # files one sort() moves; the rest wait for a second call
SORT_QUIET = 30.0                       # younger than this (seconds) may still be downloading: left alone
FIND_PRUNE = {"node_modules", "__pycache__", "compatdata", "shadercache", "site-packages", "venv"}
FIND_MAX = 30
FIND_SECONDS = 6.0
FIND_VISIT = 400_000
LIST_MAX = 60


class PathRefused(Exception):
    """A path the adapter won't touch; the message says why in plain English."""


# ---------------------------------------------------------------- credentials

# Ported from 1.x skills.is_sensitive, smaller: names that say they hold credentials. Over-broad on
# purpose; a false positive costs one file she can't touch, a false negative puts a key in a chat.
SECRET_DIRS = {".ssh", ".gnupg", ".pki", ".aws", ".azure", ".kube", ".docker", ".password-store",
               ".mozilla", ".thunderbird", "keyrings", "keyring"}
SECRET_NAMES = {"shadow", "gshadow", "sudoers", ".netrc", ".pgpass", ".htpasswd", "api_key", "credentials",
                "authorized_keys", "known_hosts"}
SECRET_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".kdbx", ".keytab", ".jks", ".asc", ".gpg", ".ovpn")
SECRET_STEMS = ("id_rsa", "id_dsa", "id_ecdsa", "id_ed25519", "secret")
SECRET_SUBSTRINGS = ("apikey", "secret", "password", "passwd", "credential", "privatekey", "keystore",
                     "keyring", "seedphrase", "recoverycode", "authtoken", "accesstoken", "gpgkey", "sshkey",
                     "refreshtoken", "oauth", "bearer")
SECRET_EXACT = {"keys", "key", "creds", "tokens", "2fa", "totp", "otp"}


def sensitive_name(name: str) -> bool:
    """True when one path component smells like a credential ('API Keys', 'id_rsa', '.env')."""
    low = name.lower()
    flat = re.sub(r"[^a-z0-9]", "", low)
    return (low in SECRET_DIRS or low in SECRET_NAMES or flat in SECRET_EXACT or low.startswith(".env")
            or low.endswith(SECRET_SUFFIXES) or low.startswith(SECRET_STEMS)
            or any(t in flat for t in SECRET_SUBSTRINGS))


# ---------------------------------------------------------------- kinds

def kind_of(name: str) -> str:
    """The widget's kind for a file name: image, audio, video, doc, archive, code, other."""
    ext = os.path.splitext(name)[1].lstrip(".").lower()
    return KIND_OF_EXT.get(ext, "other")


def is_installer(name: str) -> bool:
    return os.path.splitext(name)[1].lstrip(".").lower() in INSTALLER_EXT.split()


def sort_folder(name: str) -> str:
    """Which tidy-up subfolder a file belongs in."""
    return "Installers" if is_installer(name) else SORT_FOLDER[kind_of(name)]


def is_partial(name: str) -> bool:
    return name.lower().endswith(PARTIAL)


# ---------------------------------------------------------------- the path guard

class Guard:
    """Which paths the adapter may read or change: under $HOME or /var/mnt, nothing hidden by accident."""

    def __init__(self, home: str | os.PathLike | None = None, mounts: str | os.PathLike = MOUNTS) -> None:
        self.home = Path(os.path.realpath(home or os.path.expanduser("~")))
        self.mounts = Path(os.path.realpath(mounts))
        self.roots = (self.home, self.mounts)

    def local(self, raw: str) -> str:
        """Host-style paths (/var/home/x) mean the same place here (/home/x)."""
        raw = os.path.expanduser(str(raw).strip())
        if raw.startswith("file://"):
            raw = unquote(urlparse(raw).path)
        if raw.startswith("/var/home/") and not str(self.home).startswith("/var/home/"):
            raw = raw[4:]
        return raw

    def resolve(self, raw, *, write: bool = False, must_exist: bool = True) -> Path:
        """The real path, or PathRefused. The last part is not followed if it is a symlink."""
        if raw is None or not str(raw).strip():
            raise PathRefused("no path given")
        text = self.local(raw)
        p = Path(text) if os.path.isabs(text) else self.home / text
        p = Path(os.path.normpath(p))
        real = Path(os.path.realpath(p.parent)) / p.name if p != p.parent else p
        root = next((r for r in self.roots if real == r or r in real.parents), None)
        if root is None:
            raise PathRefused(f"{real} is outside your home folder and /var/mnt, so I won't touch it")
        rel = real.relative_to(root).parts
        if any(sensitive_name(part) for part in rel):
            raise PathRefused(f"{self.shorten(real)} looks like it holds credentials or keys; "
                              "I leave those for him")
        if any(part.startswith(".") for part in rel[:-1]):
            raise PathRefused(f"{real} is inside a hidden folder; I only go in when you name that "
                              "exact folder")
        if write:
            if real in self.roots or (real.parent == self.mounts):
                raise PathRefused(f"{real} is a whole drive or your home folder; I won't move or trash that")
            if rel and rel[-1].startswith(".") and os.path.isdir(real):
                raise PathRefused(f"{real} is a hidden folder (settings and caches); I won't move or "
                                  "trash it")
        if must_exist and not os.path.lexists(real):
            raise PathRefused(f"{self.shorten(real)} doesn't exist")
        return real

    def allowed(self, raw) -> bool:
        try:
            self.resolve(raw, must_exist=False)
            return True
        except PathRefused:
            return False

    def shorten(self, p) -> str:
        p = str(p)
        h = str(self.home)
        return "~" + p[len(h):] if p == h or p.startswith(h + "/") else p


def visible(name: str) -> bool:
    return not name.startswith(".")


def free_name(folder: Path, name: str) -> Path:
    """folder/name, or 'name (2).ext' and up if that is taken. Nothing is ever overwritten."""
    dest = folder / name
    if not os.path.lexists(dest):
        return dest
    stem, ext = os.path.splitext(name)
    n = 2
    while os.path.lexists(folder / f"{stem} ({n}){ext}"):
        n += 1
    return folder / f"{stem} ({n}){ext}"


# ---------------------------------------------------------------- KDE's recent lists

def _epoch(stamp: str | None) -> float:
    try:
        return dt.datetime.fromisoformat((stamp or "").replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def parse_xbel(text: str) -> list[tuple[str, float]]:
    """(local path, epoch) per file:// bookmark in recently-used.xbel; other schemes (steam://) are skipped."""
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return []
    out = []
    for bm in root.iter("bookmark"):
        href = bm.get("href") or ""
        if not href.startswith("file://"):
            continue
        when = max(_epoch(bm.get(k)) for k in ("visited", "modified", "added"))
        out.append((unquote(urlparse(href).path), when))
    return out


def parse_recent_documents(folder: Path) -> list[tuple[str, float]]:
    """KDE's older ~/.local/share/RecentDocuments/*.desktop, each with a URL= line."""
    out = []
    try:
        entries = list(folder.glob("*.desktop"))
    except OSError:
        return out
    for f in entries:
        try:
            m = re.search(r"^URL=(file://\S+)", f.read_text("utf-8", "replace"), re.M)
            if m:
                out.append((unquote(urlparse(m.group(1)).path), f.stat().st_mtime))
        except OSError:
            continue
    return out


def dolphin_folders(db: str | os.PathLike, limit: int = 40) -> list[tuple[str, float]]:
    """Folders Dolphin opened lately, from KDE's activity history (read-only; empty if unreadable)."""
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=0.5)
        try:
            rows = con.execute(
                "SELECT targettedResource, lastUpdate FROM ResourceScoreCache WHERE initiatingAgent=? "
                "ORDER BY lastUpdate DESC LIMIT ?", (DOLPHIN_AGENT, limit)).fetchall()
        finally:
            con.close()
    except sqlite3.Error:
        return []
    return [(r[0], float(r[1])) for r in rows if isinstance(r[0], str) and r[0].startswith("/")]


class Recents:
    """Recent folders and files for the widget, from KDE's lists, filtered through the guard."""

    def __init__(self, guard: Guard, xbel=None, docs=None, activity_db=None) -> None:
        share = Path(os.environ.get("XDG_DATA_HOME") or Path(guard.home) / ".local/share")
        self.guard = guard
        self.xbel = Path(xbel) if xbel else share / "recently-used.xbel"
        self.docs = Path(docs) if docs else share / "RecentDocuments"
        self.db = Path(activity_db) if activity_db else share / "kactivitymanagerd/resources/database"
        self._xbel_cache: tuple = (None, [])
        self.raw: dict[str, str] = {}               # local path -> how KDE spelled it (for D-Bus URLs)

    def _xbel(self) -> list[tuple[str, float]]:
        try:
            st = self.xbel.stat()
        except OSError:
            return []
        key = (st.st_mtime_ns, st.st_size)
        if self._xbel_cache[0] != key:
            try:
                self._xbel_cache = (key, parse_xbel(self.xbel.read_text("utf-8", "replace")))
            except OSError:
                return []
        return self._xbel_cache[1]

    def _usable(self, raw: str, want_dir: bool) -> Path | None:
        try:
            p = self.guard.resolve(raw)
        except PathRefused:
            return None
        if p.name.startswith(".") or (os.path.isdir(p) != want_dir):
            return None
        return p

    def files(self, limit: int = 8) -> list[dict]:
        seen: dict[Path, float] = {}
        for raw, when in self._xbel() + parse_recent_documents(self.docs):
            p = self._usable(raw, False)
            if p is not None and when > seen.get(p, 0):
                seen[p] = when
        top = sorted(seen.items(), key=lambda kv: -kv[1])[:limit]
        return [{"path": str(p), "name": p.name, "when": int(w), "kind": kind_of(p.name)} for p, w in top]

    def folders(self, limit: int = 8) -> list[dict]:
        seen: dict[Path, float] = {}
        for raw, when in dolphin_folders(self.db) + [(r, w) for r, w in self._xbel()
                                                   if os.path.isdir(self.guard.local(r))]:
            p = self._usable(raw, True)
            if p is not None:
                self.raw[str(p)] = raw
                if when > seen.get(p, 0):
                    seen[p] = when
        if len(seen) < limit:                                # not enough: the folders recent files sit in
            for f in self.files(limit * 2):
                parent = Path(f["path"]).parent
                if parent not in seen and parent != self.guard.home and not parent.name.startswith("."):
                    seen[parent] = float(f["when"])
        top = sorted(seen.items(), key=lambda kv: -kv[1])[:limit]
        return [{"path": str(p), "name": p.name or str(p), "when": int(w)} for p, w in top]


# ---------------------------------------------------------------- watching folders

def snapshot(folder: str | os.PathLike) -> dict[str, tuple[int, int]]:
    """name -> (size, mtime_ns) of the visible, finished, regular files directly in a folder."""
    out = {}
    try:
        with os.scandir(folder) as it:
            for e in it:
                if not visible(e.name) or is_partial(e.name) or sensitive_name(e.name):
                    continue
                try:
                    if e.is_file(follow_symlinks=False):
                        st = e.stat(follow_symlinks=False)
                        out[e.name] = (st.st_size, st.st_mtime_ns)
                except OSError:
                    continue
    except OSError:
        return {}
    return out


# ---------------------------------------------------------------- sort

def sort_plan(folder: Path, now: float | None = None) -> tuple[list[tuple[Path, Path]], list[str]]:
    """([(source, destination)], notes) for tidying `folder`. Only plain visible files directly in it
    move; folders, dotfiles, symlinks, partial downloads and files touched in the last 30 s stay."""
    now = time.time() if now is None else now
    for mark in PROJECT_MARKS:
        if os.path.lexists(folder / mark):
            raise PathRefused(f"{folder.name} looks like a project ({mark} is in it); I won't reshuffle that")
    moves, taken, held = [], {}, 0
    try:
        entries = sorted(os.scandir(folder), key=lambda e: e.name.lower())
    except OSError as e:
        raise PathRefused(f"can't read {folder.name}: {e.strerror}")
    for e in entries:
        if not visible(e.name) or is_partial(e.name) or sensitive_name(e.name):
            continue
        try:
            if not e.is_file(follow_symlinks=False):
                continue
            if now - e.stat(follow_symlinks=False).st_mtime < SORT_QUIET:
                held += 1
                continue
        except OSError:
            continue
        sub = folder / sort_folder(e.name)
        if os.path.lexists(sub) and not os.path.isdir(sub):
            continue                                        # a file called "Images": leave it alone
        used = taken.setdefault(sub, set())
        dest = free_name(sub, e.name)
        if dest.name in used:
            stem, ext = os.path.splitext(e.name)
            n = 2
            while f"{stem} ({n}){ext}" in used or os.path.lexists(sub / f"{stem} ({n}){ext}"):
                n += 1
            dest = sub / f"{stem} ({n}){ext}"
        used.add(dest.name)
        moves.append((Path(e.path), dest))
    notes = []
    if held:
        notes.append(f"{held} file(s) changed in the last {int(SORT_QUIET)} seconds, so they may still be "
                     "downloading; left where they are")
    if len(moves) > SORT_MAX:
        notes.append(f"{len(moves) - SORT_MAX} more files wait for another sort")
        moves = moves[:SORT_MAX]
    return moves, notes


# ---------------------------------------------------------------- find and list text

def _size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return ""


def _ago(mtime: float, now: float) -> str:
    d = int((now - mtime) / 86400)
    return "today" if d <= 0 else f"{d}d ago" if d < 60 else f"{d // 30}mo ago"


def find_files(query: str, roots: list[Path], now: float | None = None, clock=time.monotonic,
               limit: int = FIND_MAX) -> tuple[list[tuple[Path, bool]], str]:
    """Names containing every word of the query, shallowest first. Returns (hits, why it stopped early)."""
    words = [w for w in re.split(r"\s+", query.lower().strip()) if w]
    if not words:
        return [], "empty query"
    hits, visited, deadline, stopped = [], 0, clock() + FIND_SECONDS, ""
    stack = [(r, 0) for r in reversed(roots)]
    while stack and not stopped:
        folder, depth = stack.pop()
        try:
            entries = sorted(os.scandir(folder), key=lambda e: e.name)
        except OSError:
            continue
        subdirs = []
        for e in entries:
            visited += 1
            if not visible(e.name) or sensitive_name(e.name):
                continue
            low = e.name.lower()
            try:
                is_dir = e.is_dir(follow_symlinks=False)
            except OSError:
                continue
            if all(w in low for w in words):
                hits.append((depth, Path(e.path), is_dir))
            if is_dir and e.name not in FIND_PRUNE:
                subdirs.append((Path(e.path), depth + 1))
        stack.extend(reversed(subdirs))
        if len(hits) >= limit * 4:
            stopped = "plenty of matches"
        elif visited > FIND_VISIT:
            stopped = "the search got too big"
        elif clock() > deadline:
            stopped = "ran out of time"
    hits.sort(key=lambda h: (h[0], str(h[1]).lower()))
    return [(p, d) for _, p, d in hits[:limit]], stopped


def describe(p: Path, now: float, guard: Guard) -> str:
    try:
        st = p.lstat()
    except OSError:
        return guard.shorten(p)
    if os.path.isdir(p):
        return f"{guard.shorten(p)}/ (folder, {_ago(st.st_mtime, now)})"
    return f"{guard.shorten(p)} ({kind_of(p.name)}, {_size(st.st_size)}, {_ago(st.st_mtime, now)})"


def list_folder(folder: Path, now: float, guard: Guard) -> str:
    try:
        entries = list(os.scandir(folder))
    except OSError as e:
        raise PathRefused(f"can't read {guard.shorten(folder)}: {e.strerror}")
    shown = [e for e in entries if visible(e.name) and not sensitive_name(e.name)]
    hidden = len(entries) - len(shown)
    dirs = sorted((e for e in shown if e.is_dir()), key=lambda e: e.name.lower())
    files = sorted((e for e in shown if not e.is_dir()), key=lambda e: e.name.lower())
    rows = [f"{e.name}/" for e in dirs]
    for e in files:
        try:
            st = e.stat()
            rows.append(f"{e.name} ({kind_of(e.name)}, {_size(st.st_size)}, {_ago(st.st_mtime, now)})")
        except OSError:
            rows.append(e.name)
    head = f"{guard.shorten(folder)}: {len(dirs)} folders, {len(files)} files"
    if hidden:
        head += f" ({hidden} hidden or private not shown)"
    if not rows:
        return head + "."
    more = f"\n({len(rows) - LIST_MAX} more not shown)" if len(rows) > LIST_MAX else ""
    return head + ":\n" + "\n".join(rows[:LIST_MAX]) + more


# ---------------------------------------------------------------- D-Bus: ask Dolphin

async def busctl(*args: str, timeout: float = 2.0) -> tuple[int, str]:
    """Run busctl on the session bus; (exit code, stdout). Any failure is (1, "")."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "busctl", "--user", "--no-pager", *args, stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        out, _ = await asyncio.wait_for(proc.communicate(), timeout)
        return proc.returncode or 0, out.decode("utf-8", "replace")
    except (OSError, asyncio.TimeoutError):
        return 1, ""


def file_url(path: str) -> str:
    return "file://" + quote(path)


async def dolphin_windows(run=busctl) -> list[tuple[str, str, str]]:
    """(service, object path, interface) for each open Dolphin window that answers isUrlOpen."""
    code, out = await run("list", "--no-legend")
    services = sorted({line.split()[0] for line in out.splitlines()
                       if line.split() and line.split()[0].startswith("org.kde.dolphin-")})
    found = []
    for svc in services:
        code, tree = await run("tree", svc, "--list")
        for path in (p.strip() for p in tree.splitlines()):
            if not re.fullmatch(r"/dolphin/Dolphin_\d+", path):
                continue
            code, spec = await run("introspect", svc, path)
            iface = ""
            for line in spec.splitlines():
                if not line.startswith("."):
                    parts = line.split()
                    iface = parts[0] if len(parts) > 1 and parts[1] == "interface" else iface
                elif line.split()[0] == ".isUrlOpen" and iface:
                    found.append((svc, path, iface))
                    break
    return found


async def open_folder_among(candidates: list[str], windows: list[tuple[str, str, str]],
                            run=busctl) -> str | None:
    """The first candidate (most recent first) that some Dolphin window has open. Dolphin has no 'what
    folder am I in' call, but it will say whether a given URL is open."""
    for cand in candidates:
        for svc, path, iface in windows:
            code, out = await run("call", svc, path, iface, "isUrlOpen", "s", file_url(cand))
            if code == 0 and out.split()[:2] == ["b", "true"]:
                return cand
    return None
