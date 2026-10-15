"""PDF document model; every edit goes through here.

Coordinates in the public API are *display* coordinates: PDF points with the
origin at the top-left of the page as the user sees it (after /Rotate is
applied). MuPDF extracts and inserts in unrotated page space, so each method
converts with the page's (de)rotation matrix.
"""
from __future__ import annotations

import datetime
import math
import os
import re
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass, field

import pymupdf

from ..i18n import fmt_date, tr
from . import fonts, richtext
from .richtext import TextRun, TextStyle

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


def _fit_font(box: pymupdf.Rect, multiline: bool) -> float:
    """Concrete font size for a new field of this size."""
    return 10.0 if multiline else round(max(6.0, min(12.0, (min(box.width, box.height) - 4) * 0.8)), 1)


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
    runs: list[TextRun] = field(default_factory=list)  # the line with its styles
    base: pymupdf.Point | None = None  # display baseline start


@dataclass
class TextBlock:
    page: int
    rect: pymupdf.Rect  # display coordinates
    text: str  # the paragraph as one string; hard line breaks are not kept
    size: float
    color: tuple[float, float, float]
    family: str
    bold: bool
    italic: bool
    line_rects: list[pymupdf.Rect]  # display coordinates
    line_height: float  # baseline distance as a multiple of the font size
    runs: list[TextRun] = field(default_factory=list)  # the paragraph with its styles
    align: str = "left"
    left: float = 0.0  # display x of the text box
    width: float = 0.0  # wrapping width of the text box
    first_baseline: float = 0.0  # display y

@dataclass
class FormField:
    name: str
    kind: str  # "text" | "checkbox" | "radio" | "choice"
    value: object
    page: int
    choices: list[str] = field(default_factory=list)
    readonly: bool = False


@dataclass
class SearchHit:
    page: int
    rect: pymupdf.Rect  # display coordinates


@dataclass
class Bookmark:
    level: int  # 1 = top level
    title: str
    page: int  # 0-based; -1 if the bookmark points nowhere in this document


_UNSET = object()

_MOVABLE = {"Square", "Circle", "Line", "Ink", "Stamp", "Text", "FreeText"}
_RESIZABLE = _MOVABLE - {"Text"}  # a sticky note is an icon
_FILLABLE = {"Square", "Circle"}
_BORDERED = {"Square", "Circle", "Line", "Ink", "Polygon", "PolyLine"}


@dataclass
class PageObject:
    """Something the select tool can pick: an annotation, form field, image or paragraph."""
    page: int
    kind: str  # "annot" | "widget" | "image" | "text"
    xref: int  # -1 for text
    subtype: str  # annotation subtype ("Square", "Line", ...), widget type, "Image" or "Text"
    rect: pymupdf.Rect  # display coordinates
    movable: bool
    resizable: bool
    stroke: tuple | None = None
    fill: tuple | None = None
    width: float | None = None
    dashed: bool = False
    opacity: float = 1.0
    line: tuple[pymupdf.Point, pymupdf.Point] | None = None  # display endpoints of a line
    block: "TextBlock | None" = None

    @property
    def styleable(self) -> bool:
        return self.kind in ("annot", "text")


def _dashes(width: float) -> list[int]:
    # Integers: PyMuPDF silently ignores a dash array of floats.
    return [max(3, round(width * 3)), max(2, round(width * 2))]


# Private annotation key holding the color of stamps made by this app, so they can be redrawn.
_STAMP_COLOR_KEY = "LeafpenStampColor"

_KEEP = pymupdf.PDF_ENCRYPT_KEEP
_SKIP_ANNOTS = (pymupdf.PDF_ANNOT_POPUP, pymupdf.PDF_ANNOT_LINK, pymupdf.PDF_ANNOT_WIDGET)

NOTE_ICONS = ("Note", "Comment", "Help", "Key", "Insert", "Paragraph", "NewParagraph")

FIELD_KINDS = ("text", "multiline", "checkbox", "combobox", "listbox")
_WIDGET_TYPES = {
    "text": pymupdf.PDF_WIDGET_TYPE_TEXT,
    "multiline": pymupdf.PDF_WIDGET_TYPE_TEXT,
    "checkbox": pymupdf.PDF_WIDGET_TYPE_CHECKBOX,
    "combobox": pymupdf.PDF_WIDGET_TYPE_COMBOBOX,
    "listbox": pymupdf.PDF_WIDGET_TYPE_LISTBOX,
}

# Header/footer slots: (vertical position, horizontal alignment)
HF_SLOTS = ("header_left", "header_center", "header_right", "footer_left", "footer_center", "footer_right")
_ALIGN = {"left": pymupdf.TEXT_ALIGN_LEFT, "center": pymupdf.TEXT_ALIGN_CENTER, "right": pymupdf.TEXT_ALIGN_RIGHT}

# Image settings for "reduce file size": (images above this dpi..., are resampled to this dpi, JPEG quality)
COMPRESSION_LEVELS = {"high": (300, 200, 85), "medium": (225, 150, 75), "low": (150, 96, 60)}


def _dominant_style(spans: list[dict]) -> tuple[float, tuple[float, float, float], str, bool, bool]:
    main = max(spans, key=lambda s: len(s["text"].strip()))
    family, bold, italic = fonts.classify(main["font"], main["flags"])
    c = main["color"]
    return (round(main["size"], 1), ((c >> 16 & 255) / 255, (c >> 8 & 255) / 255, (c & 255) / 255),
            family, bold, italic)


def _fold_char(c: str) -> str:
    if c in "İIıi":
        return "i"  # Turkish and English dotted/dotless i all match each other
    if c.isspace():
        return " "
    low = c.lower()
    return low if len(low) == 1 else c


def _fold(text: str) -> str:
    """Case-fold one character at a time, so indexes stay aligned with the original text."""
    return "".join(_fold_char(c) for c in text)


def _span_style(span: dict) -> TextStyle:
    family, bold, italic = fonts.classify(span["font"], span["flags"])
    c = span["color"]
    return TextStyle(family, bold, italic, round(span["size"], 1),
                     ((c >> 16 & 255) / 255, (c >> 8 & 255) / 255, (c & 255) / 255))


def _span_runs(spans: list[dict]) -> list[TextRun]:
    return richtext.strip([TextRun(s["text"], _span_style(s)) for s in spans])


