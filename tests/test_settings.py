"""The settings backend: schema, store, validation, migration, hooks, and the protocol messages."""
import array
import asyncio
import json
import math
import os
import tempfile
import unittest
from pathlib import Path

from ariadne2 import protocol
from ariadne2.core import settings as S
from ariadne2.core.ears import mic
from ariadne2.core.server import CoreServer
from ariadne2.core.voice import scale_pcm

# Ronald's exclusions: none of these may appear as a label or a key.
EXCLUDED = ["human mode", "human_mode", "think it through", "preflight", "curiosity", "cents a day",
            "draft skills", "self_improve", "her brain", "brain", "her delivery", "delivery",
            "read replies aloud", "speak_replies", "hide at the screen edge", "dock", "the city", "city",
            "orb"]


def make(tmp, **kw):
    return S.Settings(path=Path(tmp) / "settings.json", personality_names=lambda: ["aries", "ida"], **kw)


class Tmp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)


class SchemaTests(unittest.TestCase):
    schema = S.build_schema(["aries", "ida"])

    def test_sections_and_no_ears(self):
        self.assertEqual({e["section"] for e in self.schema}, set(S.SECTIONS))
        self.assertNotIn("ears", {e["section"] for e in self.schema})

    def test_shape(self):
        seen = set()
        for e in self.schema:
            for field in protocol.SETTING_ENTRY:
                self.assertIn(field, e)
            self.assertIn(e["type"], protocol.SETTING_TYPES)
            self.assertNotIn((e["section"], e["key"]), seen)
            seen.add((e["section"], e["key"]))
            self.assertLessEqual(len(e["help"]), 110, e["key"])
            if e["type"] == "number":
                for f in ("min", "max", "step"):
                    self.assertIn(f, e)
                self.assertTrue(e["min"] <= e["default"] <= e["max"], e["key"])
            if e["type"] == "choice":
                self.assertIn(e["default"], [o["value"] for o in e["options"]])

    def test_no_excluded_items(self):
        for e in self.schema:
            text = f"{e['key']} {e['label']}".lower()
            for bad in EXCLUDED:
                self.assertNotIn(bad, text, f"{e['section']}.{e['key']} is excluded")

    def test_ears_settings_live_in_general(self):
        keys = {e["key"] for e in self.schema if e["section"] == "general"}
        self.assertTrue({"wake_word", "wake_phrase", "ptt_key", "mic", "personality"} <= keys)

    def test_the_avatar_ranges(self):
        by = {e["key"]: e for e in self.schema if e["section"] == "avatar"}
        for k in ("energy_drain", "fun_drain", "affection_drain", "hunger_drain"):
            self.assertEqual((by[k]["min"], by[k]["max"], by[k]["default"]), (0.25, 4.0, 1.0))
        self.assertEqual((by["size"]["min"], by["size"]["max"]), (200, 840))
        for k in ("wander", "sit_on_widgets", "walk_off_edges", "dance_to_music", "play_ball", "nap",
                  "seek_cursor", "react_to_work", "lip_sync"):
            self.assertEqual(by[k]["type"], "bool")
        self.assertIn("fps_cap", by)
        self.assertIn("sleep_after", by)

    def test_models_default_is_sonnet(self):
        by = {e["key"]: e for e in self.schema if e["section"] == "models"}
        self.assertEqual(by["conversation_model"]["default"], "claude-sonnet-5-5")
        values = [o["value"] for o in by["conversation_model"]["options"]]
        self.assertIn("claude-opus-5-5", values)
        self.assertTrue(any(v.startswith("deepseek") for v in values))

    def test_one_switch_per_sound(self):
        keys = {e["key"] for e in self.schema if e["section"] == "voice"}
        for kind in S.SOUND_KINDS:
            self.assertIn(f"sound_{kind}", keys)

    def test_real_personalities_are_offered(self):
        names = S.personalities()
        self.assertIn("aries", names)

    def test_defaults_are_valid(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = make(tmp)
            for e in self.schema:
                if e.get("readonly") or e.get("action") or e.get("secret"):
                    continue
                self.assertEqual(s.validate(e["section"], e["key"], e["default"]), e["default"],
                                 f"{e['section']}.{e['key']}")
            self.assertEqual(s.values, S.Settings.defaults())


class ValidationTests(Tmp):
    def setUp(self):
        super().setUp()
        self.s = make(self.dir)

    def bad(self, section, key, value):
        with self.assertRaises(S.SettingsError, msg=f"{section}.{key}={value!r}"):
            self.s.validate(section, key, value)

    def test_bools_are_strict(self):
        for v in ("true", 1, 0, None, "yes"):
            self.bad("avatar", "wander", v)
        self.assertIs(self.s.validate("avatar", "wander", False), False)

    def test_numbers(self):
        self.bad("avatar", "energy_drain", 0.2)
        self.bad("avatar", "energy_drain", 4.5)
        self.bad("avatar", "size", 199)
        self.bad("avatar", "size", 841)
        self.bad("avatar", "size", "300")
        self.bad("avatar", "size", True)
        self.bad("avatar", "size", math.nan)
        self.bad("avatar", "size", math.inf)
        self.bad("voice", "speed", 1.6)
        self.bad("voice", "volume", -1)
        self.assertEqual(self.s.validate("avatar", "size", 250.0), 250)
        self.assertIsInstance(self.s.validate("avatar", "size", 250.0), int)
        self.assertEqual(self.s.validate("voice", "speed", 0.6), 0.6)

    def test_choices(self):
        self.bad("models", "conversation_model", "gpt-9")
        self.bad("models", "eyes_model", "")
        self.bad("general", "personality", "nobody")
        self.assertEqual(self.s.validate("general", "personality", "ida"), "ida")

    def test_wake_phrase(self):
        self.bad("general", "wake_phrase", "Aries")
        self.bad("general", "wake_phrase", "hey")
        self.bad("general", "wake_phrase", "hey <b>x</b>")
        self.bad("general", "wake_phrase", "hey " + "a" * 30)
        self.bad("general", "wake_phrase", 5)
        self.assertEqual(self.s.validate("general", "wake_phrase", " Hi   Ida "), "hey Ida")
        self.assertEqual(self.s.validate("general", "wake_phrase", "hey there Aries"), "hey Aries")

    def test_voice_and_mic(self):
        self.bad("voice", "voice", "not a voice")
        uuid = "db6b0ed5-d5d3-463d-ae85-518a07d3c2b4"
        self.assertEqual(self.s.validate("voice", "voice", uuid.upper()), uuid)
        self.assertEqual(self.s.validate("voice", "voice", ""), "skylar")
        self.bad("general", "mic", "a b; rm -rf")
        self.bad("general", "mic", "x" * 300)
        self.bad("general", "mic", "tab\there")
        self.assertEqual(self.s.validate("general", "mic", ""), "")
        self.assertEqual(self.s.validate("general", "mic", "alsa_input.usb-Mic-00.mono"),
                         "alsa_input.usb-Mic-00.mono")

    def test_readonly_and_unknown(self):
        self.bad("general", "ptt_key", "Meta+X")
        self.bad("desktop", "raise_key", "Meta+X")
        self.bad("general", "nothing", True)
        self.bad("nowhere", "wander", True)

    def test_set_rejects_and_keeps_the_old_value(self):
        before = self.s.get("avatar", "size")
        with self.assertRaises(S.SettingsError):
            self.s.set("avatar", "size", 9999)
        self.assertEqual(self.s.get("avatar", "size"), before)
        self.assertFalse(self.s.path.exists())

    def test_a_button_must_be_pressed_true(self):
        with self.assertRaises(S.SettingsError):
            self.s.set("desktop", "reset_layout", False)


class StoreTests(Tmp):
    def test_round_trip_and_full_file(self):
        s = make(self.dir)
        self.assertEqual(s.set("avatar", "size", 360), 360)
        s.set("voice", "speed", 1.25)
        s.set("general", "wake_phrase", "hey Ida")
        s.set("models", "conversation_model", "claude-opus-5-5")
        again = make(self.dir)
        self.assertEqual(again.get("avatar", "size"), 360)
        self.assertEqual(again.get("voice", "speed"), 1.25)
        self.assertEqual(again.get("general", "wake_phrase"), "hey Ida")
        self.assertEqual(again.get("models", "conversation_model"), "claude-opus-5-5")
        on_disk = json.loads(s.path.read_text())
        self.assertEqual(set(on_disk), set(S.SECTIONS))
        self.assertEqual(on_disk["avatar"]["size"], 360)
        self.assertIn("lip_sync", on_disk["avatar"])           # every key, for the pet
        self.assertNotIn("reset_layout", on_disk["desktop"])   # a button isn't a value

    def test_atomic_leaves_no_temp_files(self):
        s = make(self.dir)
        s.set("avatar", "wander", False)
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), ["settings.json"])

    def test_bad_file_gives_defaults(self):
        (self.dir / "settings.json").write_text("{nope")
        self.assertEqual(make(self.dir).values, S.Settings.defaults())

    def test_a_bad_value_in_the_file_falls_back_one_key(self):
        (self.dir / "settings.json").write_text(json.dumps(
            {"avatar": {"size": 5000, "wander": False, "mystery": 1}, "elsewhere": {"x": 1},
             "general": {"ptt_key": "Meta+Q"}}))
        s = make(self.dir)
        self.assertEqual(s.get("avatar", "size"), 300)
        self.assertIs(s.get("avatar", "wander"), False)
        self.assertEqual(s.get("general", "ptt_key"), "Meta+S")
        self.assertNotIn("mystery", s.values["avatar"])

    def test_snapshot_shows_readonly_and_hides_buttons_state(self):
        snap = make(self.dir).snapshot()
        self.assertEqual(snap["general"]["ptt_key"], "Meta+S")
        self.assertEqual(snap["desktop"]["raise_key"], "Meta+A")
        self.assertIs(snap["desktop"]["reset_layout"], False)

    def test_sounds_json_is_migrated_once(self):
        (self.dir / "sounds.json").write_text(json.dumps(
            {"master": False, "volume": 0.8, "muted": ["spotify", "drop", "bogus"]}))
        s = make(self.dir)
        v = s.values["voice"]
        self.assertIs(v["sounds_master"], False)
        self.assertEqual(v["sounds_volume"], 80)
        self.assertIs(v["sound_spotify"], False)
        self.assertIs(v["sound_drop"], False)
        self.assertIs(v["sound_send"], True)
        self.assertTrue((self.dir / "settings.json").exists())
        self.assertFalse((self.dir / "sounds.json").exists())
        self.assertTrue((self.dir / "sounds.json.migrated").exists())
        # Second start reads settings.json, not the set-aside file.
        self.assertIs(make(self.dir).values["voice"]["sound_spotify"], False)

    def test_sounds_json_is_ignored_when_settings_exist(self):
        s = make(self.dir)
        s.set("voice", "sounds_volume", 20)
        (self.dir / "sounds.json").write_text(json.dumps({"volume": 1.0, "muted": ["send"]}))
        again = make(self.dir)
        self.assertEqual(again.get("voice", "sounds_volume"), 20)
        self.assertIs(again.get("voice", "sound_send"), True)
        self.assertTrue((self.dir / "sounds.json").exists())

    def test_a_garbled_sounds_json_changes_nothing(self):
        (self.dir / "sounds.json").write_text("[1, 2")
        self.assertEqual(make(self.dir).values, S.Settings.defaults())

    def test_migrate_sounds_shapes(self):
        self.assertEqual(S.migrate_sounds(None), {})
        self.assertEqual(S.migrate_sounds({"volume": 7}), {})
        self.assertEqual(S.migrate_sounds({"volume": 0.5, "master": True})["sounds_volume"], 50)

    def test_sounds_config_for_the_page(self):
        s = make(self.dir)
        s.set("voice", "sounds_volume", 30)
        s.set("voice", "sound_mic", False)
        cfg = S.sounds_config(s.snapshot())
        self.assertEqual(cfg, {"master": True, "volume": 0.3, "muted": ["mic"]})
        self.assertEqual(S.sounds_config({}), {"master": True, "volume": 0.5, "muted": []})

    def test_the_default_path_follows_the_environment(self):
        old = {k: os.environ.get(k) for k in ("ARIADNE2_SETTINGS", "XDG_CONFIG_HOME")}
        self.addCleanup(lambda: [os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
                                 for k, v in old.items()])
        os.environ.pop("ARIADNE2_SETTINGS", None)
        os.environ["XDG_CONFIG_HOME"] = str(self.dir)
        self.assertEqual(S.default_path(), self.dir / "ariadne2" / "settings.json")
        os.environ["ARIADNE2_SETTINGS"] = str(self.dir / "x.json")
        self.assertEqual(S.default_path(), self.dir / "x.json")


