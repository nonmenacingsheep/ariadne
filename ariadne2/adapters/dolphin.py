"""The Dolphin adapter: the folder he is in, what he used lately, and file jobs done for him.

State comes from KDE's own lists (recently-used.xbel, the activity history) and a D-Bus question to
Dolphin; folders that are being watched are polled for new files. Verbs open, find, list, move, sort and
trash, always inside $HOME or /var/mnt, and trash goes to the desktop trash (recoverable), never gone.
Disk helpers live in dolphin_files.py.
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import time
from pathlib import Path

from .base import Adapter, AdapterError, Verb
from . import dolphin_files as df
from .dolphin_files import Guard, PathRefused, Recents

log = logging.getLogger("ariadne2.adapters.dolphin")

PERIOD = 5.0
RECENT = 8
FILE_MANAGER = ("org.freedesktop.FileManager1", "/org/freedesktop/FileManager1",
                "org.freedesktop.FileManager1")


def blank_state() -> dict:
    return {"status": "ok", "current": None, "recent_folders": [], "recent_files": [], "watched": []}


async def _quiet_exec(*cmd: str, timeout: float) -> int | None:
    """Run a command, return its exit code; None if it was still running at the timeout."""
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE, start_new_session=True)
    try:
        await asyncio.wait_for(proc.wait(), timeout)
    except asyncio.TimeoutError:
        return None
    return proc.returncode


async def show_in_dolphin(path: Path) -> None:
    """Dolphin shows a folder, or the folder with the file selected. D-Bus first (it also starts Dolphin),
    then the host's xdg-open for a folder."""
    method = "ShowFolders" if path.is_dir() else "ShowItems"
    if shutil.which("busctl"):
        try:
            code = await _quiet_exec("busctl", "--user", "call", *FILE_MANAGER, method, "ass", "1",
                                     df.file_url(str(path)), "", timeout=8)
        except OSError:
            code = 1
        if code in (0, None):
            return
    if shutil.which("xdg-open"):
        target = path if path.is_dir() else path.parent
        try:
            code = await _quiet_exec("xdg-open", str(target), timeout=5)
        except OSError as e:
            raise AdapterError(f"couldn't reach Dolphin: {e.strerror}")
        if code in (0, None):
            return
    raise AdapterError("I couldn't get Dolphin to show that (no session bus or xdg-open answered)")


