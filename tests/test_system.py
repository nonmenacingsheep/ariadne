import asyncio
import os
import tempfile
import types
import unittest
from unittest import mock

from ariadne2 import protocol
from ariadne2.adapters import system as sysmod
from ariadne2.adapters.system import SystemAdapter
from ariadne2.core import server as server_mod
from ariadne2.core.server import CoreServer


def disk(name, free, used_pct=50.0):
    return {"name": name, "path": "/" + name, "used_pct": used_pct, "free_gb": free}


class FakeSampler:
    def __init__(self):
        self.cpu = 10.0

    def snapshot(self):
        return {"cpu": self.cpu, "mem": 41.0, "mem_used_gb": 6.5, "mem_total_gb": 15.8}


class ParseTests(unittest.TestCase):
    def test_gpu(self):
        self.assertEqual(sysmod.parse_gpu("41, 5561, 12282\n"), (41.0, 45.3))
        self.assertEqual(sysmod.parse_gpu("7, 100, 200\n90, 1, 2\n"), (7.0, 50.0))      # the first card
        for bad in ("", "No devices were found", "a, b, c", "1, 2", "5, 10, 0"):
            util, mem = sysmod.parse_gpu(bad)
            self.assertIsNone(mem, bad)
        self.assertEqual(sysmod.parse_gpu("5, 10, 0"), (5.0, None))

    def test_disk_row_like_df(self):
        st = types.SimpleNamespace(f_blocks=1000, f_bfree=200, f_bavail=100, f_frsize=1024 ** 3)
        with mock.patch.object(sysmod.os, "statvfs", return_value=st):
            row = sysmod.disk_row("Home", "/h")
        self.assertEqual(row, {"name": "Home", "path": "/h", "used_pct": 88.9, "free_gb": 100.0})
        with mock.patch.object(sysmod.os, "statvfs", side_effect=OSError):
            self.assertIsNone(sysmod.disk_row("Home", "/h"))

    def test_scan_disks_names_by_label_and_skips_non_mounts_and_same_device(self):
        with tempfile.TemporaryDirectory() as t:
            home, mnt = os.path.join(t, "home"), os.path.join(t, "mnt")
            for d in ("home", "mnt/games", "mnt/plain", "mnt/bind", "mnt/nolabel"):
                os.makedirs(os.path.join(t, d))
            real_stat = os.stat
            devs = {os.path.join(mnt, "games"): 11, os.path.join(mnt, "bind"): 5, os.path.join(mnt, "nolabel"): 12}

            def stat(path, *a, **k):
                r = real_stat(path, *a, **k)
                dev = 5 if path == home else devs.get(str(path))
                return types.SimpleNamespace(st_dev=dev, st_mode=r.st_mode) if dev else r
            mounted = {os.path.join(mnt, n) for n in ("games", "bind", "nolabel")}
            labels = {os.path.join(mnt, "games"): "Olympus"}
            with mock.patch.object(sysmod.os, "stat", stat), \
                    mock.patch.object(sysmod.os.path, "ismount", lambda p: p in mounted):
                rows = sysmod.scan_disks(home, mnt, label=labels.get)
        self.assertEqual([r["name"] for r in rows], ["Home", "Olympus", "Nolabel"])
        self.assertEqual(rows[1]["path"], os.path.join(mnt, "games"))
        for r in rows:
            self.assertEqual(set(r), {"name", "path", "used_pct", "free_gb"})

    def test_low_and_recovered(self):
        self.assertTrue(sysmod.is_low(disk("a", 9.9, 10)))
        self.assertTrue(sysmod.is_low(disk("a", 50, 96)))            # 4% free of a big disk
        self.assertFalse(sysmod.is_low(disk("a", 10.0, 90)))
        self.assertFalse(sysmod.recovered(disk("a", 10.5, 50)))
        self.assertTrue(sysmod.recovered(disk("a", 12, 50)))


