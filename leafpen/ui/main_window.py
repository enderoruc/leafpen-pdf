from __future__ import annotations

import html
import math
import os
import sys
from pathlib import Path

import pymupdf
from PySide6.QtCore import QPointF, QProcess, QRectF, QSettings, QStandardPaths, Qt
from PySide6.QtGui import (QAction, QActionGroup, QColor, QIcon, QImage, QKeySequence, QPainter, QPalette, QPen,
                           QPixmap, QPolygonF)
from PySide6.QtPrintSupport import QPrintDialog, QPrinter
from PySide6.QtWidgets import (QApplication, QColorDialog, QComboBox, QDockWidget, QFileDialog, QFrame, QHBoxLayout, QInputDialog,
                               QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox, QPushButton, QSpinBox, QStyle,
                               QToolBar, QToolButton, QVBoxLayout, QWidget)

from .. import APP_ID, APP_NAME, ORG_NAME
from ..core import pdftools, richtext, shell, signing
from ..core.document import PasswordRequired, PdfDocument, PdfError, SearchHit, write_file
from ..core.richtext import TextStyle
from ..core.signing import SigningError
from ..i18n import LANGUAGES, tr
from . import dialogs, palette
from .page_view import PageView, Tool
from .panels import BookmarkPanel, FindBar, FormPanel, ThumbnailList


def _pdf_filter() -> str:
    return tr("PDF documents (*.pdf)")


def _megabytes(n: int) -> str:
    return f"{n / 1_048_576:.2f} MB"


# Which properties-bar settings each drawing tool uses.
_ALL_PROPS = {"color", "fill", "width", "dashed", "opacity"}
_TOOL_PROPS = {
    Tool.PEN: {"color", "width", "opacity"},
    Tool.RECT: _ALL_PROPS,
    Tool.ELLIPSE: _ALL_PROPS,
    Tool.LINE: {"color", "width", "dashed", "opacity"},
    Tool.ARROW: {"color", "width", "dashed", "opacity"},
}


def _object_props(obj) -> set[str]:
    """Which properties-bar settings apply to a selected object."""
    if obj.kind == "text":
        return {"color"}
    if obj.kind != "annot":
        return set()
    if obj.subtype in ("Square", "Circle"):
        return _ALL_PROPS
    if obj.subtype in ("Line", "Ink", "Polygon", "PolyLine"):
        return {"color", "width", "dashed", "opacity"}
    return {"color", "opacity"}


def _object_label(obj) -> str:
    """What the select tool has picked, for the properties bar."""
    if obj.kind == "text":
        return tr("paragraph")
    if obj.kind == "image":
        return tr("image")
    if obj.kind == "widget":
        return tr("form field")
    return {"Square": tr("rectangle"), "Circle": tr("ellipse"), "Line": tr("line"), "Ink": tr("drawing"),
            "Stamp": tr("stamp"), "Text": tr("note"), "FreeText": tr("text box"),
            "Highlight": tr("highlight")}.get(obj.subtype, tr("annotation"))


