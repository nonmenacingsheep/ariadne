"""Keeping Ariadne up to date from her GitHub repository.

Ariadne runs straight from a git checkout, so updating means fetching and
fast-forwarding to what the remote has. It only ever fast-forwards: if this
checkout has local edits or commits the remote doesn't (a working copy he or
Claude is developing in), it says so and leaves it alone. It never merges,
rebases, resets or stashes.

The running app keeps the code it started with; after an update the desk shows
a Restart button (bin/ariadne2 replaces the running instance).

Settings (General): check_updates (on), auto_update (install when found, on),
check_now (an action).
"""
from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import time
from pathlib import Path

log = logging.getLogger("ariadne2.updater")

REPO = Path(__file__).resolve().parents[2]
# Where a ZIP download (no git history) is linked to, so it can update too.
REPO_URL = "https://github.com/nonmenacingsheep/ariadne.git"
FIRST_CHECK = 90.0                 # after start: let her come up first
EVERY = 6 * 3600.0
GIT_TIMEOUT = 60.0


async def _git(root: Path, *args: str) -> tuple[int, str]:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}        # never wait on a password prompt
    try:
        proc = await asyncio.create_subprocess_exec(
            "git", "-C", str(root), *args, env=env, stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        out, _ = await asyncio.wait_for(proc.communicate(), GIT_TIMEOUT)
        return proc.returncode, out.decode(errors="replace").strip()
    except (OSError, asyncio.TimeoutError) as e:
        return 1, str(e)


class Updater:
    def __init__(self, publish, root: Path = REPO, git=_git, settings=None, spawn=subprocess.Popen) -> None:
        self.publish = publish
        self.root = root
        self.git = git
        self.settings = settings
        self.spawn = spawn
        self.state: dict = {"status": "unchecked"}
        self.restart_needed = False
        self._lock = asyncio.Lock()
        self._task: asyncio.Task | None = None

    def _want(self, key: str, default: bool = True) -> bool:
        try:
            return bool(self.settings.get("general", key)) if self.settings else default
        except Exception:
            return default

    async def _say(self, **state) -> dict:
        state["restart"] = self.restart_needed
        state["checked"] = int(time.time())
        self.state = state
        await self.publish({"t": "update", **state})
        return state

    async def check(self, install: bool | None = None) -> dict:
        """Fetch, compare, and fast-forward when allowed. Returns (and publishes) the state."""
        install = self._want("auto_update") if install is None else install
        async with self._lock:
            git, root = self.git, self.root
            code, top = await git(root, "rev-parse", "--show-toplevel")
            unborn = (await git(root, "rev-parse", "--verify", "-q", "HEAD"))[0] != 0
            if code or Path(top).resolve() != root.resolve() or unborn:
                return await self._adopt(install)
            code, branch = await git(root, "rev-parse", "--abbrev-ref", "HEAD")
            if code or branch == "HEAD":
                return await self._say(status="not on a branch")
            code, upstream = await git(root, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}")
            if code:
                return await self._say(status="no remote")
            remote = upstream.split("/", 1)[0]
            code, out = await git(root, "fetch", "--quiet", remote)
            if code:
                log.info("update check: fetch failed: %s", out[:200])
                return await self._say(status="offline")
            code, counts = await git(root, "rev-list", "--left-right", "--count", f"HEAD...{upstream}")
            try:
                ahead, behind = (int(x) for x in counts.split())
            except ValueError:
                return await self._say(status="error")
            code, log_out = await git(root, "log", "--format=%s", "-n", "6", f"HEAD..{upstream}")
            commits = [line for line in log_out.splitlines() if line][:6] if behind else []
            if not behind:
                return await self._say(status="up to date", ahead=ahead)
            if ahead:
                return await self._say(status="diverged", behind=behind, ahead=ahead, commits=commits)
            code, dirty = await git(root, "status", "--porcelain", "--untracked-files=no")
            if dirty:
                return await self._say(status="local changes", behind=behind, commits=commits)
            if not install:
                return await self._say(status="available", behind=behind, commits=commits)
            code, before = await git(root, "rev-parse", "HEAD")
            code, out = await git(root, "merge", "--ff-only", "--quiet", upstream)
            if code:
                log.warning("update failed: %s", out[:300])
                return await self._say(status="failed", behind=behind, commits=commits)
            await self._packages(before)
            self.restart_needed = True
            log.info("updated %d commit(s) from %s", behind, upstream)
            return await self._say(status="updated", behind=behind, commits=commits)

    async def _packages(self, before: str) -> None:
        """An update that changed requirements.txt installs them into the
        install.sh environment (.venv), if there is one."""
        pip = self.root / ".venv" / "bin" / "python"
        if before != "HEAD":
            code, changed = await self.git(self.root, "diff", "--name-only", before, "HEAD")
            if code or "requirements.txt" not in changed.split():
                return
        if not pip.exists():
            return
        try:
            proc = await asyncio.create_subprocess_exec(
                str(pip), "-m", "pip", "install", "-q", "-r", str(self.root / "requirements.txt"),
                stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
            _, err = await asyncio.wait_for(proc.communicate(), 900)
            if proc.returncode:
                log.warning("update: pip failed: %s", err.decode(errors="replace")[-300:])
        except (OSError, asyncio.TimeoutError) as e:
            log.warning("update: couldn't install packages: %s", e)

    async def _adopt(self, install: bool) -> dict:
        """A folder with no git history (downloaded as a ZIP): make it a checkout
        of the GitHub repo, so it can update like a clone. Only tracked files
        are ever replaced; .venv, models and anything else of theirs stay."""
        git, root = self.git, self.root
        if not (root / "ariadne2").is_dir() or not (root / "bin" / "ariadne2").exists():
            return await self._say(status="not a git checkout")
        url = os.environ.get("ARIADNE2_REPO", REPO_URL)
        made = not (root / ".git").exists()
        if made:
            code, out = await git(root, "init", "-q")
            if code:
                return await self._say(status="not a git checkout")
            await git(root, "symbolic-ref", "HEAD", "refs/heads/master")
        if (await git(root, "remote", "get-url", "origin"))[0]:
            await git(root, "remote", "add", "origin", url)
        code, out = await git(root, "fetch", "--quiet", "origin", "master")
        if code:
            log.info("adopting this download: fetch failed: %s", out[:200])
            return await self._say(status="offline")
        await git(root, "reset", "-q", "origin/master")            # history now; files untouched
        await git(root, "branch", "-q", "--set-upstream-to=origin/master", "master")
        code, differ = await git(root, "status", "--porcelain", "--untracked-files=no")
        log.info("this download is now a git checkout of %s", url)
        if not differ:
            return await self._say(status="up to date", ahead=0)
        commits = ["This download is older than GitHub's version"]
        if not install:
            if made:      # only reporting: undo the link, or the next check would think it's current
                import shutil
                shutil.rmtree(root / ".git", ignore_errors=True)
            return await self._say(status="available", behind=1, commits=commits)
        code, out = await git(root, "checkout", "-q", "-f", "master")
        if code:
            log.warning("update failed: %s", out[:300])
            return await self._say(status="failed", behind=1, commits=commits)
        await self._packages("HEAD")                               # always worth a pip pass here
        self.restart_needed = True
        return await self._say(status="updated", behind=1, commits=commits)

    def restart(self) -> None:
        """Start Ariadne again; bin/ariadne2 stops this instance first."""
        self.spawn([str(self.root / "bin" / "ariadne2")], cwd=str(self.root), start_new_session=True,
                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    async def on_desk(self, msg: dict) -> None:
        op = msg.get("op")
        if op == "check":
            await self.check()
        elif op == "install":
            await self.check(install=True)
        elif op == "restart":
            self.restart()
        elif op == "hello":
            await self.publish({"t": "update", **self.state})

    async def loop(self) -> None:
        await asyncio.sleep(FIRST_CHECK)
        while True:
            if self._want("check_updates"):
                try:
                    await self.check()
                except Exception:
                    log.exception("update check failed")
            await asyncio.sleep(EVERY)

    def start(self) -> None:
        self._task = asyncio.ensure_future(self.loop())

    def stop(self) -> None:
        if self._task:
            self._task.cancel()
