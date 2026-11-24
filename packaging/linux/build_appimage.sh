#!/usr/bin/env bash
# dist/<name>-<version>-<arch>.AppImage  (single file; run it, or `--install` it for the current user)
set -euo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/common.sh"; mkdir -p build dist
freeze
say "Assembling AppDir"
APPDIR="build/$BIN.AppDir"; rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin" "$APPDIR/usr/share/applications"
cp -r "dist/$BIN/." "$APPDIR/usr/bin/"
cp like_potplayer/assets/icon-256.png "$APPDIR/$ID.png"
cat > "$APPDIR/$ID.desktop" <<DESK
[Desktop Entry]
Type=Application
Name=$NAME
GenericName=Media Player
Comment=PotPlayer-style media player
Exec=$BIN %F
Icon=$ID
Terminal=false
Categories=AudioVideo;Player;Video;Audio;
MimeType=$(python3 -c "
import sys; sys.path.insert(0,'.')
from like_potplayer import config, associations
print(';'.join(associations.mime_list(config.Config())) + ';')")
StartupWMClass=$ID
DESK
cp "$APPDIR/$ID.desktop" "$APPDIR/usr/share/applications/"
cat > "$APPDIR/AppRun" <<APPRUN
#!/bin/sh
HERE="\$(dirname "\$(readlink -f "\$0")")"
export LD_LIBRARY_PATH="\$HERE/usr/bin:\$HERE/usr/bin/_internal:\${LD_LIBRARY_PATH:-}"
exec "\$HERE/usr/bin/$BIN" "\$@"
APPRUN
chmod +x "$APPDIR/AppRun"

say "Packing the AppImage"
if command -v appimagetool >/dev/null; then TOOL=appimagetool; else
  TOOL=build/appimagetool
  [ -x "$TOOL" ] || { curl -fsSL -o "$TOOL" "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-$ARCH.AppImage" \
    && chmod +x "$TOOL"; } || die "could not download appimagetool; install it or download it manually into build/"
fi
OUT="dist/$NAME-$VER-$ARCH.AppImage"
ARCH="$ARCH" "$TOOL" --appimage-extract-and-run "$APPDIR" "$OUT" >build/appimagetool.log 2>&1 || { tail build/appimagetool.log; die "appimagetool failed"; }
say "Built $OUT ($(du -h "$OUT" | cut -f1))"
