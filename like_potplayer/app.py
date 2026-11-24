#!/usr/bin/env python3
"""
like_potplayer - a PotPlayer-style media player for Linux, Windows and macOS.
Stack: PySide6 (Qt 6) + libmpv (render API). Inspired by Daum PotPlayer for Windows.

Keys, mouse, branding and skins are data: see like_potplayer/defaults/*.json and the README.
Debug env knobs: LIKE_POTPLAYER_DEBUG=1 (mpv log), LIKE_POTPLAYER_FLIP=0|1 (picture upside down?),
                 LIKE_POTPLAYER_RGBA=1 (picture black?), LIKE_POTPLAYER_BLOCK=1
"""
import json
import locale
import os
import random
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtCore import QPoint, QSettings, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QActionGroup, QCursor, QIcon, QImage, QKeySequence, QOpenGLContext, QShortcut
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QInputDialog, QLabel,
    QListWidget, QMenu, QMessageBox, QPushButton, QSlider, QStyle, QTabWidget, QTableWidget,
    QTableWidgetItem, QToolTip, QVBoxLayout, QWidget,
)


from . import actions, associations, config as cfgmod, dsfskin
from .video import make_view

APP = "like_potplayer"
MEDIA_EXT = {
    ".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv", ".wmv", ".m4v", ".ts", ".mpg", ".mpeg",
    ".mp3", ".flac", ".ogg", ".opus", ".wav", ".m4a", ".aac", ".wma", ".ape",
}
SUB_EXT = "Subtitles (*.srt *.ass *.ssa *.sub *.vtt);;All files (*)"
ENV = lambda n: os.environ.get("LIKE_POTPLAYER_" + n)

QSS = """
QWidget { background:#1b212c; color:#c9d3e3; }
QPushButton { background:transparent; border:none; padding:4px; border-radius:4px; }
QPushButton:hover { background:#3a4458; } QPushButton:pressed { background:#2fb4ff; }
QLabel#time { color:#7fd0ff; font-family:monospace; }
QSlider::groove:horizontal { height:5px; background:#0a0e14; border-radius:2px; }
QSlider::sub-page:horizontal { background:#2fb4ff; border-radius:2px; }
QSlider::handle:horizontal { background:#e1e9f5; width:10px; margin:-5px 0; border-radius:3px; }
QListWidget { background:#141922; border:none; } QListWidget::item:selected { background:#2fb4ff; color:#0f131a; }
QMenu { background:#232a37; border:1px solid #3a4458; } QMenu::item:selected { background:#2fb4ff; color:#0f131a; }
"""


def fmt(t):
    t = int(max(0, t or 0))
    return f"{t // 3600:02d}:{t // 60 % 60:02d}:{t % 60:02d}"


# --------------------------------------------------------------------------- video widget
class ClickSlider(QSlider):
    """Horizontal slider: click/drag anywhere jumps there; emits a 0..1 fraction."""
    fraction = Signal(float)

    def __init__(self, maximum=1000):
        super().__init__(Qt.Horizontal)
        self.setRange(0, maximum)
        self.setFocusPolicy(Qt.NoFocus)
        self.setMouseTracking(True)

    def _frac(self, e):
        return min(1.0, max(0.0, e.position().x() / max(1, self.width())))

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            f = self._frac(e)
            self.setValue(round(f * self.maximum()))
            self.setSliderDown(True)
            self.fraction.emit(f)
            e.accept()

    def mouseMoveEvent(self, e):
        f = self._frac(e)
        if self.isSliderDown():
            self.setValue(round(f * self.maximum()))
            self.fraction.emit(f)
        t = getattr(self, "tip_fn", None)
        if t:
            QToolTip.showText(e.globalPosition().toPoint(), t(f), self)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.setSliderDown(False)


