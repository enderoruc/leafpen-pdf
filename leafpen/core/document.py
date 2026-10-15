"""PDF document model; every edit goes through here.

Coordinates in the public API are *display* coordinates: PDF points with the
origin at the top-left of the page as the user sees it (after /Rotate is
applied). MuPDF extracts and inserts in unrotated page space, so each method
converts with the page's (de)rotation matrix.
"""
from __future__ import annotations

import os
import re
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass, field

import pymupdf

from ..i18n import tr
from . import fonts

pymupdf.TOOLS.mupdf_display_errors(False)


class PdfError(Exception):
    """An operation failed; the message is user-facing (translated with `tr`)."""


class PasswordRequired(PdfError):
    def __init__(self, wrong: bool):
        super().__init__(tr("Wrong password.") if wrong else tr("This PDF is password protected."))
        self.wrong = wrong


def write_file(path: str, data: bytes) -> None:
    """Write via a temporary file so a failure never leaves a half-written PDF."""
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(path)), suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        # Antivirus scanners and the search indexer briefly lock freshly written
        # files on Windows; a short retry avoids spurious failures.
        for attempt in range(20):
            try:
                os.replace(tmp, path)
                break
            except PermissionError as e:
                if attempt == 19:
                    raise PdfError(tr("Could not write the file; another program may be using it.")) from e
                time.sleep(0.1)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _auto_font_size(w: pymupdf.Widget) -> float:
    """Concrete size for an "auto" (0 Tf) field; MuPDF renders auto-size fields invisibly."""
    r = w.rect
    if w.field_flags & pymupdf.PDF_TX_FIELD_IS_MULTILINE:
        return max(6.0, min(10.0, r.height - 4))
    size = max(6.0, min(12.0, (r.height - 4) * 0.8))
    text = str(w.field_value or "")
    width = pymupdf.get_text_length(text, fontname="helv", fontsize=size) if text else 0
    if width > r.width - 6:
        size = max(6.0, size * (r.width - 6) / width)
    return round(size, 1)


_NUM = r"(-?[\d.]+)"
_FLIPPED_TM = re.compile(rf"1 0 0 -1 {_NUM} {_NUM} Tm")
_FLIPPED_CLIP = re.compile(rf"(1 0 0 -1 -?0 {_NUM} cm\nq\n){_NUM} {_NUM} {_NUM} {_NUM} re")


def _fix_text_field_appearance(doc: pymupdf.Document, w: pymupdf.Widget) -> None:
    """Repair MuPDF's appearance for text fields containing non-WinAnsi text.

    For text such as "Ayşe" MuPDF switches to a Unicode layout path that places
    the baseline below the field box, so the value is clipped away. Move the
    lines back inside the box (baseline as in MuPDF's correct WinAnsi path).
    """
    kind, ref = doc.xref_get_key(w.xref, "AP/N")
    if kind != "xref":
        return
    ap = int(ref.split()[0])
    stream = doc.xref_stream(ap).decode("latin-1")
    ys = [float(m.group(2)) for m in _FLIPPED_TM.finditer(stream)]
    clip = _FLIPPED_CLIP.search(stream)
    if not ys or not clip:
        return
    x0, y0, x1, y1 = (float(v) for v in doc.xref_get_key(ap, "BBox")[1].strip("[] ").split())
    width, height = x1 - x0, y1 - y0
    size = w.text_fontsize or 12
    if w.field_flags & pymupdf.PDF_TX_FIELD_IS_MULTILINE:
        first = 2 + size * 0.9  # first baseline, measured from the top
    else:
        first = height - ((height - size) / 2 + size * 0.2)
    delta = first - ys[0]
    stream = _FLIPPED_TM.sub(lambda m: f"1 0 0 -1 {m.group(1)} {float(m.group(2)) + delta:.2f} Tm", stream)
    stream = _FLIPPED_CLIP.sub(lambda m: f"{m.group(1)}0 0 {width:.2f} {height:.2f} re", stream)
    doc.update_stream(ap, stream.encode("latin-1"))


