# Little stories: walks with character, and episodes that happen to her

Ronald, 2026-11-06: "I like watching her walk around so I want to see her do
that some more. I want some cutesy walks like with her hands behind her back,
her hips swaying, and her skipping. Right now, she kind of just cycles through
animations I'd like it to look like she's actually doing something. As an
example she'll walk to a corner, look at the ground, crouch down, and then
reach for something. A little bug would appear or something like that and
she'd fall on her butt. Having some variations of this sequence of events +
dozens of events would make her seem very alive."

## What changes

**Now:** her brain picks an activity, walks somewhere, plays a clip for a
while. Each moment is one clip; nothing leads anywhere.

**After:** some of her time is *episodes*: a few beats with a cause and an
effect. She notices something, goes to it, does something to it, it does
something back, she reacts, and the reaction depends on her mood and luck
(each episode has several endings). Between episodes she walks more, in a
walk that suits her mood.

## The pieces

1. **Walk styles** (Kimodo, `import/kimodo_walks2.txt`, looped by
   `kimodo_loop.py`, speed measured from the stride as today):
   hands clasped behind her back, hip-swaying, skipping, tiptoeing (sneaking
   up on something), plus a sad/slow shuffle. A trip keeps one style; her
   mood picks it (light: skip or sway; curious or idle: hands behind her
   back; sneaking up: tiptoe), and episodes can ask for one. She walks a
   little more often and further, so there's more of it to watch.

2. **The episode engine** (`pet/episodes.json`, read by `brain.gd`): an
   episode is beats, each one of: go somewhere (with a walk style), look at a
   point, play a clip (to its end, or for a while), a face, an emote, a
   *thing* appearing or doing something, wait for the thing, and a weighted
   branch between endings. Episodes have cooldowns, moods and times of day
   like `play.json`, and the brain scores them alongside her activities.

3. **Things** (`pet/things.gd`): small, natural, short-lived things that make
   an episode happen, and vanish after. Not held toys or furniture (those came
   out as goofy, 2026-11-03): a ladybug, a beetle, a butterfly, a moth at
   night, a spider on a thread, a leaf, a dust bunny, a shiny coin, a puddle
   of light. Each is small and procedural (a few shapes, toon-shaded like
   her), and moves by itself: crawls, scuttles, flutters, drifts, dangles.

4. **Beat clips** (Kimodo, keyed so each starts where the last ends):
   crouching down and peering, reaching for the floor, poking something,
   startled backwards onto her butt, rubbing her bottom, getting up from
   sitting on the floor, jumping back with a squeak, shooing, following
   something with her eyes and turning, cupping something in her hands and
   letting it go, waving it goodbye, tripping, sneezing, etc.

5. **The catalogue**: dozens of episodes, each with 2–4 endings.

## The first episodes (the catalogue grows from here)

| episode | beats | endings |
|---|---|---|
| bug in the corner | walks to a corner, looks down, crouches, peers, reaches | it skitters at her: falls on her butt, rubs it, laughs / it climbs onto her finger: she lifts it, smiles, lets it go / it flies off: she follows it with her eyes and waves |
| butterfly | one flutters past; she watches, follows it, skipping | it lands on her nose: cross-eyed, sneeze, it flies / she tries to cup it and misses / it lands on her hand |
| dust bunny | notices a dust bunny, crouches, blows on it | it puffs up: she sneezes / it rolls away, she chases it / it vanishes, she shrugs |
| shiny coin | spots something glinting, tiptoes over, picks it up | pockets it, pleased / it's nothing, tosses it / holds it up to the light |
| spider on a thread | a spider drops in front of her face | she shrieks and jumps back / she freezes, then pokes it, it zips up / she waves at it |
| falling leaf | a leaf drifts down; she tries to catch it | catches it, admires it / misses, it lands on her head / blows it away |
| tripping | walking, she catches her foot on nothing | stumbles and recovers, looks around embarrassed / falls, sits up, laughs |
| moth at night | a moth circles above her | she swats at it / watches it, sleepy / it lands on her, she shoos it |
| her tail | her dragon tail twitches; she turns to look at it | chases it round once / grabs it, looks at it / ignores it |
| sneeze | something tickles her nose | a big sneeze that rocks her back / a tiny one / she holds it in |

More to come: hiccups, a yawn that turns into a stretch, peeking at the
glass at her reflection, drawing on fogged glass, chasing a light spot,
balancing on a line, humming and twirling, looking for something she lost,
nodding off standing up, a staring contest with a beetle, a puddle of light
she sits in at sunset...

## Pacing

Calm, as he asked on 2026-11-03: every blend at least 0.6 s (falls and
startles quicker); an episode every few minutes at most, the same one not
again for a long while; plenty of plain walking and idling between.

## STATUS

- [ ] 1. Walk styles: clips, loops, mood-picked per trip; more walking
- [x] 2. Episode engine (`episodes.json`, beats, branches, brain scoring)
- [ ] 3. Things (`things.gd`): ladybug/beetle first, then the rest
- [ ] 4. Beat clips for the first episodes
- [ ] 5. The first ten episodes, filmed and checked
- [ ] 6. The catalogue to dozens
