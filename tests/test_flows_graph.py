import json
import unittest

from ariadne2 import protocol
from ariadne2.core.flows import graph as G
from ariadne2.core.flows import values as V
from ariadne2.core.flows.catalog import Catalog, compact
from tests.flowfakes import FakeApp, g


async def _pub(m):
    pass


def catalog():
    return Catalog.build({"steam": FakeApp(_pub, "steam"), "browser": FakeApp(_pub, "browser"),
                          "spotify": FakeApp(_pub, "spotify")})


class CatalogTests(unittest.TestCase):
    def test_about_forty_builtins_across_the_five_categories(self):
        cat = Catalog.build()
        builtin = [t for t in cat.types.values() if t.kind not in ("event", "verb", "read_state")]
        self.assertGreaterEqual(len(builtin), 40)
        self.assertEqual({t.category for t in builtin}, {"start", "check", "action", "flow", "data"})
        for t in builtin:
            d = t.to_dict()
            for key in ("type", "title", "category", "description", "inputs", "outputs", "exec_in", "exec_out",
                        "consent", "outside_content", "costly"):
                self.assertIn(key, d)
            json.dumps(d)
            for i in d["inputs"]:
                self.assertEqual({"name", "type", "required", "default"} - set(i), set())
            if t.category == "start":
                self.assertFalse(t.exec_in)
                self.assertEqual(t.exec_out, ["exec"])
            if t.exec_in:
                self.assertIn(t.category, ("check", "action", "flow", "data"))

    def test_specific_pins_from_the_design(self):
        cat = Catalog.build()
        self.assertEqual(cat.get("check.branch").exec_out, ["true", "false"])
        self.assertEqual(cat.get("flow.wait_for").exec_out, ["exec", "timeout"])
        self.assertEqual(cat.get("her.say").exec_out, ["done", "failed"])
        self.assertEqual(cat.get("you.ask_ronald").exec_out_names({"options": ["a", "b"]}), ["a", "b", "timeout"])
        self.assertEqual(cat.get("her.decide").exec_out_names({}), ["yes", "no", "failed"])
        self.assertTrue(cat.get("her.ask_aries").costly)
        for t in ("desktop.window_opened", "desktop.idle", "desktop.back_from_idle", "desktop.window_focused"):
            self.assertFalse(cat.get(t).available)

    def test_generated_from_adapters(self):
        cat = catalog()
        ev = cat.get("steam.game_started")
        self.assertEqual((ev.category, ev.kind, ev.outside_content), ("start", "event", False))
        self.assertEqual([o["name"] for o in ev.outputs], ["name", "appid"])
        self.assertEqual(ev.phrase, "When Steam starts a game")
        vol = cat.get("steam.volume")
        self.assertEqual((vol.category, vol.exec_out, vol.consent), ("action", ["done", "failed"], None))
        self.assertEqual(vol.inputs[0], {"name": "level", "type": "number", "required": True, "default": None})
        send = cat.get("steam.send")
        self.assertEqual(send.consent, "message")
        self.assertEqual([i["name"] for i in send.inputs], ["person", "text"])
        self.assertTrue(cat.get("steam.read").outside_content)
        self.assertTrue(cat.get("web.track_changed") is None)
        rs = cat.get("steam.read_state")
        self.assertEqual(rs.inputs[0]["choices"], ["status", "volume"])
        self.assertIn("steam.volume", cat.reads)

    def test_outside_content_comes_from_the_adapter_declaration(self):
        cat = Catalog.build({"web": FakeApp(_pub, "web")})
        self.assertTrue(cat.get("web.track_changed").outside_content)
        self.assertFalse(cat.get("web.game_started").outside_content)

    def test_real_adapters_load_into_the_catalog(self):
        from ariadne2 import adapters
        cat = Catalog.build(adapters.load_adapters(_pub))
        self.assertTrue(cat.get("spotify.track_changed"))
        self.assertTrue(cat.get("steam.download_done"))
        self.assertTrue(cat.get("browser.video_ended").outside_content)
        self.assertTrue(cat.get("browser.tab_opened").outside_content)
        self.assertTrue(cat.get("browser.read").outside_content)
        self.assertEqual(cat.get("spotify.volume").inputs[0]["type"], "number")
        self.assertIn("spotify.status", cat.reads)

    def test_search_and_compact(self):
        cat = catalog()
        self.assertEqual(cat.search("steam game")[0].type[:6], "steam.")
        self.assertIn("steam.volume", [t.type for t in cat.search("steam vol")])
        self.assertEqual(cat.search("branch")[0].type, "check.branch")
        self.assertEqual(cat.search("zzzz"), [])
        c = compact(cat.get("steam.volume"))
        self.assertEqual(c["in"], ["level:number*"])
        self.assertLess(len(json.dumps(c)), 300)


