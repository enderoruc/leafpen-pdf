import io
import math

import pymupdf
import pytest

from leafpen.core import fonts
from leafpen.core.document import HF_SLOTS, PdfDocument, PdfError

from .conftest import make_pdf


def texts(doc, pno=0):
    return [l.text for l in doc.text_lines(pno)]


def all_text(doc):
    return "".join(doc._doc[i].get_text() for i in range(doc.page_count))


def reopen(doc) -> PdfDocument:
    """Round-trip through bytes, as saving and reopening would."""
    return PdfDocument(doc._doc.tobytes())


# ---- search ------------------------------------------------------------------

@pytest.mark.parametrize("rotation", [0, 90, 270])
def test_search_returns_display_rects(rotation):
    doc = PdfDocument(make_pdf(pages=2, rotation=rotation))
    hits = doc.search("ikinci")  # case-insensitive, Turkish dotted capital İ
    assert [h.page for h in hits] == [0, 1]
    line = next(l for l in doc.text_lines(0) if l.text.startswith("İkinci"))
    assert line.rect.intersects(hits[0].rect)
    assert hits[0].rect.width > hits[0].rect.height  # horizontal for the viewer
    assert doc.search("   ") == []
    assert doc.search("bulunmayan") == []
    assert len(doc.search("İKİNCİ  SATIR")) == 2  # upper-case query, collapsed whitespace
    assert len(doc.search("ğüşıöç")) == 2


def test_added_text_extracts_punctuation_as_typed():
    doc = PdfDocument(make_pdf(text_lines=()))
    for family in ("sans", "serif", "mono"):
        doc.add_text(0, 40, 40, "a; b · c - d e", family=family)
        assert texts(doc) == ["a; b · c - d e"], family
        doc.undo()


# ---- redaction ---------------------------------------------------------------

@pytest.mark.parametrize("rotation", [0, 90])
def test_redaction_removes_marked_text_only_when_applied(rotation):
    doc = PdfDocument(make_pdf(rotation=rotation))
    hits = doc.search("Birinci")
    assert doc.mark_redactions([(h.page, h.rect) for h in hits]) == 1
    assert doc.redaction_count() == 1
    assert "Birinci" in all_text(doc)  # only marked so far
    with pytest.raises(PdfError):
        doc.replace_line(doc.text_lines(0)[1], "x")  # editing would apply the marks too
    assert doc.apply_redactions() == 1
    assert doc.redaction_count() == 0
    assert "Birinci" not in all_text(doc)
    assert "İkinci satır burada" in all_text(doc)
    doc.undo()
    assert "Birinci" in all_text(doc) and doc.redaction_count() == 1


def test_redaction_blanks_image_pixels():
    src = pymupdf.open()
    page = src.new_page(width=200, height=200)
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 50, 50), False)
    pix.set_rect(pix.irect, (255, 255, 255))
    page.insert_image(pymupdf.Rect(0, 0, 200, 200), pixmap=pix)
    doc = PdfDocument(src.tobytes())
    doc.mark_redactions([(0, pymupdf.Rect(50, 50, 100, 100))])
    doc.apply_redactions()
    out = doc.render(0, 1)
    assert out.pixel(75, 75) == (0, 0, 0)
    assert out.pixel(150, 150) == (255, 255, 255)


# ---- bookmarks -----------------------------------------------------------------

def test_bookmarks_add_rename_delete_with_children():
    doc = PdfDocument(make_pdf(pages=3))
    assert doc.bookmarks() == []
    doc.add_bookmark("Giriş", 0)
    doc.add_bookmark("Sonuç", 2)
    doc._set_toc([[1, "Giriş", 1], [2, "Alt bölüm", 2], [1, "Sonuç", 3]])
    idx = doc.add_bookmark("Ek", 1, after=0)  # after "Giriş" and its child, same level
    assert idx == 2
    assert [(b.level, b.title, b.page) for b in doc.bookmarks()] == [
        (1, "Giriş", 0), (2, "Alt bölüm", 1), (1, "Ek", 1), (1, "Sonuç", 2)]
    doc.rename_bookmark(3, "Kapanış")
    doc.delete_bookmark(0)  # takes "Alt bölüm" with it
    assert [b.title for b in reopen(doc).bookmarks()] == ["Ek", "Kapanış"]
    with pytest.raises(PdfError):
        doc.add_bookmark("  ", 0)


