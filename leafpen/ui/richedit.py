"""On-page text editing: a text box with a formatting bar, laid over the page.

The box shows the text at the page's zoom with the same fonts that will be
written into the PDF, so what you type is roughly what you get. Nothing is
written until the edit is confirmed.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, Qt
from PySide6.QtGui import (QColor, QIcon, QPainter, QPalette, QPen, QPixmap, QTextBlockFormat, QTextCharFormat,
                           QTextCursor, QTextOption)
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QDoubleSpinBox, QFrame, QHBoxLayout, QTextEdit, QToolButton,
                               QWidget)

from ..core import fonts
from ..core.richtext import ALIGNS, TextRun, TextStyle, normalize
from ..i18n import tr
from .dialogs import ColorButton

QT_FAMILY = {"sans": "Arial", "serif": "Times New Roman", "mono": "Courier New"}
_QT_ALIGN = {"left": Qt.AlignmentFlag.AlignLeft, "center": Qt.AlignmentFlag.AlignHCenter,
             "right": Qt.AlignmentFlag.AlignRight, "justify": Qt.AlignmentFlag.AlignJustify}
# Qt's natural line spacing for these fonts, as a multiple of the font size.
_QT_LINE_FACTOR = 1.15
_BOLD, _NORMAL = 700, 400
_CTRL_EDIT_KEYS = {Qt.Key.Key_Z, Qt.Key.Key_Y, Qt.Key.Key_A, Qt.Key.Key_C, Qt.Key.Key_V, Qt.Key.Key_X, Qt.Key.Key_B,
                   Qt.Key.Key_I, Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Left, Qt.Key.Key_Right,
                   Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_Home, Qt.Key.Key_End, Qt.Key.Key_Backspace,
                   Qt.Key.Key_Delete}


def family_of(qt_family: str) -> str:
    for key, name in QT_FAMILY.items():
        if name.lower() == qt_family.lower():
            return key
    return fonts.classify(qt_family, 0)[0]


def char_format(style: TextStyle, scale: float) -> QTextCharFormat:
    """Qt format for `style`; `scale` converts PDF points to the editor's Qt points."""
    f = QTextCharFormat()
    f.setFontFamilies([QT_FAMILY.get(style.family, "Arial")])
    f.setFontPointSize(style.size * scale)
    f.setFontWeight(_BOLD if style.bold else _NORMAL)
    f.setFontItalic(style.italic)
    f.setForeground(QColor.fromRgbF(*style.color))
    return f


def style_of(fmt: QTextCharFormat, scale: float, default: TextStyle) -> TextStyle:
    families = fmt.fontFamilies() or []
    family = family_of(families[0]) if families else default.family
    size = round(fmt.fontPointSize() / scale, 1) if fmt.fontPointSize() > 0 else default.size
    brush = fmt.foreground()
    color = brush.color() if brush.style() != Qt.BrushStyle.NoBrush else QColor.fromRgbF(*default.color)
    return TextStyle(family, int(fmt.fontWeight()) >= 600, fmt.fontItalic(), size,
                     (round(color.redF(), 4), round(color.greenF(), 4), round(color.blueF(), 4)))


def _align_icon(align: str, color: QColor) -> QIcon:
    pix = QPixmap(32, 32)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setPen(QPen(color, 3))
    for i, length in enumerate((24, 16, 24, 12)):
        if align == "justify" and i < 3:
            length = 24
        x = {"left": 4, "center": 16 - length / 2, "right": 28 - length}.get(align, 4)
        p.drawLine(round(x), 6 + i * 7, round(x + length), 6 + i * 7)
    p.end()
    return QIcon(pix)


@dataclass
class EditResult:
    runs: list[TextRun]
    align: str
    line_height: float
    width: float  # PDF points


