#!/usr/bin/env python3
"""
PotLinux - a PotPlayer-style media player for Linux.
Stack: PySide6 (Qt6) + libmpv (render API, so it works on X11 and Wayland).

Run:   python3 potlinux.py [files / folders / urls ...]
Debug/env knobs: POTLINUX_DEBUG=1 (mpv log), POTLINUX_FLIP=0|1 (picture upside down?),
                 POTLINUX_RGBA=1 (picture black?), POTLINUX_BLOCK=1
Keys and mouse actions are the tables KEYS / MOUSE near the top - edit freely.
"""
import ctypes
import locale
import os
import random
import sys
from pathlib import Path

from PySide6.QtCore import QPoint, QSettings, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QActionGroup, QCursor, QKeySequence, QOpenGLContext, QShortcut
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QInputDialog, QLabel,
    QListWidget, QMenu, QPushButton, QSlider, QStyle, QToolTip, QVBoxLayout, QWidget,
)

import json
from types import SimpleNamespace

import mpv  # python-mpv

import dsfskin

APP = "PotLinux"
MEDIA_EXT = {
    ".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv", ".wmv", ".m4v", ".ts", ".mpg", ".mpeg",
    ".mp3", ".flac", ".ogg", ".opus", ".wav", ".m4a", ".aac", ".wma", ".ape",
}
SUB_EXT = "Subtitles (*.srt *.ass *.ssa *.sub *.vtt);;All files (*)"