class Fake:
    def __init__(self, **kw):
        self.__dict__.update(kw)
        self.calls = []


class FakeEars(Fake):
    def __init__(self):
        super().__init__(wake_word=True, names=Fake(name="Aries"))

    def set_wake_word(self, on):
        self.calls.append(("wake", on))
        self.wake_word = on

    def set_name(self, name):
        self.calls.append(("name", name))
        self.names = Fake(name=name)

    def set_mic(self, source):
        self.calls.append(("mic", source))


class HookTests(Tmp):
    def setUp(self):
        super().setUp()
        self.s = make(self.dir)
        self.conv = Fake(model_name="claude-sonnet-5-5", personality="aries")
        self.voice = Fake(voice=None, speed=1.0, volume=1.0)
        self.ears = FakeEars()
        self.operate = Fake(EYES={"model": None})
        self.auto, self.resets = [], []
        S.bind_core(self.s, conversation=self.conv, voice=self.voice, ears=self.ears,
                    operate=self.operate, autostart=self.auto.append,
                    reset_layout=lambda: self.resets.append(1))

    def test_model_switch_reaches_the_conversation(self):
        self.s.set("models", "conversation_model", "claude-opus-5-5")
        self.assertEqual(self.conv.model_name, "claude-opus-5-5")
        self.s.set("models", "conversation_model", "deepseek-flash")
        self.assertEqual(self.conv.model_name, "deepseek-flash")

    def test_personality_and_eyes(self):
        self.s.set("general", "personality", "ida")
        self.assertEqual(self.conv.personality, "ida")
        self.s.set("models", "eyes_model", "claude-haiku-5-5")
        self.assertEqual(self.operate.EYES["model"], "claude-haiku-5-5")

    def test_voice(self):
        self.s.set("voice", "voice", "db6b0ed5-d5d3-463d-ae85-518a07d3c2b4")
        self.s.set("voice", "speed", 1.3)
        self.s.set("voice", "volume", 40)
        self.assertEqual(self.voice.voice, "db6b0ed5-d5d3-463d-ae85-518a07d3c2b4")
        self.assertEqual(self.voice.speed, 1.3)
        self.assertEqual(self.voice.volume, 0.4)

    def test_ears(self):
        self.s.set("general", "wake_word", False)
        self.assertIn(("wake", False), self.ears.calls)
        self.s.set("general", "wake_phrase", "hi Ida")
        self.assertIn(("name", "Ida"), self.ears.calls)
        self.s.set("general", "mic", "alsa_input.usb-Mic")
        self.assertIn(("mic", "alsa_input.usb-Mic"), self.ears.calls)

    def test_an_unchanged_value_applies_nothing(self):
        self.s.set("voice", "speed", 1.0)
        self.s.set("general", "wake_word", True)
        self.assertEqual(self.ears.calls, [])
        self.s.set("voice", "speed", 1.2)
        self.voice.speed = 9
        self.s.set("voice", "speed", 1.2)      # same again: no second apply
        self.assertEqual(self.voice.speed, 9)

    def test_apply_all_matches_the_running_parts_to_the_file(self):
        self.s.values["voice"]["speed"] = 0.8
        self.s.values["voice"]["volume"] = 10
        self.s.values["models"]["conversation_model"] = "claude-opus-5-5"
        self.s.values["general"]["wake_phrase"] = "hey Ida"
        self.s.apply_all()
        self.assertEqual((self.voice.speed, self.voice.volume), (0.8, 0.1))
        self.assertEqual(self.conv.model_name, "claude-opus-5-5")
        self.assertIn(("name", "Ida"), self.ears.calls)
        self.assertNotIn(("wake", True), self.ears.calls)        # already true: left alone
        self.assertEqual(self.auto, [])                          # no write to autostart at startup
        self.assertEqual(self.resets, [])

    def test_apply_all_skip(self):
        self.s.values["models"]["conversation_model"] = "claude-opus-5-5"
        self.s.apply_all(skip={("models", "conversation_model")})
        self.assertEqual(self.conv.model_name, "claude-sonnet-5-5")

    def test_buttons_and_autostart(self):
        self.assertIs(self.s.set("desktop", "reset_layout", True), False)
        self.assertEqual(self.resets, [1])
        self.assertIs(self.s.values["desktop"].get("reset_layout"), None)
        self.s.set("desktop", "autostart", True)
        self.assertEqual(self.auto, [True])

    def test_a_failing_hook_does_not_lose_the_setting(self):
        def boom(_v):
            raise RuntimeError("no")
        self.s.hooks[("voice", "speed")] = boom
        with self.assertLogs("ariadne2.core.settings", "ERROR"):
            self.assertEqual(self.s.set("voice", "speed", 1.1), 1.1)
        self.assertEqual(make(self.dir).get("voice", "speed"), 1.1)

    def test_parts_may_be_missing(self):
        s = make(self.dir / "quiet")
        S.bind_core(s)
        s.set("voice", "speed", 1.1)
        s.apply_all()

    def test_listeners_hear_every_change(self):
        heard = []
        self.s.listeners.append(lambda *a: heard.append(a))
        self.s.set("avatar", "nap", False)
        self.s.set("desktop", "reset_layout", True)
        self.assertEqual(heard, [("avatar", "nap", False), ("desktop", "reset_layout", True)])

    def test_autostart_writes_and_removes_the_entry(self):
        tpl = self.dir / "t.desktop"
        tpl.write_text("[Desktop Entry]\nName=X\n")
        out = self.dir / "autostart"
        S.set_autostart(True, out, tpl)
        text = (out / "ariadne2.desktop").read_text()
        self.assertIn("Name=X", text)
        self.assertIn("X-GNOME-Autostart-enabled=true", text)
        S.set_autostart(False, out, tpl)
        self.assertFalse((out / "ariadne2.desktop").exists())
        S.set_autostart(False, out, tpl)      # already gone: fine
        real = Path(S.__file__).resolve().parents[2] / "docs" / "ariadne2.desktop"
        self.assertTrue(real.exists())


