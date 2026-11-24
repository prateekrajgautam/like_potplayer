# Sourced by build-linux.sh and common.sh.  Provides:
#   find_libmpv    prints the path of the best libmpv found (empty if none); honours $LIBMPV and $LIKE_POTPLAYER_LIBMPV
#   libmpv_report  prints what was searched (used in the error message)
# Accepts libmpv.so.2, libmpv.so.1 and plain libmpv.so (Ubuntu 22.04 / Mint 21 / Debian 11 ship .so.1).
LDCONFIG="${LDCONFIG:-$(command -v ldconfig 2>/dev/null || echo /sbin/ldconfig)}"

_libmpv_dirs() {
  { "$LDCONFIG" -p 2>/dev/null | awk '/libmpv\.so/{print $NF}' | xargs -r -n1 dirname
    pkg-config --variable=libdir mpv 2>/dev/null
    printf '%s\n' /usr/lib /usr/lib64 /usr/lib32 /lib /lib64 /usr/local/lib /usr/local/lib64 \
      /usr/lib/x86_64-linux-gnu /usr/lib/aarch64-linux-gnu /lib/x86_64-linux-gnu /lib/aarch64-linux-gnu \
      /opt/mpv/lib /opt/homebrew/lib /var/lib/flatpak/runtime \
      "$HOME/.nix-profile/lib" /run/current-system/sw/lib /nix/var/nix/profiles/default/lib
    echo "${LD_LIBRARY_PATH:-}" | tr ':' '\n'
  } | awk 'NF && !seen[$0]++'
}

find_libmpv() {
  local c
  for c in "${LIBMPV:-}" "${LIKE_POTPLAYER_LIBMPV:-}"; do
    [ -n "$c" ] && [ -f "$c" ] && { readlink -f "$c"; return 0; }
  done
  local d f best=""
  while IFS= read -r d; do
    [ -d "$d" ] || continue
    for f in "$d"/libmpv.so.2 "$d"/libmpv.so.1 "$d"/libmpv.so; do      # prefer the newest soname
      if [ -f "$f" ]; then best="$(readlink -f "$f")"; break 2; fi
    done
  done < <(_libmpv_dirs)
  [ -n "$best" ] && { echo "$best"; return 0; }
  return 1
}

libmpv_report() {
  echo "  searched: ldconfig cache, pkg-config, /usr/lib*, /lib*, /usr/local/lib*, \$LD_LIBRARY_PATH, Nix profiles"
  echo "  ldconfig mentions of mpv:"; ("$LDCONFIG" -p 2>/dev/null | grep -i mpv | sed 's/^/    /') || true
  [ -n "$("$LDCONFIG" -p 2>/dev/null | grep -i mpv || true)" ] || echo "    (none)"
}

libmpv_install_hint() {
  local id="" like=""
  [ -r /etc/os-release ] && . /etc/os-release && id="${ID:-}" && like="${ID_LIKE:-}"
  if [ -e /etc/NIXOS ] || [ "$id" = nixos ]; then
    cat <<'HINT'
  You are on NixOS. Bundles built here link against /nix/store and will not run on other distros, so build the
  portable packages in a container instead:   ./build-linux-container.sh
  (For your own use on NixOS:  nix run . -- movie.mkv   or   nix-shell --run 'python -m like_potplayer')
HINT
    return
  fi
  case " $id $like " in
    *" debian "*|*" ubuntu "*) echo "  Install it:   sudo apt install libmpv2     (older releases - Ubuntu 22.04, Mint 21, Debian 11 - call it libmpv1)";;
    *" fedora "*|*" rhel "*|*" centos "*) echo "  Install it:   sudo dnf install mpv-libs     (Fedora: needs the RPM Fusion repository)";;
    *" arch "*) echo "  Install it:   sudo pacman -S mpv";;
    *" suse "*) echo "  Install it:   sudo zypper install libmpv2     (from the Packman repository)";;
    *) echo "  Install your distribution's libmpv package (often named libmpv2, libmpv1 or mpv-libs).";;
  esac
  echo "  Already installed somewhere unusual?  find / -name 'libmpv.so*' 2>/dev/null   then:   LIBMPV=/that/path/libmpv.so.2 ./build-linux.sh"
  echo "  No root / odd distro?  build inside a container instead:   ./build-linux-container.sh"
}
