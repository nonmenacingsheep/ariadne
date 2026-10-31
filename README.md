# Ariadne

**Aries**, a desktop companion for KDE Plasma. Red acrylic widgets live on your
desktop behind your windows, wired to her core: Spotify, Steam, your browser,
your files (Dolphin), your Claude Code sessions, system stats and running apps.
You talk to her by typing or by voice. She can do things in those apps, build
automations ("flows") out of nodes, remember what matters, and wander your
desktop as a 3D (VRoid) or Live2D body that you can pick up and throw.

## Requirements

- **Linux with KDE Plasma 6** (Wayland or X11). The desk is placed by a KWin
  script, so other desktops won't work.
- **Python 3.10+**, **GTK 4** and **WebKitGTK 6** with their Python bindings,
  `pactl`/`parec` (PipeWire or PulseAudio), and `git`. The installer checks
  these and offers the right install command for apt, dnf, pacman or zypper.
- An **Anthropic API key** for her brain. Optional: a **Cartesia** key for her
  voice, a **DeepSeek** key for cheaper models.
- Optional: an NVIDIA GPU for faster, more accurate speech recognition;
  [Claude Code](https://claude.com/claude-code) for the Claude widget;
  [Godot 4](https://godotengine.org) and a VRoid `.vrm` model for the 3D body,
  or a Live2D model for the 2D one.

## Install

```bash
git clone https://github.com/nonmenacingsheep/ariadne.git
cd ariadne
./install.sh
```

The installer is safe to run again. It:

1. checks the system packages (and offers to install missing ones),
2. makes a Python environment in `.venv` and installs `requirements.txt`
   (plus the CUDA libraries if you have an NVIDIA GPU and want them),
3. downloads the small model her memory search uses (MiniLM, 23 MB),
4. asks for your API keys and stores them in `~/.local/share/ariadne2/`, readable only by you,
5. optionally sets up her body: a VRoid `.vrm` for the 3D one, or a Live2D
   model (this downloads Live2D's Cubism Core, which is under
   [Live2D's own licence](https://www.live2d.com/eula/live2d-proprietary-software-license-agreement_en.html)
   and isn't included here),
6. adds **Ariadne** to your app menu.

`./install.sh --yes` takes the defaults without asking (no keys, no Live2D);
keys can also come from `ANTHROPIC_API_KEY`, `CARTESIA_API_KEY` and `DEEPSEEK_API_KEY`.

## Use

Start **Ariadne** from the app menu, or run `bin/ariadne2` (`bin/ariadne2 --stop` closes it).

- **Meta+A** lifts the desk over your windows; click empty space or press Esc to drop it.
- **"Hey Aries, …"** talks to her; **Meta+S** is push-to-talk (press, speak, press).
- The **gear** at the top left of her core opens the settings; the line under
  ARIES opens the widget drawer (the Avatar widget is in there).
- Right-click a file in the Files widget to ask her about it.

She asks before anything destructive, never sends a message unless your own
words that turn ask for it and name who it's for, and treats what she reads
on web pages, in files or in messages as information, never as instructions.

## Updates

Ariadne checks GitHub every few hours and updates herself; a **Restart to
update** chip appears on her core. It only ever fast-forwards: local edits or
commits are left alone. Turn it off under Settings > General.

## Options

| Variable | What it does |
| --- | --- |
| `ARIADNE2_OUTPUT` | The monitor to live on, by KWin's name (e.g. `DP-2`). Default: the biggest. |
| `ARIADNE2_PYTHON` | The Python for the core. Default: `.venv`. |
| `ARIADNE2_GODOT` | The Godot 4 binary for the 3D body. Default: `godot4` / `godot` on your PATH. |
| `ARIADNE2_NO_PET=1` | Start without a body. |

## Layout

`ariadne2/core` is her mind (conversation loop, tools, memory, voice, ears,
flows), `ariadne2/adapters` her hands in each app, `ariadne2/desk` the widget
layer, `ariadne2/pet2d` the Live2D body, `pet/` the Godot 3D body,
`docs/DESIGN.md` the design. Tests: `.venv/bin/python -m unittest discover -s tests -t .`
