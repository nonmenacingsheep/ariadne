#!/bin/bash
# Film her through place states (pet/states.json) and make a contact sheet.
#   pet/import/film_states.sh Bed_SitEdge,Bed_LieBack,Bed_Sleep [out.png] [held thing]
# Each state gets PET_SEQ_HOLD seconds (default 6); 14 frames are taken
# across the whole run (PET_SEQ_DT apart) and laid out two to a row, cropped
# round her. PET_SEQ_HEAD=1 in the log (out.log) gives her head and hips
# heights each frame: the quick check she isn't upside down or sunk in.
set -e
PET=$(cd "$(dirname "$0")/.." && pwd)
CHAIN=$1; OUT=${2:-/tmp/states.png}; HELD=${3:-}
HOLD=${PET_SEQ_HOLD:-6}; N=$(awk -F, '{print NF}' <<< "$CHAIN")
DT=$(python3 -c "print(round($HOLD * $N / 14, 2))")
rm -f "${OUT%.png}"_seq_*.png
PET_HOLD=$HELD PET_SEQ_HOLD=$HOLD PET_SEQ_DT=$DT PET_SEQ_HEAD=1 PET_SNAPSHOT_SEQ="state:$CHAIN" \
  PET_MODEL=${PET_MODEL:-res://models/jane.glb} PET_SNAPSHOT="$OUT" \
  timeout 300 "${GODOT:-/var/mnt/games/DevTools/godot-4.7.2/Godot_v4.7.2-stable_linux.x86_64}" \
  --path "$PET" --display-driver x11 > "${OUT%.png}.log" 2>&1
python3 - "$OUT" <<'PY'
import glob, sys
from PIL import Image
out = sys.argv[1]
frames = sorted(glob.glob(out[:-4] + "_seq_*.png"))
ims = []
for f in frames:
    im = Image.open(f).convert("RGBA")
    bg = Image.new("RGBA", im.size, (60, 62, 70, 255))
    bg.alpha_composite(im)
    ims.append(bg)
# the lower half of the screen (her room), quarter size
W, H = ims[0].size
box = (0, int(H * 0.45), W, H)
ims = [i.crop(box).resize((W // 4, (H - box[1]) // 4)) for i in ims]
w, h = ims[0].size
sheet = Image.new("RGBA", (w * 2, h * ((len(ims) + 1) // 2)))
for i, im in enumerate(ims):
    sheet.paste(im, ((i % 2) * w, (i // 2) * h))
sheet.save(out)
print(out)
PY
