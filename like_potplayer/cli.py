"""Command line + single-instance handling for like_potplayer."""
import argparse
import getpass
import json
import locale
import os
import sys
import tempfile
import time
from pathlib import Path

from . import actions, config as cfgmod

VERSION = "0.4.0"
LAST_PLAYER = None   # set for tests


def build_parser():
    p = argparse.ArgumentParser(prog="like_potplayer", description="PotPlayer-style media player (Linux, Windows, macOS).")
    p.add_argument("paths", nargs="*", help="files, folders or URLs to play")
    p.add_argument("--skin", help="skin name (a .dsf in a skins folder), a path, or 'default'")
    p.add_argument("--config", metavar="DIR", help="use this config directory")
    p.add_argument("--renderer", choices=["auto", "gl", "sw"], default=None,
                   help="video output: gl = GPU (OpenGL), sw = software (works everywhere), auto = pick (default)")
    p.add_argument("--enqueue", action="store_true", help="add to the playlist instead of replacing it")
    p.add_argument("--fullscreen", action="store_true")
    p.add_argument("--slim", action="store_true", help="start in slim (audio bar) mode")
    p.add_argument("--reload", action="store_true", help="tell the running instance to re-read its config")
    p.add_argument("--print-config", action="store_true", help="print the effective merged config and exit")
    p.add_argument("--list-actions", action="store_true", help="list every action id usable in hotkeys/mouse JSON")
    p.add_argument("--register-defaults", action="store_true", help="register as default player for media files")
    p.add_argument("--unregister-defaults", action="store_true")
    p.add_argument("--install", action="store_true",
                   help="Linux: install this AppImage for the current user (menu entry + double-click on media files)")
    p.add_argument("--uninstall", action="store_true", help="undo --install / --register-defaults")
    p.add_argument("--self-test", action="store_true",
                   help="check that Qt and libmpv load; writes the result to <temp>/like_potplayer-selftest.txt, exit 0 = ok")
    p.add_argument("--version", action="store_true")
    return p


def _abs(paths):
    return [p if "://" in p else os.path.abspath(p) for p in paths]


def _console_for_windowed_exe():
    """A Windows GUI-subsystem exe has no stdout. Attach to the parent console so --help/--version print."""
    if sys.platform == "win32" and getattr(sys, "frozen", False) and sys.stdout is None:
        try:
            import ctypes
            if ctypes.windll.kernel32.AttachConsole(-1):
                sys.stdout = sys.stderr = open("CONOUT$", "w", encoding="utf-8")
        except Exception:
            pass
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")


def self_test():
    lines, ok = [], True
    try:
        import PySide6
        lines.append(f"Qt bindings ok: PySide6 {PySide6.__version__}")
    except Exception as e:  # noqa: BLE001
        ok = False; lines.append(f"Qt bindings FAILED: {e}")
    try:
        from . import _libmpv  # noqa: F401
        import mpv
        locale.setlocale(locale.LC_NUMERIC, "C")
        m = mpv.MPV(vo="null", ao="null", idle=True)
        lines.append(f"libmpv ok: {m.mpv_version}")
        m.terminate()
    except Exception as e:  # noqa: BLE001
        ok = False; lines.append(f"libmpv FAILED: {e}")
    out = Path(tempfile.gettempdir()) / "like_potplayer-selftest.txt"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0 if ok else 1


def main(argv=None):
    _console_for_windowed_exe()
    args = build_parser().parse_args(argv)
    if args.self_test:
        return self_test()
    cfg = cfgmod.Config(args.config)
    if args.version:
        print(f"like_potplayer {VERSION}"); return 0
    if args.list_actions:
        print(actions.describe()); return 0
    if args.print_config:
        print(json.dumps(cfg.effective(), indent=2)); return 0
    if args.register_defaults or args.unregister_defaults or args.install or args.uninstall:
        from . import associations
        if args.install:
            print(associations.install(cfg))
        elif args.uninstall:
            print(associations.uninstall(cfg))
        else:
            print(associations.register(cfg) if args.register_defaults else associations.unregister(cfg))
        return 0

    from PySide6.QtCore import QTimer
    from PySide6.QtNetwork import QLocalServer, QLocalSocket
    from PySide6.QtWidgets import QApplication

    if sys.platform == "win32":                     # lets the taskbar group windows and show the right icon
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(cfg.app_id)
        except Exception:
            pass
    app = QApplication([sys.argv[0]])
    locale.setlocale(locale.LC_NUMERIC, "C")   # libmpv requires this
    server_name = f"{cfg.app_id}-{getpass.getuser()}"
    payload = {"paths": _abs(args.paths), "enqueue": args.enqueue, "reload": args.reload,
               "skin": args.skin, "fullscreen": args.fullscreen, "slim": args.slim}

    # single instance: hand the request to a running copy and leave
    sock = QLocalSocket()
    sock.connectToServer(server_name)
    if sock.waitForConnected(300):
        sock.write(json.dumps(payload).encode()); sock.flush(); sock.waitForBytesWritten(1000)
        sock.disconnectFromServer()
        return 0
    if args.reload:
        print("like_potplayer is not running", file=sys.stderr); return 1

    from .app import Player
    global LAST_PLAYER
    w = LAST_PLAYER = Player(cfg, skin_name=args.skin, renderer=args.renderer)
    for e in cfg.errors:
        print(f"[like_potplayer] config: {e}", file=sys.stderr)
    w.show()

    last_open = [0.0]

    def handle(d):
        if d.get("reload"):
            w.a_reload_config()
        if d.get("skin"):
            w.a_skin_set(d["skin"])
        if d.get("paths"):
            # Explorer starts one process per selected file: requests arriving within 1.5 s of each other
            # belong together, so later ones are added to the playlist instead of replacing it.
            now = time.monotonic()
            w.open_paths(d["paths"], enqueue=d.get("enqueue", False) or (now - last_open[0] < 1.5))
            last_open[0] = now
        if d.get("slim") and not w.slim:
            w.a_toggle_slim()
        if d.get("fullscreen") and not w.fullscreen:
            w.a_toggle_fullscreen()
        w.showNormal() if w.isMinimized() else None
        w.raise_(); w.activateWindow()

    server = QLocalServer()
    QLocalServer.removeServer(server_name)
    server.listen(server_name)

    def on_conn():
        c = server.nextPendingConnection()
        def read():
            try:
                handle(json.loads(bytes(c.readAll()).decode()))
            except (ValueError, KeyError) as ex:
                print(f"[like_potplayer] bad request: {ex}", file=sys.stderr)
        c.readyRead.connect(read)
    server.newConnection.connect(on_conn)
    w._server = server
    QTimer.singleShot(150, lambda: handle({k: v for k, v in payload.items() if k != "reload"}))
    if not args.paths:                                  # a double-click start should just play, never ask
        QTimer.singleShot(1200, w.maybe_ask_defaults)
    code = app.exec()
    server.close()
    return code
