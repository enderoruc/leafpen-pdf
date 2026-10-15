"""Font selection for text written into PDFs.

The PDF base-14 fonts use WinAnsi encoding and cannot represent Turkish letters
(ğ, ş, ı, İ, ...), so text is always written with an embedded TrueType font.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import pymupdf

_FONT_DIR = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"

# regular, bold, italic, bold-italic
_FAMILIES = {
    "sans": ("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf"),
    "serif": ("times.ttf", "timesbd.ttf", "timesi.ttf", "timesbi.ttf"),
    "mono": ("cour.ttf", "courbd.ttf", "couri.ttf", "courbi.ttf"),
}

FAMILY_LABELS = {"sans": "Sans (Arial)", "serif": "Serif (Times)", "mono": "Mono (Courier)"}


def font_file(family: str = "sans", bold: bool = False, italic: bool = False) -> str | None:
    files = _FAMILIES.get(family, _FAMILIES["sans"])
    index = (1 if bold else 0) + (2 if italic else 0)
    for name in (files[index], files[0], _FAMILIES["sans"][0]):
        path = _FONT_DIR / name
        if path.exists():
            return str(path)
    return None


def font_args(family: str = "sans", bold: bool = False, italic: bool = False) -> dict:
    """Keyword arguments for PyMuPDF's insert_text / insert_textbox."""
    path = font_file(family, bold, italic)
    if path is None:
        return {"fontname": "helv"}
    return {"fontname": f"K{family}{int(bold)}{int(italic)}", "fontfile": path}


_OUR_FONT = re.compile(r"^K(sans|serif|mono)([01])([01])$")


def fix_space_mapping(doc: pymupdf.Document, page: pymupdf.Page) -> None:
    """Make our embedded fonts extract spaces as U+0020.

    TrueType fonts like Arial share one glyph between U+0020 and U+00A0, and
    MuPDF's generated ToUnicode CMap maps it back to U+00A0, which breaks copy,
    paste and search in every viewer.
    """
    for xref, _ext, _type, _base, refname, _enc in page.get_fonts():
        m = _OUR_FONT.match(refname)
        if not m:
            continue
        kind, value = doc.xref_get_key(xref, "ToUnicode")
        if kind != "xref":
            continue
        path = font_file(m.group(1), m.group(2) == "1", m.group(3) == "1")
        gid = pymupdf.Font(fontfile=path).has_glyph(32) if path else 0
        if not gid:
            continue
        stream_xref = int(value.split()[0])
        cmap = doc.xref_stream(stream_xref).decode("latin-1")
        fixed = re.sub(rf"<{gid:04x}>\s*<00a0>", f"<{gid:04x}> <0020>", cmap, flags=re.IGNORECASE)
        if fixed != cmap:
            doc.update_stream(stream_xref, fixed.encode("latin-1"))


def classify(font_name: str, flags: int) -> tuple[str, bool, bool]:
    """Map an extracted span's font to (family, bold, italic)."""
    name = font_name.lower()
    if flags & 8 or any(k in name for k in ("courier", "mono", "consola")):
        family = "mono"
    elif flags & 4 or any(k in name for k in ("times", "serif", "roman", "georgia", "garamond", "cambria")):
        family = "serif"
    else:
        family = "sans"
    bold = bool(flags & 16) or any(k in name for k in ("bold", "black", "heavy"))
    italic = bool(flags & 2) or any(k in name for k in ("italic", "oblique"))
    return family, bold, italic
