"""Adding Live2D bodies: the importer, the drop folder and the Files menu."""
import asyncio
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from ariadne2 import protocol
from ariadne2.pet2d import importer as I


def vts_model(root: Path, name="Mika") -> Path:
    """A VTube Studio-shaped download: expressions not listed, empty groups, one broken expression."""
    d = root / "download" / name
    d.mkdir(parents=True)
    (d / f"{name}.moc3").write_bytes(b"MOC3")
    (d / f"{name}.model3.json").write_text(json.dumps({"Version": 3, "FileReferences": {
        "Moc": f"{name}.moc3", "Textures": [], "DisplayInfo": f"{name}.cdi3.json"},
        "Groups": [{"Target": "Parameter", "Name": "EyeBlink", "Ids": []}]}))
    (d / f"{name}.cdi3.json").write_text(json.dumps({"Parameters": [
        {"Id": "ParamEyeLOpen"}, {"Id": "ParamEyeROpen"}, {"Id": "ParamMouthOpenY"}]}))
    for exp in ("Angry", "StarEyes", "Cry", "Wave"):
        (d / f"{exp}.exp3.json").write_text(json.dumps({"Type": "Live2D Expression", "Parameters": []}))
    (d / "Heart.exp3.json").write_text("")          # damaged in the archive
    (d / "readme.exe").write_bytes(b"MZ")            # not ours to keep
    return d


class ImporterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.models = self.tmp / "models"

    def test_a_zipped_download_becomes_a_body(self):
        src = vts_model(self.tmp)
        zpath = self.tmp / "Mika_v2.zip"
        with zipfile.ZipFile(zpath, "w") as z:
            for p in src.rglob("*"):
                z.write(p, Path("Mika_v2") / "inner" / p.relative_to(src))
        slug, said = I.import_model(zpath, self.models)
        self.assertEqual(slug, "mika")
        self.assertIn("skipped broken expression: Heart", said)
        d = self.models / slug
        m = json.loads((d / "Mika.model3.json").read_text())
        names = {e["Name"] for e in m["FileReferences"]["Expressions"]}
        self.assertEqual(names, {"Angry", "StarEyes", "Cry", "Wave"})
        groups = {g["Name"]: g["Ids"] for g in m["Groups"]}
        self.assertEqual(groups, {"EyeBlink": ["ParamEyeLOpen", "ParamEyeROpen"], "LipSync": ["ParamMouthOpenY"]})
        about = json.loads((d / "about.json").read_text())
        self.assertEqual(about["looks"], {"angry": "Angry", "stars": "StarEyes", "tears": "Cry"})
        self.assertFalse((d / "readme.exe").exists())

    def test_a_folder_imports_twice_as_two(self):
        src = vts_model(self.tmp)
        self.assertEqual(I.import_model(src, self.models)[0], "mika")
        self.assertEqual(I.import_model(src, self.models)[0], "mika_2")

    def test_a_zip_that_escapes_its_folder_is_refused(self):
        zpath = self.tmp / "evil.zip"
        with zipfile.ZipFile(zpath, "w") as z:
            z.writestr("../../escaped.txt", "x")
            z.writestr("m/a.model3.json", "{}")
        with self.assertRaises(I.ImportError_):
            I.import_model(zpath, self.models)
        self.assertFalse((self.tmp / "escaped.txt").exists())

    def test_no_model_inside_says_so(self):
        zpath = self.tmp / "photos.zip"
        with zipfile.ZipFile(zpath, "w") as z:
            z.writestr("cat.png", "x")
        with self.assertRaisesRegex(I.ImportError_, "no Live2D model"):
            I.import_model(zpath, self.models)


class DropFolderTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from ariadne2.core import body_models as B
        self.B = B
        self.tmp = Path(tempfile.mkdtemp())
        self.drop = self.tmp / "Aries Models"
        env = mock.patch.dict(os.environ, {"ARIADNE2_MODELS_DIR": str(self.drop), "XDG_DATA_HOME": str(self.tmp / "data")})
        env.start(); self.addCleanup(env.stop)
        models = mock.patch.object(I, "MODELS", self.tmp / "models")
        models.start(); self.addCleanup(models.stop)
        self.sent, self.set = [], []

        async def publish(m):
            protocol.decode(protocol.encode(m))
            self.sent.append(m)
        settings = mock.Mock()
        settings.message.return_value = {"t": "settings", "schema": [], "values": {}}
        settings.set.side_effect = lambda *a: self.set.append(a)
        self.bm = B.BodyModels(publish, settings)

    async def test_a_download_in_the_drop_folder_is_added_once(self):
        await self.bm.scan()                                   # makes the folder and its README
        self.assertTrue((self.drop / "README.txt").exists())
        src = vts_model(self.tmp)
        os.rename(src, self.drop / "Mika")
        await self.bm.scan()
        await self.bm.scan()                                   # stays there; not added again
        said = [m["delta"] for m in self.sent if m["t"] == "chat"]
        self.assertEqual(len(said), 1)
        self.assertIn("Added Mika", said[0])
        self.assertIn("Avatar > Model", said[0])
        self.assertTrue((self.tmp / "models" / "mika" / "about.json").exists())
        self.assertEqual(self.set, [])                         # added, not worn

    async def test_use_as_her_body_switches_to_it(self):
        src = vts_model(self.tmp)
        slug = await self.bm.add(src, wear=True)
        self.assertEqual(self.set, [("avatar", "model", slug)])
        self.assertIn("wearing it now", [m for m in self.sent if m["t"] == "chat"][-1]["delta"])


class NoBodyTests(DropFolderTests):
    async def test_switches_to_a_live2d_body_when_the_3d_one_cant_run(self):
        self.bm.settings.get.side_effect = lambda s, k: {"model": "aries", "body": True}[k]
        with mock.patch.object(self.bm, "_three_d_ready", return_value=False), \
             mock.patch.object(self.bm, "_live2d_ready", return_value=["mika"]):
            await self.bm.check_body()
        self.assertEqual(self.set, [("avatar", "model", "mika")])

    async def test_says_once_when_there_is_no_body_at_all(self):
        self.bm.settings.get.side_effect = lambda s, k: {"model": "aries", "body": True}[k]
        with mock.patch.object(self.bm, "_three_d_ready", return_value=False), \
             mock.patch.object(self.bm, "_live2d_ready", return_value=[]):
            await self.bm.check_body()
            await self.bm.check_body()
        said = [m["delta"] for m in self.sent if m["t"] == "chat"]
        self.assertEqual(said, [self.B.NO_BODY])

    async def test_a_working_body_is_left_alone(self):
        self.bm.settings.get.side_effect = lambda s, k: {"model": "aries", "body": True}[k]
        with mock.patch.object(self.bm, "_three_d_ready", return_value=True):
            await self.bm.check_body()
        self.assertEqual((self.set, self.sent), ([], []))


class Live2DSupportTests(DropFolderTests):
    async def test_download_puts_the_core_in_place(self):
        core = self.tmp / "vendor" / "live2dcubismcore.min.js"

        class Reply:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self, n): return b"/**\n * Live2D Cubism Core\n */ var Live2DCubismCore;"
        with mock.patch.object(self.B, "CORE", core), mock.patch("urllib.request.urlopen", return_value=Reply()):
            self.assertEqual(self.bm.core_status(), "Not installed")
            await self.bm.get_core()
            self.assertEqual(self.bm.core_status(), "Installed")
        self.assertIn(b"Cubism Core", core.read_bytes())
        self.assertIn("installed", [m for m in self.sent if m["t"] == "chat"][-1]["delta"])

    async def test_a_live2d_body_without_the_core_says_what_is_missing(self):
        (self.tmp / "models" / "jane").mkdir(parents=True)
        self.bm.settings.get.side_effect = lambda s, k: {"model": "jane", "body": True}[k]
        with mock.patch.object(self.B, "CORE", self.tmp / "nope.js"):
            await self.bm.check_body()
        self.assertEqual([m["delta"] for m in self.sent if m["t"] == "chat"], [self.B.NEEDS_CORE])

    async def test_adding_a_model_without_the_core_says_so(self):
        with mock.patch.object(self.B, "CORE", self.tmp / "nope.js"):
            await self.bm.add(vts_model(self.tmp))
        self.assertIn("Live2D support", [m for m in self.sent if m["t"] == "chat"][-1]["delta"])


if __name__ == "__main__":
    unittest.main()
