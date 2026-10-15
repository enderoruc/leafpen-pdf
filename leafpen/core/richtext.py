"""Styled text and its layout: line breaking, alignment and line spacing.

Text written into PDFs goes through here instead of MuPDF's insert_textbox so
that one paragraph can mix fonts, sizes, colors and bold/italic, and can be
justified. Positions are in points relative to the text box: x from its left
edge, y as baselines measured from the first baseline.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, replace
from functools import lru_cache

import pymupdf

from . import fonts

ALIGNS = ("left", "center", "right", "justify")


@dataclass(frozen=True)
class TextStyle:
    family: str = "sans"
    bold: bool = False
    italic: bool = False
    size: float = 12.0
    color: tuple[float, float, float] = (0.0, 0.0, 0.0)

    def with_(self, **changes) -> "TextStyle":
        return replace(self, **changes)


@dataclass
class TextRun:
    text: str
    style: TextStyle


@dataclass
class Fragment:
    x: float
    text: str
    style: TextStyle


@dataclass
class LaidLine:
    baseline: float  # relative to the first baseline
    fragments: list[Fragment]
    width: float  # natural width before justification
    ascent: float
    descent: float


@lru_cache(maxsize=None)
def _font(family: str, bold: bool, italic: bool) -> pymupdf.Font:
    path = fonts.font_file(family, bold, italic)
    return pymupdf.Font(fontfile=path) if path else pymupdf.Font("helv")


def measure(text: str, style: TextStyle) -> float:
    return _font(style.family, style.bold, style.italic).text_length(text, fontsize=style.size)


def ascent(style: TextStyle) -> float:
    return _font(style.family, style.bold, style.italic).ascender * style.size


def descent(style: TextStyle) -> float:
    return -_font(style.family, style.bold, style.italic).descender * style.size


def normalize(runs: list[TextRun]) -> list[TextRun]:
    """Drop empty runs and merge neighbours with the same style."""
    out: list[TextRun] = []
    for r in runs:
        if not r.text:
            continue
        if out and out[-1].style == r.style:
            out[-1] = TextRun(out[-1].text + r.text, r.style)
        else:
            out.append(TextRun(r.text, r.style))
    return out


def plain(runs: list[TextRun]) -> str:
    return "".join(r.text for r in runs)


def strip(runs: list[TextRun]) -> list[TextRun]:
    """Remove leading and trailing whitespace across runs."""
    runs = normalize(runs)
    while runs and not runs[0].text.strip():
        runs.pop(0)
    while runs and not runs[-1].text.strip():
        runs.pop()
    if runs:
        runs[0] = TextRun(runs[0].text.lstrip(), runs[0].style)
        runs[-1] = TextRun(runs[-1].text.rstrip(), runs[-1].style)
    return runs


_TOKEN = re.compile(r"\n|[ \t ]+|[^ \t \n]+")


def _tokens(runs: list[TextRun]):
    """(kind, text, style) with kind in word | space | newline."""
    for r in runs:
        for m in _TOKEN.finditer(r.text.replace("\r\n", "\n").replace("\r", "\n")):
            t = m.group(0)
            kind = "newline" if t == "\n" else "space" if not t.strip() else "word"
            yield kind, t, r.style


def _split_word(text: str, style: TextStyle, width: float) -> list[str]:
    """Break a word that is wider than the box into pieces that fit."""
    pieces, cur = [], ""
    for ch in text:
        if cur and measure(cur + ch, style) > width:
            pieces.append(cur)
            cur = ch
        else:
            cur += ch
    if cur:
        pieces.append(cur)
    return pieces


def layout(runs: list[TextRun], width: float, align: str = "left", line_height: float = 1.2,
           default: TextStyle | None = None) -> list[LaidLine]:
    """Break `runs` into lines no wider than `width` and position them.

    `line_height` is the baseline distance as a multiple of the largest font size on a line.
    """
    default = default or (runs[0].style if runs else TextStyle())
    # Each raw line: list of items [kind, text, style, w]; paragraph_end marks forced breaks.
    raw: list[tuple[list[list], bool, TextStyle]] = []
    items: list[list] = []
    pending: list[list] = []  # spaces waiting for the next word
    used = 0.0
    last_style = default

    def finish(paragraph_end: bool):
        nonlocal items, pending, used
        raw.append((items, paragraph_end, last_style))
        items, pending, used = [], [], 0.0

    for kind, text, style in _tokens(runs):
        last_style = style
        if kind == "newline":
            finish(True)
        elif kind == "space":
            if items:  # spaces at the start of a wrapped line are dropped
                pending.append(["space", text, style, measure(text, style)])
        else:
            w = measure(text, style)
            gap = sum(p[3] for p in pending)
            if items and used + gap + w > width:
                finish(False)
                gap = 0.0
            if not items and w > width:
                pieces = _split_word(text, style, width)
                for piece in pieces[:-1]:
                    items.append(["word", piece, style, measure(piece, style)])
                    finish(False)
                text = pieces[-1]
                w = measure(text, style)
            items.extend(pending if items else [])
            pending = []
            items.append(["word", text, style, w])
            used += gap + w
    finish(True)

    out: list[LaidLine] = []
    baseline = 0.0
    for i, (line_items, paragraph_end, end_style) in enumerate(raw):
        styles = [it[2] for it in line_items] or [end_style]
        size = max(s.size for s in styles)
        asc = max(ascent(s) for s in styles)
        desc = max(descent(s) for s in styles)
        if i:
            baseline += size * line_height
        natural = sum(it[3] for it in line_items)
        spaces = [it for it in line_items if it[0] == "space"]
        extra = 0.0
        if align == "justify" and not paragraph_end and spaces and natural < width:
            extra = (width - natural) / len(spaces)
        offset = {"center": (width - natural) / 2, "right": width - natural}.get(align, 0.0)
        frags: list[Fragment] = []
        x = max(0.0, offset)
        for kind, text, style, w in line_items:
            if kind == "space" and extra:  # justified: words are placed one by one
                x += w + extra
                continue
            if frags and not extra and frags[-1].style == style:
                frags[-1].text += text
            else:
                frags.append(Fragment(x, text, style))
            x += w
        out.append(LaidLine(baseline, frags, natural, asc, desc))
    return out


def height(lines: list[LaidLine]) -> float:
    """From the top of the first line to the bottom of the last."""
    return lines[0].ascent + lines[-1].baseline + lines[-1].descent if lines else 0.0


def detect_align(line_rects: list[pymupdf.Rect], size: float) -> str:
    """Guess a paragraph's alignment from where its lines start and end."""
    if len(line_rects) < 2:
        return "left"
    tol = max(1.5, size * 0.15)

    def spread(values: list[float]) -> float:
        return max(values) - min(values)

    x0 =[r.x0 for r in line_rects]
    x1 = [r.x1 for r in line_rects]
    mid = [(r.x0 + r.x1) / 2 for r in line_rects]
    lefts = spread(x0) <= tol
    if lefts and len(line_rects) >= 3 and spread(x1[:-1]) <= tol and x1[-1] < max(x1[:-1]) - tol:
        return "justify"
    if not lefts and spread(mid) <= tol:
        return "center"
    if not lefts and spread(x1) <= tol:
        return "right"
    return "left"