# ---- crop ------------------------------------------------------------------------

@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_crop_keeps_what_the_user_framed(rotation):
    doc = PdfDocument(make_pdf(rotation=rotation))
    line = doc.text_lines(0)[0]
    frame = pymupdf.Rect(line.rect.x0 - 10, line.rect.y0 - 10, line.rect.x0 + 150, line.rect.y1 + 30)
    doc.crop_pages([0], frame)
    w, h = doc.page_size(0)
    assert abs(w - frame.width) < 0.5 and abs(h - frame.height) < 0.5
    (first, *_) = doc.text_lines(0)
    assert abs(first.rect.x0 - 10) < 1 and abs(first.rect.y0 - 10) < 1
    # Cropping a cropped page is relative to what is visible now.
    doc.crop_pages([0], pymupdf.Rect(5, 5, 100, 40))
    assert abs(doc.page_size(0)[0] - 95) < 0.5
    doc.reset_crop([0])
    assert doc.page_size(0) in ((400, 300), (300, 400))


def test_crop_rejects_tiny_area():
    doc = PdfDocument(make_pdf())
    with pytest.raises(PdfError):
        doc.crop_pages([0], pymupdf.Rect(0, 0, 5, 5))


# ---- watermark, header & footer --------------------------------------------------

@pytest.mark.parametrize("rotation", [0, 90])
def test_watermark_is_centred_and_rotated_for_the_viewer(rotation):
    doc = PdfDocument(make_pdf(pages=2, rotation=rotation))
    doc.add_watermark([0, 1], "GİZLİ BELGE", size=40, angle=30)
    page = doc._doc[1]
    t = page.rotation_matrix
    found = False
    for b in page.get_text("dict")["blocks"]:
        for l in b["lines"]:
            if "GİZLİ BELGE" in "".join(s["text"] for s in l["spans"]):
                ux, uy = l["dir"]
                dx, dy = ux * t.a + uy * t.c, ux * t.b + uy * t.d
                assert abs(math.degrees(math.atan2(-dy, dx)) - 30) < 1
                c = pymupdf.Rect(l["bbox"]) * t
                w, h = doc.page_size(1)
                assert abs((c.x0 + c.x1) / 2 - w / 2) < 3 and abs((c.y0 + c.y1) / 2 - h / 2) < 3
                found = True
    assert found
    with pytest.raises(PdfError):
        doc.add_watermark([0], "   ")


@pytest.mark.parametrize("rotation", [0, 90])
def test_header_footer_replaces_tokens(rotation):
    doc = PdfDocument(make_pdf(pages=3, rotation=rotation))
    doc.add_header_footer([0, 2], {"header_left": "Gizli – şirket içi", "footer_right": "Sayfa {page} / {pages}"})
    assert "Sayfa 3 / 3" in texts(doc, 2)
    assert "Gizli – şirket içi" in texts(doc, 0)
    assert not any("Sayfa" in t for t in texts(doc, 1))
    footer = next(l for l in doc.text_lines(2) if l.text.startswith("Sayfa"))
    w, h = doc.page_size(2)
    assert footer.rect.y1 > h - 40 and footer.rect.x1 > w - 40  # bottom right for the viewer
    header = next(l for l in doc.text_lines(0) if l.text.startswith("Gizli"))
    assert header.rect.y0 < 40 and header.rect.x0 < 40
    with pytest.raises(PdfError):
        doc.add_header_footer([0], {s: " " for s in HF_SLOTS})


# ---- annotations -------------------------------------------------------------------