class PartsTests(unittest.TestCase):
    def test_mic_source_aims_the_recorder(self):
        self.assertEqual(mic.with_source(["parecord", "--raw"], "dev"), ["parecord", "--raw", "--device=dev"])
        self.assertEqual(mic.with_source(["pw-record", "--format=s16", "-"], "dev"),
                         ["pw-record", "--format=s16", "--target", "dev", "-"])
        self.assertEqual(mic.with_source(["ffmpeg", "-f", "pulse", "-i", "default", "-"], "dev"),
                         ["ffmpeg", "-f", "pulse", "-i", "dev", "-"])
        self.assertEqual(mic.with_source(["arecord", "-q"], "dev"), ["arecord", "-q"])
        self.assertEqual(mic.with_source(["parecord"], ""), ["parecord"])

    def test_mic_source_state(self):
        self.addCleanup(mic.set_source, "")
        mic.set_source("  dev ")
        self.assertEqual(mic.get_source(), "dev")
        self.assertEqual(mic.default_source(), "dev")
        mic.set_source("")
        self.assertEqual(mic.get_source(), "")

    def test_volume_scales_samples(self):
        pcm = array.array("h", [1000, -1000, 32767]).tobytes()
        self.assertEqual(scale_pcm(pcm, 1.0), pcm)
        half = array.array("h")
        half.frombytes(scale_pcm(pcm, 0.5))
        self.assertEqual(list(half), [500, -500, 16383])
        self.assertEqual(set(array.array("h", scale_pcm(pcm, 0)).tolist()), {0})
        self.assertEqual(scale_pcm(b"", 0.3), b"")
        self.assertEqual(scale_pcm(pcm, 5), pcm)       # never louder than the voice made it

    def test_ears_rename(self):
        from ariadne2.core.ears import Ears
        ears = Ears(name="Aries", aliases=("ares",))
        ears.set_name("Ida")
        self.assertEqual(ears.wake_phrase, "hey Ida")
        self.assertIs(ears.dialogue.names, ears.names)
        self.assertEqual(ears.names.aliases, ("ares",))
        self.assertEqual(ears.dialogue.names.heard_name("hey ida what time is it"), "what time is it")
        self.assertIsNone(ears.dialogue.names.heard_name("hey aries what time is it"))

    def test_operate_asks_the_chosen_eyes(self):
        from ariadne2.core.tools import operate
        self.assertIn("model", operate.EYES)


