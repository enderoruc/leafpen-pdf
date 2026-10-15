from __future__ import annotations

import math
import os
import sys
from pathlib import Path

import pymupdf
from PySide6.QtCore import QPointF, QProcess, QRectF, QSettings, QStandardPaths, Qt
from PySide6.QtGui import (QAction, QActionGroup, QColor, QIcon, QImage, QKeySequence, QPainter, QPalette, QPen,
                           QPixmap, QPolygonF)
from PySide6.QtPrintSupport import QPrintDialog, QPrinter
from PySide6.QtWidgets import (QApplication, QDockWidget, QFileDialog, QFrame, QHBoxLayout, QInputDialog,
                               QLabel, QLineEdit, QMainWindow, QMessageBox, QPushButton, QSpinBox, QStyle,
                               QToolBar, QToolButton, QVBoxLayout, QWidget)

from .. import APP_ID, APP_NAME, ORG_NAME
from ..core import signing
from ..core.document import PasswordRequired, PdfDocument, PdfError, write_file
from ..core.signing import SigningError
from ..i18n import LANGUAGES, tr
from . import dialogs
from .page_view import PageView, Tool
from .panels import FormPanel, ThumbnailList



def _pdf_filter() -> str:
    return tr("PDF documents (*.pdf)")


def _tool_hint(tool: Tool) -> str:
    return {
        Tool.BROWSE: tr("Browse: drag to scroll, Ctrl+wheel to zoom."),
        Tool.ADD_TEXT: tr("Add text: click where the text should start."),
        Tool.EDIT_TEXT: tr("Edit text: click the line you want to change."),
        Tool.HIGHLIGHT: tr("Highlight: drag across the text to highlight."),
        Tool.PEN: tr("Pen: draw freely."),
        Tool.IMAGE: tr("Image: draw or click where the image should go."),
        Tool.SIGNATURE: tr("Signature: draw or click where the signature should go."),
        Tool.ERASE: tr("Erase: click the highlight, drawing or note to remove."),
        Tool.DIGITAL_SIGN: tr("Digital signature: draw or click where the signature should appear (Esc: cancel)."),
    }[tool]