class TextBox(QTextEdit):
    """The editing surface. Keeps the keys it needs away from the window's shortcuts."""

    def __init__(self, parent, on_commit: Callable[[], None], on_cancel: Callable[[], None]):
        super().__init__(parent)
        self._commit, self._cancel = on_commit, on_cancel
        self.setAcceptRichText(False)  # pasted text takes the current format, not foreign fonts
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.document().setDocumentMargin(0)
        self.setStyleSheet("QTextEdit { background: white; border: 1px solid #2563eb; }")
        self.setViewportMargins(0, 0, 0, 0)

    def event(self, e):
        if e.type() == QEvent.Type.ShortcutOverride:
            mods = e.modifiers() & ~Qt.KeyboardModifier.KeypadModifier
            typing = mods in (Qt.KeyboardModifier.NoModifier, Qt.KeyboardModifier.ShiftModifier)
            editing = (mods & Qt.KeyboardModifier.ControlModifier) and e.key() in _CTRL_EDIT_KEYS
            if typing or editing:
                e.accept()  # typing, Esc and Ctrl+Z/Y/B/I/Enter belong to the text box; Ctrl+S etc. do not
                return True
        return super().event(e)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self._cancel()
            return
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self._commit()
            return
        if e.modifiers() == Qt.KeyboardModifier.ControlModifier and e.key() in (Qt.Key.Key_B, Qt.Key.Key_I):
            fmt = QTextCharFormat()
            if e.key() == Qt.Key.Key_B:
                fmt.setFontWeight(_NORMAL if self.fontWeight() >= 600 else _BOLD)
            else:
                fmt.setFontItalic(not self.fontItalic())
            self.mergeCurrentCharFormat(fmt)
            return
        super().keyPressEvent(e)


class FormatBar(QFrame):
    """Font, size, bold, italic, color, alignment and line spacing for the text box."""

    def __init__(self, parent, editor: "InlineTextEditor", paragraph: bool):
        super().__init__(parent)
        self.editor = editor
        self.setObjectName("formatBar")
        self.setAutoFillBackground(True)
        self.setStyleSheet("#formatBar { background: palette(window); border: 1px solid palette(mid);"
                           " border-radius: 4px; }")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 3, 4, 3)
        lay.setSpacing(3)
        self.family = QComboBox()
        for key, label in fonts.FAMILY_LABELS.items():
            self.family.addItem(label, key)
        self.family.setToolTip(tr("Font"))
        self.family.activated.connect(lambda _i: editor.apply(family=self.family.currentData()))
        self.size = QDoubleSpinBox()
        self.size.setRange(4, 1000)  # pages made from photos are several times larger than A4
        self.size.setDecimals(1)
        self.size.setSuffix(" pt")
        self.size.setToolTip(tr("Size"))
        self.size.setKeyboardTracking(False)  # typed sizes apply on Enter or leaving the field
        self.size.valueChanged.connect(lambda v: editor.apply(size=v, focus=not self.size.hasFocus()))
        self.bold = self._toggle("B", tr("Bold (Ctrl+B)"), lambda on: editor.apply(bold=on))
        f = self.bold.font()
        f.setBold(True)
        self.bold.setFont(f)
        self.italic = self._toggle("I", tr("Italic (Ctrl+I)"), lambda on: editor.apply(italic=on))
        f = self.italic.font()
        f.setItalic(True)
        self.italic.setFont(f)
        self.color = ColorButton(QColor("black"))
        self.color.setFixedWidth(28)
        self.color.clicked.connect(lambda: editor.apply(color=self.color.color))
        for w in (self.family, self.size, self.bold, self.italic, self.color):
            lay.addWidget(w)
        self.aligns = QButtonGroup(self)
        self.aligns.setExclusive(True)
        self.spacing = None
        if paragraph:
            lay.addSpacing(6)
            fg = self.palette().color(QPalette.ColorRole.WindowText)
            tips = {"left": tr("Align left"), "center": tr("Center"), "right": tr("Align right"),
                    "justify": tr("Justify")}
            for align in ALIGNS:
                b = QToolButton()
                b.setCheckable(True)
                b.setIcon(_align_icon(align, fg))
                b.setToolTip(tips[align])
                b.setProperty("align", align)
                self.aligns.addButton(b)
                lay.addWidget(b)
            self.aligns.buttonClicked.connect(lambda b: editor.set_align(b.property("align")))
            self.spacing = QDoubleSpinBox()
            self.spacing.setRange(1.0, 3.0)
            self.spacing.setSingleStep(0.1)
            self.spacing.setDecimals(2)
            self.spacing.setPrefix("↕ ")
            self.spacing.setToolTip(tr("Line spacing"))
            self.spacing.valueChanged.connect(editor.set_line_height)
            lay.addWidget(self.spacing)
        lay.addSpacing(6)
        ok = QToolButton()
        ok.setText("✓")
        ok.setToolTip(tr("Apply (Ctrl+Enter)"))
        ok.clicked.connect(editor.commit)
        cancel = QToolButton()
        cancel.setText("✕")
        cancel.setToolTip(tr("Cancel (Esc)"))
        cancel.clicked.connect(editor.cancel)
        lay.addWidget(ok)
        lay.addWidget(cancel)
        self.adjustSize()

    def _toggle(self, text: str, tip: str, slot) -> QToolButton:
        b = QToolButton()
        b.setText(text)
        b.setCheckable(True)
        b.setToolTip(tip)
        b.clicked.connect(slot)  # clicks only: show_style() sets the state without applying it
        return b

    def show_style(self, style: TextStyle):
        for w in (self.family, self.size, self.bold, self.italic):
            w.blockSignals(True)
        self.family.setCurrentIndex(max(0, self.family.findData(style.family)))
        self.size.setValue(style.size)
        self.bold.setChecked(style.bold)
        self.italic.setChecked(style.italic)
        self.color.set_color(QColor.fromRgbF(*style.color))
        for w in (self.family, self.size, self.bold, self.italic):
            w.blockSignals(False)

    def show_paragraph(self, align: str, line_height: float):
        for b in self.aligns.buttons():
            b.setChecked(b.property("align") == align)
        if self.spacing is not None:
            self.spacing.blockSignals(True)
            self.spacing.setValue(line_height)
            self.spacing.blockSignals(False)


