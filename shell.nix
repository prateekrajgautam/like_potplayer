# nix-shell --run './potlinux.py some.mkv'      # run once
# nix-shell                                      # dev shell
{ pkgs ? import <nixpkgs> { } }:
let
  py = pkgs.python3.withPackages (ps: [ ps.pyside6 ps.mpv ]);   # ps.mpv = python-mpv
  qtPlugins = "${pkgs.qt6.qtbase}/${pkgs.qt6.qtbase.qtPluginPrefix}";
  qtWayland = "${pkgs.qt6.qtwayland}/${pkgs.qt6.qtbase.qtPluginPrefix}";
in
pkgs.mkShell {
  packages = [ py pkgs.mpv-unwrapped pkgs.yt-dlp pkgs.ffmpeg ];
  QT_PLUGIN_PATH = "${qtPlugins}:${qtWayland}";
  LD_LIBRARY_PATH = pkgs.lib.makeLibraryPath [
    pkgs.mpv-unwrapped pkgs.libGL pkgs.libxkbcommon pkgs.wayland pkgs.fontconfig pkgs.freetype pkgs.dbus pkgs.xorg.libX11 pkgs.xorg.libxcb
  ];
}
