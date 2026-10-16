from __future__ import annotations

import html
import os
import uuid
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, QRect, QSize, QStandardPaths, Qt
from PySide6.QtGui import (QColor, QFont, QFontDatabase, QIcon, QImage, QPainter, QPainterPath, QPen,
                           QPixmap)
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox,
                               QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit,
                               QPushButton, QRadioButton, QSpinBox, QTabWidget, QTextBrowser, QVBoxLayout,
                               QWidget)

from .. import APP_NAME, APP_VERSION
from ..core import fonts, signing
from ..core.document import NOTE_ICONS, PdfError
from ..core.pdftools import IMAGE_TYPES, every_n_pages, parse_ranges
from ..core.signing import SignatureInfo, SigningError
from ..i18n import fmt_datetime, tr


def data_dir(name: str) -> Path:
    base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
    path = Path(base) / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def warn(parent, text: str, title: str = APP_NAME):
    QMessageBox.warning(parent, title, text)


class ColorButton(QPushButton):
    def __init__(self, color: QColor):
        super().__init__()
        self.setFixedWidth(44)
        self.setToolTip(tr("Choose color"))
        self.set_color(color)
        self.clicked.connect(self._pick)

    def set_color(self, color: QColor):
        self.color = QColor(color)
        self.setStyleSheet(f"QPushButton {{ background: {self.color.name()}; border: 1px solid #888;"
                           f" border-radius: 3px; min-height: 20px; }}")

    def _pick(self):
        c = QColorDialog.getColor(self.color, self, tr("Choose color"))
        if c.isValid():
            self.set_color(c)


def rgb(color: QColor) -> tuple[float, float, float]:
    return color.redF(), color.greenF(), color.blueF()


# ---- text ----------------------------------------------------------------

class NoteDialog(QDialog):
    """Note text; for a new note also its icon and color."""

    def __init__(self, parent, text: str = "", new: bool = False, color: QColor | None = None, icon: str = "Note"):
        super().__init__(parent)
        self.setWindowTitle(tr("Note"))
        self.text = QPlainTextEdit(text)
        self.text.setPlaceholderText(tr("Note text (leave empty to delete the note)") if text
                                     else tr("Note text"))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(self.text)
        self.icon = QComboBox()
        self.color = ColorButton(color or QColor(255, 217, 51))
        if new:
            labels = {"Note": tr("Note"), "Comment": tr("Comment"), "Help": tr("Help"), "Key": tr("Key"),
                      "Insert": tr("Insertion mark"), "Paragraph": tr("Paragraph"), "NewParagraph": tr("New paragraph")}
            for key in NOTE_ICONS:
                self.icon.addItem(labels[key], key)
            self.icon.setCurrentIndex(max(0, self.icon.findData(icon)))
            row = QHBoxLayout()
            row.addWidget(QLabel(tr("Icon:")))
            row.addWidget(self.icon)
            row.addWidget(QLabel(tr("Color:")))
            row.addWidget(self.color)
            row.addStretch()
            lay.addLayout(row)
        lay.addWidget(buttons)
        self.resize(380, 240)


def stamp_presets() -> list[str]:
    return [tr("APPROVED"), tr("REJECTED"), tr("DRAFT"), tr("CONFIDENTIAL"), tr("FINAL"), tr("RECEIVED"),
            tr("PAID"), tr("COPY"), tr("FOR COMMENT"), tr("VOID")]


class StampDialog(QDialog):
    def __init__(self, parent, text: str, color: QColor):
        super().__init__(parent)
        self.setWindowTitle(tr("Stamp"))
        self.text = QComboBox()
        self.text.setEditable(True)
        self.text.addItems(stamp_presets())
        self.text.setCurrentText(text or stamp_presets()[0])
        self.color = ColorButton(color)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        form = QFormLayout(self)
        form.addRow(tr("Text:"), self.text)
        form.addRow(tr("Color:"), self.color)
        form.addRow(buttons)
        self.resize(360, 120)

    def _accept(self):
        if not self.text.currentText().strip():
            warn(self, tr("Enter the stamp text."))
            return
        self.accept()


class FormFieldDialog(QDialog):
    def __init__(self, parent, suggest_name):
        super().__init__(parent)
        self.setWindowTitle(tr("New form field"))
        self._suggest = suggest_name
        self.kind = QComboBox()
        for key, label in (("text", tr("Text")), ("multiline", tr("Multi-line text")),
                           ("checkbox", tr("Checkbox")), ("combobox", tr("Drop-down list")),
                           ("listbox", tr("List box"))):
            self.kind.addItem(label, key)
        self.name = QLineEdit(suggest_name("text"))
        self._auto_name = self.name.text()
        self.choices = QPlainTextEdit()
        self.choices.setPlaceholderText(tr("One option per line"))
        self.choices_label = QLabel(tr("Options:"))
        self.kind.currentIndexChanged.connect(self._kind_changed)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form = QFormLayout(self)
        form.addRow(tr("Type:"), self.kind)
        form.addRow(tr("Name:"), self.name)
        form.addRow(self.choices_label, self.choices)
        form.addRow(buttons)
        self._kind_changed()
        self.resize(400, 280)

    def _kind_changed(self):
        kind = self.kind.currentData()
        if self.name.text() == self._auto_name:  # the user has not typed a name of their own
            self._auto_name = self._suggest(kind)
            self.name.setText(self._auto_name)
        has_choices = kind in ("combobox", "listbox")
        self.choices.setVisible(has_choices)
        self.choices_label.setVisible(has_choices)

    def option_list(self) -> list[str]:
        return self.choices.toPlainText().splitlines()


