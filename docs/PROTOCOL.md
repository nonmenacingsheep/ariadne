# Protocol

Core and desk talk over a unix socket (`$XDG_RUNTIME_DIR/ariadne2/core.sock`,
override with `ARIADNE2_SOCKET`). One compact JSON object per line, UTF-8,
ending in `\n`. Every object has a `"t"` field. Schema and constructors live
in `ariadne2/protocol.py`; `decode` rejects anything that doesn't match.


## Core to desk

| t | fields | meaning |
|---|---|---|
| `hello` | `v`, `side="core"`, `pid` | first line after connect |
| `state` | `widget`, `data` | full snapshot for one widget; replaces the previous one |
| `action` | `id`, `widget`, `verb`, `phase`, optional `control`, `note` | drives wires: `started` sends a packet out, `done`/`failed` brings it back (`progress` keeps it travelling) |
| `line` | `text`, `speaking` | her current action in one line, shown in the core widget |
| `chat` | `id`, `role` (`aries`/`you`), `delta`, `done` | streamed chat text; deltas with the same `id` append |
| `flow` | `flow`, `run`, `phase` (`fired`/`node`/`done`/`failed`), `node`, `widget`, `note` | a flow run moving; `node` and `widget` may be null. `fired` carries the widget where the trigger happened (null for time starts); `node` is each node entered (`widget` = its adapter, if any); `failed` carries the reason in `note`. Drives the wire animation and the editor's live view |
| `ask` | `id`, `question`, `options` | an Ask Ronald question for the chat, one button per option (re-sent when a desk connects while it is still open) |

```
{"t":"hello","v":1,"side":"core","pid":4242}
{"t":"state","widget":"system","data":{"cpu":12.5,"mem":41.0,"mem_used_gb":6.5,"mem_total_gb":15.8}}
{"t":"action","id":"a1","widget":"spotify","verb":"next","phase":"started","control":"next"}
{"t":"line","text":"touching spotify…","speaking":false}
{"t":"chat","id":"c1","role":"aries","delta":"hello","done":true}
```

### The `flows` widget state

`state` with `widget="flows"` carries `{"flows": [row, ...]}`, republished on any change. A row:
`id`, `name`, `summary` (one line written from the graph), `enabled`, `approved`, `made_by`
(`ronald`/`aries`), `uses_ai` (has Ask Aries or Decide), `manual` (has a Run button),
`last_fired` (epoch or null), `last_result` (`ok`/`failed`/null), `note` (a reason, or null).
`decode` checks every row has all of those keys.

```
{"t":"flow","flow":"f_ab12","run":"r_1a2b_3","phase":"fired","node":"n1","widget":"steam","note":null}
{"t":"ask","id":"ask-1a2b-4","question":"Send Kai the score?","options":["yes","no"]}
```

On connect the core sends `hello`, then the current snapshot of every widget,
then the current `line`.

## Desk to core

| t | fields | meaning |
|---|---|---|
| `hello` | `v`, `side="desk"`, `pid` | first line after connect |
| `press` | `widget`, `control`, optional `value` | you clicked a control in a widget; `value` for sliders (Spotify `volume` 0-100, `scrub` position in seconds; Spotify `jump` takes a track uri from the state's `history` or `queue`) |
| `text` | `widget`, `text` | you typed something, e.g. into chat |
| `answer` | `id`, `choice` | the option you picked for an `ask` (`choice` must be one of its options) |

Presses on the flows widget: `press(widget="flows", control="toggle"|"run"|"approve"|"delete", value=<flow id>)`.
`toggle` turns it on or off (refused with a note on the row when it needs approval), `run` runs it now,
`approve` marks a flow she built as approved and turns it on, `delete` removes it. `decode` rejects other controls.

```
{"t":"hello","v":1,"side":"desk","pid":4343}
{"t":"press","widget":"spotify","control":"next"}
{"t":"press","widget":"spotify","control":"volume","value":40}
{"t":"text","widget":"chat","text":"hi"}
{"t":"answer","id":"ask-1a2b-4","choice":"yes"}
{"t":"press","widget":"flows","control":"run","value":"f_ab12"}
```