# PotPlayer-style defaults. Unverified-against-PotPlayer choices are marked (mine).
KEYS = {
    "Space": "toggle_pause",
    "Return": "toggle_fullscreen", "Enter": "toggle_fullscreen",
    "Esc": "leave_fullscreen",
    "Left": ("seek", -5), "Right": ("seek", 5),
    "Ctrl+Left": ("seek", -30), "Ctrl+Right": ("seek", 30),          # (mine)
    "Up": ("volume", 5), "Down": ("volume", -5),
    "M": "toggle_mute",
    "C": ("speed", 0.1), "X": ("speed", -0.1), "Z": "speed_reset",
    "D": "frame_back", "F": "frame_forward",
    "PgUp": "prev", "PgDown": "next",
    "Ctrl+E": "screenshot",
    "F3": "open_files", "Ctrl+O": "open_files", "Ctrl+U": "open_url",
    "F6": "toggle_playlist",                                           # (mine)
    "Ctrl+T": "toggle_on_top",
    "Ctrl+M": "toggle_slim",                                           # (mine) JetAudio-slimbar mode
    "Ctrl+Q": "quit",
    # --- AdvCtrl-bar functions. Key choices below are MINE, not verified PotPlayer defaults:
    "[": "ab_start", "]": "ab_end", "\\": "ab_reset",                   # A-B repeat
    "Ctrl+B": "bookmark_add", "Ctrl+PgDown": "bookmark_next", "Ctrl+PgUp": "bookmark_prev",
    "Ctrl+Shift+B": "bookmark_clear",
    "Ctrl+,": ("audio_sync", -0.1), "Ctrl+.": ("audio_sync", 0.1), "Ctrl+/": ("audio_sync", 0),
    "Alt+,": ("sub_sync", -0.1), "Alt+.": ("sub_sync", 0.1), "Alt+/": ("sub_sync", 0),
    "Alt+H": "toggle_subs", "Ctrl+R": "cycle_repeat", "F7": "control_box", "Ctrl+Tab": "cycle_page",
    "Ctrl+G": "goto", "Ctrl+Shift+S": "toggle_chrome",
    "Alt+1": ("filter", "D"), "Alt+2": ("filter", "S"), "Alt+3": ("filter", "B"), "Alt+4": ("filter", "T"),
    "Ctrl+Shift+E": "toggle_eq", "Ctrl+Shift+N": "toggle_normalize",
}
# mouse: left click on video, left double-click, wheel, right click
MOUSE = {"click": "toggle_pause", "double": "toggle_fullscreen", "wheel": ("volume", 5), "right": "context_menu"}

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
class MpvWidget(QOpenGLWidget):
    update_requested = Signal()
    prop = Signal(str, object)
    clicked = Signal()
    double_clicked = Signal()
    wheel = Signal(int)
    context = Signal(QPoint)
    moved = Signal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        # mpv leaves alpha=0 in an RGBA8 FBO, which Qt then composites as "transparent" (black video).
        # An RGB8 backing texture has no alpha channel, so the picture is always opaque.
        if os.environ.get("POTLINUX_RGBA") != "1":   # set POTLINUX_RGBA=1 to opt out if your driver dislikes it
            self.setTextureFormat(0x8051)  # GL_RGB8
        shots = Path.home() / "Pictures" / "PotLinux"
        shots.mkdir(parents=True, exist_ok=True)
        self.mpv = mpv.MPV(
            vo="libmpv", hwdec="auto-safe", idle=True, keep_open="yes",
            input_default_bindings=False, input_vo_keyboard=False, osc=False, osd_level=1,
            ytdl=True, sub_auto="fuzzy", resume_playback=True, save_position_on_quit=True,
            screenshot_directory=str(shots), screenshot_template="%F-%P",
            watch_later_options="start,aid,sid,sub-delay,audio-delay",
            **({"log_handler": lambda l, c, t: print(f"[mpv:{c}] {t.strip()}"), "loglevel": "v"}
               if os.environ.get("POTLINUX_DEBUG") else {}),
        )
        self._proc = mpv.MpvGlGetProcAddressFn(self._get_proc_address)
        self.ctx = None
        self._flip = os.environ.get("POTLINUX_FLIP", "1") == "1"  # QOpenGLWidget FBOs are bottom-up
        self.update_requested.connect(self.update)
        for name in ("time-pos", "duration", "pause", "volume", "mute", "speed",
                     "eof-reached", "media-title", "track-list", "video-bitrate", "audio-bitrate",
                     "ab-loop-a", "ab-loop-b"):
            self.mpv.observe_property(name, self._on_prop)

    def _on_prop(self, name, value):  # runs on mpv's thread -> queued signal
        self.prop.emit(name, value)

    @staticmethod
    def _get_proc_address(_ctx, name):
        gl = QOpenGLContext.currentContext()
        if gl is None:
            return 0
        addr = gl.getProcAddress(name)
        return int(addr) if addr else 0

    def initializeGL(self):
        self.ctx = mpv.MpvRenderContext(
            self.mpv, "opengl", opengl_init_params={"get_proc_address": self._proc})
        self.ctx.update_cb = lambda: self.update_requested.emit()

    def paintGL(self):
        if not self.ctx:
            return
        self.ctx.update()  # mandatory: tells mpv we consumed the "new frame" callback
        r = self.devicePixelRatioF()
        self.ctx.render(
            flip_y=self._flip,
            opengl_fbo={"w": int(self.width() * r), "h": int(self.height() * r),
                        "fbo": self.defaultFramebufferObject()},
            block_for_target_time=os.environ.get("POTLINUX_BLOCK") == "1")

    def shutdown(self):
        self.makeCurrent()
        if self.ctx:
            self.ctx.free()
            self.ctx = None
        self.doneCurrent()
        self.mpv.terminate()

    # mouse -> signals
    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit()

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.double_clicked.emit()

    def mouseMoveEvent(self, e):
        self.moved.emit(int(e.position().x()), int(e.position().y()))

    def wheelEvent(self, e):
        self.wheel.emit(e.angleDelta().y())

    def contextMenuEvent(self, e):
        self.context.emit(e.globalPos())


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
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP)
        self.setAcceptDrops(True)
        self.settings = QSettings("potlinux", "potlinux")
        self.items, self.index = [], -1
        self.pos = self.dur = 0.0
        self.shuffle, self.repeat = False, "off"      # repeat: off | one | all
        self.fullscreen = self.slim = self.auto_slimmed = False
        self._normal_geo = None
        self._eof = False

        self.view = MpvWidget()
        self.mpv = self.view.mpv
        v = self.view
        v.prop.connect(self.on_prop)
        v.clicked.connect(lambda: self._click_timer.start(QApplication.doubleClickInterval()))
        v.double_clicked.connect(self._on_double)
        v.wheel.connect(lambda d: self.do(("volume", 5 * (1 if d > 0 else -1))))
        v.context.connect(self.context_menu)
        v.moved.connect(self.on_mouse_move)
        self._click_timer = QTimer(self, singleShot=True)
        self._click_timer.timeout.connect(lambda: self.do(MOUSE["click"]))
        self._idle = QTimer(self, singleShot=True, interval=2000)
        self._idle.timeout.connect(self.hide_idle)

        self.st = SimpleNamespace(
            pos=0.0, dur=0.0, volume=80.0, speed=1.0, mute=False, paused=True, toggles={},
            vcodec="", acodec="", channels=0, vbr=0, abr=0, ab_a=None, ab_b=None, filetype="")
        self.skin = None
        sp = None if os.environ.get("POTLINUX_SKIN", "").lower() == "none" else dsfskin.find_skin()
        if sp:
            try:
                self.skin = dsfskin.Skin(sp)
            except Exception as e:  # broken skin -> fall back to the plain Qt controls
                print(f"[potlinux] could not load skin {sp}: {e}", file=sys.stderr)

        self.list = QListWidget()
        self.list.setFocusPolicy(Qt.NoFocus)
        self.list.itemDoubleClicked.connect(lambda it: self.play_index(self.list.row(it)))
        self.playlist_panel = self.list
        self.playlist_panel.setMinimumWidth(240)
        self.playlist_panel.hide()
        self.stage = QWidget()   # picture + playlist; hidden as one unit in slim mode
        row = QHBoxLayout(self.stage); row.setContentsMargins(0, 0, 0, 0); row.setSpacing(0)
        row.addWidget(self.view, 1); row.addWidget(self.playlist_panel)

        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(0, 0, 0, 0)
        self.root.setSpacing(0)
        if self.skin:
            self.setWindowFlag(Qt.FramelessWindowHint, True)
            self.controls = dsfskin.AdvBar(self.skin, self)
            self.titlebar = dsfskin.TitleBar(self.skin, self)
            self.bl, self.br, self.bb = (dsfskin.Border(self.skin, k) for k in ("left", "right", "bottom"))
            self.controls_layout = QVBoxLayout(); self.controls_layout.setSpacing(0)
            self.controls_layout.addWidget(self.stage, 1)
            self.controls_layout.addWidget(self.controls)
            mid = QHBoxLayout(); mid.setSpacing(0)
            mid.addWidget(self.bl); mid.addLayout(self.controls_layout, 1); mid.addWidget(self.br)
            self.root.addWidget(self.titlebar)
            self.root.addLayout(mid, 1)
            self.root.addWidget(self.bb)
            self.chrome = [self.titlebar, self.bl, self.br, self.bb]
            self.setMinimumSize(460, 320)
        else:
            self.controls = self._build_controls()
            self.controls_layout = self.root
            self.root.addWidget(self.stage, 1)
            self.root.addWidget(self.controls)
            self.chrome = []

        for key, act in KEYS.items():
            sc = QShortcut(QKeySequence(key), self)
            sc.setContext(Qt.ApplicationShortcut)
            sc.activated.connect(lambda a=act: self.do(a))

        self.setStyleSheet(QSS)
        self.resize(1024, 640)
        if not self.skin:
            self.seek.tip_fn = lambda f: fmt(f * self.dur)
        self.bookmarks = json.loads(self.settings.value("bookmarks", "{}"))
        self.mpv.volume = float(self.settings.value("volume", 80))

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
        if isinstance(action, tuple):
            name, arg = action
            getattr(self, "a_" + name)(arg)
        elif action == "context_menu":
            self.context_menu(self.cursor().pos())
        else:
            getattr(self, "a_" + action)()

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
        self.mpv.command("screenshot"); self.osd("Screenshot saved to ~/Pictures/PotLinux")

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

    def _on_double(self):
        self._click_timer.stop()
        self.do(MOUSE["double"])

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
            self.setWindowTitle(f"{v} - {APP}")
            if self.skin:
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


def main():
    app = QApplication(sys.argv)
    locale.setlocale(locale.LC_NUMERIC, "C")  # libmpv requires this
    app.setApplicationName(APP)
    w = Player()
    w.show()
    args = sys.argv[1:]
    if args:
        QTimer.singleShot(200, lambda: w.add_paths(args))
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