class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.cat = catalog()

    def errs(self, graph):
        return G.validate(graph, self.cat).errors

    def good(self):
        return g("t", [("n1", "steam.game_started", {}), ("n2", "her.tell", {"text": "hi"})], ["n1.exec>n2.exec"])

    def test_a_good_graph_has_no_errors(self):
        rep = G.validate(self.good(), self.cat)
        self.assertEqual((rep.errors, rep.warnings), ([], []))
        self.assertEqual(rep.graph["mode"], "ignore")

    def test_unknown_type_with_suggestion(self):
        graph = self.good()
        graph["nodes"][0]["type"] = "steam.game_start"
        e = self.errs(graph)
        self.assertTrue(any("unknown node type" in x and "steam.game_started" in x for x in e), e)

    def test_missing_required_input_named(self):
        graph = self.good()
        graph["nodes"][1]["values"] = {}
        self.assertIn("n2 (Tell): text needs a value", self.errs(graph))

    def test_value_checks(self):
        graph = g("t", [("n1", "time.at", {"time": "25:99"}), ("n2", "steam.volume", {"level": "loud"}),
                        ("n3", "her.tell", {"text": "x", "colour": "red"}), ("n4", "check.compare", {"a": 1, "b": 2, "op": "~"})],
                  ["n1.exec>n2.exec", "n2.done>n3.exec"])
        e = " | ".join(self.errs(graph))
        for needle in ("time should be a time", "level should be a number", "no input 'colour'", "op must be one of"):
            self.assertIn(needle, e)

    def test_no_start_node(self):
        e = self.errs(g("t", [("n2", "her.tell", {"text": "x"})], []))
        self.assertTrue(any("no start node" in x for x in e))

    def test_dangling_links_and_bad_pins(self):
        graph = self.good()
        graph["links"] += [{"from": ["n1", "exec"], "to": ["n9", "exec"]},
                           {"from": ["n1", "nope"], "to": ["n2", "text"]},
                           {"from": ["n2", "done"], "to": ["n1", "exec"]},
                           {"from": ["n1", "name"], "to": ["n2", "exec"]}, {"from": None, "to": None}]
        e = " | ".join(self.errs(graph))
        for needle in ("no node n9", "has no output pin 'nope'", "can only run into the exec input",
                       "is data; it can't go into an exec input", "malformed"):
            self.assertIn(needle, e)

    def test_type_mismatch(self):
        graph = g("t", [("n1", "steam.game_started", {}), ("n2", "steam.volume", {})],
                  ["n1.exec>n2.exec", "n1.name>n2.level"])
        self.assertTrue(any("gives text but" in x and "wants number" in x for x in self.errs(graph)))
        ok = g("t", [("n1", "steam.game_started", {}), ("n2", "her.tell", {})],
               ["n1.exec>n2.exec", "n1.appid>n2.text"])        # any type goes into a text input
        self.assertEqual(self.errs(ok), [])

    def test_two_wires_into_one_input(self):
        graph = g("t", [("n1", "steam.game_started", {}), ("n2", "her.tell", {})],
                  ["n1.exec>n2.exec", "n1.name>n2.text", "n1.appid>n2.text"])
        self.assertTrue(any("two data wires" in x for x in self.errs(graph)))

    def test_exec_loops_and_data_loops_are_errors(self):
        graph = g("t", [("n1", "steam.game_started", {}), ("n2", "her.tell", {"text": "a"}),
                        ("n3", "her.tell", {"text": "b"})], ["n1.exec>n2.exec", "n2.done>n3.exec", "n3.done>n2.exec"])
        self.assertTrue(any("exec wires loop" in x for x in self.errs(graph)))
        data = g("t", [("n1", "steam.game_started", {}), ("n2", "data.math", {}), ("n3", "data.math", {})],
                 ["n2.result>n3.a", "n3.result>n2.a"])
        self.assertTrue(any("data wires loop" in x for x in self.errs(data)))

    def test_unreachable_is_a_warning(self):
        graph = self.good()
        graph["nodes"].append({"id": "n3", "type": "her.tell", "values": {"text": "x"}})
        rep = G.validate(graph, self.cat)
        self.assertEqual(rep.errors, [])
        self.assertTrue(any("never reached" in w for w in rep.warnings))

    def test_unavailable_nodes_are_errors_when_enabled_warnings_when_off(self):
        graph = g("t", [("n1", "desktop.window_opened", {"match": "steam"}), ("n2", "her.tell", {"text": "x"})],
                  ["n1.exec>n2.exec"])
        self.assertTrue(any("isn't available yet" in x for x in self.errs(graph)))
        graph["enabled"] = False
        rep = G.validate(graph, self.cat)
        self.assertEqual(rep.errors, [])
        self.assertTrue(rep.warnings)

    def test_becomes_and_read_state_fields_checked(self):
        bad = g("t", [("n1", "time.becomes", {"field": "steam.nope", "value": "x"}),
                      ("n2", "steam.read_state", {"field": "wat"}), ("n3", "her.tell", {"text": "x"})],
                ["n1.exec>n3.exec"])
        e = " | ".join(self.errs(bad))
        self.assertIn("no state field 'steam.nope'", e)
        self.assertIn("field must be one of status, volume", e)

    def test_names_and_modes(self):
        graph = self.good()
        graph.update(name="", mode="sideways")
        e = " | ".join(self.errs(graph))
        self.assertIn("needs a name", e)
        self.assertIn("mode must be one of", e)

    def test_link_shorthand_and_junk_never_raise(self):
        graph = {"name": "x", "nodes": [{"id": "n1", "type": "steam.game_started"}, {"id": "n2", "type": "her.tell",
                 "values": {"text": "x"}}], "links": [{"from": "n1.exec", "to": "n2.exec"}]}
        self.assertEqual(G.validate(graph, self.cat).errors, [])
        for junk in (None, [], "x", {"nodes": "x", "links": 4}, {"nodes": [1, None], "links": [3]}):
            self.assertTrue(G.validate(junk, self.cat).errors)

    def test_run_flow_cannot_call_itself(self):
        graph = g("loopy", [("n1", "you.run_button", {}), ("n2", "flow.run_flow", {"flow": "loopy"})], ["n1.exec>n2.exec"])
        self.assertTrue(any("can't call itself" in x for x in self.errs(graph)))


