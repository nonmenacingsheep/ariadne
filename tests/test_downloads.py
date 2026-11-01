import asyncio
import sqlite3
import tempfile
import unittest
from pathlib import Path

from ariadne2 import protocol
from ariadne2.core.downloads import DownloadWatch


class FakeSteam:
    def state(self):
        return {"downloads": [{"appid": 1091500, "name": "Cyberpunk 2077", "progress": 0.42, "bytes_done": 42,
                               "bytes_total": 100, "rate_bps": 5e6, "state": "downloading"}]}


class Watch(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.dl = self.home / "Downloads"
        self.dl.mkdir()
        self.t = [100.0]
        self.w = DownloadWatch(None, steam=FakeSteam(), home=self.home, clock=lambda: self.t[0])
        self.w.note_tool("steam", {"action": "install", "game": "cyberpunk"})     # she started them

    def ids(self):
        return {i["id"].split("/")[-1] if i["id"].startswith("file:") else i["id"]: i for i in self.w.collect()}

    def test_steam_browser_partial_and_growing_files(self):
        # A Chromium-family browser (Flatpak Opera here) with one download in progress.
        prof = self.home / ".var/app/com.opera.opera-gx/config/opera-gx/Default"
        prof.mkdir(parents=True)
        part = self.dl / "Unconfirmed 123.crdownload"
        part.write_bytes(b"x" * 250)
        con = sqlite3.connect(prof / "History")
        con.execute("CREATE TABLE downloads (current_path TEXT, target_path TEXT, total_bytes INT, state INT)")
        con.execute("INSERT INTO downloads VALUES (?, ?, 1000, 0)", (str(part), str(self.dl / "game.zip")))
        con.execute("INSERT INTO downloads VALUES ('/gone', '/old.zip', 5, 1)")
        con.commit(); con.close()
        (self.dl / "movie.mkv.part").write_bytes(b"x" * 10)            # Firefox: no total known
        done = self.dl / "notes.txt"
        done.write_text("finished long ago")
        grow = self.dl / "big.iso"
        grow.write_bytes(b"x" * 10)

        first = self.ids()
        self.assertEqual(first["steam:1091500"]["progress"], 0.42)
        self.assertEqual(first["Unconfirmed 123.crdownload"]["name"], "game.zip")
        self.assertEqual(first["Unconfirmed 123.crdownload"]["progress"], 0.25)
        self.assertIsNone(first["movie.mkv.part"]["progress"])
        self.assertNotIn("notes.txt", first)
        self.assertNotIn("big.iso", first)                              # not seen growing yet

        self.t[0] += 2
        self.w.note_tool("shell", {"command": "curl -O big.iso"})
        grow.write_bytes(b"x" * 500)
        self.assertIn("big.iso", self.ids())                            # curl, wget, any app
        self.t[0] += 30
        self.assertNotIn("big.iso", self.ids())                         # stopped growing: done

    def test_sends_while_going_and_once_more_at_the_end(self):
        sent = []

        async def publish(m):
            sent.append(protocol.decode(protocol.encode(m)))
        w = DownloadWatch(publish, steam=None, home=self.home, clock=lambda: self.t[0])
        w.note_tool("browser", {"action": "open"})
        part = self.dl / "a.part"
        part.write_bytes(b"x")
        asyncio.run(w.tick())
        part.unlink()
        asyncio.run(w.tick())
        asyncio.run(w.tick())
        self.assertEqual([len(m["items"]) for m in sent], [1, 0])
        self.assertEqual(sent[1]["ended"], [{"id": "file:" + str(part), "name": "a", "ok": False}])   # no a, so stopped

    def test_only_downloads_she_started(self):
        w = DownloadWatch(None, steam=FakeSteam(), home=self.home, clock=lambda: self.t[0])
        (self.dl / "his.part").write_bytes(b"x")
        self.assertEqual(w.collect(), [])                       # she did nothing: his, not shown
        self.t[0] += 200
        w.note_tool("browser", {"action": "open", "url": "https://example.com/x.zip"})
        (self.dl / "hers.part").write_bytes(b"x")
        self.assertEqual([i["name"] for i in w.collect()], ["hers"])   # the earlier one stays his
        self.t[0] += 200
        (self.dl / "later.part").write_bytes(b"x")
        self.assertEqual([i["name"] for i in w.collect()], ["hers"])   # long after her action: his

    def test_a_finished_download_says_so(self):
        sent = []

        async def publish(m):
            sent.append(m)
        w = DownloadWatch(publish, steam=None, home=self.home, clock=lambda: self.t[0])
        w.note_tool("browser", {"action": "open"})
        part = self.dl / "song.flac.part"
        part.write_bytes(b"x")
        asyncio.run(w.tick())
        part.rename(self.dl / "song.flac")                  # the browser renames it when it's done
        asyncio.run(w.tick())
        self.assertEqual(sent[-1]["ended"][0]["ok"], True)


if __name__ == "__main__":
    unittest.main()


class HerJobs(unittest.TestCase):
    def test_a_command_of_hers_writing_a_download_shows_wherever_it_writes(self):
        import subprocess
        import sys
        import time as _t
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        d = Path(tmp.name)
        blob = d / "hub/models--org--Big-Model/blobs/abc.incomplete"
        blob.parent.mkdir(parents=True)
        script = ("import sys,time\n"
                  f"f=open({str(blob)!r},'wb')\n"
                  "for i in range(60):\n"
                  "  f.write(b'x'*1000); f.flush()\n"
                  "  sys.stdout.write(f'\\rFetching 3 files: {i}%|##  | 1/3 [00:01<00:02, 2.0MB/s]'); sys.stdout.flush()\n"
                  "  time.sleep(0.1)\n")
        log = open(d / "job.log", "w")
        p = subprocess.Popen([sys.executable, "-c", script], stdout=log, stderr=subprocess.STDOUT,
                             start_new_session=True)
        self.addCleanup(lambda: (p.kill(), p.wait(), log.close()))
        t = [0.0]
        w = DownloadWatch(None, steam=None, home=d, clock=lambda: t[0], sessions={p.pid: "python download"})
        _t.sleep(0.6)
        w.collect()
        t[0] += 1
        _t.sleep(0.6)
        items = w.collect()                                  # no tool window needed: it's her command's
        self.assertEqual(len(items), 1, items)
        self.assertEqual(items[0]["name"], "org/Big-Model (Fetching 3 files)")
        self.assertGreater(items[0]["progress"], 0)
        self.assertEqual(items[0]["rate"], 2e6)
