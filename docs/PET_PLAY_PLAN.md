# A bucket ton of interactions

Ronald, 2026-11-03, after the furniture states were built: "I've changed my
mind on the room. I'd like her to just have a bucket ton of interactions."
He chose: keep the room (the 3D space behind the glass), drop the furniture;
interactions with him, with his desktop, with things, and on her own.

The furniture is off by default now (Avatar setting "Her furniture"); its
code (places.gd, states.json) stays, unused, in case he wants it back.

## Ronald, later the same day

"She's too erratic and her animation transitions are too fast quite often.
Remove all of her objects, they're goofy. She'll just act like a cute desktop
pet doing goofy stuff." So: no props at all (the toys, the things in her
hands, the gift ring and the ball are gone; their takes are set aside in
clips/aries/unused), every clip change blends over at least 0.6 s (quicker
only for falls, grabs, landings and steps: pet.gd _calm_blend), interactions
play at 0.85 speed, and her brain idles longer and plays less often (one
interaction about a minute, the same one not again for two).

## The engine

**pet/play.json**: every interaction is a line of data: what sets it off (a
gesture of his, a desktop event, her mood, a thing in her hands), what she
does (a clip pool, a face, a sound-free emote above her head), what it does
to her needs and mood, and how soon it can happen again. pet.gd reads it the
way it reads states.json; adding one is a clip and a line.

**Gestures** (pet.gd): his pointer is read against her body. Her bones are
projected onto the screen, so the engine knows which part he's on (head,
face, hands, belly, feet) and how he's moving (still, stroking slowly,
wiggling fast, circling, clicking, holding, double-clicking, scrolling). The
desk's pointer relay gives the pointer anywhere; clicks come when he's on her.

## The catalogue (about 90)

**With him (his pointer, clicks, typing, voice)**

| Gesture | She |
|---|---|
| stroke over her head | leans into the pat, eyes closed, happy |
| click her head | bonks, rubs it, pouts or giggles by mood |
| click her cheek / face | blushes, covers her face, or boops back |
| quick wiggle over her belly or sides | tickled: giggles, squirms, swats |
| click her hand | high five |
| hold the button on her hand | holds your hand through the glass |
| click her feet | hops, startled |
| hold the button on her body (no drag) | hugs the glass |
| drag her by any part | a ragdoll (pet/ragdoll.gd, Jolt): pinned at the very point you grabbed, every limb but that one loosely flailing; let go, she tumbles, lands, goes limp, settles, then gets up by how she lies (front / back / side / sitting) |
| double-click | jumps for joy |
| scroll over her | twirls round |
| circle the pointer round her | follows it till she's dizzy |
| wave the pointer side to side | waves back |
| pointer held still near her | reaches out and touches the glass at it |
| pointer racing about | chases it along the glass |
| pointer leaves the screen | looks for it, peeks round a widget |
| shaking her by dragging | dizzy, a bit cross |
| throwing her hard | lands, glares, then laughs |
| he types to her | comes up to the glass, listens, nods |
| he speaks to her | turns to him, mouths along, reacts to his tone |
| he's been away a while | knocks on the glass, then waves when he's back |
| first thing in the day | waves good morning, stretches |
| late at night | yawns at him, points at the clock, goes to sleep |

**With his desktop (widgets on the glass, music, Aries)**

| Event | She |
|---|---|
| music starts | dances (style by mood), or bobs her head |
| song changes | perks up, picks a new move |
| music pauses | stops, looks at the Spotify widget, shrugs |
| Aries works in a widget | points at it, watches over its shoulder |
| a job done / failed | cheers / winces |
| chat message from him | runs to the glass to read it |
| a widget moved or opened | jumps back, then goes to look |
| a widget in front of her | hides behind it, peeks round its edge |
| her breath on the glass | fogs it and draws a heart or a smiley in it |
| bored | leans on the glass, presses her face to it, knocks |
| tapping the glass from behind | taps where a widget is to point at it |

**With things (gifts from his ring, toys in the room)**

Ball (kick it, bounce it off the glass at him, juggle, header), balloon (bats
it up, it floats off), paper plane (folds one, throws it at the glass),
bubbles (blows them, pops them), jump rope, hula hoop, yo-yo, plush (hugs,
dances with it, naps with it), flower (smells it, tucks it in her hair),
guitar (strums, air-guitar), sketchbook (draws, holds up the drawing to him),
sign (holds up "hi" / "!!" / a heart), hat, sunglasses and headphones (puts
them on; headphones while music plays), cookie and drink (eats, offers you
a bite through the glass), umbrella (twirls it). His right-click ring grows
to a page of gifts; things she has stay in her room, on the floor, until she
plays with them again.

**On her own (mood, needs, time)**

Stretch, yawn, hum and sway, twirl, skip in a circle, cartwheel, handstand
try, shadow boxing, yoga pose, sneeze, hiccups, check her nails, fix her hair
in her reflection on the glass, retie a shoe, sit and swing her legs, lie on
her back daydreaming, doze, air guitar, practise a dance, rock-paper-scissors
with herself, spin till dizzy, sigh, pout, giggle at nothing, look round the
room, inspect a speck on the glass, draw on the floor with her finger.

## Phases

| # | Step | STATUS |
|---|------|--------|
| 1 | Engine: play.json, emotes above her head, furniture off; brain picks interactions; avatar verb "do" | done: pet/play.gd + play.json (87 entries), drawn emotes, brain "play"/"play_more" |
| 2 | With him: gesture reader (body parts from her bones, still / stroke / wiggle / circle / hold / double / scroll), all his rows | done: stroke, tickle, circle, still, clicks by part, away/back tested; hold, double-click, scroll, shake, throw, night wired |
| 3 | On her own: ~30 clips, weighted by mood and time | done: 28 (kimodo_play.txt), brain "play"/"play_more" |
| 4 | With things: props, a bigger gift ring, things kept in her room, ~20 clip sets | dropped (he found them goofy): removed with the ring and the ball |
| 5 | With his desktop: the glass (touch, knock, fog doodles, lean), widgets (hide, peek, point, read), music, Aries' work, chat | done: fog/heart/hand marks (premultiplied, drawn over her), behind widgets, music on/off/new song, wince, startle |
| 7 | Calmer: slower blends, fewer and spaced-out interactions, no props | done |
| 6 | Filmed check of every row, tuning by eye | done: PET_SNAPSHOT_SEQ=playall (every one, heights logged, a frame each) |
