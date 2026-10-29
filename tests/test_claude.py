import asyncio
import json
import logging
import os
import signal
import tempfile
import time
import unittest
from pathlib import Path

from ariadne2.adapters import AdapterError, call_tool, consent
from ariadne2.adapters import claude as cl
from ariadne2.core.flows import graph as G
from ariadne2.core.flows.catalog import Catalog
from tests.flowfakes import FakeApp, Rig, g

SECRET = "sk-ant-api03-ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
PRIVATE_TEXT = "the quarterly numbers are in the blue folder"


async def _pub(m):
    pass


# --- fake transcripts, in the shape Claude Code writes them ---

def ts(t):
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(t))


def user(text, t, cwd="/home/u/proj"):
    return {"type": "user", "timestamp": ts(t), "cwd": cwd, "message": {"role": "user", "content": text}}


def tool_use(tid, name, inp, t):
    return {"type": "assistant", "timestamp": ts(t), "message": {
        "role": "assistant", "stop_reason": "tool_use",
        "content": [{"type": "tool_use", "id": tid, "name": name, "input": inp}]}}


def result(tid, text="ok", t=0):
    return {"type": "user", "timestamp": ts(t), "message": {
        "role": "user", "content": [{"type": "tool_result", "tool_use_id": tid, "content": text}]}}


def said(text, t, stop="end_turn"):
    return {"type": "assistant", "timestamp": ts(t), "message": {
        "role": "assistant", "stop_reason": stop, "content": [{"type": "text", "text": text}]}}


class Home:
    """A fake home with a ~/.claude/projects tree."""

    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name).resolve()
        self.projects = self.path / ".claude" / "projects"
        self.projects.mkdir(parents=True)
        self.work = self.path / "work"
        self.work.mkdir()

    def session(self, sid, entries, folder="-home-u-proj", age=5.0):
        d = self.projects / folder
        d.mkdir(exist_ok=True)
        f = d / f"{sid}.jsonl"
        with open(f, "w") as fh:
            for e in entries:
                fh.write(json.dumps(e, separators=(",", ":")) + "\n")
        t = time.time() - age
        os.utime(f, (t, t))
        return f

    def adapter(self, **kw):
        a = cl.ClaudeAdapter(_pub, home=self.path, exe=kw.pop("exe", "/usr/bin/claude"), **kw)
        a.settle = 0
        return a


class FakeProc:
    def __init__(self, pid):
        self.pid = pid

    def poll(self):
        return None


class Launcher:
    def __init__(self):
        self.calls = []
        self.alive = set()
        self.killed = []
        self.pid = 4000

    def launch(self, argv, cwd):
        self.pid += 1
        self.calls.append((argv, cwd))
        self.alive.add(self.pid)
        return FakeProc(self.pid)

    def is_alive(self, pid, run_id=""):
        return pid in self.alive

    def kill(self, pid, sig):
        self.killed.append((pid, sig))
        self.alive.discard(pid)


def rig(h):
    la = Launcher()
    a = h.adapter(launcher=la.launch, alive=la.is_alive, killer=la.kill, opener=None)
    opened = []

    async def opener(path):
        opened.append(path)
    a._open = opener
    a.opened = opened
    return a, la


class ParsingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.h = Home()
        self.addCleanup(self.h.tmp.cleanup)
        self.t0 = time.time() - 600

    async def rows(self, a):
        await a.refresh()
        return {r["id"]: r for r in a.state()["sessions"]}

    async def test_pending_tool_call_is_working_with_its_last_step(self):
        t = self.t0
        self.h.session("a" * 8 + "-0000", [
            user("fix the build", t), tool_use("t1", "Read", {"file_path": "/home/u/proj/src/main.py"}, t + 1),
            result("t1", t=t + 2), tool_use("t2", "Edit", {"file_path": "/home/u/proj/web/desk.js"}, t + 3)],
            age=100)                                           # quiet for 100 s, but a call is still out
        r = (await self.rows(self.h.adapter()))["a" * 8 + "-0000"]
        self.assertEqual((r["state"], r["last"], r["steps"], r["project"], r["mine"]),
                         ("working", "Edit desk.js", 2, "proj", False))
        self.assertEqual(r["title"], "fix the build")
        self.assertAlmostEqual(r["started"], t, delta=2)

    async def test_assistant_turn_end_is_waiting_even_when_fresh(self):
        t = self.t0
        self.h.session("s1", [user("go", t), tool_use("t1", "Bash", {"command": "cd /x && python3 -m unittest discover -s tests"}, t + 1),
                              result("t1", t=t + 2), said("done", t + 3)], age=1)
        r = (await self.rows(self.h.adapter()))["s1"]
        self.assertEqual((r["state"], r["last"], r["steps"]), ("waiting", "Bash: python3 -m unittest discover", 1))

    async def test_mid_turn_is_working_then_waiting_when_it_goes_quiet(self):
        t = self.t0
        entries = [user("go", t), tool_use("t1", "Grep", {"pattern": "def main"}, t + 1), result("t1", t=t + 2)]
        self.h.session("fresh", entries, age=10)
        self.h.session("stale", entries, age=300)
        rows = await self.rows(self.h.adapter())
        self.assertEqual((rows["fresh"]["state"], rows["stale"]["state"]), ("working", "waiting"))
        self.assertEqual(rows["fresh"]["last"], "Grep def main")

    async def test_old_pending_call_is_not_working_forever(self):
        self.h.session("dead", [user("go", self.t0), tool_use("t1", "Bash", {"command": "sleep 9"}, self.t0 + 1)],
                       age=cl.PENDING_MAX + 60)
        self.assertEqual((await self.rows(self.h.adapter()))["dead"]["state"], "waiting")

    async def test_interrupted_request_is_waiting(self):
        self.h.session("int", [user("go", self.t0), tool_use("t1", "Bash", {"command": "ls"}, self.t0 + 1),
                               result("t1", t=self.t0 + 2), user("[Request interrupted by user]", self.t0 + 3)], age=2)
        self.assertEqual((await self.rows(self.h.adapter()))["int"]["state"], "waiting")

    async def test_titles_prefer_custom_then_ai_then_first_prompt(self):
        t = self.t0
        self.h.session("c", [user("some prompt", t), {"type": "ai-title", "aiTitle": "AI summary"},
                             {"type": "custom-title", "customTitle": "Named by him"}, said("hi", t + 1)])
        self.h.session("d", [user("some prompt", t), {"type": "ai-title", "aiTitle": "AI summary"}, said("hi", t + 1)])
        self.h.session("e", [{"type": "queue-operation", "content": "ignore"},
                             user("<system-reminder>boilerplate</system-reminder>", t), user("x" * 200, t + 1)])
        rows = await self.rows(self.h.adapter())
        self.assertEqual((rows["c"]["title"], rows["d"]["title"]), ("Named by him", "AI summary"))
        self.assertEqual(rows["e"]["title"], "x" * 59 + "…")

    async def test_step_count_is_incremental_over_a_growing_file(self):
        t = self.t0
        f = self.h.session("g", [user("go", t), tool_use("t1", "Read", {"file_path": "/a/b.py"}, t + 1), result("t1", t=t + 2)])
        a = self.h.adapter()
        self.assertEqual((await self.rows(a))["g"]["steps"], 1)
        with open(f, "a") as fh:
            for i in range(2, 5):
                fh.write(json.dumps(tool_use(f"t{i}", "Read", {"file_path": "/a/b.py"}, t + i), separators=(",", ":")) + "\n")
        self.assertEqual((await self.rows(a))["g"]["steps"], 4)
        self.assertEqual(a._steps[f][1], 4)

    async def test_a_huge_last_result_does_not_hide_the_state(self):
        t = self.t0
        self.h.session("big", [user("go", t), tool_use("t1", "Read", {"file_path": "/a/b.py"}, t + 1),
                               result("t1", "x" * (cl.TAIL_BYTES * 3), t + 2), said("done", t + 3),
                               user("again", t + 4), result("zz", "y" * (cl.TAIL_BYTES * 2), t + 5)], age=3)
        r = (await self.rows(self.h.adapter()))["big"]
        self.assertEqual((r["state"], r["last"]), ("working", "Read b.py"))

    async def test_window_and_row_limit(self):
        t = self.t0
        self.h.session("old", [user("go", t), said("x", t + 1)], age=cl.WINDOW + 600)
        for i in range(10):
            self.h.session(f"s{i}", [user("go", t), said("x", t + 1)], age=60 + i * 10)
        rows = await self.rows(self.h.adapter())
        self.assertNotIn("old", rows)
        self.assertEqual(len(rows), cl.MAX_ROWS)
        a = self.h.adapter()
        await a.refresh()
        self.assertEqual([r["id"] for r in a.state()["sessions"]], [f"s{i}" for i in range(8)])   # most recent first

    async def test_a_background_agent_keeps_the_session_fresh(self):
        t = self.t0
        self.h.session("bg", [user("go", t), said("started it", t + 1)], age=cl.WINDOW + 600)
        sub = self.h.projects / "-home-u-proj" / "bg" / "subagents"
        sub.mkdir(parents=True)
        (sub / "agent-1.jsonl").write_text("{}\n")
        self.assertIn("bg", await self.rows(self.h.adapter()))

    async def test_no_claude(self):
        import shutil
        h = Home()
        self.addCleanup(h.tmp.cleanup)
        h.projects.rmdir() if not any(h.projects.iterdir()) else None
        os.rmdir(h.projects.parent)
        old = shutil.which
        cl.shutil.which = lambda *_: None
        try:
            a = cl.ClaudeAdapter(_pub, home=h.path)
            await a.refresh()
        finally:
            cl.shutil.which = old
        self.assertEqual(a.state(), {"status": "no claude", "sessions": []})


class PrivacyTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_message_content_in_state_status_or_logs(self):
        h = Home()
        self.addCleanup(h.tmp.cleanup)
        t = time.time() - 300
        h.session("p", [
            user(f"deploy with key {SECRET} please, {PRIVATE_TEXT}", t),
            {"type": "assistant", "timestamp": ts(t + 1), "message": {"role": "assistant", "stop_reason": "tool_use", "content": [
                {"type": "thinking", "thinking": "SECRET-THOUGHT " + PRIVATE_TEXT},
                {"type": "text", "text": "ASSISTANT-WORDS " + PRIVATE_TEXT}]}},
            tool_use("t1", "Bash", {"command": f"curl -H 'Authorization: Bearer {SECRET}' --token={SECRET} https://api.x/y"}, t + 2),
            result("t1", "RESULT-BODY " + PRIVATE_TEXT, t + 3),
            tool_use("t2", "Write", {"file_path": "/home/u/proj/notes.txt", "content": "FILE-BODY " + PRIVATE_TEXT}, t + 4),
            result("t2", t=t + 5), said("FINAL-WORDS " + PRIVATE_TEXT, t + 6)], age=20)
        a = h.adapter()
        records = []
        handler = logging.Handler()
        handler.emit = records.append
        logging.getLogger().addHandler(handler)
        logging.getLogger().setLevel(logging.DEBUG)
        try:
            await a.refresh()
            text = await a._status()
        finally:
            logging.getLogger().removeHandler(handler)
        blob = json.dumps(a.state()) + text + "\n".join(r.getMessage() for r in records)
        for leak in (SECRET, "SECRET-THOUGHT", "ASSISTANT-WORDS", "RESULT-BODY", "FILE-BODY", "FINAL-WORDS",
                     "quarterly numbers"):
            self.assertNotIn(leak, blob)
        row = a.state()["sessions"][0]
        self.assertEqual(row["last"], "Write notes.txt")
        self.assertIn("[redacted credential]", row["title"])

    def test_last_step_for_a_bash_call_is_only_the_first_words(self):
        self.assertEqual(cl.tool_label("Bash", {"command": f"cd /x && TOKEN=abc123456 git commit -m 'a long private message {SECRET}'"}),
                         "Bash: git commit -m")
        self.assertEqual(cl.tool_label("Bash", {"command": "ls /secret/path/dir | grep -i password"}), "Bash: ls dir")
        self.assertEqual(cl.tool_label("Bash", {"command": f"echo {SECRET}"}), "Bash: echo [redacted credential]")
        self.assertEqual(cl.tool_label("mcp__srv__do_thing", {"q": "private"}), "do_thing")
        self.assertEqual(cl.tool_label("WebFetch", {"url": "https://example.com/a/b?token=1"}), "WebFetch example.com")
        self.assertEqual(cl.tool_label("Agent", {"prompt": "private"}), "Agent")


