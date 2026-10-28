"""A fake browser for the CDP, browser and Discord tests: no sockets, no network.

`FakeNet` stands in for both the HTTP endpoints and every WebSocket, and records
each CDP call as (target id, method, params). Scripts are answered by
`net.answers[expression]` (a value, or a callable taking the target id).
"""
import asyncio
import json

from ariadne2.adapters.cdp import Cdp, CdpError


def page(tid, title="", url="https://example.com/", **extra):
    return {"id": tid, "type": "page", "title": title, "url": url,
            "webSocketDebuggerUrl": f"ws://fake/page/{tid}", **extra}


class FakeSocket:
    def __init__(self, net, url):
        self.net, self.url = net, url
        self.q = asyncio.Queue()

    async def send(self, text):
        msg = json.loads(text)
        tid = "browser" if self.url.endswith("/browser") else self.url.rsplit("/", 1)[-1]
        self.net.calls.append((tid, msg["method"], msg["params"]))
        try:
            result = self.net.respond(tid, msg["method"], msg["params"])
            reply = {"id": msg["id"], "result": result}
        except CdpError as e:
            reply = {"id": msg["id"], "error": {"message": str(e)}}
        await self.q.put(json.dumps(reply))

    async def recv(self):
        item = await self.q.get()
        if item is None:
            raise CdpError("closed")
        return item

    async def close(self):
        await self.q.put(None)

    def event(self, method, params=None):
        self.q.put_nowait(json.dumps({"method": method, "params": params or {}}))


class FakeNet:
    def __init__(self, targets=None):
        self.targets = targets if targets is not None else []
        self.answers = {}
        self.calls = []
        self.down = False
        self.sockets = {}
        self.created = []

    async def http(self, path, method="GET"):
        if self.down:
            raise CdpError("the browser isn't running with its debugging port open")
        if path == "/json/version":
            return {"webSocketDebuggerUrl": "ws://fake/browser"}
        return list(self.targets)

    async def connect(self, url):
        s = self.sockets[url] = FakeSocket(self, url)
        return s

    def respond(self, tid, method, params):
        if method == "Runtime.evaluate":
            ans = self.answers.get(params["expression"])
            ans = ans(tid) if callable(ans) else ans
            if isinstance(ans, Exception):
                return {"exceptionDetails": {"text": "Uncaught"}, "result": {"description": str(ans)}}
            return {"result": {"value": ans}}
        if method == "Target.createTarget":
            new = f"new{len(self.created) + 1}"
            self.created.append(new)
            self.targets.append(page(new, "", params["url"]))
            return {"targetId": new}
        return {}

    def cdp(self):
        return Cdp(http=self.http, connect=self.connect)

    def methods(self, name):
        return [(t, p) for t, m, p in self.calls if m == name]


def media(playing=True, ended=False, position=10.0, length=300.0, muted=False, volume=1.0):
    return {"playing": playing, "ended": ended, "position": position, "length": length,
            "muted": muted, "volume": volume}
