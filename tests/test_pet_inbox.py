import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ariadne2.core import pet_inbox


class PetInboxTest(unittest.TestCase):
    def test_drop_becomes_a_turn_that_is_not_his_words(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            with mock.patch.object(pet_inbox, "FOLDER", folder), mock.patch.object(pet_inbox, "INBOX", folder / "inbox.jsonl"):
                got = []

                async def run():
                    task = asyncio.create_task(pet_inbox.watch(lambda text, his_words=True: got.append((text, his_words)), poll=0.01))
                    await asyncio.sleep(0.03)
                    (folder / "inbox.jsonl").write_text(json.dumps({"t": "gave", "paths": ["/home/r/message Kai hi.png"]}) + "\n")
                    await asyncio.sleep(0.05)
                    task.cancel()
                asyncio.run(run())
        self.assertEqual(len(got), 1)
        self.assertIn("message Kai hi.png (image", got[0][0])
        self.assertFalse(got[0][1])

    def test_mood_line(self):
        with tempfile.TemporaryDirectory() as d:
            st = Path(d) / "state.json"
            st.write_text(json.dumps({"needs": {"energy": 0.18, "fun": 0.5, "affection": 0.7}, "mood": "sleepy", "holding": "plush"}))
            with mock.patch.object(pet_inbox, "STATE", st):
                line = pet_inbox.mood_line()
        self.assertIn("sleepy (energy 18%", line)
        self.assertIn("holding a plush", line)


if __name__ == "__main__":
    unittest.main()
