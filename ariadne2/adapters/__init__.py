"""Adapter registry and the bridge to the model's tools.

The model sees one tool per adapter ("spotify", with an `action` field naming
the verb), so ~50 verbs cost seven tools. Verbs keep their own names inside
(`<adapter>_<verb>`, "spotify_next": the API forbids dots); flows and older
callers still use those, and call_tool takes either form.
"""
from __future__ import annotations

import importlib
import logging

from .base import Adapter, AdapterError, Verb

__all__ = ["Adapter", "AdapterError", "Verb", "REGISTRY", "load_adapters", "tools",
           "call_tool", "tool_name", "owns"]

log = logging.getLogger("ariadne2.adapters")

# widget name -> "module:Class", imported lazily so a missing library in one
# adapter can't stop the rest from loading.
REGISTRY = {"spotify": "ariadne2.adapters.spotify:SpotifyAdapter",
            "steam": "ariadne2.adapters.steam:SteamAdapter",
            "browser": "ariadne2.adapters.browser:BrowserAdapter",
            "dolphin": "ariadne2.adapters.dolphin:DolphinAdapter",
            "system": "ariadne2.adapters.system:SystemAdapter",
            "claude": "ariadne2.adapters.claude:ClaudeAdapter",
            "tasks": "ariadne2.adapters.tasks:TasksAdapter",
            "avatar": "ariadne2.adapters.avatar:AvatarAdapter"}


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


def _merged_schema(adapter: Adapter) -> dict:
    """One input schema for all of an adapter's verbs: `action` plus the union of
    their params. Which params each action needs is said in the description and
    checked in call_tool, since one schema can't say it per action."""
    props: dict = {"action": {"type": "string", "enum": [v.name for v in adapter.verbs]}}
    for v in adapter.verbs:
        for key, spec in (v.params.get("properties") or {}).items():
            have = props.get(key)
            if have is None:
                props[key] = dict(spec)
                continue
            if have.get("type") != spec.get("type"):
                have.pop("type", None)              # two verbs disagree: take either
            if "enum" in have or "enum" in spec:    # choices: the union, or free if one is free
                have["enum"] = (list(dict.fromkeys(have["enum"] + spec["enum"]))
                                if "enum" in have and "enum" in spec else None)
                if have["enum"] is None:
                    del have["enum"]
            if spec.get("description") and spec.get("description") != have.get("description"):
                have["description"] = (have.get("description", "") +
                                       f" ({v.name}: {spec['description']})").strip()
    return {"type": "object", "properties": props, "required": ["action"]}


def _merged_description(adapter: Adapter) -> str:
    lines = [getattr(adapter, "summary", "") or f"The {adapter.name} widget. Pick an action:"]
    for v in adapter.verbs:
        need = v.params.get("required") or []
        lines.append(f"- {v.name}: {v.description}" + (f" (needs {', '.join(need)})" if need else ""))
    return "\n".join(lines)


def tools(adapters: dict[str, Adapter]) -> list[dict]:
    """Anthropic tool definitions: one per adapter, its verbs as actions."""
    return [{"name": a.name, "description": _merged_description(a), "input_schema": _merged_schema(a)}
            for a in adapters.values() if a.verbs]


def _find(adapters: dict[str, Adapter], name: str, args: dict):
    """(adapter, verb, args) for a merged call ("spotify", action="next") or an
    old-style verb name ("spotify_next"); None if neither."""
    a = adapters.get(name)
    if a is not None and a.verbs:
        action = args.get("action")
        rest = {k: v for k, v in args.items() if k != "action"}
        for v in a.verbs:
            if v.name == action:
                return a, v, rest
        names = ", ".join(v.name for v in a.verbs)
        raise AdapterError(f"{name} has no action {action!r}; it has: {names}")
    for adapter in adapters.values():
        for v in adapter.verbs:
            if tool_name(adapter, v) == name:
                return adapter, v, args
    return None


def owns(adapters: dict[str, Adapter], name: str) -> bool:
    """Whether a tool name belongs to the adapters (merged or verb form)."""
    return (name in adapters and bool(adapters[name].verbs)) or any(
        tool_name(a, v) == name for a in adapters.values() for v in a.verbs)


async def call_tool(adapters: dict[str, Adapter], name: str, args: dict | None,
                    his_words: str | None = None) -> str:
    """Run a tool by name through its adapter (which animates the wires).

    his_words is what he typed or said this turn; verbs that speak for him
    check it before running.
    """
    from . import consent
    found = _find(adapters, name, dict(args or {}))
    if found is None:
        raise AdapterError(f"I have no tool called {name!r}")
    adapter, v, args = found
    missing = [k for k in (v.params.get("required") or []) if args.get(k) in (None, "")]
    if missing:
        raise AdapterError(f"{adapter.name} {v.name} needs {', '.join(missing)}")
    if v.consent == "message":
        person = args.get("person") or args.get("to") or args.get("recipient")
        if not consent.allows_message(his_words, person):
            raise AdapterError(consent.refusal(person))
    elif v.consent == "spend" and not consent.allows_spend(his_words):
        raise AdapterError(consent.spend_refusal())
    return await adapter.run(v.name, args)
