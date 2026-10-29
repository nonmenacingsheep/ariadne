"""read_file, write_file, edit_file, find_files, search_text.

Ported from 1.x skills.py and project.py. Credentials are invisible to all of
them (listings and hits skip sensitive paths), reads stay in the known roots,
writes in $HOME and /tmp. Text read from a file goes back quoted as content.
"""
from __future__ import annotations

import fnmatch
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from . import common
from .common import (PRUNE_DIRS, ToolError, audit, clip, human_size, in_project, is_sensitive,
                      need_him, outside, resolve, short)

WALK_BUDGET = 6.0          # seconds a filesystem walk may spend
WALK_MAX_ENTRIES = 120_000
MAX_READ = 8 * 1024 * 1024
MAX_EDIT = 200_000         # chars of file an edit will touch
MAX_WRITE = 400_000


def _span(lines) -> tuple[int, int]:
    """'40-90' or '40:90' -> (40, 50 lines); '40' -> 200 lines from 40; none -> first 200."""
    if lines in (None, ""):
        return 1, 200
    m = re.fullmatch(r"\s*(\d+)\s*(?:[-:,]\s*(\d+))?\s*", str(lines))
    if not m:
        raise ToolError("lines is a range like '40-90', or a start line like '40'")
    start = max(1, int(m.group(1)))
    end = int(m.group(2)) if m.group(2) else start + 199
    return start, max(1, min(end - start + 1, 500))


def read_file(path: str, lines=None) -> str:
    target = resolve(path)
    if target.is_dir():
        return _list_dir(target)
    if not target.exists():
        raise ToolError(f"{short(target)} doesn't exist")
    try:
        size = target.stat().st_size
    except OSError as exc:
        raise ToolError(f"can't stat {short(target)}: {exc.strerror}")
    if size > MAX_READ:
        raise ToolError(f"{short(target)} is {human_size(size)} — too big to read; use search_text or lines of it with shell")
    start, count = _span(lines)
    out = []
    try:
        with target.open("r", encoding="utf-8", errors="replace") as fh:
            for n, line in enumerate(fh, 1):
                if n < start:
                    continue
                if n >= start + count:
                    out.append(f"... [more lines follow; the file continues past {n - 1}]")
                    break
                out.append(f"{n}\t{line.rstrip()}")
    except OSError as exc:
        raise ToolError(f"can't read {short(target)}: {exc.strerror}")
    body = "\n".join(out) or "(empty file)"
    # Source she's editing in the open project keeps its `name = value` lines
    # intact (an edit has to match them); real token shapes still go.
    mine = in_project(target)
    return f"{short(target)} ({human_size(size)}), lines {start}+:\n" + outside(
        body, f"the file {short(target)}", strong_only=mine)


def _list_dir(target: Path, limit: int = 80) -> str:
    try:
        entries = sorted(os.scandir(target), key=lambda e: (not e.is_dir(), e.name.lower()))
    except OSError as exc:
        raise ToolError(f"can't list {short(target)}: {exc.strerror}")
    rows = []
    for e in entries:
        if is_sensitive(Path(e.path)):
            continue
        try:
            rows.append(e.name + ("/" if e.is_dir() else f"\t{human_size(e.stat().st_size)}"))
        except OSError:
            rows.append(e.name)
    more = f"\n... and {len(rows) - limit} more" if len(rows) > limit else ""
    return outside("\n".join(rows[:limit]) or "(empty)", f"the listing of {short(target)}") + more


def write_file(path: str, text: str, mode: str, his_words: str | None) -> str:
    target = resolve(path, write=True)
    need_him(his_words, "writing a file")
    mode = mode or "create"
    if mode not in ("create", "overwrite", "append"):
        raise ToolError("mode is create, overwrite or append")
    if target.is_dir():
        raise ToolError(f"{short(target)} is a directory")
    if target.exists() and mode == "create":
        raise ToolError(f"{short(target)} already exists — pass mode overwrite or append if that is what he meant")
    text = str(text if text is not None else "")
    if len(text) > MAX_WRITE:
        raise ToolError("that is too much to write in one go; write it in parts (mode append)")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a" if mode == "append" else "w", encoding="utf-8") as fh:
            fh.write(text)
    except OSError as exc:
        raise ToolError(f"couldn't write {short(target)}: {exc.strerror}")
    audit("write_file", {"path": str(target), "mode": mode}, "ok", f"{len(text)} chars")
    verb = {"create": "Created", "overwrite": "Overwrote", "append": "Appended to"}[mode]
    return f"{verb} {short(target)} ({len(text)} chars)."


def edit_file(path: str, old: str, new: str, replace_all: bool, his_words: str | None) -> str:
    """Replace one exact passage; refuses if it isn't there or isn't unique, so an
    edit lands where it was meant or not at all."""
    target = resolve(path, write=True)
    need_him(his_words, "editing a file")
    if not target.is_file():
        raise ToolError(f"{short(target)} doesn't exist — write_file creates files")
    try:
        text = target.read_text("utf-8")
    except (OSError, UnicodeError) as exc:
        raise ToolError(f"can't edit {short(target)}: {exc}")
    if len(text) > MAX_EDIT:
        raise ToolError(f"{target.name} is too big to edit this way")
    old, new = str(old or ""), str(new if new is not None else "")
    if old == new:
        raise ToolError("old and new are the same; nothing to change")
    count = text.count(old) if old else 0
    if count == 0:
        raise ToolError(f"that passage isn't in {target.name}. It has to match exactly, spaces and "
                        f"indentation included — read_file the lines first and copy them.")
    if count > 1 and not replace_all:
        raise ToolError(f"that passage is in {target.name} {count} times. Include more of the lines "
                        f"around it so it's unique, or pass replace_all.")
    after = text.replace(old, new) if replace_all else text.replace(old, new, 1)
    target.write_text(after, "utf-8")
    line = text[:text.index(old)].count("\n") + 1
    changed = count if replace_all else 1
    audit("edit_file", {"path": str(target)}, "ok", f"line {line}")
    return f"Edited {short(target)} at line {line} ({changed} place{'s' if changed > 1 else ''})."


