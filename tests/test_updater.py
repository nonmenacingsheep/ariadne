"""The updater against real git repositories: a bare 'GitHub', a checkout, and a second clone that pushes."""
import asyncio
import subprocess
import tempfile
import unittest
from pathlib import Path

from ariadne2 import protocol
from ariadne2.core.updater import Updater


def git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True,
                   env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                        "GIT_COMMITTER_EMAIL": "t@t", "HOME": str(cwd), "PATH": "/usr/bin:/bin"})


class Settings:
    def __init__(self, **v): self.v = v
    def get(self, section, key): return self.v.get(key, True)


class UpdaterTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.remote, self.app, self.dev = self.tmp / "remote.git", self.tmp / "app", self.tmp / "dev"
        git(self.tmp, "init", "--bare", "-b", "main", str(self.remote))
        git(self.tmp, "clone", str(self.remote), str(self.dev))
        (self.dev / "a.txt").write_text("one\n")
        git(self.dev, "add", "a.txt"); git(self.dev, "commit", "-m", "first"); git(self.dev, "push", "origin", "main")
        git(self.tmp, "clone", str(self.remote), str(self.app))
        self.sent = []

        async def publish(m):
            protocol.decode(protocol.encode(m))
            self.sent.append(m)
        self.publish = publish

    def push(self, subject):
        (self.dev / "a.txt").write_text((self.dev / "a.txt").read_text() + subject + "\n")
        git(self.dev, "commit", "-am", subject); git(self.dev, "push", "origin", "main")

    async def test_up_to_date(self):
        st = await Updater(self.publish, root=self.app).check()
        self.assertEqual(st["status"], "up to date")

    async def test_a_clean_checkout_fast_forwards_and_asks_for_a_restart(self):
        self.push("better ears"); self.push("calmer tail")
        u = Updater(self.publish, root=self.app, settings=Settings(auto_update=True))
        st = await u.check()
        self.assertEqual((st["status"], st["behind"], st["restart"]), ("updated", 2, True))
        self.assertEqual(st["commits"], ["calmer tail", "better ears"])
        self.assertIn("calmer tail", (self.app / "a.txt").read_text())
        self.assertEqual(self.sent[-1]["t"], "update")

    async def test_with_auto_install_off_it_only_says_so(self):
        self.push("new thing")
        st = await Updater(self.publish, root=self.app, settings=Settings(auto_update=False)).check()
        self.assertEqual(st["status"], "available")
        self.assertNotIn("new thing", (self.app / "a.txt").read_text())
        st = await Updater(self.publish, root=self.app).check(install=True)       # the chip's Install
        self.assertEqual(st["status"], "updated")

    async def test_local_edits_are_never_touched(self):
        self.push("remote change")
        (self.app / "a.txt").write_text("my edit\n")
        st = await Updater(self.publish, root=self.app).check()
        self.assertEqual(st["status"], "local changes")
        self.assertEqual((self.app / "a.txt").read_text(), "my edit\n")

    async def test_local_commits_are_never_touched(self):
        self.push("remote change")
        (self.app / "b.txt").write_text("mine\n")
        git(self.app, "add", "b.txt"); git(self.app, "commit", "-m", "mine")
        st = await Updater(self.publish, root=self.app).check()
        self.assertEqual((st["status"], st["ahead"], st["behind"]), ("diverged", 1, 1))
        self.assertTrue((self.app / "b.txt").exists())

    async def test_no_remote_is_quiet(self):
        lone = self.tmp / "lone"
        git(self.tmp, "init", "-b", "main", str(lone))
        (lone / "x").write_text("x"); git(lone, "add", "x"); git(lone, "commit", "-m", "x")
        st = await Updater(self.publish, root=lone).check()
        self.assertEqual(st["status"], "no remote")

    async def test_restart_runs_the_launcher_detached(self):
        calls = []
        u = Updater(self.publish, root=self.app, spawn=lambda argv, **kw: calls.append((argv, kw)))
        await u.on_desk({"op": "restart"})
        self.assertTrue(calls[0][0][0].endswith("bin/ariadne2"))
        self.assertTrue(calls[0][1]["start_new_session"])


if __name__ == "__main__":
    unittest.main()
