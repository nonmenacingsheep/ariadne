import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ariadne2.core.memory import Facts, when
from ariadne2.core.memory.facts import age_weight
from tests.memfakes import FakeEmbed

NOW = "2026-10-29"


class FactsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "facts.jsonl"
        self.f = Facts(self.path, embed=FakeEmbed())

    def lines(self):
        return [json.loads(l) for l in self.path.read_text().splitlines()]

    def test_record_shape_one_per_line(self):
        rec = self.f.add("uses Opera GX as his browser", "preference", because="Discord works better",
                         date="2026-10-01")
        self.assertEqual(set(rec), {"id", "text", "kind", "date", "source", "status", "replaces",
                                    "replaced_by", "because", "rejected"})
        self.assertEqual((rec["id"], rec["kind"], rec["date"], rec["status"], rec["source"]),
                         (1, "preference", "2026-10-01", "current", "said in chat"))
        self.f.add("has a dog called Birdie", "fact", now=NOW)
        rows = self.lines()
        self.assertEqual([r["id"] for r in rows], [1, 2])
        self.assertEqual(rows[1]["date"], NOW)
        self.assertEqual(rows[1]["rejected"], [])
        # a fresh object over the same file sees the same records
        self.assertEqual([r["text"] for r in Facts(self.path, embed=None).all()],
                         ["uses Opera GX as his browser", "has a dog called Birdie"])

    def test_bad_kind_and_event_is_done(self):
        with self.assertRaises(ValueError):
            self.f.add("x y z", "mood")
        self.assertEqual(self.f.add("went to the dentist", "event")["status"], "done")

    def test_rewrite_is_atomic(self):
        a = self.f.add("uses Firefox", "preference", date="2026-09-02")
        before = self.path.read_text()
        with mock.patch("os.replace", side_effect=OSError("disk gone")):
            with self.assertRaises(OSError):
                self.f.add("uses Opera GX", "preference", replaces=a["id"])
        self.assertEqual(self.path.read_text(), before)              # the old file is whole
        self.f2 = Facts(self.path, embed=None)
        self.assertEqual(self.f2.get(1)["status"], "current")
        self.f.add("uses Opera GX", "preference", replaces=1)        # and it works afterwards
        self.assertFalse(list(Path(self.tmp.name).glob("*.tmp")))

    def test_torn_last_line_is_skipped(self):
        self.f.add("one thing here", "fact")
        with self.path.open("a") as fh:
            fh.write('{"id": 2, "text": "cut off')
        self.assertEqual([r["id"] for r in Facts(self.path, embed=None).all()], [1])

    def test_replace_links_both_ways_and_excludes_replaced(self):
        old = self.f.add("uses Firefox as his browser", "preference", date="2026-09-02")
        new = self.f.add("uses Opera GX as his browser", "preference", replaces=old["id"],
                         because="Discord's web client works better in it", date="2026-10-01")
        self.assertEqual(new["replaces"], 1)
        o = self.f.get(1)
        self.assertEqual((o["status"], o["replaced_by"]), ("replaced", 2))
        self.assertEqual([h.rec["id"] for h in self.f.recall("which browser", NOW)], [2])
        hist = self.f.recall("which browser", NOW, history=True)
        self.assertEqual({h.rec["id"] for h in hist}, {1, 2})
        self.assertEqual([r["id"] for r in self.f.chain(2)], [1, 2])
        self.assertEqual([r["id"] for r in self.f.chain(1)], [1, 2])
        line = self.f.describe(o, NOW)
        self.assertIn("replaced 1 Oct by #2", line)
        self.assertIn("Discord's web client", line)
        with self.assertRaises(ValueError):
            self.f.add("uses Chrome", "preference", replaces=1)       # already replaced
        with self.assertRaises(ValueError):
            self.f.add("uses Chrome", "preference", replaces=99)

    def test_same_text_with_replaces_just_links(self):
        self.f.add("uses Firefox as his browser", "preference")
        self.f.add("uses Opera GX as his browser", "preference")
        again = self.f.add("uses Opera GX as his browser", "preference", replaces=1)
        self.assertEqual(len(self.f.all()), 2)
        self.assertEqual(again["replaces"], 1)
        self.assertEqual(self.f.get(1)["replaced_by"], 2)

    def test_forget_unlinks(self):
        self.f.add("uses Firefox", "preference")
        self.f.add("uses Opera GX", "preference", replaces=1)
        self.assertEqual(self.f.forget(2)["id"], 2)
        self.assertIsNone(self.f.forget(2))
        self.assertIsNone(self.f.get(1)["replaced_by"])
        self.assertEqual(len(self.lines()), 1)

    def test_age_weights_by_kind(self):
        for kind in ("event", "plan", "decision", "preference", "fact"):
            self.assertEqual(age_weight(kind, NOW, NOW), 1.0)
        month = "2026-09-29"
        w = {k: age_weight(k, month, NOW) for k in ("event", "plan", "decision", "preference", "fact")}
        self.assertLess(w["event"], 0.25)
        self.assertLess(w["plan"], 0.4)
        self.assertGreater(w["decision"], 0.75)
        self.assertGreater(w["preference"], 0.98)
        self.assertGreater(w["decision"], w["plan"])
        self.assertGreater(w["plan"], w["event"])

    def test_recall_orders_by_relevance_times_age(self):
        # all four contain "tea bench", so relevance is equal and only age tells them apart
        self.f.add("working on the tea bench", "event", date="2026-08-20")        # 70 days: faded
        self.f.add("tea bench is where he prefers working", "preference", date="2026-06-01")
        self.f.add("tea bench plan for next week", "plan", date="2026-08-15")
        self.f.add("tea bench build started", "event", date="2026-10-28")
        order = [h.rec["id"] for h in self.f.recall("tea bench", NOW)]
        self.assertEqual(order, [4, 2, 3, 1])      # fresh event, ageless preference, faded plan, faded event
        # a faded event is dropped from the per-turn context but not from a direct recall
        kept = [h.rec["id"] for h in self.f.recall("tea bench", NOW, min_weight=0.15)]
        self.assertEqual(kept, [4, 2])

    def test_relevance_bars(self):
        self.f.add("keeps a dog called Birdie", "fact")
        self.f.add("plays Elden Ring on the weekend", "fact")
        ids = [h.rec["id"] for h in self.f.recall("how is my puppy", NOW)]    # meaning, no shared word
        self.assertEqual(ids, [1])
        self.assertEqual(self.f.recall("quantum chromodynamics lecture", NOW), [])

    def test_words_only_fallback(self):
        f = Facts(self.path, embed=None)
        f.add("uses Opera GX as his browser", "preference")
        f.add("has a dog called Birdie", "fact")
        self.assertEqual([h.how for h in f.recall("opera gx browser", NOW)], ["words"])
        self.assertEqual(f.recall("my puppy", NOW), [])

    def test_rejected_options_surface_with_their_topic(self):
        self.f.add("uses Opera GX as his browser", "decision", date="2026-10-01",
                   because="Discord's web client works better in it",
                   rejected=["Firefox -- Discord's web client is flaky there", {"option": "Chrome", "reason": "no GX tools"}])
        self.f.add("has a dog called Birdie", "fact")
        hits = self.f.recall("should I try Firefox?", NOW)
        self.assertEqual([h.rec["id"] for h in hits], [1])
        line = self.f.describe(hits[0].rec, NOW)
        self.assertIn("turned down: Firefox -- Discord's web client is flaky there; Chrome -- no GX tools", line)
        self.assertIn("because Discord's web client works better in it", line)
        # and the topic of the decision brings the same record
        self.assertEqual([h.rec["id"] for h in self.f.recall("which browser", NOW)], [1])

    def test_past_framing(self):
        ev = self.f.add("working on the tea bench", "event", date="2026-10-08")
        plan = self.f.add("build the tea workbench", "plan", date="2026-10-08")
        pref = self.f.add("likes oolong", "preference", date="2026-09-02")
        self.assertIn("happened 3 weeks ago, 8 Oct", self.f.describe(ev, NOW))
        self.assertIn("planned 3 weeks ago, 8 Oct; may have moved on", self.f.describe(plan, NOW))
        self.assertNotIn("ago", self.f.describe(pref, NOW))
        self.assertIn("since 2 Sep", self.f.describe(pref, NOW))
        self.assertEqual(when.ago("2026-10-28", NOW), "yesterday")
        self.assertEqual(when.short("2025-10-03", NOW), "3 Oct 2025")

    def test_credentials_redacted_before_saving(self):
        key = "sk-ant-" + "a1b2c3d4e5" * 4
        rec = self.f.add(f"his api key is {key}", "fact", because=f"token={key}")
        self.assertNotIn(key, self.path.read_text())
        self.assertIn("[redacted credential]", rec["text"])
        self.assertGreaterEqual(self.f.redactions, 2)
        with self.assertRaises(ValueError):
            self.f.add(key, "fact")                                   # nothing left but the secret
        self.assertEqual(len(self.f.all()), 1)

    def test_near_finds_same_subject(self):
        self.f.add("uses Firefox as his browser", "preference", date="2026-09-02")
        self.f.add("has a dog called Birdie", "fact")
        near = self.f.near("uses Opera GX as his browser")
        self.assertEqual([r["id"] for r, _ in near], [1])
        self.assertEqual(self.f.near("plays Elden Ring"), [])


if __name__ == "__main__":
    unittest.main()