class PageScope(QComboBox):
    """All pages / the current page / the pages selected in the thumbnail list."""

    def __init__(self, page_count: int, current: int, selected: list[int]):
        super().__init__()
        self.addItem(tr("All pages ({count})", count=page_count), list(range(page_count)))
        self.addItem(tr("Current page ({number})", number=current + 1), [current])
        if len(selected) > 1:
            self.addItem(tr("Selected pages ({count})", count=len(selected)), list(selected))

    def pages(self) -> list[int]:
        return self.currentData()


def _buttons(dialog: QDialog, ok_text: str | None = None) -> QDialogButtonBox:
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    if ok_text:
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(ok_text)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    return buttons


class WatermarkDialog(QDialog):
    def __init__(self, parent, scope: PageScope):
        super().__init__(parent)
        self.setWindowTitle(tr("Watermark"))
        self.text = QLineEdit(tr("CONFIDENTIAL"))
        self.size = QSpinBox()
        self.size.setRange(8, 200)
        self.size.setValue(60)
        self.size.setSuffix(" pt")
        self.angle = QSpinBox()
        self.angle.setRange(-90, 90)
        self.angle.setValue(45)
        self.angle.setSuffix("°")
        self.opacity = QSpinBox()
        self.opacity.setRange(5, 100)
        self.opacity.setValue(30)
        self.opacity.setSuffix(" %")
        self.color = ColorButton(QColor(150, 150, 150))
        self.behind = QCheckBox(tr("Place behind the page content"))
        self.scope = scope
        hint = QLabel(tr("The text is shrunk if it does not fit on a page."))
        hint.setStyleSheet("color: palette(placeholder-text);")
        form = QFormLayout(self)
        form.addRow(tr("Text:"), self.text)
        form.addRow(tr("Size:"), self.size)
        form.addRow(tr("Angle:"), self.angle)
        form.addRow(tr("Opacity:"), self.opacity)
        form.addRow(tr("Color:"), self.color)
        form.addRow(tr("Pages:"), self.scope)
        form.addRow(self.behind)
        form.addRow(hint)
        form.addRow(_buttons(self, tr("Add")))
        self.resize(420, 300)


class HeaderFooterDialog(QDialog):
    def __init__(self, parent, scope: PageScope):
        super().__init__(parent)
        self.setWindowTitle(tr("Header and footer"))
        self.fields: dict[str, QLineEdit] = {}
        grid = QFormLayout()
        labels = {"header_left": tr("Header, left:"), "header_center": tr("Header, center:"),
                  "header_right": tr("Header, right:"), "footer_left": tr("Footer, left:"),
                  "footer_center": tr("Footer, center:"), "footer_right": tr("Footer, right:")}
        for slot, label in labels.items():
            self.fields[slot] = QLineEdit()
            grid.addRow(label, self.fields[slot])
        self.fields["footer_center"].setText(tr("Page {page} of {pages}"))
        self.size = QDoubleSpinBox()
        self.size.setRange(5, 36)
        self.size.setValue(9)
        self.size.setSuffix(" pt")
        self.margin = QSpinBox()
        self.margin.setRange(4, 144)
        self.margin.setValue(24)
        self.margin.setSuffix(" pt")
        self.family = QComboBox()
        for key, label in fonts.FAMILY_LABELS.items():
            self.family.addItem(label, key)
        self.color = ColorButton(QColor(0, 0, 0))
        self.scope = scope
        hint = QLabel(tr("{page} is replaced with the page number, {pages} with the page count and {date} "
                         "with today's date."))
        hint.setWordWrap(True)
        hint.setStyleSheet("color: palette(placeholder-text);")
        grid.addRow(tr("Font:"), self.family)
        grid.addRow(tr("Size:"), self.size)
        grid.addRow(tr("Margin:"), self.margin)
        grid.addRow(tr("Color:"), self.color)
        grid.addRow(tr("Pages:"), self.scope)
        grid.addRow(hint)
        grid.addRow(_buttons(self, tr("Add")))
        self.setLayout(grid)
        self.resize(480, 400)

    def texts(self) -> dict[str, str]:
        return {slot: ed.text() for slot, ed in self.fields.items()}