@dataclass
class TextLine:
    page: int
    rect: pymupdf.Rect  # display coordinates
    text: str
    size: float
    color: tuple[float, float, float]
    family: str
    bold: bool
    italic: bool
    origin: pymupdf.Point  # unrotated baseline start
    bbox: pymupdf.Rect  # unrotated


@dataclass
class FormField:
    name: str
    kind: str  # "text" | "checkbox" | "radio" | "choice"
    value: object
    page: int
    choices: list[str] = field(default_factory=list)
    readonly: bool = False


_KEEP = pymupdf.PDF_ENCRYPT_KEEP
_SKIP_ANNOTS = (pymupdf.PDF_ANNOT_POPUP, pymupdf.PDF_ANNOT_LINK, pymupdf.PDF_ANNOT_WIDGET)


class PdfDocument:
    MAX_UNDO = 30

    def __init__(self, data: bytes, path: str | None = None, password: str | None = None):
        self._password = password
        self._doc = self._load(data)
        self.path = path
        self._undo: list[tuple[bytes, int]] = []
        self._redo: list[tuple[bytes, int]] = []
        self._state = 0
        self._next_state = 1
        self._saved_state = 0
        # Bytes of the file on disk; equals the document while _state == _saved_state.
        self._disk_bytes: bytes | None = data if path else None
        self.revision = 0  # bumped on every change; lets views drop cached renders

    @classmethod
    def open(cls, path: str, password: str | None = None) -> "PdfDocument":
        with open(path, "rb") as f:
            data = f.read()
        return cls(data, os.path.abspath(path), password)

    def _load(self, data: bytes) -> pymupdf.Document:
        try:
            doc = pymupdf.open("pdf", data)
        except Exception as e:
            raise PdfError(tr("Could not open the PDF; the file is damaged or not a PDF. ({error})",
                             error=e)) from e
        if doc.needs_pass:
            if self._password is None:
                raise PasswordRequired(wrong=False)
            if not doc.authenticate(self._password):
                raise PasswordRequired(wrong=True)
        if doc.page_count == 0:
            raise PdfError(tr("The PDF has no pages."))
        return doc

    # ---- state -------------------------------------------------------------

    @property
    def page_count(self) -> int:
        return self._doc.page_count

    @property
    def dirty(self) -> bool:
        return self._state != self._saved_state

    @property
    def password(self) -> str | None:
        return self._password

    @property
    def is_encrypted(self) -> bool:
        return self._doc.is_encrypted or self._password is not None

    def can_undo(self) -> bool:
        return bool(self._undo)

    def can_redo(self) -> bool:
        return bool(self._redo)

    def _snapshot(self) -> bytes:
        return self._doc.tobytes(garbage=0, encryption=_KEEP)

    def _restore(self, data: bytes) -> None:
        self._doc.close()
        self._doc = self._load(data)

    @contextmanager
    def _edit(self):
        """Run a mutation atomically: on failure the document is rolled back."""
        snap = self._snapshot()
        try:
            yield
        except BaseException:
            self._restore(snap)
            raise
        self._undo.append((snap, self._state))
        del self._undo[: -self.MAX_UNDO]
        self._redo.clear()
        self._state = self._next_state
        self._next_state += 1
        self.revision += 1

    def undo(self) -> None:
        if not self._undo:
            return
        snap, state = self._undo.pop()
        self._redo.append((self._snapshot(), self._state))
        self._restore(snap)
        self._state = state
        self.revision += 1

    def redo(self) -> None:
        if not self._redo:
            return
        snap, state = self._redo.pop()
        self._undo.append((self._snapshot(), self._state))
        self._restore(snap)
        self._state = state
        self.revision += 1

    def save(self, path: str) -> None:
        path = os.path.abspath(path)
        if not self.dirty and self._disk_bytes is not None:
            data = self._disk_bytes  # byte-identical copy keeps existing signatures valid
        else:
            data = self._doc.tobytes(garbage=3, deflate=True, encryption=_KEEP)
        write_file(path, data)
        self.path = path
        self._saved_state = self._state
        self._disk_bytes = data

    @property
    def disk_bytes(self) -> bytes | None:
        return self._disk_bytes

    def signing_source(self) -> bytes:
        """Bytes to sign. Unmodified files are signed as-is so existing signatures survive."""
        if not self.dirty and self._disk_bytes is not None:
            return self._disk_bytes
        return self._doc.tobytes(garbage=3, deflate=True, encryption=_KEEP)

    def has_signatures(self) -> bool:
        for page in self._doc:
            for w in page.widgets(types=[pymupdf.PDF_WIDGET_TYPE_SIGNATURE]):
                if self._doc.xref_get_key(w.xref, "V")[0] != "null":
                    return True
        return False

    def close(self) -> None:
        self._doc.close()

    # ---- rendering ---------------------------------------------------------

    def page_size(self, pno: int) -> tuple[float, float]:
        r = self._doc[pno].rect
        return r.width, r.height

    def render(self, pno: int, zoom: float) -> pymupdf.Pixmap:
        return self._doc[pno].get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)

    # ---- pages -------------------------------------------------------------

    def rotate_pages(self, pnos: list[int], degrees: int) -> None:
        with self._edit():
            for pno in pnos:
                page = self._doc[pno]
                page.set_rotation((page.rotation + degrees) % 360)

    def delete_pages(self, pnos: list[int]) -> None:
        pnos = sorted(set(pnos))
        if len(pnos) >= self.page_count:
            raise PdfError(tr("All pages cannot be deleted; a PDF must keep at least one page."))
        with self._edit():
            self._doc.delete_pages(pnos)

    def move_page(self, src: int, dst: int) -> None:
        """Move page `src` so that it ends up at index `dst`."""
        if src == dst or not (0 <= dst < self.page_count):
            return
        with self._edit():
            # MuPDF's move_page inserts *before* the target index (-1 = append).
            to = dst if dst < src else dst + 1
            self._doc.move_page(src, -1 if to >= self.page_count else to)

    def insert_pdf(self, path: str, at: int) -> int:
        """Insert all pages of another PDF before index `at`. Returns pages added."""
        try:
            other = pymupdf.open(path)
        except Exception as e:
            raise PdfError(tr("Could not open the PDF to insert: {error}", error=e)) from e
        with other:
            if not other.is_pdf:
                raise PdfError(tr("The selected file is not a PDF."))
            if other.needs_pass:
                raise PdfError(tr("The PDF to insert is password protected; remove its password first."))
            with self._edit():
                self._doc.insert_pdf(other, start_at=at)
            return other.page_count

    def extract_pages(self, pnos: list[int], path: str) -> None:
        out = pymupdf.open()
        for pno in sorted(set(pnos)):
            out.insert_pdf(self._doc, from_page=pno, to_page=pno)
        out.save(path, garbage=3, deflate=True)
        out.close()

    # ---- text --------------------------------------------------------------

    def text_lines(self, pno: int) -> list[TextLine]:
        page = self._doc[pno]
        to_display = page.rotation_matrix
        lines = []
        for block in page.get_text("dict")["blocks"]:
            if block.get("type") != 0:
                continue
            for line in block["lines"]:
                # Only text that reads left-to-right *for the viewer* is editable.
                ux, uy = line["dir"]
                dx = ux * to_display.a + uy * to_display.c
                dy = ux * to_display.b + uy * to_display.d
                if dx <= 0 or abs(dy) > 1e-3:
                    continue
                spans = line["spans"]
                first = next((i for i, s in enumerate(spans) if s["text"].strip()), None)
                if first is None:
                    continue
                spans = spans[first:]
                text = "".join(s["text"] for s in spans).rstrip()
                bbox = pymupdf.Rect(spans[0]["bbox"])
                for s in spans:
                    if s["text"].strip():
                        bbox |= pymupdf.Rect(s["bbox"])
                main = max(spans, key=lambda s: len(s["text"].strip()))
                family, bold, italic = fonts.classify(main["font"], main["flags"])
                c = main["color"]
                lines.append(TextLine(
                    page=pno, rect=bbox * to_display, text=text, size=round(main["size"], 1),
                    color=((c >> 16 & 255) / 255, (c >> 8 & 255) / 255, (c & 255) / 255),
                    family=family, bold=bold, italic=italic,
                    origin=pymupdf.Point(spans[0]["origin"]), bbox=bbox,
                ))
        lines.sort(key=lambda l: (round(l.rect.y0), l.rect.x0))
        return lines

    def line_at(self, pno: int, x: float, y: float) -> TextLine | None:
        for line in self.text_lines(pno):
            if pymupdf.Point(x, y) in line.rect:
                return line
        return None

    def replace_line(self, line: TextLine, new_text: str, size: float | None = None) -> None:
        """Replace an existing line of text, keeping its position, color and style."""
        page = self._doc[line.page]
        if any(a.type[0] == pymupdf.PDF_ANNOT_REDACT for a in page.annots()):
            raise PdfError(tr("This page has pending redaction marks; editing text would apply them too. "
                              "Remove those marks first."))
        with self._edit():
            page = self._doc[line.page]
            # Shrink across the text direction (vertically for the viewer) so glyphs
            # of neighbouring lines are not caught.
            r = line.rect
            inset = r.height * 0.25
            area = pymupdf.Rect(r.x0, r.y0 + inset, r.x1, r.y1 - inset) * page.derotation_matrix
            page.add_redact_annot(area, fill=False)
            page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE,
                                  graphics=pymupdf.PDF_REDACT_LINE_ART_NONE)
            if new_text.strip():
                page.insert_text(line.origin, new_text, fontsize=size or line.size, color=line.color,
                                 rotate=page.rotation, **fonts.font_args(line.family, line.bold, line.italic))
                fonts.fix_space_mapping(self._doc, page)

    def add_text(self, pno: int, x: float, y: float, text: str, size: float = 12,
                 color=(0, 0, 0), family: str = "sans", bold: bool = False, italic: bool = False) -> None:
        """Write text with its top-left corner at (x, y), wrapping at the right page margin."""
        if not text.strip():
            return
        page = self._doc[pno]
        disp = page.rect
        right = max(disp.x1 - 18, x + 4 * size)
        box = pymupdf.Rect(x, y, right, disp.y1) * page.derotation_matrix
        with self._edit():
            page = self._doc[pno]
            rc = page.insert_textbox(box, text, fontsize=size, color=color, rotate=page.rotation,
                                     **fonts.font_args(family, bold, italic))
            if rc < 0:
                raise PdfError(tr("The text does not fit on the page. Choose a smaller size or a higher position."))
            fonts.fix_space_mapping(self._doc, page)

    # ---- images & annotations ----------------------------------------------

    def add_image(self, pno: int, rect: pymupdf.Rect, data: bytes) -> None:
        try:
            pymupdf.Pixmap(data)
        except Exception as e:
            raise PdfError(tr("The image file could not be read.")) from e
        page = self._doc[pno]
        box = pymupdf.Rect(rect) * page.derotation_matrix
        with self._edit():
            self._doc[pno].insert_image(box, stream=data, keep_proportion=True, rotate=page.rotation)

    def add_highlight(self, pno: int, rect: pymupdf.Rect, color=(1, 0.9, 0)) -> None:
        """Highlight the words under `rect` (line by line), or the area itself if it has no text."""
        page = self._doc[pno]
        area = pymupdf.Rect(rect)
        if area.is_empty:
            return
        to_display, to_page = page.rotation_matrix, page.derotation_matrix
        # Work in display space so each quad's corners follow the text direction
        # the viewer sees; MuPDF draws highlights relative to that orientation.
        lines: dict[tuple[int, int], pymupdf.Rect] = {}
        for x0, y0, x1, y1, _w, b, ln, _n in page.get_text("words"):
            word = pymupdf.Rect(x0, y0, x1, y1) * to_display
            overlap = word & area
            if overlap.is_empty or overlap.get_area() < 0.5 * word.get_area():
                continue
            key = (b, ln)
            lines[key] = lines[key] | word if key in lines else word
        quads = [r.quad * to_page for r in lines.values()] or [area.quad * to_page]
        with self._edit():
            page = self._doc[pno]  # keep a reference: annotations only weakly reference their page
            annot = page.add_highlight_annot(quads=quads)
            annot.set_colors(stroke=color)
            annot.update()

    def add_ink(self, pno: int, strokes: list[list[tuple[float, float]]], color=(0, 0, 0), width: float = 2) -> None:
        page = self._doc[pno]
        m = page.derotation_matrix
        paths = []
        for stroke in strokes:
            pts = [tuple(pymupdf.Point(x, y) * m) for x, y in stroke]
            if len(pts) == 1:
                pts.append((pts[0][0] + 0.5, pts[0][1] + 0.5))
            if pts:
                paths.append(pts)
        if not paths:
            return
        with self._edit():
            page = self._doc[pno]
            annot = page.add_ink_annot(paths)
            annot.set_colors(stroke=color)
            annot.set_border(width=width)
            annot.update()

    def _annot_xref_at(self, pno: int, x: float, y: float) -> int | None:
        page = self._doc[pno]
        p = pymupdf.Point(x, y) * page.derotation_matrix
        hit = None
        for a in page.annots():
            if a.type[0] in _SKIP_ANNOTS:
                continue
            if p in a.rect + (-3, -3, 3, 3):
                hit = a.xref  # last match = topmost
        return hit

    def annot_rect_at(self, pno: int, x: float, y: float) -> pymupdf.Rect | None:
        xref = self._annot_xref_at(pno, x, y)
        if xref is None:
            return None
        page = self._doc[pno]
        return page.load_annot(xref).rect * page.rotation_matrix

    def delete_annot_at(self, pno: int, x: float, y: float) -> bool:
        xref = self._annot_xref_at(pno, x, y)
        if xref is None:
            return False
        with self._edit():
            page = self._doc[pno]
            page.delete_annot(page.load_annot(xref))
        return True

    # ---- forms -------------------------------------------------------------

    def form_fields(self) -> list[FormField]:
        found: dict[str, FormField] = {}
        for page in self._doc:
            for w in page.widgets():
                name, t = w.field_name, w.field_type
                readonly = bool(w.field_flags & pymupdf.PDF_FIELD_IS_READ_ONLY)
                if t == pymupdf.PDF_WIDGET_TYPE_RADIOBUTTON:
                    f = found.setdefault(name, FormField(name, "radio", None, page.number, [], readonly))
                    on = w.on_state()
                    if on not in f.choices:
                        f.choices.append(on)
                    if w.field_value not in (False, None, "", "Off"):
                        f.value = on
                    continue
                if name in found:
                    continue
                if t == pymupdf.PDF_WIDGET_TYPE_TEXT:
                    f = FormField(name, "text", w.field_value or "", page.number, readonly=readonly)
                elif t == pymupdf.PDF_WIDGET_TYPE_CHECKBOX:
                    f = FormField(name, "checkbox", w.field_value not in (False, None, "", "Off"),
                                  page.number, readonly=readonly)
                elif t in (pymupdf.PDF_WIDGET_TYPE_COMBOBOX, pymupdf.PDF_WIDGET_TYPE_LISTBOX):
                    choices = [c[0] if isinstance(c, (list, tuple)) else c for c in (w.choice_values or [])]
                    f = FormField(name, "choice", w.field_value or "", page.number, choices, readonly)
                else:
                    continue  # push buttons and signature fields are not filled here
                found[name] = f
        return list(found.values())

    def set_form_values(self, values: dict[str, object]) -> bool:
        current = {f.name: f.value for f in self.form_fields()}
        changed = {k: v for k, v in values.items() if k in current and current[k] != v}
        if not changed:
            return False
        with self._edit():
            for page in self._doc:
                for w in page.widgets():
                    if w.field_name not in changed:
                        continue
                    v = changed[w.field_name]
                    t = w.field_type
                    if t == pymupdf.PDF_WIDGET_TYPE_CHECKBOX:
                        w.field_value = w.on_state() if v else "Off"
                    elif t == pymupdf.PDF_WIDGET_TYPE_RADIOBUTTON:
                        w.field_value = w.on_state() if w.on_state() == v else "Off"
                    else:
                        w.field_value = "" if v is None else str(v)
                        if not w.text_fontsize:
                            w.text_fontsize = _auto_font_size(w)
                    w.update()
                    if t == pymupdf.PDF_WIDGET_TYPE_TEXT:
                        _fix_text_field_appearance(self._doc, w)
        return True
