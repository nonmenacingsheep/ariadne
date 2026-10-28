# Protocol

Core and desk talk over a unix socket (`$XDG_RUNTIME_DIR/ariadne2/core.sock`,
override with `ARIADNE2_SOCKET`). One compact JSON object per line, UTF-8,
ending in `\n`. Every object has a `"t"` field. Schema and constructors live
in `ariadne2/protocol.py`; `decode` rejects anything that doesn't match.

Widgets: `chat core spotify steam discord browser dolphin claude system flows`.

## Core to desk

| t | fields | meaning |
|---|---|---|
| `hello` | `v`, `side="core"`, `pid` | first line after connect |
| `state` | `widget`, `data` | full snapshot for one widget; replaces the previous one |
| `action` | `id`, `widget`, `verb`, `phase`, optional `control`, `note` | drives wires: `started` sends a packet out, `done`/`failed` brings it back (`progress` keeps it travelling) |
| `line` | `text`, `speaking` | her current action in one line, shown in the core widget |
| `chat` | `id`, `role` (`aries`/`you`), `delta`, `done` | streamed chat text; deltas with the same `id` append |

```
{"t":"hello","v":1,"side":"core","pid":4242}
{"t":"state","widget":"system","data":{"cpu":12.5,"mem":41.0,"mem_used_gb":6.5,"mem_total_gb":15.8}}
{"t":"action","id":"a1","widget":"spotify","verb":"next","phase":"started","control":"next"}
{"t":"line","text":"touching spotify…","speaking":false}
{"t":"chat","id":"c1","role":"aries","delta":"hello","done":true}
```

On connect the core sends `hello`, then the current snapshot of every widget,
then the current `line`.

## Desk to core

| t | fields | meaning |
|---|---|---|
| `hello` | `v`, `side="desk"`, `pid` | first line after connect |
| `press` | `widget`, `control`, optional `value` | you clicked a control in a widget; `value` for sliders (Spotify `volume` 0-100, `scrub` position in seconds; Spotify `jump` takes a track uri from the state's `history` or `queue`) |
| `text` | `widget`, `text` | you typed something, e.g. into chat |

```
{"t":"hello","v":1,"side":"desk","pid":4343}
{"t":"press","widget":"spotify","control":"next"}
{"t":"press","widget":"spotify","control":"volume","value":40}
{"t":"text","widget":"chat","text":"hi"}
```