class CompressDialog(QDialog):
    def __init__(self, parent, has_signatures: bool):
        super().__init__(parent)
        self.setWindowTitle(tr("Reduce file size"))
        self.level = QComboBox()
        self.level.addItem(tr("High quality (images up to 200 dpi)"), "high")
        self.level.addItem(tr("Balanced (images up to 150 dpi)"), "medium")
        self.level.addItem(tr("Smallest file (images up to 96 dpi)"), "low")
        self.level.setCurrentIndex(1)
        text = tr("A compressed copy is saved as a new file; the open document is not changed. Images are "
                  "resampled and re-compressed, fonts are reduced to the characters used, and unused data "
                  "is removed.")
        if has_signatures:
            text += "\n\n" + tr("The digital signatures in this document will not be valid in the compressed "
                                "copy.")
        info = QLabel(text)
        info.setWordWrap(True)
        form = QFormLayout(self)
        form.addRow(tr("Quality:"), self.level)
        form.addRow(info)
        form.addRow(_buttons(self, tr("Save copy…")))
        self.resize(460, 200)


class ExportImagesDialog(QDialog):
    def __init__(self, parent, scope: PageScope):
        super().__init__(parent)
        self.setWindowTitle(tr("Export pages as images"))
        self.fmt = QComboBox()
        self.fmt.addItem("PNG", "png")
        self.fmt.addItem("JPEG", "jpg")
        self.dpi = QComboBox()
        for dpi in (72, 96, 150, 200, 300, 600):
            self.dpi.addItem(f"{dpi} dpi", dpi)
        self.dpi.setCurrentIndex(2)
        self.scope = scope
        form = QFormLayout(self)
        form.addRow(tr("Format:"), self.fmt)
        form.addRow(tr("Resolution:"), self.dpi)
        form.addRow(tr("Pages:"), self.scope)
        form.addRow(_buttons(self, tr("Export…")))
        self.resize(360, 160)


# ---- handwritten signature -------------------------------------------------

# ---- whole-file tools ----------------------------------------------------------

class FileList(QListWidget):
    """Files in a chosen order: drag to reorder, or drop files from Explorer."""

    def __init__(self, extensions: tuple[str, ...]):
        super().__init__()
        self.extensions = extensions
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)

    def add_file(self, path: str, label: str | None = None):
        item = QListWidgetItem(label or os.path.basename(path))
        item.setToolTip(path)
        item.setData(Qt.ItemDataRole.UserRole, path)
        self.addItem(item)

    def add_paths(self, paths: list[str]):
        for path in paths:
            if os.path.splitext(path)[1].lstrip(".").lower() in self.extensions:
                self.add_file(path)

    def paths(self) -> list[str]:
        return [self.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.count())]

    def _external(self, e) -> bool:
        return e.source() is not self and e.mimeData().hasUrls()

    def dragEnterEvent(self, e):
        if self._external(e):
            e.acceptProposedAction()
        else:
            super().dragEnterEvent(e)

    def dragMoveEvent(self, e):
        if self._external(e):
            e.acceptProposedAction()
        else:
            super().dragMoveEvent(e)

    def dropEvent(self, e):
        if self._external(e):
            self.add_paths([u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()])
            e.acceptProposedAction()
        else:
            super().dropEvent(e)


class FileListDialog(QDialog):
    """A list of files to combine, with buttons to add, remove and reorder them."""

    def __init__(self, parent, title: str, ok_text: str, file_filter: str, extensions: tuple[str, ...],
                 start_dir: str, minimum: int):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.file_filter, self.start_dir, self.minimum = file_filter, start_dir, minimum
        self.files = FileList(extensions)
        side = QVBoxLayout()
        for text, slot in ((tr("Add files…"), self._add), (tr("Remove"), self._remove),
                           (tr("Move up"), lambda: self._move(-1)), (tr("Move down"), lambda: self._move(1))):
            b = QPushButton(text)
            b.clicked.connect(slot)
            side.addWidget(b)
        side.addStretch()
        row = QHBoxLayout()
        row.addWidget(self.files, 1)
        row.addLayout(side)
        hint = QLabel(tr("Drag files to change their order, or drop files from Explorer here."))
        hint.setWordWrap(True)
        hint.setStyleSheet("color: palette(placeholder-text);")
        self.options = QFormLayout()
        lay = QVBoxLayout(self)
        lay.addLayout(row)
        lay.addWidget(hint)
        lay.addLayout(self.options)
        lay.addWidget(_buttons(self, ok_text))
        self.resize(560, 400)

    def _add(self):
        paths, _ = QFileDialog.getOpenFileNames(self, tr("Add files"), self.start_dir, self.file_filter)
        if paths:
            self.start_dir = os.path.dirname(paths[0])
            self.files.add_paths(paths)

    def _remove(self):
        for item in self.files.selectedItems():
            self.files.takeItem(self.files.row(item))

    def _move(self, step: int):
        row = self.files.currentRow()
        if row < 0 or not 0 <= row + step < self.files.count():
            return
        item = self.files.takeItem(row)
        self.files.insertItem(row + step, item)
        self.files.setCurrentRow(row + step)

    def accept(self):
        if self.files.count() < self.minimum:
            warn(self, tr("Choose at least two PDFs to merge.") if self.minimum > 1 else
                 tr("Choose at least one image."))
            return
        super().accept()


