import asyncio
import json
import os
import signal
import tempfile
import unittest
from pathlib import Path

from ariadne2 import adapters, protocol
from ariadne2.adapters import AdapterError, tasks
from ariadne2.adapters.tasks import Desktop, ProcSampler, TasksAdapter
from ariadne2.desk import layout

ME = 1000
SCOPE = "0::/user.slice/user-1000.slice/user@1000.service/app.slice/"


class FakeProc:
    """A /proc tree in a temp dir: add processes, set the aggregate cpu line, change ticks between reads."""

    def __init__(self, cores=4):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.cores = cores
        self.cpu(0, 0)
        self.mem(1000, 400)

    def cpu(self, busy, idle):
        lines = [f"cpu  {busy} 0 0 {idle} 0 0 0 0 0 0"]
        lines += [f"cpu{i} 0 0 0 0 0 0 0 0 0 0" for i in range(self.cores)]
        Path(self.root, "stat").write_text("\n".join(lines) + "\n")

    def mem(self, total, avail):
        Path(self.root, "meminfo").write_text(f"MemTotal: {total} kB\nMemFree: 1 kB\nMemAvailable: {avail} kB\n")

    def add(self, pid, comm, ppid=1, ticks=0, unit="", cmd=None, uid=ME, rss_mb=1, start=None):
        d = Path(self.root, str(pid))
        d.mkdir(exist_ok=True)
        rss = int(rss_mb * 1048576 / tasks.PAGE)
        f = ["S", str(ppid)] + ["0"] * 9 + [str(ticks), "0"] + ["0"] * 6 + [str(start or pid), "0", str(rss)]
        d.joinpath("stat").write_text(f"{pid} ({comm}) " + " ".join(f))
        d.joinpath("status").write_text(f"Name:\t{comm}\nUid:\t{uid}\t{uid}\t{uid}\t{uid}\n")
        argv = cmd if cmd is not None else [comm]
        d.joinpath("cmdline").write_bytes(b"\0".join(a.encode() for a in argv) + (b"\0" if argv else b""))
        d.joinpath("cgroup").write_text(("0::/" + unit if unit.startswith("../") else SCOPE + unit) + "\n"
                                        if unit else "0::/\n")

    def ticks(self, pid, ticks):
        d = Path(self.root, str(pid))
        parts = d.joinpath("stat").read_text().rsplit(")", 1)
        f = parts[1].split()
        f[11] = str(ticks)
        d.joinpath("stat").write_text(parts[0] + ") " + " ".join(f))

    def remove(self, pid):
        import shutil
        shutil.rmtree(Path(self.root, str(pid)))


def desktop_dir(tmp):
    d = Path(tmp, "apps")
    d.mkdir()
    (d / "com.discordapp.Discord.desktop").write_text(
        "[Desktop Entry]\nName=Discord\nIcon=discord-icon\nExec=discord %U\n")
    (d / "steam.desktop").write_text("[Desktop Entry]\nName=Steam\nIcon=steam\nExec=/usr/bin/steam %U\n")
    (d / "org.kde.konsole.desktop").write_text("[Desktop Entry]\nName=Konsole\nIcon=utilities-terminal\nExec=konsole\n")
    return Desktop([str(d)])


