# like_potplayer

A media player for **Linux, Windows and macOS** that looks and works like **Daum PotPlayer**.

**Why this exists.** like_potplayer is *inspired by Daum PotPlayer for Windows*. PotPlayer has no equivalent
version for macOS or Linux, so this project brings its keyboard-driven workflow, skinnable window and
"advanced control" bar to those systems. It is an independent project and is not affiliated with Kakao/Daum.

It is built with Python, **PySide6 (Qt 6)** and **libmpv**, so it plays whatever mpv plays (and web URLs through yt-dlp).

![status](https://img.shields.io/badge/status-alpha-orange)

## Features

- PotPlayer-style keys (function keys F1-F7, `C`/`X`/`Q` speed, `F`/`D` frame step, `[` `]` A-B repeat, ...) and mouse actions
- **Skins**: loads real PotPlayer skin files (`.dsf`), switch live from the right-click menu or `Ctrl+Alt+S`; built-in plain skin
- The bundled-look target skin is **BlackBoxVFD_PreMod3_AdvCtrl**: VFD digits, segmented sliders, codec/channel labels, A-B, bookmarks, filters
- Everything user-facing is **JSON**: hotkeys, mouse, app name, icons, file associations, macros
- In-app keyboard editor (F5), bookmark list (H), playlist save/load, slim (audio) mode, fullscreen with floating controls
- Single instance: opening a file while the player runs sends it to the running window
- Register as the default player for media files on every OS

## Build scripts: which one, where

| You want | Run this | On | Produces |
|---|---|---|---|
| Linux packages | `./build-linux.sh` | Debian/Ubuntu, Fedora, Arch... (needs libmpv) | AppImage, `.deb`, `.tar.gz` in `dist/` |
| Linux packages without installing anything | `./build-linux-container.sh` | any Linux with docker or podman, **including NixOS** | the same files, built in Ubuntu 22.04 (runs on older distros too) |
| NixOS / Nix | `./build-nixos.sh` (`install`, `run`, `check`) | NixOS or any system with Nix | `result/bin/like_potplayer`, installed into your profile |
| Windows | `.\build-windows.ps1 -Msi` | Windows 10/11, PowerShell | `setup.exe`, `.msi`, portable `.zip` in `dist\` |
| macOS | `packaging/macos/build.sh` | macOS | `.dmg` |
| **Test-build everything without owning every OS** | GitHub > Actions > *build* > Run workflow | GitHub's servers | all of the above as downloadable artifacts, with install tests |

A Windows `.exe`/`.msi` cannot be built from Linux or NixOS by these scripts (PyInstaller only builds for the OS it runs on);
use a Windows machine or the GitHub workflow.

## Linux: build, install, double-click

Two roles: **you only want to install it** (use a file from a release), or **you want to build the files yourself**.
Either way, afterwards a double-click on a video or audio file in your file manager opens it in like_potplayer.

### A. Install from a built file

```bash
# AppImage (one file; Ubuntu 22.04+ needs FUSE 2 first: sudo apt install libfuse2)
chmod +x like_potplayer-*.AppImage && ./like_potplayer-*.AppImage --install
#   -> copies itself to ~/.local/bin, adds a menu entry, registers as default player

# .deb (Debian, Ubuntu, Mint, Pop!_OS...)
sudo apt install ./like-potplayer_*.deb        # then start it once from the menu and answer "Yes" to the default-player question

# .tar.gz (any distro, no root, no FUSE)
tar xzf like_potplayer-*-linux-*.tar.gz && cd like_potplayer-*/ && ./install.sh

# remove again:   like_potplayer --uninstall    (tar.gz: ./install.sh --uninstall; deb: sudo apt remove like-potplayer)
```

### B. Build the packages yourself

```bash
# 1. prerequisites (once). libmpv is bundled into the result, so users do NOT need mpv installed.
sudo apt install python3 python3-venv libmpv2 curl      # Debian / Ubuntu
# sudo dnf install python3 mpv-libs curl                # Fedora
# sudo pacman -S python mpv curl                        # Arch

# 2. build. Output goes to ./dist ; takes several minutes the first time (it downloads Qt, PyInstaller, appimagetool)
./build-linux.sh                  # AppImage + .deb (if dpkg is available) + .tar.gz
./build-linux.sh appimage         # or only one of: appimage | deb | tarball

# 3. the script tests what it built (starts it, plays a clip in a virtual display) and prints the install commands
```

**Running inside `nix-shell` or on NixOS?** `./build-linux.sh` detects NixOS and builds in a container instead
(portable packages cannot be built against `/nix/store`), so you need podman or docker once:
`virtualisation.podman.enable = true;` in `configuration.nix`, then `sudo nixos-rebuild switch`.
To simply *use* the app on NixOS, `./build-nixos.sh install` needs no container. If your terminal prints the short message
`ERROR: libmpv not found. Debian/Ubuntu: ...` you are running an old copy of the script: re-extract the latest zip.

If it stops with **"libmpv was not found"** the script prints what it searched and the install command for your distro
(Ubuntu 22.04 / Mint 21 / Debian 11 call it `libmpv1`, newer ones `libmpv2`, Fedora `mpv-libs`, Arch `mpv`). Already installed
somewhere unusual? `LIBMPV=/path/to/libmpv.so.2 ./build-linux.sh`. No root, an odd distro, or NixOS? Use the container build:

```bash
./build-linux-container.sh        # needs docker or podman; downloads an Ubuntu 22.04 image once
```

What you get in `dist/`: `like_potplayer-<version>-<arch>.AppImage`, `like-potplayer_<version>_<arch>.deb`,
`like_potplayer-<version>-linux-<arch>.tar.gz`. The display name and icon come from `branding.json`.
Build on the oldest distro you want to support (the bundle uses that system's glibc). Options: `NO_VENV=1` (use the current
Python), `REFREEZE=1` (force a fresh bundle), `LIBMPV=/path/libmpv.so.2`.

### C. Check that double-click works

```bash
xdg-mime query default video/mp4        # should print: like_potplayer.desktop
gio open ~/Videos/some.mkv              # the same call a file manager makes: should open like_potplayer
like_potplayer --register-defaults      # re-apply the registration any time
tests/test_doubleclick.sh appimage      # automated version of the above (appimage | tarball | deb), needs xvfb
```

If a file manager still opens something else, that desktop keeps its own per-file-type choice: right-click a file >
Properties / Open With > like_potplayer > *Set as default*. If the picture is black or glitchy, try `like_potplayer --renderer sw`.

## NixOS

Portable AppImage/`.deb` files cannot be built *on* NixOS directly (they would point at `/nix/store`): use
`./build-linux-container.sh` for those. For NixOS itself, Nix builds and installs the app properly:

```bash
./build-nixos.sh                  # build, then test (starts, loads config, Qt + libmpv load, unit tests)
./build-nixos.sh install          # install into your profile and make it the default media player
./build-nixos.sh run movie.mkv    # build and play
nix run path:. -- movie.mkv       # without the script
nix run path:.#register-defaults  # only the default-player registration
```

Declarative install (recommended on NixOS) with this repo as a flake input:

```nix
# flake.nix of your system
inputs.like_potplayer.url = "github:YOU/like_potplayer";          # or "path:/home/you/src/like_potplayer"

# NixOS configuration
imports = [ inputs.like_potplayer.nixosModules.default ];
programs.like_potplayer = { enable = true; defaultForMedia = true; };    # adds the app + default player for common media types

# or home-manager
imports = [ inputs.like_potplayer.homeManagerModules.default ];
programs.like_potplayer = { enable = true; defaultForMedia = true; };
```

Status: the flake and scripts parse (checked with a Nix parser) but have **not been built** on a Nix machine yet.
If `nix build` fails, send the error and it can be fixed quickly; the GitHub workflow also builds it.

## Windows: build, install, double-click

### A. Install from a built file

```text
like_potplayer-0.4.0-setup.exe        per-user install, no administrator needed
    keep ticked: "Open video and audio files with like_potplayer (double-click)"
    on the last page tick "Choose like_potplayer in Windows 'Default apps'" -> in Settings pick it once for video/audio
like_potplayer-0.4.0-setup.exe /VERYSILENT /TASKS=assoc        silent install
like_potplayer-0.4.0-windows-portable.zip                      unzip anywhere and run; settings stay in .\data
msiexec /i like_potplayer-0.4.0-x64.msi /qn                    MSI for IT deployment: per-machine, needs admin, no wizard
```

Windows does not let any installer make itself the default app silently, so the one-time confirmation in
*Settings > Default apps* (or right-click a file > Open with > Choose another app > like_potplayer > Always) is required.
Until then the app appears in every "Open with" list. Selecting several files and pressing Enter opens them all in one window.
The installer is unsigned unless you sign it, so SmartScreen may say "unknown publisher": *More info > Run anyway*.

### B. Build the installer yourself

```powershell
# 1. prerequisites, once (PowerShell)
winget install Python.Python.3.12
winget install JRSoftware.InnoSetup
winget install Microsoft.DotNet.SDK.8      # only for the .msi
dotnet tool install --global wix           # only for the .msi (reopen PowerShell afterwards)

# 2. build into .\dist  (first run downloads libmpv ~120 MB, Qt and PyInstaller; takes several minutes)
.\build-windows.ps1 -Msi     # -Msi = also the .msi (built automatically when WiX is installed; -NoMsi skips it)
#    scripts blocked?  powershell -ExecutionPolicy Bypass -File .\build-windows.ps1
#    portable zip only: .\build-windows.ps1 -SkipInstaller      own libmpv: -LibMpv C:\libs\libmpv-2.dll

# 3. check the installer: silent install, file-association keys, start-up test, uninstall
.\tests\test-installer.ps1 -Msi      # -Msi also tests the .msi (open PowerShell as Administrator for that)
```

The script tests what it built (loads Qt and libmpv from the bundle, starts the window and checks it stays open), then writes
`dist\like_potplayer-<version>-setup.exe` and `dist\like_potplayer-<version>-windows-portable.zip` with checksums.
libmpv comes from [shinchiro/mpv-winbuild-cmake](https://github.com/shinchiro/mpv-winbuild-cmake) (a GPL build; see Licensing).
To sign, set `WIN_SIGN_PFX` and `WIN_SIGN_PASSWORD` before running (needs `signtool` from the Windows SDK).
The app name and icon come from `branding.json`; the file types registered by the installer come from `associations.json`.

### C. Check double-click

```powershell
Get-ItemProperty HKCU:\Software\Classes\like_potplayer.Media\shell\open\command    # shows the command Explorer runs
like_potplayer.exe --register-defaults      # re-apply (also opens Settings > Default apps)
like_potplayer.exe --self-test              # no window; result in %TEMP%\like_potplayer-selftest.txt, exit code 0 = ok
```

## macOS and running from source

```bash
# libmpv must be installed: macOS `brew install mpv`; Windows: put libmpv-2.dll next to the program or set LIKE_POTPLAYER_LIBMPV
python -m venv .venv && . .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install .
like_potplayer ~/Videos/movie.mkv                    # or:  python -m like_potplayer file...
```

NixOS / Nix: `nix run . -- movie.mkv`, `nix develop`, or the module in `flake.nix` (untested, see Status).

## Video output (renderer)

like_potplayer draws video either with the GPU (OpenGL) or with libmpv's software renderer (CPU, no OpenGL needed).
`auto` (default) uses software rendering when OpenGL is only a software rasterizer (virtual machines, remote desktops) and the
GPU otherwise. Force one with `--renderer gl|sw` or `LIKE_POTPLAYER_RENDER=gl|sw`. Software mode is fine for HD; use GPU for 4K.

## Skins

Put `.dsf` PotPlayer skins in the **user skins folder** (below) or in `./skins` next to the program, then
right-click > **Skin**, or press `Ctrl+Alt+S` to cycle, or start with `--skin NAME`. **Default (Qt)** is the built-in look.

The skin artwork belongs to its author. It is loaded from your files and is **never bundled** in releases;
copy your own `BlackBoxVFD_PreMod3_AdvCtrl.dsf` into the skins folder to get the look this project targets.
Other PotPlayer skins should load too (the loader reads layout from the skin's own XML) but only one has been tested.

## Configuration (all JSON, all optional)

| OS | Config folder |
|---|---|
| Linux / NixOS | `~/.config/like_potplayer/` |
| Windows | `%APPDATA%\like_potplayer\` |
| macOS | `~/Library/Application Support/like_potplayer/` |
| Portable | an empty file `portable.flag` next to the program -> `./data/` |

Order of precedence: built-in defaults < your files < `--config DIR` / `$LIKE_POTPLAYER_CONFIG`.
Run `like_potplayer --print-config` to see the merged result, `--list-actions` for every action id,
and reload a running player with `--reload` (or `Ctrl+Alt+R`). Mistakes are reported with file and line, and defaults keep working.

| File | What it controls |
|---|---|
| `hotkeys.json` | key -> action bindings |
| `mouse.json` | mouse gestures -> actions |
| `branding.json` | app name, window-title format, icons, default skin |
| `associations.json` | which extensions are registered as "default player" |
| `commands.json` | your own macros (sequences of actions) |
| `skins/*.dsf` | skins |

### Hotkeys

```json
{ "schema": 1,
  "bindings": [
    { "action": "toggle_pause", "keys": ["Space", "K"] },
    { "action": "seek", "args": [-10], "keys": ["J"] },
    { "action": "toggle_eq", "keys": [] }
  ] }
```

A binding replaces the default with the same `action` + `args`; an empty `keys` list unbinds it.
Key names are Qt's (`Ctrl+Shift+E`, `PgUp`, `F6`). The same editor is in **F5 > Keyboard**.
The shipped defaults are in `like_potplayer/defaults/hotkeys.json`; headline keys:

| Keys | Action |
|---|---|
| Space / Enter / Esc | Play-pause / fullscreen / leave fullscreen |
| Left, Right / Ctrl+Left, Ctrl+Right | Seek 5 s / 30 s |
| Up, Down / M | Volume / mute |
| C, X / Q (or Z) | Speed + / - / reset |
| F, D | Next / previous frame |
| PgUp, PgDn / Backspace / G | Previous, next file / restart / go to time |
| `[` `]` `\` | A-B repeat start / end / on-off |
| P, H | Add bookmark / bookmark list |
| `<` `>` `/` | Subtitle sync -0.5 s / +0.5 s / reset |
| L, A | Subtitle / audio track menu |
| Ctrl+E, Ctrl+C | Screenshot to file / clipboard |
| Ctrl+Z, Ctrl+V, J | Mirror / flip / aspect ratio |
| W E, R T, Y U, I O | Brightness, contrast, saturation, hue - / + |
| F1 F2 F3 F4 | About, open folder, open file, close file |
| F5 F6 F7 | Preferences, playlist, equalizer |

PotPlayer's real defaults came from a third-party list, so a few keys may differ from your PotPlayer; fix them in `hotkeys.json`.
Keys marked "extras" (e.g. `Ctrl+Alt+M` slim mode, `Ctrl+Shift+S` skin on/off) are this project's own.

### Mouse

Default: click = pause, double-click = fullscreen, wheel = volume, right-click = menu, title bar drag/double-click,
edge drag to resize. Rebind in `mouse.json` with `gesture` names `click double middle right x1 x2 wheel_up wheel_down`
(prefix `ctrl+`, `shift+`, `alt+` for wheel), e.g. `{ "gesture": "middle", "action": "toggle_mute" }`.

### App name and icons

```json
{ "schema": 1,
  "app_name": "My Player",
  "window_title_format": "{title} - {app_name}",
  "icons": { "app": "icons/app.svg" } }
```

Save as `branding.json` in the config folder; icon paths are relative to that file (SVG or PNG).
The internal id (`app_id`, default `like_potplayer`) keeps your settings in place when you rename the app.
`tools/make_icons.py master.svg` makes the PNG/ICO/ICNS set that installers use.

### Macros

```json
{ "schema": 1,
  "macros": { "jump90": [ { "action": "seek", "args": [90] } ] } }
```

Then bind `jump90` in `hotkeys.json` like any action. The `mpv` action runs raw mpv commands
(`run`/`subprocess`/script commands are blocked).

## Default player for media files

```bash
like_potplayer --register-defaults      # or F5 > Files and config > Register
like_potplayer --unregister-defaults
```

- **Linux**: writes a `.desktop` launcher and `mimeapps.list` entries (per user). Some desktops want one confirmation in their settings.
- **NixOS**: use `programs.like_potplayer.defaultForMedia = true`.
- **Windows**: registers the app, then opens *Settings > Default apps*; Windows does not let apps switch defaults silently.
- **macOS**: no supported silent change; the app prints the Finder steps (or uses `duti` if installed).

## Command line

```text
like_potplayer [files...] [--skin NAME] [--renderer auto|gl|sw] [--config DIR] [--enqueue] [--fullscreen] [--slim]
               [--reload] [--print-config] [--list-actions]
               [--install] [--uninstall]                       # Linux AppImage: add/remove menu entry + default player
               [--register-defaults] [--unregister-defaults] [--version]
```

## Building and distributing

All builds are scripts under `packaging/`; the app name and icon come from `branding.json` (override at build time with `branding.override.json`).

```bash
# Linux  : see 'Linux: build, install, double-click' above
./build-linux.sh
# Windows: see 'Windows: build, install, double-click' above
.\build-windows.ps1
# macOS  : .app + .dmg (SIGN_ID / NOTARY_PROFILE enable signing and notarization)
packaging/macos/build.sh
# Nix    : nix build
```

`.github/workflows/release.yml` runs tests and all builds on a version tag and attaches the files plus checksums to a release.

## Testing

```bash
pip install pytest && pytest tests/test_config.py                       # config + registry, no display
QT_QPA_PLATFORM=xcb LIBGL_ALWAYS_SOFTWARE=1 xvfb-run -a python tests/smoke_gui.py clip.mp4   # GUI smoke test (Linux)
xvfb-run -a tests/test_doubleclick.sh appimage     # install a built package and open a file like a file manager does
```

## Status

Alpha. **Linux (non-Nix)** has been run end to end on Ubuntu with a virtual display: `./build-linux.sh` -> AppImage, .deb and
.tar.gz, each installed into a clean user profile and opened through `gio open` (the call a file manager makes): launcher valid,
defaults registered for 34 media types, the right player starts with the file, picture visible, a second double-click reuses the
open window, uninstall cleans up (`tests/test_doubleclick.sh`).

**Windows** is written but has not been run on Windows. Checked so far on Linux: both PowerShell scripts parse; the libmpv
download step ran for real and fetched the 64-bit `libmpv-2.dll`; the file-association registry code passes tests with a fake
registry, and the installer's generated registry entries match it key for key. Not run: PyInstaller on Windows, the Inno Setup
compile, the installer itself, Explorer double-click. Treat the first Windows build as a test: run `tests\test-installer.ps1`.

Also run: JSON hotkeys/mouse/branding, skin switching, keyboard editor, single instance. Not run yet: macOS builds, the Nix flake,
the CI workflow, Wayland move/resize, the GPU (OpenGL) renderer on real hardware (the software renderer is what was tested),
other Linux distros and file managers. Not implemented: PotPlayer's other skin XMLs, text colour themes, file navigator (F12),
DVD/TV/capture features.

## Licensing

Project license: **not chosen yet.** Note that libmpv builds are usually GPL and PySide6 is LGPL, which affects how
binaries that bundle them can be distributed. PotPlayer is a trademark of its owners; skin artwork belongs to its authors.
