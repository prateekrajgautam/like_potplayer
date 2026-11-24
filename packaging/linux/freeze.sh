#!/usr/bin/env bash
# Just the PyInstaller step (dist/like_potplayer). The other scripts reuse it.
set -euo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/common.sh"; mkdir -p build dist
freeze
