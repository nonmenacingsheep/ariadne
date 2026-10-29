import asyncio
import os
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

from ariadne2.adapters import AdapterError, dolphin as dol, dolphin_files as df
from ariadne2.adapters.dolphin_files import Guard, PathRefused, Recents

B = 1_900_000_000                # later than every date in the sample xbel

XBEL = """<?xml version="1.0" encoding="UTF-8"?>
<xbel version="1.0" xmlns:bookmark="http://www.freedesktop.org/standards/desktop-bookmarks"
      xmlns:mime="http://www.freedesktop.org/standards/shared-mime-info">
  <bookmark href="file://{home}/Pictures/a%20cat.png" added="2026-08-26T20:24:12.900000Z"
            modified="2026-08-26T20:24:16.561000Z" visited="2026-08-26T20:24:16.561000Z"><info/></bookmark>
  <bookmark href="file://{vhome}/Downloads/song.mp3" added="2026-08-27T10:00:00Z"
            modified="2026-08-27T10:00:00Z" visited="2026-08-27T10:00:00Z"/>
  <bookmark href="steam://rungameid/1486350" added="2026-09-01T10:00:00Z"/>
  <bookmark href="file://{home}/Downloads/gone.zip" added="2026-09-02T10:00:00Z"/>
  <bookmark href="file://{home}/.config/secret.conf" added="2026-09-03T10:00:00Z"/>
  <bookmark href="file://{home}/Documents/notes.txt" added="2026-08-28T10:00:00Z"/>
</xbel>"""


def touch(path: Path, data: str = "x", age: float = 3600) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data)
    t = time.time() - age
    os.utime(path, (t, t))
    return path