class SummaryTests(unittest.TestCase):
    def setUp(self):
        self.cat = catalog()

    def summary(self, graph):
        return G.summary(G.validate(graph, self.cat).graph, self.cat)

    def test_the_design_example(self):
        graph = g("late gaming", [("n1", "steam.game_started", {}),
                                  ("n2", "check.time_between", {"from": "22:00", "to": "07:00"}),
                                  ("n3", "spotify.volume", {"level": 20})],
                  ["n1.exec>n2.exec", "n2.true>n3.exec"])
        self.assertEqual(self.summary(graph), "When Steam starts a game → if 22:00–07:00 → Spotify volume 20")

    def test_wired_values_show_as_pin_names(self):
        graph = g("t", [("n1", "steam.game_started", {}), ("n2", "her.tell", {})],
                  ["n1.exec>n2.exec", "n1.name>n2.text"])
        self.assertEqual(self.summary(graph), "When Steam starts a game → Tell me ‹name›")

    def test_branches_failures_and_choices(self):
        graph = g("t", [("n1", "time.at", {"time": "08:00", "days": ["mon", "tue"]}),
                        ("n2", "steam.boom", {}), ("n3", "her.tell", {"text": "ok"}), ("n4", "her.tell", {"text": "bad"}),
                        ("n5", "you.ask_ronald", {"question": "ready?"}), ("n6", "her.say", {"text": "go"})],
                  ["n1.exec>n5.exec", "n5.yes>n2.exec", "n2.done>n3.exec", "n2.failed>n4.exec", "n5.no>n6.exec"])
        self.assertEqual(self.summary(graph),
                         "At 08:00 on mon, tue → Ask Ronald ready? (yes: Steam boom → Tell me ok "
                         "(if it fails: Tell me bad)) (no: Say go)")

    def test_becomes_every_after_and_multiple_starts(self):
        graph = g("t", [("n1", "time.becomes", {"field": "spotify.status", "value": "playing", "hold": "10s"}),
                        ("n2", "time.every", {"interval": 1800}), ("n3", "her.tell", {"text": "x"})],
                  ["n1.exec>n3.exec", "n2.exec>n3.exec"])
        self.assertEqual(self.summary(graph), "When spotify.status becomes playing for 10s → Tell me x; "
                                              "Every 30m → Tell me x")

    def test_deterministic_and_capped(self):
        nodes = [("n0", "steam.game_started", {})] + [(f"m{i}", "her.tell", {"text": "x" * 30}) for i in range(1, 12)]
        links = ["n0.exec>m1.exec"] + [f"m{i}.done>m{i + 1}.exec" for i in range(1, 11)]
        graph = g("long", nodes, links)
        s1 = self.summary(graph)
        self.assertEqual(s1, self.summary(graph))
        self.assertLessEqual(len(s1), 240)
        self.assertTrue(s1.endswith("…"))


