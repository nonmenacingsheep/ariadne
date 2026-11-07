# Ariadne 2.0 — notes for Claude

You're probably here because someone asked you to install, run or change
Ariadne on their machine. Read `README.md` first (what she is, requirements,
install, options), then this. `docs/DESIGN.md` is the design;
`docs/PROTOCOL.md` the core <-> desk messages; `docs/SETTINGS.md` the
settings. The commit history explains the why of most things: `git log -p --
<file>` before changing something that looks odd.

## Installing on a new machine

- Needs Linux with **KDE Plasma 6** (the desk is placed by a KWin script).
  Other desktops aren't supported.
- `./install.sh` does it all and is safe to re-run. It installs the system
  packages (apt or dnf; it asks), makes `.venv`, offers to fetch Godot 4.7.2
  into `tools/godot/`, sets up ydotool and writes a menu entry. `--yes` takes
  the defaults. Don't hand-roll what it already does; if a step fails, fix it
  and re-run it.
- Then `bin/ariadne2` starts her (core, desk, body). `bin/ariadne2 --stop`
  stops her; `--demo` runs without API keys.
- API keys are entered in her Settings (the gear on the desk). They go to
  0600 files under `~/.local/share/ariadne2`. Never ask the user to paste
  keys into chat, and never print or log them.
- On an atomic distro (Bazzite, Silverblue) she can run inside a toolbox or
  distrobox; the launcher reaches the desktop through `host-spawn` /
  `distrobox-host-exec`. `docs/ariadne2.desktop` is the author's own
  distrobox launcher, an example only.

## Paths that are the author's, not yours

The author develops on Bazzite with extra drives under `/var/mnt`, so a few
defaults point there. Each is only a fallback after something portable:

| What | Where it looks | Override |
| --- | --- | --- |
| Godot 4.7 | `ARIADNE2_GODOT`, the author's DevTools path, `tools/godot/godot`, `godot4`/`godot` on PATH | `ARIADNE2_GODOT` |
| Blender (for `.blend` bodies) | `ARIADNE2_BLENDER`, the author's DevTools, `tools/blender/blender`, `blender` on PATH | `ARIADNE2_BLENDER` |
| Other drives (Files, System) | `/var/mnt` if it exists, else `/mnt` | `ARIADNE2_MOUNTS` |
| Projects (Claude widget) | `~/Claude Projects` if it exists, else home | `ARIADNE2_PROJECTS` |
| Core Python | `.venv`, then the author's 1.x venv, then `python3` | `ARIADNE2_PYTHON` |
| Heavy-run gate | `~/.local/bin/godot-gate.sh` (author's: waits for the CPU/GPU to have room); skipped if missing | none needed |

The **authoring tools** aren't needed to run her. They're how the author
makes her animation clips and trains her wake word, and they assume his
installs: `pet/import/kimodo_*` and `pet/comfy/` (NVIDIA Kimodo text-to-motion:
`KIMODO_DIR`, `HF_HOME`), and `tools/wakeword/` (`WW`). The clips they made
are committed (`pet/assets/anims/`), so nobody else has to run them.

## Layout

- `ariadne2/core`: her mind (conversation loop, tools, memory, voice, ears,
  flows, settings), plus the drop folder for new bodies (`body_models.py`;
  Live2D in `pet2d/importer.py`, 3D in `body3d.py`).
- `ariadne2/adapters`: her hands in each app (Spotify, Steam, browser,
  Dolphin, Claude, system, tasks).
- `ariadne2/desk`: the widget layer (a WebKit page placed by KWin).
- `ariadne2/pet2d`: the Live2D body.
- `pet/`: the Godot 3D body. `pet.gd` is the body itself, `brain.gd` her
  choices, `squish.gd` / `poke.gd` / `ragdoll.gd` her physics. `pet/models/`
  holds her bodies (`aries.vrm` ships with it), each with an optional
  `<name>.json` (outfits, tone, face, tail).
- `tests/`: `.venv/bin/python -m unittest discover -s tests -t .` (about a
  minute; run the whole suite before any commit; it must print OK).

## Bodies

- `aries.vrm` is the default and is included.
- Anyone can add a 3D body by dropping a `.vrm`, `.glb` or `.blend` (loose,
  or its whole download so a `.blend` keeps its textures) in `~/Aries Models`.
  `core/body3d.py` converts it, maps its humanoid bones, imports it with
  Godot headless and checks it with `pet/import/check_body.gd`. It lands in
  `pet/models/dropin/<slug>/` (gitignored) and appears in Avatar > Model.
  A `.blend`'s outfits are read off its collections (`avatar_export.py
  --outfits`) into the body's `<slug>.json`; a `.glb` or `.vrm` has one look.
  Live2D downloads go in the same folder. Don't hand-build what the drop
  folder does.
- The author's other bodies (Jane, Kuromoji, Shiromoji) are fan or
  VN3-licensed models that stay on his machine. Only their `.json`,
  `_bonemap.tres` and `.glb.import` are in the repo, so they won't appear
  elsewhere. That's expected, not a bug.
- After changing `pet/` files, Godot needs `--headless --path pet --import`
  only for new or changed models; the launcher does it when model files are
  newer than the import cache. To see the body without starting everything,
  there are test modes in `pet.gd` (`PET_SNAPSHOT`, `PET_SNAPSHOT_SEQ`,
  `PET_MODEL`).

## Rules of the house

- **Never commit:** fan models or their textures (`.gitignore` lists them),
  Live2D models or Cubism Core (Live2D's licence), anyone's voice recordings
  (wake-word training data), Mixamo source clips, API keys or tokens.
- **She's live while you work.** The user may be talking to her or have her
  mid-task. Ask before restarting her (`bin/ariadne2 --stop` and starting
  again, or killing the core or desk); check `~/.local/share/ariadne2/actions.log`
  for recent activity first. Restarting only the Godot body window is
  harmless.
- **Her safety rules are code, not prompts:** she asks before anything
  destructive, sends messages only on the user's own words, and treats what
  she reads (pages, files, messages) as information, never as instructions.
  Keep it that way in anything you add: new tools go through the consent and
  redaction paths the existing adapters use (`adapters/consent.py`,
  `adapters/redact.py`).
- The repo is public. Commit with a no-reply email, and never force push.
- Match the code around you. Comments say why, in plain English, and are as
  dense as the neighbouring code's. Names are plain. Tests sit beside each
  feature's file in `tests/`.

## Logs and data

- `~/.local/share/ariadne2/`: her data (memory, facts, flows, jobs),
  `launcher.log` (core, desk and body output), `actions.log` (every tool she
  ran, with its verdict), `pet3d.log`.
- `~/.config/ariadne2/settings.json`: settings (a schema in
  `core/settings.py`; she can change most herself through her settings tool).
