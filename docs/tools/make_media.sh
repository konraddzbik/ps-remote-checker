#!/bin/bash
# Rebuilds the README media (docs/media) from fictional demo data. macOS only (SwiftUI/WebKit + ffmpeg).
#   docs/tools/make_media.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
WORK="${WORK:-$ROOT/build/media}"
OUT="$ROOT/docs/media"
W=1000   # GIF width in px
rm -rf "$WORK"; mkdir -p "$WORK"/{frames,term,panel,seg} "$OUT"
cd "$ROOT"

echo "→ demo data"
python3 docs/tools/make_demo_data.py "$WORK/demo"

echo "→ app frames"
(cd macos && swiftc -swift-version 5 -parse-as-library Tools/Snapshot.swift $(ls Sources/*.swift | grep -v App.swift) -o "$WORK/snapshot")
defaults write snapshot helperCode ABCD-EFGH-JKMN
defaults write snapshot pairCode ABCD-EFGH-JKMN
PSRC_STATE_DIR="$WORK/demo/app" SNAP_MEDIA=1 "$WORK/snapshot" "$WORK/frames" >/dev/null

echo "→ terminal frames"
python3 docs/tools/terminal_transcript.py "$WORK/demo" "$WORK/transcript.json"
swiftc docs/tools/render_terminal.swift -o "$WORK/render_terminal"
"$WORK/render_terminal" "$WORK/transcript.json" "$WORK/term" >/dev/null

echo "→ Home Assistant panel"
PSRC_DATA_DIR="$WORK/demo/addon/data" PSRC_BIND=127.0.0.1 PSRC_PORT=8098 PSRC_ALLOW_LOCAL=1 PSRC_PANEL_ONLY=1 \
  python3 homeassistant/ps_remote_helper/addon.py >/dev/null 2>&1 &
PANEL_PID=$!
trap 'kill $PANEL_PID 2>/dev/null || true' EXIT
sleep 2
swiftc docs/tools/websnap.swift -o "$WORK/websnap"
"$WORK/websnap" http://127.0.0.1:8098/ "$WORK/panel" 1100 1750 >/dev/null

# ---------------------------------------------------------------- ffmpeg helpers
gif() {  # gif <concat.txt> <out.gif> [fps]
  local fps="${3:-12}"
  ffmpeg -loglevel error -y -f concat -safe 0 -i "$1" \
    -vf "fps=$fps,scale=$W:-1:flags=lanczos,split[a][b];[a]palettegen=stats_mode=diff:max_colors=200[p];[b][p]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle" \
    -loop 0 "$2"
}
scroll() {  # scroll <tall.png> <view_h_px> <seconds> <out_prefix>  → numbered frames
  local h; h=$(ffprobe -v error -show_entries stream=height -of csv=p=0 "$1")
  ffmpeg -loglevel error -y -loop 1 -t "$3" -i "$1" \
    -vf "fps=12,crop=iw:$2:0:'min($h-$2, max(0, ($h-$2)*(t-0.6)/($3-1.6)))'" "$4-%03d.png"
}
list() {  # list <file> <duration> → concat lines
  printf "file '%s'\nduration %s\n" "$1" "$2"
}

echo "→ app-away-check.gif"
VIEW=$(ffprobe -v error -show_entries stream=height -of csv=p=0 "$WORK/frames/tour-away.png")
scroll "$WORK/frames/away-tall.png" "$VIEW" 6 "$WORK/seg/away"
{
  for i in 0 1 2 3; do list "$WORK/frames/away-run-$i.png" 0.9; done
  for f in "$WORK"/seg/away-*.png; do list "$f" 0.0833; done
  list "$(ls "$WORK"/seg/away-*.png | tail -1)" 2.5
  list "$WORK/frames/tour-away.png" 2.0
  list "$WORK/frames/tour-away.png" 0.1
} > "$WORK/away.txt"
gif "$WORK/away.txt" "$OUT/app-away-check.gif"

echo "→ app-tour.gif"
{
  for s in start home helper help; do list "$WORK/frames/tour-$s.png" 2.2; done
  for s in home away; do list "$WORK/frames/tour-$s-dark.png" 2.2; done
  list "$WORK/frames/tour-start.png" 0.1
} > "$WORK/tour.txt"
gif "$WORK/tour.txt" "$OUT/app-tour.gif"

echo "→ terminal.gif"
(cd "$WORK/term" && ffmpeg -loglevel error -y -f concat -safe 0 -i concat.txt \
  -vf "fps=12,scale=$W:-1:flags=lanczos,split[a][b];[a]palettegen=stats_mode=diff:max_colors=64[p];[b][p]paletteuse=dither=none:diff_mode=rectangle" \
  -loop 0 "$OUT/terminal.gif")

echo "→ ha-panel.gif"
PV=1500  # viewport height in px (2x)
scroll "$WORK/panel/panel.png" "$PV" 5 "$WORK/seg/panel"
ffmpeg -loglevel error -y -i "$WORK/panel/panel-dark.png" -vf "crop=iw:$PV:0:0" "$WORK/seg/panel-dark-top.png"
{
  list "$(ls "$WORK"/seg/panel-*.png | grep -v dark | head -1)" 1.5
  for f in $(ls "$WORK"/seg/panel-*.png | grep -v dark); do list "$f" 0.0833; done
  list "$WORK/seg/panel-dark-top.png" 3.0
  list "$WORK/seg/panel-dark-top.png" 0.1
} > "$WORK/panel.txt"
gif "$WORK/panel.txt" "$OUT/ha-panel.gif"

echo "→ stills"
swift macos/Resources/make_icon.swift "$WORK/icon.iconset" >/dev/null
cp "$WORK/icon.iconset/icon_256x256.png" "$OUT/icon.png"
ffmpeg -loglevel error -y -i "$WORK/frames/tour-away.png" -vf "scale=1400:-1:flags=lanczos" "$OUT/screenshot-away.png"
ffmpeg -loglevel error -y -i "$WORK/frames/tour-home-dark.png" -vf "scale=1400:-1:flags=lanczos" "$OUT/screenshot-home-dark.png"

ls -lh "$OUT"
