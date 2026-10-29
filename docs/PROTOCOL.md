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
| `catalog` | `nodes` | every node type the editor can offer (answer to `flow_catalog`) |
| `flow_graph` | `id`, `graph`, `summary`, `errors`, optional `by` | a whole flow file for the editor: the answer to `flow_open`, or, with `by="aries"` (or `"ronald"` for a widget toggle or Approve), a broadcast that the flow was just saved or changed |
| `flow_saved` | `id`, `ok`, `summary` or `errors`, optional `warnings` | the answer to `flow_save` |
| `flow_tested` | `id`, `ok`, `note`, optional `errors` | a dry run is over |
| `settings` | `schema`, `values` | every setting: the schema (a list of `{section, key, label, type, default, help, options?, min?, max?, step?, unit?, readonly?, action?}`; `type` is `bool`/`choice`/`number`/`text`/`key`; `options` is `[{value, label}]`) and the current `{section: {key: value}}`. Sent after the snapshots on connect and again after any `set`, accepted or refused, so a control that sent a bad value reverts. See SETTINGS.md |

| `menu` | `widget`, `path`, and `apps` or `info` | a one-off answer to a context-menu question about `path` (not a snapshot, never replayed): `apps` = `[{"id","name","icon"}]` that can open it (answer to the dolphin `apps_for` press), or `info` = `{size, modified, kind, mime, items?, permissions}` (answer to `properties`) |
| `attached` | `path`, `name`, `kind`, optional `error` | answer to `attach`: the chip for the chat input. `kind` is a files-widget kind or `folder`; on refusal `kind` is `""` and `error` says why |

