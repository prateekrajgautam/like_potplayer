# nix-shell                                     -> dev shell
# nix-shell --run 'python -m like_potplayer a.mkv'
{ pkgs ? import <nixpkgs> { } }:
let
  py = pkgs.python3.withPackages (ps: [ ps.pyside6 ps.mpv ps.pillow ps.pyinstaller ps.pytest ]);
  libmpv = pkgs.lib.getLib pkgs.mpv-unwrapped;
  qtPlugins = "${pkgs.qt6.qtbase}/${pkgs.qt6.qtbase.qtPluginPrefix}";
  # newer nixpkgs renamed xorg.libX11 -> libx11 and xorg.libxcb -> libxcb (the old names print evaluation warnings)
  x11 = if pkgs ? libx11 then [ pkgs.libx11 pkgs.libxcb ] else [ pkgs.xorg.libX11 pkgs.xorg.libxcb ];
in
pkgs.mkShell {
  packages = [ py pkgs.mpv-unwrapped pkgs.yt-dlp pkgs.ffmpeg ];
  QT_PLUGIN_PATH = "${qtPlugins}:${pkgs.qt6.qtwayland}/${pkgs.qt6.qtbase.qtPluginPrefix}";
  LIKE_POTPLAYER_LIBMPV = "${libmpv}/lib/libmpv.so";
  LD_LIBRARY_PATH = pkgs.lib.makeLibraryPath ([
    libmpv pkgs.libGL pkgs.libxkbcommon pkgs.wayland pkgs.fontconfig pkgs.freetype pkgs.dbus
  ] ++ x11);

shellHook = ''
    python3 like_potplayer/app.py
'';
}
