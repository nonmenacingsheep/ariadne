# Deeper actions: places, states and items

Ronald, 2026-11-03: "make every action she can take deeper. ... multiple
states. One of those states is Sitting_On_Bed where she sits at the edge of
her bed and can play different animations like kick her feet. She can then
transition into sleeping or standing up. She can read or do something else
in this state as well if she grabbed a book."

## Where we are

Each activity today is one pose at one spot: she walks to the futon, lies
down, sleeps; walks to the desk, sits, works. A role picks among a few
variants of that pose, and stances (stand, ledge, floor, crouch, lie) give
her transitions between them. What's missing is everything *inside* an
activity: other ways to be at the bed, small things she does while there,
moving between them without standing up first, and what she's holding
changing what she can do.

## The model

**Place**: a piece of furniture or a part of the room (bed, desk, cushion,
kitchen, mat, floor). It owns where her body goes (spot, lift, facing) and
a small graph of states.

**State**: a way of being at a place, named like `Bed_SitEdge`,
`Bed_LieBack`, `Bed_Sleep`, `Desk_Sit`, `Desk_LeanBack`. Each state has:

- a **base pose**: one generated clip every other clip in the state starts
  and ends on, so anything in the state can follow anything else;
- **idles**: what she does there with nothing in her hands, weighted by
  mood (kick her feet, swing her legs, stretch, look around, yawn, hum,
  pat the mattress, flop back);
- **item idles**: unlocked by what she's holding (book: read, turn pages,
  laugh at a line; phone: scroll, take a selfie; mug: sip, warm her hands;
  controller: play, rage, cheer);
- **exits**: transition clips to neighbouring states (`Bed_SitEdge ->
  Bed_LieBack`: swing legs up and lie back; `-> Stand`: push off and stand;
  `-> Bed_SitUp`: scoot back against the wall), each with how her lift and
  position move during it (sitting edge 0.47 m to lying on the mattress);
- **talk reaction**: what she does when you talk to her from that state (on
  the bed she sits up and looks at you instead of getting up).

**Graph search**: the brain asks for a state ("Bed_Sleep") and the body walks
the shortest chain of transitions to it from wherever she is (standing ->
walk to bed -> Bed_SitEdge -> Bed_LieBack -> Bed_Sleep). Nothing pops, and
she never has to stand up between two bed states.

**Items** become real things with homes: books on the shelf, her phone on
the desk, a mug at the kitchen, the controller by the monitor. She picks
one up (a reach clip at its home), carries it (carry-walk variants), and it
unlocks item idles in any state that has them. When she's done she puts it
back, or sometimes leaves it where she was: a book left on the bed stays
there (saved) until she tidies up or picks it up again.

**Data, not code**: the places, states, idles, item idles and exits are one
table (pet/states.json) read at start. Adding a fidget means adding a clip
and a line; the checker (below) flags any clip whose ends don't match its
state's base pose.

## Places and states

| Place | States | Idles (examples) | With an item |
|---|---|---|---|
| Bed (raised to a real bed, mattress top 0.5 m, so sitting on its edge is a chair-height sit) | SitEdge, SitUp (back to the wall, legs out), LieBack, LieSide, LieFront (on her stomach, feet in the air), Sleep | kick feet, swing legs, stretch, flop back, roll over, hug pillow, stare at ceiling | book: read (sitting up, on her stomach); phone: scroll (lying back, holding it up); mug: sip |
| Desk | Sit, LeanBack (feet up), Slouch, Spin (swivel the chair) | type, mouse, chin on hand, stretch, rub eyes, drum fingers | mug: sip; controller: play, rage, cheer; book: study |
| Cushion and low table | CrossLegged, HugKnees, Kneel, LieSide (propped on an elbow) | sway, look around, rest chin on knees | bowl: eat; book: read; phone: scroll |
| Kitchen | Stand, Lean (back to the counter) | wipe the counter, open a cupboard, look in the fridge | cook: stir, chop, taste; mug: make tea, sip |
| Mat | Stand, FloorSit, LieBack, Plank | warm-up, cool-down stretch | (none) |
| Floor (anywhere) | Stand, Crouch, FloorSit, Lie (today's stances) | (today's idles) | book or phone anywhere she sits |

About 25 states, 4-6 idles each plus item idles and exits: roughly 150 clips.

## Getting the clips right (what tonight taught us)

- **Base pose first, pinned**: each state's base pose is generated once and
  checked; every other clip in the state has its first and last frames
  pinned to it (kimodo_keyed.py). Text alone can't hold a pose.
- **Middle keyframes for big motions**: pinning only both ends made a static
  sit-up. kimodo_keyed.py gains middle poses ("halfway: curled up to her
  knees"), taken from a generated pose or set by hand on the skeleton.
- **Checker for every clip**: ends match the base pose (joint error under a
  threshold), head and hips heights stay plausible (no thin-air sitting, no
  upside-down), lying head direction recorded. Fails go back for a re-roll
  with another seed, up to 3, then onto a list for me to look at.
- **Filmed side-on and front**: one contact sheet per state, every clip.
- **Prone pose**: a new base pose for lying on her stomach (reading on the
  bed, planks), which we don't have yet.

## Brain changes

- Activities become goals: a place, a state, an item maybe, and how long.
  "Read in bed" = get a book from the shelf, go to the bed, Bed_SitUp,
  reading idles for a while.
- Once at a place she chains states there by mood and needs instead of
  leaving: reading in bed, getting sleepy, putting the book down, lying back,
  sleeping. A place's states score like activities do.
- Interruptions fit the state: you talk to her while she's lying in bed and
  she props herself up and faces you; she doesn't walk to the front unless
  she's standing.

## Phases

| # | Step | STATUS |
|---|------|--------|
| 1 | State engine: states.json, base poses, idles, item idles, exits with lift/position curves, graph search, talk reactions; today's activities ported to it unchanged | todo |
| 2 | Clip pipeline: middle keyframes in kimodo_keyed.py, prone base pose, per-clip checker (ends vs base pose, heights, head direction), auto re-roll, contact sheets | todo |
| 3 | Bed: raised bed prop, its 6 states, idles, exits, book/phone/mug idles (the Sitting_On_Bed example end to end first) | todo |
| 4 | Items: homes, pick up / carry / put down / leave behind (saved), carry walks | todo |
| 5 | Desk: 4 states, idles, mug/controller/book | todo |
| 6 | Cushion and low table: 4 states, bowl/book/phone | todo |
| 7 | Kitchen: 2 states, cooking and tea | todo |
| 8 | Mat: 4 states, a real routine (warm-up, floor work, cool-down) | todo |
| 9 | Floor anywhere: items in today's stances | todo |
| 10 | Brain: goals, chaining states within a place, state-fitting interruptions | todo |

## For Ronald to decide

- Raise the bed to a real bed (needed for sitting on its edge the way you
  described), or keep the low futon and sit on its edge knees-up?
- Order: bed first as the worked example (recommended), then items, then the
  rest?
- Which item idles matter most to you, and any states missing from the table?
