"""Steam's own files and the process list, read-only: the Steam adapter's eyes.

Everything here is a plain function or a small class with injectable roots, so the
tests can build a fake Steam directory and a fake /proc in a temp folder. Ported
from 1.x (`ariadne/desktop.py`) with the VDF reading rewritten as a real parser:
1.x's line scanner broke on nested blocks and could not read manifests' depots.
"""
from __future__ import annotations

import glob
import os
import re
import struct
import time
from pathlib import Path

HOME = Path.home()
STEAM_ROOTS = (".local/share/Steam", ".steam/steam", ".var/app/com.valvesoftware.Steam/data/Steam")
# A drive remounted elsewhere leaves libraryfolders.vdf pointing at nothing, and
# this machine's atomic desktop mounts under /var/mnt, so sweep the usual roots too.
MOUNT_ROOTS = ("/var/mnt", "/run/media", "/media", "/mnt")
LIB_TTL = 60.0                 # drives don't come and go every few seconds

# Runtimes and tools sit in the library like games with no playtime; never recent.
TOOL_WORDS = ("proton", "steam linux runtime", "steamworks common", "steam runtime", "steamvr",
              "compatibility tool", "steam client", "steam screenshots", "steam input configs",
              "redistributable", "dedicated server", "soundtrack", "sdk base", "spacewar")

# appmanifest StateFlags bits we read (Steam's EAppState).
INSTALLED, UPDATE_REQUIRED, UPDATE_RUNNING, PAUSED, UPDATE_STARTED = 4, 2, 256, 512, 1024
BUSY_BITS = UPDATE_RUNNING | (1 << 17) | (1 << 18) | (1 << 19) | (1 << 20) | (1 << 21) | (1 << 22)

_TOKEN = re.compile(r'"((?:[^"\\]|\\.)*)"|([{}])|//[^\n]*')
_ESC = re.compile(r"\\(.)")


def is_tool(name: str) -> bool:
    low = (name or "").lower()
    return any(w in low for w in TOOL_WORDS)


# ---- VDF text (appmanifest, localconfig, libraryfolders) ----

def parse_vdf(text: str) -> dict:
    """Nested dict with lower-cased keys (Steam's casing is inconsistent). A damaged
    file gives whatever parsed before the damage; the caller treats {} as unreadable."""
    root: dict = {}
    stack = [root]
    key = None
    for m in _TOKEN.finditer(text):
        s, brace = m.group(1), m.group(2)
        if s is not None:
            s = _ESC.sub(lambda e: {"n": "\n", "t": "\t"}.get(e.group(1), e.group(1)), s)
            if key is None:
                key = s.lower()
            else:
                stack[-1][key] = s
                key = None
        elif brace == "{":
            child: dict = {}
            if key is not None:
                stack[-1][key] = child
            stack.append(child)
            key = None
        elif brace == "}":
            if len(stack) > 1:
                stack.pop()
            key = None
    return root


