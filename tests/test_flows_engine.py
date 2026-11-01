import asyncio
import datetime
import json
import unittest

from ariadne2 import protocol
from tests.flowfakes import FakeClock, FakeConversation, Rig, g


NAMES5 = ["spotify", "steam", "browser", "dolphin", "claude"]


def at(h, m=0, s=0, day=27):
    return datetime.datetime(2026, 10, day, h, m, s).timestamp()


class EngineCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.rig = self.make_rig()
        self.addCleanup(self.rig.tmp.cleanup)
        self.e = self.rig.engine
        await self.rig.start()
        self.addAsyncCleanup(self.stop_all)

    async def stop_all(self):
        await self.rig.engine.stop()

    def make_rig(self):
        return Rig(apps=("steam", "spotify"))

    @property
    def steam(self):
        return self.rig.adapters["steam"]

    @property
    def spotify(self):
        return self.rig.adapters["spotify"]

    async def fire(self, **fields):
        self.steam.emit("game_started", **(fields or {"name": "Elden Ring", "appid": 1}))
        await self.e.idle()


class EventRunTests(EngineCase):
    def late_gaming(self):
        return g("late gaming",
                 [("n1", "steam.game_started", {}), ("n2", "check.compare", {"op": "contains", "b": "elden"}),
                  ("n3", "check.branch", {}), ("n4", "spotify.volume", {"level": 20}),
                  ("n5", "her.tell", {"text": "no volume change"})],
                 ["n1.exec>n3.exec", "n1.name>n2.a", "n2.result>n3.cond", "n3.true>n4.exec", "n3.false>n5.exec"])

    async def test_event_to_branch_to_action_through_call_tool(self):
        self.rig.save(self.late_gaming())
        await self.fire(name="Elden Ring", appid=1)
        self.assertEqual(self.spotify.ran, [("volume", 20)])
        # the wires animate: the adapter's own started/done, and the flow's fired/node/done
        self.assertEqual([m["phase"] for m in self.rig.msgs("action", widget="spotify")], ["started", "done"])
        flow_msgs = self.rig.msgs("flow")
        self.assertEqual([m["phase"] for m in flow_msgs], ["fired", "node", "node", "done"])
        self.assertEqual((flow_msgs[0]["node"], flow_msgs[0]["widget"]), ("n1", "steam"))
        self.assertEqual([(m["node"], m["widget"]) for m in flow_msgs[1:3]], [("n3", None), ("n4", "spotify")])
        for m in flow_msgs:
            protocol.decode(protocol.encode(m))
        self.assertIn("late gaming: Volume set to 20.", self.rig.chats())     # the one folded line
        row = self.rig.msgs("state", widget="flows")[-1]["data"]["flows"][0]
        self.assertEqual((row["last_result"], row["enabled"], row["uses_ai"]), ("ok", True, False))
        self.assertIsNotNone(row["last_fired"])

    async def test_false_branch(self):
        self.rig.save(self.late_gaming())
        await self.fire(name="Hades", appid=2)
        self.assertEqual(self.spotify.ran, [])
        self.assertIn("no volume change", self.rig.chats())

    async def test_run_history_kept_to_fifty(self):
        fid = self.rig.save(g("t", [("n1", "steam.game_started", {}), ("n2", "her.tell", {"text": "x"})],
                              ["n1.exec>n2.exec"], mode="parallel"))
        for i in range(55):
            self.steam.emit("game_started", name=f"G{i}", appid=i)
            await self.e.idle()
            self.e._rate.clear()                              # not testing the rate guard here
        runs = self.e.store.runs(fid)
        self.assertEqual(len(runs), 50)
        self.assertEqual(runs[-1]["trigger"]["fields"]["name"], "G54")
        self.assertEqual(runs[-1]["path"], ["n2"])
        self.assertEqual(runs[-1]["result"], "ok")

    async def test_disabled_and_unapproved_flows_do_not_fire(self):
        fid = self.rig.save(g("t", [("n1", "steam.game_started", {}), ("n2", "her.tell", {"text": "x"})],
                              ["n1.exec>n2.exec"], enabled=False))
        await self.fire()
        self.assertEqual(self.rig.chats(), [])
        self.assertEqual(await self.e.set_enabled(fid, True), "on")
        await self.fire()
        self.assertEqual(self.rig.chats(), ["x"])