OPEN_DOCUMENT = ""  # list entry standing for the document open in the window


class MergeDialog(FileListDialog):
    def __init__(self, parent, start_dir: str, open_name: str | None):
        super().__init__(parent, tr("Merge PDFs"), tr("Merge…"), tr("PDF documents (*.pdf)"), ("pdf",),
                         start_dir, 2)
        if open_name:
            self.files.add_file(OPEN_DOCUMENT, tr("{name} (open document)", name=open_name))
        self.bookmarks = QCheckBox(tr("Add a bookmark for each file"))
        self.bookmarks.setChecked(True)
        self.options.addRow(self.bookmarks)


IMAGE_EXTENSIONS = ("png", "jpg", "jpeg", "bmp", "gif", "tif", "tiff", "webp")


class ImagesToPdfDialog(FileListDialog):
    def __init__(self, parent, start_dir: str):
        patterns = " ".join(f"*.{e}" for e in IMAGE_EXTENSIONS)
        super().__init__(parent, tr("Create PDF from images"), tr("Create PDF…"),
                         tr("Images ({patterns})", patterns=patterns), IMAGE_EXTENSIONS, start_dir, 1)
        self.page_size = QComboBox()
        self.page_size.addItem(tr("Same as the image"), "image")
        self.page_size.addItem("A4", "a4")
        self.page_size.addItem("Letter", "letter")
        self.orientation = QComboBox()
        self.orientation.addItem(tr("Automatic (follows the image)"), "auto")
        self.orientation.addItem(tr("Portrait"), "portrait")
        self.orientation.addItem(tr("Landscape"), "landscape")
        self.margin = QComboBox()
        for text, points in ((tr("None"), 0), (tr("Small"), 20), (tr("Large"), 40)):
            self.margin.addItem(text, points)
        self.page_size.currentIndexChanged.connect(
            lambda: self.orientation.setEnabled(self.page_size.currentData() != "image"))
        self.orientation.setEnabled(False)
        self.options.addRow(tr("Page size:"), self.page_size)
        self.options.addRow(tr("Orientation:"), self.orientation)
        self.options.addRow(tr("Margin:"), self.margin)


def image_file(path: str) -> tuple[str, bytes]:
    """(name, bytes) of an image for `images_to_pdf`; types MuPDF cannot read are converted to PNG."""
    if os.path.splitext(path)[1].lstrip(".").lower() in IMAGE_TYPES:
        with open(path, "rb") as f:
            return path, f.read()
    img = QImage(path)
    if img.isNull():
        raise PdfError(tr("Could not read the image {name}.", name=os.path.basename(path)))
    return os.path.splitext(path)[0] + ".png", png_bytes(img)


class SplitDialog(QDialog):
    def __init__(self, parent, page_count: int):
        super().__init__(parent)
        self.setWindowTitle(tr("Split into separate PDFs"))
        self.page_count = page_count
        self.each = QRadioButton(tr("Every page into its own file"))
        self.every = QRadioButton(tr("A new file every"))
        self.size = QSpinBox()
        self.size.setRange(1, max(1, page_count))
        self.size.setValue(min(2, page_count))
        self.size.setSuffix(tr(" pages"))
        self.custom = QRadioButton(tr("Page ranges:"))
        self.ranges = QLineEdit()
        self.ranges.setPlaceholderText(tr("e.g. 1-3, 5, 8-"))
        self.each.setChecked(True)
        self.size.valueChanged.connect(lambda: self.every.setChecked(True))
        self.ranges.textEdited.connect(lambda: self.custom.setChecked(True))
        every_row = QHBoxLayout()
        every_row.addWidget(self.every)
        every_row.addWidget(self.size)
        every_row.addStretch()
        custom_row = QHBoxLayout()
        custom_row.addWidget(self.custom)
        custom_row.addWidget(self.ranges, 1)
        hint = QLabel(tr("Each range becomes a separate file; “8-” runs to the last page. The open document "
                         "is not changed."))
        hint.setWordWrap(True)
        hint.setStyleSheet("color: palette(placeholder-text);")
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(tr("The document has {count} page(s).", count=page_count)))
        lay.addWidget(self.each)
        lay.addLayout(every_row)
        lay.addLayout(custom_row)
        lay.addWidget(hint)
        lay.addWidget(_buttons(self, tr("Split…")))
        self.resize(440, 220)

    def groups(self) -> list[list[int]]:
        if self.custom.isChecked():
            return parse_ranges(self.ranges.text(), self.page_count)
        return every_n_pages(self.page_count, 1 if self.each.isChecked() else self.size.value())

    def accept(self):
        try:
            self.groups()
        except PdfError as e:
            warn(self, str(e))
            self.ranges.setFocus()
            return
        super().accept()


