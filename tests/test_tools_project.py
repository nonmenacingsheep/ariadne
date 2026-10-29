import unittest

from ariadne2.core.tools import GeneralTools, ToolError, common, project
from tests.toolsbase import ToolsCase, run

HIS = "let's build a game"


class Todo(ToolsCase):
    def test_ops(self):
        self.assertIn("(empty)", project.todo("list", None))
        project.todo("add", "player movement")
        project.todo("add", "enemies")
        out = project.todo("add", "score")
        self.assertIn("1. [ ] player movement", out)
        project.todo("start", "enemies")
        out = project.todo("start", "3")
        self.assertIn("2. [ ] enemies", out)           # only one is doing at a time
        self.assertIn("3. [>] score", out)
        self.assertIn("1. [x] player", project.todo("done", "player"))
        self.assertNotIn("enemies", project.todo("remove", "2"))
        self.assertIn("(empty)", project.todo("clear", None))

    def test_bad_input(self):
        project.todo("add", "alpha")
        project.todo("add", "alphabet")
        for op, item in (("explode", None), ("add", ""), ("done", "alp"), ("done", "zzz"), ("done", None), ("start", "9")):
            with self.subTest(op=op, item=item), self.assertRaises(ToolError):
                project.todo(op, item)

    def test_persists_between_calls(self):
        project.todo("add", "keep me")
        self.assertIn("keep me", project.todo("list", None))
        self.assertIn("keep me", (self.data / "project.json").read_text())


class Opening(ToolsCase):
    def test_needs_his_words_and_a_writable_place(self):
        for words in (None, ""):
            with self.assertRaises(ToolError):
                project.open_project(str(self.path("g")), True, words)
        self.assertFalse(self.path("g").exists())
        with self.assertRaises(ToolError):
            project.open_project("/etc/game", True, HIS)
        with self.assertRaises(ToolError):
            project.open_project(str(self.path("missing")), False, HIS)
        self.put("afile", "x")
        with self.assertRaises(ToolError):
            project.open_project(str(self.path("afile")), False, HIS)

    def test_opens_creates_and_shows_context_and_rounds(self):
        tools = GeneralTools()
        self.assertEqual(tools.context(), "")
        self.assertEqual(tools.rounds(), 16)
        out = project.open_project(str(self.path("game")), True, HIS)
        self.assertTrue(self.path("game").is_dir())
        self.assertIn("Project open", out)
        project.todo("add", "movement")
        project.todo("start", "1")
        ctx = tools.context()
        self.assertIn("You are in a project", ctx)
        self.assertIn("1. [>] movement", ctx)
        self.assertIn("edit_file", ctx)
        self.assertEqual(tools.rounds(), project.ROUNDS_IN_PROJECT)
        self.assertEqual(common.current_project(), self.path("game"))
        # opening another project starts a fresh list
        project.open_project(str(self.path("other")), True, HIS)
        self.assertIn("(empty)", project.todo("list", None))

    def test_a_deleted_project_folder_closes_itself(self):
        project.open_project(str(self.path("g")), True, HIS)
        self.path("g").rmdir()
        self.assertIsNone(common.current_project())
        self.assertEqual(GeneralTools().context(), "")

    def test_in_project_is_not_fooled_by_a_name_prefix(self):
        project.open_project(str(self.path("game")), True, HIS)
        self.assertTrue(common.in_project(self.path("game", "a.gd")))
        self.assertFalse(common.in_project(self.path("game-other", "a.gd")))


class Toolset(ToolsCase):
    def test_definitions_are_api_valid_and_short(self):
        import re
        tools = GeneralTools().tools()
        names = [t["name"] for t in tools]
        self.assertEqual(names, ["shell", "read_file", "write_file", "edit_file", "find_files", "search_text",
                                 "web_search", "read_page", "look", "place_window", "window_control", "todo",
                                 "open_project"])
        for t in tools:
            self.assertRegex(t["name"], r"^[a-zA-Z0-9_-]{1,64}$")
            self.assertLess(len(t["description"]), 420, t["name"])
            schema = t["input_schema"]
            self.assertEqual(schema["type"], "object")
            for req in schema["required"]:
                self.assertIn(req, schema["properties"])

    def test_call_routes_runs_off_the_loop_and_unknown_names_fail(self):
        t = GeneralTools()
        out = run(t.call("todo", {"op": "add", "item": "x"}, None))
        self.assertIn("1. [ ] x", out)
        p = self.put("f.txt", "hello\n")
        self.assertIn("1\thello", run(t.call("read_file", {"path": str(p)}, None)))
        with self.assertRaises(Exception) as cm:
            run(t.call("nope", {}, HIS))
        self.assertIn("no tool called", str(cm.exception))
        # a refusal is an AdapterError the loop turns into an error result
        from ariadne2.adapters import AdapterError
        with self.assertRaises(AdapterError):
            run(t.call("shell", {"command": "sudo ls"}, HIS))
        with self.assertRaises(AdapterError):
            run(t.call("write_file", {"path": str(self.path("w")), "text": "x"}, None))


if __name__ == "__main__":
    unittest.main()
