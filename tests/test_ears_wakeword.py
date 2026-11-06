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

MARK = 2345                       # a loud frame the fake spotter takes for "hey Aries"


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
    def warm(self, name, park=False): self.warmed.append((name, park))
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
        self.assertEqual(self.ears.wake_phrase, "hey Aries")
        self.assertIn("listening for hey Aries", self.status)

    async def test_at_start_the_command_model_is_warmed_and_parked(self):
        self.build()
        await self.go()
        self.assertTrue(await until(lambda: self.spot.loads == 1 and self.tr.warmed))
        self.assertEqual(self.tr.warmed, [("cmd", True)])        # loaded once, then off the card
        self.assertNotIn(transcribe.WAKE_MODEL, [w[0] for w in self.tr.warmed])

    async def test_talk_without_the_phrase_is_never_transcribed(self):
        self.build([10] * 20 + speech(900) + [10] * 40 + speech(600) + [10] * 40,
                   texts=["hey aries open firefox"])
        await self.go()
        self.assertTrue(await until(lambda: self.mic.reads > 20 + 1500 // 32 + 80))
        await asyncio.sleep(0.05)
        self.assertEqual((self.tr.calls, self.heard, self.listening), ([], [], []))

    async def test_a_command_in_the_same_breath(self):
        self.build([10] * 20 + phrase() + speech(800) + [10] * 200,
                   texts=["Hey Aries, play something."])
        await self.go()
        self.assertTrue(await until(lambda: self.heard))
        self.assertEqual(self.heard, ["play something"])
        self.assertEqual(self.listening[0], True)
        model, hint, _n = self.tr.calls[0]
        self.assertEqual((model, hint.split(" ")[:2]), ("cmd", ["Hey", "Aries."]))

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


class NothingLost(Spotting):
    """While Whisper loads, his words wait in the queue; none are thrown away."""

    async def test_talking_through_the_chime_is_kept(self):
        # The phrase, a pause long enough to end that breath, and he starts again
        # while the chime is still playing.
        from ariadne2.core.ears import session
        deaf_frames = int(session.DEAF_S * 1000) // 32
        self.build([10] * 20 + phrase() + [10] * 16 + speech(1000) + [10] * 200,
                   texts=["play something"] * 2)          # short: the control model hears it first
        await self.go()
        self.assertTrue(await until(lambda: self.heard))
        self.assertEqual(self.heard, ["play something"])
        # 16 quiet frames end the breath (450 ms); she opens on the 15th; the rest of
        # the chime's deafness falls on his words, and is in the clip
        self.assertGreaterEqual(self.tr.calls[0][2], (1000 // 32 + deaf_frames - 4) * FRAME_BYTES)

    async def test_utterances_queued_behind_a_slow_load_are_all_heard(self):
        import threading
        gate = threading.Event()

        class Slow(LazyTranscriber):
            def hear(self, pcm, model, hint):
                gate.wait(5)                      # the command model is still loading
                return super().hear(pcm, model, hint)

        gap = [10] * 25                           # long enough to end an utterance, not to send
        words = ["one", "two", "three", "four"]
        tr = Slow(*[w for w in words for _ in (1, 2)])   # each short clip: control model, then command
        self.build([10] * 20 + phrase() + [10] * 40 + (speech(600) + gap) * 4 + [10] * 400)
        self.ears.transcriber = self.ears.listener.transcriber = self.tr = tr
        await self.go()
        self.assertTrue(await until(lambda: self.mic.reads > 20 + 19 + 40 + 4 * 44))
        gate.set()
        self.assertTrue(await until(lambda: self.heard, timeout=5))
        self.assertEqual(self.heard, ["one two three four"])
        self.assertEqual(self.ears.listener.dropped, 0)

    async def test_push_to_talk_starts_the_load(self):
        self.build(wake_word=False)
        await self.go()
        self.ears.push_to_talk(True)
        self.assertEqual(self.tr.prefetched, ["cmd"])


class Fallback(Spotting):
    async def test_a_missing_model_logs_once_and_whisper_listens(self):
        script = [10] * 20 + speech(900)
        self.build(script, texts=["hey aries open firefox", "hey aries open firefox"],
                   spotter=Spotter(model="/nonexistent/hey_aries.onnx"))
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

    def make_parkable(self):
        self.now = [0.0]
        built, moves = [], []

        class Engine:
            def unload_model(e, to_cpu=False): moves.append(("park", to_cpu))
            def load_model(e): moves.append(("back",))

        class Model:
            def __init__(m, name, device, compute_type):
                built.append(name)
                m.model = Engine()

            def transcribe(m, samples, **kw):
                return iter([]), None

        t = Transcriber(model_factory=Model, device=("cuda", "float16"), clock=lambda: self.now[0])
        return t, built, moves

    def test_an_idle_gpu_model_is_parked_in_ram_and_comes_back_without_a_reload(self):
        t, built, moves = self.make_parkable()
        t.hear(b"\0" * 3200, "large-v3-turbo", "")
        t.hear(b"\0" * 3200, transcribe.WAKE_MODEL, "")
        self.now[0] = transcribe.IDLE_UNLOAD_S
        self.assertEqual(t.unload_idle(), ("large-v3-turbo", transcribe.WAKE_MODEL))
        self.assertEqual((t.parked(), t.loaded()), (("large-v3-turbo",), ()))   # tiny.en (CPU) dropped
        self.assertEqual(moves, [("park", transcribe.KEEP_IN_RAM)])
        self.assertEqual(t.unload_idle(), ())                    # parked once, not again
        t.hear(b"\0" * 3200, "large-v3-turbo", "")
        self.assertEqual(moves[-1], ("back",))
        self.assertEqual(built, ["large-v3-turbo", transcribe.WAKE_MODEL])   # never rebuilt
        self.assertEqual(t.loaded(), ("large-v3-turbo",))

    def test_warm_and_park_leaves_the_card_free_unless_a_wake_got_there_first(self):
        t, _, moves = self.make_parkable()
        t.warm("large-v3-turbo", park=True)
        self.assertEqual(t.parked(), ("large-v3-turbo",))
        t2, _, _ = self.make_parkable()
        model = t2.load("large-v3-turbo")
        inner = model.transcribe

        def during_warm(samples, **kw):               # a wake loads it while warm transcribes
            self.now[0] += 1
            t2.load("large-v3-turbo")
            return inner(samples, **kw)
        model.transcribe = during_warm
        t2.warm("large-v3-turbo", park=True)
        self.assertEqual(t2.parked(), ())

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
            return {"hey_aries": self.scores.pop(0) if self.scores else 0.0}

        def reset(self):
            self.resets += 1

    def test_it_scores_80ms_chunks_and_fires_once(self):
        model = self.Model([0.1, 0.2, 0.9, 0.95])
        s = Spotter(factory=lambda path: model, threshold=0.5)
        frame = bytes(FRAME_BYTES)                         # 32 ms
        fired = [s.feed(frame) for _ in range(8)]          # 256 ms: three predictions
        self.assertEqual(model.seen, [wakeword.CHUNK] * 3)
        self.assertEqual(fired.count(True), 1)
        self.assertEqual(model.resets, 1)                  # starts afresh after a wake

    def test_missing_names_what_is_absent(self):
        self.assertIn("hey_aries.onnx", Spotter.missing("/nonexistent/hey_aries.onnx"))
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
