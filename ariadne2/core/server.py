"""The core's socket server: holds the latest state per widget and fans out events."""
from __future__ import annotations

import asyncio
import inspect
import logging
import os
import pathlib

from .. import protocol
from . import sysinfo
from .demo import Demo

log = logging.getLogger("ariadne2.core")

LINE_LIMIT = 1 << 20          # a state snapshot can be big; 1 MiB per line
PET_PORT = 47120               # localhost only; her body (Godot) can't use a unix socket
DRAIN_TIMEOUT = 2.0           # a stuck desk is dropped rather than stalling everyone
SYSTEM_PERIOD = 2.0


class CoreServer:
    def __init__(self, demo: bool = False, path: str | os.PathLike | None = None,
                 on_desk_message=None) -> None:
        self.path = pathlib.Path(path) if path else protocol.socket_path()
        self.on_desk_message = on_desk_message
        self.snapshots: dict[str, dict] = {
            w: ({"messages": []} if w == "chat" else {"status": "no adapter yet"})
            for w in protocol.WIDGETS
        }
        self.line: dict = protocol.core_line("")
        self._clients: set[asyncio.StreamWriter] = set()
        self._server: asyncio.AbstractServer | None = None
        self._pet_server: asyncio.AbstractServer | None = None
        self._sampler = sysinfo.Sampler()
        self.snapshots["system"] = self._sampler.snapshot()
        self._system_task: asyncio.Task | None = None
        self._demo = Demo(self) if demo else None

    @property
    def demo(self) -> Demo | None:
        return self._demo

    async def start(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            self.path.unlink()          # stale socket from a crashed run
        except FileNotFoundError:
            pass
        self._server = await asyncio.start_unix_server(
            self._handle, path=str(self.path), limit=LINE_LIMIT)
        try:
            self._pet_server = await asyncio.start_server(self._handle_pet, "127.0.0.1", PET_PORT)
        except OSError as e:
            log.warning("pet port %d unavailable (%s); her body won't connect", PET_PORT, e)
        self._system_task = asyncio.create_task(self._system_loop())
        if self._demo:
            self._demo.start()
        log.info("listening on %s%s", self.path, " (demo)" if self._demo else "")

    async def stop(self) -> None:
        if self._demo:
            await self._demo.stop()
        if self._system_task:
            self._system_task.cancel()
            await asyncio.gather(self._system_task, return_exceptions=True)
        if self._server:
            self._server.close()
        if self._pet_server:
            self._pet_server.close()
        for w in list(self._clients):
            w.close()
        if self._server:
            await self._server.wait_closed()
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass

    async def publish(self, msg: dict) -> None:
        """Remember it (so late desks catch up), then send to every desk."""
        t = msg.get("t")
        if t == "state":
            self.snapshots[msg["widget"]] = msg["data"]
        elif t == "line":
            self.line = msg
        data = protocol.encode(msg)
        clients = list(self._clients)
        for w in clients:
            w.write(data)
        await asyncio.gather(*(self._drain(w) for w in clients))

    async def _drain(self, w: asyncio.StreamWriter) -> None:
        try:
            await asyncio.wait_for(w.drain(), DRAIN_TIMEOUT)
        except (ConnectionError, asyncio.TimeoutError, OSError):
            self._drop(w)

    def _drop(self, w: asyncio.StreamWriter) -> None:
        self._clients.discard(w)
        w.close()

    async def _system_loop(self) -> None:
        while True:
            await asyncio.sleep(SYSTEM_PERIOD)
            try:
                await self.publish(protocol.state("system", self._sampler.snapshot()))
            except Exception:
                log.exception("system refresh failed")

    async def _handle_pet(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        # Her body (pet/) only watches: it gets every broadcast, and anything
        # it sends is read and thrown away, so nothing reaching this port can
        # type to her or press anything.
        self._clients.add(writer)
        log.info("pet connected")
        try:
            while await reader.read(4096):
                pass
        except (ConnectionError, OSError):
            pass
        finally:
            self._drop(writer)

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        # No awaits between the catch-up writes and joining _clients, so a
        # publish can't slip in between and be missed or reordered.
        writer.write(protocol.encode(protocol.hello_core()))
        for widget, data in self.snapshots.items():
            writer.write(protocol.encode(protocol.state(widget, data)))
        writer.write(protocol.encode(self.line))
        self._clients.add(writer)
        log.info("desk connected (%d total)", len(self._clients))
        try:
            await self._drain(writer)
            while True:
                try:
                    raw = await reader.readline()
                except (ValueError, asyncio.LimitOverrunError):
                    log.warning("desk sent an oversized line; closing")
                    break
                if not raw:
                    break
                try:
                    msg = protocol.decode(raw)
                except protocol.ProtocolError as e:
                    log.warning("bad desk line ignored: %s", e)
                    continue
                await self._dispatch(msg)
        except (ConnectionError, OSError):
            pass
        finally:
            self._drop(writer)
            log.info("desk disconnected (%d left)", len(self._clients))

    async def _dispatch(self, msg: dict) -> None:
        hooks = []
        if self._demo:
            hooks.append(self._demo.on_desk_message)
        if self.on_desk_message:
            hooks.append(self.on_desk_message)
        for hook in hooks:
            try:
                result = hook(msg)
                if inspect.isawaitable(result):
                    await result
            except Exception:
                log.exception("desk message hook failed")