class ProtectDialog(QDialog):
    def __init__(self, parent, has_signatures: bool):
        super().__init__(parent)
        self.setWindowTitle(tr("Protect with password"))
        self.open_password = QLineEdit()
        self.repeat = QLineEdit()
        self.owner_password = QLineEdit()
        for edit in (self.open_password, self.repeat, self.owner_password):
            edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.owner_password.setPlaceholderText(tr("Optional"))
        self.allow = {
            "print": QCheckBox(tr("Printing")),
            "copy": QCheckBox(tr("Copying text and images")),
            "modify": QCheckBox(tr("Editing and organizing pages")),
            "annotate": QCheckBox(tr("Comments and filling in forms")),
        }
        allow_box = QVBoxLayout()
        for box in self.allow.values():
            box.setChecked(True)
            allow_box.addWidget(box)
        text = tr("A protected copy is saved as a new file; the open document is not changed. Keep the "
                  "password in a safe place: it cannot be recovered.\n\nWithout a permissions password, "
                  "restrictions cannot be lifted later, not even by you.")
        if has_signatures:
            text += "\n\n" + tr("The digital signatures in this document will not be valid in the protected "
                                "copy.")
        info = QLabel(text)
        info.setWordWrap(True)
        form = QFormLayout(self)
        form.addRow(tr("Password to open:"), self.open_password)
        form.addRow(tr("Repeat password:"), self.repeat)
        form.addRow(tr("Allow:"), allow_box)
        form.addRow(tr("Permissions password:"), self.owner_password)
        form.addRow(info)
        form.addRow(_buttons(self, tr("Save copy…")))
        self.resize(480, 360)

    def allowed(self) -> set[str]:
        return {key for key, box in self.allow.items() if box.isChecked()}

    def accept(self):
        if self.open_password.text() != self.repeat.text():
            warn(self, tr("The passwords do not match."))
            self.repeat.setFocus()
            return
        if not self.open_password.text() and len(self.allowed()) == len(self.allow):
            warn(self, tr("Set a password to open the file, or turn off at least one permission."))
            self.open_password.setFocus()
            return
        super().accept()


def crop_to_content(img: QImage, pad: int = 6) -> QImage:
    """Trim fully transparent borders."""
    img = img.convertToFormat(QImage.Format.Format_ARGB32)
    w, h = img.width(), img.height()
    alpha = bytes(img.constBits())[3::4]
    top = bottom = None
    left, right = w, 0
    for y in range(h):
        row = alpha[y * w:(y + 1) * w]
        stripped = row.lstrip(b"\x00")
        if not stripped:
            continue
        top = y if top is None else top
        bottom = y
        left = min(left, w - len(stripped))
        right = max(right, len(row.rstrip(b"\x00")))
    if top is None:
        return QImage()
    rect = QRect(left, top, right - left, bottom - top + 1).adjusted(-pad, -pad, pad, pad)
    return img.copy(rect.intersected(img.rect()))


def remove_background(img: QImage) -> QImage:
    """Make light (paper) pixels transparent; ink keeps its colour."""
    img = img.convertToFormat(QImage.Format.Format_ARGB32)
    gray = img.convertToFormat(QImage.Format.Format_Grayscale8)
    w, h = img.width(), img.height()
    gray_bytes = bytes(gray.constBits())
    stride = gray.bytesPerLine()
    if stride != w:
        gray_bytes = b"".join(gray_bytes[y * stride:y * stride + w] for y in range(h))
    table = bytes(0 if v >= 225 else 255 if v <= 140 else round((225 - v) * 255 / 85) for v in range(256))
    data = bytearray(img.constBits())
    data[3::4] = gray_bytes.translate(table)
    out = QImage(bytes(data), w, h, QImage.Format.Format_ARGB32)
    return out.copy()


def png_bytes(img: QImage) -> bytes:
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(ba)


