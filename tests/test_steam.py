import asyncio
import os
import shutil
import signal
import struct
import tempfile
import time
import unittest
from pathlib import Path

from ariadne2 import adapters
from ariadne2.adapters import AdapterError
from ariadne2.adapters import steam, steam_files as sf

NOW = 1_800_000_000


def manifest(appid, name, flags=4, done=0, total=0, staged=0, to_stage=0, last=0):
    return (f'"AppState"\n{{\n\t"appid"\t\t"{appid}"\n\t"name"\t\t"{name}"\n'
            f'\t"StateFlags"\t\t"{flags}"\n\t"LastPlayed"\t\t"{last}"\n\t"SizeOnDisk"\t\t"1000"\n'
            f'\t"BytesToDownload"\t\t"{total}"\n\t"BytesDownloaded"\t\t"{done}"\n'
            f'\t"BytesToStage"\t\t"{to_stage}"\n\t"BytesStaged"\t\t"{staged}"\n'
            f'\t"InstalledDepots"\n\t{{\n\t\t"{appid + 1}"\n\t\t{{\n\t\t\t"size"\t\t"5"\n\t\t}}\n\t}}\n}}\n')


def localconfig(apps: dict) -> str:
    body = "".join(f'\t\t\t\t\t"{a}"\n\t\t\t\t\t{{\n\t\t\t\t\t\t"LastPlayed"\t\t"{lp}"\n'
                   f'\t\t\t\t\t\t"Playtime"\t\t"{mins}"\n\t\t\t\t\t\t"cloud"\n\t\t\t\t\t\t{{\n'
                   f'\t\t\t\t\t\t\t"last_sync_state"\t\t"synchronized"\n\t\t\t\t\t\t}}\n\t\t\t\t\t}}\n'
                   for a, (lp, mins) in apps.items())
    return ('"UserLocalConfigStore"\n{\n\t"Software"\n\t{\n\t\t"Valve"\n\t\t{\n\t\t\t"Steam"\n\t\t\t{\n'
            f'\t\t\t\t"apps"\n\t\t\t\t{{\n{body}\t\t\t\t}}\n\t\t\t}}\n\t\t}}\n\t}}\n}}\n')


def appinfo_v28(names: dict) -> bytes:
    out = struct.pack("<II", 0x07564428, 1)
    for appid, name in names.items():
        body = b"\0" * 60 + b"\x01name\0" + name.encode() + b"\0\x08"
        out += struct.pack("<II", appid, len(body)) + body
    return out + struct.pack("<II", 0, 0)


def appinfo_v29(names: dict) -> bytes:
    entries = b""
    for appid, name in names.items():
        body = b"\0" * 60 + b"\x01" + struct.pack("<I", 1) + name.encode() + b"\0\x08"
        entries += struct.pack("<II", appid, len(body)) + body
    entries += struct.pack("<II", 0, 0)
    table_at = 16 + len(entries)
    return (struct.pack("<IIq", 0x07564429, 1, table_at) + entries
            + struct.pack("<I", 2) + b"junk\0name\0")


