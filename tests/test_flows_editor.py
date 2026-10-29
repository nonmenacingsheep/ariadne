"""The core side of the visual flow editor: catalog, open, save, test, and live building."""
import json
import os
import unittest

from ariadne2 import protocol
from ariadne2.core.flows import tools
from tests.flowfakes import Rig, g

HIS = "make that happen"


def tell_flow(name="download tell", **kw):
    graph = g(name, [("n1", "steam.download_done", {}), ("n2", "her.tell", {})],
              ["n1.exec>n2.exec", "n1.name>n2.text"], **kw)
    graph["nodes"][0]["pos"] = [10.5, 20]
    graph["nodes"][1]["pos"] = [300, 40.25]
    return graph


def send_flow(name="dm kai"):
    return g(name, [("n1", "you.run_button", {}), ("n2", "steam.send", {"person": "Kai", "text": "hi"})],
             ["n1.exec>n2.exec"])


class EditorCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.rig = Rig(apps=("steam", "spotify"))
        self.addCleanup(self.rig.tmp.cleanup)
        self.e = self.rig.engine
        await self.rig.start()
        self.addAsyncCleanup(self.e.stop)

    async def ask(self, msg):
        """A desk message in; everything the core published in answer."""
        protocol.decode(protocol.encode(msg))               # it must be a valid wire message
        mark = len(self.rig.sent)
        await self.e.on_desk(msg)
        await self.e.idle()
        out = self.rig.sent[mark:]
        for m in out:
            protocol.decode(protocol.encode(m))             # ...and so must every answer
        return out

    def last(self, out, t):
        found = [m for m in out if m["t"] == t]
        self.assertTrue(found, f"no {t} in {[m['t'] for m in out]}")
        return found[-1]

    async def save(self, graph):
        return self.last(await self.ask(protocol.flow_save(graph)), "flow_saved")


class CatalogTests(EditorCase):
    async def test_catalog_lists_every_node_type_with_the_agreed_fields(self):
        msg = self.last(await self.ask(protocol.flow_catalog()), "catalog")
        types = {n["type"]: n for n in msg["nodes"]}
        self.assertEqual(len(msg["nodes"]), len(self.e.catalog))
        self.assertIn("steam.download_done", types)
        self.assertIn("spotify.volume", types)
        for key in ("type", "title", "category", "description", "inputs", "outputs", "exec_in", "exec_out",
                    "consent", "outside_content", "costly", "available"):
            self.assertIn(key, types["her.tell"])
        self.assertEqual(types["steam.send"]["consent"], "message")
        self.assertEqual(types["steam.download_done"]["category"], "start")
        json.dumps(msg)


class OpenTests(EditorCase):
    async def test_open_an_existing_flow(self):
        fid = self.rig.save(tell_flow())
        msg = self.last(await self.ask(protocol.flow_open(fid)), "flow_graph")
        self.assertEqual((msg["id"], msg["errors"]), (fid, []))
        self.assertNotIn("by", msg)
        self.assertEqual(msg["summary"], "When Steam finishes a download → Tell me ‹name›")
        self.assertEqual(msg["graph"]["name"], "download tell")
        self.assertEqual([n["pos"] for n in msg["graph"]["nodes"]], [[10.5, 20.0], [300.0, 40.25]])
        self.assertEqual(len(msg["graph"]["links"]), 2)

    async def test_open_a_fresh_graph_is_empty_and_not_saved(self):
        msg = self.last(await self.ask(protocol.flow_open(None)), "flow_graph")
        self.assertIsNone(msg["id"])
        self.assertEqual((msg["graph"]["nodes"], msg["graph"]["links"], msg["graph"]["id"]), ([], [], ""))
        self.assertFalse(msg["graph"]["enabled"])
        self.assertEqual(self.e.rows(), [])
        self.assertEqual(self.e.store.ids(), [])

    async def test_open_a_flow_that_does_not_exist(self):
        msg = self.last(await self.ask(protocol.flow_open("f_nope")), "flow_graph")
        self.assertIsNone(msg["graph"])
        self.assertEqual(msg["errors"][0]["message"], "there's no such flow")

    async def test_open_gives_nodes_without_a_position_one(self):
        fid = self.rig.save(tell_flow())
        flow = dict(self.e.flows[fid])
        flow["nodes"] = [dict(n, pos=None) for n in flow["nodes"]]
        self.e.flows[fid] = flow
        msg = self.last(await self.ask(protocol.flow_open(fid)), "flow_graph")
        self.assertTrue(all(isinstance(n["pos"], list) for n in msg["graph"]["nodes"]))


