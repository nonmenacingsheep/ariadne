import array
import subprocess
import unittest

from ariadne2.core.ears import mic
from ariadne2.core.ears.mic import FRAME_BYTES, FRAME_MS, Segmenter, rms


def frame(amp):
    return array.array("h", [amp] * (FRAME_BYTES // 2)).tobytes()


class FakePopen:
    spawned = []

    def __init__(self, argv, *a, **k):
        self.argv = argv
        FakePopen.spawned.append(argv[0])
        self.stdout = type("S", (), {"read": staticmethod(lambda n: b"\x01\x00" * (n // 2))})()

    def terminate(self): pass
    def wait(self, timeout=None): return 0
    def kill(self): pass


class Recorder(unittest.TestCase):
    def setUp(self):
        mic.forget_proof()
        FakePopen.spawned = []
        self.addCleanup(mic.forget_proof)

    def test_proving_a_recorder_starts_one_once(self):
        which = lambda name: "/usr/bin/" + name
        first = mic.find_recorder(popen=FakePopen, which=which)
        self.assertEqual(first[0], "parecord")
        for _ in range(50):
            mic.find_recorder(popen=FakePopen, which=which)
        self.assertEqual(len(FakePopen.spawned), 1)
        mic.find_recorder(fresh=True, popen=FakePopen, which=which)
        self.assertEqual(len(FakePopen.spawned), 2)

    def test_status_checks_start_nothing(self):
        for _ in range(80):
            mic.recorder_installed(which=lambda n: "/usr/bin/" + n)
        self.assertEqual(FakePopen.spawned, [])

    def test_a_recorder_that_returns_no_audio_is_skipped(self):
        class Silent(FakePopen):
            def __init__(self, argv, *a, **k):
                super().__init__(argv)
                self.stdout = type("S", (), {"read": staticmethod(lambda n: b"")})()
        self.assertIsNone(mic.find_recorder(popen=Silent, which=lambda n: "/usr/bin/" + n))
        self.assertGreaterEqual(len(FakePopen.spawned), 2)      # tried several, none worked

    def test_nothing_installed(self):
        self.assertIsNone(mic.find_recorder(popen=FakePopen, which=lambda n: None))
        self.assertFalse(mic.recorder_installed(which=lambda n: None))


class Bluetooth(unittest.TestCase):
    def run_with(self, out, code=0):
        def run(argv, **k):
            return subprocess.CompletedProcess(argv, code, stdout=out)
        return mic.bluetooth_mic(run)

    def test_bluez_source_is_bluetooth(self):
        self.assertTrue(mic.is_bluetooth_source("bluez_input.AA_BB.0"))
        self.assertTrue(self.run_with("bluez_input.AA_BB_CC.0\n"))

    def test_other_sources_are_not(self):
        self.assertFalse(mic.is_bluetooth_source("alsa_input.usb-Blue_Yeti-00.analog-stereo"))
        self.assertFalse(self.run_with("alsa_input.usb-Blue_Yeti\n"))
        self.assertFalse(mic.is_bluetooth_source(""))
        self.assertFalse(mic.is_bluetooth_source(None))

    def test_unknown_when_pactl_is_missing_or_fails(self):
        def missing(argv, **k):
            raise FileNotFoundError
        self.assertFalse(mic.bluetooth_mic(missing))
        self.assertFalse(self.run_with("", code=1))
        self.assertIsNone(mic.default_source(missing))

    def test_falls_back_to_the_host_pactl(self):
        calls = []

        def run(argv, **k):
            calls.append(argv[0])
            if argv[0] == "pactl":
                raise FileNotFoundError
            return subprocess.CompletedProcess(argv, 0, stdout="bluez_input.x\n")
        self.assertTrue(mic.bluetooth_mic(run))
        self.assertEqual(calls, ["pactl", "/run/host/usr/bin/pactl"])


class Gate(unittest.TestCase):
    def feed(self, seg, amps, **kw):
        out = []
        for a in amps:
            u = seg.feed(frame(a), **kw)
            if u:
                out.append(u)
        return out

    def test_rms(self):
        self.assertAlmostEqual(rms(frame(1000)), 1000.0)
        self.assertEqual(rms(b""), 0.0)

    def test_silence_makes_no_utterance(self):
        self.assertEqual(self.feed(Segmenter(), [10] * 200), [])

    def test_speech_then_silence_makes_one_utterance_with_lead_in(self):
        s = Segmenter()
        out = self.feed(s, [10] * 20 + [2000] * 15 + [10] * 20)
        self.assertEqual(len(out), 1)
        u = out[0]
        self.assertFalse(u.interrupting)
        self.assertGreaterEqual(len(u.pcm), (10 + 15) * FRAME_BYTES)     # lead-in kept
        self.assertEqual(u.ms, 15 * FRAME_MS)

    def test_a_clipped_word_survives_via_hysteresis(self):
        s = Segmenter()
        # loud, then half-gate-level frames that still count as the word
        out = self.feed(s, [10] * 20 + [2000] * 3 + [150] * 2 + [10] * 20)
        self.assertEqual(len(out), 1)

    def test_too_short_when_asleep_is_dropped_but_not_when_awake(self):
        asleep = self.feed(Segmenter(), [10] * 20 + [2000] * 1 + [10] * 20)
        awake = self.feed(Segmenter(), [10] * 20 + [2000] * 1 + [10] * 20, awake=True)
        self.assertEqual(asleep, [])                  # 32ms is under the 80ms minimum: a click
        self.assertEqual(len(awake), 1)               # "send" is short; the model decides

    def test_speech_started_over_her_voice_is_marked(self):
        s = Segmenter()
        out = self.feed(s, [10] * 12 + [2000] * 10 + [10] * 20, her_voice=True)
        self.assertTrue(out and out[0].interrupting)

    def test_threshold_follows_the_room(self):
        s = Segmenter()
        self.feed(s, [100] * 300)                     # a noisy room
        self.assertGreater(s.threshold(), 180)
        self.assertEqual(self.feed(s, [250] * 30 + [100] * 20), [])   # not speech in this room

    def test_first_frame_cannot_seed_the_floor_with_speech(self):
        s = Segmenter()
        s.feed(frame(9000))
        self.assertLessEqual(s.floor, mic.SPEECH_RMS)

    def test_a_long_utterance_is_cut_at_the_cap(self):
        s = Segmenter()
        out = self.feed(s, [10] * 12 + [2000] * (mic.MAX_UTTERANCE_S * 1000 // FRAME_MS + 5))
        self.assertGreaterEqual(len(out), 1)


if __name__ == "__main__":
    unittest.main()
