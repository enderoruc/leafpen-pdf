"""Side panels (page thumbnails, bookmarks, form fields) and the find bar."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QImage, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QFormLayout, QFrame,
                               QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton,
                               QScrollArea, QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

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


class BookmarkPanel(QWidget):
    """The document outline. Indexes refer to positions in `PdfDocument.bookmarks()`."""
    pageActivated = Signal(int)
    addRequested = Signal(object)  # index to insert after, or None
    renameRequested = Signal(int)
    deleteRequested = Signal(int)

    def __init__(self):
        super().__init__()
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.itemClicked.connect(self._activate)
        self.tree.itemActivated.connect(self._activate)
        self.tree.itemSelectionChanged.connect(self._update_buttons)
        self._add = QPushButton(tr("Add"))
        self._add.setToolTip(tr("Add a bookmark to the current page"))
        self._add.clicked.connect(lambda: self.addRequested.emit(self.current_index()))
        self._rename = QPushButton(tr("Rename"))
        self._rename.clicked.connect(lambda: self._emit_selected(self.renameRequested))
        self._delete = QPushButton(tr("Delete"))
        self._delete.clicked.connect(lambda: self._emit_selected(self.deleteRequested))
        row = QHBoxLayout()
        row.setSpacing(2)
        for b in (self._add, self._rename, self._delete):
            row.addWidget(b)
        self._empty = QLabel(tr("No bookmarks. Use Add to bookmark the current page."))
        self._empty.setWordWrap(True)
        self._empty.setStyleSheet("color: gray;")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.addLayout(row)
        lay.addWidget(self._empty)
        lay.addWidget(self.tree, 1)
        self.set_bookmarks([], enabled=False)

    def set_bookmarks(self, bookmarks, enabled: bool = True) -> None:
        selected = self.current_index()
        self.tree.clear()
        parents: list[QTreeWidgetItem] = []
        for i, b in enumerate(bookmarks):
            item = QTreeWidgetItem([b.title])
            item.setData(0, Qt.ItemDataRole.UserRole, i)
            item.setData(0, Qt.ItemDataRole.UserRole + 1, b.page)
            if b.page >= 0:
                item.setToolTip(0, tr("Page {number}", number=b.page + 1))
            del parents[b.level - 1:]
            if parents:
                parents[-1].addChild(item)
            else:
                self.tree.addTopLevelItem(item)
            parents.append(item)
            if i == selected:
                self.tree.setCurrentItem(item)
        self.tree.expandAll()
        self._empty.setVisible(enabled and not bookmarks)
        self._add.setEnabled(enabled)
        self._update_buttons()

    def current_index(self) -> int | None:
        item = self.tree.currentItem()
        return None if item is None or not item.isSelected() else item.data(0, Qt.ItemDataRole.UserRole)

    def _update_buttons(self):
        has = self.current_index() is not None
        self._rename.setEnabled(has)
        self._delete.setEnabled(has)

    def _emit_selected(self, signal):
        index = self.current_index()
        if index is not None:
            signal.emit(index)

    def _activate(self, item: QTreeWidgetItem, _column: int = 0):
        page = item.data(0, Qt.ItemDataRole.UserRole + 1)
        if page is not None and page >= 0:
            self.pageActivated.emit(page)


class FindBar(QFrame):
    """Search field with previous/next and "mark all for redaction"."""
    searchRequested = Signal(str)
    nextRequested = Signal()
    previousRequested = Signal()
    redactAllRequested = Signal()
    closed = Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName("findBar")
        self.setStyleSheet("#findBar { border-bottom: 1px solid palette(mid); }")
        self.edit = QLineEdit()
        self.edit.setPlaceholderText(tr("Find in document"))
        self.edit.setClearButtonEnabled(True)
        self.edit.setMaximumWidth(320)
        self.edit.returnPressed.connect(self._enter)
        self.edit.installEventFilter(self)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(300)
        self._timer.timeout.connect(lambda: self.searchRequested.emit(self.edit.text()))
        self.edit.textChanged.connect(lambda _t: self._timer.start())
        prev = QToolButton()
        prev.setText("▲")
        prev.setToolTip(tr("Previous (Shift+Enter)"))
        prev.clicked.connect(self.previousRequested)
        nxt = QToolButton()
        nxt.setText("▼")
        nxt.setToolTip(tr("Next (Enter)"))
        nxt.clicked.connect(self.nextRequested)
        self.status = QLabel()
        self.redact = QPushButton(tr("Mark all for redaction"))
        self.redact.setToolTip(tr("Mark every match for redaction. Nothing is removed until you apply "
                                  "the redactions."))
        self.redact.clicked.connect(self.redactAllRequested)
        close = QToolButton()
        close.setText("✕")
        close.setToolTip(tr("Close (Esc)"))
        close.clicked.connect(self.close_bar)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 3, 8, 3)
        for w in (self.edit, prev, nxt, self.status):
            lay.addWidget(w)
        lay.addStretch()
        lay.addWidget(self.redact)
        lay.addWidget(close)
        self.set_status(None)

    def open_bar(self):
        self.show()
        self.edit.setFocus()
        self.edit.selectAll()

    def close_bar(self):
        self._timer.stop()
        self.hide()
        self.closed.emit()

    def _enter(self):
        if self._timer.isActive():  # search for what was just typed first
            self._timer.stop()
            self.searchRequested.emit(self.edit.text())
        elif QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier:
            self.previousRequested.emit()
        else:
            self.nextRequested.emit()

    def set_status(self, current: int | None, total: int = 0):
        if not self.edit.text().strip():
            self.status.clear()
        elif total == 0:
            self.status.setText(tr("No matches"))
        else:
            self.status.setText(tr("{current} of {total}", current=(current or 0) + 1, total=total))
        self.redact.setEnabled(total > 0)

    def eventFilter(self, obj, e):
        # Esc is also the Browse tool's shortcut; claim it while typing so it closes the bar.
        if obj is self.edit and e.type() == QEvent.Type.ShortcutOverride and e.key() == Qt.Key.Key_Escape:
            e.accept()
            return True
        return super().eventFilter(obj, e)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.close_bar()
            return
        super().keyPressEvent(e)


class FormPanel(QWidget):
    applyRequested = Signal(dict)
    addFieldRequested = Signal()

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
        add = QPushButton(tr("Add field…"))
        add.setToolTip(tr("Draw a new form field on the page"))
        add.clicked.connect(self.addFieldRequested)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.addWidget(scroll, 1)
        lay.addWidget(self._apply)
        lay.addWidget(add)

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
