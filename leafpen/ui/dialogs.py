from __future__ import annotations

import html
import os
import uuid
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, QRect, QSize, QStandardPaths, Qt
from PySide6.QtGui import (QColor, QFont, QFontDatabase, QIcon, QImage, QPainter, QPainterPath, QPen,
                           QPixmap)
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox,
                               QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit,
                               QPushButton, QSpinBox, QTabWidget, QTextBrowser, QVBoxLayout, QWidget)

from .. import APP_NAME
from ..core import fonts, signing
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

class TextDialog(QDialog):
    def __init__(self, parent, color: QColor, size: float = 12, family: str = "sans"):
        super().__init__(parent)
        self.setWindowTitle(tr("Add text"))
        self.text = QPlainTextEdit()
        self.text.setPlaceholderText(tr("Text to add (can be multiple lines)"))
        self.family = QComboBox()
        for key, label in fonts.FAMILY_LABELS.items():
            self.family.addItem(label, key)
        self.family.setCurrentIndex(list(fonts.FAMILY_LABELS).index(family))
        self.size = QDoubleSpinBox()
        self.size.setRange(4, 96)
        self.size.setValue(size)
        self.size.setSuffix(" pt")
        self.bold = QCheckBox(tr("Bold"))
        self.color = ColorButton(color)

        row = QHBoxLayout()
        for w in (self.family, self.size, self.bold, self.color):
            row.addWidget(w)
        row.addStretch()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(self.text)
        lay.addLayout(row)
        lay.addWidget(buttons)
        self.resize(460, 240)


class EditLineDialog(QDialog):
    def __init__(self, parent, text: str, size: float):
        super().__init__(parent)
        self.setWindowTitle(tr("Edit text"))
        self.text = QLineEdit(text)
        self.text.selectAll()
        self.size = QDoubleSpinBox()
        self.size.setRange(4, 96)
        self.size.setValue(size)
        self.size.setSuffix(" pt")
        hint = QLabel(tr("The line is rewritten in the same position, with the same color and a similar "
                         "font. Leave it empty to delete the line."))
        hint.setWordWrap(True)
        hint.setStyleSheet("color: palette(placeholder-text);")
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form = QFormLayout(self)
        form.addRow(tr("Text:"), self.text)
        form.addRow(tr("Size:"), self.size)
        form.addRow(hint)
        form.addRow(buttons)
        self.resize(520, 150)


# ---- handwritten signature -------------------------------------------------

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
<h3>{APP_NAME}</h3>
<p>{tr("An offline, free PDF editor and signer. No data ever leaves your computer.")}</p>
<p>{tr("Open-source components used:")}</p>
<ul>
<li>MuPDF / PyMuPDF — AGPL-3.0 (Artifex)</li>
<li>pyHanko — MIT</li>
<li>Qt / PySide6 — LGPL-3.0</li>
<li>cryptography — Apache-2.0 / BSD</li>
</ul>
"""
