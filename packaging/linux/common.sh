# Shared helpers for the Linux build scripts (sourced, not run).
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"; cd "$ROOT"
NAME="$(python3 tools/brand.py app_name)"      # display name, from branding.json
ID="$(python3 tools/brand.py app_id)"
VER="$(python3 tools/brand.py version)"
BIN="like_potplayer"                            # internal executable name (stays stable when you rename the app)
ARCH="$(uname -m)"
. "$ROOT/packaging/linux/find_libmpv.sh"
VENV_DIR="${VENV_DIR:-.venv-build}"
say() { printf '\n\033[1;36m==>\033[0m %s\n' "$*"; }
die() { printf '\n\033[1;31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }

# freeze: Python app -> self-contained folder dist/like_potplayer (bundles Qt and libmpv + its libraries)
freeze() {
  [ -x "dist/$BIN/$BIN" ] && [ "${REFREEZE:-0}" != 1 ] && { say "Reusing dist/$BIN (set REFREEZE=1 to rebuild)"; return; }
  say "Preparing Python environment"
  if [ "${NO_VENV:-0}" = 1 ]; then PY=python3; else
    python3 -m venv "$VENV_DIR" && . "$VENV_DIR/bin/activate" && PY=python
    pip install -q --upgrade pip
  fi
  $PY -m pip install -q . pyinstaller
  LIBMPV="$(find_libmpv)" || { libmpv_report >&2; libmpv_install_hint >&2; die "libmpv not found"; }
  # Bundle the library under its real soname (libmpv.so.2 / .so.1), not the versioned file name (libmpv.so.2.2.0),
  # so the frozen app finds it on a machine that has no libmpv installed.
  SONAME="$(objdump -p "$LIBMPV" 2>/dev/null | awk '/SONAME/{print $2; exit}' || true)"
  [ -n "$SONAME" ] || SONAME="$(basename "$LIBMPV")"
  mkdir -p build/libmpv && cp -L "$LIBMPV" "build/libmpv/$SONAME" && LIBMPV="$ROOT/build/libmpv/$SONAME"
  say "Freezing with PyInstaller (libmpv: $SONAME)"
  rm -rf build/pyi dist/$BIN
  $PY -m PyInstaller --noconfirm --clean --distpath dist --workpath build/pyi --specpath build/pyi --name "$BIN" \
    --add-data "$ROOT/like_potplayer/defaults:like_potplayer/defaults" \
    --add-data "$ROOT/like_potplayer/assets:like_potplayer/assets" \
    --add-binary "$LIBMPV:." \
    "$ROOT/packaging/entry.py" >build/pyinstaller.log 2>&1 || { tail -20 build/pyinstaller.log; die "PyInstaller failed (full log: build/pyinstaller.log)"; }
  [ -x "dist/$BIN/$BIN" ] || die "dist/$BIN/$BIN was not produced"
}
