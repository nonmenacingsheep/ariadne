# Ariadne 2.0 — design

Status: step 1 (skeleton) built 2026-10-27; next is step 2 (§11).

## 1. What it is

Ariadne 2.0 is Aries's playground: a live layer on the ultrawide desktop where
her widgets show the apps she runs for you — Spotify, Steam, the
browser, Dolphin, Claude — and where you can watch her change things in them
while you talk to her.

It should feel like she lives in the desktop and has her hands on everything,
not like a chatbot with a tool list.

### Goals

- **One surface, not boxes.** Widgets are placed freely, but they read as one
  machine: a shared frame language, and live wires from each widget to her
  core that light up when she acts in it.
- **Watch her work.** Every action she takes shows up in a widget the moment
  it happens: the control she "pressed" flashes, a trace runs down the wire,
  the widget's state changes in front of you.
- **Seamless control.** "Skip this", "launch Elden Ring", "next episode"
  happen through the apps' real controls — reliably and fast, not by clicking
  around screenshots.
- **Code you can revamp.** Small, clear modules. A new app means one adapter
  plus one widget, and nothing else needs to know about it.

### Not goals (for 2.0)

- Driving real app windows with the mouse as the main way of working (it stays
  as a fallback for apps with no other way in).
- The inner "state of mind" layer — cut entirely (§7).
- Phones, other computers, other desktops. This is for KDE Plasma on Wayland,
  on this machine.

## 2. How it looks

### Placement

- **Ultrawide only** (DP-2, 3440×1440).
- One **transparent full-screen layer**, kept below all windows by KWin and
  shown on every virtual desktop. There are no desktop icons to cover.
  It has **no background of its own**: your Waywallen wallpaper shows
  through everywhere a widget isn't.
  - Why one layer rather than separate KDE widgets: the wires between widgets
    have to be drawn across the gaps between them, which needs one canvas.
    It also lets widgets move freely, overlap and animate together.
  - Clicks on empty parts of the layer pass through to the wallpaper (an
    input region covering only the widgets).
- **Widgets are draggable and resizable**, and snap to a soft 24 px grid.
  Drag any widget by its header at any time; resize from its corners. The
  layout is saved to `~/.config/ariadne2/layout.json` and can be reset to
  the starting one.
- An **edit mode** (Meta+Shift+A) shows the grid, lets you add or remove
  widgets, and shows where the wires run.

### Meta+A: bring her to the front

The layer lives behind your windows, so anything maximised hides it.

- **Meta+A** lifts the layer above every window and focuses the chat input,
  so you can type straight away. Nothing behind it dims — it's the same
  transparent layer, just on top.
- **Meta+A again, Esc, or a click on empty space** drops it back behind.
  While it's up, empty space catches clicks instead of passing them through,
  so a "click away" never lands by accident in the app underneath. Switching
  to another window (Alt+Tab, a notification) drops it too. An unsent chat
  draft is kept.
- How: one KWin script (`desk/kwin_layer.js`), loaded while the desk runs,
  pins the layer, registers Meta+A (it shows up in System Settings →
  Shortcuts under KWin as "Ariadne 2: bring to front", rebindable there),
  flips keep-below/keep-above, and drops the layer when another window takes
  focus. It calls back to the desk over D-Bus (`io.ariadne2.desk`). Esc and
  click-away use a one-shot script. Her mark gives one glitch twitch as the
  layer comes up.
- KWin keeps the layer itself out from under the Plasma panel and reports
  the usable area; the starting layout is squeezed to fit it.

### Starting layout

Proposed for 3440×1440, for you to drag around. The idea: a centred
1920-wide window leaves a 760 px strip on each side, and the two columns sit
exactly in those strips, so the busiest widgets stay visible while you work.
Her things are on the left (chat, her hands in Claude), your apps on the
right, the core is the hub at top centre so the wires fan out evenly, and
the bottom-centre row is what you see when a window is moved or Meta+A is
pressed.