class SaveTests(EditorCase):
    async def test_save_a_new_flow(self):
        saved = await self.save(tell_flow())
        self.assertTrue(saved["ok"])
        self.assertEqual(saved["summary"], "When Steam finishes a download → Tell me ‹name›")
        fid = saved["id"]
        self.assertEqual(self.e.flows[fid]["made_by"], "ronald")
        self.assertTrue(self.e.flows[fid]["approved"])
        with open(os.path.join(self.rig.tmp.name, "flows", fid + ".json")) as f:
            self.assertEqual(json.load(f)["made_by"], "ronald")
        # the Flows widget hears about it
        out = [m for m in self.rig.sent if m["t"] == "state" and m["widget"] == "flows"]
        self.assertEqual([r["id"] for r in out[-1]["data"]["flows"]], [fid])

    async def test_node_positions_round_trip_untouched(self):
        saved = await self.save(tell_flow())
        opened = self.last(await self.ask(protocol.flow_open(saved["id"])), "flow_graph")["graph"]
        self.assertEqual([n["pos"] for n in opened["nodes"]], [[10.5, 20.0], [300.0, 40.25]])
        opened["nodes"][1]["pos"] = [-5.25, 777]
        opened["name"] = "renamed"
        again = await self.save(opened)
        self.assertEqual((again["ok"], again["id"]), (True, saved["id"]))
        self.assertEqual([n["pos"] for n in self.e.flows[saved["id"]]["nodes"]], [[10.5, 20.0], [-5.25, 777.0]])
        with open(os.path.join(self.rig.tmp.name, "flows", saved["id"] + ".json")) as f:
            self.assertEqual([n["pos"] for n in json.load(f)["nodes"]], [[10.5, 20.0], [-5.25, 777.0]])

    async def test_a_missing_value_names_the_node_and_the_pin(self):
        graph = tell_flow()
        graph["links"] = graph["links"][:1]                    # Tell's text is now unwired and empty
        saved = await self.save(graph)
        self.assertFalse(saved["ok"])
        self.assertNotIn("summary", saved)
        self.assertEqual(saved["errors"][0], {"node": "n2", "pin": "text", "message": "n2 (Tell): text needs a value"})
        self.assertEqual(self.e.rows(), [])

    async def test_a_type_mismatch_lands_on_the_wire_it_arrives_at(self):
        graph = g("odd", [("n1", "steam.download_done", {}), ("n2", "spotify.volume", {}), ("n3", "her.tell", {})],
                  ["n1.exec>n2.exec", "n1.name>n2.level", "n2.done>n3.exec"])
        graph["nodes"][2]["values"]["text"] = "x"
        saved = await self.save(graph)
        self.assertFalse(saved["ok"])
        err = saved["errors"][0]
        self.assertEqual((err["node"], err["pin"]), ("n2", "level"))
        self.assertIn("wants number", err["message"])

    async def test_unknown_type_flags_the_node_and_nameless_flows_flag_none(self):
        graph = g("", [("n1", "steam.download_done", {}), ("n2", "her.nothing", {})], ["n1.exec>n2.exec"])
        saved = await self.save(graph)
        by_message = {e["message"]: e for e in saved["errors"]}
        unknown = next(e for m, e in by_message.items() if "unknown node type" in m)
        self.assertEqual((unknown["node"], unknown["pin"]), ("n2", None))
        name = by_message["the flow needs a name"]
        self.assertEqual((name["node"], name["pin"]), (None, None))
        self.assertIsNone(saved["id"])

    async def test_an_unknown_input_and_a_loop_are_placed(self):
        graph = tell_flow()
        graph["nodes"][1]["values"]["bogus"] = 1
        saved = await self.save(graph)
        err = next(e for e in saved["errors"] if "bogus" in e["message"])
        self.assertEqual((err["node"], err["pin"]), ("n2", "bogus"))
        loop = g("loop", [("n1", "you.run_button", {}), ("n2", "check.cooldown", {"every": "1m"}),
                          ("n3", "check.cooldown", {"every": "1m"})],
                 ["n1.exec>n2.exec", "n2.exec>n3.exec", "n3.exec>n2.exec"])
        errs = (await self.save(loop))["errors"]
        self.assertEqual([e["node"] for e in errs if "loop" in e["message"]], ["n2"])

    async def test_safety_errors_are_placed_on_the_node(self):
        rig = Rig(apps=("steam", "web"))
        self.addCleanup(rig.tmp.cleanup)
        await rig.start()
        self.addAsyncCleanup(rig.engine.stop)
        graph = g("dm", [("n1", "web.track_changed", {}), ("n2", "steam.send", {"person": "Kai", "text": "x"})],
                  ["n1.exec>n2.exec"])
        await rig.engine.on_desk(protocol.flow_save(graph))
        saved = rig.msgs("flow_saved")[-1]
        self.assertFalse(saved["ok"])
        self.assertEqual(saved["errors"][0]["node"], "n2")

    async def test_the_widget_toggle_wins_over_the_editors_copy_of_enabled(self):
        fid = (await self.save(tell_flow()))["id"]
        await self.e.set_enabled(fid, False)
        graph = tell_flow()
        graph.update(id=fid, enabled=True)
        self.assertTrue((await self.save(graph))["ok"])
        self.assertFalse(self.e.flows[fid]["enabled"])

    async def test_saving_over_a_running_flow_replaces_it(self):
        fid = (await self.save(tell_flow()))["id"]
        graph = tell_flow("second name")
        graph["id"] = fid
        self.assertEqual((await self.save(graph))["id"], fid)
        self.assertEqual([r["name"] for r in self.e.rows()], ["second name"])
        self.rig.adapters["steam"].emit("download_done", name="Hades", appid=3)
        await self.e.idle()
        self.assertEqual(self.rig.chats(), ["Hades"])