def _read(path: str) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def _int(v, default=0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


# ---- appinfo.vdf (binary): names of games that aren't installed ----

def parse_appinfo(blob: bytes) -> dict[int, str]:
    """appid -> name. Up to v28 keys are inline; v29 interns them in a table at the
    end of the file and refers to them by index, so the table is read first."""
    if len(blob) < 16:
        return {}
    magic, _universe = struct.unpack_from("<II", blob, 0)
    version = magic & 0xFF
    if (magic & 0xFFFFFF00) != 0x07564400:
        return {}
    interned: list[str] = []
    end = len(blob)
    if version >= 0x29:
        (table_at,) = struct.unpack_from("<q", blob, 8)
        if not 0 < table_at < len(blob) - 4:
            return {}
        end = table_at
        (count,) = struct.unpack_from("<I", blob, table_at)
        at = table_at + 4
        for _ in range(count):
            stop = blob.find(b"\0", at)
            if stop < 0:
                break
            interned.append(blob[at:stop].decode("utf-8", "replace"))
            at = stop + 1
    wanted = {i for i, s in enumerate(interned) if s == "name"}
    names: dict[int, str] = {}
    at = 16 if version >= 0x29 else 8
    while at + 8 <= end:
        appid, size = struct.unpack_from("<II", blob, at)
        if appid == 0 or size == 0:
            break
        body, stop = at + 8, at + 8 + size
        cur = body + 60                      # past the per-app metadata
        while cur + 5 <= stop:
            kind = blob[cur]
            if kind == 0x01:                 # string
                if interned:
                    (key,) = struct.unpack_from("<I", blob, cur + 1)
                    vat = cur + 5
                else:
                    kend = blob.find(b"\0", cur + 1, stop)
                    if kend < 0:
                        break
                    key, vat = blob[cur + 1:kend].decode("utf-8", "replace"), kend + 1
                z = blob.find(b"\0", vat, stop)
                if z < 0:
                    break
                if (key in wanted) if interned else (key == "name"):
                    names[appid] = blob[vat:z].decode("utf-8", "replace")
                    break                    # the first "name" is the one under `common`
                cur = z + 1
            elif kind == 0x00:
                cur += 5 if interned else (blob.find(b"\0", cur + 1, stop) + 1 - cur)
            elif kind == 0x02:
                cur += 9 if interned else 1
            elif kind == 0x07:
                cur += 13 if interned else 1
            else:
                cur += 1
        at = stop
    return names


# ---- the file set ----

class SteamFiles:
    """Reads what Steam leaves on disk. Caches the heavy files by mtime."""

    def __init__(self, home: Path | str = HOME, mount_roots=MOUNT_ROOTS, steam_roots=STEAM_ROOTS) -> None:
        self.home = Path(home)
        self.roots = [str(self.home / r) for r in steam_roots]
        self.mount_roots = tuple(mount_roots)
        self._libs: tuple[float, list[str]] = (0.0, [])
        self._cache: dict[str, tuple[float, object]] = {}

    def _cached(self, path: str, parse):
        try:
            stamp = os.path.getmtime(path)
        except OSError:
            return None
        hit = self._cache.get(path)
        if hit and hit[0] == stamp:
            return hit[1]
        try:
            value = parse(path)
        except Exception:
            value = None
        self._cache[path] = (stamp, value)
        return value

    def available(self) -> bool:
        return any(os.path.isdir(os.path.join(r, "steamapps")) for r in self.roots)

    def libraries(self) -> list[str]:
        """Every steamapps directory, deduped by real path (~/.steam/steam is a symlink)."""
        now = time.monotonic()
        if self._libs[1] and now - self._libs[0] < LIB_TTL:
            return self._libs[1]
        found: list[str] = []
        for root in self.roots:
            apps = os.path.join(root, "steamapps")
            if os.path.isdir(apps):
                found.append(apps)
            lib = parse_vdf(_read(os.path.join(apps, "libraryfolders.vdf"))).get("libraryfolders", {})
            for entry in lib.values():
                path = entry.get("path") if isinstance(entry, dict) else None
                if path and os.path.isdir(os.path.join(path, "steamapps")):
                    found.append(os.path.join(path, "steamapps"))
        for mount in self.mount_roots:
            for pattern in ("*/steamapps", "*/*/steamapps"):
                found += [p for p in glob.glob(os.path.join(mount, pattern)) if os.path.isdir(p)]
        out: list[str] = []
        seen: set = set()
        for p in found:
            try:                    # /home and /var/home are one directory here: compare inodes
                st = os.stat(p)
            except OSError:
                continue
            if (st.st_dev, st.st_ino) not in seen:
                seen.add((st.st_dev, st.st_ino))
                out.append(os.path.realpath(p))
        self._libs = (now, out)
        return out

    def manifests(self) -> dict[int, dict]:
        """appid -> manifest summary, for every appmanifest in every library."""
        out: dict[int, dict] = {}
        for lib in self.libraries():
            for path in sorted(glob.glob(os.path.join(lib, "appmanifest_*.acf"))):
                m = self._cached(path, lambda p: parse_vdf(_read(p)).get("appstate") or {})
                if not m:
                    continue
                appid = _int(m.get("appid"))
                if not appid:
                    continue
                flags = _int(m.get("stateflags"))
                row = {"appid": appid, "name": m.get("name") or "", "flags": flags,
                       "installed": bool(flags & INSTALLED), "size": _int(m.get("sizeondisk")),
                       "last_played": _int(m.get("lastplayed")),
                       "bytes_done": _int(m.get("bytesdownloaded")),
                       "bytes_total": _int(m.get("bytestodownload")),
                       "staged": _int(m.get("bytesstaged")), "to_stage": _int(m.get("bytestostage")),
                       "mtime": os.path.getmtime(path), "manifest": path,
                       "installdir": str(m.get("installdir") or "")}
                old = out.get(appid)
                if old is None or (row["installed"] and not old["installed"]):
                    out[appid] = row        # a stale copy on a vanished drive must not win
        return out

    def playtime(self) -> dict[int, dict]:
        """appid -> {last_played, minutes} from every user's localconfig.vdf."""
        out: dict[int, dict] = {}
        for root in self.roots:
            for path in glob.glob(os.path.join(root, "userdata", "*", "config", "localconfig.vdf")):
                apps = self._cached(path, self._apps_of) or {}
                for appid, e in apps.items():
                    cur = out.setdefault(appid, {"last_played": 0, "minutes": 0})
                    cur["last_played"] = max(cur["last_played"], e["last_played"])
                    cur["minutes"] = max(cur["minutes"], e["minutes"])
        return out

    @staticmethod
    def _apps_of(path: str) -> dict[int, dict]:
        cfg = parse_vdf(_read(path))
        steam = ((cfg.get("userlocalconfigstore") or cfg).get("software", {}).get("valve", {})
                 .get("steam", {}))
        out = {}
        for k, v in (steam.get("apps") or {}).items():
            if k.isdigit() and isinstance(v, dict):
                out[int(k)] = {"last_played": _int(v.get("lastplayed")), "minutes": _int(v.get("playtime"))}
        return out

    def names(self) -> dict[int, str]:
        """Names for games not installed (the manifests only name what is on disk)."""
        for root in self.roots:
            names = self._cached(os.path.join(root, "appcache", "appinfo.vdf"),
                                 lambda p: parse_appinfo(Path(p).read_bytes()))
            if names:
                return names
        return {}


# ---- processes ----

def _proc_start(proc: str, pid: str, btime: float, hz: int) -> float | None:
    """Epoch start of a process, from /proc/<pid>/stat field 22 (after the ')' of comm)."""
    try:
        stat = Path(f"{proc}/{pid}/stat").read_text()
        ticks = int(stat.rsplit(")", 1)[1].split()[19])
    except (OSError, ValueError, IndexError):
        return None
    return btime + ticks / hz


def scan_processes(proc: str = "/proc") -> dict:
    """{"steam": bool, "games": [{"appid", "pid", "started", "pids": [...]}]}, newest game last.

    A running game shows up as a `reaper SteamLaunch AppId=N -- ...` process (Steam's
    per-launch parent of the game and Proton), whose descendants are the game itself.
    Host processes are visible from the container, so this needs no host-exec.
    """
    steam = False
    reapers: dict[str, tuple[int, str]] = {}      # pid -> (appid, ppid)
    parent: dict[str, str] = {}
    try:
        pids = [p for p in os.listdir(proc) if p.isdigit()]
    except OSError:
        return {"steam": False, "games": []}
    for pid in pids:
        try:
            argv = Path(f"{proc}/{pid}/cmdline").read_bytes().split(b"\0")
        except OSError:
            continue
        a0 = os.path.basename(argv[0].decode("utf-8", "replace")) if argv else ""
        if a0 == "steam" or (len(argv) > 1 and argv[1].endswith(b"/steam.sh")):
            steam = True
        elif a0 == "reaper" and b"SteamLaunch" in argv:
            hit = next((a for a in argv if a.startswith(b"AppId=")), None)
            if hit and hit[6:].isdigit() and int(hit[6:]) > 0:
                reapers[pid] = (int(hit[6:]), "")
        try:
            stat = Path(f"{proc}/{pid}/stat").read_text()
            parent[pid] = stat.rsplit(")", 1)[1].split()[1]
        except (OSError, IndexError):
            pass
    try:
        btime = next(float(line.split()[1]) for line in Path(f"{proc}/stat").read_text().splitlines()
                     if line.startswith("btime"))
    except (OSError, StopIteration, ValueError, IndexError):
        btime = time.time() - time.monotonic()
    hz = os.sysconf("SC_CLK_TCK")
    games = []
    for pid, (appid, _) in reapers.items():
        kids = {pid}
        grew = True
        while grew:                                 # descendants, for closing the whole tree
            grew = False
            for p, pp in parent.items():
                if pp in kids and p not in kids:
                    kids.add(p)
                    grew = True
        started = _proc_start(proc, pid, btime, hz)
        games.append({"appid": appid, "pid": int(pid), "started": started or time.time(),
                      "pids": sorted(int(k) for k in kids)})
    games.sort(key=lambda g: g["started"])
    return {"steam": steam, "games": games}


# ---- matching ----

def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def match_game(query: str, games: list[dict]) -> tuple[list[dict], str]:
    """Best matches for a spoken name among {"appid", "name"} rows -> (rows, how).

    Tiers: appid, exact name, name starts with it, every word of it in the name, then
    typo-close names. The first tier with any hit wins; more than one hit = ambiguous."""
    q = _norm(query)
    if not q:
        return [], "none"
    if q.isdigit():
        hit = [g for g in games if str(g["appid"]) == q]
        if hit:
            return hit, "appid"
    rows = [(g, _norm(g["name"])) for g in games]
    words = q.split()
    for how, ok in (("exact", lambda n: n == q), ("prefix", lambda n: n.startswith(q)),
                    ("words", lambda n: all(w in n.split() for w in words)),
                    ("substring", lambda n: q in n)):
        hit = [g for g, n in rows if ok(n)]
        if hit:
            return hit, how
    import difflib
    scored = sorted(((difflib.SequenceMatcher(None, q, n).ratio(), g) for g, n in rows),
                    key=lambda t: -t[0])
    close = [(r, g) for r, g in scored if r >= 0.72]
    if len(close) > 1 and close[0][0] - close[1][0] > 0.08:
        close = close[:1]               # one clear winner among typo-close names
    return [g for _, g in close[:5]], "fuzzy"
