import pymupdf
import pytest

from leafpen.core import fonts, richtext
from leafpen.core.document import PdfDocument
from leafpen.core.richtext import TextRun, TextStyle

from .conftest import make_pdf

PLAIN = TextStyle("sans", size=11)
BOLD = PLAIN.with_(bold=True)
RED = PLAIN.with_(color=(1.0, 0.0, 0.0))
LONG = ("Bu paragraf birkaç satıra yayılan uzun bir metindir ve kutunun genişliğine göre otomatik olarak "
        "satırlara bölünür; düzenleme sonrası da öyle kalmalıdır ve hizası korunur.")


def styles_in(doc, pno=0):
    """{word: (bold, color)} as extracted from the page."""
    out = {}
    for b in doc._doc[pno].get_text("dict")["blocks"]:
        for l in b.get("lines", ()):
            for s in l["spans"]:
                for w in s["text"].split():
                    out[w] = (bool(s["flags"] & 16) or "Bold" in s["font"], s["color"])
    return out


# ---- layout ---------------------------------------------------------------------

def test_layout_wraps_within_width_and_keeps_styles():
    runs = [TextRun("Merhaba ", PLAIN), TextRun("kalın", BOLD), TextRun(" dünya " * 20, PLAIN)]
    lines = richtext.layout(runs, 200)
    assert len(lines) > 2
    for line in lines:
        assert line.width <= 200 + 1e-6
    assert lines[0].fragments[1].style == BOLD and lines[0].fragments[1].text == "kalın"
    assert all(b.baseline > a.baseline for a, b in zip(lines, lines[1:]))


def test_layout_alignments():
    runs = [TextRun(LONG, PLAIN)]
    for align in ("left", "center", "right", "justify"):
        lines = richtext.layout(runs, 220, align)
        first = lines[0]
        end = max(f.x + richtext.measure(f.text, f.style) for f in first.fragments)
        start = first.fragments[0].x
        if align == "left":
            assert start == 0
        elif align == "right":
            assert abs(end - 220) < 0.01
        elif align == "center":
            assert abs(start - (220 - end)) < 0.01
        else:  # justified: flush on both sides, except the last line
            assert start == 0 and abs(end - 220) < 0.01
            last = lines[-1]  # not stretched: ends at its natural width
            assert abs(max(f.x + richtext.measure(f.text, f.style) for f in last.fragments) - last.width) < 0.01


def test_layout_breaks_overlong_words_and_keeps_newlines():
    lines = richtext.layout([TextRun("a" * 200 + "\n\nson", PLAIN)], 100)
    assert all(l.width <= 100 + 1e-6 for l in lines)
    assert lines[-1].fragments[0].text == "son"
    assert lines[-2].fragments == []  # the empty paragraph


@pytest.mark.parametrize("rects, expected", [
    ([pymupdf.Rect(10, 0, 200, 10), pymupdf.Rect(10, 12, 150, 22)], "left"),
    ([pymupdf.Rect(10, 0, 200, 10), pymupdf.Rect(10, 12, 200, 22), pymupdf.Rect(10, 24, 90, 34)], "justify"),
    ([pymupdf.Rect(10, 0, 200, 10), pymupdf.Rect(40, 12, 170, 22)], "center"),
    ([pymupdf.Rect(10, 0, 200, 10), pymupdf.Rect(80, 12, 200, 22)], "right"),
    ([pymupdf.Rect(10, 0, 200, 10)], "left"),
])
def test_detect_align(rects, expected):
    assert richtext.detect_align(rects, 11) == expected


# ---- editing ------------------------------------------------------------------------

@pytest.mark.parametrize("rotation", [0, 90])
def test_add_rich_text_keeps_bold_and_color(rotation):
    doc = PdfDocument(make_pdf(rotation=rotation, text_lines=()))
    doc.add_text(0, 40, 40, [TextRun("Normal ", PLAIN), TextRun("kalın", BOLD), TextRun(" kırmızı", RED)])
    words = styles_in(doc)
    assert words["Normal"] == (False, 0)
    assert words["kalın"][0] is True
    assert words["kırmızı"] == (False, 0xFF0000)
    assert [l.text for l in doc.text_lines(0)] == ["Normal kalın kırmızı"]