class ApprovalTests(EditorCase):
    async def make_hers(self):
        out = await tools.call(self.e, "flow_save", {"graph": send_flow()}, HIS)
        self.assertIn("saved OFF", out)
        fid = self.e.rows()[0]["id"]
        self.assertEqual(self.e.flows[fid]["approved"], False)
        return fid

    async def test_his_save_of_her_unapproved_flow_is_his_approval(self):
        fid = await self.make_hers()
        graph = self.last(await self.ask(protocol.flow_open(fid)), "flow_graph")["graph"]
        self.assertFalse(graph["approved"])
        self.assertEqual(graph["made_by"], "aries")
        self.assertTrue((await self.save(graph))["ok"])
        row = self.e.rows()[0]
        self.assertEqual((row["approved"], row["enabled"], row["made_by"]), (True, True, "ronald"))

    async def test_an_approval_he_did_not_give_cannot_be_forged_by_the_graph(self):
        # her tool still can't claim approval; only his editor save grants it
        graph = send_flow()
        graph["approved"] = True
        await tools.call(self.e, "flow_save", {"graph": graph}, HIS)
        self.assertFalse(self.e.rows()[0]["approved"])

    async def test_his_own_flow_with_a_message_verb_saves_approved(self):
        saved = await self.save(send_flow())
        self.assertTrue(saved["ok"])
        self.assertEqual(self.e.flows[saved["id"]]["approved"], True)


