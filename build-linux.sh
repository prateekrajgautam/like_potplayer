#!/usr/bin/env bash
# One command to build distributable Linux packages.
#
#   ./build-linux.sh            build everything: AppImage + .deb (if dpkg exists) + .tar.gz
#   ./build-linux.sh appimage   only the AppImage        (also: deb, tarball)
#
# Options (environment):  NO_VENV=1  use the current Python instead of a fresh .venv-build
#                         REFREEZE=1 rebuild the bundle even if dist/like_potplayer exists
#                         LIBMPV=/path/to/libmpv.so.2   bundle a specific libmpv
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
say() { printf '\n\033[1;36m==>\033[0m %s\n' "$*"; }
die() { printf '\n\033[1;31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }
WHAT="${1:-all}"; case "$WHAT" in all|appimage|deb|tarball) ;; *) die "usage: $0 [all|appimage|deb|tarball]";; esac

# NixOS: a PyInstaller bundle built against /nix/store would not run anywhere else (and pip's PyInstaller/Qt wheels do not
# run natively on NixOS), so build in a container. Set NATIVE=1 to skip this check.
if { [ -e "${NIXOS_MARKER:-/etc/NIXOS}" ] || grep -qs '^ID=nixos' "${OS_RELEASE_FILE:-/etc/os-release}"; } && [ "${NATIVE:-0}" != 1 ] && [ "${IN_CONTAINER:-0}" != 1 ]; then
  say "NixOS detected: building the portable packages inside a container"
  exec ./build-linux-container.sh "$WHAT"
fi

say "[1/4] Checking prerequisites"
command -v python3 >/dev/null || die "python3 (3.10+) is required"
python3 -c 'import sys; sys.exit(sys.version_info < (3,10))' || die "Python 3.10 or newer is required"
python3 -c 'import venv, ensurepip' 2>/dev/null || [ "${NO_VENV:-0}" = 1 ] || die "python venv module missing (Debian/Ubuntu: sudo apt install python3-venv)"
. packaging/linux/find_libmpv.sh
if LIBMPV_FOUND="$(find_libmpv)"; then
  echo "libmpv: $LIBMPV_FOUND"; export LIBMPV="$LIBMPV_FOUND"
else
  printf '\n\033[1;31mERROR:\033[0m libmpv was not found.\n' >&2; libmpv_report >&2; libmpv_install_hint >&2; exit 1
fi
command -v curl >/dev/null || [ "$WHAT" = deb ] || [ "$WHAT" = tarball ] || die "curl is required to fetch appimagetool"
echo "ok"

say "[2/4] Building ($WHAT)"
mkdir -p build dist
packaging/linux/freeze.sh          # freeze once; the packagers below reuse dist/like_potplayer
export REFREEZE=0
[ "$WHAT" = all ] || [ "$WHAT" = appimage ] && packaging/linux/build_appimage.sh
if [ "$WHAT" = all ] || [ "$WHAT" = deb ]; then
  if command -v dpkg-deb >/dev/null; then packaging/linux/build_deb.sh; else echo "(skipping .deb: dpkg-deb not available on this system)"; fi
fi
[ "$WHAT" = all ] || [ "$WHAT" = tarball ] && packaging/linux/build_tarball.sh

say "[3/4] Self-test of the built files"
FAIL=0
for f in dist/*.AppImage; do
  [ -e "$f" ] || continue
  APPIMAGE_EXTRACT_AND_RUN=1 "$f" --version >/dev/null 2>&1 && echo "PASS  $f starts" || { echo "FAIL  $f"; FAIL=1; }
done
if [ -x "dist/like_potplayer/like_potplayer" ]; then
  dist/like_potplayer/like_potplayer --list-actions >/dev/null && echo "PASS  frozen app runs and loads its config files" || FAIL=1
fi
if command -v xvfb-run >/dev/null && command -v ffmpeg >/dev/null; then
  ffmpeg -loglevel error -y -f lavfi -i testsrc=duration=4:size=320x180:rate=25 -f lavfi -i sine=duration=4 -shortest -pix_fmt yuv420p build/selftest.mp4
  set +e
  LIKE_POTPLAYER_NO_PROMPT=1 QT_QPA_PLATFORM=xcb LIBGL_ALWAYS_SOFTWARE=1 timeout 8 xvfb-run -a dist/like_potplayer/like_potplayer build/selftest.mp4 >build/selftest.log 2>&1
  rc=$?; set -e
  [ $rc = 124 ] && echo "PASS  plays a clip in a virtual display without crashing" || { echo "FAIL  playback self-test (exit $rc, see build/selftest.log)"; FAIL=1; }
else
  echo "(playback self-test skipped: install xvfb and ffmpeg to enable it)"
fi
[ "$FAIL" = 0 ] || die "self-test failed"

say "[4/4] Done. Files in ./dist:"
ls -1 dist | grep -E '\.(AppImage|deb|tar\.gz)$' | sed 's/^/   /'
cat <<'TXT'

Install on this or another machine (no root needed except for .deb):
   AppImage :  chmod +x dist/*.AppImage && ./dist/*.AppImage --install
   .deb     :  sudo apt install ./dist/*.deb          (then start it once: it offers to become the default player)
   tar.gz   :  tar xzf dist/*.tar.gz && cd like_potplayer-*/ && ./install.sh

After installing, double-clicking a video or audio file in your file manager opens it in the player.
(AppImage on Ubuntu 22.04+ needs FUSE 2:  sudo apt install libfuse2   - or use the .deb / .tar.gz instead.)
TXT