```
 ┌────────────────┐                 ┌────────────┐                 ┌────────────────┐
 │ CHAT           │                 │ CORE       │                 │ SPOTIFY        │
 │                │                 └────────────┘                 │                │
 │                │                                                │                │
 │                │┊                                              ┊│                │
 │                │┊                                              ┊└────────────────┘
 │                │┊                                              ┊┌────────────────┐
 │                │┊                                              ┊│ DISCORD        │
 │                │┊                                              ┊│                │
 │                │┊                                              ┊│                │
 │                │┊   (a centred 1920-wide window sits here)     ┊└────────────────┘
 │                │┊                                              ┊
 │                │┊                                              ┊┌────────────────┐
 │                │┊                                              ┊│ STEAM          │
 │                │┊                                              ┊│                │
 └────────────────┘┊                                              ┊│                │
 ┌────────────────┐┊                                              ┊│                │
 │ CLAUDE         │┊                                              ┊└────────────────┘
 │                │┊                                              ┊┌────────────────┐
 │                │                                                │ BROWSER        │
 │                │ ┌────────────────────┐ ┌─────────────┐┌──────┐ │                │
 │                │ │ DOLPHIN            │ │ FLOWS       ││SYSTEM│ │                │
 │                │ │                    │ │             ││      │ │                │
 └────────────────┘ └────────────────────┘ └─────────────┘└──────┘ └────────────────┘
```

| Widget | x, y | w × h |
|---|---|---|
| Chat | 24, 24 | 736 × 912 |
| Claude | 24, 960 | 736 × 456 |
| Core | 1440, 24 | 560 × 144 |
| Spotify | 2680, 24 | 736 × 336 |
| Steam | 2680, 696 | 736 × 360 |
| Browser | 2680, 1080 | 736 × 336 |
| Dolphin | 784, 1176 | 912 × 240 |
| Flows | 1720, 1176 | 584 × 240 |
| System | 2328, 1176 | 328 × 240 |

If a Plasma panel sits on DP-2, the layout fits inside KWin's usable area
for the screen rather than these raw numbers.

### Visual language — red cyberpunk

Taken from the mock, then made to feel like one piece:

- **Ground:** none. The wallpaper is the ground. Because it moves and can be
  bright, the glass is a little more opaque than the mock (~80%), text gets
  a soft dark shadow, and every wire carries a 1 px dark under-stroke so it
  reads over anything.
