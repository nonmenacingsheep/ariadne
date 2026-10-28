import asyncio
import os
import tempfile
import threading
import time
import unittest
from unittest import mock

from ariadne2.core.voice import Voice, cartesia, player
from ariadne2.core.voice.cartesia import TTSError
from ariadne2.core.voice.timeline import Timeline, runway_needed, window_levels

RATE = 24000


def pcm(seconds, amp=8000):
    return int(RATE * seconds) * amp.to_bytes(2, "little", signed=True)


class FakePlayer:
    def __init__(self, log, fail_writes=0):
        self.log, self.fail_writes = log, fail_writes
        self.closed = self.terminated = False

    def write(self, data):
        if self.fail_writes:
            self.fail_writes -= 1
            raise BrokenPipeError
        self.log.append(("write", len(data)))

    def close(self):
        self.closed = True

    def terminate(self):
        self.terminated = True


class Rig:
    """A Voice wired to a fake synth and player; records every event in order."""

    def __init__(self, seconds=0.12, synth=None, **kw):
        self.events, self.spoken, self.players = [], [], []
        self.fail_first_writes = 0

        def fake_synth(text, voice, speed, emotion):
            self.spoken.append((text, speed, emotion))
            return pcm(seconds), RATE

        def open_player(rate):
            p = FakePlayer(self.events, self.fail_first_writes)
            self.fail_first_writes = 0
            self.players.append(p)
            return p

        self.voice = Voice(synth=synth or fake_synth, open_player=open_player, **kw)
        self.voice.on_start = lambda: self.events.append("start")
        self.voice.on_stop = lambda: self.events.append("stop")
        self.levels = []
        self.voice.on_level = self.levels.append


