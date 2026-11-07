# Animating her in Blender

Her clips are motion-capture-style takes from Kimodo. You can fix or change
any of them in Blender, on her own body, and send the result back. It plays on
every body (Jane, Kuromoji, Shiromoji, Aries), and Kimodo's original stays
untouched, so you can always go back.

## Opening a clip

From the `ariadne2` folder:

```bash
bin/anim-edit --list
```

```bash
bin/anim-edit yawn_1
```

The second word is the clip; a third picks the body (`bin/anim-edit yawn_1 jane`;
Shiromoji if you leave it out). Blender opens with:

- **her body**, in her usual outfit, with the clip on her, and **her bones**
  drawn over her: those are what you click and turn. (Only her bones can be
  clicked, so you can't grab the mesh by accident.)
- **the timeline** along the bottom: the clip, 30 frames to a second.
- **the Aries tab** in the sidebar on the right (press **N** if it's hidden):
  the clip's name, and the two buttons that matter: **Send to Aries** and
  **Back to Kimodo's**.

## In your own Blender (the add-on)

`bin/anim-edit` builds a fresh scene for you. To load her clips into a file of
your own instead (say, your copy of Shiromoji's original `.blend`), install the
add-on once:

1. **Edit → Preferences → Add-ons**, then the small **⌄** at the top right →
   **Install from Disk…**
2. Pick `ariadne2/pet/import/aries_anim.py` (in `Claude Projects`), and tick
   **Aries clips** in the list.

Then, in any file with one of her bodies in it:

1. Click her skeleton (**Armature**, or `Armature_Base` in Shiromoji's file) in
   the Outliner.
2. In the 3D view's sidebar (**N**), the **Aries** tab: pick a **Clip**, click
   **Load onto her**. The clip is put onto her (a second or so), her bones
   are drawn over her, and you're in Pose Mode, ready to fix.
3. **Send to Aries** and **Back to Kimodo's** work as below; **Let her go**
   takes the clip off her and gives her own animation back.

If you installed the add-on before, install it again the same way to update it
(and restart Blender).

## Getting around

| Do this | To |
| --- | --- |
| drag with the **middle mouse button** | orbit round her |
| **Shift** + middle-drag | slide the view |
| **scroll wheel** | zoom |
| **numpad 1 / 3 / 7** (or click the coloured balls top right) | front / side / top view |
| **Space** | play / stop |
| drag the **blue playhead** in the timeline | go to a moment |
| **left / right arrow** | one frame back / on |
| **Ctrl+Z** | undo (as many times as you like) |

## Lesson 1: fixing a clip where her arm goes through her body

1. **Find the moment.** Press **Space** and watch. When her hand or arm goes
   into her, press **Space** again and step with the arrow keys to the frame
   where it's deepest.
2. **Pick the bone.** Click the bone for the part that should move. For an
   arm in her chest that's usually the upper arm. Its name shows in the
   sidebar's **Item** tab: on Shiromoji and Kuromoji her arm bones are
   `Shoulder_L`, `UpperArm_L`, `LowerArm_L` and `Hand_L` (and `_R`). Her
   **left** is on **your right** in the front view. Her body bones (spine,
   arms, legs, hands, fingers, head) go back to Aries; hair, tail and breast
   bones don't (the clips have none), so leave those be.
3. **Turn it.** Press **R**, move the mouse, and click to keep it (right-click
   cancels). To turn it about just one axis, press **R** then **X**, **Y** or
   **Z**. You can also type the angle: **R Z 10 Enter** turns it 10 degrees.
   Small moves are best: 5 to 15 degrees usually clears clipping.
4. **That's a key.** Auto-keying is on, so the turn is saved: a diamond appears
   in the timeline. Your keys go on a **Fixes layer** on top of the clip:
   **one key turns that bone by that much for the whole clip**, which is
   usually exactly what a clipping fix wants. Press **Space** and watch the
   whole clip through.
5. **Only for part of the clip?** If the fix should only be there around
   that moment, go to a frame a little before it, click the same bone, and
   press **I** (insert a key) without turning it. Do the same a little after.
   Now the fix eases in and back out.
6. **Send it.** Click **Send to Aries**. In a minute or two it's packed into
   her clips and her body reloads with it. If you don't like it, open the
   clip again and keep going, or click **Back to Kimodo's** to undo it all.

Save your Blender file if you like (**Ctrl+S**), but you don't need to: what
matters is sent with **Send to Aries**, and opening a clip you've sent before
starts from your version.

## How it works (for the curious)

- The takes live in `$KIMODO_DIR/clips` (`aries/` one-shots, `loops/` walks).
  Your versions go to `clips/edited/<clip>.bvh`, and packing
  (`pet/import/kimodo_batch.sh --pack`) uses one of those instead of Kimodo's
  take of the same name. Deleting it (Back to Kimodo's) brings the original back.
- The clip is put onto her body by the same maths Godot uses to put the clips
  on her, and Send to Aries runs it backwards (her pose, every frame, onto
  Kimodo's skeleton), so what you see is what she does. One thing differs: on
  her desktop, the clips that only use her top half (yawns, waves, thinking)
  take her legs from one calm idle, so she doesn't shuffle her feet between
  them. Don't worry if her legs look different in Blender for those.
- `pet/import/anim_studio.py` does it all; `--selftest` checks the round trip
  without opening a window.
