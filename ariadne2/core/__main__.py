"""python3 -m ariadne2.core [--demo] [--socket PATH] [--model NAME] [--personality NAME]"""
from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import time

from .. import adapters as adapters_mod
from .. import protocol

from . import models, prompt
from .flows.engine import Engine
from .loop import Conversation
from .tools import GeneralTools
from .server import CoreServer


def _make_voice(server):
    from .voice import Voice
    last = [0.0]

    def level(rms: float) -> None:
        # ~20 levels a second arrive; 12 a second is plenty for the waveform.
        now = time.monotonic()
        if now - last[0] >= 1 / 12 or rms == 0.0:
            last[0] = now
            asyncio.ensure_future(server.publish(protocol.voice(True, rms)))

    def piece(text: str, emotion: str, seconds: float) -> None:
        asyncio.ensure_future(server.publish(protocol.speak(text, seconds, emotion)))

    return Voice(on_level=level, on_piece=piece,
                 on_start=lambda: asyncio.ensure_future(server.publish(protocol.voice(True))),
                 on_stop=lambda: asyncio.ensure_future(server.publish(protocol.voice(False))))


def _make_ears(server, voice, conversation):
    from .ears import Ears

    def heard(text: str) -> None:
        voice.cancel()          # you talking over her stops her
        conversation.submit(text)

    return Ears(voice=voice, on_heard=heard,
                on_listening=lambda up: asyncio.ensure_future(server.publish(protocol.ears(up))))


log = logging.getLogger("ariadne2.core")


def _route_press(adapters, msg: dict) -> None:
    """A click in a widget goes to that widget's adapter, off the server's read loop."""
    adapter = adapters.get(msg.get("widget"))
    if adapter is None:
        return

    async def go() -> None:
        try:
            await adapter.press(msg["control"], msg.get("value"))
        except adapters_mod.AdapterError as e:
            log.info("press %s/%s: %s", msg["widget"], msg["control"], e)
        except Exception:
            log.exception("press %s/%s failed", msg["widget"], msg["control"])

    task = asyncio.ensure_future(go())
    _press_tasks.add(task)
    task.add_done_callback(_press_tasks.discard)


_press_tasks: set = set()


def _spawn_flow(coro) -> None:
    task = asyncio.ensure_future(coro)
    _press_tasks.add(task)
    task.add_done_callback(_press_tasks.discard)


async def run(args: argparse.Namespace) -> None:
    server = CoreServer(demo=args.demo, path=args.socket)
    engine: Engine | None = None

    async def publish(msg: dict) -> None:
        """What adapters publish: out to the desk, and state snapshots to the flow engine (Becomes)."""
        await server.publish(msg)
        if engine is not None:
            engine.observe(msg)

    adapters = adapters_mod.load_adapters(publish)
    voice = ears = None
    if not args.quiet:
        voice = _make_voice(server)
    conversation = Conversation(server.publish, lambda: server.snapshots,
                                model_name=args.model, personality=args.personality,
                                on_sentence=voice.say if voice else None,
                                adapters=adapters, toolsets=[GeneralTools()])
    engine = Engine(server.publish, adapters, conversation=conversation,
                    say=voice.say if voice else None)
    conversation.flows = engine
    conversation.on_text = engine.hear
    if voice and not args.no_ears:
        ears = _make_ears(server, voice, conversation)

    def on_desk(msg):
        if voice and msg.get("t") == "text":
            voice.cancel()      # typing to her cuts her off, like talking over her does
        if msg.get("t") == "press":
            _route_press(adapters, msg)
        if msg.get("t") in ("hello", "answer", "press"):
            _spawn_flow(engine.on_desk(msg))
        return conversation.on_desk_message(msg)
    server.on_desk_message = on_desk
    if server.demo:
        server.demo.echo_chat = False      # the real loop answers; demo keeps its fake actions
        server.demo.skip = set(adapters)   # ...except in widgets a real adapter drives
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    await server.start()
    from . import pet_inbox
    inbox_task = asyncio.create_task(pet_inbox.watch(conversation.submit))
    for adapter in adapters.values():
        try:
            await adapter.start()
        except Exception:
            log.exception("adapter %s failed to start", adapter.name)
    await engine.start()
    for part in (voice, ears):
        if part:
            await part.start()
    try:
        await stop.wait()
    finally:
        for part in (ears, voice):
            if part:
                await part.stop()
        await engine.stop()
        inbox_task.cancel()
        await conversation.stop()
        for adapter in adapters.values():
            try:
                await adapter.stop()
            except Exception:
                log.exception("adapter %s failed to stop", adapter.name)
        await server.stop()
        log.info("stopped")


def main() -> None:
    p = argparse.ArgumentParser(prog="ariadne2.core")
    p.add_argument("--demo", action="store_true", help="fake activity for testing the desk")
    p.add_argument("--socket", help="socket path (default: protocol.socket_path())")
    p.add_argument("--model", default=models.DEFAULT_MODEL, help="conversation model")
    p.add_argument("--personality", default=prompt.DEFAULT_PERSONALITY,
                   help="file name in personalities/, without .md")
    p.add_argument("--quiet", action="store_true", help="no voice and no mic")
    p.add_argument("--no-ears", action="store_true", help="voice, but no mic")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