async def gio_trash(path: Path) -> None:
    """Move to the XDG trash with gio, which also handles files on other drives."""
    if not shutil.which("gio"):
        raise AdapterError("gio isn't installed, so I can't use the trash; nothing was deleted")
    proc = await asyncio.create_subprocess_exec(
        "gio", "trash", "--", str(path), stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
    try:
        _, err = await asyncio.wait_for(proc.communicate(), 30)
    except asyncio.TimeoutError:
        proc.kill()
        raise AdapterError("the trash took too long; check whether it moved")
    if proc.returncode:
        why = err.decode("utf-8", "replace").strip().splitlines()[-1:] or ["unknown reason"]
        raise AdapterError(f"couldn't trash it ({why[0][:60]}); nothing was deleted")


class DolphinAdapter(Adapter):
    name = "dolphin"
    events = ("file_appeared",)
    event_info = {"file_appeared": {"phrase": "sees a new file in a watched folder",
                                    "fields": {"path": "path", "name": "text", "folder": "path",
                                               "kind": "text"},
                                    "outside": True}}        # a downloaded file is named by whoever made it
    state_fields = {"status": ("text", "status"), "folder": ("path", "current.path"),
                    "recent_folders": ("list", "recent_folders"), "recent_files": ("list", "recent_files"),
                    "watched": ("list", "watched")}

    def __init__(self, publish, guard=None, recents=None, trasher=None, opener=None, dbus=None,
                 watch=None) -> None:
        super().__init__(publish)
        self.guard = guard or Guard()
        self.recents = recents or Recents(self.guard)
        self._trash = trasher or gio_trash
        self._open = opener or show_in_dolphin
        self._dbus = dbus or df.busctl
        self.now = time.time
        self.mono = time.monotonic
        self._state = blank_state()
        self._watch: dict[Path, dict] = {}       # folder -> {"known": {name: sig}, "pending": {}, "new": int}
        self._watch_wanted: list = []
        self.watch(watch if watch is not None else [self.guard.home / "Downloads"])
        self._wake = asyncio.Event()
        self._main: asyncio.Task | None = None
        self.controls = {"open": "open"}
        path = {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}
        self.verbs = [
            Verb("open", "Show a file or folder in Dolphin (a file is shown selected in its folder). Takes a "
                 "path under his home or /var/mnt/games.", path, self._open_verb, "open"),
            Verb("find", "Search file and folder names under his home and the games drive (all words must "
                 "appear in the name; case ignored). Returns up to 30 paths as text. 'where' narrows it: a "
                 "folder path, 'home' or 'games'.",
                 {"type": "object", "properties": {"query": {"type": "string"}, "where": {"type": "string"}},
                  "required": ["query"]}, self._find),
            Verb("list", "List what is in a folder as text: folders first, then files with kind, size and "
                 "age. Hidden files are counted, not shown.",
                 {"type": "object", "properties": {"folder": {"type": "string"}}, "required": ["folder"]},
                 self._list),
            Verb("move", "Move or rename a file or folder. If dest is an existing folder (or ends with /), it "
                 "goes inside it. Never overwrites: if the destination exists it refuses. Does not touch "
                 "hidden folders. Tell him what you moved.",
                 {"type": "object", "properties": {"src": {"type": "string"}, "dest": {"type": "string"}},
                  "required": ["src", "dest"]}, self._move, "move"),
            Verb("sort", "Tidy a folder (like Downloads): loose files go into Images, Audio, Video, "
                 "Documents, Archives, Installers and Other subfolders. Folders, hidden files and anything "
                 "touched in the last 30 seconds stay put; nothing is overwritten. Returns a summary of "
                 "what went where. Only when he asked for a tidy; say which folder first if unsure.",
                 {"type": "object", "properties": {"folder": {"type": "string"}}, "required": ["folder"]},
                 self._sort, "sort"),
            Verb("trash", "Put a file or folder in the desktop trash, where he can restore it in Dolphin. "
                 "This is the only way to remove anything; there is no permanent delete. Confirm with him "
                 "first unless he named the file and asked.", path, self._trash_verb, "trash"),
        ]

    # ---- watching ----

    def watch(self, folders) -> None:
        """Watch these folders for new files (replaces the list). Anything outside the guard is dropped;
        one that doesn't exist yet is picked up when it appears."""
        self._watch_wanted = list(folders)
        self._sync_watch()

    def _sync_watch(self) -> None:
        keep: dict[Path, dict] = {}
        for f in self._watch_wanted:
            try:
                p = self.guard.resolve(f)
            except PathRefused:
                continue
            if p.is_dir():
                keep[p] = self._watch.get(p) or {"known": None, "pending": {}, "new": 0}
        self._watch = keep

    def _look(self, folder: Path) -> None:
        """He looked at this folder (open, list, sort), so its 'new' count starts over."""
        w = self._watch.get(folder)
        if w and w["new"]:
            w["new"] = 0
            self._poke()

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

    def _poke(self) -> None:
        self._wake.set()

    async def _loop(self) -> None:
        while True:
            try:
                await asyncio.wait_for(self._wake.wait(), PERIOD)
                await asyncio.sleep(0.3)
            except asyncio.TimeoutError:
                pass
            self._wake.clear()
            try:
                await self.refresh()
            except Exception:
                log.exception("dolphin refresh failed")

    def _scan(self) -> dict:
        return {"snaps": {p: df.snapshot(p) for p in list(self._watch)},
                "files": self.recents.files(RECENT), "folders": self.recents.folders(RECENT)}

    async def refresh(self) -> None:
        self._sync_watch()
        scan = await asyncio.to_thread(self._scan)
        self._events(scan["snaps"])
        current = await self._current(scan["folders"])
        if current:
            self._look(Path(current["path"]))
        new = {"status": "ok", "current": current, "recent_folders": scan["folders"],
               "recent_files": scan["files"],
               "watched": [{"path": str(p), "name": p.name or str(p), "new": w["new"]}
                           for p, w in self._watch.items()]}
        if new != self._state:
            self._state = new
            await self.publish_state()

    async def _current(self, folders: list[dict]) -> dict | None:
        windows = await df.dolphin_windows(self._dbus)
        if not windows:
            return None
        cands = []
        for f in folders + [{"path": str(self.guard.home)}]:
            raw = self.recents.raw.get(f["path"])
            cands += [x for x in (raw, f["path"], "/var" + f["path"] if f["path"].startswith("/home/") else None)
                      if x]
        hit = await df.open_folder_among(cands, windows, self._dbus)
        if hit is None:
            return None
        p = self.guard.local(hit)
        return {"path": p, "name": os.path.basename(p) or p}

    def _events(self, snaps: dict) -> None:
        """New files: seen in two polls with the same size and time (so a finished download), then announced."""
        for folder, snap in snaps.items():
            w = self._watch.get(folder)
            if w is None:
                continue
            if w["known"] is None:                         # first look: what's there is not news
                w["known"] = dict(snap)
                continue
            known, pending = w["known"], w["pending"]
            for name in [n for n in known if n not in snap]:
                del known[name]
            for name in [n for n in pending if n not in snap]:
                del pending[name]
            for name, sig in snap.items():
                if name in known and known[name] == sig:
                    continue
                if name in known:                          # rewritten in place: not a new file
                    known[name] = sig
                    continue
                if pending.get(name) != sig:
                    pending[name] = sig                    # appeared or still growing: wait one more poll
                    continue
                del pending[name]
                known[name] = sig
                w["new"] += 1
                path = folder / name
                self.emit("file_appeared", path=str(path), name=name, folder=str(folder),
                          kind=df.kind_of(name))

    # ---- verbs ----

    def _resolve(self, raw, **kw) -> Path:
        try:
            return self.guard.resolve(raw, **kw)
        except PathRefused as e:
            raise AdapterError(str(e)) from None

    async def _open_verb(self, path: str) -> str:
        p = self._resolve(path)
        await self._open(p)
        if p.is_dir():
            self._look(p)
        self._poke()
        return f"Showing {self.guard.shorten(p)} in Dolphin."

    async def _find(self, query: str, where: str | None = None) -> str:
        q = str(query or "").strip()
        if not q:
            raise AdapterError("say what to look for")
        w = str(where or "").strip().lower()
        games = self.guard.mounts / "games"
        if not w:
            roots = [self.guard.home] + ([games] if games.is_dir() and self.guard.allowed(games) else [])
        elif w == "home":
            roots = [self.guard.home]
        elif w in ("games", "olympus"):
            roots = [games]
        else:
            roots = [self._resolve(where)]
        hits, stopped = await asyncio.to_thread(df.find_files, q, roots, None, self.mono)
        now = self.now()
        head = f"{len(hits)} match for {q!r}" if len(hits) == 1 else f"{len(hits)} matches for {q!r}"
        if stopped:
            head += f" (stopped early: {stopped}; narrow it with 'where')"
        if not hits:
            return head + "."
        return head + ":\n" + "\n".join(df.describe(p, now, self.guard) for p, _ in hits)

    async def _list(self, folder: str) -> str:
        p = self._resolve(folder)
        if not p.is_dir():
            raise AdapterError(f"{self.guard.shorten(p)} is a file, not a folder")
        self._look(p)
        try:
            return await asyncio.to_thread(df.list_folder, p, self.now(), self.guard)
        except PathRefused as e:
            raise AdapterError(str(e)) from None

    def _dest_for(self, src: Path, dest: str) -> tuple[Path, Path | None]:
        """(final path, folder to create first or None). A folder (existing or written with /) takes src inside."""
        into_new = str(dest).rstrip().endswith("/")
        d = self._resolve(dest, write=True, must_exist=False)
        if os.path.isdir(d) or into_new:
            return d / src.name, (d if not os.path.isdir(d) else None)
        return d, None

    async def _move(self, src: str, dest: str) -> str:
        s = self._resolve(src, write=True)
        final, make = self._dest_for(s, dest)
        if final == s:
            raise AdapterError("the source and destination are the same place")
        if os.path.lexists(final):
            raise AdapterError(f"{self.guard.shorten(final)} already exists; I won't overwrite it. "
                               "Pick another name, or trash that one first")
        if s.is_dir() and (final == s or s in final.parents):
            raise AdapterError("that would move a folder into itself")
        if not make and not final.parent.exists():
            raise AdapterError(f"{self.guard.shorten(final.parent)} doesn't exist; end the destination "
                               "with / to create it")
        await self.progress(s.name)
        try:
            await asyncio.to_thread(self._do_move, s, final, make)
        except OSError as e:
            raise AdapterError(f"couldn't move it: {e.strerror or e}") from None
        self._poke()
        return f"Moved {self.guard.shorten(s)} to {self.guard.shorten(final)}."

    @staticmethod
    def _do_move(src: Path, final: Path, make: Path | None) -> None:
        if make:
            make.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(final))

    async def _sort(self, folder: str) -> str:
        p = self._resolve(folder, write=True)
        if not p.is_dir():
            raise AdapterError(f"{self.guard.shorten(p)} is a file, not a folder")
        try:
            moves, notes = await asyncio.to_thread(df.sort_plan, p, self.now())
        except PathRefused as e:
            raise AdapterError(str(e)) from None
        if not moves:
            self._look(p)
            return f"Nothing to sort in {self.guard.shorten(p)}." + "".join(f" ({n})" for n in notes)
        counts: dict[str, int] = {}
        done: list[str] = []
        for src, dest in moves:
            await self.progress(src.name)
            try:
                await asyncio.to_thread(self._do_move, src, dest, dest.parent)
            except OSError as e:
                notes.append(f"{src.name}: {e.strerror or e}")
                continue
            counts[dest.parent.name] = counts.get(dest.parent.name, 0) + 1
            done.append(f"{src.name} -> {dest.parent.name}/" + (f" as {dest.name}" if dest.name != src.name else ""))
        self._look(p)
        self._poke()
        summary = ", ".join(f"{k} {v}" for k, v in sorted(counts.items()))
        shown = "\n".join(done[:12]) + (f"\n(and {len(done) - 12} more)" if len(done) > 12 else "")
        tail = ("\nNot done: " + "; ".join(notes)) if notes else ""
        return f"Sorted {self.guard.shorten(p)}: {len(done)} moved ({summary}).\n{shown}{tail}"

    async def _trash_verb(self, path: str) -> str:
        p = self._resolve(path, write=True)
        await self.progress(p.name)
        await self._trash(p)
        self._poke()
        return f"Moved {self.guard.shorten(p)} to the trash. He can restore it from Dolphin's Trash."

    # ---- his clicks in the widget ----

    def press_args(self, control: str, value) -> dict:
        if value is None or not str(value).strip():
            raise AdapterError(f"{control} needs a path")
        return {"path": str(value)}
