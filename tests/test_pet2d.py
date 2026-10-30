"""Her Live2D body: which model shows, and the Avatar setting that picks it."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ariadne2.core import settings as s


class BodiesTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        (self.root / "jian").mkdir()
        (self.root / "jian" / "jian.model3.json").write_text("{}")
        (self.root / "jian" / "about.json").write_text(json.dumps({"name": "简"}))
        (self.root / "empty").mkdir()                       # no model3.json: not a body

    def test_the_3d_body_first_then_each_live2d_model(self):
        with mock.patch.object(s, "LIVE2D_MODELS", self.root):
            self.assertEqual(s.bodies(), [("aries", "Aries (3D, walks about)"), ("jian", "简 (Live2D)")])
            entry = next(e for e in s.build_schema() if e["section"] == "avatar" and e["key"] == "model")
            self.assertEqual(entry["default"], "aries")
            self.assertEqual([o["value"] for o in entry["options"]], ["aries", "jian"])

    def test_choosing_a_model_is_validated_against_the_list(self):
        with mock.patch.object(s, "LIVE2D_MODELS", self.root):
            st = s.Settings(path=self.root / "settings.json")
            st.set("avatar", "model", "jian")
            self.assertEqual(st.get("avatar", "model"), "jian")
            with self.assertRaises(s.SettingsError):
                st.set("avatar", "model", "nobody")


class WantedTests(unittest.TestCase):
    def test_which_window_shows(self):
        try:
            from ariadne2.pet2d import __main__ as pet2d
        except (ImportError, ValueError) as e:              # no GTK 4 / WebKit 6 here
            self.skipTest(str(e))
        with mock.patch.object(pet2d, "live2d_models", return_value={"jian": "/m/jian.model3.json"}):
            self.assertIsNone(pet2d.wanted_model({}))                                   # default: the 3D body
            self.assertEqual(pet2d.wanted_model({"avatar": {"model": "jian"}}), "jian")
            self.assertIsNone(pet2d.wanted_model({"avatar": {"model": "jian"}, "desktop": {"body": False}}))
            self.assertIsNone(pet2d.wanted_model({"avatar": {"model": "gone"}}))       # deleted folder


if __name__ == "__main__":
    unittest.main()


class BeatTests(unittest.TestCase):
    def feed(self, bpm, seconds=10.0, hop=256 / 11025):
        from ariadne2.pet2d.beats import BeatTracker
        tr, hits, t, period = BeatTracker(), [], 0.0, 60.0 / bpm
        while t < seconds:
            kick = (t % period) < hop                      # one loud hop per beat, quiet between
            hit = tr.feed(900.0 if kick else 120.0 + 10 * ((int(t / hop) * 7) % 5), t)
            if hit:
                hits.append(hit)
            t += hop
        return hits

    def test_finds_the_tempo_of_a_steady_kick(self):
        for bpm in (96, 120, 140):
            hits = self.feed(bpm)
            self.assertGreater(len(hits), 10)
            self.assertAlmostEqual(hits[-1][0], 60.0 / bpm, delta=0.03)

    def test_silence_is_not_a_beat(self):
        from ariadne2.pet2d.beats import BeatTracker
        tr = BeatTracker()
        self.assertFalse([h for i in range(500) if (h := tr.feed(5.0 + (i % 3), i * 0.023))])

    def test_slow_tempos_fold_into_dance_range(self):
        from ariadne2.pet2d.beats import fold
        self.assertAlmostEqual(fold(1.0), 0.5)
        self.assertAlmostEqual(fold(0.25), 0.5)