class BecomesTests(EngineCase):
    def flow(self, hold=0):
        return g("playing", [("n1", "time.becomes", {"field": "spotify.status", "op": "is", "value": "playing",
                                                       "hold": hold}),
                             ("n2", "her.tell", {"text": "music's on"})], ["n1.exec>n2.exec"])

    def set_status(self, s):
        self.spotify.data["status"] = s
        self.e.on_state("spotify")

    async def test_edge_fires_once_not_while_it_stays_true(self):
        self.rig.save(self.flow())
        self.set_status("paused")
        await self.e.idle()
        self.assertEqual(self.rig.chats(), [])
        self.set_status("playing")
        await self.e.idle()
        self.set_status("playing")
        await self.e.idle()
        self.assertEqual(self.rig.chats(), ["music's on"])

    async def test_already_true_at_start_does_not_fire(self):
        self.spotify.data["status"] = "playing"
        self.rig.save(self.flow())                       # first sight sets the baseline
        self.e.on_state("spotify")
        await self.e.idle()
        self.assertEqual(self.rig.chats(), [])

    async def test_hold_must_stay_true(self):
        self.rig.save(self.flow(hold=10))
        self.set_status("playing")
        await self.rig.advance(6)
        self.assertEqual(self.rig.chats(), [])
        self.set_status("paused")                         # flapped: the hold is cancelled
        await self.rig.advance(10)
        self.assertEqual(self.rig.chats(), [])
        self.set_status("playing")
        await self.rig.advance(6)
        self.assertEqual(self.rig.chats(), [])
        await self.rig.advance(5)
        self.assertEqual(self.rig.chats(), ["music's on"])

    async def test_observe_tap_routes_state_messages(self):
        self.rig.save(self.flow())
        self.spotify.data["status"] = "playing"
        self.e.observe(protocol.state("spotify", self.spotify.data))
        await self.e.idle()
        self.assertEqual(self.rig.chats(), ["music's on"])


class SchedulerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.rig = Rig(clock=FakeClock(at(21, 59, 30)))
        self.addCleanup(self.rig.tmp.cleanup)
        self.e = self.rig.engine
        await self.rig.start()
        self.addAsyncCleanup(self.e.stop)

    async def test_at_fires_on_time_and_rearms_for_the_next_day(self):
        self.rig.save(g("bed", [("n1", "time.at", {"time": "22:00"}), ("n2", "her.tell", {"text": "bed"})],
                        ["n1.exec>n2.exec"]))
        await self.rig.advance(20)
        self.assertEqual(self.rig.chats(), [])
        await self.rig.advance(11)
        self.assertEqual(self.rig.chats(), ["bed"])
        self.assertEqual(self.e.sched.due_of(("t", self.e.rows()[0]["id"], "n1")), at(22, 0, 0, 28))
        await self.rig.advance(3600)
        self.assertEqual(self.rig.chats(), ["bed"])

    async def test_at_on_chosen_days_only(self):
        # 27 Oct 2026 is a Tuesday
        self.rig.save(g("bed", [("n1", "time.at", {"time": "22:00", "days": ["wed"]}),
                                ("n2", "her.tell", {"text": "bed"})], ["n1.exec>n2.exec"]))
        await self.rig.advance(31)
        self.assertEqual(self.rig.chats(), [])
        await self.rig.advance(86400)
        self.assertEqual(self.rig.chats(), ["bed"])

    async def test_a_missed_at_is_skipped_not_replayed(self):
        self.rig.save(g("bed", [("n1", "time.at", {"time": "22:00"}), ("n2", "her.tell", {"text": "bed"})],
                        ["n1.exec>n2.exec"]))
        await self.rig.advance(3 * 3600)                  # asleep through it
        self.assertEqual(self.rig.chats(), [])

    async def test_every_and_after(self):
        self.rig.save(g("tick", [("n1", "time.every", {"interval": "1m"}), ("n2", "her.tell", {"text": "tick {count}"}),
                                 ("n3", "data.text", {"template": "tick {count}"})],
                        ["n1.exec>n2.exec", "n1.count>n3.count", "n3.text>n2.text"]))
        fid2 = self.rig.save(g("once", [("n1", "time.after", {"delay": 30}), ("n2", "her.tell", {"text": "once"})],
                               ["n1.exec>n2.exec"]))
        await self.rig.advance(31)
        self.assertEqual(self.rig.chats(), ["once"])
        await self.rig.advance(30)
        await self.rig.advance(60)
        self.assertEqual([c for c in self.rig.chats() if c != "once"], ["tick 1", "tick 2"])
        self.assertEqual(self.rig.chats().count("once"), 1)
        # a restart doesn't repeat the one-shot
        await self.e.stop()
        e2 = self.rig.make_engine()
        await e2.start(timers=False)
        await self.rig.advance(100)
        self.assertEqual(self.rig.chats().count("once"), 1)
        await e2.stop()
        self.e = e2
        self.assertEqual(self.rig.engine.store.state(fid2)["timers"]["after:n1"], "done")


