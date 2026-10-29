"""todo and open_project: how she builds things.

A project is a folder he has said yes to once; inside it writing files is the
normal way of working, with a longer leash (more tool rounds per turn) and her
task list shown to her every turn. Ported from 1.x project.py. The state is one
small JSON file so a restarted core still knows the project and the list.
"""
from __future__ import annotations

from pathlib import Path

from . import common
from .common import ToolError, audit, need_him, resolve, short

OPS = ("list", "add", "start", "done", "remove", "clear")
MAX_ITEMS = 30
ROUNDS_IN_PROJECT = 40

WORKING = """\
You are in a project: {root}. Work on it the way a careful developer does: read before you change \
anything (find_files, search_text, read_file); change files with edit_file, one exact passage; \
check a change by running it with shell and read what it says: an error is the next thing to fix, \
not something to report and stop at. Keep the task list current with todo, one item started at a \
time. When it works, say so in a line, with how to run it.
Task list:
{todo}"""


def _items() -> list[dict]:
    return [i for i in common.load_state().get("todo", []) if isinstance(i, dict)]


def _save(**changes) -> None:
    state = common.load_state()
    state.update(changes)
    common.save_state(state)


def render(items: list[dict]) -> str:
    mark = {"pending": "[ ]", "doing": "[>]", "done": "[x]"}
    return "\n".join(f"{n}. {mark.get(i['status'], '[ ]')} {i['task']}" for n, i in enumerate(items, 1)) or "(empty)"


def _find(items: list[dict], ref: str) -> int:
    ref = str(ref or "").strip()
    if not ref:
        raise ToolError("say which item: its number, or some of its words")
    if ref.isdigit() and 1 <= int(ref) <= len(items):
        return int(ref) - 1
    hits = [n for n, i in enumerate(items) if ref.lower() in i["task"].lower()]
    if len(hits) != 1:
        raise ToolError(f"{'no item' if not hits else 'more than one item'} matches {ref!r}; the list is:\n{render(items)}")
    return hits[0]


def todo(op: str, item: str | None) -> str:
    op = str(op or "list").lower()
    if op not in OPS:
        raise ToolError(f"op must be one of {', '.join(OPS)}")
    items = _items()
    if op == "add":
        task = " ".join(str(item or "").split())[:160]
        if not task:
            raise ToolError("say what the item is")
        if len(items) >= MAX_ITEMS:
            raise ToolError(f"the list is full ({MAX_ITEMS}); finish or remove some")
        items.append({"task": task, "status": "pending"})
    elif op == "start":
        n = _find(items, item)
        for i in items:                     # one at a time
            if i["status"] == "doing":
                i["status"] = "pending"
        items[n]["status"] = "doing"
    elif op == "done":
        items[_find(items, item)]["status"] = "done"
    elif op == "remove":
        del items[_find(items, item)]
    elif op == "clear":
        items = []
    if op != "list":
        _save(todo=items)
    return "Task list:\n" + render(items)


def open_project(path: str, create: bool, his_words: str | None) -> str:
    """Open a folder as the project. Needs him asking this turn: it widens what she
    does without further asking, so it never happens off a flow's or a file's say-so."""
    where = resolve(path, write=True)
    need_him(his_words, "opening a project")
    if not where.exists():
        if not create:
            raise ToolError(f"{short(where)} doesn't exist; pass create to make it")
        where.mkdir(parents=True)
    if not where.is_dir():
        raise ToolError(f"{short(where)} is a file, not a folder")
    _save(project=str(where), todo=[])
    audit("open_project", {"path": str(where)}, "ok")
    names = sorted(p.name + ("/" if p.is_dir() else "") for p in where.iterdir() if not p.name.startswith("."))[:40]
    return (f"Project open: {short(where)}. Writing and editing files there is the job now, and you "
            f"get up to {ROUNDS_IN_PROJECT} steps a turn. It has: {', '.join(names) or '(empty)'}.\n"
            f"Start with todo for anything longer than a couple of steps.")


def context() -> str:
    """Shown to her every turn while a project is open."""
    root = common.current_project()
    if root is None:
        return ""
    return WORKING.format(root=short(root), todo=render(_items()))
