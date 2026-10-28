"""Fakes for the flow tests: a clock, an app adapter, a conversation, an engine on a temp folder."""
import datetime
import tempfile

from ariadne2.adapters import Adapter, AdapterError, Verb
from ariadne2.core.flows.engine import Engine
from ariadne2.core.flows.store import FlowStore


class FakeClock:
    def __init__(self, t=None):
        self.t = t if t is not None else datetime.datetime(2026, 10, 27, 12, 0, 0).timestamp()

    def now(self):
        return self.t


class FakeApp(Adapter):
    """An app with two events, a few verbs (one needs consent, one fails, one reads a page) and a state dict."""

    def __init__(self, publish, name="steam", emit_on_verb=None):
        super().__init__(publish)
        self.name = name
        self.events = ("game_started", "game_closed", "track_changed", "download_done")
        self.event_info = {"game_started": {"phrase": "starts a game", "fields": {"name": "text", "appid": "number"}},
                           "download_done": {"phrase": "finishes a download",
                                             "fields": {"name": "text", "appid": "number"}},
                           "game_closed": {"phrase": "closes a game", "fields": {"name": "text"}},
                           "track_changed": {"fields": {"title": "text"}, "outside": name == "web"}}
        self.state_fields = {"status": ("text", "status"), "volume": ("number", "volume")}
        self.data = {"status": "paused", "volume": 50}
        self.ran = []
        self.emit_on_verb = emit_on_verb      # (verb name, event name, fields) emitted while the verb runs

        async def volume(level):
            self.ran.append(("volume", level))
            self.data["volume"] = level
            return f"Volume set to {level}."

        async def nxt():
            self.ran.append(("next",))
            if self.emit_on_verb:
                self.emit(self.emit_on_verb[0], **self.emit_on_verb[1])
            return "Skipped."

        async def send(person, text):
            self.ran.append(("send", person, text))
            return f"Sent to {person}."

        async def boom():
            raise AdapterError("It isn't running.")

        async def read():
            return "page text"

        obj = {"type": "object", "properties": {"level": {"type": "integer"}}, "required": ["level"]}
        msg = {"type": "object", "properties": {"person": {"type": "string"}, "text": {"type": "string"}},
               "required": ["person", "text"]}
        self.verbs = [Verb("volume", "Set the volume.", obj, volume), Verb("next", "Skip.", {}, nxt),
                      Verb("send", "Send a message.", msg, send, consent="message"),
                      Verb("boom", "Always fails.", {}, boom),
                      Verb("read", "Read a page.", {}, read, outside_content=True)]

    def state(self):
        return self.data


class FakeConversation:
    def __init__(self, replies=None):
        self.calls = []
        self.replies = list(replies or [])

    async def flow_turn(self, flow_name, sentence, values=None, choices=None, post=True):
        self.calls.append({"flow": flow_name, "sentence": sentence, "values": values, "choices": choices,
                           "post": post})
        return self.replies.pop(0) if self.replies else "ok"


def g(name, nodes, links, **kw):
    """A graph from compact parts: nodes = [(id, type, values)], links = ["n1.exec>n2.exec"]."""
    out = {"name": name, "nodes": [{"id": i, "type": t, "values": v} for i, t, v in nodes],
           "links": [{"from": a.split("."), "to": b.split(".")} for a, b in (x.split(">") for x in links)]}
    out.update(kw)
    return out


class Rig:
    """An engine on a temp folder with fake apps, a fake clock, and everything it publishes."""

    def __init__(self, tmp=None, apps=("steam",), conversation=None, emit_on_verb=None, clock=None):
        self.tmp = tmp or tempfile.TemporaryDirectory()
        self.sent = []
        self.clock = clock or FakeClock()
        self.toasts = []

        async def publish(m):
            self.sent.append(m)

        async def notify(title, text):
            self.toasts.append((title, text))

        self.publish, self._notify = publish, notify
        self.adapters = {n: FakeApp(publish, n, emit_on_verb if i == 0 else None) for i, n in enumerate(apps)}
        self.conversation = conversation
        self.said = []
        self.make_engine()

    def make_engine(self):
        self.engine = Engine(self.publish, self.adapters, store=FlowStore(self.tmp.name), clock=self.clock,
                             conversation=self.conversation, say=self.said.append, notify=self._notify)
        return self.engine

    async def start(self):
        await self.engine.start(timers=False)

    async def advance(self, seconds):
        self.clock.t += seconds
        await self.engine.sched.run_due()
        await self.engine.idle()

    def save(self, graph, made_by="ronald"):
        res = self.engine.save_graph(graph, made_by=made_by)
        assert res.ok, res.errors
        return res.id

    def msgs(self, t, **match):
        return [m for m in self.sent if m["t"] == t and all(m.get(k) == v for k, v in match.items())]

    def chats(self):
        return [m["delta"] for m in self.sent if m["t"] == "chat"]

    def phases(self):
        return [m["phase"] for m in self.sent if m["t"] == "flow"]
