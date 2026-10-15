"""Command palette (Ctrl+K): find any menu command or tool by typing part of its name."""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QDialog, QHeaderView, QLineEdit, QMenu, QMenuBar, QTreeWidget, QTreeWidgetItem, QVBoxLayout

from ..core.document import fold
from ..i18n import tr


@dataclass
class Command:
    title: str
    path: str  # where it lives in the menus, e.g. "Document › Watermark"
    shortcut: str
    action: QAction


def _clean(text: str) -> str:
    """Menu text without accelerator marks ("&File" -> "File", "A && B" -> "A & B")."""
    return text.replace("&&", "\0").replace("&", "").replace("\0", "&").strip()


def collect(menubar: QMenuBar) -> list[Command]:
    """Every command in the menus, in menu order (submenus included)."""
    out: list[Command] = []
    seen: set[int] = set()

    def walk(menu: QMenu, path: list[str]):
        menu.aboutToShow.emit()  # menus filled on demand (recent files) fill themselves now
        for a in menu.actions():
            if a.isSeparator() or not a.isVisible():
                continue
            if a.menu() is not None:
                walk(a.menu(), path + [_clean(a.text())])
                continue
            if id(a) in seen or not _clean(a.text()):
                continue
            seen.add(id(a))
            out.append(Command(_clean(a.text()), " › ".join(path), a.shortcut().toString(), a))

    for a in menubar.actions():
        if a.menu() is not None:
            walk(a.menu(), [_clean(a.text())])
    return out


def _loose(text: str) -> str:
    """Case-folded and without accents, so "dikdortgen" finds "Dikdörtgen" (typing without Turkish letters)."""
    decomposed = unicodedata.normalize("NFKD", fold(text))
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def rank(commands: list[Command], query: str) -> list[Command]:
    """Commands containing every typed word (ignoring case and accents), best matches first."""
    words = _loose(query).split()
    if not words:
        return list(commands)
    scored = []
    for i, c in enumerate(commands):
        title, where = _loose(c.title), _loose(c.path)
        haystack = f"{title} {where}"
        if not all(w in haystack for w in words):
            continue
        score = 0
        for w in words:
            if title.startswith(w):
                score += 3
            elif f" {w}" in f" {title}":
                score += 2
            elif w in title:
                score += 1
        scored.append((-score, i, c))
    scored.sort(key=lambda t: (t[0], t[1]))
    return [c for _s, _i, c in scored]


class CommandPalette(QDialog):
    def __init__(self, parent, commands: list[Command]):
        super().__init__(parent, Qt.WindowType.Popup)
        self.commands = commands
        self.chosen: QAction | None = None
        self.edit = QLineEdit()
        self.edit.setPlaceholderText(tr("Type a command…"))
        self.edit.setClearButtonEnabled(True)
        self.edit.textChanged.connect(self._filter)
        self.edit.installEventFilter(self)
        self.list = QTreeWidget()
        self.list.setColumnCount(3)
        self.list.setHeaderHidden(True)
        self.list.setRootIsDecorated(False)
        self.list.setUniformRowHeights(True)
        self.list.setAllColumnsShowFocus(True)
        header = self.list.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.list.itemActivated.connect(lambda _item, _col: self._run())
        self.list.itemClicked.connect(lambda _item, _col: self._run())
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.addWidget(self.edit)
        lay.addWidget(self.list)
        self.setStyleSheet("CommandPalette { border: 1px solid palette(mid); }")
        self.resize(620, 420)
        self._filter("")

    def _filter(self, text: str):
        self.list.clear()
        dim = self.palette().color(self.palette().ColorRole.PlaceholderText)
        for c in rank(self.commands, text):
            item = QTreeWidgetItem([c.title, c.path, c.shortcut])
            item.setData(0, Qt.ItemDataRole.UserRole, c.action)
            for col in (1, 2):
                item.setForeground(col, dim)
            item.setTextAlignment(2, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            if not c.action.isEnabled():
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
                item.setToolTip(0, tr("Not available now (open a document first)."))
            self.list.addTopLevelItem(item)
        first = next((self.list.topLevelItem(i) for i in range(self.list.topLevelItemCount())
                      if self.list.topLevelItem(i).flags() & Qt.ItemFlag.ItemIsEnabled), None)
        if first is not None:
            self.list.setCurrentItem(first)

    def _run(self):
        item = self.list.currentItem()
        if item is None or not item.flags() & Qt.ItemFlag.ItemIsEnabled:
            return
        self.chosen = item.data(0, Qt.ItemDataRole.UserRole)
        self.accept()

    def eventFilter(self, obj, e):
        if obj is self.edit and e.type() == QEvent.Type.KeyPress:
            if e.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_PageUp, Qt.Key.Key_PageDown):
                self.list.setFocus()
                self.list.keyPressEvent(e)  # move the selection, keep typing in the box
                self.edit.setFocus()
                return True
            if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._run()
                return True
            if e.key() == Qt.Key.Key_Escape:
                self.reject()
                return True
        return super().eventFilter(obj, e)


def run_palette(window) -> None:
    """Show the palette over `window` and trigger the chosen command after it closes."""
    palette = CommandPalette(window, collect(window.menuBar()))
    geo = window.geometry()
    palette.move(geo.x() + (geo.width() - palette.width()) // 2, geo.y() + 70)
    palette.edit.setFocus()
    if palette.exec() and palette.chosen is not None:
        palette.chosen.trigger()
