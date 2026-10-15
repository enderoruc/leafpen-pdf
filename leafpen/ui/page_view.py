"""Scrollable, zoomable page view with mouse tools.

Pages render lazily in paintEvent, so only visible pages cost anything. All
coordinates emitted to the outside are display coordinates in PDF points.
"""
from __future__ import annotations

from collections import OrderedDict
from enum import Enum, auto

import pymupdf
from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QScrollArea, QVBoxLayout, QWidget


class Tool(Enum):
    BROWSE = auto()
    ADD_TEXT = auto()
    EDIT_TEXT = auto()
    HIGHLIGHT = auto()
    PEN = auto()
    IMAGE = auto()
    SIGNATURE = auto()
    ERASE = auto()
    DIGITAL_SIGN = auto()


RECT_TOOLS = {Tool.HIGHLIGHT, Tool.IMAGE, Tool.SIGNATURE, Tool.DIGITAL_SIGN}
CLICK_TOOLS = {Tool.ADD_TEXT, Tool.EDIT_TEXT, Tool.ERASE}
HOVER_TOOLS = {Tool.EDIT_TEXT, Tool.ERASE}

_CURSORS = {
    Tool.BROWSE: Qt.CursorShape.OpenHandCursor,
    Tool.ADD_TEXT: Qt.CursorShape.IBeamCursor,
    Tool.EDIT_TEXT: Qt.CursorShape.IBeamCursor,
    Tool.ERASE: Qt.CursorShape.PointingHandCursor,
}

ACCENT = QColor(37, 99, 235)


class PageWidget(QWidget):
    def __init__(self, view: "PageView", pno: int):
        super().__init__()
        self.view = view
        self.pno = pno
        self.setMouseTracking(True)
        self._drag_start: QPointF | None = None
        self._drag_now: QPointF | None = None
        self._stroke: list[QPointF] | None = None
        self._hover: pymupdf.Rect | None = None
        self._pan_origin: QPoint | None = None

    def _pt(self, pos: QPointF) -> tuple[float, float]:
        z = self.view.zoom
        return pos.x() / z, pos.y() / z

    def clear_overlay(self):
        self._drag_start = self._drag_now = self._stroke = self._hover = None
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.drawImage(self.rect(), self.view.page_image(self.pno))
        z = self.view.zoom
        if self._hover is not None:
            r = self._hover
            p.setPen(QPen(ACCENT, 1.5))
            p.setBrush(QColor(37, 99, 235, 30))
            p.drawRect(QRectF(r.x0 * z - 2, r.y0 * z - 2, r.width * z + 4, r.height * z + 4))
        if self._drag_start is not None and self._drag_now is not None:
            p.setPen(QPen(ACCENT, 1.5, Qt.PenStyle.DashLine))
            p.setBrush(QColor(37, 99, 235, 25))
            p.drawRect(QRectF(self._drag_start, self._drag_now).normalized())
        if self._stroke:
            pen = QPen(self.view.pen_color, max(1.0, self.view.pen_width * z))
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            path = QPainterPath(self._stroke[0])
            for q in self._stroke[1:]:
                path.lineTo(q)
            p.drawPath(path)

    def mousePressEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton:
            return
        tool = self.view.tool
        pos = e.position()
        if tool in RECT_TOOLS:
            self._drag_start = self._drag_now = pos
        elif tool == Tool.PEN:
            self._stroke = [pos]
        elif tool in CLICK_TOOLS:
            self.view.pointClicked.emit(self.pno, *self._pt(pos))
        else:
            self._pan_origin = e.globalPosition().toPoint()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, e):
        pos = e.position()
        if self._drag_start is not None:
            self._drag_now = QPointF(min(max(pos.x(), 0), self.width()), min(max(pos.y(), 0), self.height()))
            self.update()
        elif self._stroke is not None:
            self._stroke.append(pos)
            self.update()
        elif self._pan_origin is not None:
            now = e.globalPosition().toPoint()
            delta = now - self._pan_origin
            self._pan_origin = now
            self.view.horizontalScrollBar().setValue(self.view.horizontalScrollBar().value() - delta.x())
            self.view.verticalScrollBar().setValue(self.view.verticalScrollBar().value() - delta.y())
        elif self.view.tool in HOVER_TOOLS and self.view.hover_provider:
            rect = self.view.hover_provider(self.view.tool, self.pno, *self._pt(pos))
            if rect != self._hover:
                self._hover = rect
                self.update()

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton:
            return
        if self._drag_start is not None:
            a, b = self._pt(self._drag_start), self._pt(self._drag_now or self._drag_start)
            rect = pymupdf.Rect(min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1]))
            self._drag_start = self._drag_now = None
            self.update()
            self.view.rectDrawn.emit(self.pno, rect)
        elif self._stroke is not None:
            pts = [self._pt(q) for q in self._stroke]
            self._stroke = None
            self.view.strokeDrawn.emit(self.pno, pts)
            self.update()
        elif self._pan_origin is not None:
            self._pan_origin = None
            self.setCursor(_CURSORS.get(self.view.tool, Qt.CursorShape.CrossCursor))

    def leaveEvent(self, _e):
        if self._hover is not None:
            self._hover = None
            self.update()