class SafetyTests(unittest.TestCase):
    def setUp(self):
        self.cat = catalog()

    def safety(self, graph):
        return G.safety(G.validate(graph, self.cat).graph, self.cat)

    def test_consent_verb_or_outside_start_needs_approval_when_she_made_it(self):
        consent = g("t", [("n1", "steam.game_started", {}), ("n2", "steam.send", {"person": "Kai", "text": "x"})],
                    ["n1.exec>n2.exec"])
        s = self.safety(consent)
        self.assertEqual(s.consent_nodes, ["n2"])
        self.assertTrue(s.needs_approval("aries"))
        self.assertFalse(s.needs_approval("ronald"))
        plain = g("t", [("n1", "steam.game_started", {}), ("n2", "her.tell", {"text": "x"})], ["n1.exec>n2.exec"])
        self.assertFalse(self.safety(plain).needs_approval("aries"))
        outside = g("t", [("n1", "web.track_changed", {}), ("n2", "her.tell", {"text": "x"})], ["n1.exec>n2.exec"])
        cat = Catalog.build({"web": FakeApp(_pub, "web")})
        s = G.safety(G.validate(outside, cat).graph, cat)
        self.assertEqual(s.outside_nodes, ["n1"])
        self.assertTrue(s.needs_approval("aries"))

    def test_outside_start_cannot_reach_a_consent_verb_without_ask_ronald(self):
        cat = Catalog.build({"web": FakeApp(_pub, "web"), "steam": FakeApp(_pub, "steam")})
        base = [("n1", "web.track_changed", {}), ("n2", "steam.send", {"person": "Kai", "text": "x"})]
        direct = G.safety(G.validate(g("t", base, ["n1.exec>n2.exec"]), cat).graph, cat)
        self.assertEqual(len(direct.violations), 1)
        self.assertIn("could send a message from outside content", direct.violations[0])
        asked = base + [("n3", "you.ask_ronald", {"question": "Send Kai?"})]
        ok = G.safety(G.validate(g("t", asked, ["n1.exec>n3.exec", "n3.yes>n2.exec"]), cat).graph, cat)
        self.assertEqual(ok.violations, [])
        via_no = G.safety(G.validate(g("t", asked, ["n1.exec>n3.exec", "n3.no>n2.exec"]), cat).graph, cat)
        self.assertEqual(len(via_no.violations), 1)             # only a yes-type answer counts

    def test_reading_page_text_taints_the_rest_of_the_path(self):
        graph = g("t", [("n1", "steam.game_started", {}), ("n2", "steam.read", {}),
                        ("n3", "steam.send", {"person": "Kai", "text": "x"})], ["n1.exec>n2.exec", "n2.done>n3.exec"])
        s = self.safety(graph)
        self.assertEqual(len(s.violations), 1)
        self.assertEqual(s.outside_nodes, ["n2"])

    def test_outside_start_cannot_call_other_flows_unasked(self):
        cat = Catalog.build({"web": FakeApp(_pub, "web")})
        graph = g("t", [("n1", "web.track_changed", {}), ("n2", "flow.run_flow", {"flow": "other"})], ["n1.exec>n2.exec"])
        self.assertEqual(len(G.safety(G.validate(graph, cat).graph, cat).violations), 1)