class Tmp(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.addCleanup(self._t.cleanup)
        self.root = Path(os.path.realpath(self._t.name))
        self.home = self.root / "home"
        self.mnt = self.root / "mnt"
        self.home.mkdir()
        (self.mnt / "games").mkdir(parents=True)
        self.guard = Guard(self.home, self.mnt)


class KindTests(unittest.TestCase):
    def test_kinds(self):
        for name, kind in [("a.PNG", "image"), ("b.flac", "audio"), ("c.mkv", "video"), ("d.pdf", "doc"),
                           ("e.tar.gz", "archive"), ("f.py", "code"), ("g.sha512sum", "other"),
                           ("noext", "other"), ("x.AppImage", "other")]:
            self.assertEqual(df.kind_of(name), kind, name)

    def test_sort_folders(self):
        self.assertEqual(df.sort_folder("x.AppImage"), "Installers")
        self.assertEqual(df.sort_folder("x.deb"), "Installers")
        self.assertEqual(df.sort_folder("x.png"), "Images")
        self.assertEqual(df.sort_folder("x.py"), "Other")
        self.assertEqual(df.sort_folder("x.zip"), "Archives")
        self.assertTrue(df.is_partial("movie.mp4.crdownload"))
        self.assertFalse(df.is_partial("movie.mp4"))


class GuardTests(Tmp):
    def test_inside_ok_outside_refused(self):
        touch(self.home / "Downloads/a.txt")
        self.assertEqual(self.guard.resolve(self.home / "Downloads/a.txt"), self.home / "Downloads/a.txt")
        for bad in ("/etc/passwd", "/tmp", str(self.home / ".." / "etc")):
            with self.assertRaises(PathRefused):
                self.guard.resolve(bad)

    def test_relative_means_under_home(self):
        touch(self.home / "Downloads/a.txt")
        self.assertEqual(self.guard.resolve("Downloads/a.txt"), self.home / "Downloads/a.txt")

    def test_hidden_inside_refused_but_named_exactly_ok_to_read(self):
        (self.home / ".config/app").mkdir(parents=True)
        with self.assertRaises(PathRefused):
            self.guard.resolve(self.home / ".config/app")
        self.assertEqual(self.guard.resolve(self.home / ".config"), self.home / ".config")
        with self.assertRaises(PathRefused):                    # but never to move or trash a config dir
            self.guard.resolve(self.home / ".config", write=True)

    def test_hidden_file_named_exactly_can_be_changed(self):
        touch(self.home / ".note")
        self.assertEqual(self.guard.resolve(self.home / ".note", write=True), self.home / ".note")

    def test_credentials_refused(self):
        touch(self.home / "Vaults/API Keys/openai.txt")
        touch(self.home / "Downloads/id_rsa")
        for p in ("Vaults/API Keys/openai.txt", "Vaults/API Keys", "Downloads/id_rsa"):
            with self.assertRaises(PathRefused):
                self.guard.resolve(p)

    def test_roots_cannot_be_moved_or_trashed(self):
        for p in (self.home, self.mnt, self.mnt / "games"):
            with self.assertRaises(PathRefused):
                self.guard.resolve(p, write=True)
        self.assertEqual(self.guard.resolve(self.mnt / "games"), self.mnt / "games")       # reading is fine

    def test_symlink_out_is_refused_but_the_link_itself_can_be_trashed(self):
        link = self.home / "out"
        link.symlink_to("/etc")
        self.assertEqual(self.guard.resolve(link, write=True), link)
        with self.assertRaises(PathRefused):
            self.guard.resolve(link / "passwd")

    def test_missing_and_empty(self):
        with self.assertRaises(PathRefused):
            self.guard.resolve(self.home / "nope")
        with self.assertRaises(PathRefused):
            self.guard.resolve("  ")
        self.assertEqual(self.guard.resolve(self.home / "nope", must_exist=False), self.home / "nope")

    def test_host_spelling(self):
        self.assertEqual(self.guard.local("/var/home/x/y"), "/home/x/y")
        self.assertEqual(self.guard.local("file:///var/mnt/games/a%20b"), "/var/mnt/games/a b")


class RecentTests(Tmp):
    def make(self, xbel=True):
        home = str(self.home)
        for f in ("Pictures/a cat.png", "Downloads/song.mp3", "Documents/notes.txt", ".config/secret.conf"):
            touch(self.home / f)
        self.xbel = self.root / "recently-used.xbel"
        if xbel:
            self.xbel.write_text(XBEL.format(home=home, vhome=home))
        self.db = self.root / "kact.db"
        con = sqlite3.connect(self.db)
        con.execute("CREATE TABLE ResourceScoreCache (usedActivity TEXT, initiatingAgent TEXT, "
                    "targettedResource TEXT, scoreType INT, cachedScore REAL, firstUpdate INT, lastUpdate INT)")
        for path, agent, when in [(str(self.home / "Downloads"), "org.kde.dolphin", B + 300),
                                  (str(self.home / "Pictures"), "org.kde.dolphin", B + 200),
                                  (str(self.home / "Gone"), "org.kde.dolphin", B + 900),
                                  (str(self.home / ".config"), "org.kde.dolphin", B + 800),
                                  (str(self.home / "Documents/notes.txt"), "org.kde.kate", B + 999),
                                  ("/etc", "org.kde.dolphin", B + 950)]:
            con.execute("INSERT INTO ResourceScoreCache VALUES ('a', ?, ?, 0, 1, 1, ?)", (agent, path, when))
        con.commit()
        con.close()
        return Recents(self.guard, xbel=self.xbel, docs=self.root / "RecentDocuments", activity_db=self.db)

    def test_parse_xbel(self):
        rows = df.parse_xbel(XBEL.format(home="/h", vhome="/vh"))
        paths = [p for p, _ in rows]
        self.assertIn("/h/Pictures/a cat.png", paths)             # percent-decoded
        self.assertNotIn("steam://rungameid/1486350", " ".join(paths))
        self.assertTrue(all(w > 0 for _, w in rows))
        self.assertEqual(df.parse_xbel("<broken"), [])

    def test_files_exist_visible_guarded_newest_first(self):
        files = self.make().files()
        names = {f["name"]: f for f in files}
        self.assertEqual(set(names), {"a cat.png", "song.mp3", "notes.txt"})     # gone.zip and dotfile out
        self.assertEqual(names["a cat.png"]["kind"], "image")
        self.assertEqual(names["song.mp3"]["kind"], "audio")
        self.assertEqual(names["notes.txt"]["kind"], "doc")
        self.assertEqual([f["when"] for f in files], sorted((f["when"] for f in files), reverse=True))
        self.assertEqual(set(files[0]), {"path", "name", "when", "kind"})

    def test_folders_from_activity_history(self):
        folders = self.make().folders()
        self.assertEqual([f["name"] for f in folders][:2], ["Downloads", "Pictures"])   # by recency
        self.assertNotIn("Gone", [f["name"] for f in folders])                         # missing
        self.assertNotIn(".config", [f["name"] for f in folders])                      # hidden
        self.assertNotIn("etc", [f["name"] for f in folders])                          # outside
        self.assertEqual(folders[0]["when"], B + 300)
        self.assertEqual(set(folders[0]), {"path", "name", "when"})

    def test_folders_fall_back_to_where_recent_files_sit(self):
        r = self.make()
        os.unlink(self.db)
        names = [f["name"] for f in r.folders()]
        self.assertIn("Documents", names)

    def test_nothing_readable_is_empty(self):
        r = Recents(self.guard, xbel=self.root / "no", docs=self.root / "no2", activity_db=self.root / "no3")
        self.assertEqual((r.files(), r.folders()), ([], []))

    def test_recent_documents_desktop_files(self):
        touch(self.home / "Documents/old.odt")
        d = self.root / "RecentDocuments"
        d.mkdir()
        (d / "old.desktop").write_text(f"[Desktop Entry]\nURL=file://{self.home}/Documents/old.odt\n")
        r = Recents(self.guard, xbel=self.root / "no", docs=d, activity_db=self.root / "no3")
        self.assertEqual([f["name"] for f in r.files()], ["old.odt"])


class SortTests(Tmp):
    def fill(self):
        d = self.home / "Downloads"
        for n in ("a.png", "b.mp3", "c.mkv", "d.pdf", "e.zip", "f.AppImage", "g.xyz", "h.py"):
            touch(d / n)
        touch(d / ".hidden.png")
        touch(d / "movie.mp4.crdownload")
        touch(d / "fresh.png", age=2)
        touch(d / "passwords.csv")
        (d / "Some Folder").mkdir()
        (d / "link.png").symlink_to(d / "a.png")
        return d

    def test_plan(self):
        d = self.fill()
        moves, notes = df.sort_plan(d)
        got = {s.name: (dst.parent.name, dst.name) for s, dst in moves}
        self.assertEqual(got, {"a.png": ("Images", "a.png"), "b.mp3": ("Audio", "b.mp3"),
                               "c.mkv": ("Video", "c.mkv"), "d.pdf": ("Documents", "d.pdf"),
                               "e.zip": ("Archives", "e.zip"), "f.AppImage": ("Installers", "f.AppImage"),
                               "g.xyz": ("Other", "g.xyz"), "h.py": ("Other", "h.py")})
        self.assertTrue(any("1 file" in n for n in notes))              # fresh.png held back
        self.assertEqual(len(os.listdir(d)), 14)                       # planning moved nothing

    def test_collision_gets_a_number_never_overwrites(self):
        d = self.home / "Downloads"
        touch(d / "a.png", "new")
        touch(d / "Images/a.png", "old")
        touch(d / "Images/a (2).png", "older")
        moves, _ = df.sort_plan(d)
        self.assertEqual(moves[0][1].name, "a (3).png")

    def test_file_named_like_a_folder_is_left(self):
        d = self.home / "Downloads"
        touch(d / "Images", "I am a file")
        touch(d / "a.png")
        moves, _ = df.sort_plan(d)
        self.assertEqual([(s.name, dst.parent.name) for s, dst in moves], [("Images", "Other")])   # a.png stays

    def test_project_folder_refused(self):
        d = self.home / "proj"
        touch(d / "a.png")
        (d / ".git").mkdir()
        with self.assertRaises(PathRefused):
            df.sort_plan(d)

    def test_cap(self):
        d = self.home / "Downloads"
        for i in range(df.SORT_MAX + 5):
            touch(d / f"f{i}.txt")
        moves, notes = df.sort_plan(d)
        self.assertEqual(len(moves), df.SORT_MAX)
        self.assertTrue(any("5 more" in n for n in notes))


class AdapterBase(Tmp, unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        super().setUp()
        self.sent = []
        self.trashed = []
        self.opened = []
        self.events = []

        async def publish(m):
            self.sent.append(m)

        async def trasher(p):
            self.trashed.append(p)

        async def opener(p):
            self.opened.append(p)

        async def nodbus(*a, **k):
            return 1, ""
        self.dbus = nodbus
        (self.home / "Downloads").mkdir()
        self.recents = Recents(self.guard, xbel=self.root / "x", docs=self.root / "d", activity_db=self.root / "db")
        self.a = dol.DolphinAdapter(publish, guard=self.guard, recents=self.recents, trasher=trasher,
                                    opener=opener, dbus=nodbus)
        self.a.subscribe(lambda name, f: self.events.append((name, f)))

    def phases(self):
        return [(m["phase"], m.get("note")) for m in self.sent if m["t"] == "action"]


class VerbTests(AdapterBase):
    async def test_sort_end_to_end_with_progress(self):
        d = touch(self.home / "Downloads/a.png").parent
        touch(d / "b.pdf")
        touch(d / "c.png")
        out = await self.a.run("sort", {"folder": str(d)})
        self.assertTrue((d / "Images/a.png").exists() and (d / "Images/c.png").exists())
        self.assertTrue((d / "Documents/b.pdf").exists())
        self.assertFalse((d / "a.png").exists())
        self.assertIn("3 moved", out)
        self.assertIn("Images 2", out)
        ph = self.phases()
        self.assertEqual(ph[0], ("started", None))
        self.assertEqual(ph[-1], ("done", None))
        self.assertEqual(sorted(n for p, n in ph if p == "progress"), ["a.png", "b.pdf", "c.png"])
        self.assertEqual({m["id"] for m in self.sent if m["t"] == "action"}.__len__(), 1)
        self.assertEqual({m["control"] for m in self.sent if m["t"] == "action"}, {"sort"})

    async def test_sort_nothing(self):
        (self.home / "Empty").mkdir()
        self.assertIn("Nothing to sort", await self.a.run("sort", {"folder": str(self.home / "Empty")}))

    async def test_sort_refusals(self):
        for bad in ("/etc", str(self.home), str(self.home / "nope")):
            with self.assertRaises(AdapterError):
                await self.a.run("sort", {"folder": bad})
        touch(self.home / "f.txt")
        with self.assertRaises(AdapterError):
            await self.a.run("sort", {"folder": str(self.home / "f.txt")})

    async def test_move_into_folder_and_rename(self):
        touch(self.home / "a.txt")
        (self.home / "Docs").mkdir()
        await self.a.run("move", {"src": str(self.home / "a.txt"), "dest": str(self.home / "Docs")})
        self.assertTrue((self.home / "Docs/a.txt").exists())
        await self.a.run("move", {"src": str(self.home / "Docs/a.txt"), "dest": str(self.home / "b.txt")})
        self.assertTrue((self.home / "b.txt").exists())
        self.assertIn(("progress", "a.txt"), self.phases())

    async def test_move_creates_folder_when_asked_with_slash(self):
        touch(self.home / "a.txt")
        await self.a.run("move", {"src": str(self.home / "a.txt"), "dest": str(self.home / "New/Place") + "/"})
        self.assertTrue((self.home / "New/Place/a.txt").exists())

    async def test_move_never_overwrites_and_never_into_itself(self):
        touch(self.home / "a.txt", "mine")
        touch(self.home / "b.txt", "theirs")
        with self.assertRaisesRegex(AdapterError, "already exists"):
            await self.a.run("move", {"src": str(self.home / "a.txt"), "dest": str(self.home / "b.txt")})
        self.assertEqual((self.home / "b.txt").read_text(), "theirs")
        (self.home / "dir").mkdir()
        with self.assertRaisesRegex(AdapterError, "into itself"):
            await self.a.run("move", {"src": str(self.home / "dir"), "dest": str(self.home / "dir/sub") + "/"})
        with self.assertRaisesRegex(AdapterError, "doesn't exist"):
            await self.a.run("move", {"src": str(self.home / "a.txt"), "dest": str(self.home / "no/such/x.txt")})

    async def test_move_outside_refused_and_nothing_moved(self):
        touch(self.home / "a.txt")
        for src, dest in [(str(self.home / "a.txt"), "/tmp/a.txt"), ("/etc/hostname", str(self.home / "h"))]:
            with self.assertRaises(AdapterError):
                await self.a.run("move", {"src": src, "dest": dest})
        self.assertTrue((self.home / "a.txt").exists())
        self.assertEqual([m["phase"] for m in self.sent if m["t"] == "action" and m["phase"] == "done"], [])

    async def test_trash_uses_the_trasher_and_reports(self):
        f = touch(self.home / "a.txt")
        out = await self.a.run("trash", {"path": str(f)})
        self.assertEqual(self.trashed, [f])
        self.assertIn("trash", out)
        self.assertIn(("progress", "a.txt"), self.phases())
        self.assertTrue(f.exists())                    # the fake did nothing: only the trasher removes

    async def test_trash_refusals(self):
        for bad in ("/etc/hostname", str(self.home), str(self.mnt), str(self.home / ".config")):
            (self.home / ".config").mkdir(exist_ok=True)
            with self.assertRaises(AdapterError):
                await self.a.run("trash", {"path": bad})
        self.assertEqual(self.trashed, [])

    async def test_trasher_failure_is_failed_not_done(self):
        async def broken(p):
            raise AdapterError("gio said no")
        self.a._trash = broken
        f = touch(self.home / "a.txt")
        with self.assertRaises(AdapterError):
            await self.a.run("trash", {"path": str(f)})
        self.assertEqual(self.phases()[-1][0], "failed")

    async def test_open_goes_to_opener_and_press_is_silent(self):
        f = touch(self.home / "Pictures/a.png")
        await self.a.run("open", {"path": str(f)})
        self.assertEqual(self.opened, [f])
        self.sent.clear()
        await self.a.press("open", str(self.home / "Pictures"))
        self.assertEqual(self.opened[-1], self.home / "Pictures")
        self.assertEqual(self.sent, [])
        with self.assertRaises(AdapterError):
            await self.a.press("open", None)
        with self.assertRaises(AdapterError):
            await self.a.run("open", {"path": "/etc/passwd"})

    async def test_list(self):
        d = self.home / "Docs"
        touch(d / "a.txt")
        touch(d / "b.png")
        touch(d / ".hid")
        touch(d / "passwords.txt")
        (d / "sub").mkdir()
        out = await self.a.run("list", {"folder": str(d)})
        self.assertIn("1 folders, 2 files", out)
        self.assertIn("2 hidden or private", out)
        self.assertLess(out.index("sub/"), out.index("a.txt"))
        self.assertIn("a.txt (doc,", out)
        self.assertNotIn("passwords", out)
        with self.assertRaises(AdapterError):
            await self.a.run("list", {"folder": str(d / "a.txt")})

    async def test_find(self):
        touch(self.home / "Docs/Report Final.pdf")
        touch(self.home / "Docs/deep/er/report notes.txt")
        touch(self.home / "Docs/.hidden/report.txt")
        touch(self.mnt / "games/Saves/report-game.sav")
        touch(self.home / "Vaults/API Keys/report.txt")
        out = await self.a.run("find", {"query": "REPORT"})
        self.assertIn("Report Final.pdf", out)
        self.assertIn("report notes.txt", out)
        self.assertIn("report-game.sav", out)
        self.assertNotIn(".hidden", out)
        self.assertNotIn("API Keys", out)
        self.assertLess(out.index("Report Final"), out.index("report notes"))        # shallow first
        only = await self.a.run("find", {"query": "report", "where": "games"})
        self.assertIn("report-game.sav", only)
        self.assertNotIn("Report Final", only)
        self.assertIn("0 matches", await self.a.run("find", {"query": "zzzz"}))
        with self.assertRaises(AdapterError):
            await self.a.run("find", {"query": "x", "where": "/etc"})
        with self.assertRaises(AdapterError):
            await self.a.run("find", {"query": " "})

    async def test_find_stops_when_out_of_time(self):
        for i in range(5):
            touch(self.home / f"d{i}/f{i}.txt")
        ticks = iter(range(0, 1000, 10))
        hits, why = df.find_files("f", [self.home], clock=lambda: next(ticks))
        self.assertEqual(why, "ran out of time")

    async def test_schema_and_tools(self):
        names = {v.name for v in self.a.verbs}
        self.assertEqual(names, {"open", "find", "list", "move", "sort", "trash",
                                 "rename", "duplicate", "compress", "extract", "info"})
        self.assertEqual({v.name: v.control for v in self.a.verbs if v.control},
                         {"open": "open", "move": "move", "sort": "sort", "trash": "trash"})
        for v in self.a.verbs:
            self.assertEqual(v.schema()["type"], "object")


class StateAndEventTests(AdapterBase):
    async def test_state_shape(self):
        touch(self.home / "Downloads/a.png")
        await self.a.refresh()
        s = self.a.state()
        self.assertEqual(set(s), {"status", "current", "recent_folders", "recent_files", "watched"})
        self.assertEqual(s["status"], "ok")
        self.assertIsNone(s["current"])
        self.assertEqual(s["watched"], [{"path": str(self.home / "Downloads"), "name": "Downloads", "new": 0}])
        self.assertEqual([m["widget"] for m in self.sent if m["t"] == "state"], ["dolphin"])

    async def test_baseline_then_settled_new_file_fires_once(self):
        d = self.home / "Downloads"
        touch(d / "old.zip")
        await self.a.refresh()
        self.assertEqual(self.events, [])                         # what was there is not news
        touch(d / "new.png", "abc")
        await self.a.refresh()
        self.assertEqual(self.events, [])                         # seen once: might still be growing
        await self.a.refresh()
        self.assertEqual(len(self.events), 1)
        name, f = self.events[0]
        self.assertEqual(name, "dolphin.file_appeared")
        self.assertEqual(f, {"path": str(d / "new.png"), "name": "new.png", "folder": str(d), "kind": "image"})
        await self.a.refresh()
        self.assertEqual(len(self.events), 1)                     # not again
        self.assertEqual(self.a.state()["watched"][0]["new"], 1)

    async def test_growing_file_waits(self):
        d = self.home / "Downloads"
        await self.a.refresh()
        f = touch(d / "big.iso", "a")
        await self.a.refresh()
        f.write_text("aaaa")
        await self.a.refresh()
        self.assertEqual(self.events, [])
        await self.a.refresh()
        self.assertEqual(len(self.events), 1)

    async def test_partial_hidden_and_folders_are_ignored_and_rename_counts(self):
        d = self.home / "Downloads"
        await self.a.refresh()
        touch(d / "x.mp4.crdownload", "zz")
        touch(d / ".hidden")
        (d / "folder").mkdir()
        for _ in range(3):
            await self.a.refresh()
        self.assertEqual(self.events, [])
        os.rename(d / "x.mp4.crdownload", d / "x.mp4")           # the download finished
        for _ in range(2):
            await self.a.refresh()
        self.assertEqual([f["name"] for _, f in self.events], ["x.mp4"])
        self.assertEqual(self.events[0][1]["kind"], "video")

    async def test_deleted_and_recreated_fires_again(self):
        d = self.home / "Downloads"
        touch(d / "a.txt")
        await self.a.refresh()
        os.unlink(d / "a.txt")
        await self.a.refresh()
        touch(d / "a.txt", "different")
        await self.a.refresh()
        await self.a.refresh()
        self.assertEqual(len(self.events), 1)

    async def test_open_or_list_resets_new_count(self):
        d = self.home / "Downloads"
        await self.a.refresh()
        touch(d / "n.txt")
        await self.a.refresh()
        await self.a.refresh()
        self.assertEqual(self.a._watch[d]["new"], 1)
        await self.a.run("list", {"folder": str(d)})
        self.assertEqual(self.a._watch[d]["new"], 0)

    async def test_watch_more_folders_and_guard(self):
        (self.home / "Pics").mkdir()
        self.a.watch([self.home / "Pics", "/etc", self.home / "missing"])
        self.assertEqual(list(self.a._watch), [self.home / "Pics"])         # /etc and missing are dropped
        await self.a.refresh()
        touch(self.home / "Pics/p.png")
        await self.a.refresh()
        await self.a.refresh()
        self.assertEqual([f["folder"] for _, f in self.events], [str(self.home / "Pics")])

    async def test_default_watch_picks_up_downloads_when_it_appears(self):
        import shutil
        shutil.rmtree(self.home / "Downloads")
        self.a._watch_wanted = [self.home / "Downloads"]
        await self.a.refresh()
        self.assertEqual(self.a.state()["watched"], [])
        (self.home / "Downloads").mkdir()
        await self.a.refresh()
        self.assertEqual([w["name"] for w in self.a.state()["watched"]], ["Downloads"])

    async def test_declared_event_info(self):
        self.assertEqual(self.a.events, ("file_appeared",))
        info = self.a.event_info["file_appeared"]
        self.assertEqual(set(info["fields"]), {"path", "name", "folder", "kind"})
        self.assertTrue(info["outside"])        # filenames come from whoever made the file

    async def test_catalog_replaces_the_placeholder(self):
        from ariadne2.core.flows.catalog import Catalog
        cat = Catalog.build({"dolphin": self.a})
        nt = cat.get("dolphin.file_appeared")
        self.assertEqual(nt.kind, "event")
        self.assertTrue(nt.available)
        self.assertEqual({o["name"] for o in nt.outputs}, {"path", "name", "folder", "kind"})
        self.assertIn("dolphin.trash", cat)
        self.assertIn("dolphin.read_state", cat)


class DBusTests(unittest.IsolatedAsyncioTestCase):
    def fake(self, open_urls=(), windows=True):
        calls = []

        async def run(*args, timeout=2.0):
            calls.append(args)
            if args[0] == "list":
                return 0, ("org.kde.dolphin-4242 4242 dolphin user :1.9 - - -\n"
                           "org.freedesktop.FileManager1 4242 dolphin user :1.9 - - -\n"
                           "org.kde.dolphin-77 77 dolphin user :1.10 - - -\n")
            if args[0] == "tree":
                if args[1] == "org.kde.dolphin-4242" and windows:
                    return 0, "/\n/dolphin\n/dolphin/Dolphin_1\n/dolphin/Dolphin_2\n/org/kde/dolphin\n"
                return 0, "/\n/org/kde/dolphin\n"
            if args[0] == "introspect":
                return 0, ("NAME TYPE SIGNATURE RESULT/VALUE FLAGS\norg.kde.dolphin.MainWindow interface - - -\n"
                           ".activateWindow method - - -\n.isUrlOpen method s b -\n"
                           "org.freedesktop.DBus.Properties interface - - -\n.Get method ss v -\n")
            if args[0] == "call":
                url = args[-1]
                return 0, "b true\n" if url in open_urls else "b false\n"
            return 1, ""
        return run, calls

    async def test_windows_found_by_name_and_method(self):
        run, _ = self.fake()
        self.assertEqual(await df.dolphin_windows(run),
                         [("org.kde.dolphin-4242", "/dolphin/Dolphin_1", "org.kde.dolphin.MainWindow"),
                          ("org.kde.dolphin-4242", "/dolphin/Dolphin_2", "org.kde.dolphin.MainWindow")])

    async def test_daemon_with_no_window_is_none(self):
        run, _ = self.fake(windows=False)
        self.assertEqual(await df.dolphin_windows(run), [])

    async def test_first_open_candidate_wins(self):
        run, _ = self.fake(open_urls={"file:///home/x/Pictures", "file:///home/x/Downloads"})
        wins = await df.dolphin_windows(run)
        got = await df.open_folder_among(["/home/x/Documents", "/home/x/Downloads", "/home/x/Pictures"], wins, run)
        self.assertEqual(got, "/home/x/Downloads")
        self.assertIsNone(await df.open_folder_among(["/home/x/Nothing"], wins, run))

    async def test_urls_are_encoded(self):
        self.assertEqual(df.file_url("/home/x/a b/é"), "file:///home/x/a%20b/%C3%A9")

    async def test_adapter_current_comes_from_dbus_and_stays_null_without_windows(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(os.path.realpath(t))
            home = root / "home"
            (home / "Pictures").mkdir(parents=True)
            (home / "Downloads").mkdir()
            guard = Guard(home, root / "mnt")
            db = root / "k.db"
            con = sqlite3.connect(db)
            con.execute("CREATE TABLE ResourceScoreCache (usedActivity TEXT, initiatingAgent TEXT, "
                        "targettedResource TEXT, scoreType INT, cachedScore REAL, firstUpdate INT, lastUpdate INT)")
            for p, w in ((home / "Downloads", 5), (home / "Pictures", 9)):
                con.execute("INSERT INTO ResourceScoreCache VALUES ('a','org.kde.dolphin',?,0,1,1,?)", (str(p), w))
            con.commit()
            con.close()
            rec = Recents(guard, xbel=root / "x", docs=root / "d", activity_db=db)
            sent = []

            async def pub(m):
                sent.append(m)
            run, _ = self.fake(open_urls={f"file://{home}/Downloads"})
            a = dol.DolphinAdapter(pub, guard=guard, recents=rec, dbus=run, watch=[])
            await a.refresh()
            self.assertEqual(a.state()["current"], {"path": str(home / "Downloads"), "name": "Downloads"})
            run2, _ = self.fake(windows=False)
            b = dol.DolphinAdapter(pub, guard=guard, recents=rec, dbus=run2, watch=[])
            await b.refresh()
            self.assertIsNone(b.state()["current"])


if __name__ == "__main__":
    unittest.main()
