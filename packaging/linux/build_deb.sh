#!/usr/bin/env bash
# dist/<id>_<version>_<arch>.deb  (Debian/Ubuntu/Mint: installs system-wide, shows in the menu, "Open with")
set -euo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/common.sh"; mkdir -p build dist
command -v dpkg-deb >/dev/null || die "dpkg-deb not found (run this on Debian/Ubuntu)"
freeze
PKG="$(echo "$ID" | tr '_A-Z' '-a-z')"                      # Debian package names: lowercase, no underscores
case "$ARCH" in x86_64) DEBARCH=amd64;; aarch64) DEBARCH=arm64;; *) DEBARCH="$ARCH";; esac
ST="build/deb"; rm -rf "$ST"
mkdir -p "$ST/DEBIAN" "$ST/opt/$PKG" "$ST/usr/bin" "$ST/usr/share/applications" "$ST/usr/share/icons/hicolor/256x256/apps" \
         "$ST/usr/share/icons/hicolor/48x48/apps" "$ST/usr/share/icons/hicolor/scalable/apps"
cp -r "dist/$BIN/." "$ST/opt/$PKG/"
ln -s "/opt/$PKG/$BIN" "$ST/usr/bin/$ID"
cp like_potplayer/assets/icon-256.png "$ST/usr/share/icons/hicolor/256x256/apps/$ID.png"
cp like_potplayer/assets/icon-48.png  "$ST/usr/share/icons/hicolor/48x48/apps/$ID.png"
cp like_potplayer/assets/icon.svg     "$ST/usr/share/icons/hicolor/scalable/apps/$ID.svg"
python3 - > "$ST/usr/share/applications/$ID.desktop" <<PY
import sys; sys.path.insert(0, '.')
from like_potplayer import config, associations
c = config.Config()
print(associations.desktop_entry(c, '/usr/bin/$ID'), end='')
PY
SIZE=$(du -sk "$ST/opt" | cut -f1)
cat > "$ST/DEBIAN/control" <<CTL
Package: $PKG
Version: $VER
Section: video
Priority: optional
Architecture: $DEBARCH
Installed-Size: $SIZE
Depends: libgl1, libegl1, libxkbcommon-x11-0, libxcb-cursor0, libxcb-icccm4, libxcb-keysyms1, libxcb-shape0, libxcb-image0, libxcb-render-util0, libdbus-1-3, libfontconfig1
Maintainer: $NAME packagers <noreply@example.invalid>
Description: $NAME - PotPlayer-style media player
 Inspired by Daum PotPlayer for Windows. Plays anything mpv plays; skinnable; fully
 configurable hotkeys. Bundles libmpv and Qt.
CTL
cat > "$ST/DEBIAN/postinst" <<'POST'
#!/bin/sh
set -e
command -v update-desktop-database >/dev/null && update-desktop-database -q /usr/share/applications || true
command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor || true
exit 0
POST
cp "$ST/DEBIAN/postinst" "$ST/DEBIAN/postrm"; chmod 755 "$ST/DEBIAN/postinst" "$ST/DEBIAN/postrm"
OUT="dist/${PKG}_${VER}_${DEBARCH}.deb"
dpkg-deb --root-owner-group --build "$ST" "$OUT" >/dev/null
say "Built $OUT ($(du -h "$OUT" | cut -f1)). Install: sudo apt install ./$OUT"