class Tree:
    """A fake home with a Steam install and a fake /proc, in one temp dir."""

    def __init__(self):
        self.root = Path(tempfile.mkdtemp())
        self.home = self.root / "home"
        self.apps = self.home / ".local/share/Steam/steamapps"
        self.apps.mkdir(parents=True)
        self.proc = self.root / "proc"
        self.proc.mkdir()
        (self.proc / "stat").write_text("cpu 1 2 3\nbtime 1000\n")
        self.tick = 0

    def manifest(self, appid, name, **kw):
        path = self.apps / f"appmanifest_{appid}.acf"
        path.write_text(manifest(appid, name, **kw))
        self.tick += 10
        os.utime(path, (self.tick, self.tick))      # the parse cache keys on mtime

    def remove_manifest(self, appid):
        (self.apps / f"appmanifest_{appid}.acf").unlink()

    def config(self, apps):
        d = self.home / ".local/share/Steam/userdata/42/config"
        d.mkdir(parents=True, exist_ok=True)
        (d / "localconfig.vdf").write_text(localconfig(apps))
        self.tick += 10
        os.utime(d / "localconfig.vdf", (self.tick, self.tick))

    def appinfo(self, blob):
        d = self.home / ".local/share/Steam/appcache"
        d.mkdir(parents=True, exist_ok=True)
        (d / "appinfo.vdf").write_bytes(blob)

    def process(self, pid, argv, ppid=1, start_ticks=0):
        d = self.proc / str(pid)
        d.mkdir(exist_ok=True)
        (d / "cmdline").write_bytes(b"\0".join(a.encode() for a in argv) + b"\0")
        fields = ["S", str(ppid)] + ["0"] * 17 + [str(start_ticks)] + ["0"] * 30
        (d / "stat").write_text(f"{pid} (x y) " + " ".join(fields) + "\n")

    def kill_process(self, pid):
        shutil.rmtree(self.proc / str(pid), ignore_errors=True)

    def steam_up(self):
        self.process(10, ["/home/u/.local/share/Steam/ubuntu12_32/steam", "-srt-logger-opened"])

    def game_up(self, appid, reaper=200, start_ticks=100 * os.sysconf("SC_CLK_TCK")):
        self.process(reaper, ["/x/ubuntu12_32/reaper", "SteamLaunch", f"AppId={appid}", "--", "game.sh"],
                     start_ticks=start_ticks)
        self.process(reaper + 1, ["/x/proton", "run", "game.exe"], ppid=reaper)
        self.process(reaper + 2, ["game.exe"], ppid=reaper + 1)

    def files(self):
        return sf.SteamFiles(home=self.home, mount_roots=())

    def cleanup(self):
        shutil.rmtree(self.root, ignore_errors=True)


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class Base(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tree = Tree()
        self.addCleanup(self.tree.cleanup)
        self.tree.steam_up()
        self.published, self.events, self.opened, self.signals = [], [], [], []
        self.clock = Clock()
        self.alive = set()

    def make(self):
        async def publish(msg):
            self.published.append(msg)

        async def opener(url):
            self.opened.append(url)

        a = steam.SteamAdapter(publish, files=self.tree.files(), proc=str(self.tree.proc), opener=opener,
                               send=lambda pid, sig: self.signals.append((pid, sig)),
                               alive=lambda pid: pid in self.alive)
        a.now, a.mono, a.settle = (lambda: NOW), self.clock, 0
        a.subscribe(lambda ev, f: self.events.append((ev, f)))
        return a


class VdfTests(unittest.TestCase):
    def test_nested_and_lowercased(self):
        d = sf.parse_vdf('"AppState" { "AppID" "7" // c\n "Inner" { "K" "v" } "Path" "C:\\\\x \\"q\\"" }')
        self.assertEqual(d["appstate"]["appid"], "7")
        self.assertEqual(d["appstate"]["inner"], {"k": "v"})
        self.assertEqual(d["appstate"]["path"], 'C:\\x "q"')

    def test_damaged_file_gives_what_parsed(self):
        self.assertEqual(sf.parse_vdf('"a" "1" "b" {  "c" "2"')["a"], "1")
        self.assertEqual(sf.parse_vdf(""), {})
        self.assertEqual(sf.parse_vdf("} } }"), {})

    def test_localconfig_apps_survive_nested_blocks(self):
        t = Tree()
        self.addCleanup(t.cleanup)
        t.config({550: (111, 60), 620: (222, 120)})
        self.assertEqual(t.files().playtime(), {550: {"last_played": 111, "minutes": 60},
                                                620: {"last_played": 222, "minutes": 120}})

    def test_appinfo_both_generations(self):
        names = {70: "Half-Life", 400: "Portal"}
        self.assertEqual(sf.parse_appinfo(appinfo_v28(names)), names)
        self.assertEqual(sf.parse_appinfo(appinfo_v29(names)), names)
        self.assertEqual(sf.parse_appinfo(b"nope"), {})
        self.assertEqual(sf.parse_appinfo(appinfo_v29(names)[:40]), {})


class MatchTests(unittest.TestCase):
    G = [{"appid": 1203620, "name": "Enshrouded"}, {"appid": 1144200, "name": "Ready or Not"},
         {"appid": 553850, "name": "HELLDIVERS™ 2"}, {"appid": 292030, "name": "The Witcher 3: Wild Hunt"},
         {"appid": 20900, "name": "The Witcher: Enhanced Edition"}]

    def names(self, q):
        return [g["name"] for g in sf.match_game(q, self.G)[0]]

    def test_tiers(self):
        self.assertEqual(self.names("enshrouded"), ["Enshrouded"])
        self.assertEqual(self.names("ready"), ["Ready or Not"])          # prefix
        self.assertEqual(self.names("helldivers 2"), ["HELLDIVERS™ 2"])  # punctuation ignored
        self.assertEqual(self.names("wild hunt"), ["The Witcher 3: Wild Hunt"])  # words
        self.assertEqual(self.names("shroud"), ["Enshrouded"])           # substring
        self.assertEqual(self.names("1144200"), ["Ready or Not"])        # appid

    def test_ambiguous_and_typo_and_none(self):
        self.assertEqual(len(self.names("witcher")), 2)
        self.assertEqual(self.names("ensrouded"), ["Enshrouded"])        # typo
        self.assertEqual(self.names("zzzz"), [])
        self.assertEqual(self.names(""), [])


class StateTests(Base):
    async def test_recent_newest_first_capped_and_clean(self):
        t = self.tree
        t.manifest(1, "Alpha", last=500)
        t.manifest(2, "Proton 9.0", last=9000)             # a tool: never recent
        t.manifest(3, "Gamma", flags=4)
        t.config({1: (600, 90), 3: (700, 30), 4: (650, 600), 5: (0, 10), 6: (800, 5)})
        t.appinfo(appinfo_v28({4: "Delta (not installed)"}))
        for i in range(10, 20):
            t.config({1: (600, 90), 3: (700, 30), 4: (650, 600), 5: (0, 10), 6: (800, 5),
                      **{j: (100 + j, 0) for j in range(10, i + 1)}})
            t.manifest(i, f"G{i}", last=0)
        a = self.make()
        await a.refresh()
        s = a.state()
        self.assertEqual(set(s), {"status", "playing", "recent", "downloads"})
        self.assertEqual(s["status"], "running")
        self.assertEqual(len(s["recent"]), 8)
        self.assertEqual([r["appid"] for r in s["recent"][:3]], [3, 4, 1])   # 6 has no name: skipped
        self.assertEqual(s["recent"][0], {"appid": 3, "name": "Gamma", "last_played": 700,
                                          "hours": 0.5, "installed": True})
        d = next(r for r in s["recent"] if r["appid"] == 4)
        self.assertEqual((d["name"], d["installed"], d["hours"]), ("Delta (not installed)", False, 10.0))
        self.assertNotIn(2, [r["appid"] for r in s["recent"]])
        self.assertNotIn(5, [r["appid"] for r in s["recent"]])               # never played

    async def test_not_running_and_no_steam_files(self):
        self.tree.kill_process(10)
        a = self.make()
        await a.refresh()
        self.assertEqual(a.state(), steam.blank_state())

    async def test_publishes_only_on_change(self):
        self.tree.manifest(1, "Alpha", last=5)
        a = self.make()
        await a.refresh()
        await a.refresh()
        self.assertEqual(len(self.published), 1)
        self.tree.manifest(1, "Alpha", last=6)
        await a.refresh()
        self.assertEqual(len(self.published), 2)
        self.assertEqual(self.published[-1]["widget"], "steam")

    async def test_running_game_from_process_list(self):
        t = self.tree
        t.manifest(1203620, "Enshrouded", last=5)
        t.game_up(1203620)
        t.process(300, ["wallpaper", "--assets", "/x/Steam/steamapps/AppId=999"])   # not a game
        a = self.make()
        await a.refresh()
        self.assertEqual(a.state()["playing"], {"appid": 1203620, "name": "Enshrouded", "since": 1100})
        self.assertEqual(a.state()["recent"][0]["last_played"], 1100)    # playing now = most recent

    async def test_unknown_game_still_shows_as_playing(self):
        self.tree.game_up(999999)
        a = self.make()
        await a.refresh()
        self.assertEqual(a.state()["playing"]["name"], "app 999999")
        self.assertEqual(a.state()["recent"], [])


class DownloadTests(Base):
    def test_download_state_table(self):
        f = lambda flags, done=0: steam.download_state({"flags": flags, "bytes_done": done})  # noqa: E731
        self.assertIsNone(f(4))
        self.assertIsNone(f(6))                      # update available, not running
        self.assertEqual(f(1026), "queued")
        self.assertEqual(f(1026, 5), "downloading")  # new install, bytes moving
        self.assertEqual(f(1030, 5), "updating")     # installed game updating
        self.assertEqual(f(2 | 1 << 20, 5), "downloading")
        self.assertEqual(f(4 | 2 | 1 << 20), "updating")
        self.assertEqual(f(2 | 512), "paused")
        self.assertEqual(f(2), "queued")             # new install waiting its turn

    async def test_progress_rate_and_ordering(self):
        t, a = self.tree, None
        t.manifest(10, "Big", flags=1026, done=1_000, total=10_000)
        t.manifest(11, "Waiting", flags=1026, done=0, total=500)
        t.manifest(12, "Held", flags=2 | 512, done=50, total=100)
        t.manifest(13, "Done", flags=4, done=9, total=9)
        a = self.make()
        await a.refresh()
        dl = a.state()["downloads"]
        self.assertEqual([(d["name"], d["state"]) for d in dl],
                         [("Big", "downloading"), ("Waiting", "queued"), ("Held", "paused")])
        big = dl[0]
        self.assertEqual((big["progress"], big["bytes_done"], big["bytes_total"]), (0.1, 1000, 10000))
        self.assertIsNone(big["rate_bps"])             # one sample: no rate yet
        self.clock.t += 4
        t.manifest(10, "Big", flags=1026, done=5_000, total=10_000)
        await a.refresh()
        self.assertEqual(a.state()["downloads"][0]["rate_bps"], 1000.0)
        self.assertEqual(a.state()["downloads"][0]["progress"], 0.5)
        self.assertIsNone(a.state()["downloads"][1]["rate_bps"])        # queued
        self.clock.t += 50                              # no progress for ~a minute: stalled
        await a.refresh()
        self.assertEqual(a.state()["downloads"][0]["rate_bps"], 0.0)

    async def test_staging_phase_uses_staged_bytes(self):
        self.tree.manifest(10, "Big", flags=4 | 1 << 21 | 1024, done=100, total=100, staged=25, to_stage=100)
        a = self.make()
        await a.refresh()
        d = a.state()["downloads"][0]
        self.assertEqual((d["state"], d["progress"], d["bytes_done"]), ("updating", 0.25, 25))

    async def test_poll_period_follows_activity(self):
        a = self.make()
        await a.refresh()
        self.assertEqual(a._period(), steam.SLOW)
        self.tree.manifest(10, "Big", flags=1026, done=5, total=10)
        await a.refresh()
        self.assertEqual(a._period(), steam.FAST)


class EventTests(Base):
    async def test_game_started_and_closed(self):
        self.tree.manifest(1203620, "Enshrouded")
        a = self.make()
        await a.refresh()
        self.assertEqual(self.events, [])
        self.tree.game_up(1203620)
        await a.refresh()
        self.assertEqual(self.events, [("steam.game_started", {"name": "Enshrouded", "appid": 1203620})])
        await a.refresh()
        self.assertEqual(len(self.events), 1)                           # no repeat
        for pid in (200, 201, 202):
            self.tree.kill_process(pid)
        await a.refresh()
        self.assertEqual(self.events[-1], ("steam.game_closed", {"name": "Enshrouded", "appid": 1203620}))

    async def test_already_running_at_startup_is_not_an_event(self):
        self.tree.manifest(1203620, "Enshrouded")
        self.tree.game_up(1203620)
        a = self.make()
        await a.refresh()
        self.assertEqual(self.events, [])

    async def test_download_done_only_when_it_finished(self):
        t = self.tree
        t.manifest(10, "Big", flags=1026, done=5, total=10)
        t.manifest(11, "Held", flags=1026, done=5, total=10)
        t.manifest(12, "Cancelled", flags=1026, done=5, total=10)
        a = self.make()
        await a.refresh()
        t.manifest(10, "Big", flags=4, done=10, total=10)               # finished
        t.manifest(11, "Held", flags=2 | 512, done=5, total=10)         # paused: still listed
        t.remove_manifest(12)                                           # cancelled
        await a.refresh()
        self.assertEqual(self.events, [("steam.download_done", {"name": "Big", "appid": 10})])
        self.assertEqual([d["state"] for d in a.state()["downloads"]], ["paused"])

    def test_events_are_declared(self):
        self.assertEqual(steam.SteamAdapter.events, ("game_started", "game_closed", "download_done"))


class VerbTests(Base):
    def setUp(self):
        super().setUp()
        t = self.tree
        t.manifest(1203620, "Enshrouded", last=5)
        t.manifest(1144200, "Ready or Not", last=4)
        t.manifest(292030, "The Witcher 3: Wild Hunt")
        t.manifest(20900, "The Witcher: Enhanced Edition")
        t.config({1203620: (5, 486), 2104890: (7, 2230)})
        t.appinfo(appinfo_v28({2104890: "RoadCraft"}))

    async def test_launch_fuzzy_goes_through_steam_url(self):
        a = self.make()
        out = await a.run("launch", {"game": "enshr"})
        self.assertEqual(self.opened, ["steam://rungameid/1203620"])
        self.assertIn("Enshrouded", out)
        self.assertEqual([m["phase"] for m in self.published if m["t"] == "action"], ["started", "done"])

    async def test_launch_error_paths(self):
        a = self.make()
        for args, text in (({"game": ""}, "say which game"), ({"game": "zzzzzz"}, "can't find"),
                           ({"game": "witcher"}, "which one"), ({"game": "roadcraft"}, "not installed")):
            with self.assertRaises(AdapterError, msg=args) as cm:
                await a.run("launch", args)
            self.assertIn(text, str(cm.exception))
        with self.assertRaises(AdapterError):
            await a.run("launch", {})                       # missing argument
        self.assertEqual(self.opened, [])
        fail = [m for m in self.published if m["t"] == "action" and m["phase"] == "failed"]
        self.assertTrue(fail)

    async def test_launch_when_opener_fails_and_when_already_running(self):
        a = self.make()

        async def broken(url):
            raise AdapterError("couldn't reach Steam (xdg-open exited 3)")
        a._open = broken
        with self.assertRaises(AdapterError):
            await a.run("launch", {"game": "enshrouded"})
        self.tree.game_up(1203620)
        a._open = lambda url: self.fail("must not relaunch")
        self.assertIn("already running", await a.run("launch", {"game": "enshrouded"}))

    async def test_launch_notes_steam_not_running(self):
        self.tree.kill_process(10)
        out = await self.make().run("launch", {"game": "enshrouded"})
        self.assertIn("has to start first", out)

    async def test_close_signals_children_first_then_reaper(self):
        self.tree.game_up(1203620)
        a = self.make()
        out = await a.run("close", {})
        self.assertEqual(self.signals, [(202, signal.SIGTERM), (201, signal.SIGTERM), (200, signal.SIGTERM)])
        self.assertEqual(out, "Closed Enshrouded.")

    async def test_close_error_paths(self):
        a = self.make()
        with self.assertRaises(AdapterError) as cm:
            await a.run("close", {})
        self.assertIn("no Steam game is running", str(cm.exception))
        self.tree.game_up(1203620)
        with self.assertRaises(AdapterError) as cm:
            await a.run("close", {"game": "ready or not"})
        self.assertIn("can't find", str(cm.exception))
        self.assertEqual(self.signals, [])
        self.alive = {200}                                   # ignores SIGTERM
        with self.assertRaises(AdapterError) as cm:
            await a.run("close", {"game": "enshrouded"})
        self.assertIn("didn't exit", str(cm.exception))

    async def test_close_description_warns_to_confirm(self):
        a = self.make()
        self.assertIn("confirm with him first", a.verb("close").description)
        self.assertIn("unsaved", a.verb("close").description)

    async def test_install(self):
        a = self.make()
        self.assertIn("Asked Steam to install RoadCraft", await a.run("install", {"game": "roadcraft"}))
        self.assertEqual(self.opened, ["steam://install/2104890"])
        self.assertIn("already installed", await a.run("install", {"game": "enshrouded"}))
        self.assertIn("RoadCraft", await a.run("install", {"game": "2104890"}))
        await a.run("install", {"game": "424242"})            # unknown appid: trusted
        self.assertEqual(self.opened[-1], "steam://install/424242")
        with self.assertRaises(AdapterError):
            await a.run("install", {"game": "nothing like it"})
        with self.assertRaises(AdapterError):
            await a.run("install", {"game": " "})
        self.tree.manifest(2104890, "RoadCraft", flags=1026, done=5, total=10)
        self.assertIn("already downloading", await a.run("install", {"game": "roadcraft"}))

    async def test_library(self):
        a = self.make()
        text = await a.run("library", {})
        self.assertIn("4 installed of 5", text)
        self.assertNotIn("RoadCraft", text)
        text = await a.run("library", {"query": "road"})
        self.assertIn("RoadCraft (appid 2104890) — not installed, 37.2h", text)
        self.assertIn("Enshrouded", await a.run("library", {"query": "Enshrouded"}))
        self.assertIn("0 match", await a.run("library", {"query": "zzzzz"}))

    async def test_library_without_steam_files(self):
        shutil.rmtree(self.tree.home)
        self.tree.home.mkdir()
        with self.assertRaises(AdapterError):
            await self.make().run("library", {})

    async def test_widget_presses(self):
        a = self.make()
        self.assertEqual(a.controls, {"launch": "launch", "close": "close"})
        out = await a.press("launch", 1144200)
        self.assertEqual(self.opened, ["steam://rungameid/1144200"])
        self.assertIn("Ready or Not", out)
        self.assertEqual([m for m in self.published if m["t"] == "action"], [])   # his click: no wires
        self.tree.game_up(1144200)
        await a.press("close", 1144200)
        self.assertEqual(self.signals[-1], (200, signal.SIGTERM))
        with self.assertRaises(AdapterError):
            await a.press("launch", None)
        self.assertIsNone(await a.press("nothing", 1))

    async def test_tools_registered(self):
        self.assertEqual(adapters.REGISTRY["steam"], "ariadne2.adapters.steam:SteamAdapter")
        a = self.make()
        names = {adapters.tool_name(a, v) for v in a.verbs}
        self.assertEqual(names, {"steam_launch", "steam_close", "steam_install", "steam_library"})
        schemas = {t["name"]: t["input_schema"] for t in adapters.tools({"steam": a})}
        self.assertEqual(list(schemas), ["steam"])
        self.assertEqual(set(schemas["steam"]["properties"]["action"]["enum"]), {"launch", "close", "install", "library"})


class ProcessTests(unittest.TestCase):
    def test_scan_processes_tree_and_start_time(self):
        t = Tree()
        self.addCleanup(t.cleanup)
        t.steam_up()
        t.game_up(77, reaper=500, start_ticks=50 * os.sysconf("SC_CLK_TCK"))
        r = sf.scan_processes(str(t.proc))
        self.assertTrue(r["steam"])
        self.assertEqual(r["games"], [{"appid": 77, "pid": 500, "started": 1050.0, "pids": [500, 501, 502]}])

    def test_no_proc_dir(self):
        self.assertEqual(sf.scan_processes("/nonexistent-proc"), {"steam": False, "games": []})


if __name__ == "__main__":
    unittest.main()