class SignaturePad(QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumSize(520, 200)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.paths: list[QPainterPath] = []
        self.color = QColor(15, 30, 110)

    def clear(self):
        self.paths.clear()
        self.update()

    def mousePressEvent(self, e):
        self.paths.append(QPainterPath(e.position()))
        self.update()

    def mouseMoveEvent(self, e):
        if self.paths and e.buttons() & Qt.MouseButton.LeftButton:
            self.paths[-1].lineTo(e.position())
            self.update()

    def _pen(self, scale=1.0):
        pen = QPen(self.color, 2.6 * scale)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        return pen

    def paintEvent(self, _e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("white"))
        p.setPen(QPen(QColor(200, 200, 200), 1, Qt.PenStyle.DashLine))
        base = self.height() * 0.75
        p.drawLine(QPointF(20, base), QPointF(self.width() - 20, base))
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(self._pen())
        for path in self.paths:
            if path.elementCount() == 1:
                p.drawPoint(path.currentPosition())
            p.drawPath(path)

    def image(self) -> QImage:
        scale = 3.0
        img = QImage(round(self.width() * scale), round(self.height() * scale), QImage.Format.Format_ARGB32)
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.scale(scale, scale)
        p.setPen(self._pen())
        for path in self.paths:
            if path.elementCount() == 1:
                p.drawPoint(path.currentPosition())
            p.drawPath(path)
        p.end()
        return crop_to_content(img)


_SCRIPT_FONTS = ("Segoe Script", "Lucida Handwriting", "Ink Free", "Brush Script MT", "Freestyle Script",
                 "Edwardian Script ITC", "Mistral", "Segoe Print")


class CreateSignatureDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle(tr("New handwritten signature"))
        self.result_image = QImage()
        self.tabs = QTabWidget()

        # draw
        self.pad = SignaturePad()
        clear = QPushButton(tr("Clear"))
        clear.clicked.connect(self.pad.clear)
        draw = QWidget()
        dl = QVBoxLayout(draw)
        dl.addWidget(QLabel(tr("Sign with your mouse, pen or touch screen:")))
        dl.addWidget(self.pad, 1)
        dl.addWidget(clear, 0, Qt.AlignmentFlag.AlignRight)
        self.tabs.addTab(draw, tr("Draw"))

        # type
        self.name = QLineEdit()
        self.name.setPlaceholderText(tr("Your full name"))
        self.font = QComboBox()
        families = set(QFontDatabase.families())
        for f in _SCRIPT_FONTS:
            if f in families:
                self.font.addItem(f)
        if not self.font.count():
            self.font.addItem(QFont().defaultFamily())
        self.preview = QLabel()
        self.preview.setMinimumHeight(120)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setStyleSheet("background: white; border: 1px solid #ccc;")
        self.name.textChanged.connect(self._update_preview)
        self.font.currentTextChanged.connect(self._update_preview)
        typed = QWidget()
        tl = QFormLayout(typed)
        tl.addRow(tr("Full name:"), self.name)
        tl.addRow(tr("Font:"), self.font)
        tl.addRow(self.preview)
        self.tabs.addTab(typed, tr("Type"))

        # image
        self.image_label = QLabel(tr("Choose a scanned signature image (PNG/JPG)."))
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setMinimumHeight(140)
        self.image_label.setStyleSheet("background: white; border: 1px solid #ccc;")
        self.remove_bg = QCheckBox(tr("Make the paper background transparent"))
        self.remove_bg.setChecked(True)
        self.remove_bg.toggled.connect(self._update_image_preview)
        pick = QPushButton(tr("Choose image…"))
        pick.clicked.connect(self._pick_image)
        self._source_image = QImage()
        img_tab = QWidget()
        il = QVBoxLayout(img_tab)
        il.addWidget(self.image_label, 1)
        row = QHBoxLayout()
        row.addWidget(pick)
        row.addWidget(self.remove_bg)
        row.addStretch()
        il.addLayout(row)
        self.tabs.addTab(img_tab, tr("Image"))

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(self.tabs)
        lay.addWidget(buttons)
        self.resize(600, 360)

    def _typed_image(self) -> QImage:
        text = self.name.text().strip()
        if not text:
            return QImage()
        font = QFont(self.font.currentText(), 72)
        img = QImage(1600, 300, QImage.Format.Format_ARGB32)
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        p.setFont(font)
        p.setPen(QColor(15, 30, 110))
        p.drawText(img.rect(), Qt.AlignmentFlag.AlignCenter, text)
        p.end()
        return crop_to_content(img)

    def _update_preview(self):
        img = self._typed_image()
        self.preview.setPixmap(QPixmap.fromImage(img).scaled(
            self.preview.size() - QSize(10, 10), Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation) if not img.isNull() else QPixmap())

    def _pick_image(self):
        path, _ = QFileDialog.getOpenFileName(self, tr("Signature image"), "",
                                              tr("Images (*.png *.jpg *.jpeg *.bmp)"))
        if not path:
            return
        img = QImage(path)
        if img.isNull():
            warn(self, tr("The image could not be read."))
            return
        if img.width() > 1600:
            img = img.scaledToWidth(1600, Qt.TransformationMode.SmoothTransformation)
        self._source_image = img
        self._update_image_preview()

    def _processed_image(self) -> QImage:
        if self._source_image.isNull():
            return QImage()
        img = self._source_image
        if self.remove_bg.isChecked():
            img = crop_to_content(remove_background(img))
        return img

    def _update_image_preview(self):
        img = self._processed_image()
        if not img.isNull():
            self.image_label.setPixmap(QPixmap.fromImage(img).scaled(
                self.image_label.size() - QSize(10, 10), Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))

    def _accept(self):
        img = [self.pad.image, self._typed_image, self._processed_image][self.tabs.currentIndex()]()
        if img.isNull():
            warn(self, tr("Create a signature first."))
            return
        self.result_image = img
        self.accept()


class SignatureLibraryDialog(QDialog):
    """Pick (or create / delete) a saved handwritten signature."""

    def __init__(self, parent, selected: str | None):
        super().__init__(parent)
        self.setWindowTitle(tr("My signatures"))
        self.dir = data_dir("signatures")
        self.selected_path: str | None = None
        self.list = QListWidget()
        self.list.setViewMode(QListWidget.ViewMode.IconMode)
        self.list.setIconSize(QSize(220, 90))
        self.list.setGridSize(QSize(240, 110))
        self.list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.list.setMovement(QListWidget.Movement.Static)
        self.list.itemDoubleClicked.connect(lambda _i: self._accept())
        new = QPushButton(tr("New signature…"))
        new.clicked.connect(self._new)
        delete = QPushButton(tr("Delete"))
        delete.clicked.connect(self._delete)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr("Select"))
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        row = QHBoxLayout()
        row.addWidget(new)
        row.addWidget(delete)
        row.addStretch()
        row.addWidget(buttons)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(tr("Signatures are stored only on this computer.")))
        lay.addWidget(self.list)
        lay.addLayout(row)
        self.resize(560, 380)
        self._reload(selected)
        if not self.list.count():
            self._new()

    def _reload(self, select: str | None = None):
        self.list.clear()
        for path in sorted(self.dir.glob("*.png"), key=os.path.getmtime, reverse=True):
            pix = QPixmap(str(path))
            canvas = QPixmap(220, 90)
            canvas.fill(QColor("white"))
            p = QPainter(canvas)
            scaled = pix.scaled(210, 80, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            p.drawPixmap((220 - scaled.width()) // 2, (90 - scaled.height()) // 2, scaled)
            p.end()
            item = QListWidgetItem(QIcon(canvas), "")
            item.setData(Qt.ItemDataRole.UserRole, str(path))
            self.list.addItem(item)
            if select and Path(select) == path:
                self.list.setCurrentItem(item)
        if self.list.currentRow() < 0 and self.list.count():
            self.list.setCurrentRow(0)

    def _new(self):
        dlg = CreateSignatureDialog(self)
        if dlg.exec():
            path = self.dir / f"{uuid.uuid4().hex}.png"
            dlg.result_image.save(str(path), "PNG")
            self._reload(str(path))

    def _delete(self):
        item = self.list.currentItem()
        if item and QMessageBox.question(self, tr("Delete signature"), tr("Delete the selected signature?")) == QMessageBox.StandardButton.Yes:
            os.remove(item.data(Qt.ItemDataRole.UserRole))
            self._reload()

    def _accept(self):
        item = self.list.currentItem()
        if not item:
            warn(self, tr("Select a signature or create a new one."))
            return
        self.selected_path = item.data(Qt.ItemDataRole.UserRole)
        self.accept()


# ---- digital signature -----------------------------------------------------

class NewCertificateDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle(tr("New digital ID"))
        self.path: str | None = None
        self.password_value = ""
        self.name = QLineEdit()
        self.email = QLineEdit()
        self.org = QLineEdit()
        self.pw1 = QLineEdit()
        self.pw1.setEchoMode(QLineEdit.EchoMode.Password)
        self.pw2 = QLineEdit()
        self.pw2.setEchoMode(QLineEdit.EchoMode.Password)
        self.years = QSpinBox()
        self.years.setRange(1, 20)
        self.years.setValue(5)
        self.years.setSuffix(tr(" year(s)"))
        info = QLabel(tr(
            "A self-signed certificate will be created. It proves the document has not changed since it was "
            "signed, but the other party will only see your identity as verified if they trust your "
            "certificate. For legally recognised signatures, use a .pfx/.p12 file from an authorised provider."))
        info.setWordWrap(True)
        info.setStyleSheet("color: palette(placeholder-text);")
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr("Create and save…"))
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        form = QFormLayout(self)
        form.addRow(tr("Full name*:"), self.name)
        form.addRow(tr("Email:"), self.email)
        form.addRow(tr("Organization:"), self.org)
        form.addRow(tr("Password*:"), self.pw1)
        form.addRow(tr("Repeat password*:"), self.pw2)
        form.addRow(tr("Validity:"), self.years)
        form.addRow(info)
        form.addRow(buttons)
        self.resize(480, 300)

    def _accept(self):
        if not self.name.text().strip():
            warn(self, tr("Full name is required."))
            return
        if self.pw1.text() != self.pw2.text():
            warn(self, tr("Passwords do not match."))
            return
        if len(self.pw1.text()) < 4:
            warn(self, tr("Password must be at least 4 characters."))
            return
        default = str(Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation))
                      / f"{self.name.text().strip()}.p12")
        path, _ = QFileDialog.getSaveFileName(self, tr("Save digital ID"), default,
                                              tr("Digital ID (*.p12)"))
        if not path:
            return
        try:
            signing.create_certificate(path, self.name.text(), self.pw1.text(), self.email.text(),
                                       self.org.text(), self.years.value())
        except (SigningError, OSError) as e:
            warn(self, str(e))
            return
        self.path = path
        self.password_value = self.pw1.text()
        self.accept()


