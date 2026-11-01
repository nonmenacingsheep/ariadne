"""The Tasks adapter: a task manager. Open applications and what each one uses (CPU, memory, GPU memory,
windows), read-only, plus two of his own buttons: focus an app, close an app.

Everything comes from /proc (stdlib, no psutil). Processes are grouped into the app a person would name,
not by pid: the systemd scope or service an app was launched in names it (app-flatpak-com.discordapp.Discord-*.scope,
app-steam@*.service), and a process without one belongs to the top of its own process tree (a terminal and
the shells and programs inside it are one row; Chromium/Electron renderers, Steam's games and helpers are
children of their app). KDE and system daemons, root's processes and kernel threads are one "System" row.
Windows per app come from KWin (a one-shot script, every few rounds), GPU memory from nvidia-smi.

Protected, never closed or signalled: pid 1, the session (KWin, plasmashell, systemd, the login manager),
Ariadne's own processes, and any app that hosts one of them (the terminal this runs in).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import signal
import time
from dataclasses import dataclass, field
from pathlib import Path

from .base import Adapter, AdapterError, Verb

log = logging.getLogger("ariadne2.adapters.tasks")

PERIOD = 2.0
REPO = Path(__file__).resolve().parents[2]


def pins_path() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config"))
    return base / "ariadne2" / "tasks_pins.json"
WINDOW_EVERY = 3                 # a KWin script per poll is the dearest part, so every 6 s
GPU_EVERY = 2
MAX_APPS = 25
MAX_PIDS = 64                    # pids listed per row; the full set is still what close ends
ASK_TTL = 300.0                  # a second "close" within this long escalates to ending the processes
SYSTEM = "System"
PAGE = os.sysconf("SC_PAGE_SIZE") if hasattr(os, "sysconf") else 4096
CLK = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100

# A process tree stops climbing at these (they launch apps; they aren't one).
BOUNDARY = {"systemd", "init", "conmon", "catatonit", "sddm", "plasmalogin", "dbus-broker", "(sd-pam)",
            "kdeinit5", "kdeinit6", "gdm", "lightdm", "login", "sshd"}
# Daemons by name, for processes no unit tells us about. Prefix match.
DAEMON_PREFIXES = ("kwin", "plasma", "kded", "ksmserver", "krunner", "baloo", "pipewire", "wireplumber",
                   "xdg-", "dbus", "polkit", "at-spi", "gvfs", "ibus", "fcitx", "xwayland", "systemd",
                   "kactivity", "kglobalaccel", "kscreen", "powerdevil", "kwalletd", "xembed",
                   "gmenudbusmenuproxy", "pulseaudio", "udisks", "upower", "rtkit", "bluetoothd",
                   "networkmanager", "wpa_supplicant", "avahi", "nvidia-", "geoclue")
# Never signalled, in any group, by name.
PROTECTED_COMM = {"systemd", "init", "kwin_wayland", "kwin_wayland_wrapper", "kwin_x11", "plasmashell",
                  "sddm", "plasmalogin", "xwayland", "dbus-broker", "dbus-broker-launch", "dbus-daemon",
                  "ksmserver", "gdm", "lightdm", "sshd", "login", "kded6", "kded5"}
INTERPRETERS = ("python", "node", "java", "ruby", "perl", "bash", "sh", "deno", "bun")


# --------------------------------------------------------------------------- reading /proc

@dataclass
class Proc:
    pid: int
    ppid: int
    comm: str
    cmd: list
    uid: int
    unit: str                    # last part of the cgroup path ("" when unknown)
    ticks: int                   # utime + stime
    start: int
    rss_mb: float
    cpu: float = 0.0             # percent of one core since the last read


def _read(path, binary=False):
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return None
    return data if binary else data.decode("utf-8", "replace")


def parse_stat(text: str):
    """(comm, ppid, ticks, start, rss_pages) from /proc/<pid>/stat, or None. comm may hold spaces/parens."""
    if not text:
        return None
    a, b = text.find("("), text.rfind(")")
    if a < 0 or b < a:
        return None
    f = text[b + 1:].split()
    try:
        return text[a + 1:b], int(f[1]), int(f[11]) + int(f[12]), int(f[19]), int(f[21])
    except (ValueError, IndexError):
        return None


def parse_unit(cgroup: str) -> str:
    """The last component of the cgroup path (v2 `0::/a/b/c.scope` -> c.scope); '' for the root / unreachable."""
    for line in (cgroup or "").splitlines():
        if line.startswith("0::"):
            leaf = line[3:].rstrip("/").rsplit("/", 1)[-1]
            return "" if leaf in ("", "..", ".") else leaf
    return ""


def _unescape(s: str) -> str:
    return re.sub(r"\\x([0-9a-fA-F]{2})", lambda m: chr(int(m.group(1), 16)), s)


def app_id(unit: str) -> str | None:
    """The app a systemd unit was started for: `app-flatpak-com.opera.opera\\x2dgx-123.scope` -> com.opera.opera-gx,
    `app-steam@<hash>.service` -> steam. None for anything that isn't an app unit."""
    unit = _unescape(unit or "")
    m = re.match(r"^app-(.+?)\.(?:scope|service)$", unit)
    if not m:
        return None
    s = re.sub(r"@[^@]*$", "", m.group(1))
    s = re.sub(r"-\d+$", "", s)
    pre = re.match(r"^[A-Za-z0-9_]+-(.+\..+)$", s)
    if pre and "." not in s.split("-", 1)[0]:        # a launcher prefix: flatpak-, claude-, gnome-
        s = pre.group(1)
    return s or None


