import struct

import pymupdf
import pytest

from leafpen.core.document import PdfDocument, PdfError
from leafpen.core.pdftools import (every_n_pages, heic_to_image, images_to_pdf, is_heic, merge_pdfs, parse_ranges,
                                   repair_pdf)

from .conftest import make_pdf


def with_toc(pages: int, toc: list) -> bytes:
    doc = pymupdf.open("pdf", make_pdf(pages=pages))
    doc.set_toc(toc)
    return doc.tobytes()


def png(width: int, height: int) -> bytes:
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, width, height), False)
    pix.clear_with(200)
    return pix.tobytes("png")


def jpeg_with_orientation(width: int, height: int, orientation: int) -> bytes:
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, width, height), False)
    pix.clear_with(120)
    data = pix.tobytes("jpg")
    tiff = (b"MM\x00\x2a\x00\x00\x00\x08\x00\x01\x01\x12\x00\x03\x00\x00\x00\x01"
            + struct.pack(">H", orientation) + b"\x00\x00\x00\x00\x00\x00")
    app1 = b"Exif\x00\x00" + tiff
    return data[:2] + b"\xff\xe1" + struct.pack(">H", len(app1) + 2) + app1 + data[2:]


def heic(width: int, height: int, mode: str = "RGB") -> bytes:
    import io

    import pillow_heif
    from PIL import Image

    pillow_heif.register_heif_opener()
    buf = io.BytesIO()
    Image.new(mode, (width, height), (90, 160, 220, 128)[:len(mode)]).save(buf, "HEIF")
    return buf.getvalue()


# ---- merge -------------------------------------------------------------------

def test_merge_keeps_order_and_nests_bookmarks():
    a = with_toc(2, [[1, "Giriş", 1], [2, "Alt", 2]])
    b = make_pdf(pages=3)
    out = pymupdf.open("pdf", merge_pdfs([(r"C:\x\rapor.pdf", a), ("ek.pdf", b)]))
    assert out.page_count == 5
    assert out.get_toc() == [[1, "rapor", 1], [2, "Giriş", 1], [3, "Alt", 2], [1, "ek", 3]]


def test_merge_without_file_bookmarks_keeps_original_ones():
    a = make_pdf(pages=1)
    b = with_toc(2, [[1, "Bölüm", 2]])
    out = pymupdf.open("pdf", merge_pdfs([("a.pdf", a), ("b.pdf", b)], bookmarks=False))
    assert out.get_toc() == [[1, "Bölüm", 3]]


def test_merge_rejects_protected_and_broken_files(pdf_bytes):
    locked = pymupdf.open("pdf", pdf_bytes).tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="x",
                                                     owner_pw="y")
    with pytest.raises(PdfError, match="locked.pdf"):
        merge_pdfs([("a.pdf", pdf_bytes), ("locked.pdf", locked)])
    with pytest.raises(PdfError, match="junk.pdf"):
        merge_pdfs([("a.pdf", pdf_bytes), ("junk.pdf", b"not a pdf")])
    with pytest.raises(PdfError):
        merge_pdfs([("a.pdf", pdf_bytes)])


# ---- images to PDF -------------------------------------------------------------

def test_images_page_fits_image_with_margin():
    out = pymupdf.open("pdf", images_to_pdf([("a.png", png(200, 100)), ("b.png", png(50, 80))], margin=10))
    assert out.page_count == 2
    a, b = out[0].rect, out[1].rect
    assert a.width > a.height and b.height > b.width
    assert len(out[0].get_images()) == 1


@pytest.mark.parametrize("orientation, landscape", [("auto", True), ("portrait", False), ("landscape", True)])
def test_images_on_a4(orientation, landscape):
    out = pymupdf.open("pdf", images_to_pdf([("wide.png", png(300, 100))], "a4", orientation, 20))
    r = out[0].rect
    assert sorted((round(r.width), round(r.height))) == [595, 842]
    assert (r.width > r.height) == landscape
    box = out[0].get_image_rects(out[0].get_images()[0][0])[0]
    assert box.x0 >= 19.9 and box.x1 <= r.width - 19.9  # inside the margins
    assert abs((box.x0 + box.x1) / 2 - r.width / 2) < 1  # centred


def test_images_follow_exif_orientation():
    out = pymupdf.open("pdf", images_to_pdf([("phone.jpg", jpeg_with_orientation(200, 100, 6))]))
    assert out[0].rect.height > out[0].rect.width