def find_files(query: str, where: str | None) -> str:
    """Names that match, newest first. Several patterns in one walk, comma-separated."""
    base = resolve(where or "~")
    if not base.is_dir():
        raise ToolError(f"{short(base)} isn't a directory I can search")
    patterns = [b.strip() for b in str(query or "").split(",") if b.strip()]
    if not patterns:
        raise ToolError("no pattern was given")
    prepared = [(b.lower(), any(c in b for c in "*?[")) for b in patterns]
    limit = 40

    def matches(name: str) -> bool:
        low = name.lower()
        return any(fnmatch.fnmatch(low, w) if g else w in low for w, g in prepared)

    hits, started, seen, truncated, stack = [], time.monotonic(), 0, False, [base]
    while stack:
        if time.monotonic() - started > WALK_BUDGET or seen > WALK_MAX_ENTRIES:
            truncated = True
            break
        try:
            entries = list(os.scandir(stack.pop()))
        except OSError:
            continue
        for entry in entries:
            seen += 1
            name, path = entry.name, Path(entry.path)
            try:
                is_dir = entry.is_dir(follow_symlinks=False)
            except OSError:
                continue
            if is_sensitive(path) or name.startswith("."):
                continue
            if is_dir:
                if name in PRUNE_DIRS:
                    continue
                stack.append(path)
            if not matches(name):
                continue
            try:
                hits.append((path, entry.stat(follow_symlinks=False), is_dir))
            except OSError:
                continue
            if len(hits) >= limit * 4:
                truncated = True
                stack.clear()
                break
    hits.sort(key=lambda h: h[1].st_mtime, reverse=True)
    hits = hits[:limit]
    if not hits:
        end = ("and stopped early on the time budget, so this is not proof it isn't there"
               if truncated else "and reached the end, so it really isn't there under that name")
        return (f"No matches for {' or '.join(repr(p) for p in patterns)} under {short(base)}. I "
                f"searched it and everything under it, skipping dotfiles and folders like "
                f"node_modules and .git, {end}.")
    rows = [f"{short(p)}\t{'dir' if d else human_size(st.st_size)}\t"
            f"{time.strftime('%Y-%m-%d %H:%M', time.localtime(st.st_mtime))}" for p, st, d in hits]
    head = f"{len(hits)} match(es) under {short(base)}, newest first:" + (
        " (partial — the tree is big)" if truncated else "")
    return outside(head + "\npath\tsize\tmodified\n" + "\n".join(rows), "file names on disk")


def _python_grep(base: Path, pattern: str, glob, limit: int) -> list[str]:
    try:
        rx = re.compile(pattern, re.I)
    except re.error as exc:
        raise ToolError(f"that isn't a valid pattern ({exc})")
    rows, started = [], time.monotonic()
    for current, dirs, files in os.walk(base):
        if time.monotonic() - started > WALK_BUDGET:
            break
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in PRUNE_DIRS]
        for name in files:
            path = Path(current) / name
            if is_sensitive(path) or (glob and not fnmatch.fnmatch(name, glob)):
                continue
            try:
                if path.stat().st_size > 2 * 1024 * 1024:
                    continue
                with path.open("r", encoding="utf-8", errors="ignore") as fh:
                    for n, line in enumerate(fh, 1):
                        if rx.search(line):
                            rows.append(f"{short(path)}:{n}:{line.strip()[:200]}")
                            if len(rows) >= limit:
                                return rows
                            break
            except OSError:
                continue
    return rows


def search_text(pattern: str, where: str | None, glob: str | None = None) -> str:
    """Search inside files, ripgrep when present, Python when not."""
    base = resolve(where or "~")
    pattern = str(pattern or "")
    if not pattern:
        raise ToolError("no pattern was given")
    limit = 40
    if shutil.which("rg"):
        argv = ["rg", "--line-number", "--no-heading", "--color", "never", "--max-filesize", "2M",
                "-m", "3", "--no-messages", "--threads", "4", "-i"]
        if glob:
            argv += ["--glob", glob]
        argv += ["--regexp", pattern, "--", str(base)]
        try:
            out = subprocess.run(argv, capture_output=True, text=True, errors="replace",
                                 timeout=WALK_BUDGET + 4).stdout
        except subprocess.TimeoutExpired:
            out = ""
        rows = []
        for line in out.splitlines():
            if is_sensitive(Path(line.split(":", 1)[0])):
                continue    # never surface a hit inside a credential file
            rows.append(line.replace(str(common.HOME), "~", 1)[:300])
            if len(rows) >= limit:
                break
    else:
        rows = _python_grep(base, pattern, glob, limit)
    if not rows:
        return f"No occurrences of '{pattern}' under {short(base)}."
    return f"Occurrences of '{pattern}' under {short(base)} (path:line:text):\n" + outside(
        clip("\n".join(rows)), "file contents on disk")