class LayoutAndValuesTests(unittest.TestCase):
    def test_layout_gives_columns(self):
        cat = catalog()
        graph = G.validate(g("t", [("n1", "steam.game_started", {}), ("n2", "her.tell", {"text": "x"}),
                                   ("n3", "her.tell", {"text": "y"})], ["n1.exec>n2.exec", "n2.done>n3.exec"]), cat).graph
        G.layout(graph, cat)
        xs = [n["pos"][0] for n in graph["nodes"]]
        self.assertEqual(xs, sorted(xs))
        self.assertEqual(len(set(xs)), 3)

    def test_durations_times_days(self):
        self.assertEqual(V.parse_duration("1h30m"), 5400)
        self.assertEqual(V.parse_duration("2 hours"), 7200)
        self.assertEqual(V.parse_duration(90), 90)
        self.assertIsNone(V.parse_duration("soon"))
        self.assertEqual(V.fmt_duration(5400), "1h30m")
        self.assertEqual(V.parse_time("10pm"), (22, 0))
        self.assertEqual(V.parse_time("7:05"), (7, 5))
        self.assertIsNone(V.parse_time("25:00"))
        self.assertEqual(V.parse_days("weekdays"), ["mon", "tue", "wed", "thu", "fri"])
        self.assertEqual(V.parse_days(["Saturday", "mon"]), ["mon", "sat"])
        self.assertIsNone(V.parse_days(["someday"]))
        self.assertTrue(V.compatible("number", "text") and V.compatible("duration", "number"))
        self.assertFalse(V.compatible("text", "number"))
        self.assertTrue(V.loose_eq("Running", "running") and V.loose_eq(3, "3"))


class ProtocolAdditionTests(unittest.TestCase):
    def rt(self, msg):
        return protocol.decode(protocol.encode(msg))

    def row(self, **kw):
        row = {"id": "f_1", "name": "n", "summary": "s", "enabled": True, "approved": True, "made_by": "aries",
               "uses_ai": False, "manual": False, "last_fired": None, "last_result": None, "note": None}
        row.update(kw)
        return row

    def test_flows_state(self):
        m = self.rt(protocol.flows_state([self.row(), self.row(id="f_2", last_fired=1.5, last_result="ok")]))
        self.assertEqual(len(m["data"]["flows"]), 2)
        bad = {k: v for k, v in self.row().items() if k != "uses_ai"}
        with self.assertRaises(protocol.ProtocolError):
            protocol.flows_state([bad])
        with self.assertRaises(protocol.ProtocolError):
            protocol.decode(json.dumps({"t": "state", "widget": "flows", "data": {"flows": [bad]}}))
        # the placeholder the server starts with still decodes
        self.rt(protocol.state("flows", {"status": "no adapter yet"}))

    def test_flow_message(self):
        m = self.rt(protocol.flow("f_1", "r_1", "fired", "n1", "steam"))
        self.assertEqual((m["phase"], m["node"], m["widget"], m["note"]), ("fired", "n1", "steam", None))
        m = self.rt(protocol.flow("f_1", "r_1", "failed", note="why"))
        self.assertEqual((m["node"], m["widget"], m["note"]), (None, None, "why"))
        with self.assertRaises(protocol.ProtocolError):
            protocol.flow("f", "r", "weird")
        with self.assertRaises(protocol.ProtocolError):
            protocol.flow("f", "r", "fired", widget="nope")
        with self.assertRaises(protocol.ProtocolError):
            protocol.decode('{"t":"flow","flow":"f","run":"r","phase":"weird"}')
        with self.assertRaises(protocol.ProtocolError):
            protocol.decode('{"t":"flow","flow":"f","run":"r"}')

    def test_ask_and_answer(self):
        m = self.rt(protocol.ask("a1", "Close it?", ["yes", "no"]))
        self.assertEqual((m["question"], m["options"]), ("Close it?", ["yes", "no"]))
        self.assertEqual(self.rt(protocol.answer("a1", "yes"))["choice"], "yes")
        with self.assertRaises(protocol.ProtocolError):
            protocol.ask("a", "q", [])
        with self.assertRaises(protocol.ProtocolError):
            protocol.decode('{"t":"ask","id":"a","question":"q","options":[]}')
        with self.assertRaises(protocol.ProtocolError):
            protocol.decode('{"t":"answer","id":"a"}')

    def test_flows_presses(self):
        for control in ("toggle", "run", "approve", "delete"):
            self.assertEqual(self.rt(protocol.press("flows", control, "f_1"))["value"], "f_1")
        with self.assertRaises(protocol.ProtocolError):
            protocol.decode('{"t":"press","widget":"flows","control":"explode"}')


if __name__ == "__main__":
    unittest.main()
