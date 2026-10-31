"""python3 -m ariadne2.core [--demo] [--socket PATH] [--model NAME] [--personality NAME]"""
from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import time

from .. import adapters as adapters_mod
from .. import protocol

from . import models, prompt, settings as settings_mod
from .tools import operate as operate_mod
from .flows import editor as flow_editor
from .flows.engine import Engine
from .loop import Conversation
from .memory import MemoryToolset
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


def _cli_overrides(args) -> set:
    """Settings the command line chose for this run; the file must not undo them at startup."""
    skip = set()
    if args.model:
        skip.add(("models", "conversation_model"))
    if args.personality:
        skip.add(("general", "personality"))
    return skip


async def _apply_set(settings, server, msg: dict) -> None:
    """A setting changed on the desk: check it, apply it, and tell every desk what is now true
    (a refused value reverts the control that sent it)."""
    try:
        settings.set(msg["section"], msg["key"], msg["value"])
    except settings_mod.SettingsError as e:
        log.info("set %s.%s refused: %s", msg["section"], msg["key"], e)
    await server.publish(settings.message())


def _spawn_flow(coro) -> None:
    task = asyncio.ensure_future(coro)
    _press_tasks.add(task)
    task.add_done_callback(_press_tasks.discard)


async def run(args: argparse.Namespace) -> None:
    settings = settings_mod.Settings()
    server = CoreServer(demo=args.demo, path=args.socket, settings_provider=settings.message)
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
    from .extensions import Extensions, ExtensionTools
    extensions = Extensions(server.publish)
    memory = MemoryToolset()
    memory.warm()           # the model and the old transcript, loaded off the main thread
    conversation = Conversation(server.publish, lambda: server.snapshots,
                                model_name=args.model or settings.get("models", "conversation_model"),
                                personality=args.personality or settings.get("general", "personality"),
                                on_sentence=voice.say if voice else None,
                                adapters=adapters, toolsets=[GeneralTools(), memory, ExtensionTools(extensions)],
                                on_turn=memory.on_turn)
    engine = Engine(server.publish, adapters, conversation=conversation,
                    say=voice.say if voice else None)
    conversation.flows = engine
    conversation.on_text = engine.hear
    if voice and not args.no_ears:
        ears = _make_ears(server, voice, conversation)

    settings_mod.bind_core(settings, conversation=conversation, voice=voice, ears=ears, operate=operate_mod)
    settings.apply_all(skip=_cli_overrides(args))

    from .claude_live import LiveClaude
    live_claude = LiveClaude(server.publish)
    from .updater import Updater
    updater = Updater(server.publish, settings=settings)
    from .body_models import BodyModels
    body_models = BodyModels(server.publish, settings)
    settings.hooks[("general", "check_now")] = lambda _v: asyncio.ensure_future(updater.check())
    # Spotify's Web API login, from Settings > Models (adapters/spotify_login.py).
    from ..adapters import spotify_login
    spotify_note = {"text": ""}

    def spotify_said(text: str) -> None:
        spotify_note["text"] = "" if text.startswith("Connected") or text == "Not connected" else text
        asyncio.ensure_future(server.publish(settings.message()))
    settings.status_providers[("models", "spotify_connect")] = lambda: spotify_note["text"] or spotify_login.status()
    if not settings.get("models", "spotify_client_id") and spotify_login.saved_client_id():
        try:     # an existing login's app ID, so the box isn't blank while it's connected
            settings.set("models", "spotify_client_id", spotify_login.saved_client_id())
        except settings_mod.SettingsError:
            pass
    settings.hooks[("models", "spotify_connect")] = lambda _v: asyncio.ensure_future(
        spotify_login.connect(settings.get("models", "spotify_client_id") or spotify_login.saved_client_id(), spotify_said))
    settings.hooks[("models", "spotify_disconnect")] = lambda _v: spotify_said(spotify_login.disconnect())

    def on_desk(msg):
        # The Claude widget's own Claude Code session: his, never routed to her.
        if msg.get("t") == "cc_do":
            _spawn_flow(live_claude.on_desk(msg))
            return None
        # His Allow / Deny on an extension's approval card; and a desk that
        # (re)connects gets any cards still waiting.
        if msg.get("t") == "answer" and str(msg.get("id", "")).startswith("ext:"):
            _spawn_flow(extensions.answer(str(msg["id"]), str(msg.get("choice", ""))))
            return None
        if msg.get("t") == "hello":
            _spawn_flow(extensions.ask_pending())
        # Files menu > Use as her body: import that download and wear it.
        if msg.get("t") == "press" and msg.get("widget") == "dolphin" and msg.get("control") == "avatar_import":
            path = (msg.get("value") or {}).get("path") if isinstance(msg.get("value"), dict) else msg.get("value")
            if path:
                _spawn_flow(body_models.add(str(path), wear=True))
            return None
        if msg.get("t") == "update_do":
            _spawn_flow(updater.on_desk(msg))
            return None
        # Push-to-talk (Meta+S via KWin and the desk): press, speak, press.
        if msg.get("t") == "press" and msg.get("widget") == "core" and msg.get("control") == "talk":
            if ears:
                ears.toggle_talk()
            return None
        if msg.get("t") == "set":
            return _apply_set(settings, server, msg)
        if voice and msg.get("t") == "text":
            voice.cancel()      # typing to her cuts her off, like talking over her does
        if msg.get("t") == "press":
            _route_press(adapters, msg)
        if msg.get("t") in ("hello", "answer", "press", *flow_editor.IN):
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

    async def body_state():
        # Her body's needs and mood, for the Avatar widget.
        import json
        last = None
        while True:
            try:
                d = json.loads(pet_inbox.STATE.read_text())
                if d != last:
                    last = d
                    await server.publish(protocol.state("avatar", {k: d.get(k) for k in ("needs", "mood", "holding", "state")}))
            except (OSError, ValueError):
                pass
            await asyncio.sleep(4)
    avatar_task = asyncio.create_task(body_state())
    for adapter in adapters.values():
        try:
            await adapter.start()
        except Exception:
            log.exception("adapter %s failed to start", adapter.name)
    await engine.start()
    updater.start()
    extensions.start()
    body_models.start()
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
        await live_claude.end()
        updater.stop()
        await extensions.stop()
        body_models.stop()
        inbox_task.cancel()
        avatar_task.cancel()
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
    p.add_argument("--model", default=None, help="conversation model (default: the Models setting)")
    p.add_argument("--personality", default=None,
                   help="file name in personalities/, without .md (default: the General setting)")
    p.add_argument("--quiet", action="store_true", help="no voice and no mic")
    p.add_argument("--no-ears", action="store_true", help="voice, but no mic")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
