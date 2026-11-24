# nix build            -> ./result/bin/like_potplayer
# nix run . -- a.mkv   -> run without installing
# nix develop          -> dev shell (same as `nix-shell`)
# NixOS:  imports = [ like_potplayer.nixosModules.default ];  programs.like_potplayer.enable = true;
# home-manager: imports = [ like_potplayer.homeManagerModules.default ]; programs.like_potplayer.enable = true;
# NOTE: written without access to a Nix machine - first build may need small fixes (see README, "Status").
{
  description = "like_potplayer - a PotPlayer-style media player for Linux, macOS and Windows";
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs = { self, nixpkgs }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" "x86_64-darwin" "aarch64-darwin" ];
      forAll = f: nixpkgs.lib.genAttrs systems (system: f nixpkgs.legacyPackages.${system});
      mimeTypes = [
        "video/mp4" "video/x-matroska" "video/webm" "video/x-msvideo" "video/quicktime" "video/x-m4v"
        "video/mp2t" "video/mpeg" "video/x-ms-wmv" "video/x-flv"
        "audio/mpeg" "audio/flac" "audio/ogg" "audio/x-wav" "audio/mp4" "audio/aac" "audio/x-ms-wma"
      ];
      mkPackage = pkgs:
        let
          inherit (pkgs) lib;
          py = pkgs.python3Packages;
          libmpv = lib.getLib pkgs.mpv-unwrapped;
        in
        py.buildPythonApplication {
          pname = "like_potplayer";
          version = "0.4.0";
          pyproject = true;
          src = ./.;
          build-system = [ py.setuptools ];
          dependencies = [ py.pyside6 py.mpv ];
          nativeBuildInputs = [ pkgs.qt6.wrapQtAppsHook ];
          buildInputs = [ pkgs.qt6.qtbase ] ++ lib.optional pkgs.stdenv.isLinux pkgs.qt6.qtwayland;
          dontWrapQtApps = true;                    # wrapped below together with the python wrapper
          preFixup = ''
            makeWrapperArgs+=("''${qtWrapperArgs[@]}"
              --set LIKE_POTPLAYER_LIBMPV ${libmpv}/lib/libmpv${pkgs.stdenv.hostPlatform.extensions.sharedLibrary}
              --prefix LD_LIBRARY_PATH : ${lib.makeLibraryPath [ libmpv pkgs.libGL ]})
          '';
          postInstall = ''
            install -Dm644 packaging/linux/like_potplayer.desktop $out/share/applications/like_potplayer.desktop
            install -Dm644 like_potplayer/assets/icon.svg $out/share/icons/hicolor/scalable/apps/like_potplayer.svg
          '';
          doCheck = false;                          # the GUI smoke tests need a display + GPU
          meta = {
            description = "PotPlayer-style media player (PySide6 + libmpv)";
            mainProgram = "like_potplayer";
            platforms = lib.platforms.unix;
          };
        };
    in
    {
      packages = forAll (pkgs: { default = mkPackage pkgs; like_potplayer = mkPackage pkgs; });
      apps = forAll (pkgs:
        let p = mkPackage pkgs; in {
          default = { type = "app"; program = "${p}/bin/like_potplayer"; };
          # nix run .#register-defaults  -> make it the default player for media files (per user)
          register-defaults = { type = "app"; program = "${pkgs.writeShellScript "register-defaults" ''
            exec ${p}/bin/like_potplayer --register-defaults
          ''}"; };
        });
      checks = forAll (pkgs: { build = mkPackage pkgs; });
      devShells = forAll (pkgs: { default = import ./shell.nix { inherit pkgs; }; });
      overlays.default = final: _prev: { like_potplayer = mkPackage final; };

      nixosModules.default = { config, lib, pkgs, ... }: {
        options.programs.like_potplayer = {
          enable = lib.mkEnableOption "like_potplayer";
          defaultForMedia = lib.mkEnableOption "like_potplayer as the default player for common media types";
        };
        config = lib.mkIf config.programs.like_potplayer.enable {
          environment.systemPackages = [ (mkPackage pkgs) ];
          xdg.mime.defaultApplications = lib.mkIf config.programs.like_potplayer.defaultForMedia
            (lib.genAttrs mimeTypes (_: "like_potplayer.desktop"));
        };
      };

      homeManagerModules.default = { config, lib, pkgs, ... }: {
        options.programs.like_potplayer = {
          enable = lib.mkEnableOption "like_potplayer";
          defaultForMedia = lib.mkEnableOption "like_potplayer as the default player for common media types";
        };
        config = lib.mkIf config.programs.like_potplayer.enable {
          home.packages = [ (mkPackage pkgs) ];
          xdg.mimeApps = lib.mkIf config.programs.like_potplayer.defaultForMedia {
            enable = true;
            defaultApplications = lib.genAttrs mimeTypes (_: [ "like_potplayer.desktop" ]);
          };
        };
      };
    };
}
