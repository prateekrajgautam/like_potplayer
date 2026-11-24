#!/usr/bin/env bash
# Build, test and install like_potplayer with Nix (NixOS, or any Linux/macOS that has Nix).
#
#   ./build-nixos.sh            build + test                         (default)
#   ./build-nixos.sh install    build, test, install into your profile, make it the default media player
#   ./build-nixos.sh run [files...]    build and start it
#   ./build-nixos.sh check      only the unit tests, inside the dev shell
#
# Declarative alternative (NixOS configuration / home-manager): see "NixOS" in README.md.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
say() { printf '\n\033[1;36m==>\033[0m %s\n' "$*"; }
die() { printf '\n\033[1;31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }
MODE="${1:-build}"; shift || true
command -v nix >/dev/null || die "nix not found. Install it from https://nixos.org/download (NixOS has it already)."
NIX=(nix --extra-experimental-features "nix-command flakes")
REF="path:$PWD"          # 'path:' ignores git state, so files you have not committed are still built

case "$MODE" in
  check)
    say "Unit tests (dev shell)"
    "${NIX[@]}" develop "$REF" --command python -m pytest tests/test_config.py tests/test_windows_registry.py -q
    exit 0;;
  build|install|run) ;;
  *) die "usage: $0 [build|install|run|check]";;
esac

say "[1/3] Building (first time downloads Qt and mpv from the binary cache)"
"${NIX[@]}" build "$REF#default" --print-build-logs -o result
BIN="$PWD/result/bin/like_potplayer"
[ -x "$BIN" ] || die "result/bin/like_potplayer was not produced"

say "[2/3] Testing the built program"
FAIL=0
"$BIN" --version >/dev/null                       && echo "PASS  starts"                           || FAIL=1
"$BIN" --list-actions >/dev/null                  && echo "PASS  loads its JSON config"          || FAIL=1
"$BIN" --self-test                                && echo "PASS  Qt and libmpv load"             || FAIL=1
"${NIX[@]}" develop "$REF" --command python -m pytest tests/test_config.py tests/test_windows_registry.py -q \
                                                  && echo "PASS  unit tests"                      || FAIL=1
[ "$FAIL" = 0 ] || die "a check failed (see above)"

say "[3/3] Done: $BIN"
case "$MODE" in
  run)     exec "$BIN" "$@";;
  install)
    say "Installing into your profile"
    "${NIX[@]}" profile install "$REF#default" 2>&1 || "${NIX[@]}" profile upgrade like_potplayer 2>&1 || true
    if [ -L "$HOME/.config/mimeapps.list" ] && readlink "$HOME/.config/mimeapps.list" | grep -q /nix/store; then
      echo "Your mimeapps.list is managed by home-manager (read-only): set the default declaratively instead:"
      echo "   programs.like_potplayer = { enable = true; defaultForMedia = true; };   # see README, NixOS"
    else
      like_potplayer --register-defaults 2>/dev/null || "$BIN" --register-defaults
    fi;;
  *) cat <<'TXT'

Use it:      ./result/bin/like_potplayer movie.mkv        or    nix run .#default -- movie.mkv
Install:     ./build-nixos.sh install                      (imperative, per user)
Declarative: add the flake's module to your NixOS configuration or home-manager (README: NixOS)
TXT
esac