class ProtocolTests(Tmp):
    def test_round_trip(self):
        s = make(self.dir)
        msg = s.message()
        self.assertEqual(msg["t"], "settings")
        again = protocol.decode(protocol.encode(msg))
        self.assertEqual(again, msg)
        self.assertEqual(again["values"]["avatar"]["size"], 300)
        self.assertEqual(again["schema"], s.schema())

    def test_set_round_trip(self):
        msg = protocol.set_setting("avatar", "size", 320)
        self.assertEqual(protocol.decode(protocol.encode(msg)), msg)
        self.assertEqual(msg, {"t": "set", "section": "avatar", "key": "size", "value": 320})

    def test_decode_checks(self):
        ok = make(self.dir).message()
        for broken in (
                {**ok, "schema": "x"},
                {**ok, "schema": ["x"]},
                {**ok, "schema": [{"section": "a", "key": "b"}]},
                {**ok, "schema": [{**ok["schema"][0], "type": "slider"}]},
                {**ok, "values": []},
                {**ok, "values": {"general": 1}}):
            with self.assertRaises(protocol.ProtocolError):
                protocol.decode(protocol.encode(broken))
        for line in ({"t": "settings", "values": {}}, {"t": "set", "section": "a", "key": "b"},
                     {"t": "set", "section": 1, "key": "b", "value": 1},
                     {"t": "set", "section": "a", "key": ["b"], "value": 1}):
            with self.assertRaises(protocol.ProtocolError):
                protocol.decode(protocol.encode(line))

    def test_constructor_validates(self):
        with self.assertRaises(protocol.ProtocolError):
            protocol.settings([{"section": "a"}], {})
        with self.assertRaises(protocol.ProtocolError):
            protocol.settings([], {"a": 1})