# --------------------------------------------------------------------------- main window
class Player(QWidget):
    """Main window. Everything user-facing is driven by `cfg` (JSON) and the active skin."""

    def __init__(self, cfg, skin_name=None, renderer=None):
        super().__init__()
        self.cfg = cfg
        self.setAcceptDrops(True)
        self.setWindowFlag(Qt.FramelessWindowHint, True)   # always frameless: every skin draws its own frame
        self.settings = QSettings(cfg.app_id, cfg.app_id)
        self.items, self.index = [], -1
        self.pos = self.dur = 0.0
        self.shuffle, self.repeat = False, "off"      # repeat: off | one | all
        self.fullscreen = self.slim = self.auto_slimmed = False
        self._normal_geo = None
        self._eof = False
        self._ab_saved = None
        self._shortcuts = []
        self.mouse_map = {}
        self.st = SimpleNamespace(
            pos=0.0, dur=0.0, volume=80.0, speed=1.0, mute=False, paused=True, toggles={},
            vcodec="", acodec="", channels=0, vbr=0, abr=0, ab_a=None, ab_b=None, filetype="")
        self.skin = None
        self.chrome = []

        self.view = make_view(renderer)
        self.mpv = self.view.mpv
        v = self.view
        v.prop.connect(self.on_prop)
        v.clicked.connect(self._on_click)
        v.double_clicked.connect(self._on_double)
        v.gesture.connect(self.on_gesture)
        v.context.connect(self._on_right)
        v.moved.connect(self.on_mouse_move)
        self._click_timer = QTimer(self, singleShot=True)
        self._click_timer.timeout.connect(lambda: self.on_gesture("click"))
        self._idle = QTimer(self, singleShot=True, interval=2000)
        self._idle.timeout.connect(self.hide_idle)

        self.list = QListWidget()
        self.list.setFocusPolicy(Qt.NoFocus)
        self.list.itemDoubleClicked.connect(lambda it: self.play_index(self.list.row(it)))
        self.playlist_panel = self.list
        self.playlist_panel.setMinimumWidth(240)
        self.playlist_panel.hide()
        self.stage = QWidget()   # picture + playlist; hidden as one unit in slim mode
        row = QHBoxLayout(self.stage); row.setContentsMargins(0, 0, 0, 0); row.setSpacing(0)
        row.addWidget(self.view, 1); row.addWidget(self.playlist_panel)

        self.root = QVBoxLayout(self); self.root.setContentsMargins(0, 0, 0, 0); self.root.setSpacing(0)
        self.mid = QHBoxLayout(); self.mid.setSpacing(0)
        self.controls_layout = QVBoxLayout(); self.controls_layout.setSpacing(0)
        self.controls_layout.addWidget(self.stage, 1)
        self.setStyleSheet(QSS)
        self.resize(1024, 640)

        self.bookmarks = json.loads(self.settings.value("bookmarks", "{}"))
        self.mpv.volume = float(self.settings.value("volume", 80))
        self.apply_branding()
        self.rebind()
        # initial skin: CLI/arg > saved choice > branding default > any bundled skin > plain Qt
        want = skin_name or self.settings.value("skin") or cfg.branding.get("default_skin")
        self._first_chrome = True
        self.set_skin_by_name(want or "default", remember=False, first=True)

    # ---- branding, skins -----------------------------------------------------
    def apply_branding(self):
        ico = self.cfg.icon_path("app")
        if ico:
            icon = QIcon(ico)
            self.setWindowIcon(icon)
            QApplication.instance().setWindowIcon(icon)
        QApplication.instance().setApplicationName(self.cfg.app_name)
        self.setWindowTitle(self.cfg.app_name)

    def discover_skins(self):
        found = {}
        for d in cfgmod.skin_dirs(self.cfg.dir):
            if d.is_dir():
                for f in sorted(d.glob("*.dsf")):
                    found.setdefault(f.stem, f)
        extra = ENV("SKIN")
        if extra and extra.lower() != "none" and Path(extra).is_file():
            found.setdefault(Path(extra).stem, Path(extra))
        return found

    def set_skin_by_name(self, name, remember=True, first=False):
        if self.fullscreen:
            return False
        sk = None
        if name and name.lower() not in ("default", "none", "default (qt)"):
            path = self.discover_skins().get(name) or (Path(name) if Path(name).is_file() else None)
            if path is None:
                self.report(f"Skin '{name}' not found")
            else:
                try:
                    sk = dsfskin.Skin(path)
                except Exception as e:
                    self.report(f"Could not load skin '{name}': {e}")
        self._install_chrome(sk)
        if remember:
            self.settings.setValue("skin", sk.name if sk else "default")
        return True

    def report(self, msg):
        print(f"[{APP}] {msg}", file=sys.stderr)
        if hasattr(self, "controls"):
            self.osd(msg)

    def _install_chrome(self, sk):
        """Create title bar / borders / control bar for `sk` (None = plain Qt) and swap them in live."""
        old = [getattr(self, n, None) for n in ("titlebar", "bl", "br", "bb", "controls")]
        if sk:
            controls = dsfskin.AdvBar(sk, self)
            title = dsfskin.TitleBar(sk, self)
        else:
            controls = self._build_controls()
            title = dsfskin.PlainTitleBar(self)
        bl, br, bb = (dsfskin.Border(sk, k) for k in ("left", "right", "bottom"))
        new = [title, bl, br, bb, controls]
        self.skin = sk
        if old[0] is None:                               # first build
            self.root.addWidget(title)
            self.mid.addWidget(bl); self.mid.addLayout(self.controls_layout, 1); self.mid.addWidget(br)
            self.root.addLayout(self.mid, 1)
            self.root.addWidget(bb)
            self.controls_layout.addWidget(controls)
        else:
            self.root.replaceWidget(old[0], title)
            self.mid.replaceWidget(old[1], bl); self.mid.replaceWidget(old[2], br)
            self.root.replaceWidget(old[3], bb)
            self.controls_layout.replaceWidget(old[4], controls)
            for w in old:
                w.hide(); w.deleteLater()
        self.titlebar, self.bl, self.br, self.bb, self.controls = new
        self.chrome = [self.titlebar, self.bl, self.br, self.bb]
        self.setMinimumSize(*((460, 320) if sk else (420, 240)))
        if self.slim:
            self.setMinimumHeight(0)
        self.titlebar.title = self.windowTitle()
        if not sk:
            self.seek.tip_fn = lambda f: fmt(f * self.dur)
            self._sync_plain()
        for w in new:
            w.show()
        self.update()

    def _sync_plain(self):
        st = self.st
        self.update_time()
        self.b_play.setIcon(self._icon(QStyle.SP_MediaPlay if st.paused else QStyle.SP_MediaPause))
        self.vol.blockSignals(True); self.vol.setValue(int(st.volume)); self.vol.blockSignals(False)
        self.b_mute.setIcon(self._icon(QStyle.SP_MediaVolumeMuted if st.mute else QStyle.SP_MediaVolume))
        self.speed_lbl.setText(f"{st.speed:.2f}x".replace(".00x", ".0x"))

    def a_skin_next(self):
        names = ["default"] + list(self.discover_skins())
        cur = self.skin.name if self.skin else "default"
        self.a_skin_set(names[(names.index(cur) + 1) % len(names)] if cur in names else names[0])

    def a_skin_set(self, name):
        if self.set_skin_by_name(name):
            self.osd("Skin: " + (self.skin.name if self.skin else "Default (Qt)"))

    # ---- bindings -------------------------------------------------------------
    def rebind(self):
        for sc in self._shortcuts:
            sc.setEnabled(False); sc.setParent(None); sc.deleteLater()
        self._shortcuts = []
        seen = {}
        for b in self.cfg.hotkeys:
            for k in b["keys"]:
                ks = QKeySequence(k)
                if ks.isEmpty():
                    self.cfg.errors.append(f"hotkeys: cannot parse key '{k}' for {b['action']}")
                    continue
                ident = ks.toString()
                if ident in seen:
                    self.cfg.errors.append(f"hotkeys: '{k}' is bound to both {seen[ident]} and {b['action']}")
                seen[ident] = b["action"]
                sc = QShortcut(ks, self)
                sc.setContext(Qt.ApplicationShortcut)
                sc.activated.connect(lambda a=b["action"], g=list(b.get("args", [])): self.run(a, g))
                self._shortcuts.append(sc)
        self.mouse_map = {m["gesture"].lower(): (m["action"], list(m.get("args", []))) for m in self.cfg.mouse}
        for e in self.cfg.errors:
            print(f"[{APP}] config: {e}", file=sys.stderr)

    def run(self, action, args=(), _depth=0):
        """Run a registry action (or a user macro) by id."""
        steps = actions.macro(action)
        if steps is not None:
            if _depth > 5:
                return
            for st in steps:
                self.run(st.get("action", ""), st.get("args", []), _depth + 1)
            return
        fn = getattr(self, "a_" + action, None)
        if fn is None:
            self.report(f"Action '{action}' is not available")
            return
        try:
            fn(*args)
        except Exception as e:  # a bad binding must never take the player down
            self.report(f"{action} failed: {e}")

    def on_gesture(self, name):
        hit = self.mouse_map.get(name.lower())
        if hit:
            self.run(hit[0], hit[1])

    def _on_click(self):
        if "double" in self.mouse_map:
            self._click_timer.start(QApplication.doubleClickInterval())
        else:
            self.on_gesture("click")

    def _on_double(self):
        self._click_timer.stop()
        self.on_gesture("double")

    def _on_right(self, gpos):
        if "right" in self.mouse_map:
            self.on_gesture("right")
        else:
            self.context_menu(gpos)

    def a_reload_config(self):
        self.cfg.reload()
        self.apply_branding()
        self.rebind()
        n = len(self.cfg.errors)
        self.osd("Config reloaded" + (f" ({n} problem(s), see terminal)" if n else ""))

    # ---- UI
    def _icon(self, sp):
        return self.style().standardIcon(sp)

    def _btn(self, sp, tip, fn):
        b = QPushButton()
        b.setIcon(self._icon(sp)); b.setToolTip(tip); b.setFocusPolicy(Qt.NoFocus)
        b.clicked.connect(fn)
        return b

    def _build_controls(self):
        w = QWidget()
        col = QVBoxLayout(w); col.setContentsMargins(8, 4, 8, 6); col.setSpacing(2)
        self.seek = ClickSlider(1000)
        self.seek.fraction.connect(self.seek_fraction)
        col.addWidget(self.seek)
        row = QHBoxLayout(); row.setSpacing(2)
        self.b_play = self._btn(QStyle.SP_MediaPlay, "Play/Pause (Space)", lambda: self.do("toggle_pause"))
        row.addWidget(self.b_play)
        row.addWidget(self._btn(QStyle.SP_MediaStop, "Stop", lambda: self.do("stop")))
        row.addWidget(self._btn(QStyle.SP_MediaSkipBackward, "Previous (PgUp)", lambda: self.do("prev")))
        row.addWidget(self._btn(QStyle.SP_MediaSkipForward, "Next (PgDn)", lambda: self.do("next")))
        row.addWidget(self._btn(QStyle.SP_DirOpenIcon, "Open file(s) (F3)", lambda: self.do("open_files")))
        self.time = QLabel("00:00:00 / 00:00:00"); self.time.setObjectName("time")
        row.addSpacing(8); row.addWidget(self.time); row.addStretch(1)
        self.speed_lbl = QLabel("1.0x"); row.addWidget(self.speed_lbl)
        self.b_mute = self._btn(QStyle.SP_MediaVolume, "Mute (M)", lambda: self.do("toggle_mute"))
        row.addWidget(self.b_mute)
        self.vol = ClickSlider(130); self.vol.setFixedWidth(90)
        self.vol.fraction.connect(lambda f: setattr(self.mpv, "volume", round(f * 130)))
        row.addWidget(self.vol)
        row.addWidget(self._btn(QStyle.SP_TitleBarMaxButton, "Fullscreen (Enter)", lambda: self.do("toggle_fullscreen")))
        row.addWidget(self._btn(QStyle.SP_FileDialogDetailedView, "Playlist (F6)", lambda: self.do("toggle_playlist")))
        row.addWidget(self._btn(QStyle.SP_TitleBarShadeButton, "Slim mode (Ctrl+M)", lambda: self.do("toggle_slim")))
        col.addLayout(row)
        return w

    # ---- command dispatcher (keys, mouse, buttons, menu all go through here)
    def do(self, action):
        """Internal helper: str id, or (id, arg) tuple (used by the skin bar)."""
        if isinstance(action, tuple):
            self.run(action[0], [action[1]])
        elif action == "context_menu":
            self.context_menu(self.cursor().pos())
        else:
            self.run(action, [])

    def osd(self, text):
        try:
            self.mpv.command("show-text", text, 1200)
        except Exception:
            pass

    def a_toggle_pause(self):
        if self.index < 0 and self.items:
            self.play_index(0)
        else:
            self.mpv.pause = not self.mpv.pause

    def a_stop(self):
        self.mpv.command("stop"); self.pos = self.dur = 0; self.update_time()

    def a_seek(self, d):
        self.mpv.command("seek", d, "relative")

    def a_volume(self, d):
        v = max(0, min(130, (self.mpv.volume or 0) + d))
        self.mpv.volume = v; self.osd(f"Volume {int(v)}%")

    def a_toggle_mute(self):
        self.mpv.mute = not self.mpv.mute

    def a_speed(self, d):
        s = round(max(0.1, min(8.0, (self.mpv.speed or 1.0) + d)), 2)
        self.mpv.speed = s; self.osd(f"Speed {s}x")

    def a_speed_reset(self):
        self.mpv.speed = 1.0; self.osd("Speed 1.0x")

    def a_frame_forward(self):
        self.mpv.command("frame-step")

    def a_frame_back(self):
        self.mpv.command("frame-back-step")

    def a_screenshot(self):
        self.mpv.command("screenshot"); self.osd("Screenshot saved to ~/Pictures/like_potplayer")

    def a_prev(self):
        if self.items:
            self.play_index(max(0, self.index - 1))

    def a_next(self, auto=False):
        if not self.items:
            return
        if auto and self.repeat == "one":
            return self.play_index(self.index)
        i = random.randrange(len(self.items)) if self.shuffle else self.index + 1
        if i >= len(self.items):
            if self.repeat == "all":
                i = 0
            else:
                return
        self.play_index(i)

    def a_open_files(self):
        exts = " ".join("*" + e for e in sorted(MEDIA_EXT))
        files, _ = QFileDialog.getOpenFileNames(self, "Open", str(Path.home()), f"Media ({exts});;All files (*)")
        if files:
            self.add_paths(files)

    def a_open_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Open folder", str(Path.home()))
        if d:
            self.add_paths([d])

    def a_open_url(self):
        url, ok = QInputDialog.getText(self, "Open URL", "URL:")
        if ok and url.strip():
            self.add_paths([url.strip()])

    def a_open_sub(self):
        f, _ = QFileDialog.getOpenFileName(self, "Subtitle", str(Path.home()), SUB_EXT)
        if f:
            self.mpv.command("sub-add", f, "select")

    def a_toggle_playlist(self):
        self.playlist_panel.setVisible(not self.playlist_panel.isVisible())

    def a_toggle_on_top(self):
        self.setWindowFlag(Qt.WindowStaysOnTopHint, not bool(self.windowFlags() & Qt.WindowStaysOnTopHint))
        self.show()

    def a_quit(self):
        self.close()

    # fullscreen: controls float over the video so the picture never resizes
    def a_toggle_fullscreen(self):
        self.leave_fs() if self.fullscreen else self.enter_fs()

    def a_leave_fullscreen(self):
        if self.fullscreen:
            self.leave_fs()

    def enter_fs(self):
        if self.slim:
            self.a_toggle_slim()
        self.fullscreen = True
        for w in self.chrome:
            w.hide()
        self.controls_layout.removeWidget(self.controls)
        self.controls.setParent(self.view)
        self.playlist_panel.hide()
        self.showFullScreen()
        self.place_overlay(); self.controls.hide(); self._idle.start()

    def leave_fs(self):
        self.fullscreen = False
        self.view.setCursor(Qt.ArrowCursor)
        self.controls.setParent(self)
        self.controls_layout.addWidget(self.controls)
        self.controls.show()
        for w in self.chrome:
            w.show()
        self.showNormal()

    def place_overlay(self):
        h = self.controls.height() if self.skin else self.controls.sizeHint().height()
        self.controls.setGeometry(0, self.view.height() - h, self.view.width(), h)
        self.controls.raise_()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.fullscreen:
            self.place_overlay()

    def on_mouse_move(self, x, y):
        self.view.setCursor(Qt.ArrowCursor)
        if self.fullscreen:
            if y > self.view.height() * 0.85:
                self.place_overlay(); self.controls.show()
            self._idle.start()

    def hide_idle(self):
        if self.fullscreen:
            if not self.controls.underMouse():
                self.controls.hide()
                self.view.setCursor(Qt.BlankCursor)
            else:
                self._idle.start()


    # JetAudio-Slimbar-like compact mode: hides picture + playlist
    def a_toggle_slim(self):
        if self.fullscreen:
            return
        if not self.slim:
            self._normal_geo = self.saveGeometry()
            self.slim = True
            self.stage.hide(); self.playlist_panel.hide()
            self.setFixedHeight(sum(w.height() for w in self.chrome[:1] + self.chrome[3:]) + self.controls.height()
                                if self.skin else self.controls.sizeHint().height())
            self.resize(680, self.height())
        else:
            self.slim = False
            self.setMinimumHeight(0); self.setMaximumHeight(16777215)
            self.stage.show()
            if self._normal_geo:
                self.restoreGeometry(self._normal_geo)
        self.auto_slimmed = False

    # ---- playlist
    def open_paths(self, paths, enqueue=False):
        """Open from the command line / another instance: replace the playlist, or enqueue."""
        if not enqueue:
            self.items.clear(); self.list.clear(); self.index = -1
        self.add_paths(paths, play=not enqueue or self.index < 0)

    def add_paths(self, paths, play=True):
        new = []
        for p in paths:
            if "://" in p:
                new.append(p)
            elif os.path.isdir(p):
                new += sorted(str(f) for f in Path(p).rglob("*") if f.suffix.lower() in MEDIA_EXT)
            elif os.path.exists(p):
                new.append(os.path.abspath(p))
        start = len(self.items)
        for p in new:
            self.items.append(p)
            self.list.addItem(os.path.basename(p) or p)
        if new and play:
            self.play_index(start)

    def save_position(self):
        if self.index < 0:
            return
        try:
            self.mpv.command("delete-watch-later-config" if self._eof else "write-watch-later-config")
        except Exception:
            pass

    def play_index(self, i):
        if not 0 <= i < len(self.items):
            return
        self.save_position()
        self._eof = False
        ext = os.path.splitext(self.items[i])[1].lstrip(".").lower()
        self.st.filetype = dsfskin.EXT_TYPE.get(ext, "etc")
        self.index = i
        self.list.setCurrentRow(i)
        self.mpv.pause = False          # set BEFORE loading: a sync property call right after
        self.mpv.play(self.items[i])    # loadfile can stall the UI thread while mpv opens the VO

    # ---- mpv -> UI
    def on_prop(self, name, v):
        st = self.st
        if name == "time-pos":
            self.pos = st.pos = v or 0.0
        elif name == "duration":
            self.dur = st.dur = v or 0.0
        elif name == "pause":
            st.paused = bool(v)
        elif name == "volume" and v is not None:
            st.volume = float(v)
        elif name == "mute":
            st.mute = bool(v)
        elif name == "speed" and v:
            st.speed = float(v)
        elif name == "video-bitrate":
            st.vbr = v or 0
        elif name == "audio-bitrate":
            st.abr = v or 0
        elif name == "ab-loop-a":
            st.ab_a = v if isinstance(v, (int, float)) else None
        elif name == "ab-loop-b":
            st.ab_b = v if isinstance(v, (int, float)) else None
        elif name == "eof-reached":
            self._eof = bool(v)
            if v:
                self.a_next(auto=True)
        elif name == "media-title" and v:
            self.setWindowTitle(self.cfg.title_for(v))
            self.titlebar.title = v; self.titlebar.update()
        elif name == "track-list" and v:
            for t in v:
                if t.get("type") == "video" and t.get("selected") and not t.get("albumart"):
                    st.vcodec = t.get("codec", "")
                elif t.get("type") == "audio" and t.get("selected"):
                    st.acodec = t.get("codec", ""); st.channels = t.get("demux-channel-count") or 0
            self.auto_slim(v)
        if self.skin:
            self.controls.update()
            return
        if name in ("time-pos", "duration"):
            self.update_time()
        elif name == "pause":
            self.b_play.setIcon(self._icon(QStyle.SP_MediaPlay if v else QStyle.SP_MediaPause))
        elif name == "volume" and v is not None:
            self.vol.blockSignals(True); self.vol.setValue(int(v)); self.vol.blockSignals(False)
        elif name == "mute":
            self.b_mute.setIcon(self._icon(QStyle.SP_MediaVolumeMuted if v else QStyle.SP_MediaVolume))
        elif name == "speed" and v:
            self.speed_lbl.setText(f"{v:.2f}x".replace(".00x", ".0x"))
        elif name == "media-title" and v:
            pass

    def update_time(self):
        if self.skin:
            return
        self.time.setText(f"{fmt(self.pos)} / {fmt(self.dur)}")
        if self.dur and not self.seek.isSliderDown():
            self.seek.blockSignals(True)
            self.seek.setValue(int(self.pos / self.dur * self.seek.maximum()))
            self.seek.blockSignals(False)

    def a_seek_fraction(self, f):
        if self.dur:
            self.mpv.command("seek", f * self.dur, "absolute")

    seek_fraction = a_seek_fraction

    def auto_slim(self, tracks):
        has_video = any(t.get("type") == "video" and not t.get("albumart") for t in tracks)
        if not has_video and not self.slim and not self.fullscreen:
            self.a_toggle_slim(); self.auto_slimmed = True
        elif has_video and self.slim and self.auto_slimmed:
            self.a_toggle_slim()

    # ---- AdvCtrl-bar actions
    def a_set_volume(self, v):
        self.mpv.volume = max(0, min(130, v)); self.osd(f"Volume {int(v)}%")

    def a_set_speed(self, v):
        v = round(v, 2); self.mpv.speed = v; self.osd(f"Speed {v}x")

    def a_cycle_page(self):
        if self.skin:
            self.controls.page = (self.controls.page + 1) % 4; self.controls.update()

    def a_ab_start(self):
        self.mpv.ab_loop_a = self.st.pos; self.osd(f"A-B start {fmt(self.st.pos)}")

    def a_ab_end(self):
        self.mpv.ab_loop_b = self.st.pos; self.osd(f"A-B end {fmt(self.st.pos)}")

    def a_ab_reset(self):
        self.mpv.ab_loop_a = "no"; self.mpv.ab_loop_b = "no"; self.osd("A-B repeat off")

    def _bm_key(self):
        return self.items[self.index] if 0 <= self.index < len(self.items) else ""

    def _bm_save(self):
        self.settings.setValue("bookmarks", json.dumps(self.bookmarks))

    def a_bookmark_add(self):
        k = self._bm_key()
        if k:
            self.bookmarks.setdefault(k, []).append(round(self.st.pos, 2))
            self.bookmarks[k] = sorted(set(self.bookmarks[k])); self._bm_save()
            self.osd(f"Bookmark {fmt(self.st.pos)} added")

    def _bm_jump(self, step):
        marks = self.bookmarks.get(self._bm_key(), [])
        cand = [m for m in marks if (m > self.st.pos + 0.5 if step > 0 else m < self.st.pos - 0.5)]
        if cand:
            t = min(cand) if step > 0 else max(cand)
            self.mpv.command("seek", t, "absolute"); self.osd(f"Bookmark {fmt(t)}")
        else:
            self.osd("No more bookmarks")

    def a_bookmark_next(self):
        self._bm_jump(1)

    def a_bookmark_prev(self):
        self._bm_jump(-1)

    def a_bookmark_clear(self):
        self.bookmarks.pop(self._bm_key(), None); self._bm_save(); self.osd("Bookmarks cleared")

    def a_audio_sync(self, d):
        v = 0.0 if d == 0 else round((self.mpv.audio_delay or 0) + d, 2)
        self.mpv.audio_delay = v; self.osd(f"Audio sync {v:+.2f}s")

    def a_sub_sync(self, d):
        v = 0.0 if d == 0 else round((self.mpv.sub_delay or 0) + d, 2)
        self.mpv.sub_delay = v; self.osd(f"Subtitle sync {v:+.2f}s")

    def a_toggle_subs(self):
        vis = not bool(self.mpv.sub_visibility)
        self.mpv.sub_visibility = vis; self.st.toggles["ID_CAPTION_VISIBLE"] = vis
        self.osd("Subtitles " + ("on" if vis else "off")); self.controls.update()

    def a_cycle_repeat(self):
        self.repeat = {"off": "all", "all": "one", "one": "off"}[self.repeat]
        self.st.toggles["ID_PLAYBACK_REPEAT"] = self.repeat != "off"
        self.osd(f"Repeat: {self.repeat}"); self.controls.update()

    FILTERS = {  # (button cmd, mpv filter) - same four toggles the skin shows as D S B T
        "D": ("ID_VIDEO_DENOISE_D", "@dn3d:lavfi=[hqdn3d=4:3:6:4.5]"),
        "S": ("ID_VIDEO_SHARPEN", "@sharp:lavfi=[unsharp=5:5:1.0:5:5:0.0]"),
        "B": ("ID_VIDEO_BLUR", "@blur:lavfi=[gblur=sigma=1.2]"),
        "T": ("ID_VIDEO_DENOISE_T", "@tden:lavfi=[hqdn3d=0:0:8:8]"),
    }

    def a_filter(self, key):
        cmd, flt = self.FILTERS[key]
        self.mpv.command("vf", "toggle", flt)
        self.st.toggles[cmd] = not self.st.toggles.get(cmd, False)
        self.osd(f"{cmd.split('_', 2)[-1].title()} {'on' if self.st.toggles[cmd] else 'off'}")
        self.controls.update()

    def a_toggle_eq(self):
        self.mpv.command("af", "toggle", "@eq:lavfi=[equalizer=f=60:t=q:w=1:g=5,equalizer=f=10000:t=q:w=1:g=3]")
        self.st.toggles["ID_AUDIO_EQULIZER"] = not self.st.toggles.get("ID_AUDIO_EQULIZER", False)
        self.osd("Equalizer " + ("on" if self.st.toggles["ID_AUDIO_EQULIZER"] else "off")); self.controls.update()

    def a_toggle_normalize(self):
        self.mpv.command("af", "toggle", "@norm:lavfi=[dynaudnorm]")
        self.st.toggles["ID_AUDIO_NORMALIZE"] = not self.st.toggles.get("ID_AUDIO_NORMALIZE", False)
        self.osd("Normalizer " + ("on" if self.st.toggles["ID_AUDIO_NORMALIZE"] else "off")); self.controls.update()

    def a_goto(self):
        t, ok = QInputDialog.getText(self, "Go to", "Time (HH:MM:SS, MM:SS or seconds):")
        if ok and t.strip():
            try:
                secs = 0.0
                for part in t.strip().split(":"):
                    secs = secs * 60 + float(part)
                self.mpv.command("seek", secs, "absolute")
            except ValueError:
                self.osd("Bad time")

    def a_toggle_chrome(self):  # the skin's "floating window (skin on/off)" button
        if not self.skin or self.fullscreen:
            return
        hide = self.titlebar.isVisible()
        for w in self.chrome + [self.controls]:
            w.setVisible(not hide)

    def a_control_box(self):
        d = QDialog(self); d.setWindowTitle("Control panel"); lay = QFormLayout(d)
        for label, prop in (("Brightness", "brightness"), ("Contrast", "contrast"), ("Saturation", "saturation"),
                            ("Gamma", "gamma"), ("Hue", "hue")):
            sl = QSlider(Qt.Horizontal); sl.setRange(-100, 100); sl.setValue(int(getattr(self.mpv, prop) or 0))
            sl.valueChanged.connect(lambda v, p=prop: setattr(self.mpv, p, v))
            lay.addRow(label, sl)
        di = QCheckBox("Deinterlace"); di.setChecked(bool(self.mpv.deinterlace))
        di.toggled.connect(lambda c: setattr(self.mpv, "deinterlace", c)); lay.addRow(di)
        rs = QPushButton("Reset")
        def reset():
            for p in ("brightness", "contrast", "saturation", "gamma", "hue"):
                setattr(self.mpv, p, 0)
            d.close()
        rs.clicked.connect(reset); lay.addRow(rs)
        d.show(); self._ctl = d

    def track_menu(self, kind):
        m = QMenu(self)
        prop = "aid" if kind == "audio" else "sid"
        tracks = [t for t in (self.mpv.track_list or []) if t["type"] == kind]
        off = m.addAction("Off"); off.triggered.connect(lambda: self.mpv.command("set", prop, "no"))
        for t in tracks:
            a = m.addAction(f'{t["id"]}: {t.get("title") or t.get("lang") or "track"}')
            a.setCheckable(True); a.setChecked(bool(t.get("selected")))
            a.triggered.connect(lambda _=False, i=t["id"]: self.mpv.command("set", prop, str(i)))
        if kind == "sub":
            m.addSeparator(); m.addAction("Open subtitle...", lambda: self.do("open_sub"))
        m.exec(QCursor.pos())

    # bar/title-bar command ids -> actions. (left-click table; right-click passes the item's AltCmdID)
    CMD = {
        "CMD_MEDIA_PLAY": "toggle_pause", "CMD_MEDIA_PAUSE": "toggle_pause", "CMD_MEDIA_CLOSE": "stop",
        "ID_PROCESS_PREV": "prev", "ID_PROCESS_NEXT": "next",
        "ID_PLAYBACK_30SEC_BACK": ("seek", -30), "ID_PLAYBACK_30SEC_FORW": ("seek", 30),
        "ID_OPEN_FILE": "open_files", "ID_AUDIO_MUTE": "toggle_mute",
        "ID_PLAY_SPEED_SLOWER": ("speed", -0.1), "ID_PLAY_SPEED_NORMAL": "speed_reset",
        "ID_PLAY_SPEED_FASTER": ("speed", 0.1),
        "ID_PLAY_REPEAT_START_SET": "ab_start", "ID_PLAY_REPEAT_RESET": "ab_reset", "ID_PLAY_REPEAT_STOP_SET": "ab_end",
        "ID_PLAY_PREV_FRAME": "frame_back", "ID_PLAY_NEXT_FRAME": "frame_forward",
        "ID_AUDIO_SLOWER": ("audio_sync", -0.1), "ID_AUDIO_FASTER": ("audio_sync", 0.1), "ID_AUDIO_NORMAL": ("audio_sync", 0),
        "ID_CAPTION_SLOW_SYNC": ("sub_sync", -0.1), "ID_CAPTION_FAST_SYNC": ("sub_sync", 0.1), "ID_CAPTION_RESET_SYNC": ("sub_sync", 0),
        "ID_BOOKMARK_PREV": "bookmark_prev", "ID_BOOKMARK_NEXT": "bookmark_next", "ID_BOOKMARK_ADD": "bookmark_add",
        "ID_BOOKMARK_CLEAR": "bookmark_clear",
        "ID_CAPTION_VISIBLE": "toggle_subs", "ID_PLAYLIST_WINDOW": "toggle_playlist", "CMD_ATTACH_PLAYLIST": "toggle_playlist",
        "ID_CONTROL_BOX_WINDOW": "control_box", "CMD_LOAD_SKIN_XML": "control_box",
        "ID_VIDEO_IMAGE_CAPTURE": "screenshot", "ID_PLAYBACK_REPEAT": "cycle_repeat",
        "ID_AUDIO_EQULIZER": "toggle_eq", "ID_AUDIO_NORMALIZE": "toggle_normalize",
        "ID_VIDEO_DENOISE_D": ("filter", "D"), "ID_VIDEO_SHARPEN": ("filter", "S"),
        "ID_VIDEO_BLUR": ("filter", "B"), "ID_VIDEO_DENOISE_T": ("filter", "T"),
        "CMD_POPUPMENU_PLAY_GOTO": "goto",
        "ID_APP_EXIT": "quit", "CMD_MIN_WINDOW": "minimize", "CMD_MAX_WINDOW": "maximize", "CMD_RESTORE_WINDOW": "restore",
        "ID_SKIN_AUTO_HIDE": "toggle_chrome", "ID_ETC_NEXTONTOP": "toggle_on_top",
    }

    def a_minimize(self):
        self.showMinimized()

    def a_maximize(self):
        self.showMaximized()

    def a_restore(self):
        self.showNormal()

    def bar_command(self, cmd, item, right):
        if cmd in ("CMD_POPUP_USER_MENU", "CMD_POPUPMENU_ETC"):
            return self.context_menu(QCursor.pos())
        if cmd == "ID_AUDIO_SELECT_MENU":
            return self.track_menu("audio")
        if cmd == "ID_CAPTION_SELECT_MENU":
            return self.track_menu("sub")
        act = self.CMD.get(cmd)
        if act:
            self.do(act)

    # ---- more actions (registry ids -> a_<id>)
    def a_seek_start(self):
        self.mpv.command("seek", 0, "absolute")

    def a_close_file(self):
        self.save_position(); self._eof = True
        self.index = -1
        self.a_stop()

    def _adjust(self, prop, d, label):
        v = max(-100, min(100, int((getattr(self.mpv, prop) or 0) + d)))
        setattr(self.mpv, prop, v); self.osd(f"{label} {v}")

    def a_brightness(self, d): self._adjust("brightness", d, "Brightness")
    def a_contrast(self, d): self._adjust("contrast", d, "Contrast")
    def a_saturation(self, d): self._adjust("saturation", d, "Saturation")
    def a_colour(self, d): self._adjust("hue", d, "Hue")

    def a_image_reset(self):
        for p in ("brightness", "contrast", "saturation", "gamma", "hue"):
            setattr(self.mpv, p, 0)
        self.osd("Picture reset")

    def a_mirror(self):
        self.mpv.command("vf", "toggle", "@mirror:hflip"); self.osd("Mirror")

    def a_flip_vertical(self):
        self.mpv.command("vf", "toggle", "@flipv:vflip"); self.osd("Flip vertical")

    _ASPECTS = ["-1", "16:9", "4:3", "21:9", "1:1"]

    def a_aspect_cycle(self):
        cur = str(self.mpv.video_aspect_override)
        i = (self._ASPECTS.index(cur) + 1) % len(self._ASPECTS) if cur in self._ASPECTS else 1
        self.mpv.command("set", "video-aspect-override", self._ASPECTS[i])
        self.osd("Aspect: " + ("default" if self._ASPECTS[i] == "-1" else self._ASPECTS[i]))

    def a_sub_menu(self): self.track_menu("sub")
    def a_audio_menu(self): self.track_menu("audio")

    def a_screenshot_clipboard(self):
        fd, path = tempfile.mkstemp(suffix=".png"); os.close(fd)
        try:
            self.mpv.command("screenshot-to-file", path, "window")
            QApplication.clipboard().setImage(QImage(path)); self.osd("Screenshot copied")
        finally:
            os.unlink(path)

    def a_ab_toggle(self):
        a, b = self.st.ab_a, self.st.ab_b
        if a is not None or b is not None:
            self._ab_saved = (a, b); self.a_ab_reset()
        elif self._ab_saved:
            na, nb = self._ab_saved
            if na is not None: self.mpv.ab_loop_a = na
            if nb is not None: self.mpv.ab_loop_b = nb
            self.osd("A-B repeat on")

    def a_shuffle_toggle(self):
        self.shuffle = not self.shuffle; self.osd("Shuffle " + ("on" if self.shuffle else "off"))

    def a_playlist_save(self):
        f, _ = QFileDialog.getSaveFileName(self, "Save playlist", str(Path.home() / "playlist.m3u8"), "Playlist (*.m3u8 *.m3u)")
        if f:
            Path(f).write_text("#EXTM3U\n" + "\n".join(self.items) + "\n", encoding="utf-8")

    def a_playlist_load(self):
        f, _ = QFileDialog.getOpenFileName(self, "Load playlist", str(Path.home()), "Playlist (*.m3u8 *.m3u)")
        if f:
            lines = [l.strip() for l in Path(f).read_text(encoding="utf-8", errors="replace").splitlines()]
            self.add_paths([l for l in lines if l and not l.startswith("#")])

    def a_bookmark_list(self):
        k = self._bm_key()
        d = QDialog(self); d.setWindowTitle("Bookmarks"); lay = QVBoxLayout(d)
        lst = QListWidget(); lay.addWidget(lst)
        def fill():
            lst.clear(); lst.addItems([fmt(t) for t in self.bookmarks.get(k, [])])
        fill()
        lst.itemDoubleClicked.connect(lambda it: self.mpv.command("seek", self.bookmarks[k][lst.row(it)], "absolute"))
        rm = QPushButton("Remove selected")
        def remove():
            r = lst.currentRow()
            if r >= 0:
                del self.bookmarks[k][r]; self._bm_save(); fill()
        rm.clicked.connect(remove); lay.addWidget(rm)
        d.resize(260, 320); d.show(); self._dlg = d

    def a_mpv(self, *args):
        if args and args[0] in actions.MPV_BLOCKED:
            self.report(f"mpv command '{args[0]}' is blocked"); return
        self.mpv.command(*args)

    def a_about(self):
        QMessageBox.about(self, f"About {self.cfg.app_name}",
            f"<b>{self.cfg.app_name}</b><br>A PotPlayer-style media player for Linux, Windows and macOS.<br><br>"
            "Inspired by Daum PotPlayer for Windows. Not affiliated with Kakao/Daum.<br>"
            f"Config folder: {self.cfg.dir}<br>Skin: {self.skin.name if self.skin else 'Default (Qt)'}")

    def a_register_defaults(self):
        QMessageBox.information(self, "Default player", associations.install(self.cfg))

    def maybe_ask_defaults(self):
        """First start only: offer to become the default player so double-click works."""
        if ENV("NO_PROMPT") or self.settings.value("defaults_asked") in ("1", 1, True, "true"):
            return
        box = QMessageBox(self)
        box.setWindowTitle(self.cfg.app_name)
        box.setText(f"Open video and audio files with {self.cfg.app_name} when you double-click them?")
        box.setInformativeText("This adds a menu entry and sets it as the default player for your user. "
                               "You can change it later in Preferences (F5).")
        yes = box.addButton("Yes, make it the default", QMessageBox.AcceptRole)
        later = box.addButton("Not now", QMessageBox.RejectRole)
        never = box.addButton("Don't ask again", QMessageBox.DestructiveRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is yes:
            self.settings.setValue("defaults_asked", "1")
            QMessageBox.information(self, self.cfg.app_name, associations.install(self.cfg))
        elif clicked is never:
            self.settings.setValue("defaults_asked", "1")

    def a_unregister_defaults(self):
        QMessageBox.information(self, "Default player", associations.unregister(self.cfg))

    def a_preferences(self):
        d = QDialog(self); d.setWindowTitle("Preferences"); d.resize(720, 520)
        tabs = QTabWidget(); lay = QVBoxLayout(d); lay.addWidget(tabs)

        # --- keyboard editor (PotPlayer: F5 > General > Keyboard)
        kb = QWidget(); kl = QVBoxLayout(kb)
        rows = sorted(self.cfg.hotkeys, key=lambda b: (b["action"], json.dumps(b.get("args", []))))
        tbl = QTableWidget(len(rows), 3); tbl.setHorizontalHeaderLabels(["Action", "Args", "Keys (separate several with  |  )"])
        for r, b in enumerate(rows):
            for c, txt in enumerate((b["action"], json.dumps(b.get("args", [])), " | ".join(b["keys"]))):
                it = QTableWidgetItem(txt)
                if c < 2:
                    it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                tbl.setItem(r, c, it)
        tbl.setColumnWidth(0, 190); tbl.setColumnWidth(1, 90); tbl.horizontalHeader().setStretchLastSection(True)
        kl.addWidget(tbl)
        msg = QLabel(""); kl.addWidget(msg)
        bar = QHBoxLayout()
        def save():
            out, seen = [], {}
            for r, b in enumerate(rows):
                keys = [k.strip() for k in tbl.item(r, 2).text().split("|") if k.strip()]
                for k in keys:
                    ks = QKeySequence(k).toString()
                    if not ks:
                        msg.setText(f"Cannot parse key '{k}' ({b['action']})"); return
                    if ks in seen:
                        msg.setText(f"Conflict: '{k}' is used by {seen[ks]} and {b['action']}"); return
                    seen[ks] = b["action"]
                nb = {"action": b["action"], "keys": keys}
                if b.get("args"): nb["args"] = b["args"]
                out.append(nb)
            self.cfg.save_hotkeys(out); self.a_reload_config(); msg.setText("Saved.")
        def reset():
            (self.cfg.dir / "hotkeys.json").unlink(missing_ok=True); self.a_reload_config(); d.close()
        sv = QPushButton("Save"); sv.clicked.connect(save); rs = QPushButton("Reset to defaults"); rs.clicked.connect(reset)
        bar.addWidget(sv); bar.addWidget(rs); bar.addStretch(1); kl.addLayout(bar)
        tabs.addTab(kb, "Keyboard")

        # --- skins
        sw = QWidget(); sl = QVBoxLayout(sw)
        skl = QListWidget(); sl.addWidget(skl)
        def fill_skins():
            skl.clear(); skl.addItem("default")
            skl.addItems(list(self.discover_skins()))
            cur = self.skin.name if self.skin else "default"
            for i in range(skl.count()):
                if skl.item(i).text() == cur: skl.setCurrentRow(i)
        fill_skins()
        ap = QPushButton("Apply selected skin")
        ap.clicked.connect(lambda: skl.currentItem() and self.set_skin_by_name(skl.currentItem().text()))
        def add_skin():
            f, _ = QFileDialog.getOpenFileName(d, "Add skin", str(Path.home()), "PotPlayer skin (*.dsf)")
            if f:
                try:
                    dsfskin.Skin(f)
                except Exception as e:
                    QMessageBox.warning(d, "Skin", f"Not a usable skin: {e}"); return
                dest = self.cfg.dir / "skins"; dest.mkdir(parents=True, exist_ok=True)
                (dest / Path(f).name).write_bytes(Path(f).read_bytes()); fill_skins()
        ad = QPushButton("Add skin..."); ad.clicked.connect(add_skin)
        br = QHBoxLayout(); br.addWidget(ap); br.addWidget(ad); br.addStretch(1); sl.addLayout(br)
        tabs.addTab(sw, "Skins")

        # --- associations / paths
        aw = QWidget(); al = QVBoxLayout(aw)
        al.addWidget(QLabel("Extensions: " + ", ".join(associations.enabled_exts(self.cfg))))
        b1 = QPushButton("Register as default player"); b1.clicked.connect(self.a_register_defaults)
        b2 = QPushButton("Remove registration"); b2.clicked.connect(self.a_unregister_defaults)
        al.addWidget(b1); al.addWidget(b2); al.addWidget(QLabel(f"Config folder: {self.cfg.dir}"))
        al.addWidget(QLabel("Edit branding.json, hotkeys.json, mouse.json, associations.json there, then Reload."))
        rl = QPushButton("Reload config"); rl.clicked.connect(self.a_reload_config); al.addWidget(rl); al.addStretch(1)
        tabs.addTab(aw, "Files and config")
        d.show(); self._prefs = d

    # ---- context menu (right click)
    def context_menu(self, gpos):
        m = QMenu(self)
        m.addAction("Open file(s)...", lambda: self.do("open_files"))
        m.addAction("Open folder...", lambda: self.do("open_folder"))
        m.addAction("Open URL...", lambda: self.do("open_url"))
        m.addAction("Open subtitle...", lambda: self.do("open_sub"))
        m.addSeparator()
        m.addAction("Play / Pause", lambda: self.do("toggle_pause"))
        m.addAction("Stop", lambda: self.do("stop"))
        m.addAction("Previous", lambda: self.do("prev"))
        m.addAction("Next", lambda: self.do("next"))
        m.addSeparator()
        tracks = self.mpv.track_list or []
        for kind, title, prop in (("audio", "Audio track", "aid"), ("sub", "Subtitles", "sid")):
            sub = m.addMenu(title)
            grp = QActionGroup(sub); grp.setExclusive(True)
            off = sub.addAction("Off"); off.setCheckable(True); grp.addAction(off)
            off.setChecked(not any(t.get("selected") for t in tracks if t["type"] == kind))
            off.triggered.connect(lambda _=False, p=prop: self.mpv.command("set", p, "no"))
            for t in (t for t in tracks if t["type"] == kind):
                label = f'{t["id"]}: {t.get("title") or t.get("lang") or "track"}'
                a = sub.addAction(label); a.setCheckable(True); grp.addAction(a)
                a.setChecked(bool(t.get("selected")))
                a.triggered.connect(lambda _=False, p=prop, i=t["id"]: self.mpv.command("set", p, str(i)))
        ar = m.addMenu("Aspect ratio")
        for label, val in (("Default", "-1"), ("16:9", "16:9"), ("4:3", "4:3"), ("21:9", "21:9"), ("1:1", "1:1")):
            ar.addAction(label, lambda v=val: self.mpv.command("set", "video-aspect-override", v))
        sp = m.addMenu("Speed")
        for s in (0.5, 0.75, 1.0, 1.25, 1.5, 2.0):
            sp.addAction(f"{s}x", lambda s=s: setattr(self.mpv, "speed", s))
        rp = m.addMenu("Repeat")
        g = QActionGroup(rp)
        for label, val in (("Off", "off"), ("One", "one"), ("All", "all")):
            a = rp.addAction(label); a.setCheckable(True); g.addAction(a); a.setChecked(self.repeat == val)
            a.triggered.connect(lambda _=False, v=val: setattr(self, "repeat", v))
        sh = m.addAction("Shuffle"); sh.setCheckable(True); sh.setChecked(self.shuffle)
        sh.triggered.connect(lambda c: setattr(self, "shuffle", c))
        m.addSeparator()
        m.addAction("Fullscreen\tEnter", lambda: self.do("toggle_fullscreen"))
        m.addAction("Slim (audio) mode\tCtrl+M", lambda: self.do("toggle_slim"))
        m.addAction("Always on top\tCtrl+T", lambda: self.do("toggle_on_top"))
        m.addAction("Playlist\tF6", lambda: self.do("toggle_playlist"))
        m.addAction("Screenshot\tCtrl+E", lambda: self.do("screenshot"))
        m.addSeparator()
        sk = m.addMenu("Skin")
        cur = self.skin.name if self.skin else "default"
        grp = QActionGroup(sk)
        for nm in ["default"] + list(self.discover_skins()):
            a = sk.addAction("Default (Qt)" if nm == "default" else nm); a.setCheckable(True); grp.addAction(a)
            a.setChecked(nm == cur)
            a.triggered.connect(lambda _=False, n=nm: self.a_skin_set(n))
        m.addAction("Preferences...\tF5", self.a_preferences)
        m.addAction("Reload config", self.a_reload_config)
        m.addAction("About", self.a_about)
        m.addSeparator()
        m.addAction("Quit", self.close)
        m.exec(gpos)

    # ---- drag & drop, shutdown
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        self.add_paths([u.toLocalFile() or u.toString() for u in e.mimeData().urls()])

    def closeEvent(self, e):
        self.settings.setValue("volume", self.mpv.volume or 80)
        self.save_position()
        self.view.shutdown()
        super().closeEvent(e)