@pytest.mark.parametrize("rotation", [0, 90])
def test_paragraph_edit_keeps_mixed_styles(rotation):
    doc = PdfDocument(make_pdf(rotation=rotation, text_lines=()))
    doc.add_text(0, 40, 40, [TextRun("Sözleşme ", PLAIN), TextRun("önemli", BOLD), TextRun(" " + LONG, PLAIN)],
                 width=250)
    block = doc.block_at(0, 50, 45)
    assert any(r.style.bold and r.text == "önemli" for r in block.runs)
    runs = [TextRun(r.text.replace("uzun", "çok uzun"), r.style) for r in block.runs]
    doc.replace_block(block, runs)
    after = doc.block_at(0, 50, 45)
    assert after.text.startswith("Sözleşme önemli Bu paragraf") and "çok uzun" in after.text
    assert styles_in(doc)["önemli"][0] is True
    assert abs(after.rect.x0 - block.rect.x0) < 1 and abs(after.first_baseline - block.first_baseline) < 0.5


@pytest.mark.parametrize("align", ["center", "right", "justify"])
def test_paragraph_alignment_is_detected_and_kept(align):
    doc = PdfDocument(make_pdf(text_lines=()))
    doc.add_text(0, 40, 40, LONG, size=11, align=align, width=260)
    block = doc.block_at(0, 150, 50)
    assert block.align == align
    doc.replace_block(block, block.text.replace("uzun", "kısa"))
    after = doc.block_at(0, 150, 50)
    assert after.align == align
    if align == "right":
        assert abs(after.rect.x1 - block.rect.x1) < 1
    elif align == "center":
        assert abs((after.rect.x0 + after.rect.x1) / 2 - (block.rect.x0 + block.rect.x1) / 2) < 1
    else:
        assert abs(after.rect.x0 - block.rect.x0) < 1 and abs(after.rect.x1 - block.rect.x1) < 1


def test_unchanged_paragraph_breaks_at_the_same_places():
    doc = PdfDocument(make_pdf(text_lines=()))
    doc.add_text(0, 40, 40, LONG, size=11, width=230)
    before = [l.text for l in doc.text_lines(0)]
    doc.replace_block(doc.block_at(0, 50, 45), doc.block_at(0, 50, 45).runs)
    assert [l.text for l in doc.text_lines(0)] == before


def test_paragraph_can_change_alignment_spacing_and_width():
    doc = PdfDocument(make_pdf(text_lines=()))
    doc.add_text(0, 40, 40, LONG, size=11, width=230)
    block = doc.block_at(0, 50, 45)
    doc.replace_block(block, block.runs, align="center", line_height=2.0, width=320)
    after = doc.block_at(0, 50, 45) or doc.text_blocks(0)[0]
    assert len(after.line_rects) < len(block.line_rects)  # wider box, fewer lines
    gaps = [b.y0 - a.y0 for a, b in zip(after.line_rects, after.line_rects[1:])]
    assert all(abs(g - 22) < 1 for g in gaps)


@pytest.mark.parametrize("align", ["center", "right"])
def test_realigned_paragraph_stays_one_paragraph(align):
    """After centering a one-block-per-line paragraph its lines start at different x; still one paragraph."""
    from pathlib import Path
    doc = PdfDocument.open(str(Path(__file__).resolve().parents[1] / "samples" / "sample-en.pdf"))
    block = next(b for b in doc.text_blocks(0) if b.text.startswith("This document"))
    runs = block.runs + [TextRun(" Bir cümle daha.", block.runs[-1].style)]
    doc.replace_block(block, runs, align=align, line_height=1.6)
    after = next(b for b in doc.text_blocks(0) if b.text.startswith("This document"))
    assert after.text.endswith("Bir cümle daha.") and after.align == align


def test_overlap_with_text_below_is_reported():
    doc = PdfDocument(make_pdf(text_lines=()))
    doc.add_text(0, 40, 40, "Kısa paragraf.", size=11)
    doc.add_text(0, 40, 60, "Alttaki metin.", size=11)
    block = doc.block_at(0, 45, 45)
    assert doc.replace_block(block, LONG, width=200) is True
    doc.undo()
    assert doc.replace_block(doc.block_at(0, 45, 45), "Yine kısa.") is False


def test_line_edit_with_runs():
    doc = PdfDocument(make_pdf())
    line = doc.text_lines(0)[0]
    doc.replace_line(line, [TextRun("Yeni ", line.runs[0].style), TextRun("kalın\nsatır", BOLD)])
    assert doc.text_lines(0)[0].text == "Yeni kalın satır"
    assert styles_in(doc)["kalın"][0] is True
    assert abs(doc.text_lines(0)[0].rect.x0 - line.rect.x0) < 1