class ServerTests(Tmp, unittest.IsolatedAsyncioTestCase):
    async def test_settings_go_to_a_desk_on_connect(self):
        s = make(self.dir)
        sock = str(self.dir / "run" / "core.sock")
        server = CoreServer(path=sock, settings_provider=s.message)
        await server.start()
        self.addAsyncCleanup(server.stop)
        r, w = await asyncio.open_unix_connection(sock)
        self.addCleanup(w.close)
        got = []
        for _ in range(len(protocol.WIDGETS) + 3):
            got.append(protocol.decode(await asyncio.wait_for(r.readline(), 3)))
        self.assertEqual(got[0]["t"], "hello")
        self.assertEqual(got[-1]["t"], "settings")
        self.assertEqual(got[-1]["values"]["models"]["conversation_model"], "claude-sonnet-5-5")

    async def test_set_is_routed_and_answered(self):
        from ariadne2.core import __main__ as core_main
        s = make(self.dir)
        sent = []

        class FakeServer:
            async def publish(self, msg):
                sent.append(msg)

        await core_main._apply_set(s, FakeServer(), protocol.set_setting("avatar", "size", 380))
        self.assertEqual(s.get("avatar", "size"), 380)
        self.assertEqual(sent[-1]["values"]["avatar"]["size"], 380)
        # A refused value still gets an answer, so the control that sent it can revert.
        await core_main._apply_set(s, FakeServer(), protocol.set_setting("avatar", "size", 1))
        self.assertEqual(s.get("avatar", "size"), 380)
        self.assertEqual(len(sent), 2)
        self.assertEqual(sent[-1]["values"]["avatar"]["size"], 380)
        await core_main._apply_set(s, FakeServer(), protocol.set_setting("nowhere", "x", 1))
        self.assertEqual(len(sent), 3)