class PauseTests(EngineCase):
    def waiting(self):
        return g("later", [("n1", "steam.game_started", {}), ("n2", "flow.wait", {"duration": "1m"}),
                           ("n3", "her.tell", {"text": "a minute on"})], ["n1.exec>n2.exec", "n2.exec>n3.exec"])

    async def test_wait_pauses_and_resumes(self):
        self.rig.save(self.waiting())
        await self.fire()
        self.assertEqual(self.rig.chats(), [])
        self.assertEqual(len(self.e.runs), 1)
        await self.rig.advance(61)
        self.assertEqual(self.rig.chats(), ["a minute on"])
        self.assertEqual(self.e.runs, {})

    async def test_paused_run_survives_a_restart(self):
        fid = self.rig.save(self.waiting())
        await self.fire()
        self.assertEqual(len(self.e.store.state(fid)["paused"]), 1)
        await self.e.stop()
        e2 = self.rig.make_engine()
        await e2.start(timers=False)
        self.assertEqual(len(e2.runs), 1)
        await self.rig.advance(30)
        self.assertEqual(self.rig.chats(), [])
        await self.rig.advance(31)
        self.assertEqual(self.rig.chats(), ["a minute on"])
        self.assertEqual(e2.store.state(fid)["paused"], [])
        await e2.stop()

    async def test_wait_for_event_and_its_timeout(self):
        self.rig.save(g("close", [("n1", "steam.game_started", {}),
                                  ("n2", "flow.wait_for", {"event": "steam.game_closed", "timeout": "10m"}),
                                  ("n3", "her.tell", {"text": "closed"}), ("n4", "her.tell", {"text": "gave up"})],
                        ["n1.exec>n2.exec", "n2.exec>n3.exec", "n2.timeout>n4.exec"]))
        await self.fire()
        self.steam.emit("game_closed", name="Elden Ring")
        await self.e.idle()
        self.assertEqual(self.rig.chats(), ["closed"])
        await self.fire()
        await self.rig.advance(601)
        self.assertEqual(self.rig.chats(), ["closed", "gave up"])

    async def test_settle_waits_for_the_burst_to_end(self):
        self.rig.save(g("burst", [("n1", "steam.game_started", {}), ("n2", "check.settle", {"quiet": 10}),
                                  ("n3", "her.tell", {"text": "settled"})], ["n1.exec>n2.exec", "n2.exec>n3.exec"]))
        for _ in range(8):                                 # more than the rate limit: absorbed ones don't count
            await self.fire()
            await self.rig.advance(5)
        self.assertEqual(self.rig.chats(), [])
        await self.rig.advance(6)
        self.assertEqual(self.rig.chats(), ["settled"])
        self.assertTrue(self.e.flows[self.e.rows()[0]["id"]]["enabled"])


class AskRonaldTests(EngineCase):
    def flow(self, **kw):
        return g("ask", [("n1", "steam.game_started", {}),
                         ("n2", "you.ask_ronald", {"question": "Close it?", "options": ["yes", "no"], "timeout": 60}),
                         ("n3", "her.tell", {"text": "closing"}), ("n4", "her.tell", {"text": "leaving it"}),
                         ("n5", "her.tell", {"text": "no answer"})],
                 ["n1.exec>n2.exec", "n2.yes>n3.exec", "n2.no>n4.exec", "n2.timeout>n5.exec"], **kw)

    async def test_question_out_answer_in(self):
        self.rig.save(self.flow())
        await self.fire()
        ask = self.rig.msgs("ask")[0]
        self.assertEqual((ask["question"], ask["options"]), ("Close it?", ["yes", "no"]))
        await self.e.on_desk(protocol.answer("nope", "yes"))          # wrong id: nothing
        await self.e.on_desk(protocol.answer(ask["id"], "maybe"))     # not an option: nothing
        await self.e.idle()
        self.assertEqual(self.rig.chats(), [])
        await self.e.on_desk(protocol.answer(ask["id"], "no"))
        await self.e.idle()
        self.assertEqual(self.rig.chats(), ["leaving it"])

    async def test_timed_out_out(self):
        self.rig.save(self.flow())
        await self.fire()
        await self.rig.advance(61)
        self.assertEqual(self.rig.chats(), ["no answer"])

    async def test_question_is_resent_when_a_desk_connects(self):
        self.rig.save(self.flow())
        await self.fire()
        await self.e.on_desk(protocol.hello_desk())
        self.assertEqual(len(self.rig.msgs("ask")), 2)

    async def test_question_survives_restart(self):
        self.rig.save(self.flow())
        await self.fire()
        ask_id = self.rig.msgs("ask")[0]["id"]
        await self.e.stop()
        e2 = self.rig.make_engine()
        await e2.start(timers=False)
        self.assertEqual(self.rig.msgs("ask")[-1]["id"], ask_id)
        await e2.on_answer({"id": ask_id, "choice": "yes"})
        await e2.idle()
        self.assertEqual(self.rig.chats(), ["closing"])
        await e2.stop()


