"""The wake model's path through the ears: a fake spotter that fires on a marked frame."""
import array
import asyncio
import unittest
from unittest import mock

import numpy as np

from ariadne2.core.ears import transcribe, wakeword
from ariadne2.core.ears.mic import FRAME_BYTES
from ariadne2.core.ears.transcribe import Transcriber
from ariadne2.core.ears.wakeword import Spotter
from tests.test_ears import Base, FakeTranscriber, speech, until

MARK = 2345                       # a loud frame the fake spotter takes for "wake Aries"


def phrase(ms=600):
    """Speech that ends with the wake model firing."""
    return speech(ms - 32) + [MARK]


class FakeSpotter:
    def __init__(self, fail=False):
        self.fail, self.fed, self.resets, self.loads, self.score = fail, 0, 0, 0, 0.0

    def available(self): return None
    def load(self): self.loads += 1
    def reset(self): self.resets += 1

    def feed(self, pcm):
        if self.fail:
            raise RuntimeError("onnx exploded")
        self.fed += 1
        hit = array.array("h", pcm[:2])[0] == MARK
        self.score = 0.9 if hit else 0.01
        return hit


class LazyTranscriber(FakeTranscriber):
    def __init__(self, *texts):
        super().__init__(*texts)
        self.prefetched, self.warmed, self.idle_checks = [], [], 0

    def prefetch(self, name): self.prefetched.append(name)
    def warm(self, name): self.warmed.append(name)
    def unload_idle(self, idle_s=transcribe.IDLE_UNLOAD_S):
        self.idle_checks += 1
        return ()


class Spotting(Base):
    def build(self, script=(), texts=(), spotter=None, **kw):
        tr = LazyTranscriber(*texts)
        super().build(script, texts, spotter=spotter or FakeSpotter(), transcriber=tr, **kw)
        self.tr, self.spot = tr, self.ears.spotter


