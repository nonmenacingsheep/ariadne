import json
import tempfile
import time
import unittest
from pathlib import Path

from ariadne2.core.memory import Facts, import_1x
from tests.memfakes import FakeEmbed

D = lambda s: time.mktime(time.strptime(s, "%Y-%m-%d")) + 43200       # noon, local


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.src, self.dest = Path(self.tmp.name) / "old", Path(self.tmp.name) / "new"
        self.src.mkdir()
        facts = {
            "Their dog is called Dirty birdie": D("2026-09-05"),
            "Opera GX is their default browser": D("2026-10-04"),
            "opera gx is their default browser.": D("2026-10-10"),              # a restatement
            "They would rather I stay quiet and just finish the job": D("2026-10-12"),
            "Turned off Steam shader pre-caching": D("2026-10-13"),
            "Their GPU has 12GB of memory and no more": D("2026-10-14"),
            "Their GPU has 24GB of memory and no more": D("2026-10-20"),          # contradicts
            "uses Opera GX now": D("2026-10-15"),
        }
        state = {"created": D("2026-08-30"), "facts": list(facts) + ["Undated fact about trains"],
                 "fact_when": facts,
                 "retired": [{"kind": "fact", "text": "Uses Firefox", "since": D("2026-09-01"), "until": D("2026-10-15"),
                              "replaced_by": "uses Opera GX now", "why": "replaced"},
                             {"kind": "fact", "text": "gone for good", "replaced_by": "", "why": "contradicted"}]}
        (self.src / "state.json").write_text(json.dumps(state))
        rows = [{"ts": D("2026-09-17") + i, "role": "user" if i % 2 == 0 else "assistant", "text": f"line {i}"}
                for i in range(6)]
        (self.src / "transcript.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")

    def run_import(self, **kw):
        return import_1x.run(self.src, self.dest, embed=FakeEmbed(), **kw)

    def test_dry_run_counts_and_writes_nothing(self):
        c = self.run_import(dry_run=True)
        self.assertEqual((c["facts_in_1x"], c["facts_imported"], c["duplicates_merged"]), (9, 8, 1))
        self.assertEqual((c["transcript_rows_imported"], c["transcript_user_turns_imported"]), (6, 3))
        self.assertEqual(c["history_links"], 1)
        self.assertEqual(c["undated_given_install_date"], 1)
        self.assertEqual(c["contradictions_listed"], 1)
        self.assertTrue(c["dry_run"])
        self.assertFalse(self.dest.exists())

    def test_real_run_mapping(self):
        c = self.run_import()
        facts = Facts(self.dest / "facts.jsonl", embed=None).all()
        by_text = {f["text"]: f for f in facts}
        self.assertEqual(len(facts), 9)                              # 8 current + 1 replaced Firefox
        browser = by_text["opera gx is their default browser."]       # the newest of the pair is kept
        self.assertEqual((browser["date"], browser["status"], browser["source"]),
                         ("2026-10-10", "current", "carried over from 1.x"))
        self.assertNotIn("Opera GX is their default browser", by_text)
        self.assertEqual(by_text["Their dog is called Dirty birdie"]["date"], "2026-09-05")
        self.assertEqual(by_text["Undated fact about trains"]["date"], "2026-08-30")
        self.assertEqual(by_text["Turned off Steam shader pre-caching"]["kind"], "event")
        self.assertEqual(by_text["They would rather I stay quiet and just finish the job"]["kind"], "preference")
        self.assertEqual(by_text["Their dog is called Dirty birdie"]["kind"], "fact")
        old, new = by_text["Uses Firefox"], by_text["uses Opera GX now"]
        self.assertEqual((old["status"], old["replaced_by"], new["replaces"]), ("replaced", new["id"], old["id"]))
        self.assertEqual(old["date"], "2026-09-01")
        self.assertNotIn("gone for good", by_text)
        pairs = json.loads((self.dest / import_1x.CONTRADICTIONS).read_text())["pairs"]
        self.assertEqual(len(pairs), c["contradictions_listed"])
        texts = {pairs[0]["a"]["text"], pairs[0]["b"]["text"]}
        self.assertEqual(texts, {"Their GPU has 12GB of memory and no more", "Their GPU has 24GB of memory and no more"})
        self.assertTrue(all(p["id"] for p in (pairs[0]["a"], pairs[0]["b"])))
        self.assertTrue({f["id"] for f in facts} >= {pairs[0]["a"]["id"], pairs[0]["b"]["id"]})
        # both sides are still current: nothing was guessed
        self.assertEqual({by_text[t]["status"] for t in texts}, {"current"})
        rows = [json.loads(l) for l in (self.dest / "transcript.jsonl").read_text().splitlines()]
        self.assertEqual(len(rows), 6)
        self.assertEqual(rows[0], {"ts": D("2026-09-17"), "role": "user", "text": "line 0"})

    def test_idempotent_and_never_resurrects(self):
        self.run_import()
        facts_file = (self.dest / "facts.jsonl").read_text()
        again = self.run_import()
        self.assertEqual((again["facts_imported"], again["transcript_rows_imported"],
                          again["history_links"], again["contradictions_listed"]), (0, 0, 0, 0))
        self.assertEqual((self.dest / "facts.jsonl").read_text(), facts_file)
        self.assertEqual(len((self.dest / "transcript.jsonl").read_text().splitlines()), 6)
        # he forgets one and settles nothing else: a re-run must not bring it back
        f = Facts(self.dest / "facts.jsonl", embed=None)
        dog = next(r for r in f.all() if "dog" in r["text"])
        f.forget(dog["id"])
        self.run_import()
        self.assertFalse(any("dog" in r["text"] for r in Facts(self.dest / "facts.jsonl", embed=None).all()))

    def test_new_2x_turns_survive_a_rerun_in_order(self):
        self.run_import()
        with (self.dest / "transcript.jsonl").open("a") as fh:
            fh.write(json.dumps({"ts": D("2026-10-29"), "role": "user", "text": "a 2.0 turn"}) + "\n")
        (self.src / "transcript.jsonl").write_text((self.src / "transcript.jsonl").read_text()
                                                   + json.dumps({"ts": D("2026-09-18"), "role": "user", "text": "late 1.x"}) + "\n")
        self.run_import()
        rows = [json.loads(l)["text"] for l in (self.dest / "transcript.jsonl").read_text().splitlines()]
        self.assertEqual((len(rows), rows[-1], "late 1.x" in rows), (8, "a 2.0 turn", True))

    def test_kind_guess_is_cautious(self):
        for text, kind in [("Their dog is called Birdie", "fact"), ("Asked about TRIPO3D at $20", "event"),
                           ("They'd rather I stay quiet", "preference"), ("Decided on Opera instead of Firefox", "decision")]:
            self.assertEqual(import_1x.guess_kind(text), kind)

    def test_missing_1x_is_harmless(self):
        c = import_1x.run(Path(self.tmp.name) / "nothing", self.dest, embed=FakeEmbed())
        self.assertEqual((c["facts_imported"], c["transcript_rows_imported"]), (0, 0))


if __name__ == "__main__":
    unittest.main()
