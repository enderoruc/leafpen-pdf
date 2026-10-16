"""Whole-file tools that work on files rather than the open document: merge, images to PDF, repair."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass

import pymupdf

from ..i18n import tr
from .document import PdfError

# Page sizes for "images to PDF", in points (portrait).
PAGE_SIZES = {"a4": pymupdf.paper_size("a4"), "letter": pymupdf.paper_size("letter")}

# Image types MuPDF opens itself; others are converted to PNG by the caller.
IMAGE_TYPES = ("png", "jpg", "jpeg", "bmp", "gif", "tif", "tiff", "jxr", "jpx", "jp2", "pnm", "pbm", "pgm",
               "ppm", "psd")
# Phone photo types neither MuPDF nor Qt read; decoded with pillow-heif (see heic_to_image).
HEIC_TYPES = ("heic", "heif")


def is_heic(name: str) -> bool:
    return os.path.splitext(name)[1].lstrip(".").lower() in HEIC_TYPES


def heic_to_image(data: bytes) -> tuple[str, bytes]:
    """(extension, bytes) of the primary image of a HEIC/HEIF file: JPEG, or PNG if it has transparency.

    libheif applies the file's rotation/mirroring while decoding, so the result is upright.
    """
    import io

    import pillow_heif

    try:
        heif = pillow_heif.open_heif(data, convert_hdr_to_8bit=True)
        img = heif.to_pillow()
    except Exception as e:
        raise PdfError(tr("The image file could not be read.")) from e
    buf = io.BytesIO()
    if img.mode in ("RGBA", "LA"):
        img.save(buf, "PNG")
        return "png", buf.getvalue()
    img.convert("RGB").save(buf, "JPEG", quality=92)
    return "jpg", buf.getvalue()


def _label(name: str) -> str:
    return os.path.splitext(os.path.basename(name))[0] or name


def merge_pdfs(sources: list[tuple[str, bytes]], bookmarks: bool = True) -> bytes:
    """Join PDFs in order. `sources` are (file name, bytes) pairs.

    With `bookmarks`, each file gets a top-level bookmark (its name) with its own bookmarks nested
    below; otherwise the files' own bookmarks are kept as they are.
    """
    if len(sources) < 2:
        raise PdfError(tr("Choose at least two PDFs to merge."))
    out = pymupdf.open()
    toc: list[list] = []
    for name, data in sources:
        try:
            src = pymupdf.open("pdf", data)
        except Exception as e:
            raise PdfError(tr("Could not open {name}; the file is damaged or not a PDF.",
                              name=os.path.basename(name))) from e
        with src:
            if src.needs_pass:
                raise PdfError(tr("{name} is password protected. Open it and remove its password first.",
                                  name=os.path.basename(name)))
            if src.page_count == 0:
                continue
            offset = out.page_count
            out.insert_pdf(src)
            shift = 1 if bookmarks else 0
            if bookmarks:
                toc.append([1, _label(name), offset + 1])
            for level, title, page, *_ in src.get_toc(simple=True):
                toc.append([level + shift, title, offset + (page if page >= 1 else 1)])
    if out.page_count == 0:
        raise PdfError(tr("The PDF has no pages."))
    if toc:
        out.set_toc(toc)
    return out.tobytes(garbage=3, deflate=True)


def images_to_pdf(images: list[tuple[str, bytes]], page_size: str = "image", orientation: str = "auto",
                  margin: float = 0) -> bytes:
    """One page per image (every frame of a multi-page TIFF), in order.

    page_size: "image" (the page fits the image) or a key of PAGE_SIZES, where the image is scaled to
    fit and centred. orientation: "auto" (follows the image), "portrait" or "landscape"; ignored for
    "image". margin: points around the image. JPEGs are embedded without recompression and their
    EXIF orientation is honoured.
    """
    if not images:
        raise PdfError(tr("Choose at least one image."))
    out = pymupdf.open()
    for name, data in images:
        ext = os.path.splitext(name)[1].lstrip(".").lower() or "png"
        try:
            with pymupdf.open(stream=data, filetype=ext) as img:
                src = pymupdf.open("pdf", img.convert_to_pdf())
        except Exception as e:
            raise PdfError(tr("Could not read the image {name}.", name=os.path.basename(name))) from e
        with src:
            for page in src:
                w, h = page.rect.width, page.rect.height
                if page_size == "image":
                    pw, ph = w + 2 * margin, h + 2 * margin
                else:
                    pw, ph = PAGE_SIZES[page_size]
                    landscape = w > h if orientation == "auto" else orientation == "landscape"
                    if landscape:
                        pw, ph = ph, pw
                target = out.new_page(width=pw, height=ph)
                target.show_pdf_page(pymupdf.Rect(margin, margin, pw - margin, ph - margin), src, page.number)
    return out.tobytes(garbage=3, deflate=True)


@dataclass
class RepairReport:
    rebuilt: bool  # the file's structure (cross-reference table) was damaged and was reconstructed
    pages: int  # pages in the repaired file
    dropped: int  # unreadable pages left out


def repair_pdf(data: bytes) -> tuple[bytes, RepairReport]:
    """Rebuild a damaged PDF into a clean file that other programs can open.

    MuPDF reconstructs a broken structure while opening; the file is then rewritten with clean
    content streams. Pages that cannot be read at all are left out.
    """
    try:
        doc = pymupdf.open("pdf", data)
    except Exception as e:
        raise PdfError(tr("The file could not be recovered; too little of it is readable as a PDF.")) from e
    with doc:
        if doc.needs_pass:
            raise PdfError(tr("This PDF is password protected. Open it and remove its password first."))
        rebuilt = bool(doc.is_repaired)
        total = doc.page_count
        keep = []
        for pno in range(total):
            try:
                doc.load_page(pno).get_displaylist()
                keep.append(pno)
            except Exception:
                pass
        if not keep:
            raise PdfError(tr("The file could not be recovered; too little of it is readable as a PDF."))
        if len(keep) < total:
            doc.select(keep)
        out = doc.tobytes(garbage=3, deflate=True, clean=True, encryption=pymupdf.PDF_ENCRYPT_KEEP)
        return out, RepairReport(rebuilt, len(keep), total - len(keep))


_RANGE = re.compile(r"^(\d+)?\s*(-)?\s*(\d+)?$")


def parse_ranges(text: str, page_count: int) -> list[list[int]]:
    """Page groups from text such as "1-3, 5, 8-" (1-based; "8-" runs to the last page).

    Returns 0-based page lists, one per comma-separated part.
    """
    groups = []
    for part in re.split(r"[,;]", text):
        part = part.strip()
        if not part:
            continue
        m = _RANGE.match(part)
        if not m or not (m.group(1) or m.group(3)) or (m.group(3) and not m.group(2)):
            raise PdfError(tr("“{part}” is not a page range. Use for example 1-3, 5, 8-.", part=part))
        first = int(m.group(1)) if m.group(1) else 1
        last = int(m.group(3)) if m.group(3) else (page_count if m.group(2) else first)
        if not (1 <= first <= last <= page_count):
            raise PdfError(tr("“{part}” is outside the document's pages (1–{count}).", part=part,
                              count=page_count))
        groups.append(list(range(first - 1, last)))
    if not groups:
        raise PdfError(tr("Enter at least one page range."))
    return groups


def every_n_pages(page_count: int, n: int) -> list[list[int]]:
    return [list(range(i, min(i + n, page_count))) for i in range(0, page_count, max(1, n))]