class ModeTests(EngineCase):
    def flow(self, mode):
        return g("m", [("n1", "steam.game_started", {}), ("n2", "flow.wait", {"duration": 60}),
                       ("n3", "her.tell", {"text": "{x}"})], ["n1.exec>n2.exec", "n2.exec>n3.exec"], mode=mode)

    async def run_mode(self, mode):
        self.rig.save(self.flow(mode))
        for i in range(3):
            self.steam.emit("game_started", name=f"G{i}", appid=i)
            await self.e.idle()
        return len(self.e.runs)

    async def test_ignore(self):
        self.assertEqual(await self.run_mode("ignore"), 1)
        await self.rig.advance(61)
        self.assertEqual(len(self.rig.chats()), 1)

    async def test_restart(self):
        self.assertEqual(await self.run_mode("restart"), 1)
        statuses = [r["result"] for r in self.e.store.runs(self.e.rows()[0]["id"])]
        self.assertEqual(statuses, ["cancelled", "cancelled"])
        await self.rig.advance(61)
        self.assertEqual(len(self.rig.chats()), 1)

    async def test_queue(self):
        self.assertEqual(await self.run_mode("queue"), 1)
        await self.rig.advance(61)           # first ends, second starts and waits
        self.assertEqual(len(self.rig.chats()), 1)
        await self.rig.advance(61)
        await self.rig.advance(61)
        self.assertEqual(len(self.rig.chats()), 3)

    async def test_parallel(self):
        self.assertEqual(await self.run_mode("parallel"), 3)
        await self.rig.advance(61)
        self.assertEqual(len(self.rig.chats()), 3)


class LoopGuardTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.rig = Rig(apps=NAMES5, emit_on_verb=None)
        self.addCleanup(self.rig.tmp.cleanup)
        self.e = self.rig.engine
        await self.rig.start()
        self.addAsyncCleanup(self.e.stop)

    async def test_a_flow_cannot_retrigger_itself(self):
        a = self.rig.adapters["spotify"]
        a.emit_on_verb = ("track_changed", {"title": "x"})
        self.rig.save(g("self", [("n1", "spotify.track_changed", {}), ("n2", "spotify.next", {})], ["n1.exec>n2.exec"]))
        a.emit("track_changed", title="start")
        await self.e.idle()
        self.assertEqual(a.ran, [("next",)])
        self.assertEqual(len(self.e.store.runs(self.e.rows()[0]["id"])), 1)

    async def test_chains_stop_at_depth_three(self):
        names = NAMES5
        for x, y in zip(names, names[1:]):
            self.rig.adapters[y].emit_on_verb = ("track_changed", {"title": "x"})
            self.rig.save(g(f"{x}-{y}", [("n1", f"{x}.track_changed", {}), ("n2", f"{y}.next", {})],
                            ["n1.exec>n2.exec"]))
        self.rig.adapters[names[0]].emit("track_changed", title="go")
        await self.e.idle()
        # 1->2 (depth 1), 2->3 (2), 3->4 (3); 4->5 would be depth 4
        self.assertEqual([n for n in names if self.rig.adapters[n].ran], names[1:4])

    async def test_more_than_six_a_minute_pauses_the_flow_and_says_so_once(self):
        fid = self.rig.save(g("busy", [("n1", "spotify.game_started", {}), ("n2", "her.tell", {"text": "hi"})],
                              ["n1.exec>n2.exec"], mode="parallel"))
        for i in range(10):
            self.rig.adapters["spotify"].emit("game_started", name=str(i), appid=i)
            await self.e.idle()
        self.assertEqual(self.rig.chats().count("hi"), 6)
        notices = [c for c in self.rig.chats() if "switched it off" in c]
        self.assertEqual(len(notices), 1)
        self.assertFalse(self.e.flows[fid]["enabled"])
        row = self.e.rows()[0]
        self.assertFalse(row["enabled"])
        self.assertIn("fired more than 6 times", row["note"])


