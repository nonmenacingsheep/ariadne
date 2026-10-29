"""Her general tools (DESIGN §4): the machine in general, beyond any one app.

`GeneralTools` is a toolset: `tools()` lists the definitions, `await call(name,
args, his_words)` runs one and returns text, or a list of content blocks when
there's a picture to hand back. Conversation(toolsets=[...]) merges toolsets
with the adapter verbs every turn and routes calls; other toolsets (memory,
later) plug in the same way. Optional extras the loop honours when present:
`context() -> str` (appended to the system prompt) and `rounds() -> int`
(a bigger tool-round allowance for the turn).

Everything read from outside (pages, search results, files, command output)
comes back quoted and redacted; see common.outside.
"""
from __future__ import annotations

import asyncio

from ...adapters import AdapterError
from . import files, operate, project, shell, web, windows
from .common import ToolError, current_project

__all__ = ["GeneralTools", "ToolError", "Toolset"]

ROUNDS = 16


class Toolset:
    """What the loop expects of a toolset (duck-typed; subclassing is optional)."""

    def tools(self) -> list[dict]:
        raise NotImplementedError

    async def call(self, name: str, args: dict, his_words: str | None = None):
        raise NotImplementedError

    def context(self) -> str:
        return ""

    def rounds(self) -> int | None:
        return None


def _s(desc: str, **extra) -> dict:
    return {"type": "string", "description": desc, **extra}


def _tool(name: str, desc: str, props: dict, required: list[str]) -> dict:
    return {"name": name, "description": desc,
            "input_schema": {"type": "object", "properties": props, "required": required}}


TOOLS = [
    _tool("shell", "Run a shell command on his machine (bash, 20s limit). Output is trimmed. background=true "
          "starts it detached with a log, for builds, installs, downloads and servers. Never destructive "
          "without asking, never anything with credentials. Prefer the file and search tools where they fit.",
          {"command": _s("The command."),
           "background": {"type": "boolean", "description": "Detach it; output goes to a log."},
           "cwd": _s("Folder to run in (default: the open project, else home).")}, ["command"]),
    _tool("read_file", "Read a text file with line numbers (200 lines at a time), or list a folder.",
          {"path": _s("File or folder."), "lines": _s("Range like '40-90', or a start line.")}, ["path"]),
    _tool("write_file", "Create a file (refuses if it exists unless mode overwrite or append). Home and /tmp only.",
          {"path": _s("Where."), "text": _s("The content."),
           "mode": _s("create (default), overwrite or append.", enum=["create", "overwrite", "append"])},
          ["path", "text"]),
    _tool("edit_file", "Replace one exact passage in a file. The passage must match exactly (read_file first) "
          "and be unique unless replace_all.",
          {"path": _s("The file."), "old": _s("Exact text to replace."), "new": _s("Replacement."),
           "replace_all": {"type": "boolean"}}, ["path", "old", "new"]),
    _tool("find_files", "Find files and folders by name under a folder, newest first. Comma-separate several "
          "patterns; * and ? work, otherwise it's a substring.",
          {"query": _s("Name pattern(s)."), "where": _s("Folder (default home).")}, ["query"]),
    _tool("search_text", "Search inside files for a regex; returns path:line:text.",
          {"pattern": _s("Regex, case-insensitive."), "where": _s("Folder (default home)."),
           "glob": _s("Only files matching, e.g. *.py.")}, ["pattern"]),
    _tool("web_search", "Search the web: titles, addresses and snippets. Use plain words, three or four.",
          {"query": _s("What to look for."), "recent": _s("Only the last day, week, month or year.",
                                                          enum=["", "day", "week", "month", "year"]),
           "site": _s("Only this site, e.g. docs.python.org.")}, ["query"]),
    _tool("read_page", "Fetch a web page (or PDF) and read its text. Public addresses only. Long pages: "
          "carry on with offset.",
          {"url": _s("An http or https address."), "offset": {"type": "integer"}}, ["url"]),
    _tool("look", "Look at his screen. what: empty for the whole desktop, a monitor name (DP-2), part of a "
          "window's title or app name, or 'area' to let him drag a selection. You actually see the picture.",
          {"what": _s("What to look at.")}, []),
    _tool("place_window", "Put a window somewhere: left, right, top, bottom, a corner, centre, full, left/middle/"
          "right third, a monitor name, 'other' (the other monitor), or both ('left on DP-2').",
          {"window": _s("Part of its title or app name."), "where": _s("Where.")}, ["window", "where"]),
    _tool("window_control", "Do a job in an app's window with the mouse and keyboard, for apps with no other way "
          "in (a game, a launcher, a settings dialog). By control name where the app allows, else by looking "
          "and clicking. Stops if he touches the mouse, at logins and passwords, and at anything that deletes, "
          "spends or sends. Slow; use an API or command when one exists.",
          {"window": _s("Part of its title or app name."), "task": _s("The job, in plain words."),
           "steps": {"type": "integer", "description": "Most actions (default 16)."}}, ["window", "task"]),
    _tool("todo", "Your task list for a job of several steps. op: list, add, start (one at a time), done, "
          "remove, clear. item is a number or some of its words.",
          {"op": _s("The operation.", enum=list(project.OPS)), "item": _s("The item.")}, ["op"]),
    _tool("open_project", "Open a folder as the project you're building (a game, an app, a site): writing and "
          "editing files there is the job, with more steps a turn and your task list shown every turn.",
          {"path": _s("The folder."), "create": {"type": "boolean", "description": "Make it if missing."}},
          ["path"]),
]


class GeneralTools(Toolset):
    def tools(self) -> list[dict]:
        return [dict(t) for t in TOOLS]

    def context(self) -> str:
        return project.context()

    def rounds(self) -> int:
        return project.ROUNDS_IN_PROJECT if current_project() else ROUNDS

    async def call(self, name: str, args: dict, his_words: str | None = None):
        a = args or {}
        run = self._runner(name, a, his_words)
        if run is None:
            raise AdapterError(f"I have no tool called {name!r}")
        # All of it blocks (disk, subprocesses, D-Bus): off the event loop.
        return await asyncio.to_thread(run)

    @staticmethod
    def _runner(name: str, a: dict, his_words: str | None):
        g = a.get
        table = {
            "shell": lambda: shell.run(g("command"), bool(g("background")), g("cwd"), his_words),
            "read_file": lambda: files.read_file(g("path"), g("lines")),
            "write_file": lambda: files.write_file(g("path"), g("text"), g("mode"), his_words),
            "edit_file": lambda: files.edit_file(g("path"), g("old"), g("new"), bool(g("replace_all")), his_words),
            "find_files": lambda: files.find_files(g("query"), g("where")),
            "search_text": lambda: files.search_text(g("pattern"), g("where"), g("glob")),
            "web_search": lambda: web.web_search(g("query"), g("recent") or "", g("site") or ""),
            "read_page": lambda: web.read_page(g("url"), g("offset") or 0),
            "look": lambda: windows.look(g("what")),
            "place_window": lambda: windows.place_window(g("window"), g("where")),
            "window_control": lambda: operate.window_control(g("window"), g("task"), g("steps"), his_words),
            "todo": lambda: project.todo(g("op"), g("item")),
            "open_project": lambda: project.open_project(g("path"), bool(g("create")), his_words),
        }
        return table.get(name)