@pytest.mark.parametrize("rotation", [0, 90])
def test_shapes_notes_and_stamps_can_be_erased(rotation):
    doc = PdfDocument(make_pdf(rotation=rotation, text_lines=()))
    doc.add_shape(0, "rect", pymupdf.Rect(20, 20, 80, 60), color=(1, 0, 0))
    doc.add_shape(0, "ellipse", pymupdf.Rect(100, 20, 160, 60))
    doc.add_line(0, (20, 100), (120, 100), arrow=True)
    doc.add_note(0, 200, 100, "Bunu kontrol et")
    doc.add_stamp(0, pymupdf.Rect(20, 150, 180, 200), "ONAYLANDI")
    page = doc._doc[0]
    kinds = sorted(a.type[1] for a in page.annots())
    assert kinds == ["Circle", "Line", "Square", "Stamp", "Text"]
    line = next(a for a in page.annots() if a.type[1] == "Line")
    assert line.line_ends[1] == pymupdf.PDF_ANNOT_LE_OPEN_ARROW
    stamp = next(a for a in page.annots() if a.type[1] == "Stamp")
    r = stamp.rect * page.rotation_matrix
    assert r.width > r.height  # upright for the viewer
    xref, text = doc.note_at(0, 205, 105)
    assert text == "Bunu kontrol et"
    doc.set_note_text(0, xref, "Değişti")
    assert doc.note_at(0, 205, 105)[1] == "Değişti"
    assert doc.note_at(0, 50, 40) is None  # a rectangle, not a note
    for x, y in ((50, 20), (130, 40), (70, 100), (205, 105), (100, 175)):
        assert doc.delete_annot_at(0, x, y), (x, y)
    assert not list(doc._doc[0].annots())


def test_stamp_renders_red_text():
    doc = PdfDocument(make_pdf(text_lines=()))
    doc.add_stamp(0, pymupdf.Rect(20, 20, 220, 80), "TASLAK ğüşİ", color=(1, 0, 0))
    pix = doc.render(0, 1)
    reds = sum(1 for x in range(20, 220, 2) for y in range(20, 80, 2)
               if (lambda p: p[0] > 200 and p[1] < 80)(pix.pixel(x, y)))
    assert reds > 50


# ---- form fields -------------------------------------------------------------------

@pytest.mark.parametrize("rotation", [0, 90])
def test_created_fields_can_be_filled(rotation):
    doc = PdfDocument(make_pdf(rotation=rotation, text_lines=()))
    doc.add_form_field(0, pymupdf.Rect(20, 20, 200, 40), "text", "Ad")
    doc.add_form_field(0, pymupdf.Rect(20, 50, 200, 120), "multiline", "Adres")
    doc.add_form_field(0, pymupdf.Rect(20, 130, 36, 146), "checkbox", "Onay")
    doc.add_form_field(0, pymupdf.Rect(20, 160, 200, 180), "combobox", "Şehir", ["İzmir", "Ankara"])
    doc.add_form_field(0, pymupdf.Rect(20, 190, 200, 240), "listbox", "Renk", ["Kırmızı", "Mavi"])
    assert doc.suggest_field_name("text") == "Text1"
    with pytest.raises(PdfError):
        doc.add_form_field(0, pymupdf.Rect(20, 250, 200, 270), "text", "Ad")  # duplicate
    with pytest.raises(PdfError):
        doc.add_form_field(0, pymupdf.Rect(20, 250, 200, 270), "combobox", "Boş", [" "])
    fields = {f.name: f for f in doc.form_fields()}
    assert {n: f.kind for n, f in fields.items()} == {
        "Ad": "text", "Adres": "text", "Onay": "checkbox", "Şehir": "choice", "Renk": "choice"}
    assert fields["Şehir"].choices == ["İzmir", "Ankara"]
    doc.set_form_values({"Ad": "Ayşe Yılmaz", "Onay": True, "Şehir": "Ankara"})
    again = {f.name: f.value for f in reopen(doc).form_fields()}
    assert again["Ad"] == "Ayşe Yılmaz" and again["Onay"] is True and again["Şehir"] == "Ankara"
    assert doc.delete_annot_at(0, 25, 30)  # Erase removes a form field
    assert "Ad" not in doc.field_names()


# ---- paragraph editing ---------------------------------------------------------------

