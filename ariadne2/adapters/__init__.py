"""Adapter registry and the bridge to the model's tools.

Tool names are `<adapter>_<verb>` ("spotify_next"): the API forbids dots.
"""
from __future__ import annotations

import importlib
import logging

from .base import Adapter, AdapterError, Verb

__all__ = ["Adapter", "AdapterError", "Verb", "REGISTRY", "load_adapters", "tools",
           "call_tool", "tool_name"]

log = logging.getLogger("ariadne2.adapters")

# widget name -> "module:Class", imported lazily so a missing library in one
# adapter can't stop the rest from loading.
REGISTRY = {"spotify": "ariadne2.adapters.spotify:SpotifyAdapter",
            "steam": "ariadne2.adapters.steam:SteamAdapter",
            "browser": "ariadne2.adapters.browser:BrowserAdapter",
            "dolphin": "ariadne2.adapters.dolphin:DolphinAdapter",
            "system": "ariadne2.adapters.system:SystemAdapter",
            "claude": "ariadne2.adapters.claude:ClaudeAdapter"}


def load_adapters(publish, only=None) -> dict[str, Adapter]:
    out: dict[str, Adapter] = {}
    for name, path in REGISTRY.items():
        if only is not None and name not in only:
            continue
        module, _, cls = path.partition(":")
        try:
            out[name] = getattr(importlib.import_module(module), cls)(publish)
        except Exception:
            log.exception("adapter %s failed to load", name)
    return out


def tool_name(adapter: Adapter, verb: Verb) -> str:
    return f"{adapter.name}_{verb.name}"


def tools(adapters: dict[str, Adapter]) -> list[dict]:
    """Anthropic tool definitions for every verb of every adapter."""
    out = []
    for adapter in adapters.values():
        for v in adapter.verbs:
            out.append({"name": tool_name(adapter, v), "description": v.description,
                        "input_schema": v.schema()})
    return out


async def call_tool(adapters: dict[str, Adapter], name: str, args: dict | None,
                    his_words: str | None = None) -> str:
    """Run a tool by name through its adapter (which animates the wires).

    his_words is what he typed or said this turn; verbs that speak for him
    check it before running.
    """
    from . import consent
    for adapter in adapters.values():
        for v in adapter.verbs:
            if tool_name(adapter, v) == name:
                args = args or {}
                if v.consent == "message":
                    person = args.get("person") or args.get("to") or args.get("recipient")
                    if not consent.allows_message(his_words, person):
                        raise AdapterError(consent.refusal(person))
                elif v.consent == "spend" and not consent.allows_spend(his_words):
                    raise AdapterError(consent.spend_refusal())
                return await adapter.run(v.name, args)
    raise AdapterError(f"I have no tool called {name!r}")
