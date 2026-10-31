"""Her body as a tool: reading where it is, and sending it commands."""
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from ariadne2 import protocol
from ariadne2.adapters import AdapterError
from ariadne2.adapters import avatar as A


class AvatarTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        env = mock.patch.dict(os.environ, {"XDG_DATA_HOME": str(self.tmp / "data")})
        env.start(); self.addCleanup(env.stop)
        cfg = self.tmp / ".config" / "ariadne2"; cfg.mkdir(parents=True)
        (cfg / "layout.json").write_text(json.dumps({"version": 1, "widgets": {
            "spotify": [2664, 24, 736, 325], "chat": [24, 23, 736, 883], "claude": [960, 744, 736, 441],
            "core": [1464, 48, 560, 139]}}))
        (cfg / "hidden.json").write_text(json.dumps(["claude"]))
        home = mock.patch.object(Path, "home", return_value=self.tmp)
        home.start(); self.addCleanup(home.stop)
        self.sent = []

        async def publish(m):
            protocol.decode(protocol.encode(m))
            self.sent.append(m)
        self.a = A.AvatarAdapter(publish)
        self.a.settle = 0

    def cmds(self):
        return [m for m in self.sent if m["t"] == "body"]

    def body(self, **kw):
        d = {"kind": "live2d", "model": "简", "x": 2900, "y": 24, "w": 3440, "h": 1400, "mode": "stand",
             "on": "spotify", "look": "smile", "dancing": False, "asleep": False, "ts": time.time()}
        d.update(kw)
        p = A.status_path(); p.parent.mkdir(parents=True, exist_ok=True); p.write_text(json.dumps(d))

    async def test_status_says_where_and_what(self):
        self.body()
        out = await self.a.run("status", {})
        self.assertIn("简 (Live2D)", out)
        self.assertIn("on top of the spotify widget", out)
        self.assertIn("right of the screen", out)

    async def test_no_body_running(self):
        self.assertIn("isn't on screen", await self.a.run("status", {}))
        self.body(ts=time.time() - 60)                        # stale: the body stopped
        with self.assertRaises(AdapterError):
            await self.a.run("go", {"to": "spotify"})

    async def test_go_onto_a_widget_by_name(self):
        self.body()
        out = await self.a.run("go", {"to": "spot"})
        self.assertIn("Jumping onto the spotify widget", out)
        self.assertEqual(self.cmds()[-1], {"t": "body", "cmd": "go", "widget": "spotify"})
        with self.assertRaises(AdapterError):                 # hidden in the drawer: nothing to stand on
            await self.a.run("go", {"to": "claude"})
        with self.assertRaises(AdapterError):                 # the core has no top to stand on
            await self.a.run("go", {"to": "core"})

    async def test_go_to_a_side_or_a_place(self):
        self.body()
        await self.a.run("go", {"to": "left"})
        await self.a.run("go", {"to": "1200"})
        self.assertEqual(self.cmds()[-2:], [{"t": "body", "cmd": "go", "side": "left"},
                                          {"t": "body", "cmd": "go", "x": 1200.0}])

    async def test_dance_feel_sleep_and_pin(self):
        self.body()
        await self.a.run("dance", {"seconds": 9999})
        self.assertEqual(self.cmds()[-1]["seconds"], 300.0)     # capped
        await self.a.run("feel", {"look": "hearts"})
        self.assertEqual(self.cmds()[-1]["look"], "hearts")
        with self.assertRaises(AdapterError):
            await self.a.run("feel", {"look": "smug-ish"})
        self.a.settings = mock.Mock()
        await self.a.run("pin", {})
        self.a.settings.set.assert_called_with("avatar", "pinned", True)


if __name__ == "__main__":
    unittest.main()
