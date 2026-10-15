import pymupdf
import pytest

from leafpen.core.document import PasswordRequired, PdfDocument, PdfError

from .conftest import make_pdf


def texts(doc, pno=0):
    return [l.text for l in doc.text_lines(pno)]


def test_rejects_non_pdf():
    with pytest.raises(PdfError):
        PdfDocument(b"not a pdf at all")


def test_password_protected(tmp_path):
    src = pymupdf.open("pdf", make_pdf())
    path = tmp_path / "enc.pdf"
    src.save(path, encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="gizli", owner_pw="sahip")
    src.close()
    with pytest.raises(PasswordRequired) as e:
        PdfDocument.open(str(path))
    assert not e.value.wrong
    with pytest.raises(PasswordRequired) as e:
        PdfDocument.open(str(path), "yanlis")
    assert e.value.wrong

    doc = PdfDocument.open(str(path), "gizli")
    doc.add_text(0, 40, 150, "Şifreli belgeye eklendi")
    doc.undo()
    doc.redo()
    doc.save(str(path))
    assert pymupdf.open(str(path)).needs_pass  # stays encrypted after saving
    again = PdfDocument.open(str(path), "gizli")
    assert "Şifreli belgeye eklendi" in texts(again)


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_add_text_lands_where_clicked(rotation):
    doc = PdfDocument(make_pdf(rotation=rotation, text_lines=()))
    doc.add_text(0, 50, 40, "Çığ düştü İzmir", size=14)
    (line,) = doc.text_lines(0)
    assert line.text == "Çığ düştü İzmir"
    # Display rect starts at the click point and runs left-to-right for the viewer.
    assert abs(line.rect.x0 - 50) < 3 and abs(line.rect.y0 - 40) < 6
    assert line.rect.width > line.rect.height


def test_add_text_that_does_not_fit_rolls_back(pdf_bytes):
    doc = PdfDocument(pdf_bytes)
    before = texts(doc)
    with pytest.raises(PdfError):
        doc.add_text(0, 40, 290, "çok\nsatırlı\nmetin\nsığmaz", size=20)
    assert texts(doc) == before
    assert not doc.dirty and not doc.can_undo()


@pytest.mark.parametrize("rotation", [0, 90])
def test_replace_line_keeps_neighbours_and_position(rotation):
    doc = PdfDocument(make_pdf(rotation=rotation))
    first, second = doc.text_lines(0)
    doc.replace_line(first, "Değiştirilmiş satır ĞŞİ")
    lines = doc.text_lines(0)
    assert [l.text for l in lines] == ["Değiştirilmiş satır ĞŞİ", "İkinci satır burada"]
    assert abs(lines[0].rect.x0 - first.rect.x0) < 1 and abs(lines[0].rect.y0 - first.rect.y0) < 1
    assert lines[0].size == first.size


def test_replace_line_with_empty_text_deletes_it(pdf_bytes):
    doc = PdfDocument(pdf_bytes)
    doc.replace_line(doc.text_lines(0)[1], "  ")
    assert texts(doc) == ["Birinci satır ğüşıöç"]


def test_undo_redo_and_dirty(pdf_bytes):
    doc = PdfDocument(pdf_bytes)
    assert not doc.dirty
    doc.add_text(0, 40, 150, "bir")
    doc.add_text(0, 40, 200, "iki")
    assert doc.dirty and len(texts(doc)) == 4
    doc.undo()
    doc.undo()
    assert not doc.dirty and len(texts(doc)) == 2
    doc.redo()
    assert doc.dirty and "bir" in texts(doc)
    doc.add_text(0, 40, 200, "üç")
    assert not doc.can_redo()


def test_save_marks_clean_and_overwrites_opened_file(tmp_path, pdf_bytes):
    path = tmp_path / "a.pdf"
    path.write_bytes(pdf_bytes)
    doc = PdfDocument.open(str(path))
    doc.add_text(0, 40, 150, "kaydedildi")
    doc.save(str(path))
    assert not doc.dirty
    assert "kaydedildi" in texts(PdfDocument.open(str(path)))
    doc.undo()
    assert doc.dirty  # undoing past the save point differs from disk


def test_page_operations(tmp_path):
    doc = PdfDocument(make_pdf(pages=3))
    for i in range(3):
        doc.replace_line(doc.text_lines(i)[0], f"Sayfa {i}")
    order = lambda: [doc.text_lines(i)[0].text for i in range(doc.page_count)]

    doc.move_page(0, 2)
    assert order() == ["Sayfa 1", "Sayfa 2", "Sayfa 0"]
    doc.move_page(2, 0)
    assert order() == ["Sayfa 0", "Sayfa 1", "Sayfa 2"]
    doc.move_page(1, 2)
    assert order() == ["Sayfa 0", "Sayfa 2", "Sayfa 1"]

    doc.rotate_pages([0], 90)
    doc.rotate_pages([0], 270)
    doc.rotate_pages([1], -90)
    assert doc.page_size(0) == (400, 300) and doc.page_size(1) == (300, 400)

    with pytest.raises(PdfError):
        doc.delete_pages([0, 1, 2])
    doc.delete_pages([1])
    assert order() == ["Sayfa 0", "Sayfa 1"]

    other = tmp_path / "other.pdf"
    other.write_bytes(make_pdf(pages=2, text_lines=("Ek",)))
    assert doc.insert_pdf(str(other), 1) == 2
    assert order() == ["Sayfa 0", "Ek", "Ek", "Sayfa 1"]

    out = tmp_path / "out.pdf"
    doc.extract_pages([3, 0], str(out))
    ex = PdfDocument.open(str(out))
    assert [ex.text_lines(i)[0].text for i in range(2)] == ["Sayfa 0", "Sayfa 1"]


