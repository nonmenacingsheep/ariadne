import unittest

from ariadne2.core.voice.text import (MarkStream, SkipTracker, chunks, ends_sentence,
                                      next_chunk, speakable, strip_marks)


class Speakable(unittest.TestCase):
    def test_link_is_its_site(self):
        self.assertEqual(speakable("it's at https://www.ups.com/track?n=1 if you want"),
                         "it's at ups.com if you want")

    def test_ids_hashes_numbers(self):
        self.assertEqual(speakable("tracking 1Z0179WE0328075077 says delivered"),
                         "tracking an ID says delivered")
        self.assertEqual(speakable("commit 3ca7583f1e9a0b2c4d5e6f7a8b9c0d1e is in"),
                         "commit a hash is in")
        self.assertEqual(speakable("the order is 4 512 887 230 91"), "the order is a long number")
        self.assertEqual(speakable("mail ronald@example.com now"), "mail an email address now")

    def test_ordinary_numbers_are_said(self):
        s = "81% full, 167G free, port 8081, since 2019, about $1,400 a month"
        self.assertEqual(speakable(s), s)

    def test_code_and_markup(self):
        self.assertEqual(speakable("run ```rm -rf x``` then **go**"), "run (code omitted) then go")

    def test_marks_are_left_for_strip_marks(self):
        self.assertIn("((excited))", speakable("((excited)) it worked"))


class Marks(unittest.TestCase):
    def test_emotion_and_rate(self):
        words, rate, emo = strip_marks("((sarcastic)) oh, brilliant. ((slow)) really.")
        self.assertEqual((rate, emo), (0.78, "sarcastic"))
        self.assertNotIn("((", words)

    def test_first_emotion_wins(self):
        self.assertEqual(strip_marks("((calm)) a ((excited)) b")[2], "calm")

    def test_an_unknown_mark_is_never_read_aloud(self):
        self.assertEqual(strip_marks("((grumpy)) hm"), (" hm", 1.0, ""))

    def test_a_group_heading_used_as_a_mark_means_its_plainest_member(self):
        self.assertEqual(strip_marks("((uneasy)) Honestly."), (" Honestly.", 1.0, "anxious"))

    def test_stream_holds_split_marks(self):
        s = MarkStream()
        shown = "".join(s.feed(c) for c in ["((apolo", "getic)) sorry. ", "((fast)) anyway"]) + s.flush()
        self.assertEqual(shown, "sorry. anyway")

    def test_stream_leaves_plain_text(self):
        s = MarkStream()
        self.assertEqual(s.feed("see ((this)) here") + s.flush(), "see ((this)) here")
        s = MarkStream()
        self.assertEqual(s.feed("a ((") + s.feed("x))") + s.flush(), "a ((x))")

    def test_stream_keeps_skipped_words_on_screen(self):
        s = MarkStream()
        shown = "".join(s.feed(c) for c in ["path ((sk", "ip))~/x((/sk", "ip)) done"]) + s.flush()
        self.assertEqual(shown, "path ~/x done")


class Skips(unittest.TestCase):
    def test_within_one_chunk(self):
        self.assertEqual(" ".join(SkipTracker().apply("the path ((skip))~/.config/x((/skip)) is yours").split()),
                         "the path is yours")

    def test_across_chunks_including_a_chunk_wholly_inside(self):
        t = SkipTracker()
        self.assertEqual(t.apply("run this: ((skip))rm -rf ~/x").strip(), "run this:")
        self.assertEqual(t.apply("this middle chunk is all skipped."), "")
        self.assertEqual(t.apply("--force((/skip)) and it's gone").strip(), "and it's gone")
        self.assertFalse(t.inside)

    def test_reset(self):
        t = SkipTracker()
        t.apply("((skip))a")
        t.reset()
        self.assertEqual(t.apply("spoken"), "spoken")


class Chunking(unittest.TestCase):
    def test_short_line_is_one_chunk(self):
        self.assertEqual(chunks("Hey."), ["Hey."])
        self.assertEqual(chunks("  "), [])

    def test_abbreviation_does_not_end_a_chunk(self):
        for piece in chunks("See Dr. Smith about it. Then come back. " * 3):
            self.assertFalse(piece.endswith("Dr."))

    def test_sentences_stay_in_order_and_complete(self):
        text = "One. Two. Three. " + "A longer sentence that runs on. " * 6
        self.assertEqual(" ".join(chunks(text)).split(), text.split())

    def test_first_chunk_breaks_on_a_clause_when_the_sentence_is_long(self):
        s = "I found three of them in the downloads folder, and two of them look like duplicates of each other."
        piece, rest = next_chunk(s + " Next.", first=True)
        self.assertTrue(piece.endswith("folder,") or piece.endswith("folder"), piece)

    def test_streaming_holds_a_half_sentence(self):
        piece, rest = next_chunk("I found three of them and", first=True)
        self.assertIsNone(piece)
        self.assertEqual(rest, "I found three of them and")

    def test_final_releases_the_tail(self):
        self.assertEqual(next_chunk("half a thought", first=True, final=True), ("half a thought", ""))

    def test_a_runaway_sentence_is_cut_at_a_space(self):
        piece, rest = next_chunk("and then " + "words " * 80)
        self.assertIsNotNone(piece)
        self.assertLessEqual(len(piece), 125)
        self.assertFalse(piece.endswith("wor"))

    def test_ends_sentence(self):
        self.assertTrue(ends_sentence("Done."))
        self.assertTrue(ends_sentence('He said "no."'))
        self.assertFalse(ends_sentence("Well, so"))


if __name__ == "__main__":
    unittest.main()
