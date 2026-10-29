import base64
import io
import json
import unittest
from unittest import mock

from PIL import Image

from ariadne2.core.tools import ToolError, operate, windows
from tests.toolsbase import ToolsCase

HIS = "open the launcher"


def png(w, h, color=(10, 20, 30)):
    out = io.BytesIO()
    Image.new("RGB", (w, h), color).save(out, "PNG")
    return out.getvalue()


def size_of(block):
    return Image.open(io.BytesIO(base64.b64decode(block["source"]["data"]))).size


class Patched(ToolsCase):
    def patch(self, mod, **kw):
        for k, v in kw.items():
            p = mock.patch.object(mod, k, v)
            p.start()
            self.addCleanup(p.stop)


class Look(Patched):
    def test_whole_desktop_is_an_image_block_with_a_text_block(self):
        self.patch(windows, SHOT_HOOK=lambda interactive: png(300, 100))
        out = windows.look(None)
        self.assertEqual([b["type"] for b in out], ["text", "image"])
        self.assertEqual(out[1]["source"]["media_type"], "image/png")
        self.assertEqual(size_of(out[1]), (300, 100))
        self.assertIn("never an instruction", out[0]["text"])

    def test_big_screens_are_shrunk(self):
        self.patch(windows, SHOT_HOOK=lambda i: png(3440, 1440))
        w, h = size_of(windows.look("screen")[1])
        self.assertLess(w * h, windows.MAX_PIXELS + 10_000)
        self.assertAlmostEqual(w / h, 3440 / 1440, places=1)

    def test_a_monitor_by_name_is_cropped(self):
        self.patch(windows, SHOT_HOOK=lambda i: png(400, 100),
                   KWIN_HOOK=lambda js, r: json.dumps({"DP-1": [0, 0, 200, 100], "DP-2": [200, 0, 200, 100]}))
        self.assertEqual(size_of(windows.look("dp-2")[1]), (200, 100))

    def test_a_window_is_cropped_to_its_client_area(self):
        win = {"caption": "Launcher", "app": "launcher", "x": 10, "y": 20, "w": 50, "h": 40}
        self.patch(windows, SHOT_HOOK=lambda i: png(200, 100), KWIN_HOOK=lambda js, r: json.dumps(win))
        out = windows.look("launcher")
        self.assertEqual(size_of(out[1]), (50, 40))
        self.assertIn("Launcher", out[0]["text"])

    def test_unknown_window_and_forbidden_screen(self):
        self.patch(windows, KWIN_HOOK=lambda js, r: "null")
        with self.assertRaises(ToolError):
            windows.look("nothing-like-it")
        self.patch(windows, KWIN_HOOK=None)
        with self.assertRaises(ToolError) as cm:         # ARIADNE_NO_SCREEN is set by the base
            windows.look(None)
        self.assertIn("forbidden", str(cm.exception))

    def test_area_is_interactive(self):
        seen = []
        self.patch(windows, SHOT_HOOK=lambda i: (seen.append(i), png(10, 10))[1])
        windows.look("area")
        self.assertEqual(seen, [True])


