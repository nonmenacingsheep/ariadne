#!/bin/bash
# Installs Ariadne from this folder (a git clone). Safe to run again: each step
# checks what's already there. Nothing outside this folder, your
# ~/.local/share/ariadne2 and one menu entry is changed without asking.
#
#   ./install.sh            interactive
#   ./install.sh --yes      take the defaults, ask for nothing (no keys, no Live2D)
set -uo pipefail
cd "$(dirname "$0")" || exit 1
REPO=$PWD
YES=0; [ "${1:-}" = "--yes" ] && YES=1
DATA=${XDG_DATA_HOME:-$HOME/.local/share}
STATE=$DATA/ariadne2; [ -d "$DATA/ariadne" ] && KEYS=$DATA/ariadne || KEYS=$DATA/ariadne2

bold() { printf '\n\033[1;31m== %s\033[0m\n' "$*"; }
ok()   { printf '   \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '   \033[33m!\033[0m %s\n' "$*"; }
ask()  {   # ask "question" default(y/n) -> 0 for yes
  local d=$2 a
  [ $YES = 1 ] && { [ "$d" = y ]; return; }
  read -r -p "   $1 [$([ "$d" = y ] && echo Y/n || echo y/N)] " a
  a=${a:-$d}; [[ $a =~ ^[Yy] ]]
}

# ------------------------------------------------------------- the desktop
bold "Desktop"
case "${XDG_CURRENT_DESKTOP:-}" in
  *KDE*) ok "KDE Plasma" ;;
  *) warn "Ariadne's desk needs KDE Plasma (KWin scripts place it). You're on '${XDG_CURRENT_DESKTOP:-unknown}'."
     ask "Carry on anyway?" n || exit 1 ;;
esac

# ------------------------------------------------------- system packages
bold "System packages"
need=()
command -v python3 >/dev/null || need+=(python3)
python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null || need+=("python3>=3.10")
python3 -c 'import venv, ensurepip' 2>/dev/null || need+=(python3-venv)
python3 - 2>/dev/null <<'PY' || need+=("GTK 4 + WebKitGTK 6 for Python")
import gi
gi.require_version("Gtk", "4.0"); gi.require_version("WebKit", "6.0")
from gi.repository import Gtk, WebKit
import cairo
PY
command -v pactl >/dev/null && command -v parec >/dev/null || need+=("pactl/parec")
command -v git >/dev/null || need+=(git)
python3 -c 'import pyatspi' 2>/dev/null \
  || warn "optional: pyatspi (python3-pyatspi) lets her press buttons inside other apps' windows"
if [ ${#need[@]} = 0 ]; then
  ok "all there"
else
  warn "missing: ${need[*]}"
  if command -v apt-get >/dev/null; then
    cmd="sudo apt-get install -y python3-venv python3-gi python3-gi-cairo python3-cairo gir1.2-gtk-4.0 gir1.2-webkit-6.0 python3-pyatspi pulseaudio-utils git"
  elif command -v dnf >/dev/null; then
    cmd="sudo dnf install -y python3-gobject python3-cairo gtk4 webkitgtk6.0 python3-pyatspi pulseaudio-utils git"
  elif command -v pacman >/dev/null; then
    cmd="sudo pacman -S --needed python-gobject python-cairo gtk4 webkitgtk-6.0 python-atspi libpulse git"
  elif command -v zypper >/dev/null; then
    cmd="sudo zypper install -y python3-gobject python3-gobject-cairo typelib-1_0-Gtk-4_0 typelib-1_0-WebKit-6_0 python3-pyatspi pulseaudio-utils git"
  else
    cmd=""
  fi
  if [ -n "$cmd" ] && [ $YES = 0 ] && ask "Install them with: $cmd ?" y; then
    $cmd || { warn "that didn't finish; install them yourself and run this again"; exit 1; }
  else
    warn "install them${cmd:+ (e.g. $cmd)} and run this again"; exit 1
  fi
fi

# --------------------------------------------- updates (a ZIP download too)
bold "Updates"
if [ -d .git ] && git rev-parse -q --verify HEAD >/dev/null 2>&1; then
  ok "installed with git; it updates itself from GitHub"
else
  # Downloaded as a ZIP: make it a git checkout of the repo so it can update.
  [ -d .git ] || git init -q && git symbolic-ref HEAD refs/heads/master
  git remote get-url origin >/dev/null 2>&1 || git remote add origin https://github.com/nonmenacingsheep/ariadne.git
  if git fetch -q origin master && git reset -q origin/master; then
    git branch -q --set-upstream-to=origin/master master 2>/dev/null || true
    if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
      git checkout -q -f master && ok "linked to GitHub and brought up to date"
    else
      ok "linked to GitHub; it updates itself from now on"
    fi
  else
    warn "couldn't reach GitHub; run this again later to turn on updates"
  fi
fi

# ------------------------------------------------------------ python env
bold "Python environment (.venv)"
if [ ! -x .venv/bin/python ]; then
  python3 -m venv --system-site-packages .venv || { warn "couldn't make .venv"; exit 1; }
fi
.venv/bin/python -m pip install -q --upgrade pip >/dev/null
.venv/bin/python -m pip install -q -r requirements.txt && ok "packages installed" || { warn "pip failed"; exit 1; }
if command -v nvidia-smi >/dev/null && nvidia-smi >/dev/null 2>&1; then
  if { [ $YES = 0 ] && ask "NVIDIA GPU found. Install CUDA libraries for faster, more accurate speech (~1.5 GB)?" y; } \
     || [ "${ARIADNE2_GPU:-}" = 1 ]; then
    .venv/bin/python -m pip install -q nvidia-cublas-cu12 "nvidia-cudnn-cu12>=9,<10" && ok "GPU speech ready"
  fi
fi

# ------------------------------------------------------ speech models
bold "Speech models (Whisper)"
# The ones her ears will use on this machine: tiny.en for "hey Aries", plus
# large-v3-turbo with a working GPU or base.en on the CPU. Fetched now so the
# first thing said to her isn't spent downloading (they land in ~/.cache/huggingface).
.venv/bin/python - <<'PY2' && ok "ready" || warn "couldn't fetch them now; they'll download the first time she listens"
from ariadne2.core.ears import transcribe
from faster_whisper.utils import download_model
t = transcribe.Transcriber()
names = dict.fromkeys([transcribe.WAKE_MODEL, t.command_model(), t.control_model()])
where = "GPU" if t.device()[0] == "cuda" else "CPU"
for name in names:
    print(f"   fetching {name} ({where})", flush=True)
    download_model(name)
PY2

# --------------------------------------------------------- memory model
bold "Memory search model (MiniLM, 23 MB)"
EMBED=$STATE/embed
if [ -f "$EMBED/model.onnx" ] || [ -f "$DATA/ariadne/embed/model.onnx" ]; then
  ok "already there"
else
  mkdir -p "$EMBED"
  HF=https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/resolve/main
  if curl -fsSL -o "$EMBED/model.onnx" "$HF/onnx/model_quint8_avx2.onnx" \
     && curl -fsSL -o "$EMBED/tokenizer.json" "$HF/tokenizer.json" \
     && echo "b941bf19f1f1283680f449fa6a7336bb5600bdcd5f84d10ddc5cd72218a0fd21  $EMBED/model.onnx" | sha256sum -c --quiet; then
    ok "downloaded"
  else
    rm -f "$EMBED/model.onnx" "$EMBED/tokenizer.json"; warn "download failed; her memory works without it, recall is just weaker"
  fi
fi

# ------------------------------------------------------------------ keys
bold "Keys (stored in $KEYS, readable only by you)"
mkdir -p "$KEYS"; chmod 700 "$KEYS"
save_key() {   # save_key file "label" ENVVAR required?
  local file=$1 label=$2 env=$3 key
  if [ -n "${!env:-}" ] || [ -s "$KEYS/$file" ]; then ok "$label: already set"; return; fi
  [ $YES = 1 ] && { warn "$label: not set (export $env, or run this again)"; return; }
  read -r -s -p "   $label (Enter to skip): " key; echo
  if [ -n "$key" ]; then (umask 077; printf '%s\n' "$key" > "$KEYS/$file"); ok "$label saved"; else warn "$label skipped"; fi
}
save_key api_key "Anthropic API key (her brain)" ANTHROPIC_API_KEY
save_key cartesia_key "Cartesia API key (her voice; optional)" CARTESIA_API_KEY
save_key deepseek_key "DeepSeek API key (optional)" DEEPSEEK_API_KEY

# ----------------------------------------------------------------- bodies
bold "Her body (optional)"
CORE=ariadne2/pet2d/web/vendor/live2dcubismcore.min.js
if [ -f "$CORE" ]; then
  ok "Live2D Cubism Core already there"
elif [ $YES = 0 ] && ask "Use a Live2D model as her body? This downloads Live2D's Cubism Core (free for individuals, under Live2D's licence: https://www.live2d.com/eula/live2d-proprietary-software-license-agreement_en.html). Accept and download?" n; then
  curl -fsSL -o "$CORE" https://cubism.live2d.com/sdk-web/cubismcore/live2dcubismcore.min.js && ok "Cubism Core downloaded" || warn "download failed"
fi
if [ -f "$CORE" ] && [ $YES = 0 ]; then
  read -r -p "   Path to a Live2D model folder (with a .model3.json) to add, or Enter to skip: " l2d
  if [ -n "$l2d" ] && ls "$l2d"/*.model3.json >/dev/null 2>&1; then
    name=$(basename "$l2d" | tr -cs 'A-Za-z0-9_-' '_' | sed 's/^_*//;s/_*$//'); name=${name:-model}
    mkdir -p "ariadne2/pet2d/web/models/$name" && cp -r "$l2d"/. "ariadne2/pet2d/web/models/$name/" \
      && ok "added as '$name': pick it in the Avatar widget > Model"
  elif [ -n "$l2d" ]; then warn "no .model3.json in $l2d"; fi
fi
if [ ! -f pet/models/aries.vrm ] && [ $YES = 0 ]; then
  read -r -p "   Path to a VRM model (e.g. from VRoid Studio) for the 3D body, or Enter to skip: " vrm
  if [ -n "$vrm" ] && [ -f "$vrm" ]; then
    mkdir -p pet/models && cp "$vrm" pet/models/aries.vrm && ok "VRM copied"
    command -v godot4 >/dev/null || command -v godot >/dev/null || [ -n "${ARIADNE2_GODOT:-}" ] \
      || warn "the 3D body runs in Godot 4 (godotengine.org): put godot4 on your PATH or set ARIADNE2_GODOT"
  fi
fi

# ----------------------------------------------------------------- extras
bold "Extras"
command -v claude >/dev/null && ok "Claude Code found (the Claude widget uses it)" \
  || warn "Claude Code isn't installed; the Claude widget needs it (https://claude.com/claude-code)"

# -------------------------------------------------------------- menu entry
bold "Menu entry"
APPS=$DATA/applications; ENTRY=$APPS/ariadne-desk.desktop
mkdir -p "$APPS"
if [ -f "$ENTRY" ] && ! grep -q "$REPO/bin/ariadne2" "$ENTRY"; then
  warn "$ENTRY exists and points elsewhere; left alone"
else
  cat > "$ENTRY" <<EOF
[Desktop Entry]
Type=Application
Name=Ariadne
Comment=Aries, a desktop companion
Exec="$REPO/bin/ariadne2"
Icon=user-available
Terminal=false
Categories=Utility;
Actions=Stop;

[Desktop Action Stop]
Name=Stop Ariadne
Exec="$REPO/bin/ariadne2" --stop
EOF
  ok "Ariadne is in your app menu"
fi

bold "Done"
cat <<EOF
   Start it from the app menu, or:  $REPO/bin/ariadne2
   Meta+A raises the desk over your windows; Meta+S is push-to-talk;
   "hey Aries" wakes her. Settings: the gear at the top left of her core.
   It updates itself from GitHub (Settings > General).
EOF
