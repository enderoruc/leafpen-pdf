"""The select tool's document API: picking, moving, resizing, restyling and deleting objects."""
import pymupdf
import pytest

from leafpen.core.document import PdfDocument, PdfError

from .conftest import make_pdf


def close(a: pymupdf.Rect, b: pymupdf.Rect, tol: float = 1.0) -> bool:
    return all(abs(x - y) <= tol for x, y in zip(a, b))


def _png(w=40, h=20) -> bytes:
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, w, h), True)
    pix.set_rect(pix.irect, (255, 0, 0, 160))
    return pix.tobytes("png")


@pytest.mark.parametrize("rotation", [0, 90])
@pytest.mark.parametrize("kind", ["rect", "ellipse"])
def test_shape_moves_and_resizes_exactly(rotation, kind):
    doc = PdfDocument(make_pdf(rotation=rotation, text_lines=()))
    doc.add_shape(0, kind, pymupdf.Rect(20, 20, 100, 60), color=(1, 0, 0), width=4)
    obj = doc.object_at(0, 60, 22)
    assert obj and obj.kind == "annot" and obj.resizable
    target = pymupdf.Rect(150, 100, 260, 190)
    doc.transform_object(obj, target)
    moved = doc.object_at(0, 205, 102)
    assert moved and close(moved.rect, target)
    for _ in range(3):  # repeated moves must not grow the shape
        moved = doc.object_at(0, moved.rect.x0 + 30, moved.rect.y0 + 2)
        doc.transform_object(moved, moved.rect + (5, 5, 5, 5))
    final = doc.object_at(0, moved.rect.x0 + 40, moved.rect.y0 + 17)
    assert close(final.rect, target + (15, 15, 15, 15))
    assert final.stroke == (1.0, 0.0, 0.0) and final.width == 4


@pytest.mark.parametrize("rotation", [0, 90])
def test_line_endpoints_and_ink_move(rotation):
    doc = PdfDocument(make_pdf(rotation=rotation, text_lines=()))
    doc.add_line(0, (20, 100), (120, 100), color=(0, 0, 1), width=3, arrow=True)
    line = doc.object_at(0, 70, 100)
    assert line.subtype == "Line" and close(pymupdf.Rect(*line.line[0], *line.line[1]), pymupdf.Rect(20, 100, 120, 100))
    doc.transform_object(line, line.rect, line=((30, 150), (180, 200)))
    moved = doc.object_at(0, 105, 175)
    assert moved.subtype == "Line"
    assert close(pymupdf.Rect(*moved.line[0], *moved.line[1]), pymupdf.Rect(30, 150, 180, 200))
    page = doc._doc[0]  # keep a reference: annotations only weakly reference their page
    annot = page.load_annot(moved.xref)
    assert annot.line_ends[1] == pymupdf.PDF_ANNOT_LE_OPEN_ARROW and moved.width == 3  # style kept

    doc.add_ink(0, [[(20, 20), (60, 40), (100, 20)]], color=(0, 0.5, 0), width=2)
    ink = doc.object_at(0, 60, 40)
    assert ink.subtype == "Ink"
    doc.transform_object(ink, ink.rect + (100, 50, 100, 50))
    assert doc.object_at(0, 60, 40) is None or doc.object_at(0, 60, 40).subtype != "Ink"
    assert doc.object_at(0, 160, 90).subtype == "Ink"


def test_note_moves_without_resizing_and_stamp_resizes():
    doc = PdfDocument(make_pdf(text_lines=()))
    doc.add_note(0, 50, 50, "not")
    note = doc.object_at(0, 52, 52)
    assert note.subtype == "Text" and not note.resizable
    size = (note.rect.width, note.rect.height)
    doc.transform_object(note, pymupdf.Rect(200, 200, 400, 400))
    moved = doc.object_at(0, 203, 203)
    assert (round(moved.rect.width), round(moved.rect.height)) == tuple(map(round, size))
    assert doc.object_text(moved) == "not"

    doc.add_stamp(0, pymupdf.Rect(20, 150, 180, 200), "ONAYLANDI")
    stamp = doc.object_at(0, 100, 175)
    doc.transform_object(stamp, pymupdf.Rect(20, 150, 340, 250))
    big = doc.object_at(0, 300, 240)
    assert big.subtype == "Stamp" and big.rect.width > 300


@pytest.mark.parametrize("rotation", [0, 90])
def test_image_moves_resizes_and_deletes(rotation):
    doc = PdfDocument(make_pdf(rotation=rotation, text_lines=()))
    doc.add_image(0, pymupdf.Rect(20, 20, 100, 60), _png())
    before = doc.render(0, 1).pixel(60, 40)
    img = doc.object_at(0, 60, 40)
    assert img.kind == "image" and img.movable
    xref = img.xref
    doc.transform_object(img, pymupdf.Rect(150, 100, 310, 180))
    moved = doc.object_at(0, 200, 140)
    assert moved.kind == "image" and moved.xref == xref and close(moved.rect, pymupdf.Rect(150, 100, 310, 180))
    assert doc.object_at(0, 60, 40) is None
    pix = doc.render(0, 1)
    after = pix.pixel(230, 140)
    assert all(abs(x - y) <= 2 for x, y in zip(after, before))  # same color: the transparency mask survived
    doc.delete_object(moved)
    assert doc.object_at(0, 200, 140) is None
    doc.undo()
    assert doc.object_at(0, 200, 140).kind == "image"