class FailureTests(EngineCase):
    async def test_failed_pin_is_followed(self):
        self.rig.save(g("f", [("n1", "steam.game_started", {}), ("n2", "spotify.boom", {}),
                              ("n3", "her.tell", {"text": "worked"}), ("n4", "her.tell", {"text": "recovered"})],
                        ["n1.exec>n2.exec", "n2.done>n3.exec", "n2.failed>n4.exec"]))
        await self.fire()
        self.assertEqual(self.rig.chats(), ["recovered"])
        self.assertEqual(self.e.rows()[0]["last_result"], "ok")

    async def test_unwired_failure_stops_the_run_and_is_mentioned_once(self):
        self.rig.save(g("f", [("n1", "steam.game_started", {}), ("n2", "spotify.boom", {})], ["n1.exec>n2.exec"]))
        for _ in range(3):
            await self.fire()
        row = self.e.rows()[0]
        self.assertEqual((row["last_result"], row["note"]), ("failed", "It isn't running."))
        self.assertEqual(self.rig.chats(), ["f: stopped, It isn't running."])
        self.assertEqual(self.rig.phases().count("failed"), 3)
        self.assertEqual(self.rig.msgs("flow", phase="failed")[0]["note"], "It isn't running.")

    async def test_a_node_that_crashes_does_not_take_the_engine_down(self):
        self.rig.save(g("f", [("n1", "steam.game_started", {}), ("n2", "her.tell", {"text": "x"})],
                        ["n1.exec>n2.exec"]))

        async def bad(text):
            raise RuntimeError("x")
        self.e.tell = bad
        with self.assertLogs("ariadne2.core.flows", "ERROR"):
            await self.fire()
        self.assertEqual(self.e.rows()[0]["last_result"], "failed")


class GateTests(EngineCase):
    async def test_cooldown_and_once_per_day_and_count(self):
        self.rig.save(g("cool", [("n1", "steam.game_started", {}), ("n2", "check.cooldown", {"every": "1h"}),
                                 ("n3", "her.tell", {"text": "cool"})], ["n1.exec>n2.exec", "n2.exec>n3.exec"]))
        self.rig.save(g("daily", [("n1", "steam.game_started", {}), ("n2", "check.once_per_day", {}),
                                  ("n3", "her.tell", {"text": "daily"})], ["n1.exec>n2.exec", "n2.exec>n3.exec"]))
        self.rig.save(g("count", [("n1", "steam.game_started", {}), ("n2", "check.count", {"n": 3, "within": "1m"}),
                                  ("n3", "her.tell", {"text": "three"})], ["n1.exec>n2.exec", "n2.exec>n3.exec"]))
        await self.fire()
        await self.rig.advance(1)
        await self.fire()
        await self.rig.advance(1)
        self.assertEqual(sorted(self.rig.chats()), ["cool", "daily"])
        await self.fire()
        self.assertEqual(sorted(self.rig.chats()), ["cool", "daily", "three"])
        await self.rig.advance(3601)
        await self.fire()
        self.assertEqual(sorted(self.rig.chats()), ["cool", "cool", "daily", "three"])
        await self.rig.advance(86400)
        await self.fire()
        self.assertEqual(self.rig.chats().count("daily"), 2)

    async def test_for_each_text_set_get_and_math(self):
        fid = self.rig.save(g("data", [
            ("n1", "steam.game_started", {}), ("n2", "flow.for_each", {"items": ["a", "b", "c"]}),
            ("n3", "data.text", {"template": "item {item} of {total}", "total": 3}),
            ("n4", "her.tell", {}), ("n5", "data.get", {"name": "seen", "default": 0}),
            ("n6", "data.math", {"op": "+", "b": 1}), ("n7", "data.set", {"name": "seen"}),
            ("n8", "her.tell", {"text": "done"})],
            ["n1.exec>n2.exec", "n2.body>n7.exec", "n7.exec>n4.exec", "n2.done>n8.exec", "n2.item>n3.item",
             "n3.text>n4.text", "n5.value>n6.a", "n6.result>n7.value"]))
        await self.fire()
        self.assertEqual(self.rig.chats(), ["item a of 3", "item b of 3", "item c of 3", "done"])
        self.assertEqual(self.e.store.state(fid)["vars"]["seen"], 3)

    async def test_stop_ends_the_run(self):
        self.rig.save(g("s", [("n1", "steam.game_started", {}), ("n2", "flow.stop", {}),
                              ("n3", "her.tell", {"text": "never"})], ["n1.exec>n2.exec"]))
        await self.fire()
        self.assertEqual(self.rig.chats(), [])
        self.assertEqual(self.e.rows()[0]["last_result"], "ok")

    async def test_run_flow_waits_for_the_other_flow(self):
        self.rig.save(g("inner", [("n1", "you.run_button", {}), ("n2", "her.tell", {"text": "inner"})],
                        ["n1.exec>n2.exec"]))
        self.rig.save(g("outer", [("n1", "steam.game_started", {}), ("n2", "flow.run_flow", {"flow": "inner"}),
                                  ("n3", "her.tell", {"text": "outer"})], ["n1.exec>n2.exec", "n2.done>n3.exec"]))
        await self.fire()
        self.assertEqual(self.rig.chats(), ["inner", "outer"])