if __name__ == "__main__":
    unittest.main()


class ApiKeyTests(unittest.TestCase):
    """Keys go to 0600 files and never into settings.json or the desk's message."""

    def setUp(self):
        import os
        import tempfile
        from pathlib import Path
        from unittest import mock
        self.tmp = Path(tempfile.mkdtemp())
        self.data = self.tmp / "data"
        env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY", "CARTESIA_API_KEY")}
        env["XDG_DATA_HOME"] = str(self.data)
        self.addCleanup(mock.patch.dict(os.environ, env, clear=True).stop)
        mock.patch.dict(os.environ, env, clear=True).start()
        self.st = S.Settings(path=self.tmp / "settings.json", personality_names=lambda: ["aries"])

    def test_saved_to_a_private_file_and_never_echoed(self):
        import json
        key = "sk-ant-api03-ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-wxyz"
        status = self.st.set("models", "anthropic_key", key)
        self.assertEqual(status, "set:…wxyz")
        path = self.data / "ariadne2" / "api_key"
        self.assertEqual(path.read_text().strip(), key)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        msg = json.dumps(self.st.message(), ensure_ascii=False)
        self.assertNotIn(key, msg)
        self.assertIn("set:…wxyz", msg)
        self.st.set("general", "wake_word", False)                  # any save of the settings file
        self.assertNotIn(key, (self.tmp / "settings.json").read_text())
        from ariadne2.core import models
        self.assertEqual(models.find_key("anthropic"), key)          # what her brain reads

    def test_remove_and_bad_values(self):
        self.st.set("models", "cartesia_key", "sk_car_abcdefgh1234")
        self.assertEqual(self.st.set("models", "cartesia_key", ""), "")
        self.assertFalse((self.data / "ariadne2" / "cartesia_key").exists())
        with self.assertRaises(S.SettingsError):
            self.st.set("models", "deepseek_key", "not a key; rm -rf")

    def test_environment_wins_and_says_so(self):
        import os
        os.environ["DEEPSEEK_API_KEY"] = "sk-envkey12345678"
        self.assertEqual(self.st.snapshot()["models"]["deepseek_key"], "env")


class SmallScreenTests(unittest.TestCase):
    def test_first_layout_fits_a_small_monitor(self):
        from ariadne2.desk import layout
        for area in ((0, 0, 1920, 1050), (0, 0, 1366, 728), (0, 32, 2560, 1408)):
            fitted = layout.fit(dict(layout.DEFAULT), area, scale=True)
            ax, ay, aw, ah = area
            for name, (x, y, w, h) in fitted.items():
                self.assertTrue(ax <= x and ay <= y and x + w <= ax + aw and y + h <= ay + ah, (area, name, (x, y, w, h)))
