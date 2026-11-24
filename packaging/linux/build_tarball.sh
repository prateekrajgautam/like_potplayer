#!/usr/bin/env bash
# dist/<name>-<version>-linux-<arch>.tar.gz  (any distro, no FUSE, no root: run ./install.sh inside)
set -euo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/common.sh"; mkdir -p build dist
freeze
ST="build/tar/$NAME-$VER"; rm -rf build/tar; mkdir -p "$ST"
cp -r "dist/$BIN" "$ST/app"
cp packaging/linux/tarball-install.sh "$ST/install.sh"; chmod +x "$ST/install.sh"
cat > "$ST/README.txt" <<TXT
$NAME $VER
  ./install.sh              install for your user (menu entry + double-click on media files)
  ./install.sh --uninstall  remove it again
  ./app/$BIN file.mkv       or just run it from here
TXT
OUT="dist/$NAME-$VER-linux-$ARCH.tar.gz"
tar -C build/tar -czf "$OUT" "$NAME-$VER"
say "Built $OUT ($(du -h "$OUT" | cut -f1))"
