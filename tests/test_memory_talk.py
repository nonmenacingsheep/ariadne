import json
import tempfile
import time
import unittest
from pathlib import Path

from ariadne2.core.memory import Talk
from tests.memfakes import FakeEmbed

T0 = time.mktime((2026, 10, 3, 12, 0, 0, 0, 0, -1))
NOW = "2026-10-29"


class TalkTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "transcript.jsonl"
        self.t = Talk(self.path, embed=FakeEmbed())

    def test_turn_appended_dated_and_ordered(self):
        self.t.turn("hello  there", "hi.\n how are you", T0)
        rows = [json.loads(l) for l in self.path.read_text().splitlines()]
        self.assertEqual([(r["role"], r["text"]) for r in rows],
                         [("user", "hello there"), ("assistant", "hi. how are you")])
        self.assertLess(rows[0]["ts"], rows[1]["ts"])
        self.assertEqual(rows[0]["ts"], T0)
        self.assertEqual([r["role"] for r in Talk(self.path, embed=None).rows()], ["user", "assistant"])

    def test_empty_and_bad_role_not_written(self):
        self.assertFalse(self.t.append("user", "  "))
        self.assertFalse(self.t.append("system", "hi"))
        self.t.turn("only me", "", T0)                    # an empty reply isn't a line
        self.assertEqual(len(self.t.rows()), 1)

    def test_credentials_redacted(self):
        key = "sk-ant-" + "q9w8e7r6t5" * 4
        self.t.turn(f"my key is {key}", "ok", T0)
        self.assertNotIn(key, self.path.read_text())

    def test_recall_by_meaning_at_the_bar_and_framed_as_past(self):
        self.t.turn("the kettle on the tea bench keeps tripping the breaker", "move it off that circuit", T0)
        self.t.turn("what should I play tonight", "elden ring?", T0 + 86400)
        hits = self.t.recall("tea bench kettle")
        self.assertEqual(hits[0].row["role"], "user")
        self.assertGreaterEqual(hits[0].score, 0.45)
        self.assertEqual(self.t.recall("quantum lecture notes"), [])
        self.assertEqual(self.t.frame(hits[0].row, NOW),
                         'on 3 Oct (3 weeks ago) you said: "the kettle on the tea bench keeps tripping the breaker"')
        reply = self.t.frame(self.t.rows()[1], NOW)
        self.assertTrue(reply.startswith("on 3 Oct (3 weeks ago) I told you:"))

    def test_before_leaves_out_the_live_thread(self):
        self.t.turn("tea bench kettle trouble", "tea bench kettle noted", T0)
        self.t.turn("tea bench kettle trouble again", "tea bench kettle noted again", T0 + 3600)
        self.assertEqual(len(self.t.recall("tea bench kettle", k=10)), 4)
        old = self.t.recall("tea bench kettle", k=10, before=T0 + 1800)
        self.assertEqual([h.row["text"] for h in old if h.row["role"] == "user"], ["tea bench kettle trouble"])

    def test_words_fallback_is_stricter(self):
        t = Talk(self.path, embed=None)
        t.turn("the kettle on the tea bench keeps tripping the breaker", "ok", T0)
        self.assertEqual(len(t.recall("tea bench kettle breaker")), 1)
        self.assertEqual(t.recall("kettle"), [])          # one shared word is not enough
        self.assertEqual(t.recall("my puppy"), [])

    def test_picks_up_changes_made_by_another_process(self):
        self.assertEqual(self.t.rows(), [])
        with self.path.open("a") as fh:
            fh.write(json.dumps({"ts": T0, "role": "user", "text": "tea bench kettle"}) + "\n")
        self.assertEqual(len(self.t.recall("tea bench kettle")), 1)


if __name__ == "__main__":
    unittest.main()