class PageView(QScrollArea):
    rectDrawn = Signal(int, object)  # page, pymupdf.Rect
    pointClicked = Signal(int, float, float)
    strokeDrawn = Signal(int, list)
    currentPageChanged = Signal(int)
    zoomChanged = Signal(float)

    MIN_ZOOM, MAX_ZOOM = 0.25, 5.0
    CACHE_SIZE = 24

    def __init__(self):
        super().__init__()
        self.doc = None
        self.zoom = 1.0
        self.tool = Tool.BROWSE
        self.pen_color = QColor(0, 0, 0)
        self.pen_width = 2.0
        self.hover_provider = None  # (tool, page, x, y) -> pymupdf.Rect | None
        self._cache: OrderedDict[int, QImage] = OrderedDict()
        self._pages: list[PageWidget] = []
        self._current = 0

        self._container = QWidget()
        self._container.setObjectName("pageContainer")
        self._layout = QVBoxLayout(self._container)
        self._layout.setSpacing(14)
        self._layout.setContentsMargins(20, 20, 20, 20)
        self._layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.setWidget(self._container)
        self.setWidgetResizable(True)
        self.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.verticalScrollBar().valueChanged.connect(self._track_current)

    # ---- document --------------------------------------------------------

    def set_document(self, doc):
        self.doc = doc
        self._current = 0
        self.reload()
        self.verticalScrollBar().setValue(0)

    def reload(self):
        """Re-render after the document changed (content, rotation or page count)."""
        self._cache.clear()
        count = self.doc.page_count if self.doc else 0
        while len(self._pages) > count:
            w = self._pages.pop()
            self._layout.removeWidget(w)
            w.deleteLater()
        while len(self._pages) < count:
            w = PageWidget(self, len(self._pages))
            w.setCursor(_CURSORS.get(self.tool, Qt.CursorShape.CrossCursor))
            self._layout.addWidget(w, 0, Qt.AlignmentFlag.AlignHCenter)
            self._pages.append(w)
        self._apply_sizes()
        for w in self._pages:
            w.clear_overlay()
        self._track_current()

    def _apply_sizes(self):
        for w in self._pages:
            width, height = self.doc.page_size(w.pno)
            w.setFixedSize(round(width * self.zoom), round(height * self.zoom))

    def page_image(self, pno: int) -> QImage:
        img = self._cache.get(pno)
        if img is not None:
            self._cache.move_to_end(pno)
            return img
        dpr = self.devicePixelRatioF()
        pix = self.doc.render(pno, self.zoom * dpr)
        img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGB888).copy()
        img.setDevicePixelRatio(dpr)
        self._cache[pno] = img
        while len(self._cache) > self.CACHE_SIZE:
            self._cache.popitem(last=False)
        return img

    # ---- navigation & zoom -------------------------------------------------

    def current_page(self) -> int:
        return self._current

    def _track_current(self):
        if not self._pages:
            return
        middle = self.verticalScrollBar().value() + self.viewport().height() / 3
        current = 0
        for w in self._pages:
            if w.y() <= middle:
                current = w.pno
            else:
                break
        if current != self._current:
            self._current = current
            self.currentPageChanged.emit(current)

    def go_to(self, pno: int):
        if 0 <= pno < len(self._pages):
            self._container.adjustSize()
            self.verticalScrollBar().setValue(self._pages[pno].y() - 10)

    def set_zoom(self, zoom: float):
        zoom = min(max(zoom, self.MIN_ZOOM), self.MAX_ZOOM)
        if not self.doc or abs(zoom - self.zoom) < 1e-3:
            return
        bar = self.verticalScrollBar()
        frac = bar.value() / max(1, bar.maximum())
        self.zoom = zoom
        self._cache.clear()
        self._apply_sizes()
        self._container.adjustSize()
        bar.setValue(round(frac * bar.maximum()))
        self.zoomChanged.emit(zoom)

    def fit_width(self):
        if not self.doc:
            return
        widest = max(self.doc.page_size(i)[0] for i in range(self.doc.page_count))
        available = self.viewport().width() - 40 - self.verticalScrollBar().sizeHint().width()
        self.set_zoom(available / widest)

    def wheelEvent(self, e):
        if e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            step = 1.1 if e.angleDelta().y() > 0 else 1 / 1.1
            self.set_zoom(self.zoom * step)
            e.accept()
        else:
            super().wheelEvent(e)

    # ---- tools ---------------------------------------------------------------

    def set_tool(self, tool: Tool):
        self.tool = tool
        cursor = _CURSORS.get(tool, Qt.CursorShape.CrossCursor)
        for w in self._pages:
            w.setCursor(cursor)
            w.clear_overlay()
