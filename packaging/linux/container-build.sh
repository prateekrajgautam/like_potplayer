#!/usr/bin/env bash
# Runs INSIDE the build container (started by build-linux-container.sh). Not meant to be run by hand,
# but it also works on a throw-away Debian/Ubuntu machine or VM as root.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."
export DEBIAN_FRONTEND=noninteractive
echo "==> Installing build tools and libraries"
apt-get update -qq
apt-get install -y -qq --no-install-recommends python3 python3-venv python3-pip ca-certificates curl file binutils \
  dpkg-dev desktop-file-utils libgl1 libegl1 libxkbcommon-x11-0 libxcb-cursor0 libxcb-icccm4 libxcb-keysyms1 \
  libxcb-shape0 libxcb-image0 libxcb-render-util0 libxcb-xinerama0 libdbus-1-3 libfontconfig1 xvfb xauth ffmpeg >/dev/null
# libmpv: Debian 12 / Ubuntu 24.04 call it libmpv2, Ubuntu 22.04 / Debian 11 libmpv1
apt-get install -y -qq --no-install-recommends libmpv2 >/dev/null 2>&1 || apt-get install -y -qq --no-install-recommends libmpv1 >/dev/null
echo "==> Building"
status=0
./build-linux.sh "${1:-all}" || status=$?
if [ -n "${HOST_UID:-}" ]; then          # give the results back to the user who started docker
  chown -R "$HOST_UID:${HOST_GID:-$HOST_UID}" dist build .venv-container 2>/dev/null || true
fi
exit $status