def world(fp):
    """Discord (flatpak) with Electron helpers, two Opera scopes, Steam with a game, Konsole with a shell and
    the process running this, Ariadne, daemons, a root process and a kernel thread."""
    fp.add(1, "systemd", 0, cmd=["/sbin/init"], uid=0, unit="../init.scope")
    fp.add(2, "kthreadd", 0, cmd=[], uid=0, unit="../")
    fp.add(3, "kworker/0:1", 2, cmd=[], uid=0, unit="../")
    fp.add(10, "systemd", 1, cmd=["/usr/lib/systemd/systemd", "--user"], unit="user@1000.service")
    fp.add(11, "kwin_wayland", 10, cmd=["kwin_wayland"], unit="plasma-kwin_wayland.service")
    fp.add(12, "plasmashell", 10, cmd=["plasmashell"], unit="plasma-plasmashell.service")
    fp.add(13, "baloo_file", 10, cmd=["baloo_file"], unit="kde-baloo.service")
    fp.add(14, "sshd", 1, cmd=["sshd"], uid=0, unit="sshd.service")
    fp.add(15, "mystery", 10, cmd=["/opt/mystery/mystery"], unit="")        # no unit, no daemon name: its own app
    # Discord: main, renderer, GPU helper in the same flatpak scope; a helper that lost its unit info
    d = "app-flatpak-com.discordapp.Discord-111.scope"
    fp.add(100, "bwrap", 10, cmd=["bwrap", "--args"], unit=d)
    fp.add(101, "Discord", 100, cmd=["/app/discord/Discord"], unit=d)
    fp.add(102, "Discord", 101, cmd=["/app/discord/Discord", "--type=renderer"], unit=d)
    fp.add(103, "Discord", 101, cmd=["/app/discord/Discord", "--type=gpu-process"], unit=d)
    fp.add(104, "Discord", 101, cmd=["/app/discord/Discord", "--type=utility"], unit="")
    # Opera in two scopes: one app
    fp.add(200, "opera-gx", 10, cmd=["opera-gx"], unit="app-flatpak-com.opera.opera\\x2dgx-1.scope")
    fp.add(201, "opera-gx", 10, cmd=["opera-gx"], unit="app-flatpak-com.opera.opera\\x2dgx-2.scope")
    # Steam and what it started
    fp.add(300, "steam", 10, cmd=["steam"], unit="app-steam@abc.service")
    fp.add(301, "steamwebhelper", 300, cmd=["steamwebhelper"], unit="app-steam@abc.service")
    fp.add(302, "reaper", 300, cmd=["reaper", "SteamLaunch"], unit="")
    fp.add(303, "game.exe", 302, cmd=["game.exe"], unit="")
    # Konsole, a shell in its own vte scope, and this run
    fp.add(400, "konsole", 10, cmd=["konsole"], unit="app-org.kde.konsole@x.service")
    fp.add(401, "bash", 400, cmd=["bash"], unit="vte-spawn-1.scope")
    fp.add(402, "python3", 401, cmd=["python3", "-m", "unittest"], unit="vte-spawn-1.scope")
    # Ariadne itself
    fp.add(500, "python3", 10, cmd=["python3", "-m", "ariadne2.core"], unit="app-ariadne2@y.service")
    fp.add(501, "godot", 500, cmd=["godot", "--path", "pet"], unit="app-ariadne2@y.service")


def adapter(fp, **kw):
    published = []

    async def pub(msg):
        published.append(msg)

    tmp = tempfile.TemporaryDirectory()
    kw.setdefault("desktop", desktop_dir(tmp.name))
    kw.setdefault("self_pid", 402)
    kw.setdefault("my_uid", ME)
    kw.setdefault("kwin", lambda js, reply: "[]")
    async def no_gpu():
        return None

    kw.setdefault("gpu", no_gpu)
    a = TasksAdapter(pub, root=fp.root, **kw)
    a._tmp = tmp
    a.published = published
    return a


def by_name(state):
    return {r["name"]: r for r in state["apps"]}


class Parsing(unittest.TestCase):
    def test_app_id(self):
        cases = {"app-flatpak-com.discordapp.Discord-111.scope": "com.discordapp.Discord",
                 "app-flatpak-com.opera.opera\\x2dgx-3677086758.scope": "com.opera.opera-gx",
                 "app-steam@7bbfb7fcb8ea.service": "steam",
                 "app-claude\\x2dcom.anthropic.Claude@f7ea.service": "com.anthropic.Claude",
                 "app-com.anthropic.Claude-191290.scope": "com.anthropic.Claude",
                 "app-org.local.Ariadne@4aa4.service": "org.local.Ariadne",
                 "app-ariadne2@b3ad.service": "ariadne2",
                 "plasma-kwin_wayland.service": None, "session-1.scope": None, "": None}
        for unit, want in cases.items():
            self.assertEqual(tasks.app_id(unit), want, unit)

    def test_unit_and_stat(self):
        self.assertEqual(tasks.parse_unit("0::/a/b/app-x.scope\n"), "app-x.scope")
        self.assertEqual(tasks.parse_unit("0::/../../..\n"), "")
        self.assertEqual(tasks.parse_unit(""), "")
        fields = ["S", "1"] + ["0"] * 9 + ["5", "7"] + ["0"] * 6 + ["99", "0", "33"]
        st = tasks.parse_stat("12 (we ird) name) " + " ".join(fields))
        self.assertEqual(st, ("we ird) name", 1, 12, 99, 33))
        self.assertIsNone(tasks.parse_stat("garbage"))

    def test_desktop_entry(self):
        e = tasks.parse_desktop("[Desktop Entry]\nName=Foo\nName[de]=Fu\nIcon=foo\nExec=env A=1 /usr/bin/foo %F\n"
                                "[Desktop Action x]\nName=Other\n", "org.foo")
        self.assertEqual((e.name, e.icon, e.exec_base), ("Foo", "foo", "foo"))

    def test_gpu_apps(self):
        self.assertEqual(tasks.parse_gpu_apps("2135, 101\n8521, 154\n8521, 6\n"), {2135: 101.0, 8521: 160.0})
        self.assertEqual(tasks.parse_gpu_apps("No running processes found\n"), {})
        self.assertEqual(tasks.parse_gpu_apps(""), {})
        self.assertIsNone(tasks.parse_gpu_apps("NVIDIA-SMI has failed because it couldn't communicate"))
        self.assertEqual(tasks.parse_gpu_apps("7, [N/A]\n"), {7: 0.0})