class InlineTextEditor(QObject):
    """Edits styled text in place on a page widget; calls `on_commit(EditResult)` or `on_cancel()`."""

    def __init__(self, page: QWidget, zoom: float, x: float, top: float, width: float, runs: list[TextRun],
                 default: TextStyle, *, paragraph: bool, align: str = "left", line_height: float = 1.2,
                 min_height: float = 0, on_commit: Callable[[EditResult], None],
                 on_cancel: Callable[[], None] | None = None):
        super().__init__(page)
        self.page = page
        self.zoom = zoom
        self.x, self.top, self.width = x, top, width
        self.min_height = min_height
        self.default = default
        self.paragraph = paragraph
        self.align = align if paragraph else "left"
        self.line_height = line_height
        self._on_commit, self._on_cancel = on_commit, on_cancel
        self._done = False
        # PDF points -> the editor's Qt points (Qt points are 1/72 inch at the widget's logical dpi).
        self.scale = zoom * 72 / page.logicalDpiY()

        self.box = TextBox(page, self.commit, self.cancel)
        if not paragraph:
            self.box.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        else:
            self.box.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        # The bar lives on the page container so it is not clipped at the page edge.
        self.host = page.parentWidget() or page
        self.bar = FormatBar(self.host, self, paragraph)
        self.handle = None
        if paragraph:  # drag the right edge to change the wrapping width
            self.handle = QFrame(page)
            self.handle.setCursor(Qt.CursorShape.SizeHorCursor)
            self.handle.setStyleSheet("background: #2563eb; border-radius: 2px;")
            self.handle.setToolTip(tr("Drag to change the width"))
            self.handle.installEventFilter(self)
            self._drag_x: float | None = None

        self._load(runs)
        self.box.currentCharFormatChanged.connect(self._format_changed)
        self.box.document().contentsChanged.connect(self._layout)
        self.bar.show_style(self._style_at_cursor())
        self.bar.show_paragraph(self.align, self.line_height)
        for w in (self.box, self.bar, self.handle):
            if w is not None:
                w.show()
                w.raise_()
        self._layout()
        self.box.setFocus()
        self.box.moveCursor(QTextCursor.MoveOperation.End)

    # ---- content -------------------------------------------------------------------

    def _load(self, runs: list[TextRun]):
        doc = self.box.document()
        doc.clear()
        cursor = QTextCursor(doc)
        first = runs[0].style if runs else self.default
        self.box.setCurrentCharFormat(char_format(first, self.scale))
        for run in runs:
            parts = run.text.replace("\r\n", "\n").split("\n")
            for i, part in enumerate(parts):
                if i:
                    cursor.insertBlock()
                cursor.insertText(part, char_format(run.style, self.scale))
        self._apply_block_format()
        doc.setModified(False)
        self.box.document().clearUndoRedoStacks()

    def result(self) -> EditResult:
        runs: list[TextRun] = []
        block = self.box.document().begin()
        while block.isValid():
            if runs:
                runs.append(TextRun("\n", runs[-1].style))
            it = block.begin()
            while not it.atEnd():
                frag = it.fragment()
                if frag.isValid():
                    text = frag.text().replace(" ", "\n").replace(" ", "\n")
                    runs.append(TextRun(text, style_of(frag.charFormat(), self.scale, self.default)))
                it += 1
            block = block.next()
        return EditResult(normalize(runs), self.align, self.line_height, self.width)

    def _style_at_cursor(self) -> TextStyle:
        return style_of(self.box.currentCharFormat(), self.scale, self.default)

    def _format_changed(self, fmt: QTextCharFormat):
        self.bar.show_style(style_of(fmt, self.scale, self.default))

    # ---- formatting ----------------------------------------------------------------

    def apply(self, *, family=None, size=None, bold=None, italic=None, color=None, focus=True):
        """Format the selection, or the whole text if nothing is selected (and what is typed next)."""
        fmt = QTextCharFormat()
        if family is not None:
            fmt.setFontFamilies([QT_FAMILY[family]])
        if size is not None:
            fmt.setFontPointSize(size * self.scale)
        if bold is not None:
            fmt.setFontWeight(_BOLD if bold else _NORMAL)
        if italic is not None:
            fmt.setFontItalic(italic)
        if color is not None:
            fmt.setForeground(QColor(color))
        if not self.box.textCursor().hasSelection():
            cursor = QTextCursor(self.box.document())
            cursor.select(QTextCursor.SelectionType.Document)
            cursor.mergeCharFormat(fmt)
            cursor.mergeBlockCharFormat(fmt)  # an empty box keeps it when clicked into
        self.box.mergeCurrentCharFormat(fmt)
        if focus:
            self.box.setFocus()

    def set_align(self, align: str):
        self.align = align
        self.bar.show_paragraph(align, self.line_height)
        self._apply_block_format()
        self.box.setFocus()

    def set_line_height(self, value: float):
        self.line_height = value
        self._apply_block_format()

    def _apply_block_format(self):
        fmt = QTextBlockFormat()
        fmt.setAlignment(_QT_ALIGN[self.align])
        if self.paragraph:
            fmt.setLineHeight(self.line_height / _QT_LINE_FACTOR * 100,
                              QTextBlockFormat.LineHeightTypes.ProportionalHeight.value)
        cursor = QTextCursor(self.box.document())
        cursor.select(QTextCursor.SelectionType.Document)
        cursor.mergeBlockFormat(fmt)
        self._layout()

    # ---- geometry --------------------------------------------------------------------

    def _layout(self):
        z = self.zoom
        doc = self.box.document()
        if self.paragraph:
            doc.setTextWidth(self.width * z)
            width_px = self.width * z
        else:
            doc.setTextWidth(-1)
            width_px = max(doc.idealWidth(), 40)
        height_px = max(doc.size().height(), self.min_height * z, 12)
        pad = 2
        box = QRect(round(self.x * z) - pad, round(self.top * z) - pad, round(width_px) + 2 * pad + 6,
                    round(height_px) + 2 * pad)
        self.box.setGeometry(box)
        if self.handle is not None:
            self.handle.setGeometry(box.right() + 2, box.top() + box.height() // 2 - 12, 5, 24)
        bar = self.bar.sizeHint()
        origin = self.page.mapTo(self.host, QPoint(0, 0)) if self.host is not self.page else QPoint(0, 0)
        bx = min(max(0, origin.x() + box.left()), max(0, self.host.width() - bar.width()))
        by = origin.y() + box.top() - bar.height() - 4
        if by < 0:
            by = origin.y() + box.bottom() + 4
        self.bar.setGeometry(bx, by, bar.width(), bar.height())

    def eventFilter(self, obj, e):
        if obj is self.handle:
            if e.type() == QEvent.Type.MouseButtonPress:
                self._drag_x = e.globalPosition().x()
                return True
            if e.type() == QEvent.Type.MouseMove and self._drag_x is not None:
                dx = (e.globalPosition().x() - self._drag_x) / self.zoom
                self._drag_x = e.globalPosition().x()
                limit = self.page.width() / self.zoom - self.x
                self.width = min(max(self.width + dx, 4 * self.default.size), limit)
                self._layout()
                return True
            if e.type() == QEvent.Type.MouseButtonRelease:
                self._drag_x = None
                self.box.setFocus()
                return True
        return super().eventFilter(obj, e)

    # ---- finishing ---------------------------------------------------------------------

    def commit(self):
        if self._done:
            return
        result = self.result()
        self._close()
        self._on_commit(result)

    def cancel(self):
        if self._done:
            return
        self._close()
        if self._on_cancel:
            self._on_cancel()

    def _close(self):
        self._done = True
        for w in (self.box, self.bar, self.handle):
            if w is not None:
                w.hide()
                w.deleteLater()
        self.deleteLater()

    @property
    def done(self) -> bool:
        return self._done
