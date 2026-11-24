"""
dsfskin - load a Daum PotPlayer skin (.dsf = zip of sprite sheet + XML) and render it with Qt.

Written for BlackBoxVFD_PreMod3_AdvCtrl but data-driven: the control-bar layout (button
rectangles, sprite coordinates, tooltips, command ids) is read from the skin's own VideoSkin.xml.
The artwork is NOT bundled; it is read from the user's .dsf at runtime.
"""
import math
import re
import zipfile
from pathlib import Path

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget

# ----------------------------------------------------------------------------- lenient XML
_TAG = re.compile(r"<(/?)([A-Za-z_]\w*)((?:\s+[\w:]+\s*=\s*(?:'[^']*'|\"[^\"]*\"))*)\s*(/?)>", re.S)
_ATTR = re.compile(r"([\w:]+)\s*=\s*(?:'([^']*)'|\"([^\"]*)\")", re.S)


class Node:
    def __init__(self, tag, a=None, parent=None):
        self.tag, self.a, self.parent, self.kids = tag, a or {}, parent, []

    def get(self, k, d=None):
        return self.a.get(k, d)

    def i(self, k, d=0):
        try:
            return int(float(self.a.get(k, d)))
        except (TypeError, ValueError):
            return d

    def walk(self):
        yield self
        for k in self.kids:
            yield from k.walk()


def parse_xml(text):
    """PotPlayer's own parser is forgiving (stray '<' in attributes, mismatched tags); so is this."""
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    root = cur = Node("#root")
    for m in _TAG.finditer(text):
        close, name, attrs, selfc = m.groups()
        if close:
            n = cur
            while n is not None and n.tag != name:
                n = n.parent
            if n is not None and n.parent is not None:
                cur = n.parent
            continue
        a = {k: (v1 if v1 else v2) for k, v1, v2 in _ATTR.findall(attrs)}
        node = Node(name, a, cur)
        cur.kids.append(node)
        if not selfc:
            cur = node
    return root


# ----------------------------------------------------------------------------- skin
VIDEO_CODECS = {  # mpv/lavc codec name -> cell in the 32px label strip (y=1330)
    "mpeg4": 2, "msmpeg4v3": 4, "msmpeg4v2": 5, "msmpeg4v1": 6, "wmv1": 7, "wmv2": 8, "wmv3": 9,
    "vc1": 10, "h263": 11, "h264": 12, "mpeg1video": 13, "mpeg2video": 14, "svq1": 16, "svq3": 17,
    "flv1": 19, "rv10": 20, "rv20": 20, "rv30": 20, "rv40": 20, "theora": 21, "vp6": 22, "vp6f": 22,
    "vp7": 22, "vp8": 22, "vp9": 22, "tscc": 23, "rawvideo": 25, "dvvideo": 26,
}
AUDIO_CODECS = {  # -> cell in the 23px strip (y=1340)
    "mp3": 0, "mp2": 1, "ac3": 2, "eac3": 2, "dts": 3, "wmav1": 4, "wmav2": 4, "wmapro": 4,
    "vorbis": 5, "opus": 5, "aac": 7, "cook": 8, "ra_144": 8, "ape": 10, "tta": 11, "flac": 12,
    "musepack7": 14, "musepack8": 14, "truehd": 16,
}
FILETYPES = ["dvd", "cam", "cap", "atv", "dtv", "asf", "mkv", "real", "mp4", "ogg", "avi", "mpg", "etc"]
EXT_TYPE = {"mkv": "mkv", "mp4": "mp4", "m4v": "mp4", "mov": "mp4", "avi": "avi", "mpg": "mpg",
            "mpeg": "mpg", "ogg": "ogg", "ogv": "ogg", "opus": "ogg", "asf": "asf", "wmv": "asf",
            "wma": "asf", "rm": "real", "rmvb": "real", "iso": "dvd", "vob": "dvd"}
GLYPH_CELL = {".": 9, " ": 10, ":": 21, "-": 22, **{str(d): 11 + d for d in range(10)}}  # 5px cells from x=0