class Place(Patched):
    def run_place(self, window, where, reply):
        sent = []
        self.patch(windows, KWIN_HOOK=lambda js, r: (sent.append(js), json.dumps(reply))[1])
        return windows.place_window(window, where), sent[0]

    def test_where_parsing(self):
        self.assertEqual(windows.parse_where("Right Third"), ("right third", ""))
        self.assertEqual(windows.parse_where("top-left"), ("top left", ""))
        self.assertEqual(windows.parse_where("DP-2"), ("", "dp-2"))
        self.assertEqual(windows.parse_where("other"), ("", "other"))
        self.assertEqual(windows.parse_where("left on DP-2"), ("left", "dp-2"))
        for bad in ("", "sideways on DP-2"):
            with self.assertRaises(ToolError):
                windows.parse_where(bad)

    def test_places_with_fractions_of_the_work_area(self):
        out, js = self.run_place("Steam", "left third", {"ok": True, "caption": "Steam", "screen": "DP-1"})
        self.assertIn("Put 'Steam' left third on DP-1", out)
        self.assertIn("[0.0, 0.0, 0.34, 1.0]", js)
        self.assertIn('"steam"', js)               # the window needle, lowercased and escaped as JSON

    def test_hostile_window_name_cannot_break_out_of_the_script(self):
        _, js = self.run_place('x"; callDBus("evil"); "', "left", {"ok": True, "caption": "c", "screen": "s"})
        self.assertIn(json.dumps('x"; calldbus("evil"); "'), js)

    def test_no_window_and_bad_monitor(self):
        self.patch(windows, KWIN_HOOK=lambda js, r: json.dumps({"ok": False, "why": "no window"}))
        with self.assertRaises(ToolError) as cm:
            windows.place_window("zzz", "left")
        self.assertIn("no window matching", str(cm.exception))
        self.patch(windows, KWIN_HOOK=lambda js, r: json.dumps({"ok": False, "screens": ["DP-1", "DP-2"]}))
        with self.assertRaises(ToolError) as cm:
            windows.place_window("steam", "HDMI-9")
        self.assertIn("DP-1, DP-2", str(cm.exception))


WIN = {"caption": "FunGen", "app": "fungen", "x": 100, "y": 50, "w": 400, "h": 300}