@pytest.mark.parametrize("rotation", [0, 90])
def test_paragraph_is_rewritten_in_place(rotation):
    src = pymupdf.open()
    page = src.new_page(width=400, height=500)
    page.set_rotation(rotation)
    body = ("Bu paragraf birkaç satıra yayılan uzun bir metindir ve kutunun genişliğine göre "
            "otomatik olarak satırlara bölünür; düzenleme sonrası da öyle kalmalıdır.")
    box = pymupdf.Rect(40, 40, 260, 200)
    page.insert_textbox(box * page.derotation_matrix, body, fontsize=11, rotate=rotation,
                        **fonts.font_args("serif"))
    page.insert_text(pymupdf.Point(40, 400) * page.derotation_matrix, "Alttaki ayrı satır", fontsize=11,
                     rotate=rotation, **fonts.font_args("sans"))
    fonts.fix_space_mapping(src, page)
    doc = PdfDocument(src.tobytes())

    block = doc.block_at(0, 60, 50)
    assert block is not None and len(block.line_rects) >= 3
    assert block.text == body
    assert block.family == "serif"
    new = body.replace("uzun bir metindir", "daha da uzun, yeniden yazılmış bir metindir")
    doc.replace_block(block, new)
    after = doc.block_at(0, 60, 50)
    assert after.text == new
    assert abs(after.rect.x0 - block.rect.x0) < 2 and abs(after.rect.y0 - block.rect.y0) < 3
    assert after.rect.x1 <= block.rect.x1 + 12  # re-flowed within the original width
    assert "Alttaki ayrı satır" in texts(doc)
    doc.replace_block(after, "")
    assert doc.block_at(0, 60, 50) is None
    assert "Alttaki ayrı satır" in texts(doc)


def test_join_lines_undoes_hyphenation():
    from leafpen.core.document import _join_lines
    assert _join_lines(["Bir keli-", "me ve  ", "", "devamı"]) == "Bir kelime ve devamı"
    assert _join_lines(["2020-", "2021"]) == "2020- 2021"


# ---- export & compression ------------------------------------------------------------

def test_export_images(tmp_path):
    doc = PdfDocument(make_pdf(pages=12))
    paths = doc.export_images([0, 11], str(tmp_path / "out"), "png", dpi=72)
    assert [p.rsplit("_", 1)[1] for p in paths] == ["01.png", "12.png"]
    pix = pymupdf.Pixmap(paths[0])
    assert (pix.width, pix.height) == (400, 300)
    (jpg,) = doc.export_images([1], str(tmp_path / "j"), "jpg", dpi=144)
    assert open(jpg, "rb").read(3) == b"\xff\xd8\xff"
    assert pymupdf.Pixmap(jpg).width == 800


def _noisy_png(size=1200) -> bytes:
    import random
    rnd = random.Random(1)
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, size, size), False)
    for y in range(0, size, 8):
        for x in range(0, size, 8):
            pix.set_rect(pymupdf.IRect(x, y, x + 8, y + 8), (rnd.randrange(256), rnd.randrange(256), 128))
    return pix.tobytes("png")


def test_compression_shrinks_images_and_keeps_text():
    src = pymupdf.open("pdf", make_pdf())
    src[0].insert_image(pymupdf.Rect(0, 100, 200, 300), stream=_noisy_png())  # ~430 dpi
    doc = PdfDocument(src.tobytes(deflate=True))
    before = len(doc._doc.tobytes(garbage=3, deflate=True))
    out = doc.compressed_bytes("low")
    assert len(out) < before / 3
    small = pymupdf.open("pdf", out)
    assert "Birinci satır" in small[0].get_text()
    assert not doc.dirty  # the open document is untouched


def test_compression_keeps_password(tmp_path):
    src = pymupdf.open("pdf", make_pdf())
    path = tmp_path / "enc.pdf"
    src.save(path, encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="gizli", owner_pw="sahip")
    doc = PdfDocument.open(str(path), "gizli")
    out = pymupdf.open("pdf", doc.compressed_bytes("medium"))
    assert out.needs_pass and out.authenticate("gizli")