class Skin:
    def __init__(self, path):
        self.path = Path(path)
        self.name = self.path.stem
        with zipfile.ZipFile(path) as z:
            self.sheet = QImage.fromData(z.read("Main.png")).convertToFormat(QImage.Format_ARGB32_Premultiplied)
            self.root = parse_xml(z.read("VideoSkin.xml").decode("utf-8-sig", "replace"))
        self._cache = {}
        area = next(n for n in self.root.walk() if n.tag == "MainSkinArea")
        statics = [n for n in area.walk() if n.tag == "Static"]
        self.title_node = next(n for n in statics if n.get("Align") == "Top" and n.i("Height") == 28)
        self.bar_node = next(n for n in statics if n.get("Align") == "Bottom" and n.i("Height") == 71)
        self.bottom_node = next(n for n in statics if n.get("Align") == "Bottom" and n.i("Height") == 5)
        self.left_node = next(n for n in statics if n.get("Align") == "Left" and n.i("Width") == 5)
        self.right_node = next(n for n in statics if n.get("Align") == "Right" and n.i("Width") == 5
                               and n.get("State") is not None and not n.get("Contain"))

    def spr(self, x, y, w, h):
        k = (x, y, w, h)
        if k not in self._cache:
            self._cache[k] = QPixmap.fromImage(self.sheet.copy(x, y, w, h))
        return self._cache[k]

    def nine(self, p, node, rect, vertical=False):
        """Static strip: fixed LeftMargin/RightMargin ends, stretched middle (or Top/Bottom for vertical)."""
        sx, sy, sw, sh = node.i("ImageLeft"), node.i("ImageTop"), node.i("ImageWidth"), node.i("ImageHeight")
        if vertical:
            p.drawPixmap(rect, self.spr(sx, sy, sw, sh))
            return
        lm, rm = node.i("LeftMargin"), node.i("RightMargin")
        if lm + rm >= sw:
            lm, rm = sw // 2, sw // 2
        p.drawPixmap(QRect(rect.x(), rect.y(), lm, rect.height()), self.spr(sx, sy, lm, sh))
        p.drawPixmap(QRect(rect.right() + 1 - rm, rect.y(), rm, rect.height()), self.spr(sx + sw - rm, sy, rm, sh))
        mid_w = rect.width() - lm - rm
        if mid_w > 0:
            src = self.spr(sx + lm, sy, sw - lm - rm, sh)
            if sw - lm - rm <= 0:
                return
            x = rect.x() + lm
            end = x + mid_w
            while x < end:  # tile the stretch band so the panel art isn't distorted
                w = min(src.width(), end - x)
                p.drawPixmap(QRect(x, rect.y(), w, rect.height()), src, QRect(0, 0, w, src.height()))
                x += w


# ----------------------------------------------------------------------------- helpers
def fmt_time(t):
    t = int(max(0, t or 0))
    return f"{t // 3600:02d}:{t // 60 % 60:02d}:{t % 60:02d}"


class Item:
    __slots__ = ("tag", "cmd", "alt", "tip", "alt_tip", "L", "T", "W", "H", "sx", "sy", "page", "rect",
                 "parent_rect", "node", "text_row")

    def __init__(self, node, ox=0, oy=0, page=0):
        self.node, self.tag, self.page = node, node.tag, page
        self.cmd, self.alt = node.get("CmdID", ""), node.get("AltCmdID", "")
        tips = (node.get("Tooltip", "") or "").split("< >")
        self.tip = tips[0].strip()
        self.alt_tip = tips[1].strip() if len(tips) > 1 else ""
        self.L, self.T = node.i("Left") + ox if node.i("Left") >= 0 else node.i("Left"), node.i("Top") + oy
        self.W, self.H = node.i("Width"), node.i("Height")
        self.sx = node.i("ImageLeft", -1) if node.get("ImageLeft") is not None else None
        self.sy = node.i("ImageTop", -1) if node.get("ImageTop") is not None else None
        self.rect = QRect()
        self.text_row = node.i("ImageTop") if node.tag == "PicLabel" else None


