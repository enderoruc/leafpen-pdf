"""Render leafpen/assets/icon.svg into the Windows icon leafpen/assets/icon.ico.

Run after changing the SVG:  .venv\\Scripts\\python tools\\make_icon.py
The .ico holds PNG images (supported since Windows Vista) at the sizes Explorer and the taskbar use.
"""
import os
import struct
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

ASSETS = Path(__file__).resolve().parents[1] / "leafpen" / "assets"
SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def render_png(renderer: QSvgRenderer, size: int) -> bytes:
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    renderer.render(p, QRectF(0, 0, size, size))
    p.end()
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(data)


def build_ico(images: list[tuple[int, bytes]]) -> bytes:
    """ICONDIR + one ICONDIRENTRY per image, followed by the PNG data."""
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = len(header) + 16 * len(images)
    entries, blobs = b"", b""
    for size, png in images:
        dim = 0 if size >= 256 else size  # 0 means 256
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(png), offset)
        blobs += png
        offset += len(png)
    return header + entries + blobs


def main() -> int:
    app = QGuiApplication(sys.argv)  # noqa: F841 (needed for rendering)
    renderer = QSvgRenderer(str(ASSETS / "icon.svg"))
    if not renderer.isValid():
        print("icon.svg could not be read", file=sys.stderr)
        return 1
    images = [(s, render_png(renderer, s)) for s in SIZES]
    (ASSETS / "icon.ico").write_bytes(build_ico(images))
    print(f"wrote {ASSETS / 'icon.ico'} ({', '.join(str(s) for s in SIZES)} px)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