class UserStartTests(EngineCase):
    async def test_you_say_and_run_by_name(self):
        self.rig.save(g("say", [("n1", "you.say", {"phrase": "movie time"}), ("n2", "her.tell", {"text": "lights"})],
                        ["n1.exec>n2.exec"]))
        self.rig.save(g("Tidy Up", [("n1", "you.run_button", {}), ("n2", "her.tell", {"text": "tidied"})],
                        ["n1.exec>n2.exec"]))
        self.e.hear("hey, MOVIE time please")
        await self.e.idle()
        self.assertEqual(self.rig.chats(), ["lights"])
        self.e.hear("run tidy up")
        await self.e.idle()
        self.assertEqual(self.rig.chats(), ["lights", "tidied"])

    async def test_presses_toggle_run_approve_delete(self):
        fid = self.rig.save(g("p", [("n1", "you.run_button", {}), ("n2", "her.tell", {"text": "ran"})],
                              ["n1.exec>n2.exec"]))
        self.assertTrue(self.e.rows()[0]["manual"])
        await self.e.on_desk(protocol.press("flows", "run", fid))
        await self.e.idle()
        self.assertEqual(self.rig.chats(), ["ran"])
        await self.e.on_desk(protocol.press("flows", "toggle", fid))
        self.assertFalse(self.e.rows()[0]["enabled"])
        await self.e.on_desk(protocol.press("flows", "delete", fid))
        self.assertEqual(self.e.rows(), [])
        self.assertEqual(self.e.store.ids(), [])
        self.assertEqual(self.rig.msgs("state", widget="flows")[-1]["data"], {"flows": []})

    async def test_unapproved_flow_refuses_to_turn_on_until_approved(self):
        self.rig.adapters["steam"]
        fid = self.rig.save(g("risky", [("n1", "you.run_button", {}), ("n2", "steam.send", {"person": "kai", "text": "hi"})],
                              ["n1.exec>n2.exec"]), made_by="aries")
        row = self.e.rows()[0]
        self.assertEqual((row["approved"], row["enabled"]), (False, False))
        await self.e.on_desk(protocol.press("flows", "toggle", fid))
        self.assertFalse(self.e.rows()[0]["enabled"])
        self.assertEqual(self.e.rows()[0]["note"], "it needs your approval first")
        await self.e.on_desk(protocol.press("flows", "approve", fid))
        row = self.e.rows()[0]
        self.assertEqual((row["approved"], row["enabled"]), (True, True))


class ConsentInFlowsTests(EngineCase):
    def flow(self, question="Send Kai the score?", wired=False, answer_pin="yes", made="ronald"):
        nodes = [("n1", "you.run_button", {}), ("n2", "you.ask_ronald", {"question": question}),
                 ("n3", "steam.send", {"person": "Kai", "text": "we won"})]
        links = ["n1.exec>n2.exec", f"n2.{answer_pin}>n3.exec"]
        if wired:
            nodes[1] = ("n2", "you.ask_ronald", {})
            nodes.append(("n4", "data.text", {"template": question}))
            links.append("n4.text>n2.question")
        return g("score", nodes, links)

    async def run_flow(self, graph, choice="yes"):
        self.rig.save(graph)
        fid = self.e.rows()[0]["id"]
        self.e.run_now(fid)
        await self.e.idle()
        if self.rig.msgs("ask"):
            await self.e.on_answer({"id": self.rig.msgs("ask")[-1]["id"], "choice": choice})
            await self.e.idle()
        return self.e.rows()[0]

    async def test_without_an_ask_the_message_refuses(self):
        self.rig.save(g("nope", [("n1", "you.run_button", {}), ("n2", "steam.send", {"person": "Kai", "text": "x"})],
                        ["n1.exec>n2.exec"]))
        self.e.run_now(self.e.rows()[0]["id"])
        await self.e.idle()
        self.assertEqual(self.steam.ran, [])
        self.assertIn("Not sent", self.e.rows()[0]["note"])

    async def test_his_yes_to_a_question_naming_the_person_sends_once(self):
        row = await self.run_flow(self.flow())
        self.assertEqual(self.steam.ran, [("send", "Kai", "we won")])
        self.assertEqual(row["last_result"], "ok")

    async def test_question_that_doesnt_name_the_recipient_does_not_count(self):
        row = await self.run_flow(self.flow(question="Send it?"))
        self.assertEqual(self.steam.ran, [])
        self.assertEqual(row["last_result"], "failed")

    async def test_a_question_wired_from_data_never_counts(self):
        row = await self.run_flow(self.flow(wired=True))
        self.assertEqual(self.steam.ran, [])
        self.assertEqual(row["last_result"], "failed")

    async def test_the_grant_covers_one_message(self):
        graph = self.flow()
        graph["nodes"].append({"id": "n5", "type": "steam.send", "values": {"person": "Kai", "text": "again"}})
        graph["links"].append({"from": ["n3", "done"], "to": ["n5", "exec"]})
        row = await self.run_flow(graph)
        self.assertEqual(len(self.steam.ran), 1)
        self.assertEqual(row["last_result"], "failed")


