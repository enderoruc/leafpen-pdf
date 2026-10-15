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

from .richedit import InlineTextEditor


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
    EDIT_PARAGRAPH = auto()
    RECT = auto()
    ELLIPSE = auto()
    LINE = auto()
    ARROW = auto()
    NOTE = auto()
    STAMP = auto()
    REDACT = auto()
    CROP = auto()
    FORM_FIELD = auto()
    SELECT = auto()


RECT_TOOLS = {Tool.HIGHLIGHT, Tool.IMAGE, Tool.SIGNATURE, Tool.DIGITAL_SIGN, Tool.RECT, Tool.ELLIPSE,
              Tool.STAMP, Tool.REDACT, Tool.CROP, Tool.FORM_FIELD}
LINE_TOOLS = {Tool.LINE, Tool.ARROW}
CLICK_TOOLS = {Tool.ADD_TEXT, Tool.EDIT_TEXT, Tool.EDIT_PARAGRAPH, Tool.ERASE, Tool.NOTE}
HOVER_TOOLS = {Tool.EDIT_TEXT, Tool.EDIT_PARAGRAPH, Tool.ERASE, Tool.NOTE}

_CURSORS = {
    Tool.BROWSE: Qt.CursorShape.OpenHandCursor,
    Tool.ADD_TEXT: Qt.CursorShape.IBeamCursor,
    Tool.EDIT_TEXT: Qt.CursorShape.IBeamCursor,
    Tool.EDIT_PARAGRAPH: Qt.CursorShape.IBeamCursor,
    Tool.ERASE: Qt.CursorShape.PointingHandCursor,
    Tool.NOTE: Qt.CursorShape.PointingHandCursor,
    Tool.SELECT: Qt.CursorShape.ArrowCursor,
}

# Resize handles: name -> (x factor, y factor) along the selection rect.
_HANDLES = {"tl": (0, 0), "t": (0.5, 0), "tr": (1, 0), "r": (1, 0.5), "br": (1, 1), "b": (0.5, 1), "bl": (0, 1),
            "l": (0, 0.5)}
_HANDLE_CURSORS = {"tl": Qt.CursorShape.SizeFDiagCursor, "br": Qt.CursorShape.SizeFDiagCursor,
                   "tr": Qt.CursorShape.SizeBDiagCursor, "bl": Qt.CursorShape.SizeBDiagCursor,
                   "t": Qt.CursorShape.SizeVerCursor, "b": Qt.CursorShape.SizeVerCursor,
                   "l": Qt.CursorShape.SizeHorCursor, "r": Qt.CursorShape.SizeHorCursor,
                   "p0": Qt.CursorShape.CrossCursor, "p1": Qt.CursorShape.CrossCursor}
_HANDLE_PX = 7