class SpendConsentTests(unittest.IsolatedAsyncioTestCase):
    def test_his_words_must_ask_for_claude_or_a_hand(self):
        ok = consent.allows_spend
        self.assertTrue(ok("have claude fix the tests"))
        self.assertTrue(ok("can you ask Claude Code to refactor the loop?"))
        self.assertTrue(ok("start claude on the widget in ariadne2"))
        self.assertTrue(ok("run a claude code session for the audit"))
        self.assertTrue(ok("hand it off to a second hand"))
        self.assertTrue(ok("let claude handle that"))
        self.assertFalse(ok("fix the tests"))
        self.assertFalse(ok("what is the weather"))
        self.assertFalse(ok("claude is a nice name"))
        self.assertFalse(ok("don't use claude for this"))
        self.assertFalse(ok("do it without claude"))
        self.assertFalse(ok(""))
        self.assertFalse(ok(None))

    async def test_call_tool_gates_start_on_his_words(self):
        h = Home()
        self.addCleanup(h.tmp.cleanup)
        a, la = rig(h)
        adapters = {"claude": a}
        args = {"task": "run the tests and fix what fails", "folder": str(h.work)}
        for words in (None, "", "fix the tests", "what's claude up to?"):
            with self.assertRaises(AdapterError):
                await call_tool(adapters, "claude_start", args, his_words=words)
        self.assertEqual(la.calls, [])
        out = await call_tool(adapters, "claude_start", args, his_words="have claude fix the tests")
        self.assertIn("Started a Claude Code run", out)
        self.assertEqual(len(la.calls), 1)
        # the other verbs never need it
        await call_tool(adapters, "claude_status", {}, his_words=None)

    def test_the_verb_declares_spend(self):
        a = cl.ClaudeAdapter(_pub, home=Path(tempfile.gettempdir()) / "nohome-claude-test")
        self.assertEqual({v.name: v.consent for v in a.verbs},
                         {"start": "spend", "status": None, "stop": None, "open": None})
        self.assertEqual(a.verb("start").control, "start")
        self.assertEqual(a.controls, {"stop": "stop", "open": "open"})     # a widget press can't start a run


class StartTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.h = Home()
        self.addCleanup(self.h.tmp.cleanup)
        self.a, self.la = rig(self.h)

    async def test_start_launches_a_detached_headless_run_in_the_folder(self):
        out = await self.a._start(f"fix the tests, key {SECRET}", str(self.h.work))
        argv, cwd = self.la.calls[0]
        self.assertEqual(cwd, str(self.h.work))
        self.assertEqual(argv[:2], ["sh", "-c"])
        claude = argv[argv.index("/usr/bin/claude"):]
        self.assertIn("-p", claude)
        self.assertEqual(claude[claude.index("--output-format") + 1], "stream-json")
        self.assertIn("--verbose", claude)
        sid = claude[claude.index("--session-id") + 1]
        self.assertEqual(claude[claude.index("--permission-mode") + 1], "acceptEdits")
        self.assertNotIn("--dangerously-skip-permissions", claude)
        self.assertIn("--max-budget-usd", claude)
        self.assertNotIn("fix the tests", " ".join(argv))                  # the brief goes on stdin, not argv
        task = self.h.path / ".local/share/ariadne2/hands" / f"{sid}.task"
        self.assertIn("fix the tests", task.read_text())
        self.assertEqual(oct(task.stat().st_mode & 0o777), "0o600")
        self.assertIn(sid[:8], out)
        row = self.a.state()["sessions"][0]
        self.assertEqual((row["id"], row["mine"], row["state"], row["project"], row["last"]),
                         (sid, True, "working", "work", "starting"))
        self.assertNotIn(SECRET, json.dumps(self.a.state()))
        reg = json.loads((self.h.path / ".local/share/ariadne2/hands/runs.json").read_text())
        self.assertEqual((reg[0]["id"], reg[0]["pid"]), (sid, 4001))

    async def test_refuses_bad_folders_short_briefs_and_a_third_hand(self):
        with self.assertRaises(AdapterError):
            await self.a._start("do something useful", "/etc")
        with self.assertRaises(AdapterError):
            await self.a._start("do something useful", str(self.h.path / "nope"))
        with self.assertRaises(AdapterError):
            await self.a._start("hi", str(self.h.work))
        self.assertEqual(self.la.calls, [])
        await self.a._start("first job in full", str(self.h.work))
        await self.a._start("second job in full", "work")             # relative to home
        with self.assertRaisesRegex(AdapterError, "both hands are busy"):
            await self.a._start("third job in full", str(self.h.work))
        self.assertEqual(len(self.la.calls), 2)

    async def test_no_claude_installed(self):
        cl.shutil.which, old = (lambda *_: None), cl.shutil.which
        try:
            a = cl.ClaudeAdapter(_pub, home=self.h.path, launcher=self.la.launch)
            with self.assertRaisesRegex(AdapterError, "isn't installed"):
                await a._start("do something useful", str(self.h.work))
        finally:
            cl.shutil.which = old

    def test_build_command(self):
        cmd = cl.build_command("claude", "sid-1", 2.5)
        self.assertEqual(cmd[0], "claude")
        self.assertIn("2.50", cmd)
        self.assertEqual(cmd[-len(cl.HAND_TOOLS):], list(cl.HAND_TOOLS))   # variadic option goes last
        self.assertNotIn("Bash", cmd)                                        # no bare Bash


class RunLifecycleTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.h = Home()
        self.addCleanup(self.h.tmp.cleanup)
        self.a, self.la = rig(self.h)
        self.events = []
        self.a.subscribe(lambda ev, f: self.events.append((ev, f)))

    def finish(self, sid, code):
        (self.a.root / f"{sid}.exit").write_text(f"{code}\n")

    async def started(self, task="fix the tests please"):
        await self.a._start(task, str(self.h.work))
        return self.a.runs[-1]["id"]

    async def test_exit_zero_is_done_and_announced_once(self):
        sid = await self.started()
        self.finish(sid, 0)
        await self.a.refresh()
        row = self.a.state()["sessions"][0]
        self.assertEqual((row["state"], row["mine"]), ("done", True))
        await self.a.refresh()
        self.assertEqual(self.events, [("claude.hand_finished", {"title": "fix the tests please", "state": "done"})])

    async def test_nonzero_exit_and_a_killed_run_are_failed(self):
        s1 = await self.started("first job in full")
        s2 = await self.started("second job in full")
        self.finish(s1, 2)
        self.la.alive.discard(self.a._run(s2)["pid"])             # gone, no exit file
        await self.a.refresh()
        rows = {r["id"]: r for r in self.a.state()["sessions"]}
        self.assertEqual((rows[s1]["state"], rows[s2]["state"]), ("failed", "failed"))
        self.assertEqual(sorted(f["state"] for _, f in self.events), ["failed", "failed"])

    async def test_a_run_that_ended_while_the_core_was_down_is_announced_on_restart(self):
        sid = await self.started()
        self.finish(sid, 0)
        b = self.h.adapter(launcher=self.la.launch, alive=self.la.is_alive)
        got = []
        b.subscribe(lambda ev, f: got.append(ev))
        await b.refresh()                                         # baseline, but a finish is still news
        self.assertEqual(got, ["claude.hand_finished"])
        await b.refresh()
        self.assertEqual(got, ["claude.hand_finished"])
        c = self.h.adapter(launcher=self.la.launch, alive=self.la.is_alive)
        got2 = []
        c.subscribe(lambda ev, f: got2.append(ev))
        await c.refresh()
        self.assertEqual(got2, [])                                # already announced

    async def test_working_run_keeps_its_transcript_steps(self):
        sid = await self.started()
        t = time.time() - 30
        self.h.session(sid, [user("fix the tests please", t, cwd=str(self.h.work)),
                             tool_use("t1", "Edit", {"file_path": str(self.h.work / "a_test.py")}, t + 1)],
                       folder="-home-u-work", age=2)
        await self.a.refresh()
        rows = self.a.state()["sessions"]
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["state"], rows[0]["last"], rows[0]["steps"], rows[0]["mine"]),
                         ("working", "Edit a_test.py", 1, True))
        self.finish(sid, 0)
        await self.a.refresh()
        self.assertEqual(self.a.state()["sessions"][0]["state"], "done")

    async def test_stop_signals_her_run_and_does_not_announce(self):
        sid = await self.started()
        out = await self.a._stop(sid[:8])
        self.assertIn("Stopped", out)
        self.assertEqual(self.la.killed, [(self.a.runs[-1]["pid"], signal.SIGTERM)])
        self.assertEqual(self.a.state()["sessions"][0]["state"], "failed")
        self.assertEqual(self.events, [])
        self.assertIn("already finished", await self.a._stop(sid))

    async def test_stop_refuses_his_own_sessions(self):
        t = time.time() - 60
        self.h.session("his-session-1", [user("work on things", t), said("ok", t + 1)])
        await self.a.refresh()
        for ref in ("his-session-1", "his-s", "work on"):
            with self.assertRaisesRegex(AdapterError, "only stop runs I started"):
                await self.a._stop(ref)
        with self.assertRaises(AdapterError):
            await self.a._stop("nonexistent")
        self.assertEqual(self.la.killed, [])
        # and through the widget press
        with self.assertRaises(AdapterError):
            await self.a.press("stop", "his-session-1")

    async def test_press_stop_and_open_from_the_widget(self):
        sid = await self.started()
        await self.a.press("open", sid)
        self.assertEqual(self.a.opened, [str(self.h.work)])
        await self.a.press("stop", sid)
        self.assertEqual(len(self.la.killed), 1)

    async def test_open_a_session_folder(self):
        t = time.time() - 60
        self.h.session("his-1", [user("go", t, cwd=str(self.h.work)), said("ok", t + 1)])
        await self.a.refresh()
        await self.a._open_folder("his-1")
        self.assertEqual(self.a.opened, [str(self.h.work)])
        with self.assertRaises(AdapterError):
            await self.a._open_folder("zzzz-unknown")

    async def test_ambiguous_prefix_is_an_error(self):
        t = time.time() - 60
        self.h.session("abcd-1", [user("go", t), said("ok", t + 1)])
        self.h.session("abcd-2", [user("go", t), said("ok", t + 1)])
        await self.a.refresh()
        with self.assertRaisesRegex(AdapterError, "more than one"):
            await self.a._status("abcd")