def _tool_hint(tool: Tool) -> str:
    return {
        Tool.BROWSE: tr("Browse: drag to scroll, Ctrl+wheel to zoom."),
        Tool.ADD_TEXT: tr("Add text: click where the text should start."),
        Tool.EDIT_TEXT: tr("Edit text: click the line you want to change."),
        Tool.HIGHLIGHT: tr("Highlight: drag across the text to highlight."),
        Tool.PEN: tr("Pen: draw freely."),
        Tool.IMAGE: tr("Image: draw or click where the image should go."),
        Tool.SIGNATURE: tr("Signature: draw or click where the signature should go."),
        Tool.ERASE: tr("Erase: click an annotation, stamp, note or form field to remove it."),
        Tool.DIGITAL_SIGN: tr("Digital signature: draw or click where the signature should appear (Esc: cancel)."),
        Tool.EDIT_PARAGRAPH: tr("Edit paragraph: click the paragraph you want to change."),
        Tool.RECT: tr("Rectangle: drag to draw."),
        Tool.ELLIPSE: tr("Ellipse: drag to draw."),
        Tool.LINE: tr("Line: drag from start to end."),
        Tool.ARROW: tr("Arrow: drag from the tail to the tip."),
        Tool.NOTE: tr("Note: click to add a sticky note, or click a note to edit it."),
        Tool.STAMP: tr("Stamp: draw or click where the stamp should go."),
        Tool.REDACT: tr("Redact: drag over the content to remove. Apply the marks with Document › Apply "
                        "redactions."),
        Tool.CROP: tr("Crop: drag the area to keep (applies to the selected pages)."),
        Tool.FORM_FIELD: tr("Form field: draw or click where the field should go."),
        Tool.SELECT: tr("Select: click a shape, stamp, note, image, form field or paragraph to move, resize or "
                        "restyle it."),
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
        self._text_cache: dict[tuple[str, int], tuple[int, list]] = {}
        self._hits: list[SearchHit] = []
        self._hit_index: int | None = None

        self.view = PageView()
        self.view.hover_provider = self._hover_rect
        self.view.rectDrawn.connect(self._on_rect)
        self.view.pointClicked.connect(self._on_click)
        self.view.strokeDrawn.connect(self._on_stroke)
        self.view.lineDrawn.connect(self._on_line)
        self.view.select_provider = lambda pno, x, y: self.doc.object_at(pno, x, y)
        self.view.objectSelected.connect(self._on_selection)
        self.view.objectChanged.connect(self._on_object_changed)
        self.view.objectActivated.connect(self._on_object_activated)
        self.view.deleteSelection.connect(self._delete_selection)
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

        # Start screen: how to open a file, and the recently opened ones as links.
        self.empty = QLabel()
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setTextFormat(Qt.TextFormat.RichText)
        self.empty.setStyleSheet("font-size: 14px;")
        self.empty.linkActivated.connect(lambda href: self._open_recent(self._recent_files()[int(href)]))

        self.find_bar = FindBar()
        self.find_bar.searchRequested.connect(self._search)
        self.find_bar.nextRequested.connect(lambda: self._step_hit(1))
        self.find_bar.previousRequested.connect(lambda: self._step_hit(-1))
        self.find_bar.redactAllRequested.connect(self._redact_hits)
        self.find_bar.closed.connect(self._clear_search)
        self.find_bar.hide()

        central = QWidget()
        lay = QVBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.sig_bar)
        lay.addWidget(self.find_bar)
        lay.addWidget(self.view, 1)
        lay.addWidget(self.empty, 1)
        self.setCentralWidget(central)

        self._build_pages_dock()
        self._build_bookmarks_dock()
        self._build_forms_dock()
        self._build_actions()
        self._build_menus_and_toolbars()

        self.page_label = QLabel()
        self.statusBar().addPermanentWidget(self.page_label)
        self.statusBar().addPermanentWidget(self._build_zoom_controls())

        self.setAcceptDrops(True)
        self.resize(1200, 860)
        geometry = self.settings.value("geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)
        self._set_tool(Tool.BROWSE)
        self._refresh_ui()
        self._follow_moved_folder()

    # ---- construction ------------------------------------------------------

    def _build_pages_dock(self):
        self.thumbs = ThumbnailList()
        self.thumbs.pageActivated.connect(self.view.go_to)
        self.thumbs.pagesDropped.connect(self._move_pages)
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
        self.pages_dock = dock

    def _build_bookmarks_dock(self):
        self.bookmark_panel = BookmarkPanel()
        self.bookmark_panel.pageActivated.connect(self.view.go_to)
        self.bookmark_panel.addRequested.connect(self._add_bookmark)
        self.bookmark_panel.renameRequested.connect(self._rename_bookmark)
        self.bookmark_panel.deleteRequested.connect(self._delete_bookmark)
        self.bookmarks_dock = QDockWidget(tr("Bookmarks"), self)
        self.bookmarks_dock.setObjectName("bookmarksDock")
        self.bookmarks_dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable)
        self.bookmarks_dock.setWidget(self.bookmark_panel)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.bookmarks_dock)
        self.tabifyDockWidget(self.pages_dock, self.bookmarks_dock)
        self.pages_dock.raise_()

    def _build_forms_dock(self):
        self.form_panel = FormPanel()
        self.form_panel.applyRequested.connect(self._apply_form)
        self.form_panel.addFieldRequested.connect(lambda: self._set_tool(Tool.FORM_FIELD))
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
        self.act_bookmarks = self.bookmarks_dock.toggleViewAction()
        self.act_bookmarks.setText(tr("Bookmarks"))
        self.act_find = self._action(tr("Find…"), self.find, QKeySequence.StandardKey.Find)
        self.act_export_images = self._action(tr("Export pages as images…"), self.export_images)
        self.act_compress = self._action(tr("Reduce file size…"), self.compress)
        self.act_apply_redactions = self._action(tr("Apply redactions…"), self.apply_redactions)
        self.act_watermark = self._action(tr("Add watermark…"), self.add_watermark)
        self.act_header_footer = self._action(tr("Add header and footer…"), self.add_header_footer)
        self.act_reset_crop = self._action(tr("Remove crop (selected pages)"), self.reset_crop)
        self.act_palette = self._action(tr("Command palette…"), lambda: palette.run_palette(self), "Ctrl+K",
                                        tip=tr("Find any command by typing part of its name"))
        self.act_merge = self._action(tr("Merge PDFs…"), lambda: self.merge_pdfs())
        self.act_split = self._action(tr("Split into separate PDFs…"), self.split_pdf)
        self.act_images_to_pdf = self._action(tr("Create PDF from images…"), lambda: self.images_to_pdf())
        self.act_protect = self._action(tr("Protect with password…"), self.protect_pdf)
        self.act_unlock = self._action(tr("Remove password…"), self.unlock_pdf,
                                       tip=tr("Save a copy without the password and permission restrictions"))
        self.act_repair = self._action(tr("Repair a damaged PDF…"), self.repair_pdf)
        self.act_open_with = self._action(tr("Show in “Open with” for PDF files"), self._toggle_open_with)
        self.act_open_with.setCheckable(True)
        self.act_shortcuts = {
            "desktop": self._action(tr("Shortcut on the desktop"), lambda on: self._toggle_shortcut("desktop", on)),
            "start_menu": self._action(tr("Shortcut in the Start menu"),
                                       lambda on: self._toggle_shortcut("start_menu", on)),
        }
        for a in self.act_shortcuts.values():
            a.setCheckable(True)

        self.tool_group = QActionGroup(self)
        self.tool_actions: dict[Tool, QAction] = {}
        for tool, text, key in (
            (Tool.BROWSE, tr("Browse"), "Esc"),
            (Tool.SELECT, tr("Select"), "V"),
            (Tool.ADD_TEXT, tr("Add text"), "T"),
            (Tool.EDIT_TEXT, tr("Edit line"), "E"),
            (Tool.EDIT_PARAGRAPH, tr("Edit paragraph"), "Shift+E"),
            (Tool.HIGHLIGHT, tr("Highlight"), "H"),
            (Tool.PEN, tr("Pen"), "P"),
            (Tool.RECT, tr("Rectangle"), "R"),
            (Tool.ELLIPSE, tr("Ellipse"), "O"),
            (Tool.LINE, tr("Line"), "L"),
            (Tool.ARROW, tr("Arrow"), "A"),
            (Tool.NOTE, tr("Note"), "N"),
            (Tool.STAMP, tr("Stamp"), "M"),
            (Tool.IMAGE, tr("Image"), "I"),
            (Tool.SIGNATURE, tr("Signature"), "S"),
            (Tool.REDACT, tr("Redact"), "D"),
            (Tool.ERASE, tr("Erase"), "X"),
            (Tool.CROP, tr("Crop pages"), "C"),
            (Tool.FORM_FIELD, tr("Add form field"), "F"),
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
                            self.act_digital, self.act_verify, self.act_find, self.act_export_images,
                            self.act_compress, self.act_apply_redactions, self.act_watermark,
                            self.act_header_footer, self.act_reset_crop, self.act_split, self.act_protect,
                            self.act_unlock, *self.tool_actions.values()]

    def _tool_menu_button(self, text: str, tools: list[Tool]) -> QToolButton:
        """A toolbar button that shows the last tool chosen from its menu."""
        button = QToolButton()
        button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        menu = QMenu(text, button)
        for tool in tools:
            menu.addAction(self.tool_actions[tool])
            self.tool_actions[tool].triggered.connect(
                lambda _c=False, a=self.tool_actions[tool]: button.setDefaultAction(a))
        button.setMenu(menu)
        button.setDefaultAction(self.tool_actions[tools[0]])
        return button

    def _build_menus_and_toolbars(self):
        T = self.tool_actions
        mb = self.menuBar()
        m = mb.addMenu(tr("&File"))
        m.addAction(self.act_open)
        self.recent_menu = m.addMenu(tr("Open &recent"))
        self.recent_menu.aboutToShow.connect(self._fill_recent_menu)
        m.addActions([self.act_save, self.act_save_as])
        m.addSeparator()
        m.addActions([self.act_insert, self.act_extract])
        m.addSeparator()
        m.addActions([self.act_export_images, self.act_compress])
        m.addSeparator()
        m.addAction(self.act_print)
        m.addSeparator()
        m.addAction(self.act_quit)
        m = mb.addMenu(tr("E&dit"))
        m.addActions([self.act_undo, self.act_redo])
        m.addSeparator()
        m.addAction(self.act_find)
        m.addSeparator()
        m.addActions([T[t] for t in (Tool.BROWSE, Tool.ADD_TEXT, Tool.EDIT_TEXT, Tool.EDIT_PARAGRAPH,
                                     Tool.IMAGE, Tool.ERASE)])
        m = mb.addMenu(tr("&Comment"))
        m.addActions([T[t] for t in (Tool.HIGHLIGHT, Tool.PEN, Tool.RECT, Tool.ELLIPSE, Tool.LINE, Tool.ARROW,
                                     Tool.NOTE, Tool.STAMP)])
        m = mb.addMenu(tr("&Document"))
        m.addActions([T[Tool.CROP], self.act_reset_crop])
        m.addSeparator()
        m.addActions([self.act_watermark, self.act_header_footer])
        m.addSeparator()
        m.addActions([T[Tool.REDACT], self.act_apply_redactions])
        m.addSeparator()
        m.addAction(T[Tool.FORM_FIELD])
        m = mb.addMenu(tr("&Tools"))
        m.addActions([self.act_merge, self.act_split, self.act_images_to_pdf])
        m.addSeparator()
        m.addActions([self.act_protect, self.act_unlock])
        m.addSeparator()
        m.addAction(self.act_repair)
        m = mb.addMenu(tr("&View"))
        m.addAction(self.act_palette)
        m.addSeparator()
        m.addActions([self.act_zoom_in, self.act_zoom_out, self.act_fit, self.act_actual])
        m.addSeparator()
        m.addActions([self.act_bookmarks, self.act_forms])
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
        help_menu.addAction(self.act_open_with)
        help_menu.addActions(list(self.act_shortcuts.values()))
        help_menu.aboutToShow.connect(self._update_explorer_actions)
        help_menu.addSeparator()
        help_menu.addAction(self.act_about)

        # One row: file and history icons, then the tools. Zoom lives in the status bar, and the
        # properties bar below only appears for the tools that use it.
        tools = QToolBar(tr("Tools"))
        tools.setObjectName("toolsToolbar")
        tools.setMovable(False)
        tools.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        for a in (self.act_open, self.act_save, None, self.act_undo, self.act_redo, None):
            if a is None:
                tools.addSeparator()
            else:
                tools.addAction(a)
                tools.widgetForAction(a).setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        tools.addActions([T[Tool.BROWSE], T[Tool.SELECT], T[Tool.ADD_TEXT]])
        tools.addWidget(self._tool_menu_button(tr("Edit text"), [Tool.EDIT_TEXT, Tool.EDIT_PARAGRAPH]))
        tools.addActions([T[Tool.HIGHLIGHT], T[Tool.PEN]])
        tools.addWidget(self._tool_menu_button(tr("Shapes"), [Tool.RECT, Tool.ELLIPSE, Tool.LINE, Tool.ARROW]))
        tools.addActions([T[Tool.NOTE], T[Tool.STAMP]])
        tools.addWidget(self._tool_menu_button(tr("Insert"), [Tool.IMAGE, Tool.SIGNATURE]))
        tools.addActions([T[Tool.REDACT], T[Tool.ERASE]])
        tools.addSeparator()
        sign_btn = QToolButton()
        sign_btn.setDefaultAction(self.act_digital)
        sign_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        sign_btn.setStyleSheet("QToolButton { font-weight: bold; }")
        tools.addWidget(sign_btn)
        self.addToolBar(tools)
        self.addToolBarBreak()
        self.props_bar = self._build_properties_bar()
        self.addToolBar(self.props_bar)

    def _build_zoom_controls(self) -> QWidget:
        """− [zoom ▾] + in the status bar."""
        host = QWidget()
        lay = QHBoxLayout(host)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        out_btn = QToolButton()
        out_btn.setText("−")
        out_btn.setToolTip(tr("Zoom out") + f" ({self.act_zoom_out.shortcut().toString()})")
        out_btn.setAutoRaise(True)
        out_btn.clicked.connect(self.act_zoom_out.trigger)
        self.zoom_btn = QToolButton()
        self.zoom_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.zoom_btn.setAutoRaise(True)
        self.zoom_btn.setToolTip(tr("Zoom"))
        menu = QMenu(self.zoom_btn)
        menu.addAction(self.act_fit)
        menu.addAction(self.act_actual)
        menu.addSeparator()
        for percent in (50, 75, 100, 125, 150, 200, 300, 400):
            menu.addAction(tr("{percent}%", percent=percent), lambda p=percent: self.view.set_zoom(p / 100))
        self.zoom_btn.setMenu(menu)
        in_btn = QToolButton()
        in_btn.setText("+")
        in_btn.setToolTip(tr("Zoom in") + f" ({self.act_zoom_in.shortcut().toString()})")
        in_btn.setAutoRaise(True)
        in_btn.clicked.connect(self.act_zoom_in.trigger)
        for w in (out_btn, self.zoom_btn, in_btn):
            lay.addWidget(w)
        self._zoom_buttons = [out_btn, self.zoom_btn, in_btn]
        return host

    def _build_properties_bar(self) -> QToolBar:
        """Color, fill, line width/style and opacity: defaults for new items, or the selected item's style."""
        bar = QToolBar(tr("Properties"))
        bar.setObjectName("propertiesToolbar")
        bar.setMovable(False)
        self.props_label = QLabel()
        self.props_label.setStyleSheet("color: palette(placeholder-text); padding: 0 6px;")
        bar.addWidget(self.props_label)
        labels = {name: QLabel(text) for name, text in (
            ("color", tr(" Color ")), ("fill", tr(" Fill ")), ("width", tr(" Width ")), ("dashed", tr(" Line ")),
            ("opacity", tr(" Opacity ")))}
        bar.addWidget(labels["color"])
        self.color_btn = dialogs.ColorButton(self.view.pen_color)
        self.color_btn.clicked.disconnect()
        self.color_btn.clicked.connect(self._pick_color)
        bar.addWidget(self.color_btn)
        bar.addWidget(labels["fill"])
        self.fill_btn = QToolButton()
        self.fill_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.fill_btn.setToolTip(tr("Fill color of rectangles and ellipses"))
        menu = QMenu(self.fill_btn)
        menu.addAction(tr("No fill"), lambda: self._set_fill(None))
        menu.addAction(tr("Choose fill color…"), self._pick_fill)
        self.fill_btn.setMenu(menu)
        bar.addWidget(self.fill_btn)
        bar.addWidget(labels["width"])
        self.width_spin = QSpinBox()
        self.width_spin.setRange(1, 12)
        self.width_spin.setValue(round(self.view.pen_width))
        self.width_spin.valueChanged.connect(self._set_pen_width)
        bar.addWidget(self.width_spin)
        bar.addWidget(labels["dashed"])
        self.dash_combo = QComboBox()
        self.dash_combo.addItem(tr("Solid"), False)
        self.dash_combo.addItem(tr("Dashed"), True)
        self.dash_combo.activated.connect(lambda _i: self._set_dashed(self.dash_combo.currentData()))
        bar.addWidget(self.dash_combo)
        bar.addWidget(labels["opacity"])
        self.opacity_spin = QSpinBox()
        self.opacity_spin.setRange(10, 100)
        self.opacity_spin.setSingleStep(10)
        self.opacity_spin.setSuffix(" %")
        self.opacity_spin.valueChanged.connect(lambda v: self._set_opacity(v / 100))
        bar.addWidget(self.opacity_spin)
        self._prop_widgets = {
            "color": [labels["color"], self.color_btn], "fill": [labels["fill"], self.fill_btn],
            "width": [labels["width"], self.width_spin], "dashed": [labels["dashed"], self.dash_combo],
            "opacity": [labels["opacity"], self.opacity_spin]}
        self._show_defaults()
        return bar

    # ---- state helpers -----------------------------------------------------

    def _refresh_ui(self):
        has_doc = self.doc is not None
        for a in self.doc_actions:
            a.setEnabled(has_doc)
        for b in self._page_buttons:
            b.setEnabled(has_doc)
        self.act_undo.setEnabled(has_doc and self.doc.can_undo())
        self.act_redo.setEnabled(has_doc and self.doc.can_redo())
        self.act_unlock.setEnabled(has_doc and self.doc.is_encrypted)
        self.view.setVisible(has_doc)
        self.empty.setVisible(not has_doc)
        if not has_doc:
            self._update_empty()
        if has_doc:
            name = os.path.basename(self.doc.path) if self.doc.path else tr("Untitled")
            self.setWindowTitle(f"{name}{' •' if self.doc.dirty else ''} — {APP_NAME}")
        else:
            self.setWindowTitle(APP_NAME)
        self._update_status()

    def _update_status(self):
        for w in self._zoom_buttons:
            w.setVisible(self.doc is not None)
        if self.doc:
            self.page_label.setText(tr("Page {page} / {total}", page=self.view.current_page() + 1,
                                       total=self.doc.page_count))
            self.zoom_btn.setText(tr("{percent}%", percent=round(self.view.zoom * 100)) + " ")
        else:
            self.page_label.clear()

    def _on_page_changed(self, pno: int):
        self.thumbs.show_current(pno)
        self._update_status()

    def _changed(self, pages: list[int] | None = None):
        """Call after the document was modified."""
        self._text_cache.clear()
        self.view.reload()
        self.thumbs.refresh(pages)
        if self.forms_dock.isVisible() or pages is None:
            self._load_form_fields()
        self._load_bookmarks()
        if self.find_bar.isVisible():
            self._search(self.find_bar.edit.text(), keep_position=True)
        self._refresh_ui()

    def _run(self, fn, pages: list[int] | None = None) -> bool:
        """Run a document edit, reporting user-facing errors."""
        self.view.finish_inline(commit=True)  # an open text box is applied first
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
        self._update_props_bar()
        self.statusBar().showMessage(_tool_hint(tool))

    # ---- properties bar ----------------------------------------------------------
    # With an object selected the bar edits that object; otherwise it holds the defaults for new items.

    def _default_fill(self) -> QColor | None:
        value = str(self.settings.value("fill_color", ""))
        return QColor(value) if value else None

    def _default_dashed(self) -> bool:
        return str(self.settings.value("line_dashed", "false")) == "true"

    def _default_opacity(self) -> float:
        return float(self.settings.value("opacity", 1.0))

    def _show_fill(self, color: QColor | None):
        pix = QPixmap(28, 16)
        pix.fill(color if color is not None else QColor("white"))
        p = QPainter(pix)
        p.setPen(QPen(QColor("#888"), 1))
        p.drawRect(0, 0, 27, 15)
        if color is None:  # "no fill": a red diagonal
            p.setPen(QPen(QColor(220, 38, 38), 2))
            p.drawLine(2, 14, 26, 2)
        p.end()
        self.fill_btn.setIcon(QIcon(pix))
        self.fill_btn.setIconSize(pix.size())

    def _show_style(self, color: QColor, fill: QColor | None, width: float, dashed: bool, opacity: float):
        for w in (self.width_spin, self.dash_combo, self.opacity_spin):
            w.blockSignals(True)
        self.color_btn.set_color(color)
        self._show_fill(fill)
        self.width_spin.setValue(max(1, round(width)))
        self.dash_combo.setCurrentIndex(1 if dashed else 0)
        self.opacity_spin.setValue(round(opacity * 100))
        for w in (self.width_spin, self.dash_combo, self.opacity_spin):
            w.blockSignals(False)

    def _show_defaults(self):
        self.props_label.setText(tr("New items:"))
        self._show_style(self.view.pen_color, self._default_fill(), self.view.pen_width, self._default_dashed(),
                         self._default_opacity())

    def _enable_props(self, fields: set[str]):
        for name, widgets in self._prop_widgets.items():
            for w in widgets:
                w.setEnabled(name in fields)

    def _update_props_bar(self):
        """Show the properties bar only for tools that use it, with only the settings that apply."""
        tool = self.view.tool
        obj = self.view.selection
        if tool in _TOOL_PROPS:
            self._show_defaults()
            self._enable_props(_TOOL_PROPS[tool])
        elif tool == Tool.SELECT and obj is not None:
            self.props_label.setText(tr("Selected {kind}:", kind=_object_label(obj)))
            color = QColor.fromRgbF(*obj.stroke) if obj.stroke else self.view.pen_color
            fill = QColor.fromRgbF(*obj.fill) if obj.fill else None
            self._show_style(color, fill, obj.width or self.view.pen_width, obj.dashed, obj.opacity)
            self._enable_props(_object_props(obj))
        elif tool == Tool.SELECT:
            self.props_label.setText(tr("Nothing selected"))
            self._enable_props(set())
        self.props_bar.setVisible(tool in _TOOL_PROPS or tool == Tool.SELECT)

    def _on_selection(self, obj):
        self._update_props_bar()
        if obj is None:
            return
        if obj.movable:
            hint = tr("Drag to move, drag the handles to resize. Delete removes it; double-click edits it.")
        else:
            hint = tr("This object cannot be moved here; you can change its color or delete it.")
        self.statusBar().showMessage(hint)

    def _style_selection(self, **style) -> bool:
        """Apply a style change to the selected object. Returns False if nothing styleable is selected."""
        obj = self.view.selection
        if obj is None or not obj.styleable:
            return False
        if self._run(lambda: self.doc.style_object(obj, **style), [obj.page]):
            self._reselect(obj.page, obj.rect)
        return True

    def _reselect(self, pno: int, rect: pymupdf.Rect, line=None):
        """Select the object now at `rect` (objects are re-read after every change)."""
        if line is not None:
            (x0, y0), (x1, y1) = line
            x, y = (x0 + x1) / 2, (y0 + y1) / 2
        else:
            x, y = (rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2
        obj = self.doc.object_at(pno, x, y) or self.doc.object_at(pno, rect.x0 + 2, rect.y0 + 2)
        self.view.set_selection(obj)

    def _pick_color(self):
        self.color_btn._pick()
        if not self._style_selection(stroke=dialogs.rgb(self.color_btn.color)):
            self.view.pen_color = self.color_btn.color
            self.settings.setValue("pen_color", self.color_btn.color.name())

    def _pick_fill(self):
        current = self._default_fill() or QColor("white")
        color = QColorDialog.getColor(current, self, tr("Fill color"))
        if color.isValid():
            self._set_fill(color)

    def _set_fill(self, color: QColor | None):
        self._show_fill(color)
        if not self._style_selection(fill=dialogs.rgb(color) if color is not None else None):
            self.settings.setValue("fill_color", color.name() if color is not None else "")

    def _set_pen_width(self, value: int):
        if not self._style_selection(width=float(value)):
            self.view.pen_width = float(value)
            self.settings.setValue("pen_width", value)

    def _set_dashed(self, dashed: bool):
        if not self._style_selection(dashed=dashed):
            self.settings.setValue("line_dashed", "true" if dashed else "false")

    def _set_opacity(self, opacity: float):
        if not self._style_selection(opacity=opacity):
            self.settings.setValue("opacity", opacity)

    # ---- select tool -------------------------------------------------------------

    def _on_object_changed(self, obj, rect, line):
        if self._run(lambda: self.doc.transform_object(obj, rect, line), [obj.page]):
            self._reselect(obj.page, rect, line)

    def _delete_selection(self):
        obj = self.view.selection
        if obj is not None:
            self._run(lambda: self.doc.delete_object(obj), [obj.page])

    def _on_object_activated(self, obj):
        if obj.kind == "text":
            self._start_edit_paragraph(obj.block)
        elif obj.kind == "widget":
            self.forms_dock.show()
        elif obj.kind == "annot" and obj.subtype == "Text":
            dlg = dialogs.NoteDialog(self, self.doc.object_text(obj))
            if dlg.exec():
                text = dlg.text.toPlainText()
                if self._run(lambda: self.doc.set_note_text(obj.page, obj.xref, text), [obj.page]) and text.strip():
                    self._reselect(obj.page, obj.rect)
        elif obj.kind == "annot" and obj.subtype == "Stamp":
            color = QColor.fromRgbF(*obj.stroke) if obj.stroke else QColor("#c81e1e")
            dlg = dialogs.StampDialog(self, self.doc.object_text(obj), color)
            if dlg.exec():
                text, new_color = dlg.text.currentText(), dialogs.rgb(dlg.color.color)
                if self._run(lambda: self.doc.set_stamp_text(obj, text, new_color), [obj.page]):
                    self._reselect(obj.page, obj.rect)

    def _last_dir(self) -> str:
        return self.settings.value(
            "last_dir", QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation))

    # ---- files ---------------------------------------------------------------

    def _confirm_discard(self) -> bool:
        self.view.finish_inline(commit=True)
        if not self.doc or not self.doc.dirty:
            return True
        r = QMessageBox.question(
            self, APP_NAME, tr("There are unsaved changes. Do you want to save them?"),
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel)
        if r == QMessageBox.StandardButton.Save:
            return self.save()
        return r == QMessageBox.StandardButton.Discard

    # ---- recent files ----------------------------------------------------------------

    MAX_RECENT = 10

    def _recent_files(self) -> list[str]:
        value = self.settings.value("recent_files", [])
        if isinstance(value, str):  # QSettings returns a lone entry as a plain string
            value = [value]
        return [str(v) for v in (value or []) if v]

    def _set_recent_files(self, paths: list[str]):
        self.settings.setValue("recent_files", paths[: self.MAX_RECENT])
        if self.doc is None:
            self._update_empty()

    def _add_recent(self, path: str):
        path = os.path.abspath(path)
        key = os.path.normcase(path)
        self._set_recent_files([path] + [p for p in self._recent_files() if os.path.normcase(p) != key])

    def _fill_recent_menu(self):
        self.recent_menu.clear()
        paths = self._recent_files()
        for i, path in enumerate(paths):
            number = f"&{i + 1}" if i < 9 else str(i + 1)  # Alt+1..9 shortcuts
            a = self.recent_menu.addAction(f"{number}  {os.path.basename(path).replace('&', '&&')}")
            a.setToolTip(path)
            a.setStatusTip(path)
            a.triggered.connect(lambda _c=False, p=path: self._open_recent(p))
        if not paths:
            self.recent_menu.addAction(tr("No recent files")).setEnabled(False)
        else:
            self.recent_menu.addSeparator()
            self.recent_menu.addAction(tr("Clear list"), lambda: self._set_recent_files([]))
        self.recent_menu.setToolTipsVisible(True)

    def _open_recent(self, path: str):
        if not os.path.exists(path):
            dialogs.warn(self, tr("The file no longer exists:\n{path}\n\nIt was removed from the list.", path=path))
            self._set_recent_files([p for p in self._recent_files() if p != path])
            return
        if self._confirm_discard():
            self.open_path(path)

    def _update_empty(self):
        """The start screen: how to open a file and the recent files as links."""
        parts = [f"<p style='color: gray; font-size: 15px'>"
                 f"{html.escape(tr('Press Ctrl+O to open a PDF or drag a file here.'))}</p>"]
        paths = self._recent_files()
        if paths:
            parts.append(f"<p style='margin-top: 24px'><b>{html.escape(tr('Recent files'))}</b></p>")
            for i, path in enumerate(paths):
                folder = os.path.dirname(path)
                parts.append(f"<p style='margin: 4px'><a href='{i}'>{html.escape(os.path.basename(path))}</a>"
                             f"<br><span style='color: gray; font-size: 11px'>{html.escape(folder)}</span></p>")
        self.empty.setText("".join(parts))

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
        self._add_recent(doc.path)
        self._text_cache.clear()
        self._clear_search()
        self.find_bar.hide()
        self.view.set_document(doc)
        self.thumbs.set_document(doc)
        self._set_tool(Tool.BROWSE)
        self.view.fit_width()
        self._load_form_fields(show_if_any=True)
        self._load_bookmarks()
        (self.bookmarks_dock if doc.bookmarks() else self.pages_dock).raise_()
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

    def _confirm_pending_redactions(self) -> bool:
        """Marked-but-unapplied redactions still contain the content; offer to apply them."""
        count = self.doc.redaction_count()
        if not count:
            return True
        r = QMessageBox.warning(
            self, APP_NAME,
            tr("{count} area(s) are marked for redaction but not applied yet. The marked content is still in "
               "the file and can be read by anyone.\n\nApply the redactions before saving?", count=count),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Yes)
        if r == QMessageBox.StandardButton.Yes:
            return self._run(self.doc.apply_redactions)
        return r == QMessageBox.StandardButton.No

    def save(self) -> bool:
        if not self.doc:
            return False
        self.view.finish_inline(commit=True)
        if not self.doc.path:
            return self.save_as()
        if not self._confirm_pending_redactions() or not self._confirm_breaking_signatures():
            return False
        return self._save_to(self.doc.path)

    def save_as(self) -> bool:
        if not self.doc:
            return False
        self.view.finish_inline(commit=True)
        if not self._confirm_pending_redactions() or not self._confirm_breaking_signatures():
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
        self._add_recent(path)
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
        self.view.finish_inline(commit=True)
        if self.doc and self.doc.can_undo():
            self.doc.undo()
            self._changed()

    def redo(self):
        self.view.finish_inline(commit=True)
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
        """Move the selected pages one place up (-1) or down (+1)."""
        if not self.doc:
            return
        pages = self._target_pages()
        to = min(pages) - 1 if step < 0 else max(pages) + 2
        if 0 <= to <= self.doc.page_count:
            self._move_pages(pages, to)

    def _move_pages(self, pages: list[int], to: int):
        moved: list[int] = []
        if self._run(lambda: moved.extend(self.doc.move_pages(pages, to))) and moved:
            self.thumbs.clearSelection()
            for pno in moved:
                self.thumbs.item(pno).setSelected(True)
            self.thumbs.scrollToItem(self.thumbs.item(moved[0]))
            self.view.go_to(moved[0])

    def _delete_pages(self):
        if not self.doc:
            return
        pages = self._target_pages()
        question = (tr("Delete {count} pages?", count=len(pages)) if len(pages) > 1
                    else tr("Delete page {number}?", number=pages[0] + 1))
        if QMessageBox.question(self, APP_NAME, question) == QMessageBox.StandardButton.Yes:
            if self._run(lambda: self.doc.delete_pages(pages)):
                self.thumbs.clearSelection()

    def _text_items(self, kind: str, pno: int) -> list:
        """Cached `text_lines` ("lines") or `text_blocks` ("blocks") of a page."""
        cached = self._text_cache.get((kind, pno))
        if cached and cached[0] == self.doc.revision:
            return cached[1]
        items = self.doc.text_lines(pno) if kind == "lines" else self.doc.text_blocks(pno)
        self._text_cache[(kind, pno)] = (self.doc.revision, items)
        return items

    def _text_item_at(self, kind: str, pno: int, x: float, y: float):
        p = pymupdf.Point(x, y)
        return next((item for item in self._text_items(kind, pno) if p in item.rect), None)

    def _hover_rect(self, tool: Tool, pno: int, x: float, y: float):
        if tool in (Tool.EDIT_TEXT, Tool.EDIT_PARAGRAPH):
            item = self._text_item_at("lines" if tool == Tool.EDIT_TEXT else "blocks", pno, x, y)
            return item.rect if item else None
        if tool == Tool.ERASE:
            return self.doc.annot_rect_at(pno, x, y)
        if tool == Tool.NOTE:
            return self.doc.annot_rect_at(pno, x, y) if self.doc.note_at(pno, x, y) else None
        return None

    def _on_click(self, pno: int, x: float, y: float):
        tool = self.view.tool
        if tool == Tool.ADD_TEXT:
            self._start_add_text(pno, x, y)
        elif tool in (Tool.EDIT_TEXT, Tool.EDIT_PARAGRAPH):
            item = self._text_item_at("lines" if tool == Tool.EDIT_TEXT else "blocks", pno, x, y)
            if item is None:
                self.statusBar().showMessage(tr("There is no editable text here. (Text on scanned pages is an "
                                                 "image and cannot be edited.)"), 5000)
                return
            if tool == Tool.EDIT_TEXT:
                self._start_edit_line(item)
            else:
                self._start_edit_paragraph(item)
        elif tool == Tool.NOTE:
            existing = self.doc.note_at(pno, x, y)
            if existing:
                dlg = dialogs.NoteDialog(self, existing[1])
            else:
                dlg = dialogs.NoteDialog(self, new=True, color=QColor(self.settings.value("note_color", "#ffd933")),
                                         icon=str(self.settings.value("note_icon", "Note")))
            if not dlg.exec():
                return
            text = dlg.text.toPlainText()
            if existing:
                if text != existing[1]:
                    self._run(lambda: self.doc.set_note_text(pno, existing[0], text), [pno])
            elif text.strip():
                icon, color = dlg.icon.currentData(), dlg.color.color
                self.settings.setValue("note_icon", icon)
                self.settings.setValue("note_color", color.name())
                self._run(lambda: self.doc.add_note(pno, x, y, text, dialogs.rgb(color), icon), [pno])
        elif tool == Tool.ERASE:
            if self.doc.annot_rect_at(pno, x, y) is None:
                self.statusBar().showMessage(tr("There is no annotation to erase here. Use Undo (Ctrl+Z) for "
                                                 "added text and images."), 5000)
                return
            self._run(lambda: self.doc.delete_annot_at(pno, x, y), [pno])

    # ---- on-page text editing ----------------------------------------------------

    def _text_style(self, pno: int) -> TextStyle:
        """The style new text starts with (remembered from the last text added).

        The size is remembered as it would be on an A4 page and scaled to the page's size.
        """
        size = float(self.settings.value("text_size", 12)) * self.doc.text_scale(pno)
        return TextStyle(str(self.settings.value("text_family", "sans")),
                         str(self.settings.value("text_bold", "false")) == "true",
                         str(self.settings.value("text_italic", "false")) == "true",
                         round(size, 1), dialogs.rgb(self.view.pen_color))

    def _remember_text_style(self, style: TextStyle, pno: int):
        self.settings.setValue("text_family", style.family)
        self.settings.setValue("text_bold", "true" if style.bold else "false")
        self.settings.setValue("text_italic", "true" if style.italic else "false")
        self.settings.setValue("text_size", round(style.size / self.doc.text_scale(pno), 1))

    def _start_add_text(self, pno: int, x: float, y: float):
        style = self._text_style(pno)
        width = self.doc.default_text_width(pno, x, style.size)

        def commit(r):
            if not r.runs or not "".join(run.text for run in r.runs).strip():
                return
            self._remember_text_style(r.runs[0].style, pno)
            self.settings.setValue("text_align", r.align)
            self._run(lambda: self.doc.add_text(pno, x, y, r.runs, align=r.align, line_height=r.line_height,
                                                width=r.width), [pno])

        self.view.start_inline(pno, x=x, top=y, width=width, runs=[], default=style, paragraph=True,
                               align=str(self.settings.value("text_align", "left")), on_commit=commit)
        self.statusBar().showMessage(tr("Type the text. Ctrl+Enter or a click outside the box adds it; Esc "
                                        "cancels."))

    def _start_edit_line(self, line):
        def commit(r):
            if r.runs != line.runs:
                self._run(lambda: self.doc.replace_line(line, r.runs), [line.page])

        self.view.start_inline(line.page, x=line.rect.x0, top=line.rect.y0, width=line.rect.width, runs=line.runs,
                               default=line.runs[0].style if line.runs else self._text_style(line.page), paragraph=False,
                               min_height=line.rect.height, on_commit=commit)
        self.statusBar().showMessage(tr("Edit the line. Ctrl+Enter or a click outside the box applies it; Esc "
                                        "cancels. Leave it empty to delete the line."))

    def _start_edit_paragraph(self, block):
        def commit(r):
            if (r.runs, r.align, round(r.line_height, 2), round(r.width, 1)) == (
                    block.runs, block.align, round(block.line_height, 2), round(block.width, 1)):
                return
            overlaps = []
            if self._run(lambda: overlaps.append(self.doc.replace_block(
                    block, r.runs, align=r.align, line_height=r.line_height, width=r.width)), [block.page]):
                if overlaps and overlaps[0]:
                    self.statusBar().showMessage(tr("The paragraph now overlaps the text below it. Make it "
                                                    "shorter or wider, or undo with Ctrl+Z."), 10000)

        first = block.runs[0].style if block.runs else TextStyle(size=block.size)
        top = block.first_baseline - richtext.ascent(first)
        self.view.start_inline(block.page, x=block.left, top=min(top, block.rect.y0), width=block.width,
                               runs=block.runs, default=block.runs[0].style if block.runs else self._text_style(block.page),
                               paragraph=True, align=block.align, line_height=block.line_height,
                               min_height=block.rect.height, on_commit=commit)
        self.statusBar().showMessage(tr("Edit the paragraph. Ctrl+Enter or a click outside the box applies it; "
                                        "Esc cancels. Drag the blue handle to change the width."))

    def _on_stroke(self, pno: int, points: list):
        self._run(lambda: self.doc.add_ink(pno, [points], dialogs.rgb(self.view.pen_color), self.view.pen_width,
                                           opacity=self._default_opacity()), [pno])

    def _on_line(self, pno: int, start, end):
        arrow = self.view.tool == Tool.ARROW
        self._run(lambda: self.doc.add_line(pno, start, end, dialogs.rgb(self.view.pen_color),
                                            self.view.pen_width, arrow, dashed=self._default_dashed(),
                                            opacity=self._default_opacity()), [pno])

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
                                                  tr("Images (*.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff *.heic *.heif)"))
            if not path:
                return
            data = self._read_files([path], dialogs.read_image)
            if data is None:
                return
            data = data[0]
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
        elif tool in (Tool.RECT, Tool.ELLIPSE):
            kind = "rect" if tool == Tool.RECT else "ellipse"
            fill = self._default_fill()
            self._run(lambda: self.doc.add_shape(pno, kind, rect, dialogs.rgb(self.view.pen_color),
                                                 self.view.pen_width, fill=dialogs.rgb(fill) if fill else None,
                                                 dashed=self._default_dashed(), opacity=self._default_opacity()),
                      [pno])
        elif tool == Tool.STAMP:
            dlg = dialogs.StampDialog(self, self.settings.value("stamp_text", ""),
                                      QColor(self.settings.value("stamp_color", "#c81e1e")))
            if not dlg.exec():
                return
            text = dlg.text.currentText().strip()
            self.settings.setValue("stamp_text", text)
            self.settings.setValue("stamp_color", dlg.color.color.name())
            box = self._box_at(rect, 160, 3.2, size)
            self._run(lambda: self.doc.add_stamp(pno, box, text, dialogs.rgb(dlg.color.color)), [pno])
        elif tool == Tool.REDACT:
            if rect.width >= 2 and rect.height >= 2:
                self._run(lambda: self.doc.mark_redactions([(pno, rect)]), [pno])
        elif tool == Tool.CROP:
            if rect.width < 10 or rect.height < 10:
                return
            selected = self.thumbs.selected_pages()
            pages = selected if pno in selected else [pno]  # the framed page, plus the others selected with it
            if self._run(lambda: self.doc.crop_pages(pages, rect), pages):
                self._set_tool(Tool.BROWSE)
        elif tool == Tool.FORM_FIELD:
            dlg = dialogs.FormFieldDialog(self, self.doc.suggest_field_name)
            if not dlg.exec():
                return
            kind = dlg.kind.currentData()
            width, aspect = {"checkbox": (14, 1.0), "multiline": (220, 3.0), "listbox": (160, 2.0)}.get(
                kind, (180, 9.0))
            box = self._box_at(rect, width, aspect, size)
            if self._run(lambda: self.doc.add_form_field(pno, box, kind, dlg.name.text(), dlg.option_list()), [pno]):
                self.forms_dock.show()
                self._load_form_fields()

    def _apply_form(self, values: dict):
        self._run(lambda: self.doc.set_form_values(values))

    def _load_form_fields(self, show_if_any: bool = False):
        fields = self.doc.form_fields() if self.doc else []
        self.form_panel.set_fields(fields)
        if show_if_any:
            self.forms_dock.setVisible(bool(fields))

    # ---- search ----------------------------------------------------------------

    def find(self):
        if self.doc:
            self.find_bar.open_bar()

    def _search(self, query: str, keep_position: bool = False):
        if not self.doc:
            return
        old = self._hits[self._hit_index] if keep_position and self._hit_index is not None else None
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self._hits = self.doc.search(query)
        finally:
            QApplication.restoreOverrideCursor()
        if not self._hits:
            self._hit_index = None
        elif old is not None:
            # Stay near the previous match after an edit.
            self._hit_index = next((i for i, h in enumerate(self._hits)
                                    if (h.page, h.rect.y0, h.rect.x0) >= (old.page, old.rect.y0, old.rect.x0)), 0)
        else:
            current = self.view.current_page()
            self._hit_index = next((i for i, h in enumerate(self._hits) if h.page >= current), 0)
        self._show_hits(scroll=not keep_position)

    def _step_hit(self, step: int):
        if not self._hits:
            if self.find_bar.edit.text().strip():
                self._search(self.find_bar.edit.text())
            return
        self._hit_index = ((self._hit_index or 0) + step) % len(self._hits)
        self._show_hits()

    def _show_hits(self, scroll: bool = True):
        by_page: dict[int, list] = {}
        for h in self._hits:
            by_page.setdefault(h.page, []).append(h.rect)
        current = None
        if self._hit_index is not None:
            hit = self._hits[self._hit_index]
            current = (hit.page, hit.rect)
            if scroll:
                self.view.show_rect(hit.page, hit.rect)
        self.view.set_search_hits(by_page, current)
        self.find_bar.set_status(self._hit_index, len(self._hits))

    def _clear_search(self):
        self._hits = []
        self._hit_index = None
        self.view.set_search_hits({}, None)

    def _redact_hits(self):
        if not self._hits:
            return
        count = len(self._hits)
        if self._run(lambda: self.doc.mark_redactions([(h.page, h.rect) for h in self._hits])):
            self.statusBar().showMessage(tr("{count} match(es) marked for redaction. Apply them with Document › "
                                            "Apply redactions.", count=count), 8000)

    # ---- bookmarks ---------------------------------------------------------------

    def _load_bookmarks(self):
        self.bookmark_panel.set_bookmarks(self.doc.bookmarks() if self.doc else [], enabled=self.doc is not None)

    def _add_bookmark(self, after):
        pno = self.view.current_page()
        title, ok = QInputDialog.getText(self, tr("Add bookmark"), tr("Bookmark title:"),
                                         text=tr("Page {number}", number=pno + 1))
        if ok:
            self._run(lambda: self.doc.add_bookmark(title, pno, after), [])

    def _rename_bookmark(self, index: int):
        current = self.doc.bookmarks()[index].title
        title, ok = QInputDialog.getText(self, tr("Rename bookmark"), tr("Bookmark title:"), text=current)
        if ok and title != current:
            self._run(lambda: self.doc.rename_bookmark(index, title), [])

    def _delete_bookmark(self, index: int):
        title = self.doc.bookmarks()[index].title
        if QMessageBox.question(self, APP_NAME, tr("Delete the bookmark \"{title}\" and the bookmarks "
                                                   "under it?", title=title)) == QMessageBox.StandardButton.Yes:
            self._run(lambda: self.doc.delete_bookmark(index), [])

    # ---- document --------------------------------------------------------------

    def _page_scope(self) -> dialogs.PageScope:
        return dialogs.PageScope(self.doc.page_count, self.view.current_page(), self.thumbs.selected_pages())

    def reset_crop(self):
        pages = self._target_pages()
        self._run(lambda: self.doc.reset_crop(pages), pages)

    def add_watermark(self):
        dlg = dialogs.WatermarkDialog(self, self._page_scope())
        if dlg.exec():
            pages = dlg.scope.pages()
            self._run(lambda: self.doc.add_watermark(
                pages, dlg.text.text(), dlg.size.value(), dialogs.rgb(dlg.color.color), dlg.opacity.value() / 100,
                dlg.angle.value(), dlg.behind.isChecked()), pages)

    def add_header_footer(self):
        dlg = dialogs.HeaderFooterDialog(self, self._page_scope())
        if dlg.exec():
            pages = dlg.scope.pages()
            self._run(lambda: self.doc.add_header_footer(
                pages, dlg.texts(), dlg.size.value(), dialogs.rgb(dlg.color.color), dlg.margin.value(),
                dlg.family.currentData()), pages)

    def apply_redactions(self):
        count = self.doc.redaction_count()
        if not count:
            dialogs.warn(self, tr("There are no redaction marks. Mark areas with the Redact tool or with "
                                  "Find › Mark all for redaction first."))
            return
        if QMessageBox.warning(
                self, APP_NAME,
                tr("Permanently remove the text, images and drawings under {count} redaction mark(s)? The areas "
                   "are filled with black. Once the file is saved this cannot be undone.", count=count),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            if self._run(self.doc.apply_redactions):
                self.statusBar().showMessage(tr("Redactions applied. Save the document to keep the result."), 6000)

    def _base_name(self) -> str:
        return Path(self.doc.path).stem if self.doc.path else tr("document")

    def _save_copy_path(self, title: str, filename: str, file_filter: str,
                        folder: str | None = None) -> str | None:
        if folder is None:
            folder = os.path.dirname(self.doc.path) if self.doc and self.doc.path else self._last_dir()
        path, _ = QFileDialog.getSaveFileName(self, title, str(Path(folder) / filename), file_filter)
        return path or None

    def _pdf_target(self, title: str, filename: str, folder: str | None = None,
                    original: str | None = None) -> str | None:
        """Where to save a new PDF; never over the open document (or `original`)."""
        path = self._save_copy_path(title, filename, _pdf_filter(), folder)
        if not path:
            return None
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        taken = {os.path.normcase(os.path.abspath(p)) for p in (self.doc.path if self.doc else None, original) if p}
        if os.path.normcase(os.path.abspath(path)) in taken:
            dialogs.warn(self, tr("Choose a different file name; the new file cannot replace the original."))
            return None
        return path

    def _write_new_pdf(self, path: str, make) -> bytes | None:
        """Build a PDF with `make()` and write it to `path`. Returns its bytes, or None after an error."""
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            data = make()
            write_file(path, data)
        except PdfError as e:
            dialogs.warn(self, str(e))
            return None
        except (OSError, RuntimeError) as e:
            dialogs.warn(self, tr("Could not save: {error}", error=e))
            return None
        finally:
            QApplication.restoreOverrideCursor()
        self.settings.setValue("last_dir", os.path.dirname(path))
        return data

    def _offer_open(self, path: str, text: str):
        if (QMessageBox.question(self, APP_NAME, text + "\n\n" + tr("Open it now?"))
                == QMessageBox.StandardButton.Yes and self._confirm_discard()):
            self.open_path(path)

    def compress(self):
        dlg = dialogs.CompressDialog(self, self.doc.has_signatures())
        if not dlg.exec():
            return
        path = self._pdf_target(tr("Save compressed copy"), tr("{base}_compressed.pdf", base=self._base_name()))
        if not path:
            return
        before = len(self.doc.disk_bytes) if self.doc.disk_bytes is not None and not self.doc.dirty else None
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            data = self.doc.compressed_bytes(dlg.level.currentData())
            write_file(path, data)
        except (PdfError, OSError, RuntimeError) as e:
            dialogs.warn(self, tr("Could not save: {error}", error=e))
            return
        finally:
            QApplication.restoreOverrideCursor()
        if before:
            text = tr("Compressed copy saved:\n{path}\n\n{before} → {after} ({percent}% smaller)", path=path,
                      before=_megabytes(before), after=_megabytes(len(data)),
                      percent=max(0, round(100 - 100 * len(data) / before)))
        else:
            text = tr("Compressed copy saved:\n{path}\n\nSize: {after}", path=path, after=_megabytes(len(data)))
        QMessageBox.information(self, APP_NAME, text)

    def export_images(self):
        dlg = dialogs.ExportImagesDialog(self, self._page_scope())
        if not dlg.exec():
            return
        fmt = dlg.fmt.currentData()
        file_filter = tr("PNG images (*.png)") if fmt == "png" else tr("JPEG images (*.jpg)")
        path = self._save_copy_path(tr("Export pages as images"), f"{self._base_name()}.{fmt}", file_filter)
        if not path:
            return
        base = str(Path(path).with_suffix(""))
        pages = dlg.scope.pages()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            written = self.doc.export_images(pages, base, fmt, dlg.dpi.currentData())
        except (PdfError, OSError, RuntimeError) as e:
            dialogs.warn(self, tr("Could not save: {error}", error=e))
            return
        finally:
            QApplication.restoreOverrideCursor()
        self.statusBar().showMessage(tr("{count} image(s) saved, e.g. {path}", count=len(written),
                                        path=written[0]), 8000)

    # ---- whole-file tools -----------------------------------------------------

    def _read_files(self, paths: list[str], read) -> list[tuple[str, bytes]] | None:
        try:
            return [read(p) for p in paths]
        except OSError as e:
            dialogs.warn(self, tr("Could not read the file: {error}", error=e))
        except PdfError as e:
            dialogs.warn(self, str(e))
        return None

    def merge_pdfs(self, paths: list[str] | None = None):
        if self.doc:
            self.view.finish_inline(commit=True)
        open_name = (os.path.basename(self.doc.path) if self.doc.path else tr("Untitled")) if self.doc else None
        dlg = dialogs.MergeDialog(self, self._last_dir(), open_name)
        dlg.files.add_paths(paths or [])
        if not dlg.exec():
            return
        paths = dlg.files.paths()

        def read(p: str) -> tuple[str, bytes]:
            if p == dialogs.OPEN_DOCUMENT:
                return self.doc.path or tr("Untitled"), self.doc.plain_bytes()
            return p, Path(p).read_bytes()

        sources = self._read_files(paths, read)
        if sources is None:
            return
        first_is_open = paths[0] == dialogs.OPEN_DOCUMENT
        base = self._base_name() if first_is_open else Path(paths[0]).stem
        folder = None if first_is_open else os.path.dirname(paths[0])
        path = self._pdf_target(tr("Save merged PDF"), tr("{base}_merged.pdf", base=base), folder)
        if path and self._write_new_pdf(path, lambda: pdftools.merge_pdfs(sources, dlg.bookmarks.isChecked())):
            self._offer_open(path, tr("Merged PDF saved:\n{path}", path=path))

    def images_to_pdf(self, paths: list[str] | None = None):
        dlg = dialogs.ImagesToPdfDialog(self, self._last_dir())
        dlg.files.add_paths(paths or [])
        if not dlg.exec():
            return
        paths = dlg.files.paths()
        images = self._read_files(paths, dialogs.image_file)
        if images is None:
            return
        path = self._pdf_target(tr("Save PDF"), f"{Path(paths[0]).stem}.pdf", os.path.dirname(paths[0]))
        if path and self._write_new_pdf(path, lambda: pdftools.images_to_pdf(
                images, dlg.page_size.currentData(), dlg.orientation.currentData(), dlg.margin.currentData())):
            self._offer_open(path, tr("PDF saved:\n{path}", path=path))

    def split_pdf(self):
        self.view.finish_inline(commit=True)
        dlg = dialogs.SplitDialog(self, self.doc.page_count)
        if not dlg.exec():
            return
        groups = dlg.groups()
        path = self._save_copy_path(tr("Split into separate PDFs"), f"{self._base_name()}.pdf", _pdf_filter())
        if not path:
            return
        base = str(Path(path).with_suffix(""))
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            written = self.doc.split(groups, base)
        except (PdfError, OSError, RuntimeError) as e:
            dialogs.warn(self, tr("Could not save: {error}", error=e))
            return
        finally:
            QApplication.restoreOverrideCursor()
        QMessageBox.information(self, APP_NAME, tr("{count} PDF file(s) saved in:\n{folder}", count=len(written),
                                                   folder=os.path.dirname(written[0])))

    def protect_pdf(self):
        self.view.finish_inline(commit=True)
        dlg = dialogs.ProtectDialog(self, self.doc.has_signatures())
        if not dlg.exec():
            return
        path = self._pdf_target(tr("Save protected copy"), tr("{base}_protected.pdf", base=self._base_name()))
        if path and self._write_new_pdf(path, lambda: self.doc.protected_bytes(
                dlg.open_password.text(), dlg.allowed(), dlg.owner_password.text())):
            QMessageBox.information(self, APP_NAME, tr("Protected copy saved:\n{path}", path=path))

    def unlock_pdf(self):
        self.view.finish_inline(commit=True)
        path = self._pdf_target(tr("Save copy without password"),
                                tr("{base}_unlocked.pdf", base=self._base_name()))
        if path and self._write_new_pdf(path, self.doc.plain_bytes):
            self._offer_open(path, tr("A copy without the password and restrictions was saved:\n{path}", path=path))

    def repair_pdf(self):
        src, _ = QFileDialog.getOpenFileName(self, tr("PDF to repair"), self._last_dir(), _pdf_filter())
        if not src:
            return
        try:
            data = Path(src).read_bytes()
        except OSError as e:
            dialogs.warn(self, tr("Could not read the file: {error}", error=e))
            return
        path = self._pdf_target(tr("Save repaired PDF"), tr("{base}_repaired.pdf", base=Path(src).stem),
                                os.path.dirname(src), original=src)
        report = None

        def make() -> bytes:
            nonlocal report
            out, report = pdftools.repair_pdf(data)
            return out

        if not path or not self._write_new_pdf(path, make):
            return
        lines = [tr("Repaired PDF saved:\n{path}", path=path), "",
                 tr("The file's structure was damaged and has been rebuilt.") if report.rebuilt else
                 tr("No structural damage was found; the file was rewritten cleanly."),
                 tr("{count} page(s) recovered.", count=report.pages)]
        if report.dropped:
            lines.append(tr("{count} unreadable page(s) could not be recovered and were left out.",
                            count=report.dropped))
        self._offer_open(path, "\n".join(lines))

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

    # ---- Explorer integration ------------------------------------------------------

    def _update_explorer_actions(self):
        exe = shell.current_exe()
        for a in (self.act_open_with, *self.act_shortcuts.values()):
            a.setVisible(shell.supported())
            a.setEnabled(exe is not None)
            a.setToolTip("" if exe else tr("Available in the packaged app (LeafpenPDF.exe)."))
        if not (exe and shell.supported()):
            return
        registered = shell.registered_exe()
        self.act_open_with.setChecked(bool(registered and os.path.normcase(registered) == os.path.normcase(exe)))
        for place, a in self.act_shortcuts.items():
            try:
                a.setChecked(shell.shortcut_is_ours(shell.shortcut_path(place, APP_NAME), exe))
            except OSError:
                a.setChecked(False)

    def _toggle_open_with(self, on: bool):
        exe = shell.current_exe()
        if exe is None:
            return
        try:
            if on:
                shell.register(exe, APP_NAME)
                self.statusBar().showMessage(tr("{name} now appears under Open with for PDF files. Your default "
                                                "PDF program is unchanged.", name=APP_NAME), 8000)
            else:
                shell.unregister()
                self.statusBar().showMessage(tr("{name} was removed from Open with.", name=APP_NAME), 6000)
        except OSError as e:
            dialogs.warn(self, tr("Windows did not allow the change: {error}", error=e))
        self._update_explorer_actions()

    def _toggle_shortcut(self, place: str, on: bool):
        exe = shell.current_exe()
        if exe is None:
            return
        try:
            lnk = shell.shortcut_path(place, APP_NAME)
            if on:
                shell.create_shortcut(lnk, exe, APP_NAME)
                self.statusBar().showMessage(tr("Shortcut created: {path}", path=lnk), 6000)
            elif shell.shortcut_is_ours(lnk, exe):  # never delete a same-named shortcut to another copy
                shell.remove_shortcut(lnk)
                self.statusBar().showMessage(tr("Shortcut removed."), 6000)
        except OSError as e:
            dialogs.warn(self, tr("Windows did not allow the change: {error}", error=e))
        self._update_explorer_actions()

    def _follow_moved_folder(self):
        """The portable folder was moved: keep an existing "Open with" entry and shortcuts working."""
        exe = shell.current_exe()
        if exe and shell.supported():
            try:
                shell.refresh_if_moved(exe, APP_NAME)
                for place in shell.SHORTCUT_PLACES:
                    shell.refresh_shortcut_if_moved(shell.shortcut_path(place, APP_NAME), exe, APP_NAME)
            except OSError:
                pass

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

    @staticmethod
    def _dropped(e) -> tuple[list[str], list[str]]:
        """Dropped PDFs and images."""
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        exts = [os.path.splitext(p)[1].lstrip(".").lower() for p in paths]
        return ([p for p, x in zip(paths, exts) if x == "pdf"],
                [p for p, x in zip(paths, exts) if x in dialogs.IMAGE_EXTENSIONS])

    def dragEnterEvent(self, e):
        if any(self._dropped(e)):
            e.acceptProposedAction()

    def dropEvent(self, e):
        """One PDF opens; several go to Merge PDFs, and images to Create PDF from images."""
        pdfs, images = self._dropped(e)
        if len(pdfs) == 1:
            if self._confirm_discard():
                self.open_path(pdfs[0])
        elif pdfs:
            self.merge_pdfs(pdfs)
        elif images:
            self.images_to_pdf(images)

    def closeEvent(self, e):
        if not self._restarting and not self._confirm_discard():
            e.ignore()
            return
        self.settings.setValue("geometry", self.saveGeometry())
        e.accept()