class EventTests(unittest.TestCase):
    def make(self):
        a = SystemAdapter(self.publish, sampler=FakeSampler(), gpu=self.gpu, disks=lambda: [])
        self.events = []
        a.subscribe(lambda n, f: self.events.append((n, f)))
        return a

    async def publish(self, m):
        pass

    async def gpu(self):
        return None, None

    def sample(self, cpu=10.0, disks=()):
        return {"cpu": cpu, "disks": list(disks)}

    def test_disk_low_fires_once_per_crossing(self):
        a = self.make()
        a.observe(self.sample(disks=[disk("Home", 50), disk("Olympus", 30)]), 0)
        a.observe(self.sample(disks=[disk("Home", 50), disk("Olympus", 9.5)]), 2)
        self.assertEqual(self.events, [("system.disk_low", {"name": "Olympus", "free_gb": 9.5})])
        a.observe(self.sample(disks=[disk("Home", 50), disk("Olympus", 9.0)]), 4)
        a.observe(self.sample(disks=[disk("Home", 50), disk("Olympus", 10.4)]), 6)      # between the lines
        a.observe(self.sample(disks=[disk("Home", 50), disk("Olympus", 9.8)]), 8)       # still the same crossing
        self.assertEqual(len(self.events), 1)
        a.observe(self.sample(disks=[disk("Home", 50), disk("Olympus", 20)]), 10)       # recovered
        a.observe(self.sample(disks=[disk("Home", 50), disk("Olympus", 8)]), 12)
        self.assertEqual([f["free_gb"] for _, f in self.events], [9.5, 8])

    def test_already_low_at_start_is_not_news(self):
        a = self.make()
        a.observe(self.sample(disks=[disk("Olympus", 6.3, 99.2)]), 0)
        a.observe(self.sample(disks=[disk("Olympus", 6.2, 99.2)]), 2)
        self.assertEqual(self.events, [])

    def test_percent_threshold(self):
        a = self.make()
        a.observe(self.sample(disks=[disk("Big", 400, 90)]), 0)
        a.observe(self.sample(disks=[disk("Big", 40, 96)]), 2)          # 40 GB but only 4% free
        self.assertEqual([n for n, _ in self.events], ["system.disk_low"])

    def test_cpu_hot_after_thirty_seconds_once(self):
        a = self.make()
        for t in range(0, 30, 2):
            a.observe(self.sample(cpu=95), t)
        self.assertEqual(self.events, [])
        a.observe(self.sample(cpu=95), 30)
        self.assertEqual(self.events, [("system.cpu_hot", {"percent": 95})])
        for t in range(32, 80, 2):
            a.observe(self.sample(cpu=99), t)
        self.assertEqual(len(self.events), 1)

    def test_cpu_dip_restarts_the_clock_and_rearms_when_cool(self):
        a = self.make()
        for t in (0, 10, 20):
            a.observe(self.sample(cpu=95), t)
        a.observe(self.sample(cpu=50), 25)                       # dip: clock restarts
        for t in (30, 40, 50, 59):
            a.observe(self.sample(cpu=95), t)
        self.assertEqual(self.events, [])
        a.observe(self.sample(cpu=95), 61)
        self.assertEqual(len(self.events), 1)
        a.observe(self.sample(cpu=85), 62)                       # not cool enough to re-arm
        a.observe(self.sample(cpu=95), 63)
        a.observe(self.sample(cpu=95), 100)
        self.assertEqual(len(self.events), 1)
        a.observe(self.sample(cpu=40), 101)
        a.observe(self.sample(cpu=95), 102)
        a.observe(self.sample(cpu=95), 133)
        self.assertEqual(len(self.events), 2)


class AdapterTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.sent = []
        self.gpu_reads = 0

        async def publish(m):
            self.sent.append(m)

        async def gpu():
            self.gpu_reads += 1
            return 33.0, 44.0
        self.sampler = FakeSampler()
        self.disks = [disk("Home", 80, 40), disk("Olympus", 200, 70)]
        self.a = SystemAdapter(publish, sampler=self.sampler, gpu=gpu, disks=lambda: self.disks)
        self.a.mono = lambda: 0.0

    async def test_state_keeps_old_fields_and_adds_new(self):
        await self.a.refresh()
        s = self.a.state()
        self.assertEqual(set(s), {"cpu", "mem", "mem_used_gb", "mem_total_gb", "gpu", "gpu_mem", "disks"})
        self.assertEqual((s["gpu"], s["gpu_mem"]), (33.0, 44.0))
        self.assertEqual([d["name"] for d in s["disks"]], ["Home", "Olympus"])
        msg = self.sent[-1]
        self.assertEqual((msg["t"], msg["widget"]), ("state", "system"))
        protocol.decode(protocol.encode(msg))

    async def test_no_gpu_is_null(self):
        async def none():
            return None, None
        self.a._gpu = none
        await self.a.refresh()
        self.assertEqual((self.a.state()["gpu"], self.a.state()["gpu_mem"]), (None, None))
        self.assertIn("no GPU reading", await self.a.run("report"))

    async def test_publishes_only_on_change_but_always_first(self):
        await self.a.refresh()
        await self.a.refresh()
        self.assertEqual(len(self.sent), 1)
        self.sampler.cpu = 55.0
        await self.a.refresh()
        self.assertEqual(len(self.sent), 2)

    async def test_gpu_read_every_other_round(self):
        for _ in range(4):
            await self.a.refresh()
        self.assertEqual(self.gpu_reads, 2)

    async def test_report_text_and_no_announce_noise_besides_wire(self):
        self.disks = [disk("Home", 80, 40), disk("Olympus", 6.3, 99.2)]
        await self.a.refresh()
        out = await self.a.run("report")
        self.assertIn("CPU 10%", out)
        self.assertIn("Olympus is 99% full with 6.3 GB free (low)", out)
        self.assertNotIn("Home is 40% full with 80.0 GB free (low)", out)

    async def test_refresh_emits_disk_low_through_the_loop(self):
        events = []
        self.a.subscribe(lambda n, f: events.append((n, f)))
        await self.a.refresh()
        self.disks = [disk("Home", 80, 40), disk("Olympus", 4, 99)]
        await self.a.refresh()
        self.assertEqual(events, [("system.disk_low", {"name": "Olympus", "free_gb": 4})])

    async def test_catalog_replaces_placeholder(self):
        from ariadne2.core.flows.catalog import Catalog
        cat = Catalog.build({"system": self.a})
        self.assertEqual(cat.get("system.disk_low").kind, "event")
        self.assertTrue(cat.get("system.disk_low").available)
        self.assertIn("system.cpu_hot", cat)
        self.assertIn("system.gpu", cat.reads)


class ServerHandoverTests(unittest.IsolatedAsyncioTestCase):
    async def test_server_stops_publishing_system_once_an_adapter_does(self):
        with tempfile.TemporaryDirectory() as t, mock.patch.object(server_mod, "SYSTEM_PERIOD", 0.02):
            s = CoreServer(path=os.path.join(t, "run", "core.sock"))
            await s.start()
            try:
                await asyncio.sleep(0.1)
                self.assertNotIn("gpu", s.snapshots["system"])
                self.assertFalse(s._system_owned)
                await s.publish(protocol.state("system", {"cpu": 1.0, "mem": 2.0, "mem_used_gb": 3.0,
                                                          "mem_total_gb": 4.0, "gpu": 5.0, "gpu_mem": 6.0,
                                                          "disks": []}))
                self.assertTrue(s._system_owned)
                await asyncio.sleep(0.15)
                self.assertEqual(s.snapshots["system"]["gpu"], 5.0)       # the loop did not overwrite it
            finally:
                await s.stop()


if __name__ == "__main__":
    unittest.main()