class Grouping(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.fp = FakeProc()
        self.addCleanup(self.fp.tmp.cleanup)
        world(self.fp)
        self.a = adapter(self.fp)
        await self.a.refresh()
        self.rows = by_name(self.a.state())

    def test_electron_helpers_join_their_app(self):
        self.assertEqual(self.rows["Discord"]["pids"], [100, 101, 102, 103, 104])    # incl. the one with no unit
        self.assertEqual(self.rows["Discord"]["icon"], "discord-icon")

    def test_two_scopes_one_app(self):
        k = [n for n in self.rows if "opera" in n.lower()]
        self.assertEqual(len(k), 1)
        self.assertEqual(self.rows[k[0]]["pids"], [200, 201])

    def test_steam_children(self):
        self.assertEqual(self.rows["Steam"]["pids"], [300, 301, 302, 303])
        self.assertEqual(self.rows["Steam"]["icon"], "steam")

    def test_terminal_holds_its_shells(self):
        self.assertEqual(self.rows["Konsole"]["pids"], [400, 401, 402])

    def test_daemons_root_and_kernel_are_one_system_row(self):
        self.assertEqual(self.rows["System"]["pids"], [1, 2, 3, 10, 11, 12, 13, 14])
        self.assertEqual(self.rows["System"]["windows"], 0)

    def test_unknown_process_is_its_own_app(self):
        self.assertEqual(self.rows["mystery"]["pids"], [15])

    def test_ariadne_is_named(self):
        self.assertEqual(self.rows["ariadne2"]["pids"], [500, 501])

    def test_shape(self):
        s = self.a.state()
        self.assertEqual(s["status"], "ok")
        self.assertEqual(set(s["total"]), {"cpu", "mem_pct"})
        self.assertEqual(s["total"]["mem_pct"], 60.0)
        for r in s["apps"]:
            self.assertEqual(set(r), {"name", "pids", "cpu", "mem_mb", "gpu_mb", "windows", "icon"})
            self.assertIsNone(r["gpu_mb"])         # no nvidia-smi reading
        protocol.state("tasks", s)                  # fits the wire

    async def test_python_script_named_by_script(self):
        self.fp.add(600, "python3", 10, cmd=["python3", "/home/x/backup.py", "--now"], unit="")
        await self.a.refresh()
        self.assertIn("backup", by_name(self.a.state()))


class Numbers(unittest.IsolatedAsyncioTestCase):
    async def test_cpu_deltas_and_memory(self):
        fp = FakeProc(cores=4)
        self.addCleanup(fp.tmp.cleanup)
        fp.add(1, "systemd", 0, uid=0, unit="../init.scope")
        fp.add(10, "systemd", 1, unit="user@1000.service")
        fp.add(20, "a", 10, ticks=100, unit="app-a@1.service", rss_mb=100)
        fp.add(21, "a", 20, ticks=50, unit="app-a@1.service", rss_mb=50)
        fp.add(30, "b", 10, ticks=0, unit="app-b@1.service", rss_mb=10)
        fp.cpu(1000, 3000)
        a = adapter(fp)
        await a.refresh()
        self.assertTrue(all(r["cpu"] == 0 for r in a.state()["apps"]))     # first read has nothing to compare with
        # 400 jiffies elapse on 4 cores = 100 per core; a ran 100 + 50, b ran 25; machine busy 150 of 400
        fp.cpu(1000 + 175, 3000 + 225)
        fp.ticks(20, 200)
        fp.ticks(21, 100)
        fp.ticks(30, 25)
        await a.refresh()
        s = a.state()
        r = by_name(s)
        self.assertEqual(r["a"]["cpu"], 150.0)                   # 150 jiffies where one core had 100: 1.5 cores
        self.assertEqual(r["b"]["cpu"], 25.0)
        self.assertEqual(r["a"]["mem_mb"], 150.0)
        self.assertEqual(s["total"]["cpu"], round(100.0 * 175 / 400, 1))
        self.assertEqual([x["name"] for x in s["apps"]][:2], ["a", "b"])    # busiest first

    async def test_new_process_counts_what_it_ran_and_dead_ones_vanish(self):
        fp = FakeProc(cores=1)
        self.addCleanup(fp.tmp.cleanup)
        fp.add(10, "systemd", 1, unit="user@1000.service")
        fp.add(20, "old", 10, ticks=10, unit="app-old@1.service")
        fp.cpu(100, 100)
        a = adapter(fp)
        await a.refresh()
        fp.remove(20)
        fp.add(21, "new", 10, ticks=40, unit="app-new@1.service")
        fp.cpu(200, 200)                                         # 200 jiffies, one core
        await a.refresh()
        r = by_name(a.state())
        self.assertNotIn("old", r)
        self.assertEqual(r["new"]["cpu"], 20.0)

    async def test_pid_reuse_is_a_new_process(self):
        fp = FakeProc(cores=1)
        self.addCleanup(fp.tmp.cleanup)
        fp.add(10, "systemd", 1, unit="user@1000.service")
        fp.add(20, "x", 10, ticks=1000, unit="app-x@1.service", start=5)
        fp.cpu(0, 100)
        a = adapter(fp)
        await a.refresh()
        fp.add(20, "x", 10, ticks=10, unit="app-x@1.service", start=999)     # same pid, later start
        fp.cpu(50, 150)
        await a.refresh()
        self.assertEqual(by_name(a.state())["x"]["cpu"], 10.0)

    async def test_sorting_and_limit(self):
        fp = FakeProc(cores=1)
        self.addCleanup(fp.tmp.cleanup)
        fp.add(10, "systemd", 1, unit="user@1000.service")
        for i in range(30):
            fp.add(100 + i, f"app{i:02d}", 10, ticks=0, unit=f"app-app{i:02d}@1.service", rss_mb=i + 1)
        fp.cpu(0, 100)
        a = adapter(fp)
        await a.refresh()
        for i in range(30):
            fp.ticks(100 + i, i)
        fp.cpu(0, 200)
        await a.refresh()
        apps = a.state()["apps"]
        self.assertEqual(len(apps), 25)
        cpus = [r["cpu"] for r in apps]
        self.assertEqual(cpus, sorted(cpus, reverse=True))
        self.assertEqual(apps[0]["name"], "app29")
        self.assertNotIn("app00", [r["name"] for r in apps])

    async def test_pid_list_is_capped(self):
        fp = FakeProc(cores=1)
        self.addCleanup(fp.tmp.cleanup)
        fp.add(10, "systemd", 1, unit="user@1000.service")
        for i in range(100):
            fp.add(1000 + i, "helper", 10, unit="app-big@1.service")
        a = adapter(fp)
        await a.refresh()
        self.assertEqual(len(by_name(a.state())["big"]["pids"]), tasks.MAX_PIDS)

    async def test_gpu_per_app(self):
        fp = FakeProc()
        self.addCleanup(fp.tmp.cleanup)
        world(fp)

        async def gpu():
            return {101: 150.0, 102: 4.0, 303: 700.0}

        a = adapter(fp, gpu=gpu)
        await a.refresh()
        r = by_name(a.state())
        self.assertEqual(r["Discord"]["gpu_mb"], 154.0)
        self.assertEqual(r["Steam"]["gpu_mb"], 700.0)
        self.assertEqual(r["Konsole"]["gpu_mb"], 0.0)

    async def test_windows_counted_per_app(self):
        fp = FakeProc()
        self.addCleanup(fp.tmp.cleanup)
        world(fp)
        wins = [{"id": "{a}", "pid": 101, "cls": "discord", "desk": "com.discordapp.Discord", "cap": "x"},
                {"id": "{b}", "pid": 101, "cls": "discord", "desk": "", "cap": "y"},
                {"id": "{c}", "pid": 4242, "cls": "steam", "desk": "steam", "cap": "z"},     # pid we can't see: by class
                {"id": "{d}", "pid": 4243, "cls": "who", "desk": "", "cap": "?"}]
        a = adapter(fp, kwin=lambda js, reply: json.dumps(wins))
        await a.refresh()
        r = by_name(a.state())
        self.assertEqual((r["Discord"]["windows"], r["Steam"]["windows"], r["Konsole"]["windows"]), (2, 1, 0))

    async def test_kwin_trouble_means_zero_windows(self):
        fp = FakeProc()
        self.addCleanup(fp.tmp.cleanup)
        world(fp)

        def broken(js, reply):
            raise AdapterError("this isn't KDE")

        a = adapter(fp, kwin=broken)
        await a.refresh()
        self.assertEqual(by_name(a.state())["Discord"]["windows"], 0)


class Verbs(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.fp = FakeProc()
        self.addCleanup(self.fp.tmp.cleanup)
        world(self.fp)
        self.sent = []
        self.kills = []
        self.wins = [{"id": "{a}", "pid": 101, "cls": "discord", "desk": "com.discordapp.Discord", "cap": "x"},
                     {"id": "{k}", "pid": 400, "cls": "konsole", "desk": "org.kde.konsole", "cap": "k"}]

        def kwin(js, reply):
            if reply:
                return json.dumps(self.wins)
            self.sent.append(js)

        self.clock = [1000.0]
        self.a = adapter(self.fp, kwin=kwin, kill=lambda pid, sig: self.kills.append((pid, sig)),
                         mono=lambda: self.clock[0])
        await self.a.refresh()

    async def run_verb(self, verb, **args):
        return await self.a.run(verb, args, announce=False)

    async def test_close_asks_politely_then_ends_when_asked_again(self):
        out = await self.run_verb("close", app="discord")
        self.assertIn("Asked Discord to close", out)
        self.assertEqual(self.kills, [])
        self.assertIn("closeWindow", self.sent[-1])
        self.assertIn('"{a}"', self.sent[-1])
        self.clock[0] += 20
        out = await self.run_verb("close", app="Discord")
        self.assertIn("Ended Discord", out)
        self.assertEqual(sorted(p for p, _ in self.kills), [100, 101, 102, 103, 104])
        self.assertTrue(all(s == signal.SIGTERM for _, s in self.kills))

    async def test_a_stale_request_asks_politely_again(self):
        await self.run_verb("close", app="Discord")
        self.clock[0] += tasks.ASK_TTL + 1
        out = await self.run_verb("close", app="Discord")
        self.assertIn("Asked Discord", out)
        self.assertEqual(self.kills, [])

    async def test_app_with_no_window_is_ended_straight_away(self):
        out = await self.run_verb("close", app="Steam")
        self.assertIn("Ended Steam", out)
        self.assertEqual(sorted(p for p, _ in self.kills), [300, 301, 302, 303])

    async def test_refuses_system_pid1_kwin_plasmashell(self):
        for app in ("System",):
            with self.assertRaises(AdapterError) as cm:
                await self.run_verb("close", app=app)
            self.assertIn("won't close", str(cm.exception))
        self.assertEqual(self.kills, [])

    async def test_refuses_ariadne_and_the_app_hosting_this_process(self):
        for app in ("ariadne2", "Konsole"):                 # Konsole holds pid 402, our own
            with self.assertRaises(AdapterError):
                await self.run_verb("close", app=app)
        self.assertEqual(self.kills, [])
        self.assertEqual(self.sent, [])                      # nor was a window closed

    async def test_ariadne_cmdline_anywhere_protects_the_app(self):
        self.fp.add(700, "node", 10, cmd=["node", "/x/ariadne2/server.js"], unit="app-thing@1.service")
        self.fp.add(701, "thing", 700, cmd=["thing"], unit="app-thing@1.service")
        await self.a.refresh()
        with self.assertRaises(AdapterError):
            await self.run_verb("close", app="thing")
        self.assertEqual(self.kills, [])

    async def test_never_signals_a_protected_pid_in_a_group(self):
        # a protected process (kwin by name) that somehow sits in an app's group is skipped, and the group refused
        self.fp.add(710, "kwin_wayland", 10, cmd=["kwin_wayland"], unit="app-odd@1.service")
        self.fp.add(711, "odd", 10, cmd=["odd"], unit="app-odd@1.service")
        await self.a.refresh()
        with self.assertRaises(AdapterError):
            await self.run_verb("close", app="odd")
        self.assertEqual(self.kills, [])

    async def test_unknown_and_ambiguous_names(self):
        with self.assertRaises(AdapterError):
            await self.run_verb("close", app="nothing-like-this")
        with self.assertRaises(AdapterError):
            await self.run_verb("close", app="")
        self.fp.add(720, "dis", 10, cmd=["dis"], unit="app-dis@1.service")
        self.fp.add(721, "disk", 10, cmd=["disk"], unit="app-disk@1.service")
        await self.a.refresh()
        with self.assertRaises(AdapterError) as cm:
            await self.run_verb("focus", app="dis")           # exact match wins...
        self.assertIn("no window", str(cm.exception))
        with self.assertRaises(AdapterError) as cm:
            await self.run_verb("focus", app="di")            # ...a bare fragment of two doesn't
        self.assertIn("which one", str(cm.exception))

    async def test_focus(self):
        out = await self.run_verb("focus", app="discord")
        self.assertIn("Brought Discord", out)
        self.assertIn("activeWindow", self.sent[-1])
        self.assertIn('"{a}"', self.sent[-1])
        with self.assertRaises(AdapterError):
            await self.run_verb("focus", app="Steam")        # no window

    async def test_press_controls_run_unannounced(self):
        out = await self.a.press("focus", "Discord")
        self.assertIn("Brought", out)
        self.assertEqual([m for m in self.a.published if m.get("t") == "action"], [])
        self.assertEqual(self.a.press_args("close", "Steam"), {"app": "Steam"})
        await self.a.press("close", "Steam")
        self.assertTrue(self.kills)

    async def test_report(self):
        out = await self.run_verb("report")
        self.assertIn("Busiest:", out)
        self.assertIn("Most memory:", out)
        self.assertIn("Machine: CPU", out)
        few = await self.run_verb("report", n=1)
        self.assertEqual(few.count("MB"), 2 if "GPU" not in few else 3)       # one app + the memory line
        self.assertTrue(await self.run_verb("report", n=999))

    async def test_close_is_announced_for_her(self):
        await self.a.run("close", {"app": "discord"})
        phases = [(m["verb"], m["phase"], m.get("control")) for m in self.a.published if m.get("t") == "action"]
        self.assertEqual(phases, [("close", "started", "close"), ("close", "done", "close")])

    def test_close_description_says_confirm(self):
        self.assertIn("confirm", self.a.verb("close").description)


class Wiring(unittest.TestCase):
    def test_registered_everywhere(self):
        self.assertIn("tasks", protocol.WIDGETS)
        self.assertIn("tasks", layout.DEFAULT)
        self.assertEqual(layout.clamp(layout.DEFAULT["tasks"]), layout.DEFAULT["tasks"])
        reg = adapters.load_adapters(None, only=["tasks"])
        self.assertIn("tasks", reg)
        names = {t["name"] for t in adapters.tools(reg)}
        self.assertEqual(names, {"tasks_report", "tasks_focus", "tasks_close"})

    def test_default_rect_overlaps_nothing(self):
        def hit(a, b):
            return a[0] < b[0] + b[2] and b[0] < a[0] + a[2] and a[1] < b[1] + b[3] and b[1] < a[1] + a[3]
        t = layout.DEFAULT["tasks"]
        for n, r in layout.DEFAULT.items():
            if n != "tasks":
                self.assertFalse(hit(t, r), n)


class RealProc(unittest.TestCase):
    def test_reads_this_machines_proc(self):
        s = ProcSampler()
        procs, cpu, mem = s.read()
        mine = [p for p in procs if p.pid == os.getpid()]
        self.assertEqual(len(mine), 1)
        self.assertTrue(0 <= mem <= 100)
        self.assertGreater(mine[0].rss_mb, 0)


if __name__ == "__main__":
    unittest.main()
