# Settings

The backend is `ariadne2/core/settings.py`; the store is `~/.config/ariadne2/settings.json`
(override with `ARIADNE2_SETTINGS`). The desk draws the page from the schema the core sends
(`settings` message, PROTOCOL.md) and sends `set` back. The core validates, saves atomically,
applies the change to the running parts, and re-sends `settings`.

The file is `{section: {key: value}}` with **every** key written, so the pet and the desk can read
their part without knowing the defaults (still keep a fallback for a missing file). Buttons
(`action`) and read-only shortcut displays are not stored.

## 1.x inventory

What the old app's settings drawer (gui.py `_page_settings`, five sections) offered, and where it went.

### General (1.x)

| Label | What it did | 2.0 |
|---|---|---|
| Name | what she's called (also her wake word) | **carried** as General "Wake phrase" |
| Icon | the app icon in the grid, tray and browser extension | dropped: no tray or app-icon swapping in 2.0 |
| Actions look / ask / auto | how freely her tools act | dropped: 2.0 has no global mode; sending as him and spending Claude usage need his own words that turn (adapters/consent.py), and writes outside a few folders are refused |
| Home only | confine reading to the home directory | dropped: path limits are fixed in core/tools/common.py |
| Quick replies | thinking off before answering | dropped: always on, per-model, in models.py |
| Catgirl accent | cat-speak on top of any personality | dropped: it is a personality file now (the Personality choice) |
| Closing the window quits | close button hides or quits | dropped: the desk is a layer with no window to close |
| Safe search | filter on her web searches | dropped: 2.0's search is Anthropic's search tool, which has no filter to set |
| When she's done working | conversational or chatty | dropped: 2.0 folds steps into the chat one way |
| When she goes quiet to work | her own words / stock lines / nothing | dropped: a prompt matter in the personality, not a switch |
| Inner layer | background thinking | dropped: the inner layer is cut from 2.0 (DESIGN section 7) |
| Human mode | | excluded by Ronald |
| Think it through first | | excluded |
| Curiosity, cents a day | | excluded |
| Draft skills on her own time | | excluded |

### Models (1.x)

| Label | What it did | 2.0 |
|---|---|---|
| Conversation tier | model she talks with | **carried** as "Conversation model" (Sonnet 5.5 default, Opus 5.5, DeepSeek Flash, DeepSeek V4 Pro) |
| Work tier | model that drives skills | dropped: one loop, no separate work tier |
| Inner tier | background model | dropped with the inner layer |
| Model for clicking in windows | model that looks at a window and picks the click | **carried** as "Window-control model"; the "her tiers" option is dropped with the tiers |
| Her brain | Ariadne or Claude Code | excluded |

### Voice (1.x)

| Label | What it did | 2.0 |
|---|---|---|
| Chime | which style of listening/sent chime | dropped: the desk's synthesised sound effects (the `mic` sound) replace it |
| Use the cloud voice | Cartesia instead of local Kokoro | dropped: 2.0 is Cartesia only |
| Voice field and Set up voice | voice name; download Kokoro | voice **carried** as "Voice"; the install button is dropped (no local engine) |
| Her delivery | pin a Cartesia emotion | excluded |
| She colours her own voice | marks versus mood | dropped: marks `((calm))` are always honoured; there is no mood layer |
| Read replies aloud | | excluded (speaking always happens) |
| (not in the drawer) speed | `voice_speed` in 1.x memory | **carried** as "Speed" |

### Ears (1.x), all moved into General

