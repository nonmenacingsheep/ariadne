# Her 3D body's AI: a room, and a brain

Ronald, 2026-11-02: "the AI needs to be worked on. She should be in a 3D
space the size of the monitor and like 5-10 ft deep." Choices: perspective
(she's smaller at the back), depth on the desk floor only (widget tops stay
ledges at the front), and a rework of all of it: getting around, choosing
what to do, reacting to him.

## The room

- The desk floor (the bottom of her window) becomes a room floor as wide as
  the screen and `avatar.room_depth` deep (default 8 ft, 2.4 m).
- A perspective camera that keeps the front plane (z = 0) exactly where the
  old flat camera had it, PPM pixels a metre, so widget ledges, the cursor
  and clicks line up as before; behind it she shrinks toward the horizon.
- Widget tops stay ledges at the front: to jump up she walks to the front.
- A soft shadow under her on the floor sells the depth.

## Getting around

- Position is (x, depth); targets are points on the floor or a ledge.
- Facing any direction (yaw from the walking direction), turning in place
  for big turns, strafing for small sideways moves, backing up for small
  moves behind her, walking otherwise, stops at the end (all from the gait
  set already built).
- Points of interest in the room: front centre (to talk to him), the back
  corners (to nap), near widget ledges (to climb), near the cursor.

## Choosing what to do

- A utility brain: every activity scores from her needs (energy, fun,
  affection, hunger), moods, the time, what's on screen (music, a game,
  him typing), what she did lately (no repeats), and picks the best with a
  little randomness. Activities: wander/explore, inspect something on the
  floor (crouch), stretch, sit on a ledge, sit on the floor, lie down, nap,
  dance to music, play ball, come to the front and watch him, follow the
  cursor, idle.
- Each activity is a short plan (go there, then do this for a while), so she
  looks like she means it.

## Reacting to him

- When he talks to her (voice or chat), she stops, turns to him and comes
  to the front; when she speaks, she faces him.
- The cursor: she notices it, looks at it, sometimes comes over or
  follows it; a quick wiggle near her gets her attention.
- Clicks and grabs as now, with reactions that fit her mood.

## Phases

| # | Step | STATUS |
|---|------|--------|
| 1 | Room: perspective camera matched at the front plane, depth setting, (x, depth) position, shadow, click area and grabbing in 3D, ledges only at the front | done |
| 2 | Getting around in 3D: targets on the floor, facing/turning, gait choice by direction, stops; walking to the front before climbing | done |
| 3 | Utility brain: activities scored from needs/moods/context/recency, plans per activity | todo |
| 4 | Reacting to him: talk, cursor, clicks | todo |
