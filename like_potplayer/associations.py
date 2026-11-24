"""Register / unregister like_potplayer as a default app for media files (per user, no admin rights)."""
import mimetypes
import os
import shutil
import subprocess
import sys
from pathlib import Path

# Several MIME names per extension: different shared-mime-info versions / file managers use different ones,
# and a double-click only works if the app is registered for the name the file manager picks.
MIME_ALIASES = {
    "mp4": ["video/mp4"], "m4v": ["video/x-m4v", "video/mp4"], "mkv": ["video/x-matroska"],
    "webm": ["video/webm"], "avi": ["video/x-msvideo", "video/avi", "video/vnd.avi"],
    "mov": ["video/quicktime"], "ts": ["video/mp2t"], "mpg": ["video/mpeg"], "mpeg": ["video/mpeg"],
    "wmv": ["video/x-ms-wmv"], "flv": ["video/x-flv"],
    "mp3": ["audio/mpeg", "audio/mp3"], "flac": ["audio/flac", "audio/x-flac"],
    "ogg": ["audio/ogg", "video/ogg", "application/ogg"], "opus": ["audio/ogg", "audio/opus", "audio/x-opus+ogg"],
    "wav": ["audio/x-wav", "audio/wav", "audio/vnd.wave"], "m4a": ["audio/mp4", "audio/x-m4a"],
    "aac": ["audio/aac", "audio/x-aac"], "wma": ["audio/x-ms-wma"], "ape": ["audio/x-ape"],
    "m3u": ["audio/x-mpegurl", "application/x-mpegurl"], "m3u8": ["application/vnd.apple.mpegurl", "audio/mpegurl"],
    "iso": ["application/x-iso9660-image"],
}


def enabled_exts(cfg):
    out = []
    for g in cfg.assoc.get("groups", {}).values():
        if g.get("enabled"):
            out += [e.lower().lstrip(".") for e in g.get("ext", [])]
    return sorted(set(out))


def mime_for(ext):
    return MIME_ALIASES.get(ext) or [m for m in [mimetypes.types_map.get("." + ext)] if m]


def mime_list(cfg):
    return sorted({m for e in enabled_exts(cfg) for m in mime_for(e)})


def _q(path):
    return '"' + str(path).replace("\\", "\\\\").replace('"', '\\"') + '"'


def launch_command():
    """Command that starts THIS installation. An AppImage must point at the .AppImage file itself:
    sys.executable lives in a temporary mount that disappears when the app exits."""
    if os.environ.get("APPIMAGE"):
        return _q(os.environ["APPIMAGE"])
    if getattr(sys, "frozen", False):
        return _q(sys.executable)
    exe = shutil.which("like_potplayer")      # installed console script / package wrapper
    if exe:
        return _q(exe)
    return f'{_q(sys.executable)} -m like_potplayer'


def desktop_entry(cfg, command=None):
    icon = cfg.app_id if cfg.icon_path("app") else "multimedia-video-player"
    return (
        "[Desktop Entry]\nType=Application\n"
        f"Name={cfg.app_name}\nGenericName=Media Player\n"
        "Comment=PotPlayer-style media player\n"
        f"Exec={command or launch_command()} %F\nIcon={icon}\nTerminal=false\n"
        "Categories=AudioVideo;Player;Video;Audio;\nKeywords=video;audio;movie;music;player;\n"
        f"MimeType={';'.join(mime_list(cfg))};\nStartupWMClass={cfg.app_id}\n")


def _data_home():
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))


def _conf_home():
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))


def _mimeapps_edit(path, desktop, mimes, add):
    """Edit [Default Applications] in mimeapps.list directly (what `xdg-mime default` does)."""
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    out, sect = [], None
    done = set()
    for ln in lines:
        if ln.startswith("["):
            if sect == "Default Applications" and add:
                out += [f"{m}={desktop}" for m in mimes if m not in done]
                done |= set(mimes)
            sect = ln.strip("[]")
            out.append(ln)
            continue
        if sect == "Default Applications" and "=" in ln:
            m, v = ln.split("=", 1)
            if m in mimes:
                if add:
                    out.append(f"{m}={desktop}"); done.add(m)
                elif v.strip(";") == desktop:
                    continue
                else:
                    out.append(ln)
                continue
        out.append(ln)
    if add:
        if sect != "Default Applications" and not any(l == "[Default Applications]" for l in out):
            out.append("[Default Applications]")
            out += [f"{m}={desktop}" for m in mimes]
        elif sect == "Default Applications":
            out += [f"{m}={desktop}" for m in mimes if m not in done]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def _system_desktop(desktop):
    """A launcher installed system-wide (e.g. by the .deb), if any."""
    for d in os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share").split(":"):
        p = Path(d) / "applications" / desktop
        if d and p.is_file() and not str(p).startswith(str(_data_home())):
            return p
    return None


