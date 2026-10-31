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

    async def test_his_own_file_where_the_update_adds_one_is_kept_aside(self):
        (self.dev / "body.vrm").write_text("aries")
        git(self.dev, "add", "body.vrm"); git(self.dev, "commit", "-m", "ship a body"); git(self.dev, "push", "origin", "main")
        (self.app / "body.vrm").write_text("his own")             # untracked in his copy
        st = await Updater(self.publish, root=self.app).check(install=True)
        self.assertEqual(st["status"], "updated")
        self.assertEqual((self.app / "body.vrm").read_text(), "aries")
        self.assertEqual((self.app / "body.vrm.local-backup").read_text(), "his own")

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


class ZipDownloadTests(unittest.IsolatedAsyncioTestCase):
    """A folder downloaded as a ZIP (no .git) gets linked to the repo and can update."""

    async def asyncSetUp(self):
        import os
        import shutil
        self.tmp = Path(tempfile.mkdtemp())
        self.remote, self.dev = self.tmp / "remote.git", self.tmp / "dev"
        git(self.tmp, "init", "--bare", "-b", "master", str(self.remote))
        git(self.tmp, "clone", str(self.remote), str(self.dev))
        git(self.dev, "checkout", "-b", "master")
        (self.dev / "ariadne2").mkdir(); (self.dev / "bin").mkdir()
        (self.dev / "ariadne2" / "core.py").write_text("v1\n"); (self.dev / "bin" / "ariadne2").write_text("#!/bin/sh\n")
        git(self.dev, "add", "-A"); git(self.dev, "commit", "-m", "v1"); git(self.dev, "push", "origin", "master")
        self.zip = self.tmp / "download"                     # what the ZIP unpacks to: files, no history
        shutil.copytree(self.dev, self.zip, ignore=shutil.ignore_patterns(".git"))
        (self.zip / ".venv").mkdir(); (self.zip / ".venv" / "keep").write_text("theirs")
        os.environ["ARIADNE2_REPO"] = str(self.remote)
        self.addCleanup(os.environ.pop, "ARIADNE2_REPO", None)
        self.env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}

        async def publish(m):
            protocol.decode(protocol.encode(m))
        self.publish = publish

    async def test_a_current_download_is_linked_and_up_to_date(self):
        st = await Updater(self.publish, root=self.zip).check(install=True)
        self.assertEqual(st["status"], "up to date")
        self.assertTrue((self.zip / ".git").is_dir())
        st = await Updater(self.publish, root=self.zip).check(install=True)    # and from now on, a normal clone
        self.assertEqual(st["status"], "up to date")

    async def test_an_older_download_is_brought_up_to_date(self):
        (self.dev / "ariadne2" / "core.py").write_text("v2\n")
        git(self.dev, "commit", "-am", "v2"); git(self.dev, "push", "origin", "master")
        st = await Updater(self.publish, root=self.zip).check(install=False)
        self.assertEqual(st["status"], "available")
        self.assertEqual((self.zip / "ariadne2" / "core.py").read_text(), "v1\n")
        st = await Updater(self.publish, root=self.zip).check(install=True)
        self.assertEqual((st["status"], st["restart"]), ("updated", True))
        self.assertEqual((self.zip / "ariadne2" / "core.py").read_text(), "v2\n")
        self.assertEqual((self.zip / ".venv" / "keep").read_text(), "theirs")   # untracked: untouched
        (self.dev / "ariadne2" / "core.py").write_text("v3\n")
        git(self.dev, "commit", "-am", "v3"); git(self.dev, "push", "origin", "master")
        st = await Updater(self.publish, root=self.zip).check(install=True)     # then ordinary updates
        self.assertEqual((st["status"], st["behind"]), ("updated", 1))

    async def test_a_folder_that_isnt_ariadne_is_left_alone(self):
        other = self.tmp / "other"; other.mkdir()
        st = await Updater(self.publish, root=other).check(install=True)
        self.assertEqual(st["status"], "not a git checkout")
        self.assertFalse((other / ".git").exists())
