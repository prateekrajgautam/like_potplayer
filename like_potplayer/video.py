"""
Video surface: two interchangeable widgets that render libmpv's output.

  MpvGLWidget    - OpenGL render API (GPU scaling, hardware decoding). Best on real graphics hardware.
  MpvSoftWidget  - libmpv *software* render API into a QImage, painted with QPainter. No OpenGL anywhere, so it
                   works in VMs, remote desktops, headless servers and broken GL stacks. Uses the CPU.

Default "auto": software when Qt's OpenGL renderer is a software rasterizer (llvmpipe & co.), GPU otherwise.
Override with  --renderer gl|sw|auto  or  LIKE_POTPLAYER_RENDER=gl|sw.
"""
import ctypes
import os
import sys
from pathlib import Path

from PySide6.QtCore import QObject, QPoint, Qt, Signal
from PySide6.QtGui import QImage, QOpenGLContext, QOffscreenSurface, QPainter
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import QWidget

from . import _libmpv  # noqa: F401  (must run before `import mpv`)
import mpv

# python-mpv ships no software-render parameters; add them (ids from libmpv/render.h)
class _SwSize(ctypes.Structure):
    _fields_ = [("w", ctypes.c_int), ("h", ctypes.c_int)]


class _SizeT(ctypes.Structure):
    _fields_ = [("value", ctypes.c_size_t)]


mpv.MpvRenderParam.TYPES.update({"sw_size": (17, _SwSize), "sw_format": (18, str),
                                 "sw_stride": (19, _SizeT), "sw_pointer": (20, ctypes.c_void_p)})

PROPS = ("time-pos", "duration", "pause", "volume", "mute", "speed", "eof-reached", "media-title",
         "track-list", "video-bitrate", "audio-bitrate", "ab-loop-a", "ab-loop-b")


class _Signals(QObject):
    update_requested = Signal()
    prop = Signal(str, object)
    clicked = Signal()
    double_clicked = Signal()
    gesture = Signal(str)
    context = Signal(QPoint)
    moved = Signal(int, int)


def make_mpv(hwdec):
    shots = Path.home() / "Pictures" / "like_potplayer"
    shots.mkdir(parents=True, exist_ok=True)
    return mpv.MPV(
        vo="libmpv", hwdec=hwdec, idle=True, keep_open="yes",
        input_default_bindings=False, input_vo_keyboard=False, osc=False, osd_level=1,
        ytdl=True, sub_auto="fuzzy", resume_playback=True, save_position_on_quit=True,
        screenshot_directory=str(shots), screenshot_template="%F-%P",
        watch_later_options="start,aid,sid,sub-delay,audio-delay",
        **({"log_handler": lambda l, c, t: print(f"[mpv:{c}] {t.strip()}"), "loglevel": "v"}
           if os.environ.get("LIKE_POTPLAYER_DEBUG") else {}))


class _Mixin:
    """Signals, mpv instance and mouse handling shared by both widgets."""

    def _setup(self, hwdec):
        sig = self._sig = _Signals()
        for n in ("update_requested", "prop", "clicked", "double_clicked", "gesture", "context", "moved"):
            setattr(self, n, getattr(sig, n))
        self.setMouseTracking(True)
        self.mpv = make_mpv(hwdec)
        self.update_requested.connect(self.update)
        for name in PROPS:
            self.mpv.observe_property(name, self._on_prop)

    def _on_prop(self, name, value):          # runs on mpv's thread -> queued signal
        self.prop.emit(name, value)

    def mouseReleaseEvent(self, e):
        b = e.button()
        if b == Qt.LeftButton:
            self.clicked.emit()
        elif b == Qt.MiddleButton:
            self.gesture.emit("middle")
        elif b == Qt.BackButton:
            self.gesture.emit("x1")
        elif b == Qt.ForwardButton:
            self.gesture.emit("x2")

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.double_clicked.emit()

    def mouseMoveEvent(self, e):
        self.moved.emit(int(e.position().x()), int(e.position().y()))

    def wheelEvent(self, e):
        d = e.angleDelta().y()
        if not d:
            return
        m = e.modifiers()
        prefix = (("ctrl+" if m & Qt.ControlModifier else "") + ("shift+" if m & Qt.ShiftModifier else "")
                  + ("alt+" if m & Qt.AltModifier else ""))
        self.gesture.emit(prefix + ("wheel_up" if d > 0 else "wheel_down"))

    def contextMenuEvent(self, e):
        self.context.emit(e.globalPos())