class AskAriesTests(unittest.IsolatedAsyncioTestCase):
    async def test_ask_aries_and_decide_call_the_conversation_with_quoted_values(self):
        conv = FakeConversation(["he sounds fine", "urgent"])
        rig = Rig(conversation=conv)
        self.addCleanup(rig.tmp.cleanup)
        await rig.start()
        self.addAsyncCleanup(rig.engine.stop)
        rig.save(g("dm", [("n1", "steam.game_started", {}),
                          ("n2", "her.ask_aries", {"sentence": "does this sound ok?"}),
                          ("n3", "her.decide", {"sentence": "is it urgent?", "choices": ["urgent", "later"]}),
                          ("n4", "her.tell", {"text": "ping"}), ("n5", "her.tell", {"text": "later then"})],
                 ["n1.exec>n2.exec", "n1.name>n2.game", "n2.done>n3.exec", "n3.urgent>n4.exec",
                  "n3.later>n5.exec"]))
        rig.adapters["steam"].emit("game_started", name="Elden Ring", appid=1)
        await rig.engine.idle()
        self.assertEqual(conv.calls[0], {"flow": "dm", "sentence": "does this sound ok?",
                                         "values": {"game": "Elden Ring"}, "choices": None, "post": True})
        self.assertEqual((conv.calls[1]["choices"], conv.calls[1]["post"]), (["urgent", "later"], False))
        self.assertEqual(rig.chats(), ["ping"])
        self.assertTrue(rig.engine.rows()[0]["uses_ai"])

    async def test_decide_that_picks_nothing_fails(self):
        rig = Rig(conversation=FakeConversation(["hmm, not sure"]))
        self.addCleanup(rig.tmp.cleanup)
        await rig.start()
        self.addAsyncCleanup(rig.engine.stop)
        rig.save(g("d", [("n1", "steam.game_started", {}), ("n2", "her.decide", {"sentence": "?"}),
                         ("n3", "her.tell", {"text": "yes!"})], ["n1.exec>n2.exec", "n2.yes>n3.exec"]))
        rig.adapters["steam"].emit("game_started", name="x", appid=1)
        await rig.engine.idle()
        self.assertEqual(rig.engine.rows()[0]["last_result"], "failed")
        self.assertIn("didn't pick", rig.engine.rows()[0]["note"])

    async def test_say_uses_the_voice_and_notify_the_toast(self):
        rig = Rig()
        self.addCleanup(rig.tmp.cleanup)
        await rig.start()
        self.addAsyncCleanup(rig.engine.stop)
        rig.save(g("s", [("n1", "steam.game_started", {}), ("n2", "her.say", {"text": "hello"}),
                         ("n3", "desktop.notify", {"text": "hey"})], ["n1.exec>n2.exec", "n2.done>n3.exec"]))
        rig.adapters["steam"].emit("game_started", name="x", appid=1)
        await rig.engine.idle()
        self.assertEqual((rig.said, rig.toasts), (["hello"], [("Ariadne", "hey")]))
        self.assertEqual(rig.chats(), [])


class DryRunTests(EngineCase):
    async def test_dry_run_pretends(self):
        fid = self.rig.save(g("d", [("n1", "steam.game_started", {}), ("n2", "spotify.volume", {"level": 5})],
                              ["n1.exec>n2.exec"]))
        self.assertEqual(self.e.run_now(fid, dry=True), "started")
        await self.e.idle()
        self.assertEqual(self.spotify.ran, [])
        self.assertEqual(self.e.store.runs(fid), [])
        self.assertIn("done", self.rig.phases())


