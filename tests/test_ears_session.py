import unittest

from ariadne2.core.ears.session import (AUTOSEND_S, FOLLOW_UP_S, MAX_OPEN_S, IDLE, OPEN, OVER, PTT, Dialogue)
from ariadne2.core.ears.wake import Names


class Rig:
    def __init__(self, **kw):
        self.now = 1000.0
        self.heard, self.mic, self.cut = [], [], []
        self.speaking = self.busy = self.media = False
        self.d = Dialogue(Names("Aries"), heard=lambda t, s: self.heard.append(t),
                          listening=self.mic.append, interrupt=lambda r="": self.cut.append(r),
                          is_speaking=lambda: self.speaking, is_busy=lambda: self.busy,
                          media_playing=lambda: self.media, clock=lambda: self.now, **kw)

    def advance(self, s):
        self.now += s
        self.d.tick()

    def say(self, text, mode=None):
        self.d.consider(text, mode or self.d.mode)


class Wake(unittest.TestCase):
    def test_nothing_happens_without_the_name(self):
        r = Rig()
        r.say("what a lovely day")
        self.assertEqual((r.heard, r.mic, r.d.awake), ([], [], False))

    def test_the_name_alone_opens_and_reports_listening(self):
        r = Rig()
        r.say("hey aries")
        self.assertTrue(r.d.awake)
        self.assertEqual(r.mic, [True])

    def test_name_and_words_in_one_breath_send_after_silence(self):
        r = Rig()
        r.say("hey aries what's playing")
        self.assertEqual(r.heard, [])
        r.advance(AUTOSEND_S - 0.2)
        self.assertEqual(r.heard, [])
        r.advance(0.3)
        self.assertEqual(r.heard, ["what's playing"])

    def test_clips_in_one_sentence_join_into_one_utterance(self):
        r = Rig()
        r.say("hey aries")
        r.say("open firefox")
        r.advance(0.6)
        r.say("and go to the news")
        r.advance(AUTOSEND_S + 0.1)
        self.assertEqual(r.heard, ["open firefox and go to the news"])

    def test_autosend_waits_for_clips_still_being_transcribed(self):
        r = Rig()
        r.say("hey aries do this")
        r.d.began()
        r.advance(5)
        self.assertEqual(r.heard, [])
        r.d.finished()
        r.advance(0)
        self.assertEqual(r.heard, ["do this"])

    def test_send_flushes_now_and_is_not_part_of_the_message(self):
        r = Rig()
        r.say("hey aries open the pod bay doors")
        r.say("send")
        self.assertEqual(r.heard, ["open the pod bay doors"])

    def test_send_with_nothing_drafted_does_nothing(self):
        r = Rig()
        r.say("hey aries")
        r.say("send")
        self.assertEqual(r.heard, [])
        self.assertTrue(r.d.awake)

    def test_dismissal_discards_the_draft_and_closes(self):
        r = Rig()
        r.say("hey aries delete everything")
        r.say("never mind")
        r.advance(10)
        self.assertEqual(r.heard, [])
        self.assertFalse(r.d.awake)
        self.assertEqual(r.mic, [True, False])

    def test_open_but_nothing_said_closes_after_the_follow_up_window(self):
        r = Rig()
        r.say("hey aries")
        r.advance(FOLLOW_UP_S - 1)
        self.assertTrue(r.d.awake)
        r.advance(2)
        self.assertFalse(r.d.awake)
        self.assertEqual(r.mic, [True, False])

    def test_a_sent_message_closes_the_mic_and_room_talk_after_goes_nowhere(self):
        r = Rig()
        r.say("hey aries tell me a story")
        r.advance(AUTOSEND_S + 0.1)
        self.assertEqual(r.heard, ["tell me a story"])
        self.assertFalse(r.d.awake)                         # stopped listening once it was sent
        r.speaking = True
        r.advance(20)
        r.speaking = False
        r.say("look at that one, it's so aesthetic")        # him, to the stream: not for her
        r.advance(AUTOSEND_S + 1)
        self.assertEqual(r.heard, ["tell me a story"])
        r.say("hey aries and another thing")                # her name opens it again
        r.advance(AUTOSEND_S + 0.1)
        self.assertEqual(r.heard, ["tell me a story", "and another thing"])

    def test_a_room_that_never_goes_quiet_still_closes(self):
        r = Rig()
        r.say("hey aries")
        self.assertTrue(r.d.awake)
        r.now += MAX_OPEN_S - 1             # never quiet, so tick() (silence only) never runs
        r.d.expire()
        self.assertTrue(r.d.awake)
        r.now += 2
        r.d.expire()                                        # called every frame, loud or not
        self.assertFalse(r.d.awake)

    def test_at_the_limit_a_started_message_is_sent_not_dropped(self):
        r = Rig()
        r.say("hey aries remind me to")
        r.advance(MAX_OPEN_S + 1)
        r.d.expire()
        self.assertEqual(r.heard, ["remind me to"])
        self.assertFalse(r.d.awake)

    def test_while_open_everything_said_is_for_her(self):
        r = Rig()
        r.say("hey aries")
        r.say("turn it down a bit", mode=OPEN)
        r.advance(AUTOSEND_S + 0.1)
        self.assertEqual(r.heard, ["turn it down a bit"])

    def test_addressing_her_while_she_works_interrupts(self):
        r = Rig()
        r.busy = True
        r.say("hey aries stop")
        self.assertEqual(len(r.cut), 1)

    def test_deaf_window_after_opening_and_closing(self):
        r = Rig()
        r.say("hey aries")
        self.assertGreater(r.d.deaf_until, r.now)
        r.now += 5
        r.d.close()
        self.assertGreater(r.d.deaf_until, r.now)