def _linux_register(cfg, command=None):
    """Write the .desktop launcher, icons and per-user default-app entries. Returns the list of media types."""
    apps = _data_home() / "applications"
    apps.mkdir(parents=True, exist_ok=True)
    desktop = f"{cfg.app_id}.desktop"
    if command is None and _system_desktop(desktop):
        pass          # a package already installed a launcher with a stable path: only set the defaults
    else:
        (apps / desktop).write_text(desktop_entry(cfg, command), encoding="utf-8")
    icons = _data_home() / "icons" / "hicolor"
    ico = cfg.icon_path("app")
    if ico:
        (icons / "scalable" / "apps").mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ico, icons / "scalable" / "apps" / f"{cfg.app_id}{Path(ico).suffix}")
        for size in (48, 256):                    # PNGs for file managers that ignore SVG
            png = Path(ico).with_name(f"icon-{size}.png")
            if png.is_file():
                d = icons / f"{size}x{size}" / "apps"
                d.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(png, d / f"{cfg.app_id}.png")
    mimes = mime_list(cfg)
    _mimeapps_edit(_conf_home() / "mimeapps.list", desktop, mimes, add=True)
    for tool, args in (("update-desktop-database", [str(apps)]),
                       ("gtk-update-icon-cache", ["-q", "-t", "-f", str(icons)]),
                       ("kbuildsycoca6", []), ("kbuildsycoca5", [])):
        if shutil.which(tool):
            subprocess.run([tool, *args], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return mimes


def register(cfg):
    """Returns a human-readable result message."""
    if sys.platform.startswith("linux"):
        mimes = _linux_register(cfg)
        return (f"Registered {cfg.app_id}.desktop as the default for {len(mimes)} media types.\n"
                "Double-clicking a media file in your file manager should now open it here. Some desktops "
                "keep their own default until you confirm it in their settings.")
    if sys.platform == "win32":
        import winreg  # noqa: PLC0415
        prog = f"{cfg.app_id}.Media"
        cmd = f'{launch_command()} "%1"'
        base = r"Software\Classes"
        def put(path, name, val):
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, path) as k:
                winreg.SetValueEx(k, name, 0, winreg.REG_SZ, val)
        put(rf"{base}\{prog}", "", f"{cfg.app_name} media file")
        put(rf"{base}\{prog}\DefaultIcon", "", f'{launch_command()},0')
        put(rf"{base}\{prog}\shell\open\command", "", cmd)
        put(rf"Software\{cfg.app_id}\Capabilities", "ApplicationName", cfg.app_name)
        put(rf"Software\{cfg.app_id}\Capabilities", "ApplicationDescription", "PotPlayer-style media player")
        for e in enabled_exts(cfg):
            put(rf"Software\{cfg.app_id}\Capabilities\FileAssociations", f".{e}", prog)
            put(rf"{base}\.{e}\OpenWithProgids", prog, "")
        put(r"Software\RegisteredApplications", cfg.app_id, rf"Software\{cfg.app_id}\Capabilities")
        os.startfile("ms-settings:defaultapps")
        return ("Registered. Windows does not allow apps to set defaults silently: choose "
                f"{cfg.app_name} in Settings > Default apps (opened for you).")
    if sys.platform == "darwin":
        exts = enabled_exts(cfg)
        bundle = cfg.branding.get("bundle_id", f"org.{cfg.app_id}")
        if shutil.which("duti"):
            for e in exts:
                subprocess.run(["duti", "-s", bundle, f".{e}", "all"], check=False)
            return f"Set {bundle} as default for {len(exts)} extensions using duti."
        return ("macOS has no supported silent default change. In Finder: select a media file > Get Info > "
                "Open with > choose the app > Change All. (Or `brew install duti` and run this again.)")
    return "File associations are not supported on this platform."


def install(cfg):
    """Linux self-install. From an AppImage: copy it to ~/.local/bin, then register that copy
    (so the launcher keeps working after the original download is deleted). Elsewhere: just register."""
    if not sys.platform.startswith("linux"):
        return register(cfg)
    src = os.environ.get("APPIMAGE")
    if not src:
        return register(cfg)
    dest = Path.home() / ".local" / "bin" / f"{cfg.app_id}.AppImage"
    dest.parent.mkdir(parents=True, exist_ok=True)
    if Path(src).resolve() != dest.resolve():
        shutil.copyfile(src, dest)
    dest.chmod(0o755)
    mimes = _linux_register(cfg, _q(dest))
    note = "" if str(dest.parent) in os.environ.get("PATH", "") else f"\n(add {dest.parent} to PATH to run it from a terminal)"
    return (f"Installed to {dest}\nRegistered as the default for {len(mimes)} media types - double-click a media "
            f"file to play it.{note}")


def uninstall(cfg):
    msg = unregister(cfg)
    dest = Path.home() / ".local" / "bin" / f"{cfg.app_id}.AppImage"
    if dest.exists():
        dest.unlink()
        msg += f"\nRemoved {dest}"
    return msg


def unregister(cfg):
    if sys.platform.startswith("linux"):
        desktop = f"{cfg.app_id}.desktop"
        _mimeapps_edit(_conf_home() / "mimeapps.list", desktop, mime_list(cfg), add=False)
        (_data_home() / "applications" / desktop).unlink(missing_ok=True)
        icons = _data_home() / "icons" / "hicolor"
        for rel in ("scalable/apps/%s.svg", "48x48/apps/%s.png", "256x256/apps/%s.png"):
            (icons / (rel % cfg.app_id)).unlink(missing_ok=True)
        if shutil.which("update-desktop-database"):
            subprocess.run(["update-desktop-database", str(_data_home() / "applications")], check=False)
        return "Removed the launcher entry, icons and default-app settings."
    if sys.platform == "win32":
        import winreg  # noqa: PLC0415
        for path in (rf"Software\Classes\{cfg.app_id}.Media", rf"Software\{cfg.app_id}"):
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
            except OSError:
                pass
        return "Removed the registration (sub-keys may remain until the next sign-in)."
    return "Nothing to remove on this platform (change defaults in Finder)."
