"""Side panels: page thumbnails and form fields."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QImage, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QFormLayout, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QPushButton, QScrollArea, QVBoxLayout, QWidget)

from ..i18n import tr

THUMB_WIDTH = 120


class ThumbnailList(QListWidget):
    pageActivated = Signal(int)

    def __init__(self):
        super().__init__()
        self.doc = None
        self.setViewMode(QListWidget.ViewMode.IconMode)
        self.setFlow(QListWidget.Flow.TopToBottom)
        self.setWrapping(False)
        self.setMovement(QListWidget.Movement.Static)
        self.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.setIconSize(QSize(THUMB_WIDTH, round(THUMB_WIDTH * 1.42)))
        self.setSpacing(6)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setFixedWidth(THUMB_WIDTH + 52)
        self.itemClicked.connect(lambda item: self.pageActivated.emit(self.row(item)))
        self._queue: list[int] = []
        self._timer = QTimer(self)
        self._timer.setInterval(0)
        self._timer.timeout.connect(self._render_some)

    def set_document(self, doc):
        self.doc = doc
        self.refresh()

    def refresh(self, pages: list[int] | None = None):
        """Rebuild all thumbnails, or only re-render `pages`."""
        if self.doc is None:
            self.clear()
            return
        if pages is None or self.count() != self.doc.page_count:
            selected = self.selected_pages()
            self.clear()
            for i in range(self.doc.page_count):
                item = QListWidgetItem(self._placeholder(i), str(i + 1))
                item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter)
                self.addItem(item)
            for i in selected:
                if i < self.count():
                    self.item(i).setSelected(True)
            pages = list(range(self.doc.page_count))
        self._queue = [p for p in pages if p not in self._queue] + self._queue
        self._timer.start()

    def _placeholder(self, pno: int) -> QIcon:
        w, h = self.doc.page_size(pno)
        pix = QPixmap(THUMB_WIDTH, max(1, round(THUMB_WIDTH * h / w)))
        pix.fill(QColor("white"))
        return QIcon(pix)

    def _render_some(self):
        for _ in range(4):
            if not self._queue or self.doc is None:
                self._timer.stop()
                return
            pno = self._queue.pop(0)
            if pno >= self.count():
                continue
            w, _h = self.doc.page_size(pno)
            pix = self.doc.render(pno, THUMB_WIDTH / w)
            img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGB888).copy()
            self.item(pno).setIcon(QIcon(QPixmap.fromImage(img)))

    def selected_pages(self) -> list[int]:
        return sorted(self.row(i) for i in self.selectedItems())

    def show_current(self, pno: int):
        """Follow scrolling without destroying a deliberate multi-selection."""
        if len(self.selectedItems()) <= 1 and 0 <= pno < self.count():
            self.blockSignals(True)
            self.setCurrentRow(pno)
            self.blockSignals(False)


class FormPanel(QWidget):
    applyRequested = Signal(dict)

    def __init__(self):
        super().__init__()
        self._editors: dict[str, tuple[str, QWidget]] = {}
        self._form_host = QWidget()
        self._form = QFormLayout(self._form_host)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._form_host)
        self._apply = QPushButton(tr("Apply form"))
        self._apply.clicked.connect(self._emit)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.addWidget(scroll, 1)
        lay.addWidget(self._apply)

    def set_fields(self, fields) -> None:
        while self._form.rowCount():
            self._form.removeRow(0)
        self._editors.clear()
        for f in fields:
            if f.kind == "text":
                ed = QLineEdit(str(f.value))
            elif f.kind == "checkbox":
                ed = QCheckBox()
                ed.setChecked(bool(f.value))
            else:
                ed = QComboBox()
                if f.kind == "radio":
                    ed.addItem(tr("— none selected —"), None)
                for c in f.choices:
                    ed.addItem(c, c)
                idx = ed.findData(f.value)
                if idx < 0 and f.value:  # keep a value that is not among the choices
                    ed.addItem(str(f.value), f.value)
                    idx = ed.count() - 1
                ed.setCurrentIndex(max(idx, 0))
            ed.setEnabled(not f.readonly)
            label = QLabel(f"{f.name} <span style='color:gray'>{tr('(p. {page})', page=f.page + 1)}</span>")
            label.setToolTip(f.name)
            self._form.addRow(label, ed)
            self._editors[f.name] = (f.kind, ed)

    def _emit(self):
        values = {}
        for name, (kind, ed) in self._editors.items():
            if not ed.isEnabled():
                continue
            if kind == "text":
                values[name] = ed.text()
            elif kind == "checkbox":
                values[name] = ed.isChecked()
            else:
                values[name] = ed.currentData()
        self.applyRequested.emit(values)