@pytest.mark.parametrize("rotation", [0, 90, 270])
def test_image_is_upright_for_viewer(rotation):
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 40, 20), False)
    pix.set_rect(pymupdf.IRect(0, 0, 20, 20), (255, 0, 0))
    pix.set_rect(pymupdf.IRect(20, 0, 40, 20), (0, 0, 255))
    doc = PdfDocument(make_pdf(rotation=rotation, text_lines=()))
    doc.add_image(0, pymupdf.Rect(100, 100, 300, 200), pix.tobytes("png"))
    out = doc.render(0, 1)
    assert out.pixel(150, 150) == (255, 0, 0)  # left half red
    assert out.pixel(250, 150) == (0, 0, 255)  # right half blue


def test_add_image_rejects_garbage(pdf_bytes):
    with pytest.raises(PdfError):
        PdfDocument(pdf_bytes).add_image(0, pymupdf.Rect(0, 0, 50, 50), b"nope")


@pytest.mark.parametrize("rotation", [0, 90])
def test_annotations_hit_test_and_delete(rotation):
    doc = PdfDocument(make_pdf(rotation=rotation))
    line = doc.text_lines(0)[0]
    doc.add_highlight(0, line.rect)
    doc.add_ink(0, [[(200, 200), (250, 220), (260, 260)]], color=(1, 0, 0), width=3)

    hl = doc.annot_rect_at(0, line.rect.x0 + 5, (line.rect.y0 + line.rect.y1) / 2)
    # MuPDF pads highlight boxes a little; it must still hug the line.
    assert hl is not None and hl.contains(line.rect) and hl.height < line.rect.height * 1.6
    pix = doc.render(0, 1)
    y = int(line.rect.y0 + line.rect.height * 0.93)  # below the baseline: few glyph pixels
    row = [pix.pixel(x, y) for x in range(int(line.rect.x0) + 1, int(line.rect.x1) - 1)]
    yellow = sum(1 for r, g, b in row if r > 200 and g > 170 and b < 120)
    assert yellow > 0.5 * len(row)  # the line is covered in yellow, for every rotation
    assert doc.annot_rect_at(0, 250, 220) is not None
    assert doc.annot_rect_at(0, 20, 280) is None

    assert doc.delete_annot_at(0, 250, 220)
    assert doc.annot_rect_at(0, 250, 220) is None
    assert not doc.delete_annot_at(0, 20, 280)


def _form_pdf():
    doc = pymupdf.open()
    page = doc.new_page(width=400, height=300)
    def widget(kind, name, rect, **kw):
        w = pymupdf.Widget()
        w.field_type, w.field_name, w.rect = kind, name, pymupdf.Rect(rect)
        for k, v in kw.items():
            setattr(w, k, v)
        page.add_widget(w)
    widget(pymupdf.PDF_WIDGET_TYPE_TEXT, "ad", (20, 20, 200, 40), field_value="")
    widget(pymupdf.PDF_WIDGET_TYPE_CHECKBOX, "onay", (20, 50, 35, 65), field_value=False)
    widget(pymupdf.PDF_WIDGET_TYPE_COMBOBOX, "sehir", (20, 80, 200, 100),
           choice_values=["Ankara", "İstanbul", "İzmir"], field_value="Ankara")
    widget(pymupdf.PDF_WIDGET_TYPE_RADIOBUTTON, "cins", (20, 110, 35, 125), field_value=False)
    widget(pymupdf.PDF_WIDGET_TYPE_RADIOBUTTON, "cins", (60, 110, 75, 125), field_value=False)
    # Real radio groups give each button its own "on" state name; PyMuPDF names them all "Yes".
    radios = [w for w in page.widgets() if w.field_type == pymupdf.PDF_WIDGET_TYPE_RADIOBUTTON]
    for w, state in zip(radios, ("Kadin", "Erkek")):
        ap = doc.xref_get_key(w.xref, "AP/N")[1]
        doc.xref_set_key(w.xref, "AP/N", ap.replace("/Yes", f"/{state}"))
        for key in ("AP/D",):
            kind, val = doc.xref_get_key(w.xref, key)
            if kind == "dict":
                doc.xref_set_key(w.xref, key, val.replace("/Yes", f"/{state}"))
    return doc.tobytes()


def test_form_fill_round_trip(tmp_path):
    doc = PdfDocument(_form_pdf())
    fields = {f.name: f for f in doc.form_fields()}
    assert fields["ad"].kind == "text" and fields["onay"].kind == "checkbox"
    assert fields["sehir"].choices == ["Ankara", "İstanbul", "İzmir"]
    assert fields["cins"].kind == "radio" and len(fields["cins"].choices) == 2
    second = fields["cins"].choices[1]

    assert doc.set_form_values({"ad": "Şule Çağlar", "onay": True, "sehir": "İzmir", "cins": second})
    assert not doc.set_form_values({"ad": "Şule Çağlar"})  # unchanged -> no undo step

    # The filled value must actually be visible (auto-size fields used to render invisibly).
    # Non-WinAnsi text ("Şule") used to be placed below the box and clipped.
    pix = doc.render(0, 4)
    dark_rows = [y for y in range(80, 160) if any(sum(pix.pixel(x, y)) < 300 for x in range(88, 790, 3))]
    assert dark_rows, "filled value is invisible"
    centre = (min(dark_rows) + max(dark_rows)) / 2
    assert 100 < centre < 140, centre  # field spans y 20..40 pt = 80..160 px

    path = tmp_path / "form.pdf"
    doc.save(str(path))
    got = {f.name: f.value for f in PdfDocument.open(str(path)).form_fields()}
    assert got == {"ad": "Şule Çağlar", "onay": True, "sehir": "İzmir", "cins": second}
