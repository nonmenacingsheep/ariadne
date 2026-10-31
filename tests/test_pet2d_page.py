"""The Live2D page's script must start: a mistake in it leaves her body blank, silently."""
import shutil
import subprocess
import unittest
from pathlib import Path

PAGE = Path(__file__).resolve().parents[1] / "ariadne2" / "pet2d" / "web" / "pet2d.js"
RUN = r"""
const fs = require("fs");
global.window = global; global.innerWidth = 1920; global.innerHeight = 1080;
global.addEventListener = () => {}; global.performance = { now: () => Date.now() };
global.document = { body: { appendChild() {} }, querySelector: () => null };
global.requestAnimationFrame = () => 0;
(0, eval)(fs.readFileSync(process.argv[1], "utf8") + "\n;globalThis.__pet = pet;");
const p = globalThis.__pet;
for (const k of ["load", "message", "settings", "layout", "feel", "beat"]) if (typeof p[k] !== "function") throw new Error("no pet." + k);
p.message({ t: "speak", emotion: "excited", seconds: 2 });   // before a model: must not throw
console.log("ok");
"""


@unittest.skipUnless(shutil.which("node"), "needs node")
class PageStarts(unittest.TestCase):
    def test_the_script_defines_her_body(self):
        out = subprocess.run(["node", "-e", RUN, str(PAGE)], capture_output=True, text=True, timeout=30)
        self.assertEqual(out.stdout.strip(), "ok", out.stderr[-800:])


if __name__ == "__main__":
    unittest.main()