class WakeModel(Spotting):

    async def test_the_phrase_alone_opens_without_whisper(self):
        self.build([10] * 20 + phrase() + [10] * 40)
        await self.go()
        self.assertTrue(await until(lambda: self.listening == [True]))
        self.assertEqual(self.tr.calls, [])                      # nothing was transcribed
        self.assertIn("cmd", self.tr.prefetched)                 # but the command model is on its way
        self.assertEqual(self.ears.wake_phrase, "wake Aries")
        self.assertIn("listening for wake Aries", self.status)

    async def test_only_the_wake_model_loads_at_start(self):
        self.build()
        await self.go()
        self.assertTrue(await until(lambda: self.spot.loads == 1))
        await asyncio.sleep(0.05)
        self.assertEqual(self.tr.warmed, [])                     # no Whisper until she is woken

    async def test_talk_without_the_phrase_is_never_transcribed(self):
        self.build([10] * 20 + speech(900) + [10] * 40 + speech(600) + [10] * 40,
                   texts=["hey aries open firefox"])
        await self.go()
        self.assertTrue(await until(lambda: self.mic.reads > 20 + 1500 // 32 + 80))
        await asyncio.sleep(0.05)
        self.assertEqual((self.tr.calls, self.heard, self.listening), ([], [], []))

    async def test_a_command_in_the_same_breath(self):
        self.build([10] * 20 + phrase() + speech(800) + [10] * 200,
                   texts=["Wake Aries, play something."])
        await self.go()
        self.assertTrue(await until(lambda: self.heard))
        self.assertEqual(self.heard, ["play something"])
        self.assertEqual(self.listening[0], True)
        model, hint, _n = self.tr.calls[0]
        self.assertEqual((model, hint.split(" ")[:2]), ("cmd", ["Wake", "Aries."]))

    async def test_when_whisper_misspells_the_phrase_only_what_followed_is_kept(self):
        self.build([10] * 20 + phrase() + speech(800) + [10] * 200,
                   texts=["Make a ruse, play something.", "play something"])
        await self.go()
        self.assertTrue(await until(lambda: self.heard))
        self.assertEqual(self.heard, ["play something"])
        whole, rest = self.tr.calls[0][2], self.tr.calls[1][2]
        self.assertLess(rest, whole)
        self.assertGreaterEqual(rest, 800 // 32 * FRAME_BYTES)

    async def test_a_breath_after_the_phrase_is_not_a_command(self):
        self.build([10] * 20 + phrase() + speech(96) + [10] * 300)
        await self.go()
        self.assertTrue(await until(lambda: self.listening == [True, False], timeout=4))
        self.assertEqual((self.tr.calls, self.heard), ([], []))

    async def test_over_her_voice_she_stops_at_once(self):
        voice = mock.Mock(speaking=True)
        self.build([10] * 20 + phrase() + speech(3000), voice=voice)
        await self.go()
        self.assertTrue(await until(lambda: voice.cancel.called))
        self.assertLess(self.mic.reads, 20 + (600 + 3000) // 32)     # before he stopped talking
        self.assertIn(transcribe.WAKE_MODEL, self.tr.prefetched)     # tiny.en, for a "skip"

    async def test_skip_over_her_voice_still_works(self):
        voice = mock.Mock(speaking=True)
        self.build([10] * 20 + speech(500) + [10] * 40, texts=["skip"], voice=voice)
        await self.go()
        self.assertTrue(await until(lambda: voice.cancel.called))
        self.assertEqual(self.tr.calls[0][0], transcribe.WAKE_MODEL)
        self.assertEqual(self.heard, [])

    async def test_while_she_works_the_phrase_interrupts(self):
        busy = {"on": True}
        interrupted = []
        self.build([10] * 20 + phrase() + [10] * 40, is_busy=lambda: busy["on"],
                   on_interrupt=lambda: interrupted.append(1))
        await self.go()
        self.assertTrue(await until(lambda: interrupted and self.listening == [True]))

    async def test_idle_models_are_looked_at_only_while_idle(self):
        self.build([10] * 2000)
        await self.go()
        self.assertTrue(await until(lambda: self.tr.idle_checks >= 1, timeout=4))

    async def test_idle_models_stay_while_she_talks(self):
        voice = mock.Mock(speaking=True)
        self.build([10] * 2000, voice=voice)
        await self.go()
        await asyncio.sleep(1.2)
        self.assertEqual(self.tr.idle_checks, 0)


class Fallback(Spotting):
    async def test_a_missing_model_logs_once_and_whisper_listens(self):
        script = [10] * 20 + speech(900)
        self.build(script, texts=["hey aries open firefox", "hey aries open firefox"],
                   spotter=Spotter(model="/nonexistent/wake_aries.onnx"))
        with self.assertLogs("ariadne2.ears", "WARNING") as logs:
            await self.go()
        self.assertEqual(len([o for o in logs.output if "wake model" in o]), 1)
        self.assertTrue(await until(lambda: self.heard))
        self.assertEqual(self.heard, ["open firefox"])
        self.assertEqual(self.tr.calls[0][0], transcribe.WAKE_MODEL)
        self.assertEqual(self.ears.wake_phrase, "hey Aries")

    async def test_a_model_that_breaks_hands_back_to_whisper(self):
        spot = FakeSpotter(fail=True)
        script = [10] * 20 + speech(900)
        self.build(script, texts=["hey aries open firefox", "hey aries open firefox"], spotter=spot)
        with self.assertLogs("ariadne2.ears", "WARNING") as logs:
            await self.go()
            self.assertTrue(await until(lambda: self.heard))
        self.assertEqual(self.heard, ["open firefox"])
        self.assertEqual(len([o for o in logs.output if "wake model failed" in o]), 1)
        self.assertIsNone(self.ears._spotting())

    async def test_another_name_is_listened_for_by_whisper(self):
        script = [10] * 20 + speech(900)
        self.build(script, texts=["hey ida open firefox", "hey ida open firefox"],
                   spotter=FakeSpotter(), name="Ida")
        await self.go()
        self.assertTrue(await until(lambda: self.heard))
        self.assertEqual(self.heard, ["open firefox"])
        self.assertEqual(self.ears.spotter.fed, 0)


class Lazy(unittest.TestCase):
    """The transcriber loads on demand and lets go of what sits idle."""

    def make(self):
        self.now = [0.0]
        built = []

        class Model:
            def __init__(m, name, device, compute_type):
                built.append((name, device))

            def transcribe(m, samples, **kw):
                return iter([]), None

        t = Transcriber(model_factory=Model, device=("cuda", "float16"), clock=lambda: self.now[0])
        return t, built

    def test_nothing_is_loaded_until_asked(self):
        t, built = self.make()
        self.assertEqual((t.loaded(), built), ((), []))

    def test_idle_models_are_unloaded_and_used_ones_kept(self):
        t, _ = self.make()
        t.hear(b"\0" * 3200, "large-v3-turbo", "")
        self.now[0] = 200.0
        t.hear(b"\0" * 3200, transcribe.WAKE_MODEL, "")
        self.now[0] = transcribe.IDLE_UNLOAD_S + 1
        self.assertEqual(t.unload_idle(), ("large-v3-turbo",))
        self.assertEqual(t.loaded(), (transcribe.WAKE_MODEL,))
        self.now[0] = 200.0 + transcribe.IDLE_UNLOAD_S
        self.assertEqual(t.unload_idle(), (transcribe.WAKE_MODEL,))
        self.assertEqual(t.unload_idle(), ())

    def test_prefetch_loads_in_the_background(self):
        t, built = self.make()
        t.prefetch("large-v3-turbo")
        for _ in range(200):
            if t.loaded():
                break
            import time
            time.sleep(0.005)
        self.assertEqual(t.loaded(), ("large-v3-turbo",))
        self.assertEqual(built, [("large-v3-turbo", "cuda")])

    def test_tiny_en_never_wakes_the_card(self):
        t, built = self.make()
        t.hear(b"\0" * 3200, transcribe.WAKE_MODEL, "")
        self.assertEqual(built, [(transcribe.WAKE_MODEL, "cpu")])


class SpotterUnit(unittest.TestCase):
    """The openWakeWord wrapper, against a fake model."""

    class Model:
        def __init__(self, scores):
            self.scores, self.seen, self.resets = list(scores), [], 0

        def predict(self, x):
            self.seen.append(len(x))
            return {"wake_aries": self.scores.pop(0) if self.scores else 0.0}

        def reset(self):
            self.resets += 1

    def test_it_scores_80ms_chunks_and_fires_once(self):
        model = self.Model([0.1, 0.2, 0.9, 0.95])
        s = Spotter(factory=lambda path: model)
        frame = bytes(FRAME_BYTES)                         # 32 ms
        fired = [s.feed(frame) for _ in range(8)]          # 256 ms: three predictions
        self.assertEqual(model.seen, [wakeword.CHUNK] * 3)
        self.assertEqual(fired.count(True), 1)
        self.assertEqual(model.resets, 1)                  # starts afresh after a wake

    def test_missing_names_what_is_absent(self):
        self.assertIn("wake_aries.onnx", Spotter.missing("/nonexistent/wake_aries.onnx"))
        with mock.patch("importlib.util.find_spec", return_value=None):
            self.assertIn("openwakeword", Spotter.missing())

    @unittest.skipIf(Spotter.missing() is not None, "openwakeword or the model isn't here")
    def test_the_real_model_is_quiet_on_silence_and_noise(self):
        s = Spotter()
        rng = np.random.default_rng(1)
        noise = (rng.standard_normal(16000 * 3) * 300).astype("<i2").tobytes()
        self.assertFalse(s.feed(bytes(16000 * 2 * 2)) or s.feed(noise))


if __name__ == "__main__":
    unittest.main()