class MpvGLWidget(_Mixin, QOpenGLWidget):
    kind = "gl"

    def __init__(self):
        QOpenGLWidget.__init__(self)
        self._setup("auto-safe")
        # mpv leaves alpha=0 in an RGBA8 FBO, which Qt then composites as "transparent" (black video).
        if os.environ.get("LIKE_POTPLAYER_RGBA") != "1":
            self.setTextureFormat(0x8051)  # GL_RGB8: no alpha channel
        self._proc = mpv.MpvGlGetProcAddressFn(self._get_proc_address)
        self.ctx = None
        self._flip = os.environ.get("LIKE_POTPLAYER_FLIP", "1") == "1"   # QOpenGLWidget FBOs are bottom-up

    @staticmethod
    def _get_proc_address(_ctx, name):
        gl = QOpenGLContext.currentContext()
        addr = gl.getProcAddress(name) if gl else None
        return int(addr) if addr else 0

    def initializeGL(self):
        self.ctx = mpv.MpvRenderContext(self.mpv, "opengl", opengl_init_params={"get_proc_address": self._proc})
        self.ctx.update_cb = lambda: self.update_requested.emit()

    def paintGL(self):
        if not self.ctx:
            return
        self.ctx.update()      # mandatory: tells mpv we consumed the "new frame" callback
        r = self.devicePixelRatioF()
        self.ctx.render(flip_y=self._flip,
                        opengl_fbo={"w": int(self.width() * r), "h": int(self.height() * r),
                                    "fbo": self.defaultFramebufferObject()},
                        block_for_target_time=os.environ.get("LIKE_POTPLAYER_BLOCK") == "1")

    def shutdown(self):
        self.makeCurrent()
        if self.ctx:
            self.ctx.free(); self.ctx = None
        self.doneCurrent()
        self.mpv.terminate()


class MpvSoftWidget(_Mixin, QWidget):
    kind = "sw"

    def __init__(self):
        QWidget.__init__(self)
        self._setup("no")                      # software decode: hardware decoders need GL interop
        self.setAttribute(Qt.WA_OpaquePaintEvent)
        self.ctx = mpv.MpvRenderContext(self.mpv, "sw")
        self.ctx.update_cb = lambda: self.update_requested.emit()
        self._img = None

    def paintEvent(self, _):
        w, h = max(2, self.width()), max(2, self.height())
        if self._img is None or self._img.width() != w or self._img.height() != h:
            self._img = QImage(w, h, QImage.Format_RGB32)       # B,G,R,x in memory on little-endian = mpv "bgr0"
            self._img.fill(Qt.black)
        if self.ctx is not None:
            self.ctx.update()
            buf = self._img.bits()
            addr = ctypes.addressof(ctypes.c_char.from_buffer(buf))
            self.ctx.render(sw_size={"w": w, "h": h}, sw_format="bgr0",
                            sw_stride={"value": self._img.bytesPerLine()}, sw_pointer=ctypes.c_void_p(addr))
        p = QPainter(self)
        p.drawImage(0, 0, self._img)

    def shutdown(self):
        if self.ctx is not None:
            self.ctx.free(); self.ctx = None
        self.mpv.terminate()


def gl_is_software():
    """True when Qt's OpenGL is a software rasterizer (or unavailable): the GPU path would be slow or glitchy."""
    try:
        ctx = QOpenGLContext()
        if not ctx.create():
            return True
        surf = QOffscreenSurface(); surf.setFormat(ctx.format()); surf.create()
        if not ctx.makeCurrent(surf):
            return True
        r = ctx.functions().glGetString(0x1F01)            # GL_RENDERER
        ctx.doneCurrent()
        text = (r.decode("utf-8", "replace") if isinstance(r, (bytes, bytearray)) else str(r or "")).lower()
        return any(k in text for k in ("llvmpipe", "softpipe", "swrast", "software", "lavapipe", "gdi generic", "basic render")) or not text
    except Exception:
        return True


def make_view(requested=None):
    r = (requested or os.environ.get("LIKE_POTPLAYER_RENDER") or "auto").lower()
    if r not in ("gl", "sw"):
        r = "sw" if gl_is_software() else "gl"
    if os.environ.get("LIKE_POTPLAYER_DEBUG"):
        print(f"[like_potplayer] video renderer: {r}", file=sys.stderr)
    return MpvSoftWidget() if r == "sw" else MpvGLWidget()
