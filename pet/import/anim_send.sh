#!/bin/bash
# After anim_studio.py's "Send to Aries" (or "Back to Kimodo's"): pack her clips
# (his edits in clips/edited take the place of Kimodo's takes), then have her
# body reload so it plays them: bin/ariadne2 starts it again when it sees the
# reload flag. Output: $KIMODO_DIR/clips/edited/send.log.
HERE=$(cd "$(dirname "$0")" && pwd)
echo "$(date '+%T') packing (${1:-})"
"$HERE/kimodo_batch.sh" --pack || { echo "packing failed"; exit 1; }
RUN=${XDG_RUNTIME_DIR:-/tmp}
for p in $(pgrep -f -- '--path pet'); do
  mapfile -d '' -t a < "/proc/$p/cmdline" 2>/dev/null || continue
  case "${a[0]##*/}" in [Gg]odot*) touch "$RUN/ariadne2-reload"; kill -TERM "$p" ;; esac
done
echo "$(date '+%T') in: her body is reloading"