class OverHerVoice(unittest.TestCase):
    def test_her_own_voice_coming_back_is_ignored(self):
        r = Rig()
        r.speaking = True
        r.say("sure thing, I'll open that for you now", mode=OVER)
        self.assertEqual((r.cut, r.heard, r.d.awake), ([], [], False))

    def test_her_name_over_her_voice_cuts_her_off_and_listens(self):
        r = Rig()
        r.speaking = True
        r.say("hey aries", mode=OVER)
        self.assertEqual(len(r.cut), 1)
        self.assertTrue(r.d.awake)

    def test_name_and_command_over_her_voice_interrupts_once(self):
        r = Rig()
        r.speaking = True
        r.busy = True
        r.say("hey aries play something else", mode=OVER)
        self.assertEqual(len(r.cut), 1)
        r.speaking = r.busy = False          # the interrupt took effect
        r.advance(AUTOSEND_S + 0.1)
        self.assertEqual(r.heard, ["play something else"])

    def test_skip_cuts_her_off_but_does_not_open(self):
        r = Rig()
        r.speaking = True
        r.say("skip", mode=OVER)
        self.assertEqual(len(r.cut), 1)
        self.assertFalse(r.d.awake)

    def test_a_bare_skip_while_media_plays_needs_her_name(self):
        r = Rig()
        r.speaking = r.media = True
        r.say("be quiet", mode=OVER)
        self.assertEqual(r.cut, [])
        r.say("aries be quiet", mode=OVER)
        self.assertEqual(len(r.cut), 1)


class PushToTalk(unittest.TestCase):
    def test_key_is_the_address_no_name_needed(self):
        r = Rig()
        r.d.set_ptt(True)
        r.say("what's the weather like", mode=PTT)
        self.assertEqual(r.heard, ["what's the weather like"])

    def test_listening_follows_the_key(self):
        r = Rig()
        r.d.set_ptt(True)
        r.d.set_ptt(False)
        self.assertEqual(r.mic, [True, False])

    def test_key_while_already_open_does_not_double_report(self):
        r = Rig()
        r.say("hey aries")
        r.d.set_ptt(True)
        r.d.set_ptt(False)
        self.assertEqual(r.mic, [True])
        self.assertTrue(r.d.awake)

    def test_empty_transcript_is_ignored(self):
        r = Rig()
        r.say("   ", mode=PTT)
        self.assertEqual(r.heard, [])

    def test_a_raising_handler_does_not_break_the_dialogue(self):
        r = Rig()
        r.d._heard = lambda t, s: 1 / 0
        with self.assertLogs("ariadne2.ears", "ERROR"):
            r.say("hello", mode=PTT)


if __name__ == "__main__":
    unittest.main()
