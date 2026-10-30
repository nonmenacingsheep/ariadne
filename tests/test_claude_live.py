"""The Claude widget's live session, against a fake `claude` that speaks stream-json."""
import asyncio
import json
import os
import stat
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from ariadne2 import protocol
from ariadne2.core import claude_live

FAKE = textwrap.dedent('''\
    #!/usr/bin/env python3
    import json, sys, os
    def out(o): print(json.dumps(o), flush=True)
    open(os.environ["FAKE_ARGV"], "w").write(json.dumps(sys.argv[1:]) + "\\n" + os.getcwd()
        + "\\n" + ("KEY" if "ANTHROPIC_API_KEY" in os.environ else "NOKEY"))
    for line in sys.stdin:
        m = json.loads(line)
        if m["type"] == "control_request" and m["request"]["subtype"] == "initialize":
            out({{"type": "control_response", "response": {{"subtype": "success", "request_id": m["request_id"]}}}})
            out({{"type": "system", "subtype": "init", "session_id": "s-123", "cwd": os.getcwd()}})
        elif m["type"] == "user":
            text = m["message"]["content"]
            if text == "login":
                out({{"type": "result", "subtype": "success", "is_error": True, "total_cost_usd": 0,
                      "result": "Failed to authenticate: OAuth session expired"}})
                continue
            out({{"type": "stream_event", "event": {{"type": "content_block_delta", "delta": {{"type": "text_delta", "text": "Look"}}}}}})
            out({{"type": "assistant", "message": {{"content": [{{"type": "text", "text": "Looking."}}]}}}})
            out({{"type": "assistant", "message": {{"content": [{{"type": "tool_use", "id": "tu1", "name": "Bash",
                  "input": {{"command": "ls -la"}}}}]}}}})
            out({{"type": "control_request", "request_id": "ask1", "request": {{"subtype": "can_use_tool",
                  "tool_name": "Bash", "input": {{"command": "ls -la"}},
                  "permission_suggestions": [{{"type": "addRules"}}]}}}})
            answer = json.loads(sys.stdin.readline())
            out({{"type": "user", "message": {{"content": [{{"type": "tool_result", "tool_use_id": "tu1",
                  "content": "a.txt", "is_error": answer["response"]["response"]["behavior"] != "allow"}}]}}}})
            open(os.environ["FAKE_ARGV"] + ".answer", "w").write(json.dumps(answer))
            out({{"type": "result", "subtype": "success", "is_error": False, "total_cost_usd": 0.0123, "result": "done"}})
''')


class LiveClaudeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.exe = self.tmp / "claude"
        self.exe.write_text(FAKE.format())
        self.exe.chmod(self.exe.stat().st_mode | stat.S_IEXEC)
        self.argv_file = self.tmp / "argv"
        os.environ["FAKE_ARGV"] = str(self.argv_file)
        os.environ["ANTHROPIC_API_KEY"] = "her-key"
        self.addCleanup(os.environ.pop, "ANTHROPIC_API_KEY", None)
        (self.tmp / "Claude Projects" / "proj").mkdir(parents=True)
        self.got = []

        async def publish(m):
            protocol.decode(protocol.encode(m))         # every event is a valid message
            self.got.append(m)
        self.live = claude_live.LiveClaude(publish, home=self.tmp, projects=self.tmp / "projects", exe=str(self.exe))
        self.addAsyncCleanup(self.live.end)

    def evs(self, ev):
        return [m for m in self.got if m["ev"] == ev]

    async def until(self, pred, timeout=10):
        for _ in range(int(timeout / 0.02)):
            if pred():
                return True
            await asyncio.sleep(0.02)
        return False

    async def test_a_turn_streams_asks_and_answers(self):
        await self.live.on_desk({"op": "new", "cwd": str(self.tmp / "Claude Projects" / "proj")})
        await self.live.on_desk({"op": "send", "text": "list the files"})
        self.assertTrue(await self.until(lambda: self.evs("ask")))
        ask = self.evs("ask")[0]
        self.assertEqual((ask["tool"], ask["label"], ask["always"]), ("Bash", "Bash: ls -la", True))
        self.assertEqual(self.live.state, "asking")
        await self.live.on_desk({"op": "answer", "req": ask["req"], "allow": True, "always": True})
        self.assertTrue(await self.until(lambda: self.evs("done")))
        answer = json.loads(Path(str(self.argv_file) + ".answer").read_text())["response"]
        self.assertEqual(answer["request_id"], "ask1")
        self.assertEqual(answer["response"]["behavior"], "allow")
        self.assertEqual(answer["response"]["updatedPermissions"], [{"type": "addRules"}])
        self.assertEqual([m["text"] for m in self.evs("delta")], ["Look"])
        self.assertEqual([m["text"] for m in self.evs("text")], ["Looking."])
        self.assertEqual(self.evs("tool")[0]["label"], "Bash: ls -la")
        self.assertFalse(self.evs("tool_done")[0]["error"])
        self.assertEqual(self.evs("done")[0]["cost"], 0.0123)
        self.assertEqual((self.live.state, self.live.session), ("idle", "s-123"))
        argv, cwd, key = self.argv_file.read_text().splitlines()
        argv = json.loads(argv)
        self.assertIn("--permission-prompt-tool", argv)
        self.assertEqual(argv[argv.index("--permission-mode") + 1], "default")
        self.assertNotIn("bypassPermissions", argv)
        self.assertTrue(cwd.endswith("proj"))
        self.assertEqual(key, "NOKEY")                   # his login, never her API key

    async def test_deny_goes_back_as_a_deny(self):
        await self.live.on_desk({"op": "send", "text": "list"})
        self.assertTrue(await self.until(lambda: self.evs("ask")))
        await self.live.on_desk({"op": "answer", "req": "ask1", "allow": False})
        self.assertTrue(await self.until(lambda: self.evs("done")))
        answer = json.loads(Path(str(self.argv_file) + ".answer").read_text())["response"]["response"]
        self.assertEqual(answer["behavior"], "deny")
        self.assertTrue(self.evs("tool_done")[0]["error"])

    async def test_signed_out_is_its_own_state(self):
        await self.live.on_desk({"op": "send", "text": "login"})
        self.assertTrue(await self.until(lambda: self.live.state == "signed_out"))
        self.assertIn("authenticate", self.evs("done")[0]["error"])

    async def test_bypass_mode_is_refused(self):
        await self.live.on_desk({"op": "mode", "mode": "bypassPermissions"})
        self.assertEqual(self.live.mode, "default")

    async def test_resume_shows_the_transcript_tail_and_resumes_by_id(self):
        d = self.tmp / "projects" / "-x"
        d.mkdir(parents=True)
        lines = [{"type": "user", "cwd": str(self.tmp / "Claude Projects" / "proj"), "message": {"content": "fix the bug"}},
                 {"type": "assistant", "message": {"content": [{"type": "text", "text": "On it."},
                     {"type": "tool_use", "id": "t1", "name": "Edit", "input": {"file_path": "/a/b.py"}}]}},
                 {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]}}]
        (d / "abc.jsonl").write_text("\n".join(json.dumps(x) for x in lines) + "\n")
        await self.live.on_desk({"op": "resume", "session": "abc"})
        items = self.evs("history")[0]["items"]
        self.assertEqual([i["kind"] for i in items], ["user", "text", "tool", "tool_done"])
        self.assertEqual(items[2]["label"], "Edit b.py")
        self.assertTrue(self.live.cwd.endswith("proj"))
        await self.live.on_desk({"op": "send", "text": "login"})
        self.assertTrue(await self.until(lambda: self.argv_file.exists()))
        argv = json.loads(self.argv_file.read_text().splitlines()[0])
        self.assertEqual(argv[argv.index("--resume") + 1], "abc")

    async def test_resume_rejects_paths(self):
        await self.live.on_desk({"op": "resume", "session": "../../etc/passwd"})
        self.assertTrue(self.evs("error"))


if __name__ == "__main__":
    unittest.main()