class TestRunTests(EditorCase):
    def flow_events(self, out):
        return [(m["phase"], m["node"]) for m in out if m["t"] == "flow"]

    async def test_a_dry_run_lights_the_nodes_and_does_nothing(self):
        graph = g("vol", [("n1", "you.run_button", {}), ("n2", "spotify.volume", {"level": 20}),
                          ("n3", "her.tell", {"text": "done"})], ["n1.exec>n2.exec", "n2.done>n3.exec"])
        fid = (await self.save(graph))["id"]
        out = await self.ask(protocol.flow_test(id=fid))
        self.assertEqual(self.flow_events(out),
                         [("fired", "n1"), ("node", "n2"), ("node", "n3"), ("done", None)])
        self.assertEqual({m["flow"] for m in out if m["t"] == "flow"}, {fid})
        tested = self.last(out, "flow_tested")
        self.assertEqual((tested["id"], tested["ok"]), (fid, True))
        self.assertEqual(out[-1]["t"], "flow_tested")            # after the last node event
        self.assertEqual(self.rig.adapters["spotify"].ran, [])
        self.assertEqual(self.rig.chats(), [])
        # nothing of the test is left behind
        self.assertEqual(self.e.store.runs(fid), [])
        self.assertEqual([r["id"] for r in self.e.rows()], [fid])
        self.assertEqual(self.e.store.ids(), [fid])
        self.assertEqual(os.listdir(os.path.join(self.rig.tmp.name, "flow_state")) if os.path.isdir(
            os.path.join(self.rig.tmp.name, "flow_state")) else [], [])
        self.assertEqual(self.e.runs, {})

    async def test_an_unsaved_graph_can_be_tested_and_carries_sample_values(self):
        graph = tell_flow()
        out = await self.ask(protocol.flow_test(graph=graph))
        self.assertEqual(self.flow_events(out), [("fired", "n1"), ("node", "n2"), ("done", None)])
        tested = self.last(out, "flow_tested")
        self.assertTrue(tested["ok"])
        self.assertIsNone(tested["id"])
        self.assertEqual(self.rig.chats(), [])                   # Tell only pretended
        self.assertEqual(self.e.rows(), [])
        self.assertEqual(self.e.store.ids(), [])

    async def test_the_test_runs_the_edited_graph_not_the_saved_one(self):
        fid = (await self.save(tell_flow()))["id"]
        edited = tell_flow()
        edited["id"] = fid
        edited["nodes"].append({"id": "n3", "type": "her.tell", "values": {"text": "extra"}, "pos": [600, 0]})
        edited["links"].append({"from": ["n2", "done"], "to": ["n3", "exec"]})
        out = await self.ask(protocol.flow_test(id=fid, graph=edited))
        self.assertEqual([n for p, n in self.flow_events(out) if p == "node"], ["n2", "n3"])
        self.assertEqual({m["flow"] for m in out if m["t"] == "flow"}, {fid})
        self.assertEqual(len(self.e.flows[fid]["nodes"]), 2)

    async def test_waits_are_not_sat_through_and_state_is_not_touched(self):
        graph = g("slow", [("n1", "you.run_button", {}), ("n2", "flow.wait", {"duration": "1h"}),
                           ("n3", "data.set", {"name": "seen", "value": "yes"})],
                  ["n1.exec>n2.exec", "n2.exec>n3.exec"])
        fid = (await self.save(graph))["id"]
        self.e.store.state(fid)["vars"]["seen"] = "no"
        out = await self.ask(protocol.flow_test(id=fid))
        self.assertTrue(self.last(out, "flow_tested")["ok"])
        self.assertEqual([n for p, n in self.flow_events(out) if p == "node"], ["n2", "n3"])
        self.assertEqual(self.e.store.state(fid)["vars"]["seen"], "no")

    async def test_a_graph_that_does_not_validate_is_not_run(self):
        graph = tell_flow()
        graph["links"] = graph["links"][:1]
        out = await self.ask(protocol.flow_test(graph=graph))
        tested = self.last(out, "flow_tested")
        self.assertFalse(tested["ok"])
        self.assertIn("can't test yet", tested["note"])
        self.assertEqual(tested["errors"][0]["node"], "n2")
        self.assertEqual(self.flow_events(out), [])

    async def test_a_test_of_a_flow_that_is_off_or_unapproved_still_runs(self):
        fid = (await tools.call(self.e, "flow_save", {"graph": send_flow()}, HIS), self.e.rows()[0]["id"])[1]
        self.assertFalse(self.e.flows[fid]["approved"])
        out = await self.ask(protocol.flow_test(id=fid))
        self.assertTrue(self.last(out, "flow_tested")["ok"])
        self.assertEqual(self.rig.adapters["steam"].ran, [])     # the message was not sent

    async def test_testing_a_flow_that_is_not_there(self):
        tested = self.last(await self.ask(protocol.flow_test(id="f_nope")), "flow_tested")
        self.assertEqual((tested["ok"], tested["note"]), (False, "there's no such flow"))

    async def test_a_failing_test_says_why(self):
        graph = g("bad", [("n1", "you.run_button", {}), ("n2", "check.cooldown", {"every": "1h"}),
                          ("n3", "her.tell", {"text": "x"})], ["n1.exec>n2.exec", "n2.exec>n3.exec"])
        fid = (await self.save(graph))["id"]
        self.assertTrue(self.last(await self.ask(protocol.flow_test(id=fid)), "flow_tested")["ok"])
        # a second test is not held back by the first one's cooldown: tests never write the real timers
        self.assertTrue(self.last(await self.ask(protocol.flow_test(id=fid)), "flow_tested")["ok"])


