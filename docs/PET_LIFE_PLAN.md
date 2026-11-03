# Things for her to do

Ronald, 2026-11-02: "give her a bunch of things to do. Eat, sleep, work,
workout, etc." She lives in a room behind the screen (docs/PET_AI_PLAN.md);
now the room gets furniture and she gets a life in it.

## Furniture (pet/import/props_build.py -> pet/models/props.glb)

Futon bed, desk with computer and chair, low table and cushion, yoga mat
(dumbbell, towel), kitchenette, bookshelf, plant, rug, watering can. Real
sizes, soft bevels, warm plain colours, toon-shaded like her. Placed around
the back and sides of the room so the front stays hers to walk. The chair
seat is the sitting clips' seat height (0.47 m), the futon top 0.14 m.

## Clips (Kimodo; pet/import/kimodo_life*.txt)

Work (typing, mouse, thinking), gaming (controller), eating (sandwich,
bowl), reading, phone, meditating, sleeping in bed (back, side), workout
(squats, jacks, lunges, push-ups, sit-ups, stretch, shadowboxing), drinking
from a mug, watering the plant, cooking. Seated/lying ones have their poses
pinned to the existing stance clips so transitions match.

## Her life (life.gd + brain.gd)

- New needs: fitness (workout raises it), purpose (work raises it), next to
  energy, fun, affection, hunger.
- Activities, each a plan to the right furniture: eat (cook at the
  kitchenette, then eat at the low table), sleep in bed (instead of curling
  on the floor when the bed's there), work at the desk, play games at the
  desk, read on the cushion, phone, meditate, workout on the mat, water the
  plant, have a drink.
- Props she holds: sandwich/bowl, book, phone, mug, controller, watering can
  (life.gd's held-item meshes).
- Her status says what she's doing; an Avatar setting turns the furniture off.

## Steps

| # | Step | STATUS |
|---|------|--------|
| 1 | Furniture GLB + placed in the room, toon-shaded, setting to hide (pet/room.gd: spots + routing round it) | done |
| 2 | Kimodo clips generated, checked, packed (21 clips; sleep_bed_2 rolls end for end, left out of SleepBed) | done |
| 3 | Needs + activities + plans in brain.gd/life.gd, body at the furniture (seat/bed heights, facing) | todo |
| 4 | Held props for each activity | todo |
| 5 | Filmed checks of each activity, fixes, commit, restart body | todo |