@dataclass
class SignRequest:
    cert: signing.Certificate
    reason: str
    location: str
    visible: bool
    with_image: bool


class SignDialog(QDialog):
    def __init__(self, parent, cert_path: str, has_visual_signature: bool):
        super().__init__(parent)
        self.setWindowTitle(tr("Sign digitally"))
        self.request: SignRequest | None = None
        self.cert_path = QLineEdit(cert_path)
        self.cert_path.setPlaceholderText(tr(".p12 / .pfx file"))
        browse = QPushButton(tr("Browse…"))
        browse.clicked.connect(self._browse)
        create = QPushButton(tr("Create new…"))
        create.clicked.connect(self._create)
        cert_row = QHBoxLayout()
        cert_row.addWidget(self.cert_path, 1)
        cert_row.addWidget(browse)
        cert_row.addWidget(create)
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.reason = QLineEdit()
        self.reason.setPlaceholderText(tr("e.g. I approve the contract"))
        self.location = QLineEdit()
        self.visible = QCheckBox(tr("Visible signature (draw an area on the page to place it)"))
        self.visible.setChecked(True)
        self.with_image = QCheckBox(tr("Also show my handwritten signature"))
        self.with_image.setEnabled(has_visual_signature)
        self.with_image.setChecked(has_visual_signature)
        if not has_visual_signature:
            self.with_image.setToolTip(
                tr("First create a handwritten signature with Signatures › My signatures…"))
        self.visible.toggled.connect(lambda on: self.with_image.setEnabled(on and has_visual_signature))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr("Sign"))
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        form = QFormLayout(self)
        form.addRow(tr("Digital ID:"), cert_row)
        form.addRow(tr("Password:"), self.password)
        form.addRow(tr("Reason:"), self.reason)
        form.addRow(tr("Location:"), self.location)
        form.addRow(self.visible)
        form.addRow(self.with_image)
        form.addRow(buttons)
        self.resize(560, 240)
        (self.password if cert_path else self.cert_path).setFocus()

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(self, tr("Digital ID"), self.cert_path.text(),
                                              tr("Digital ID (*.p12 *.pfx)"))
        if path:
            self.cert_path.setText(path)
            self.password.setFocus()

    def _create(self):
        dlg = NewCertificateDialog(self)
        if dlg.exec():
            self.cert_path.setText(dlg.path)
            self.password.setText(dlg.password_value)

    def _accept(self):
        try:
            cert = signing.load_certificate(self.cert_path.text().strip(), self.password.text())
        except SigningError as e:
            warn(self, str(e))
            return
        self.request = SignRequest(cert, self.reason.text(), self.location.text(),
                                   self.visible.isChecked(), self.with_image.isChecked() and self.visible.isChecked())
        self.accept()


