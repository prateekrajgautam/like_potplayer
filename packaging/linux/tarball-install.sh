#!/usr/bin/env bash
# Per-user installer shipped inside the .tar.gz. No root needed.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="${PREFIX:-$HOME/.local}/opt/like_potplayer"
BINDIR="${PREFIX:-$HOME/.local}/bin"
if [ "${1:-}" = "--uninstall" ]; then
  [ -x "$DEST/like_potplayer" ] && "$DEST/like_potplayer" --uninstall || true
  rm -rf "$DEST" "$BINDIR/like_potplayer"; echo "Removed."; exit 0
fi
mkdir -p "$DEST" "$BINDIR"
rm -rf "$DEST"; cp -r "$HERE/app" "$DEST"
ln -sf "$DEST/like_potplayer" "$BINDIR/like_potplayer"
"$DEST/like_potplayer" --register-defaults
case ":$PATH:" in *":$BINDIR:"*) ;; *) echo "Note: add $BINDIR to your PATH to start it from a terminal.";; esac
