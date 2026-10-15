import pymupdf
import pytest

from leafpen.core import signing
from leafpen.core.document import PdfDocument
from leafpen.core.signing import SigningError

from .conftest import make_pdf


@pytest.fixture(scope="module")
def cert(tmp_path_factory):
    path = tmp_path_factory.mktemp("cert") / "ben.p12"
    signing.create_certificate(str(path), "Şükrü Öğüt", "parola123", email="s@example.com")
    return signing.load_certificate(str(path), "parola123")


def test_certificate_round_trip(cert, tmp_path):
    assert cert.name == "Şükrü Öğüt"
    with pytest.raises(SigningError):
        signing.load_certificate(str(tmp_path / "yok.p12"), "x")
    path = tmp_path / "c.p12"
    signing.create_certificate(str(path), "A B", "parola")
    with pytest.raises(SigningError):
        signing.load_certificate(str(path), "yanlis")


def test_invisible_signature_verifies(cert):
    signed = signing.sign_pdf(make_pdf(), cert, reason="Onay")
    (info,) = signing.verify_pdf(signed)
    assert info.intact and info.covers_all and not info.trusted
    assert info.status == "untrusted" and info.signer == "Şükrü Öğüt"
    assert PdfDocument(signed).has_signatures()
    assert not PdfDocument(make_pdf()).has_signatures()


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_visible_signature_lands_where_drawn(cert, rotation):
    pdf = make_pdf(rotation=rotation, cropbox=(10, 20, 380, 290), text_lines=())
    box = pymupdf.Rect(30, 40, 230, 110)  # display coordinates
    signed = signing.sign_pdf(pdf, cert, page=0, rect=box, reason="Sözleşme onayı")
    assert signing.verify_pdf(signed)[0].intact

    doc = pymupdf.open("pdf", signed)
    page = doc[0]
    pix = page.get_pixmap(dpi=72)
    # The stamp's text is upright and inside the box: extract it in display space.
    words = [(pymupdf.Rect(w[:4]) * page.rotation_matrix, w[4]) for w in page.get_text("words")]
    assert words, "appearance text missing"
    for rect, _ in words:
        assert box.contains(rect), (rect, box)
    text = " ".join(w for _, w in words)
    assert "Şükrü" in text and "Öğüt" in text
    # Reading order must be left-to-right for the viewer (upright text).
    first_line = [r for r, w in words if w in ("Digitally", "signed")]
    assert first_line[0].x0 < first_line[1].x0
    # Nothing drawn outside the box.
    outside = pymupdf.Rect(box.x0, box.y1 + 5, box.x1, box.y1 + 60)
    assert all(pix.pixel(x, y) == (255, 255, 255)
               for x in range(int(outside.x0), int(outside.x1), 7)
               for y in range(int(outside.y0), int(outside.y1), 7))


def test_save_as_of_unmodified_signed_file_keeps_signature(cert, tmp_path):
    src = tmp_path / "imzali.pdf"
    src.write_bytes(signing.sign_pdf(make_pdf(), cert))
    doc = PdfDocument.open(str(src))
    doc.save(str(tmp_path / "kopya.pdf"))
    assert (tmp_path / "kopya.pdf").read_bytes() == src.read_bytes()
    doc.add_text(0, 40, 150, "değişiklik")
    doc.undo()  # back at the saved state: still byte-identical
    doc.save(str(tmp_path / "kopya2.pdf"))
    assert signing.verify_pdf((tmp_path / "kopya2.pdf").read_bytes())[0].covers_all


def test_tampering_is_detected(cert):
    signed = bytearray(signing.sign_pdf(make_pdf(), cert))
    # Flip a byte inside the signed page content (not in the signature value).
    idx = signed.find(b"stream") + 20
    signed[idx] ^= 0x01
    infos = signing.verify_pdf(bytes(signed))
    assert infos and infos[0].status == "invalid"


def test_second_signature_keeps_first_valid(cert):
    once = signing.sign_pdf(make_pdf(), cert, page=0, rect=pymupdf.Rect(20, 150, 180, 200))
    doc = PdfDocument(once, path="x.pdf")
    twice = signing.sign_pdf(doc.signing_source(), cert, page=0, rect=pymupdf.Rect(200, 150, 380, 200))
    first, second = signing.verify_pdf(twice)
    assert first.intact and not first.covers_all and first.allowed_changes
    assert first.status == "untrusted"
    assert second.intact and second.covers_all
    assert {first.field, second.field} == {"Signature1", "Signature2"}


def test_content_change_after_signing_is_flagged(cert, tmp_path):
    path = tmp_path / "signed.pdf"
    path.write_bytes(signing.sign_pdf(make_pdf(), cert))
    doc = pymupdf.open(path)
    doc[0].insert_text((50, 200), "sonradan eklendi")
    doc.save(path, incremental=True, encryption=pymupdf.PDF_ENCRYPT_KEEP)
    doc.close()
    (info,) = signing.verify_pdf(path.read_bytes())
    assert info.intact and info.status == "modified"


def test_sign_encrypted_pdf(cert):
    src = pymupdf.open("pdf", make_pdf())
    enc = src.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="gizli", owner_pw="gizli")
    with pytest.raises(SigningError):
        signing.sign_pdf(enc, cert)
    signed = signing.sign_pdf(enc, cert, password="gizli", page=0, rect=pymupdf.Rect(20, 150, 180, 200))
    out = pymupdf.open("pdf", signed)
    assert out.needs_pass and out.authenticate("gizli")
    (info,) = signing.verify_pdf(signed, password="gizli")
    assert info.intact and info.covers_all


def test_signature_with_handwritten_image(cert):
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 60, 20), False)
    pix.set_rect(pix.irect, (0, 0, 200))
    signed = signing.sign_pdf(make_pdf(), cert, page=0, rect=pymupdf.Rect(20, 150, 260, 220), image=pix.tobytes("png"))
    page = pymupdf.open("pdf", signed)[0]
    out = page.get_pixmap(dpi=72)
    blue = sum(1 for x in range(20, 140, 3) for y in range(150, 220, 3) if out.pixel(x, y) == (0, 0, 200))
    assert blue > 20
    assert signing.verify_pdf(signed)[0].intact
