# Jane Doe 3D body: plan

Goal: the [ZZZ] Jane Doe Blender model as her 3D desktop body, fleshed out and
dynamic: a GASP-like set of animation states she moves between on her own,
with motion made by NVIDIA's MotionBricks and Kimodo.

The model is a fan model of a game character: it stays on this machine, in
the drop folder / pet/models, and is never committed or bundled (same rule as
the Live2D Jane). Friends bring their own.

## What we have

- `/var/mnt/games/OlympusDownloads/_ZZZ__JaneDoe_Basic_b1.0/[ZZZ]_JaneDoe.blend`
  (and .pmx copies). MMD rig, 185 bones (Center, Groove, Waist, Spine, Chest,
  Neck, Head, arms, legs + D bones), 55 secondary bones (hair, ponytail, tail,
  ears), ~45k tris in 16 meshes, toon materials, 79 face shape keys (brows,
  eyes, pupils incl. hearts, mouth), clothing layers as separate meshes, a
  weapon on its own 3-bone rig. No animations.
- The 3D body today: Godot 4.7 (pet/), loads `pet/models/aries.vrm` through
  the VRM addon (spring bones, expressions, MToon), Quaternius clips
  retargeted by Godot's BoneMap.
- MotionBricks (NVlabs/motionbricks): real-time neural motion on the SOMA
  skeleton, 30 Hz, from the last 4 poses + 1-4 target poses; walk/run/strafe/
  crouch + 6 styles in its scene preview. Python + TensorRT, NVIDIA GPU.
  Code Apache-2.0, weights NVIDIA Open Model Agreement (commercial OK);
  sample motions are evaluation-only; no retargeting to other rigs built in.
- Kimodo (NVIDIA): text-to-motion on SOMA ("she stretches, then sits
  cross-legged"), exports BVH; has ComfyUI nodes (ComfyUI is installed).

## Decisions (Ronald, 2026-11-02)

- GASP-like, from baked clips. Running MotionBricks live is too expensive:
  it and Kimodo only generate clips here, offline.
- Idle life first (many idles per mood, stretches, yawns, looking around,
  sitting on widget edges, lying down, napping, dancing); getting around
  after.

## Approach

1. **Bake, don't stream.** Kimodo and MotionBricks generate clips on this PC;
   they're retargeted SOMA -> Jane in Blender and baked into a Godot
   animation library. Her body plays and blends them in real time with no
   model running, so it costs nothing while she idles, and works on a
   friend's PC with any GPU.
2. **States, GASP-style.** A state graph of locomotion (idle, walk, run,
   start, stop, turn-in-place), stances (stand, sit on a widget edge, lie,
   crouch), moods (several idles per mood) and actions (stretch, yawn, wave,
   dance, look around, react, pick up, fetch). Many variations per state,
   picked by her state and mood so she rarely repeats. Distance-matched
   starts/stops on the desk surfaces.
3. **Live layers on top.** Look-at and gaze (head/eyes to the cursor),
   VRM spring bones for hair/ponytail/tail/ears, face shape keys from her
   TTS emotions, lip sync, foot IK on widget tops.
4. ~~Live MotionBricks~~: dropped, too expensive to run all the time.

## Phases

| # | Step | STATUS |
|---|------|--------|
| 1 | Jane into the 3D body: pet/import/jane_export.py -> pet/models/jane.glb + jane_bonemap.tres (humanoid), picked in Avatar > Model as 'Jane (3D)' and swapped live; toon shading + outlines; spring-bone jiggle (hair, ponytail, ears, chest, hips, belts, tie, bag, tassels) with a dragon tail; MMD faces blended per mood plus accents (hearts, blush, smirk, tears, gloom, sleepy, thoughtful, bored, dizzy, stars, sweat) for her looks and voice emotions | done |
| 2 | Retarget pipeline: Kimodo BVH (standard T-pose rest) -> Blender BVH import -> GLB clip; a soma_bonemap.tres maps SOMA joints to Godot's humanoid, so clips play on every body like the Quaternius set | todo (needs a first clip) |
| 3 | Kimodo locally: installed at /var/mnt/games/AI/Kimodo (.venv shares ComfyUI's torch 2.11/cu128 via a .pth; system cmake for its C++ part). Run with HF_HOME=/var/mnt/games/AI/hf TEXT_ENCODER_DEVICE=cpu (the Llama-3-8B text encoder needs ~17 GB VRAM on GPU; on CPU ~16 GB RAM, Kimodo itself <3 GB VRAM). `kimodo_gen "prompt" --duration N --seed S --output X --bvh --bvh_standard_tpose`. Waiting on: Meta's gated Llama access + his HF token (`hf auth login`), and disk (games drive 31 GB free). Then: prompt list per state, batch variations | blocked (his HF access) |
| 4 | MotionBricks locally: install, TensorRT plan, record locomotion clips (walk/run/strafe/crouch x styles, starts/stops/turns) | todo |
| 5 | State graph in pet.gd: states, transitions, variation picking, mood weights, distance-matched starts/stops, sit/lie on widgets | todo |
| 6 | Live layers: gaze, spring bones, TTS faces, lip sync, foot IK | todo |
| 7 | Her control: the avatar tool gains the new states (sit, lie, stretch, wave...) | todo |
| 8 | ~~Live MotionBricks sidecar~~ | dropped |

## Open questions

- Clothing: the default outfit, and whether the jacket/weapon are toggles.