| Label | What it did | 2.0 |
|---|---|---|
| Listen for her name | hold the mic open for the wake word | **carried** as General "Listen for her name" |
| Set up listening | install faster-whisper | dropped: an install step, not a preference |
| Heard lately | live view of what the mic heard | dropped: diagnostics, not a setting (the log has it) |
| (the wake phrase, from Name) | "hey <name>" | **carried** as General "Wake phrase" |
| (push-to-talk, from Desktop's hotkey) | | **carried** as General "Push-to-talk key" (display only) |
| (new) Microphone | which capture device | new: General "Microphone" |

### Desktop (1.x)

| Label | What it did | 2.0 |
|---|---|---|
| Start when I log in | autostart | **carried** as "Start when I log in" (writes `~/.config/autostart/ariadne2.desktop`) |
| Hide at the screen edge | edge dock | excluded |
| (hotkey line) | shows the global shortcut | **carried** as "Raise hotkey" (display only) |
| Let her glance at the screen | gate for screen watches | dropped: she looks only when a tool call asks, in his turn |
| The city | Night City backdrop | excluded |
| Tell her what I'm looking at | focused window as context | dropped: not a 2.0 feature yet; add the switch when it exists |
| Keep the orb on the desktop | | excluded |

### Not in the five sections (Accounts page)

API keys and workspace id, Google client and sign-in, Spotify sign-in, ntfy topic, browser panel and
token. Not part of this settings store: keys stay in their own `0600` files under `~/.local/share/ariadne/`
(secrets never go in `settings.json`), and per-app sign-ins belong to their adapters. The ntfy topic and
the browser panel are 1.x-only features.

## 2.0 settings

Types: `bool`, `choice` (`options: [{value, label}]`), `number` (`min`, `max`, `step`, optional `unit`),
`text`, `key` (a shortcut shown, `readonly`, rebound in System Settings, Shortcuts). `action` marks a
button: send `set` with `true`; nothing is stored.

### general

| key | type | default | what it does / applies to |
|---|---|---|---|
| `personality` | choice (files in `personalities/`) | `aries` | `Conversation.personality`, from the next turn |
| `wake_word` | bool | true | `Ears.set_wake_word`: hold the mic open for the phrase |
| `wake_phrase` | text | `hey Aries` | greeting + her name; stored normalised to `hey <name>`; `Ears.set_name(name)` |
| `ptt_key` | key, readonly | `Meta+S` | display only |
| `mic` | text | `` | capture device from `pactl list short sources`; blank is the system default; `Ears.set_mic` reopens the recorder |

### models

| key | type | default | applies to |
|---|---|---|---|
| `conversation_model` | choice | `claude-sonnet-5-5` | `Conversation.model_name`, next turn. Options: `claude-sonnet-5-5`, `claude-opus-5-5`, `deepseek-flash`, `deepseek-v4-pro` |
| `eyes_model` | choice | `claude-sonnet-5-5` | `tools.operate.EYES["model"]` (the `ARIADNE2_EYES` env var still outranks it). Options: sonnet, `claude-haiku-5-5`, opus, `deepseek-flash` |

### voice

| key | type | default | applies to |
|---|---|---|---|
| `voice` | text | `skylar` | `Voice.voice`; a Cartesia id or a known name |
| `speed` | number 0.6 to 1.5, step 0.05 | 1.0 | `Voice.speed` |
| `volume` | number 0 to 100 (%) | 100 | `Voice.volume` (gain on the samples, never above 1) |
| `sounds_master` | bool | true | the desk's sound effects |
| `sounds_volume` | number 0 to 100 (%) | 50 | sound effects volume |
| `sound_<kind>` | bool, one each | true | false mutes that kind. Kinds: `send done fail flow spotify steam browser dolphin claude mic raise drop` |

For the page: `settings.sounds_config(values)` gives `{master, volume: 0-1, muted: [kinds]}`, the shape
`Sounds.configure` takes. `desk/layer.py` already calls `desk.configureSounds(...)` with it on every
`settings` message, so the page needs no mapping of its own; it can also read `values.voice.*` directly.
A right-click mute on a widget is `set voice sound_<kind> false`.

### desktop

| key | type | default | applies to |
|---|---|---|---|
| `raise_key` | key, readonly | `Meta+A` | display only |
| `reset_layout` | bool, action | | the desk resets the layout when it forwards `set desktop reset_layout true` (layer.py `_reset_layout`); the core acknowledges and re-sends `settings` |
| `body` | bool | true | **pet reads it**: false hides or quits her body |
| `quiet_fullscreen` | bool | true | **page reads it**: no sound effects while a fullscreen window is focused (voice unaffected) |
| `autostart` | bool | false | writes or removes `~/.config/autostart/ariadne2.desktop` (not run at startup) |

### avatar (the pet reads these)

The pet polls the mtime of `settings.json` and re-reads `avatar` (plus `desktop.body`). Every key is
always present in the file; clamp to the ranges anyway.

| key | type | range / default | meaning |
|---|---|---|---|
| `energy_drain` | number | 0.25 to 4, default 1 | multiplier on energy loss while awake (life.gd: 0.009 per minute at 1) |
| `fun_drain` | number | 0.25 to 4, default 1 | multiplier on boredom (0.012 per minute at 1) |
| `affection_drain` | number | 0.25 to 4, default 1 | multiplier on affection loss (0.007 per minute at 1) |
| `hunger_drain` | number | 0.25 to 4, default 1 | multiplier on the new hunger need's drain; the base rate is life.gd's to choose |
| `size` | number, int | 200 to 420, default 300 | `PPM`, screen pixels per metre |
| `fps_cap` | number, int | 10 to 60, default 30 | `FPS_BUSY`; idle is `min(FPS_IDLE, cap)` |
| `sleep_after` | number, int minutes | 1 to 120, default 8 | `SLEEP_AFTER` is `minutes * 60` s of nothing before she dozes |
| `wander` | bool | true | walks about on her own |
| `sit_on_widgets` | bool | true | perches on widget edges |
| `walk_off_edges` | bool | true | steps off a widget and drops; false turns back at the edge |
| `dance_to_music` | bool | true | dances when Spotify plays (`wish()` "dance") |
| `play_ball` | bool | true | fetches the ball on her own (`wish()` "ball"); the ring item still works |
| `nap` | bool | true | may fall asleep from tiredness or `sleep_after` |
| `seek_cursor` | bool | true | comes to the cursor when lonely (`wish()` "find_him") |
| `react_to_work` | bool | true | shows the glowing slab while she works |
| `lip_sync` | bool | true | shapes her mouth to the vowels of `speak` |

## Interpreted

- "Wake phrase" is the name: 1.x's wake phrase was always "hey <name>", so one text field takes a
  greeting plus a name and the greeting is normalised to "hey".
- "Push-to-talk key display" and "raise hotkey shown" are read-only `key` rows; KWin owns the bindings.
- "Layout reset" is a momentary button (`action`) the desk performs; the core only acknowledges.
- Sound effects live in the Voice section, one `sound_<kind>` switch per kind, volume in percent
  (the old `sounds.json` stored 0 to 1; it is migrated once to `sounds.json.migrated`).
- Voice volume is a gain at or below 1, applied to the samples before they reach the player.
- "Nap" and `sleep_after` are separate: nap off means she never sleeps; `sleep_after` is how long she
  waits when it is on.
- `--model` and `--personality` on the command line still win over the file for that run.