ACCENT = QColor(37, 99, 235)
REDACT = QColor(220, 38, 38)
HIT = QColor(250, 204, 21, 110)
CURRENT_HIT = QColor(249, 115, 22, 150)


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
        # select tool: what is being dragged ("move", a handle name, "p0"/"p1"), from where, and the preview
        self._sel_mode: str | None = None
        self._sel_origin: QPointF | None = None
        self._sel_rect: pymupdf.Rect | None = None
        self._sel_line: tuple[pymupdf.Point, pymupdf.Point] | None = None

    def _pt(self, pos: QPointF) -> tuple[float, float]:
        z = self.view.zoom
        return pos.x() / z, pos.y() / z

    def clear_overlay(self):
        self._drag_start = self._drag_now = self._stroke = self._hover = None
        self._sel_mode = self._sel_origin = self._sel_rect = self._sel_line = None
        self.update()

    # ---- select tool ---------------------------------------------------------------

    def _selection(self):
        sel = self.view.selection
        return sel if sel is not None and sel.page == self.pno else None

    def _handle_points(self, rect: pymupdf.Rect, sel) -> dict[str, QPointF]:
        z = self.view.zoom
        if sel.line is not None:
            line = self._sel_line or sel.line
            return {"p0": QPointF(line[0].x * z, line[0].y * z), "p1": QPointF(line[1].x * z, line[1].y * z)}
        if not sel.resizable:
            return {}
        return {name: QPointF((rect.x0 + fx * rect.width) * z, (rect.y0 + fy * rect.height) * z)
                for name, (fx, fy) in _HANDLES.items()}

    def _handle_at(self, pos: QPointF, sel) -> str | None:
        for name, hp in self._handle_points(sel.rect, sel).items():
            if abs(hp.x() - pos.x()) <= _HANDLE_PX and abs(hp.y() - pos.y()) <= _HANDLE_PX:
                return name
        return None

    def _select_press(self, pos: QPointF):
        x, y = self._pt(pos)
        sel = self._selection()
        mode = None
        if sel is not None:
            mode = self._handle_at(pos, sel)
            if mode is None and sel.movable and pymupdf.Point(x, y) in sel.rect + (-3, -3, 3, 3):
                mode = "move"
        if mode is None:
            sel = self.view.select_provider(self.pno, x, y) if self.view.select_provider else None
            self.view.set_selection(sel)
            mode = "move" if sel is not None and sel.movable else None
        if mode is not None:
            self._sel_mode, self._sel_origin = mode, pos
            self._sel_rect = pymupdf.Rect(sel.rect)
            self._sel_line = tuple(pymupdf.Point(p) for p in sel.line) if sel.line else None

    def _select_drag(self, pos: QPointF):
        sel = self._selection()
        if sel is None:
            return
        z = self.view.zoom
        dx, dy = (pos.x() - self._sel_origin.x()) / z, (pos.y() - self._sel_origin.y()) / z
        w, h = self.width() / z, self.height() / z
        r = pymupdf.Rect(sel.rect)
        mode = self._sel_mode
        if mode == "move":
            dx = min(max(dx, -r.x0), w - r.x1)  # stay on the page
            dy = min(max(dy, -r.y0), h - r.y1)
            self._sel_rect = r + (dx, dy, dx, dy)
            if sel.line:
                self._sel_line = tuple(p + (dx, dy) for p in sel.line)
        elif mode in ("p0", "p1"):
            ends = list(sel.line)
            i = int(mode[1])
            ends[i] = pymupdf.Point(min(max(ends[i].x + dx, 0), w), min(max(ends[i].y + dy, 0), h))
            self._sel_line = tuple(ends)
            self._sel_rect = pymupdf.Rect(ends[0], ends[0]) | ends[1]
        else:
            x0, y0, x1, y1 = r
            if "l" in mode:
                x0 = min(max(x0 + dx, 0), x1 - 4)
            if "r" in mode:
                x1 = max(min(x1 + dx, w), x0 + 4)
            if "t" in mode:
                y0 = min(max(y0 + dy, 0), y1 - 4)
            if mode in ("b", "bl", "br"):
                y1 = max(min(y1 + dy, h), y0 + 4)
            self._sel_rect = pymupdf.Rect(x0, y0, x1, y1)
        self.update()

    def _select_release(self):
        sel = self._selection()
        rect, line = self._sel_rect, self._sel_line
        moved = sel is not None and rect is not None and (
            any(abs(a - b) > 0.5 for a, b in zip(rect, sel.rect))
            or (line is not None and any(abs(a - b) > 0.5 for p, q in zip(line, sel.line) for a, b in zip(p, q))))
        self._sel_mode = self._sel_origin = self._sel_rect = self._sel_line = None
        self.update()
        if moved:
            self.view.objectChanged.emit(sel, rect, tuple(tuple(p) for p in line) if line else None)

    def _paint_selection(self, p: QPainter):
        sel = self._selection()
        if sel is None:
            return
        z = self.view.zoom
        rect = self._sel_rect or sel.rect
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(ACCENT, 1.5, Qt.PenStyle.DashLine))
        p.setBrush(Qt.BrushStyle.NoBrush)
        if sel.line is not None:
            a, b = self._sel_line or sel.line
            p.drawLine(QPointF(a.x * z, a.y * z), QPointF(b.x * z, b.y * z))
        else:
            p.drawRect(QRectF(rect.x0 * z - 2, rect.y0 * z - 2, rect.width * z + 4, rect.height * z + 4))
        p.setPen(QPen(ACCENT, 1.2))
        p.setBrush(QColor("white"))
        s = _HANDLE_PX - 2
        for hp in self._handle_points(rect, sel).values():
            p.drawRect(QRectF(hp.x() - s / 2 - 1, hp.y() - s / 2 - 1, s + 2, s + 2))

    def mouseDoubleClickEvent(self, e):
        sel = self._selection()
        if self.view.tool == Tool.SELECT and sel is not None and e.button() == Qt.MouseButton.LeftButton:
            if pymupdf.Point(*self._pt(e.position())) in sel.rect + (-3, -3, 3, 3):
                self.view.objectActivated.emit(sel)
                return
        super().mouseDoubleClickEvent(e)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.drawImage(self.rect(), self.view.page_image(self.pno))
        z = self.view.zoom
        hits = self.view.search_hits.get(self.pno)
        if hits:
            p.setPen(Qt.PenStyle.NoPen)
            current = self.view.current_hit
            for r in hits:
                p.setBrush(CURRENT_HIT if current is not None and current[0] == self.pno and current[1] == r
                           else HIT)
                p.drawRect(QRectF(r.x0 * z - 1, r.y0 * z - 1, r.width * z + 2, r.height * z + 2))
        if self._hover is not None:
            r = self._hover
            p.setPen(QPen(ACCENT, 1.5))
            p.setBrush(QColor(37, 99, 235, 30))
            p.drawRect(QRectF(r.x0 * z - 2, r.y0 * z - 2, r.width * z + 4, r.height * z + 4))
        if self._drag_start is not None and self._drag_now is not None:
            tool = self.view.tool
            if tool in LINE_TOOLS:
                p.setRenderHint(QPainter.RenderHint.Antialiasing)
                p.setPen(QPen(self.view.pen_color, max(1.0, self.view.pen_width * z)))
                p.drawLine(self._drag_start, self._drag_now)
            else:
                color = REDACT if tool == Tool.REDACT else ACCENT
                p.setPen(QPen(color, 1.5, Qt.PenStyle.DashLine))
                p.setBrush(QColor(color.red(), color.green(), color.blue(), 25))
                box = QRectF(self._drag_start, self._drag_now).normalized()
                if tool == Tool.ELLIPSE:
                    p.setRenderHint(QPainter.RenderHint.Antialiasing)
                    p.drawEllipse(box)
                else:
                    p.drawRect(box)
        if self.view.tool == Tool.SELECT:
            self._paint_selection(p)
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
        if self.view.inline is not None:  # a click outside the text box confirms the edit
            self.view.finish_inline(commit=True)
            return
        tool = self.view.tool
        pos = e.position()
        if tool == Tool.SELECT:
            self.view.setFocus()  # for Delete and the arrow keys
            self._select_press(pos)
        elif tool in RECT_TOOLS or tool in LINE_TOOLS:
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
        if self._sel_mode is not None:
            self._select_drag(pos)
        elif self.view.tool == Tool.SELECT:
            sel = self._selection()
            handle = self._handle_at(pos, sel) if sel is not None else None
            if handle:
                self.setCursor(_HANDLE_CURSORS[handle])
            elif sel is not None and sel.movable and pymupdf.Point(*self._pt(pos)) in sel.rect:
                self.setCursor(Qt.CursorShape.SizeAllCursor)
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)
        elif self._drag_start is not None:
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
        if self._sel_mode is not None:
            self._select_release()
        elif self._drag_start is not None:
            a, b = self._pt(self._drag_start), self._pt(self._drag_now or self._drag_start)
            self._drag_start = self._drag_now = None
            self.update()
            if self.view.tool in LINE_TOOLS:
                self.view.lineDrawn.emit(self.pno, a, b)
            else:
                rect = pymupdf.Rect(min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1]))
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
    lineDrawn = Signal(int, object, object)  # page, (x, y) start, (x, y) end
    objectSelected = Signal(object)  # PageObject or None
    objectChanged = Signal(object, object, object)  # PageObject, new display rect, new line endpoints or None
    objectActivated = Signal(object)  # double-clicked PageObject
    deleteSelection = Signal()
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
        self.select_provider = None  # (page, x, y) -> PageObject | None
        self.selection = None  # the selected PageObject
        self.search_hits: dict[int, list[pymupdf.Rect]] = {}
        self.current_hit: tuple[int, pymupdf.Rect] | None = None
        self._cache: OrderedDict[int, QImage] = OrderedDict()
        self._pages: list[PageWidget] = []
        self._current = 0
        self.inline: InlineTextEditor | None = None

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
        self.finish_inline(commit=False)  # the text under the box may have changed
        self.set_selection(None)  # objects are re-read after a change
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

    def show_rect(self, pno: int, rect: pymupdf.Rect):
        """Scroll so that `rect` (display coordinates) on page `pno` is visible."""
        if 0 <= pno < len(self._pages):
            self._container.adjustSize()
            w = self._pages[pno]
            z = self.zoom
            self.ensureVisible(round(w.x() + rect.x0 * z), round(w.y() + rect.y0 * z), 80, 120)

    def set_search_hits(self, hits: dict[int, list[pymupdf.Rect]], current: tuple[int, pymupdf.Rect] | None):
        self.search_hits = hits
        self.current_hit = current
        for w in self._pages:
            w.update()

    def set_zoom(self, zoom: float):
        zoom = min(max(zoom, self.MIN_ZOOM), self.MAX_ZOOM)
        if not self.doc or abs(zoom - self.zoom) < 1e-3:
            return
        self.finish_inline(commit=True)
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

    def start_inline(self, pno: int, **kwargs) -> InlineTextEditor:
        """Open a text box on page `pno` (arguments as for `InlineTextEditor`, coordinates in PDF points)."""
        self.finish_inline(commit=True)
        commit, cancel = kwargs.pop("on_commit"), kwargs.pop("on_cancel", None)

        def done_commit(result):
            self.inline = None
            commit(result)

        def done_cancel():
            self.inline = None
            if cancel:
                cancel()

        self.inline = InlineTextEditor(self._pages[pno], self.zoom, on_commit=done_commit, on_cancel=done_cancel,
                                       **kwargs)
        return self.inline

    def finish_inline(self, commit: bool = True):
        if self.inline is not None and not self.inline.done:
            (self.inline.commit if commit else self.inline.cancel)()
        self.inline = None

    def set_selection(self, obj):
        if obj is None and self.selection is None:
            return
        self.selection = obj
        for w in self._pages:
            w.update()
        self.objectSelected.emit(obj)

    def keyPressEvent(self, e):
        sel = self.selection
        if self.tool == Tool.SELECT and sel is not None:
            if e.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
                self.deleteSelection.emit()
                return
            step = 10 if e.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1
            delta = {Qt.Key.Key_Left: (-step, 0), Qt.Key.Key_Right: (step, 0), Qt.Key.Key_Up: (0, -step),
                     Qt.Key.Key_Down: (0, step)}.get(e.key())
            if delta and sel.movable:
                dx, dy = delta
                line = tuple((p.x + dx, p.y + dy) for p in sel.line) if sel.line else None
                self.objectChanged.emit(sel, sel.rect + (dx, dy, dx, dy), line)
                return
        super().keyPressEvent(e)

    def set_tool(self, tool: Tool):
        self.finish_inline(commit=True)
        if tool != Tool.SELECT:
            self.set_selection(None)
        self.tool = tool
        cursor = _CURSORS.get(tool, Qt.CursorShape.CrossCursor)
        for w in self._pages:
            w.setCursor(cursor)
            w.clear_overlay()
