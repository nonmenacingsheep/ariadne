import json
import os
import unittest

from ariadne2 import protocol as p


class RoundTrip(unittest.TestCase):
    def rt(self, msg):
        line = p.encode(msg)
        self.assertTrue(line.endswith(b"\n"))
        self.assertNotIn(b'": ', line)  # compact separators
        self.assertNotIn(b'", ', line)
        self.assertEqual(p.decode(line), msg)
        self.assertEqual(p.decode(line.decode()), msg)
        return msg

    def test_hello(self):
        self.assertEqual(self.rt(p.hello_core())["side"], "core")
        d = self.rt(p.hello_desk())
        self.assertEqual((d["side"], d["v"], d["pid"]), ("desk", 1, os.getpid()))

    def test_state(self):
        self.rt(p.state("system", {"cpu": 1.5}))

    def test_action(self):
        m = self.rt(p.action("a1", "spotify", "next", "started"))
        self.assertNotIn("control", m)
        self.assertNotIn("note", m)
        m = self.rt(p.action("a1", "spotify", "next", "failed", control="skip", note="x"))
        self.assertEqual((m["control"], m["note"]), ("skip", "x"))

    def test_line_chat(self):
        self.assertFalse(self.rt(p.core_line("hi"))["speaking"])
        self.assertTrue(self.rt(p.core_line("hi", True))["speaking"])
        self.assertFalse(self.rt(p.chat("c", "aries", "yo"))["done"])
        self.assertTrue(self.rt(p.chat("c", "you", "yo", True))["done"])

    def test_desk_side(self):
        self.rt(p.press("steam", "launch"))
        self.rt(p.text("chat", "héllo ✓"))

    def test_constructors_validate(self):
        with self.assertRaises(p.ProtocolError):
            p.state("nope", {})
        with self.assertRaises(p.ProtocolError):
            p.action("a", "spotify", "v", "weird")
        with self.assertRaises(p.ProtocolError):
            p.chat("c", "robot", "x")
        with self.assertRaises(p.ProtocolError):
            p.press("nope", "x")


class Rejects(unittest.TestCase):
    def bad(self, raw):
        with self.assertRaises(p.ProtocolError):
            p.decode(raw)

    def test_bad_json(self):
        self.bad("{nope")
        self.bad(b"\xff\xfe")

    def test_not_object(self):
        self.bad("[1,2]")
        self.bad("3")

    def test_t(self):
        self.bad("{}")
        self.bad('{"t":"bogus"}')

    def test_widget_phase_role(self):
        self.bad('{"t":"press","widget":"nope","control":"x"}')
        self.bad('{"t":"action","id":"1","widget":"spotify","verb":"v","phase":"meh"}')
        self.bad('{"t":"chat","id":"1","role":"robot","delta":"x"}')

    def test_missing_fields(self):
        self.bad('{"t":"hello","v":1}')
        self.bad('{"t":"state","widget":"chat"}')
        self.bad('{"t":"state","widget":"chat","data":[]}')
        self.bad('{"t":"action","id":"1","widget":"spotify","verb":"v"}')
        self.bad('{"t":"line"}')
        self.bad('{"t":"chat","id":"1","role":"you"}')
        self.bad('{"t":"press","widget":"spotify"}')
        self.bad('{"t":"text","widget":"chat"}')


class SocketPath(unittest.TestCase):
    def test_paths(self):
        old = {k: os.environ.pop(k, None) for k in ("ARIADNE2_SOCKET", "XDG_RUNTIME_DIR")}
        try:
            os.environ["XDG_RUNTIME_DIR"] = "/run/user/9"
            self.assertEqual(str(p.socket_path()), "/run/user/9/ariadne2/core.sock")
            del os.environ["XDG_RUNTIME_DIR"]
            self.assertEqual(str(p.socket_path()), f"/tmp/ariadne2-{os.getuid()}/core.sock")
            os.environ["ARIADNE2_SOCKET"] = "/x/y.sock"
            self.assertEqual(str(p.socket_path()), "/x/y.sock")
        finally:
            for k, v in old.items():
                os.environ.pop(k, None)
                if v is not None:
                    os.environ[k] = v


if __name__ == "__main__":
    unittest.main()