async def until(pred, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        await asyncio.sleep(0.01)
    return False


class Playback(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.rig = Rig()
        self.v = self.rig.voice
        await self.v.start()
        self.addAsyncCleanup(self.v.stop)

    async def test_sentences_play_in_order_and_speaking_tracks_them(self):
        self.assertFalse(self.v.speaking)
        for s in ("First sentence here.", "Second sentence here.", "Third one right here."):
            self.v.say(s)
        self.assertTrue(self.v.speaking)
        self.assertTrue(await until(lambda: "stop" in self.rig.events))
        self.assertEqual([t for t, *_ in self.rig.spoken],
                         ["First sentence here.", "Second sentence here.", "Third one right here."])
        self.assertEqual(self.rig.events.count("start"), 1)
        self.assertEqual(self.rig.events.count("stop"), 1)
        self.assertEqual(len(self.rig.players), 1)
        self.assertFalse(self.v.speaking)
        self.assertTrue(self.rig.players[0].closed)           # closed at the end of the reply

    async def test_levels_are_reported_then_zero(self):
        self.v.say("A sentence that is long enough.")
        self.assertTrue(await until(lambda: "stop" in self.rig.events))
        await asyncio.sleep(0.05)
        self.assertGreater(max(self.rig.levels), 0.2)         # 8000/32768
        self.assertLess(max(self.rig.levels), 0.3)
        self.assertEqual(self.rig.levels[-1], 0.0)
        self.assertGreaterEqual(len(self.rig.levels), 2)

    async def test_cancel_drops_everything_and_kills_the_player(self):
        slow = Rig(seconds=0.6)
        v = slow.voice
        await v.start()
        v.say("A sentence that will be cut off.")
        v.say("And this one never plays at all.")
        self.assertTrue(await until(lambda: "start" in slow.events))
        v.cancel()
        self.assertFalse(v.speaking)
        self.assertTrue(slow.players[0].terminated)
        self.assertTrue(await until(lambda: "stop" in slow.events))
        await asyncio.sleep(0.3)
        self.assertEqual(slow.events.count("stop"), 1)
        self.assertLessEqual(len(slow.spoken), 2)
        self.assertEqual(slow.levels[-1], 0.0)
        # and she can speak again afterwards
        slow.events.clear()
        v.say("Back again now, hello.")
        self.assertTrue(await until(lambda: "start" in slow.events))
        await v.stop()

    async def test_cancel_when_idle_is_quiet(self):
        self.v.cancel()
        self.assertEqual(self.rig.events, [])

    async def test_marks_drive_emotion_and_speed_and_never_reach_the_synth(self):
        self.v.say("((sarcastic)) Oh, brilliant. ((slow)) Really, it is.")
        self.assertTrue(await until(lambda: "stop" in self.rig.events))
        texts = [t for t, *_ in self.rig.spoken]
        self.assertTrue(all("((" not in t for t in texts), texts)
        by_text = {t: (s, e) for t, s, e in self.rig.spoken}
        self.assertEqual(by_text["Oh, brilliant."], (1.0, "sarcastic"))
        self.assertEqual(by_text["Really, it is."][0], 0.78)

    async def test_default_emotion_applies_when_unmarked(self):
        rig = Rig(emotion="calm")
        await rig.voice.start()
        rig.voice.say("Plain words here, nothing marked.")
        self.assertTrue(await until(lambda: "stop" in rig.events))
        self.assertEqual(rig.spoken[0][2], "calm")
        await rig.voice.stop()

    async def test_skipped_span_is_never_spoken_across_feeds(self):
        v = self.v
        v.feed("The command is ((skip))rm -rf ~/stuff and then a long")
        v.feed(" middle part that is all skipped. ")
        v.feed("more((/skip)) and that is all of it.")
        v.finish()
        self.assertTrue(await until(lambda: "stop" in self.rig.events))
        said = " ".join(t for t, *_ in self.rig.spoken)
        self.assertNotIn("rm -rf", said)
        self.assertNotIn("skipped", said)
        self.assertIn("The command is", said)
        self.assertIn("that is all of it", said)

    async def test_a_mark_holds_for_its_sentence_only(self):
        self.v.say("Fine. ((sarcastic)) Oh, brilliant. And then plain again, as before.")
        self.assertTrue(await until(lambda: "stop" in self.rig.events))
        by = {t: e for t, _s, e in self.rig.spoken}
        self.assertEqual(by["Oh, brilliant."], "sarcastic")
        self.assertEqual(by["Fine."], "")
        self.assertEqual(by["And then plain again, as before."], "")

    async def test_a_mark_carries_over_a_mid_sentence_cut_then_reverts(self):
        v = self.v
        v.feed("((sympathetic)) I am really so sorry to hear that, honestly, it sounds like a long one. Next sentence is plain and ordinary.")
        v.finish()
        self.assertTrue(await until(lambda: "stop" in self.rig.events))
        emos = [(t, e) for t, _s, e in self.rig.spoken]
        self.assertEqual(emos[0][1], "sympathetic")
        self.assertEqual(emos[1][1], "sympathetic")              # rest of the cut sentence
        self.assertEqual(emos[-1], ("Next sentence is plain and ordinary.", ""))

    async def test_streamed_reply_speaks_before_it_is_finished(self):
        v = self.v
        v.feed("Right, so that worked fine. And ")
        self.assertTrue(await until(lambda: "start" in self.rig.events))
        v.feed("here is the rest of it.")
        v.finish()
        self.assertTrue(await until(lambda: "stop" in self.rig.events))
        self.assertEqual([t for t, *_ in self.rig.spoken],
                         ["Right, so that worked fine.", "And here is the rest of it."])

    async def test_unspeakable_text_makes_no_sound(self):
        self.v.say("((skip))all of it((/skip))")
        self.v.say("...")
        await asyncio.sleep(0.1)
        self.assertEqual(self.rig.spoken, [])
        self.assertFalse(self.v.speaking)

    async def test_callbacks_run_on_the_loop_thread_and_may_be_coroutines(self):
        main = threading.get_ident()
        seen = []

        async def on_start():
            seen.append(threading.get_ident())

        self.v.on_start = on_start
        self.v.on_level = lambda r: seen.append(threading.get_ident())
        self.v.say("Check the thread, please.")
        self.assertTrue(await until(lambda: "stop" in self.rig.events))
        self.assertTrue(seen)
        self.assertTrue(all(t == main for t in seen))

    async def test_a_raising_callback_does_not_kill_the_voice(self):
        def boom():
            raise RuntimeError("desk exploded")

        self.v.on_start = boom
        with self.assertLogs("ariadne2.voice", "ERROR"):
            self.v.say("Still goes on speaking.")
            self.assertTrue(await until(lambda: "stop" in self.rig.events))


class Failures(unittest.IsolatedAsyncioTestCase):
    async def test_broken_pipe_reopens_the_player_once(self):
        rig = Rig()
        rig.fail_first_writes = 1
        await rig.voice.start()
        rig.voice.say("This write fails first, then goes.")
        self.assertTrue(await until(lambda: "stop" in rig.events))
        self.assertEqual(len(rig.players), 2)
        self.assertIn(("write", len(pcm(0.12))), rig.events)
        await rig.voice.stop()

    async def test_a_transient_synth_error_skips_that_sentence_and_logs_once(self):
        calls = []

        def synth(text, voice, speed, emotion):
            calls.append(text)
            if "bad" in text:
                raise TTSError("Cartesia said 503")
            return pcm(0.05), RATE

        rig = Rig(synth=synth)
        await rig.voice.start()
        with self.assertLogs("ariadne2.voice", "WARNING") as logs:
            for line in ("A bad sentence one.", "A bad sentence two.", "A good sentence here."):
                rig.voice.say(line)
            self.assertTrue(await until(lambda: "stop" in rig.events))
        self.assertEqual(len(calls), 3)
        self.assertEqual(len([l for l in logs.output if "skipping" in l]), 1)
        self.assertTrue(rig.voice.available)
        await rig.voice.stop()

    async def test_a_refused_key_disables_the_voice_quietly(self):
        def synth(text, voice, speed, emotion):
            raise TTSError("Cartesia refused the key (401)", fatal=True)

        rig = Rig(synth=synth)
        await rig.voice.start()
        with self.assertLogs("ariadne2.voice", "WARNING") as logs:
            rig.voice.say("Anything at all, please.")
            self.assertTrue(await until(lambda: not rig.voice.available))
        self.assertEqual(len(logs.output), 1)
        rig.voice.say("Silently ignored now.")        # a no-op, not an exception
        self.assertFalse(rig.voice.speaking)
        await rig.voice.stop()

    async def test_no_player_disables_the_voice(self):
        v = Voice(synth=lambda *a: (pcm(0.05), RATE), open_player=lambda rate: None)
        await v.start()
        with self.assertLogs("ariadne2.voice", "WARNING"):
            v.say("Nowhere to play this.")
            self.assertTrue(await until(lambda: not v.available))
        await v.stop()


class Degradation(unittest.IsolatedAsyncioTestCase):
    """No keys and no devices: log once, then do nothing, never raise."""

    async def test_no_key(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.dict(os.environ, {"XDG_DATA_HOME": tmp}), \
                mock.patch.object(player, "player_installed", return_value=True):
            os.environ.pop("CARTESIA_API_KEY", None)
            v = Voice()
            with self.assertLogs("ariadne2.voice", "WARNING") as logs:
                await v.start()
                v.say("Nobody hears this.")
                v.feed("or this. ")
                v.flush(); v.finish(); v.cancel()
            self.assertEqual(len(logs.output), 1)
            self.assertNotIn("sekrit", logs.output[0])
            self.assertFalse(v.available)
            self.assertFalse(v.speaking)
            await v.stop()

    async def test_no_audio_output(self):
        with mock.patch.dict(os.environ, {"CARTESIA_API_KEY": "k"}), \
                mock.patch.object(player, "player_installed", return_value=False):
            v = Voice()
            with self.assertLogs("ariadne2.voice", "WARNING") as logs:
                await v.start()
            self.assertIn("play audio", logs.output[0])
            v.say("silence")
            self.assertFalse(v.speaking)
            await v.stop()

    async def test_say_before_start_is_a_noop(self):
        v = Voice(synth=lambda *a: (pcm(0.05), RATE), open_player=lambda r: None)
        v.say("too early")
        self.assertFalse(v.speaking)


class Pieces(unittest.TestCase):
    def test_timeline_follows_the_clock_and_catches_up_after_a_gap(self):
        now = [100.0]
        t = Timeline(lambda: now[0])
        self.assertEqual(t.note(pcm(1.0), RATE), 0.0)
        now[0] += 0.4
        self.assertAlmostEqual(t.position(), 0.4)
        now[0] += 3.0                    # the player ran dry long ago
        self.assertTrue(t.finished())
        self.assertAlmostEqual(t.note(pcm(1.0), RATE), 3.4)     # starts now, not at 1.0
        self.assertFalse(t.finished())

    def test_level_follows_position_and_is_silent_in_a_gap(self):
        now = [0.0]
        t = Timeline(lambda: now[0])
        t.note(pcm(0.5, 16000), RATE)
        now[0] = 0.2
        self.assertAlmostEqual(t.level(), 16000 / 32768, places=2)
        now[0] = 2.0
        t.note(pcm(0.5, 4000), RATE)
        now[0] = 2.1
        self.assertAlmostEqual(t.level(), 4000 / 32768, places=2)

    def test_window_levels_is_twenty_a_second(self):
        self.assertEqual(len(window_levels(pcm(1.0), RATE)), 20)

    def test_runway_is_measured_not_fixed(self):
        # Fast machine: a 1s sentence made in 0.05s needs a fraction of a second in hand.
        self.assertLess(runway_needed(1.0, 0.05, 40, 120), 0.5)
        # Slow: made in 0.9s needs more audio than the opener has.
        self.assertGreater(runway_needed(1.0, 0.9, 40, 120), 2.0)
        self.assertEqual(runway_needed(0.0, 0.0, 10, 120), 4.0)


if __name__ == "__main__":
    unittest.main()
