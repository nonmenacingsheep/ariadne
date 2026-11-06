# Recording script: "hey Aries" in your own voice

Three parts. Each block goes in **its own file**, named as shown (`a1.wav`, `a2.wav`, … `c.wav`), so I know which style each take is without you saying it on the recording.

**Before you start**
- Record on the **mic she listens through** (your headset, the same input EasyEffects feeds her). Using the same mic matters more than anything else.
- Leave **about 2 seconds of silence** between takes. I split the files at the gaps.
- Don't try to say it identically each time. Natural drift is good.
- Mistakes, coughs and laughs are fine. Leave them in and keep going.
- Save everything in `~/Downloads/wake/`, as WAV or FLAC.

To record from a terminal: run the line, speak, then press Ctrl+C to stop.
```bash
mkdir -p ~/Downloads/wake && parecord --file-format=wav ~/Downloads/wake/a1.wav
```
(Change `a1` for each block.)

---

## Part A: "hey Aries", 200 times

Each block is **25 takes**. Most of them are how you'd really say it.

| file | how | |
|---|---|---|
| `a1` | Normal, sitting at the desk, the way you'd call her | 25 |
| `a2` | Quieter, a bit tired or mumbled | 25 |
| `a3` | Quick and casual, almost one word: "heyAries" | 25 |
| `a4` | With something after it: "hey Aries, what's the weather", "hey Aries, open Steam", "hey Aries, pause the music". Make up your own, a different one each time | 25 |
| `a5` | With a game or music playing out loud in the background | 25 |
| `a6` | Leaning back or turned away from the mic, about arm's length or further | 25 |
| `a7` | With a pause in the middle: "hey… Aries", "hey, Aries" | 25 |
| `a8` | A mix: louder, questioning ("hey Aries?"), annoyed, laughing, slow and clear | 25 |

---

## Part B: close-sounding phrases (must **not** wake her)

Say each line **twice**, normally, with the usual 2-second gap. One file per block.

**`b1`: almost the phrase**
- hey Harry
- hey Ari
- hey Ares
- hey arrays
- hey there
- hey airy
- hey Larry
- hey Carrie
- hey Mary
- hey Siri
- hey Alexa
- okay Aries
- wake Aries
- Aries
- hey

**`b2`: "hey" in normal speech**
- hey, are you coming?
- hey, is this thing on?
- hey, eyes up here
- hey, that's mine
- hey, how are you
- hay is for horses
- a hairy situation
- hey, what's up
- hey, wait a second
- hey, everyone

**`b3`: her name in normal speech** (only "hey Aries" should wake her, not her name on its own)
- I asked Aries about that yesterday
- Aries is a fire sign
- the Aries constellation is up tonight
- Aries, never mind
- is Aries still running?
- I'll tell Aries later
- Ariadne 2 is open
- the series finale was good
- that's an easy one
- they're over there

---

## Part C: you talking normally, 5–10 minutes (`c`)

Just talk the way you normally would at the desk, with no pauses needed:
- Gaming chatter: callouts, swearing at a boss, reacting to a match.
- Talking to someone on Discord.
- Reading something out loud: a Reddit post, a patch note, a page of anything.
- Thinking out loud while you do something.

If you'd like a prompt to read, these are fine:
- "Okay, I'm going to try the left side this time, there's usually a chest behind that wall."
- "Did the update drop yet? I keep getting the same error when I launch it."
- "No, no, no, he's behind you, behind you! Ugh. Okay, again."
- "I think I need a new headset, the left side keeps cutting out."
- "What time is it? I should probably eat something."
- "Hold on, my mic was muted the whole time."

---

## Done?

Tell me the files are in `~/Downloads/wake/`. I'll split them, set a fifth of your takes aside as a test set, and train. Then I'll compare the new model against "wake Aries" on your own held-out voice before swapping anything.