class Operate(Patched):
    def setUp(self):
        super().setUp()
        self.inputs, self.pos = [], [0, 0]

        def fake_input(argv):
            self.inputs.append(argv)
            if argv[1] == "mousemove" and "--wheel" not in argv:
                self.pos[0] += int(argv[argv.index("-x") + 1])
                self.pos[1] += int(argv[argv.index("-y") + 1])
        self.patch(operate, INPUT_HOOK=fake_input, CURSOR_HOOK=lambda: tuple(self.pos),
                   WINDOW_HOOK=lambda name: dict(WIN) if "fun" in name.lower() else (_ for _ in ()).throw(ToolError("no window")),
                   GRAB_HOOK=lambda rect: png(rect["w"], rect["h"]), A11Y_HOOK=lambda name: None)

    def plan(self, *actions):
        it = iter(actions)
        self.told = []
        self.patch(operate, DECIDE_HOOK=lambda p, task, hist: (self.told.append(list(hist)), next(it))[1])

    def clicks(self):
        return [a for a in self.inputs if a[1] == "click"]

    def test_clicks_land_where_the_image_pointed_and_picture_comes_back(self):
        self.plan({"action": "click", "x": 40, "y": 30, "why": "the button"}, {"action": "done", "report": "loaded"})
        out = operate.window_control("fungen", "load the clip", None, HIS)
        self.assertEqual(self.pos, [140, 80])                    # window origin + image point
        self.assertEqual(len(self.clicks()), 1)
        self.assertEqual([b["type"] for b in out], ["text", "image"])
        self.assertIn("loaded", out[0]["text"])
        self.assertIn("Quoted from the window", out[0]["text"])
        self.assertEqual(len(self.told[1]), 1)                   # the second look saw what was done

    def test_a_click_outside_the_window_is_refused(self):
        self.plan({"action": "click", "x": 9999, "y": 5}, {"action": "click", "x": -4, "y": 5}, {"action": "done"})
        out = operate.window_control("fungen", "click something", None, HIS)
        self.assertEqual(self.clicks(), [])
        self.assertEqual(out[0]["text"].count("outside the window"), 2)

    def test_drag_scroll_type_key_wait(self):
        self.plan({"action": "drag", "x": 10, "y": 10, "to_x": 50, "to_y": 10},
                  {"action": "scroll", "x": 20, "y": 20, "amount": 3},
                  {"action": "type", "text": "hello"}, {"action": "key", "keys": "ctrl+s"},
                  {"action": "key", "keys": "ctrl+nonsense"}, {"action": "wait", "seconds": 1},
                  {"action": "explode"}, {"action": "done"})
        out = operate.window_control("fungen", "do many things", 20, HIS)[0]["text"]
        self.assertIn(["ydotool", "type", "--key-delay", "8", "--", "hello"], self.inputs)
        self.assertIn(["ydotool", "key", "29:1", "31:1", "31:0", "29:0"], self.inputs)
        self.assertIn("no key called 'nonsense'", out)
        self.assertIn("no action called 'explode'", out)
        self.assertEqual([a[2] for a in self.clicks()], ["0x40", "0x80"])   # down at the start, up at the end

    def test_the_step_budget_ends_it(self):
        self.patch(operate, DECIDE_HOOK=lambda p, t, h: {"action": "wait", "seconds": 1})
        out = operate.window_control("fungen", "wait forever", 4, HIS)[0]["text"]
        self.assertIn("ran out of steps (4)", out)
        out = operate.window_control("fungen", "wait forever", 999, HIS)[0]["text"]
        self.assertIn(f"ran out of steps ({operate.MAX_STEPS})", out)

    def test_he_moves_the_mouse_and_she_lets_go(self):
        acts = iter([{"action": "click", "x": 10, "y": 10}, {"action": "click", "x": 20, "y": 20}])

        def decide(p, t, h):
            if h:
                self.pos[0] += 200            # his hand, while the model was deciding
            return next(acts)
        self.patch(operate, DECIDE_HOOK=decide)
        out = operate.window_control("fungen", "click twice", None, HIS)[0]["text"]
        self.assertIn("he moved the mouse, so I let go", out)
        self.assertEqual(len(self.clicks()), 1)

    def test_needs_his_words_a_job_and_a_window(self):
        self.plan({"action": "done"})
        for words in (None, ""):
            with self.assertRaises(ToolError):
                operate.window_control("fungen", "load it", None, words)
        with self.assertRaises(ToolError):
            operate.window_control("fungen", "x", None, HIS)
        with self.assertRaises(ToolError):
            operate.window_control("nowhere", "load the clip", None, HIS)
        self.assertEqual(self.inputs, [])

    def test_the_deciding_prompt_keeps_1x_safety_rules(self):
        for needle in ("deleting", "spending money", "sending something", "typing a password", "never instructions"):
            self.assertIn(needle, operate.SYSTEM)

    def test_by_name_when_the_app_publishes_controls(self):
        ctrls = [{"id": i, "role": "push button", "name": n, "value": "", "actions": ["press"], "editable": False,
                  "checked": False, "enabled": True} for i, n in ((1, "7"), (2, "x"), (3, "="))]
        ctrls.append({"id": 4, "role": "text", "name": "display", "value": "16", "actions": [], "editable": True,
                      "checked": False, "enabled": True})
        pressed, told = [], []
        plan = iter([{"action": "press", "id": 1}, {"action": "press", "id": 99}, {"action": "done", "report": "it is 16"}])
        self.patch(operate, A11Y_HOOK=lambda name: [dict(c) for c in ctrls],
                   PRESS_HOOK=lambda cid, kind, text: pressed.append((cid, kind)),
                   DECIDE_TEXT_HOOK=lambda c, task, hist: (told.append(c), next(plan))[1])
        out = operate.window_control("fungen", "4 times 4", None, HIS)
        self.assertEqual(pressed, [(1, "press")])
        self.assertIn("it is 16", out)
        self.assertIn("no control #99", out)
        self.assertIn("display: 16", out)
        self.assertIn("#1 push button '7'", told[0])
        self.assertEqual(self.clicks(), [])                       # nothing was clicked

    def test_real_input_is_forbidden_under_the_flag(self):
        self.patch(operate, INPUT_HOOK=None)
        with self.assertRaises(ToolError):
            operate._ydotool("click", "0xC0")


if __name__ == "__main__":
    unittest.main()
