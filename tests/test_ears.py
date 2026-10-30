"""Ears end to end with a fake recorder and a fake transcriber: no mic, no model."""
import array
import asyncio
import threading
import time
import unittest
from unittest import mock

from ariadne2.core.ears import Ears, mic, transcribe
from ariadne2.core.ears.mic import FRAME_BYTES
from ariadne2.core.ears.transcribe import Heard, Transcriber


def frame(amp):
    return array.array("h", [amp] * (FRAME_BYTES // 2)).tobytes()


class Clock:
    """Advances 32ms per frame read, so silences and follow-up windows take no real time."""
    t = 1000.0

    def __call__(self):
        return self.t


class FakeMic:
    def __init__(self, clock, script=()):
        self.clock, self.script = clock, list(script)
        self.spawned = 0
        self.live = None
        self.reads = 0

    def find_recorder(self, fresh=False):
        return "fake", ["fake"]

    def popen(self, argv, **kw):
        self.spawned += 1
        owner = self
        proc = mock.Mock()
        proc.alive = True
        proc.poll = lambda: None if proc.alive else 0
        proc.terminate = lambda: setattr(proc, "alive", False)

        def read(n):
            if not proc.alive:
                return b""
            owner.reads += 1
            owner.clock.t += 0.032
            time.sleep(0.0005)
            return frame(owner.script.pop(0) if owner.script else 10)

        proc.stdout.read = read
        self.live = proc
        return proc


class FakeTranscriber:
    def __init__(self, *texts):
        self.texts, self.calls = list(texts), []

    def available(self): return None
    def command_model(self): return "cmd"
    def control_model(self): return "ctl"
    def warm(self, name): pass
    def unload(self): self.unloaded = True

    def hear(self, pcm, model, hint):
        self.calls.append((model, hint, len(pcm)))
        text = self.texts.pop(0) if self.texts else ""
        return Heard(text, -0.2)


async def until(pred, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        await asyncio.sleep(0.005)
    return False


def speech(ms):
    return [2000] * (ms // 32)


class Base(unittest.IsolatedAsyncioTestCase):
    def build(self, script=(), texts=(), **kw):
        self.clock = Clock()
        self.mic = FakeMic(self.clock, script)
        self.tr = FakeTranscriber(*texts)
        self.heard, self.listening, self.status = [], [], []
        defaults = dict(on_heard=self.heard.append, on_listening=self.listening.append,
                        on_status=self.status.append, transcriber=self.tr, clock=self.clock,
                        find_recorder=self.mic.find_recorder, popen=self.mic.popen,
                        bluetooth=lambda: False)
        defaults.update(kw)
        self.ears = Ears(**defaults)

    async def go(self):
        with mock.patch.object(mic, "recorder_installed", return_value=True):
            await self.ears.start()
        self.addAsyncCleanup(self.ears.stop)


class PushToTalk(Base):
    async def test_hold_records_release_transcribes_and_puts_the_mic_down(self):
        self.build(texts=["what's the weather like"], wake_word=False)
        await self.go()
        self.assertEqual(self.mic.spawned, 0)             # wake word off: the mic is not held
        self.ears.push_to_talk(True)
        self.assertTrue(await until(lambda: self.mic.reads > 10))
        self.assertEqual(self.listening, [True])
        self.ears.push_to_talk(False)
        self.assertTrue(await until(lambda: self.heard))
        self.assertEqual(self.heard, ["what's the weather like"])
        self.assertEqual(self.listening, [True, False])
        self.assertEqual(self.tr.calls[0][:2], ("cmd", transcribe.COMMAND_HINT))   # no wake model, no name
        self.assertTrue(await until(lambda: not self.mic.live.alive))              # and the mic is down again
        self.assertEqual(self.mic.spawned, 1)

    async def test_works_with_the_wake_word_on_too(self):
        self.build(texts=["play something"])
        await self.go()
        self.assertTrue(await until(lambda: self.mic.spawned == 1))
        self.ears.push_to_talk(True)
        await until(lambda: self.mic.reads > 10)
        self.ears.push_to_talk(False)
        self.assertTrue(await until(lambda: self.heard))
        self.assertEqual(self.heard, ["play something"])
        self.assertEqual(self.mic.spawned, 1)             # the held mic was reused
        self.assertTrue(self.mic.live.alive)

    async def test_pressing_a_key_with_no_recorder_gives_up_cleanly(self):
        self.build(wake_word=False, find_recorder=lambda fresh=False: None)
        await self.go()
        self.ears.push_to_talk(True)
        self.assertTrue(await until(lambda: "no microphone" in self.status))
        self.assertTrue(await until(lambda: self.listening == [True, False]))


    async def test_the_talk_key_follows_the_recorder_not_its_own_flag(self):
        self.build(texts=["first", "second"], wake_word=False)
        await self.go()
        self.ears.toggle_talk()                             # press: recording
        self.assertTrue(await until(lambda: self.mic.reads > 10))
        self.ears.toggle_talk()                             # press: sent
        self.assertTrue(await until(lambda: self.heard == ["first"]))
        self.ears.toggle_talk()
        self.assertTrue(await until(lambda: self.ears.listener.ptt_recording()))
        self.ears.listener._give_up_ptt()                   # the recording ends without the key (cap, lost mic)
        self.ears.toggle_talk()                             # so the next press starts one, not "stops" nothing
        self.assertTrue(self.ears.listener.ptt_recording())


class WakeWord(Base):
    async def test_hey_aries_then_words_are_heard_after_silence(self):
        script = [10] * 20 + speech(900)
        self.build(script, texts=["hey aries open firefox", "hey aries open firefox"])
        await self.go()
        self.assertTrue(await until(lambda: self.heard))
        self.assertEqual(self.heard, ["open firefox"])
        self.assertEqual(self.listening[0], True)
        # the wake model spotted the name, then the better model heard the words
        self.assertEqual([c[0] for c in self.tr.calls], [transcribe.WAKE_MODEL, "cmd"])
        self.assertEqual(self.tr.calls[0][1], "Hey Aries.")

    async def test_the_window_closes_after_the_follow_up_time_and_the_wake_word_still_works(self):
        script = [10] * 20 + speech(500)
        self.build(script, texts=["hey aries"])
        await self.go()
        self.assertTrue(await until(lambda: self.listening == [True]))
        self.assertTrue(await until(lambda: self.listening == [True, False]))
        self.assertTrue(self.mic.live.alive)               # wake word still held

    async def test_while_she_works_the_open_mic_needs_her_name(self):
        # He asks, she starts working; talk in the room meanwhile must not be
        # drafted and sent the moment she's done.
        busy = {"on": False}
        script = [10] * 20 + speech(900) + [10] * 60 + speech(900) + [10] * 200
        self.build(script, texts=["hey aries open firefox", "hey aries open firefox",
                                  "when she's activated"], is_busy=lambda: busy["on"])
        await self.go()
        self.assertTrue(await until(lambda: self.heard))
        busy["on"] = True
        self.assertTrue(await until(lambda: len(self.tr.calls) >= 3))
        self.assertEqual(self.tr.calls[2][1], self.ears.names.interrupt_hint)   # heard as over her
        busy["on"] = False
        await asyncio.sleep(0.15)
        self.assertEqual(self.heard, ["open firefox"])

    async def test_speech_without_the_name_goes_nowhere(self):
        script = [10] * 20 + speech(800)
        self.build(script, texts=["so I told him the other day"])
        await self.go()
        self.assertTrue(await until(lambda: len(self.tr.calls) >= 1))
        await asyncio.sleep(0.1)
        self.assertEqual((self.heard, self.listening), ([], []))

    async def test_turning_the_wake_word_off_puts_the_mic_down(self):
        self.build()
        await self.go()
        self.assertTrue(await until(lambda: self.mic.spawned == 1))
        proc = self.mic.live
        self.ears.set_wake_word(False)
        self.assertTrue(await until(lambda: not proc.alive))
        self.ears.set_wake_word(True)
        self.assertTrue(await until(lambda: self.mic.spawned == 2))

    async def test_wake_now_opens_without_the_phrase(self):
        self.build(wake_word=False)
        await self.go()
        self.assertTrue(self.ears.wake_now())
        self.assertFalse(self.ears.wake_now())            # already open: no second chime
        self.assertTrue(await until(lambda: self.listening == [True]))
        self.assertTrue(await until(lambda: self.mic.spawned == 1))

    async def test_a_dying_recorder_is_reopened_with_backoff(self):
        self.build()
        await self.go()
        self.assertTrue(await until(lambda: self.mic.spawned == 1))
        self.mic.live.alive = False                         # the recorder exits under us
        self.assertTrue(await until(lambda: self.mic.spawned == 2, timeout=4))


class BargeIn(Base):
    async def test_her_name_over_her_voice_calls_voice_cancel(self):
        voice = mock.Mock(speaking=True)
        script = [10] * 20 + speech(500)
        self.build(script, texts=["hey aries"], voice=voice)
        await self.go()
        self.assertTrue(await until(lambda: voice.cancel.called))
        self.assertEqual(self.tr.calls[0][:2], (transcribe.WAKE_MODEL, "Hey Aries. Skip. Stop talking."))

    async def test_her_own_voice_is_ignored(self):
        voice = mock.Mock(speaking=True)
        script = [10] * 20 + speech(500)
        self.build(script, texts=["sure, opening that for you now"], voice=voice)
        await self.go()
        self.assertTrue(await until(lambda: self.tr.calls))
        await asyncio.sleep(0.1)
        self.assertFalse(voice.cancel.called)
        self.assertEqual(self.heard, [])

    async def test_barge_in_off_is_fully_deaf_while_she_speaks(self):
        voice = mock.Mock(speaking=True)
        self.build([10] * 20 + speech(500), texts=["hey aries"], voice=voice, barge_in=False)
        await self.go()
        await asyncio.sleep(0.3)
        self.assertEqual(self.tr.calls, [])


class Degradation(Base):
    async def test_no_transcriber_package_logs_once_and_does_nothing(self):
        self.build(transcriber=Transcriber())
        with mock.patch.object(Transcriber, "missing", return_value="faster-whisper isn't installed"), \
                mock.patch.object(mic, "recorder_installed", return_value=True):
            with self.assertLogs("ariadne2.ears", "WARNING") as logs:
                await self.ears.start()
                await self.ears.start()
        self.assertEqual(len(logs.output), 1)
        self.assertFalse(self.ears.available)
        self.assertIn("faster-whisper", self.ears.status)
        self.ears.push_to_talk(True)                      # no-ops, no exceptions
        self.assertFalse(self.ears.wake_now())
        self.ears.set_wake_word(False)
        await self.ears.stop()
        self.assertEqual(self.mic.spawned, 0)

    async def test_no_recorder_tools(self):
        self.build()
        with mock.patch.object(mic, "recorder_installed", return_value=False):
            with self.assertLogs("ariadne2.ears", "WARNING") as logs:
                await self.ears.start()
        self.assertFalse(self.ears.available)
        self.assertIn("record audio", logs.output[0])
        await self.ears.stop()

    async def test_bluetooth_mic_blocks_the_wake_word_but_not_push_to_talk(self):
        self.build(texts=["hello"], bluetooth=lambda: True)
        await self.go()
        await asyncio.sleep(0.2)
        self.assertEqual(self.mic.spawned, 0)             # not held open for the wake word
        self.assertTrue(any("Bluetooth" in s for s in self.status))
        self.assertEqual(len([s for s in self.status if "Bluetooth" in s]), 1)
        self.ears.push_to_talk(True)
        await until(lambda: self.mic.reads > 10)
        self.ears.push_to_talk(False)
        self.assertTrue(await until(lambda: self.heard))
        self.assertEqual(self.mic.spawned, 1)

    async def test_stop_unloads_the_models_and_a_raising_callback_is_survived(self):
        def boom(text):
            raise RuntimeError("desk exploded")
        self.build(texts=["hello"], wake_word=False, on_heard=boom)
        await self.go()
        self.ears.push_to_talk(True)
        await until(lambda: self.mic.reads > 5)
        with self.assertLogs("ariadne2", "ERROR"):
            self.ears.push_to_talk(False)
            await until(lambda: self.tr.calls)
            await asyncio.sleep(0.2)
        await self.ears.stop()
        self.assertTrue(self.tr.unloaded)


class Transcription(unittest.TestCase):
    """The faster-whisper wrapper, against a fake model."""

    class Seg:
        def __init__(self, text, lp): self.text, self.avg_logprob = text, lp

    def make(self, device=("cpu", "int8"), segs=None, fail_on_gpu=False):
        built = []

        class Model:
            def __init__(m, name, device, compute_type):
                if fail_on_gpu and device != "cpu":
                    raise RuntimeError("no cublas")
                built.append((name, device, compute_type))

            def transcribe(m, samples, **kw):
                m.kw = kw
                return iter(segs or [Transcription.Seg(" hello", -0.2), Transcription.Seg(" there", -0.4)]), None

        return Transcriber(model_factory=Model, device=device), built

    def pcm(self):
        return array.array("h", [1000] * 1600).tobytes()

    def test_text_confidence_and_hint(self):
        t, built = self.make()
        h = t.hear(self.pcm(), "base.en", "hint")
        self.assertEqual(h.text, "hello there")
        self.assertAlmostEqual(h.confidence, -0.3)
        self.assertTrue(h.sure)
        self.assertEqual(built, [("base.en", "cpu", "int8")])

    def test_unsure_below_threshold(self):
        t, _ = self.make(segs=[self.Seg("paset at coward", -1.4)])
        self.assertFalse(t.hear(self.pcm(), "base.en", "").sure)

    def test_models_are_loaded_once_and_unloaded(self):
        t, built = self.make()
        for _ in range(3):
            t.hear(self.pcm(), "tiny.en", "")
        self.assertEqual(len(built), 1)
        self.assertEqual(t.unload(), 1)
        t.hear(self.pcm(), "tiny.en", "")
        self.assertEqual(len(built), 2)

    def test_model_choice_follows_the_device(self):
        cpu, _ = self.make(("cpu", "int8"))
        gpu, _ = self.make(("cuda", "float16"))
        self.assertEqual((cpu.command_model(), cpu.control_model()), ("base.en", "base.en"))
        self.assertEqual((gpu.command_model(), gpu.control_model()), ("large-v3-turbo", "large-v3-turbo"))

    def test_a_broken_gpu_falls_back_to_the_cpu(self):
        t, built = self.make(("cuda", "float16"), fail_on_gpu=True)
        with self.assertLogs("ariadne2.ears", "WARNING"):
            self.assertEqual(t.hear(self.pcm(), "tiny.en", "").text, "hello there")
        self.assertEqual(built, [("tiny.en", "cpu", "int8")])
        self.assertEqual(t.device(), ("cpu", "int8"))

    def test_levelling_brings_quiet_audio_up_but_caps_the_gain(self):
        quiet = array.array("h", [30] * 100).tobytes()
        out = transcribe.levelled(quiet)
        self.assertAlmostEqual(max(out), 30 / 32768 * transcribe.MAX_GAIN, places=5)
        loud = array.array("h", [16000] * 100).tobytes()
        self.assertAlmostEqual(max(transcribe.levelled(loud)), transcribe.TARGET_PEAK, places=3)
        self.assertEqual(len(transcribe.levelled(b"")), 0)

    def test_missing_report_names_the_package(self):
        with mock.patch("importlib.util.find_spec", return_value=None):
            self.assertIn("faster-whisper", Transcriber.missing())


if __name__ == "__main__":
    unittest.main()