def test_image_used_twice_is_not_movable():
    src = pymupdf.open()
    page = src.new_page(width=400, height=300)
    xref = page.insert_image(pymupdf.Rect(20, 20, 100, 60), stream=_png())
    page.insert_image(pymupdf.Rect(200, 20, 280, 60), xref=xref)
    doc = PdfDocument(src.tobytes())
    img = doc.object_at(0, 60, 40)
    assert img.kind == "image" and not img.movable
    with pytest.raises(PdfError):
        doc.transform_object(img, pymupdf.Rect(0, 100, 80, 140))
    with pytest.raises(PdfError):
        doc.delete_object(img)


def test_style_changes():
    doc = PdfDocument(make_pdf(text_lines=()))
    doc.add_shape(0, "rect", pymupdf.Rect(20, 20, 120, 80), color=(0, 0, 0), width=2)
    obj = doc.object_at(0, 70, 21)
    doc.style_object(obj, stroke=(1, 0, 0), fill=(1, 1, 0), width=5, dashed=True, opacity=0.5)
    obj = doc.object_at(0, 70, 21)
    assert obj.stroke == (1.0, 0.0, 0.0) and obj.fill == (1.0, 1.0, 0.0)
    assert obj.width == 5 and obj.dashed and abs(obj.opacity - 0.5) < 0.01
    doc.style_object(obj, width=6.0)  # a float width, then dashes on their own
    doc.style_object(doc.object_at(0, 70, 21), dashed=False)
    doc.style_object(doc.object_at(0, 70, 21), dashed=True)
    obj = doc.object_at(0, 70, 21)
    assert obj.dashed and obj.width == 6
    doc.style_object(obj, fill=None, dashed=False, width=5)
    obj = doc.object_at(0, 70, 21)
    assert obj.fill is None and not obj.dashed and obj.width == 5

    doc.add_stamp(0, pymupdf.Rect(20, 150, 180, 200), "TASLAK", color=(1, 0, 0))
    stamp = doc.object_at(0, 100, 175)
    doc.style_object(stamp, stroke=(0, 0, 1))
    pix = doc.render(0, 1)
    blues = sum(1 for x in range(20, 180, 2) for y in range(150, 200, 2)
                if (lambda p: p[2] > 200 and p[0] < 80)(pix.pixel(x, y)))
    assert blues > 30
    doc.set_stamp_text(doc.object_at(0, 100, 175), "ONAY")
    assert doc.object_text(doc.object_at(0, 100, 175)) == "ONAY"


def test_created_shape_options():
    doc = PdfDocument(make_pdf(text_lines=()))
    doc.add_shape(0, "ellipse", pymupdf.Rect(20, 20, 120, 80), color=(0, 0, 1), width=3, fill=(0.9, 0.9, 1),
                  dashed=True, opacity=0.6)
    obj = doc.object_at(0, 70, 50)
    assert obj.fill == pytest.approx((0.9, 0.9, 1.0), abs=1e-4) and obj.dashed and abs(obj.opacity - 0.6) < 0.01


@pytest.mark.parametrize("rotation", [0, 90])
def test_paragraph_moves_and_rewraps(rotation):
    doc = PdfDocument(make_pdf(rotation=rotation, text_lines=()))
    doc.add_text(0, 40, 40, "Taşınabilir paragraf " * 8, size=11, width=150)
    obj = doc.object_at(0, 45, 45)
    assert obj.kind == "text"
    lines_before = len(obj.block.line_rects)
    target = obj.rect + (20, 100, 20 + 60, 100)  # move and make wider (stays on the page)
    doc.transform_object(obj, target)
    assert doc.object_at(0, 45, 45) is None
    moved = doc.object_at(0, target.x0 + 5, target.y0 + 5)
    assert moved.kind == "text" and moved.block.text == obj.block.text
    assert abs(moved.rect.x0 - target.x0) < 1 and abs(moved.rect.y0 - target.y0) < 1.5
    assert len(moved.block.line_rects) < lines_before
    doc.style_object(moved, stroke=(1, 0, 0))
    assert doc.object_at(0, target.x0 + 5, target.y0 + 5).block.color == (1.0, 0.0, 0.0)
    doc.delete_object(doc.object_at(0, target.x0 + 5, target.y0 + 5))
    assert doc.object_at(0, target.x0 + 5, target.y0 + 5) is None


def test_text_moved_off_the_page_is_refused():
    doc = PdfDocument(make_pdf(text_lines=()))
    doc.add_text(0, 40, 40, "Kenara taşınamaz", size=11)
    obj = doc.object_at(0, 45, 45)
    with pytest.raises(PdfError):
        doc.transform_object(obj, obj.rect + (380, 0, 380, 0))
    assert doc.object_at(0, 45, 45).kind == "text"  # rolled back


def test_form_field_moves():
    doc = PdfDocument(make_pdf(text_lines=()))
    doc.add_form_field(0, pymupdf.Rect(20, 20, 200, 40), "text", "Ad")
    obj = doc.object_at(0, 50, 30)
    assert obj.kind == "widget"
    doc.transform_object(obj, pymupdf.Rect(20, 100, 250, 124))
    assert doc.object_at(0, 50, 30) is None
    moved = doc.object_at(0, 100, 110)
    assert moved.kind == "widget" and close(moved.rect, pymupdf.Rect(20, 100, 250, 124))
    doc.delete_object(moved)
    assert "Ad" not in doc.field_names()