PAGE_TIPS = {"show remaining time": 1, "show elapsed time": 0, "show bitrate": 2,
             "show playback time": 0, "show ab repeat time": 3}


# ----------------------------------------------------------------------------- the bar
class AdvBar(QWidget):
    """The 71px 'advanced control' bar. All state comes from player.st; actions go to player.do()."""
    HEIGHT = 71

    def __init__(self, skin, player):
        super().__init__()
        self.skin, self.p = skin, player
        self.setFixedHeight(self.HEIGHT)
        self.setMinimumWidth(440)
        self.setMouseTracking(True)
        self.items, self.page_rects = [], {}
        self.hover = self.down = None
        self.page = 0
        self._build(skin.bar_node)

    # --- build item list from the skin XML (drawn in file order, hit-tested in reverse)
    def _build(self, bar):
        page_no = 0
        for n in bar.kids:
            if n.tag == "Static" and n.get("State") == "CMD_PAGE_CONTROL":
                page_no += 1
                st = Item(n, page=page_no)
                st.tag = "PageStatic"
                self.items.append(st)
                self.page_rects[page_no] = st
                for c in n.kids:
                    if c.tag in ("Button", "PicLabel", "Image"):
                        self.items.append(Item(c, ox=n.i("Left"), oy=n.i("Top"), page=page_no))
            elif n.tag in ("Button", "PicLabel", "Image", "Slider"):
                self.items.append(Item(n))

    def _layout(self):
        W = self.width()
        for it in self.items:
            x = it.L if it.L >= 0 else W + it.L
            w = it.W if it.W > 0 else (48 if it.tag == "PicLabel" and it.W == 0 else W + it.W)
            it.rect = QRect(x, it.T, max(w, 0), it.H)
        for pg, st in self.page_rects.items():  # page statics: keep fixed width
            st.rect = QRect(st.L, st.T, st.W, st.H)

    def visible(self, it):
        if it.tag == "PageStatic":
            return it.page == self.page
        if it.page:
            return it.page == self.page
        if self.page and self.page in self.page_rects:
            return not it.rect.intersects(self.page_rects[self.page].rect)
        return True

    # --- state helpers
    def st(self):
        return self.p.st

    def label_text(self, it):
        s = self.st()
        c = it.cmd
        if c == "CMD_CURRENTTIME_MESSAGE":
            return fmt_time(s.pos)
        if c == "CMD_LEFTTIME_MESSAGE":
            return "-" + fmt_time(max(0, s.dur - s.pos))
        if c == "CMD_VIDEO_BIT_RATE_MESSAGE":
            return str(int(s.vbr / 1000)) if s.vbr else ""
        if c == "CMD_AUDIO_BIT_RATE_MESSAGE":
            return str(int(s.abr / 1000)) if s.abr else ""
        if c == "CMD_REPEAT_START_MESSAGE":
            return fmt_time(s.ab_a) if s.ab_a is not None else "00:00:00"
        if c == "CMD_REPEAT_END_MESSAGE":
            return fmt_time(s.ab_b) if s.ab_b is not None else "00:00:00"
        return ""

    def slider_frac(self, it):
        s = self.st()
        if it.cmd == "CMD_TIMEBAR_CTRL":
            return (s.pos / s.dur) if s.dur else 0.0
        if it.cmd == "CMD_VOLUME_CTRL":
            return max(0.0, min(1.0, s.volume / 100.0))
        if it.cmd == "CMD_SPEED_CTRL":
            return max(0.0, min(1.0, math.log2(max(0.25, s.speed) / 0.25) / 4.0))
        return 0.0

    def slider_set(self, it, f):
        f = max(0.0, min(1.0, f))
        if it.cmd == "CMD_TIMEBAR_CTRL":
            self.p.do(("seek_fraction", f))
        elif it.cmd == "CMD_VOLUME_CTRL":
            self.p.do(("set_volume", f * 100))
        elif it.cmd == "CMD_SPEED_CTRL":
            self.p.do(("set_speed", 0.25 * 2 ** (f * 4)))

    # --- painting
    def paintEvent(self, _):
        self._layout()
        p = QPainter(self)
        sk = self.skin
        W = self.width()
        n = sk.bar_node
        # background: left 336 + stretched/tiled middle + right 10
        sx, sy, sw, sh = n.i("ImageLeft"), n.i("ImageTop"), n.i("ImageWidth"), n.i("ImageHeight")
        sk.nine(p, n, QRect(0, 0, W, self.HEIGHT))
        for it in self.items:
            if not self.visible(it):
                continue
            if it.tag == "PageStatic":
                sk.nine(p, it.node, it.rect)
            elif it.tag == "Slider":
                self._paint_slider(p, it)
            elif it.tag == "Button":
                self._paint_button(p, it)
            elif it.tag == "PicLabel":
                self._paint_label(p, it)
            elif it.tag == "Image" and it.cmd == "CMD_PLAY_FILE_TYPE":
                self._paint_cell(p, it, 0, 192, 23, 9, FILETYPES.index(self.st().filetype)
                                 if self.st().filetype in FILETYPES else 12)

    def _paint_slider(self, p, it):
        frac = self.slider_frac(it)
        r = it.rect
        segs = max(1, (r.width() + 2) // 5)
        filled = round(segs * frac)
        y0 = r.y() + (r.height() - 5) // 2
        for i in range(segs):
            x = r.x() + i * 5
            on = i < filled
            for row in range(5):
                col = (115, 207, 229) if on and row in (0, 4) else (52, 108, 126) if on else (24, 24, 24)
                p.fillRect(x, y0 + row, 3, 1, QColor(*col))

    def _button_state(self, it):
        s = self.st()
        on = False
        c = it.cmd
        if c == "ID_AUDIO_MUTE":
            on = s.mute
        elif c in s.toggles:
            on = s.toggles[c]
        if self.down is it:
            return 2
        if self.hover is it:
            return 1
        return 1 if on and c != "ID_AUDIO_MUTE" else (2 if on else 0)

    def _button_visible(self, it):
        s = self.st()
        if it.cmd == "CMD_MEDIA_PLAY":
            return s.paused
        if it.cmd == "CMD_MEDIA_PAUSE":
            return not s.paused
        return True

    def _paint_button(self, p, it):
        if it.sx is None or not self._button_visible(it):
            return
        idx = self._button_state(it)
        p.drawPixmap(it.rect.topLeft(), self.skin.spr(it.sx + idx * it.W, it.sy, it.W, it.H))

    def _paint_cell(self, p, it, ox, sy, cw, ch, idx):
        if idx is None:
            return
        p.drawPixmap(it.rect.x(), it.rect.y(), self.skin.spr(ox + idx * cw, sy, cw, ch))

    def _paint_label(self, p, it):
        c, s = it.cmd, self.st()
        if c == "CMD_VIDEO_CODEC_FOURCC_MESSAGE":
            idx = VIDEO_CODECS.get(s.vcodec)
            return self._label_or_text(p, it, 32, 1330, 32, 9, idx, s.vcodec.upper()[:6])
        if c == "CMD_AUDIO_CODEC_TAG_MESSAGE":
            idx = AUDIO_CODECS.get(s.acodec)
            if idx is None and s.acodec.startswith("pcm"):
                idx = 15
            return self._label_or_text(p, it, 23, 1340, 23, 9, idx, s.acodec.upper()[:5])
        if c == "CMD_AUDIO_IN_NUM_CHANNEL_MESSAGE":
            idx = {1: 0, 2: 1, 3: 2, 4: 3, 5: 4, 6: 5, 7: 6, 8: 7}.get(s.channels)
            return self._label_or_text(p, it, 23, 1350, 23, 9, idx, f"{s.channels}CH" if s.channels else "")
        text = self.label_text(it)
        if not text or it.text_row is None:
            return
        gw, gh = 5, 7
        total = gw * len(text)
        x = it.rect.x() + (it.rect.width() - total) // 2
        y = it.rect.y() + (it.rect.height() - gh) // 2
        for ch in text:
            cell = GLYPH_CELL.get(ch)
            if cell is not None:
                p.drawPixmap(x, y, self.skin.spr(cell * gw, it.text_row, gw, gh))
            x += gw

    def _label_or_text(self, p, it, cw, sy, cellw, ch, idx, fallback):
        if idx is not None:
            p.drawPixmap(it.rect.x(), it.rect.y(), self.skin.spr(idx * cw, sy, cellw, ch))
        elif fallback:  # codec not in the skin's label strip -> same look, drawn
            r = QRect(it.rect.x(), it.rect.y(), cellw - 2, ch)
            p.setPen(QPen(QColor(52, 108, 126)))
            p.drawRect(r.adjusted(0, 0, 0, -1))
            f = QFont("monospace"); f.setPixelSize(7); f.setBold(True)
            p.setFont(f); p.setPen(QColor(115, 207, 229))
            p.drawText(r, Qt.AlignCenter, fallback)

    # --- mouse
    def _hit(self, pos):
        self._layout()
        for it in reversed(self.items):
            if it.tag in ("PageStatic",):
                if self.visible(it) and it.rect.contains(pos):
                    return None  # page panel swallows clicks that aren't on its own children
                continue
            if not self.visible(it) or not it.rect.contains(pos):
                continue
            if it.tag == "Button" and not self._button_visible(it):
                continue
            if it.tag == "PicLabel" or (it.tag == "Image" and not it.tip):
                continue
            if it.tag == "Button" and not it.cmd:
                continue
            return it
        return None

    def mouseMoveEvent(self, e):
        if self.down is not None and self.down.tag == "Slider":
            r = self.down.rect
            self.slider_set(self.down, (e.position().x() - r.x()) / max(1, r.width()))
            return
        h = self._hit(e.position().toPoint())
        if h is not self.hover:
            self.hover = h
            self.update()
        if h is not None and (h.tip or h.alt_tip):
            self.setToolTip(h.tip + (f"\n(right-click: {h.alt_tip})" if h.alt_tip else ""))
        else:
            self.setToolTip("")

    def leaveEvent(self, _):
        self.hover = None
        self.update()

    def mousePressEvent(self, e):
        h = self._hit(e.position().toPoint())
        if h is None:
            if e.button() == Qt.RightButton:
                self.p.context_menu(e.globalPosition().toPoint())
            return
        if e.button() == Qt.LeftButton:
            self.down = h
            if h.tag == "Slider":
                self.slider_set(h, (e.position().x() - h.rect.x()) / max(1, h.rect.width()))
            self.update()
        elif e.button() == Qt.RightButton and h.tag == "Button" and h.alt:
            self.p.bar_command(h.alt, h, right=True)

    def mouseReleaseEvent(self, e):
        h, d = self._hit(e.position().toPoint()), self.down
        self.down = None
        if d is not None and e.button() == Qt.LeftButton and d is h and d.tag != "Slider":
            tgt = PAGE_TIPS.get(d.tip.lower()) if d.cmd == "CMD_SELECT_PAGE" else None
            if tgt is not None:
                self.page = tgt
            else:
                self.p.bar_command(d.cmd, d, right=False)
        self.update()

    def wheelEvent(self, e):
        self.p.on_gesture("wheel_up" if e.angleDelta().y() > 0 else "wheel_down")


# ----------------------------------------------------------------------------- frame pieces
class TitleBar(QWidget):
    HEIGHT = 28

    def __init__(self, skin, player):
        super().__init__()
        self.skin, self.p = skin, player
        self.setFixedHeight(self.HEIGHT)
        self.setMouseTracking(True)
        self.buttons = []  # (cmd, alt, sprite xy, w, h, left, top, tip)
        for b in skin.title_node.kids:
            if b.tag == "Button":
                self.buttons.append(b)
        self.hover = self.down = None
        self.title = ""

    def _rect(self, b):
        W = self.width()
        l = b.i("Left")
        x = l if l >= 0 else W + l
        return QRect(x, b.i("Top"), b.i("Width"), b.i("Height"))

    def _shown(self, b):
        c = b.get("CmdID")
        if c == "CMD_MAX_WINDOW":
            return not self.window().isMaximized()
        if c == "CMD_RESTORE_WINDOW":
            return self.window().isMaximized()
        return True

    def paintEvent(self, _):
        p = QPainter(self)
        n = self.skin.title_node
        self.skin.nine(p, n, QRect(0, 0, self.width(), self.HEIGHT))
        for b in self.buttons:
            if not self._shown(b):
                continue
            r = self._rect(b)
            idx = 2 if self.down is b else 1 if self.hover is b else 0
            p.drawPixmap(r.topLeft(), self.skin.spr(b.i("ImageLeft") + idx * r.width(), b.i("ImageTop"), r.width(), r.height()))
        # title text (Label CMD_TITLE_MESSAGE: Left=70, width fills)
        lab = next((k for k in n.kids if k.tag == "Label"), None)
        if lab:
            x = lab.i("Left"); w = self.width() + lab.i("Width") - x
            p.setPen(QColor(190, 205, 215))
            f = QFont(); f.setPixelSize(11); p.setFont(f)
            fm = p.fontMetrics()
            p.drawText(QRect(x, lab.i("Top") - 2, w, 16), Qt.AlignLeft | Qt.AlignVCenter,
                       fm.elidedText(self.title, Qt.ElideRight, w))

    def _hit(self, pos):
        for b in self.buttons:
            if self._shown(b) and self._rect(b).contains(pos):
                return b
        return None

    def mouseMoveEvent(self, e):
        h = self._hit(e.position().toPoint())
        if h is not self.hover:
            self.hover = h
            self.setToolTip((h.get("Tooltip", "") or "").split("< >")[0] if h else "")
            self.update()

    def leaveEvent(self, _):
        self.hover = None
        self.update()

    def mousePressEvent(self, e):
        h = self._hit(e.position().toPoint())
        if h is None:
            if e.button() == Qt.LeftButton:
                self.window().windowHandle().startSystemMove()
            return
        if e.button() == Qt.LeftButton:
            self.down = h
        elif e.button() == Qt.RightButton and h.get("AltCmdID"):
            self.p.bar_command(h.get("AltCmdID"), h, right=True)
        self.update()

    def mouseReleaseEvent(self, e):
        h, d = self._hit(e.position().toPoint()), self.down
        self.down = None
        if d is not None and d is h and e.button() == Qt.LeftButton:
            self.p.bar_command(d.get("CmdID"), d, right=False)
        self.update()

    def mouseDoubleClickEvent(self, e):
        if self._hit(e.position().toPoint()) is None:
            self.p.bar_command("CMD_MAX_WINDOW" if not self.window().isMaximized() else "CMD_RESTORE_WINDOW", None, False)


class Border(QWidget):
    """5px frame strip (left / right / bottom). Doubles as a resize handle."""

    def __init__(self, skin, kind):
        super().__init__()
        self.skin, self.kind = skin, kind
        node = {"left": skin.left_node, "right": skin.right_node, "bottom": skin.bottom_node}[kind] if skin else None
        self.node = node
        if kind == "bottom":
            self.setFixedHeight(5)
        else:
            self.setFixedWidth(5)
        self.setMouseTracking(True)
        self.setCursor({"left": Qt.SizeHorCursor, "right": Qt.SizeHorCursor, "bottom": Qt.SizeVerCursor}[kind])

    def paintEvent(self, _):
        p = QPainter(self)
        if self.skin is None:                      # plain (default Qt) frame
            p.fillRect(self.rect(), QColor(42, 49, 64))
            return
        n = self.node
        if self.kind == "bottom":
            self.skin.nine(p, n, QRect(0, 0, self.width(), 5))
        else:
            self.skin.nine(p, n, QRect(0, 0, 5, self.height()), vertical=True)

    def _edges(self, pos):
        if self.kind == "left":
            e = Qt.LeftEdge
            if pos.y() > self.height() - 12:
                e |= Qt.BottomEdge
        elif self.kind == "right":
            e = Qt.RightEdge
            if pos.y() > self.height() - 12:
                e |= Qt.BottomEdge
        else:
            e = Qt.BottomEdge
            if pos.x() < 12:
                e |= Qt.LeftEdge
            elif pos.x() > self.width() - 12:
                e |= Qt.RightEdge
        return e

    def mouseMoveEvent(self, e):
        ed = self._edges(e.position().toPoint())
        diag = (ed & Qt.BottomEdge) and (ed & (Qt.LeftEdge | Qt.RightEdge))
        if diag:
            self.setCursor(Qt.SizeBDiagCursor if ed & Qt.LeftEdge else Qt.SizeFDiagCursor)
        else:
            self.setCursor(Qt.SizeVerCursor if self.kind == "bottom" else Qt.SizeHorCursor)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.window().windowHandle().startSystemResize(self._edges(e.position().toPoint()))


class PlainTitleBar(QWidget):
    """Title bar for the built-in (non-skin) look: title, minimize / maximize / close, drag, double-click."""
    HEIGHT = 26

    def __init__(self, player):
        super().__init__()
        self.p, self.title, self.hover = player, "", None
        self.setFixedHeight(self.HEIGHT)
        self.setMouseTracking(True)

    def _btns(self):
        w = self.width()
        return {"min": QRect(w - 84, 3, 26, 20), "max": QRect(w - 56, 3, 26, 20), "close": QRect(w - 28, 3, 26, 20)}

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(42, 49, 64))
        p.setPen(QColor(201, 211, 227))
        f = QFont(); f.setPixelSize(12); p.setFont(f)
        p.drawText(QRect(10, 0, self.width() - 100, self.HEIGHT), Qt.AlignVCenter | Qt.AlignLeft,
                   p.fontMetrics().elidedText(self.title, Qt.ElideRight, self.width() - 100))
        for k, r in self._btns().items():
            if self.hover == k:
                p.fillRect(r, QColor(200, 50, 50) if k == "close" else QColor(58, 68, 90))
            p.setPen(QPen(QColor(220, 228, 240), 1.6))
            c = r.center()
            if k == "min":
                p.drawLine(c.x() - 5, c.y() + 4, c.x() + 5, c.y() + 4)
            elif k == "max":
                p.drawRect(c.x() - 5, c.y() - 5, 10, 9)
            else:
                p.drawLine(c.x() - 5, c.y() - 5, c.x() + 5, c.y() + 5)
                p.drawLine(c.x() + 5, c.y() - 5, c.x() - 5, c.y() + 5)

    def _hit(self, pos):
        return next((k for k, r in self._btns().items() if r.contains(pos)), None)

    def mouseMoveEvent(self, e):
        h = self._hit(e.position().toPoint())
        if h != self.hover:
            self.hover = h
            self.update()

    def leaveEvent(self, _):
        self.hover = None
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and self._hit(e.position().toPoint()) is None:
            self.window().windowHandle().startSystemMove()

    def mouseReleaseEvent(self, e):
        h = self._hit(e.position().toPoint())
        if h and e.button() == Qt.LeftButton:
            w = self.window()
            if h == "min":
                w.showMinimized()
            elif h == "max":
                w.showNormal() if w.isMaximized() else w.showMaximized()
            else:
                w.close()

    def mouseDoubleClickEvent(self, e):
        if self._hit(e.position().toPoint()) is None:
            w = self.window()
            w.showNormal() if w.isMaximized() else w.showMaximized()
