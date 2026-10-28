import unittest

from ariadne2.core.ears.wake import Names, edit_distance, flatten


class WakeWord(unittest.TestCase):
    def setUp(self):
        self.n = Names("Aries")

    def test_phrase_and_hint(self):
        self.assertEqual(self.n.phrase, "hey Aries")
        self.assertIn("Aries", self.n.wake_hint)

    def test_name_alone_after_a_greeting_wakes(self):
        for s in ("Hey Aries", "hey, aries!", "OK Aries.", "hey there aries", "Hi Aries"):
            self.assertEqual(self.n.heard_name(s), "", s)

    def test_command_after_the_name(self):
        self.assertEqual(self.n.heard_name("Hey Aries, what's playing on Spotify?"),
                         "what's playing on spotify")
        self.assertEqual(self.n.heard_name("hey aries's thing"), "thing")

    def test_known_mishearings_work_with_a_greeting(self):
        for s in ("hey ares", "hey aeries do it", "hey eris"):
            self.assertIsNotNone(self.n.heard_name(s), s)

    def test_no_greeting_does_not_wake(self):
        for s in ("Aries", "aries what time is it", "that is a good idea", "", "   "):
            self.assertIsNone(self.n.heard_name(s), s)

    def test_name_inside_a_sentence_does_not_wake(self):
        self.assertIsNone(self.n.heard_name("I told him hey aries is the phrase"))
        self.assertIsNone(self.n.heard_name("my star sign is aries"))

    def test_a_longer_greeting_is_not_taken_as_hey_plus_command(self):
        self.assertEqual(self.n.heard_name("hey there aries open firefox"), "open firefox")

    def test_the_phrase_is_configurable(self):
        ida = Names("Ida")
        self.assertEqual(ida.phrase, "hey Ida")
        self.assertEqual(ida.heard_name("hey either"), "")           # a known Whisper rendering
        self.assertIsNone(ida.heard_name("hey aries"))
        self.assertIsNone(self.n.heard_name("hey ida"))

    def test_unknown_name_gets_itself_and_possessive(self):
        n = Names("Nova")
        self.assertEqual(n.heard_name("hey nova play something"), "play something")
        self.assertEqual(n.heard_name("hey nova's"), "")

    def test_aliases(self):
        n = Names("Aries", aliases=("Ariadne",))
        self.assertEqual(n.heard_name("hey ariadne stop"), "stop")
        self.assertEqual(n.heard_name("hey aries stop"), "stop")


class ControlWords(unittest.TestCase):
    def setUp(self):
        self.n = Names("Aries")

    def test_send(self):
        for s in ("send", "Send it.", "go ahead", "aries send", "sent", "cent", "send!"):
            self.assertTrue(self.n.is_send(s), s)

    def test_send_is_the_whole_utterance(self):
        self.assertFalse(self.n.is_send("send it to him tomorrow"))
        self.assertFalse(self.n.is_send("spend"))
        self.assertFalse(self.n.is_send("bend"))
        self.assertFalse(self.n.is_send("what time is it"))
        self.assertFalse(self.n.is_send(""))

    def test_dismissal_is_the_whole_utterance(self):
        self.assertTrue(self.n.is_dismissal("Never mind."))
        self.assertTrue(self.n.is_dismissal("aries, that's all"))
        self.assertFalse(self.n.is_dismissal("nevermind, play the next one"))

    def test_skip(self):
        self.assertTrue(self.n.is_skip("Skip"))
        self.assertTrue(self.n.is_skip("aries be quiet"))
        self.assertFalse(self.n.is_skip("skip to the part about the cat"))

    def test_addressed_without_a_greeting(self):
        self.assertTrue(self.n.addressed("aries shut up"))
        self.assertTrue(self.n.addressed("hey aries"))
        self.assertFalse(self.n.addressed("shut up"))


class Helpers(unittest.TestCase):
    def test_flatten(self):
        self.assertEqual(flatten("Hey, Aries!  What's up?"), "hey aries what's up")

    def test_edit_distance(self):
        self.assertEqual(edit_distance("send", "sand", 1), 1)
        self.assertGreater(edit_distance("send", "stop", 1), 1)


if __name__ == "__main__":
    unittest.main()