```
{"t":"menu","widget":"dolphin","path":"/home/x/a.txt","apps":[{"id":"org.kde.kate.desktop","name":"Kate","icon":"kate"}]}
{"t":"menu","widget":"dolphin","path":"/home/x/a.txt","info":{"kind":"doc","mime":"text/plain","modified":1790000000,"permissions":"rw-r--r-- (644)","size":5}}
{"t":"attached","path":"/home/x/a.png","name":"a.png","kind":"image"}
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

### The flow editor

The desk holds no logic; the core checks, saves and test-runs every graph (DESIGN §10).

- `flow_catalog` -> `{"t":"catalog","nodes":[{type,title,category,description,inputs,outputs,exec_in,exec_out,consent,outside_content,costly,available, and sometimes note, dynamic_inputs, exec_out_from}]}`.
- `flow_open` `{"id":"f_ab12"}` -> `{"t":"flow_graph","id":"f_ab12","graph":{...the flow file...},"summary":"...","errors":[]}`.
  `graph` is the file as stored: `id, name, enabled, made_by, approved, mode, created, updated, nodes, links`; every
  node `{id, type, values, pos:[x,y]}` (positions are filled in for old flows that lack them), every link
  `{from:[node,pin], to:[node,pin]}`. `id` null opens `{"id":"","name":"","enabled":false,...,"nodes":[],"links":[]}` and
  nothing is saved. An unknown id answers `graph` null with one error. `errors` are the problems of a flow that no
  longer validates (same shape as below).
- `flow_save` `{"graph":{...}}` -> `{"t":"flow_saved","id":"f_ab12","ok":true,"summary":"..."}` (plus `warnings` in the
  error shape, if any) and a fresh `state` for the flows widget; or
  `{"t":"flow_saved","id":"f_ab12"|null,"ok":false,"errors":[{"node":"n2"|null,"pin":"text"|null,"message":"n2 (Tell): text needs a value"}]}`.
  A graph without an `id` becomes a new flow (the reply carries its id). Saved as `made_by` "ronald", `approved` true:
  saving one of her unapproved flows is his approval, and turns it on as the Approve button does. For an existing flow
  `enabled` is kept as the Flows widget has it, not as the editor's copy says. Node `pos` is stored untouched.
- `flow_test` `{"id":"f_ab12"}` or `{"graph":{...}}` (or both: the edited graph, reported under that id) -> the run's
  `flow` events (`fired`, `node` per node, `done`/`failed`) carrying the flow's id (`""` for a graph with none), then
  `{"t":"flow_tested","id":"f_ab12"|null,"ok":true,"note":"2 nodes ran"}`. It runs on a throwaway copy: actions only
  pretend, waits are skipped, the real flow's variables, cooldowns and history are untouched, and it needs no approval
  or switch-on. The start is `start` if given, else the Run button, else the first available start; its values are
  the last real firing's, or a sample. A graph that doesn't validate answers `ok` false, `note` "can't test yet: ...",
  and `errors`.
- Live building: whenever she saves or changes a flow (`flow_save`, `flow_manage` enable/disable) the core broadcasts
  `{"t":"flow_graph","id":"f_ab12","graph":{...},"summary":"...","errors":[],"by":"aries"}` so an open editor shows it
  appear (one message per save: her tool saves the whole graph at once). Approve or the toggle in the Flows widget
  broadcasts the same with `by="ronald"`.

On connect the core sends `hello`, then the current snapshot of every widget,
then the current `line`.

## Desk to core

| t | fields | meaning |
|---|---|---|
| `hello` | `v`, `side="desk"`, `pid` | first line after connect |
| `press` | `widget`, `control`, optional `value` | you clicked a control in a widget; `value` for sliders (Spotify `volume` 0-100, `scrub` position in seconds; Spotify `jump` takes a track uri from the state's `history` or `queue`) |
| `text` | `widget`, `text`, optional `attachments` (up to 8 paths) | you typed something, e.g. into chat; `attachments` are the files on the chips you accepted (shown to her this turn only; they are not your words) |
| `attach` | `path` | you picked "Paste into chat" on a file; the core answers with `attached` |
| `answer` | `id`, `choice` | the option you picked for an `ask` (`choice` must be one of its options) |
| `flow_catalog` | (none) | ask for the node catalog |
| `flow_open` | `id` | open a flow in the editor; `id` null = a fresh empty graph (not saved) |
| `flow_save` | `graph` | save his edit of a flow (the whole file) |
| `flow_test` | `id` and/or `graph`, optional `start` | dry-run a saved flow, or the graph as edited |
| `set` | `section`, `key`, `value` | you changed one setting; the core checks it, applies it, saves it and answers with a `settings`. A `readonly` key is refused; an `action` key (a button, like `desktop.reset_layout`) takes `true` and is not stored |

Presses on the flows widget: `press(widget="flows", control="toggle"|"run"|"approve"|"delete", value=<flow id>)`.
`toggle` turns it on or off (refused with a note on the row when it needs approval), `run` runs it now,
`approve` marks a flow she built as approved and turns it on, `delete` removes it. `decode` rejects other controls.

Presses on the dolphin widget (your context-menu clicks, no wire animation), `value` an object with `path`:
`open` (default app; a bare string still means show in Dolphin), `open_with` (+`app`, a .desktop id), `apps_for`
(publishes a `menu`), `reveal`, `copy_path`, `copy`/`cut` (or `paths`: [..]), `paste` (`folder`), `rename` (`name`),
`duplicate`, `new_folder` (`folder`, optional `name`), `compress` (optional `format` zip/tar.gz), `extract`, `trash`,
`properties` (publishes a `menu`). The dolphin state gains `clipboard: {mode, count, names}` while something is copied or cut.

```
{"t":"press","widget":"dolphin","control":"open_with","value":{"path":"/home/x/a.txt","app":"org.kde.kate.desktop"}}
{"t":"attach","path":"/home/x/a.png"}
{"t":"text","widget":"chat","text":"What's this?","attachments":["/home/x/a.png"]}
{"t":"hello","v":1,"side":"desk","pid":4343}
{"t":"press","widget":"spotify","control":"next"}
{"t":"press","widget":"spotify","control":"volume","value":40}
{"t":"text","widget":"chat","text":"hi"}
{"t":"answer","id":"ask-1a2b-4","choice":"yes"}
{"t":"press","widget":"flows","control":"run","value":"f_ab12"}
```

| `speak` | `{"t":"speak","text":"Paused.","seconds":0.6,"emotion":""}` | a sentence starting to play (her body shapes the vowels) |

```
{"t":"set","section":"avatar","key":"size","value":340}
{"t":"settings","schema":[{"section":"avatar","key":"size","label":"Size","type":"number","default":300,"help":"...","min":200,"max":420,"step":10,"unit":"px/m"}],"values":{"avatar":{"size":340}}}
```