class LiveBuildingTests(EditorCase):
    def graphs(self):
        return [m for m in self.rig.sent if m["t"] == "flow_graph"]

    async def test_her_flow_save_broadcasts_the_graph(self):
        await tools.call(self.e, "flow_save", {"graph": tell_flow()}, HIS)
        await self.e.idle()
        (msg,) = self.graphs()
        fid = self.e.rows()[0]["id"]
        self.assertEqual((msg["id"], msg["by"], msg["errors"]), (fid, "aries", []))
        self.assertEqual(msg["summary"], "When Steam finishes a download → Tell me ‹name›")
        self.assertEqual(msg["graph"]["made_by"], "aries")
        self.assertEqual(msg["graph"]["name"], "download tell")
        self.assertEqual([n["pos"] for n in msg["graph"]["nodes"]], [[10.5, 20.0], [300.0, 40.25]])
        protocol.decode(protocol.encode(msg))

    async def test_her_edit_of_a_flow_broadcasts_again(self):
        await tools.call(self.e, "flow_save", {"graph": tell_flow()}, HIS)
        fid = self.e.rows()[0]["id"]
        graph = tell_flow("better name")
        graph["id"] = fid
        await tools.call(self.e, "flow_save", {"graph": graph}, HIS)
        await self.e.idle()
        self.assertEqual([(m["id"], m["graph"]["name"]) for m in self.graphs()],
                         [(fid, "download tell"), (fid, "better name")])

    async def test_a_refused_save_broadcasts_nothing(self):
        graph = tell_flow()
        graph["links"] = graph["links"][:1]
        with self.assertRaises(Exception):
            await tools.call(self.e, "flow_save", {"graph": graph}, HIS)
        await self.e.idle()
        self.assertEqual(self.graphs(), [])

    async def test_her_enable_and_disable_broadcast_with_by_aries(self):
        await tools.call(self.e, "flow_save", {"graph": tell_flow()}, HIS)
        await tools.call(self.e, "flow_manage", {"op": "disable", "id": "download tell"}, HIS)
        await self.e.idle()
        last = self.graphs()[-1]
        self.assertEqual((last["by"], last["graph"]["enabled"]), ("aries", False))

    async def test_his_widget_press_broadcasts_the_flag_change_too(self):
        fid = (await self.save(tell_flow()))["id"]
        await self.e.on_desk(protocol.press("flows", "toggle", fid))
        await self.e.idle()
        last = self.graphs()[-1]
        self.assertEqual((last["id"], last["by"], last["graph"]["enabled"]), (fid, "ronald", False))

    async def test_approving_her_flow_from_the_widget_updates_an_open_editor(self):
        await tools.call(self.e, "flow_save", {"graph": send_flow()}, HIS)
        fid = self.e.rows()[0]["id"]
        await self.e.on_desk(protocol.press("flows", "approve", fid))
        await self.e.idle()
        last = self.graphs()[-1]
        self.assertEqual((last["graph"]["approved"], last["graph"]["enabled"]), (True, True))


class WireTests(unittest.TestCase):
    def test_constructors_round_trip_through_decode(self):
        for msg in (protocol.flow_catalog(), protocol.catalog([{"type": "x.y"}]), protocol.flow_open(None),
                    protocol.flow_open("f_1"), protocol.flow_graph("f_1", {"nodes": []}, "s", [], by="aries"),
                    protocol.flow_graph(None, {}, "", []), protocol.flow_graph("f", None, "", [protocol.flow_error("x")]),
                    protocol.flow_save({"name": "a"}), protocol.flow_saved("f_1", True, "sum"),
                    protocol.flow_saved("f_1", False, errors=[protocol.flow_error("bad", "n1", "text")]),
                    protocol.flow_test(id="f_1"), protocol.flow_test(graph={"nodes": []}, start="n1"),
                    protocol.flow_tested("f_1", True, "2 nodes ran"), protocol.flow_tested(None, False, "no")):
            self.assertEqual(protocol.decode(protocol.encode(msg)), msg)

    def test_decode_rejects_malformed_editor_messages(self):
        bad = [{"t": "flow_open"}, {"t": "flow_open", "id": 3}, {"t": "flow_save", "graph": "x"},
               {"t": "flow_save"}, {"t": "flow_test"}, {"t": "flow_test", "id": 4},
               {"t": "flow_graph", "id": "a", "graph": [], "summary": "", "errors": []},
               {"t": "flow_graph", "id": "a", "graph": {}, "summary": "", "errors": [{"message": "m"}]},
               {"t": "flow_saved", "id": "a", "ok": "yes"},
               {"t": "flow_saved", "id": "a", "ok": False, "errors": [{"node": None, "pin": None, "message": 3}]},
               {"t": "flow_tested", "id": "a", "ok": 1, "note": ""}, {"t": "catalog", "nodes": [{"title": "x"}]}]
        for msg in bad:
            with self.assertRaises(protocol.ProtocolError, msg=msg):
                protocol.decode(protocol.encode(msg))
        with self.assertRaises(protocol.ProtocolError):
            protocol.flow_test()


if __name__ == "__main__":
    unittest.main()