def _join_line_runs(lines: list[list[TextRun]]) -> list[TextRun]:
    """Join the styled lines of a paragraph, undoing hyphenation at line ends."""
    out: list[TextRun] = []
    for runs in lines:
        runs = richtext.strip(runs)
        if not runs:
            continue
        if out:
            prev = out[-1].text
            if prev.endswith("-") and len(prev) > 1 and prev[-2].isalpha() and runs[0].text[:1].islower():
                out[-1] = TextRun(prev[:-1], out[-1].style)
            else:
                out[-1] = TextRun(prev + " ", out[-1].style)
        out.extend(runs)
    return richtext.normalize(out)


def _join_lines(lines: list[str]) -> str:
    """Join the lines of a paragraph, undoing hyphenation at line ends."""
    out = ""
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if not out:
            out = line
        elif out.endswith("-") and len(out) > 1 and out[-2].isalpha() and line[:1].islower():
            out = out[:-1] + line
        else:
            out += " " + line
    return out


def _stamp_pdf(text: str, color: tuple[float, float, float], width: float, height: float) -> pymupdf.Document:
    """A one-page PDF showing a rubber stamp: rounded frame with bold text."""
    doc = pymupdf.open()
    page = doc.new_page(width=width, height=height)
    lw = max(1.5, min(width, height) * 0.06)
    frame = pymupdf.Rect(lw, lw, width - lw, height - lw)
    page.draw_rect(frame, color=color, width=lw, radius=0.12)
    font = fonts.font_args("sans", bold=True)
    inner = frame + (lw * 1.5, lw, -lw * 1.5, -lw)
    size = inner.height * 0.62
    path = fonts.font_file("sans", True)
    measure = pymupdf.Font(fontfile=path) if path else pymupdf.Font("helv")
    size = min(size, inner.width / max(measure.text_length(text, fontsize=1), 1e-3))
    base = pymupdf.Point(inner.x0 + (inner.width - measure.text_length(text, fontsize=size)) / 2,
                         inner.y0 + inner.height / 2 + size * 0.35)
    page.insert_text(base, text, fontsize=size, color=color, **font)
    return doc


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
        self.move_pages([src], dst if dst < src else dst + 1)

    def move_pages(self, pnos: list[int], to: int) -> list[int]:
        """Move pages so they end up, in their current order, before the page now at index `to`
        (`to == page_count` appends). Returns their new indexes. Bookmarks, links, annotations
        and form fields move with their pages."""
        n = self.page_count
        moving = sorted(set(p for p in pnos if 0 <= p < n))
        if not moving:
            return []
        rest = [p for p in range(n) if p not in moving]
        at = sum(1 for p in rest if p < to)
        order = rest[:at] + moving + rest[at:]
        if order != list(range(n)):
            with self._edit():
                self._doc.select(order)
        return list(range(at, at + len(moving)))

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
                size, color, family, bold, italic = _dominant_style(spans)
                origin = pymupdf.Point(spans[0]["origin"])
                lines.append(TextLine(
                    page=pno, rect=bbox * to_display, text=text, size=size, color=color,
                    family=family, bold=bold, italic=italic, origin=origin, bbox=bbox,
                    runs=_span_runs(spans), base=origin * to_display,
                ))
        lines.sort(key=lambda l: (round(l.rect.y0), l.rect.x0))
        return lines

    def text_blocks(self, pno: int) -> list[TextBlock]:
        """Paragraphs whose lines all read left-to-right for the viewer.

        Starts from MuPDF's text blocks, then joins blocks that continue each other:
        many PDF generators (and every rotated page) put each line in its own block.
        """
        page = self._doc[pno]
        to_display = page.rotation_matrix
        groups: list[list[dict]] = []
        for block in page.get_text("dict")["blocks"]:
            if block.get("type") != 0:
                continue
            lines, ok = [], True
            for line in block["lines"]:
                ux, uy = line["dir"]
                if ux * to_display.a + uy * to_display.c <= 0 or abs(ux * to_display.b + uy * to_display.d) > 1e-3:
                    ok = False
                    break
                spans = [s for s in line["spans"] if s["text"].strip()]
                if not spans:
                    continue
                r = pymupdf.Rect(spans[0]["bbox"])
                for s in spans:
                    r |= pymupdf.Rect(s["bbox"])
                size, _color, family, bold, italic = _dominant_style(spans)
                lines.append({"text": "".join(s["text"] for s in line["spans"]), "rect": r * to_display,
                              "base": pymupdf.Point(spans[0]["origin"]) * to_display, "spans": spans,
                              "all": line["spans"], "size": size, "style": (family, bold, italic)})
            if ok and lines:
                groups.append(lines)
        groups = self._join_groups(groups)

        blocks = []
        for lines in groups:
            size, color, family, bold, italic = _dominant_style([s for l in lines for s in l["spans"]])
            rects = [l["rect"] for l in lines]
            rect = pymupdf.Rect(rects[0])
            for r in rects[1:]:
                rect |= r
            gaps = [b["base"].y - a["base"].y for a, b in zip(lines, lines[1:]) if b["base"].y > a["base"].y]
            line_height = (sum(gaps) / len(gaps) / size) if gaps and size else 1.2
            align = richtext.detect_align(rects, size)
            # Wrapping width: wide enough for every original line (+ a hair), so unchanged text
            # breaks at the same places.
            widest = max(r.width for r in rects)
            width = (rect.width if align == "justify" else widest) + 0.5
            left = {"center": (rect.x0 + rect.x1 - width) / 2, "right": rect.x1 - width}.get(align, rect.x0)
            blocks.append(TextBlock(pno, rect, _join_lines([l["text"] for l in lines]), size, color, family,
                                    bold, italic, rects, max(1.0, min(line_height, 2.5)),
                                    runs=_join_line_runs([_span_runs(l["all"]) for l in lines]), align=align,
                                    left=left, width=width, first_baseline=lines[0]["base"].y))
        blocks.sort(key=lambda b: (round(b.rect.y0), b.rect.x0))
        return blocks

    @staticmethod
    def _join_groups(groups: list[list[dict]]) -> list[list[dict]]:
        """Join line groups that read as one paragraph: same style, stacked at the paragraph's line spacing,
        starting at about the same x (a first-line indent is allowed)."""

        def spacing(g: list[dict]) -> float | None:
            gaps = [b["base"].y - a["base"].y for a, b in zip(g, g[1:])]
            return sum(gaps) / len(gaps) if gaps else None

        groups = sorted(groups, key=lambda g: (g[0]["base"].y, g[0]["rect"].x0))
        out: list[list[dict]] = []
        for g in groups:
            first = g[0]
            r, size = first["rect"], first["size"]
            for p in out:
                last = p[-1]
                lr = last["rect"]
                gap = first["base"].y - last["base"].y
                overlap = min(r.x1, lr.x1) - max(r.x0, lr.x0)
                tol = max(1.5, size * 0.15)
                aligned = (abs(r.x0 - lr.x0) <= 2 * size  # left (a first-line indent is allowed)
                           or abs((r.x0 + r.x1) - (lr.x0 + lr.x1)) / 2 <= tol  # centered
                           or abs(r.x1 - lr.x1) <= tol)  # right
                if not (0 < gap <= 1.8 * size and abs(last["size"] - size) <= 0.15 * size
                        and last["style"] == first["style"]
                        and aligned and overlap > 0.3 * min(r.width, lr.width)):
                    continue
                # A larger gap than the lines already have marks a new paragraph.
                if any(s is not None and gap > 1.2 * s for s in (spacing(p), spacing(g))):
                    continue
                p.extend(g)
                break
            else:
                out.append(list(g))
        return out

    def _check_no_pending_redactions(self, pno: int) -> None:
        if any(True for _ in self._doc[pno].annots(types=[pymupdf.PDF_ANNOT_REDACT])):
            raise PdfError(tr("This page has pending redaction marks; editing text would apply them too. "
                              "Remove those marks first."))

    @staticmethod
    def _erase_text(page: pymupdf.Page, rects: list[pymupdf.Rect]) -> None:
        """Remove the text in these display rects (shrunk vertically so neighbouring lines survive)."""
        for r in rects:
            inset = r.height * 0.25
            page.add_redact_annot(pymupdf.Rect(r.x0, r.y0 + inset, r.x1, r.y1 - inset) * page.derotation_matrix,
                                  fill=False)
        page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE, graphics=pymupdf.PDF_REDACT_LINE_ART_NONE)

    def _write_runs(self, page: pymupdf.Page, runs: list[TextRun], left: float, first_baseline: float,
                    width: float, align: str, line_height: float, too_long: str) -> pymupdf.Rect:
        """Lay out and write styled text; returns the display rect it occupies."""
        lines = richtext.layout(runs, width, align, line_height)
        top = first_baseline - lines[0].ascent
        rect = pymupdf.Rect(left, top, left + width, top + richtext.height(lines))
        ink = [(left + f.x, left + f.x + richtext.measure(f.text, f.style))
               for line in lines for f in line.fragments if f.text.strip()]
        outside_x = ink and (min(a for a, _ in ink) < -0.5 or max(b for _, b in ink) > page.rect.width + 0.5)
        if rect.y1 > page.rect.height + 0.5 or rect.y0 < -0.5 or outside_x:
            raise PdfError(too_long)
        m = page.derotation_matrix
        for line in lines:
            y = first_baseline + line.baseline
            for frag in line.fragments:
                if not frag.text.strip():
                    continue
                st = frag.style
                page.insert_text(pymupdf.Point(left + frag.x, y) * m, frag.text, fontsize=st.size, color=st.color,
                                 rotate=page.rotation, **fonts.font_args(st.family, st.bold, st.italic))
        fonts.fix_space_mapping(self._doc, page)
        if align == "left":  # the text box is as wide as the page allows; report what is used
            rect.x1 = left + max(l.width for l in lines)
        return rect

    @staticmethod
    def _as_runs(content: str | list[TextRun], style: TextStyle) -> list[TextRun]:
        if isinstance(content, str):
            return richtext.strip([TextRun(content, style)])
        return richtext.strip(list(content))

    def replace_block(self, block: TextBlock, content: str | list[TextRun], size: float | None = None,
                      align: str | None = None, line_height: float | None = None,
                      width: float | None = None) -> bool:
        """Rewrite a paragraph, re-flowing it inside the paragraph's box.

        `content` is plain text (written in the paragraph's main style, at `size` if given) or
        styled runs. The paragraph keeps its position and may grow downwards if the new text is
        longer. Returns True if it now overlaps other text below it.
        """
        self._check_no_pending_redactions(block.page)
        style = TextStyle(block.family, block.bold, block.italic, size or block.size, block.color)
        runs = self._as_runs(content, style)
        others = [b.rect for b in self.text_blocks(block.page) if not b.rect.intersects(block.rect)]
        with self._edit():
            page = self._doc[block.page]
            self._erase_text(page, block.line_rects)
            if not runs:
                return False
            align = align or block.align
            box_width = width or block.width
            left = block.left
            if width and align in ("center", "right"):  # keep the paragraph's anchor
                anchor = block.left + block.width / (2 if align == "center" else 1)
                left = anchor - box_width / (2 if align == "center" else 1)
            rect = self._write_runs(page, runs, left, block.first_baseline, box_width, align,
                                    line_height or block.line_height,
                                    tr("The paragraph does not fit on the page. Shorten the text or choose a "
                                       "smaller size."))
        return any(rect.intersects(o) for o in others)

    def block_at(self, pno: int, x: float, y: float) -> TextBlock | None:
        p = pymupdf.Point(x, y)
        return next((b for b in self.text_blocks(pno) if p in b.rect), None)

    # ---- search --------------------------------------------------------------

    def search(self, query: str) -> list[SearchHit]:
        """Case-insensitive search across all pages, in reading order.

        Matching is done here rather than with MuPDF's search, which folds only
        ASCII case: "ikinci" must find "İKİNCİ" and "Ikinci" as well.
        """
        needle = _fold(" ".join(query.split()))
        if not needle:
            return []
        hits = []
        for page in self._doc:
            to_display = page.rotation_matrix
            found = []
            for block in page.get_text("rawdict")["blocks"]:
                for line in block.get("lines", ()):
                    chars = [c for s in line["spans"] for c in s["chars"]]
                    hay = _fold("".join(c["c"] for c in chars))
                    start = hay.find(needle)
                    while start >= 0:
                        r = pymupdf.Rect(chars[start]["bbox"])
                        for c in chars[start + 1:start + len(needle)]:
                            r |= pymupdf.Rect(c["bbox"])
                        found.append(r * to_display)
                        start = hay.find(needle, start + len(needle))
            found.sort(key=lambda r: (round(r.y0), r.x0))
            hits.extend(SearchHit(page.number, r) for r in found)
        return hits

    # ---- redaction -----------------------------------------------------------

    def mark_redactions(self, areas: list[tuple[int, pymupdf.Rect]]) -> int:
        """Mark areas (page, display rect) for redaction. Nothing is removed until `apply_redactions`."""
        areas = [(pno, pymupdf.Rect(r)) for pno, r in areas if not pymupdf.Rect(r).is_empty]
        if not areas:
            return 0
        with self._edit():
            pages = {}
            for pno, r in areas:
                page = pages.setdefault(pno, self._doc[pno])
                annot = page.add_redact_annot(r * page.derotation_matrix, fill=(0, 0, 0))
                annot.set_colors(stroke=(0.85, 0.1, 0.1))
                annot.update()
        return len(areas)

    def redaction_count(self) -> int:
        return sum(1 for page in self._doc for a in page.annots(types=[pymupdf.PDF_ANNOT_REDACT]))

    def apply_redactions(self) -> int:
        """Permanently remove everything under the redaction marks. Returns the number of marks applied."""
        count = self.redaction_count()
        if not count:
            return 0
        with self._edit():
            for page in self._doc:
                if any(True for _ in page.annots(types=[pymupdf.PDF_ANNOT_REDACT])):
                    page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_PIXELS,
                                          graphics=pymupdf.PDF_REDACT_LINE_ART_REMOVE_IF_TOUCHED,
                                          text=pymupdf.PDF_REDACT_TEXT_REMOVE)
        return count

    # ---- bookmarks -----------------------------------------------------------

    def bookmarks(self) -> list[Bookmark]:
        return [Bookmark(lvl, title, page - 1) for lvl, title, page, *_ in self._doc.get_toc(simple=False)]

    def _set_toc(self, toc: list) -> None:
        with self._edit():
            self._doc.set_toc(toc)

    def add_bookmark(self, title: str, pno: int, after: int | None = None) -> int:
        """Insert a bookmark after entry `after` (same level), or at the end. Returns its index."""
        title = title.strip()
        if not title:
            raise PdfError(tr("A bookmark needs a title."))
        toc = self._doc.get_toc(simple=False)
        if after is None or not (0 <= after < len(toc)):
            index, level = len(toc), 1
        else:
            level = toc[after][0]
            index = after + 1
            while index < len(toc) and toc[index][0] > level:  # skip the children of `after`
                index += 1
        toc.insert(index, [level, title, pno + 1])
        self._set_toc(toc)
        return index

    def rename_bookmark(self, index: int, title: str) -> None:
        title = title.strip()
        if not title:
            raise PdfError(tr("A bookmark needs a title."))
        toc = self._doc.get_toc(simple=False)
        toc[index][1] = title
        self._set_toc(toc)

    def delete_bookmark(self, index: int) -> None:
        """Delete a bookmark and its children."""
        toc = self._doc.get_toc(simple=False)
        level = toc[index][0]
        end = index + 1
        while end < len(toc) and toc[end][0] > level:
            end += 1
        del toc[index:end]
        self._set_toc(toc)

    # ---- page layout -----------------------------------------------------------

    def crop_pages(self, pnos: list[int], rect: pymupdf.Rect) -> None:
        """Crop pages to `rect` (display coordinates of the visible page)."""
        rect = pymupdf.Rect(rect)
        if rect.width < 10 or rect.height < 10:
            raise PdfError(tr("The crop area is too small."))
        with self._edit():
            for pno in sorted(set(pnos)):
                page = self._doc[pno]
                crop = page.cropbox
                area = rect * page.derotation_matrix + (crop.x0, crop.y0, crop.x0, crop.y0)
                area &= page.mediabox
                if area.width < 10 or area.height < 10:
                    raise PdfError(tr("The crop area lies outside page {number}.", number=pno + 1))
                page.set_cropbox(area)

    def reset_crop(self, pnos: list[int]) -> None:
        with self._edit():
            for pno in sorted(set(pnos)):
                page = self._doc[pno]
                page.set_cropbox(page.mediabox)

    def add_watermark(self, pnos: list[int], text: str, size: float = 60, color=(0.6, 0.6, 0.6),
                      opacity: float = 0.3, angle: float = 45, behind: bool = False) -> None:
        """Write `text` centred on each page, rotated `angle` degrees counter-clockwise for the viewer."""
        text = " ".join(text.split())
        if not text:
            raise PdfError(tr("Enter the watermark text."))
        args = fonts.font_args("sans", bold=True)
        path = fonts.font_file("sans", True)
        measure = pymupdf.Font(fontfile=path) if path else pymupdf.Font("helv")
        with self._edit():
            for pno in sorted(set(pnos)):
                page = self._doc[pno]
                disp = page.rect
                m = page.derotation_matrix
                # Fit the text inside the page along its direction.
                fit = min(disp.width, disp.height) * 1.2 / max(measure.text_length(text, fontsize=1), 1e-3)
                fs = min(size, fit)
                width = measure.text_length(text, fontsize=fs)
                rad = math.radians(angle)
                d = pymupdf.Point(math.cos(rad), -math.sin(rad)) * m - pymupdf.Point(0, 0) * m
                ang = math.degrees(math.atan2(d.y, d.x))  # direction in unrotated page space
                center = pymupdf.Point(disp.width / 2, disp.height / 2) * m
                start = pymupdf.Point(center.x - width / 2, center.y + fs * 0.35)
                page.insert_text(start, text, fontsize=fs, color=color, fill_opacity=opacity,
                                 morph=(center, pymupdf.Matrix(1, 0, 0, 1, 0, 0).prerotate(-ang)),
                                 overlay=not behind, **args)
                fonts.fix_space_mapping(self._doc, page)

    def add_header_footer(self, pnos: list[int], texts: dict[str, str], size: float = 9,
                          color=(0, 0, 0), margin: float = 24, family: str = "sans") -> None:
        """Write header/footer text. Slots are `HF_SLOTS`; `{page}`, `{pages}` and `{date}` are replaced."""
        texts = {k: v for k, v in texts.items() if k in HF_SLOTS and v.strip()}
        if not texts:
            raise PdfError(tr("Enter at least one header or footer text."))
        today = fmt_date(datetime.date.today())
        total = self.page_count
        args = fonts.font_args(family)
        with self._edit():
            for pno in sorted(set(pnos)):
                page = self._doc[pno]
                disp = page.rect
                for slot, raw in texts.items():
                    where, align = slot.split("_")
                    value = raw.replace("{page}", str(pno + 1)).replace("{pages}", str(total)).replace("{date}", today)
                    height = size * 1.6
                    if where == "header":
                        box = pymupdf.Rect(margin, margin, disp.width - margin, margin + height)
                    else:
                        box = pymupdf.Rect(margin, disp.height - margin - height, disp.width - margin,
                                           disp.height - margin)
                    rc = page.insert_textbox(box * page.derotation_matrix, value, fontsize=size, color=color,
                                             align=_ALIGN[align], rotate=page.rotation, **args)
                    if rc < 0:
                        raise PdfError(tr("The header or footer text does not fit on page {number}.",
                                          number=pno + 1))
                fonts.fix_space_mapping(self._doc, page)

    def line_at(self, pno: int, x: float, y: float) -> TextLine | None:
        for line in self.text_lines(pno):
            if pymupdf.Point(x, y) in line.rect:
                return line
        return None

    def replace_line(self, line: TextLine, content: str | list[TextRun], size: float | None = None) -> None:
        """Replace an existing line of text, keeping its position (and its color and style for plain text)."""
        self._check_no_pending_redactions(line.page)
        runs = self._as_runs(content, TextStyle(line.family, line.bold, line.italic, size or line.size, line.color))
        runs = [TextRun(" ".join(r.text.splitlines()), r.style) for r in runs]  # a line has no breaks
        with self._edit():
            page = self._doc[line.page]
            self._erase_text(page, [line.rect])
            if runs:
                base = line.base if line.base is not None else line.origin * page.rotation_matrix
                self._write_runs(page, runs, base.x, base.y, 1e6, "left", 1.2,
                                 tr("The text does not fit on the page. Choose a smaller size or a "
                                    "higher position."))

    def default_text_width(self, pno: int, x: float, size: float = 12) -> float:
        """Width of a new text box at x: up to the right page margin."""
        return max(self._doc[pno].rect.width - 18 - x, 4 * size)

    def add_text(self, pno: int, x: float, y: float, content: str | list[TextRun], size: float = 12,
                 color=(0, 0, 0), family: str = "sans", bold: bool = False, italic: bool = False,
                 align: str = "left", line_height: float = 1.2, width: float | None = None) -> pymupdf.Rect | None:
        """Write text with its top-left corner at (x, y), wrapping at `width` (default: the right page margin).

        `content` is plain text in the given style, or styled runs. Returns the display rect written.
        """
        runs = self._as_runs(content, TextStyle(family, bold, italic, size, tuple(color)))
        if not runs:
            return None
        width = width or self.default_text_width(pno, x, max(r.style.size for r in runs))
        first = richtext.layout(runs, width, align, line_height)[0]
        with self._edit():
            return self._write_runs(self._doc[pno], runs, x, y + first.ascent, width, align, line_height,
                                    tr("The text does not fit on the page. Choose a smaller size or a "
                                       "higher position."))

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

    def add_ink(self, pno: int, strokes: list[list[tuple[float, float]]], color=(0, 0, 0), width: float = 2,
                opacity: float = 1.0) -> None:
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
            self._annot_style(annot, color, width, opacity=opacity)

    @staticmethod
    def _annot_style(annot: pymupdf.Annot, color, width: float | None = None, fill=None, dashed: bool = False,
                     opacity: float = 1.0) -> None:
        annot.set_colors(stroke=color, fill=fill if fill is not None else [])
        if width is not None:
            annot.set_border(width=width, dashes=_dashes(width) if dashed else [])
        annot.set_opacity(opacity)
        annot.update()

    def add_shape(self, pno: int, kind: str, rect: pymupdf.Rect, color=(0, 0, 0), width: float = 2,
                  fill=None, dashed: bool = False, opacity: float = 1.0) -> None:
        """Rectangle (`kind="rect"`) or ellipse (`kind="ellipse"`); `fill` None means no fill."""
        rect = pymupdf.Rect(rect)
        if rect.width < 2 or rect.height < 2:
            return
        with self._edit():
            page = self._doc[pno]
            box = rect * page.derotation_matrix
            annot = page.add_rect_annot(box) if kind == "rect" else page.add_circle_annot(box)
            self._annot_style(annot, color, width, fill, dashed, opacity)

    def add_line(self, pno: int, start: tuple[float, float], end: tuple[float, float], color=(0, 0, 0),
                 width: float = 2, arrow: bool = False, dashed: bool = False, opacity: float = 1.0) -> None:
        a, b = pymupdf.Point(start), pymupdf.Point(end)
        if abs(b - a) < 2:
            return
        with self._edit():
            page = self._doc[pno]
            m = page.derotation_matrix
            annot = page.add_line_annot(a * m, b * m)
            if arrow:
                annot.set_line_ends(pymupdf.PDF_ANNOT_LE_NONE, pymupdf.PDF_ANNOT_LE_OPEN_ARROW)
            self._annot_style(annot, color, width, dashed=dashed, opacity=opacity)

    def add_note(self, pno: int, x: float, y: float, text: str, color=(1, 0.85, 0.2), icon: str = "Note") -> None:
        """Sticky note: an icon (one of `NOTE_ICONS`) whose text viewers show in a pop-up."""
        if not text.strip():
            return
        if icon not in NOTE_ICONS:
            raise ValueError(icon)
        with self._edit():
            page = self._doc[pno]
            annot = page.add_text_annot(pymupdf.Point(x, y) * page.derotation_matrix, text, icon=icon)
            annot.set_colors(stroke=color)
            annot.update()

    def note_at(self, pno: int, x: float, y: float) -> tuple[int, str] | None:
        """(xref, text) of the sticky note under the point, if any."""
        xref = self._annot_xref_at(pno, x, y)
        if xref is None:
            return None
        page = self._doc[pno]  # keep a reference: annotations only weakly reference their page
        annot = page.load_annot(xref)
        if annot.type[0] != pymupdf.PDF_ANNOT_TEXT:
            return None
        return xref, annot.info.get("content", "")

    def set_note_text(self, pno: int, xref: int, text: str) -> None:
        with self._edit():
            page = self._doc[pno]
            annot = page.load_annot(xref)
            if text.strip():
                annot.set_info(content=text)
                annot.update()
            else:
                page.delete_annot(annot)

    def add_stamp(self, pno: int, rect: pymupdf.Rect, text: str, color=(0.8, 0.1, 0.1)) -> None:
        """Rubber stamp with any (Unicode) text, drawn upright for the viewer."""
        text = " ".join(text.split())
        if not text:
            return
        with self._edit():
            self._make_stamp(self._doc[pno], pymupdf.Rect(rect), text, color)

    @staticmethod
    def _make_stamp(page: pymupdf.Page, rect: pymupdf.Rect, text: str, color) -> pymupdf.Annot:
        # Draw at display size, then render turned to the page's unrotated orientation.
        stamp = _stamp_pdf(text, color, rect.width, rect.height)
        spage = stamp[0]
        spage.set_rotation((-page.rotation) % 360)
        png = spage.get_pixmap(matrix=pymupdf.Matrix(4, 4), alpha=True).tobytes("png")
        stamp.close()
        annot = page.add_stamp_annot(rect * page.derotation_matrix, stamp=png)
        annot.set_info(content=text)
        annot.update()
        page.parent.xref_set_key(annot.xref, _STAMP_COLOR_KEY, "[%s]" % " ".join(f"{c:.4f}" for c in color))
        return annot

    def _annot_at(self, pno: int, x: float, y: float) -> tuple[str, int] | None:
        """("annot" | "widget", xref) of the topmost removable item under the point."""
        page = self._doc[pno]
        p = pymupdf.Point(x, y) * page.derotation_matrix
        hit = None
        for a in page.annots():
            if a.type[0] in _SKIP_ANNOTS:
                continue
            if p in a.rect + (-3, -3, 3, 3):
                hit = ("annot", a.xref)  # last match = topmost
        if hit is None:
            for w in page.widgets():
                if w.field_type != pymupdf.PDF_WIDGET_TYPE_SIGNATURE and p in w.rect:
                    hit = ("widget", w.xref)
        return hit

    def _annot_xref_at(self, pno: int, x: float, y: float) -> int | None:
        hit = self._annot_at(pno, x, y)
        return hit[1] if hit and hit[0] == "annot" else None

    def annot_rect_at(self, pno: int, x: float, y: float) -> pymupdf.Rect | None:
        hit = self._annot_at(pno, x, y)
        if hit is None:
            return None
        page = self._doc[pno]
        item = page.load_annot(hit[1]) if hit[0] == "annot" else page.load_widget(hit[1])
        return item.rect * page.rotation_matrix

    def delete_annot_at(self, pno: int, x: float, y: float) -> bool:
        """Remove the annotation or form field (never a signature field) under the point."""
        hit = self._annot_at(pno, x, y)
        if hit is None:
            return False
        with self._edit():
            page = self._doc[pno]
            if hit[0] == "annot":
                page.delete_annot(page.load_annot(hit[1]))
            else:
                page.delete_widget(page.load_widget(hit[1]))
        return True

    # ---- objects (select tool) ---------------------------------------------------

    def object_at(self, pno: int, x: float, y: float) -> PageObject | None:
        """The topmost selectable object under a display point: annotation, form field, image or paragraph."""
        page = self._doc[pno]
        to_display = page.rotation_matrix
        p = pymupdf.Point(x, y) * page.derotation_matrix
        hit = None
        for a in page.annots():
            if a.type[0] in _SKIP_ANNOTS:
                continue
            if p in a.rect + (-3, -3, 3, 3):
                hit = a  # last match = topmost
        if hit is not None:
            return self._annot_object(page, hit)
        for w in page.widgets():
            if w.field_type != pymupdf.PDF_WIDGET_TYPE_SIGNATURE and p in w.rect:
                return PageObject(pno, "widget", w.xref, w.field_type_string, w.rect * to_display, True, True)
        image = self._image_at(page, p)
        if image is not None:
            return image
        block = self.block_at(pno, x, y)
        if block is not None:
            return PageObject(pno, "text", -1, "Text", pymupdf.Rect(block.rect), True, True,
                              stroke=block.color, block=block)
        return None

    def _annot_object(self, page: pymupdf.Page, a: pymupdf.Annot) -> PageObject:
        to_display = page.rotation_matrix
        sub = a.type[1]
        colors = a.colors or {}
        border = a.border or {}
        width = border.get("width", -1)
        line = None
        if sub == "Line":
            v = a.vertices
            line = (pymupdf.Point(v[0]) * to_display, pymupdf.Point(v[1]) * to_display)
        opacity = a.opacity if a.opacity is not None and a.opacity >= 0 else 1.0
        stroke = tuple(colors["stroke"]) if colors.get("stroke") else None
        if sub == "Stamp":
            stroke = self._stamp_color(a.xref) or stroke
        return PageObject(page.number, "annot", a.xref, sub, a.rect * to_display,
                          movable=sub in _MOVABLE, resizable=sub in _RESIZABLE,
                          stroke=stroke,
                          fill=tuple(colors["fill"]) if colors.get("fill") else None,
                          width=width if width and width > 0 else None, dashed=bool(border.get("dashes")),
                          opacity=opacity, line=line)

    def _image_at(self, page: pymupdf.Page, p: pymupdf.Point) -> PageObject | None:
        images = page.get_images(full=True)
        hit = None
        for info in page.get_image_info(xrefs=True):
            xref = info["xref"]
            if xref > 0 and any(x[0] == xref for x in images) and p in pymupdf.Rect(info["bbox"]):
                hit = info
        if hit is None:
            return None
        m = pymupdf.Matrix(hit["transform"]) * page.rotation_matrix
        upright = abs(m.b) < 1e-3 and abs(m.c) < 1e-3 and m.a > 0 and m.d > 0
        movable = upright and self._image_uses(page, hit["xref"]) == 1
        return PageObject(page.number, "image", hit["xref"], "Image", pymupdf.Rect(hit["bbox"]) * page.rotation_matrix,
                          movable, movable)

    @staticmethod
    def _image_pattern(page: pymupdf.Page, xref: int) -> re.Pattern | None:
        """Matches the page-level drawing operators of image `xref`, or None if it is drawn inside a form."""
        entries = [x for x in page.get_images(full=True) if x[0] == xref]
        if not entries or any(x[9] != 0 for x in entries):
            return None
        names = b"|".join(re.escape(x[7].encode()) for x in entries)
        return re.compile(rb"/(?:" + names + rb")\s+Do\b")

    def _image_uses(self, page: pymupdf.Page, xref: int) -> int:
        """How often the page draws image `xref` (all resource names for it together)."""
        pattern = self._image_pattern(page, xref)
        if pattern is None:
            return 0
        content = b"".join(self._doc.xref_stream(x) or b"" for x in page.get_contents())
        return len(pattern.findall(content))

    def _remove_image_use(self, page: pymupdf.Page, xref: int) -> None:
        """Stop drawing image `xref` on this page (the image object itself stays for reuse)."""
        pattern = self._image_pattern(page, xref)
        if pattern is None or self._image_uses(page, xref) != 1:
            raise PdfError(tr("This image cannot be moved or removed."))
        page.clean_contents()
        (cxref,) = page.get_contents()
        stream, count = pattern.subn(b"", self._doc.xref_stream(cxref))
        if count != 1:
            raise PdfError(tr("This image cannot be moved or removed."))
        self._doc.update_stream(cxref, stream)

    @staticmethod
    def _set_annot_rect(annot: pymupdf.Annot, target: pymupdf.Rect) -> None:
        """Set the outer rect to `target` (unrotated); MuPDF grows it by the border on update."""
        annot.set_rect(target)
        annot.update()
        got = annot.rect
        grow = (target.x0 - got.x0, target.y0 - got.y0, got.x1 - target.x1, got.y1 - target.y1)
        if any(abs(g) > 0.01 for g in grow):
            inner = pymupdf.Rect(target.x0 + grow[0], target.y0 + grow[1], target.x1 - grow[2], target.y1 - grow[3])
            if inner.width > 1 and inner.height > 1:
                annot.set_rect(inner)
                annot.update()

    @staticmethod
    def _copy_annot_style(src: pymupdf.Annot, dst: pymupdf.Annot) -> None:
        colors = src.colors or {}
        dst.set_colors(stroke=colors.get("stroke") or [], fill=colors.get("fill") or [])
        border = src.border or {}
        if border.get("width", -1) and border.get("width", -1) > 0:
            dst.set_border(width=border["width"], dashes=list(border.get("dashes") or []))
        if src.opacity is not None and src.opacity >= 0:
            dst.set_opacity(src.opacity)
        info = src.info
        dst.set_info(content=info.get("content", ""), title=info.get("title", ""), subject=info.get("subject", ""))
        if src.type[1] == "Line":
            dst.set_line_ends(*src.line_ends)
        dst.update()

    def transform_object(self, obj: PageObject, rect: pymupdf.Rect,
                         line: tuple[tuple[float, float], tuple[float, float]] | None = None) -> None:
        """Move/resize an object to display rect `rect` (a line: to the endpoints `line`)."""
        if not obj.movable:
            raise PdfError(tr("This object cannot be moved."))
        rect = pymupdf.Rect(rect)
        if not obj.resizable:
            rect = pymupdf.Rect(rect.x0, rect.y0, rect.x0 + obj.rect.width, rect.y0 + obj.rect.height)
        if rect.width < 2 or rect.height < 2:
            raise PdfError(tr("The object would be too small."))
        old = obj.rect

        def remap(pt: pymupdf.Point) -> pymupdf.Point:
            fx = (pt.x - old.x0) / old.width if old.width else 0
            fy = (pt.y - old.y0) / old.height if old.height else 0
            return pymupdf.Point(rect.x0 + fx * rect.width, rect.y0 + fy * rect.height)

        if obj.kind == "text":
            self._check_no_pending_redactions(obj.page)
        with self._edit():
            page = self._doc[obj.page]
            m, to_display = page.derotation_matrix, page.rotation_matrix
            if obj.kind == "widget":
                w = page.load_widget(obj.xref)
                w.rect = rect * m
                w.update()
            elif obj.kind == "image":
                self._remove_image_use(page, obj.xref)
                page.insert_image(rect * m, xref=obj.xref, keep_proportion=False, rotate=page.rotation)
            elif obj.kind == "text":
                b = obj.block
                dx, dy = rect.x0 - old.x0, rect.y0 - old.y0
                width = b.width + (rect.width - old.width)
                self._erase_text(page, b.line_rects)
                self._write_runs(page, b.runs, b.left + dx, b.first_baseline + dy, max(width, 4 * b.size), b.align,
                                 b.line_height, tr("The paragraph does not fit on the page. Shorten the text or "
                                                   "choose a smaller size."))
            else:
                annot = page.load_annot(obj.xref)
                if obj.subtype == "Line":
                    a, b = (pymupdf.Point(p) for p in line) if line else (remap(obj.line[0]), remap(obj.line[1]))
                    new = page.add_line_annot(a * m, b * m)
                    self._copy_annot_style(annot, new)
                    page.delete_annot(annot)
                elif obj.subtype == "Ink":
                    paths = [[tuple(remap(pymupdf.Point(pt) * to_display) * m) for pt in stroke]
                             for stroke in annot.vertices]
                    new = page.add_ink_annot(paths)
                    self._copy_annot_style(annot, new)
                    page.delete_annot(annot)
                else:
                    self._set_annot_rect(annot, rect * m)

    def style_object(self, obj: PageObject, *, stroke=_UNSET, fill=_UNSET, width: float | None = None,
                     dashed: bool | None = None, opacity: float | None = None) -> None:
        """Change colors, line width/style or opacity. `fill=None` removes the fill."""
        if obj.kind == "text":
            if stroke is not _UNSET and stroke is not None:
                runs = [TextRun(r.text, r.style.with_(color=tuple(stroke))) for r in obj.block.runs]
                self.replace_block(obj.block, runs)
            return
        if obj.kind != "annot":
            return
        with self._edit():
            page = self._doc[obj.page]
            annot = page.load_annot(obj.xref)
            if obj.subtype == "Stamp":
                if stroke is not _UNSET and stroke is not None and self._doc.xref_get_key(
                        obj.xref, _STAMP_COLOR_KEY)[0] != "null":
                    text = annot.info.get("content", "")
                    page.delete_annot(annot)
                    annot = self._make_stamp(page, obj.rect, text, tuple(stroke))
                if opacity is not None:
                    annot.set_opacity(opacity)
                    annot.update()
                return
            if stroke is not _UNSET and stroke is not None:
                annot.set_colors(stroke=stroke)
            if fill is not _UNSET and obj.subtype in _FILLABLE:
                annot.set_colors(fill=fill if fill is not None else [])
            if (width is not None or dashed is not None) and obj.subtype in _BORDERED:
                w = width if width is not None else (obj.width or 1)
                d = dashed if dashed is not None else obj.dashed
                annot.set_border(width=w, dashes=_dashes(w) if d else [])
            if opacity is not None:
                annot.set_opacity(opacity)
            annot.update()

    def delete_object(self, obj: PageObject) -> None:
        if obj.kind == "text":
            self.replace_block(obj.block, "")
            return
        with self._edit():
            page = self._doc[obj.page]
            if obj.kind == "annot":
                page.delete_annot(page.load_annot(obj.xref))
            elif obj.kind == "widget":
                page.delete_widget(page.load_widget(obj.xref))
            elif obj.kind == "image":
                if not obj.movable:
                    raise PdfError(tr("This image cannot be moved or removed."))
                self._remove_image_use(page, obj.xref)

    def object_text(self, obj: PageObject) -> str:
        """The editable text of a note or stamp."""
        return self._doc[obj.page].load_annot(obj.xref).info.get("content", "") if obj.kind == "annot" else ""

    def _stamp_color(self, xref: int) -> tuple[float, float, float] | None:
        kind, value = self._doc.xref_get_key(xref, _STAMP_COLOR_KEY)
        return tuple(float(v) for v in value.strip("[]").split()) if kind != "null" else None

    def set_stamp_text(self, obj: PageObject, text: str, color=None) -> None:
        """Redraw a stamp with new text (and color; default: its current color)."""
        text = " ".join(text.split())
        if not text:
            return
        with self._edit():
            page = self._doc[obj.page]
            annot = page.load_annot(obj.xref)
            color = tuple(color) if color is not None else (self._stamp_color(obj.xref) or (0.8, 0.1, 0.1))
            page.delete_annot(annot)
            self._make_stamp(page, obj.rect, text, color)

    # ---- export ----------------------------------------------------------------

    def export_images(self, pnos: list[int], base: str, fmt: str = "png", dpi: int = 150) -> list[str]:
        """Save each page as `<base>_<n>.<fmt>` (fmt: png | jpg). Returns the written paths."""
        paths = []
        pnos = sorted(set(pnos))
        digits = len(str(self.page_count))
        for pno in pnos:
            pix = self._doc[pno].get_pixmap(dpi=dpi, alpha=False)
            data = pix.tobytes("jpg", jpg_quality=90) if fmt == "jpg" else pix.tobytes("png")
            path = f"{base}_{pno + 1:0{digits}d}.{fmt}"
            write_file(path, data)
            paths.append(path)
        return paths

    def compressed_bytes(self, level: str = "medium") -> bytes:
        """A smaller copy of the current document: images are resampled, fonts subset, objects packed.

        The open document is not changed.
        """
        threshold, target, quality = COMPRESSION_LEVELS[level]
        doc = pymupdf.open("pdf", self._doc.tobytes(encryption=_KEEP))
        try:
            if doc.needs_pass:
                doc.authenticate(self._password or "")
            doc.rewrite_images(dpi_threshold=threshold, dpi_target=target, quality=quality,
                               lossy=True, lossless=True, bitonal=False)
            try:
                doc.subset_fonts()
            except Exception:
                pass  # subsetting is an optimisation; a font MuPDF cannot subset stays as it is
            out = doc.tobytes(garbage=4, deflate=True, deflate_images=True, deflate_fonts=True,
                              clean=True, use_objstms=1, encryption=_KEEP)
        finally:
            doc.close()
        return out

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

    def field_names(self) -> set[str]:
        return {w.field_name for page in self._doc for w in page.widgets()}

    def suggest_field_name(self, kind: str) -> str:
        taken = self.field_names()
        prefix = {"checkbox": "Check", "combobox": "Dropdown", "listbox": "List"}.get(kind, "Text")
        return next(f"{prefix}{i}" for i in range(1, 100_000) if f"{prefix}{i}" not in taken)

    def add_form_field(self, pno: int, rect: pymupdf.Rect, kind: str, name: str,
                       choices: list[str] | None = None, value: str = "") -> None:
        if kind not in _WIDGET_TYPES:
            raise ValueError(kind)
        name = name.strip()
        if not name:
            raise PdfError(tr("The field needs a name."))
        if "." in name:
            raise PdfError(tr("Field names cannot contain a dot."))
        if name in self.field_names():
            raise PdfError(tr("A field named \"{name}\" already exists.", name=name))
        choices = [c.strip() for c in (choices or []) if c.strip()]
        if kind in ("combobox", "listbox") and not choices:
            raise PdfError(tr("Enter at least one option for the list."))
        page = self._doc[pno]
        box = pymupdf.Rect(rect) * page.derotation_matrix
        if box.width < 6 or box.height < 6:
            raise PdfError(tr("The field area is too small."))
        with self._edit():
            page = self._doc[pno]
            w = pymupdf.Widget()
            w.field_type = _WIDGET_TYPES[kind]
            w.field_name = name
            w.rect = box
            w.border_color = (0.45, 0.45, 0.45)
            w.border_width = 1
            w.fill_color = (0.93, 0.95, 1.0)
            if kind == "checkbox":
                w.field_value = False
            elif kind in ("combobox", "listbox"):
                w.choice_values = choices
                w.field_value = value if value in choices else choices[0]
                w.text_fontsize = _fit_font(box, multiline=False)
            else:
                if kind == "multiline":
                    w.field_flags |= pymupdf.PDF_TX_FIELD_IS_MULTILINE
                w.field_value = value
                w.text_fontsize = _fit_font(box, multiline=kind == "multiline")
            page.add_widget(w)

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