_STATUS_STYLE = {
    "valid": ("#15803d", "✔"),
    "untrusted": ("#b45309", "●"),
    "modified": ("#b45309", "▲"),
    "invalid": ("#b91c1c", "✖"),
}


class VerifyDialog(QDialog):
    def __init__(self, parent, infos: list[SignatureInfo], note: str = ""):
        super().__init__(parent)
        self.setWindowTitle(tr("Signature verification"))
        view = QTextBrowser()
        parts = []
        if note:
            parts.append(f"<p><i>{html.escape(note)}</i></p>")
        if not infos:
            parts.append(f"<p>{html.escape(tr('This document has no digital signatures.'))}</p>")
        for info in infos:
            color, mark = _STATUS_STYLE[info.status]
            when = fmt_datetime(info.signed_at.astimezone()) if info.signed_at else tr("unknown")
            parts.append(
                f"<h3 style='color:{color}; margin-bottom:2px'>{mark} {html.escape(info.signer)}</h3>"
                f"<p style='margin-top:0'>{html.escape(tr('Signed at: {when}', when=when))}<br>"
                f"<b>{html.escape(info.summary)}</b></p>"
                f"<pre style='font-size:9pt'>{html.escape(info.details)}</pre><hr>")
        view.setHtml("".join(parts))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(view)
        lay.addWidget(buttons)
        self.resize(640, 460)


def about_html() -> str:
    return f"""
<h3>{APP_NAME} {APP_VERSION}</h3>
<p>{tr("An offline, free PDF editor and signer. No data ever leaves your computer.")}</p>
<p>{tr("Open-source components used:")}</p>
<ul>
<li>MuPDF / PyMuPDF — AGPL-3.0 (Artifex)</li>
<li>pyHanko — MIT</li>
<li>Qt / PySide6 — LGPL-3.0</li>
<li>cryptography — Apache-2.0 / BSD</li>
</ul>
"""
