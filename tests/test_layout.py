import json
import os
import pathlib
import tempfile
import unittest

from ariadne2.desk import layout


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.file = pathlib.Path(self.tmp.name) / "sub" / "layout.json"
        self._old = os.environ.get("ARIADNE2_LAYOUT")
        os.environ["ARIADNE2_LAYOUT"] = str(self.file)
        self.addCleanup(self._restore)

    def _restore(self):
        if self._old is None:
            os.environ.pop("ARIADNE2_LAYOUT", None)
        else:
            os.environ["ARIADNE2_LAYOUT"] = self._old

    def write(self, text):
        self.file.parent.mkdir(parents=True, exist_ok=True)
        self.file.write_text(text)


class Geometry(unittest.TestCase):
    def test_snap(self):
        self.assertEqual(layout.snap(0), 0)
        self.assertEqual(layout.snap(11), 0)
        self.assertEqual(layout.snap(13), 24)
        self.assertEqual(layout.snap(100.4), 96)
        self.assertEqual(layout.snap(-30), -24)

    def test_clamp_off_screen(self):
        self.assertEqual(layout.clamp((-50, -50, 300, 200)), (0, 0, 300, 200))
        self.assertEqual(layout.clamp((3400, 1400, 300, 200)), (3140, 1240, 300, 200))

    def test_clamp_too_small(self):
        self.assertEqual(layout.clamp((10, 10, 5, 5)), (10, 10, 192, 96))

    def test_clamp_too_big(self):
        self.assertEqual(layout.clamp((100, 100, 9000, 9000)), (0, 0, 3440, 1440))

    def test_defaults_on_screen(self):
        for name, r in layout.DEFAULT.items():
            self.assertEqual(layout.clamp(r), r, name)


class Storage(Base):
    def test_missing_file(self):
        self.assertEqual(layout.load(), layout.DEFAULT)

    def test_corrupt(self):
        for junk in ("{not json", "[]", '{"widgets": 5}', ""):
            self.write(junk)
            self.assertEqual(layout.load(), layout.DEFAULT, junk)

    def test_partial_and_unknown(self):
        self.write(json.dumps({"version": 1, "widgets": {
            "chat": [48, 48, 400, 400],
            "ghost": [0, 0, 300, 300],
            "steam": [1, 2, 3],
            "spotify": "nope",
            "system": [0, 0, True, 300],
            "core": [-100, 0, 560, 144],
        }}))
        got = layout.load()
        self.assertEqual(got["chat"], (48, 48, 400, 400))
        self.assertNotIn("ghost", got)
        self.assertEqual(got["steam"], layout.DEFAULT["steam"])
        self.assertEqual(got["spotify"], layout.DEFAULT["spotify"])
        self.assertEqual(got["system"], layout.DEFAULT["system"])
        self.assertEqual(got["core"], (0, 0, 560, 144))
        self.assertEqual(got["browser"], layout.DEFAULT["browser"])

    def test_round_trip(self):
        lay = layout.load()
        lay["chat"] = (240, 48, 480, 480)
        layout.save(lay)
        data = json.loads(self.file.read_text())
        self.assertEqual(data["version"], 1)
        self.assertEqual(data["widgets"]["chat"], [240, 48, 480, 480])
        self.assertEqual(layout.load(), lay)
        self.assertEqual([p.name for p in self.file.parent.iterdir()], ["layout.json"])

    def test_reset(self):
        layout.save({"chat": (240, 48, 480, 480)})
        self.assertTrue(self.file.exists())
        self.assertEqual(layout.reset(), layout.DEFAULT)
        self.assertFalse(self.file.exists())
        layout.reset()  # no file: still fine

    def test_path_xdg(self):
        os.environ.pop("ARIADNE2_LAYOUT")
        old = os.environ.get("XDG_CONFIG_HOME")
        os.environ["XDG_CONFIG_HOME"] = "/cfg"
        try:
            self.assertEqual(str(layout.path()), "/cfg/ariadne2/layout.json")
        finally:
            if old is None:
                os.environ.pop("XDG_CONFIG_HOME")
            else:
                os.environ["XDG_CONFIG_HOME"] = old


if __name__ == "__main__":
    unittest.main()