def read_procs(root: str = "/proc", cache: dict | None = None) -> list[Proc]:
    cache = cache if cache is not None else {}
    out = []
    try:
        names = os.listdir(root)
    except OSError:
        return out
    for n in names:
        if not n.isdigit():
            continue
        pid = int(n)
        st = parse_stat(_read(f"{root}/{n}/stat"))
        if not st:
            continue
        comm, ppid, ticks, start, rss = st
        uid = cache.get((pid, start))
        if uid is None:
            uid = -1
            for line in (_read(f"{root}/{n}/status") or "").splitlines():
                if line.startswith("Uid:"):
                    try:
                        uid = int(line.split()[1])
                    except (ValueError, IndexError):
                        pass
                    break
            cache[(pid, start)] = uid
        raw = _read(f"{root}/{n}/cmdline", binary=True) or b""
        cmd = [a.decode("utf-8", "replace") for a in raw.split(b"\0") if a]
        out.append(Proc(pid, ppid, comm, cmd, uid, parse_unit(_read(f"{root}/{n}/cgroup") or ""),
                        ticks, start, rss * PAGE / 1048576.0))
    return out


class ProcSampler:
    """CPU as deltas between two reads. The clock is /proc/stat's own jiffies, so a fake tree gives exact numbers:
    one core fully busy for the interval = 100."""

    def __init__(self, root: str = "/proc") -> None:
        self.root = root
        self._prev: dict = {}                    # (pid, start) -> ticks
        self._last = None                        # (busy, total) jiffies
        self._cache: dict = {}

    def _cpu_times(self):
        text = _read(f"{self.root}/stat") or ""
        cores, first = 0, None
        for line in text.splitlines():
            if line.startswith("cpu "):
                first = [int(x) for x in line.split()[1:]]
            elif re.match(r"cpu\d+ ", line):
                cores += 1
        if not first:
            return 0, 0, 1
        idle = first[3] + (first[4] if len(first) > 4 else 0)
        return sum(first) - idle, sum(first), max(cores, 1)

    def _mem_pct(self) -> float:
        kb = {}
        for line in (_read(f"{self.root}/meminfo") or "").splitlines():
            k, _, rest = line.partition(":")
            if k in ("MemTotal", "MemAvailable"):
                try:
                    kb[k] = int(rest.split()[0])
                except (ValueError, IndexError):
                    pass
        if not kb.get("MemTotal"):
            return 0.0
        return round(100.0 * (kb["MemTotal"] - kb.get("MemAvailable", 0)) / kb["MemTotal"], 1)

    def read(self):
        """-> (procs with .cpu set, machine cpu percent, memory percent)"""
        busy, total, cores = self._cpu_times()
        procs = read_procs(self.root, self._cache)
        first = self._last is None
        d_busy = d_total = 0
        if not first:
            d_busy, d_total = busy - self._last[0], total - self._last[1]
        self._last = (busy, total)
        machine = round(100.0 * d_busy / d_total, 1) if d_total > 0 else 0.0
        per_core = d_total / cores if d_total > 0 else 0       # jiffies one core had in the interval
        now = {}
        for p in procs:
            k = (p.pid, p.start)
            now[k] = p.ticks
            if first or per_core <= 0:
                continue
            delta = p.ticks - self._prev.get(k, 0)             # a pid new this round has only run this round
            p.cpu = max(0.0, 100.0 * delta / per_core)
        self._prev = now
        self._cache = {k: v for k, v in self._cache.items() if k in now}
        return procs, machine, self._mem_pct()


