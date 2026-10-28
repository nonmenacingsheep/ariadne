"""python3 -m ariadne2.core [--demo] [--socket PATH] [--model NAME] [--personality NAME]"""
from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import time

from .. import protocol

from . import models, prompt
from .loop import Conversation
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

    return Voice(on_level=level,
                 on_start=lambda: asyncio.ensure_future(server.publish(protocol.voice(True))),
                 on_stop=lambda: asyncio.ensure_future(server.publish(protocol.voice(False))))


def _make_ears(server, voice, conversation):
    from .ears import Ears

    def heard(text: str) -> None:
        voice.cancel()          # you talking over her stops her
        conversation.submit(text)

    return Ears(voice=voice, on_heard=heard,
                on_listening=lambda up: asyncio.ensure_future(server.publish(protocol.ears(up))))


async def run(args: argparse.Namespace) -> None:
    server = CoreServer(demo=args.demo, path=args.socket)
    voice = ears = None
    if not args.quiet:
        voice = _make_voice(server)
    conversation = Conversation(server.publish, lambda: server.snapshots,
                                model_name=args.model, personality=args.personality,
                                on_sentence=voice.say if voice else None)
    if voice and not args.no_ears:
        ears = _make_ears(server, voice, conversation)
    def on_desk(msg):
        if voice and msg.get("t") == "text":
            voice.cancel()      # typing to her cuts her off, like talking over her does
        return conversation.on_desk_message(msg)
    server.on_desk_message = on_desk
    if server.demo:
        server.demo.echo_chat = False      # the real loop answers; demo keeps its fake actions
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    await server.start()
    for part in (voice, ears):
        if part:
            await part.start()
    try:
        await stop.wait()
    finally:
        for part in (ears, voice):
            if part:
                await part.stop()
        await conversation.stop()
        await server.stop()
        logging.getLogger("ariadne2.core").info("stopped")


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
