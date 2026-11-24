#!/usr/bin/env bash
# Simulates "double-click a media file": installs the package into a throw-away HOME, then asks the desktop's
# own opener (gio / xdg-open) to open a video and checks that THIS player started and is playing it.
# usage: tests/test_doubleclick.sh appimage|tarball|deb   (run from the repo root, after ./build-linux.sh)
set -uo pipefail
MODE="${1:-appimage}"; cd "$(dirname "$0")/.."
export HOME="$(mktemp -d)"; export XDG_DATA_HOME="$HOME/.local/share" XDG_CONFIG_HOME="$HOME/.config"
mkdir -p "$XDG_DATA_HOME" "$XDG_CONFIG_HOME" "$HOME/Videos"
export LIKE_POTPLAYER_NO_PROMPT=1 QT_QPA_PLATFORM=xcb LIBGL_ALWAYS_SOFTWARE=1 APPIMAGE_EXTRACT_AND_RUN=1
ffmpeg -loglevel error -y -f lavfi -i testsrc=duration=30:size=320x180:rate=25 -f lavfi -i sine=duration=30 -shortest -pix_fmt yuv420p "$HOME/Videos/clip.mp4"
ffmpeg -loglevel error -y -f lavfi -i sine=frequency=440:duration=30 "$HOME/Videos/song.mp3"
pass() { echo "PASS  $*"; }; fail() { echo "FAIL  $*"; RC=1; }; RC=0

case "$MODE" in
  appimage) IMG="$(ls dist/*.AppImage | head -1)"; chmod +x "$IMG"; "$IMG" --install | sed 's/^/      /'
            EXPECT="$HOME/.local/bin/like_potplayer.AppImage";;
  tarball)  T="$(mktemp -d)"; tar -C "$T" -xzf dist/*.tar.gz; (cd "$T"/*/ && ./install.sh) | sed 's/^/      /'
            EXPECT="$HOME/.local/opt/like_potplayer/like_potplayer";;
  deb)      dpkg -i dist/*.deb >/dev/null 2>&1 || apt-get install -y -q ./dist/*.deb >/dev/null 2>&1
            /usr/bin/like_potplayer --register-defaults | sed 's/^/      /'; EXPECT="/usr/bin/like_potplayer";;
esac
DESK="$XDG_DATA_HOME/applications/like_potplayer.desktop"; [ "$MODE" = deb ] && DESK=/usr/share/applications/like_potplayer.desktop
[ -f "$DESK" ] && pass "launcher present: $DESK" || fail "no launcher at $DESK"
desktop-file-validate "$DESK" 2>&1 && pass "launcher passes desktop-file-validate" || fail "launcher invalid"
grep -q "^Exec=\"\?$EXPECT" "$DESK" && pass "launcher Exec points at the installed copy ($EXPECT)" || { fail "Exec line wrong:"; grep ^Exec= "$DESK"; }
[ -x "$EXPECT" ] && pass "installed program exists" || fail "installed program missing: $EXPECT"
for m in video/mp4 video/x-matroska audio/mpeg audio/flac video/x-msvideo; do
  [ "$(xdg-mime query default $m)" = like_potplayer.desktop ] && pass "default for $m" || fail "default for $m is '$(xdg-mime query default $m)'"
done
for f in clip.mp4 song.mp3; do
  [ "$(xdg-mime query default "$(xdg-mime query filetype "$HOME/Videos/$f")")" = like_potplayer.desktop ] \
    && pass "$f is detected as $(xdg-mime query filetype "$HOME/Videos/$f") -> this player" || fail "$f resolves to another app"
done

# the real thing: open the file the way a file manager does
pkill -x like_potplayer 2>/dev/null; sleep 1
gio open "$HOME/Videos/clip.mp4" >/dev/null 2>&1 &
for i in $(seq 1 20); do sleep 0.5; pgrep -f "clip.mp4" >/dev/null && break; done
sleep 4
if pgrep -af "clip.mp4" | grep -q like_potplayer; then pass "gio open started the player with clip.mp4"; else fail "player did not start (gio open)"; fi
if [ -n "${DISPLAY:-}" ] && command -v ffmpeg >/dev/null; then
  ffmpeg -loglevel error -y -f x11grab -video_size 1024x640 -i "$DISPLAY" -frames:v 1 /tmp/doubleclick_$MODE.png 2>/dev/null && echo "      screenshot: /tmp/doubleclick_$MODE.png"
  python3 - <<PY && pass "picture is visible on screen (not a black window)" || fail "video area is black"
import sys
from PIL import Image, ImageStat
m = ImageStat.Stat(Image.open("/tmp/doubleclick_$MODE.png").convert("RGB").crop((100, 60, 900, 500))).mean
sys.exit(0 if sum(m) > 60 else 1)
PY
fi
# second double-click goes to the already-running window (single instance)
gio open "$HOME/Videos/song.mp3" >/dev/null 2>&1; sleep 3
[ "$(pgrep -xc like_potplayer)" -le 2 ] && pass "second file reused the running window" || fail "second instance spawned"
pkill -x like_potplayer 2>/dev/null
# uninstall leaves nothing behind
case "$MODE" in appimage) "$EXPECT" --uninstall >/dev/null;; tarball) "$EXPECT" --uninstall >/dev/null;; deb) /usr/bin/like_potplayer --uninstall >/dev/null; dpkg -r like-potplayer >/dev/null 2>&1;; esac
[ ! -f "$DESK" ] && [ ! -f "$XDG_DATA_HOME/applications/like_potplayer.desktop" ] && pass "uninstall removed the launcher" || fail "launcher still present after uninstall"
exit $RC