def test_images_bad_file_is_named():
    with pytest.raises(PdfError, match="broken.png"):
        images_to_pdf([("broken.png", b"\x89PNG nope")])
    with pytest.raises(PdfError):
        images_to_pdf([])


def test_heic_is_converted():
    assert is_heic("IMG_0001.HEIC") and is_heic("a.heif") and not is_heic("a.jpg")
    ext, data = heic_to_image(heic(120, 80))
    assert ext == "jpg"
    pix = pymupdf.Pixmap(data)
    assert (pix.width, pix.height) == (120, 80)
    assert heic_to_image(heic(40, 40, "RGBA"))[0] == "png"
    out = pymupdf.open("pdf", images_to_pdf([("photo.jpg", data)]))
    assert out[0].rect.width > out[0].rect.height
    with pytest.raises(PdfError):
        heic_to_image(b"not a heic file")


def test_heic_added_to_page():
    doc = PdfDocument(make_pdf(text_lines=()))
    doc.add_image(0, pymupdf.Rect(50, 50, 170, 130), heic_to_image(heic(120, 80))[1])
    assert len(doc._doc[0].get_images()) == 1


# ---- repair --------------------------------------------------------------------

def test_repair_rebuilds_broken_cross_reference():
    data = make_pdf(pages=3)
    broken = data[: data.rindex(b"startxref")] + b"startxref\n999999\n%%EOF\n"
    out, report = repair_pdf(broken)
    assert report.rebuilt and report.pages == 3 and report.dropped == 0
    fixed = pymupdf.open("pdf", out)
    assert fixed.page_count == 3 and not fixed.is_repaired
    assert "Birinci" in fixed[0].get_text()


def test_repair_intact_file_and_garbage():
    _out, report = repair_pdf(make_pdf())
    assert not report.rebuilt and report.pages == 1
    with pytest.raises(PdfError):
        repair_pdf(b"garbage" * 100)


# ---- page ranges and split -------------------------------------------------------

def test_parse_ranges():
    assert parse_ranges("1-3, 5; 8-", 9) == [[0, 1, 2], [4], [7, 8]]
    assert parse_ranges(" -2 ,", 5) == [[0, 1]]
    for bad in ("", "0", "4-2", "1-10", "a", "3 5", "1--2"):
        with pytest.raises(PdfError):
            parse_ranges(bad, 9)


def test_every_n_pages():
    assert every_n_pages(5, 2) == [[0, 1], [2, 3], [4]]
    assert every_n_pages(3, 1) == [[0], [1], [2]]


def test_split_writes_one_file_per_group(tmp_path):
    doc = PdfDocument(make_pdf(pages=12))
    paths = doc.split([[0, 1, 2], [9]], str(tmp_path / "rapor"))
    assert [p.rsplit("\\", 1)[-1].rsplit("/", 1)[-1] for p in paths] == ["rapor_01-03.pdf", "rapor_10.pdf"]
    assert [pymupdf.open(p).page_count for p in paths] == [3, 1]


# ---- passwords --------------------------------------------------------------------

def test_protect_with_open_password(pdf_bytes):
    doc = PdfDocument(pdf_bytes)
    data = doc.protected_bytes("gizli", {"print", "copy", "modify", "annotate"})
    out = pymupdf.open("pdf", data)
    assert out.needs_pass and not out.authenticate("yanlış") and out.authenticate("gizli")
    reopened = PdfDocument(data, password="gizli")
    assert reopened.is_encrypted


def test_protect_restrictions_only(pdf_bytes):
    data = PdfDocument(pdf_bytes).protected_bytes("", {"print"}, owner_password="sahip")
    out = pymupdf.open("pdf", data)
    assert not out.needs_pass
    assert out.permissions & pymupdf.PDF_PERM_PRINT
    assert not out.permissions & pymupdf.PDF_PERM_COPY
    assert not out.permissions & pymupdf.PDF_PERM_MODIFY
    assert PdfDocument(data).is_encrypted  # owner password only: opens freely but is still protected
    with pytest.raises(PdfError):
        PdfDocument(pdf_bytes).protected_bytes("", {"print", "copy", "modify", "annotate"})


def test_remove_password(pdf_bytes):
    locked = PdfDocument(pdf_bytes).protected_bytes("gizli", {"print"})
    doc = PdfDocument(locked, password="gizli")
    plain = PdfDocument(doc.plain_bytes())
    assert not plain.is_encrypted
    assert "Birinci" in plain._doc[0].get_text()
    assert not PdfDocument(pdf_bytes).is_encrypted