if __name__ == "__main__":
    unittest.main()


class LoopsAndSharedTests(EngineCase):
    async def run_button(self, fid):
        await self.e.on_desk(protocol.press("flows", "run", fid))
        await self.e.idle()

    async def test_repeat_runs_its_body_n_times_then_done(self):
        fid = self.rig.save(g("r", [("n1", "you.run_button", {}), ("n2", "flow.repeat", {"times": 3}),
                                    ("n3", "her.tell", {"text": "a"}), ("n4", "her.tell", {"text": "end"})],
                              ["n1.exec>n2.exec", "n2.body>n3.exec", "n2.done>n4.exec"]))
        await self.run_button(fid)
        self.assertEqual(self.rig.chats(), ["a", "a", "a", "end"])

    async def test_break_leaves_the_loop_for_its_done(self):
        # The retry shape: try, and on success break; otherwise go round again.
        fid = self.rig.save(g("r", [("n1", "you.run_button", {}), ("n2", "flow.repeat", {"times": 5}),
                                    ("n3", "her.tell", {"text": "a"}), ("n4", "flow.break", {}),
                                    ("n5", "her.tell", {"text": "end"})],
                              ["n1.exec>n2.exec", "n2.body>n3.exec", "n3.done>n4.exec", "n2.done>n5.exec"]))
        await self.run_button(fid)
        self.assertEqual(self.rig.chats(), ["a", "end"])

    async def test_shared_variables_cross_flows(self):
        a = self.rig.save(g("a", [("n1", "you.run_button", {}),
                                  ("n2", "data.set", {"name": "x", "value": "seven", "shared": True})], ["n1.exec>n2.exec"]))
        b = self.rig.save(g("b", [("n1", "you.run_button", {}), ("n2", "data.get", {"name": "x", "shared": True}),
                                  ("n3", "her.tell", {})], ["n1.exec>n3.exec", "n2.value>n3.text"]))
        c = self.rig.save(g("c", [("n1", "you.run_button", {}), ("n2", "data.get", {"name": "x", "default": "none"}),
                                  ("n3", "her.tell", {})], ["n1.exec>n3.exec", "n2.value>n3.text"]))
        await self.run_button(a)
        await self.run_button(b)
        await self.run_button(c)                        # its own variables don't see the shared one
        self.assertEqual(self.rig.chats(), ["seven", "none"])

    async def test_run_command_uses_her_shell_and_hers_needs_approval(self):
        from unittest import mock
        from ariadne2.core.tools import shell
        seen = []
        with mock.patch.object(shell, "run", lambda cmd, bg, cwd, words: (seen.append((cmd, words)), "$ echo hi\nhi")[1]):
            fid = self.rig.save(g("cmd", [("n1", "you.run_button", {}), ("n2", "shell.run", {"command": "echo hi"}),
                                          ("n3", "her.tell", {})], ["n1.exec>n2.exec", "n2.done>n3.exec", "n2.output>n3.text"]))
            await self.run_button(fid)
        self.assertEqual(seen[0][0], "echo hi")
        self.assertTrue(seen[0][1])                      # the flow stands in for his words
        self.assertIn("hi", self.rig.chats()[-1])
        res = self.e.save_graph(g("hers", [("n1", "you.run_button", {}), ("n2", "shell.run", {"command": "ls"})],
                                  ["n1.exec>n2.exec"]), made_by="aries")
        self.assertTrue(res.needs_approval)


class DatesTests(unittest.TestCase):
    def test_at_can_fire_on_days_of_the_month_and_the_last(self):
        from ariadne2.core.flows.sched import next_at
        now = at(12, day=27)                             # 27 Oct 2026, noon
        self.assertEqual(datetime.datetime.fromtimestamp(next_at(now, (9, 0), None, [1])).date(),
                         datetime.date(2026, 11, 1))
        self.assertEqual(datetime.datetime.fromtimestamp(next_at(now, (9, 0), None, ["last"])).date(),
                         datetime.date(2026, 10, 31))
        self.assertEqual(datetime.datetime.fromtimestamp(next_at(now, (13, 0), None, [27])).date(),
                         datetime.date(2026, 10, 27))

    def test_search_takes_loose_words(self):
        from tests.flowfakes import Rig
        rig = Rig()
        self.addCleanup(rig.tmp.cleanup)
        found = [nt.type for nt in rig.engine.catalog.search("start trigger time")]
        self.assertIn("time.at", found)
        self.assertEqual(rig.engine.catalog.search("retry loop")[0].type, "flow.repeat")