# --------------------------------------------------------------------------- .desktop files

@dataclass
class Entry:
    id: str
    name: str
    icon: str | None
    wmclass: str
    exec_base: str


def desktop_dirs() -> list[str]:
    dirs = []
    home = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    dirs.append(f"{home}/applications")
    for d in (os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share").split(":"):
        if d:
            dirs.append(f"{d}/applications")
    dirs += [f"{home}/flatpak/exports/share/applications", "/var/lib/flatpak/exports/share/applications",
             "/run/host/usr/share/applications", "/run/host/var/lib/flatpak/exports/share/applications"]
    return dirs


def parse_desktop(text: str, stem: str) -> Entry | None:
    name = icon = wm = ex = None
    inside = False
    for line in (text or "").splitlines():
        line = line.strip()
        if line.startswith("["):
            inside = line == "[Desktop Entry]"
            continue
        if not inside or "=" not in line:
            continue
        k, _, v = line.partition("=")
        if k == "Name" and name is None:
            name = v.strip()
        elif k == "Icon" and icon is None:
            icon = v.strip() or None
        elif k == "StartupWMClass" and wm is None:
            wm = v.strip()
        elif k == "Exec" and ex is None:
            for tok in v.split():
                if tok.startswith("%") or tok in ("env",) or "=" in tok.split("/")[0]:
                    continue
                ex = os.path.basename(tok.strip("\"'"))
                break
    if not name:
        return None
    return Entry(stem, name, icon, (wm or "").lower(), (ex or "").lower())


class Desktop:
    """A lazy index of the .desktop files: look an app up by desktop id, window class, binary or name."""

    def __init__(self, dirs=None) -> None:
        self._dirs = dirs
        self._entries: list[Entry] | None = None
        self._by: dict[str, Entry] = {}

    def _load(self) -> None:
        self._entries = []
        seen = set()
        for d in (self._dirs if self._dirs is not None else desktop_dirs()):
            try:
                files = sorted(os.listdir(d))
            except OSError:
                continue
            for f in files:
                if not f.endswith(".desktop") or f in seen:
                    continue
                seen.add(f)
                try:
                    text = Path(d, f).read_text("utf-8", "replace")
                except OSError:
                    continue
                e = parse_desktop(text, f[:-8])
                if e:
                    self._entries.append(e)
        # strongest keys first: an id beats a window class beats a binary beats a name
        for rank in ("id", "wmclass", "exec_base", "name"):
            for e in self._entries:
                key = getattr(e, rank).lower()
                if key:
                    self._by.setdefault(key, e)

    def lookup(self, *candidates) -> Entry | None:
        if self._entries is None:
            self._load()
        for c in candidates:
            if c and str(c).lower() in self._by:
                return self._by[str(c).lower()]
        return None


# --------------------------------------------------------------------------- grouping

def is_kernel(p: Proc) -> bool:
    return not p.cmd and (p.ppid in (0, 2) or p.pid == 2)


def is_system(p: Proc, my_uid: int) -> bool:
    if p.uid != my_uid or not p.cmd:                    # root's, other users', kernel threads, zombies
        return True
    u = p.unit
    if u.startswith("app-"):
        return False
    return u.endswith(".service") or u in ("init.scope", "udev")


def _daemon(p: Proc) -> bool:
    c = p.comm.lower()
    return any(c.startswith(d) for d in DAEMON_PREFIXES)


def group_procs(procs: list[Proc], my_uid: int) -> dict[str, list[Proc]]:
    """key -> its processes. key is SYSTEM, "app:<id>" or "proc:<pid of the tree's top>"."""
    by = {p.pid: p for p in procs}
    groups: dict[str, list[Proc]] = {}
    for p in procs:
        key = None
        if is_system(p, my_uid):
            key = SYSTEM
        else:
            aid = app_id(p.unit)
            if aid:
                key = "app:" + aid.lower()
            else:
                root, seen = p, {p.pid}
                while True:
                    par = by.get(root.ppid)
                    if (par is None or par.pid <= 1 or par.pid in seen or par.comm in BOUNDARY
                            or is_system(par, my_uid)):
                        break
                    seen.add(par.pid)
                    root = par
                aid = app_id(root.unit)
                if aid:
                    key = "app:" + aid.lower()
                elif _daemon(root):
                    key = SYSTEM
                else:
                    key = f"proc:{root.pid}"
        groups.setdefault(key, []).append(p)
    return groups


def ancestors(pid: int, by: dict) -> set:
    out, seen = set(), set()
    while pid in by and pid not in seen:
        seen.add(pid)
        out.add(pid)
        pid = by[pid].ppid
    return out


def protected_pids(procs: list[Proc], self_pid: int) -> set:
    by = {p.pid: p for p in procs}
    keep = {1, self_pid} | ancestors(self_pid, by)
    for p in procs:
        if p.comm.lower() in PROTECTED_COMM or any("ariadne" in a.lower() for a in p.cmd):
            keep.add(p.pid)
    return keep


def proc_label(p: Proc) -> str:
    c = p.comm
    if c.lower().startswith(INTERPRETERS):
        for a in p.cmd[1:]:
            if not a.startswith("-"):
                base = os.path.basename(a.rstrip("/"))
                return re.sub(r"\.(py|js|jar|rb|pl|sh)$", "", base) or c
    return c


@dataclass
class Group:
    key: str
    name: str
    icon: str | None
    procs: list = field(default_factory=list)
    win_ids: list = field(default_factory=list)
    protected: str | None = None                 # why it can't be closed, or None

    @property
    def pids(self):
        return sorted(p.pid for p in self.procs)


def _last_segment(aid: str) -> str:
    return aid.rsplit(".", 1)[-1] if "." in aid else aid


def build_groups(procs, windows, my_uid, self_pid, desktop: Desktop) -> list[Group]:
    """Name the groups, attach windows, mark the protected ones, merge groups that came out with one name."""
    prot = protected_pids(procs, self_pid)
    raw = group_procs(procs, my_uid)
    pid_key = {p.pid: k for k, ps in raw.items() for p in ps}
    wins: dict[str, list] = {}
    loose = []
    for w in windows or []:
        k = pid_key.get(w.get("pid"))
        if k and k != SYSTEM:
            wins.setdefault(k, []).append(w)
        else:
            loose.append(w)
    named: dict[str, Group] = {}
    meta = {}
    for key, ps in raw.items():
        aid = key[4:] if key.startswith("app:") else None
        inside = {q.pid for q in ps}
        top = min(ps, key=lambda p: (p.ppid in inside, p.pid))
        if key == SYSTEM:
            name, icon = SYSTEM, None
        else:
            ws = wins.get(key, [])
            cands = [x for w in ws for x in (w.get("desk"), w.get("cls"))]
            cands += [aid, _last_segment(aid) if aid else None, top.comm,
                      os.path.basename(top.cmd[0]) if top.cmd else None]
            e = desktop.lookup(*cands)
            icon = e.icon if e else None
            if e:
                name = e.name
            elif ws and ws[0].get("cls"):
                name = ws[0]["cls"]
            elif aid:
                name = _last_segment(aid)
            else:
                name = proc_label(top)
        meta[key] = (name, aid, top, icon)
    # windows whose pid we couldn't place: match by class/desktop name to a group
    for w in loose:
        want = {str(x).lower() for x in (w.get("cls"), w.get("desk")) if x}
        for key, (name, aid, top, _icon) in meta.items():
            if key == SYSTEM:
                continue
            have = {name.lower(), top.comm.lower()}
            if aid:
                have |= {aid, _last_segment(aid)}
            if want & have:
                wins.setdefault(key, []).append(w)
                break
    for key, ps in raw.items():
        name, aid, top, icon = meta[key]
        g = named.get(name.lower())
        if g is None:
            g = named[name.lower()] = Group(key, name, icon)
        elif g.icon is None:
            g.icon = icon
        g.procs += ps
        g.win_ids += [w["id"] for w in wins.get(key, []) if w.get("id")]
        if key == SYSTEM:
            g.protected = "System is the session and the machine's own daemons"
        elif aid and "ariadne" in aid:
            g.protected = "that's Ariadne"
        elif any(p.pid in prot for p in ps):
            g.protected = "it's running Ariadne or the session itself"
    return list(named.values())


# --------------------------------------------------------------------------- GPU

def parse_gpu_apps(text: str) -> dict[int, float] | None:
    """{pid: MiB} from `nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader,nounits`.
    None when it isn't that output at all (no driver); {} when nothing is using the GPU."""
    out: dict[int, float] = {}
    lines = [l for l in (text or "").splitlines() if l.strip()]
    for line in lines:
        parts = [x.strip() for x in line.split(",")]
        try:
            pid = int(parts[0])
        except (ValueError, IndexError):
            if "no running" in line.lower():
                return {}
            return None
        try:
            out[pid] = out.get(pid, 0.0) + float(parts[1])
        except (ValueError, IndexError):
            out.setdefault(pid, 0.0)             # "[N/A]": it's on the GPU, size unknown
    return out


async def read_gpu_apps() -> dict[int, float] | None:
    if not shutil.which("nvidia-smi"):
        return None
    try:
        proc = await asyncio.create_subprocess_exec(
            "nvidia-smi", "--query-compute-apps=pid,used_memory", "--format=csv,noheader,nounits",
            stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL)
        out, _ = await asyncio.wait_for(proc.communicate(), 4)
    except (OSError, asyncio.TimeoutError):
        return None
    return parse_gpu_apps(out.decode("utf-8", "replace")) if proc.returncode == 0 else None


# --------------------------------------------------------------------------- KWin

LIST_JS = """
var list = (typeof workspace.windowList === "function") ? workspace.windowList() : workspace.clientList();
var out = [];
for (var i = 0; i < list.length; i++) {
    var w = list[i];
    if (!w || !w.normalWindow || w.skipTaskbar) continue;
    out.push({id: String(w.internalId), pid: w.pid, cls: String(w.resourceClass),
              desk: String(w.desktopFileName || ""), cap: String(w.caption).substring(0, 80)});
}
__REPLY__JSON.stringify(out));
"""


def act_js(action: str, ids: list) -> str:
    do = ("w.closeWindow();" if action == "close" else
          "if (w.minimized) w.minimized = false; workspace.activeWindow = w; break;")
    return f"""
var ids = {json.dumps([str(i) for i in ids])};
var list = (typeof workspace.windowList === "function") ? workspace.windowList() : workspace.clientList();
for (var i = 0; i < list.length; i++) {{
    var w = list[i];
    if (!w || ids.indexOf(String(w.internalId)) < 0) continue;
    {do}
}}
"""


def parse_windows(payload) -> list[dict]:
    try:
        data = json.loads(payload or "[]")
    except ValueError:
        return []
    return [w for w in data if isinstance(w, dict) and isinstance(w.get("pid"), int)] if isinstance(data, list) else []


# --------------------------------------------------------------------------- the adapter

class TasksAdapter(Adapter):
    name = "tasks"

    def __init__(self, publish, root: str = "/proc", kwin=None, gpu=None, desktop=None, kill=None,
                 self_pid: int | None = None, my_uid: int | None = None, mono=None, spawn=None,
                 pins: Path | None = None) -> None:
        super().__init__(publish)
        self._pins_path = pins or pins_path()
        try:
            self.pins: list[str] = [str(n) for n in json.loads(self._pins_path.read_text())][:50]
        except (OSError, ValueError, TypeError):
            self.pins = []
        self._spawn = spawn              # tests: catches the restart instead of running it
        self.sampler = ProcSampler(root)
        self._kwin = kwin
        self._gpu = gpu or read_gpu_apps
        self.desktop = desktop or Desktop()
        self._kill = kill or os.kill
        self.self_pid = os.getpid() if self_pid is None else self_pid
        self.my_uid = os.getuid() if my_uid is None else my_uid
        self.mono = mono or time.monotonic
        self._state: dict = {"status": "ok", "apps": [], "total": {"cpu": 0.0, "mem_pct": 0.0}}
        self._groups: list[Group] = []
        self._prot: set = set()
        self._windows: list = []
        self._procs: list = []
        self._gpu_now = None
        self._round = 0
        self._asked: dict[str, float] = {}
        self._main: asyncio.Task | None = None
        self.controls = {"close": "close", "focus": "focus"}
        self.verbs = [
            Verb("open", "Start an app from his menu by name (\"Spotify\", \"Steam\", \"Firefox\", \"Discord\"): "
                 "it opens on his desktop as if he'd clicked it. Use it whenever something he wants needs an "
                 "app that isn't running.",
                 {"properties": {"app": {"type": "string", "description": "the app's name"}},
                  "required": ["app"]}, self._open),
            Verb("report", "A short read of what's using the machine: the top apps by CPU (default 5, up to 25) "
                 "with their CPU, memory and GPU memory, and the biggest memory user. Read-only.",
                 {"properties": {"n": {"type": "integer", "description": "how many apps to list (1-25)"}}},
                 self._report),
            Verb("focus", "Bring an open app's window to the front. Name it as the Tasks list does "
                 "(\"Discord\", \"Steam\").",
                 {"properties": {"app": {"type": "string", "description": "the app's name"}},
                  "required": ["app"]}, self._focus, control="focus"),
            Verb("close", "Close an open app. Destructive: unsaved work or a running game can be lost, so confirm "
                 "with him first unless he asked you to close it. The first call politely asks its windows to "
                 "close; calling again for the same app ends its processes (SIGTERM). Refuses the system, the "
                 "session and Ariadne herself.",
                 {"properties": {"app": {"type": "string", "description": "the app's name"}},
                  "required": ["app"]}, self._close, control="close"),
            Verb("restart_yourself", "Restart yourself, Ariadne: every part closes at once and comes back in "
                 "about 20 seconds. Only when he asks. It ends whatever you have running (a Claude hand's job, a "
                 "flow mid-run).",
                 {}, self._restart, consent="him"),
        ]

    async def _restart(self) -> str:
        # Her own launcher, run straight from here, detached: it stops what's
        # running (her included) and starts it all again, right away.
        import subprocess
        argv = [str(REPO / "bin" / "ariadne2")]
        if self._spawn is not None:
            self._spawn(argv)
        else:
            base = Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")) / "ariadne2"
            base.mkdir(parents=True, exist_ok=True)
            with open(base / "launcher.log", "ab") as out:
                subprocess.Popen(argv, cwd=REPO, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
                                 start_new_session=True)
        log.info("restarting, as he asked")
        return "Restarting now; back in about 20 seconds."

    async def _open(self, app: str) -> str:
        from .launch import open_app
        return await open_app(app)

    def press_args(self, control: str, value) -> dict:
        return {"app": str(value or "")}

    async def press(self, control: str, value=None) -> str | None:
        if control != "pin":
            return await super().press(control, value)
        name = str(value or "").strip()          # his click only: not a verb, so not hers to change
        if not name:
            return None
        self.pins = [n for n in self.pins if n != name] if name in self.pins else (self.pins + [name])[-50:]
        try:
            self._pins_path.parent.mkdir(parents=True, exist_ok=True)
            self._pins_path.write_text(json.dumps(self.pins))
        except OSError as e:
            log.warning("couldn't save the pins: %s", e)
        await self._regroup()
        await self.publish_state()
        return None

    # ---- lifecycle ----

    async def start(self) -> None:
        self._main = asyncio.create_task(self._loop())
        await self.refresh()

    async def stop(self) -> None:
        if self._main:
            self._main.cancel()
            await asyncio.gather(self._main, return_exceptions=True)

    def state(self) -> dict:
        return self._state

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(PERIOD)
            try:
                await self.refresh()
            except Exception:
                log.exception("tasks refresh failed")

    # ---- reading ----

    async def _kwin_run(self, js: str, expect_reply: bool):
        if self._kwin is not None:
            return await asyncio.to_thread(self._kwin, js, expect_reply)
        from ..core.tools import windows            # late: only here, and tests hook windows.KWIN_HOOK
        return await asyncio.to_thread(windows.kwin_script, js, expect_reply)

    async def poll_windows(self) -> None:
        try:
            self._windows = parse_windows(await self._kwin_run(LIST_JS, True))
        except AdapterError as e:                       # not KDE, no bus, forbidden: no window counts
            log.debug("no window list: %s", e)
            self._windows = []
        except Exception:
            log.exception("window list failed")
            self._windows = []

    async def refresh(self) -> None:
        procs, machine, mem = await asyncio.to_thread(self.sampler.read)
        self._procs = procs
        if self._round % WINDOW_EVERY == 0:
            await self.poll_windows()
        if self._round % GPU_EVERY == 0:
            try:
                self._gpu_now = await self._gpu()
            except Exception:
                log.exception("gpu read failed")
                self._gpu_now = None
        self._round += 1
        self._state = self.assemble(procs, machine, mem)
        await self.publish_state()

    def assemble(self, procs, machine: float, mem: float) -> dict:
        self._prot = protected_pids(procs, self.self_pid)
        self._groups = build_groups(procs, self._windows, self.my_uid, self.self_pid, self.desktop)
        gpu = self._gpu_now
        rows = []
        for g in self._groups:
            rows.append({"name": g.name, "pids": g.pids[:MAX_PIDS],
                         "cpu": round(sum(p.cpu for p in g.procs), 1),
                         "mem_mb": round(sum(p.rss_mb for p in g.procs), 1),
                         "gpu_mb": None if gpu is None else round(sum(gpu.get(p.pid, 0.0) for p in g.procs), 1),
                         "windows": len(g.win_ids), "icon": g.icon})
        rows.sort(key=lambda r: (-r["cpu"], -r["mem_mb"], r["name"].lower()))
        # His pins (right-click in the widget): on top in the order he pinned
        # them, and always listed while running, however quiet.
        pinned = [r for n in self.pins for r in rows if r["name"] == n]
        for r in pinned:
            r["pinned"] = True
        rest = [r for r in rows if not r.get("pinned")]
        return {"status": "ok", "apps": pinned + rest[:max(0, MAX_APPS - len(pinned))],
                "total": {"cpu": machine, "mem_pct": mem}}

    # ---- verbs ----

    def _resolve(self, app: str) -> Group:
        want = (app or "").strip().lower()
        if not want:
            raise AdapterError("which app?")
        exact = [g for g in self._groups if g.name.lower() == want]
        part = exact or [g for g in self._groups if want in g.name.lower()]
        if not part:
            raise AdapterError(f"no open app called {app!r}")
        if len(part) > 1:
            raise AdapterError("that could be " + ", ".join(g.name for g in part[:5]) + ": which one?")
        return part[0]

    async def _report(self, n: int = 5) -> str:
        try:
            n = max(1, min(int(n), MAX_APPS))
        except (TypeError, ValueError):
            n = 5
        rows = self._state["apps"][:n]
        if not rows:
            return "I can't see any apps yet."
        bits = []
        for r in rows:
            s = f"{r['name']} {r['cpu']:.0f}% CPU, {r['mem_mb']:.0f} MB"
            if r["gpu_mb"]:
                s += f", {r['gpu_mb']:.0f} MB GPU"
            bits.append(s)
        text = "Busiest: " + "; ".join(bits) + "."
        big = max(self._state["apps"], key=lambda r: r["mem_mb"])
        text += f" Most memory: {big['name']} ({big['mem_mb']:.0f} MB)."
        t = self._state["total"]
        return text + f" Machine: CPU {t['cpu']:.0f}%, memory {t['mem_pct']:.0f}%."

    async def _focus(self, app: str) -> str:
        await self.poll_windows()
        await self._regroup()
        g = self._resolve(app)
        if not g.win_ids:
            raise AdapterError(f"{g.name} has no window open")
        await self._kwin_run(act_js("focus", g.win_ids), False)
        return f"Brought {g.name} to the front."

    async def _close(self, app: str) -> str:
        await self.poll_windows()
        await self._regroup()
        g = self._resolve(app)
        if g.protected:
            raise AdapterError(f"I won't close {g.name}: {g.protected}.")
        key, now = g.name.lower(), self.mono()
        asked = self._asked.get(key)
        if g.win_ids and not (asked is not None and now - asked < ASK_TTL):
            await self._kwin_run(act_js("close", g.win_ids), False)
            self._asked[key] = now
            w = len(g.win_ids)
            return (f"Asked {g.name} to close ({w} window{'s' if w != 1 else ''}). "
                    "If it stays open, ask again and I'll end it.")
        sent = failed = 0
        for pid in g.pids:
            if pid in self._prot:
                continue
            try:
                self._kill(pid, signal.SIGTERM)
                sent += 1
            except ProcessLookupError:
                pass
            except OSError:
                failed += 1
        self._asked.pop(key, None)
        if not sent:
            raise AdapterError(f"couldn't end {g.name}" + (" (not allowed to)" if failed else " (already gone)"))
        return f"Ended {g.name} (SIGTERM to {sent} process{'es' if sent != 1 else ''})."

    async def _regroup(self) -> None:
        t = self._state["total"]
        self._state = self.assemble(self._procs, t["cpu"], t["mem_pct"])      # same numbers, fresh windows