class EventTests(unittest.IsolatedAsyncioTestCase):
    async def test_session_waiting_fires_on_working_to_waiting_only(self):
        h = Home()
        self.addCleanup(h.tmp.cleanup)
        t = time.time() - 600
        base = [user("go", t, cwd="/home/u/proj"), tool_use("t1", "Bash", {"command": "ls"}, t + 1)]
        f = h.session("w1", base, age=1)
        a = h.adapter()
        got = []
        a.subscribe(lambda ev, fields: got.append((ev, fields)))
        await a.refresh()                                            # baseline: working, nothing emitted
        self.assertEqual(got, [])
        with open(f, "a") as fh:
            fh.write(json.dumps(result("t1", t=t + 2)) + "\n" + json.dumps(said("all done", t + 3)) + "\n")
        await a.refresh()
        self.assertEqual(got, [("claude.session_waiting", {"project": "proj", "title": "go"})])
        await a.refresh()
        self.assertEqual(len(got), 1)                                # not again

    async def test_a_session_already_waiting_at_startup_emits_nothing(self):
        h = Home()
        self.addCleanup(h.tmp.cleanup)
        t = time.time() - 600
        h.session("w2", [user("go", t), said("done", t + 1)])
        a = h.adapter()
        got = []
        a.subscribe(lambda ev, fields: got.append(ev))
        await a.refresh()
        await a.refresh()
        self.assertEqual(got, [])

    async def test_declared_events_and_fields(self):
        self.assertEqual(cl.ClaudeAdapter.events, ("hand_finished", "session_waiting"))
        self.assertEqual(cl.ClaudeAdapter.event_info["session_waiting"]["fields"], {"project": "text", "title": "text"})


class FlowSafetyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.h = Home()
        self.addCleanup(self.h.tmp.cleanup)

    def catalog(self):
        return Catalog.build({"web": FakeApp(_pub, "web"), "claude": self.h.adapter()})

    def safety(self, graph):
        cat = self.catalog()
        return G.safety(G.validate(graph, cat).graph, cat)

    def test_spend_verb_needs_approval_when_she_made_the_flow(self):
        cat = self.catalog()
        self.assertEqual(cat.get("claude.start").consent, "spend")
        graph = g("t", [("n1", "you.run_button", {}),
                        ("n2", "claude.start", {"task": "fix the tests please", "folder": "~/x"})], ["n1.exec>n2.exec"])
        s = self.safety(graph)
        self.assertEqual(s.consent_nodes, ["n2"])
        self.assertTrue(s.needs_approval("aries"))
        self.assertFalse(s.needs_approval("ronald"))

    def test_outside_content_cannot_reach_start_without_an_ask(self):
        nodes = [("n1", "web.track_changed", {}),
                 ("n2", "claude.start", {"task": "fix the tests please", "folder": "~/x"})]
        direct = self.safety(g("t", nodes, ["n1.exec>n2.exec"]))
        self.assertEqual(len(direct.violations), 1)
        self.assertIn("spend his Claude usage", direct.violations[0])
        asked = nodes + [("n3", "you.ask_ronald", {"question": "Have Claude fix the tests?"})]
        ok = self.safety(g("t", asked, ["n1.exec>n3.exec", "n3.yes>n2.exec"]))
        self.assertEqual(ok.violations, [])
        no = self.safety(g("t", asked, ["n1.exec>n3.exec", "n3.no>n2.exec"]))
        self.assertEqual(len(no.violations), 1)

    async def run_flow(self, question, wired=False):
        r = Rig(apps=("steam",))
        self.addCleanup(r.tmp.cleanup)
        la = Launcher()
        r.adapters["claude"] = self.h.adapter(launcher=la.launch, alive=la.is_alive)
        r.make_engine()
        await r.start()
        self.addAsyncCleanup(r.engine.stop)
        nodes = [("n1", "you.run_button", {}), ("n2", "you.ask_ronald", {"question": question}),
                 ("n3", "claude.start", {"task": "fix the tests in full", "folder": str(self.h.work)})]
        links = ["n1.exec>n2.exec", "n2.yes>n3.exec"]
        if wired:
            nodes[1] = ("n2", "you.ask_ronald", {})
            nodes.append(("n4", "data.text", {"template": question}))
            links.append("n4.text>n2.question")
        r.save(g("hand", nodes, links))
        r.engine.run_now(r.engine.rows()[0]["id"])
        await r.engine.idle()
        if r.msgs("ask"):
            await r.engine.on_answer({"id": r.msgs("ask")[-1]["id"], "choice": "yes"})
            await r.engine.idle()
        return la, r.engine.rows()[0]

    async def test_his_yes_to_a_question_asking_for_claude_starts_one_run(self):
        la, row = await self.run_flow("Have Claude fix the tests?")
        self.assertEqual(len(la.calls), 1)
        self.assertEqual(row["last_result"], "ok")

    async def test_a_question_that_does_not_ask_for_claude_does_not_count(self):
        la, row = await self.run_flow("Fix the tests?")
        self.assertEqual(la.calls, [])
        self.assertEqual(row["last_result"], "failed")
        self.assertIn("Not started", row["note"])

    async def test_a_question_wired_from_data_never_counts(self):
        la, row = await self.run_flow("Have Claude fix the tests?", wired=True)
        self.assertEqual(la.calls, [])
        self.assertEqual(row["last_result"], "failed")


class RegistryTests(unittest.TestCase):
    def test_claude_is_registered_and_loads(self):
        from ariadne2 import adapters
        self.assertEqual(adapters.REGISTRY["claude"], "ariadne2.adapters.claude:ClaudeAdapter")
        got = adapters.load_adapters(_pub, only={"claude"})
        self.assertIn("claude", got)
        self.assertEqual(got["claude"].name, "claude")
        (t,) = adapters.tools(got)
        self.assertEqual(t["name"], "claude")
        self.assertEqual(sorted(t["input_schema"]["properties"]["action"]["enum"]), ["open", "start", "status", "stop"])


if __name__ == "__main__":
    unittest.main()
