"""python3 -m ariadne2.core [--demo] [--socket PATH]"""
from __future__ import annotations

import argparse
import asyncio
import logging
import signal

from .server import CoreServer


async def run(args: argparse.Namespace) -> None:
    server = CoreServer(demo=args.demo, path=args.socket)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    await server.start()
    try:
        await stop.wait()
    finally:
        await server.stop()
        logging.getLogger("ariadne2.core").info("stopped")


def main() -> None:
    p = argparse.ArgumentParser(prog="ariadne2.core")
    p.add_argument("--demo", action="store_true", help="fake activity for testing the desk")
    p.add_argument("--socket", help="socket path (default: protocol.socket_path())")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
