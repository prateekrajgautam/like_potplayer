#!/usr/bin/env python3
"""
Turn one master icon (SVG or PNG) into the files each OS needs.
Usage: python tools/make_icons.py [master.svg|png] [out_dir]     (needs PySide6 + Pillow)
Outputs: out_dir/app-<size>.png, app.ico (Windows), app.icns (macOS)
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")   # no display needed

from PIL import Image
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter

root = Path(__file__).resolve().parent.parent
master = Path(sys.argv[1]) if len(sys.argv) > 1 else root / "like_potplayer" / "assets" / "icon.svg"
out = Path(sys.argv[2]) if len(sys.argv) > 2 else root / "like_potplayer" / "assets" / "build"
out.mkdir(parents=True, exist_ok=True)
app = QGuiApplication([])
SIZES = [16, 32, 48, 64, 128, 256, 512, 1024]


def render(size):
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    if master.suffix.lower() == ".svg":
        from PySide6.QtSvg import QSvgRenderer
        QSvgRenderer(str(master)).render(p, QRectF(0, 0, size, size))
    else:
        src = QImage(str(master))
        p.drawImage(QRectF(0, 0, size, size), src)
    p.end()
    return img


for s in SIZES:
    render(s).save(str(out / f"app-{s}.png"))
big = Image.open(out / "app-1024.png").convert("RGBA")
big.save(out / "app.ico", sizes=[(s, s) for s in (16, 32, 48, 64, 128, 256)])
big.save(out / "app.icns")
print("wrote", sorted(p.name for p in out.iterdir()))