- **Glass:** widgets are dark translucent red (#2a0a0e at ~70%) with a 1 px
  inner hairline (#ff2a3d at 35%) and a soft red outer glow. GTK can't blur
  what's behind a widget, so the "glass" is a tinted wash plus grain; on this
  ground it reads as frosted.
- **Accent:** blood red #ff2a3d for structure and live state. Bright red
  #ff4d5e when something is active. **Cyan #00e5ff only as the rare
  highlight**: the control she just touched, your words in the chat.
- **Shape:** chamfered corners (cut, not rounded) on frames and buttons,
  echoing the old window. Thin lines. No pill bubbles.
- **Type:** Rajdhani (condensed, uppercase) for labels and headers; Noto Sans
  for content; Fira Code for numbers and states.
- **Her mark:** not a serif "Ariadne" title. A compact glitch wordmark — the
  current misregistered one, recoloured red and white with a cyan offset —
  sitting in her core widget. It twitches when she starts acting.

### Her core and the wires

- A small **core** widget: her mark, a live voice waveform while she speaks,
  and her current action in one line ("skipping track…").
- From the core, a **wire** runs to each widget: a thin red line with a
  routed, circuit-like path (horizontal and vertical runs, 45° corners).
  - **Idle:** dim, with a slow faint pulse.
  - **Acting:** a bright packet travels from the core to the widget, the
    widget's frame flares, and the control she used lights cyan for a moment.
  - **Result:** a packet travels back. A failure sends back a red flicker
    and the widget shows why.
- Wires reroute live when you drag widgets.
- When a flow (§10) fires, the packet starts at the widget where the trigger
  happened, runs *up* its wire to the core, and then out to the widgets it
  acts in, so you see cause and effect cross the desk.

### Sounds

Small sound effects when she acts, each one mutable on its own, plus a
master switch.

| Sound | When |
|---|---|
| `send` | a packet leaves the core for a widget (she starts an action) |
| `done` | the result packet arrives back |
| `fail` | an action failed (red flicker) |
| `flow` | a flow fires |
| `spotify` | a track change, play or pause she caused |
| `steam` | a game launch or close she caused |
| `browser` | a tab opened, closed or switched by her |
| `dolphin` | a file moved, sorted or binned by her |
| `claude` | a hand starts or finishes |
| `mic` | the mic opens or closes (the 1.x chime) |
| `raise` | Meta+A lifts or drops the layer |

- The desk plays them, since it's the one drawing the events. Short OGG
  files in `desk/sounds/`, played through PipeWire.
- Settings: master on/off, master volume, and an on/off per sound, all in
  the settings page (with a play button to preview each); right-click a
  widget to mute just its sound.
- Bursts are coalesced: one sound of a kind per 150 ms at most, so sorting
  200 files is a short patter, not 200 clicks.
- **Quiet while a fullscreen window is focused** (a game), on by default and
  one switch to turn off. Her voice is unaffected.

## 3. The widgets (first set)

Each widget shows live state, offers a few direct controls for you, and
animates whenever she acts through its adapter.

| Widget | Shows | You can | She can (adapter verbs) |
|---|---|---|---|
| **Chat** | the conversation, her replies streaming, steps folding inline, the mic state | type; talk (hotkey or "hey Aries"); paste images | — (it's her voice) |
| **Spotify** | now playing: art, title, progress; queue; volume | play/pause, skip, scrub, like | `play(query)`, `pause`, `next`, `prev`, `volume(n)`, `queue(query)`, `like`, `playlist(name)` |
| **Steam** | recently played, downloads/updates in progress, what's running | launch, see install progress | `launch(game)`, `close(game)`, `install(game)`, `library(query)` |
| **Browser** | tabs, what's playing (YouTube or a show), episode | switch tab, play/pause | `open(url)`, `next_episode`, `fullscreen`, `read(tab)`, `close(tab)` |
| **Dolphin** | the folder you're in, recent folders and files, a drop zone | open, drop files on it | `open(path)`, `sort(folder)`, `move(a, b)`, `trash(path)` — every move animates in the widget |
| **Claude** | running Claude Code sessions and her hands: what each is doing, steps, time | stop one, open one | `start(task, folder)`, `status`, `stop` |
| **System** (small) | CPU, GPU, memory, disks (home and Olympus), volume | — | read-only |
| **Flows** | your flows, each with a one-line summary, on/off, last fired; rows light when one fires | toggle, run, open in the editor, new flow | `flow.*` (§10) |

Later candidates: a project widget (her task list while she builds), a
downloads widget. ("What she's watching for" is now the Flows widget.)

**Discord:** built in step 4, then removed at Ronald's request (2026-10-27).
The consent check for verbs that speak for him (`consent="message"`) stays in
the core for any future app that sends messages.

## 4. Architecture

Two processes, talking over one local socket.

```
┌────────────────────────────┐        ┌─────────────────────────────┐
│  core  (ariadne2.core)     │ events │  desk  (ariadne2.desk)      │
│  - conversation loop       │──────► │  - the desktop layer (GTK4) │
│  - adapters (apps)         │        │  - widgets + wires          │
│  - memory, voice, ears     │ ◄──────│  - your clicks/typing       │
└────────────────────────────┘ intents└─────────────────────────────┘
```

- **core** runs her: the model loop, the adapters, memory, the voice and the
  mic. It has no UI code. It can be restarted without the desk going blank
  (the desk shows "reconnecting").
- **desk** draws everything and holds no logic: it renders state and events
  from the core, and sends back what you did ("you pressed skip", "you typed
  this").
- **The desk's widgets are a web page** (`desk/web/`) inside a transparent
  WebKitGTK view on the GTK layer (decided 2026-10-27 after the flat GTK
  drawing looked poor): CSS does the acrylic-slab look and the working
  effect. `layer.py` forwards core messages into it and reports the widget
  rectangles back for the input region. Without a GPU in the container,
  anything animating costs CPU, so nothing redraws at rest, each wire has its
  own small canvas, and blend-mode effects exist only while a widget is
  being worked on. `bin/ariadne2` borrows the host's NVIDIA EGL driver so GTK
  composites on the GPU instead of llvmpipe, and the WebKit sandbox is allowed
  to read those driver files (idle ≈ 2% of a core; continuous demo ≈ 0.9 cores).
- **The socket** carries JSON lines: state snapshots per widget, action
  events (started, progress, done, failed — what drives the wires), chat
  deltas, and your input. One documented schema in `protocol.py`.

### Adapters

One file per app in `adapters/`. Each adapter:

- declares its **verbs**, with short descriptions and arguments. These become
  her tools, named `spotify.next`, `steam.launch` and so on.
- owns its **state** (polled or pushed) and publishes it for its widget.
- **emits action events** around every verb — that's what makes the widget
  animate and the wire pulse, with no extra work.
- declares its **events**: the things that happen in the app on their own
  (`spotify.track_changed`, `steam.download_done`, `browser.video_ended`), with typed
  fields. These are what flows start from (§10).
- talks to the app the most reliable way available: MPRIS/DBus or the Web
  API for Spotify, the `steam://` protocol plus local files for Steam, the
  browser's debugging port for tabs, KDE DBus for
  Dolphin, the CLI for Claude Code.

Adding an app means adding an adapter and a widget, and nothing else.

### Her tools

- The **adapter verbs** (a few per app).
- A small **general set**, carried over because they earned their place:
  shell (with the hard refusals and the background-launch fix), read, write
  and edit files, find/search files, web search (with the Claude fallback),
  read a page, screenshot/look at the screen, place a window, the fallback
  window control for apps with no other way in, open project, todo, hand off
  to a second hand.
- Three **flow** tools: `flow.nodes(query)`, `flow.save(graph)`,
  `flow.manage(id, op)` (§10).
- Target: **about 30 tools in total**, all offered every turn: small enough
  that per-message tool selection and its cache problems go away.

## 5. Conversation and prompt

- **One model** for conversation (Sonnet 5.5 by default, switchable), and one
  for work and hands (Opus 5.5). DeepSeek stays as a cheap option.
- **The prompt is rebuilt from scratch, and short:**
  1. Who she is: the personality file. **Default: Aries**
     (`personalities/aries.md`): she acts on anything that's part of what
     you already asked, and asks only about new directions, things that
     can't be undone, or a real two-way choice. Bright and Unleashed can
     be carried over as alternatives; one file each.
  2. How she works: about a page, written as **whole example exchanges**
     rather than rules (the lesson from the benches).
  3. The live state: a compact version of the current dashboard, built from
     the adapters' state rather than a separate scrape.
  4. Memory: the relevant facts and any genuinely matching old conversation.
- **Target:** under 4k tokens of prompt plus tools, down from about 16k.
- **Carried over:** streaming voice by sentence, the conversational wrap-up
  after work, the "said she'd do it" guard, per-model thinking switches, the
  promise and background-launch fixes.
- **Dropped:** the preflight block, mentions queue, curiosity, the inner
  layer, journal and episodes, and the long rulebook sections. Recipes and
  "watch for this" rules are replaced by flows (§10).

## 6. Memory

Two things, both plain files:

- **Facts about you** (`facts.jsonl`): dated records with their source,
  what replaced them, and why. Details below.
- **Old conversations:** the full transcript on disk, searched by meaning
  (≥ 0.45) when something you say refers back. Every line keeps its date,
  and anything recalled is framed as past ("on the 3rd you said…").

Both are read and edited in one Memory widget page, where you can see why
something was shown.

Cut: biography and self-beliefs, the case file, journal, episodes, summaries
of summaries, the nightly tidy beyond deduplication.

### Facts: dated, superseded, with reasons

Three ideas taken from DREAM (an event-aware memory graph for role-play
agents), minus its main purpose (stopping a character leaking future plot),
which an assistant doesn't have. Not a graph either: a flat store of records
whose links are just ids in fields.

```json
{"id": 41, "text": "uses Opera GX as his browser", "kind": "preference",
 "date": "2026-10-01", "source": "said in chat", "status": "current",
 "replaces": 17, "because": "Discord's web client works better in it",
 "rejected": []}
```

| Field | Meaning |
|---|---|
| `kind` | `preference`, `fact`, `plan`, `decision` or `event` (decides how it ages) |
| `date` | when it became true or was said; every record has one |
| `source` | where it came from: said in chat, seen in an app, inferred by her |
| `status` | `current`, `replaced` (see `replaced_by`) or `done` (a finished plan or past event) |
| `replaces` / `replaced_by` | the link both ways when something changed |
| `because` | why: "chose X because Y"; optional |
| `rejected` | for decisions: the options turned down, each with its reason |

**1. Time on everything.** Retrieval scores each record by relevance
(meaning ≥ 0.36 or word overlap ≥ 0.4, as now), then weights it by age:
events and plans fade over about a month, decisions more slowly, and
preferences and facts barely at all until something replaces them. A
recalled record shows its date, and old events and plans are worded as past
("three weeks ago you were working on the tea bench"), never as now.

**2. Superseded, not stacked.** When something changes (a tool switch, a new
plan, a corrected preference), the old record is marked `replaced` and
linked to the new one, so the two never sit side by side for retrieval to
pick at random. Replaced records are left out of normal recall and only
come back for history questions. How a replacement is spotted: when she
saves a fact, the closest existing ones (meaning ≥ 0.6) come back to her in
the tool result ("#17 'uses Firefox' (2026-09-02): same subject?"), and she
decides. That's cheaper and more reliable than a separate judging pass.

**3. Why, not just what.** `because` and `rejected` let her answer "why did
we do it this way?" by following the chain (Firefox → Opera GX on the 1st,
because of Discord's web client), and stop her re-suggesting an option
already turned down for a known reason: when a topic comes up, its
decision's rejected options come with it.

**Her tools:** `remember(text, kind, because?, replaces?, rejected?)`,
`forget(id)` and `recall(query, history?)`. Writing stays deliberate: she
saves what you'd expect a friend to remember, not every remark.

**From 1.x:** the facts come over with their dates and sources, marked
`current`; obvious duplicates are merged, and any pairs that contradict
each other are listed in the Memory page for you to settle, not guessed at.
The transcript comes over as it is.

## 7. Cut entirely

- The inner layer: mood, wants, the background thinker, "state of mind"
  blocks. Her voice's emotion comes from her own tags and nothing else.
- The city-skyline window and the old drawer/menu UI.
- Cat-speak and other accents as code paths (a personality can still write
  that way).
- Most of the 164 skills (Spotify's eight become one adapter, and so on).

## 8. Carried over from 1.x

| Part | Why it stays |
|---|---|
| Voice (Cartesia streaming, sentence chunking, emotion tags, named streams) | works, tuned |
| Ears (wake word, push-to-talk, the audio-footprint fixes, Bluetooth guard) | works, tuned |
| Recall (MiniLM index, measured thresholds) | the fixed version |
| KWin control (window list, placement, keep-below) | the desk needs it |
| Project mode, `edit_file`, todo | how she builds things |
| Web search with the Claude fallback, page reading | works |
| Safety: hard command refusals, credential guards, redaction | non-negotiable |
| The dashboard's sources | become adapter state |

Everything carried over is copied in and trimmed, not imported from 1.x.

## 9. Code shape

```
ariadne2/
  core/        loop.py  prompt.py  memory.py  voice/  ears/  tools.py  protocol.py
  core/flows/  graph.py  catalog.py  engine.py  store.py
  adapters/    spotify.py  steam.py  discord.py  browser.py  dolphin.py  claude.py  system.py
  desk/        layer.py  widgets/  wires.py  theme.py  sounds.py  hotkey.py
  desk/editor/ canvas.py  palette.py  inspector.py
  personalities/
  tests/       one per module; adapters tested against recorded app responses
docs/          DESIGN.md (this), PROTOCOL.md
```

Rules for staying revampable:

- No file over about 600 lines.
- The desk never imports core logic; the core never imports GTK.
- Every adapter has the same shape and can be tested without the app running.
- Comments say *why*, briefly.

## 10. Flows

Flows replace two 1.x things: **recipes** (hints from repeated requests) and
**"watch for this" rules** (a trigger plus a sentence for her to act on).
A flow is a small visual program, like an Unreal Blueprint: a **start node**
(something happens) wired to **checks** and **actions**. When the start
fires and the checks pass, the actions run.

```
 ┌─ Steam: game started ─┐     ┌─ Time between ─┐ true ┌─ Spotify: volume ─┐
 │                     ▶─┼────►│ 22:00 – 07:00  ├─────►│ level  20         │
 │ game ●                │     └────────────────┘      └───────────────────┘
 └───────────────────────┘
```

### What a flow is made of

- **Nodes** with **pins**. Like Blueprints there are two kinds of wire:
  - **Exec wires** (thick, red) say what happens next. A node runs when an
    exec wire reaches it.
  - **Data wires** (thin, coloured by type) carry values: the game that
    started, the DM text, the track title.
- **Types** are few: `text`, `number`, `yes/no`, `time`, `duration`, `path`,
  `list`, and app things that adapters define (`track`, `game`, `tab`,
  `message`, `session`). A data wire only connects matching types (any type
  goes into a `text` input, written out as text).
- An input with no wire takes a typed-in value on the node itself.

### Node types

**Starts** — one exec output, plus data outputs for what happened.

| Group | Nodes |
|---|---|
| Time | `At` (time of day, chosen days), `Every` (interval), `After` (once, after a delay) |
| App events | one per event an adapter declares: `Spotify: track changed`, `Steam: game started / closed / download done`, `Discord: DM / mention / someone joined voice`, `Browser: video ended / tab opened`, `Dolphin: file appeared in folder`, `Claude: hand finished`, `System: disk low` … |
| State | `Becomes` — any adapter state crossing a line ("GPU above 90%", "Spotify stops playing"), with a *for at least* hold so it doesn't flap |
| Desktop | `Window opened / closed / focused` (KWin), `Idle for`, `Back from idle`, `Ariadne started` |
| You | `You say` (a phrase in chat or voice), `Run button` (fires from the Flows widget, or "run <flow name>") |

**Checks** — decide whether and where to go on.

| Node | Does |
|---|---|
| `Branch` | yes/no in → *true* or *false* exec out |
| `Compare` | = ≠ < > *contains* *matches*, gives yes/no |
| `And`, `Or`, `Not` | combine yes/no |
| `Time between`, `Day is` | clock checks |
| `Read state` | any adapter state as a value: *what's playing*, *game running*, *focused window is fullscreen*, *free space* (one per state field the adapter declares) |
| `Cooldown` | passes at most once per duration |
| `Once per day` | passes the first time each day |
| `Settle` | waits until the start has stopped firing for a duration, then passes once (for downloads, bursts of files) |
| `Count` | passes when the start has fired N times within a duration |

**Actions** — do something; each has *done* and *failed* exec outputs.

| Group | Nodes |
|---|---|
| App verbs | one per adapter verb, inputs = its arguments: `Spotify: play / pause / next / volume / queue`, `Steam: launch / close`, `Discord: mute / join`, `Browser: open / close tab`, `Dolphin: move / sort / trash`, `Claude: start hand` … |
| General | `Move / copy file`, `Run command` (same hard refusals as her shell), `Place window`, `Notify` (a desktop toast) |
| Her | `Say` (she speaks a line), `Tell` (a line in chat), `Ask Aries` (hands her a sentence plus the wired-in values as one turn; outputs her reply as text), `Decide` (same, but she picks *yes/no* or one of named choices, each its own exec out) |
| You | `Ask Ronald` (a question in chat with buttons, one exec out per answer, and a *timed out* out) |

`Ask Aries` and `Decide` are the escape hatch for anything a graph can't say
("if this DM sounds urgent…"). They cost a model call, so they're drawn
in a different shade, and the Flows widget shows which flows use them.

**Flow control and data**

| Node | Does |
|---|---|
| `Sequence` | runs its outputs in order |
| `Wait` | pauses for a duration |
| `Wait for` | pauses until an event (with a timeout out) |
| `For each` | runs its body once per item in a list |
| `Run flow` | calls another flow and waits for it |
| `Stop` | ends this run |
| `Get / Set` | a variable kept by the flow between runs ("last game played") |
| `Text` | a template: "now playing {title} by {artist}" |
| `Math`, `List` | the small arithmetic and pick/filter you need |

That's about 40 built-in node types; every adapter adds its own events,
verbs and state reads automatically, with no flow code knowing about it.
It's the same rule as the widgets: **a new adapter means new nodes for
free**.

### How flows are built

**By you, in the editor.** Open the Flows widget → *new* or *open*. The
editor fills the raised layer (Meta+A style) as one large canvas:

- Pan with middle-drag, zoom with the wheel. Nodes are chamfered red cards;
  start nodes have a bright header, actions the normal one, `Ask Aries` a
  cyan-edged one.
- **Space** or right-click opens a search palette ("spot vol" finds
  `Spotify: volume`). **Drag out from a pin** and drop on empty space, and
  the palette shows only nodes that fit that pin, as in Blueprints.
- Inline fields for unwired inputs, comment boxes, undo, copy/paste.
- Problems show on the node as you work: a required input with nothing in
  it glows, a type mismatch won't connect.
- **Test** fires the start with the last real event it saw (or a sample) in
  *dry run*: wires animate and values appear on them, but actions only
  pretend.
- Save, and the toggle on the flow turns it on.

**By her, from conversation.** "Whenever a Steam download finishes, tell
me" is part of what you asked, so under Aries she just builds it:

1. `flow.nodes("steam download")` looks up the node types she needs — the
   catalog stays out of the prompt, so the 4k budget holds.
2. `flow.save(graph)` sends a compact JSON graph (nodes, links, values). The
   core checks it against the catalog; anything wrong comes back to her by
   name ("Tell.text needs a value") and she fixes it, at most twice.
3. The new flow appears in the Flows widget and draws itself node by node,
   so you see what she made. She says one line: "made a flow: when a Steam
   download finishes, I'll tell you."

- `flow.manage(id, op)` lists, explains, runs, turns on or off, edits and
  deletes. She edits your flows only when you ask.
- **Instead of recipes:** when you've asked for the same multi-step thing
  about three times, she offers once to make it a flow. That's a new
  direction, so under Aries it's a question, not an action.
- Every flow has a **one-line summary written from the graph itself**, not
  by the model ("When Steam starts a game → if 22:00–07:00 → Spotify volume
  20"), so it's always true to what the flow does.

### How they run in the core

- **Events.** Adapters already publish state and action events for the
  desk; they now also publish their declared events on one in-process bus.
  The engine subscribes once and keeps an index from event name to the
  start nodes that want it, so an event only touches the flows that care.
- **Time** starts sit in one scheduler (a single timer to the next due
  time), not a polling tick. `Becomes` starts compare each new state
  snapshot with the last one. Polling only happens inside adapters that
  have no push, at their own rate.
- **A run** is one firing: it walks the exec wires from the start, pulls
  data inputs on demand from the nodes wired into them (as Blueprints do),
  and awaits each action. `Wait`, `Wait for` and `Ask Ronald` pause the run;
  paused runs are saved, so a restart resumes them.
- **If a flow fires while it's still running**, its mode decides: *ignore*
  the new one (default), *restart*, *queue*, or run *in parallel*.
- **Failures** follow the action's *failed* wire if there is one. Otherwise
  the run stops, the flow's row goes red with the reason, and she mentions
  it once — not on every repeat.
- **Loops.** Flows' own actions cause events (`Spotify: next` causes
  *track changed*). Each event carries what caused it; a flow can't
  retrigger itself from its own action, chains stop at depth 3, and a flow
  that fires more than 6 times a minute pauses itself and tells you.
- **Safety.** Flow actions go through the same tool layer as her own calls:
  hard refusals, credential guards and redaction all apply.
  - Verbs that can't be undone or that speak for you (`trash`, `close
    game`, `run command`, sending a message) are marked in their adapter.
  - A flow **she** built that uses one of them is saved **off**, with an
    *Approve* button that shows you the graph. Flows you build are trusted.
  - A flow started by **outside content** (a DM, a page, a file's name)
    can't reach a marked verb without an `Ask Ronald` node in front of it;
    saving refuses otherwise. Message text reaching `Ask Aries` arrives
    quoted, as data.
- **Storage.** One JSON file per flow in `~/.local/share/ariadne2/flows/`
  (readable, diffable), plus the last 50 runs per flow: what fired it, the
  path taken, values, time, result.
- **1.x import.** Each 1.x watch rule becomes a flow: its trigger as the
  start node and its sentence as an `Ask Aries` node, which is exactly what
  it was. Recipes aren't imported; they were hints, not programs.

### How they show in the widgets

- **Flows widget:** a row per flow: name, the one-line summary, on/off,
  "fired 2 h ago", and a small glyph if it uses `Ask Aries`. A row flares
  when its flow fires; a *Run* button on manual ones; *open* takes you to
  the editor.
- **On the wires:** a firing flow sends a packet from the widget where the
  trigger happened, up to the core (whose action line reads "flow: late
  gaming"), then out to each widget it acts in, with the usual flash on the
  control used. The `flow` sound plays once.
- **On the widgets they watch:** a small flow mark in the corner of a
  widget, or next to the item inside it (the Downloads folder in Dolphin,
  a game in Steam), shows something is watching it. Click it to open that
  flow.
- **In chat:** a flow that acts leaves one folded line ("late gaming:
  volume to 20"). It only speaks if it has a `Say` node.
- **In the editor, live:** with a flow open, each real run lights its
  nodes and wires in turn and shows the values on the wires, so you can
  watch it work and see where it stopped.

The protocol gains: the flow list snapshot, run events (*started*, *node
entered*, *node done*, *finished*, *failed*), the node catalog with types
(so the editor can show only fitting nodes), and your edits (save, test,
toggle). The desk still holds no logic: the core checks and saves every
graph.

## 11. Build order

1. **Skeleton** — *done 2026-10-27:* core and desk processes, the socket protocol, the
   transparent layer pinned below windows on the ultrawide with the
   wallpaper showing through, the theme, the starting layout with drag by
   header, Meta+A to raise and drop. Run it with `bin/ariadne2 --demo`
   (fake actions every 4 s, so the wires animate).
2. **Chat + core widget** — *built 2026-10-27, awaiting Ronald's first try:*
   conversation streaming in the chat widget, her mark, voice and mic
   carried over, the Aries personality, the sound player. At this point 2.0
   can replace 1.x day to day for talking. (The core borrows 1.x's venv for
   faster-whisper/CUDA until 2.0 gets its own; push-to-talk has no hotkey yet.)
3. **Spotify end to end** — *built 2026-10-27, awaiting Ronald's try:* adapter (verbs, events, state), widget, wire
   animation, its sounds. **Ronald tries the "watch her do it" feel here
   before the rest is built.**
4. Steam, browser, Discord — *built 2026-10-27; Steam and browser kept,
   Discord removed at Ronald's request.*
5. **Flows** — *built 2026-10-27, awaiting Ronald's try:* engine, store, the Flows widget, her building flows from
   conversation, the 1.x watch import, trigger packets on the wires.
6. Dolphin, Claude, system.
7. The flow editor.
8. Memory page, settings (sound switches among them), edit mode; then
   retire 1.x.

## 12. Decisions

Ronald's answers, 2026-10-27:

1. **Layout:** proposed starting layout in §2, draggable.
2. **Hotkey:** Meta+A raises the layer; again, Esc, or a click away drops
   it (§2).
3. **Wallpaper:** Waywallen shows through; the layer has no background.
4. **Sounds:** small effects when she acts, each mutable, plus a master
   switch (§2).
5. **Personality:** Aries is the default (§5).
6. **Discord:** reading DMs through the browser login was approved; the Discord
   widget was later removed at his request (§3).
7. **Flows** replace recipes and watch rules (§10).

Still open, none blocking step 1:

- Should she ever raise the layer herself, e.g. when a flow's `Ask Ronald`
  needs an answer while a game is fullscreen? Proposed: no — she says it
  aloud and the question waits in chat.
