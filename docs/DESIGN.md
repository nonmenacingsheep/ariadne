# Ariadne 2.0 — design

Status: draft for Ronald to mark up (2026-10-26). Nothing is built yet.

## 1. What it is

Ariadne 2.0 is Aries's playground: a live layer on the ultrawide desktop where
her widgets show the apps she runs for you — Spotify, Steam, Discord, the
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
- **Seamless control.** "Skip this", "launch Elden Ring", "mute me on Discord"
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
  - Why one layer rather than separate KDE widgets: the wires between widgets
    have to be drawn across the gaps between them, which needs one canvas.
    It also lets widgets move freely, overlap and animate together.
  - Clicks on empty parts of the layer pass through to the wallpaper (an
    input region covering only the widgets).
- **Widgets are draggable and resizable**, and snap to a soft grid. Their
  layout is saved.
- An **edit mode** (hotkey) shows the grid, lets you add or remove widgets,
  and shows where the wires run.

### Visual language — red cyberpunk

Taken from the mock, then made to feel like one piece:

- **Ground:** near-black (#0b0708) with a faint dark-red marble/circuit
  texture; your wallpaper shows through wherever there's no widget.
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

## 3. The widgets (first set)

Each widget shows live state, offers a few direct controls for you, and
animates whenever she acts through its adapter.

| Widget | Shows | You can | She can (adapter verbs) |
|---|---|---|---|
| **Chat** | the conversation, her replies streaming, steps folding inline, the mic state | type; talk (hotkey or "hey Aries"); paste images | — (it's her voice) |
| **Spotify** | now playing: art, title, progress; queue; volume | play/pause, skip, scrub, like | `play(query)`, `pause`, `next`, `prev`, `volume(n)`, `queue(query)`, `like`, `playlist(name)` |
| **Steam** | recently played, downloads/updates in progress, what's running | launch, see install progress | `launch(game)`, `close(game)`, `install(game)`, `library(query)` |
| **Discord** | who's in voice, unread DMs/mentions count, mute/deafen | mute, deafen | `mute`, `deafen`, `join(channel)`, `read(dm)` (through the browser login) |
| **Browser** | tabs, what's playing (YouTube or a show), episode | switch tab, play/pause | `open(url)`, `next_episode`, `fullscreen`, `read(tab)`, `close(tab)` |
| **Dolphin** | the folder you're in, recent folders and files, a drop zone | open, drop files on it | `open(path)`, `sort(folder)`, `move(a, b)`, `trash(path)` — every move animates in the widget |
| **Claude** | running Claude Code sessions and her hands: what each is doing, steps, time | stop one, open one | `start(task, folder)`, `status`, `stop` |
| **System** (small) | CPU, GPU, memory, disks (home and Olympus), volume | — | read-only |

Later candidates: a project widget (her task list while she builds), a
"what she's watching for" widget (rules and reminders), a downloads widget.

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
- talks to the app the most reliable way available: MPRIS/DBus or the Web
  API for Spotify, the `steam://` protocol plus local files for Steam, the
  browser's debugging port for tabs and Discord's web client, KDE DBus for
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
- Target: **about 30 tools in total**, all offered every turn: small enough
  that per-message tool selection and its cache problems go away.

## 5. Conversation and prompt

- **One model** for conversation (Sonnet 5.5 by default, switchable), and one
  for work and hands (Opus 5.5). DeepSeek stays as a cheap option.
- **The prompt is rebuilt from scratch, and short:**
  1. Who she is: the personality file (Bright, Unleashed or others; one file).
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
  layer, journal and episodes, recipes, and the long rulebook sections.

## 6. Memory

Two things, both plain files:

- **Facts about you:** one line each, dated, superseded rather than
  duplicated, picked each turn by relevance (meaning ≥ 0.36 or word overlap
  ≥ 0.4) plus the newest few.
- **Old conversations:** the full transcript on disk, searched by meaning
  (≥ 0.45) when something you say refers back.

Both are read and edited in one Memory widget page, where you can see why
something was shown. The facts and transcript come over from 1.x as they are.

Cut: biography and self-beliefs, the case file, journal, episodes, summaries
of summaries, the nightly tidy beyond deduplication.

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
  adapters/    spotify.py  steam.py  discord.py  browser.py  dolphin.py  claude.py  system.py
  desk/        layer.py  widgets/  wires.py  theme.py
  personalities/
  tests/       one per module; adapters tested against recorded app responses
docs/          DESIGN.md (this), PROTOCOL.md
```

Rules for staying revampable:

- No file over about 600 lines.
- The desk never imports core logic; the core never imports GTK.
- Every adapter has the same shape and can be tested without the app running.
- Comments say *why*, briefly.

## 10. Build order

1. **Skeleton:** core and desk processes, the socket protocol, the
   transparent layer pinned below windows on the ultrawide, the theme.
2. **Chat + core widget:** conversation streaming in the chat widget, her
   mark, voice and mic carried over. At this point 2.0 can replace 1.x day to
   day for talking.
3. **Spotify end to end:** adapter, widget, wire animation. **Ronald tries
   the "watch her do it" feel here before the rest is built.**
4. Steam, browser, Discord.
5. Dolphin, Claude, system.
6. Memory page, settings, edit mode; then retire 1.x.

## 11. Open questions for Ronald

1. **Starting layout:** do you have a picture of where widgets sit on the
   ultrawide, e.g. chat bottom-left, Spotify top-right? Or should I propose a
   starting layout for you to drag around?
2. **Behind your windows only?** The layer sits below your apps, so it's
   hidden whenever something is maximised. Should a hotkey bring it to the
   front temporarily ("show me Aries"), or a gesture like moving the cursor
   into a corner?
3. **The wallpaper:** keep your current Waywallen wallpaper showing through,
   or should the layer have its own dark-red background?
4. **Sound design:** should the wires and widgets make small sounds when she
   acts (soft ticks, data chirps), or stay silent apart from her voice and the
   chime?
5. **Personality:** which personality is the default for 2.0: Unleashed,
   Bright, or a new one written for it?
6. **Discord:** is reading DMs and mentions through your browser's Discord
   login okay, given that she'd see your messages?