def _rotate_icon(widget: QWidget, clockwise: bool) -> QIcon:
    """A circular-arrow icon (no font glyph needed)."""
    pix = QPixmap(64, 64)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    color = widget.palette().color(QPalette.ColorRole.WindowText)
    p.setPen(QPen(color, 6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
    if not clockwise:
        p.translate(64, 0)
        p.scale(-1, 1)
    cx = cy = 32
    r = 20
    start, span = 60, -280  # clockwise from upper right, leaving a gap at the top
    p.drawArc(QRectF(cx - r, cy - r, 2 * r, 2 * r), start * 16, span * 16)
    end = math.radians(start + span)
    tip = QPointF(cx + r * math.cos(end), cy - r * math.sin(end))
    forward = QPointF(math.sin(end), math.cos(end))  # direction of clockwise travel
    radial = QPointF(math.cos(end), -math.sin(end))
    p.setBrush(color)
    p.setPen(Qt.PenStyle.NoPen)
    p.drawPolygon(QPolygonF([tip + forward * 14, tip + radial * 11, tip - radial * 11]))
    p.end()
    return QIcon(pix)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.doc: PdfDocument | None = None
        self.settings = QSettings(ORG_NAME, APP_ID)
        self._restarting = False
        self._pending_sign: dialogs.SignRequest | None = None
        self._lines_cache: dict[int, tuple[int, list]] = {}

        self.view = PageView()
        self.view.hover_provider = self._hover_rect
        self.view.rectDrawn.connect(self._on_rect)
        self.view.pointClicked.connect(self._on_click)
        self.view.strokeDrawn.connect(self._on_stroke)
        self.view.currentPageChanged.connect(self._on_page_changed)
        self.view.zoomChanged.connect(lambda _z: self._update_status())
        self.view.pen_color = QColor(self.settings.value("pen_color", "#1d4ed8"))
        self.view.pen_width = float(self.settings.value("pen_width", 2))

        self.sig_bar = QFrame()
        self.sig_bar.setObjectName("sigBar")
        self.sig_bar.setStyleSheet(
            "#sigBar { background: #fef3c7; border-bottom: 1px solid #f59e0b; }"
            "#sigBar QLabel { color: #78350f; }"
            "#sigBar QPushButton { color: #78350f; background: #fffbeb; border: 1px solid #d97706;"
            " border-radius: 4px; padding: 3px 12px; }"
            "#sigBar QPushButton:hover { background: #fde68a; }")
        bar_lay = QHBoxLayout(self.sig_bar)
        bar_lay.setContentsMargins(10, 4, 10, 4)
        self.sig_label = QLabel()
        verify_btn = QPushButton(tr("Verify signatures"))
        verify_btn.clicked.connect(self.verify_signatures)
        bar_lay.addWidget(self.sig_label, 1)
        bar_lay.addWidget(verify_btn)
        self.sig_bar.hide()

        self.empty = QLabel(tr("Press Ctrl+O to open a PDF or drag a file here."))
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setStyleSheet("color: gray; font-size: 15px;")

        central = QWidget()
        lay = QVBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.sig_bar)
        lay.addWidget(self.view, 1)
        lay.addWidget(self.empty, 1)
        self.setCentralWidget(central)

        self._build_pages_dock()
        self._build_forms_dock()
        self._build_actions()
        self._build_menus_and_toolbars()

        self.page_label = QLabel()
        self.zoom_label = QLabel()
        self.statusBar().addPermanentWidget(self.page_label)
        self.statusBar().addPermanentWidget(self.zoom_label)

        self.setAcceptDrops(True)
        self.resize(1200, 860)
        geometry = self.settings.value("geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)
        self._set_tool(Tool.BROWSE)
        self._refresh_ui()

    # ---- construction ------------------------------------------------------

    def _build_pages_dock(self):
        self.thumbs = ThumbnailList()
        self.thumbs.pageActivated.connect(self.view.go_to)
        buttons = QHBoxLayout()
        buttons.setSpacing(2)
        self._page_buttons = []
        SP = QStyle.StandardPixmap
        for icon, tip, slot in (
            (_rotate_icon(self, clockwise=False), tr("Rotate left (selected pages)"), lambda: self._rotate(-90)),
            (_rotate_icon(self, clockwise=True), tr("Rotate right (selected pages)"), lambda: self._rotate(90)),
            (self.style().standardIcon(SP.SP_ArrowUp), tr("Move up"), lambda: self._move(-1)),
            (self.style().standardIcon(SP.SP_ArrowDown), tr("Move down"), lambda: self._move(1)),
            (self.style().standardIcon(SP.SP_TrashIcon), tr("Delete selected pages"), self._delete_pages),
        ):
            b = QToolButton()
            b.setIcon(icon)
            b.setToolTip(tip)
            b.clicked.connect(slot)
            buttons.addWidget(b)
            self._page_buttons.append(b)
        host = QWidget()
        v = QVBoxLayout(host)
        v.setContentsMargins(2, 2, 2, 2)
        v.addLayout(buttons)
        v.addWidget(self.thumbs, 1)
        dock = QDockWidget(tr("Pages"), self)
        dock.setObjectName("pagesDock")
        dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable)
        dock.setWidget(host)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock)

    def _build_forms_dock(self):
        self.form_panel = FormPanel()
        self.form_panel.applyRequested.connect(self._apply_form)
        self.forms_dock = QDockWidget(tr("Form fields"), self)
        self.forms_dock.setObjectName("formsDock")
        self.forms_dock.setWidget(self.form_panel)
        self.forms_dock.setMinimumWidth(260)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.forms_dock)
        self.forms_dock.hide()

    def _action(self, text, slot, shortcut=None, icon=None, tip=None) -> QAction:
        a = QAction(text, self)
        if icon is not None:
            a.setIcon(self.style().standardIcon(icon))
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
        if tip:
            a.setToolTip(tip)
        a.triggered.connect(slot)
        return a

    def _build_actions(self):
        SP = QStyle.StandardPixmap
        self.act_open = self._action(tr("Open…"), self.open_dialog, QKeySequence.StandardKey.Open, SP.SP_DialogOpenButton)
        self.act_save = self._action(tr("Save"), self.save, QKeySequence.StandardKey.Save, SP.SP_DialogSaveButton)
        self.act_save_as = self._action(tr("Save as…"), self.save_as, QKeySequence.StandardKey.SaveAs)
        self.act_insert = self._action(tr("Insert pages from another PDF…"), self.insert_pdf)
        self.act_extract = self._action(tr("Save selected pages as a separate PDF…"), self.extract_pages)
        self.act_print = self._action(tr("Print…"), self.print_doc, QKeySequence.StandardKey.Print)
        self.act_quit = self._action(tr("Quit"), self.close, QKeySequence.StandardKey.Quit)
        self.act_undo = self._action(tr("Undo"), self.undo, QKeySequence.StandardKey.Undo, SP.SP_ArrowBack)
        self.act_redo = self._action(tr("Redo"), self.redo, "Ctrl+Y", SP.SP_ArrowForward)
        self.act_zoom_in = self._action(tr("Zoom in"), lambda: self.view.set_zoom(self.view.zoom * 1.2),
                                        QKeySequence.StandardKey.ZoomIn)
        self.act_zoom_out = self._action(tr("Zoom out"), lambda: self.view.set_zoom(self.view.zoom / 1.2),
                                         QKeySequence.StandardKey.ZoomOut)
        self.act_fit = self._action(tr("Fit width"), self.view.fit_width, "Ctrl+0")
        self.act_actual = self._action(tr("Actual size"), lambda: self.view.set_zoom(1.0), "Ctrl+1")
        self.act_signatures = self._action(tr("My signatures…"), self.manage_signatures)
        self.act_digital = self._action(tr("Sign digitally…"), self.digital_sign)
        self.act_new_cert = self._action(tr("Create new digital ID…"), self.new_certificate)
        self.act_verify = self._action(tr("Verify signatures"), self.verify_signatures)
        self.act_about = self._action(tr("About"), lambda: QMessageBox.about(self, APP_NAME, dialogs.about_html()))
        self.act_forms = self.forms_dock.toggleViewAction()
        self.act_forms.setText(tr("Form fields"))

        self.tool_group = QActionGroup(self)
        self.tool_actions: dict[Tool, QAction] = {}
        for tool, text, key in (
            (Tool.BROWSE, tr("Browse"), "Esc"),
            (Tool.ADD_TEXT, tr("Add text"), "T"),
            (Tool.EDIT_TEXT, tr("Edit text"), "E"),
            (Tool.HIGHLIGHT, tr("Highlight"), "H"),
            (Tool.PEN, tr("Pen"), "P"),
            (Tool.IMAGE, tr("Image"), "I"),
            (Tool.SIGNATURE, tr("Signature"), "S"),
            (Tool.ERASE, tr("Erase"), "X"),
        ):
            a = QAction(text, self)
            a.setCheckable(True)
            a.setShortcut(QKeySequence(key))
            a.setToolTip(f"{text} ({key})\n{_tool_hint(tool)}")
            a.triggered.connect(lambda _c=False, t=tool: self._set_tool(t))
            self.tool_group.addAction(a)
            self.tool_actions[tool] = a

        self.doc_actions = [self.act_save, self.act_save_as, self.act_insert, self.act_extract, self.act_print,
                            self.act_zoom_in, self.act_zoom_out, self.act_fit, self.act_actual,
                            self.act_digital, self.act_verify, *self.tool_actions.values()]

    def _build_menus_and_toolbars(self):
        mb = self.menuBar()
        m = mb.addMenu(tr("&File"))
        m.addActions([self.act_open, self.act_save, self.act_save_as])
        m.addSeparator()
        m.addActions([self.act_insert, self.act_extract])
        m.addSeparator()
        m.addAction(self.act_print)
        m.addSeparator()
        m.addAction(self.act_quit)
        m = mb.addMenu(tr("E&dit"))
        m.addActions([self.act_undo, self.act_redo])
        m.addSeparator()
        m.addActions(list(self.tool_actions.values()))
        m = mb.addMenu(tr("&View"))
        m.addActions([self.act_zoom_in, self.act_zoom_out, self.act_fit, self.act_actual])
        m.addSeparator()
        m.addAction(self.act_forms)
        m = mb.addMenu(tr("&Signatures"))
        m.addActions([self.act_signatures, self.tool_actions[Tool.SIGNATURE]])
        m.addSeparator()
        m.addActions([self.act_digital, self.act_new_cert, self.act_verify])
        help_menu = mb.addMenu(tr("&Help"))
        lang_menu = help_menu.addMenu(tr("&Language"))
        lang_group = QActionGroup(self)
        self._lang_actions: dict[str, QAction] = {}
        current = str(self.settings.value("language", "system"))
        for code, label in (("system", tr("System default")), *LANGUAGES.items()):
            a = QAction(label, self)
            a.setCheckable(True)
            a.setChecked(code == current or (code == "system" and current not in LANGUAGES))
            a.triggered.connect(lambda _c=False, c=code: self._set_language(c))
            lang_group.addAction(a)
            lang_menu.addAction(a)
            self._lang_actions[code] = a
        help_menu.addSeparator()
        help_menu.addAction(self.act_about)

        tb = QToolBar(tr("File"))
        tb.setObjectName("fileToolbar")
        tb.setMovable(False)
        tb.addActions([self.act_open, self.act_save])
        tb.addSeparator()
        tb.addActions([self.act_undo, self.act_redo])
        tb.addSeparator()
        tb.addActions([self.act_zoom_out, self.act_fit, self.act_zoom_in])
        self.addToolBar(tb)

        tools = QToolBar(tr("Tools"))
        tools.setObjectName("toolsToolbar")
        tools.setMovable(False)
        tools.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        tools.addActions(list(self.tool_actions.values()))
        tools.addSeparator()
        tools.addWidget(QLabel(tr(" Color ")))
        self.color_btn = dialogs.ColorButton(self.view.pen_color)
        self.color_btn.clicked.disconnect()
        self.color_btn.clicked.connect(self._pick_color)
        tools.addWidget(self.color_btn)
        tools.addWidget(QLabel(tr(" Width ")))
        self.width_spin = QSpinBox()
        self.width_spin.setRange(1, 12)
        self.width_spin.setValue(round(self.view.pen_width))
        self.width_spin.valueChanged.connect(self._set_pen_width)
        tools.addWidget(self.width_spin)
        tools.addSeparator()
        sign_btn = QToolButton()
        sign_btn.setDefaultAction(self.act_digital)
        sign_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        sign_btn.setStyleSheet("QToolButton { font-weight: bold; }")
        tools.addWidget(sign_btn)
        self.addToolBar(tools)

    # ---- state helpers -----------------------------------------------------

    def _refresh_ui(self):
        has_doc = self.doc is not None
        for a in self.doc_actions:
            a.setEnabled(has_doc)
        for b in self._page_buttons:
            b.setEnabled(has_doc)
        self.act_undo.setEnabled(has_doc and self.doc.can_undo())
        self.act_redo.setEnabled(has_doc and self.doc.can_redo())
        self.view.setVisible(has_doc)
        self.empty.setVisible(not has_doc)
        if has_doc:
            name = os.path.basename(self.doc.path) if self.doc.path else tr("Untitled")
            self.setWindowTitle(f"{name}{' •' if self.doc.dirty else ''} — {APP_NAME}")
        else:
            self.setWindowTitle(APP_NAME)
        self._update_status()

    def _update_status(self):
        if self.doc:
            self.page_label.setText(tr("Page {page} / {total}", page=self.view.current_page() + 1,
                                       total=self.doc.page_count))
            self.zoom_label.setText(tr("{percent}%", percent=round(self.view.zoom * 100)))
        else:
            self.page_label.clear()
            self.zoom_label.clear()

    def _on_page_changed(self, pno: int):
        self.thumbs.show_current(pno)
        self._update_status()

    def _changed(self, pages: list[int] | None = None):
        """Call after the document was modified."""
        self._lines_cache.clear()
        self.view.reload()
        self.thumbs.refresh(pages)
        if self.forms_dock.isVisible() or pages is None:
            self._load_form_fields()
        self._refresh_ui()

    def _run(self, fn, pages: list[int] | None = None) -> bool:
        """Run a document edit, reporting user-facing errors."""
        try:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                fn()
            finally:
                QApplication.restoreOverrideCursor()
        except PdfError as e:
            dialogs.warn(self, str(e))
            return False
        self._changed(pages)
        return True

    def _set_tool(self, tool: Tool):
        if tool != Tool.DIGITAL_SIGN:
            self._pending_sign = None
        self.view.set_tool(tool)
        if tool in self.tool_actions:
            self.tool_actions[tool].setChecked(True)
        else:
            checked = self.tool_group.checkedAction()
            if checked:
                checked.setChecked(False)
        self.statusBar().showMessage(_tool_hint(tool))

    def _pick_color(self):
        self.color_btn._pick()
        self.view.pen_color = self.color_btn.color
        self.settings.setValue("pen_color", self.color_btn.color.name())

    def _set_pen_width(self, value: int):
        self.view.pen_width = float(value)
        self.settings.setValue("pen_width", value)

    def _last_dir(self) -> str:
        return self.settings.value(
            "last_dir", QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation))

    # ---- files ---------------------------------------------------------------

    def _confirm_discard(self) -> bool:
        if not self.doc or not self.doc.dirty:
            return True
        r = QMessageBox.question(
            self, APP_NAME, tr("There are unsaved changes. Do you want to save them?"),
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel)
        if r == QMessageBox.StandardButton.Save:
            return self.save()
        return r == QMessageBox.StandardButton.Discard

    def open_dialog(self):
        if not self._confirm_discard():
            return
        path, _ = QFileDialog.getOpenFileName(self, tr("Open PDF"), self._last_dir(), _pdf_filter())
        if path:
            self.open_path(path)

    def open_path(self, path: str, data: bytes | None = None, password: str | None = None) -> bool:
        try:
            if data is None:
                with open(path, "rb") as f:
                    data = f.read()
        except OSError as e:
            dialogs.warn(self, tr("Could not read the file: {error}", error=e))
            return False
        while True:
            try:
                doc = PdfDocument(data, os.path.abspath(path), password)
                break
            except PasswordRequired as e:
                prompt = (tr("Wrong password. This PDF is password protected. Enter the password:") if e.wrong
                          else tr("This PDF is password protected. Enter the password:"))
                password, ok = QInputDialog.getText(self, tr("Password"), prompt,
                                                    QLineEdit.EchoMode.Password)
                if not ok:
                    return False
            except PdfError as e:
                dialogs.warn(self, str(e))
                return False
        if self.doc:
            self.doc.close()
        self.doc = doc
        self.settings.setValue("last_dir", os.path.dirname(doc.path))
        self._lines_cache.clear()
        self.view.set_document(doc)
        self.thumbs.set_document(doc)
        self._set_tool(Tool.BROWSE)
        self.view.fit_width()
        self._load_form_fields(show_if_any=True)
        self._update_signature_bar()
        self._refresh_ui()
        return True

    def _update_signature_bar(self):
        if self.doc and self.doc.has_signatures():
            self.sig_label.setText(tr("This document contains digital signatures. If you edit and save it, "
                                     "the existing signatures will appear invalid."))
            self.sig_bar.show()
        else:
            self.sig_bar.hide()

    def _confirm_breaking_signatures(self) -> bool:
        if not (self.doc.dirty and self.doc.has_signatures()):
            return True
        return QMessageBox.warning(
            self, APP_NAME,
            tr("This document is digitally signed. In the file saved with your changes the existing "
               "signatures will appear invalid.\n\nUsing 'Save as' is recommended to keep the original "
               "signed file. Continue?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes

    def save(self) -> bool:
        if not self.doc:
            return False
        if not self.doc.path:
            return self.save_as()
        if not self._confirm_breaking_signatures():
            return False
        return self._save_to(self.doc.path)

    def save_as(self) -> bool:
        if not self.doc:
            return False
        if not self._confirm_breaking_signatures():
            return False
        path, _ = QFileDialog.getSaveFileName(self, tr("Save as"), self.doc.path or self._last_dir(),
                                                _pdf_filter())
        return bool(path) and self._save_to(path)

    def _save_to(self, path: str) -> bool:
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        try:
            self.doc.save(path)
        except (PdfError, OSError) as e:
            dialogs.warn(self, tr("Could not save: {error}", error=e))
            return False
        self.settings.setValue("last_dir", os.path.dirname(path))
        self.statusBar().showMessage(tr("Saved: {path}", path=path), 4000)
        self._update_signature_bar()
        self._refresh_ui()
        return True

    def insert_pdf(self):
        path, _ = QFileDialog.getOpenFileName(self, tr("PDF to insert"), self._last_dir(), _pdf_filter())
        if not path:
            return
        at = self.view.current_page() + 1
        if self._run(lambda: self.doc.insert_pdf(path, at)):
            self.view.go_to(at)

    def extract_pages(self):
        pages = self.thumbs.selected_pages() or [self.view.current_page()]
        base = Path(self.doc.path).stem if self.doc.path else tr("pages")
        default = str(Path(self._last_dir()) / tr("{base}_page_{number}.pdf", base=base,
                                                  number=pages[0] + 1))
        path, _ = QFileDialog.getSaveFileName(self, tr("Save pages"), default, _pdf_filter())
        if not path:
            return
        try:
            self.doc.extract_pages(pages, path)
        except Exception as e:
            dialogs.warn(self, tr("Could not save: {error}", error=e))
            return
        self.statusBar().showMessage(tr("{count} page(s) saved: {path}", count=len(pages), path=path), 4000)

    def print_doc(self):
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        dlg = QPrintDialog(printer, self)
        dlg.setMinMax(1, self.doc.page_count)
        if dlg.exec() != QPrintDialog.DialogCode.Accepted:
            return
        first, last = printer.fromPage(), printer.toPage()
        if first == 0:
            first, last = 1, self.doc.page_count
        dpi = min(printer.resolution(), 300)
        painter = QPainter()
        if not painter.begin(printer):
            dialogs.warn(self, tr("The printer could not be started."))
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            for i, pno in enumerate(range(first - 1, last)):
                if i:
                    printer.newPage()
                pix = self.doc.render(pno, dpi / 72)
                img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGB888)
                area = printer.pageLayout().paintRectPixels(printer.resolution())
                area.moveTo(0, 0)
                size = img.size().scaled(area.size(), Qt.AspectRatioMode.KeepAspectRatio)
                target = area.adjusted((area.width() - size.width()) // 2, (area.height() - size.height()) // 2, 0, 0)
                target.setSize(size)
                painter.drawImage(target, img)
        finally:
            painter.end()
            QApplication.restoreOverrideCursor()

    # ---- edit ----------------------------------------------------------------

    def undo(self):
        if self.doc and self.doc.can_undo():
            self.doc.undo()
            self._changed()

    def redo(self):
        if self.doc and self.doc.can_redo():
            self.doc.redo()
            self._changed()

    def _target_pages(self) -> list[int]:
        return self.thumbs.selected_pages() or [self.view.current_page()]

    def _rotate(self, degrees: int):
        if self.doc:
            pages = self._target_pages()
            self._run(lambda: self.doc.rotate_pages(pages, degrees))

    def _move(self, step: int):
        if not self.doc:
            return
        src = self._target_pages()[0]
        dst = src + step
        if 0 <= dst < self.doc.page_count and self._run(lambda: self.doc.move_page(src, dst)):
            self.thumbs.clearSelection()
            self.thumbs.item(dst).setSelected(True)
            self.view.go_to(dst)

    def _delete_pages(self):
        if not self.doc:
            return
        pages = self._target_pages()
        question = (tr("Delete {count} pages?", count=len(pages)) if len(pages) > 1
                    else tr("Delete page {number}?", number=pages[0] + 1))
        if QMessageBox.question(self, APP_NAME, question) == QMessageBox.StandardButton.Yes:
            if self._run(lambda: self.doc.delete_pages(pages)):
                self.thumbs.clearSelection()

    def _lines(self, pno: int):
        cached = self._lines_cache.get(pno)
        if cached and cached[0] == self.doc.revision:
            return cached[1]
        lines = self.doc.text_lines(pno)
        self._lines_cache[pno] = (self.doc.revision, lines)
        return lines

    def _hover_rect(self, tool: Tool, pno: int, x: float, y: float):
        if tool == Tool.EDIT_TEXT:
            p = pymupdf.Point(x, y)
            return next((l.rect for l in self._lines(pno) if p in l.rect), None)
        if tool == Tool.ERASE:
            return self.doc.annot_rect_at(pno, x, y)
        return None

    def _on_click(self, pno: int, x: float, y: float):
        tool = self.view.tool
        if tool == Tool.ADD_TEXT:
            dlg = dialogs.TextDialog(self, self.view.pen_color, float(self.settings.value("text_size", 12)),
                                     self.settings.value("text_family", "sans"))
            if dlg.exec() and dlg.text.toPlainText().strip():
                self.settings.setValue("text_size", dlg.size.value())
                self.settings.setValue("text_family", dlg.family.currentData())
                self._run(lambda: self.doc.add_text(
                    pno, x, y, dlg.text.toPlainText(), dlg.size.value(), dialogs.rgb(dlg.color.color),
                    dlg.family.currentData(), dlg.bold.isChecked()), [pno])
        elif tool == Tool.EDIT_TEXT:
            p = pymupdf.Point(x, y)
            line = next((l for l in self._lines(pno) if p in l.rect), None)
            if line is None:
                self.statusBar().showMessage(tr("There is no editable text here. (Text on scanned pages is an "
                                                 "image and cannot be edited.)"), 5000)
                return
            dlg = dialogs.EditLineDialog(self, line.text, line.size)
            if dlg.exec() and (dlg.text.text() != line.text or dlg.size.value() != line.size):
                self._run(lambda: self.doc.replace_line(line, dlg.text.text(), dlg.size.value()), [pno])
        elif tool == Tool.ERASE:
            if self.doc.annot_rect_at(pno, x, y) is None:
                self.statusBar().showMessage(tr("There is no annotation to erase here. Use Undo (Ctrl+Z) for "
                                                 "added text and images."), 5000)
                return
            self._run(lambda: self.doc.delete_annot_at(pno, x, y), [pno])

    def _on_stroke(self, pno: int, points: list):
        self._run(lambda: self.doc.add_ink(pno, [points], dialogs.rgb(self.view.pen_color), self.view.pen_width), [pno])

    @staticmethod
    def _box_at(rect: pymupdf.Rect, width: float, aspect: float, page_size) -> pymupdf.Rect:
        """Use the drawn rect, or a default-size box centred on a click."""
        if rect.width >= 8 and rect.height >= 8:
            return rect
        w, h = width, width / aspect
        pw, ph = page_size
        x = min(max(rect.x0 - w / 2, 0), max(pw - w, 0))
        y = min(max(rect.y0 - h / 2, 0), max(ph - h, 0))
        return pymupdf.Rect(x, y, x + w, y + h)

    def _on_rect(self, pno: int, rect: pymupdf.Rect):
        tool = self.view.tool
        size = self.doc.page_size(pno)
        if tool == Tool.HIGHLIGHT:
            if rect.width >= 3 and rect.height >= 3:
                self._run(lambda: self.doc.add_highlight(pno, rect), [pno])
        elif tool == Tool.IMAGE:
            path, _ = QFileDialog.getOpenFileName(self, tr("Choose image"), self._last_dir(),
                                                  tr("Images (*.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff)"))
            if not path:
                return
            data = Path(path).read_bytes()
            img = QImage.fromData(data)
            aspect = img.width() / img.height() if not img.isNull() and img.height() else 1.0
            box = self._box_at(rect, 200, aspect, size)
            self._run(lambda: self.doc.add_image(pno, box, data), [pno])
        elif tool == Tool.SIGNATURE:
            path = self._visual_signature(ask=True)
            if not path:
                return
            img = QImage(path)
            box = self._box_at(rect, 150, img.width() / max(1, img.height()), size)
            self._run(lambda: self.doc.add_image(pno, box, Path(path).read_bytes()), [pno])
        elif tool == Tool.DIGITAL_SIGN and self._pending_sign:
            box = self._box_at(rect, 210, 3.0, size)
            request = self._pending_sign
            self._set_tool(Tool.BROWSE)
            self._finish_digital_sign(request, pno, box)

    def _apply_form(self, values: dict):
        self._run(lambda: self.doc.set_form_values(values))

    def _load_form_fields(self, show_if_any: bool = False):
        fields = self.doc.form_fields() if self.doc else []
        self.form_panel.set_fields(fields)
        if show_if_any:
            self.forms_dock.setVisible(bool(fields))

    # ---- signatures ----------------------------------------------------------

    def _visual_signature(self, ask: bool) -> str | None:
        path = self.settings.value("visual_signature", "")
        if path and os.path.exists(path):
            return path
        if not ask:
            return None
        return self.manage_signatures()

    def manage_signatures(self) -> str | None:
        dlg = dialogs.SignatureLibraryDialog(self, self.settings.value("visual_signature", ""))
        if dlg.exec() and dlg.selected_path:
            self.settings.setValue("visual_signature", dlg.selected_path)
            if self.doc:
                self._set_tool(Tool.SIGNATURE)
            return dlg.selected_path
        return None

    def new_certificate(self):
        dlg = dialogs.NewCertificateDialog(self)
        if dlg.exec():
            self.settings.setValue("cert_path", dlg.path)
            QMessageBox.information(self, APP_NAME, tr(
                "Digital ID created:\n{path}\n\nBack up this file and its password in a safe place.",
                path=dlg.path))

    def digital_sign(self):
        if not self.doc:
            return
        dlg = dialogs.SignDialog(self, self.settings.value("cert_path", ""), bool(self._visual_signature(ask=False)))
        if not dlg.exec():
            return
        self.settings.setValue("cert_path", dlg.cert_path.text().strip())
        if dlg.request.visible:
            self._set_tool(Tool.DIGITAL_SIGN)
            self._pending_sign = dlg.request
        else:
            self._finish_digital_sign(dlg.request, None, None)

    def _finish_digital_sign(self, request: dialogs.SignRequest, pno, rect):
        if self.doc.dirty and self.doc.has_signatures():
            if QMessageBox.warning(
                    self, APP_NAME, tr("The document has existing signatures and unsaved changes. If you "
                                       "continue, the existing signatures will appear invalid. Continue?"),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
                return
        base = Path(self.doc.path).stem if self.doc.path else tr("document")
        folder = os.path.dirname(self.doc.path) if self.doc.path else self._last_dir()
        path, _ = QFileDialog.getSaveFileName(self, tr("Save signed PDF"),
                                              str(Path(folder) / tr("{base}_signed.pdf", base=base)),
                                              _pdf_filter())
        if not path:
            return
        image = None
        if request.with_image:
            sig_path = self._visual_signature(ask=False)
            image = Path(sig_path).read_bytes() if sig_path else None
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            data = signing.sign_pdf(self.doc.signing_source(), request.cert, password=self.doc.password,
                                    page=pno, rect=rect, image=image,
                                    reason=request.reason, location=request.location)
            write_file(path, data)
        except (SigningError, PdfError, OSError) as e:
            dialogs.warn(self, str(e))
            return
        finally:
            QApplication.restoreOverrideCursor()
        password = self.doc.password
        self.open_path(path, data, password)
        self.statusBar().showMessage(tr("Signed and saved: {path}", path=path), 6000)
        self.verify_signatures()

    def verify_signatures(self):
        if not self.doc:
            return
        data = self.doc.disk_bytes
        note = ""
        if data is None:
            data = self.doc.signing_source()
        elif self.doc.dirty:
            note = tr("Verification was performed on the saved version on disk "
                      "(excluding unsaved changes).")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            infos = signing.verify_pdf(data, self.doc.password)
        except SigningError as e:
            dialogs.warn(self, str(e))
            return
        finally:
            QApplication.restoreOverrideCursor()
        dialogs.VerifyDialog(self, infos, note).exec()

    # ---- language ------------------------------------------------------------

    def _set_language(self, pref: str):
        """Store the choice and restart: every string is translated while the UI is built."""
        old = str(self.settings.value("language", "system"))
        if pref == old or (pref == "system" and old not in LANGUAGES):
            return
        if not self._confirm_discard():
            self._lang_actions[old if old in self._lang_actions else "system"].setChecked(True)
            return
        self.settings.setValue("language", pref)
        if getattr(sys, "frozen", False):
            args: list[str] = []
        elif sys.argv and sys.argv[0].lower().endswith(".pyw"):
            args = [sys.argv[0]]
        else:
            args = ["-m", "leafpen"]
        if self.doc and self.doc.path and os.path.exists(self.doc.path):
            args.append(self.doc.path)
        started = QProcess.startDetached(sys.executable, args)
        if started[0] if isinstance(started, tuple) else started:  # PySide6 also returns the pid
            self._restarting = True
            self.close()
        else:
            QMessageBox.information(self, APP_NAME, tr("Restart the application to apply the new language."))

    # ---- window events -------------------------------------------------------

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape and self.view.tool != Tool.BROWSE:
            self._set_tool(Tool.BROWSE)
            return
        super().keyPressEvent(e)

    def dragEnterEvent(self, e):
        if any(u.toLocalFile().lower().endswith(".pdf") for u in e.mimeData().urls()):
            e.acceptProposedAction()

    def dropEvent(self, e):
        for u in e.mimeData().urls():
            path = u.toLocalFile()
            if path.lower().endswith(".pdf"):
                if self._confirm_discard():
                    self.open_path(path)
                return

    def closeEvent(self, e):
        if not self._restarting and not self._confirm_discard():
            e.ignore()
            return
        self.settings.setValue("geometry", self.saveGeometry())
        e.accept()
