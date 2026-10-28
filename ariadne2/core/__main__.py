"""python3 -m ariadne2.core [--demo] [--socket PATH] [--model NAME] [--personality NAME]"""
from __future__ import annotations

import argparse
import asyncio
import logging
import signal

from . import models, prompt
from .loop import Conversation
from .server import CoreServer


async def run(args: argparse.Namespace) -> None:
    server = CoreServer(demo=args.demo, path=args.socket)
    conversation = Conversation(server.publish, lambda: server.snapshots,
                                model_name=args.model, personality=args.personality)
    server.on_desk_message = conversation.on_desk_message
    if server.demo:
        server.demo.echo_chat = False      # the real loop answers; demo keeps its fake actions
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    await server.start()
    try:
        await stop.wait()
    finally:
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
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
