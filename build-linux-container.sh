#!/usr/bin/env bash
# Build the Linux packages inside a clean Ubuntu 22.04 container (docker or podman).
# Use this on NixOS (native builds there are tied to /nix/store), on distros without libmpv, or to get packages that
# run on older systems: Ubuntu 22.04 has the oldest glibc we want to support.
#
#   ./build-linux-container.sh            AppImage + .deb + .tar.gz  -> ./dist
#   ./build-linux-container.sh appimage   (or: deb | tarball)
#   IMAGE=debian:12 ./build-linux-container.sh     use another base image
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
WHAT="${1:-all}"
IMAGE="${IMAGE:-ubuntu:22.04}"
if command -v docker >/dev/null 2>&1; then ENGINE=docker
elif command -v podman >/dev/null 2>&1; then ENGINE=podman
else
  cat >&2 <<'MSG'

ERROR: neither docker nor podman was found, and this build needs one of them.

  NixOS - add ONE of these to /etc/nixos/configuration.nix, run `sudo nixos-rebuild switch`, then run this script again:
            virtualisation.podman.enable = true;                         # rootless, no daemon (recommended)
            virtualisation.docker.enable = true;                         # + add yourself to the "docker" group, log out/in
          (`nix-shell -p podman` alone is not enough: rootless containers need NixOS's setuid helpers from the config above.)
  Debian/Ubuntu: sudo apt install podman      Fedora: sudo dnf install podman      Arch: sudo pacman -S podman

  Only want to RUN or INSTALL the app on NixOS (no AppImage/.deb needed)?   ./build-nixos.sh install
MSG
  exit 1
fi
mkdir -p build dist
VOL="$PWD:/src"; [ "$ENGINE" = podman ] && VOL="$VOL:Z"
EXTRA=()
[ "$ENGINE" = docker ] && EXTRA+=(-e "HOST_UID=$(id -u)" -e "HOST_GID=$(id -g)")    # rootless podman already maps root -> you
printf '\n\033[1;36m==>\033[0m Building "%s" in %s with %s (first run downloads the image and packages)\n' "$WHAT" "$IMAGE" "$ENGINE"
"$ENGINE" run --rm -v "$VOL" -w /src "${EXTRA[@]}" \
  -e IN_CONTAINER=1 -e REFREEZE=1 -e VENV_DIR=.venv-container \
  "$IMAGE" bash packaging/linux/container-build.sh "$WHAT"
printf '\n\033[1;32mDone.\033[0m Files in ./dist:\n'; ls -1 dist | grep -E '\.(AppImage|deb|tar\.gz)$' | sed 's/^/   /'
